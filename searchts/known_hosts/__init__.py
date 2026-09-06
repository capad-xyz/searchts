# -*- coding: utf-8 -*-
"""Tier-0.5 extractors for known-host public-API endpoints — a fail-open RING.

Some sites expose a clean JSON API for their canonical document type (e.g.
Reddit's ``.json`` endpoints). These pages are not SPA shells — the JSON *is*
the content — but a generic HTML ladder (curl_cffi / Jina / stealth) either
returns HTML interstitials or forces a login wall. A dedicated extractor can
return structured content that is already machine-readable.

This package mirrors the ``share_extractors`` plugin pattern. Each non-underscore
module defines:

- ``PATTERN``: compiled regex matched against the normalized URL.
- ``extract_known(url, match) -> Optional[KnownResult]``: fetch + parse. May
  raise; the registry converts any exception into a fall-through.

Adding a host is dropping in a new module — no registry edits needed.

Public API: ``matches(url)`` and ``extract(url)``. ``extract`` never raises,
so ``unlocker.fetch`` can always fall through to the normal ladder.

This is a **RING** — it runs first (tier 0.5, between share-extractors and
the backend ladder). On miss/exception the normal ladder runs unchanged. No
host is pinned to this ring.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple


@dataclass
class KnownResult:
    """Result of a known-host extractor."""
    provider: str
    title: Optional[str]
    markdown: str


# ── registry (auto-discovered from the package's modules) ────────────────────

_EXTRACTORS: List[Tuple[re.Pattern[str], Callable[..., Optional[KnownResult]]]] = []


def _discover() -> None:
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"{__name__}.{info.name}")
        except Exception:  # noqa: BLE001 - a broken plugin must not break the rest
            continue
        pattern = getattr(mod, "PATTERN", None)
        fn = getattr(mod, "extract_known", None)
        if pattern is not None and callable(fn):
            _EXTRACTORS.append((pattern, fn))


def matches(url: str) -> bool:
    """True if `url` matches a known-host pattern handled by one of the extractors."""
    return any(pat.match(url) for pat, _fn in _EXTRACTORS)


def matching_name(url: str) -> Optional[str]:
    """Module name of the first extractor that matches ``url``, else None."""
    for pat, fn in _EXTRACTORS:
        if pat.match(url):
            mod = getattr(fn, "__module__", "") or ""
            return mod.rsplit(".", 1)[-1] or None
    return None


def extract(url: str) -> Optional[KnownResult]:
    """Extract structured content from a known host; None otherwise.

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
