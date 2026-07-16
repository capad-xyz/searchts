# -*- coding: utf-8 -*-
"""Open-source escalating web fetcher — the "unlocker".

Walks an ordered ladder of backends until one returns real content that is
not a bot-wall challenge page:

  1. ``curl_cffi``      local fetch impersonating a real Chrome (TLS/JA3 + HTTP2
                        fingerprint). Beats user-agent and fingerprint filters.
  2. ``Jina Reader``    free JS-rendering relay (r.jina.ai); good when a page
                        only renders content after JavaScript.
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
from typing import Dict, List, Mapping, Optional, Tuple

#: Default ladder order. curl_cffi first keeps the URL local + private and is
#: the strongest single backend; Jina is the JS-rendering fallback; the browser
#: tier handles live challenges.
DEFAULT_BACKENDS: List[str] = ["curl_cffi", "Jina Reader", "stealth-browser"]

_UA_REAL = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

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
# degrades to "no memory" rather than breaking a fetch.

#: Same config dir as searchts.config.Config (~/.searchts).
_CACHE_DIR = Path.home() / ".searchts"
_CACHE_PATH = _CACHE_DIR / "unlocker_cache.json"

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


def load_memory() -> Dict[str, str]:
    """Load the domain -> backend map. Best-effort: returns {} on any error."""
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception:  # noqa: BLE001 - missing/corrupt cache is non-fatal
        pass
    return {}


def remember(domain: str, backend: str) -> None:
    """Record `backend` as the last winner for `domain`. Best-effort, never raises."""
    if not domain or not backend:
        return
    try:
        mem = load_memory()
        if mem.get(domain) == backend:
            return  # no change — skip the write
        mem[domain] = backend
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # Write owner-only from the start (mirrors Config.save); fall back to a
        # plain write on platforms where the os.open flags aren't honored.
        payload = json.dumps(mem, ensure_ascii=False, indent=2)
        try:
            fd = os.open(
                str(_CACHE_PATH),
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                stat.S_IRUSR | stat.S_IWUSR,  # 0o600
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
        except OSError:
            with open(_CACHE_PATH, "w", encoding="utf-8") as f:
                f.write(payload)
    except Exception:  # noqa: BLE001 - cache write failure must not break fetch
        pass


def looks_blocked(
    status: Optional[int],
    text: str,
    headers: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """Return a short reason if the response is a hard block/challenge page, else None.

    HTTP errors, known challenge phrases, and explicit challenge headers count as
    blocked. Short-but-real content is NOT a block (example.com is tiny yet valid); the
    fetch ladder treats a thin extraction as a reason to escalate, then falls back to
    the best result.
    """
    if status is None:
        return "no-response"
    if status >= 400:
        return f"http-{status}"
    if headers and headers.get("cf-mitigated") == "challenge":
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
    """
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
            html = page.content()
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
    """
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
            html = page.content()
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


def _challenge_seen(attempts: List[Tuple[str, str]]) -> bool:
    """True if any failed attempt looked like an interactive challenge/CAPTCHA."""
    for _backend, reason in attempts:
        if reason == "challenge" or reason.startswith("http-403"):
            return True
    return False


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
          allow_human: bool = False, scrub: bool = False) -> FetchResult:
    """Fetch `url` as agent-readable text, escalating through `backends`.

    Returns the first FetchResult that yields real content; raises UnlockerError
    with a per-backend breakdown if every rung fails.

    use_memory:
        When True (and SEARCHTS_NO_MEMORY is unset), a backend previously
        recorded as the winner for this URL's registrable domain is moved to the
        FRONT of the ladder, and a fresh clean win is persisted for next time.
    allow_human:
        When True and the automated ladder fails on an interactive challenge /
        CAPTCHA, fall back to a HEADFUL browser the user solves by hand
        (Feature D). Default False so normal/agent use is never interrupted.
    scrub:
        Prompt-injection handling for the returned content. Invisible/control
        characters are ALWAYS stripped and the text is ALWAYS scanned, with any
        findings attached to ``result.warnings``. When True, matched injection
        spans are additionally redacted from the text. Default False (report,
        don't alter visible content).
    """
    url = normalize(url)
    order = list(backends or DEFAULT_BACKENDS)

    memory_on = use_memory and _memory_enabled()
    domain = registrable_domain(url) if memory_on else ""
    if memory_on and domain:
        remembered = load_memory().get(domain)
        # Move a remembered, still-valid backend to the front of the ladder.
        if remembered and remembered in order:
            order.remove(remembered)
            order.insert(0, remembered)

    attempts: List[Tuple[str, str]] = []
    best: Optional[FetchResult] = None  # richest non-blocked but thin result so far
    status: Optional[int] = None

    for backend in order:
        try:
            final_url = url
            headers: Dict[str, str] = {}
            if backend == "curl_cffi":
                status, body, final_url, headers = _fetch_curl_cffi(url)
                reason = looks_blocked(status, body, headers)
                if reason:
                    attempts.append((backend, reason))
                    continue
                text = html_to_text(body, url)
            elif backend == "Jina Reader":
                status, body, final_url, headers = _fetch_jina(url)
                reason = looks_blocked(status, body, headers)
                if reason:
                    attempts.append((backend, reason))
                    continue
                text = body  # Jina already returns markdown
            elif backend == "stealth-browser":
                status, body, final_url, headers = _fetch_stealth(url)
                reason = looks_blocked(status, body, headers)
                if reason:
                    attempts.append((backend, reason))
                    continue
                text = html_to_text(body, url)
            else:
                attempts.append((backend, "unknown-backend"))
                continue

            text = text or ""
            if len(text) >= min_chars:
                if memory_on and domain:
                    remember(domain, backend)  # record the winner for next time
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
            if best is None or len(text) > len(best.text):
                best = FetchResult(
                    backend,
                    text,
                    status,
                    final_url=final_url or url,
                    headers=headers,
                )
        except Exception as e:  # noqa: BLE001 — any backend failure escalates
            attempts.append((backend, f"{type(e).__name__}: {e}"))
            continue

    if best is not None:
        # best-effort real content beats reporting a false block
        return _finalize(best, scrub)

    err = UnlockerError(url, attempts)

    # Human-in-the-loop last resort: only when explicitly allowed AND the ladder
    # failed on an interactive challenge/CAPTCHA we can't auto-clear.
    if allow_human and _challenge_seen(attempts):
        try:
            status, html, final_url = _fetch_human(url)
        except Exception:  # noqa: BLE001 - patchright missing/launch failure
            raise err
        if looks_blocked(status, html) is None:
            text = html_to_text(html, url)
            if text:
                return _finalize(
                    FetchResult(
                        backend="human-browser", text=text, status=status,
                        final_url=final_url or url,
                    ),
                    scrub,
                )
        raise err  # stayed blocked / timed out -> original failure

    raise err
