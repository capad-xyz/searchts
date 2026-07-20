# -*- coding: utf-8 -*-
"""Gemini share-link extractor (gemini.google.com/share, g.co/gemini/share).

The share page's initial HTML (``window.WIZ_global_data``) carries only app
config and suggestion chips — never the shared conversation. The conversation is
loaded client-side by a keyless Google WIZ ``batchexecute`` RPC:

    POST /_/BardChatUi/data/batchexecute?rpcids=ujx1Bf
        f.req = [[["ujx1Bf","[null,\"<share_id>\",[4]]",null,"generic"]]]

No auth (no ``SNlM0e`` token is present on a public share), so the same
Chrome-impersonated fetch used by the unlocker clears it. The response is a
Google WIZ envelope: a ``)]}'`` guard, length-prefixed chunks, and a
``["wrb.fr","ujx1Bf","<stringified JSON>", ...]`` entry whose stringified JSON is
the conversation.

That inner JSON is positional (no keys). Structure, reverse-engineered against
several live pages:

    payload[0]           -> root
    root[1]              -> ordered list of turns (one per user/model exchange)
    root[2][1]           -> conversation title
    turn[2][0][0]        -> user prompt text  (empty for Canvas/regen turns)
    turn[3][0][0][1][0]  -> model response markdown

The parser digs those anchored paths defensively, type-checks each hop, skips
malformed or empty turns, and returns None on any mismatch (the registry then
falls through to the generic browser ladder).
"""

from __future__ import annotations

import json
import re
from typing import List, Optional

from searchts.share_extractors import ShareResult, Turn, _fetch, _render

PATTERN = re.compile(
    r"^https?://(?:gemini\.google\.com/share|g\.co/gemini/share)/([A-Za-z0-9]+)")

#: WIZ RPC id that serves a shared conversation.
_RPCID = "ujx1Bf"
_BATCH_URL = "https://gemini.google.com/_/BardChatUi/data/batchexecute"


def _dig(obj, path):
    """Follow a list of positional indices, tolerating any wrong-shape hop."""
    for key in path:
        if isinstance(obj, list) and isinstance(key, int) and -len(obj) <= key < len(obj):
            obj = obj[key]
        else:
            return None
    return obj


def _decode_envelope(text: str):
    """Pull the ``ujx1Bf`` payload out of a WIZ batchexecute response."""
    decoder = json.JSONDecoder()
    for m in re.finditer(r'\[\["wrb\.fr"', text):
        try:
            obj, _ = decoder.raw_decode(text[m.start():])
        except ValueError:
            continue
        if not isinstance(obj, list):
            continue
        for entry in obj:
            if (isinstance(entry, list) and len(entry) >= 3
                    and entry[0] == "wrb.fr" and entry[1] == _RPCID
                    and isinstance(entry[2], str)):
                try:
                    return json.loads(entry[2])
                except ValueError:
                    return None
    return None


def parse_gemini_batchexecute(text: str) -> Optional[ShareResult]:
    """Render a Gemini ``ujx1Bf`` batchexecute response as conversation markdown."""
    payload = _decode_envelope(text)
    if not isinstance(payload, list) or not payload:
        return None
    root = payload[0]
    if not isinstance(root, list):
        return None
    container = _dig(root, [1])
    if not isinstance(container, list):
        return None
    title = _dig(root, [2, 1])
    title = title if isinstance(title, str) and title.strip() else None
    turns: List[Turn] = []
    for node in container:
        if not isinstance(node, list):
            continue
        user = _dig(node, [2, 0, 0])
        model = _dig(node, [3, 0, 0, 1, 0])
        if isinstance(user, str) and user.strip():
            turns.append(("User", user))
        if isinstance(model, str) and model.strip():
            turns.append(("Gemini", model))
    return _render("gemini", title, turns)


def _resolve_share_id(url: str, match: "re.Match[str]") -> Optional[str]:
    """Canonical gemini share id — following a g.co redirect when needed."""
    if "gemini.google.com" in url:
        return match.group(1)
    # g.co/gemini/share/<id> -> follow the redirect (_fetch follows them) and
    # read the canonical gemini share id from the final URL or page.
    try:
        r = _fetch(url)
    except Exception:  # noqa: BLE001 - fall back to the raw id on any fetch error
        return match.group(1)
    for hay in (getattr(r, "url", "") or "", r.text or ""):
        m = re.search(r"gemini\.google\.com/share/([A-Za-z0-9]+)", hay)
        if m:
            return m.group(1)
    return match.group(1)


def _fetch_conversation(share_id: str):
    """Keyless Chrome-impersonated batchexecute POST for a shared conversation."""
    from curl_cffi import requests as cr

    inner = json.dumps([None, share_id, [4]])
    freq = json.dumps([[[_RPCID, inner, None, "generic"]]])
    url = f"{_BATCH_URL}?rpcids={_RPCID}&source-path=%2Fshare%2F{share_id}&rt=c"
    return cr.post(
        url,
        impersonate="chrome",
        data={"f.req": freq},
        headers={
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=30,
    )


def extract_share(url: str, match: "re.Match[str]") -> Optional[ShareResult]:
    share_id = _resolve_share_id(url, match)
    if not share_id:
        return None
    r = _fetch_conversation(share_id)
    if r.status_code != 200:
        return None
    return parse_gemini_batchexecute(r.text)
