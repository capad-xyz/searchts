# -*- coding: utf-8 -*-
"""Tier-0 extractors for AI-chat share links — one plugin module per provider.

Share pages are JS-heavy SPAs whose conversation never appears in the rendered
DOM as extractable text (ChatGPT serializes it into turbo-stream script chunks,
Claude loads it from a keyless JSON API behind Cloudflare, Poe embeds it in
``__NEXT_DATA__``, ...). The generic unlocker ladder therefore returns a thin
shell or a partial render. These extractors recognize share-URL shapes and
decode the provider's own data channel into complete conversation markdown.

Plugin contract — each non-underscore module in this package defines:

- ``PATTERN``: compiled regex matched against the normalized URL; group(1) is
  the share id.
- ``extract_share(url, match) -> Optional[ShareResult]``: fetch + parse. May
  raise; the registry converts any exception into a fall-through.

Adding a provider is dropping in a new module — no registry edits needed.

Public API: ``matches(url)`` and ``extract(url)``. ``extract`` never raises,
so ``unlocker.fetch`` can always fall through to the normal ladder.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

#: (role, text) turns in conversation order.
Turn = Tuple[str, str]


@dataclass
class ShareResult:
    provider: str
    title: Optional[str]
    markdown: str


# ── shared helpers for provider modules ──────────────────────────────────────

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


# ── registry (auto-discovered from the package's modules) ────────────────────

_EXTRACTORS: List[Tuple[object, Callable[..., Optional[ShareResult]]]] = []


def _discover() -> None:
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"{__name__}.{info.name}")
        except Exception:  # noqa: BLE001 - a broken plugin must not break the rest
            continue
        pattern = getattr(mod, "PATTERN", None)
        fn = getattr(mod, "extract_share", None)
        if pattern is not None and callable(fn):
            _EXTRACTORS.append((pattern, fn))


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


_discover()

# Back-compat / test-facing re-exports of the provider parsers.
from searchts.share_extractors.chatgpt import parse_chatgpt_html  # noqa: E402
from searchts.share_extractors.claude import parse_claude_snapshot  # noqa: E402
from searchts.share_extractors.poe import parse_poe_html  # noqa: E402
