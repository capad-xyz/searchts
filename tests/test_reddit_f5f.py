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
``reddit_profile``          /user/spez/ as served: header fields plus cards.
``reddit_profile_batch``    that profile's cursor: posts and comments mixed.
``reddit_search``           /search/?q=searchts as served: result cards.
``reddit_search_nsfw``      /search/?q=gore: the over-18 banner.
``reddit_private``          /r/gryffindor/  ``reddit_banned``  /r/Random/
``reddit_quarantined``      /r/incest/      ``reddit_community_gone`` /r/nsfw/
``reddit_post_gone``        a comment URL for a post that is not there.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from searchts import unlocker
from searchts.known_hosts import reddit

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


def page(url: str, name: str, expand: int = 0):
    return reddit.extract_page(url, fixture(name), expand=expand)


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


def test_a_community_page_with_no_cards_still_falls_through():
    # F5c's rule: zero or one node falls through so the ladder owns the page.
    assert reddit.extract_page(LISTING, "<html><body>nothing here</body></html>") is None


# ── deeper comments ──────────────────────────────────────────────────────────


def test_thread_default_cap_and_the_expand_cap():
    first = page(THREAD, "reddit_thread_first_window.html")
    assert first.failure is None
    assert first.markdown.count(" pts)") == 14
    assert "[truncated:" not in first.markdown
    # The same thread after its "more replies" controls were opened: 31
    # comments, so the default 30-comment cap cuts one and says so.
    default = page(THREAD, "reddit_thread_expanded.html")
    assert default.markdown.count(" pts)") == 30
    assert "[truncated: 1 more comments in the page were cut at the 30-comment cap]" in default.markdown
    # Asking for more raises the cap, so the 31st comment is there.
    expanded = page(THREAD, "reddit_thread_expanded.html", expand=200)
    assert expanded.markdown.count(" pts)") == 31
    assert "[truncated:" not in expanded.markdown


def test_expand_asks_for_more_comments_than_the_cap_allows_and_says_so():
    p = page(THREAD, "reddit_thread_expanded.html", expand=5000)
    notes = "\n".join(m["note"] for m in p.more)
    assert "[items: asked to expand to 5000 comments, the ceiling is 200]" in notes
    assert p.markdown.count(" pts)") == 31


def test_thread_always_says_how_many_comments_reddit_reports():
    for name in ("reddit_thread_first_window.html", "reddit_thread_expanded.html"):
        md = page(THREAD, name, expand=200).markdown
        assert "[partial: Reddit reports 195 comments;" in md


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
    reddit.expand_more(p, 50)
    assert p.log.count("wait:3000") == 1, "a stalled round must stop the walk"
    assert p.log.count("scroll") == 2, "one scroll and one click per control"


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
    reddit.expand_more(p, 5)
    # 50 comments are already there, so no round is spent clicking.
    assert p.calls == 0


def test_expand_more_on_a_page_that_raises_content_just_stops():
    class Page:
        def content(self):
            raise RuntimeError("page is navigating")

    reddit.expand_more(Page(), 100)  # must not raise


# ── the walls, each named ────────────────────────────────────────────────────


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


def test_items_counts_new_rows_only_and_says_when_the_feed_repeated_one(monkeypatch):
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
    last = got[-1].text
    assert "were not counted twice" in last
    # 3 unique rows from the first page, then the same 8 rows a second time:
    # 11 read, 8 of them already had.
    assert "11 new rows; 8 the feed handed back again" in last


def test_expand_reaches_only_the_browser_rung(monkeypatch):
    """The intent reaches the rung that has a page, and raises the comment cap.

    curl answers this URL on a machine Reddit does not challenge, so the read
    stops there and nothing is expanded. That is the fence working: the flag is
    an intent the browser honours, not a reason to skip ahead to it.
    """
    _no_reddit_json(monkeypatch)
    seen = {}

    def stealth(url, timeout=60, progress=None, expand=0, **kw):
        seen["expand"] = expand
        return 200, fixture("reddit_thread_expanded.html"), url, {}

    monkeypatch.setattr(
        unlocker, "_fetch_curl_cffi", lambda url, timeout=30: (200, "curl " * 400, url, {})
    )
    monkeypatch.setattr(unlocker, "_fetch_stealth", stealth)
    res = unlocker.fetch(
        THREAD, backends=["curl_cffi", "stealth-browser"], use_memory=False, expand=120
    )
    assert res.backend == "curl_cffi"
    assert "expand" not in seen, "a rung that never ran gets no intent"

    # Now make curl unable to read the page, so the browser rung carries it.
    monkeypatch.setattr(
        unlocker, "_fetch_curl_cffi", lambda url, timeout=30: (403, "nope", url, {})
    )
    seen.clear()
    res = unlocker.fetch(
        THREAD, backends=["curl_cffi", "stealth-browser"], use_memory=False, expand=120
    )
    assert seen["expand"] == 120
    assert res.backend == "stealth-browser"
    # The thread parse ran with the raised cap: no 30-comment truncation note.
    assert res.text.count(" pts)") == 31
    assert "[truncated:" not in res.text


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
