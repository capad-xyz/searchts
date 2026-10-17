# -*- coding: utf-8 -*-
"""F5f: Reddit, the rest. More posts, deeper comments, every wall named.

Every fixture here is a trimmed slice of a page this box actually fetched on
2026-10-17 (the comment in each file names the source). Nothing is guessed
markup, and nothing in this file touches the network.

What each fixture is, and what it proved:

``reddit_feed_cursor``      /r/MachineLearning/hot/ in the browser: 3 post cards
                            in the light DOM and a ``faceplate-partial`` whose
                            ``src`` is Reddit's next-batch cursor.
``reddit_feed_batch``       that cursor, fetched with curl: 8 cards kept of 24
                            in the page, and its own next cursor.
``reddit_thread_first_window`` a 195-comment thread as first served: 14 comments.
``reddit_thread_expanded``  the same thread after its "more replies" controls
                            were opened: 31 comments, past the 30 cap.
``reddit_post_archived``    a thread whose OP Reddit archived (its text is gone).
``reddit_post_quoting_archived``
                            a live thread whose OP quotes "Archived post. New
                            comments cannot be posted" in its own body, and is
                            not archived: the notice as prose, not as a wall.
``reddit_profile``          /user/spez/ as served: header fields plus cards.
``reddit_profile_batch``    that profile's cursor: posts and comments mixed.
``reddit_search``           /search/?q=searchts as served: result cards.
``reddit_search_nsfw``      /search/?q=gore: the over-18 banner.
``reddit_private``          /r/gryffindor/  ``reddit_banned``  /r/Random/
``reddit_quarantined``      /r/incest/      ``reddit_community_gone`` /r/nsfw/
``reddit_post_gone``        a comment URL for a post that is not there.
``reddit_challenge``        Reddit's "Prove your humanity", served HTTP 200 to a
                            direct request for a next-batch cursor: zero cards.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from searchts import unlocker
from searchts.known_hosts import reddit
from searchts.unlocker import looks_blocked

FIXTURES = Path(__file__).parent / "fixtures"

LISTING = "https://www.reddit.com/r/MachineLearning/hot/"
BATCH = (
    "https://www.reddit.com/svc/shreddit/community-more-posts/hot/"
    "?after=dDNfMXg3ZjZmdA%3D%3D&t=DAY&name=MachineLearning"
)
THREAD = (
    "https://www.reddit.com/r/MachineLearning/comments/1x4awlk/"
    "what_is_the_strongest_mechanistic_argument_that/"
)
ARCHIVED = (
    "https://www.reddit.com/r/findareddit/comments/17k6a07/"
    "can_someone_list_some_subreddits_that_are_private/"
)
#: A live thread whose OP *quotes* the archived notice in its own body text
#: (``reddit_post_quoting_archived.html``). Nothing about this page is a wall.
QUOTING_ARCHIVED = (
    "https://www.reddit.com/r/NoStupidQuestions/comments/1x4uke7/"
    "is_it_possible_to_read_the_body_text_to_an/"
)
PROFILE = "https://www.reddit.com/user/spez/"
PROFILE_BATCH = (
    "https://www.reddit.com/svc/shreddit/profiles/profile_overview-more-posts/new/"
    "?after=dDNfMXR2c2E1OQ%3D%3D&name=spez"
)
SEARCH = "https://www.reddit.com/search/?q=searchts"
SEARCH_NSFW = "https://www.reddit.com/search/?q=gore"
GONE = "https://www.reddit.com/r/MachineLearning/comments/1zzzzzz/this_post_is_not_here/"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def page(url: str, name: str):
    return reddit.extract_page(url, fixture(name))


# ── page kinds ───────────────────────────────────────────────────────────────


def test_page_kind_splits_the_reddit_pages():
    assert reddit.page_kind(LISTING) == "listing"
    assert reddit.page_kind(BATCH) == "batch"
    assert reddit.page_kind(THREAD) == "thread"
    assert reddit.page_kind(PROFILE) == "profile"
    assert reddit.page_kind(SEARCH) == "search"
    assert reddit.page_kind("https://www.reddit.com/r/python/search/?q=lists") == "search"
    assert reddit.page_kind("https://www.reddit.com/user/spez/submitted/") == "profile"


def test_page_kind_is_empty_for_json_and_for_other_hosts():
    # The JSON ring owns every .json URL; this entry point must not claim one.
    assert reddit.page_kind("https://www.reddit.com/r/python/hot.json") == ""
    assert reddit.page_kind("https://old.reddit.com/r/python/comments/abc/t/.json") == ""
    assert reddit.page_kind("https://example.com/r/python/hot/") == ""
    assert reddit.page_kind("https://www.reddit.com/user/spez/.json") == ""


def test_batch_url_is_reddit_own_cursor_and_nothing_else():
    assert reddit.is_reddit_batch_url(BATCH)
    assert reddit.is_reddit_batch_url(PROFILE_BATCH)
    assert reddit.is_reddit_profile_batch_url(PROFILE_BATCH)
    assert not reddit.is_reddit_profile_batch_url(BATCH)
    # A lookalike host is not Reddit's cursor, and it is what `next_url` would
    # hand an agent to follow.
    assert not reddit.is_reddit_batch_url(
        "https://evil.test/svc/shreddit/community-more-posts/hot/?after=x"
    )
    assert not reddit.is_reddit_batch_url(
        "https://www.reddit.com.evil.test/svc/shreddit/community-more-posts/hot/?after=x"
    )


def test_json_url_still_falls_through_to_the_json_ring():
    assert reddit.extract_page("https://www.reddit.com/r/python/hot.json", fixture("reddit_feed_cursor.html")) is None
    assert reddit.extract_page("https://example.com/r/python/hot/", "<html>hi</html>") is None


# ── the next-post cursor ─────────────────────────────────────────────────────


def test_listing_reads_and_hands_back_reddits_own_cursor():
    p = page(LISTING, "reddit_feed_cursor.html")
    assert p.failure is None
    assert p.label == "listing-html: 3 posts"
    assert p.next_url, "the first window must name Reddit's next batch"
    assert p.next_url.startswith(
        "https://www.reddit.com/svc/shreddit/community-more-posts/hot/?after="
    )
    assert "&amp;" not in p.next_url  # unescaped, or the next request is broken
    assert p.keys and len(set(p.keys)) == len(p.keys), "one identity per row"
    assert [m["kind"] for m in p.more] == ["next-page"]
    # The note counts the page that was just read, and never the batch behind the
    # cursor: that count is Reddit's and we have not seen it. Measured live
    # 2026-10-17 (artifacts f5f/r3/r3_listing_items): 3 cards on page one, 24
    # on the batch its cursor served, and the note claimed a 3-post batch.
    note = p.more[0]["note"]
    assert note == (
        f"[more: after these 3 cards, Reddit's own cursor for the next batch of "
        f"this feed is {p.next_url}]"
    ), note
    assert p.more[0]["url"] == p.next_url


def test_batch_is_a_listing_and_carries_the_next_cursor_on():
    p = page(BATCH, "reddit_feed_batch.html")
    assert p.failure is None
    assert p.label == "listing-batch: 8 posts"
    assert p.next_url and "after=" in p.next_url
    assert len(p.keys) == 8
    body = p.markdown.splitlines()
    assert body[0].startswith("- **")
    assert sum(1 for line in body if line.startswith("- **")) == 8


def test_batch_cursor_from_a_profile_names_the_profile_cursor():
    p = page(PROFILE_BATCH, "reddit_profile_batch.html")
    assert p.next_url and p.next_url.startswith(
        "https://www.reddit.com/svc/shreddit/profiles/profile_overview-more-posts/"
    )


def test_next_batch_url_refuses_a_foreign_host():
    html = (
        '<faceplate-partial slot="load-after" '
        'src="/svc/shreddit/community-more-posts/hot/?after=x"></faceplate-partial>'
    )
    assert reddit.next_batch_url(html).startswith("https://www.reddit.com/svc/")
    hostile = html.replace("/svc/", "https://evil.test/svc/")
    assert reddit.next_batch_url(hostile) == ""
    # A partial that is not the load-after slot is not the cursor.
    assert reddit.next_batch_url(html.replace('slot="load-after"', 'slot="x"')) == ""


def test_empty_batch_fails_loud_instead_of_reading_as_an_empty_feed():
    p = reddit.extract_page(BATCH, "<html><body><shreddit-feed></shreddit-feed></body></html>")
    assert p is not None and p.failure == "reddit-no-posts"
    assert p.markdown == ""


def test_reddits_humanity_check_is_never_read_as_an_empty_feed():
    """Measured 2026-10-17: HTTP 200, a reCAPTCHA mount, zero post cards.

    Called "no posts" this would be the worst answer in the file: it is wrong
    (the feed had 24 cards for the browser rung in the same minute) and nothing
    in the page can refute it. Both the shared wall detector and this ring name
    it, because it reaches the batch path that only ever expects cards.
    """
    html = fixture("reddit_challenge.html")
    assert looks_blocked(200, html, {}) == "challenge", (
        "the ladder must escalate past this, not extract it"
    )
    assert reddit.page_state(BATCH, html) == "reddit-challenge"
    p = reddit.extract_page(BATCH, html)
    assert p is not None and p.failure == "reddit-challenge"
    assert p.markdown == ""
    assert "Prove your humanity" in reddit.state_note("reddit-challenge", BATCH)
    # A listing page must not be swallowed by it either: a real listing page
    # never carries the interstitial's own title.
    assert reddit.page_state(LISTING, fixture("reddit_feed_cursor.html")) == ""


def test_the_ladder_reports_the_challenge_and_keeps_climbing(monkeypatch):
    _no_reddit_json(monkeypatch)
    challenge = fixture("reddit_challenge.html")
    served = [challenge, challenge]
    monkeypatch.setattr(
        unlocker,
        "_fetch_curl_cffi",
        lambda url, timeout=30: (200, served.pop() if served else "x" * 400, url, {}),
    )
    monkeypatch.setattr(
        unlocker, "_fetch_jina", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no jina"))
    )
    monkeypatch.setattr(
        unlocker,
        "_fetch_stealth",
        lambda url, *a, **k: (200, fixture("reddit_feed_batch.html"), url, {}),
    )
    res = unlocker.fetch(
        BATCH, backends=["curl_cffi", "stealth-browser"], use_memory=False
    )
    # The browser rung answered the same URL with 24 cards, so the read lands
    # there. Nothing in the receipt claims the feed was empty.
    assert res.backend == "stealth-browser"
    assert res.text.count("- **") == 8


def test_every_rung_failing_on_the_challenge_names_it_not_an_empty_feed(monkeypatch):
    _no_reddit_json(monkeypatch)
    challenge = fixture("reddit_challenge.html")
    monkeypatch.setattr(
        unlocker, "_fetch_curl_cffi", lambda url, timeout=30: (200, challenge, url, {})
    )
    monkeypatch.setattr(
        unlocker, "_fetch_jina", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no jina"))
    )
    monkeypatch.setattr(unlocker, "_fetch_stealth", lambda url, *a, **k: (200, challenge, url, {}))
    with pytest.raises(unlocker.UnlockerError) as ei:
        unlocker.fetch(
            BATCH, backends=["curl_cffi", "stealth-browser"], use_memory=False
        )
    reasons = dict(ei.value.attempts)
    assert "no posts" not in " ".join(reasons.values()), reasons
    # "challenge" is true and useless; the host names which one.
    assert reasons["curl_cffi"] == "reddit-challenge"
    assert reasons["stealth-browser"] == "reddit-challenge"
    assert "humanity" in ei.value.hint


def test_a_wall_on_the_human_rung_is_one_line_and_still_loud(monkeypatch, capsys):
    """One rung, one line: the wall's own name, and nothing after it.

    The human rung used to say the wall (``human-browser: reddit-private``) and
    then fall into the generic "no text came out" branch, printing
    ``human-browser: empty-extract`` under it. Two lines for one rung read as two
    failures, and the second one is a lie about the page: it was not empty, it was
    refused. Fail loud is unchanged: the error still names the wall and still
    carries Reddit's hint.
    """
    _no_reddit_json(monkeypatch)
    monkeypatch.setattr(
        unlocker, "_fetch_curl_cffi", lambda url, timeout=30: (403, "no", url, {})
    )
    monkeypatch.setattr(
        unlocker, "_fetch_jina", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no jina"))
    )
    monkeypatch.setattr(unlocker, "_fetch_stealth", lambda url, *a, **k: (403, "no", url, {}))
    monkeypatch.setattr(
        unlocker,
        "_fetch_human",
        lambda url, timeout=180: (200, fixture("reddit_private.html"), url),
    )
    with pytest.raises(unlocker.UnlockerError) as ei:
        unlocker.fetch(
            "https://www.reddit.com/r/gryffindor/",
            backends=["curl_cffi", "stealth-browser"],
            allow_human=True,
            progress=True,
            use_memory=False,
        )
    said = [
        line
        for line in capsys.readouterr().err.splitlines()
        if "human-browser:" in line
    ]
    assert len(said) == 1, said
    assert "reddit-private" in said[0], said
    assert "empty-extract" not in said[0], said
    assert dict(ei.value.attempts)["human-browser"] == "reddit-private"
    assert "private" in ei.value.hint


def test_a_community_page_with_no_cards_still_falls_through():
    # F5c's rule: zero or one node falls through so the ladder owns the page.
    assert reddit.extract_page(LISTING, "<html><body>nothing here</body></html>") is None


# ── deeper comments ──────────────────────────────────────────────────────────


def test_a_thread_reads_every_comment_the_page_holds():
    first = page(THREAD, "reddit_thread_first_window.html")
    assert first.failure is None
    assert first.markdown.count(" pts)") == 14
    assert "[truncated:" not in first.markdown
    # The same thread after its "more replies" controls were opened: 31
    # comments in the page, and the rows knob is 300 by default, so all 31 come
    # back. Nothing is cut and no note claims a cap that did not bite.
    opened = page(THREAD, "reddit_thread_expanded.html")
    assert opened.markdown.count(" pts)") == 31
    assert "[truncated:" not in opened.markdown


def test_the_comment_ceiling_is_the_items_knob_and_never_above_it(monkeypatch):
    """F23e: a comment is a row, so ``SEARCHTS_MAX_ITEMS`` is what caps it.

    Both directions matter. A raised ceiling is the read the user asked for, and a
    lowered one is the user saying "fewer rows", which the plain read obeys too.
    There is no second, hidden ceiling under it: a ``--items 250`` that printed
    30 comments said the ceiling was 300 and lied about the other number.
    """
    monkeypatch.setenv("SEARCHTS_MAX_ITEMS", "300")
    assert reddit._row_ceiling() == 300

    monkeypatch.setenv("SEARCHTS_MAX_ITEMS", "12")
    assert reddit._row_ceiling() == 12

    md = page(THREAD, "reddit_thread_expanded.html").markdown
    assert md.count(" pts)") == 12
    assert "[truncated: 19 more comments in the page were cut at the 12-comment cap]" in md
    # And the note the ceiling buys is named on the read, not left to be found.
    kinds = [m["kind"] for m in page(THREAD, "reddit_thread_expanded.html").more]
    assert "count" in kinds


def test_a_broken_items_knob_falls_back_to_the_default_instead_of_failing(monkeypatch):
    monkeypatch.setenv("SEARCHTS_MAX_ITEMS", "not-a-number")
    assert reddit._row_ceiling() == 300


def test_thread_always_says_how_many_comments_reddit_reports():
    for name in ("reddit_thread_first_window.html", "reddit_thread_expanded.html"):
        md = page(THREAD, name).markdown
        assert "[partial: Reddit reports 195 comments;" in md


def test_the_json_ring_row_caps_are_the_knob_and_never_a_literal(monkeypatch):
    """The ``.json`` ring used to slice both renderers at a module literal.

    A post card and a comment are both rows, so one knob answers for them here
    too. Lowering ``SEARCHTS_MAX_ITEMS`` lowers the JSON listing *and* the JSON
    thread at once, and nothing in this file can raise it back.
    """
    posts = [
        {"kind": "t3", "data": {"title": f"post {i}", "author": "a", "score": i,
                                "permalink": f"/r/x/comments/{i}/p/"}}
        for i in range(12)
    ]
    comments = [
        {"kind": "t1", "data": {"body": f"comment body number {i}", "author": "a",
                                "score": i, "permalink": f"/r/x/comments/1/p/{i}/"}}
        for i in range(12)
    ]

    monkeypatch.setenv("SEARCHTS_MAX_ITEMS", "300")
    long_listing = reddit._render_subreddit_from_children(posts)
    long_thread = reddit._render_thread({"title": "t"}, comments)
    assert long_listing.count("- **") == 12
    assert long_thread.count(" pts)") == 12

    monkeypatch.setenv("SEARCHTS_MAX_ITEMS", "4")
    short_listing = reddit._render_subreddit_from_children(posts)
    short_thread = reddit._render_thread({"title": "t"}, comments)
    assert short_listing.count("- **") == 4, "the listing's rows are capped too"
    assert short_thread.count(" pts)") == 4
    assert "comment body number 4" not in short_thread

    # And no literal is left in this file to answer "how many" on its own.
    assert not hasattr(reddit, "_MAX_COMMENTS")


def test_the_click_budget_has_no_default_and_the_rung_without_a_sink_reads_the_knob(
    monkeypatch,
):
    """F23e/F5f: the press budget is ``SEARCHTS_MAX_EXPAND_CLICKS``, always.

    ``expand_more`` takes the budget instead of carrying one, and the rung's
    no-sink path resolves the knob rather than a literal 8 that no user policy
    could lower.
    """
    import inspect

    params = inspect.signature(reddit.expand_more).parameters
    assert params["clicks"].default is inspect.Parameter.empty
    assert params["want"].default is inspect.Parameter.empty

    monkeypatch.setenv("SEARCHTS_MAX_EXPAND_CLICKS", "3")
    assert unlocker._expand_clicks(None) == 3
    assert unlocker._expand_clicks(unlocker._ExpandSink(max_clicks=11)) == 11


def test_a_thread_that_quotes_the_humanity_check_is_not_the_humanity_check():
    """Reddit is full of posts *about* the "Prove your humanity" check.

    Both detectors used to match the bare words anywhere in the first 8 KB, so a
    readable thread whose title or opening comments quote them was refused as a
    captcha: a fail-loud lie in the direction that loses a page that was there.
    The interstitial's own title is the signal, in both places.
    """
    thread = (
        '<shreddit-post post-title="Reddit asks me to prove my humanity" '
        'author="u/op" permalink="/r/MachineLearning/comments/abc/reddit_asks/">'
        "<div slot=\"text-body\"><p>Here is the page again.</p></div></shreddit-post>"
        '<shreddit-comment author="u/c1" score="4">'
        "<div slot=\"comment\"><p>The interstitial says prove your humanity "
        "and then serves nothing.</p></div></shreddit-comment>"
    )
    # The title is the one thing a real page of that thread cannot have, and
    # Reddit's interstitial is the one page that cannot have post cards.
    readable = (
        "<html><head><title>Reddit - Prove your humanity : r/MachineLearning</title>"
        f"</head><body>{thread}</body></html>"
    )
    assert reddit.page_state(THREAD, readable) == "", "a title prefix is not the interstitial"
    assert reddit.extract_page(THREAD, readable).failure is None
    assert looks_blocked(200, readable, {}) is None

    body_only = f"<html><body>{thread}</body></html>"
    assert reddit.page_state(THREAD, body_only) == ""
    assert looks_blocked(200, body_only, {}) is None

    # And the real thing is still caught, by the host and by the shared detector.
    interstitial = fixture("reddit_challenge.html")
    assert reddit.page_state(BATCH, interstitial) == "reddit-challenge"
    assert looks_blocked(200, interstitial, {}) == "challenge"


def test_expand_more_clicks_until_quiet_and_never_raises():
    class Control:
        def __init__(self, log):
            self.log = log

        def scroll_into_view_if_needed(self, timeout=None):
            self.log.append("scroll")

        def click(self, timeout=None, force=None):
            self.log.append("click")
            raise RuntimeError("control went stale")

    class Page:
        """A page that never grows: the stall must stop the loop, not hang."""

        def __init__(self):
            self.log = []
            self.html = "<shreddit-comment author=a><div slot='comment'>hello there friend</div></shreddit-comment>"

        def content(self):
            return self.html

        def query_selector_all(self, selector):
            self.log.append(selector)
            return [Control(self.log)]

        def wait_for_timeout(self, ms):
            self.log.append(f"wait:{ms}")

    p = Page()
    reddit.expand_more(p, 50, clicks=4)
    assert p.log.count("wait:3000") == 1, "a stalled round must stop the walk"
    assert p.log.count("scroll") == 2, "one scroll and one click per control"


def test_expand_more_never_spends_more_than_the_click_budget():
    """The rounds come from the knob, so a lower budget is fewer waits."""
    class Control:
        def scroll_into_view_if_needed(self, timeout=None):
            pass

        def click(self, timeout=None, force=None):
            pass

    class Page:
        """Every round adds a comment, so only the budget can stop it."""

        def __init__(self):
            self.html = ""
            self.waits = 0

        def _grow(self):
            self.html += (
                "<shreddit-comment author=a><div slot='comment'>a comment body "
                f"{self.waits} here</div></shreddit-comment>"
            )

        def content(self):
            return self.html

        def query_selector_all(self, selector):
            self._grow()
            return [Control()]

        def wait_for_timeout(self, ms):
            self.waits += 1

    p = Page()
    reddit.expand_more(p, 999, clicks=3)
    assert p.waits == 3, "the click ceiling is the loop's stop, not a constant"

    tight = Page()
    reddit.expand_more(tight, 999, clicks=1)
    assert tight.waits == 1


def test_expand_more_ticks_each_round_on_the_callers_stderr_budget():
    """P4.6: a loop that waits on the network says so, through the caller."""
    class Control:
        def scroll_into_view_if_needed(self, timeout=None):
            pass

        def click(self, timeout=None, force=None):
            pass

    class Page:
        def __init__(self):
            self.html = ""

        def content(self):
            return self.html

        def query_selector_all(self, selector):
            self.html += (
                "<shreddit-comment author=a><div slot='comment'>another body "
                "here</div></shreddit-comment>"
            )
            return [Control()]

        def wait_for_timeout(self, ms):
            pass

    said: list = []
    reddit.expand_more(Page(), 999, clicks=3, tick=said.append)
    assert len(said) == 3
    assert "more-replies control(s) (round 1 of 3)" in said[0]


def test_expand_more_stops_at_the_count_it_was_asked_for():
    class Control:
        def scroll_into_view_if_needed(self, timeout=None):
            pass

        def click(self, timeout=None, force=None):
            pass

    class Page:
        def __init__(self):
            self.calls = 0

        def content(self):
            body = "".join(
                f"<shreddit-comment author=a><div slot='comment'>comment number {i} here</div>"
                f"</shreddit-comment>"
                for i in range(50)
            )
            return body

        def query_selector_all(self, selector):
            self.calls += 1
            return [Control()]

        def wait_for_timeout(self, ms):
            pass

    p = Page()
    reddit.expand_more(p, 5, clicks=8)
    # 50 comments are already there, so no round is spent clicking.
    assert p.calls == 0


def test_expand_more_on_a_page_that_raises_content_just_stops():
    class Page:
        def content(self):
            raise RuntimeError("page is navigating")

    reddit.expand_more(Page(), 100, clicks=8)  # must not raise


# ── the walls, each named ────────────────────────────────────────────────────


def test_a_notice_this_file_does_not_know_falls_through_instead_of_reading_as_a_page():
    """A wall we have not named yet must not come back as content.

    No page saying "removed by the subreddit moderators" was obtained from this
    box, so there is no state for it. Failing open is the point: an unmodelled
    notice reaches the ladder, which can still call it thin, instead of being
    rendered as if it were the community.
    """
    notice = (
        "<html><body><h1>Page not found</h1><p>Sorry, this post was removed "
        "by the subreddit moderators.</p><nav>Home  Popular  Explore</nav>"
        "</body></html>"
    )
    # A listing and a thread fall through: the ladder still gets to call the page
    # thin, which is the honest answer for a notice we cannot name.
    for url in (THREAD, LISTING):
        assert reddit.extract_page(url, notice) is None, url
        assert reddit.extract_from_html(url, notice) is None, url
    # A batch is only ever reached by following a cursor this ring printed, so
    # one with no cards means the feed ended, and it says so by name.
    batch = reddit.extract_page(BATCH, notice)
    assert batch is not None and batch.failure == "reddit-no-posts" and batch.markdown == ""
    # A profile and a search are cards or a loud failure, and a notice is not a
    # card: they fail by name with no markdown at all.
    for url, state in ((PROFILE, "reddit-profile-empty"), (SEARCH, "reddit-search-empty")):
        page = reddit.extract_page(url, notice)
        assert page is not None and page.failure == state and page.markdown == "", url
        assert reddit.extract_from_html(url, notice) is None, url


@pytest.mark.parametrize(
    "fixture_name,url,state",
    [
        ("reddit_private.html", "https://www.reddit.com/r/gryffindor/", "reddit-private"),
        ("reddit_banned.html", "https://www.reddit.com/r/Random/", "reddit-banned"),
        (
            "reddit_quarantined.html",
            "https://www.reddit.com/r/incest/",
            "reddit-quarantined",
        ),
        (
            "reddit_community_gone.html",
            "https://www.reddit.com/r/nsfw/",
            "reddit-community-not-found",
        ),
        ("reddit_post_gone.html", GONE, "reddit-post-gone"),
        (SEARCH and "reddit_search_nsfw.html", SEARCH_NSFW, "reddit-nsfw-gate"),
    ],
)
def test_a_page_that_is_a_wall_fails_with_its_own_reason(fixture_name, url, state):
    assert reddit.page_state(url, fixture(fixture_name)) == state
    p = reddit.extract_page(url, fixture(fixture_name))
    assert p is not None
    assert p.failure == state
    assert p.markdown == "", "a wall must never hand back chrome as content"
    assert reddit.extract_page(url, fixture(fixture_name)).label == f"reddit: {state}"


def test_a_state_survives_a_hostile_lookalike_inside_the_page():
    """The reason comes from Reddit's own wrapper, not from a word anywhere."""
    noise = (
        '<html><body><div slot="title">r/notprivate is private</div>'
        "<p>1k posts</p>" + "filler text " * 200 + "</body></html>"
    )
    assert reddit.page_state(LISTING, noise) == ""


def test_archived_post_is_named_and_its_comments_still_read():
    p = page(ARCHIVED, "reddit_post_archived.html")
    assert p.failure is None, "an archived post's comments are still real content"
    assert "**Post:** archived by Reddit. Its text is not available." in p.markdown
    assert "[removed: this post is archived on Reddit; its text is not available" in p.markdown
    kinds = [m["kind"] for m in p.more]
    assert "removed" in kinds
    # The comments are real content and are still read.
    assert "**/u/thatguy99911**" in p.markdown


def _op_attrs(html: str) -> set:
    """The OP element's own attribute names (the test's own reader, no private API)."""
    import re

    from searchts.known_hosts.reddit import _attrs_of

    for tag in re.findall(r"<shreddit-post\b[^>]*>", html):
        names = {k.lower() for k, _v in _attrs_of(tag)}
        if "post-title" in names:
            return names
    return set()


def test_a_thread_that_quotes_the_archived_notice_is_not_archived():
    """Reddit serves threads *about* archived posts, and they quote the notice.

    Measured live 2026-10-17 on r/NoStupidQuestions 1x4uke7, fetched on the
    stealth rung and trimmed to ``reddit_post_quoting_archived.html``: a text
    post whose own body says it saw "Archived post. New comments cannot be
    posted" on *another* post. The OP element carries no ``archived``
    attribute. Both detectors matched the bare sentence, so the read opened

        **Post:** archived by Reddit. Its text is not available.

    and printed the text on the next lines. The element that says a post is
    archived is the one carrying ``archived``, so that is the only signal.
    """
    html = fixture("reddit_post_quoting_archived.html")
    assert "archived" not in _op_attrs(html), "the OP here is not archived"
    assert reddit.page_state(QUOTING_ARCHIVED, html) == ""
    p = reddit.extract_page(QUOTING_ARCHIVED, html)
    assert p.failure is None
    assert "archived by Reddit" not in p.markdown
    assert "[removed:" not in p.markdown
    # The post reads as itself: title, body, and the comments Reddit served.
    assert p.markdown.startswith("# Is it possible to read the body text")
    assert "I’m trying to figure out something simple" in p.markdown
    assert p.markdown.count(" pts)") == 4
    # And a post Reddit really did archive still says so, from its own attribute.
    assert "archived" in _op_attrs(fixture("reddit_post_archived.html"))
    assert reddit.page_state(ARCHIVED, fixture("reddit_post_archived.html")) == (
        "reddit-post-archived"
    )


def test_a_notice_quoted_in_a_page_is_not_the_notice():
    """Same rule for the three strings this file still reads as bare text.

    ``subreddit-content-error``, ``shreddit-forbidden`` and "NSFW search results
    are hidden" are each things Reddit's own pages say *about* a wall, so a
    search page can carry them in a result snippet or a thread can quote them.
    The element is what says a wall happened; the words only say somebody
    talked about one. Each real wall still fires, checked on its own fixture.
    """
    prose = (
        '<html><body><shreddit-post post-title="How do I search this" '
        'author="u/op" permalink="/r/x/comments/abc/q/">'
        "<div slot=\"text-body\"><p>When a subreddit is gone Reddit serves "
        '<span class="subreddit-content-error">Sorry, there aren’t any '
        "communities on Reddit with that name.</span> and for a removed post "
        'it serves <span id="shreddit-forbidden">Page not found</span>. Search '
        "for gore and it says NSFW search results are hidden.</p></div>"
        "</shreddit-post></body></html>"
    )
    assert reddit.page_state(THREAD, prose) == "", "prose about a wall is not the wall"
    assert reddit.extract_page(THREAD, prose).failure is None
    # The real walls, still named, from their own pages.
    assert reddit.page_state("https://www.reddit.com/r/nsfw/", fixture("reddit_community_gone.html")) == (
        "reddit-community-not-found"
    )
    assert reddit.page_state(GONE, fixture("reddit_post_gone.html")) == "reddit-post-gone"
    assert reddit.page_state(SEARCH_NSFW, fixture("reddit_search_nsfw.html")) == (
        "reddit-nsfw-gate"
    )


def test_state_note_only_offers_the_browser_where_a_person_can_act():
    assert "--human" in reddit.state_note("reddit-quarantined", LISTING)
    assert "--human" in reddit.state_note("reddit-nsfw-gate", SEARCH_NSFW)
    assert "--human" not in reddit.state_note("reddit-private", LISTING)
    assert reddit.state_note("reddit-banned", LISTING).startswith("Reddit has banned")
    assert reddit.state_note("something-else", LISTING) == ""


# ── profiles and search, as cards ────────────────────────────────────────────


def test_profile_is_a_card_document_with_the_header_fields():
    p = page(PROFILE, "reddit_profile.html")
    assert p.failure is None
    assert p.label == "profile-html: cards"
    head = p.markdown.split("## Posts", 1)[0]
    assert head.splitlines()[0] == "# /u/spez"
    assert "**Karma:** 941,063" in head
    assert "**Contributions:** 4,064" in head
    assert "**Cake day:** 2005-06-06 (21 y ago)" in head
    assert "**Bio:** Reddit CEO" in head
    assert "## Posts (" in p.markdown and "## Comments (" in p.markdown
    assert p.keys, "rows a feed cursor can repeat need an identity"


def test_profile_comment_cards_carry_their_own_text_and_link():
    md = page(PROFILE, "reddit_profile.html").markdown
    comments = md.split("## Comments", 1)[1]
    assert "- **Comment** (2026-08-05 18:31 UTC)" in comments
    assert "[`permalink`](https://www.reddit.com/user/spez/comments/" in comments
    assert "That was the thinking." in comments


def test_profile_batch_mixes_post_cards_and_comment_cards():
    p = page(PROFILE_BATCH, "reddit_profile_batch.html")
    assert p.label.startswith("listing-batch:")
    assert "### Comments" in p.markdown
    assert p.markdown.count("- **") == len(p.keys)


def test_search_is_a_card_list_from_reddits_own_telemetry():
    p = page(SEARCH, "reddit_search.html")
    assert p.failure is None
    assert p.label == "search-html: cards"
    assert p.markdown.startswith("## Results")
    assert (
        "r/browsers · /u/Shoddy_Importance377 · 2026-10-13 14:11 UTC · 29 pts · 46 comments"
        in p.markdown
    )
    assert "[`permalink`](https://www.reddit.com/r/browsers/comments/1x4xppp/" in p.markdown
    assert p.keys == ["t3_1x4xppp", "t3_1x41kxe", "t3_w8zu70"]


def test_search_says_reddit_pages_beyond_this_window():
    kinds = [m["kind"] for m in page(SEARCH, "reddit_search.html").more]
    assert "feed" in kinds


def test_a_profile_or_search_with_no_cards_fails_loud():
    empty = "<html><body><shreddit-app></shreddit-app>" + "nav text " * 200 + "</body></html>"
    p = reddit.extract_page(PROFILE, empty)
    assert p is not None and p.failure == "reddit-profile-empty" and p.markdown == ""
    p = reddit.extract_page(SEARCH, empty)
    assert p is not None and p.failure == "reddit-search-empty" and p.markdown == ""


# ── the ladder ───────────────────────────────────────────────────────────────


def _no_reddit_json(monkeypatch):
    import searchts.known_hosts.reddit as reddit_mod

    monkeypatch.setattr(
        reddit_mod,
        "_fetch",
        lambda u, timeout=30: '{"error": 403, "message": "blocked"}',
    )


def test_fetch_gives_the_cursor_and_the_rows_to_items(monkeypatch):
    _no_reddit_json(monkeypatch)

    def fake_curl(url, timeout=30):
        name = "reddit_feed_cursor.html" if url == LISTING else "reddit_feed_batch.html"
        return 200, fixture(name), url, {}

    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", fake_curl)
    monkeypatch.setattr(
        unlocker, "_fetch_jina", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no jina"))
    )
    monkeypatch.setattr(
        unlocker,
        "_fetch_stealth",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no browser")),
    )
    got = unlocker.read_items(LISTING, 6, use_memory=False)
    assert len(got) == 2, "the first page plus one batch, then it stops"
    assert got[0].next_url and got[0].final_url == LISTING
    assert got[1].final_url == got[0].next_url
    # 3 rows on the first page, 8 on the batch: the caller asked for 6 and the
    # walk stopped once it had them.
    assert sum(len(p.index_keys) for p in got) == 11
    assert [len(p.index_keys) for p in got] == [3, 8]


def test_fetch_fails_loud_on_a_private_community(monkeypatch):
    _no_reddit_json(monkeypatch)
    private = fixture("reddit_private.html")
    monkeypatch.setattr(
        unlocker, "_fetch_curl_cffi", lambda url, timeout=30: (200, private, url, {})
    )
    monkeypatch.setattr(
        unlocker, "_fetch_jina", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no jina"))
    )
    monkeypatch.setattr(
        unlocker, "_fetch_stealth", lambda url, *a, **k: (200, private, url, {})
    )
    with pytest.raises(unlocker.UnlockerError) as ei:
        unlocker.fetch(
            "https://www.reddit.com/r/gryffindor/",
            backends=["curl_cffi", "stealth-browser"],
            use_memory=False,
        )
    reasons = dict(ei.value.attempts)
    assert reasons["curl_cffi"] == "reddit-private"
    assert reasons["stealth-browser"] == "reddit-private"
    assert "private" in ei.value.hint
    assert "--human" not in ei.value.hint


def test_a_quarantine_names_the_browser_as_the_next_step(monkeypatch):
    _no_reddit_json(monkeypatch)
    quarantined = fixture("reddit_quarantined.html")
    monkeypatch.setattr(
        unlocker, "_fetch_stealth", lambda url, *a, **k: (200, quarantined, url, {})
    )
    with pytest.raises(unlocker.UnlockerError) as ei:
        unlocker.fetch(
            "https://www.reddit.com/r/incest/",
            backends=["stealth-browser"],
            use_memory=False,
        )
    assert ei.value.hint.endswith("--human")
    assert "quarantined" in ei.value.hint


def test_the_content_wall_wins_over_the_humanity_check_in_the_hint(monkeypatch):
    """Measured 2026-10-17: curl got the interstitial, the browser the page.

    /r/gryffindor/ answered curl with "Prove your humanity" and the browser rung
    with the real community notice. The hint has to be about the community: the
    interstitial is true of the request and useless about the URL, and it is the
    reason a reader would give up on a page that is simply private.
    """
    _no_reddit_json(monkeypatch)
    private = fixture("reddit_private.html")
    monkeypatch.setattr(
        unlocker, "_fetch_curl_cffi", lambda url, timeout=30: (200, fixture("reddit_challenge.html"), url, {})
    )
    monkeypatch.setattr(
        unlocker, "_fetch_stealth", lambda url, *a, **k: (200, private, url, {})
    )
    with pytest.raises(unlocker.UnlockerError) as ei:
        unlocker.fetch(
            "https://www.reddit.com/r/gryffindor/",
            backends=["curl_cffi", "stealth-browser"],
            use_memory=False,
        )
    assert dict(ei.value.attempts) == {
        "curl_cffi": "reddit-challenge",
        "stealth-browser": "reddit-private",
    }
    assert "this community is private" in ei.value.hint
    assert "humanity" not in ei.value.hint


def test_the_humanity_check_is_still_the_hint_when_it_is_all_there_is(monkeypatch):
    _no_reddit_json(monkeypatch)
    challenge = fixture("reddit_challenge.html")
    monkeypatch.setattr(
        unlocker, "_fetch_curl_cffi", lambda url, timeout=30: (200, challenge, url, {})
    )
    monkeypatch.setattr(
        unlocker, "_fetch_stealth", lambda url, *a, **k: (200, challenge, url, {})
    )
    with pytest.raises(unlocker.UnlockerError) as ei:
        unlocker.fetch(
            BATCH, backends=["curl_cffi", "stealth-browser"], use_memory=False
        )
    assert "humanity" in ei.value.hint


def test_items_counts_new_rows_only_and_says_when_the_feed_repeated_one(monkeypatch):
    """A feed cursor that hands back old rows must not inflate the count.

    The note lands on **page one**: that is the page every caller reads
    (``--json``'s ``text``, the MCP envelope, the CLI's stdout), so a count
    correction anywhere else is a correction nobody sees.
    """
    _no_reddit_json(monkeypatch)
    batch_html = fixture("reddit_feed_batch.html")
    monkeypatch.setattr(
        unlocker,
        "_fetch_curl_cffi",
        lambda url, timeout=30: (
            200,
            fixture("reddit_feed_cursor.html") if url == LISTING else batch_html,
            url,
            {},
        ),
    )
    monkeypatch.setattr(
        unlocker, "_fetch_jina", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no jina"))
    )
    monkeypatch.setattr(
        unlocker,
        "_fetch_stealth",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no browser")),
    )
    got = unlocker.read_items(LISTING, 300, use_memory=False)
    first = got[0].text
    # 3 unique rows from the first page, then the same 8 rows a second time:
    # 11 read, 8 of them already had.
    assert "11 new rows; 8 the feed handed back again" in first
    assert "were not counted twice" in first
    # Asking for 300 and getting 11 is not the list ending, and the read says so:
    # the batch's own cursor pointed back at the batch.
    assert "cursor pointed back at a page this walk had already read" in first


def test_the_cursor_hop_stops_at_the_items_ceiling_and_never_counts_a_row_twice(
    monkeypatch,
):
    """Reddit's own cursor is followed only while the rows asked for are short.

    The ceiling is ``SEARCHTS_MAX_ITEMS``. A walk that has what it asked for
    makes no further request (3 rows, one fetch; 5 rows, one hop), and a feed
    whose cursor repeats a window is never counted twice for it. This is the
    walk's *request* count, not a trim of the last window: a window that
    overshoots the ceiling still comes back whole, which is issue #378 and not
    fixed here.
    """
    _no_reddit_json(monkeypatch)
    listing_html = fixture("reddit_feed_cursor.html")
    batch_html = fixture("reddit_feed_batch.html")
    fetched = []

    def curl(url, timeout=30):
        fetched.append(url)
        return 200, (listing_html if url == LISTING else batch_html), url, {}

    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", curl)
    for dead in ("_fetch_jina", "_fetch_stealth"):
        monkeypatch.setattr(
            unlocker, dead, lambda *a, **k: (_ for _ in ()).throw(RuntimeError("off"))
        )

    # (ceiling, requests the walk may make, rows counted)
    for ceiling, requests, rows in ((3, 1, 3), (5, 2, 11)):
        fetched.clear()
        monkeypatch.setenv("SEARCHTS_MAX_ITEMS", str(ceiling))
        got = unlocker.read_items(LISTING, 300, use_memory=False)
        assert len(fetched) == requests, (ceiling, fetched)
        keys = [k for r in got for k in (r.index_keys or [])]
        assert len(keys) == len(set(keys)), "a row was counted twice"
        assert len(set(keys)) == rows

    # No ceiling short of the feed: the walk follows the cursor until the feed
    # points back at a window it has read; that repeat is named, not counted.
    fetched.clear()
    monkeypatch.setenv("SEARCHTS_MAX_ITEMS", "300")
    got = unlocker.read_items(LISTING, 300, use_memory=False)
    assert len(fetched) == 3
    assert len(set(fetched)) == 3, "a URL was requested twice in one walk"
    assert "8 the feed handed back again were not counted twice" in got[0].text


def test_expand_escalates_to_the_browser_and_raises_the_comment_cap(monkeypatch):
    """``--expand`` gets a read to the rung that has a page, and says what it got.

    Two rungs, two facts. An unasked read stops at curl and the browser is never
    launched, because clicking is not an unasked-for read's job. An asked read
    escalates to the browser (F23d: a window with the folds shut is the failure
    the flag exists to remove), the intent reaches it, and the thread comes back
    with the raised ceiling rather than the 30-comment default.
    """
    _no_reddit_json(monkeypatch)
    seen = {}

    def stealth(url, timeout=60, progress=None, expand=False, **kw):
        seen["expand"] = expand
        return 200, fixture("reddit_thread_expanded.html"), url, {}

    monkeypatch.setattr(
        unlocker, "_fetch_curl_cffi", lambda url, timeout=30: (200, "curl " * 400, url, {})
    )
    monkeypatch.setattr(unlocker, "_fetch_stealth", stealth)

    # Not asked: curl wins, the browser rung never runs, so it gets no keyword.
    quiet = unlocker.fetch(
        THREAD, backends=["curl_cffi", "stealth-browser"], use_memory=False
    )
    assert quiet.backend == "curl_cffi"
    assert "expand" not in seen, "a rung that never ran gets no intent"

    seen.clear()
    res = unlocker.fetch(
        THREAD, backends=["curl_cffi", "stealth-browser"], use_memory=False, expand=True
    )
    assert seen["expand"] is True
    assert res.backend == "stealth-browser"
    # The thread parse ran with the raised cap: no 30-comment truncation note.
    assert res.text.count(" pts)") == 31
    assert "[truncated:" not in res.text


def test_the_known_host_expand_budget_is_the_knob_not_a_constant(monkeypatch):
    """F5f's budgets are ``SEARCHTS_MAX_EXPAND_CLICKS`` / ``_MAX_ITEMS``."""
    _no_reddit_json(monkeypatch)
    asked = []

    def spy(page, want, clicks, tick=None):
        asked.append((want, clicks))
        page.said = "opened"

    monkeypatch.setattr(reddit, "expand_more", spy)
    monkeypatch.setenv("SEARCHTS_MAX_EXPAND_CLICKS", "3")
    monkeypatch.setenv("SEARCHTS_MAX_ITEMS", "77")

    class Page:
        def content(self):
            return "<html><body>hi</body></html>"

    page = Page()
    out = unlocker._expand_known_host(page, THREAD, "<html>a</html>", clicks=3)
    assert asked == [(77, 3)], asked
    assert out == page.content()

    # A host the ring does not know is left alone: no click, no change, no error.
    class Other:
        def content(self):
            return "<html><body>hi</body></html>"

    assert unlocker._expand_known_host(
        Other(), "https://example.test/post", "<html>a</html>", clicks=2
    ) == "<html>a</html>"


def test_the_wider_reddit_gate_presses_nothing_where_there_is_no_control():
    """Asking a Reddit page that has no "more replies" costs nothing.

    The expand now answers to ``is_reddit_url`` (every Reddit host) instead of the
    ``.json`` ring's ``PATTERN``, so the selectors are consulted on a listing, a
    profile and a search too. Only threads carry the control - across every saved
    Reddit fixture the markup appears in the two thread pages and nowhere else -
    and this pins that asking changes nothing a caller can see: no press, no tick,
    the same HTML back.
    """
    asked = []

    class Page:
        def __init__(self, html):
            self.html = html

        def content(self):
            return self.html

        def query_selector_all(self, selector):
            asked.append(selector)
            return []

    ticks = []
    html = fixture("reddit_search.html")
    out = unlocker._expand_known_host(
        Page(html), SEARCH, "<html>a</html>", clicks=3, tick=ticks.append
    )
    assert out == html
    assert asked, "the host's own selectors were never consulted"
    assert ticks == [], ticks


def test_a_reddit_lookalike_gets_neither_the_expand_nor_the_browser_retry():
    """Both host checks answer on the real host, not on a name that starts alike.

    The cursor's ``src`` travels as a ``next_url`` an agent can act on, so
    ``www.reddit.com.evil.test`` is the shape this has to refuse. It gets no
    "more replies" press, and a walled-off hop on it is not worth a browser
    launch.
    """
    class Never:
        def content(self):
            raise AssertionError("a lookalike host was asked for its content")

        def query_selector_all(self, _selector):
            raise AssertionError("a lookalike host was asked for its controls")

    for url in (
        "https://www.reddit.com.evil.test/r/MachineLearning/hot/",
        "https://notreddit.com/r/MachineLearning/hot/",
        "https://reddit.com.evil.test/svc/shreddit/community-more-posts/hot/?after=x",
        "https://evil.test/svc/shreddit/community-more-posts/hot/?after=x",
    ):
        assert not reddit.is_reddit_url(url), url
        assert not reddit.hop_needs_browser(
            url, [("curl_cffi", "reddit-challenge")]
        ), url
        assert unlocker._expand_known_host(
            Never(), url, "<html>a</html>", clicks=2
        ) == "<html>a</html>", url
        assert (
            unlocker._retry_hop_on_browser(
                url, unlocker.UnlockerError(url, [("curl_cffi", "challenge")]), {}
            )
            is None
        ), url


def test_the_ring_declares_no_hook_beyond_pattern_and_extract_known():
    """N4: the ring is a ring, not a plugin framework (the hooks are gone).

    A per-module ``HOSTS`` + ``hop_needs_browser`` / ``expand_more`` pair read by
    ``getattr`` was a second, optional protocol inside the one place that already
    promised a single contract. The ladder now imports the host file it needs the
    way it already did for :func:`unlocker._host_wall_reason`, so this pins that
    nothing crept back in.
    """
    import searchts.known_hosts as ring

    for gone in ("needs_browser_hop", "expand_page"):
        assert not hasattr(ring, gone), f"the ring grew {gone} again"
    for banned in ("HOSTS", "hop_needs_browser", "expand_more"):
        assert not hasattr(ring, banned), f"the ring advertises {banned} again"


def test_the_hop_retry_is_asked_of_reddit_itself_not_the_ring(monkeypatch):
    """A walled-off cursor hop is offered to the browser by the host's own answer."""
    asked = []
    monkeypatch.setattr(
        reddit, "hop_needs_browser", lambda url, reasons: asked.append(url) or True
    )
    calls = []
    monkeypatch.setattr(
        unlocker, "fetch", lambda url, **kw: calls.append((url, kw)) or "fetched"
    )
    err = unlocker.UnlockerError(BATCH, [("curl_cffi", "challenge")])

    assert unlocker._retry_hop_on_browser(BATCH, err, {"timeout": 30}) == "fetched"
    assert asked == [BATCH]
    assert calls[0][1]["backends"] == ["stealth-browser"]
    assert calls[0][1]["allow_human"] is False

    # A host that is not Reddit is never retried, whatever it said.
    asked.clear()
    calls.clear()
    assert unlocker._retry_hop_on_browser(
        "https://example.test/next", err, {"timeout": 30}
    ) is None
    assert asked == [] and calls == []


def test_no_expand_means_the_browser_rung_is_called_exactly_as_before(monkeypatch):
    """A read that did not ask for more must not hand the rung a new keyword."""
    _no_reddit_json(monkeypatch)
    seen = {}

    def stealth(url, **kw):
        seen.update(kw)
        return 200, "page " * 400, url, {}

    monkeypatch.setattr(unlocker, "_fetch_stealth", stealth)
    unlocker.fetch("https://site.test/plain", backends=["stealth-browser"], use_memory=False)
    assert "expand" not in seen
    assert "proxy" not in seen


@pytest.mark.parametrize(
    "fixture_name",
    ["reddit_challenge.html", "reddit_community_gone.html", "reddit_private.html"],
)
@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/r/foo/",
        "https://www.reddit.com.evil.test/r/foo/",
        "https://notreddit.com/svc/shreddit/community-more-posts/hot/?after=x",
    ],
)
def test_reddit_walls_are_never_named_on_a_host_that_is_not_reddit(fixture_name, url):
    """Generic-first: an unknown host never gets a Reddit reason.

    The ladder hands every URL's HTML to ``extract_page``, so a page on any
    other site that happens to carry Reddit's interstitial title, its community
    error element or its guard modal (a mirror, an archive, an article quoting
    the markup) must fall through to the generic path untouched.
    """
    assert reddit.extract_page(url, fixture(fixture_name)) is None
