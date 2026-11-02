# -*- coding: utf-8 -*-
"""#510: resume a scroll read with a signed token.

The token is tested for what it refuses (tampered, expired, foreign URL) and
for what it carries (row tail, captured cursor, URL position). The three
resume methods are driven through a fake page, the same way
``test_scroll_expand.py`` drives the loop, because the thing under test is the
decision the loop makes and a live feed would make it non-deterministic.
"""

from __future__ import annotations

import json

import pytest

from searchts import resume, scroll, unlocker

URL = "https://example.org/feed"


# ── token sign / verify / expiry ─────────────────────────────────────────────


def keys_for(numbers):
    return ["Lhttps://example.org/t/item-%d/" % i for i in numbers]


def test_a_token_round_trips_what_the_walk_needs():
    token = resume.mint(
        URL,
        keys=keys_for(range(30)),
        cursor="abc123",
        replay={"u": "https://example.org/api?after=x", "m": "get",
                "b": "", "f": "after"},
        position=("page", "3"),
    )
    state = resume.read(URL, token)
    assert len(state.keys) == resume.TAIL_KEYS, "the token keeps a bounded tail"
    assert state.keys[-1] == keys_for([29])[0]
    assert state.cursor == "abc123"
    assert state.replay is not None
    assert state.replay["m"] == "GET"
    assert state.position == ("page", "3")


def test_a_tampered_token_is_refused():
    token = resume.mint(URL, keys=keys_for(range(3)))
    body, _, sig = token.partition(".")
    flipped = body[:-1] + ("A" if body[-1] != "A" else "B")
    with pytest.raises(resume.ResumeError, match="does not verify"):
        resume.read(URL, f"{flipped}.{sig}")


def test_an_unsigned_token_is_refused():
    with pytest.raises(resume.ResumeError, match="unsigned"):
        resume.read(URL, "eyJrIjpbXX0")


def test_a_token_for_another_url_is_refused():
    token = resume.mint(URL, keys=keys_for(range(3)))
    with pytest.raises(resume.ResumeError, match="different URL"):
        resume.read("https://elsewhere.test/feed", token)


def test_the_position_does_not_change_the_fingerprint():
    # A token issued for the feed must still verify when the resumed read opens
    # ?page=2; that is the whole point of the URL-position method.
    token = resume.mint(URL, keys=keys_for(range(3)))
    assert resume.read(URL + "?page=2", token).keys


def test_an_expired_token_is_refused():
    issued = 1_000_000
    token = resume.mint(URL, keys=keys_for(range(3)), now=issued)
    with pytest.raises(resume.ResumeError, match="expired"):
        resume.read(URL, token, now=issued + resume.TOKEN_TTL_SECONDS + 1)


def test_an_unknown_version_is_refused():
    # A v2 payload from a future release is not guessed at. Signed with this
    # process's resume key, so the refusal is the version and not the signature.
    token = resume._b64encode({"v": 2, "u": "x", "t": 0, "k": []})
    with pytest.raises(resume.ResumeError, match="version"):
        resume.read(URL, token)


def test_a_token_verifies_with_the_key_a_later_process_would_read(tmp_path, monkeypatch):
    # The key is on disk, not in the process. A second call, with the cache
    # cleared, must accept the token the first call minted.
    from searchts.config import Config

    monkeypatch.setattr(Config, "CONFIG_DIR", tmp_path)
    resume._KEY = None
    token = resume.mint(URL, keys=keys_for(range(2)))
    resume._KEY = None
    assert resume.read(URL, token).keys == tuple(keys_for(range(2)))


def test_the_token_is_not_mintable_from_page_text():
    # A payload a page could write, with no signature this process issued.
    forged = "eyJ2IjoxLCJ1IjoiMCAiLCJ0IjowLCJrIjpbXX0"
    with pytest.raises(resume.ResumeError, match="not valid"):
        resume.read(URL, forged)


# ── URL positions ────────────────────────────────────────────────────────────


def test_the_next_position_prefers_the_page_s_own_next_link():
    got = resume.next_position(
        "https://news.ycombinator.com/newest",
        "https://news.ycombinator.com/newest?p=2",
    )
    assert got == ("p", "2")


def test_a_numeric_position_is_bumped_one_page():
    assert resume.next_position("https://example.org/list?page=2") == ("page", "3")
    # offset is a stride, not a page number: bumping it by one is wrong, so a
    # URL with only an offset gets no position unless its own next link says.
    assert resume.next_position("https://example.org/list?offset=40") is None


def test_an_opaque_position_is_not_bumped():
    assert resume.next_position("https://example.org/list?after=t3_abc") is None


def test_url_at_position_sets_the_parameter_without_losing_the_others():
    got = resume.url_at_position(
        "https://example.org/list?sort=new&page=1", ("page", "2")
    )
    assert "page=2" in got
    assert "sort=new" in got


# ── passive capture ──────────────────────────────────────────────────────────


class FakeRequest:
    def __init__(self, url, method="GET", body="", rtype="xhr"):
        self.url = url
        self.method = method
        self.post_data = body
        self.resource_type = rtype


class FakeResponse:
    def __init__(self, url, data, request=None, status=200,
                 ctype="application/json"):
        self.url = url
        self._data = data
        self.request = request or FakeRequest(url)
        self.status = status
        self.headers = {"content-type": ctype}
        self.json_calls = 0

    def json(self):
        self.json_calls += 1
        return self._data


def test_a_cursor_is_captured_from_a_same_site_json_response():
    cap = resume.Capture(URL)
    data = {"data": {"pageInfo": {"endCursor": "CUR1", "hasNextPage": True}}}
    cap(FakeResponse("https://example.org/api/feed", data))
    assert cap.pending, "the body is read later, not inside the handler"
    cap.drain()
    assert cap.cursor == "CUR1"
    assert cap.replay is not None
    assert cap.replay["f"] == "endCursor"


def test_a_cross_site_or_non_json_response_is_ignored():
    cap = resume.Capture(URL)
    cap(FakeResponse("https://elsewhere.test/api", {"cursor": "X"}))
    cap(FakeResponse("https://example.org/api", {"cursor": "X"},
                     ctype="text/html"))
    cap(FakeResponse("https://example.org/api", {"cursor": "X"},
                     request=FakeRequest("https://example.org/api", rtype="document")))
    cap.drain()
    assert cap.cursor == ""
    assert cap.pending == []


def test_a_429_data_response_is_noticed_and_does_not_raise():
    cap = resume.Capture(URL)
    cap(FakeResponse("https://example.org/api/feed", None, status=429))
    assert cap.rate_limited is True
    # A page that is not the feed's own data does not count.
    other = resume.Capture(URL)
    other(FakeResponse("https://example.org/asset.js", None, status=429,
                       request=FakeRequest("https://example.org/asset.js",
                                           rtype="script")))
    assert other.rate_limited is False


def test_the_most_explicit_cursor_name_wins():
    data = {"cursor": "old", "paging": {"next_cursor": "next"},
            "edges": [{"end_cursor": "end"}]}
    assert resume.find_cursor(data) == ("end", "end_cursor")
    assert resume.find_cursor({"data": {"after": "A"}}) == ("A", "after")
    assert resume.find_cursor({"nothing": "here"}) is None


def test_the_replayed_request_moves_the_cursor_in_the_body():
    state = resume.ResumeState(
        keys=(),
        cursor="NEXT",
        replay={"u": "https://example.org/graphql", "m": "POST",
                "b": json.dumps({"variables": {"after": "OLD"}}), "f": "after"},
    )
    moved = resume.replay_request(state)
    assert moved is not None
    assert json.loads(moved["b"])["variables"]["after"] == "NEXT"
    assert moved["u"] == "https://example.org/graphql"


def test_the_replayed_request_moves_the_cursor_in_the_url():
    state = resume.ResumeState(
        keys=(),
        cursor="NEXT",
        replay={"u": "https://example.org/api?after=OLD&n=20", "m": "GET",
                "b": "", "f": "after"},
    )
    moved = resume.replay_request(state)
    assert moved is not None
    assert "after=NEXT" in moved["u"]
    assert "n=20" in moved["u"]


# ── the loop, on a fake page ─────────────────────────────────────────────────


def row(i):
    href = "https://example.org/t/item-%d/" % i
    return {
        "key": "L" + href,
        "html": (
            f'<tr class="topic-list-item"><td><a href="{href}">'
            f"Topic number {i} with a title long enough to look like a row</a>"
            f"</td></tr>"
        ),
    }


class FakePage:
    """The scroll loop's JS, in Python, with a resume-shaped store."""

    def __init__(self, steps, url=URL):
        self.steps = steps
        self.url = url
        self.scrolled = 0
        self.store = {}
        self.order = []
        self.start = 0
        self.replay_result = None
        self.replays = []
        self.rebuilt = []

    def evaluate(self, js, arg=None):
        if "await fetch(" in js:
            self.replays.append(arg)
            return self.replay_result
        if "window.scrollTo" in js:
            self.scrolled += 1
            return None
        if "s.start = s.order.length" in js:
            hidden = len(self.order) - self.start
            self.start = len(self.order)
            return hidden
        if "row.key" in js:
            added = 0
            for r in arg or []:
                if r["key"] in self.store:
                    continue
                self.store[r["key"]] = r["html"]
                self.order.append(r["key"])
                added += 1
            return {"added": added, "total": len(self.order) - self.start}
        if "keys.indexOf" in js:
            keys = arg or []
            last = -1
            for i, k in enumerate(self.order):
                if k in keys:
                    last = i
            if last < 0:
                return {"dropped": 0, "total": len(self.order) - self.start,
                        "found": False}
            if last + 1 > self.start:
                self.start = last + 1
            return {"dropped": self.start, "total": len(self.order) - self.start,
                    "found": True}
        if "s.order.slice" in js:
            order = self.order[self.start:]
            return {"order": order, "rows": [self.store[k] for k in order]}
        if "findBest" in js:
            before = len(self.order)
            for r in self._rows():
                if r["key"] in self.store:
                    continue
                self.store[r["key"]] = r["html"]
                self.order.append(r["key"])
            return {"rows": len(self._rows()), "total": len(self.order) - self.start,
                    "added": len(self.order) - before, "found": True}
        if "data-searchts-collected" in js:
            self.rebuilt = [self.store[k] for k in self.order[self.start:]]
            return len(self.rebuilt)
        if "deepLink" in js:
            return {"rows": len(self._rows()), "parent": True} if len(self._rows()) >= 3 else None
        if "button,[role=button]" in js:
            return None
        if "challenge-form" in js:
            return ""
        return None

    def wait_for_timeout(self, ms):
        return None

    def query_selector_all(self, selector):
        return []

    def content(self):
        return "<html><body><p>a feed with no wall on it</p></body></html>"

    def _rows(self):
        return list(self.steps[min(self.scrolled, len(self.steps) - 1)])


def run(page, **kw):
    opts = dict(want_rows=50, max_clicks=0, budget_seconds=5, step_ms=1,
                empty_steps=2)
    opts.update(kw)
    return scroll.collect(page, **opts)


def test_fast_skip_reports_only_rows_after_the_seam():
    steps = [
        [row(i) for i in range(10)],
        [row(i) for i in range(5, 15)],
        [row(i) for i in range(10, 20)],
        [row(i) for i in range(10, 20)],
    ]
    page = FakePage(steps)
    state = resume.ResumeState(keys=tuple(keys_for(range(4, 10))))
    rep = run(page, resume=state, want_rows=8)
    assert rep.resume_method == "fast-skip"
    assert rep.resume_found is True
    assert rep.keys == keys_for(range(10, 20))
    assert all(k not in rep.keys for k in keys_for(range(10))), (
        "a row the token already had was returned again"
    )
    assert "resumed after the last row this token had" in rep.note()


def test_a_reordered_feed_says_it_resumed_from_the_top():
    steps = [[row(i) for i in range(10)], [row(i) for i in range(10, 20)],
             [row(i) for i in range(20, 30)], [row(i) for i in range(20, 30)]]
    page = FakePage(steps)
    state = resume.ResumeState(keys=tuple(keys_for(range(90, 100))))
    rep = run(page, resume=state, want_rows=50, empty_steps=2)
    assert rep.resume_found is False
    assert rep.resume_method == "changed"
    assert "the feed changed" in rep.note()
    assert len(rep.keys) > 0, "the rows it did see are not thrown away"


def test_a_captured_cursor_replays_the_next_batch_and_keeps_only_it():
    page = FakePage([[row(i) for i in range(5)], [row(i) for i in range(5)]])
    page.replay_result = {
        "status": 200,
        "url": "https://example.org/api/feed",
        "json": {"data": {"items": [
            {"url": "/t/item-50/", "title": "A replayed row title long enough"},
            {"url": "/t/item-51/", "title": "Another replayed row title here"},
        ], "pageInfo": {"endCursor": "CUR3"}}},
    }
    state = resume.ResumeState(
        keys=tuple(keys_for(range(5))),
        cursor="CUR2",
        replay={"u": "https://example.org/api/feed?after=CUR1", "m": "GET",
                "b": "", "f": "after"},
    )
    rep = run(page, resume=state, want_rows=2)
    assert page.replays, "the captured request was never replayed"
    assert rep.resume_method == "cursor"
    assert len(rep.keys) == 2, "the top of the feed was counted again"
    assert "resumed at the feed's own captured cursor" in rep.note()
    # The cursor this read sent is spent. The token keeps the one the
    # response named, or the next resume would replay this same batch.
    assert rep.cursor == "CUR3"
    assert rep.cursor != "CUR2"


def test_a_cursor_resume_keeps_scrolling_for_rows_the_replay_did_not_hold():
    # The replay is the seam, not the whole answer. Rows the page reveals
    # after it are kept; rows the token already had, including ones that
    # unmount as the page scrolls, are not counted again.
    later = [row(i) for i in range(3, 8)]
    page = FakePage([[row(i) for i in range(5)], later, later])
    page.replay_result = {
        "status": 200,
        "url": "https://example.org/api/feed",
        "json": {"data": {"items": [
            {"url": "/t/item-50/", "title": "A replayed row title long enough"},
        ]}},
    }
    state = resume.ResumeState(
        keys=tuple(keys_for(range(5))),
        cursor="CUR2",
        replay={"u": "https://example.org/api/feed?after=CUR1", "m": "GET",
                "b": "", "f": "after"},
    )
    rep = run(page, resume=state, want_rows=6)
    assert rep.resume_method == "cursor"
    assert keys_for([50])[0] in rep.keys
    assert any(k in rep.keys for k in keys_for(range(5, 8)))
    assert all(k not in rep.keys for k in keys_for(range(5)))


def test_a_replayed_429_stops_and_keeps_the_rows_already_seen():
    page = FakePage([[row(i) for i in range(5)], [row(i) for i in range(5, 15)]])
    page.replay_result = {"status": 429, "url": "https://example.org/api/feed",
                          "json": None}
    state = resume.ResumeState(
        keys=tuple(keys_for(range(90, 95))),
        cursor="CUR2",
        replay={"u": "https://example.org/api/feed?after=CUR1", "m": "GET",
                "b": "", "f": "after"},
    )
    rep = run(page, resume=state, want_rows=50, empty_steps=5)
    assert rep.rate_limited is True
    assert "rate-limited the feed (429)" in rep.note()
    assert rep.resume_method != "changed"
    assert page.scrolled == 0, "a 429 must not keep scrolling"
    assert len(rep.keys) == 5


def test_a_rate_limited_data_response_stops_the_walk_and_keeps_rows():
    cap = resume.Capture(URL)
    page = FakePage([[row(i) for i in range(5)], [row(i) for i in range(10)]])

    original = page.wait_for_timeout

    def wait_then_429(ms):
        original(ms)
        cap(FakeResponse("https://example.org/api/feed", None, status=429))

    page.wait_for_timeout = wait_then_429
    rep = scroll.collect(page, want_rows=50, max_clicks=0, budget_seconds=5,
                         step_ms=1, empty_steps=5, capture=cap)
    assert rep.rate_limited is True
    assert "rate-limited the feed (429)" in rep.note()
    assert rep.stop == "the site rate-limited the feed (429)"
    assert len(rep.keys) == 5, "rows seen before the 429 are kept"


# ── wiring: the token reaches the read and the surfaces ──────────────────────


def _stub_fetch(monkeypatch, text="- [Row](https://example.org/r/0)"):
    def fake(url, **kw):
        return unlocker.FetchResult(backend="curl_cffi", text=text, status=200,
                                    final_url=url, next_url=None)

    monkeypatch.setattr(unlocker, "fetch", fake)


def test_in_page_resume_is_tried_before_the_url_is_bumped(monkeypatch):
    # Keys (or a cursor) mean the seam can be found on the page. The URL
    # position is the third method, so the walk must not skip to it.
    token = resume.mint(
        URL, keys=keys_for(range(3)), position=("page", "2"),
        cursor="CUR", replay={"u": "https://example.org/api", "m": "GET",
                              "b": "", "f": "after"},
    )
    seen = []
    fetched = []

    def fake_fetch(url, **kw):
        fetched.append(url)
        return unlocker.FetchResult(backend="curl_cffi", text="- [Row](https://example.org/r/0)",
                                    status=200, final_url=url, next_url=None)

    def fake_collect(url, **kw):
        seen.append((url, kw.get("resume")))
        return scroll.ScrollReport(
            rows=[row(9)["html"]], keys=keys_for([9]), page_url=url,
            resume_method="fast-skip",
            html="<html><body><div>" + row(9)["html"] + "</div></body></html>",
        ), ""

    monkeypatch.setattr(unlocker, "fetch", fake_fetch)
    monkeypatch.setattr(scroll, "browser_available", lambda: True)
    monkeypatch.setattr(scroll, "collect_url", fake_collect)
    got = unlocker.read_items(URL, 10, resume=token)
    assert fetched and fetched[0] == URL
    assert seen and seen[0][0] == URL
    assert seen[0][1] is not None, "the scroll must be handed the token"
    assert seen[0][1].cursor == "CUR"
    assert "resumed after the last row" in got[0].text.lower() or "Resumed after" in got[0].text
    assert got[0].resume


def test_a_position_only_token_starts_at_the_next_page(monkeypatch):
    token = resume.mint(URL, keys=[], position=("page", "2"))
    fetched = []

    def fake_fetch(url, **kw):
        fetched.append(url)
        rows = "\n".join(
            "- [Post %d](https://example.org/t/item-%d/)" % (i, i) for i in range(10)
        )
        return unlocker.FetchResult(
            backend="curl_cffi", text=rows, status=200, final_url=url,
            next_url=URL + "?page=3",
        )

    monkeypatch.setattr(unlocker, "fetch", fake_fetch)
    monkeypatch.setattr(scroll, "browser_available", lambda: True)
    got = unlocker.read_items(URL, 10, resume=token)
    assert fetched and fetched[0] == URL + "?page=2"
    assert "Resumed at the next page in the URL" in got[0].text
    assert got[0].resume
    # The token continues from the page this read landed on, not from page 2
    # again.
    assert resume.read(URL, got[0].resume).position == ("page", "3")


def test_an_items_read_names_the_next_page_when_it_did_not_scroll(monkeypatch):
    def fake(url, **kw):
        rows = "\n".join(
            "- [Post %d](https://example.org/t/item-%d/)" % (i, i) for i in range(8)
        )
        return unlocker.FetchResult(
            backend="curl_cffi", text=rows, status=200, final_url=url,
            next_url=URL + "?p=2",
        )

    monkeypatch.setattr(unlocker, "fetch", fake)
    monkeypatch.setattr(scroll, "browser_available", lambda: False)
    got = unlocker.read_items(URL, 5)
    state = resume.read(URL, got[0].resume)
    assert state.position == ("p", "2")
    assert state.keys == ()
    assert "[resume:" in got[0].text


def test_a_resumed_scroll_uses_the_resolved_ceilings(monkeypatch):
    monkeypatch.setenv("SEARCHTS_MORE_SECONDS", "7")
    monkeypatch.setenv("SEARCHTS_MORE_EMPTY_STEPS", "4")
    token = resume.mint(URL, keys=keys_for(range(3)))
    seen = {}

    def fake_collect(url, **kw):
        seen.update(kw)
        return scroll.ScrollReport(
            rows=[row(9)["html"]], keys=keys_for([9]), page_url=url,
            html="<html><body><div>" + row(9)["html"] + "</div></body></html>",
        ), ""

    _stub_fetch(monkeypatch)
    monkeypatch.setattr(scroll, "browser_available", lambda: True)
    monkeypatch.setattr(scroll, "collect_url", fake_collect)
    unlocker.read_items(URL, 10, resume=token)
    assert seen.get("budget_seconds") == 7
    assert seen.get("empty_steps") == 4
    assert seen.get("resume") is not None


def test_a_bad_resume_token_is_refused_not_silently_read_from_the_top(monkeypatch):
    _stub_fetch(monkeypatch)
    with pytest.raises(unlocker.UnlockerError, match="resume"):
        unlocker.read_items(URL, 10, resume="not-a-token")


def test_the_mcp_envelope_carries_the_resume_token(monkeypatch):
    from searchts.integrations import mcp_server

    token = resume.mint(URL, keys=keys_for(range(3)))
    seen = {}

    def fake(*args, **kw):
        seen.update(kw)
        seen["max_items"] = args[1]
        return [unlocker.FetchResult(
            backend="curl_cffi", text="body", status=200, final_url=args[0],
            resume=token,
        )]

    monkeypatch.setattr(unlocker, "read_items", fake)
    monkeypatch.setattr("searchts.ssrf.guard_mcp_url", lambda url, **kw: None)
    out = mcp_server.read_url(URL, resume=token)
    assert seen.get("resume") == token
    assert seen.get("max_items"), "resume must select the rows-first path"
    assert json.loads(out)["resume"] == token


def test_a_read_without_a_scroll_has_no_resume_token(monkeypatch):
    from searchts.integrations import mcp_server

    def fake(*args, **kw):
        return [unlocker.FetchResult(
            backend="curl_cffi", text="body", status=200, final_url=args[0],
        )]

    monkeypatch.setattr(unlocker, "read_pages", fake)
    monkeypatch.setattr("searchts.ssrf.guard_mcp_url", lambda url, **kw: None)
    assert "resume" not in json.loads(mcp_server.read_url(URL))
