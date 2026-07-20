# -*- coding: utf-8 -*-
"""Grok share-link extractor (grok.com/share/<id>, x.com/i/grok/share/<id>).

The share page is a Next.js App Router shell: the server HTML only carries the
conversation *title* and a truncated ``og:description`` inside the
``self.__next_f.push([1,"..."])`` flight chunks — the messages themselves are
never server-rendered. The client component (``SharedConversationPageClient``)
hydrates them from a keyless JSON endpoint,
``grok.com/rest/app-chat/share_links/<shareLinkId>``, which the
Chrome-impersonated fetch clears without auth.

That payload is ``{"conversation": {...}, "responses": [...]}``; each response
carries ``sender`` (``"human"`` / ``"assistant"``, case-insensitive), the text
in ``message`` (falling back to ``query``), a ``createTime`` timestamp, and a
``parentResponseId`` linking it to the previous turn. Turns are emitted in
``createTime`` order with role labels "User" and "Grok".
"""

from __future__ import annotations

import re
from typing import List, Optional

from searchts.share_extractors import ShareResult, Turn, _fetch, _render

PATTERN = re.compile(
    r"^https?://(?:www\.)?(?:grok\.com/share|x\.com/i/grok/share)/([A-Za-z0-9._-]+)")

_API = "https://grok.com/rest/app-chat/share_links/{share_id}"


def parse_grok_share(data: dict) -> Optional[ShareResult]:
    """Render a grok.com share_links JSON payload as conversation markdown."""
    if not isinstance(data, dict):
        return None
    responses = data.get("responses")
    if not isinstance(responses, list) or not responses:
        return None

    # Order by createTime (ISO-8601, lexicographically sortable); a stable sort
    # keeps the server's original order for any ties (e.g. a turn and its reply
    # sharing a timestamp). Fall back to the raw order if createTime is absent.
    indexed = list(enumerate(responses))
    indexed.sort(key=lambda pair: (str((pair[1] or {}).get("createTime") or ""), pair[0]))

    turns: List[Turn] = []
    for _idx, resp in indexed:
        if not isinstance(resp, dict) or resp.get("isControl"):
            continue
        sender = str(resp.get("sender") or "").lower()
        role = "User" if sender == "human" else "Grok"
        text = resp.get("message")
        if not isinstance(text, str) or not text.strip():
            text = resp.get("query")
        if not isinstance(text, str) or not text.strip():
            continue
        turns.append((role, text.strip()))

    title = (data.get("conversation") or {}).get("title") if isinstance(
        data.get("conversation"), dict) else None
    return _render("grok", title if isinstance(title, str) and title.strip() else None, turns)


def extract_share(url: str, match: "re.Match[str]") -> Optional[ShareResult]:
    r = _fetch(_API.format(share_id=match.group(1)))
    if r.status_code != 200 or "json" not in (r.headers.get("content-type") or ""):
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    return parse_grok_share(data)
