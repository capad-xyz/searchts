# -*- coding: utf-8 -*-
"""Open-source escalating, fusion-merged web search.

Mirrors the unlocker's ladder philosophy on the *search* side: query several
providers best-effort and fuse their ranked result lists into one consensus
ranking with Reciprocal Rank Fusion (RRF). Free and keyless by default
(DuckDuckGo via the ``ddgs`` package); stronger providers (SearXNG, Exa, Brave,
Tavily) join automatically when their key/env is present.

Design goals (parallel to ``unlocker.fetch``):

* Each provider is a best-effort callable that returns a ranked
  ``list[SearchResult]`` and NEVER raises out of :func:`search`; on error it is
  skipped and its reason recorded.
* Providers live in a module-level registry (:data:`PROVIDERS`) so tests can
  monkeypatch them without any network.
* If every selected provider fails or returns nothing, :func:`search` raises
  :class:`SearchError` with a per-provider reason breakdown (same shape as
  ``unlocker.UnlockerError``).
"""

from __future__ import annotations

import os
import urllib.parse
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

#: Browser-ish UA so keyless HTTP providers (SearXNG instances) don't 403 us.
_UA_REAL = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

#: Reciprocal Rank Fusion constant. 60 is the value from the original RRF paper
#: (Cormack et al.) and the de-facto default; it damps the influence of the very
#: top ranks just enough that agreement across providers wins over any single
#: provider's #1.
_RRF_K = 60

#: Short per-request HTTP timeout (seconds). A slow provider must not stall the
#: whole fused search — it just gets skipped and recorded.
_HTTP_TIMEOUT = 10

#: Query params that are pure tracking noise; dropped when normalizing a URL so
#: the same page from two providers dedupes into one fused result.
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "msclkid", "mc_cid", "mc_eid", "ref", "ref_src",
    "igshid", "spm", "_ga", "yclid",
})


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str


@dataclass
class SearchError(Exception):
    """Raised when every selected provider failed or returned nothing.

    ``attempts`` is a per-provider ``(provider, reason)`` breakdown, mirroring
    ``unlocker.UnlockerError`` so callers can render an identical diagnostic.
    """

    query: str
    attempts: List[Tuple[str, str]] = field(default_factory=list)

    def __str__(self) -> str:
        rungs = "; ".join(f"{p}: {why}" for p, why in self.attempts)
        return f"all search providers failed for {self.query!r} -> {rungs}"


# ── URL normalization (dedup key) ─────────────────────────────────────────────

def normalize_url(url: str) -> str:
    """Best-effort canonical form of `url` used as the dedup/fusion key.

    Lower-cases the host, drops a default port, strips common tracking query
    params, and removes a trailing slash on the path. Never raises — on any
    parse error it falls back to the stripped input so a weird URL still keys to
    itself rather than blowing up the fusion.
    """
    try:
        parts = urllib.parse.urlsplit(url.strip())
        scheme = parts.scheme.lower() or "https"
        host = (parts.hostname or "").lower()
        if parts.port and not (
            (scheme == "https" and parts.port == 443)
            or (scheme == "http" and parts.port == 80)
        ):
            host = f"{host}:{parts.port}"
        # Keep only non-tracking query params, in stable (sorted) order.
        kept = [
            (k, v)
            for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in _TRACKING_PARAMS
        ]
        query = urllib.parse.urlencode(sorted(kept))
        path = parts.path.rstrip("/")
        return urllib.parse.urlunsplit((scheme, host, path, query, ""))
    except Exception:  # noqa: BLE001 - a malformed URL must not break fusion
        return url.strip()


# ── providers: each returns a ranked list and NEVER raises ────────────────────
# Signature: (query, max_results) -> list[SearchResult]. Availability is decided
# by the caller (env/config); a provider invoked here may still legitimately
# raise (network, parse) — search() catches and records it.

def _provider_duckduckgo(query: str, max_results: int) -> List[SearchResult]:
    """Keyless default. Uses the `ddgs` package (DuckDuckGo et al.).

    Degrades gracefully: if `ddgs` is not installed, raise ImportError with an
    actionable message — search() records it as a skipped provider rather than
    failing the whole search.
    """
    try:
        from ddgs import DDGS
    except ImportError as e:  # pragma: no cover - exercised via monkeypatch
        raise ImportError("duckduckgo needs the 'ddgs' package: pip install ddgs") from e

    out: List[SearchResult] = []
    with DDGS() as ddgs:
        for row in ddgs.text(query, max_results=max_results):
            url = row.get("href") or row.get("url") or row.get("link") or ""
            if not url:
                continue
            out.append(SearchResult(
                title=(row.get("title") or "").strip(),
                url=url.strip(),
                snippet=(row.get("body") or row.get("snippet") or "").strip(),
                source="duckduckgo",
            ))
    return out


def _provider_searxng(query: str, max_results: int) -> List[SearchResult]:
    """Self-hosted/instance SearXNG JSON API (only when SEARXNG_URL is set)."""
    import requests

    base = (os.environ.get("SEARXNG_URL") or "").rstrip("/")
    if not base:
        raise RuntimeError("SEARXNG_URL not set")
    resp = requests.get(
        f"{base}/search",
        params={"q": query, "format": "json", "language": "en"},
        headers={"User-Agent": _UA_REAL},
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    rows = resp.json().get("results", []) or []
    out: List[SearchResult] = []
    for row in rows[:max_results]:
        url = (row.get("url") or "").strip()
        if not url:
            continue
        out.append(SearchResult(
            title=(row.get("title") or "").strip(),
            url=url,
            snippet=(row.get("content") or "").strip(),
            source="searxng",
        ))
    return out


def _provider_exa(query: str, max_results: int) -> List[SearchResult]:
    """Exa neural/keyword search via the official REST API (needs EXA_API_KEY).

    The repo's exa_search channel reaches Exa over the keyless mcporter MCP; the
    fusion layer instead uses the official HTTP API keyed by `exa_api_key`
    (env EXA_API_KEY), which is the simplest dependency-free path here.
    """
    import requests

    from searchts.config import Config

    key = Config().get("exa_api_key")
    if not key:
        raise RuntimeError("EXA_API_KEY not set")
    resp = requests.post(
        "https://api.exa.ai/search",
        json={"query": query, "numResults": max_results, "contents": {"text": False}},
        headers={"x-api-key": str(key), "Content-Type": "application/json"},
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    rows = resp.json().get("results", []) or []
    out: List[SearchResult] = []
    for row in rows[:max_results]:
        url = (row.get("url") or "").strip()
        if not url:
            continue
        out.append(SearchResult(
            title=(row.get("title") or "").strip(),
            url=url,
            snippet=(row.get("text") or row.get("snippet") or "").strip(),
            source="exa",
        ))
    return out


def _provider_brave(query: str, max_results: int) -> List[SearchResult]:
    """Brave Search API (needs BRAVE_API_KEY)."""
    import requests

    key = os.environ.get("BRAVE_API_KEY")
    if not key:
        raise RuntimeError("BRAVE_API_KEY not set")
    resp = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": max_results},
        headers={
            "X-Subscription-Token": key,
            "Accept": "application/json",
            "User-Agent": _UA_REAL,
        },
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    rows = (resp.json().get("web", {}) or {}).get("results", []) or []
    out: List[SearchResult] = []
    for row in rows[:max_results]:
        url = (row.get("url") or "").strip()
        if not url:
            continue
        out.append(SearchResult(
            title=(row.get("title") or "").strip(),
            url=url,
            snippet=(row.get("description") or "").strip(),
            source="brave",
        ))
    return out


def _provider_tavily(query: str, max_results: int) -> List[SearchResult]:
    """Tavily search API (needs TAVILY_API_KEY)."""
    import requests

    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        raise RuntimeError("TAVILY_API_KEY not set")
    resp = requests.post(
        "https://api.tavily.com/search",
        json={"api_key": key, "query": query, "max_results": max_results},
        headers={"Content-Type": "application/json"},
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    rows = resp.json().get("results", []) or []
    out: List[SearchResult] = []
    for row in rows[:max_results]:
        url = (row.get("url") or "").strip()
        if not url:
            continue
        out.append(SearchResult(
            title=(row.get("title") or "").strip(),
            url=url,
            snippet=(row.get("content") or "").strip(),
            source="tavily",
        ))
    return out


#: Module-level provider registry. Monkeypatch entries here in tests to feed
#: canned ranked lists without any network. Order is the default escalation
#: order: keyless DuckDuckGo first, then the keyed/instance providers.
PROVIDERS: Dict[str, Callable[[str, int], List[SearchResult]]] = {
    "duckduckgo": _provider_duckduckgo,
    "searxng": _provider_searxng,
    "exa": _provider_exa,
    "brave": _provider_brave,
    "tavily": _provider_tavily,
}


# ── provider availability ─────────────────────────────────────────────────────

def _available_providers() -> List[str]:
    """Default provider selection: duckduckgo plus every configured provider.

    Availability is decided purely by env/config presence so it stays clean and
    testable. Order follows :data:`PROVIDERS` (the escalation order).
    """
    available = ["duckduckgo"]  # keyless default, always selected
    if os.environ.get("SEARXNG_URL"):
        available.append("searxng")
    # Exa: env EXA_API_KEY or the saved config key (matches Config semantics).
    try:
        from searchts.config import Config
        if Config().get("exa_api_key"):
            available.append("exa")
    except Exception:  # noqa: BLE001 - config read must not break selection
        if os.environ.get("EXA_API_KEY"):
            available.append("exa")
    if os.environ.get("BRAVE_API_KEY"):
        available.append("brave")
    if os.environ.get("TAVILY_API_KEY"):
        available.append("tavily")
    # Preserve PROVIDERS order, drop anything unknown.
    return [name for name in PROVIDERS if name in available]


# ── Reciprocal Rank Fusion ─────────────────────────────────────────────────────

def _fuse(
    per_provider: List[Tuple[str, List[SearchResult]]],
    max_results: int,
) -> List[SearchResult]:
    """Merge per-provider ranked lists into one ranking via RRF.

    For each provider list, a result at 0-based ``rank`` contributes
    ``1 / (_RRF_K + rank + 1)`` to its URL's fused score. Results dedupe by
    :func:`normalize_url`; we keep the longest non-empty title/snippet seen and
    record every contributing source (joined into ``source``).
    """
    scores: Dict[str, float] = {}
    # Accumulated best fields + ordered set of sources, keyed by normalized URL.
    titles: Dict[str, str] = {}
    snippets: Dict[str, str] = {}
    display_url: Dict[str, str] = {}
    sources: Dict[str, List[str]] = {}

    for _provider, results in per_provider:
        for rank, res in enumerate(results):
            key = normalize_url(res.url)
            scores[key] = scores.get(key, 0.0) + 1.0 / (_RRF_K + rank + 1)

            # Keep the longest non-empty title/snippet across providers.
            if len(res.title or "") > len(titles.get(key, "")):
                titles[key] = res.title or ""
            if len(res.snippet or "") > len(snippets.get(key, "")):
                snippets[key] = res.snippet or ""
            # First display URL wins (keeps the original, un-normalized form).
            display_url.setdefault(key, res.url)
            # Record each contributing source once, preserving encounter order.
            bucket = sources.setdefault(key, [])
            if res.source and res.source not in bucket:
                bucket.append(res.source)

    # Sort by fused score desc; ties broken by normalized URL for determinism.
    ranked_keys = sorted(scores, key=lambda k: (-scores[k], k))
    fused = [
        SearchResult(
            title=titles.get(key, ""),
            url=display_url.get(key, key),
            snippet=snippets.get(key, ""),
            source=", ".join(sources.get(key, [])),
        )
        for key in ranked_keys
    ]
    return fused[:max_results]


# ── the public entry point ─────────────────────────────────────────────────────

def search(
    query: str,
    max_results: int = 10,
    providers: Optional[List[str]] = None,
) -> List[SearchResult]:
    """Multi-source web search with Reciprocal Rank Fusion.

    Queries each selected provider best-effort (a provider that errors or returns
    nothing is skipped and recorded), then fuses the surviving ranked lists into
    one consensus ranking deduped by normalized URL.

    providers:
        Explicit override of which providers to run, in any order. Names not in
        :data:`PROVIDERS` are recorded as ``unknown-provider``. When omitted, the
        default is DuckDuckGo plus every provider whose key/env is present.

    Returns the top ``max_results`` fused :class:`SearchResult` objects. Raises
    :class:`SearchError` (with a per-provider breakdown) if every selected
    provider failed or returned nothing.
    """
    selected = list(providers) if providers is not None else _available_providers()

    attempts: List[Tuple[str, str]] = []
    per_provider: List[Tuple[str, List[SearchResult]]] = []

    for name in selected:
        fn = PROVIDERS.get(name)
        if fn is None:
            attempts.append((name, "unknown-provider"))
            continue
        try:
            results = fn(query, max_results) or []
        except Exception as e:  # noqa: BLE001 - any provider failure is recorded, never raised
            attempts.append((name, f"{type(e).__name__}: {e}"))
            continue
        if not results:
            attempts.append((name, "no-results"))
            continue
        per_provider.append((name, results))

    if not per_provider:
        raise SearchError(query, attempts)

    return _fuse(per_provider, max_results)
