# -*- coding: utf-8 -*-
"""Tests for the Grok tier-0 share-link extractor (no network).

Grok never server-renders the conversation into the share page; the messages
come from a keyless JSON endpoint (``grok.com/rest/app-chat/share_links/<id>``),
so the fixture is a synthetic ``share_links`` payload byte-mirroring the real
schema (responses[] with ``sender`` / ``message`` / ``createTime``), trimmed to
an innocuous conversation.
"""

import json
from pathlib import Path

from searchts.share_extractors import ShareResult, extract, matches
from searchts.share_extractors.grok import PATTERN, parse_grok_share

FIXTURES = Path(__file__).parent / "fixtures"


# ── URL matching ─────────────────────────────────────────────────────────────


def test_matches_grok_share_urls():
    assert matches(
        "https://grok.com/share/bGVnYWN5_b8625806-94b3-4886-bc4c-0e559a77139e")
    assert matches(
        "https://www.grok.com/share/bGVnYWN5_6dae0579-f14f-4eec-b89a-f7bbdd8c52ea")
    assert matches("https://x.com/i/grok/share/abc123DEF456")


def test_pattern_captures_share_id():
    m = PATTERN.match(
        "https://grok.com/share/bGVnYWN5_b8625806-94b3-4886-bc4c-0e559a77139e")
    assert m is not None
    assert m.group(1) == "bGVnYWN5_b8625806-94b3-4886-bc4c-0e559a77139e"


def test_matches_rejects_non_grok_share_urls():
    assert not matches("https://grok.com/")               # no share id
    assert not matches("https://grok.com/share/")          # empty id
    assert not matches("https://grok.com/chat/abc123")     # not a share
    assert not matches("https://example.com/share/abc123")


# ── share_links JSON parsing ─────────────────────────────────────────────────


def test_parse_grok_fixture():
    data = json.loads((FIXTURES / "grok_share.json").read_text(encoding="utf-8"))
    res = parse_grok_share(data)
    assert isinstance(res, ShareResult)
    assert res.provider == "grok"
    assert res.title == "Starting a Balcony Herb Garden"
    # Both role labels present.
    assert "**User:**" in res.markdown
    assert "**Grok:**" in res.markdown
    assert res.markdown.count("**User:**") == 3
    assert res.markdown.count("**Grok:**") == 3
    # Known text from each side survives, including the uppercase-"ASSISTANT"
    # turn (case-insensitive role mapping).
    assert "small herb garden on my balcony" in res.markdown
    assert "south-facing window" in res.markdown
    # Complete from the very first (opening user) turn.
    assert res.markdown.index("How do I start a small herb garden") < res.markdown.index(
        "south-facing window")


def test_parse_grok_orders_by_create_time():
    # Shuffle the responses; the parser must still emit them in createTime order.
    data = json.loads((FIXTURES / "grok_share.json").read_text(encoding="utf-8"))
    data["responses"] = list(reversed(data["responses"]))
    res = parse_grok_share(data)
    assert res is not None
    first_user = res.markdown.index("How do I start a small herb garden")
    water_q = res.markdown.index("How often should I water them")
    winter_q = res.markdown.index("growing them indoors over winter")
    assert first_user < water_q < winter_q


def test_parse_grok_garbage_returns_none():
    assert parse_grok_share({}) is None
    assert parse_grok_share({"responses": "nope"}) is None
    assert parse_grok_share({"responses": []}) is None
    assert parse_grok_share(None) is None
    # Responses present but none carry usable text.
    assert parse_grok_share(
        {"responses": [{"sender": "human", "message": "  "}]}) is None


def test_extract_unrecognized_url_returns_none():
    assert extract("https://example.com/") is None
