# -*- coding: utf-8 -*-
"""#511: the native LinkedIn feed, proven offline.

Every fixture here is synthetic: a captured response body shaped like
LinkedIn's own feed envelope (``included[]`` entities with an
``urn:li:activity`` and a ``paginationToken``), and rendered feed HTML. No test
opens a socket or a browser. The driver is exercised through :func:`walk` with
a fake page, and the ladder through :func:`unlocker.fetch` with the feed reader
replaced.

What is proven:

* the permalink, author, text, relative time and promoted marker come out of
  passive capture and the DOM, deduped by activity id;
* the walk is bounded (posts, steps, seconds) and paces its scroll steps;
* every stop signal is handed to the guard exactly once, with no retry, and
  posts read before the signal are still returned;
* the module contains no direct LinkedIn API call and no in-page fetch.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from searchts import linkedin, unlocker
from searchts import linkedin_feed as lf
from searchts.unlocker import UnlockerError

# ── synthetic captures ───────────────────────────────────────────────────────

PAYLOAD = {
    "data": {"metadata": {"paginationToken": "TOKEN-NEXT"}},
    "included": [
        {
            "entityUrn": "urn:li:activity:7001",
            "actor": {
                "name": {"text": "Ada Lovelace"},
                "subDescription": {"text": "3h"},
            },
            "commentary": {"text": "  Built a tiny engine.  \n"},
        },
        {
            "entityUrn": "urn:li:activity:7002",
            "actor": "urn:li:person:42",
            "commentary": {"text": "We are hiring."},
            "header": {"text": "Promoted"},
        },
        {
            "entityUrn": "urn:li:person:42",
            "name": {"text": "Grace Hopper"},
        },
    ],
}


def payload(*, extra=None, cursor="TOKEN-NEXT"):
    data = json.loads(json.dumps(PAYLOAD))
    if extra:
        data["included"].extend(extra)
    data["data"]["metadata"]["paginationToken"] = cursor
    return json.dumps(data)


DOM_ONE = (
    '<div class="feed-shared-update-v2" data-urn="urn:li:activity:7001">'
    '<span class="update-components-actor__name">Ada Lovelace</span>'
    '<span class="update-components-actor__sub-description">3h</span>'
    '<div class="update-components-text"><span>Built a tiny engine.</span></div>'
    "</div>"
)
DOM_THREE = (
    '<div class="feed-shared-update-v2" data-urn="urn:li:activity:7003">'
    '<span class="update-components-actor__name">Katherine Johnson</span>'
    '<span class="update-components-actor__sub-description">1d</span>'
    '<span class="update-components-header__text">Promoted</span>'
    '<div class="update-components-text"><span>A promoted post.</span></div>'
    "</div>"
)


class FakeResponse:
    def __init__(self, url, body="", status=200, ctype="application/json"):
        self.url = url
        self.status = status
        self.headers = {"content-type": ctype}
        self._body = body

    def text(self):
        return self._body


class FakePage:
    """A live page as :func:`walk` uses it: one goto, a listener, scrolls."""

    def __init__(self, frames, responses=(), scroll_responses=()):
        self.frames = list(frames) or [""]
        self.responses = list(responses)
        self.scroll_responses = [list(batch) for batch in scroll_responses]
        self.handlers = []
        self.waits = []
        self.scrolls = 0
        self.gotos = []
        self.url = lf.FEED_URL
        self._frame = 0

    def on(self, event, handler):
        assert event == "response"
        self.handlers.append(handler)

    def goto(self, url, **kwargs):
        self.gotos.append(url)
        self._frame = 0
        for response in self.responses:
            for handler in self.handlers:
                handler(response)

    def wait_for_timeout(self, ms):
        self.waits.append(ms)

    def evaluate(self, script):
        low = script.lower()
        assert "fetch" not in low and "http" not in low
        self.scrolls += 1
        self._frame = min(self._frame + 1, len(self.frames) - 1)
        if self.scroll_responses:
            batch = self.scroll_responses.pop(0)
            for response in batch:
                for handler in self.handlers:
                    handler(response)

    def content(self):
        return self.frames[self._frame]


class FakeGuard:
    def __init__(self):
        self.calls = []

    def before_load(self):
        self.calls.append("before")

    def record(self, signal):
        self.calls.append(signal)


class FakeResume:
    def __init__(self):
        self.begun = 0
        self.cursors = []

    def begin(self):
        self.begun += 1
        return None

    def advance(self, cursor, posts):
        self.cursors.append((cursor, len(posts)))


# ── parsing and permalinks ─────────────────────────────────────────────────


def test_permalink_is_the_activity_update_url():
    assert lf.permalink("urn:li:activity:7001") == (
        "https://www.linkedin.com/feed/update/urn:li:activity:7001/"
    )
    assert lf.permalink("7001") == lf.permalink("urn:li:activity:7001")


def test_parse_capture_reads_author_text_time_and_cursor():
    got = lf.parse_capture(payload())
    assert [p.activity for p in got.posts] == ["7001", "7002"]
    first = got.posts[0]
    assert first.author == "Ada Lovelace"
    assert first.text == "Built a tiny engine."
    assert first.when == "3h"
    assert first.permalink.endswith("urn:li:activity:7001/")
    assert got.cursor == "TOKEN-NEXT"


def test_parse_capture_resolves_an_actor_urn_from_included():
    got = lf.parse_capture(payload())
    second = got.posts[1]
    assert second.author == "Grace Hopper"
    assert second.text == "We are hiring."
    assert second.promoted is True


def test_parse_capture_ignores_a_post_that_says_too_many_pages():
    body = json.dumps({
        "included": [{
            "entityUrn": "urn:li:activity:1",
            "commentary": {"text": "LinkedIn says too many pages, so here I am."},
        }],
    })
    assert lf.parse_capture(body).signal == ""


def test_parse_capture_reads_a_rate_limit_message_from_the_envelope():
    body = json.dumps({
        "message": "It looks like you are visiting a very high number of pages",
    })
    assert lf.parse_capture(body).signal == "rate-limit"


def test_parse_capture_on_a_non_json_body_names_a_stop_signal():
    body = "<h1>Your account is temporarily restricted</h1>"
    assert lf.parse_capture(body).signal == "restriction"


def test_parse_html_reads_cards_and_promoted():
    posts = lf.parse_html(DOM_ONE + DOM_THREE)
    assert [p.activity for p in posts] == ["7001", "7003"]
    assert posts[0].author == "Ada Lovelace"
    assert posts[0].text == "Built a tiny engine."
    assert posts[0].when == "3h"
    assert posts[1].promoted is True
    assert posts[1].text == "A promoted post."


def test_parse_html_keeps_text_inside_a_nested_element():
    html = (
        '<div data-urn="urn:li:activity:9">'
        '<div class="update-components-text"><span>Nested <b>words</b>.</span></div>'
        "</div>"
    )
    assert lf.parse_html(html)[0].text == "Nested words."


def test_parse_html_reads_a_time_tag():
    html = (
        '<div data-urn="urn:li:activity:5"><time>4h</time>'
        '<div class="update-components-text">Words.</div></div>'
    )
    assert lf.parse_html(html)[0].when == "4h"


def test_parse_html_is_empty_for_no_markup():
    assert lf.parse_html("") == []
    assert lf.parse_html("<p>No cards here</p>") == []


def test_render_has_author_time_text_permalink_and_promoted():
    text = lf.render([
        lf.Post("7001", "Ada Lovelace", "Built a tiny engine.", "3h"),
        lf.Post("7002", "Grace Hopper", "We are hiring.", "1d", promoted=True),
    ], stop="reached the 2 posts asked for")
    assert "Ada Lovelace · 3h" in text
    assert "Built a tiny engine." in text
    assert "urn:li:activity:7001" in text
    assert "[promoted] Grace Hopper · 1d" in text
    assert "reached the 2 posts asked for" in text


# ── the walk ────────────────────────────────────────────────────────────────


def limits(**kwargs):
    base = dict(
        max_posts=25, max_steps=3, max_seconds=90,
        step_min_ms=2000, step_max_ms=5000, settle_ms=0,
    )
    base.update(kwargs)
    return lf.Limits(**base)


def test_walk_merges_capture_and_dom_and_dedupes_by_activity():
    page = FakePage([DOM_ONE, DOM_THREE], [
        FakeResponse("https://www.linkedin.com/graphql/feed", payload()),
    ])
    guard = FakeGuard()
    resume = FakeResume()
    read = lf.walk(page, guard=guard, resume=resume,
                    limits=limits(max_posts=10, max_steps=2))
    assert [p.activity for p in read.posts] == ["7001", "7002", "7003"]
    assert read.steps == 2
    assert read.cursor == "TOKEN-NEXT"
    assert resume.begun == 1
    assert resume.cursors and resume.cursors[-1][0] == "TOKEN-NEXT"
    assert guard.calls == ["before"]


def test_walk_stops_at_the_post_limit_without_scrolling():
    extra = [
        {
            "entityUrn": f"urn:li:activity:{8000 + i}",
            "commentary": {"text": f"Post {i}"},
        }
        for i in range(30)
    ]
    page = FakePage([DOM_ONE], [
        FakeResponse("https://www.linkedin.com/graphql/feed", payload(extra=extra)),
    ])
    read = lf.walk(page, guard=FakeGuard(), limits=limits(max_posts=25))
    assert len(read.posts) == 25
    assert read.steps == 0
    assert "25 posts asked for" in read.stop
    assert page.scrolls == 0


def test_walk_stops_at_the_step_limit():
    page = FakePage([DOM_ONE])
    read = lf.walk(page, guard=FakeGuard(), limits=limits(max_steps=2))
    assert read.steps == 2
    assert page.scrolls == 2
    assert "2 scroll step limit" in read.stop


def test_walk_paces_its_scroll_steps_between_two_and_five_seconds():
    page = FakePage([DOM_ONE])
    lf.walk(page, guard=FakeGuard(), limits=limits(max_steps=3))
    # settle_ms is 0 here, so the non-zero waits are the step gaps.
    gaps = [ms for ms in page.waits if ms]
    assert len(gaps) == 3
    assert all(2000 <= ms <= 5000 for ms in gaps)


def test_walk_stops_on_a_429_and_never_scrolls():
    page = FakePage([""], [
        FakeResponse("https://www.linkedin.com/graphql/feed", "", status=429),
    ])
    guard = FakeGuard()
    read = lf.walk(page, guard=guard, limits=limits())
    assert read.signal == "rate-limit"
    assert read.posts == []
    assert guard.calls == ["before", "rate-limit"]
    assert "24 h" in read.text
    assert page.scrolls == 0


def test_walk_stops_on_999():
    page = FakePage([DOM_ONE], [
        FakeResponse("https://www.linkedin.com/graphql/feed", "", status=999),
    ])
    guard = FakeGuard()
    read = lf.walk(page, guard=guard, limits=limits())
    assert read.signal == "rate-limit"
    assert guard.calls == ["before", "rate-limit"]


def test_walk_returns_posts_read_before_a_stop_signal():
    page = FakePage([DOM_ONE, DOM_ONE + "<p>It looks like you are visiting a "
                    "very high number of pages on LinkedIn</p>"])
    guard = FakeGuard()
    read = lf.walk(page, guard=guard, limits=limits())
    assert [p.activity for p in read.posts] == ["7001"]
    assert read.steps == 1
    assert read.signal == "rate-limit"
    assert guard.calls == ["before", "rate-limit"]
    assert "Built a tiny engine." in read.text


@pytest.mark.parametrize("words,signal", [
    ("Your account is temporarily restricted", "restriction"),
    ("Let's do a quick security check", "checkpoint"),
    ("Sign in to LinkedIn", "logout"),
    ("You have been signed out", "logout"),
])
def test_walk_names_each_stop_page(words, signal):
    page = FakePage([f"<p>{words}</p>"])
    guard = FakeGuard()
    read = lf.walk(page, guard=guard, limits=limits())
    assert read.signal == signal
    assert guard.calls == ["before", signal]


def test_walk_records_a_restriction_as_stop_until_cleared():
    page = FakePage(["<p>Your account is temporarily restricted</p>"])
    read = lf.walk(page, guard=FakeGuard(), limits=limits())
    assert "person must clear" in read.stop


def test_walk_resumes_by_scrolling_past_the_cursor_already_read():
    nxt = payload(
        extra=[{
            "entityUrn": "urn:li:activity:7004",
            "actor": {"name": {"text": "Margaret Hamilton"}},
            "commentary": {"text": "The next page."},
        }],
        cursor="TOKEN-2",
    )
    page = FakePage(
        [DOM_ONE, DOM_ONE],
        [FakeResponse("https://www.linkedin.com/graphql/feed", payload())],
        scroll_responses=[[
            FakeResponse("https://www.linkedin.com/graphql/feed", nxt),
        ]],
    )
    resume = lf.TokenResume(cursor="TOKEN-NEXT", seen=["7001", "7002"])
    read = lf.walk(
        page, guard=FakeGuard(), resume=resume,
        limits=limits(max_posts=10, max_steps=2),
    )
    assert [p.activity for p in read.posts] == ["7004"]
    assert read.posts[0].author == "Margaret Hamilton"
    assert resume.latest == "TOKEN-2"
    assert page.gotos == [lf.FEED_URL]
    assert page.scrolls >= 1


def test_walk_says_when_the_resume_cursor_never_moves():
    page = FakePage([DOM_ONE], [
        FakeResponse("https://www.linkedin.com/graphql/feed", payload()),
    ])
    read = lf.walk(
        page, guard=FakeGuard(), resume=lf.TokenResume(cursor="TOKEN-NEXT"),
        limits=limits(max_steps=1),
    )
    assert read.posts == []
    assert "nothing new" in read.stop
    assert page.scrolls == 1


def test_walk_never_retries_a_signal():
    page = FakePage([DOM_ONE], [
        FakeResponse("https://www.linkedin.com/graphql/feed", "", status=429),
    ])
    lf.walk(page, guard=FakeGuard(), limits=limits())
    assert page.gotos == [lf.FEED_URL]
    assert page.scrolls == 0


# ── the guard seam ──────────────────────────────────────────────────────────


def test_feed_guard_records_a_stop_through_the_linkedin_guard():
    guard = lf.FeedGuard()
    guard.record("rate-limit")
    stop = linkedin.current_stop()
    assert stop is not None and stop.reason == "rate-limit"
    with pytest.raises(lf.GuardRefused) as ei:
        guard.before_load()
    assert "24" in str(ei.value)
    assert "rate limit" in str(ei.value).lower()


def test_feed_guard_refuses_until_a_restriction_is_cleared():
    guard = lf.FeedGuard()
    guard.record("restriction")
    stop = linkedin.current_stop()
    assert stop is not None and stop.until is None
    with pytest.raises(lf.GuardRefused) as ei:
        guard.before_load()
    assert "person" in str(ei.value)


def test_feed_guard_enforces_the_feed_gap(monkeypatch):
    loads = []
    monkeypatch.setattr(linkedin, "take_load", lambda **_k: loads.append("load"))
    now = 1_700_000_000.0
    lf._remember_feed(now - 60)
    guard = lf.FeedGuard(clock=lambda: now)
    with pytest.raises(lf.GuardRefused) as ei:
        guard.before_load()
    assert "at least 30 min apart" in str(ei.value)
    assert loads == []


def test_feed_guard_gap_zero_turns_the_feed_gap_off(monkeypatch):
    monkeypatch.setenv("SEARCHTS_LINKEDIN_FEED_GAP_MINUTES", "0")
    loads = []
    monkeypatch.setattr(linkedin, "take_load", lambda **_k: loads.append("load"))
    now = 1_700_000_000.0
    lf._remember_feed(now - 1)
    lf.FeedGuard(clock=lambda: now).before_load()
    assert loads == ["load"]
    assert lf._last_feed() == now


def test_feed_guard_books_one_load_and_names_a_spent_budget(monkeypatch):
    loads = []

    def counted(**_kwargs):
        loads.append("load")

    monkeypatch.setattr(linkedin, "take_load", counted)
    lf.FeedGuard(clock=lambda: 1_700_000_000.0).before_load()
    assert loads == ["load"]

    def spent(**_kwargs):
        raise linkedin.Paced("budget spent", "wait for SEARCHTS_LINKEDIN_LOADS_PER_HOUR")

    monkeypatch.setattr(linkedin, "take_load", spent)
    lf._remember_feed(0)
    with pytest.raises(lf.GuardRefused) as ei:
        lf.FeedGuard(clock=lambda: 1_700_000_000.0).before_load()
    assert "SEARCHTS_LINKEDIN_LOADS_PER_HOUR" in str(ei.value)


# ── profile and wiring ──────────────────────────────────────────────────────


def test_feed_urls_are_the_home_feed_only():
    assert linkedin.is_feed("https://www.linkedin.com/feed/")
    assert linkedin.is_feed("https://linkedin.com/feed")
    assert not linkedin.is_feed("https://www.linkedin.com/feed/update/urn:li:activity:1/")
    assert not linkedin.is_feed("https://www.linkedin.com/in/someone/")
    assert not linkedin.is_feed("https://example.com/feed/")


def test_profile_problem_names_the_env_var():
    problem = lf.profile_problem("")
    assert "SEARCHTS_LINKEDIN_PROFILE" in problem


def test_profile_problem_rejects_a_missing_directory(tmp_path):
    assert "not a directory" in lf.profile_problem(str(tmp_path / "nope"))


def test_profile_problem_refuses_a_profile_open_in_another_browser(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    os.symlink(f"box-{os.getpid()}", profile / "SingletonLock")
    problem = lf.profile_problem(str(profile))
    assert "already open" in problem
    assert "SEARCHTS_LINKEDIN_CDP" in problem


def test_profile_problem_allows_a_stale_lock(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    os.symlink("box-999999", profile / "SingletonLock")
    assert lf.profile_problem(str(profile)) == ""


def test_read_feed_refuses_without_a_kept_login(monkeypatch):
    monkeypatch.setattr("searchts.login_store.kept", lambda _site: False)
    with pytest.raises(lf.FeedUnavailable) as ei:
        lf.read_feed()
    assert "no kept LinkedIn login" in str(ei.value)
    assert "linkedin-scraper-mcp" in str(ei.value)


def test_read_feed_refuses_before_opening_a_browser_when_the_guard_says_no(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr("searchts.login_store.kept", lambda _site: True)
    monkeypatch.setattr(lf, "profile_problem", lambda _profile: "")
    opened = []
    monkeypatch.setattr(lf, "_browser_page", lambda *a, **k: opened.append(a))

    class No:
        def before_load(self):
            raise lf.GuardRefused("still stopped")

        def record(self, signal):
            raise AssertionError("record must not run")

    with pytest.raises(lf.FeedUnavailable) as ei:
        lf.read_feed(guard=No(), profile=str(tmp_path))
    assert "still stopped" in str(ei.value)
    assert opened == []


def test_read_feed_walks_with_a_fake_page_and_checks_the_guard_once(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr("searchts.login_store.kept", lambda _site: True)
    monkeypatch.setattr(lf, "profile_problem", lambda _profile: "")
    page = FakePage([DOM_ONE], [
        FakeResponse("https://www.linkedin.com/graphql/feed", payload()),
    ])

    class Opened:
        def __enter__(self):
            return page

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(lf, "_browser_page", lambda *a, **k: Opened())
    guard = FakeGuard()
    read = lf.read_feed(guard=guard, limits=limits(), profile=str(tmp_path))
    assert [p.activity for p in read.posts] == ["7001", "7002"]
    assert guard.calls == ["before"]
    assert page.gotos == [lf.FEED_URL]


def test_read_feed_attaches_over_cdp_when_the_profile_is_already_open(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr("searchts.login_store.kept", lambda _site: True)
    monkeypatch.setattr(
        lf, "profile_problem",
        lambda _profile: (_ for _ in ()).throw(
            AssertionError("a CDP attach is the allowed open-profile path")
        ),
    )
    seen = {}
    page = FakePage([DOM_ONE])

    class Opened:
        def __enter__(self):
            return page

        def __exit__(self, *exc):
            return False

    def open_page(profile, executable, cdp, url):
        seen.update(profile=profile, cdp=cdp)
        return Opened()

    monkeypatch.setattr(lf, "_browser_page", open_page)
    lf.read_feed(
        guard=FakeGuard(), limits=limits(), profile=str(tmp_path),
        cdp="127.0.0.1:9222",
    )
    assert seen["cdp"] == "127.0.0.1:9222"


def test_read_feed_is_fail_loud_when_nothing_was_read(monkeypatch, tmp_path):
    monkeypatch.setattr("searchts.login_store.kept", lambda _site: True)
    monkeypatch.setattr(lf, "profile_problem", lambda _profile: "")
    page = FakePage(["<p>nothing here</p>"])

    class Opened:
        def __enter__(self):
            return page

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(lf, "_browser_page", lambda *a, **k: Opened())
    with pytest.raises(lf.FeedUnavailable) as ei:
        lf.read_feed(guard=FakeGuard(), limits=limits(), profile=str(tmp_path))
    assert "no posts" in str(ei.value)


def test_read_routes_the_linkedin_feed_to_the_native_path(monkeypatch):
    read = lf.FeedRead(
        posts=[lf.Post("7001", "Ada Lovelace", "Built a tiny engine.", "3h")],
        text="Ada Lovelace · 3h\nBuilt a tiny engine.\n"
             "https://www.linkedin.com/feed/update/urn:li:activity:7001/",
        stop="reached the 1 posts asked for",
    )
    monkeypatch.setattr(
        lf, "read_feed", lambda url, tick=None, resume_token="": read,
    )
    result = unlocker.fetch("https://www.linkedin.com/feed/", use_memory=False)
    assert result.backend == "linkedin-feed"
    assert result.authenticated is True
    assert "Built a tiny engine." in result.text
    from searchts import resume
    state = resume.read("https://www.linkedin.com/feed/", result.resume or "")
    assert state.keys == ("urn:li:activity:7001",)
    assert state.cursor == ""
    assert state.replay is None


def test_read_a_feed_that_cannot_start_is_a_named_failure(monkeypatch):
    def no(url, tick=None, resume_token=""):
        raise lf.FeedUnavailable("SEARCHTS_LINKEDIN_PROFILE is not set")

    monkeypatch.setattr(lf, "read_feed", no)
    with pytest.raises(UnlockerError) as ei:
        unlocker.fetch("https://www.linkedin.com/feed/", use_memory=False)
    assert ei.value.attempts == [
        ("linkedin-feed", "SEARCHTS_LINKEDIN_PROFILE is not set")
    ]


def test_scroll_steps_do_not_book_a_page_load(monkeypatch):
    calls = []
    monkeypatch.setattr(linkedin, "take_load", lambda **_k: calls.append("load"))
    page = FakePage([DOM_ONE])
    lf.walk(page, guard=FakeGuard(), limits=limits(max_steps=3))
    assert page.scrolls == 3
    assert calls == []


def test_a_feed_read_books_one_load_and_a_second_read_waits(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(linkedin, "take_load", lambda **_k: calls.append("load"))
    monkeypatch.setattr("searchts.login_store.kept", lambda _site: True)
    monkeypatch.setattr(lf, "profile_problem", lambda _profile: "")
    page = FakePage([DOM_ONE, DOM_ONE, DOM_ONE], [
        FakeResponse("https://www.linkedin.com/graphql/feed", payload()),
    ])

    class Opened:
        def __enter__(self):
            return page

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(lf, "_browser_page", lambda *a, **k: Opened())
    read = lf.read_feed(limits=limits(max_steps=3), profile=str(tmp_path))
    assert page.scrolls == 3
    assert [post.activity for post in read.posts] == ["7001", "7002"]
    assert calls == ["load"]
    with pytest.raises(lf.FeedUnavailable) as ei:
        lf.read_feed(limits=limits(max_steps=3), profile=str(tmp_path))
    assert "at least 30 min apart" in str(ei.value)
    assert calls == ["load"]


def test_resume_from_token_is_an_in_page_hook():
    class State:
        cursor = "TOKEN-NEXT"
        keys = ["urn:li:activity:7001", "7002"]

    class Mod:
        def read(self, url, token):
            assert url == lf.FEED_URL
            assert token == "signed"
            return State()

    hook = lf.resume_from_token(lf.FEED_URL, "signed", module=Mod())
    assert isinstance(hook, lf.TokenResume)
    assert hook.begin() == "TOKEN-NEXT"
    assert hook.seen() == ["urn:li:activity:7001", "7002"]
    assert lf.resume_from_token(lf.FEED_URL, "  ").begin() is None


def test_resume_from_token_refuses_before_a_browser(monkeypatch, tmp_path):
    monkeypatch.setattr("searchts.login_store.kept", lambda _site: True)
    monkeypatch.setattr(lf, "profile_problem", lambda _profile: "")
    opened = []
    monkeypatch.setattr(lf, "_browser_page", lambda *a, **k: opened.append(a))
    with pytest.raises(lf.FeedUnavailable) as ei:
        lf.read_feed(
            guard=FakeGuard(), profile=str(tmp_path), resume_token="signed",
        )
    assert opened == []
    assert "resume token" in str(ei.value).lower()


def test_resume_from_token_names_a_rejected_token():
    class Mod:
        def read(self, url, token):
            raise type("ResumeError", (Exception,), {})("token expired")

    with pytest.raises(lf.FeedUnavailable) as ei:
        lf.resume_from_token(lf.FEED_URL, "signed", module=Mod())
    assert "token expired" in str(ei.value)


def test_cdp_attach_opens_a_tab_in_the_existing_window():
    opened = []

    class Page:
        pass

    class Context:
        def new_page(self):
            page = Page()
            opened.append(page)
            return page

    class Browser:
        contexts = [Context()]

        def new_context(self):
            raise AssertionError("a CDP attach must not open a new context")

    page = lf._cdp_page(Browser())
    assert page is opened[0]


def test_cdp_attach_refuses_when_chrome_has_no_window():
    class Browser:
        contexts = []

        def new_context(self):
            raise AssertionError("a CDP attach must not open a new context")

    with pytest.raises(lf.FeedUnavailable) as ei:
        lf._cdp_page(Browser())
    assert "no open window" in str(ei.value)
    assert "new browser context is not opened" in str(ei.value)


def test_a_resumed_feed_read_scrolls_and_does_not_replay(monkeypatch):
    from searchts import resume

    seen = {}

    def fake(url, tick=None, resume_token=""):
        seen["token"] = resume_token
        return lf.FeedRead(
            posts=[lf.Post("7004", "Margaret Hamilton", "The next page.", "1h")],
            text="Margaret Hamilton · 1h\nThe next page.",
            cursor="TOKEN-2",
        )

    monkeypatch.setattr(lf, "read_feed", fake)

    def boom(*_args, **_kwargs):
        raise AssertionError("the generic scroll must not run for this feed")

    monkeypatch.setattr(unlocker, "_scroll_feed", boom)
    token = resume.mint(
        "https://www.linkedin.com/feed/",
        keys=["urn:li:activity:7001"],
        cursor="TOKEN-NEXT",
    )
    pages = unlocker.read_items(
        "https://www.linkedin.com/feed/", 10, resume=token, use_memory=False,
    )
    assert seen["token"] == token
    assert pages[0].backend == "linkedin-feed"
    state = resume.read("https://www.linkedin.com/feed/", pages[0].resume or "")
    assert state.cursor == "TOKEN-2"
    assert state.replay is None
    assert "captured cursor" in pages[0].text


def test_the_driver_never_calls_linkedin_or_fetches_in_page():
    source = (
        Path(__file__).resolve().parents[1] / "searchts" / "linkedin_feed.py"
    ).read_text(encoding="utf-8").lower()
    for banned in (
        "fetch(",
        "xmlhttprequest",
        "page.request",
        "api.linkedin.com",
        "/voyager",
        "requests.get",
    ):
        assert banned not in source, banned
