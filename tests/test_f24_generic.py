# -*- coding: utf-8 -*-
"""F24: fidelity on a site nothing special-cases, from signals in the page.

Every fixture here is hand-written. No real host's markup is copied in: the
point of F24 is that the page says what is wrong with the read, so a test that
needed a site's own class names would be testing the site.
"""

from __future__ import annotations

import pytest

from searchts import expand, more, unlocker

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
        '[folded: 4 controls like "Show more" on the page; the text behind them may be missing]'
    ]


