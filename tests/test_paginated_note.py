# -*- coding: utf-8 -*-
"""F23e/F24: a paginated list says so, and says which knob asks for the rest.

A read of page 1 of a list used to end the same way as a read of a whole
document: the page silently gave back one window and the agent had no way to
tell that was not everything. The ``[more: the next page is ...]`` note was
already there when the page declared its next page well enough; this covers the
shapes that were silent anyway, a numbered nav that marks nothing current, an
"Older posts" link outside any pager, and a ``Link: rel="next"`` header with no
markup at all.

The fixtures are real-shaped, not real pages: no host's own class names, so a
test cannot start passing because a site renames a container. The one page that
*is* real, ``fixtures/django_weblog.html``, is used as saved for the shape the
blog index already worked on, which is what keeps that path honest.

The note that names the knob carries no URL on purpose. The MCP envelope strips
page-chosen URLs out of every note (``mcp_server._more_without_urls``), so a
note with a URL in it is blanked there; this one names the knobs instead, which
is what survives to the agent.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from searchts import more, unlocker

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

URL = "https://example.org/blog/"

SENT = (
    "The committee met on Tuesday to hear what the engineers had measured in the "
    "second week, and nobody expected the numbers to be this far apart. "
)


def _rows(n: int = 12) -> str:
    return (
        '<ul class="posts">'
        + "".join(
            f'<li class="post"><h2><a href="/blog/post-{i}/">Post number {i} '
            f"about the thing</a></h2><p class=\"meta\">Oct {i}, 2026</p></li>"
            for i in range(n)
        )
        + "</ul>"
    )


def _index(inner: str = "", head: str = "", body: str = "") -> str:
    return (
        f"<html><head><title>A blog</title>{head}</head><body><main>"
        f"<h1>Writing</h1>{_rows()}{inner}</main>{body}</body></html>"
    )


def _article(inner: str = "") -> str:
    return (
        '<html><head><title>One post</title></head><body><main><article><h1>A post</h1>'
        + f"<p>{SENT * 12}</p>{inner}"
        + "</article></main></body></html>"
    )


def _notes(found, kind: str):
    return [m.note for m in found if m.kind == kind]


def _urls(found, kind: str):
    return [m.url for m in found if m.kind == kind]


# ── the shapes that used to be silent ────────────────────────────────────────


def test_a_numbered_nav_that_marks_nothing_current():
    """No aria-current, no bare number, no rel=next: only the numbers.

    The address is the evidence for where we are. It carries no page marker, so
    this is page 1 of the list, and page 2 is the link the pager holds.
    """
    pager = (
        '<nav class="pagination" aria-label="Pagination">'
        '<a href="/blog/">1</a><a href="/blog/page/2/">2</a><a href="/blog/page/3/">3</a>'
        "</nav>"
    )
    found = more.detect(_index(pager), URL, "kept text")
    assert _urls(found, "next-page") == ["https://example.org/blog/page/2/"]


def test_the_page_marker_in_the_address_wins_over_the_pager():
    """``/blog/page/4/`` is page 4 whatever the pager forgets to mark."""
    pager = '<nav class="pagination"><a href="/blog/page/3/">3</a><a href="/blog/page/5/">5</a></nav>'
    found = more.detect(_index(pager), "https://example.org/blog/page/4/", "kept text")
    assert _urls(found, "next-page") == ["https://example.org/blog/page/5/"]


def test_a_query_page_marker_is_read_too():
    """``?p=2`` is Hacker News's own spelling of the same thing."""
    pager = '<nav aria-label="pagination"><a href="/list?p=1">1</a><a href="/list?p=3">3</a></nav>'
    found = more.detect(_index(pager), "https://example.org/list?p=2", "kept text")
    assert _urls(found, "next-page") == ["https://example.org/list?p=3"]


def test_a_pager_that_never_links_page_one_is_left_alone():
    """Numbers 4, 5, 6 on an address with no marker: this is somebody else's
    pager window, and claiming page 5 from here would be a guess."""
    pager = '<nav class="pagination"><a href="/blog/page/4/">4</a><a href="/blog/page/5/">5</a></nav>'
    found = more.detect(_index(pager), URL, "kept text")
    assert _urls(found, "next-page") == []


def test_a_pager_with_no_link_after_the_current_page_is_left_alone():
    """Page 3 with only 1 and 2 on offer: there is no next page in the page, so
    there is none to name. Last page of a series, exactly."""
    pager = '<nav class="pagination"><a href="/blog/">1</a><a href="/blog/page/2/">2</a></nav>'
    found = more.detect(_index(pager), "https://example.org/blog/page/3/", "kept text")
    assert _urls(found, "next-page") == []


def test_an_older_posts_link_outside_any_pager_still_counts():
    """The words on the link, in navigation chrome. A blog that keeps its
    "Older posts" in a footer nav and never names a pager class was silent."""
    nav = '<div class="postnav"><a href="/blog/page/2/">Older posts</a></div>'
    found = more.detect(_index(body=nav), URL, "kept text")
    assert _urls(found, "next-page") == ["https://example.org/blog/page/2/"]


def test_a_next_link_in_a_nav_element_counts():
    nav = '<nav aria-label="Post navigation"><a href="/blog/page/2/">Next</a></nav>'
    found = more.detect(_index(body=nav), URL, "kept text")
    assert _urls(found, "next-page") == ["https://example.org/blog/page/2/"]


def test_a_link_response_header_is_read_when_the_markup_says_nothing():
    """RFC 8288. A page can paginate with no rel=next link, no pager, no word
    "next" anywhere, and say so in the one header the markup does not carry."""
    headers = {
        "content-type": "text/html",
        "link": '</style.css>; rel=preload; as=style, '
                '<https://example.org/blog/page/2/>; rel="next", '
                '</feed.xml>; rel="alternate"',
    }
    found = more.detect(_index(), URL, "kept text", headers=headers)
    assert _urls(found, "next-page") == ["https://example.org/blog/page/2/"]


@pytest.mark.parametrize(
    "header",
    [
        "<https://other.example/blog/page/2/>; rel=\"next\"",  # another host
        "<https://example.org/blog/2026/10/a-post/>; rel=\"next\"",  # another document
        "<https://example.org/blog/page/2/>; rel=\"prev\"",  # not next
    ],
)
def test_a_link_header_the_page_did_not_mean_for_us_is_refused(header):
    found = more.detect(_index(), URL, "kept text", headers={"link": header})
    assert _urls(found, "next-page") == []


def test_markup_wins_over_the_header():
    pager = '<nav class="pagination"><a href="/blog/">1</a><a href="/blog/page/2/">2</a></nav>'
    headers = {"link": '<https://example.org/blog/page/9/>; rel="next"'}
    found = more.detect(_index(pager), URL, "kept text", headers=headers)
    assert _urls(found, "next-page") == ["https://example.org/blog/page/2/"]


# ── what must stay silent ────────────────────────────────────────────────────


def test_a_page_that_is_not_paginated_gets_no_note():
    """An ordinary article with nav around it. Nothing here says there is more,
    so nothing may claim there is."""
    inner = '<nav class="site-nav"><a href="/blog/">Home</a><a href="/about/">About</a></nav>'
    assert _urls(more.detect(_article(inner), "https://example.org/blog/a-post/", "kept"), "next-page") == []
    assert _notes(more.detect(_article(inner), "https://example.org/blog/a-post/", "kept"), "paginated") == []


def test_next_in_a_sentence_is_not_a_next_page():
    """The widening above is bounded by navigation chrome and by the same
    document. Prose that happens to contain the word stays prose."""
    inner = '<p>Read the <a href="/blog/page/2/">next</a> post.</p>'
    assert _urls(more.detect(_article(inner), "https://example.org/blog/a-post/", "kept"), "next-page") == []


def test_a_link_to_another_document_is_never_the_next_page():
    inner = '<div class="postnav"><a href="/blog/another-post/">Older posts</a></div>'
    assert _urls(more.detect(_article(inner), "https://example.org/blog/a-post/", "kept"), "next-page") == []


def test_a_feed_with_no_next_page_does_not_claim_one():
    """role=feed is "more items load on scroll", not a next page URL. The note
    that names the knob is only ever added with a URL that was really found."""
    feed = '<div role="feed"><article><h2>One thing that happened today</h2></article></div>'
    found = more.detect(_index(body=feed), URL, "kept text")
    assert _urls(found, "next-page") == []
    assert _notes(found, "paginated") == []
    assert _notes(found, "feed")  # the feed note is still there


# ── the note itself ──────────────────────────────────────────────────────────


def test_the_paginated_note_names_both_knobs_on_both_surfaces():
    found = more.detect(_index(head='<link rel="next" href="/blog/page/2/">'), URL, "kept text")
    note = _notes(found, "paginated")[0]
    assert "--pages" in note and "--items" in note
    assert "max_pages" in note and "max_items" in note
    assert note == more.PAGINATED_NOTE


def test_the_paginated_note_carries_no_url():
    """It has to: the MCP envelope blanks any note holding a page-chosen URL,
    and this note is the one that names the knob."""
    found = more.detect(_index(head='<link rel="next" href="/blog/page/2/">'), URL, "kept text")
    for item in found:
        if item.kind == "paginated":
            assert item.url is None
            assert "http" not in item.note


def test_the_next_page_note_is_unchanged():
    """F23a's note is pinned elsewhere; this is the same string, so a change to
    it shows up here too."""
    found = more.detect(_index(head='<link rel="next" href="/blog/page/2/">'), URL, "kept text")
    assert _notes(found, "next-page") == ["[more: the next page is https://example.org/blog/page/2/]"]


def test_a_real_saved_blog_index_says_both_its_parts():
    """The one fixture that is a real page, used as saved."""
    html = (FIXTURES / "django_weblog.html").read_text(encoding="utf-8")
    found = more.detect(html, "https://www.djangoproject.com/weblog/", "kept text")
    assert _urls(found, "next-page") == ["https://www.djangoproject.com/weblog/?page=2"]
    assert _notes(found, "paginated") == [more.PAGINATED_NOTE]


# ── the read path, not the function behind it ────────────────────────────────


def _curl(monkeypatch, pages, headers=None):
    """The tier-0 rung, answering with the fixture for each URL."""
    monkeypatch.setattr(unlocker, "jina_enabled", lambda: False)
    monkeypatch.setattr(
        unlocker,
        "_fetch_curl_cffi",
        lambda url, timeout=30: (200, pages[url], url, dict(headers or {})),
    )


def test_read_carries_the_note_and_the_next_url(monkeypatch):
    pager = '<nav class="pagination"><a href="/blog/">1</a><a href="/blog/page/2/">2</a></nav>'
    _curl(monkeypatch, {URL: _index(pager)})
    r = unlocker.fetch(URL, backends=["curl_cffi"], use_memory=False)
    assert r.next_url == "https://example.org/blog/page/2/"
    kinds = [m["kind"] for m in r.more]
    assert "next-page" in kinds and kinds[-1] == "paginated"
    assert r.text.rstrip().endswith(more.PAGINATED_NOTE)
    assert r.page_html is None


def test_read_pages_follows_the_page_the_numbered_nav_pointed_at(monkeypatch):
    """The note names ``--pages``; this is that flag following the link the
    numbered nav gave, with no other page in the markup."""
    pager = '<nav class="pagination"><a href="/blog/">1</a><a href="/blog/page/2/">2</a></nav>'
    pages = {
        URL: _index(pager),
        "https://example.org/blog/page/2/": _index(
            '<nav class="pagination"><a href="/blog/">1</a></nav>'
        ),
    }
    _curl(monkeypatch, pages)
    got = unlocker.read_pages(URL, 2)
    assert [p.final_url for p in got] == [URL, "https://example.org/blog/page/2/"]


def test_read_items_follows_the_link_header_next_page(monkeypatch):
    """The other half of the note's promise: the knob it names reaches the page
    the header declared, with no link for it anywhere in the markup."""
    pages = {
        URL: _index(),
        "https://example.org/blog/page/2/": _index(),
    }
    monkeypatch.setattr(unlocker, "jina_enabled", lambda: False)

    def rung(url, timeout=30):
        headers = {"link": '<https://example.org/blog/page/2/>; rel="next"'} if url == URL else {}
        return (200, pages[url], url, headers)

    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", rung)
    got = unlocker.read_items(URL, 20)
    assert [p.final_url for p in got] == [URL, "https://example.org/blog/page/2/"]


# ── the MCP envelope ─────────────────────────────────────────────────────────


def _mcp_page(monkeypatch, html, headers=None):
    from searchts.integrations import mcp_server

    _curl(monkeypatch, {URL: html}, headers=headers)
    monkeypatch.setattr("searchts.ssrf.guard_mcp_url", lambda url, **kw: None)
    real_fetch = unlocker.fetch
    monkeypatch.setattr(
        unlocker, "fetch", lambda url, **kw: real_fetch(url, backends=["curl_cffi"], use_memory=False)
    )
    return json.loads(mcp_server.read_url(URL))


def test_an_mcp_agent_is_told_the_page_is_paginated_and_which_knob(monkeypatch):
    pager = '<nav class="pagination"><a href="/blog/">1</a><a href="/blog/page/2/">2</a></nav>'
    doc = _mcp_page(monkeypatch, _index(pager))
    notes = " ".join(m.get("note") or "" for m in doc["more"])
    assert "max_pages" in notes and "max_items" in notes
    assert more.PAGINATED_NOTE in [m["note"] for m in doc["more"]]


def test_the_envelope_still_carries_no_page_chosen_url(monkeypatch):
    """The leak test from #339, kept honest on the widened detection: a page
    that names its own next page does not get to author the agent's next
    request, and the note that survives names the knob instead."""
    pager = '<nav class="pagination"><a href="/blog/">1</a><a href="/blog/page/2/">2</a></nav>'
    doc = _mcp_page(monkeypatch, _index(pager))
    envelope = {k: v for k, v in doc.items() if k not in ("text", "pages")}
    assert "next_url" not in doc
    assert "https://example.org/blog/page/2/" not in json.dumps(envelope)
    # Inside the fence it stays, which is where page data belongs.
    assert "https://example.org/blog/page/2/" in doc["text"]
