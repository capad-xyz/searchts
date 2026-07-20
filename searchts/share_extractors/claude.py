# -*- coding: utf-8 -*-
"""Claude share-link extractor (claude.ai/share/<uuid>).

The share page is a React shell behind Cloudflare, but the snapshot itself is
served by a keyless JSON endpoint — ``claude.ai/api/chat_snapshots/<uuid>`` —
that the Chrome-impersonated fetch clears. Messages arrive unordered with an
``index`` field; text lives in ``content[]`` blocks (falling back to the flat
``text`` field when blocks are absent).
"""

from __future__ import annotations

import re
from typing import List, Optional

from searchts.share_extractors import ShareResult, Turn, _fetch, _render

PATTERN = re.compile(r"^https?://claude\.ai/share/([a-f0-9-]{36})")


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


def extract_share(url: str, match: "re.Match[str]") -> Optional[ShareResult]:
    r = _fetch(f"https://claude.ai/api/chat_snapshots/{match.group(1)}")
    if r.status_code != 200 or "json" not in (r.headers.get("content-type") or ""):
        return None
    return parse_claude_snapshot(r.json())
