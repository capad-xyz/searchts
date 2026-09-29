# -*- coding: utf-8 -*-
"""Tests for the Reddit known-host extractor (no network).

Mirrors the structure of ``test_share_extractors.py``: URL matching tests,
fixture-driven parse tests, fail-open tests, and unlocker wiring tests.
"""

import json
from pathlib import Path

from conftest import Tripwire

from searchts import unlocker
from searchts.known_hosts import (
    KnownResult,
    extract,
    matches,
    reddit,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ── URL matching ─────────────────────────────────────────────────────────────


def test_matches_thread_www():
    assert matches(
        "https://www.reddit.com/r/python/comments/abc123/how_list_comps_work/.json"
    )


def test_matches_thread_old():
    assert matches(
        "https://old.reddit.com/r/python/comments/abc123/how_list_comps_work/.json"
    )


def test_matches_subreddit_listing_www():
    assert matches("https://www.reddit.com/r/python/.json")


def test_matches_subreddit_listing_old():
    assert matches("https://old.reddit.com/r/python/.json")


def test_matches_user_about():
    assert matches("https://www.reddit.com/user/spez/.json")


def test_matches_with_query_string():
    """?raw_json=1 or other params should not prevent matching."""
    assert matches(
        "https://www.reddit.com/r/python/comments/abc123/some_title/.json?raw_json=1"
    )


def test_matches_html_listing_and_thread():
    assert matches("https://www.reddit.com/r/python/")
    assert matches("https://www.reddit.com/r/python")
    assert matches("https://old.reddit.com/r/python/hot/")
    assert matches("https://reddit.com/r/python/new")
    assert matches("https://www.reddit.com/r/python/top/")
    assert matches("https://www.reddit.com/r/python/rising/")
    assert matches("https://www.reddit.com/r/python/comments/abc123/some_title/")
    assert matches("https://old.reddit.com/r/python/comments/abc123/")
    assert matches("https://reddit.com/user/spez/")


def test_matches_json_without_slash_before_ext():
    assert matches("https://www.reddit.com/r/python.json")
    assert matches("https://www.reddit.com/r/python/hot.json")
    assert matches("https://www.reddit.com/r/python/comments/abc123.json")
    assert matches("https://www.reddit.com/r/python/comments/abc123/title.json")


def test_matches_rejects_other_domains():
    assert not matches("https://example.com/.json")
    assert not matches("https://www.nytimes.com/r/python/.json")
    assert not matches("https://example.com/r/python/hot/")


def test_matches_rejects_non_listing_reddit_paths():
    assert not matches("https://www.reddit.com/login")
    assert not matches("https://www.reddit.com/r/python/wiki/")
    assert not matches("https://www.reddit.com/r/python/about/")


def test_pattern_subreddit_capture_set_on_thread_url():
    """The named group `subreddit` must be set on /r/<sub>/... URLs."""
    m = reddit.PATTERN.match(
        "https://www.reddit.com/r/python/comments/abc123/title/.json"
    )
    assert m is not None
    assert m.group("subreddit") == "python"
    assert m.group("user") is None


def test_pattern_user_capture_set_on_user_url():
    m = reddit.PATTERN.match("https://old.reddit.com/user/spez/.json")
    assert m is not None
    assert m.group("user") == "spez"
    assert m.group("subreddit") is None


# _fetch appends ?raw_json=1 before calling curl_cffi. That's an
# implementation detail of the extractor, not a ring-level contract, and
# testing it without actually importing curl_cffi.requests is not worth
# the extra fixture. Covered by the real _fetch implementation.


# ── Parse helpers ────────────────────────────────────────────────────────────


def _load(name: str):
    raw = (FIXTURES / name).read_text(encoding="utf-8")
    return json.loads(raw)


# ── Thread rendering ─────────────────────────────────────────────────────────


def test_extract_thread_returns_known_result():
    url = "https://www.reddit.com/r/python/comments/abc123/how_list_comps_work/.json"
    fixture = _load("reddit_thread.json")
    raw = json.dumps(fixture)

    # Monkeypatch _fetch to return the fixture without touching the network.
    import searchts.known_hosts.reddit as reddit_mod
    original = reddit_mod._fetch
    reddit_mod._fetch = lambda u: raw

    try:
        res = extract(url)
    finally:
        reddit_mod._fetch = original

    assert isinstance(res, KnownResult)
    assert res.provider == "reddit"
    assert res.title == "How do list comprehensions work in Python?"


def test_thread_markdown_contains_title():
    url = "https://www.reddit.com/r/python/comments/abc123/how_list_comps_work/.json"
    fixture = _load("reddit_thread.json")
    raw = json.dumps(fixture)

    import searchts.known_hosts.reddit as reddit_mod
    original = reddit_mod._fetch
    reddit_mod._fetch = lambda u: raw

    try:
        res = extract(url)
    finally:
        reddit_mod._fetch = original

    assert "How do list comprehensions work in Python?" in res.markdown


def test_thread_markdown_contains_op_author():
    url = "https://www.reddit.com/r/python/comments/abc123/how_list_comps_work/.json"
    fixture = _load("reddit_thread.json")
    raw = json.dumps(fixture)

    import searchts.known_hosts.reddit as reddit_mod
    original = reddit_mod._fetch
    reddit_mod._fetch = lambda u: raw

    try:
        res = extract(url)
    finally:
        reddit_mod._fetch = original

    assert "/u/example_user" in res.markdown


def test_thread_markdown_contains_comment_authors():
    url = "https://www.reddit.com/r/python/comments/abc123/how_list_comps_work/.json"
    fixture = _load("reddit_thread.json")
    raw = json.dumps(fixture)

    import searchts.known_hosts.reddit as reddit_mod
    original = reddit_mod._fetch
    reddit_mod._fetch = lambda u: raw

    try:
        res = extract(url)
    finally:
        reddit_mod._fetch = original

    assert "/u/helpful_reply" in res.markdown
    assert "/u/another_coder" in res.markdown


def test_thread_markdown_contains_scores():
    url = "https://www.reddit.com/r/python/comments/abc123/how_list_comps_work/.json"
    fixture = _load("reddit_thread.json")
    raw = json.dumps(fixture)

    import searchts.known_hosts.reddit as reddit_mod
    original = reddit_mod._fetch
    reddit_mod._fetch = lambda u: raw

    try:
        res = extract(url)
    finally:
        reddit_mod._fetch = original

    assert "15 pts" in res.markdown
    assert "8 pts" in res.markdown


def test_thread_markdown_contains_permalink():
    url = "https://www.reddit.com/r/python/comments/abc123/how_list_comps_work/.json"
    fixture = _load("reddit_thread.json")
    raw = json.dumps(fixture)

    import searchts.known_hosts.reddit as reddit_mod
    original = reddit_mod._fetch
    reddit_mod._fetch = lambda u: raw

    try:
        res = extract(url)
    finally:
        reddit_mod._fetch = original

    assert "https://www.reddit.com/r/python/comments/abc123/" in res.markdown


def test_thread_markdown_preserves_code_blocks():
    """Code fences in a comment body must survive rendering."""
    url = "https://www.reddit.com/r/python/comments/abc123/how_list_comps_work/.json"
    fixture = _load("reddit_thread.json")
    raw = json.dumps(fixture)

    import searchts.known_hosts.reddit as reddit_mod
    original = reddit_mod._fetch
    reddit_mod._fetch = lambda u: raw

    try:
        res = extract(url)
    finally:
        reddit_mod._fetch = original

    assert "```python" in res.markdown
    assert "x*2" in res.markdown
    assert "result = [x*2 for x in range(5)]" in res.markdown


# ── Subreddit listing rendering ────────────────────────────────────────────────


def test_extract_subreddit_listing():
    url = "https://www.reddit.com/r/python/.json"
    fixture = _load("reddit_listing.json")
    raw = json.dumps(fixture)

    import searchts.known_hosts.reddit as reddit_mod
    original = reddit_mod._fetch
    reddit_mod._fetch = lambda u: raw

    try:
        res = extract(url)
    finally:
        reddit_mod._fetch = original

    assert isinstance(res, KnownResult)
    assert res.provider == "reddit"
    assert res.title == "r/python"
    assert "How do list comprehensions work in Python?" in res.markdown
    assert "/u/example_user" in res.markdown


# ── User about rendering ───────────────────────────────────────────────────────


def test_extract_user():
    url = "https://www.reddit.com/user/spez/.json"
    fixture = _load("reddit_user.json")
    raw = json.dumps(fixture)

    import searchts.known_hosts.reddit as reddit_mod
    original = reddit_mod._fetch
    reddit_mod._fetch = lambda u: raw

    try:
        res = extract(url)
    finally:
        reddit_mod._fetch = original

    assert isinstance(res, KnownResult)
    assert res.provider == "reddit"
    assert res.title == "/u/spez"
    assert "/u/spez" in res.markdown


# ── Fail-open tests ──────────────────────────────────────────────────────────


def test_extract_returns_none_on_403_block_interstitial():
    """A 403 JSON interstitial → ladder runs, not a parse error."""
    url = "https://www.reddit.com/r/python/comments/abc123/title/.json"
    block_json = json.dumps({"error": 403, "message": "blocked"})

    import searchts.known_hosts.reddit as reddit_mod
    original = reddit_mod._fetch
    reddit_mod._fetch = lambda u: block_json

    try:
        res = extract(url)
    finally:
        reddit_mod._fetch = original

    assert res is None


def test_extract_returns_none_on_malformed_json():
    """A non-JSON body → ladder runs, not a parse error."""
    url = "https://www.reddit.com/r/python/comments/abc123/title/.json"
    html = "<html><body>blocked</body></html>"

    import searchts.known_hosts.reddit as reddit_mod
    original = reddit_mod._fetch
    reddit_mod._fetch = lambda u: html

    try:
        res = extract(url)
    finally:
        reddit_mod._fetch = original

    assert res is None


def test_extract_returns_none_on_empty_body():
    """An empty response → ladder runs."""
    url = "https://www.reddit.com/r/python/comments/abc123/title/.json"

    import searchts.known_hosts.reddit as reddit_mod
    original = reddit_mod._fetch
    reddit_mod._fetch = lambda u: ""

    try:
        res = extract(url)
    finally:
        reddit_mod._fetch = original

    assert res is None


def test_extract_returns_none_on_wrong_json_structure():
    """A valid but structurally unexpected JSON → ladder runs."""
    url = "https://www.reddit.com/r/python/comments/abc123/title/.json"
    # Valid JSON but not a listing: a bare string.
    weird = json.dumps("just a string")

    import searchts.known_hosts.reddit as reddit_mod
    original = reddit_mod._fetch
    reddit_mod._fetch = lambda u: weird

    try:
        res = extract(url)
    finally:
        reddit_mod._fetch = original

    assert res is None


def test_extract_never_raises():
    """extract() must never raise — contract for the unlocker ring."""
    import searchts.known_hosts.reddit as reddit_mod
    original = reddit_mod._fetch
    # Make _fetch raise to exercise the exception guard.
    reddit_mod._fetch = lambda u: (_ for _ in ()).throw(RuntimeError("simulated network error"))

    try:
        res = extract("https://www.reddit.com/r/python/comments/abc123/title/.json")
    finally:
        reddit_mod._fetch = original

    assert res is None


# ── unlocker.fetch wiring tests ───────────────────────────────────────────────


def test_fetch_uses_known_host_ring_for_json_url(monkeypatch):
    """A Reddit .json URL hits the ring; ladder backends must NOT be called."""
    # Simulate a real Reddit thread response.
    fixture = _load("reddit_thread.json")
    raw = json.dumps(fixture)

    def fake_fetch(url, timeout=30):
        # The real reddit._fetch appends ?raw_json=1 before this stub is
        # called — but here we're replacing _fetch entirely, so the URL
        # arrives unmodified. Just return the canned JSON.
        return raw

    import searchts.known_hosts.reddit as reddit_mod
    monkeypatch.setattr(reddit_mod, "_fetch", fake_fetch)

    def boom(*a, **k):
        raise Tripwire("curl_cffi called despite known-host ring hit")

    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", boom)
    monkeypatch.setattr(unlocker, "_fetch_jina", boom)
    monkeypatch.setattr(unlocker, "_fetch_stealth", boom)

    res = unlocker.fetch(
        "https://www.reddit.com/r/python/comments/abc123/title/.json",
        use_memory=False,
    )
    assert res.backend == "known-host:reddit"
    assert "list comprehensions" in res.text.lower()


def test_fetch_html_listing_hits_ring(monkeypatch):
    """Caller passes a page (not an API URL). Ring rewrites to .json."""
    fixture = _load("reddit_listing.json")
    raw = json.dumps(fixture)
    seen = []

    def fake_fetch(url, timeout=30):
        seen.append(url)
        return raw

    import searchts.known_hosts.reddit as reddit_mod
    monkeypatch.setattr(reddit_mod, "_fetch", fake_fetch)

    def boom(*a, **k):
        raise Tripwire("ladder called despite HTML listing ring hit")

    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", boom)
    monkeypatch.setattr(unlocker, "_fetch_jina", boom)
    monkeypatch.setattr(unlocker, "_fetch_stealth", boom)

    res = unlocker.fetch(
        "https://www.reddit.com/r/python/hot/",
        use_memory=False,
    )
    assert res.backend == "known-host:reddit"
    assert seen
    assert seen[0].endswith("hot.json") or "hot.json" in seen[0]
    assert "list comprehensions" in res.text.lower()


def test_fetch_html_thread_hits_ring(monkeypatch):
    fixture = _load("reddit_thread.json")
    raw = json.dumps(fixture)

    import searchts.known_hosts.reddit as reddit_mod
    monkeypatch.setattr(reddit_mod, "_fetch", lambda u, timeout=30: raw)

    def boom(*a, **k):
        raise Tripwire("ladder called despite HTML thread ring hit")

    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", boom)
    monkeypatch.setattr(unlocker, "_fetch_jina", boom)
    monkeypatch.setattr(unlocker, "_fetch_stealth", boom)

    res = unlocker.fetch(
        "https://old.reddit.com/r/python/comments/abc123/how_list_comps_work/",
        use_memory=False,
    )
    assert res.backend == "known-host:reddit"
    assert "list comprehensions" in res.text.lower()


def test_to_json_url_listing_and_thread():
    assert reddit._to_json_url("https://www.reddit.com/r/foo/hot/") == (
        "https://www.reddit.com/r/foo/hot.json"
    )
    assert reddit._to_json_url(
        "https://reddit.com/r/foo/comments/abc/slug/"
    ) == "https://reddit.com/r/foo/comments/abc/slug.json"
    assert reddit._to_json_url("https://www.reddit.com/r/foo.json").endswith(
        "/r/foo.json"
    )


def test_fetch_skips_ring_for_unknown_url(monkeypatch):
    """A non-Reddit URL must not trigger the known-host ring."""
    ring_calls = []

    import searchts.known_hosts.reddit as reddit_mod
    original = reddit_mod._fetch
    reddit_mod._fetch = lambda u: ring_calls.append(u) or ""

    def fake_curl(url, timeout=30):
        return 200, "<html><body>" + "page content " * 100 + "</body></html>", url, {}

    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", fake_curl)
    monkeypatch.setattr(unlocker, "_fetch_jina", lambda url, **k: (_ for _ in ()).throw(Tripwire("jina called")))
    monkeypatch.setattr(unlocker, "_fetch_stealth", lambda url, **k: (_ for _ in ()).throw(Tripwire("stealth called")))

    try:
        unlocker.fetch("https://example.com/page", backends=["curl_cffi"], use_memory=False)
    finally:
        reddit_mod._fetch = original

    assert ring_calls == [], "known-host ring must not be triggered for example.com"


def test_fetch_ring_returns_none_falls_through_to_ladder(monkeypatch):
    """Ring match but extract() returns None → ladder runs."""
    import searchts.known_hosts.reddit as reddit_mod
    # Interstitial → extract returns None
    reddit_mod._fetch = lambda u: json.dumps({"error": 403, "message": "blocked"})

    calls = []

    def spy_curl(url, timeout=30):
        calls.append("curl_cffi")
        return 200, "<html><body>" + "page content " * 100 + "</body></html>", url, {}

    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", spy_curl)
    monkeypatch.setattr(unlocker, "_fetch_jina", lambda url, **k: (_ for _ in ()).throw(Tripwire("jina called")))
    monkeypatch.setattr(unlocker, "_fetch_stealth", lambda url, **k: (_ for _ in ()).throw(Tripwire("stealth called")))

    res = unlocker.fetch(
        "https://www.reddit.com/r/python/comments/abc123/title/.json",
        backends=["curl_cffi"],
        use_memory=False,
    )
    assert calls == ["curl_cffi"]
    assert "page content" in res.text


def test_known_host_hit_ticks_stderr(monkeypatch, capsys):
    fixture = _load("reddit_thread.json")
    raw = json.dumps(fixture)
    import searchts.known_hosts.reddit as reddit_mod
    monkeypatch.setattr(reddit_mod, "_fetch", lambda u, timeout=30: raw)
    monkeypatch.setattr(
        unlocker,
        "_fetch_curl_cffi",
        lambda *a, **k: (_ for _ in ()).throw(Tripwire("ladder")),
    )
    monkeypatch.setattr(
        unlocker,
        "_fetch_jina",
        lambda *a, **k: (_ for _ in ()).throw(Tripwire("ladder")),
    )
    monkeypatch.setattr(
        unlocker,
        "_fetch_stealth",
        lambda *a, **k: (_ for _ in ()).throw(Tripwire("ladder")),
    )
    unlocker.fetch(
        "https://www.reddit.com/r/python/comments/abc123/title/.json",
        use_memory=False,
        progress=True,
    )
    captured = capsys.readouterr()
    assert "trying known-host:reddit" in captured.err
    assert "known-host:reddit: ok" in captured.err
    assert captured.out == ""


def test_known_host_miss_ticks_then_ladder(monkeypatch, capsys):
    import searchts.known_hosts.reddit as reddit_mod
    monkeypatch.setattr(
        reddit_mod,
        "_fetch",
        lambda u, timeout=30: json.dumps({"error": 403, "message": "blocked"}),
    )

    def spy_curl(url, timeout=30):
        return 200, "<html><body>" + "page content " * 100 + "</body></html>", url, {}

    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", spy_curl)
    monkeypatch.setattr(
        unlocker,
        "_fetch_jina",
        lambda *a, **k: (_ for _ in ()).throw(Tripwire("jina")),
    )
    monkeypatch.setattr(
        unlocker,
        "_fetch_stealth",
        lambda *a, **k: (_ for _ in ()).throw(Tripwire("stealth")),
    )
    unlocker.fetch(
        "https://www.reddit.com/r/python/hot/",
        backends=["curl_cffi"],
        use_memory=False,
        progress=True,
    )
    captured = capsys.readouterr()
    assert "trying known-host:reddit" in captured.err
    assert "known-host:reddit: miss" in captured.err
    assert "trying curl_cffi" in captured.err
    assert captured.out == ""


def test_known_host_progress_false_is_quiet(monkeypatch, capsys):
    fixture = _load("reddit_thread.json")
    raw = json.dumps(fixture)
    import searchts.known_hosts.reddit as reddit_mod
    monkeypatch.setattr(reddit_mod, "_fetch", lambda u, timeout=30: raw)
    monkeypatch.setattr(
        unlocker,
        "_fetch_curl_cffi",
        lambda *a, **k: (_ for _ in ()).throw(Tripwire("ladder")),
    )
    monkeypatch.setattr(
        unlocker,
        "_fetch_jina",
        lambda *a, **k: (_ for _ in ()).throw(Tripwire("ladder")),
    )
    monkeypatch.setattr(
        unlocker,
        "_fetch_stealth",
        lambda *a, **k: (_ for _ in ()).throw(Tripwire("ladder")),
    )
    unlocker.fetch(
        "https://www.reddit.com/r/python/comments/abc123/title/.json",
        use_memory=False,
        progress=False,
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""


# ── F5c: shreddit-post HTML listing short-circuit (no network) ────────────────

_REDDIT_LISTING_HTML_3 = """
<html>
<body>
<shreddit-post post-title="First post title" permalink="/r/python/comments/abc/first/" comment-count="3"></shreddit-post>
<shreddit-post post-title="Second post title" content-href="/r/python/comments/def/second/"></shreddit-post>
<shreddit-post post-title="Third post title" permalink="/r/python/comments/ghi/third/" comment-count="12"></shreddit-post>
</body>
</html>
"""

_REDDIT_LISTING_HTML_1 = """
<html>
<body>
<shreddit-post post-title="Only one" permalink="/r/python/comments/only/one/"></shreddit-post>
</body>
</html>
"""

_REDDIT_THREAD_HTML_MANY = """
<html>
<body>
<shreddit-post post-title="Thread reply one" permalink="/r/python/comments/abc/first/reply"></shreddit-post>
<shreddit-post post-title="Thread reply two" permalink="/r/python/comments/abc/second/reply"></shreddit-post>
</body>
</html>
"""


_REDDIT_LISTING_HTML_WITH_BODY = """
<html>
<body>
<shreddit-post post-title="CoWindow paper" permalink="/r/python/comments/aaa/cowindow/" comment-count="0">
  <a slot="title">CoWindow paper</a>
  <div slot="text-body">I am one of the authors of two recent papers exploring different sources of redundant computation in attention. CoWindow Attention distributes distant context across KV heads.</div>
  <button>Share</button>
</shreddit-post>
<shreddit-post post-title="Link only card" permalink="/r/python/comments/bbb/link/">
  <a slot="title">Link only card</a>
</shreddit-post>
<shreddit-post post-title="Long body post" permalink="/r/python/comments/ccc/long/" comment-count="5">
  <div slot="text-body">%s</div>
</shreddit-post>
</body>
</html>
""" % ("word " * 80)


def test_parse_reddit_listing_html_three_posts():
    import searchts.known_hosts.reddit as reddit_mod
    md = reddit_mod.parse_reddit_listing_html(_REDDIT_LISTING_HTML_3, "https://www.reddit.com/r/python/hot/")
    assert md is not None
    assert "First post title" in md
    assert "Second post title" in md
    assert "Third post title" in md
    assert "https://www.reddit.com/r/python/comments/abc/first/" in md
    assert "https://www.reddit.com/r/python/comments/def/second/" in md
    assert "https://www.reddit.com/r/python/comments/ghi/third/" in md
    assert "(3 comments)" in md
    assert "(12 comments)" in md


def test_parse_reddit_listing_html_includes_card_snippet():
    import searchts.known_hosts.reddit as reddit_mod
    md = reddit_mod.parse_reddit_listing_html(
        _REDDIT_LISTING_HTML_WITH_BODY,
        "https://www.reddit.com/r/python/hot/",
    )
    assert md is not None
    assert "CoWindow paper" in md
    assert "I am one of the authors of two recent papers" in md
    # Title is not repeated as the snippet.
    cowindow_block = md.split("Link only card")[0]
    assert cowindow_block.count("CoWindow paper") == 1
    # Link-only card has no snippet line between title and permalink.
    link_block = md.split("Link only card", 1)[1].split("Long body post", 1)[0]
    assert "I am one of the authors" not in link_block
    assert "[`permalink`]" in link_block
    # Card body is the full slot text, not a 280-character cut.
    assert "word " * 40 in md
    assert "..." not in md.split("Long body post", 1)[1]


def test_parse_reddit_listing_html_one_post_returns_none():
    import searchts.known_hosts.reddit as reddit_mod
    md = reddit_mod.parse_reddit_listing_html(_REDDIT_LISTING_HTML_1, "https://www.reddit.com/r/python/")
    assert md is None


def test_parse_reddit_listing_html_comments_url_does_not_trigger(monkeypatch):
    """A /comments/ page with many shreddit-post must not produce listing MD."""
    import searchts.known_hosts.reddit as reddit_mod
    # Even with many posts, thread URL must return None for parse
    md = reddit_mod.parse_reddit_listing_html(_REDDIT_THREAD_HTML_MANY, "https://www.reddit.com/r/python/comments/abc/title/")
    assert md is None
    # And is_reddit_listing_url must be false
    assert not reddit_mod.is_reddit_listing_url("https://www.reddit.com/r/python/comments/abc/title/")


_REDDIT_THREAD_HTML = """
<html>
<body>
<shreddit-post post-title="CoWindow paper" author="alice" score="2" comment-count="3" permalink="/r/python/comments/abc/cowindow/">
  <div slot="text-body">I am one of the authors of two recent papers exploring attention.</div>
</shreddit-post>
<shreddit-comment author="bob" score="1">This is a useful comment about the paper here.</shreddit-comment>
</body>
</html>
"""


def test_parse_reddit_thread_html_op_score_body_and_comment():
    import searchts.known_hosts.reddit as reddit_mod
    md = reddit_mod.parse_reddit_thread_html(
        _REDDIT_THREAD_HTML,
        "https://www.reddit.com/r/python/comments/abc/cowindow/",
    )
    assert md is not None
    assert md.startswith("# CoWindow paper")
    assert "**OP:** /u/alice" in md
    assert "**Score:** 2" in md
    assert "**Comments:** 3" in md
    assert "I am one of the authors of two recent papers" in md
    assert "/u/bob" in md
    assert "useful comment about the paper" in md
    assert "https://www.reddit.com/r/python/comments/abc/cowindow/" in md


def test_extract_from_html_listing_vs_thread_vs_json():
    import searchts.known_hosts.reddit as reddit_mod
    listing = reddit_mod.extract_from_html(
        "https://www.reddit.com/r/python/hot/",
        _REDDIT_LISTING_HTML_3,
    )
    assert listing is not None
    assert listing[0].startswith("listing-html:")
    thread = reddit_mod.extract_from_html(
        "https://www.reddit.com/r/python/comments/abc/cowindow/",
        _REDDIT_THREAD_HTML,
    )
    assert thread is not None
    assert thread[0] == "thread-html: op"
    assert reddit_mod.extract_from_html(
        "https://www.reddit.com/r/python/hot.json",
        _REDDIT_LISTING_HTML_3,
    ) is None
    assert reddit_mod.is_reddit_thread_url("https://www.reddit.com/r/python/comments/abc/cowindow/")
    assert not reddit_mod.is_reddit_thread_url("https://www.reddit.com/r/python/hot/")
    assert not reddit_mod.is_reddit_thread_url("https://www.reddit.com/r/python/comments/abc/cowindow.json")


def test_is_reddit_listing_url_rejects_json_and_comments_and_other_hosts():
    import searchts.known_hosts.reddit as reddit_mod
    assert not reddit_mod.is_reddit_listing_url("https://www.reddit.com/r/python/hot.json")
    assert not reddit_mod.is_reddit_listing_url("https://www.reddit.com/r/python/hot/.json")
    assert not reddit_mod.is_reddit_listing_url("https://www.reddit.com/r/python/comments/abc/title/")
    assert not reddit_mod.is_reddit_listing_url("https://example.com/r/python/hot/")
    assert not reddit_mod.is_reddit_listing_url("https://news.ycombinator.com/")


def test_is_reddit_listing_url_accepts_variants_and_controversial():
    import searchts.known_hosts.reddit as reddit_mod
    assert reddit_mod.is_reddit_listing_url("https://www.reddit.com/r/python/")
    assert reddit_mod.is_reddit_listing_url("https://www.reddit.com/r/python")
    assert reddit_mod.is_reddit_listing_url("https://www.reddit.com/r/python/hot/")
    assert reddit_mod.is_reddit_listing_url("https://old.reddit.com/r/python/new")
    assert reddit_mod.is_reddit_listing_url("https://reddit.com/r/python/top/")
    assert reddit_mod.is_reddit_listing_url("https://reddit.com/r/python/rising?sort=hot")
    assert reddit_mod.is_reddit_listing_url("https://www.reddit.com/r/python/controversial/")


def test_listing_html_short_circuit_in_fetch(monkeypatch, capsys):
    """JSON ring 403, curl returns 3-post HTML, jina/stealth raise; listing wins, ticks listing-html."""
    import searchts.known_hosts.reddit as reddit_mod

    # JSON ring returns 403 interstitial → None
    monkeypatch.setattr(reddit_mod, "_fetch", lambda u, timeout=30: json.dumps({"error": 403, "message": "blocked"}))

    def fake_curl(url, timeout=30):
        return 200, _REDDIT_LISTING_HTML_3, url, {}

    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", fake_curl)
    monkeypatch.setattr(unlocker, "_fetch_jina", lambda url, **k: (_ for _ in ()).throw(Tripwire("jina")))
    monkeypatch.setattr(unlocker, "_fetch_stealth", lambda url, **k: (_ for _ in ()).throw(Tripwire("stealth")))

    res = unlocker.fetch(
        "https://www.reddit.com/r/python/hot/",
        backends=["curl_cffi"],
        use_memory=False,
        progress=True,
    )
    assert "First post title" in res.text
    assert "Second post title" in res.text
    assert "Third post title" in res.text
    captured = capsys.readouterr()
    assert "listing-html:" in captured.err
    assert captured.out == ""


def test_listing_html_three_posts_skips_html_to_text(monkeypatch):
    """3-post case must short-circuit before html_to_text; 1-post case must still call through."""
    import searchts.known_hosts.reddit as reddit_mod
    import searchts.unlocker as ul_mod

    monkeypatch.setattr(
        reddit_mod,
        "_fetch",
        lambda u, timeout=30: json.dumps({"error": 403, "message": "blocked"}),
    )

    # 3-post case
    calls = []
    def exploding_to_text(html, url=None):
        calls.append("html_to_text")
        raise AssertionError("html_to_text must not be called for 3+ post listing")

    monkeypatch.setattr(ul_mod, "html_to_text", exploding_to_text)

    def fake_curl(url, timeout=30):
        return 200, _REDDIT_LISTING_HTML_3, url, {}

    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", fake_curl)
    monkeypatch.setattr(unlocker, "_fetch_jina", lambda url, **k: (_ for _ in ()).throw(Tripwire("jina")))
    monkeypatch.setattr(unlocker, "_fetch_stealth", lambda url, **k: (_ for _ in ()).throw(Tripwire("stealth")))

    res3 = unlocker.fetch(
        "https://www.reddit.com/r/python/hot/",
        backends=["curl_cffi"],
        use_memory=False,
    )
    assert "First post title" in res3.text
    assert calls == [], "html_to_text must not have been called for >=2 titled posts"

    # 1-post case: must fall through to html_to_text
    html_to_text_calls = []
    def spy_to_text(html, url=None):
        html_to_text_calls.append(1)
        # Return > _MIN_CHARS so the normal win path returns instead of thin-fail.
        return "FALLTHROUGH TEXT FROM HTML_TO_TEXT " + ("x" * 600)

    monkeypatch.setattr(ul_mod, "html_to_text", spy_to_text)

    def fake_curl1(url, timeout=30):
        return 200, _REDDIT_LISTING_HTML_1, url, {}

    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", fake_curl1)
    monkeypatch.setattr(unlocker, "_fetch_jina", lambda url, **k: (_ for _ in ()).throw(Tripwire("jina")))
    monkeypatch.setattr(unlocker, "_fetch_stealth", lambda url, **k: (_ for _ in ()).throw(Tripwire("stealth")))

    res1 = unlocker.fetch(
        "https://www.reddit.com/r/python/",
        backends=["curl_cffi"],
        use_memory=False,
    )
    assert html_to_text_calls, "html_to_text should have been called for 1-post fallthrough"
    assert "FALLTHROUGH" in res1.text


def test_canonical_permalink_rewrites_old_reddit_and_keeps_other_hosts():
    import searchts.known_hosts.reddit as reddit_mod
    html = """
    <shreddit-post post-title="Old host" permalink="https://old.reddit.com/r/python/comments/abc/old/"></shreddit-post>
    <shreddit-post post-title="Off site" permalink="https://example.com/not-reddit"></shreddit-post>
    """
    md = reddit_mod.parse_reddit_listing_html(html, "https://www.reddit.com/r/python/hot/")
    assert md is not None
    assert "https://www.reddit.com/r/python/comments/abc/old/" in md
    assert "old.reddit.com" not in md
    assert "https://example.com/not-reddit" in md


def test_human_listing_beats_longer_thin_best(monkeypatch):
    """A short listing from the human rung wins even when an earlier thin body is longer."""
    import searchts.known_hosts.reddit as reddit_mod

    monkeypatch.setattr(
        reddit_mod,
        "_fetch",
        lambda u, timeout=30: json.dumps({"error": 403, "message": "blocked"}),
    )
    monkeypatch.setattr(
        unlocker,
        "_fetch_curl_cffi",
        lambda url, timeout=30: (200, "<html><body>no posts here</body></html>", url, {}),
    )
    monkeypatch.setattr(
        unlocker,
        "html_to_text",
        lambda html, url=None: "Z" * 450,
    )
    monkeypatch.setattr(unlocker, "_fetch_jina", lambda url, **k: (_ for _ in ()).throw(Tripwire("jina")))
    monkeypatch.setattr(unlocker, "_fetch_stealth", lambda url, **k: (_ for _ in ()).throw(Tripwire("stealth")))
    short = (
        '<shreddit-post post-title="Aa" permalink="/r/python/comments/a/a/"></shreddit-post>'
        '<shreddit-post post-title="Bb" permalink="/r/python/comments/b/b/"></shreddit-post>'
    )
    monkeypatch.setattr(
        unlocker,
        "_fetch_human",
        lambda url, **k: (200, short, url),
    )

    res = unlocker.fetch(
        "https://www.reddit.com/r/python/hot/",
        backends=["curl_cffi"],
        use_memory=False,
        allow_human=True,
        progress=False,
    )
    assert "Aa" in res.text
    assert "Bb" in res.text
    assert "ZZZ" not in res.text
    assert res.backend == "human-browser"
