# -*- coding: utf-8 -*-
"""F23f: a list page whose extract lost the items is rebuilt from its HTML.

Bing, Hashnode and the Django weblog fixtures are trimmed from real pages
(2026-10-01). Curl got every title, link and date; the extractor did not.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from searchts import more, unlocker
from searchts.unlocker import html_to_text

FIXTURES = Path(__file__).parent / "fixtures"
PARA = "This paragraph carries enough ordinary words to look like the main body of a real article, part {}."


def _index(name: str, url: str):
    html = (FIXTURES / name).read_text(encoding="utf-8")
    return more.list_index(html, url, html_to_text(html, url=url))


def test_sidebar_archive_does_not_beat_the_main_list():
    posts = "".join(
        f'<article class="post"><h3><a href="/p/{i}">Post number {i} on the weblog</a></h3>'
        f"<p>A teaser for post {i} that is long enough to be the item.</p></article>"
        for i in range(10)
    )
    months = "".join(
        f'<li class="month"><a href="/archive/{i}">Month {i} in the archive</a></li>'
        for i in range(24)
    )
    html = (
        f"<html><body><main>{posts}</main>"
        f'<div class="sidebar"><ul>{months}</ul></div></body></html>'
    )
    doc = more._parse(html)
    items = more._best_list(doc)
    assert items is not None
    assert all("/archive/" not in (a.get("href") or "") for a in items[0].xpath(".//a"))
    assert items[0].xpath(".//a[contains(@href, '/p/')]")


def test_a_huge_archive_does_not_drop_the_post_dates():
    posts = "".join(
        f'<article class="post"><h3><a href="/p/{i}">Post number {i} on the weblog</a></h3>'
        f"<p>Posted by Writer {i} on Sept. {i + 1}, 2026</p>"
        f"<p>A teaser for post {i} that is long enough to be the item.</p></article>"
        for i in range(10)
    )
    months = "".join(
        f'<li class="month"><a href="/archive/{y}/{m}">Month {m} of {y}</a></li>'
        for y in range(2004, 2026)
        for m in range(1, 13)
    )
    html = (
        f"<html><body><main>{posts}</main>"
        f'<div class="sidebar"><h2>Archive</h2><ul>{months}</ul></div></body></html>'
    )
    text = "\n\n".join(
        f"Post number {i} on the weblog\n\nA teaser for post {i} that is long enough to be the item."
        for i in range(10)
    )
    rebuilt = more.list_index(html, "https://www.djangoproject.com/weblog/", text)
    assert rebuilt is not None
    md, note = rebuilt
    assert "Posted by Writer 0 on Sept. 1, 2026" in md
    assert "/archive/" not in md
    assert "dates" in note.note


def test_a_headed_side_panel_is_named_and_its_text_stays_out():
    article = "The article " + ("word " * 40)
    card = "task details " * 20
    html = (
        "<html><body><main><article><h1>The article</h1><p>"
        + article
        + "</p></article></main>"
        + '<aside><h2>prommer.net</h2><p>'
        + card
        + "</p></aside>"
        + '<footer><h2>Site footer</h2><p>'
        + ("footer words " * 20)
        + "</p></footer></body></html>"
    )
    found = more.detect(html, "https://example.com/post", article)
    notes = [m.note for m in found if m.kind == "region"]
    assert notes == ['[left out: a side panel headed "prommer.net"]']
    annotated = more.annotate(article, found)
    assert "task details" not in annotated
    assert "Site footer" not in annotated


def test_hacker_news_table_rows_keep_title_link_and_points():
    rows = "".join(
        f'<tr class="athing" id="{i}"><td class="title"><span class="rank">{i}.</span></td>'
        f'<td><span class="titleline"><a href="https://example{i}.com/post">Story {i} about tools</a>'
        f'</span></td></tr><tr><td colspan="2"></td><td class="subtext"><span class="score">{i} points</span> '
        f'by <a href="user?id=u{i}" class="hnuser">u{i}</a> | <a href="item?id={i}">{i} comments</a></td></tr>'
        for i in range(1, 31)
    )
    html = (
        '<html><head><title>Hacker News</title></head><body><table>'
        f'{rows}<tr><td><a href="?p=2" class="morelink" rel="next">More</a></td></tr>'
        '</table></body></html>'
    )
    # The extractor prints the title words and drops the links.
    text = "\n".join(f"Story {i} about tools" for i in range(1, 31))
    rebuilt = more.list_index(html, "https://news.ycombinator.com/", text)
    assert rebuilt is not None
    md, note = rebuilt
    assert "[Story 1 about tools](https://example1.com/post)" in md
    assert "1 points" in md
    assert "u1" in md
    assert note.kind == "index"
    assert "links" in note.note


def test_a_card_list_that_only_lost_its_links_still_has_to_be_the_extract():
    """Titles in the text are not proof. The carve-out is for table rows only."""
    cards = "".join(
        f'<article class="card"><h2><a href="https://example.com/{i}">Story {i} about tools and more words</a></h2>'
        f"<p>{'teaser ' * 20}</p></article>"
        for i in range(8)
    )
    html = f"<html><body><main>{cards}</main></body></html>"
    essay = "This paragraph is a different article and it never mentions those cards. " * 12
    titles = "\n\n".join(f"Story {i} about tools and more words" for i in range(8))
    doc = more._parse(html)
    assert more._best_list(doc) is not None
    assert more.list_index(html, "https://example.com/blog", essay + "\n\n" + titles) is None


def test_a_long_byline_link_is_still_the_detail_row():
    user = "a" * 40
    rows = "".join(
        f'<tr class="athing" id="{i}"><td class="title"><span class="titleline">'
        f'<a href="https://example{i}.com/post">Story {i} about tools</a></span></td></tr>'
        f'<tr><td class="subtext"><span class="score">{i} points</span> by '
        f'<a href="user?id={user}" class="hnuser">{user}</a></td></tr>'
        for i in range(1, 31)
    )
    html = f"<html><body><table>{rows}</table></body></html>"
    text = "\n".join(f"Story {i} about tools" for i in range(1, 31))
    rebuilt = more.list_index(html, "https://news.ycombinator.com/", text)
    assert rebuilt is not None
    md, _note = rebuilt
    assert user in md
    assert "1 points" in md


def test_bing_results_get_titles_and_real_links_back():
    rebuilt = _index("bing_results.html", "https://www.bing.com/search?q=searchts")
    assert rebuilt is not None
    md, note = rebuilt
    assert note.kind == "index"
    assert note.note == "[list: 10 items rebuilt from the page; the extractor dropped their titles and links]"
    assert md.startswith("# searchts - Search\n")
    assert "- [searchts · PyPI](https://pypi.org/project/searchts/)" in md
    assert "- [SearchTS MCP Server by Aadarsh Upadhyay | PulseMCP](https://www.pulsemcp.com/servers/capad-xyz-searchts)" in md
    assert len(re.findall(r"^- \[", md, re.M)) == 10
    assert "bing.com/ck/" not in md  # the redirect is replaced by its target


def test_hashnode_cards_get_links_and_stop_running_together():
    rebuilt = _index("hashnode_tag.html", "https://hashnode.com/tag/web-development")
    assert rebuilt is not None
    md, note = rebuilt
    assert note.note == "[list: 10 items rebuilt from the page; the extractor dropped their links]"
    assert md.startswith("# #web-development\n")
    assert (
        "- [What is MERN Stack? Complete Beginner's Guide 2026]"
        "(https://umercodelabs.hashnode.dev/what-is-mern-stack-complete-beginner-s-guide-2026)" in md
    )
    assert re.search(r"^  Muhammed Umer in umercodelabs\.hashnode\.dev · \d+h ago · 3 min read$", md, re.M)
    assert "utm_" not in md
    assert "Umerinumercodelabs" not in md and not re.search(r"\d00$", md, re.M)


def test_django_weblog_gets_its_dates_back():
    rebuilt = _index("django_weblog.html", "https://www.djangoproject.com/weblog/")
    assert rebuilt is not None
    md, note = rebuilt
    assert note.note == "[list: 10 items rebuilt from the page; the extractor dropped their dates]"
    assert md.startswith("# News & Events\n")
    assert "  Posted by Sarah Abderemane on Sept. 24, 2026" in md.splitlines()
    assert "Read more" not in md
    assert "Upcoming Events" not in md  # the sidebar is not part of the list


def test_byline_written_after_the_heading_is_kept():
    cards = "".join(
        f'<div class="card"><h3><a href="/p/{i}">Post number {i} on list pages</a></h3>'
        f"by Writer {i} on Sep {i + 1}, 2026<p>A teaser for post {i} that runs long enough to be the snippet.</p></div>"
        for i in range(10)
    )
    html = f"<html><body><main><h1>Blog</h1><div class=\"grid\">{cards}</div></main></body></html>"
    text = "\n\n".join(f"Post number {i} on list pages A teaser for post {i} that runs long enough to be the snippet." for i in range(10))
    rebuilt = more.list_index(html, "https://example.org/blog/", text)
    assert rebuilt is not None
    assert "  by Writer 3 on Sep 4, 2026" in rebuilt[0].splitlines()


def test_fetch_puts_the_index_first_and_drops_the_partial_note(monkeypatch):
    html = (FIXTURES / "bing_results.html").read_text(encoding="utf-8")
    url = "https://www.bing.com/search?q=searchts"
    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", lambda u, timeout=30: (200, html, url, {}))
    r = unlocker.fetch(url, backends=["curl_cffi"], use_memory=False)
    assert r.text.startswith("# searchts - Search")
    assert r.more[0]["kind"] == "index"
    assert "[list: 10 items rebuilt from the page" in r.text
    assert "[partial:" not in r.text


def _cards(n: int) -> str:
    return "".join(
        f'<div class="card"><h3><a href="/item/{i}">Story number {i} about something</a></h3>'
        f"<p>A short teaser for story {i} with a few more words.</p></div>"
        for i in range(n)
    )


def test_related_grid_under_an_article_is_left_alone():
    body = "".join(f"<p>{PARA.format(i)} {PARA.format(i + 50)} {PARA.format(i + 90)}</p>" for i in range(12))
    html = (
        f"<html><body><main><article><h1>A long article</h1>{body}</article>"
        f'<section class="related"><div class="grid">{_cards(9)}</div></section></main></body></html>'
    )
    assert more.list_index(html, "https://example.org/a", html_to_text(html, url="https://example.org/a")) is None


def _short_post_beside_a_grid() -> str:
    cards = "".join(
        f'<li class="card"><h3><a href="/posts/{i}">Related story number {i} about the town fair</a></h3>'
        f"<p>A longer teaser for related story {i}, with enough words to look like a real card.</p></li>"
        for i in range(1, 9)
    )
    return (
        "<html><head><title>Store hours</title></head><body><main><article>"
        "<h1>Store hours this week</h1><p>Closed on Monday.</p><p>Back Tuesday at 9.</p>"
        "<p>Thanks, the team.</p></article>"
        f'<section class="related"><h2>More stories</h2><ul>{cards}</ul></section></main></body></html>'
    )


def test_short_article_is_not_replaced_by_a_related_grid():
    # Every paragraph is under the coverage cut-off, so the guard had nothing to measure.
    short = "# Store hours this week\n\nClosed on Monday.\n\nBack Tuesday at 9.\n\nThanks, the team."
    assert more.list_index(_short_post_beside_a_grid(), "https://news.example/hours", short) is None


def test_an_extract_with_no_text_still_gets_the_index():
    out = more.list_index(_short_post_beside_a_grid(), "https://news.example/hours", "")
    assert out is not None and out[1].kind == "index"


def test_list_the_extract_kept_whole_is_left_alone():
    items = "".join(
        f'<li class="entry"><a href="https://example.org/lang/{i}">Language number {i}</a>'
        f" is a programming language from the year {1970 + i} with a long and storied history.</li>"
        for i in range(12)
    )
    html = f"<html><body><main><h1>List of languages</h1><ul>{items}</ul></main></body></html>"
    text = html_to_text(html, url="https://example.org/list")
    assert "https://example.org/lang/3" in text  # the extractor kept the links itself
    assert more.list_index(html, "https://example.org/list", text) is None


def test_article_with_a_comment_list_is_not_replaced():
    body = "".join(f"<p>{PARA.format(i)} {PARA.format(i + 50)}</p>" for i in range(10))
    comments = "".join(
        f'<li class="comment"><a href="/u/{i}">commenter{i}</a> <time>Sep {i + 1}, 2026</time>'
        f"<p>Comment {i}: I agree with most of this and want to add a long thought of my own here.</p></li>"
        for i in range(12)
    )
    html = f"<html><body><main><article><h1>Essay</h1>{body}</article><ol>{comments}</ol></main></body></html>"
    text = "\n\n".join(f"{PARA.format(i)} {PARA.format(i + 50)}" for i in range(10))  # the article only
    assert more.list_index(html, "https://example.org/essay", text) is None


@pytest.mark.parametrize(
    "url, expected",
    [
        (
            "https://www.bing.com/ck/a?!&&p=abc&u=a1aHR0cHM6Ly9weXBpLm9yZy9wcm9qZWN0L3NlYXJjaHRzLw&ntb=1",
            "https://pypi.org/project/searchts/",
        ),
        ("https://www.bing.com/ck/a?!&&p=abc&u=a1%%%&ntb=1", "https://www.bing.com/ck/a?!&&p=abc&u=a1%%%&ntb=1"),
        ("https://x.dev/post?utm_source=hashnode&utm_medium=feed&id=7", "https://x.dev/post?id=7"),
        ("https://x.dev/post", "https://x.dev/post"),
    ],
)
def test_item_urls_lose_redirects_and_tracking(url, expected):
    assert more._clean_item_url(url) == expected
