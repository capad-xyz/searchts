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


def test_matches_rejects_non_json_url():
    assert not matches("https://www.reddit.com/r/python/comments/abc123/some_title/")
    assert not matches("https://www.reddit.com/r/python/")
    assert not matches("https://www.reddit.com/user/spez/")


def test_matches_rejects_other_domains():
    assert not matches("https://example.com/.json")
    assert not matches("https://www.nytimes.com/r/python/.json")


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


def test_fetch_falls_through_to_ladder_for_non_json_reddit_url(monkeypatch):
    """A Reddit HTML URL (no .json) walks the ladder unchanged."""
    calls = []

    def spy_curl(url, timeout=30):
        calls.append(("curl_cffi", url))
        return 200, "<html><body>" + "real reddit page " * 100 + "</body></html>", url, {}

    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", spy_curl)
    monkeypatch.setattr(unlocker, "_fetch_jina", lambda url, timeout=40: (_ for _ in ()).throw(Tripwire("jina called")))
    monkeypatch.setattr(unlocker, "_fetch_stealth", lambda url, **k: (_ for _ in ()).throw(Tripwire("stealth called")))

    res = unlocker.fetch(
        "https://www.reddit.com/r/python/comments/abc123/some_title/",
        backends=["curl_cffi"],
        use_memory=False,
    )
    assert calls == [("curl_cffi", "https://www.reddit.com/r/python/comments/abc123/some_title/")]
    assert "real reddit page" in res.text


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
