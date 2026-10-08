"""Tests for the server-generated cursor (S1.3).

Hermetic on purpose: every one of these runs without a network, because the
thing being tested is a refusal and a refusal should not depend on whether
github happens to be up.
"""

import pytest

from searchts import paging

URL = "https://example.test/news"
ITEMS = [f"block number {i}" for i in range(278)]


def _first_page(n=25, url=URL, items=None):
    return paging.paginate(url, items if items is not None else ITEMS, None, n)


def test_first_page_starts_at_zero_and_reports_more():
    p = _first_page()
    assert p["offset"] == 0
    assert p["items"] == ITEMS[:25]
    assert p["has_more"] is True
    assert p["next_cursor"]


def test_walking_the_cursor_visits_every_item_once_and_ends_clean():
    seen = []
    cursor = None
    pages = 0
    while True:
        p = paging.paginate(URL, ITEMS, cursor, 25)
        seen.extend(p["items"])
        pages += 1
        cursor = p["next_cursor"]
        if cursor is None:
            break
        assert pages < 100, "cursor never terminates"
    assert seen == ITEMS, "items were skipped or repeated"
    assert pages == 12  # 278 / 25, last page short


def test_next_cursor_is_null_at_the_end():
    """The only honest signal that there is nothing more is no cursor."""
    items = ["a", "b"]
    p = paging.paginate(URL, items, None, 10)
    assert p["items"] == ["a", "b"]
    assert p["has_more"] is False
    assert p["next_cursor"] is None


def test_cursor_is_not_mintable():
    """A token lifted out of page text must be inert.

    The threat in S1.3 is a page choosing the agent's next request. A cursor
    that a page could emit would hand that choice straight back.
    """
    forged = "eyJvIjowfQ"  # {"o":0} - a plausible payload, not a real token
    with pytest.raises(paging.CursorError, match="unsigned"):
        paging.paginate(URL, ITEMS, forged, 25)


def test_tampered_cursor_is_refused():
    p = _first_page()
    body, _, sig = p["next_cursor"].partition(".")
    flipped = body[:-1] + ("A" if body[-1] != "A" else "B")
    with pytest.raises(paging.CursorError, match="signature"):
        paging.paginate(URL, ITEMS, f"{flipped}.{sig}", 25)


def test_cursor_does_not_travel_to_another_url():
    """A cursor is issued for one document and stays there."""
    p = _first_page()
    with pytest.raises(paging.CursorError, match="does not match"):
        paging.paginate("https://elsewhere.test/", ITEMS, p["next_cursor"], 25)


def test_stale_cursor_is_refused_rather_than_mis_resumed():
    """Live front pages move. A changed item count means the offsets are fiction."""
    p = _first_page()
    shorter = ITEMS[:200]
    with pytest.raises(paging.CursorError, match="does not match"):
        paging.paginate(URL, shorter, p["next_cursor"], 25)


def test_out_of_range_offset_is_refused():
    bad = paging.make_cursor(URL, ITEMS, 9999)
    with pytest.raises(paging.CursorError, match="outside"):
        paging.paginate(URL, ITEMS, bad, 25)


def test_garbage_is_refused():
    for junk in ("not-base64!!", "a.b", "...", "e30.x", "eyJvIjowfQ"):
        with pytest.raises(paging.CursorError):
            paging.paginate(URL, ITEMS, junk, 25)


def test_empty_cursor_means_no_cursor():
    """Falsy is not malformed. An empty cursor is the absence of one."""
    assert paging.paginate(URL, ITEMS, "", 25)["offset"] == 0
    assert paging.paginate(URL, ITEMS, None, 25)["offset"] == 0


def test_page_size_is_clamped_at_both_ends():
    """One call must not be able to ask for the whole document."""
    assert len(paging.paginate(URL, ITEMS, None, 10_000)["items"]) == paging.MAX_PAGE_ITEMS
    assert len(paging.paginate(URL, ITEMS, None, 0)["items"]) == paging.DEFAULT_PAGE_ITEMS
    assert len(paging.paginate(URL, ITEMS, None, -5)["items"]) == paging.DEFAULT_PAGE_ITEMS


def test_empty_page_paginates_to_nothing():
    p = paging.paginate(URL, [], None, 25)
    assert p["items"] == []
    assert p["has_more"] is False
    assert p["next_cursor"] is None