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
from typing import List, Optional, Tuple

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


def _codex_turns(data: object) -> Optional[Tuple[Optional[str], List[Turn]]]:
    """Extract (title, turns) from a Codex ``/s/cd_`` post route, or None.

    Codex shares don't carry ``linear_conversation``/``messages``. The
    conversation lives in ``post.attachments[].turns.turn_mapping``, a tree of
    user/assistant turns keyed by turn id. A post can carry more than one
    attachment; every attachment is read, and a turn id kept from an earlier
    attachment is not repeated. Each user turn holds ``input_items[]``
    message content; each assistant turn holds ``output_items[]`` of which the
    ``type == "message"`` entries carry the narrative text.
    """
    if not isinstance(data, dict):
        return None
    loader = data.get("loaderData")
    if not isinstance(loader, dict):
        return None
    route = loader.get("routes/s.$postId")
    if not isinstance(route, dict):
        return None
    pwp = route.get("postWithProfile")
    if not isinstance(pwp, dict):
        return None
    post = pwp.get("post")
    if not isinstance(post, dict):
        return None
    attachments = post.get("attachments")
    if not isinstance(attachments, list) or not attachments:
        return None
    mappings: List[dict] = []
    for att in attachments:
        if not isinstance(att, dict):
            continue
        turns_obj = att.get("turns")
        if not isinstance(turns_obj, dict):
            continue
        tm = turns_obj.get("turn_mapping")
        if isinstance(tm, dict) and tm:
            mappings.append(tm)
    if not mappings:
        return None

    def text_of_content(parts: List[object] | None) -> str:
        out: List[str] = []
        for p in parts or []:
            if (isinstance(p, dict) and p.get("content_type") == "text"
                    and isinstance(p.get("text"), str)):
                out.append(p["text"])
        return "".join(out)

    collected: List[Tuple[object, str, str]] = []
    seen: set[object] = set()
    for tm in mappings:
        for key, node in tm.items():
            if key in seen or not isinstance(node, dict):
                continue
            turn = node.get("turn")
            if not isinstance(turn, dict):
                continue
            rtype = turn.get("type") or turn.get("role")
            created = turn.get("created_at")
            text = ""
            if rtype == "user":
                for item in turn.get("input_items") or []:
                    if isinstance(item, dict) and item.get("type") == "message":
                        text += text_of_content(item.get("content"))
            elif rtype == "assistant":
                for item in turn.get("output_items") or []:
                    if isinstance(item, dict) and item.get("type") == "message":
                        text += text_of_content(item.get("content"))
            else:
                continue
            text = text.strip()
            if not text:
                continue
            seen.add(key)
            collected.append((created, rtype, text))

    collected.sort(key=lambda item: (item[0] is None, item[0]))
    turns: List[Turn] = []
    for _created, rtype, text in collected:
        if not text:
            continue
        turns.append(("User" if rtype == "user" else "ChatGPT", text))

    title = post.get("title")
    if not isinstance(title, str) or not title.strip():
        title = None
    if not turns:
        return None
    return title, turns


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
        if messages:
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
            if turns:
                return _render("chatgpt", title if isinstance(title, str) else None, turns)
        codex = _codex_turns(data)
        if codex is not None:
            title, turns = codex
            return _render("chatgpt", title, turns)
    return None


def extract_share(url: str, match: "re.Match[str]") -> Optional[ShareResult]:
    r = _fetch(url)
    if r.status_code != 200:
        return None
    return parse_chatgpt_html(r.text)
