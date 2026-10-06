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

#: Login *shells* (HTTP 200, often longer than ``_MIN_CHARS`` after extract).
#: Distinctive wall copy only — never a lone "sign in" in page chrome
#: (Wikipedia / GitHub nav would false-positive).
_LOGIN_WALL_PHRASES = (
    "new to linkedin",
    "sign in to linkedin",
    "sign in to continue",
    "log in to continue",
    "please sign in to continue",
    "please log in to continue",
    "you must be logged in",
    "you must be signed in",
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
    #: F23a: the next page when the page links one (``rel=next``, a pager, a
    #: "Load more" link). None when nothing was detected, which is not a
    #: promise that the page is complete.
    next_url: Optional[str] = None
    #: F23a: what the page has beyond this read, as ``{kind, note, url?}``
    #: (kinds: next-page, feed, fold, list, count). The notes are also the last
    #: lines of ``text``.
    more: List[Dict[str, str]] = field(default_factory=list)
    #: Page HTML kept only until ``_finalize`` runs detection; never returned.
    page_html: Optional[str] = field(default=None, repr=False, compare=False)


@dataclass
class UnlockerError(Exception):
    url: str
    attempts: List[Tuple[str, str]] = field(default_factory=list)

    def __str__(self) -> str:
        rungs = "; ".join(f"{b}: {why}" for b, why in self.attempts)
        return f"all backends failed for {self.url} -> {rungs}"


_BLOCKED_SCHEMES = (
    "file:",
    "data:",
    "javascript:",
    "ftp:",
    "gopher:",
    "about:",
    "mailto:",
)


def normalize(url: str) -> str:
    """Return an http(s) URL. Bare hosts (and ``host:port``) get ``https://``.

    Never rewrite other schemes: ``file://`` / ``data:`` used to become
    ``https://file://…`` and then fetch. That was a silent lie (P1.4).
    Raises ValueError instead.

    ``urllib.parse`` treats ``example.com:8080`` as scheme ``example.com``.
    Only a real ``://`` (or a blocked prefix like ``data:``) is a scheme.
    """
    from searchts.ssrf import unwrap_link  # stdlib-only module, no import cycle

    raw = unwrap_link(url)  # "<https://…>" / "[https://…]" pasted from chat (F22c)
    if not raw:
        raise ValueError("empty url")
    lower = raw.lower()
    if lower.startswith(_BLOCKED_SCHEMES):
        scheme = lower.split(":", 1)[0]
        raise ValueError(f"scheme '{scheme}://' is not allowed")
    if "://" in raw:
        parsed = urllib.parse.urlparse(raw)
        scheme = (parsed.scheme or "").lower()
        if not scheme:
            raise ValueError(f"not a URL: {raw!r}")
        if scheme not in ("http", "https"):
            raise ValueError(f"scheme '{scheme}://' is not allowed")
        return raw
    return "https://" + raw


# ── per-domain backend memory (Feature C) ────────────────────────────────────
# Remember, per registrable domain, which backend last produced a clean win, so
# repeat visits skip straight to the rung that works instead of re-walking the
# whole ladder from curl_cffi. Stored at <config-dir>/unlocker_cache.json; all
# IO is best-effort and NEVER raises — a corrupt or unwritable cache silently
# degrades to "no memory" rather than breaking a fetch. Each entry carries an
# ISO-8601 UTC timestamp (P3.3); entries older than _MEMORY_TTL_SECONDS (default
# 24h) are expired — ignored on promotion and dropped on load/save. A remembered
# backend that fails (block/thin/exception) before a clean win is unpinned so
# later fetches aren't stuck on a dead rung. A pin lasts the TTL from the walk
# that earned it: winning again on the remembered rung does not extend it, so a
# wrong pin (example.com sent to the browser, F25) heals within a day.

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


_jina_spent = False


def _spend_jina() -> None:
    global _jina_spent
    _jina_spent = True


def reset_jina_spend() -> None:
    """Forget a Jina 403 from an earlier call.

    MCP calls this at the start of each tool call. A long-lived server must
    not lose the relay for every later read because one page returned 403.
    A CLI process does not call this, so one 403 still skips Jina for the
    rest of that process, including a later page of the same read.
    """
    global _jina_spent
    _jina_spent = False


def jina_enabled() -> bool:
    """Whether the Jina Reader relay is allowed (P3.5 / Q4).

    Default is **on**. ``SEARCHTS_NO_JINA=1`` (or true/yes) disables the
    third-party relay so URLs never leave the machine via r.jina.ai.
    Config key ``jina: false`` (YAML under ``~/.searchts``) also disables when
    the env is unset. When disabled, the Jina rung is stripped from **every**
    ladder walk — including an explicit ``backends=[..., "Jina Reader"]`` list —
    so opt-out is a hard privacy switch, not only a default-order tweak.
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
    *,
    login_wall: bool = False,
) -> Optional[str]:
    """Return a short reason if the response is a hard block/challenge page, else None.

    HTTP errors (including vendor codes like 999), known challenge phrases, and
    explicit challenge headers count as blocked. Login-wall phrases are scored
    only when ``login_wall=True`` (extracted text / Jina markdown) so a real
    page with a sign-in modal in the raw HTML is not rejected. Thin-but-real
    pages are not a block; ``fetch`` escalates, then fails unless ``allow_thin``.
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
    if login_wall and _looks_login_wall(text):
        return "login-wall"
    return None


def _looks_login_wall(text: str) -> bool:
    """True when *text* is an auth shell, not the page the URL named.

    LinkedIn ``/feed/`` (and similar) extract to 500–900 chars of Sign in /
    Join now — above ``_MIN_CHARS``, so thin-gate would miss them. Bare
    "sign in" in a long article or site chrome must not trip this.
    """
    raw = text or ""
    head = raw[:8192].lower()
    if not head:
        return False
    for phrase in _LOGIN_WALL_PHRASES:
        if phrase in head:
            return True
    if len(raw.strip()) >= 1500:
        return False
    t = raw.lower()
    has_auth = "sign in" in t or "log in" in t
    has_signup = (
        "join now" in t
        or "create an account" in t
        or "new to " in t
        or "don't have an account" in t
        or "do not have an account" in t
    )
    return has_auth and has_signup


def html_to_text(html: str, url: Optional[str] = None) -> str:
    """Extract clean main-content markdown from raw HTML (trafilatura, with fallback)."""
    try:
        import trafilatura

        from searchts.more import prepare_panels, tidy_markdown

        html = prepare_panels(html)  # F23a: keep FAQ questions and hidden answers
        out = trafilatura.extract(
            html, url=url, output_format="markdown",
            include_links=True, include_tables=True, favor_recall=True,
        )
        if out and out.strip():
            return tidy_markdown(out).strip()
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


# ── F25: a short page that is the whole page ──────────────────────────────────
#: Below this a short extract is a stub, not a page (example.com keeps 156).
_WHOLE_MIN_CHARS = 60
#: Visible text the extract may leave out and still be the whole page, such as
#: a "Learn more" link or a footer line.
_WHOLE_SLACK = 80
#: Inline script above this many characters is an app, not a short static page.
_WHOLE_INLINE_JS = 5_000
#: Mount nodes that client-side apps fill after load.
_APP_ROOT_IDS = frozenset({"root", "app", "__next", "__nuxt", "___gatsby", "svelte", "main-app"})
#: App state shipped in a script: the content lives there, not in the HTML.
_APP_STATE_MARKERS = (
    "__NEXT_DATA__", "__NUXT__", "__INITIAL_STATE__", "__APOLLO_STATE__",
    "__PRELOADED_STATE__", "__remixContext", "__sveltekit",
)
_NEEDS_JS = re.compile(
    r"\b(?:enable|turn on|requires?|needs?)\s+javascript\b"
    r"|\bjavascript\s+(?:is\s+)?(?:required|disabled|needed|off)\b",
    re.I,
)


def _plain_len(markdown: str) -> int:
    """Visible length of an extract: link targets and Markdown marks do not count."""
    t = re.sub(r"\]\([^)]*\)", "]", markdown or "")
    t = re.sub(r"[\[\]#*_>`|]", "", t)
    return len(re.sub(r"\s+", " ", t).strip())


def whole_short_page(html: str, text: str) -> bool:
    """True when a short extract is everything the page shows as served (F25).

    Thin means "the page has more than the extract". example.com serves one
    paragraph and a link, so its 156-character extract is a read, not a reason
    to start a browser or pin the domain to one. Anything that looks like an
    app stays thin: an empty mount node, a noscript "enable JavaScript" notice,
    app state in a script, a module script or more than two external ones,
    lots of inline script, a frame, or visible text the extract left out.
    """
    if len((text or "").strip()) < _WHOLE_MIN_CHARS or len(re.findall(r"\w+", text)) < 8:
        return False
    if not html or not re.search(r"<(?:html|body)\b", html, re.I):
        return False
    if any(marker in html for marker in _APP_STATE_MARKERS):
        return False
    try:
        import lxml.html

        doc = lxml.html.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", html))
    except Exception:  # noqa: BLE001 - HTML we cannot parse is not one we can vouch for
        return False
    external = inline = 0
    for el in doc.iter():
        tag = el.tag.lower() if isinstance(el.tag, str) else ""
        if tag in ("iframe", "frame", "frameset", "app-root"):
            return False
        if tag == "script":
            if (el.get("type") or "").strip().lower() == "module":
                return False
            if el.get("src"):
                external += 1
            else:
                inline += len(el.text or "")
        elif tag == "noscript":
            if _NEEDS_JS.search(el.text_content() or ""):
                return False
        elif (el.get("id") or "").strip().lower() in _APP_ROOT_IDS:
            if len(re.sub(r"\s+", " ", el.text_content() or "").strip()) < 40:
                return False
    if external > 2 or inline > _WHOLE_INLINE_JS:
        return False
    body = doc.find(".//body")
    root = body if body is not None else doc
    for el in root.xpath(".//script|.//style|.//noscript|.//template|.//svg"):
        el.drop_tree()
    visible = len(re.sub(r"\s+", " ", root.text_content() or "").strip())
    return visible <= _plain_len(text) + _WHOLE_SLACK


# ── backend fetchers: each returns (status, body, final_url, headers) or raises ──

def _normalize_headers(headers: Mapping[str, object]) -> Dict[str, str]:
    """Return string response headers with case-insensitive names normalized."""
    return {str(name).lower(): str(value) for name, value in headers.items()}


def _fetch_curl_cffi(url: str, timeout: int = 30) -> Tuple[int, str, str, Dict[str, str]]:
    from curl_cffi import requests as cr

    from searchts.ssrf import curl_resolve_options, curl_safe_redirects
    r = cr.get(url, impersonate="chrome", timeout=timeout,
               allow_redirects=curl_safe_redirects(),
               curl_options=curl_resolve_options(url),
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


_NAV_RACE = "the page is navigating"
_NAV_CONTENT_RETRIES = 4
_NAV_CONTENT_WAIT_MS = 400
_SETTLE_LOAD_MS = 8000
_SETTLE_NETWORKIDLE_MS = 3000

#: Persistent browser profile directory (searchts-owned). Same dir for
#: stealth and --human. Opt out via SEARCHTS_NO_BROWSER_PROFILE=1.
_BROWSER_PROFILE_DIR = Path.home() / ".searchts" / "browser-profile"


def _profile_path() -> Path:
    """Resolve the persistent browser profile path.

    Returns ``_BROWSER_PROFILE_DIR`` when the profile feature is enabled
    (default), or a throwaway temporary dir when ``SEARCHTS_NO_BROWSER_PROFILE=1``
    opts out. Creates the directory if missing.
    """
    if os.environ.get("SEARCHTS_NO_BROWSER_PROFILE", "") in ("1", "true", "yes"):
        import tempfile
        return Path(tempfile.mkdtemp(prefix="searchts-browser-"))
    _BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return _BROWSER_PROFILE_DIR


def _use_persistent_profile() -> bool:
    """True when the persistent profile feature is enabled (default)."""
    return os.environ.get("SEARCHTS_NO_BROWSER_PROFILE", "") not in ("1", "true", "yes")


def _is_nav_race(exc: BaseException) -> bool:
    return _NAV_RACE in str(exc).lower()


def _stderr_tick(msg: str, progress: bool) -> None:
    if not progress:
        return
    try:
        print(msg, file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass


def _progress_wanted(progress: Optional[bool] = None) -> bool:
    if progress is None:
        return os.environ.get("SEARCHTS_PROGRESS", "") in (
            "1", "true", "True", "yes",
        )
    return bool(progress)


def _wait_settled_load(
    page, timeout_ms: int = _SETTLE_LOAD_MS, progress: bool = False
) -> None:
    """Wait for a settled load before ``page.content()`` (P3.11).

    ``goto(..., wait_until="domcontentloaded")`` can still be mid-redirect.
    Prefer ``load``; try a short ``networkidle`` if ``load`` times out. Idle
    wait is bounded — live sockets never settle, and that is not a hang.
    """
    load_ms = max(1000, int(timeout_ms))
    _stderr_tick("waiting for page to settle…", progress)
    try:
        page.wait_for_load_state("load", timeout=load_ms)
        return
    except Exception:  # noqa: BLE001 - timeout / missing API in tests
        pass
    try:
        page.wait_for_load_state(
            "networkidle", timeout=min(_SETTLE_NETWORKIDLE_MS, load_ms)
        )
    except Exception:  # noqa: BLE001
        pass


def _page_content(
    page,
    retries: int = _NAV_CONTENT_RETRIES,
    wait_ms: int = _NAV_CONTENT_WAIT_MS,
    progress: bool = False,
) -> str:
    """``page.content()`` with retries on Playwright's mid-navigation error.

    After retries, raise — do not return the HTML from a half-navigated
    document (that reads as thin and looks like a win).
    """
    last: Optional[BaseException] = None
    total_wait = max(0, retries - 1) * wait_ms
    if total_wait >= 1000:
        _stderr_tick("waiting for navigation to finish…", progress)
    for i in range(max(1, retries)):
        try:
            return page.content()
        except Exception as e:  # noqa: BLE001
            if not _is_nav_race(e):
                raise
            last = e
            if i >= retries - 1:
                break
            page.wait_for_timeout(wait_ms)
    raise RuntimeError(
        "Page.content: Unable to retrieve content because the page is navigating"
    ) from last


def _await_hydration(
    page,
    html: str,
    budget_ms: int = 8000,
    step_ms: int = 500,
    progress: bool = False,
) -> str:
    """Poll until the rendered HTML stops growing; return the fullest seen.

    A JS app is still an empty shell at ``domcontentloaded``, so reading
    ``page.content()`` immediately yields pre-hydration markup and the caller
    judges a live page to be thin. Polling for content-length stability beats
    waiting for ``networkidle``, which never settles on pages holding a live
    connection (streaming, websockets, analytics beacons).

    Stops as soon as two consecutive reads agree, so an already-rendered page
    costs one extra step rather than the whole budget. A persistent
    navigation race fails loud instead of returning the last partial HTML.
    """
    waited = 0
    while waited < budget_ms:
        page.wait_for_timeout(step_ms)
        waited += step_ms
        try:
            current = _page_content(page, progress=progress)
        except Exception as e:  # noqa: BLE001
            if _is_nav_race(e):
                raise
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
    url: str, timeout: int = 60, progress: Optional[bool] = None
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
    return _call_sync_browser(_fetch_stealth_impl, url, timeout, progress)


def _fetch_stealth_impl(
    url: str, timeout: int = 60, progress: Optional[bool] = None
) -> Tuple[Optional[int], str, str, Dict[str, str]]:
    try:
        from patchright.sync_api import sync_playwright
    except ImportError as e:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "stealth-browser backend needs patchright: "
            "searchts install --browser"
        ) from e

    ms = int(timeout * 1000)
    from searchts.ssrf import chromium_pin_args
    pin_args = chromium_pin_args(url)
    with sync_playwright() as p:
        persistent = _use_persistent_profile()
        if persistent:
            profile_dir = _profile_path()
            browser = p.chromium.launch_persistent_context(
                str(profile_dir), headless=True,
                args=pin_args,
                user_agent=_UA_REAL, locale="en-US",
                viewport={"width": 1280, "height": 800},
            )
        else:
            browser = p.chromium.launch(headless=True, args=pin_args)
        try:
            if persistent:
                page = browser.new_page()
            else:
                ctx = browser.new_context(
                    user_agent=_UA_REAL, locale="en-US",
                    viewport={"width": 1280, "height": 800},
                )
                page = ctx.new_page()
            from searchts.ssrf import guard_browser_page
            guard_browser_page(page, url)
            resp = page.goto(url, wait_until="domcontentloaded", timeout=ms)
            init_status = resp.status if resp else None
            headers = _normalize_headers(resp.all_headers()) if resp else {}
            want_tick = _progress_wanted(progress)
            # Redirects after DCL: wait for load before the first content().
            _wait_settled_load(
                page, timeout_ms=min(_SETTLE_LOAD_MS, ms), progress=want_tick
            )
            html = _page_content(page, progress=want_tick)
            # Let a JS app hydrate before judging the page; otherwise an SPA
            # comes back as a near-empty shell and reads as "thin".
            html = _await_hydration(page, html, progress=want_tick)
            # Wait (bounded) for a managed JS challenge to auto-resolve.
            waited = 0
            while waited < 15000 and looks_blocked(200, html) == "challenge":
                page.wait_for_timeout(1500)
                waited += 1500
                html = _page_content(page, progress=want_tick)
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
            "searchts install --browser"
        ) from e

    print(
        f"A browser opened - solve the challenge/CAPTCHA; waiting up to {timeout} s...",
        file=sys.stderr,
        flush=True,
    )

    deadline_ms = int(timeout * 1000)
    from searchts.ssrf import chromium_pin_args
    pin_args = chromium_pin_args(url)
    with sync_playwright() as p:
        persistent = _use_persistent_profile()
        if persistent:
            profile_dir = _profile_path()
            browser = p.chromium.launch_persistent_context(
                str(profile_dir), headless=False,
                args=pin_args,
                user_agent=_UA_REAL, locale="en-US",
                viewport={"width": 1280, "height": 800},
            )
        else:
            browser = p.chromium.launch(headless=False, args=pin_args)
        try:
            if persistent:
                page = browser.new_page()
            else:
                ctx = browser.new_context(
                    user_agent=_UA_REAL, locale="en-US",
                    viewport={"width": 1280, "height": 800},
                )
                page = ctx.new_page()
            from searchts.ssrf import guard_browser_page
            guard_browser_page(page, url)
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

def _finalize(
    result: FetchResult, scrub: bool, tick: Optional[Callable[[str], None]] = None
) -> FetchResult:
    """Sanitize a winning FetchResult before returning it.

    ALWAYS strips invisible/control chars and scans for prompt-injection
    indicators, attaching any findings to ``result.warnings``. When ``scrub`` is
    True the matched injection spans in the text are redacted too. Untrusted web
    content must never reach a model with hidden instructions intact.

    F23a: when the page HTML came along, notes what the page has beyond this
    read (next page, feed, folds, a list the extract mostly dropped, stated
    counts) as trailing lines and in ``next_url`` / ``more``. The HTML is
    dropped here and never returned.
    """
    from searchts import more, sanitize

    if result.page_html:
        # F23f: a list page whose extract lost the items' titles, links or dates
        # is rebuilt from the HTML before the notes are worked out.
        rebuilt = more.list_index(result.page_html, result.final_url or "", result.text)
        if rebuilt:
            result.text = rebuilt[0]
        found = more.detect(result.page_html, result.final_url or "", result.text)
        if rebuilt:
            found.insert(0, rebuilt[1])
        if found:
            result.text = more.annotate(result.text, found)
            result.more = [m.as_dict() for m in found]
            result.next_url = next((m.url for m in found if m.kind == "next-page"), None)
            if tick is not None:
                tick(f"  {more.summary(found)}")
        result.page_html = None
    out = sanitize.scrub(result.text, redact=scrub)
    result.text = out.text
    if not result.fetched_at:
        result.fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result.warnings = out.findings
    return result


def fetch(url: str, backends: Optional[List[str]] = None,
          min_chars: int = _MIN_CHARS, use_memory: bool = True,
          allow_human: bool = False, scrub: bool = False,
          allow_thin: bool = False, progress: Optional[bool] = None) -> FetchResult:
    """Fetch `url` as agent-readable text, escalating through `backends`.

    Returns the first FetchResult that yields real content; raises UnlockerError
    with a per-backend breakdown if every rung fails.

    use_memory:
        When True (and SEARCHTS_NO_MEMORY is unset), a backend previously
        recorded as the winner for this URL's registrable domain is moved to the
        FRONT of the ladder, and a clean win on any other rung is persisted for
        next time. A win on the remembered rung does not extend its TTL.
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
        True: stderr ticks per ladder rung. False: never (CLI ``--json``).
        None: follow ``SEARCHTS_PROGRESS=1``. MCP/library omit the arg.
    """
    if progress is None:
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

    try:
        url = normalize(url)
    except ValueError as e:
        raise UnlockerError(url, [("normalize", str(e))]) from e

    from searchts.known_hosts import reddit as _reddit_listing
    from searchts.ssrf import guard_mcp_url, private_hop
    blocked = guard_mcp_url(url, resolve_dns=True)
    if blocked:
        why = blocked[7:] if blocked.startswith("Error: ") else blocked
        raise UnlockerError(url, [("ssrf", why)])

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

    # Tier-0.5: known-host public-API endpoints (e.g. Reddit .json).
    # A fail-open ring — on miss/exception the normal ladder runs unchanged.
    # No domain-memory pinning for reddit.com (volatile per request).
    try:
        from searchts import known_hosts as _known_hosts
        if _known_hosts.matches(url):
            kh_name = _known_hosts.matching_name(url) or "known-host"
            _tick(f"trying known-host:{kh_name}…")
            kh = _known_hosts.extract(url)
            if kh is not None and kh.markdown:
                _tick(
                    f"  known-host:{kh.provider}: ok ({len(kh.markdown)} chars)"
                )
                return _finalize(
                    FetchResult(
                        f"known-host:{kh.provider}",
                        kh.markdown,
                        200,
                        final_url=url,
                    ),
                    scrub,
                )
            _tick(f"  known-host:{kh_name}: miss")
    except Exception:  # noqa: BLE001 - ring must never break the ladder
        pass

    order = list(backends if backends is not None else DEFAULT_BACKENDS)
    if not jina_enabled() or _jina_spent:
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
            elif backend == "Jina Reader":
                status, body, final_url, headers = _fetch_jina(url)
            elif backend == "stealth-browser":
                status, body, final_url, headers = _fetch_stealth(
                    url, progress=progress
                )
            else:
                attempts.append((backend, "unknown-backend"))
                _tick(f"  {backend}: unknown-backend")
                if backend == remembered:
                    unpin(domain)
                    remembered = None
                continue

            hop = private_hop(url, final_url)
            if hop:
                attempts.append((backend, hop))
                _tick(f"  {backend}: {hop}")
                if backend == remembered:
                    unpin(domain)
                    remembered = None
                continue

            if backend == "Jina Reader":
                reason = looks_blocked(status, body, headers)
                if status == 403:
                    _spend_jina()
                if reason:
                    attempts.append((backend, reason))
                    _tick(f"  {backend}: {reason}")
                    if backend == remembered:
                        unpin(domain)
                        remembered = None
                    continue
                text = body  # Jina already returns markdown
            else:
                reason = looks_blocked(status, body, headers)
                if reason:
                    attempts.append((backend, reason))
                    _tick(f"  {backend}: {reason}")
                    if backend == remembered:
                        unpin(domain)
                        remembered = None
                    continue
                # F5c: Reddit listing or thread HTML before Trafilatura.
                reddit_hit = _reddit_listing.extract_from_html(url, body)
                if reddit_hit:
                    label, listing_md = reddit_hit
                    _tick(label)
                    return _finalize(
                        FetchResult(
                            backend,
                            listing_md,
                            status,
                            final_url=final_url or url,
                            headers=headers,
                        ),
                        scrub,
                    )
                text = html_to_text(body, url)

            text = text or ""
            # Login-wall on the extract only (raw HTML often has a sign-in modal).
            extract_reason = looks_blocked(200, text, login_wall=True)
            if extract_reason:
                attempts.append((backend, extract_reason))
                _tick(f"  {backend}: {extract_reason}")
                if backend == remembered:
                    unpin(domain)
                    remembered = None
                continue

            # F25: a short page that is the whole page, as curl got it, is a
            # read. Starting a browser for it was slow, failed without the
            # browser extra, and pinned the domain to the browser.
            whole = (
                len(text) < min_chars
                and backend == "curl_cffi"
                and status is not None and 200 <= status < 300
                and whole_short_page(body, text)
            )
            if len(text) >= min_chars or whole:
                if memory_on and domain and backend != remembered:
                    # A win on the remembered rung does not extend its pin, so a
                    # pin earned by mistake heals once _MEMORY_TTL_SECONDS pass.
                    remember(domain, backend)
                _tick(f"  {backend}: ok ({len(text)} chars{', whole page' if whole else ''})")
                # clean win, stop here — sanitize untrusted content before return
                return _finalize(
                    FetchResult(
                        backend,
                        text,
                        status,
                        final_url=final_url or url,
                        headers=headers,
                        page_html=None if backend == "Jina Reader" else body,
                    ),
                    scrub,
                    tick=_tick,
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
                    page_html=None if backend == "Jina Reader" else body,
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
        human_error = ""
        try:
            status, html, final_url = _fetch_human(url)
        except Exception as e:  # noqa: BLE001 - patchright missing/launch failure
            status, html, final_url = None, "", url
            human_error = f"{type(e).__name__}: {e}"
        blocked_reason = looks_blocked(status, html)
        if blocked_reason is not None:
            # Fail loud: the rung the user asked for must show up in the error.
            why = human_error or blocked_reason
            attempts.append(("human-browser", why))
            _tick(f"  human-browser: {why}")
        else:
            hop = private_hop(url, final_url or url)
            listing_hit = False
            if hop:
                attempts.append(("human-browser", hop))
                _tick(f"  human-browser: {hop}")
                text = ""
            else:
                # F5c: listing or thread HTML (human rung). Wins even if short,
                # and even when an earlier rung left a longer thin `best`.
                try:
                    reddit_hit = _reddit_listing.extract_from_html(url, html)
                    if reddit_hit:
                        label, listing_md = reddit_hit
                        _tick(label)
                        text = listing_md
                        listing_hit = True
                    else:
                        text = html_to_text(html, url)
                except Exception as e:  # noqa: BLE001 - fail loud, not a traceback
                    text = ""
                    human_error = human_error or f"extract failed ({type(e).__name__}: {e})"
            wall = looks_blocked(200, text, login_wall=True) if text else None
            if (
                text
                and wall is None
                and (
                    listing_hit
                    or best is None
                    or len(text) > len(best.text)
                )
            ):
                human = FetchResult(
                    backend="human-browser", text=text, status=status,
                    final_url=final_url or url,
                    page_html=None if listing_hit else html,
                )
                if listing_hit or len(text) >= min_chars:
                    return _finalize(human, scrub, tick=_tick)
                best = human
                attempts.append(("human-browser", f"thin-{len(text)}b"))
                _tick(f"  human-browser: thin-{len(text)}b")
            elif not hop:
                if human_error:
                    why = human_error
                elif not text:
                    why = "empty-extract"
                elif wall is not None:
                    why = wall
                else:
                    why = f"thin-{len(text)}b"
                attempts.append(("human-browser", why))
                _tick(f"  human-browser: {why}")

    if allow_thin and best is not None:
        return _finalize(best, scrub, tick=_tick)

    raise UnlockerError(url, attempts)


_MAX_PAGES = 5


def read_pages(url: str, pages: int = 1, **kwargs) -> List[FetchResult]:
    """Read this page and follow its next page, curl only, up to ``pages``.

    Stops on a loop, a missing next link, or the cap. The first page uses the
    caller's backends. Later pages are curl only: a browser on every next page
    is not this change. The cap is said out loud: a walk that hits it with a
    live next link would otherwise look like the list ended.
    """
    wanted = max(1, int(pages or 1))
    pages = min(wanted, _MAX_PAGES)
    seen = set()
    out: List[FetchResult] = []
    current = url
    for i in range(pages):
        key = current.split("#", 1)[0].rstrip("/")
        if key in seen:
            break
        seen.add(key)
        call = dict(kwargs)
        if i:
            call["backends"] = ["curl_cffi"]
            call["allow_human"] = False
        try:
            result = fetch(current, **call)
        except UnlockerError as e:
            # Page one is the URL the caller asked for: nothing to return, so
            # the error stands. A later hop failing means the caller already
            # has real content, and throwing it away to report a URL they never
            # asked for is a bad trade. Keep the pages, say why the walk ended.
            if i == 0 or _is_refusal(e):
                raise
            _note_walk_stopped(out[-1], current, e)
            break
        out.append(result)
        nxt = result.next_url
        if not nxt:
            break
        # No pre-check on nxt. fetch guards every URL it is handed, so it
        # raises UnlockerError with the guard's own reason on the next hop.
        # Guarding here and breaking quietly turned a refused address into a
        # short read with exit 0, which is the opposite of fail loud.
        current = nxt
    else:
        # The loop ran out with pages still coming. Without this the caller
        # cannot tell a finished list from one cut off at the cap.
        if out and out[-1].next_url:
            _note_walk_capped(out[-1], len(out), wanted, out[-1].next_url)
    return out


def _note_walk_capped(
    last: "FetchResult", got_pages: int, asked: int, nxt: str, rows: str = ""
) -> None:
    """Say the walk stopped at a cap, not because the list ended."""
    got = f"asked for {asked}, got {got_pages}" if asked > got_pages else f"stopped at the {got_pages}-page cap"
    got = f"{rows}, {got}" if rows else got
    last.text = (last.text or "").rstrip() + f"\n\n[pages: {got}. The next page is {nxt}]"


_MAX_ITEMS = 300
# Both markdown list shapes the extractor emits: unordered "- [" and ordered
# "1. [". Matching only the unordered form counted every ordered list as zero
# rows, so --items walked the whole page cap and reported nothing.
_ITEM_LINE = re.compile(r"(?m)^(?:-|\d+\.)\s+\[")


def _is_refusal(err: UnlockerError) -> bool:
    """True when the error is the SSRF guard refusing, not a page that failed.

    A refused address is a security event and must reach the caller as an
    error even mid-walk. A challenge on page 3 is just a page that failed.
    """
    return any(str(backend).strip() == "ssrf" for backend, _ in (err.attempts or []))


def _note_walk_stopped(last: "FetchResult", url: str, err: UnlockerError) -> None:
    """Say on the last page that the walk stopped there and why.

    The URL is scrubbed on the way in. It comes from the page's own markup, so
    a query string can carry an injection payload into a note that lands after
    _finalize ran, which is exactly where the text is no longer scanned.
    """
    from searchts import sanitize

    reasons = "; ".join(f"{backend}: {why}" for backend, why in (err.attempts or []))
    note = sanitize.scrub(f"[read: stopped before {url}. {reasons}]", redact=True)
    last.warnings = list(last.warnings or []) + note.findings
    last.text = (last.text or "").rstrip() + f"\n\n{note.text}"


def _browser_installed() -> bool:
    try:
        import patchright  # noqa: F401
        return True
    except Exception:  # noqa: BLE001 - a missing extra is the normal case
        return False


def item_count(text: str) -> int:
    """Index rows already rendered as markdown links."""
    return len(_ITEM_LINE.findall(text or ""))


def read_items(url: str, items: int = _MAX_ITEMS, **kwargs) -> List[FetchResult]:
    """Follow next-page links until ``items`` list rows, curl only after the first.

    The ceiling is ``SEARCHTS_MAX_ITEMS`` and never above 300. A request over
    the ceiling is clamped and the read says so. A feed with no next link and
    no browser says to install one. Scrolling that feed is not this function.
    """
    try:
        raw_ceiling = int(os.environ.get("SEARCHTS_MAX_ITEMS") or _MAX_ITEMS)
    except ValueError:
        raw_ceiling = _MAX_ITEMS
    ceiling = max(1, min(raw_ceiling, _MAX_ITEMS))
    asked = max(1, int(items or 1))
    want = min(asked, ceiling)
    seen = set()
    out: List[FetchResult] = []
    current = url
    got = 0
    broke = False
    for i in range(_MAX_PAGES):
        key = current.split("#", 1)[0].rstrip("/")
        if key in seen:
            break
        seen.add(key)
        call = dict(kwargs)
        if i:
            call["backends"] = ["curl_cffi"]
            call["allow_human"] = False
        try:
            result = fetch(current, **call)
        except UnlockerError as e:
            if i == 0 or _is_refusal(e):
                raise
            _note_walk_stopped(out[-1], current, e)
            broke = True
            break
        out.append(result)
        got += item_count(result.text)
        nxt = result.next_url
        if got >= want or not nxt:
            break
        # No pre-check on nxt, same as read_pages: fetch guards it and raises.
        current = nxt
    else:
        # Out of pages with more to read. Say so: otherwise asking for 300 rows
        # and getting 150 is indistinguishable from the list ending there.
        if out and got < want and out[-1].next_url and not broke:
            _note_walk_capped(
                out[-1], len(out), asked, out[-1].next_url,
                rows=f"{got} rows of {asked}" if got else "no rows",
            )
    if not out:
        return out
    extra = ""
    if asked > ceiling:
        extra += f"\n\n[items: asked for {asked}, the ceiling is {ceiling}]"
    last = out[-1]
    # The walk stopped because a page failed, and _note_walk_stopped already
    # wrote that on the last page. Say nothing more about running out.
    if not broke and got < want and not last.next_url and "[feed:" in (out[0].text or "") and not _browser_installed():
        extra += "\n\n[items: more of this list loads in the browser. Run: searchts install --browser]"
    if extra:
        last.text = (last.text or "").rstrip() + extra
    return out
