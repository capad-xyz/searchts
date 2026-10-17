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
import sys
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


def needs_browser_hop(url: str, reasons) -> bool:
    """True when the wall that stopped a next-page hop is one a browser can pass.

    F5f. A next-page hop is fetched curl-only (F23b), which is right for a static
    pager and wrong for a site that judges the *request* rather than the address:
    measured on Reddit, a direct request for its ``/svc/shreddit/…`` feed cursor
    was answered with the "Prove your humanity" interstitial while the browser
    rung read the same URL with 24 cards in the same minute. Without this the
    walk ends at the first window of every feed, on a cold profile.

    Only a host that declares :data:`HOSTS` and answers :func:`hop_needs_browser`
    can say yes, and the ring asks one file. False for everything else, so no
    other walk changes.
    """
    host = ""
    try:
        host = (url or "").split("//", 1)[-1].split("/", 1)[0].split(":")[0].lower()
    except Exception:  # noqa: BLE001 - an unparsable URL is not a known host
        return False
    if not host:
        return False
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"{__name__}.{info.name}")
        except Exception:  # noqa: BLE001 - a broken module must not break a walk
            continue
        hosts = getattr(mod, "HOSTS", None)
        checker = getattr(mod, "hop_needs_browser", None)
        if not isinstance(hosts, (set, frozenset)) or not callable(checker):
            continue
        if host not in {str(h).lower() for h in hosts}:
            continue
        try:
            return bool(checker(url, reasons))
        except Exception:  # noqa: BLE001 - a broken check must not break a walk
            return False
    return False


def expand_page(
    page, url: str, html: str, want: int, clicks: int, tick=None
) -> Optional[str]:
    """Open what a known host's own page hides behind controls; None if none.

    F5f. Some sites serve the first window of a document and keep the rest
    behind controls the page itself renders (Reddit's "more replies"). Opening
    them needs the live page, so this is the one place the ring meets a browser:
    the caller passes the page, the ring owns the selectors, and the return is
    the fullest HTML seen.

    ``want`` and ``clicks`` are budgets, and they arrive from the knobs
    (:mod:`searchts.knobs`), never from a flag: ``want`` is how many rows the
    read may print, ``clicks`` how many presses the loop may spend. ``tick`` is
    the caller's stderr narrator, passed straight through so a host's loop obeys
    P4.6 without this file printing anything. A host module that has no opener of
    its own contributes nothing and returns None.

    None means "this host has nothing of its own to open", which is not a
    failure: the caller keeps the HTML it had. The generic path (accordions,
    buttons labelled read/show/see-more) is **F23d** and lives with the ring
    rather than in the ladder, so a host either knows its own controls or does
    not.
    """
    for pat, fn in _EXTRACTORS:
        if not pat.match(url):
            continue
        mod = sys.modules.get(getattr(fn, "__module__", "") or "")
        opener = getattr(mod, "expand_more", None)
        if callable(opener):
            opener(page, want, clicks, tick)
            return page.content()
        return None
    return None
    return None
    return None


_discover()
