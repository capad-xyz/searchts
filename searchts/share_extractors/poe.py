# -*- coding: utf-8 -*-
"""Poe share-link extractor (poe.com/s/<code>).

Poe server-renders the shared chat into Next.js ``__NEXT_DATA__``; the
conversation sits at ``chatShare.messagesConnection.edges[].node`` with a
``text`` body and an ``author`` that is either ``"human"`` or a bot handle.
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

PATTERN = re.compile(r"^https?://(?:www\.)?poe\.com/s/([A-Za-z0-9]+)")


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


def extract_share(url: str, match: "re.Match[str]") -> Optional[ShareResult]:
    r = _fetch(url)
    if r.status_code != 200:
        return None
    return parse_poe_html(r.text)
