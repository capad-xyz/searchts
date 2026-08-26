# -*- coding: utf-8 -*-
"""Open-source escalating web fetcher — the "unlocker".

Walks an ordered ladder of backends until one returns real content that is
not a bot-wall challenge page:

  1. ``curl_cffi``      local fetch impersonating a real Chrome (TLS/JA3 + HTTP2
                        fingerprint). Beats user-agent and fingerprint filters.
  2. ``Jina Reader``    free JS-rendering relay (r.jina.ai); good when a page
                        only renders content after JavaScript. Default on;
                        set ``SEARCHTS_NO_JINA=1`` or config ``jina: false`` to
                        skip this third-party hop (URLs are sent to r.jina.ai).
  3. ``stealth-browser`` lazy headless browser for live JS challenges (tier-2,
                        undetected Chromium via patchright; launched only when
                        the lighter rungs fail).

This runs from the user's own IP at personal volume, which sidesteps the
residential-proxy pools that commercial unlockers (Bright Data, Browserbase)
charge for. It is therefore personal-grade, not a scale tool. Interactive
CAPTCHA / Turnstile (e.g. DataDome) is the honest ceiling and needs tier-2 or
a human in the loop.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import re
import stat
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Tuple, TypeVar

_T = TypeVar("_T")

#: Default ladder order. curl_cffi first keeps the URL local + private and is
#: the strongest single backend; Jina is the JS-rendering fallback; the browser
#: tier handles live challenges.
DEFAULT_BACKENDS: List[str] = ["curl_cffi", "Jina Reader", "stealth-browser"]

_UA_REAL = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")

#: A response containing one of these is a block / challenge page, not content.
#: NOTE: match block-PAGE phrases, never vendor names — legit pages embed bot
#: sensor scripts (e.g. Zillow ships the PerimeterX sensor on its real homepage).
_BLOCK_PHRASES = (
    "just a moment...",
    "enable javascript and cookies to continue",
    "checking your browser before accessing",
    "attention required! | cloudflare",
    "/cdn-cgi/challenge-platform",
    "_cf_chl_opt",
    "press & hold",
    "access to this page has been denied",
    "verify you are human",
    "please verify you are a human",
    "request unsuccessful. incapsula incident",
    "captcha-delivery.com",
    "target url returned error",  # Jina relay's HTTP-200 wrapper around an upstream block
    "awswafcookiedomainlist",     # AWS WAF JS challenge (e.g. Dribbble): window.awsWafCookieDomainList
    "gokuprops",                  # AWS WAF challenge token blob (window.gokuProps)
    # --- other WAF / bot-manager block pages. INTERSTITIAL-ONLY copy (not vendor
    # sensor-JS names), so we never flag a real page that merely embeds a sensor.
    # Most also serve a 4xx/5xx (already escalated); these catch the on-200/202/302
    # variants (Imperva, Akamai, DataDome, Queue-it, Radware, Vercel, ...).
    "pardon our interruption",                   # F5/Shape (Distil) + some Imperva block pages
    "powered by incapsula",                      # Imperva/Incapsula block page (can serve on HTTP 200)
    "please enable js and disable any ad blocker",  # DataDome challenge (<p id="cmsg">)
    "px-captcha",                                # PerimeterX/HUMAN challenge mount element
    "oops! it appears something made us think you are a bot",  # PerimeterX block copy
    "sucuri website firewall",                   # Sucuri WAF block page
    "vercel security checkpoint",                # Vercel bot-protection checkpoint
    "needs to review the security of your connection before proceeding",  # Cloudflare managed challenge
    "press and hold to verify that you are human",  # Arkose Labs / FunCaptcha enforcement
    "queue-it.net",                              # Queue-it virtual waiting room (302 -> waiting page)
    "perfdrive.com",                             # Radware Bot Manager challenge host (validate/captcha.perfdrive.com)
    "window.kpsdk",                              # Kasada challenge bootstrap (usually HTTP 429)
    "reference #18.",                            # Akamai Bot Manager deny-page reference id
    "errors.edgesuite.net",                     # Akamai/EdgeSuite error interstitial host
    "your request has been blocked as a possible bot",  # Fastly Bot Management block copy
    "checking if the site connection is secure",  # Cloudflare interstitial (alt phrasing)
    "complete the challenge below",  # Reddit bot interstitial (often HTTP 200)
    "let us know you're a real person",
    "let us know you are a real person",
    "we're committed to safety",  # Reddit interstitial lead-in (short extract)
    "we are committed to safety",
    # Reddit login walls (old.reddit / .com) — long enough to beat thin gate
    "accounts are required to access old reddit",
    "to keep reddit safe",
    "log in, or continue without an account",
)

_MIN_CHARS = 500


@dataclass
class FetchResult:
    backend: str
    text: str
    status: Optional[int]
    #: Prompt-injection findings detected in the fetched content (empty if none).
    #: Defaulted so existing positional construction FetchResult(backend, text,
    #: status) keeps working unchanged.
    warnings: List[str] = field(default_factory=list)
    #: URL after redirects (may differ from the requested URL). Defaults to None
    #: so existing positional construction stays valid; ``fetch`` always sets it.
    final_url: Optional[str] = None
    #: ISO-8601 UTC timestamp of the successful fetch (set by ``fetch`` / ``_finalize``).
    fetched_at: Optional[str] = None
    #: Normalized response headers. Defaulted to preserve positional construction.
    headers: Dict[str, str] = field(default_factory=dict)


@dataclass
class UnlockerError(Exception):
    url: str
    attempts: List[Tuple[str, str]] = field(default_factory=list)

    def __str__(self) -> str:
        rungs = "; ".join(f"{b}: {why}" for b, why in self.attempts)
        return f"all backends failed for {self.url} -> {rungs}"


def normalize(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


# ── per-domain backend memory (Feature C) ────────────────────────────────────
# Remember, per registrable domain, which backend last produced a clean win, so
# repeat visits skip straight to the rung that works instead of re-walking the
# whole ladder from curl_cffi. Stored at <config-dir>/unlocker_cache.json; all
# IO is best-effort and NEVER raises — a corrupt or unwritable cache silently
# degrades to "no memory" rather than breaking a fetch. Each entry carries an
# ISO-8601 UTC timestamp (P3.3); entries older than _MEMORY_TTL_SECONDS (default
# 24h) are expired — ignored on promotion and dropped on load/save. A remembered
# backend that fails (block/thin/exception) before a clean win is unpinned so
# later fetches aren't stuck on a dead rung.

#: Same config dir as searchts.config.Config (~/.searchts).
_CACHE_DIR = Path.home() / ".searchts"
_CACHE_PATH = _CACHE_DIR / "unlocker_cache.json"

#: Default TTL for a remembered backend: 24h. After this an entry is expired
#: (ignored on promotion, dropped on load/save) so a dead rung can't pin a
#: domain forever.
_MEMORY_TTL_SECONDS: int = 24 * 60 * 60

#: Multi-label public suffixes we special-case so the registrable domain keeps
#: the right number of labels (e.g. bbc.co.uk, not co.uk). Not exhaustive — a
#: heuristic that avoids pulling in a public-suffix-list dependency; unknown
#: suffixes fall back to the last two labels.
_MULTI_SUFFIXES = frozenset({
    "co.uk", "org.uk", "gov.uk", "ac.uk", "co.jp", "co.kr", "co.in",
    "com.au", "com.br", "com.cn", "com.mx", "com.tr", "co.nz", "co.za",
})


def _memory_enabled() -> bool:
    """Global off-switch via env var (SEARCHTS_NO_MEMORY=1)."""
    return os.environ.get("SEARCHTS_NO_MEMORY", "") not in ("1", "true", "True", "yes")


def jina_enabled() -> bool:
    """Whether the Jina Reader rung is on the default ladder (P3.5 / Q4).

    Default is **on**. ``SEARCHTS_NO_JINA=1`` (or true/yes) disables the
    third-party relay so URLs never leave the machine via r.jina.ai.
    Config key ``jina: false`` (YAML under ~/.searchts) also disables when the
    env is unset. Explicit ``backends=[..., "Jina Reader"]`` still runs Jina —
    only the default ladder is filtered.
    """
    no = os.environ.get("SEARCHTS_NO_JINA", "").strip().lower()
    if no in ("1", "true", "yes", "on"):
        return False
    # Optional positive/negative via SEARCHTS_JINA (env beats YAML).
    j = os.environ.get("SEARCHTS_JINA", "").strip().lower()
    if j in ("0", "false", "no", "off"):
        return False
    if j in ("1", "true", "yes", "on"):
        return True
    try:
        from searchts.config import Config
        raw = Config().data.get("jina", True)
    except Exception:  # noqa: BLE001 - config must never break fetch
        return True
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str) and raw.strip().lower() in ("0", "false", "no", "off"):
        return False
    return True




def registrable_domain(url: str) -> str:
    """Best-effort registrable domain (eTLD+1) for a URL, lower-cased.

    Uses a small built-in multi-label-suffix table; falls back to the last two
    labels. Good enough to key the backend cache; never raises.
    """
    try:
        host = urllib.parse.urlsplit(normalize(url)).hostname or ""
    except Exception:  # noqa: BLE001 - malformed input must not break the ladder
        host = ""
    host = host.lower().strip(".")
    # A real hostname has no whitespace; reject obvious garbage so it does not
    # become a junk cache key.
    if not host or any(c.isspace() for c in host):
        return ""
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    last_two = ".".join(parts[-2:])
    if last_two in _MULTI_SUFFIXES:
        return ".".join(parts[-3:])
    return last_two


def _cache_path() -> Path:
    """Resolve the cache path, honouring SEARCHTS_CACHE_DIR for tests/overrides."""
    override = os.environ.get("SEARCHTS_CACHE_DIR")
    if override:
        d = Path(override)
        return d / "unlocker_cache.json"
    return _CACHE_PATH


def _load_raw() -> Dict[str, object]:
    """Load the raw cache dict (domain -> backend or domain -> {backend, ts}).

    Best-effort: returns {} on any error (missing/corrupt file). Does NOT
    apply TTL — callers filter expired entries themselves.
    """
    try:
        with open(_cache_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): v for k, v in data.items()}
    except Exception:  # noqa: BLE001 - missing/corrupt cache is non-fatal
        pass
    return {}


def _entry_backend(val: object) -> Optional[str]:
    """Extract the backend name from a cache entry (str or dict)."""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        b = val.get("backend")
        if isinstance(b, str):
            return b
    return None


def _entry_ts(val: object) -> Optional[str]:
    """Extract the ISO timestamp from a cache entry (string-only or dict)."""
    if isinstance(val, dict):
        ts = val.get("ts")
        if isinstance(ts, str):
            return ts
    return None


def _entry_is_expired(val: object) -> bool:
    """True if the entry has no usable timestamp (string-only) or is older than TTL.

    String-only entries (old cache format) count as expired so a stale file can
    never pin a domain forever.
    """
    ts = _entry_ts(val)
    if ts is None:
        return True
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - dt).total_seconds()
    return age >= _MEMORY_TTL_SECONDS


def _now_iso() -> str:
    """ISO-8601 UTC timestamp for cache entries."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_entry(backend: str) -> Dict[str, str]:
    """Build a timestamped cache entry for a domain."""
    return {"backend": backend, "ts": _now_iso()}


def _write_raw(raw: Dict[str, object]) -> None:
    """Persist the raw cache dict. Best-effort, never raises."""
    # Drop expired *and* malformed entries so memory doesn't accumulate
    # tombstones (Rabbit: fresh invalid values must not stick on disk).
    cleaned = {
        d: v
        for d, v in raw.items()
        if isinstance(d, str)
        and _entry_backend(v) is not None
        and not _entry_is_expired(v)
    }
    if not cleaned:
        try:
            _cache_path().unlink(missing_ok=True)
        except Exception:  # noqa: BLE001 - best-effort
            pass
        return
    try:
        _cache_path().parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(cleaned, ensure_ascii=False, indent=2)
        try:
            fd = os.open(
                str(_cache_path()),
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                stat.S_IRUSR | stat.S_IWUSR,  # 0o600
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
        except OSError:
            with open(_cache_path(), "w", encoding="utf-8") as f:
                f.write(payload)
    except Exception:  # noqa: BLE001 - cache write failure must not break fetch
        pass


def load_memory() -> Dict[str, str]:
    """Load the domain -> backend map, with expired entries dropped.

    Best-effort: returns {} on any error. Honours SEARCHTS_NO_MEMORY (already
    disabled by callers, but safe if called directly).
    """
    if not _memory_enabled():
        return {}
    raw = _load_raw()
    out: Dict[str, str] = {}
    dropped = False
    for domain, val in raw.items():
        if not isinstance(domain, str):
            continue
        backend = _entry_backend(val)
        if backend is None:
            dropped = True
            continue
        # String-only entries have no timestamp → treat as expired so stale
        # cache files can never pin a domain forever.
        if _entry_is_expired(val):
            dropped = True
            continue
        out[domain] = backend
    if dropped:
        _write_raw(raw)
    return out


def remember(domain: str, backend: str) -> None:
    """Record `backend` as the last winner for `domain`. Best-effort, never raises."""
    if not domain or not backend:
        return
    if not _memory_enabled():
        return
    try:
        raw = _load_raw()
        raw[domain] = _make_entry(backend)
        _write_raw(raw)
    except Exception:  # noqa: BLE001 - cache write failure must not break fetch
        pass


def unpin(domain: str) -> None:
    """Remove the remembered backend for `domain`. Best-effort, never raises.

    Called when a remembered backend fails before walking the rest of the
    ladder, so later fetches don't get stuck on a dead winner.
    """
    if not domain:
        return
    if not _memory_enabled():
        return
    try:
        raw = _load_raw()
        if domain in raw:
            del raw[domain]
            _write_raw(raw)
    except Exception:  # noqa: BLE001 - cache write failure must not break fetch
        pass


def _drop_stale_challenge_headers(headers: Dict[str, str], html: str) -> Dict[str, str]:
    """Drop first-response challenge stamps when the rendered body is clean."""
    if looks_blocked(200, html) is not None:
        return headers
    out = dict(headers)
    out.pop("cf-mitigated", None)
    if str(out.get("x-datadome-ch") or "").lower() in ("blocked", "challenge"):
        out.pop("x-datadome-ch", None)
    if "challenge" in str(out.get("x-akamai-session-info") or "").lower():
        out.pop("x-akamai-session-info", None)
    return out


def looks_blocked(
    status: Optional[int],
    text: str,
    headers: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """Return a short reason if the response is a hard block/challenge page, else None.

    HTTP errors (including vendor codes like 999), known challenge phrases, and
    explicit challenge headers count as blocked. Thin-but-real pages are not a
    block; ``fetch`` escalates, then fails unless ``allow_thin`` is set.
    """
    if status is None:
        return "no-response"
    if status >= 400:
        return f"http-{status}"
    if headers:
        if headers.get("cf-mitigated") == "challenge":
            return "challenge"
        # Explicit block stamps (not "Server: AkamaiGHost" — that hosts real pages).
        if str(headers.get("x-datadome-ch") or "").lower() in ("blocked", "challenge"):
            return "challenge"
        if str(headers.get("x-akamai-session-info") or "").lower().find("challenge") >= 0:
            return "challenge"
    head = (text or "")[:8192].lower()
    for phrase in _BLOCK_PHRASES:
        if phrase in head:
            return "challenge"
    return None


def html_to_text(html: str, url: Optional[str] = None) -> str:
    """Extract clean main-content markdown from raw HTML (trafilatura, with fallback)."""
    try:
        import trafilatura
        out = trafilatura.extract(
            html, url=url, output_format="markdown",
            include_links=True, include_tables=True, favor_recall=True,
        )
        if out and out.strip():
            return out.strip()
    except Exception:
        pass
    # Fallback: crude tag strip so we never hard-fail on extraction.
    import html as _html
    t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    t = re.sub(r"(?s)<[^>]+>", "\n", t)
    t = _html.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n\n", t)
    return t.strip()


# ── backend fetchers: each returns (status, body, final_url, headers) or raises ──

def _normalize_headers(headers: Mapping[str, object]) -> Dict[str, str]:
    """Return string response headers with case-insensitive names normalized."""
    return {str(name).lower(): str(value) for name, value in headers.items()}


def _fetch_curl_cffi(url: str, timeout: int = 30) -> Tuple[int, str, str, Dict[str, str]]:
    from curl_cffi import requests as cr
    r = cr.get(url, impersonate="chrome", timeout=timeout,
               headers={"Accept-Language": "en-US,en;q=0.9"})
    final = str(getattr(r, "url", None) or url)
    return r.status_code, r.text, final, _normalize_headers(dict(r.headers.items()))


def _fetch_jina(url: str, timeout: int = 40) -> Tuple[int, str, str, Dict[str, str]]:
    # Jina is a relay: we asked for `url`, so report that as the final source URL
    # (the wire URL is r.jina.ai/... which is not useful for citations).
    req = urllib.request.Request(
        "https://r.jina.ai/" + url,
        headers={"User-Agent": _UA_REAL, "Accept": "text/plain"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        headers = _normalize_headers(dict(resp.headers.items()))
        return resp.status, resp.read().decode("utf-8", "replace"), url, headers


def _await_hydration(page, html: str, budget_ms: int = 8000, step_ms: int = 500) -> str:
    """Poll until the rendered HTML stops growing; return the fullest seen.

    A JS app is still an empty shell at ``domcontentloaded``, so reading
    ``page.content()`` immediately yields pre-hydration markup and the caller
    judges a live page to be thin. Polling for content-length stability beats
    waiting for ``networkidle``, which never settles on pages holding a live
    connection (streaming, websockets, analytics beacons).

    Stops as soon as two consecutive reads agree, so an already-rendered page
    costs one extra step rather than the whole budget.
    """
    waited = 0
    while waited < budget_ms:
        page.wait_for_timeout(step_ms)
        waited += step_ms
        try:
            current = page.content()
        except Exception:  # noqa: BLE001 - page may navigate mid-read
            break
        if len(current) <= len(html):
            break  # stopped growing: hydrated, or static all along
        html = current
    return html


def _call_sync_browser(fn: Callable[..., _T], *args, **kwargs) -> _T:
    """Run sync Playwright work off a running asyncio loop (MCP FastMCP path).

    ``mcp`` 1.x FastMCP invokes sync tools on the event-loop thread. Patchright's
    ``sync_playwright`` refuses to start there (\"Sync API inside asyncio loop\").
    When a loop is already running, offload to a one-shot worker thread; CLI and
    plain sync callers keep the inline path.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return fn(*args, **kwargs)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(fn, *args, **kwargs).result()


def _fetch_stealth(
    url: str, timeout: int = 60
) -> Tuple[Optional[int], str, str, Dict[str, str]]:
    """Tier-2: render with an undetected headless Chromium (patchright).

    Lazy by construction — patchright is imported and the browser launched only
    when this backend is reached, then torn down immediately, so it costs memory
    only on the hard pages that tier-1 could not crack (keeps a 16GB box happy).

    Auto-resolves non-interactive JS / Cloudflare "managed" challenges by letting
    the page execute and polling until the challenge markup clears. Interactive
    CAPTCHA (DataDome, Turnstile click-to-verify) is the honest ceiling and will
    still come back as a challenge page.

    Safe under MCP/FastMCP: see ``_call_sync_browser``.
    """
    return _call_sync_browser(_fetch_stealth_impl, url, timeout)


def _fetch_stealth_impl(
    url: str, timeout: int = 60
) -> Tuple[Optional[int], str, str, Dict[str, str]]:
    try:
        from patchright.sync_api import sync_playwright
    except ImportError as e:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "stealth-browser backend needs patchright: "
            "pip install patchright && patchright install chromium"
        ) from e

    ms = int(timeout * 1000)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(
                user_agent=_UA_REAL, locale="en-US",
                viewport={"width": 1280, "height": 800},
            )
            page = ctx.new_page()
            resp = page.goto(url, wait_until="domcontentloaded", timeout=ms)
            init_status = resp.status if resp else None
            headers = _normalize_headers(resp.all_headers()) if resp else {}
            # Let a JS app hydrate before judging the page; otherwise an SPA
            # comes back as a near-empty shell and reads as "thin".
            html = _await_hydration(page, page.content())
            # Wait (bounded) for a managed JS challenge to auto-resolve.
            waited = 0
            while waited < 15000 and looks_blocked(200, html) == "challenge":
                page.wait_for_timeout(1500)
                waited += 1500
                try:
                    html = page.content()
                except Exception:  # noqa: BLE001 - page may navigate mid-read
                    break
            # If the challenge cleared, the real status is 200 regardless of the
            # initial challenge response; otherwise keep the original status.
            status = 200 if looks_blocked(200, html) is None else init_status
            final = page.url or url
            # page.goto headers can still say "challenge" after the DOM cleared.
            headers = _drop_stale_challenge_headers(headers, html)
            return status, html, final, headers
        finally:
            browser.close()


def _fetch_human(url: str, timeout: int = 180) -> Tuple[Optional[int], str, str]:
    """Human-in-the-loop fallback: open a HEADFUL browser and let the user solve it.

    Last resort for interactive CAPTCHA / Turnstile (DataDome et al.) that no
    automated rung can clear. Launches a visible (headless=False) patchright
    Chromium, prints an instruction to stderr, then polls the page content until
    ``looks_blocked`` clears or `timeout` seconds elapse, and returns
    (status, html, final_url). Raises RuntimeError if patchright is unavailable so the
    caller can re-raise the original UnlockerError.

    Safe under MCP/FastMCP: see ``_call_sync_browser``.
    """
    return _call_sync_browser(_fetch_human_impl, url, timeout)


def _fetch_human_impl(url: str, timeout: int = 180) -> Tuple[Optional[int], str, str]:
    try:
        from patchright.sync_api import sync_playwright
    except ImportError as e:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "human-browser fallback needs patchright: "
            "pip install patchright && patchright install chromium"
        ) from e

    print(
        f"A browser opened - solve the challenge/CAPTCHA; waiting up to {timeout} s...",
        file=sys.stderr,
        flush=True,
    )

    deadline_ms = int(timeout * 1000)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        try:
            ctx = browser.new_context(
                user_agent=_UA_REAL, locale="en-US",
                viewport={"width": 1280, "height": 800},
            )
            page = ctx.new_page()
            resp = page.goto(url, wait_until="domcontentloaded", timeout=min(60000, deadline_ms))
            init_status = resp.status if resp else None
            html = _await_hydration(page, page.content())
            waited = 0
            while waited < deadline_ms and looks_blocked(200, html) == "challenge":
                page.wait_for_timeout(1500)
                waited += 1500
                try:
                    html = page.content()
                except Exception:  # noqa: BLE001 - page may navigate mid-read
                    break
            status = 200 if looks_blocked(200, html) is None else init_status
            final = page.url or url
            return status, html, final
        finally:
            browser.close()


# ── the ladder ───────────────────────────────────────────────────────────────

def _finalize(result: FetchResult, scrub: bool) -> FetchResult:
    """Sanitize a winning FetchResult before returning it.

    ALWAYS strips invisible/control chars and scans for prompt-injection
    indicators, attaching any findings to ``result.warnings``. When ``scrub`` is
    True the matched injection spans in the text are redacted too. Untrusted web
    content must never reach a model with hidden instructions intact.
    """
    from searchts import sanitize

    out = sanitize.scrub(result.text, redact=scrub)
    result.text = out.text
    if not result.fetched_at:
        result.fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result.warnings = out.findings
    return result


def fetch(url: str, backends: Optional[List[str]] = None,
          min_chars: int = _MIN_CHARS, use_memory: bool = True,
          allow_human: bool = False, scrub: bool = False,
          allow_thin: bool = False, progress: bool = False) -> FetchResult:
    """Fetch `url` as agent-readable text, escalating through `backends`.

    Returns the first FetchResult that yields real content; raises UnlockerError
    with a per-backend breakdown if every rung fails.

    use_memory:
        When True (and SEARCHTS_NO_MEMORY is unset), a backend previously
        recorded as the winner for this URL's registrable domain is moved to the
        FRONT of the ladder, and a fresh clean win is persisted for next time.
    allow_thin:
        When True and no rung met ``min_chars``, return the longest non-blocked
        body instead of raising. Default False: thin/challenge leftovers are
        UnlockerError (P3.2). Scorecard smoke cases pass ``min_chars=0``.
    allow_human:
        When True and no rung produced a clean win, fall back to a HEADFUL
        browser the user solves by hand (Feature D). Covers interactive
        CAPTCHAs and soft walls alike — a login page served as HTTP 200 is a
        thin result, not a challenge, and must still reach this rung. Default
        False so normal/agent use is never interrupted.
    scrub:
        Prompt-injection handling for the returned content. Invisible/control
        characters are ALWAYS stripped and the text is ALWAYS scanned, with any
        findings attached to ``result.warnings``. When True, matched injection
        spans are additionally redacted from the text. Default False (report,
        don't alter visible content).
    progress:
        When True, print one stderr line per ladder rung (``trying curl_cffi…``)
        so long CLI fetches are not silent. Off by default so MCP/library
        callers stay quiet. Also on when ``SEARCHTS_PROGRESS=1``.
    """
    if not progress:
        progress = os.environ.get("SEARCHTS_PROGRESS", "") in (
            "1", "true", "True", "yes",
        )

    def _tick(msg: str) -> None:
        # Best-effort only: a closed/broken stderr must never abort the fetch.
        if not progress:
            return
        try:
            print(msg, file=sys.stderr, flush=True)
        except (OSError, ValueError):
            pass

    url = normalize(url)

    # Tier-0: AI-chat share links (chatgpt.com/share, claude.ai/share, poe.com/s)
    # carry their conversation in provider-specific data channels that generic
    # HTML extraction can't see (or sees only partially). A dedicated extractor
    # returns the COMPLETE conversation; any failure falls through to the ladder.
    try:
        from searchts import share_extractors
        share = share_extractors.extract(url) if share_extractors.matches(url) else None
    except Exception:  # noqa: BLE001 - tier-0 must never break the ladder
        share = None
    if share is not None and share.markdown:
        return _finalize(
            FetchResult(f"share:{share.provider}", share.markdown, 200, final_url=url),
            scrub,
        )

    order = list(backends if backends is not None else DEFAULT_BACKENDS)
    if not jina_enabled():
        order = [b for b in order if b != "Jina Reader"]

    memory_on = use_memory and _memory_enabled()
    domain = registrable_domain(url) if memory_on else ""
    remembered: Optional[str] = None
    if memory_on and domain:
        # load_memory drops expired entries, so a remembered backend here is
        # non-expired and safe to promote to the front of the ladder.
        remembered = load_memory().get(domain)
        if remembered and remembered in order:
            order.remove(remembered)
            order.insert(0, remembered)

    attempts: List[Tuple[str, str]] = []
    best: Optional[FetchResult] = None  # richest non-blocked but thin result so far
    status: Optional[int] = None

    for backend in order:
        _tick(f"trying {backend}…")
        try:
            final_url = url
            headers: Dict[str, str] = {}
            if backend == "curl_cffi":
                status, body, final_url, headers = _fetch_curl_cffi(url)
                reason = looks_blocked(status, body, headers)
                if reason:
                    attempts.append((backend, reason))
                    _tick(f"  {backend}: {reason}")
                    if backend == remembered:
                        unpin(domain)
                        remembered = None
                    continue
                text = html_to_text(body, url)
            elif backend == "Jina Reader":
                status, body, final_url, headers = _fetch_jina(url)
                reason = looks_blocked(status, body, headers)
                if reason:
                    attempts.append((backend, reason))
                    _tick(f"  {backend}: {reason}")
                    if backend == remembered:
                        unpin(domain)
                        remembered = None
                    continue
                text = body  # Jina already returns markdown
            elif backend == "stealth-browser":
                status, body, final_url, headers = _fetch_stealth(url)
                reason = looks_blocked(status, body, headers)
                if reason:
                    attempts.append((backend, reason))
                    _tick(f"  {backend}: {reason}")
                    if backend == remembered:
                        unpin(domain)
                        remembered = None
                    continue
                text = html_to_text(body, url)
            else:
                attempts.append((backend, "unknown-backend"))
                _tick(f"  {backend}: unknown-backend")
                if backend == remembered:
                    unpin(domain)
                    remembered = None
                continue

            text = text or ""
            if len(text) >= min_chars:
                if memory_on and domain:
                    remember(domain, backend)  # record the winner for next time
                _tick(f"  {backend}: ok ({len(text)} chars)")
                # clean win, stop here — sanitize untrusted content before return
                return _finalize(
                    FetchResult(
                        backend,
                        text,
                        status,
                        final_url=final_url or url,
                        headers=headers,
                    ),
                    scrub,
                )
            # Real but thin (e.g. JS-rendered or genuinely short): keep as a
            # fallback and escalate in case a richer backend renders more.
            attempts.append((backend, f"thin-{len(text)}b"))
            _tick(f"  {backend}: thin-{len(text)}b")
            if backend == remembered:
                # Remembered backend produced a thin result, not a clean win —
                # unpin so the ladder isn't stuck on a flaky winner.
                unpin(domain)
                remembered = None
            if best is None or len(text) > len(best.text):
                best = FetchResult(
                    backend,
                    text,
                    status,
                    final_url=final_url or url,
                    headers=headers,
                )
        except Exception as e:  # noqa: BLE001 — any backend failure escalates
            why = f"{type(e).__name__}: {e}"
            attempts.append((backend, why))
            _tick(f"  {backend}: {why}")
            if backend == remembered:
                unpin(domain)
                remembered = None
            continue

    # Human-in-the-loop last resort. Runs BEFORE the `best` fallback below:
    # a soft wall (login page served as HTTP 200) leaves a thin `best`, and
    # returning it here would skip the human rung entirely — exactly the case
    # --human exists for. Reaching this point already means no rung produced a
    # clean win, and the flag is explicit and off by default, so honour it
    # rather than second-guessing which failures a human could fix.
    if allow_human:
        _tick("trying human-browser…")
        try:
            status, html, final_url = _fetch_human(url)
        except Exception:  # noqa: BLE001 - patchright missing/launch failure
            status, html, final_url = None, "", url
        if looks_blocked(status, html) is None:
            text = html_to_text(html, url)
            if text and (best is None or len(text) > len(best.text)):
                human = FetchResult(
                    backend="human-browser", text=text, status=status,
                    final_url=final_url or url,
                )
                if len(text) >= min_chars:
                    return _finalize(human, scrub)
                best = human

    if allow_thin and best is not None:
        return _finalize(best, scrub)

    raise UnlockerError(url, attempts)
