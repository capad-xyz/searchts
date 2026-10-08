"""Tests for the S1.1 resource caps.

These exist because of a specific finding: the injection fence handled a
140 MB page correctly and the caller still paid for it. A perfectly marked,
perfectly fenced untrusted string is still 140 MB, so the caps are a separate
defect from the fence rather than part of fixing it.
"""

import time

import pytest

from searchts import unlocker


def test_html_over_the_cap_is_truncated_and_says_so():
    body = "<html><body><p>" + ("word " * 100) + "</p></body></html>"
    capped = unlocker.cap_html(body + "x" * unlocker.MAX_HTML_BYTES)
    assert len(capped) < len(body) + unlocker.MAX_HTML_BYTES
    assert "truncated at" in capped
    assert "was not read" in capped


def test_html_under_the_cap_is_untouched():
    body = "<html><body><p>short</p></body></html>"
    assert unlocker.cap_html(body) is body


def test_text_over_the_cap_is_truncated():
    long_text = "a" * (unlocker.MAX_TEXT_CHARS + 5_000)
    out = unlocker.cap_text(long_text)
    assert len(out) < len(long_text)
    assert out.startswith("a" * 100)
    assert "truncated at" in out


def test_text_under_the_cap_is_untouched():
    text = "ordinary prose"
    assert unlocker.cap_text(text) is text


def test_html_to_text_bounds_a_huge_document():
    """The whole pipeline, not just the helper."""
    big = "<html><body><p>" + ("word " * 6_000_000) + "</p></body></html>"
    assert len(big) > unlocker.MAX_HTML_BYTES
    out = unlocker.html_to_text(big, "https://example.test/")
    # The marker itself is ~90 chars; allow room for it plus slack.
    assert len(out) <= unlocker.MAX_TEXT_CHARS + 200, len(out)
    assert "truncated" in out


def test_extraction_timeout_falls_back_instead_of_hanging(monkeypatch):
    """A hung parse must cost the budget and then give the reader something.

    The crude strip is not as good as trafilatura, but it is a linear regex pass
    over text we already hold, so it always terminates. Returning the article is
    worth more than returning nothing.
    """
    def hang(html, url=None):
        time.sleep(30)
        return "never reached"  # pragma: no cover

    monkeypatch.setattr(unlocker, "_extract_inner", hang)
    monkeypatch.setattr(unlocker, "EXTRACTION_TIMEOUT", 0.5)
    out = unlocker.html_to_text(
        "<html><body><p>Real prose here.</p></body></html>", "https://example.test/"
    )
    assert "Real prose here." in out
    assert "never reached" not in out


def test_timeout_is_reported_not_swallowed(monkeypatch):
    """A caller that wants to know the parse was abandoned can."""
    def hang(html, url=None):
        time.sleep(30)
        return "never reached"  # pragma: no cover

    monkeypatch.setattr(unlocker, "_extract_inner", hang)
    with pytest.raises(unlocker._ExtractionTimeout):
        unlocker._extract_within("<p>x</p>", None, budget=0.4)


def test_a_slow_but_finishing_parse_is_kept(monkeypatch):
    """The budget is a ceiling, not a target. Do not abandon work that will land."""

    def slow(html, url=None):
        time.sleep(0.3)
        return "the good extract"

    monkeypatch.setattr(unlocker, "_extract_inner", slow)
    got = unlocker._extract_within("<p>x</p>", None, budget=5.0)
    assert got == "the good extract"


def test_an_exception_inside_extraction_propagates(monkeypatch):
    """The worker must not swallow a real error into a silent empty result."""

    def boom(html, url=None):
        raise ValueError("upstream library exploded")

    monkeypatch.setattr(unlocker, "_extract_inner", boom)
    with pytest.raises(ValueError, match="exploded"):
        unlocker._extract_within("<p>x</p>", None, budget=5.0)


def test_normal_extraction_still_works():
    html = (
        "<html><body><article><h1>Title</h1><p>"
        + ("Body sentence about a thing. " * 60)
        + "</p></article></body></html>"
    )
    out = unlocker.html_to_text(html, "https://example.test/a")
    assert "Body sentence about a thing." in out
    assert "<p>" not in out