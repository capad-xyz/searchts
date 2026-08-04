# -*- coding: utf-8 -*-
"""ChatGPT share-link extractor (chatgpt.com/share, chat.openai.com/share).

The share page never renders the conversation into the DOM; it ships it inside
React Router turbo-stream script chunks
(``window.__reactRouterContext.streamController.enqueue("...")``). The stream
is a flat JSON pool: objects are ``{"_K": V}`` (key string at pool[K], value at
pool[V]), arrays are lists of pool indices, negative indices are sentinels
(undefined/NaN/...), and typed markers (Promises, Dates) are arrays starting
with a tag string. Hydrating index 0 yields the route data whose
``linear_conversation`` holds the ordered message nodes.
"""

from __future__ import annotations

import json
import re
from typing import List, Optional

from searchts.share_extractors import (
    ShareResult,
    Turn,
    _fetch,
    _find_key,
    _render,
)

PATTERN = re.compile(
    r"^https?://(?:chatgpt\.com|chat\.openai\.com)/(?:share|s)/([A-Za-z0-9_-]+)")


def _hydrate_turbo_stream(pool: list, index, depth: int = 0):
    """Resolve one value from a React Router turbo-stream pool."""
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


def _conversation_messages(data) -> Optional[List[object]]:
    """Ordered message dicts from either share-page schema, or None if absent.

    ``/share/<id>`` (full conversation) carries ``linear_conversation``, a list of
    nodes that each WRAP a message. ``/s/<id>`` (single-turn share) carries a flat
    ``messages`` list of the same message dicts, unwrapped. Normalize both to a
    plain list of message dicts so the caller has one shape to walk.
    """
    conv = _find_key(data, "linear_conversation")
    if isinstance(conv, list):
        return [
            node.get("message") if isinstance(node, dict) else None
            for node in conv
        ]
    msgs = _find_key(data, "messages")
    if isinstance(msgs, list):
        return list(msgs)
    return None


def parse_chatgpt_html(html: str) -> Optional[ShareResult]:
    """Decode a chatgpt.com share page's turbo-stream into conversation markdown."""
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
        messages = _conversation_messages(data)
        if messages is None:
            continue
        title = _find_key(data, "title")
        turns: List[Turn] = []
        for msg in messages:
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


def extract_share(url: str, match: "re.Match[str]") -> Optional[ShareResult]:
    r = _fetch(url)
    if r.status_code != 200:
        return None
    return parse_chatgpt_html(r.text)
