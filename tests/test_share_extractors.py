# -*- coding: utf-8 -*-
"""Tests for the tier-0 AI-chat share-link extractors (no network).

The ChatGPT fixture is a real share page trimmed to its turbo-stream script
chunks (ground truth for the serialization format); the Claude and Poe fixtures
are synthetic payloads mirroring the schemas verified against live pages.
"""

import json
from pathlib import Path

from conftest import Tripwire

from searchts import share_extractors, unlocker
from searchts.share_extractors import (
    ShareResult,
    copilot,
    extract,
    grok,
    matches,
    parse_chatgpt_html,
    parse_claude_snapshot,
    parse_poe_html,
    perplexity,
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
        raise Tripwire("ladder backend called despite share hit")

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


# ── ChatGPT short-share links (/s/<id>) ──────────────────────────────────────
#
# Regression: ChatGPT issues single-turn shares at `/s/t_<hex>`, which the
# `/share/`-only PATTERN never matched, so tier-0 was skipped and the generic
# ladder returned the un-hydrated SPA shell. The route also serves its turns as
# a flat `messages` list rather than `linear_conversation` nodes, so widening
# the URL pattern alone was not enough.


def test_matches_chatgpt_short_share_urls():
    assert matches("https://chatgpt.com/s/t_6a714d2148c8819188f1ce1f4c074a19")
    assert matches("https://chat.openai.com/s/t_6a714d2148c8819188f1ce1f4c074a19")
    # The `t_` prefix means the id contains an underscore; a pattern without
    # `_` in its character class silently truncates and fails to match.
    assert matches("https://chatgpt.com/s/abc_123-XYZ")


def test_matches_all_chatgpt_short_share_prefixes():
    """`/s/` ids carry a type prefix and there is more than one.

    Verified live: t_ = thread, m_ = single message, dr_ = deep research,
    cd_ = Codex session. Keep the id class permissive rather than pinning the
    known prefixes, since OpenAI adds new ones without notice.
    """
    for prefix in ("t_", "m_", "dr_", "cd_"):
        url = f"https://chatgpt.com/s/{prefix}6a714d2148c8819188f1ce1f4c074a19"
        assert matches(url), prefix


def test_matches_still_rejects_chatgpt_non_share_paths():
    assert not matches("https://chatgpt.com/s/")           # no id
    assert not matches("https://chatgpt.com/s")            # no trailing segment
    assert not matches("https://chatgpt.com/c/abc123")     # private chat, not a share


def _turbo_stream_html(pool):
    """Wrap a turbo-stream pool the way a share page ships it."""
    return (
        "<script>streamController.enqueue("
        + json.dumps(json.dumps(pool))
        + ");</script>"
    )


def test_parse_chatgpt_flat_messages_schema():
    """`/s/` shares carry `messages` (flat dicts), not `linear_conversation`."""
    pool = [
        {"_1": 2},            # 0: {loaderData: <2>}
        "loaderData",         # 1
        {"_3": 4, "_15": 16},  # 2: {messages: <4>, title: <16>}
        "messages",           # 3
        [5],                  # 4: [<5>]
        {"_6": 7, "_10": 11},  # 5: {author: <7>, content: <11>}
        "author",             # 6
        {"_8": 9},            # 7: {role: <9>}
        "role",               # 8
        "assistant",          # 9
        "content",            # 10
        {"_12": 13},          # 11: {parts: <13>}
        "parts",              # 12
        [14],                 # 13: [<14>]
        "hello from a single-turn share",  # 14
        "title",              # 15
        "Synthetic single turn",  # 16
    ]
    res = parse_chatgpt_html(_turbo_stream_html(pool))
    assert isinstance(res, ShareResult)
    assert res.provider == "chatgpt"
    assert res.title == "Synthetic single turn"
    assert "**ChatGPT:**" in res.markdown
    assert "hello from a single-turn share" in res.markdown


def test_parse_chatgpt_flat_messages_ignores_non_dict_entries():
    """A malformed entry in `messages` must be skipped, not raise."""
    pool = [
        {"_1": 2},
        "loaderData",
        {"_3": 4},
        "messages",
        [5, 6],               # 4: one junk entry, one real message
        "not-a-message",      # 5
        {"_7": 8, "_11": 12},  # 6
        "author",             # 7
        {"_9": 10},           # 8
        "role",               # 9
        "user",               # 10
        "content",            # 11
        {"_13": 14},          # 12
        "parts",              # 13
        [15],                 # 14
        "still parsed",       # 15
    ]
    res = parse_chatgpt_html(_turbo_stream_html(pool))
    assert isinstance(res, ShareResult)
    assert "**User:**" in res.markdown
    assert "still parsed" in res.markdown


# ── share-id capture (regression: patterns matched but truncated the id) ─────
#
# These patterns never failed loudly. They matched the URL and captured a
# truncated id, which for Grok then 404s against its share_links API.


def test_grok_captures_base64_padding_in_share_id():
    """A grok id is `<base64 shard>_<uuid>` and the base64 may carry `=`."""
    cases = [
        # literal padding
        ("https://grok.com/share/bGVnYWN5LWNvcHk=_3c82dc3b-a9fb-4c63-9482-0d9a3131dbe2",
         "bGVnYWN5LWNvcHk=_3c82dc3b-a9fb-4c63-9482-0d9a3131dbe2"),
        # percent-encoded padding, same share
        ("https://grok.com/share/c2hhcmQtMg%3D%3D_4e6798eb-9288-4a09-b00f-8292ce23dab6",
         "c2hhcmQtMg%3D%3D_4e6798eb-9288-4a09-b00f-8292ce23dab6"),
        # unpadded
        ("https://grok.com/share/bGVnYWN5_6dae0579-f14f-4eec-b89a-f7bbdd8c52ea",
         "bGVnYWN5_6dae0579-f14f-4eec-b89a-f7bbdd8c52ea"),
        # bare uuid, no shard prefix
        ("https://grok.com/share/7497a668-4a30-4862-a79d-901f624650e0",
         "7497a668-4a30-4862-a79d-901f624650e0"),
        # x.com base62 and hex32 forms
        ("https://x.com/i/grok/share/ya31uGG63eMvwCIako6OEkD1r",
         "ya31uGG63eMvwCIako6OEkD1r"),
        ("https://x.com/i/grok/share/02c6fe33a715493fbd66090b8fec7458",
         "02c6fe33a715493fbd66090b8fec7458"),
    ]
    for url, expected in cases:
        m = grok.PATTERN.match(url)
        assert m is not None, url
        assert m.group(1) == expected, url


def test_grok_share_id_is_percent_decoded_for_the_api(monkeypatch):
    """Both encodings of one share must hit the same API id."""
    seen = []

    class _Resp:
        status_code = 404
        headers: dict = {}

    monkeypatch.setattr(
        grok, "_fetch", lambda u, *a, **k: (seen.append(u), _Resp())[1]
    )
    for url in (
        "https://grok.com/share/c2hhcmQtMg%3D%3D_4e6798eb-9288-4a09-b00f-8292ce23dab6",
        "https://grok.com/share/c2hhcmQtMg==_4e6798eb-9288-4a09-b00f-8292ce23dab6",
    ):
        grok.extract_share(url, grok.PATTERN.match(url))
    assert len(seen) == 2
    assert seen[0] == seen[1], "percent-encoded and literal padding must agree"
    assert seen[0].endswith("c2hhcmQtMg==_4e6798eb-9288-4a09-b00f-8292ce23dab6")


def test_perplexity_matches_pages_and_captures_full_id():
    # Published Pages are a distinct path that previously did not match at all.
    page = "https://www.perplexity.ai/page/scratchpad-ai-reasoning-framew-790vL5qORlyvX7VSwMYmzg"
    assert matches(page)
    # Ids use `.` and `_`; `-` is the slug separator.
    m = perplexity.PATTERN.match(
        "https://www.perplexity.ai/search/explain-perplexity-as-Jenq7WDWRiqT_FwX0nvalg")
    assert m.group(1) == "explain-perplexity-as-Jenq7WDWRiqT_FwX0nvalg"
    m = perplexity.PATTERN.match(
        "https://www.perplexity.ai/search/summarize-the-so2l6.dLT8C9xKubqLB8pQ")
    assert m.group(1) == "summarize-the-so2l6.dLT8C9xKubqLB8pQ"


def test_perplexity_excludes_spaces():
    """Spaces are restricted by default; do not spend a render on them."""
    assert not matches("https://www.perplexity.ai/spaces/osint-K6xoTsgxRlWSIGNL3HlniA")


def test_copilot_shared_page_id_is_not_the_word_pages():
    m = copilot.PATTERN.match(
        "https://copilot.microsoft.com/shares/pages/GXnUTdR5Cqakvtxw5ndAo")
    assert m is not None
    assert m.group(1) == "GXnUTdR5Cqakvtxw5ndAo"
    # Plain conversation shares are unaffected.
    m = copilot.PATTERN.match(
        "https://copilot.microsoft.com/shares/4rcdcS2vcxrwe3UyaEWXa")
    assert m.group(1) == "4rcdcS2vcxrwe3UyaEWXa"


def test_copilot_excludes_private_chats():
    assert not matches("https://copilot.microsoft.com/chats/94EXsDefVqjHqgdqAZ1Mq")
