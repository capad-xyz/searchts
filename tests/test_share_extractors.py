# -*- coding: utf-8 -*-
"""Tests for the tier-0 AI-chat share-link extractors (no network).

The ChatGPT fixture is a real share page trimmed to its turbo-stream script
chunks (ground truth for the serialization format); the Claude and Poe fixtures
are synthetic payloads mirroring the schemas verified against live pages.
"""

import json
from pathlib import Path

import pytest

from searchts import share_extractors, unlocker
from searchts.share_extractors import (
    ShareResult,
    extract,
    matches,
    parse_chatgpt_html,
    parse_claude_snapshot,
    parse_poe_html,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ── URL matching ─────────────────────────────────────────────────────────────


def test_matches_recognized_share_urls():
    assert matches("https://chatgpt.com/share/67a4266c-dbcc-800f-9b92-f0a8a6480e16")
    assert matches("https://chat.openai.com/share/67a4266c-dbcc-800f-9b92-f0a8a6480e16")
    assert matches("https://claude.ai/share/805ee3e5-eb74-43b6-8036-03615b303f6d")
    assert matches("https://poe.com/s/XBaS4nMuAk8YAWevOFmi")
    assert matches("https://www.poe.com/s/XBaS4nMuAk8YAWevOFmi")


def test_matches_rejects_other_urls():
    assert not matches("https://example.com/")
    assert not matches("https://chatgpt.com/")            # no share id
    assert not matches("https://claude.ai/share/not-a-uuid")
    assert not matches("https://claude.ai/chat/805ee3e5-eb74-43b6-8036-03615b303f6d")
    assert not matches("https://poe.com/Assistant")       # bot page, not a share


def test_extract_returns_none_for_unrecognized_url():
    assert extract("https://example.com/") is None


# ── ChatGPT turbo-stream ─────────────────────────────────────────────────────


def test_parse_chatgpt_real_stream():
    html = (FIXTURES / "chatgpt_share.html").read_text(encoding="utf-8")
    res = parse_chatgpt_html(html)
    assert isinstance(res, ShareResult)
    assert res.provider == "chatgpt"
    # The real conversation has 9 linear nodes; role-labeled turns for each
    # user/assistant message with text.
    assert res.markdown.count("**User:**") >= 3
    assert res.markdown.count("**ChatGPT:**") >= 3
    # Known content from the fixture conversation (a Japanese word game).
    assert "きょういくせいど" in res.markdown
    # Complete from the very first turn — the generic ladder's Jina render
    # started mid-conversation and missed this opening user message.
    assert "「き」から始まる7文字の言葉を挙げて" in res.markdown
    assert res.title == "きから始まる言葉"


def test_parse_chatgpt_garbage_html():
    assert parse_chatgpt_html("<html><body>hello</body></html>") is None
    assert parse_chatgpt_html("") is None


def test_parse_chatgpt_malformed_stream_chunk():
    html = ('<script>window.__reactRouterContext.streamController.enqueue'
            '("not json at all");</script>')
    assert parse_chatgpt_html(html) is None


# ── Claude snapshot JSON ─────────────────────────────────────────────────────


def test_parse_claude_snapshot():
    data = json.loads((FIXTURES / "claude_snapshot.json").read_text(encoding="utf-8"))
    res = parse_claude_snapshot(data)
    assert isinstance(res, ShareResult)
    assert res.provider == "claude"
    assert res.title == "Fibonacci helper"
    # Sorted by index: the human turn (index 0) precedes the assistant turn.
    assert res.markdown.index("**User:**") < res.markdown.index("**Claude:**")
    assert "fibonacci function" in res.markdown
    # Text pulled from content blocks when the flat text field is empty.
    assert "a, b = b, a + b" in res.markdown


def test_parse_claude_snapshot_empty_or_wrong_shape():
    assert parse_claude_snapshot({}) is None
    assert parse_claude_snapshot({"chat_messages": "nope"}) is None
    assert parse_claude_snapshot({"chat_messages": []}) is None


# ── Poe __NEXT_DATA__ ────────────────────────────────────────────────────────


def test_parse_poe_html():
    html = (FIXTURES / "poe_share.html").read_text(encoding="utf-8")
    res = parse_poe_html(html)
    assert isinstance(res, ShareResult)
    assert res.provider == "poe"
    assert res.title == "Assistant"
    assert res.markdown.count("**User:**") == 1  # empty human turn dropped
    assert res.markdown.count("**Assistant:**") == 2
    assert "capital of France is Paris" in res.markdown


def test_parse_poe_html_without_next_data():
    assert parse_poe_html("<html><body>nothing here</body></html>") is None


# ── unlocker.fetch tier-0 wiring ─────────────────────────────────────────────


def test_fetch_uses_share_extractor(monkeypatch):
    hit = ShareResult("chatgpt", "T", "**User:**\n\nhi\n\n**ChatGPT:**\n\nhello")
    monkeypatch.setattr(share_extractors, "extract", lambda url: hit)

    def boom(*a, **k):  # the ladder must not run when tier-0 wins
        raise AssertionError("ladder backend called despite share hit")

    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", boom)
    monkeypatch.setattr(unlocker, "_fetch_jina", boom)
    monkeypatch.setattr(unlocker, "_fetch_stealth", boom)

    res = unlocker.fetch("https://chatgpt.com/share/abc123", use_memory=False)
    assert res.backend == "share:chatgpt"
    assert "hello" in res.text
    assert res.status == 200


def test_fetch_falls_through_when_extractor_fails(monkeypatch):
    monkeypatch.setattr(share_extractors, "extract", lambda url: None)
    monkeypatch.setattr(
        unlocker, "_fetch_curl_cffi",
        lambda url, timeout=30: (200, "<html><body>" + "real content " * 100 + "</body></html>",
                                 url, {}),
    )
    res = unlocker.fetch(
        "https://chatgpt.com/share/abc123", backends=["curl_cffi"], use_memory=False)
    assert res.backend == "curl_cffi"
    assert "real content" in res.text


def test_fetch_non_share_url_skips_extractor(monkeypatch):
    calls = []

    def spy(url):
        calls.append(url)
        return None

    monkeypatch.setattr(share_extractors, "extract", spy)
    monkeypatch.setattr(
        unlocker, "_fetch_curl_cffi",
        lambda url, timeout=30: (200, "<html><body>" + "page text " * 100 + "</body></html>",
                                 url, {}),
    )
    unlocker.fetch("https://example.com/", backends=["curl_cffi"], use_memory=False)
    assert calls == []  # matches() gate prevents the extract call entirely
