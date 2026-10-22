# -*- coding: utf-8 -*-
"""F24: fidelity on a site nothing special-cases, from signals in the page.

Every fixture here is hand-written. No real host's markup is copied in: the
point of F24 is that the page says what is wrong with the read, so a test that
needed a site's own class names would be testing the site.
"""

from __future__ import annotations

import pytest

from searchts import expand, more, unlocker
from searchts.session_cookies import CookieRecord

URL = "https://example.org/article/"

#: Ordinary prose, long enough that a real body is made of it.
SENT = (
    "The committee met on Tuesday to hear what the engineers had found in the "
    "second week of measurements, and nobody expected the numbers to be so far "
    "apart from what the model had predicted. "
)


def _prose(paras: int, size: int = 1) -> str:
    return "".join(f"<p>{SENT * size}Paragraph {i}.</p>" for i in range(paras))


def _page(inner: str = "", head: str = "") -> str:
    return (
        f"<html><head>{head}</head><body><main><article><h1>A page</h1>"
        f"{_prose(40)}{inner}</article></main></body></html>"
    )


def _kept(size: int) -> str:
    """A read that kept ``size`` paragraphs worth of the body."""
    return "".join(f"{SENT}Paragraph {i}." for i in range(size))


def _share(html: str, text: str):
    return [m.note for m in more.detect(html, URL, text) if m.kind == "share"]


def _number_after(note: str, word: str) -> int:
    """The first number in ``note`` that follows ``word``."""
    tail = note.split(word, 1)[1].lstrip()
    digits = ""
    for ch in tail:
        if ch.isdigit() or ch in ",.":
            digits += ch
        elif digits:
            break
    return int(digits.replace(",", ""))


# ── the read kept far less of the page than the page holds ───────────────────


def test_a_third_of_the_page_says_so_with_both_numbers():
    found = more.short_read(more._parse(_page()), _kept(10))
    assert found is not None and found.kind == "share"
    assert _number_after(found.note, "kept") < _number_after(found.note, "of")
    assert "characters are in blocks this read did not return" in found.note
    assert _share(_page(), _kept(10)) == [found.note]


def test_the_numbers_are_the_page_and_the_read_not_a_guess():
    doc = more._parse(_page())
    have = more.page_text_chars(doc)
    text = _kept(10)
    found = more.short_read(doc, text)
    assert f"[kept {more.plain_len(text):,} of {have:,} characters" in found.note


def test_a_complete_read_says_nothing():
    assert _share(_page(), _kept(40)) == []


def test_chrome_around_the_content_is_not_content_lost():
    nav = "".join(
        f'<li><a href="/s/{i}">Section number {i} with a long name</a></li>' for i in range(60)
    )
    html = (
        f"<html><body><nav><ul>{nav}</ul></nav><aside>{_prose(40)}</aside>"
        f"<main><h1>A page</h1>{_prose(40)}</main><footer>{_prose(40)}</footer></body></html>"
    )
    # A page carrying 8,000 characters of navigation, side panel and footer next
    # to a 5,000-character article, read whole. Nothing was lost to the
    # extractor, so the numbers must not say it was.
    assert _share(html, _kept(40)) == []


def test_a_small_page_is_not_a_short_read():
    html = f"<html><body><main><article><h1>Small</h1>{_prose(3)}</article></main></body></html>"
    assert more.page_text_chars(more._parse(html)) < more._GAP_MIN_REGION_CHARS
    assert _share(html, "One line of the article.") == []


def test_a_big_page_with_a_small_gap_is_not_a_short_read():
    # 90% kept: over the share line, and few characters left behind.
    assert _share(_page(), _kept(36)) == []


def test_a_read_longer_than_the_page_says_nothing():
    assert _share(_page(), _kept(90)) == []


@pytest.mark.parametrize(
    "tail",
    [
        "This sentence ends properly.",
        "By A. Writer, 17 October 2026",
        "## A heading the extract left last",
        "",
    ],
)
def test_no_mid_sentence_clause_when_the_read_ends_cleanly(tail):
    notes = _share(_page(), _kept(10) + (f"\n\n{tail}" if tail else ""))
    assert notes, "the short-read note still fires"
    assert "mid-sentence" not in notes[0]


def test_a_read_that_stops_mid_sentence_says_so():
    notes = _share(_page(), _kept(10) + " and then the extract ran out of page in the")
    assert "mid-sentence" in notes[0]


def test_the_note_is_a_note_not_a_refusal(monkeypatch):
    """The read that lost the second half still returns the first, with the note."""
    monkeypatch.setattr(
        unlocker,
        "_fetch_curl_cffi",
        lambda url, **kw: (200, _article_with_cards(), url, {}),
    )
    result = unlocker.fetch(URL, backends=["curl_cffi"], use_memory=False, progress=False)
    assert result.status == 200
    assert "The committee met on Tuesday" in result.text
    assert "characters are in blocks this read did not return" in result.text
    assert [m["kind"] for m in result.more if m["kind"] == "share"]


def test_the_short_read_is_named_in_the_summary():
    assert more.summary(more.detect(_page(), URL, _kept(10))) == "more: short read"


def test_broken_html_does_not_break_the_walk():
    assert more.short_read(more._parse("<html><body><main>"), "text") is None
    assert more.page_text_chars(more._parse("")) == 0


def test_the_measure_is_the_same_one_the_extractor_uses():
    """Both sides of the share are counted the same way, or the share is a lie."""
    markdown = "Read [the docs](https://example.org/docs) and `pip install x` now."
    assert more.plain_len(markdown) == len("Read the docs and pip install x now.")
    assert unlocker._plain_len(markdown) == more.plain_len(markdown)


# ── a list page whose prose the extract dropped ──────────────────────────────


def _cards(n: int) -> str:
    return "".join(
        f'<article class="card"><h3>Story number {i} about something real</h3>'
        f"<p>{SENT}</p><span>2 hours ago</span></article>"
        for i in range(n)
    )


def _card_read(n: int, prose_paras: int = 0) -> str:
    out = "".join(f"Story number {i} about something real\n\n{SENT}2 hours ago\n\n" for i in range(n))
    return out + "".join(f"{SENT}Paragraph {i}.\n\n" for i in range(prose_paras))


def test_a_page_whose_prose_the_list_extract_dropped_says_so():
    html = f"<html><body><main>{_prose(16)}{_cards(12)}</main></body></html>"
    notes = _share(html, _card_read(12))
    assert notes and "blocks this read did not return" in notes[0]


def test_the_same_page_read_whole_says_nothing():
    html = f"<html><body><main>{_prose(16)}{_cards(12)}</main></body></html>"
    assert _share(html, _card_read(12, prose_paras=16)) == []


# ── the shape the scorecard measured: the article reads, the page is bigger ──


def _article_with_cards() -> str:
    """One complete article and a second section of cards inside the same main.

    This is the front-page and wire-service shape with no host in it: the
    extractor keeps the article and drops the cards, which is a reasonable call
    and still leaves a person looking at half the page.
    """
    article = f"<article><h1>A page</h1>{_prose(20)}</article>"
    cards = "".join(
        f'<div class="card"><h3>Card number {i} with a headline</h3><p>{SENT}</p></div>'
        for i in range(20)
    )
    return f"<html><body><main>{article}<section>{cards}</section></main></body></html>"


def test_a_real_read_on_that_page_is_half_the_page_and_says_so(monkeypatch):
    html = _article_with_cards()
    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", lambda url, **kw: (200, html, url, {}))
    result = unlocker.fetch(URL, backends=["curl_cffi"], use_memory=False, progress=False)
    share = [m for m in result.more if m["kind"] == "share"]
    assert share, result.text[-400:]
    kept = more.plain_len(result.text.split("[kept")[0])
    have = more.page_text_chars(more._parse(html))
    assert kept < 0.55 * have
    assert f"of {have:,} characters" in share[0]["note"]


# ── one fold label family, shared with what --expand presses ─────────────────


def _fold_page(labels: tuple) -> str:
    buttons = "".join(f'<button type="button">{label}</button>' for label in labels)
    return f"<html><body><main><h1>A page</h1>{_prose(40)}{buttons}</main></body></html>"


@pytest.mark.parametrize("label", ["Read more", "Show more", "Show all reviews", "View all files"])
def test_a_control_that_says_the_rest_is_behind_it_is_a_fold(label):
    count, first = more._folds(more._parse(_fold_page((label,))))
    assert count == 1 and first == label


@pytest.mark.parametrize(
    "label",
    [
        "Show Search",  # the phrase has to come first
        "load()",  # no space after the verb
        "See also",
        "Open source",
        "Continue reading",  # a paywall, named elsewhere and never pressed
    ],
)
def test_a_control_that_does_not_say_it_is_not_a_fold(label):
    assert more._folds(more._parse(_fold_page((label,)))) == (0, "")


def test_every_fold_the_note_names_is_one_expand_would_press():
    """The note and the feature have to be the same list, or the note lies."""
    labels = ("Read more", "Show more", "Show all reviews", "View all files", "Show Search", "See also")
    html = _fold_page(labels)
    count, _first = more._folds(more._parse(html))
    eligible, first = expand.eligible_labels(html)
    assert count == 4, "Show Search and See also are not folds"
    assert eligible == 4 and first == "Read more"


def test_the_label_policy_is_one_object():
    assert more._FOLD_ANY_RE is expand.EXPAND_RE
    assert more._FOLD_RE is expand.EXPAND_EXACT_RE


def test_a_disclosure_named_like_a_fold_is_still_opened_in_the_markup():
    """``prepare_panels`` un-hides panels, and must not skip one over the label.

    The wide family exists to count folds. It must not reach the pass that
    opens hidden answers, or a docs page's hidden table stops being read.
    """
    html = (
        "<html><body><main><h2>Support</h2>"
        '<button aria-expanded="false" aria-controls="bc">See full compatibility</button>'
        '<table id="bc"><tr><td>Chrome 120</td><td>yes</td></tr></table></main></body></html>'
    )
    opened = more.prepare_panels(html)
    assert "display:none" not in opened
    assert "See full compatibility" in opened


def test_the_note_counts_every_fold_on_the_page():
    html = _fold_page(("Show more", "Show all reviews", "Show all reviews", "Show all accessories"))
    notes = [m.note for m in more.detect(html, URL, _kept(40)) if m.kind == "fold"]
    assert notes == [
        '[folded: 4 controls like "Show more" on the page; the text behind them may be missing; --expand (MCP expand) opens them]'
    ]


# ── F24d: the space next to inline code or bold ──────────────────────────────


@pytest.mark.parametrize(
    "before, after",
    [
        ("Run `searchts`read a page.", "Run `searchts` read a page."),
        ("Use `a`and `b`or it.", "Use `a` and `b` or it."),
        ("Set `--items`for the count.", "Set `--items` for the count."),
        ("**bold**text follows.", "**bold** text follows."),
        ("__bold__text follows.", "__bold__ text follows."),
        ("**bold** and `code`x", "**bold** and `code` x"),
    ],
)
def test_a_missing_space_comes_back(before, after):
    assert more.space_after_inline(before) == after


@pytest.mark.parametrize(
    "same",
    [
        "**bold** and more",
        "`code` alone",
        "`code`. And `code`, and `code`;",
        "plain prose with no inline markup at all",
        "a `code` span\n\non its own line",
        "`x`**bold**",
        "",
    ],
)
def test_text_that_is_already_right_is_left_alone(same):
    assert more.space_after_inline(same) == same


def test_code_inside_a_fence_is_never_touched():
    """A fence is code the page wrote on purpose, glued or not."""
    fenced = "text\n\n```python\nfoo`bar and x**y\n```\n\nafter `x`y"
    out = more.space_after_inline(fenced)
    assert "foo`bar and x**y" in out
    assert "after `x` y" in out


def test_a_code_span_is_never_edited_from_the_inside():
    assert more.space_after_inline("`foo bar`baz") == "`foo bar` baz"
    assert more.space_after_inline("`foo  bar`x") == "`foo  bar` x"


def test_the_extract_path_runs_the_fix():
    html = (
        "<html><body><main><p>Run <code>searchts</code>read a page and it works."
        + _prose(6) + "</p></main></body></html>"
    )
    assert "`searchts` read" in unlocker.html_to_text(html, URL)


# ── F24b: the page's own JSON-LD ─────────────────────────────────────────────


def _ld(payload: str, inner: str = "") -> str:
    return f'<html><body><main>{inner}</main><script type="application/ld+json">{payload}</script></body></html>'


def _body_words(n: int) -> str:
    return " ".join(f"word{i}" for i in range(n))


def test_a_shell_page_is_read_from_its_own_data():
    body = _body_words(1_500)
    html = _ld(
        '{"@context":"https://schema.org","@type":"NewsArticle",'
        '"headline":"The finding of the week","articleBody":"' + body + '"}',
        '<div id="root"></div>',
    )
    data = more.structured_text(html)
    assert data.startswith("# The finding of the week")
    assert data.endswith("word1499")
    read = unlocker.html_to_text(html, URL)
    assert "word1499" in read
    assert len(read) > 1_500


def test_a_page_that_reads_well_keeps_its_own_text():
    """The data is a copy of what the extractor already had: nothing changes."""
    prose = _kept(6).replace("\n\n", " ")
    html = _ld(
        '{"@type":"Article","headline":"A page","articleBody":"' + prose + '"}',
        "<article><h1>A page</h1>" + _prose(6) + "</article>",
    )
    read = unlocker.html_to_text(html, URL)
    assert read.count(_body_words(2)) == 0
    assert "Paragraph 3" in read


def test_an_faq_reads_from_the_page_data():
    payload = (
        '{"@type":"FAQPage","mainEntity":[{"@type":"Question","name":"How long does it take?",'
        '"acceptedAnswer":{"@type":"Answer","text":"' + _body_words(400) + '"}},'
        '{"@type":"Question","name":"Is it free?","acceptedAnswer":{"@type":"Answer","text":"'
        + _body_words(300) + '"}}]}'
    )
    read = unlocker.html_to_text(_ld(payload, '<div id="root"></div>'), URL)
    assert "## How long does it take?" in read
    assert "## Is it free?" in read
    assert _body_words(300) in read


def test_a_recipe_reads_ingredients_and_directions_from_the_page_data():
    payload = (
        '{"@type":"Recipe","name":"A stew","recipeIngredient":["water","salt","a root vegetable"],'
        '"recipeInstructions":[{"@type":"HowToStep","text":"' + _body_words(300) + '"},'
        '{"@type":"HowToStep","text":"' + _body_words(300) + '"}]}'
    )
    read = unlocker.html_to_text(_ld(payload, '<div id="root"></div>'), URL)
    assert "## Ingredients" in read and "- water" in read
    assert "## Directions" in read and "1. word0" in read and "2. word0" in read


def test_a_discussion_reads_the_post_and_its_comments():
    payload = (
        '{"@type":"DiscussionForumPosting","headline":"A thread",'
        '"text":"' + _body_words(400) + '","comment":[{"@type":"Comment","text":"'
        + _body_words(200) + '"}]}'
    )
    read = unlocker.html_to_text(_ld(payload, '<div id="root"></div>'), URL)
    assert read.startswith("# A thread")
    assert read.count("> word0") == 1


@pytest.mark.parametrize(
    "wall",
    [
        '<div class="paywall"><p>Continue reading</p></div>',
        '<div class="paywall"><p>This story is for subscribers</p></div>',
        '<div class="paywall"><p>Subscribe to read further</p></div>',
    ],
)
def test_a_paywalled_page_never_reads_its_data_body(wall):
    """The body in the markup is the copy the wall is charging for."""
    payload = '{"@type":"NewsArticle","headline":"A paid story","articleBody":"' + _body_words(1_500) + '"}'
    html = _ld(payload, wall)
    assert more.structured_text(html) == ""
    assert more._pays_for_the_rest(html)


def test_structured_data_that_is_not_a_body_is_ignored():
    payload = '{"@type":"Organization","name":"A company","url":"https://example.org"}'
    assert more.structured_text(_ld(payload)) == ""
    assert more.structured_text(_ld('{"@type":"NewsArticle","description":"' + _body_words(600) + '"}')) == ""


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "<html><body>no data here</body></html>",
        '<script type="application/ld+json">{not json</script>',
        '<script type="application/ld+json">[]</script>',
        '<script type="application/ld+json">"a string"</script>',
        '<script type="application/ld+json">{"@type":"NewsArticle","articleBody":null}</script>',
    ],
)
def test_bad_or_empty_data_never_raises(bad):
    html = f"<html><body><main><p>{_kept(3)}</p></main>{bad}</body></html>"
    assert "Paragraph 2" in unlocker.html_to_text(html, URL)


def test_the_data_is_read_from_the_bytes_already_downloaded(monkeypatch):
    """One request, not two: the fence is the whole point of this box."""
    calls: list = []
    body = _body_words(1_500)
    html = _ld(
        '{"@type":"NewsArticle","headline":"A shell","articleBody":"' + body + '"}',
        '<div id="root"></div>',
    )

    def _one_call(url, **kwargs):
        calls.append(url)
        return 200, html, url, {}

    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", _one_call)
    result = unlocker.fetch(URL, backends=["curl_cffi"], use_memory=False)
    assert len(calls) == 1
    assert body[:200] in result.text


def test_the_faq_answers_a_read_already_had_are_not_double_counted():
    """A page whose markup carries the answers reads once, from the markup."""
    questions = "".join(
        f"<details><summary>Question {i} about the thing</summary>"
        f"<p>{_body_words(200)}</p></details>"
        for i in range(6)
    )
    payload = (
        '{"@type":"FAQPage","mainEntity":[{"@type":"Question","name":"Question 0 about the thing",'
        '"acceptedAnswer":{"@type":"Answer","text":"' + _body_words(200) + '"}}]}'
    )
    html = _ld(payload, questions)
    read = unlocker.html_to_text(html, URL)
    assert read.count(_body_words(200)) == 6





# ── F24c: one line saying where the page came from ────────────────────────────


def _meta_page(head: str, inner: str = "") -> str:
    return f"<html><head>{head}</head><body><main><h1>A page</h1>{_prose(40)}{inner}</main></body></html>"


def _context(html: str) -> str:
    return more.context_line(more._parse(html), html, URL)


def test_the_line_says_the_site_the_author_and_the_date():
    html = _meta_page(
        '<meta property="og:site_name" content="The Gazette">'
        '<meta property="article:section" content="U.S. News">'
        '<meta name="author" content="A. Writer">'
        '<meta property="article:published_time" content="2026-10-17T09:30:00Z">'
    )
    assert _context(html) == "[page: The Gazette · U.S. News · by A. Writer · 2026-10-17]"


def test_the_line_is_built_from_the_data_when_the_meta_tag_lies():
    """A CMS ``article:section`` read "tags" while the page's own data said "security"."""
    payload = (
        '{"@type":"NewsArticle","headline":"A story","articleSection":"security",'
        '"author":{"@type":"Person","name":"B. Writer"},'
        '"datePublished":"2026-10-16T18:00:00-04:00"}'
    )
    html = _meta_page(
        '<meta property="og:site_name" content="A Magazine">'
        '<meta property="article:section" content="tags">' + f"{payload}"
    ).replace("</main>", f'<script type="application/ld+json">{payload}</script></main>')
    assert _context(html) == "[page: A Magazine · security · by B. Writer · 2026-10-16]"


def test_a_page_that_states_one_thing_gets_no_line():
    html = _meta_page('<meta property="og:site_name" content="The Gazette">')
    assert _context(html) == ""


def test_a_page_that_states_nothing_gets_no_line():
    assert _context(_meta_page("")) == ""


def test_the_site_is_never_guessed_from_the_url():
    """The caller already has the URL; repeating it is not context."""
    html = _meta_page('<meta name="author" content="A. Writer">')
    assert "example.org" not in _context(html)
    assert _context(html) == ""


@pytest.mark.parametrize(
    "key, value",
    [
        ("article:author", "https://example.org/staff/a-writer"),
        ("og:article:author", "https://example.org/people/a"),
        ("byl", "https://example.org/by/a"),
    ],
)
def test_an_author_that_is_a_url_is_not_an_author(key, value):
    html = _meta_page(
        '<meta property="og:site_name" content="The Gazette">'
        f'<meta name="{key}" content="{value}">'
    )
    assert "by " not in _context(html)


def test_a_field_the_page_repeats_is_not_printed_twice():
    html = _meta_page(
        '<meta property="og:site_name" content="The Gazette">'
        '<meta name="author" content="The Gazette">'
    )
    assert _context(html) == ""


def test_a_field_longer_than_a_name_is_left_out():
    html = _meta_page(
        '<meta property="og:site_name" content="The Gazette">'
        f'<meta name="author" content="{"A. Writer " * 40}">'
    )
    assert _context(html) == ""


def test_the_line_is_the_first_note_a_read_prints(monkeypatch):
    html = (
        _meta_page(
            '<meta property="og:site_name" content="The Gazette">'
            '<meta property="article:published_time" content="2026-10-17">'
        )
    )
    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", lambda url, **kw: (200, html, url, {}))
    result = unlocker.fetch(URL, backends=["curl_cffi"], use_memory=False)
    notes = result.text.rsplit("\n\n", 1)[1].splitlines()
    assert notes[0] == "[page: The Gazette · 2026-10-17]"
    assert result.more[0] == {"kind": "context", "note": notes[0]}


def test_the_line_appears_in_the_summary_and_never_raises():
    html = _meta_page('<meta property="og:site_name" content="The Gazette"><meta name="author" content="A">')
    assert more.summary(more.detect(html, URL, _kept(40))) == "more: context"
    assert more.context_line(None, "", URL) == ""
    assert more.context_line(more._parse("<html><body><main>x"), "", "") == ""


def test_a_data_field_that_is_a_list_gives_its_first_name():
    """A list of sections is one section, not the string "['a', 'b']"."""
    payload = '{"@type":"NewsArticle","articleSection":["U.S. News","World"],"datePublished":"2026-10-17"}'
    html = _meta_page('<meta property="og:site_name" content="A Wire">').replace(
        "</main>", f'<script type="application/ld+json">{payload}</script></main>'
    )
    assert _context(html) == "[page: A Wire · U.S. News · 2026-10-17]"


# ── F24a: the media in the main content ───────────────────────────────────────


def _media_note(inner: str, base: str = URL) -> str:
    html = f"<html><body><main><h1>A page</h1>{_prose(40)}{inner}</main></body></html>"
    notes = [m.note for m in more.detect(html, base, _kept(40)) if m.kind == "media"]
    return notes[0] if notes else ""


def test_media_in_the_content_is_listed_with_its_addresses():
    note = _media_note(
        '<figure><img src="/img/one.jpg" alt="One"><figcaption>One</figcaption></figure>'
        '<iframe src="https://player.example.org/v/1"></iframe>'
        '<video src="/clip/two.mp4"></video>'
    )
    assert note == (
        "[media: 1 image, 1 video, 1 embed in the main content: "
        "https://example.org/img/one.jpg, https://player.example.org/v/1, "
        "https://example.org/clip/two.mp4. searchts get fetches one of these.]"
    )


def test_a_lazy_image_is_found_wherever_the_address_is():
    note = _media_note('<img data-src="https://cdn.example.org/lazy.jpg" alt="">')
    assert "https://cdn.example.org/lazy.jpg" in note


def test_a_srcset_gives_its_largest_candidate():
    note = _media_note('<img srcset="/a.jpg 480w, /b.jpg 800w" alt="Two">')
    assert "https://example.org/b.jpg" in note
    assert "a.jpg" not in note


def test_a_protocol_relative_address_becomes_a_full_one():
    note = _media_note('<img src="//cdn.example.org/x.jpg" alt="">')
    assert "https://cdn.example.org/x.jpg" in note


def test_media_nobody_can_see_is_not_media_in_the_content():
    note = _media_note(
        '<iframe src="https://tracker.example.org/ns.html" style="display:none"></iframe>'
        '<img src="/pixel.gif" width="1" height="1">'
        '<video src="/clip.mp4" hidden></video>'
    )
    assert note == ""


def test_media_in_page_chrome_is_not_the_content():
    html = (
        "<html><body><header><img src='/logo.svg' alt='Logo'></header>"
        f"<main><h1>A page</h1>{_prose(40)}<img src='/in-main.jpg' alt='In main'></main></body></html>"
    )
    notes = [m.note for m in more.detect(html, URL, _kept(40)) if m.kind == "media"]
    assert len(notes) == 1 and "in-main.jpg" in notes[0] and "logo.svg" not in notes[0]


def test_a_picture_does_not_count_its_sources_as_more_images():
    """Measured: 658 ``source`` children against 112 pictures on a front page."""
    html = _media_note(
        "<picture><source srcset='/a.webp 1x'><source srcset='/b.webp 2x'>"
        '<img src="/a.png" alt="A"></picture><video src="/clip.mp4"><source src="/clip.webm"></video>'
    )
    assert html == (
        "[media: 1 image, 1 video in the main content: "
        "https://example.org/a.png, https://example.org/clip.mp4. "
        "searchts get fetches one of these.]"
    )


def test_media_with_no_address_says_it_is_not_resolved():
    html = (
        "<html><body><main><h1>A page</h1>"
        f"{_prose(40)}<iframe></iframe><img alt='A picture with no source at all'></main></body></html>"
    )
    notes = [m.note for m in more.detect(html, URL, _kept(40)) if m.kind == "media"]
    assert notes == ["[media: 1 image, 1 embed in the main content; media present, not resolved]"]


def test_a_page_with_no_media_has_no_media_note():
    assert _media_note("<p>Words only.</p>") == ""


def test_the_note_never_lists_more_than_four_addresses():
    images = "".join(f'<img src="/img/{i}.jpg" alt="Image {i}">' for i in range(30))
    note = _media_note(images)
    assert note.count("https://example.org/img/") == 4
    assert note.endswith(
        "and 26 more. searchts get fetches one of these. "
        "--media N (MCP max_media) lists more here, ceiling 40; "
        "searchts grab saves the files.]"
    )
    assert "[media: 30 images" in note


def test_a_higher_media_limit_lists_more_addresses():
    images = "".join(f'<img src="/img/{i}.jpg" alt="Image {i}">' for i in range(12))
    html = f"<html><body><main><h1>A page</h1>{_prose(40)}{images}</main></body></html>"
    notes = [m.note for m in more.detect(html, URL, _kept(40), media_limit=10) if m.kind == "media"]
    assert len(notes) == 1
    assert notes[0].count("https://example.org/img/") == 10
    assert "and 2 more" in notes[0]
    assert "--media N" in notes[0] and "searchts grab" in notes[0]


def test_media_limit_resolves_from_the_flag_and_the_config(monkeypatch):
    monkeypatch.delenv("SEARCHTS_MAX_MEDIA", raising=False)
    monkeypatch.setattr(more, "_configured_media_default", lambda: 4)
    assert more.resolve_media_limit(None) == (4, None)
    assert more.resolve_media_limit(0) == (4, None)
    assert more.resolve_media_limit(12) == (12, None)
    limit, note = more.resolve_media_limit(200)
    assert limit == 40
    assert note == "[media: asked for 200, the ceiling is 40]"
    monkeypatch.setattr(more, "_configured_media_default", lambda: 20)
    assert more.resolve_media_limit(None) == (20, None)


def test_the_media_note_is_carried_on_the_read(monkeypatch):
    html = f"<html><body><main><h1>A page</h1>{_prose(40)}<img src='/photo.jpg' alt='A photo'></main></body></html>"
    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", lambda url, **kw: (200, html, url, {}))
    result = unlocker.fetch(URL, backends=["curl_cffi"], use_memory=False)
    assert (
        "[media: 1 image in the main content: https://example.org/photo.jpg. "
        "searchts get fetches one of these.]"
    ) in result.text
    assert [m["kind"] for m in result.more if m["kind"] == "media"]
    assert "media" in more.summary(more.detect(html, URL, _kept(40)))


# ── the two hints: a login wall, and a page only a browser can read ───────────


def _app_shell_page() -> str:
    return (
        "<html><body><noscript>You need to enable JavaScript to run this app.</noscript>"
        '<div id="root"></div><script src="/static/js/main.js"></script>'
        "<script>window.__NEXT_DATA__ = {};</script></body></html>"
    )


def test_a_shell_that_serves_no_text_is_named_as_a_js_app(monkeypatch):
    from searchts import scroll

    monkeypatch.setattr(scroll, "browser_available", lambda: False)
    monkeypatch.setattr(
        unlocker, "_fetch_curl_cffi", lambda url, **kw: (200, _app_shell_page(), url, {})
    )
    with pytest.raises(unlocker.UnlockerError) as raised:
        unlocker.fetch(
            "https://example.org/app/post/1", backends=["curl_cffi"],
            use_memory=False, progress=False,
        )
    hint = raised.value.hint
    assert "this page is a JS app" in hint
    assert "no cookies" in hint
    assert "searchts install --browser" in hint


def test_the_js_app_hint_does_not_claim_a_browser_is_the_fix_when_one_ran(monkeypatch):
    from searchts import scroll

    monkeypatch.setattr(scroll, "browser_available", lambda: True)
    hint = unlocker._app_shell_hint()
    assert "did not manage this page either" in hint
    assert "install --browser" not in hint


@pytest.mark.parametrize(
    "body, text",
    [
        ("<html><body><p>Short but whole.</p></body></html>", "Short but whole."),
        ("<html><body><main>" + _prose(4) + "</main></body></html>", _kept(4)),
        ("", ""),
    ],
)
def test_a_thin_page_that_is_not_an_app_is_not_called_one(body, text):
    assert unlocker._is_app_shell(body, text) is False


def test_a_thin_read_that_is_not_an_app_gets_no_hint(monkeypatch):
    monkeypatch.setattr(
        unlocker,
        "_fetch_curl_cffi",
        lambda url, **kw: (200, "<html><body><p>Only this.</p></body></html>", url, {}),
    )
    with pytest.raises(unlocker.UnlockerError) as raised:
        unlocker.fetch(
            "https://example.org/page", backends=["curl_cffi"], use_memory=False
        )
    assert "JS app" not in raised.value.hint


def _big_app_shell() -> str:
    """The measured video-page shape: megabytes of script, a mount, little text.

    Measured on a real video page: 1.4 MB of HTML and 234 characters of visible
    text. This fixture keeps the ratio and names no site.
    """
    machine = "<script>" + "var x=1;" * 20_000 + "</script>"
    return (
        "<html><head><title>A video page</title></head><body>"
        "<div id='stage'></div>"
        + machine
        + "<div id='player'></div>"
        "<footer>About Press Copyright Contact us</footer>"
        "<iframe src='/embed/xyz'></iframe>"
        "</body></html>"
    )


def test_a_big_page_that_shows_no_text_is_an_app_shell():
    html = _big_app_shell()
    assert len(html) > unlocker._APP_SHELL_MIN_HTML
    assert unlocker._is_app_shell(html, "About Press Copyright Contact us") is True


def test_a_big_page_with_its_content_in_the_markup_is_not_an_app_shell():
    html = f"<html><body><main>{_prose(200, size=4)}</main></body></html>"
    assert len(html) > unlocker._APP_SHELL_MIN_HTML
    assert unlocker._is_app_shell(html, "a short extract") is False


def test_a_big_image_page_is_not_called_a_js_app():
    """Little text and no script is a gallery, not an app; F24a names the images."""
    imgs = "".join(f'<img src="/g/{i}.jpg" alt="Photo {i}">' for i in range(4000))
    html = f"<html><body><main>{imgs}</main></body></html>"
    assert len(html) > unlocker._APP_SHELL_MIN_HTML
    assert unlocker._is_app_shell(html, "One caption.") is False


def test_a_real_app_shell_page_gets_the_js_app_hint(monkeypatch):
    from searchts import scroll

    monkeypatch.setattr(scroll, "browser_available", lambda: False)
    monkeypatch.setattr(
        unlocker, "_fetch_curl_cffi", lambda url, **kw: (200, _big_app_shell(), url, {})
    )
    with pytest.raises(unlocker.UnlockerError) as raised:
        unlocker.fetch(
            "https://example.org/watch/1", backends=["curl_cffi"],
            use_memory=False, progress=False,
        )
    assert "this page is a JS app" in raised.value.hint


def test_the_cookie_hint_says_the_browser_tier_gets_no_cookies(monkeypatch):
    monkeypatch.setattr(
        unlocker,
        "_fetch_curl_cffi",
        lambda url, **kw: (200, "<html><body><p>Sign in to continue</p></body></html>", url, {}),
    )
    with pytest.raises(unlocker.UnlockerError) as raised:
        unlocker.fetch(
            "https://example.org/account", backends=["curl_cffi"], use_memory=False,
            cookies=[
                CookieRecord(name="session", value="abc", domain="example.org")
            ],
        )
    hint = raised.value.hint
    assert "browser tier is sent no cookies at all" in hint
    assert "ride the direct request only" in hint


def test_the_login_wall_hint_names_the_fence_on_stderr(capsys):
    from searchts import cli

    cli._print_login_wall_hint("https://example.org/private/page")
    err = capsys.readouterr().err
    assert "the browser tier is sent none of them" in err
    assert "searchts login signin https://example.org/private/page" in err


def test_a_stale_kept_login_says_so_and_still_names_the_fence(capsys, tmp_home):
    from searchts import cli
    from searchts.session_cookies import save_owned_site

    save_owned_site(
        "https://example.org",
        [CookieRecord(name="session", value="abc", domain="example.org")],
    )
    cli._print_login_wall_hint("https://example.org/private/page")
    err = capsys.readouterr().err
    assert "already in the searchts store" in err
    assert "the browser tier is sent none of them" in err


# ── --expand: the HTML count and the browser finder are one list ─────────────

_PARITY_LABELS = [
    "Read more", "Show more", "See all", "View full", "Read the rest",
    "Show all reviews", "See full compatibility", "Show all 42",
    "Show more results", "See more videos", "View all products",
    "Show more posts", "View more news", "Load more",
    "Show Search", "See also", "Open source", "Show more comments",
    "Continue reading", "Read the rest with a subscription",
]


def _browser_verdicts(labels):
    """Run the real _FIND_JS in node against a fake DOM of one button per label."""
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    from searchts import expand

    script = (
        "const labels = %s;\n"
        "const mk = (t) => ({innerText: t, textContent: t, tagName: 'BUTTON',\n"
        "  offsetWidth: 10, offsetHeight: 10, disabled: false,\n"
        "  getClientRects: () => [1], getAttribute: () => null,\n"
        "  closest: () => null, matches: () => true, setAttribute: () => {}});\n"
        "const els = labels.map(mk);\n"
        "const document = {querySelectorAll: () => els};\n"
        "const f = %s;\n"
        "console.log(JSON.stringify(f().map(o => [o.label, o.why])));\n"
    ) % (json.dumps(labels), expand._FIND_JS.replace("() => {", "function () {", 1))
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return {label: why for label, why in json.loads(done.stdout)}


def test_the_browser_finder_and_the_html_count_agree_on_every_label():
    from searchts import expand

    seen = _browser_verdicts(_PARITY_LABELS)
    for label in _PARITY_LABELS:
        python = expand._verdict(label, tag="button", href=None, in_form=False)
        assert seen.get(label, "no") == python, (label, seen.get(label), python)


@pytest.mark.parametrize(
    "label",
    ["Show more results", "See more videos", "View all products", "Show more posts",
     "View more news"],
)
def test_a_feed_control_is_not_a_fold_for_expand(label):
    from searchts import expand

    html = f"<main><p>x</p><button>{label}</button></main>"
    assert expand.eligible_labels(html) == (0, "")
    import lxml.html

    assert more._folds(lxml.html.fromstring(html)) == (0, "")


def test_a_review_fold_is_pressed_by_the_browser_as_well_as_counted():
    from searchts import expand

    assert expand.eligible_labels("<main><button>Show all reviews</button></main>")[0] == 1
    assert _browser_verdicts(["Show all reviews"]) == {"Show all reviews": "yes"}
