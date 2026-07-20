# -*- coding: utf-8 -*-
"""Tier-0 extractors for AI-chat share links (ChatGPT, Claude, Poe).

Share pages are JS-heavy SPAs whose conversation never appears in the rendered
DOM as extractable text: ChatGPT serializes it into React Router turbo-stream
script chunks, Claude loads it from a keyless JSON API behind Cloudflare, and
Poe embeds it in Next.js ``__NEXT_DATA__``. The generic unlocker ladder
therefore returns a thin shell or a partial Jina render. These extractors
recognize the share-URL shapes and decode the provider's own data channel into
complete conversation markdown instead.

Contract: ``extract(url)`` returns a ``ShareResult`` for a recognized +
successfully parsed share link, or ``None`` for anything else (unknown URL,
network failure, provider changed their serialization). It never raises, so
``unlocker.fetch`` can always fall through to the normal ladder.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

#: (role, text) turns in conversation order.
Turn = Tuple[str, str]


@dataclass
class ShareResult:
    provider: str
    title: Optional[str]
    markdown: str


def _fetch(url: str, timeout: int = 30):
    """Chrome-impersonated GET (same fingerprint as the unlocker's tier 1)."""
    from curl_cffi import requests as cr
    return cr.get(url, impersonate="chrome", timeout=timeout,
                  headers={"Accept-Language": "en-US,en;q=0.9"})


def _render(provider: str, title: Optional[str], turns: List[Turn]) -> Optional[ShareResult]:
    if not turns:
        return None
    lines: List[str] = []
    if title:
        lines.append(f"# {title}\n")
    for role, text in turns:
        lines.append(f"**{role}:**\n\n{text.strip()}\n")
    return ShareResult(provider, title, "\n".join(lines).strip())


# ── ChatGPT ──────────────────────────────────────────────────────────────────

def _hydrate_turbo_stream(pool: list, index, depth: int = 0):
    """Resolve one value from a React Router turbo-stream pool.

    The stream is a flat JSON array: objects are ``{"_K": V}`` (key string at
    pool[K], value at pool[V]), arrays are lists of pool indices, and negative
    indices are sentinels (undefined/NaN/...). Typed markers (Promises, Dates)
    are arrays starting with a tag string — irrelevant to the conversation, so
    they resolve to None.
    """
    if depth > 80 or not isinstance(index, int) or index < 0 or index >= len(pool):
        return None
    value = pool[index]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            key_idx = int(k[1:]) if k.startswith("_") else -1
            key = pool[key_idx] if 0 <= key_idx < len(pool) else None
            if isinstance(key, str):
                out[key] = _hydrate_turbo_stream(pool, v, depth + 1)
        return out
    if isinstance(value, list):
        if value and isinstance(value[0], str):
            return None  # typed marker, e.g. ["P", idx] promise reference
        return [_hydrate_turbo_stream(pool, v, depth + 1) for v in value]
    return value


def _find_key(obj, key: str):
    """Depth-first search for the first occurrence of `key` in nested data."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            hit = _find_key(v, key)
            if hit is not None:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = _find_key(v, key)
            if hit is not None:
                return hit
    return None


def parse_chatgpt_html(html: str) -> Optional[ShareResult]:
    """Decode a chatgpt.com/share page's turbo-stream into conversation markdown."""
    chunks = re.findall(
        r'streamController\.enqueue\((".*?")\);</script>', html, re.S)
    for raw in chunks:
        try:
            pool = json.loads(json.loads(raw))
        except (ValueError, TypeError):
            continue
        if not isinstance(pool, list) or not pool:
            continue
        data = _hydrate_turbo_stream(pool, 0)
        conv = _find_key(data, "linear_conversation")
        if not isinstance(conv, list):
            continue
        title = _find_key(data, "title")
        turns: List[Turn] = []
        for node in conv:
            msg = (node or {}).get("message") if isinstance(node, dict) else None
            if not isinstance(msg, dict):
                continue
            role = ((msg.get("author") or {}).get("role")) or ""
            parts = ((msg.get("content") or {}).get("parts")) or []
            texts = []
            for p in parts:
                if isinstance(p, str) and p.strip():
                    texts.append(p)
                elif isinstance(p, dict) and isinstance(p.get("text"), str):
                    texts.append(p["text"])
            if not texts or role not in ("user", "assistant"):
                continue
            turns.append(("User" if role == "user" else "ChatGPT",
                          "\n\n".join(texts)))
        return _render("chatgpt", title if isinstance(title, str) else None, turns)
    return None


def _extract_chatgpt(url: str, match: "re.Match[str]") -> Optional[ShareResult]:
    r = _fetch(url)
    if r.status_code != 200:
        return None
    return parse_chatgpt_html(r.text)


# ── Claude ───────────────────────────────────────────────────────────────────

def parse_claude_snapshot(data: dict) -> Optional[ShareResult]:
    """Render a claude.ai chat_snapshots JSON payload as conversation markdown."""
    messages = data.get("chat_messages")
    if not isinstance(messages, list):
        return None
    turns: List[Turn] = []
    for msg in sorted(messages, key=lambda m: m.get("index", 0)):
        role = {"human": "User", "assistant": "Claude"}.get(msg.get("sender"))
        texts = []
        for block in msg.get("content") or []:
            if isinstance(block, dict) and isinstance(block.get("text"), str) and block["text"].strip():
                texts.append(block["text"])
        if not texts and isinstance(msg.get("text"), str) and msg["text"].strip():
            texts.append(msg["text"])
        if role and texts:
            turns.append((role, "\n\n".join(texts)))
    return _render("claude", data.get("snapshot_name") or None, turns)


def _extract_claude(url: str, match: "re.Match[str]") -> Optional[ShareResult]:
    r = _fetch(f"https://claude.ai/api/chat_snapshots/{match.group(1)}")
    if r.status_code != 200 or "json" not in (r.headers.get("content-type") or ""):
        return None
    return parse_claude_snapshot(r.json())


# ── Poe ──────────────────────────────────────────────────────────────────────

def parse_poe_html(html: str) -> Optional[ShareResult]:
    """Render a poe.com/s share page's __NEXT_DATA__ as conversation markdown."""
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return None
    share = _find_key(data, "chatShare")
    if not isinstance(share, dict):
        return None
    bot = share.get("chatBot") or {}
    bot_name = bot.get("displayName") or bot.get("handle") or None
    edges = ((share.get("messagesConnection") or {}).get("edges")) or []
    turns: List[Turn] = []
    for edge in edges:
        node = (edge or {}).get("node") or {}
        text = node.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        author = node.get("author") or ""
        role = "User" if author == "human" else (bot_name or author or "Bot")
        turns.append((role, text))
    return _render("poe", bot_name, turns)


def _extract_poe(url: str, match: "re.Match[str]") -> Optional[ShareResult]:
    r = _fetch(url)
    if r.status_code != 200:
        return None
    return parse_poe_html(r.text)


# ── registry ─────────────────────────────────────────────────────────────────

_EXTRACTORS: List[Tuple["re.Pattern[str]", Callable[..., Optional[ShareResult]]]] = [
    (re.compile(r"^https?://(?:chatgpt\.com|chat\.openai\.com)/share/([A-Za-z0-9-]+)"),
     _extract_chatgpt),
    (re.compile(r"^https?://claude\.ai/share/([a-f0-9-]{36})"), _extract_claude),
    (re.compile(r"^https?://(?:www\.)?poe\.com/s/([A-Za-z0-9]+)"), _extract_poe),
]


def matches(url: str) -> bool:
    """True if `url` looks like a share link one of the extractors handles."""
    return any(pat.match(url) for pat, _fn in _EXTRACTORS)


def extract(url: str) -> Optional[ShareResult]:
    """Extract a full conversation from a recognized share link; None otherwise.

    Never raises: any failure means the caller should fall through to the
    generic unlocker ladder.
    """
    for pat, fn in _EXTRACTORS:
        m = pat.match(url)
        if not m:
            continue
        try:
            return fn(url, m)
        except Exception:  # noqa: BLE001 - extractor failure must not break fetch
            return None
    return None
