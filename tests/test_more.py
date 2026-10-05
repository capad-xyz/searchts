# -*- coding: utf-8 -*-
"""F23a: say when a page has more than the read returned (no extra requests, no clicks)."""

from __future__ import annotations

import json

import pytest

from searchts import more, unlocker

URL = "https://example.org/blog/"
PARA = "This paragraph carries enough ordinary words to look like the main body of a real page, part {}."


def _page(inner: str, head: str = "") -> str:
    body = "".join(f"<p>{PARA.format(i)} {PARA.format(i + 100)}</p>" for i in range(3))
    return f"<html><head>{head}</head><body><main><article><h1>Title</h1>{body}{inner}</article></main></body></html>"


def _kinds(found):
    return [m.kind for m in found]


# ── next page ────────────────────────────────────────────────────────────────


def test_link_rel_next_in_head():
    found = more.detect(_page("", head='<link rel="next" href="/blog/page/2/">'), URL, "text")
    assert _kinds(found) == ["next-page"]
    assert found[0].url == "https://example.org/blog/page/2/"
    assert "https://example.org/blog/page/2/" in found[0].note


def test_anchor_rel_next_resolves_relative_links():
    found = more.detect(_page('<a rel="prev next" href="?page=3">3</a>'), "https://example.org/list?page=2", "t")
    assert found[0].url == "https://example.org/list?page=3"


def test_pager_next_link_without_rel():
    pager = '<nav aria-label="Pagination"><a href="/blog/page/1/">1</a><a href="/blog/page/2/">Next ›</a></nav>'
    found = more.detect(_page(pager), URL, "t")
    assert found and found[0].url == "https://example.org/blog/page/2/"


def test_pager_uses_the_current_page_number():
    pager = (
        '<ul class="pagination"><li><span aria-current="page">4</span></li>'
        '<li><a href="/blog/page/5/">5</a></li><li><a href="/blog/page/6/">6</a></li></ul>'
    )
    found = more.detect(_page(pager), "https://example.org/blog/page/4/", "t")
    assert found[0].url == "https://example.org/blog/page/5/"


@pytest.mark.parametrize(
    "inner",
    [
        '<a href="/blog/another-post/">Next article</a>',  # a related post, not page 2
        '<p>Read the <a href="/blog/page/2/">next</a> post.</p>',  # not in a pager
        '<link rel="next" href="https://other.example/page/2">',  # another host
        '<a rel="next" href="#comments">Next</a>',  # same page
    ],
)
def test_not_a_next_page(inner):
    assert "next-page" not in _kinds(more.detect(_page(inner), URL, "t"))


# ── feeds ────────────────────────────────────────────────────────────────────


def test_role_feed_is_a_feed():
    found = more.detect(_page('<div role="feed"><article>one</article></div>'), URL, "t")
    assert _kinds(found) == ["feed"]


def test_load_more_button_is_a_feed():
    found = more.detect(_page("<button>Load more</button>"), URL, "t")
    assert _kinds(found) == ["feed"]
    assert "first window" in found[0].note


def test_load_more_link_is_the_next_page():
    found = more.detect(_page('<a href="/blog/page/2/">Load more posts</a>'), URL, "t")
    assert _kinds(found) == ["next-page"]
    assert found[0].url == "https://example.org/blog/page/2/"


# ── folds ────────────────────────────────────────────────────────────────────


def test_read_more_button_is_a_fold():
    found = more.detect(_page('<p>Start of a long post</p><button type="button">Read more</button>'), URL, "t")
    assert _kinds(found) == ["fold"]
    assert '1 control like "Read more"' in found[0].note


def test_blog_index_read_more_links_are_links_not_folds():
    cards = "".join(f'<p>Excerpt {i}</p><a href="/blog/post-{i}/">Read more</a>' for i in range(5))
    assert "fold" not in _kinds(more.detect(_page(cards), URL, "t"))


def test_read_more_in_page_chrome_is_ignored():
    html = _page("").replace("<main>", '<header><button>Show more</button></header><main>')
    html = html.replace("</main>", '</main><footer><a href="#">See more</a></footer>')
    assert more.detect(html, URL, "t") == []


# ── accordions and tabs ──────────────────────────────────────────────────────


FAQ_HIDDEN = (
    "<h2>FAQ</h2>"
    '<button aria-expanded="false" aria-controls="p1">Can I change my plan?</button>'
    '<div id="p1" hidden><p>Yes, you can switch plans at any time from the billing page.</p></div>'
    '<button aria-expanded="false">Is there a free tier?</button>'
    '<div style="display:none"><p>There is a free tier with three projects and community support.</p></div>'
)


def test_accordion_questions_and_hidden_answers_survive_extraction():
    text = unlocker.html_to_text(_page(FAQ_HIDDEN), URL)
    assert "Can I change my plan?" in text
    assert "switch plans at any time" in text
    assert "Is there a free tier?" in text
    assert "free tier with three projects" in text  # was dropped whole before F23a


def test_tab_labels_move_into_their_panels():
    tabs = (
        '<div role="tablist"><button role="tab" aria-controls="m">Monthly</button>'
        '<button role="tab" aria-controls="y">Yearly</button></div>'
        '<div role="tabpanel" id="m"><p>Monthly costs ten dollars per seat billed each month.</p></div>'
        '<div role="tabpanel" id="y" hidden><p>Yearly costs one hundred dollars per seat per year.</p></div>'
    )
    text = unlocker.html_to_text(_page(tabs), URL)
    assert text.index("Monthly") < text.index("ten dollars") < text.index("Yearly") < text.index("one hundred")


def test_menu_toggles_are_left_alone():
    html = _page('<button aria-expanded="false" aria-haspopup="true">Share</button><ul><li>X</li></ul>')
    assert more.prepare_panels(html) == html


def test_empty_panel_is_a_fold():
    html = _page('<button aria-expanded="false" aria-controls="q">Shipping times?</button><div id="q"></div>')
    found = more.detect(html, URL, "t")
    assert _kinds(found) == ["fold"]
    assert "1 collapsed section was empty" in found[0].note


def test_details_still_read_without_help():
    html = _page("<details><summary>How do refunds work?</summary><p>Refunds reach the card in five days.</p></details>")
    text = unlocker.html_to_text(html, URL)
    assert "How do refunds work?" in text and "five days" in text


# Bootstrap 5.3 markup (getbootstrap.com/docs/5.3/components/accordion/): the
# button sits inside the page's own <h2>, with whitespace around it.
BOOTSTRAP_ACCORDION = (
    '<div class="accordion" id="acc">'
    '<div class="accordion-item"><h2 class="accordion-header">\n      '
    '<button class="accordion-button" type="button" data-bs-toggle="collapse" data-bs-target="#one" '
    'aria-expanded="true" aria-controls="one">\n        Accordion Item #1\n      </button>\n    </h2>'
    '<div id="one" class="accordion-collapse collapse show"><div class="accordion-body">'
    "<strong>This is the first item's accordion body.</strong> It is shown by default until the plugin runs."
    "</div></div></div>"
    '<div class="accordion-item"><h2 class="accordion-header">\n      '
    '<button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#two" '
    'aria-expanded="false" aria-controls="two">\n        Accordion Item #2\n      </button>\n    </h2>'
    '<div id="two" class="accordion-collapse collapse"><div class="accordion-body">'
    "<strong>This is the second item's accordion body.</strong> It is hidden by default until the plugin runs."
    "</div></div></div></div>"
)


def test_button_inside_a_heading_becomes_that_heading():
    text = unlocker.html_to_text(_page(BOOTSTRAP_ACCORDION), URL)
    lines = text.splitlines()
    assert "## Accordion Item #1" in lines
    assert "## Accordion Item #2" in lines  # was indented, so Markdown read it as code
    assert "##" not in [ln.strip() for ln in lines]  # no empty heading left behind
    assert "### Accordion Item" not in text
    assert "shown by default until the plugin runs" in text
    assert "hidden by default until the plugin runs" in text


def test_table_of_contents_toggle_is_not_a_question():
    toc = (
        '<div class="bd-toc"><button class="bd-toc-toggle" type="button" data-bs-toggle="collapse" '
        'data-bs-target="#toc" aria-expanded="false" aria-controls="toc">On this page</button>'
        '<div class="collapse" id="toc"><nav id="TableOfContents"><ul>'
        '<li><a href="#how">How it works</a></li><li><a href="#example">Example</a></li>'
        '<li><a href="#a11y">Accessibility</a></li></ul></nav></div></div>'
    )
    html = _page(toc)
    assert more.prepare_panels(html) == html
    assert "On this page" not in unlocker.html_to_text(html, URL)


@pytest.mark.parametrize(
    "answer",
    [
        '<a href="/docs/">Read the docs</a>',
        '<ul><li><a href="/g/1">Setup guide</a></li><li><a href="/g/2">API guide</a></li>'
        '<li><a href="/g/3">CLI guide</a></li></ul>',
    ],
)
def test_an_answer_made_of_links_is_still_an_answer(answer):
    faq = (
        '<button aria-expanded="false" aria-controls="d">Where are the docs?</button>'
        f'<div id="d" hidden>{answer}</div>'
    )
    out = more.prepare_panels(_page(faq))
    assert "<h3>Where are the docs?</h3>" in out  # only a nav of links is skipped
    assert '<div id="d">' in out  # and the panel is un-hidden


# The live page puts a code sample right after each accordion. When the last
# body text is a tail after <code>, Trafilatura prints the fence glued to it
# ("application.```") or indented by the tail's whitespace.
CODE_SAMPLE = (
    '<div class="bd-code-snippet"><div class="highlight"><pre tabindex="0" class="chroma">'
    '<code class="language-html">&lt;div class="accordion accordion-flush"&gt;\n'
    '  &lt;div class="accordion-item"&gt;&lt;/div&gt;\n&lt;/div&gt;</code></pre></div></div>'
)


def _flush_page(tail_ws: str) -> str:
    def item(n: int) -> str:
        return (
            '<div class="accordion-item"><h2 class="accordion-header">\n      '
            f'<button class="accordion-button collapsed" type="button" aria-expanded="false" aria-controls="f{n}">'
            f"\n        Accordion Item #{n}\n      </button>\n    </h2>"
            f'<div id="f{n}" class="accordion-collapse collapse"><div class="accordion-body">'
            "Placeholder content to show the <code>.accordion-flush</code> class in a real-world application."
            f"{tail_ws}</div></div></div>"
        )

    accordion = f'<div class="accordion accordion-flush" id="flush">{item(1)}{item(2)}</div>'
    after = '<h3 id="always-open">Always open</h3><p>Omit the parent attribute to keep items open.</p>'
    return _page("<h3>Flush</h3>" + accordion + CODE_SAMPLE + after)


@pytest.mark.parametrize("tail_ws", ["", "\n      "])
def test_code_sample_after_an_accordion_opens_on_its_own_line(tail_ws):
    lines = unlocker.html_to_text(_flush_page(tail_ws), URL).splitlines()
    assert "## Accordion Item #2" in lines
    first_code_line = lines.index('<div class="accordion accordion-flush">')
    assert lines[first_code_line - 1] == "```"
    assert lines.count("```") == 2
    assert not any(ln.endswith("application.```") for ln in lines)


def test_tidy_markdown_puts_an_indented_heading_on_its_own_line():
    md = "limit overflow.\n      ## Accordion Item #2\n\nBody text."
    assert more.tidy_markdown(md) == "limit overflow.\n\n## Accordion Item #2\n\nBody text."


def test_tidy_markdown_unglues_and_unindents_code_fences():
    glued = "a real-world application.```\n<div></div>\n```\n### Always open"
    assert more.tidy_markdown(glued) == "a real-world application.\n\n```\n<div></div>\n```\n### Always open"
    indented = "limit overflow.\n      ```\n<div></div>\n```"
    assert more.tidy_markdown(indented) == "limit overflow.\n\n```\n<div></div>\n```"


@pytest.mark.parametrize(
    "md",
    [
        "Intro.\n\n```\n    # a shell comment\n  ## not a heading\n      ```\n```\n\n## Real heading",
        "Wrap code in ```",  # no closing fence anywhere, so this is just a sentence
        "- item\n  ## Nested",  # under four spaces is still a heading
    ],
)
def test_tidy_markdown_leaves_these_alone(md):
    assert more.tidy_markdown(md) == md


# ── list pages the extract mostly dropped ────────────────────────────────────


def _cards(n: int) -> str:
    return "".join(
        f'<div class="card"><h3><a href="/item/{i}">Story number {i} about something</a></h3>'
        f"<p>A short teaser for story {i} with a few more words.</p></div>"
        for i in range(n)
    )


def _list_page(n: int) -> str:
    return f'<html><body><main><div class="grid">{_cards(n)}</div></main></body></html>'


def test_list_page_where_the_extract_kept_one_item():
    found = more.detect(_list_page(27), URL, "Story number 0 about something. A short teaser.")
    assert _kinds(found) == ["list"]
    assert found[0].note == "[partial: the page lists 27 items; this read kept 1]"


def test_list_page_fully_kept_has_no_note():
    text = " ".join(f"Story number {i} about something" for i in range(27))
    assert more.detect(_list_page(27), URL, text) == []


def test_related_grid_under_an_article_is_not_a_partial_list():
    long_body = "".join(f"<p>{PARA.format(i)} {PARA.format(i + 50)} {PARA.format(i + 90)}</p>" for i in range(12))
    html = (
        f"<html><body><main><article><h1>A long article</h1>{long_body}</article>"
        f'<section class="related"><div class="grid">{_cards(9)}</div></section></main></body></html>'
    )
    assert "list" not in _kinds(more.detect(html, URL, "the article text only"))


def test_nav_menus_are_not_lists():
    links = "".join(f'<li class="m"><a href="/c/{i}">Category number {i} with a long name</a></li>' for i in range(20))
    html = f"<html><body><nav><ul>{links}</ul></nav><main><p>{PARA.format(1) * 3}</p></main></body></html>"
    assert "list" not in _kinds(more.detect(html, URL, PARA.format(1)))


# ── counts the page states ───────────────────────────────────────────────────


def test_showing_x_of_y():
    found = more.detect(_page("<p>Showing 1–20 of 340 results</p>"), URL, "t")
    assert "[page says: showing 1–20 of 340]" in [m.note for m in found]


def test_page_x_of_y():
    found = more.detect(_page("<span>Page 2 of 9</span>"), URL, "t")
    assert "[page says: page 2 of 9]" in [m.note for m in found]


@pytest.mark.parametrize("said", ["Showing 1–20 of 20 results", "Page 9 of 9"])
def test_counts_already_complete_say_nothing(said):
    assert more.detect(_page(f"<p>{said}</p>"), URL, "t") == []


# ── plain pages and bad input ────────────────────────────────────────────────


def test_plain_article_has_no_notes():
    assert more.detect(_page(""), URL, "whatever") == []
    assert more.annotate("body", []) == "body"


@pytest.mark.parametrize("bad", ["", "   ", '<?xml version="1.0" encoding="utf-8"?><html><body>x</body></html>'])
def test_odd_input_never_raises(bad):
    assert more.detect(bad, URL, "") == []
    assert more.prepare_panels(bad) == bad or "<html" in more.prepare_panels(bad)


# ── wired into fetch, --json and MCP ─────────────────────────────────────────


def _curl(monkeypatch, html, final_url=URL):
    monkeypatch.setattr(unlocker, "jina_enabled", lambda: False)
    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", lambda url, timeout=30: (200, html, final_url, {}))


def _hn_page(more_href: str) -> str:
    rows = "".join(
        f'<tr class="athing submission" id="{i}"><td class="title"><span class="rank">{i}.</span></td>'
        f'<td class="title"><span class="titleline"><a href="https://example{i}.com/post">Story {i} about tools</a>'
        f'</span></td></tr><tr><td colspan="2"></td><td class="subtext"><span class="score">{i} points</span> by '
        f'<a href="user?id=u{i}" class="hnuser">u{i}</a> | <a href="item?id={i}">{i} comments</a></td></tr>'
        for i in range(1, 31)
    )
    return (
        '<html><head><title>Hacker News</title></head><body><center><table id="hnmain"><tr><td>'
        f'<table>{rows}<tr class="morespace"></tr><tr><td colspan="2"></td><td class="title">'
        f'<a href="{more_href}" class="morelink" rel="next">More</a></td></tr></table></td></tr></table></center></body></html>'
    )


@pytest.mark.parametrize(
    "url, href, expected",
    [
        ("https://news.ycombinator.com/", "?p=2", "https://news.ycombinator.com/?p=2"),
        ("https://news.ycombinator.com/news", "news?p=2", "https://news.ycombinator.com/news?p=2"),
    ],
)
def test_hacker_news_more_link_is_the_next_page(url, href, expected):
    found = more.detect(_hn_page(href), url, "text")
    assert [(m.kind, m.url) for m in found if m.kind == "next-page"] == [("next-page", expected)]


def test_read_pages_follows_next_then_stops_on_a_loop(monkeypatch):
    pages = {
        "https://example.org/blog": ("page one", "https://example.org/blog/page/2"),
        "https://example.org/blog/page/2": ("page two", "https://example.org/blog"),
    }

    def fake(url, **_k):
        text, nxt = pages[url]
        return unlocker.FetchResult(backend="curl_cffi", text=text, status=200, final_url=url, next_url=nxt)

    monkeypatch.setattr(unlocker, "fetch", fake)
    got = unlocker.read_pages("https://example.org/blog", 5)
    assert [p.text for p in got] == ["page one", "page two"]


def test_fetch_carries_next_url_and_a_trailing_note(monkeypatch):
    html = _page("", head='<link rel="next" href="/blog/page/2/">')
    _curl(monkeypatch, html)
    r = unlocker.fetch(URL, backends=["curl_cffi"], use_memory=False)
    assert r.next_url == "https://example.org/blog/page/2/"
    assert r.more == [{"kind": "next-page", "note": "[more: the next page is https://example.org/blog/page/2/]",
                       "url": "https://example.org/blog/page/2/"}]
    assert r.text.rstrip().endswith("[more: the next page is https://example.org/blog/page/2/]")
    assert r.page_html is None  # the HTML is never returned


def test_fetch_without_findings_is_unchanged(monkeypatch):
    _curl(monkeypatch, _page(""))
    r = unlocker.fetch(URL, backends=["curl_cffi"], use_memory=False)
    assert r.next_url is None and r.more == []
    assert "[" not in r.text.splitlines()[-1]


def test_mcp_read_url_reports_next_url(monkeypatch):
    from searchts.integrations import mcp_server

    html = _page("", head='<link rel="next" href="/blog/page/2/">')
    _curl(monkeypatch, html)
    monkeypatch.setattr("searchts.ssrf.guard_mcp_url", lambda url, **kw: None)
    real_fetch = unlocker.fetch
    monkeypatch.setattr(unlocker, "fetch", lambda url, **kw: real_fetch(url, backends=["curl_cffi"], use_memory=False))
    data = json.loads(mcp_server.read_url(URL))
    assert data["next_url"] == "https://example.org/blog/page/2/"
    assert data["more"][0]["kind"] == "next-page"


# ── next-page follow-up: links that name themselves, and links that are another document ──


def test_bing_style_next_page_label_without_rel_or_pager_class():
    pager = (
        '<nav role="navigation" aria-label="More results for test"><ul class="sb_pagF">'
        '<li><a class="sb_pagS" aria-current="page">1</a></li>'
        '<li><a href="/search?q=test&amp;first=11" aria-label="Page 2">2</a></li>'
        '<li><a class="sb_pagN" href="/search?q=test&amp;first=11&amp;FORM=PORE" title="Next page" '
        'aria-label="Next page"><div class="sw_next"></div></a></li></ul></nav>'
    )
    found = more.detect(_page(pager), "https://www.bing.com/search?q=test", "t")
    assert found[0].url == "https://www.bing.com/search?q=test&first=11&FORM=PORE"


def test_google_style_next_text_in_a_page_number_table():
    pager = (
        '<div role="navigation"><table><tr><td><span>1</span></td>'
        '<td><a href="/search?q=x&amp;start=10">2</a></td><td><a href="/search?q=x&amp;start=20">3</a></td>'
        '<td><a id="pnnext" href="/search?q=x&amp;start=10"><span>Next</span></a></td></tr></table></div>'
    )
    found = more.detect(_page(pager), "https://www.google.com/search?q=x", "t")
    assert found[0].url == "https://www.google.com/search?q=x&start=10"


def test_wordpress_next_post_links_are_not_a_next_page():
    head = "<link rel='next' title='Another post' href='https://example.org/2026/09/another-post/' />"
    nav = (
        '<nav class="navigation post-navigation" aria-label="Posts"><div class="nav-links">'
        '<div class="nav-next"><a href="/2026/09/another-post/" rel="next">Another post</a></div></div></nav>'
    )
    found = more.detect(_page(nav, head=head), "https://example.org/2026/09/this-post/", "t")
    assert "next-page" not in _kinds(found)


def test_wordpress_multi_page_post_is_a_next_page():
    head = '<link rel="next" href="https://example.org/2026/09/long-post/2/" />'
    found = more.detect(_page("", head=head), "https://example.org/2026/09/long-post/", "t")
    assert found[0].url == "https://example.org/2026/09/long-post/2/"


def test_docs_next_chapter_is_another_document():
    head = '<link rel="next" title="Chapter 2" href="chapter2.html" />'
    found = more.detect(_page("", head=head), "https://docs.example.org/guide/intro.html", "t")
    assert "next-page" not in _kinds(found)


def test_a_thousand_links_stay_fast():
    import time

    rows = "".join(f"<tr><td><a href='/r/{i}'>{i % 100}</a></td><td>cell text {i}</td></tr>" for i in range(1500))
    html = _page(f"<table><tbody>{rows}</tbody></table>")
    started = time.monotonic()
    more.detect(html, URL, "t")
    assert time.monotonic() - started < 2.0


# ── Bing redirect host check ─────────────────────────────────────────────────

_EVIL = "a1aHR0cHM6Ly9ldmlsLmV4YW1wbGUv"  # "https://evil.example/"
_PYPI = "a1aHR0cHM6Ly9weXBpLm9yZy9wcm9qZWN0L3NlYXJjaHRzLw"  # "https://pypi.org/project/searchts/"


@pytest.mark.parametrize(
    "url",
    [
        f"https://notbing.com/ck/a?!&&p=abc&u={_EVIL}&ntb=1",
        f"https://bing.com.attacker.net/ck/a?!&&p=abc&u={_EVIL}&ntb=1",
        f"https://www.bing.com.attacker.net/ck/a?!&&p=abc&u={_EVIL}&ntb=1",
    ],
)
def test_lookalike_hosts_are_not_treated_as_bing(url):
    assert more._clean_item_url(url) == url  # left as written, never decoded


@pytest.mark.parametrize(
    "url",
    [
        f"https://bing.com/ck/a?!&&p=abc&u={_PYPI}&ntb=1",
        f"https://www.bing.com/ck/a?!&&p=abc&u={_PYPI}&ntb=1",
        f"https://WWW.Bing.com:443/ck/a?!&&p=abc&u={_PYPI}&ntb=1",
    ],
)
def test_bing_and_its_subdomains_are_decoded(url):
    assert more._clean_item_url(url) == "https://pypi.org/project/searchts/"

