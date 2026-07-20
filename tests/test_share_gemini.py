# -*- coding: utf-8 -*-
"""Tests for the Gemini share-link extractor (no network).

The conversation is served by a keyless WIZ ``batchexecute`` RPC (``ujx1Bf``),
not the initial HTML. The fixture is a synthetic batchexecute envelope that
mirrors the exact positional structure verified against live share pages
(``root[1]`` = turns, ``root[2][1]`` = title, ``turn[2][0][0]`` = user prompt,
``turn[3][0][0][1][0]`` = model response).
"""

from pathlib import Path

from searchts.share_extractors import ShareResult, matches
from searchts.share_extractors.gemini import (
    PATTERN,
    parse_gemini_batchexecute,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ── URL matching ─────────────────────────────────────────────────────────────


def test_pattern_matches_gemini_share_urls():
    assert PATTERN.match("https://gemini.google.com/share/6d141b742a13")
    assert PATTERN.match("http://gemini.google.com/share/3e672adbc177")
    assert PATTERN.match("https://g.co/gemini/share/abc123def456")
    # group(1) is the share id
    assert PATTERN.match(
        "https://gemini.google.com/share/6d141b742a13").group(1) == "6d141b742a13"


def test_pattern_rejects_other_urls():
    assert not PATTERN.match("https://gemini.google.com/")
    assert not PATTERN.match("https://gemini.google.com/app/6d141b742a13")
    assert not PATTERN.match("https://gemini.google.com/share/")  # no id
    assert not PATTERN.match("https://example.com/share/6d141b742a13")


def test_registry_matches_gemini_share_url():
    # The auto-discovery registry recognizes the URL shape.
    assert matches("https://gemini.google.com/share/6d141b742a13")
    assert matches("https://g.co/gemini/share/abc123def456")
    assert not matches("https://gemini.google.com/app")


# ── batchexecute payload parsing ─────────────────────────────────────────────


def test_parse_gemini_fixture():
    text = (FIXTURES / "gemini_share.html").read_text(encoding="utf-8")
    res = parse_gemini_batchexecute(text)
    assert isinstance(res, ShareResult)
    assert res.provider == "gemini"
    assert res.title == "Houseplant care tips"
    # Both roles present, labeled "User" and "Gemini".
    assert res.markdown.count("**User:**") == 2
    assert res.markdown.count("**Gemini:**") == 2
    # Known content from the fixture's user prompts and model responses.
    assert "keeping houseplants healthy" in res.markdown
    assert "root rot" in res.markdown
    assert "repotting" in res.markdown
    # Chronological order: first exchange precedes the second, and within a
    # turn the user prompt precedes the model response.
    first_user = res.markdown.index("**User:**")
    first_gemini = res.markdown.index("**Gemini:**")
    assert first_user < first_gemini
    assert res.markdown.index("root rot") < res.markdown.index("repotting")


# ── garbage / wrong-shape input returns None ─────────────────────────────────


def test_parse_gemini_garbage_returns_none():
    assert parse_gemini_batchexecute("") is None
    assert parse_gemini_batchexecute("<html><body>hello</body></html>") is None
    assert parse_gemini_batchexecute(")]}'\n\nnot json at all") is None


def test_parse_gemini_envelope_without_ujx1bf_returns_none():
    # A well-formed WIZ envelope carrying a different RPC id must not parse.
    text = ')]}\'\n\n42\n[["wrb.fr","otAQ7b","[6,[false,null]]",null,null,null,"generic"]]\n'
    assert parse_gemini_batchexecute(text) is None


def test_parse_gemini_empty_conversation_returns_none():
    # Envelope shaped right but with no turns -> _render yields None.
    text = ')]}\'\n\n30\n[["wrb.fr","ujx1Bf","[[null,[],[null,\\"T\\"]]]",null,null,null,"generic"]]\n'
    assert parse_gemini_batchexecute(text) is None
