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

This runs from the user's own IP at personal volume. It does not bundle the
residential-proxy pools that commercial unlockers charge for. A DataDome
device-check is a script the stealth rung is supposed to finish, including one
simple click. A puzzle that asks a person to recognize images still needs a
human. A block that is only the address is a separate layer, not this ceiling.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import re
import stat
import sys
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Mapping, Optional, Tuple, TypeVar

if TYPE_CHECKING:
    from searchts.session_cookies import CookieRecord

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
    "/_fs-ch-",                                  # F5/Shape client challenge (its asset path; PyPI and others)
    "enable javascript to proceed",              # the same F5/Shape shell, as a relay renders it (no asset path left)
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
    # Reddit's current interstitial, measured 2026-10-17: the direct (non-browser)
    # request for a next-batch cursor was answered HTTP 200 with this title and
    # a reCAPTCHA mount, 0 post cards, and it read as an *empty feed*. Reddit
    # shows it or not from the browser's persistent profile, so the same URL
    # returned 24 posts to the browser rung in the same minute.
    #
    # Matched as the interstitial's whole title element, not as a bare phrase:
    # "prove your humanity" is what people *write about* on Reddit, and this list
    # is checked against the first 8 KB of a page, so a thread whose title or
    # opening comments quote the words was refused as a captcha (F5f). A thread
    # page's own title ends in " : r/<sub>", so the closing tag is what tells
    # the interstitial from a post *about* it. Measured at offset 163 of 167,165
    # in the raw page, far inside the 8 KB window this list searches.
    "reddit - prove your humanity</title>",
    "let us know you're a real person",
    "let us know you are a real person",
    "we're committed to safety",  # Reddit interstitial lead-in (short extract)
    "we are committed to safety",
    # Reddit login walls (old.reddit / .com) — long enough to beat thin gate
    "accounts are required to access old reddit",
    "to keep reddit safe",
    "log in, or continue without an account",
    # Google served its bot-check on HTTP 200 and it read as content: 964
    # characters beginning "Our systems have detected unusual traffic from
    # your computer network", returned to the agent as the search results.
    # Search engines are the first thing an agent is asked to read, so a
    # silent block here is worse than a hard failure anywhere else.
    "detected unusual traffic from your computer network",
    "this page appears when google automatically detects requests",
    "solving the above captcha will let you continue",
    # DuckDuckGo and other engines answering a challenge on 200.
    "please solve the below captcha to continue",
    "unusual traffic from your computer network",
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

#: Auth vocabulary, for the density check below. A login page is made of these;
#: an article that happens to carry a "Sign in" link in its header carries two.
_AUTH_WORDS = re.compile(
    r"(?i)\b(sign in|sign-in|log in|log-in|login|log into|password|username|"
    r"email address|forgot password|create (?:a )?(?:new )?account|sign up|"
    r"join now|continue with|remember me)\b"
)

#: Auth words per 100 words above which the extract IS the auth form. Measured
#: across the dogfood corpus: instagram 5.79, and every page that reads
#: correctly sits at 0.40 or below (pypi 0.37, amazon 0.40, guardian 0.21,
#: wikipedia 0.00). The 15x gap is why a threshold in the middle is safe.
#:
#: The phrase list above missed Instagram entirely: its login page says "Log
#: into Instagram", "Forgot password?" and "Create new account", none of which
#: are in that list, so a login form was returned as a successful read.
_AUTH_DENSITY_PER_100 = 2.0

#: Below this many words the density ratio is not trustworthy: one "Sign in"
#: in an eleven-word line is 9 per 100 and is not a login form. An auth page
#: always has more to it than that, and this floor is what keeps
#: "Welcome. Sign in from the menu if you have an account." reading normally.
_AUTH_DENSITY_MIN_WORDS = 60

#: Cookie-consent vocabulary, same shape of check and same reasoning. A consent
#: wall is the page *about* cookies, so the words are most of the text. Measured:
#: app.slack.com/client 11.68 per 100 and everything that reads correctly at
#: 0.23 or below (notion 0.23, nature 0.13, pypi 0.08, guardian 0.05).
#: That page returned its banner as the content of a 1026-character read, which
#: is the same class of lie as the login wall and the Google bot-check.
_COOKIE_WORDS = re.compile(
    r"(?i)\b(cookies?|consent|accept all|reject all|privacy settings|"
    r"manage preferences|always active|gdpr|cookie policy|"
    r"accept additional|allow all|your privacy,? your choice)\b"
)
_COOKIE_DENSITY_PER_100 = 2.0
_COOKIE_DENSITY_MIN_WORDS = 60

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
    #: True when this read carried session cookies to the target host. Reported,
    #: never a value: the point is that an agent can tell a logged-in read from
    #: an anonymous one, which it otherwise cannot. A read that sent cookies and
    #: still landed on a login wall sets this False, because the answer it got
    #: is the anonymous answer.
    authenticated: bool = False
    #: Page HTML kept only until ``_finalize`` runs detection; never returned.
    page_html: Optional[str] = field(default=None, repr=False, compare=False)
    #: F23c/F23d: trailing lines the pass itself earned (scroll stop reason,
    #: what ``--expand`` opened, a named paywall). Appended inside ``_finalize``,
    #: so they are sanitized with the rest of the text rather than after it.
    extra_notes: List[str] = field(default_factory=list, repr=False, compare=False)
    #: One identity per index row this read added, when the producer can name
    #: them (a known-host feed knows the post id on every card). ``--items``
    #: dedupes on these because a site's own cursor can hand back a row the
    #: previous window already had, and counting it twice would be a lie about
    #: how many rows were read. None means "count the markdown rows", which is
    #: what every other read does.
    index_keys: Optional[List[str]] = field(default=None, repr=False, compare=False)


@dataclass
class UnlockerError(Exception):
    url: str
    attempts: List[Tuple[str, str]] = field(default_factory=list)
    #: One extra sentence that changes what the caller should do next, appended
    #: to the message. Set when the ladder's reasons are all true but none of
    #: them says the useful thing: a read that carried cookies and still got a
    #: login page has one cause and one next step, and three copies of
    #: "login-wall" do not say either.
    hint: str = ""

    def __str__(self) -> str:
        rungs = "; ".join(f"{b}: {why}" for b, why in self.attempts)
        base = f"all backends failed for {self.url} -> {rungs}"
        return f"{base} ({self.hint})" if self.hint else base


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


#: Path segments that mean "this URL IS the login page", whatever the site calls
#: the page. Matched as whole segments, so an article at ``/login-tips`` or
#: ``/signin-guide`` is untouched and only the exact segment counts.
#:
#: Every entry here names the act of authenticating and appears in no other
#: page's URL.
#:
#: ACCEPTED MISS, stated here because it is load-bearing: a site that puts its
#: login at a bare ``/auth`` or ``/session`` is NOT recognised. Those two words
#: were in this set and were removed for the opposite reason -- they are
#: ordinary nouns on the rest of the web, and this check fires on the EXTRACT
#: alone, where it is the only signal. With them in, ``/docs/auth``,
#: ``/blog/auth/2024``, ``/session/2024/notes`` and ``/podcast/session/12`` were
#: all refused as login walls, which is a wrong answer rather than a safe one:
#: the caller asked for an article and was told to log in.
#:
#: The trade is deliberate and it fails open in the worse direction, so here is
#: what a missed wall actually costs, so nobody has to guess: a site at a bare
#: ``/auth`` falls back to the text classifiers in :mod:`searchts.walls`. Those
#: are the defence for a long enough shell (the Instagram case) and the known
#: miss for a short one (reddit's 36 words), which is exactly the case that made
#: this rule necessary. If such a site is ever hit, the fix is to widen
#: ``walls.py`` for it, not to put an ordinary noun back here.
_LOGIN_SEGMENTS = frozenset({
    "login", "login.php", "signin", "signin.php", "sign-in", "log-in",
    "logout", "signout", "sign-out",
})


def is_login_url(url: Optional[str]) -> bool:
    """True when `url` addresses a login page rather than the page asked for.

    The text classifiers need words and a denominator, so a short auth shell
    slips between them: reddit's `/settings/account/` redirects to
    ``/login/?dest=...`` and extracts to 36 words naming two of the three
    things a login shell names, which is under the breadth bar. The redirect
    target is the stronger fact and it needs no vocabulary: a page whose own
    canonical URL is ``/login`` is a login page on every site, in every
    language, whether or not anyone has written its copy down here.
    """
    if not url:
        return False
    try:
        path = urllib.parse.urlparse(url).path
    except ValueError:
        return False
    path = path.lower().strip("/")
    if not path:
        return False
    segments = [s for s in path.split("/") if s]
    if not segments:
        return False
    # Any segment that is exactly a login word. `path in _LOGIN_SEGMENTS` would
    # miss Reddit, which redirects to /login/ with a trailing slash and is
    # caught here by the same rule as /login.
    return any(seg in _LOGIN_SEGMENTS for seg in segments)


def looks_blocked(
    status: Optional[int],
    text: str,
    headers: Optional[Mapping[str, str]] = None,
    *,
    login_wall: bool = False,
    final_url: Optional[str] = None,
) -> Optional[str]:
    """Return a short reason if the response is a hard block/challenge page, else None.

    HTTP errors (including vendor codes like 999), known challenge phrases, and
    explicit challenge headers count as blocked. Login-wall phrases are scored
    only when ``login_wall=True`` (extracted text / Jina markdown) so a real
    page with a sign-in modal in the raw HTML is not rejected. ``final_url``
    adds the redirect fact: a read that landed on ``/login`` is a login wall
    whatever its text happens to score. Thin-but-real pages are not a block;
    ``fetch`` escalates, then fails unless ``allow_thin``.
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
        if str(headers.get("x-akamai-session-info") or "").find("challenge") >= 0:
            return "challenge"
    head = (text or "")[:8192].lower()
    for phrase in _BLOCK_PHRASES:
        if phrase in head:
            return "challenge"
    if login_wall and (_looks_login_wall(text) or is_login_url(final_url)):
        return "login-wall"
    if _looks_cookie_wall(text):
        return "cookie-wall"
    return None


def _looks_login_wall(text: str) -> bool:
    """True when *text* is an auth shell, not the page the URL named.

    Delegates to :mod:`searchts.walls`. This used to consult a phrase list,
    and that list was LinkedIn's own copy, so it caught LinkedIn and almost
    nothing else: Instagram's login form says "Log into Instagram", "Forgot
    password?" and "Create new account", none of which were in it, and was
    returned as a successful 913-character read.

    LinkedIn ``/feed/`` (and similar) extract to 500–900 chars of Sign in /
    Join now — above ``_MIN_CHARS``, so thin-gate would miss them. Bare
    "sign in" in a long article or site chrome must not trip this, which is
    what the density ratio in the classifier is for.
    """
    return _wall_is(text, "auth")


def _looks_cookie_wall(text: str) -> bool:
    """True when the extract IS the consent dialog, not the page behind it."""
    return _wall_is(text, "consent")


def _wall_is(text: str, kind: str) -> bool:
    """Is this extract a wall of ``kind``? See :mod:`searchts.walls`."""
    from searchts import walls

    found = walls.classify(text)
    return found is not None and found.kind == kind


#: A page whose words the extraction recovered fewer than this share of are not
#: trustworthy, and the crude strip is used instead. trafilatura's precision
#: heuristic looks for an article: on a page whose content *is* a link list
#: (a news front page, a docs index, a package registry) it discards the
#: entries and keeps the navigation, then returns that as a success because it
#: is non-empty. Measured against the crude strip as ground truth:
#: theguardian.com/uk 2%, bbc.com/news 4%, postgresql docs index 13%.
#: Wikipedia, Hacker News and lite.cnn score high and keep the good extract.
_EXTRACT_MIN_RECALL = 0.35

#: Below this many words in the crude strip there is nothing to compare, so the
#: extract is taken as-is. Prevents a short article from being judged on noise.
_RECALL_MIN_WORDS = 40

#: A one-line extract next to a crude strip this many lines long has lost its
#: block structure rather than found a short page. Measured across 16 pages,
#: only bbc.com/news does this: 1 kept line against 279 crude.
_MIN_CRUDE_LINES = 20

#: How many rungs may return the same 4xx refusal before the ladder stops
#: escalating. Two, not one: the first refusal is a fact about this request, the
#: second is a fact about the site, and the browser is the rung most likely to
#: differ. A third identical answer is the server telling us plainly.
_REFUSAL_REPEAT_LIMIT = 2

_WORD_RE = re.compile(r"[a-z][a-z'-]{2,}")


def _line_count(text: str) -> int:
    """Non-blank lines. Structure, as opposed to length."""
    return sum(1 for line in (text or "").splitlines() if line.strip())


def _word_recall(kept: str, whole: str) -> float:
    """Share of ``whole``'s distinct words that survive into ``kept``."""
    a = set(_WORD_RE.findall(whole.lower()))
    if not a:
        return 1.0
    b = set(_WORD_RE.findall(kept.lower()))
    return len(a & b) / len(a)


# ── S1.1: resource caps ────────────────────────────────────────────────────────
#: Largest HTML body any rung will parse. 20 MB is far above a real article and
#: far below the 140 MB one page in the security research served, which is a
#: perfectly marked, perfectly fenced untrusted string that still cost the caller
#: gigabytes. The fence was never the resource limit.
MAX_HTML_BYTES = 20 * 1024 * 1024

#: Largest extract returned. Sized for prose, not for a page: a 400,000-character
#: book page is already beyond what an agent will read, and every consumer here
#: (MCP response, search index, transcript) pays for it more than once.
MAX_TEXT_CHARS = 400_000
#: F24b: how much bigger the page's own data has to be than the extract to
#: replace it. One word in ten, so a formatted article that says the same
#: thing keeps its Markdown.
_STRUCTURED_MARGIN = 1.1
#: Below this the data is a caption or a teaser, so it sits under the extract
#: only when there is a paragraph's worth of it.
_SUPPLEMENT_MIN_CHARS = 600

#: Wall-clock budget for the extraction parse itself. This is the CPU class the
#: other two caps do not cover: a small, pathological document can burn arbitrary
#: CPU in a regex backtrack. Enforced in a worker thread so a hang cannot take the
#: caller with it.
EXTRACTION_TIMEOUT = 20.0


class _ExtractionTimeout(Exception):
    """The parse outran its budget. The crude strip is the answer."""


def _extract_within(html: str, url: Optional[str], budget: float) -> Optional[str]:
    """Run ``_extract_inner`` under a wall-clock budget, or return None.

    Threads rather than signals: signals only interrupt the main thread, and
    extraction also runs inside MCP worker threads where SIGALRM is not available
    or not safe. A daemon thread that is still running when the budget expires is
    abandoned rather than joined, because joining it would be the hang we are
    trying to avoid.
    """
    box: Dict[str, object] = {}

    def run() -> None:
        try:
            box["out"] = _extract_inner(html, url)
        except BaseException as e:  # noqa: BLE001 - reported through the box
            box["err"] = e

    worker = threading.Thread(target=run, name="searchts-extract", daemon=True)
    worker.start()
    worker.join(budget)
    if worker.is_alive():
        raise _ExtractionTimeout(
            f"extraction exceeded {budget:.0f}s and was abandoned"
        )
    if "err" in box:
        raise box["err"]  # type: ignore[misc]
    return box.get("out")  # type: ignore[return-value]


def _strip_html(html: str) -> str:
    """Crude tag strip, so we never hard-fail on extraction."""
    import html as _html

    t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    t = re.sub(r"(?s)<[^>]+>", "\n", t)
    t = _html.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n\n", t)
    return t.strip()


def _strip_keeping_links(html: str, url: Optional[str] = None) -> str:
    """The crude strip, with each real anchor kept as one markdown link.

    This is only the text we return when the article extract loses. The recall
    gate and the one-line gate still measure :func:`_strip_html`, which drops
    hrefs, so a link in the answer cannot change which path wins.

    The label's whitespace is collapsed. A relative href is joined to the page
    URL, and a ``<base href>`` wins over that page URL. An empty label, a
    ``#`` fragment and ``javascript:`` stay ordinary text. A ``]`` in the label
    or a ``)`` in the URL would break the markdown, so those come out as the
    label and the URL on two plain lines.
    """
    try:
        from urllib.parse import urljoin

        from lxml import html as lhtml
    except Exception:  # noqa: BLE001 - the strip is the fallback, never raise
        return _strip_html(html)
    try:
        doc = lhtml.fromstring(html or "")
    except Exception:  # noqa: BLE001 - broken markup still has to yield text
        return _strip_html(html)
    if not hasattr(doc, "iter"):
        return _strip_html(html)
    for bad in list(doc.iter("script", "style", "noscript")):
        parent = bad.getparent()
        if parent is not None:
            parent.remove(bad)
    base = url or ""
    for el in doc.iter("base"):
        href = (el.get("href") or "").strip()
        if href:
            base = urljoin(base, href) if base else href
            break
    # Innermost first, so a nested anchor is already text when its parent is read.
    for anchor in reversed(list(doc.iter("a"))):
        if anchor.getparent() is None:
            continue
        href = (anchor.get("href") or "").strip()
        label = " ".join((anchor.text_content() or "").split())
        if (
            not label
            or not href
            or href.startswith("#")
            or href.lower().startswith("javascript:")
        ):
            continue
        absolute = urljoin(base, href) if base else href
        if "]" in label or ")" in absolute or "\n" in label or "\n" in absolute:
            replacement = f"{label}\n{absolute}"
        else:
            replacement = f"[{label}]({absolute})"
        tail = anchor.tail
        anchor.clear()
        anchor.text = "\n" + replacement + "\n"
        anchor.tail = tail
    try:
        rendered = lhtml.tostring(doc, encoding="unicode", method="html")
    except Exception:  # noqa: BLE001 - serialization failed, keep the bare strip
        return _strip_html(html)
    return _strip_html(rendered)


def cap_html(body: str) -> str:
    """Drop a body too large to parse.

    Truncation is not silent: a cut body loses its tail, so it says so, and the
    marker is placed where a reader will see it rather than at the end of a
    string nobody reads.
    """
    if len(body) <= MAX_HTML_BYTES:
        return body
    head = body[:MAX_HTML_BYTES]
    return (
        head
        + f"\n\n[searchts: truncated at {MAX_HTML_BYTES:,} bytes of HTML. "
        "The rest of this page was not read.]"
    )


def cap_text(text: str) -> str:
    """Bound the extract, on the way out of every rung including Jina."""
    if len(text) <= MAX_TEXT_CHARS:
        return text
    return (
        text[:MAX_TEXT_CHARS]
        + f"\n\n[searchts: truncated at {MAX_TEXT_CHARS:,} characters. "
        "The rest of this page was not read.]"
    )


#: Content types whose body is already the page's text. A README served as
#: ``text/plain`` is not HTML with tags in it, and the article extractor reads
#: it as one long paragraph and drops the code blocks it cannot parse.
_PLAIN_TEXT_TYPES = frozenset({
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "text/x-rst",
    "text/tab-separated-values",
    "text/csv",
    "text/ascii",
    "text/yaml",
    "text/x-yaml",
    "application/json",
    "application/javascript",
    "application/x-javascript",
    "application/ecmascript",
    "text/javascript",
    "text/ecmascript",
    "application/yaml",
    "application/x-yaml",
    "application/toml",
    "application/x-toml",
    "text/x-python",
    "text/x-c",
    "text/x-c++",
    "text/x-java",
    "text/x-go",
    "text/x-rust",
    "text/x-shellscript",
})

#: Types that look plain by name but carry markup the extractor must read.
_MARKUP_TYPES = frozenset({
    "text/html",
    "application/xhtml+xml",
    "application/xml",
    "text/xml",
    "application/ld+json",
    "application/xhtml",
})


def _is_plain_text_body(body: str, headers: Optional[Mapping[str, str]] = None) -> bool:
    """True when the server sent text that is the page, not markup to extract.

    The Content-Type is the signal, and it is a generic one: no host is named
    and none is needed. A body that claims to be plain text but opens like an
    HTML document is treated as markup anyway, because some servers serve a
    whole page under ``text/plain``.
    """
    ctype = ""
    if headers:
        ctype = (headers.get("content-type") or "").split(";")[0].strip().lower()
    if not ctype:
        return False
    if ctype in _MARKUP_TYPES:
        return False
    if ctype not in _PLAIN_TEXT_TYPES and not ctype.startswith("text/"):
        return False
    head = (body or "")[:512].lstrip().lower()
    if head.startswith("<!doctype html") or head.startswith("<html"):
        return False
    return True


def html_to_text(html: str, url: Optional[str] = None) -> str:
    """Extract clean main-content markdown, under a size and time budget.

    Three caps, each covering a different failure:

    - the body is truncated at :data:`MAX_HTML_BYTES` before anything parses it
    - the parse runs in a worker thread with a wall-clock budget
      (:data:`EXTRACTION_TIMEOUT`), because a small document can burn arbitrary
      CPU in a regex backtrack
    - the result is truncated at :data:`MAX_TEXT_CHARS`, which is the only cap
      that also covers Jina, since it returns markdown rather than HTML

    The extract itself is only trusted when it accounts for most of the page. A
    page that is mostly links loses its content to an article-shaped heuristic
    and comes back as navigation, so on those the crude strip wins: whole beats
    clean when clean is chrome.

    F24b: when that all comes back thinner than the data the same bytes carry,
    the data wins. Same download, no second request: either it is the *richer*
    of the two and replaces the extract, or it holds a paragraph the extract
    never showed and sits under it. A page that ships no data costs one
    substring test, and one that ships data this cannot read costs a failed
    ``json.loads``.
    """
    body = cap_html(html)
    try:
        text = cap_text(
            _extract_within(_without_page_data(body), url, EXTRACTION_TIMEOUT) or ""
        )
    except _ExtractionTimeout:
        text = cap_text(_tidy_crude(_strip_keeping_links(body, url), url))
    except Exception:
        text = cap_text(_tidy_crude(_strip_keeping_links(body, url), url))
    return _prefer_structured(body, text)


def _without_page_data(html: str) -> str:
    """The page with the scripts the page-data reader owns taken out of it."""
    from searchts.more import drop_data_scripts

    return drop_data_scripts(html)


def _prefer_structured(html: str, text: str) -> str:
    """F24b: the page's own data, against an extract that may already say it.

    Two ways in, in that order. The data replaces the extract when it is the
    richer of the two by :data:`_STRUCTURED_MARGIN`, because a shell page that
    carries its article in a script has nothing else to give. Failing that the
    page's own app state is asked what the extract never said, and sits under
    it as a section when that is a paragraph or more, so a page whose markup
    reads well gains the answers the markup hid instead of repeating itself.

    Both sides are compared the same way (:func:`_plain_len`), so "thinner"
    means fewer visible characters rather than fewer bytes of markup.
    """
    from searchts.more import page_data_chunks, page_data_text, page_state_blocks, plain_len

    chunks = page_data_chunks(html)
    if not chunks:
        return text
    whole = page_data_text(html, chunks=chunks)
    data = page_state_blocks(html, text, chunks=chunks)
    jsonld = page_data_text(html, source="JSON-LD", chunks=chunks)
    # JSON-LD is a typed article body and retains the original replacement
    # behavior. App state also contains related cards and SEO descriptions;
    # its total length cannot establish that it is the page's main article.
    # Let app state replace only a shell extract, and otherwise use the
    # deduplicated supplement path below.
    # App state often contains longer related-card descriptions than the
    # visible article. Only let it replace an effectively empty shell; any
    # readable visible copy remains the lead and state can supplement it.
    has_short_sentence = (
        len(re.findall(r"\b[\w'-]+\b", text)) >= 3
        and re.search(r"[.!?](?:\s|$)", text) is not None
    )
    if (
        plain_len(text) < 120
        and not has_short_sentence
        and plain_len(whole) >= _STRUCTURED_MARGIN * plain_len(text)
    ):
        return cap_text(whole)
    if jsonld and plain_len(jsonld) >= _STRUCTURED_MARGIN * plain_len(text):
        text = jsonld
        data = page_state_blocks(html, text, chunks=chunks)
    kept = sum(plain_len(body) for _, body in data)
    if kept >= _SUPPLEMENT_MIN_CHARS:
        return cap_text(
            (text or "").rstrip() + "\n\n" + "\n\n".join(body for _, body in data)
        )
    return text


def _extract_inner(html: str, url: Optional[str]) -> Optional[str]:
    """The extraction itself, unbounded. Run via :func:`_extract_within`."""
    try:
        import trafilatura

        from searchts.more import prepare_panels, tidy_markdown

        html = prepare_panels(html)  # F23a: keep FAQ questions and hidden answers
        out = trafilatura.extract(
            html, url=url, output_format="markdown",
            include_links=True, include_tables=True, favor_recall=True,
        )
        if out and out.strip():
            kept = tidy_markdown(out).strip()
            crude = _strip_html(html)
            # An extract of one line means the block structure was lost, not that
            # the page had one block. bbc.com/news comes back as 7,356 characters
            # of correct headlines run together: "...hospital bed.3 hrs agoUS &
            # CanadaWhat could happen next..." The character gate below would
            # have kept it, because length is what that gate measures and here
            # the extract is longer than a third of the page. Structure is a
            # separate property from size, so it is checked separately.
            if _line_count(kept) <= 1 and _line_count(crude) >= _MIN_CRUDE_LINES:
                return _tidy_crude(_strip_keeping_links(html, url), url)
            # Cheap gate first: an extract that is nearly as long as the page
            # cannot be the one that dropped it.
            if len(kept) >= _EXTRACT_MIN_RECALL * len(crude) or len(
                _WORD_RE.findall(crude)
            ) < _RECALL_MIN_WORDS:
                return kept
            if _word_recall(kept, crude) >= _EXTRACT_MIN_RECALL:
                return kept
            return _tidy_crude(_strip_keeping_links(html, url), url)
    except Exception:
        pass
    return _tidy_crude(_strip_keeping_links(html, url), url)


def extract_text(html: str, url: Optional[str] = None) -> str:
    """Alias kept so callers can be explicit about which entry point they mean.

    :func:`html_to_text` is the historical name and is what tests import.
    """
    return html_to_text(html, url)


def _tidy_crude(text: str, url: Optional[str] | None) -> str:
    """Clean up the crude strip without trafilatura's article heuristic."""
    try:
        from searchts.more import tidy_markdown

        return tidy_markdown(text).strip() or text
    except Exception:  # noqa: BLE001 - the strip is the fallback, never raise
        return text.strip()


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
_SCRIPTISH_RE = re.compile(r"(?is)<(script|style)\b[^>]*>.*?</\1\s*>")
_NEEDS_JS = re.compile(
    r"\b(?:enable|turn on|requires?|needs?)\s+javascript\b"
    r"|\bjavascript\s+(?:is\s+)?(?:required|disabled|needed|off)\b",
    re.I,
)


def _plain_len(markdown: str) -> int:
    """Visible length of an extract: link targets and Markdown marks do not count.

    The definition lives in :mod:`searchts.more`, because F24 compares this
    number against the page's own text and the two sides have to mean the same
    thing.
    """
    from searchts.more import plain_len

    return plain_len(markdown)


#: Below this a page is short enough that its own markup states the app shape.
_APP_SHELL_MAX_CHARS = 60
#: A page this big that still shows this few characters is a client app, not a
#: read an HTTP rung could have completed.
_APP_SHELL_MIN_HTML = 100_000
_APP_SHELL_MAX_VISIBLE = 1_200
#: Inline script this long, on a page that shows almost no text, is the app's
#: own state and bundle rather than an analytics tag a static page also ships.
_APP_SHELL_MIN_INLINE = 50_000
_TAG_RE = re.compile(r"(?s)<[^>]*>")
_INLINE_SCRIPT_RE = re.compile(r"(?is)<script\b(?![^>]*\bsrc=)[^>]*>(.*?)</script\s*>")
#: Visible characters in a rendered DOM below which the page has not painted for
#: a reader yet. Measured 2026-10-18 on a served app shell: 8 characters of
#: visible markup (a ``<title>``) held steady for 2.0s while the module bundle
#: downloaded, then the same document showed 308 the moment the bundle ran.
#: Anything a reader came for is far above this, so the floor only decides how
#: long a client app is given before it is called settled.
_PAINTED_MIN_VISIBLE = 200


def _visible_markup_len(markup: str) -> int:
    """Characters a reader would see in the served markup, tags and scripts off."""
    return len(re.sub(r"\s+", " ", _TAG_RE.sub(" ", markup)).strip())


def _inline_script_chars(html: str) -> int:
    """Characters of inline script, the app's state and bundle in the markup."""
    return sum(len(m.group(1) or "") for m in _INLINE_SCRIPT_RE.finditer(html))


def _app_signal(html: str, visible: str) -> bool:
    """A shape a client app leaves in the markup: state, a mount node, no-JS.

    These are the page's own structures, never a host name: app state in a
    script, a known empty mount node, an "enable JavaScript" notice, or a
    module script.
    """
    if any(marker in html for marker in _APP_STATE_MARKERS):
        return True
    if _NEEDS_JS.search(visible):
        return True
    try:
        import lxml.html

        doc = lxml.html.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", html))
    except Exception:  # noqa: BLE001 - HTML we cannot parse is not one we can call an app
        return False
    for el in doc.iter():
        if not isinstance(el.tag, str):
            continue
        if (el.get("id") or "").strip().lower() in _APP_ROOT_IDS:
            if len(re.sub(r"\s+", " ", el.text_content() or "").strip()) < _APP_SHELL_MAX_CHARS:
                return True
        if el.tag.lower() == "script" and (el.get("type") or "").strip().lower() == "module":
            return True
    return False


def _is_app_shell(html: str, text: str) -> bool:
    """True when the page was drawn by a client app this rung cannot run.

    Two measured shapes. A short page (under :data:`_APP_SHELL_MAX_CHARS` of
    extract) that still carries an app's own structure is one; the tests are the
    page's, not the host's. Bigger than that, the served markup itself gives the
    page away: a real video page measured 1.4 MB of HTML that showed 234
    characters of text, and a social post page 738 KB that showed 1.1 KB, both
    of them all script and a mount node, none of it the content a reader came
    for. A page that big with text that thin is not a truncated article: the
    article would still be in the markup. No HTTP rung can read it, and the one
    request already made is never repeated to decide this.
    """
    if not html:
        return False
    visible = _SCRIPTISH_RE.sub(" ", html)
    if _plain_len(text) < _APP_SHELL_MAX_CHARS and _app_signal(html, visible):
        return True
    return (
        len(html) >= _APP_SHELL_MIN_HTML
        and _visible_markup_len(visible) <= _APP_SHELL_MAX_VISIBLE
        and (
            _app_signal(html, visible)
            or _inline_script_chars(html) >= _APP_SHELL_MIN_INLINE
        )
    )


def _is_unpainted(html: str) -> bool:
    """True when a rendered DOM shows too little text to be the page.

    The rendered document, not the extract: this asks whether the *browser* has
    shown the reader anything, and it is the question the hydration wait needs.
    A shell and a settled page look identical at ``domcontentloaded``, and the
    only difference arrives later, so a caller that stops at "the length did
    not change" reads the shell and calls the page thin.

    The floor is deliberately loose: 200 visible characters is below any real
    article and above the title-only document an app shows before its bundle
    runs. It is a "has anything happened yet" test, not a quality one, so it
    never decides a page is good. Only the extractor does that.
    """
    if not html:
        return True
    return _visible_markup_len(_SCRIPTISH_RE.sub(" ", html)) < _PAINTED_MIN_VISIBLE


def _is_refused_render(html: str, status: Optional[int]) -> bool:
    """A browser navigation that came back refused and rendered nothing.

    The empty ``<html><head></head><body></body></html>`` a server sends beside
    a 403 carries no challenge phrase and no text, so every block test passes
    it and the rung below promotes the status to 200: a refusal becomes a
    thin page. Measured 2026-10-18 driving the stealth rung against
    ``x.com``: ``page.goto`` answered 403, the DOM stayed at 39 bytes of empty
    document for 48s, and the ladder reported ``stealth-browser: thin-0b``.

    Three conditions, all needed. A 4xx that rendered text is a real page (a
    styled error page, a challenge that cleared) and stays a 200. A 2xx that
    rendered nothing is a broken page and is already thin. Only a refusal with
    no rendered text at all is the case that was being laundered.
    """
    if status is None or status < 400:
        return False
    body = re.sub(
        r"(?is)<head\b[^>]*>.*?(?:</head\s*>|(?=<body\b)|\Z)",
        " ",
        html or "",
    )
    return _visible_markup_len(_SCRIPTISH_RE.sub(" ", body)) == 0


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


def _fetch_curl_cffi(url: str, timeout: int = 30,
                     extra_headers: Optional[Mapping[str, str]] = None,
                     proxy: Optional[str] = None
                     ) -> Tuple[int, str, str, Dict[str, str]]:
    """Hit `url` directly, impersonating Chrome.

    The one rung that talks to the target host itself, so it is the only rung
    allowed to carry cookie material (see :func:`fetch`). ``extra_headers`` is
    merged onto the fixed set; None leaves the request byte-identical to a
    cookie-free read. ``proxy`` routes the request through a proxy, which is how
    a read escapes a block decided on our egress address rather than our
    request; curl_cffi is the rung that can honour it.
    """
    from curl_cffi import requests as cr

    from searchts.ssrf import curl_resolve_options, curl_safe_redirects
    req_headers = {"Accept-Language": "en-US,en;q=0.9"}
    req_headers.update(extra_headers or {})
    # Passed only when set, so a proxy-free read calls curl exactly as before.
    proxy_kwargs: Dict[str, object] = {"proxy": proxy} if proxy else {}
    r = cr.get(url, impersonate="chrome", timeout=timeout,
               allow_redirects=curl_safe_redirects(),
               curl_options=curl_resolve_options(url),
               headers=req_headers, **proxy_kwargs)
    final = str(getattr(r, "url", None) or url)
    return r.status_code, r.text, final, _normalize_headers(dict(r.headers.items()))


def _fetch_jina(url: str, timeout: int = 40) -> Tuple[int, str, str, Dict[str, str]]:
    # Jina is a relay: we asked for `url`, so report that as the final source URL
    # (the wire URL is r.jina.ai/... which is not useful for citations).
    #
    # FENCE: this signature takes a URL and nothing else, on purpose. r.jina.ai
    # is a third party, so there is no parameter through which cookie material
    # could reach this rung -- a Cookie header here would hand a live login to
    # someone else's server. Adding one would be the bug, not the feature.
    req = urllib.request.Request(
        "https://r.jina.ai/" + url,
        headers={"User-Agent": _UA_REAL, "Accept": "text/plain"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        headers = _normalize_headers(dict(resp.headers.items()))
        return resp.status, resp.read().decode("utf-8", "replace"), url, headers


_NAV_RACE = "the page is navigating"
#: Also a race: Playwright raises this when the renderer process dies under the
#: page, which is what an HTTP/2 protocol error on goto looks like from here.
_NAV_CRASH = "page has crashed"
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


#: Transport errors that mean "the connection moved under us", which is the
#: situation the retry in `_page_content` exists for. Measured on real pages:
#: `_fetch_stealth('https://www.lululemon.com/')` raises
#: `Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR`, and StackOverflow raises a reset
#: while the interstitial navigates. Neither matched _NAV_RACE, so both escaped
#: as raw Playwright errors instead of being retried and reported as a verdict.
_TRANSPORT_RACES = (
    _NAV_RACE,
    _NAV_CRASH,
    "net::err_http2_protocol_error",
    "net::err_connection_reset",
    "net::err_connection_closed",
    "net::err_empty_response",
    "net::err_stream_error",
)


def _is_nav_race(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(token in msg for token in _TRANSPORT_RACES)


def _stderr_tick(msg: str, progress: bool) -> None:
    if not progress:
        return
    # A live phase renames the step. A one-shot caller still gets one line.
    from searchts.progress import announce

    announce(msg)


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


def _is_vendor_wall(html: str) -> bool:
    """Does this refusal body carry an anti-bot vendor's own markup?

    The narrow question the repeated-4xx fast-fail cannot answer. Two identical
    4xx usually means the server is being plain, and #338 stops the ladder there
    to save a browser launch. But a device-check answers a browser with a
    rendered challenge instead of repeating the status, so in that one case the
    rungs would NOT have agreed and skipping the browser hides the only answer
    that names the wall.

    Keyed on the vendor markers in ``_INTERACTIVE_PHRASES`` plus the puzzle
    vendor names, so it fires on evidence rather than on any 403.
    """
    if not html:
        return False
    low = html.lower()
    from searchts.device_check import PUZZLE_MARKERS

    if any(m in low for m in PUZZLE_MARKERS):
        return True
    return "captcha-delivery.com" in low or "px-captcha" in low


#: How much of a refused body is read when the rung raised instead of returning.
_VENDOR_WALL_SCAN = 65536


def _raised_body(exc: BaseException) -> str:
    """The body of a rung that refused by raising, or "" if there is not one.

    urllib's HTTPError keeps the body on its file object, not on a ``body``
    attribute, so a rung that raises on a 4xx looks bodyless to a plain
    ``getattr(exc, "body", "")`` and a vendor wall behind that exception would
    never reach the fast-fail exception in :func:`fetch`. The read is bounded at
    ``_VENDOR_WALL_SCAN``, so a large error page is not pulled into memory for a
    substring test, and the result is trimmed again in case the reader ignored
    the bound. Total as well: no body, no reader, a reader that raises, and a
    reader that returns something other than text all come back "" rather than
    out of here, because a body we cannot read is not a wall.
    """
    body = getattr(exc, "body", None)
    if body is None:
        reader = getattr(exc, "read", None)
        if not callable(reader):
            return ""
        try:
            body = reader(_VENDOR_WALL_SCAN)
        except Exception:  # noqa: BLE001 - see the docstring
            return ""
    if isinstance(body, bytes):
        body = body.decode("utf-8", "replace")
    if not isinstance(body, str):
        return ""
    return body[:_VENDOR_WALL_SCAN]


#: ``page.content()`` serializes the light DOM only. A web component that
#: renders into an open shadow root (MDN's ``<mdn-code-example>`` holds every
#: code sample of a reference page that way) vanishes from it the moment the
#: component upgrades, leaving an empty custom element where the text was. This
#: copies each host's shadow tree into a marked ``<div>`` inside the host, so the
#: serialization carries it. Only hosts with nothing of their own in the light
#: DOM get one: a slotted host's light children are already serialized and a
#: copy would print them twice. Markers from an earlier call are removed first,
#: so calling it again after the page changed never stacks copies.
_INLINE_SHADOW_JS = """() => {
  const MARK = 'data-searchts-shadow';
  const SKIP = new Set(['STYLE', 'SCRIPT', 'LINK', 'SLOT', 'TEMPLATE']);
  let copied = 0;
  const visit = (root) => {
    for (const old of root.querySelectorAll('[' + MARK + ']')) old.remove();
    for (const host of Array.from(root.querySelectorAll('*'))) {
      const sr = host.shadowRoot;
      if (!sr) continue;
      visit(sr);
      if (host.children.length || (host.textContent || '').trim()) continue;
      const box = document.createElement('div');
      box.setAttribute(MARK, '');
      for (const child of Array.from(sr.childNodes)) {
        if (child.nodeType === 1 && SKIP.has(child.tagName)) continue;
        box.appendChild(child.cloneNode(true));
      }
      if (box.childNodes.length) { host.appendChild(box); copied++; }
    }
  };
  visit(document);
  return copied;
}"""


def _inline_shadow_roots(page) -> int:
    """Copy open shadow-root content into the light DOM; how many hosts got one.

    Never raises: a page that will not answer (mid-navigation, closed) has
    nothing to copy, and ``page.content()`` right after reports that failure
    with its own retry and its own error.
    """
    try:
        return int(page.evaluate(_INLINE_SHADOW_JS) or 0)
    except Exception:  # noqa: BLE001 - the caller's content() owns the failure
        return 0


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
            _inline_shadow_roots(page)
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
    """Poll until a painted document stabilizes; keep the largest snapshot until then.

    A JS app is still an empty shell at ``domcontentloaded``, so reading
    ``page.content()`` immediately yields pre-hydration markup and the caller
    judges a live page to be thin. Polling for content-length stability beats
    waiting for ``networkidle``, which never settles on pages holding a live
    connection (streaming, websockets, analytics beacons).

    Stops as soon as two consecutive reads agree, so an already-rendered page
    costs one extra step rather than the whole budget. A persistent
    navigation race fails loud instead of returning the last partial HTML.

    "Stopped growing" is not the same as "finished", though, and on a client
    app the two are indistinguishable at first: measured 2026-10-18 on a served
    page whose module bundle mounts its body 2.2s after load, the DOM held the
    same 146 bytes through +0.25s, +0.50s ... +2.00s and jumped to 488 at
    +2.25s. Length stability read that as "settled" on the first poll, and the
    rung returned the shell: 146 bytes, 8 characters of text, and a page the
    browser was fully able to read.

    So an unpainted DOM does not end the wait. While the rendered document
    still shows less than :data:`_PAINTED_MIN_VISIBLE` characters, keep polling
    to the budget. The cost is bounded and only paid by pages that have not
    painted: a page with real content keeps the one-extra-step behaviour above,
    and a page that never paints ends at the budget and is then judged thin by
    the extractor, which is the honest verdict for it.
    """
    _stderr_tick("waiting for the page to render…", progress)
    waited = 0
    painted_candidate: Optional[str] = None
    painted_stability = 0
    latest_painted: Optional[str] = None
    while waited < budget_ms:
        page.wait_for_timeout(step_ms)
        waited += step_ms
        try:
            current = _page_content(page, progress=progress)
        except Exception as e:  # noqa: BLE001
            if _is_nav_race(e):
                raise
            break
        if len(current) > len(html):
            html = current
            painted_candidate = None
            painted_stability = 0
            if not _is_unpainted(current):
                latest_painted = current
            # The document grew, so "waiting to render" is no longer the step.
            _stderr_tick("waiting for the page to finish rendering…", progress)
            continue
        if not _is_unpainted(current):
            latest_painted = current
            if len(current) < len(html):
                if current != painted_candidate:
                    painted_candidate = current
                    painted_stability = 1
                else:
                    painted_stability += 1
                # A shorter header can paint before the page body. Require five
                # matching polls before treating a shorter DOM as settled: the
                # late paint documented above landed at 2.25s, and three polls
                # (1.5s at the 500ms step) decide inside that window, while a
                # page that paints at 2.25s has had the article on poll five
                # (2.5s). Five identical polls = 2.5s, so a short page that
                # truly is finished still stops far inside the 8s budget.
                if painted_stability < 5:
                    continue
            html = current
            break
        painted_candidate = None
        painted_stability = 0
    return latest_painted or html


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
    # The worker is a different thread, and this runtime does not copy
    # context into the pool. The live step is a context var, so copy it
    # or the browser rung narrates the wrong (or no) step.
    import contextvars

    ctx = contextvars.copy_context()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: ctx.run(fn, *args, **kwargs)).result()


def _expand_clicks(expand_sink: Optional["_ExpandSink"]) -> int:
    """How many presses an expand pass may spend. The knobs answer (F23e).

    The sink carries the budget the read already resolved, so the generic pass
    and a known host's own controls spend **one** budget, not two. A caller that
    reaches the rung without a sink still gets the user's
    ``SEARCHTS_MAX_EXPAND_CLICKS`` rather than a literal: a read has one click
    budget, and it is the ceiling either way (F5f).
    """
    if expand_sink is not None:
        return expand_sink.max_clicks
    from searchts import knobs as _expand_knobs

    return _expand_knobs.resolve().expand_clicks


def _fetch_stealth(
    url: str, timeout: int = 60, progress: Optional[bool] = None,
    proxy: Optional[Dict[str, Any]] = None,
    expand: bool = False, expand_sink: Optional["_ExpandSink"] = None,
) -> Tuple[Optional[int], str, str, Dict[str, str]]:
    """Tier-2: render with an undetected headless Chromium (patchright).

    Lazy by construction — patchright is imported and the browser launched only
    when this backend is reached, then torn down immediately, so it costs memory
    only on the hard pages that tier-1 could not crack (keeps a 16GB box happy).

    Lets the page execute and polls until a script challenge clears. When the page
    is still waiting after that, takes the ONE simple action a device-check
    wants (continue, a checkbox, a press-and-hold that is a single press) via
    ``searchts.device_check``. At most one click is spent, and never on a page
    whose DOM carries a puzzle vendor's markup.

    A puzzle that asks a person to recognize images stops there and is named in
    the returned headers under ``x-searchts-device-stop``, so the caller can say
    WHICH kind of wall this was. It is not solved and it is not sent anywhere.

    F23d: with ``expand`` set, closed ``<details>`` are opened and eligible
    "read/show/see more" buttons are pressed *before* the HTML is captured, so
    the text behind them is extracted by the same extractor as everything else.
    The sink collects what was done so the read can say so in one line.

    Safe under MCP/FastMCP: see ``_call_sync_browser``.
    """
    if proxy or expand:
        # Keyword-only through a closure. The impl's positional order is
        # (url, timeout, progress, proxy, expand, expand_sink), and packing
        # positionals here meant a read with a proxy but no expand handed
        # ``proxy=True`` to the browser rung, which is a boolean where patchright
        # wants a dict. One call site, one rule: never guess positions.
        return _call_sync_browser(
            lambda: _fetch_stealth_impl(
                url, timeout, progress, proxy or None, expand, expand_sink
            )
        )
    # No proxy: delegate exactly as before. An impl stub may take only the
    # original three arguments, and an extra positional is a TypeError.
    return _call_sync_browser(_fetch_stealth_impl, url, timeout, progress)


#: A Chromium that was never downloaded. Patchright's own text for it is a
#: seven-line box naming ``patchright install``, a command that does not exist
#: in the user's environment and does not install what searchts needs. Matched
#: on the sentence, not the box.
_MISSING_CHROMIUM = (
    "executable doesn't exist",
    "playwright was just installed or updated",
)

#: The one sentence for "the browser rung is not there". Named in both spellings
#: because they are different fixes for different machines: pip is what puts the
#: extra in an ordinary venv, and ``searchts install --browser`` is what puts it
#: in a pipx or uv tool env where a bare pip write is wiped by the next upgrade.
_BROWSER_MISSING_HINT = (
    'install the browser tier: pip install "searchts[browser]" (or '
    "searchts install --browser), then read again"
)


def _browser_missing_reason(exc: BaseException) -> Optional[str]:
    """The browser-rung reason for a launch that failed because Chromium is
    absent, or ``None`` when the launch failed for any other reason.

    Only the one case is renamed. Every other launch failure keeps Playwright's
    own message, because "the browser would not start" and "the browser was
    never installed" are different facts and the fix is only known for one of
    them.
    """
    msg = str(exc).lower()
    if any(needle in msg for needle in _MISSING_CHROMIUM):
        return f"browser not installed: {_BROWSER_MISSING_HINT}"
    return None


def _fetch_stealth_impl(
    url: str, timeout: int = 60, progress: Optional[bool] = None,
    proxy: Optional[Dict[str, Any]] = None,
    expand: bool = False, expand_sink: Optional["_ExpandSink"] = None,
) -> Tuple[Optional[int], str, str, Dict[str, str]]:
    try:
        from patchright.sync_api import sync_playwright
    except ImportError as e:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "stealth-browser backend needs patchright: "
            + _BROWSER_MISSING_HINT
        ) from e

    ms = int(timeout * 1000)
    from searchts.ssrf import chromium_pin_args
    pin_args = chromium_pin_args(url)
    # A proxy changes the browser's egress address, which is the whole point
    # when a wall is blocking the address rather than the request. Passed only
    # when set so a proxy-free read launches exactly as before.
    proxy_kwargs: Dict[str, Any] = {"proxy": proxy} if proxy else {}
    want_tick = _progress_wanted(progress)
    _stderr_tick("launching the browser…", want_tick)
    with sync_playwright() as p:
        persistent = _use_persistent_profile()
        try:
            if persistent:
                profile_dir = _profile_path()
                browser = p.chromium.launch_persistent_context(
                    str(profile_dir), headless=True,
                    args=pin_args,
                    user_agent=_UA_REAL, locale="en-US",
                    viewport={"width": 1280, "height": 800},
                    **proxy_kwargs,
                )
            else:
                browser = p.chromium.launch(headless=True, args=pin_args,
                                            **proxy_kwargs)
        except Exception as e:  # noqa: BLE001 - one launch failure, one reason
            missing = _browser_missing_reason(e)
            if missing:
                raise RuntimeError(missing) from e
            raise
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
            _stderr_tick("opening the page…", want_tick)
            resp = page.goto(url, wait_until="domcontentloaded", timeout=ms)
            init_status = resp.status if resp else None
            headers = _normalize_headers(resp.all_headers()) if resp else {}
            # Redirects after DCL: wait for load before the first content().
            _wait_settled_load(
                page, timeout_ms=min(_SETTLE_LOAD_MS, ms), progress=want_tick
            )
            html = _page_content(page, progress=want_tick)
            # Let a JS app hydrate before judging the page; otherwise an SPA
            # comes back as a near-empty shell and reads as "thin".
            html = _await_hydration(page, html, progress=want_tick)
            # Wait (bounded) for a managed JS challenge to auto-resolve.
            from searchts import device_check as _dc

            waited = 0
            if looks_blocked(200, html) == "challenge":
                _stderr_tick("waiting for the check to clear…", want_tick)
            while waited < 15000 and looks_blocked(200, html) == "challenge":
                # A puzzle that needs a person will not resolve itself, and
                # waiting 15s on it only delays the naming of the reason.
                if _dc.human_required(html):
                    break
                page.wait_for_timeout(1500)
                waited += 1500
                html = _page_content(page, progress=want_tick)
            # Still a challenge after the script had its time: take the one
            # simple action it is waiting on. A device-check is a script that
            # finishes and then wants a single press; refusing every click is
            # what made this look permanent. A puzzle needing a person to
            # recognise something stops here by name instead.
            device_stop: Optional[str] = None
            if looks_blocked(200, html) == "challenge":
                html, device_stop = _dc.solve_simple_click(
                    page, html, progress=want_tick
                )
            # F23d: open the folds, while the DOM is still live. This runs after
            # the device-check so a press there is never confused with a press
            # here: one is finishing a challenge script, the other is opening an
            # article, and the counts are separate.
            if expand:
                from searchts import expand as _expand_mod

                want_tick = _progress_wanted(progress)
                _stderr_tick("opening the rest of the page…", want_tick)
                opened = _expand_mod.open_details_in_page(page)
                if opened:
                    html = _page_content(page, progress=want_tick)
                clicks = _expand_clicks(expand_sink)
                report = _expand_mod.click_in_page(page, clicks)
                report.details = opened
                report.pin_paywall(_page_content(page, progress=False))
                if expand_sink is not None:
                    expand_sink.add(report)
                elif report.note():
                    html = _page_content(page, progress=False)
                # F5f: a known host's own controls, on top of the generic pass.
                # Reddit serves the first window of a thread and keeps the rest
                # behind its ``more-comments-partial``, which the generic
                # read/show/see-more words never match. The selectors stay in the
                # one ring file that already knows the host, and the row budget
                # comes from the knobs, so nothing here decides a number.
                host_html = _expand_known_host(
                    page, url, html, clicks,
                    lambda msg: _stderr_tick(msg, want_tick),
                )
                if host_html != html:
                    html = host_html
            # If the challenge cleared, the real status is 200 regardless of the
            # initial challenge response; otherwise keep the original status.
            # A refusal that rendered nothing is the one case the promotion would
            # get wrong: the DOM is an empty document, so it carries no challenge
            # phrase, and 403 would come back as a thin page. Checked before it
            # happens, because afterwards there is nothing left to check.
            status = 200 if (
                looks_blocked(200, html) is None
                and not _is_refused_render(html, init_status)
            ) else init_status
            final = page.url or url
            # page.goto headers can still say "challenge" after the DOM cleared.
            headers = _drop_stale_challenge_headers(headers, html)
            # A named stop travels back so the CLI can say WHICH kind of wall
            # this was. "needs a person: arkoselabs" is actionable; a bare 403
            # is not, and the two are not the same failure.
            if device_stop:
                headers = dict(headers)
                headers["x-searchts-device-stop"] = device_stop
            return status, html, final, headers
        finally:
            browser.close()


def _host_wall_reason(url: str, html: str) -> str:
    """The known host's own name for the wall in ``html``, or ``""``.

    F5f. Only Reddit has one of these today, so this asks one file, and only for
    URLs that file itself claims: ``page_state`` matches copy in the document,
    which is right for a page that really is that page and wrong for a page that
    merely quotes the words. A host with nothing to say returns ``""`` and the
    ladder keeps the generic reason.
    """
    from searchts.known_hosts import reddit as _reddit

    if not _reddit.is_reddit_url(url or ""):
        return ""
    try:
        return _reddit.page_state(url, html) or ""
    except Exception:  # noqa: BLE001 - a named reason must never break the ladder
        return ""


def _expand_known_host(
    page, url: str, html: str, clicks: int, tick=None
) -> str:
    """Let a known host open what its own page hides behind controls (F5f).

    Reddit serves the first window of a thread and keeps the rest behind its
    ``more-comments-partial`` controls; opening them is a browser action, and the
    selectors belong to the one fail-open ring file that already knows the host.
    A host the ring does not recognise returns its HTML unchanged, so this is not
    a routing decision and never a silent one: only ``expand`` reaches here, and
    only after the caller asked.

    Asked the same way as :func:`_host_wall_reason`: import the one host file
    that has an answer, check the host, call it. The ring gains no third hook for
    it (**N4**).

    ``clicks`` is the press budget the caller already resolved from
    ``SEARCHTS_MAX_EXPAND_CLICKS`` (the same number the generic pass spent, so a
    read has one click budget and not two). ``want`` is the row ceiling,
    ``SEARCHTS_MAX_ITEMS``: a comment is a row, and the user caps rows there.
    Both are read from :mod:`searchts.knobs` and never written here.

    ``tick`` is the caller's stderr narrator (P4.6): each round of opening Reddit's
    controls waits on the network, and a loop that can sit for many seconds has to
    say so on the way. It is None when the caller wants silence.

    Returns the fullest HTML seen, or the input unchanged when nothing loaded.
    """
    try:
        from searchts import knobs
        from searchts.known_hosts import reddit as _reddit
    except Exception:  # noqa: BLE001 - the ring must never break the ladder
        return html
    try:
        limits = knobs.resolve()
    except Exception:  # noqa: BLE001 - the ring must never break the ladder
        return html
    try:
        if not _reddit.is_reddit_url(url or ""):
            return html
    except Exception:  # noqa: BLE001 - a named host must never break the ladder
        return html
    try:
        _reddit.expand_more(page, limits.items, clicks, tick)
    except Exception:  # noqa: BLE001 - a failed expand is a shorter read, not a failure
        return html
    try:
        return page.content() or html
    except Exception:  # noqa: BLE001 - the page's own HTML is still worth returning
        return html


def _fetch_human(url: str, timeout: int = 180) -> Tuple[Optional[int], str, str]:
    """Human-in-the-loop fallback: open a HEADFUL browser and let the user solve it.

    Last resort for a puzzle no automated rung could clear (an image grid, a
    login the user has to finish by hand). A DataDome script and a single click
    belong on the stealth rung, not here. Launches a visible (headless=False) patchright
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

    from searchts.progress import current as progress_current
    from searchts.progress import note as progress_note
    from searchts.progress import update as progress_update

    msg = (
        f"A browser opened - solve the challenge/CAPTCHA; waiting up to {timeout} s..."
    )
    # The instruction stays. The live line after it is the wait itself, so a
    # person who is still solving it can see the seconds move.
    if progress_current() is not None:
        progress_note(msg)
        progress_update("waiting for you in the browser…")
    else:
        print(msg, file=sys.stderr, flush=True)

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


class _ExpandSink:
    """Collects what the F23d expand pass did, and prints it once.

    The pass runs inside whichever rung produced the HTML, and the note belongs
    to the read rather than to a rung, so the rungs push into this and
    ``_with_auth`` reads it back. A pass that did nothing adds nothing: a plain
    ``read`` of a page with no folds must end up byte-identical to before.
    """

    def __init__(self, max_clicks: int = 8):
        self.max_clicks = max_clicks
        self._details = 0
        #: Text the markup half measured (extract after minus before), and
        #: whether any rung that opened sections did not measure it. One
        #: unmeasured rung makes the total unknown, which reads as "opened".
        self._added = 0
        self._unmeasured = False
        self._clicks = 0
        self._clicked: List[str] = []
        self._buttons = 0
        self._paywall = False
        self._stop = ""
        #: True once a rung has actually run the pass, so "nothing found" and
        #: "never asked" stay different answers.
        self.ran = False
        self._reports: List["Any"] = []

    def add(self, report: "Any") -> None:
        self.ran = True
        self._reports.append(report)
        self._details += getattr(report, "details", 0)
        if getattr(report, "details", 0):
            added = getattr(report, "added_chars", None)
            if added is None:
                self._unmeasured = True
            else:
                self._added += added
        self._clicks += getattr(report, "clicks", 0)
        self._clicked.extend(getattr(report, "clicked", []) or [])
        self._buttons += getattr(report, "buttons", 0)
        self._paywall = self._paywall or bool(getattr(report, "paywall", False))
        stop = getattr(report, "stop", "")
        if getattr(report, "produced", bool)():
            # A report that found something supersedes an earlier "nothing
            # here". The markup rung cannot see a control the page builds in
            # JavaScript, so its "nothing in this page's markup answered" is
            # stale the moment the browser presses it: measured on
            # kickstarter.com/discover/advanced, two "Show more" presses and
            # the same read also claiming nothing was found is a note nobody
            # can act on. Its own stop is kept when it has one.
            self._stop = stop
        elif stop and not self._stop:
            self._stop = stop

    def note(self) -> str:
        if not self.ran:
            return ""
        return self.report().note()

    @property
    def buttons(self) -> int:
        """Eligible buttons seen in the markup so far, across every rung.

        Read by the ladder to decide whether the markup could answer ``--expand``
        at all, and by the deferred branch to decide whether the note still needs
        to say a browser is missing: when the markup *did* find buttons, the
        expand report already named the command.
        """
        return self._buttons

    def produced(self) -> bool:
        """True when any rung that ran the pass actually opened or found something.

        A page can hold text back with a control it builds in JavaScript, and
        then its markup holds no evidence at all. When that is what happened the
        ladder escalates to the rung that has the DOM, because the caller asked
        for the text and the markup rung could not supply it.
        """
        return any(r.produced() for r in self._reports)

    def report(self):
        from searchts.expand import Report

        return Report(
            html="",
            details=self._details,
            added_chars=(None if self._unmeasured or not self._details
                         else self._added),
            clicks=self._clicks,
            clicked=list(self._clicked),
            buttons=self._buttons,
            paywall=self._paywall,
            stop=self._stop,
        )


def _finalize(
    result: FetchResult, scrub: bool, tick: Optional[Callable[[str], None]] = None,
    media_limit: Optional[int] = None, media_clamp: Optional[str] = None,
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

    F23c/F23d: ``result.extra_notes`` (what the scroll collected and why it
    stopped, what ``--expand`` opened or refused to press) lands here too, and
    *before* the sanitizer runs. A note written after sanitizing is a hole: the
    next-page stop note already had to scrub itself by hand because of that.
    """
    from searchts import more, sanitize
    from searchts.walls import strip_trailing_consent

    kept, banner = strip_trailing_consent(result.text or "")
    if banner:
        result.text = kept
        result.extra_notes.append(
            "[left off: a cookie banner at the end of the page]"
        )

    if result.page_html:
        # F23f: a list page whose extract lost the items' titles, links or dates
        # is rebuilt from the HTML before the notes are worked out.
        rebuilt = more.list_index(result.page_html, result.final_url or "", result.text)
        if rebuilt:
            result.text = rebuilt[0]
        found = more.detect(
            result.page_html, result.final_url or "", result.text,
            headers=result.headers, media_limit=media_limit,
        )
        if media_clamp:
            found.append(more.More("media", media_clamp))
        if rebuilt:
            found.insert(0, rebuilt[1])
        if found:
            result.text = more.annotate(result.text, found)
            result.more = [m.as_dict() for m in found]
            result.next_url = next((m.url for m in found if m.kind == "next-page"), None)
            if tick is not None:
                tick(f"  {more.summary(found)}")
        result.page_html = None
    if result.extra_notes:
        result.text = (result.text or "").rstrip() + "\n\n" + "\n".join(result.extra_notes)
    out = sanitize.scrub(result.text, redact=scrub)
    result.text = out.text
    if not result.fetched_at:
        result.fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result.warnings = out.findings
    return result


def fetch(url: str, backends: Optional[List[str]] = None,
          min_chars: int = _MIN_CHARS, use_memory: bool = True,
          allow_human: bool = False, scrub: bool = False,
          allow_thin: bool = False, progress: Optional[bool] = None,
          cookies: Optional[List["CookieRecord"]] = None,
          proxy: Optional[str] = None, proxy_trusted: bool = False,
          expand: bool = False, echo_attempts: bool = True,
          media: Optional[int] = None) -> FetchResult:
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
        True: stderr names the step that is running, and reprints it with the
        real elapsed seconds while that step is still the one running.
        False: never (CLI ``--json``). None: follow ``SEARCHTS_PROGRESS=1``.
        MCP/library omit the arg.
    echo_attempts:
        True: also print each rung's result (``curl_cffi: ok``, ``thin-12b``).
        False: the live line is only the step. The caller prints the reasons
        once, which is what ``searchts read`` does so a failure is not said
        twice.
    cookies:
        Session cookies to present as an already-logged-in reader, from
        ``searchts.session_cookies``. Default None: no cookie material anywhere,
        and every rung behaves exactly as it did before.

        They are filtered to the normalized target's own host before use, so a
        jar holding cookies for several sites contributes only the ones this
        host would really have been sent. ``.amazon.in`` rides along on
        ``www.amazon.in``; ``notamazon.in`` gets nothing.

        THE FENCE: a Cookie header is attached to exactly one rung, the
        direct-host ``curl_cffi`` fetch. It never goes to ``Jina Reader`` (a
        cookie sent to r.jina.ai is a live login handed to a third party), and
        this change does not wire cookies into ``stealth-browser`` either. The
        value is never logged, printed, or put in an error message or on the
        FetchResult.
    proxy:
        ``scheme://[user:pass@]host:port`` to route the direct and browser rungs
        through. This is the lever for a block decided on our egress ADDRESS
        rather than our request, which no fingerprint or cookie can move.
        Measured: some sites 403 this network on principle, with byte-identical
        responses for Chrome-impersonated curl and plain requests, while
        Wikipedia/GitHub/BBC read 200 from the same IP in the same minute.

        None (the default) keeps every rung on the user's own address, which is
        today's behaviour. The Jina rung is deliberately NOT proxied: it fetches
        from r.jina.ai's address, not yours, so your proxy cannot move it.
    proxy_trusted:
        Acknowledge that a remote proxy's operator will see the cookie header.
    expand:
        F23d. Open the text the page is holding back: closed ``<details>`` and
        buttons labelled read/show/see more. Off unless asked, because a click
        makes the read slower and different each time. Never presses a link, a
        form control or a sign-in, and a "continue reading" paywall is named
        rather than opened.

        Asking for it also drops **Jina Reader** from the ladder. The relay
        returns rendered markdown and nothing can tell it to press a button, so
        on a page with a real "Show more" (measured on
        kickstarter.com/discover/advanced: one press is worth +4,102 characters)
        the relay would quietly win and the read would come back short of what
        was asked for. With ``expand`` the read runs on a rung that has the DOM.

        F5f rides this same bool rather than a count: how many clicks that
        budget is comes from the ``expand_clicks`` knob, never from here. A known
        host keeps its own selectors - Reddit's "more replies" partials are its
        own, not the generic read/show/see-more words.
    """
    if progress is None:
        progress = os.environ.get("SEARCHTS_PROGRESS", "") in (
            "1", "true", "True", "yes",
        )

    from searchts.progress import note as progress_note
    from searchts.progress import phase as progress_phase

    def _tick(msg: str) -> None:
        # Best-effort only: a closed/broken stderr must never abort the fetch.
        # Indented lines are the rung's result. The CLI prints those once at
        # the end, so it asks for the step without the copy. A proxy note and
        # a "more:" note are not that copy.
        if not progress:
            return
        diagnosis = (
            msg.startswith("  ")
            and not msg.startswith("  proxy:")
            and not msg.startswith("  more:")
        )
        if diagnosis and not echo_attempts:
            return
        progress_note(msg)

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

    # Host-scoped cookie material, resolved ONCE and used by ONE rung. Scoped
    # here, against the normalized URL's host, because that is the only place
    # the target host is known: by the time the ladder runs, `final_url` may be
    # a redirect and `url` is the only host the caller actually asked about.
    # filter_for_host owns the suffix rule (.amazon.in yes, notamazon.in no), so
    # this does not re-implement it.
    cookie_header = ""
    if cookies:
        from searchts.session_cookies import build_header, filter_for_host
        target_host = (urllib.parse.urlparse(url).hostname or "").lower().rstrip(".")
        scoped_cookies = filter_for_host(cookies, target_host)
        if scoped_cookies:
            cookie_header = build_header(scoped_cookies)
        # A jar with nothing for this host is not an error: it just means this
        # read is anonymous. The ladder runs unchanged.

    # Proxy resolution, and the second fence. A proxy is a third party in the
    # path, so a Cookie header through one hands that operator a live login.
    # Refused for a remote proxy unless the caller says they accept it; a proxy
    # on loopback or a private network is this machine and is trusted by
    # default, because that is a property of the connection rather than
    # something the far side can assert.
    proxy_spec = None
    proxy_curl: Optional[str] = None
    proxy_browser: Optional[Dict[str, Any]] = None
    if proxy:
        from searchts.egress import (
            ProxyError,
            cookies_may_travel,
            curl_proxy_url,
            normalize_proxy,
            playwright_proxy,
            redact,
        )

        try:
            proxy_spec = normalize_proxy(proxy)
        except ProxyError as e:
            raise UnlockerError(url, [("proxy", str(e))]) from e
        if cookie_header and not cookies_may_travel(proxy_spec, proxy_trusted):
            # Never log the proxy credentials, not even here.
            raise UnlockerError(url, [("proxy", (
                f"refusing to send cookies through {redact(proxy)}: a proxy "
                f"operator can read the Cookie header, which is a live login. "
                f"Use a proxy on this machine, run the read without cookies, or "
                f"pass --proxy-trusted (proxy_trusted=True) to accept it."
            ))])
        proxy_curl = curl_proxy_url(proxy_spec)
        proxy_browser = playwright_proxy(proxy_spec)
        _tick(f"  proxy: {redact(proxy)}")

    # Tier-0: AI-chat share links (chatgpt.com/share, claude.ai/share, poe.com/s)
    # carry their conversation in provider-specific data channels that generic
    # HTML extraction can't see (or sees only partially). A dedicated extractor
    # returns the COMPLETE conversation; any failure falls through to the ladder.
    #
    # ── does this read answer "as the logged-in user" or "as anyone"? ────────
    # Only the direct curl rung can carry the jar, so only a curl win is an
    # authenticated answer. Reported so an agent can tell the two apart; a
    # boolean, never a value. Measured: with `--cdp-port` on a real login the
    # receipt was byte-identical to the anonymous one, so "I read your Drive"
    # and "I read Drive's public page" looked the same to the caller.
    cookie_rung = "curl_cffi"

    # F23d: what the expand pass did, collected across the rungs that ran and
    # printed once, on whichever result wins. A sink rather than a return value
    # because the pass happens deep inside a rung and the note belongs to the
    # read, not to the rung.
    from searchts import expand as _expand
    from searchts import knobs as _knobs
    from searchts import scroll as _scroll

    # The click ceiling is policy, not argument (F23e): `--expand` says yes to
    # expanding and the user's ceiling says how far. Nothing here raises it.
    _limits = _knobs.resolve()
    expand_sink = _ExpandSink(max_clicks=_limits.expand_clicks)

    from searchts import more as _more_mod

    media_limit, media_clamp = _more_mod.resolve_media_limit(media)

    def _with_auth(result: FetchResult) -> FetchResult:
        result.authenticated = bool(cookie_header) and result.backend == cookie_rung
        note = expand_sink.note()
        if note:
            result.extra_notes = list(result.extra_notes or []) + [note]
        return _finalize(
            result, scrub, tick=_tick,
            media_limit=media_limit, media_clamp=media_clamp,
        )

    try:
        from searchts import share_extractors
        share = share_extractors.extract(url) if share_extractors.matches(url) else None
    except Exception:  # noqa: BLE001 - tier-0 must never break the ladder
        share = None
    if share is not None and share.markdown:
        return _with_auth(
            FetchResult(f"share:{share.provider}", share.markdown, 200, final_url=url)
        )

    # A player page's words are spoken. Captions come back as the read. No
    # captions is a named failure, not a title and a shell passed off as the
    # article. A crash, or a URL that is not a player, falls through.
    try:
        from searchts import players
        if players.matches(url):
            with progress_phase("trying player captions…", enabled=bool(progress)):
                played = players.extract(url)
        else:
            played = None
    except Exception:  # noqa: BLE001 - a player miss must not break the ladder
        played = None
    if played is not None and played.failure:
        _tick(f"  player: {played.failure}")
        raise UnlockerError(url, [("player", played.failure)], hint=played.failure)
    if played is not None and played.markdown:
        _tick(f"  player: captions ({len(played.markdown)} chars)")
        return _with_auth(
            FetchResult("player:captions", played.markdown, 200, final_url=url)
        )

    # Tier-0.5: known-host public-API endpoints (e.g. Reddit .json).
    # A fail-open ring — on miss/exception the normal ladder runs unchanged.
    # No domain-memory pinning for reddit.com (volatile per request).
    try:
        from searchts import known_hosts as _known_hosts
        if _known_hosts.matches(url):
            kh_name = _known_hosts.matching_name(url) or "known-host"
            with progress_phase(f"trying known-host:{kh_name}…", enabled=bool(progress)):
                kh = _known_hosts.extract(url)
            if kh is not None and kh.markdown:
                _tick(
                    f"  known-host:{kh.provider}: ok ({len(kh.markdown)} chars)"
                )
                return _with_auth(
                    FetchResult(
                        f"known-host:{kh.provider}",
                        kh.markdown,
                        200,
                        final_url=url,
                    )
                )
            _tick(f"  known-host:{kh_name}: miss")
    except Exception:  # noqa: BLE001 - ring must never break the ladder
        pass

    order = list(backends if backends is not None else DEFAULT_BACKENDS)
    if not jina_enabled() or _jina_spent:
        order = [b for b in order if b != "Jina Reader"]
    if expand:
        # F23d: the relay cannot be told to press a button, so an expanded read
        # has to run on a rung that has the DOM. Dropping Jina here also means
        # an expanded read never hands a URL to a third party, which is the
        # wrong trade for "open the folds on this page".
        _jina_dropped = "Jina Reader" in order
        order = [b for b in order if b != "Jina Reader"]
    else:
        _jina_dropped = False

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
    if _jina_dropped and not order:
        # `--backend jina --expand` leaves nothing to try. An empty reason list
        # says only "all backends failed"; name the real cause.
        attempts.append(("Jina Reader", "skipped: the relay cannot press a button, so --expand does not use it"))
    best: Optional[FetchResult] = None  # richest non-blocked but thin result so far
    status: Optional[int] = None
    #: The refusal status seen so far, and how many rungs have repeated it. A
    #: server that says 403 to curl says 403 to a browser; see _ESCALATE_UNLESS.
    refusal_status: Optional[int] = None
    refusal_count = 0
    #: A status that only the non-browser rungs reported, and the fact that the
    #: browser has not actually been asked. See _REFUSAL_REPEAT_LIMIT: two
    #: identical 4xx normally means the server is telling us plainly. That
    #: reasoning is wrong for a device-check, because the browser's verdict is
    #: not a status at all, it is a rendered interstitial. datadome.co measured
    #: 403 from curl, 403 from Jina, and then 403 carrying 1,464 characters of
    #: geo.captcha-delivery.com from a real Chromium. Skipping the rung there
    #: hides the only answer that names the wall.
    browser_would_differ = False
    #: A rung served markup with no text in it and the signs of a client app.
    #: Only the browser can read such a page, and the browser is sent no
    #: cookies, so the one sentence worth saying is about the rung and the
    #: fence rather than about a thin article.
    app_shell = False
    #: F23d: a clean curl win we stepped over to let the browser try to open the
    #: folds. If the browser cannot be run, or fails, this read is still good
    #: and saying so beats failing on a page we already read. `allow_thin` is
    #: not the right home for it: nothing here was thin, we simply asked a
    #: second question.
    deferred: Optional[FetchResult] = None

    for backend in order:
        if refusal_count >= _REFUSAL_REPEAT_LIMIT and not (
            browser_would_differ and backend == "stealth-browser"
        ):
            attempts.append((backend, "skipped-no-new-tls"))
            _tick(f"  {backend}: skipped, {refusal_status} already refused twice")
            continue
        with progress_phase(f"trying {backend}…", enabled=bool(progress)):
            try:
                final_url = url
                headers: Dict[str, str] = {}
                if backend == "curl_cffi":
                    # The one rung that talks to the target host, so the one rung
                    # that may carry its cookies. Passed only when there is a header
                    # to pass, so a cookie-free read calls the fetcher exactly as
                    # before. Jina's and the browser's call sites below stay bare:
                    # that is the fence, and it is a call-site fence, not a filter.
                    if cookie_header or proxy_curl:
                        # Both kwargs are passed only when they carry something, so a
                        # plain read calls the fetcher with the identical argument
                        # list it always had. That is not only tidiness: existing
                        # test stubs are `lambda url, timeout=30`, and passing a
                        # keyword they do not declare is a TypeError, not a no-op.
                        kwargs: Dict[str, Any] = {}
                        if cookie_header:
                            kwargs["extra_headers"] = {"Cookie": cookie_header}
                        if proxy_curl:
                            kwargs["proxy"] = proxy_curl
                        status, body, final_url, headers = _fetch_curl_cffi(url, **kwargs)
                    else:
                        status, body, final_url, headers = _fetch_curl_cffi(url)
                elif backend == "Jina Reader":
                    # FENCE, and deliberately unchanged by the proxy work: this rung
                    # takes a URL and nothing else. It fetches from r.jina.ai's
                    # address, so our proxy cannot move it either, and a cookie here
                    # would be a live login handed to a third party.
                    status, body, final_url, headers = _fetch_jina(url)
                elif backend == "stealth-browser":
                    # No cookie header here, ever. The browser may carry the proxy,
                    # because that changes the address the challenge is judged from.
                    if proxy_browser or expand:
                        status, body, final_url, headers = _fetch_stealth(
                            url, progress=progress, proxy=proxy_browser,
                            expand=expand, expand_sink=expand_sink,
                        )
                    else:
                        status, body, final_url, headers = _fetch_stealth(
                            url, progress=progress,
                        )
                else:
                    attempts.append((backend, "unknown-backend"))
                    _tick(f"  {backend}: unknown-backend")
                    if backend == remembered:
                        unpin(domain)
                        remembered = None
                    continue

                if status is not None and 400 <= status < 500 and status not in (404, 429):
                    # A refusal status that survives a change of TLS fingerprint and
                    # user agent is the server declining on the request itself, not
                    # on how it arrived. Measured across 13 sites: stackoverflow,
                    # economist and science return 403 to curl AND 403 to the
                    # stealth browser; arstechnica 405 and 405; reuters 401 and 401.
                    # Each browser launch cost 18-20s to confirm the refusal.
                    #
                    # GitLab is the case this must not break, and it does not: curl
                    # returns 200 there with a thin 279-char extract, so there is no
                    # refusal to repeat and the ladder escalates on thinness as
                    # before. 404 and 429 are excluded because both can legitimately
                    # differ per client - a path may exist only in the rendered
                    # app, and a rate limit may reset between rungs.
                    if status == refusal_status:
                        refusal_count += 1
                    else:
                        refusal_status = status
                        refusal_count = 1
                    if status in (403, 405, 401) and _is_vendor_wall(body or ""):
                        # The refusal carried a vendor's own wall markup, so the
                        # browser's answer is a rendered challenge rather than the
                        # same status. Worth the launch; see browser_would_differ.
                        browser_would_differ = True

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
                    if reason == "challenge":
                        # F5f: "challenge" says a wall was here. When a known host
                        # can say WHICH one, that is the only actionable fact in the
                        # run. Measured 2026-10-17: Reddit answers a direct request
                        # for a next-batch cursor with HTTP 200 and its "Prove your
                        # humanity" page, which is indistinguishable from any other
                        # challenge in the body alone.
                        reason = _host_wall_reason(url, body) or reason
                    if reason:
                        # Say WHICH wall it was when the rung can name one. The
                        # stealth browser reports its device-check stop in headers,
                        # and collapsing that to a bare "http-403" throws away the
                        # only actionable fact in the whole run: whether a person
                        # is required, and which vendor wants one.
                        stop = headers.get("x-searchts-device-stop")
                        if stop:
                            reason = "%s (needs a person: %s)" % (reason, stop)
                        attempts.append((backend, reason))
                        _tick(f"  {backend}: {reason}")
                        if backend == remembered:
                            unpin(domain)
                            remembered = None
                        continue
                    # F5c/F5f: Reddit listing, feed batch, thread, profile or search
                    # from the HTML this rung already downloaded. A page that is a
                    # wall reports itself and the ladder keeps going, so a private,
                    # banned, quarantined, gone or NSFW page never comes back as
                    # navigation chrome wearing a URL.
                    reddit_hit = _reddit_listing.extract_page(url, body)
                    if reddit_hit is not None:
                        if reddit_hit.failure:
                            attempts.append((backend, reddit_hit.failure))
                            _tick(f"  {backend}: {reddit_hit.failure}")
                            if backend == remembered:
                                unpin(domain)
                                remembered = None
                            continue
                        _tick(reddit_hit.label)
                        page_result = FetchResult(
                            backend,
                            reddit_hit.markdown,
                            status,
                            final_url=final_url or url,
                            headers=headers,
                            next_url=reddit_hit.next_url,
                            more=reddit_hit.as_dicts(),
                            index_keys=reddit_hit.keys or None,
                        )
                        return _with_auth(page_result)
                    if _is_plain_text_body(body, headers):
                        # The server sent text, not markup: a README, a JSON
                        # document, an rST file. The article extractor is shaped for
                        # HTML and throws away what it cannot read as a paragraph,
                        # which for a README is most of the code. The body is
                        # already the page, so it is the text.
                        text = cap_text(body)
                    else:
                        text = html_to_text(body, url)

                text = text or ""
                # F23d: a rung that produced HTML gets the no-browser half of the
                # expand pass before extraction, so a closed `<details>` becomes
                # text. `body` is only set on the non-Jina path, which is exactly
                # where there is markup to rewrite.
                if expand and body:
                    rep = _expand.expand_html(body)
                    if rep.html != body:
                        body = rep.html
                        if backend != "Jina Reader":
                            opened_text = html_to_text(body, url)
                            # Measured, so the note says what the rewrite really
                            # did. And never trade text for text: an extract that
                            # came out shorter with the folds open keeps the one
                            # the read already had.
                            rep.added_chars = len(opened_text) - len(text)
                            if rep.added_chars > 0:
                                text = opened_text
                    expand_sink.add(rep)
                # Login-wall on the extract only (raw HTML often has a sign-in modal).
                # `final_url` rides along: a redirect onto /login is the wall, even
                # when the shell that renders there is too short to be scored.
                extract_reason = looks_blocked(200, text, login_wall=True,
                                               final_url=final_url)
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
                    # F23d: the caller asked for the text behind the folds and this
                    # rung's HTML has buttons whose text is not in it. Say why the
                    # rung is passing and escalate; a read that quietly returns the
                    # window is the failure `--expand` exists to remove. The second
                    # clause covers the harder case: a page that builds its "Show
                    # more" in JavaScript leaves nothing in its markup for the
                    # first check to find, and only the rendered DOM can answer.
                    if expand and backend == "curl_cffi" and (
                        expand_sink.buttons or not expand_sink.produced()
                    ):
                        why = (
                            f"expand-needed-{expand_sink.buttons}-control(s)"
                            if expand_sink.buttons
                            else "expand-not-satisfied-by-markup"
                        )
                        attempts.append((backend, why))
                        _tick(f"  {backend}: {why}, escalating to the browser")
                        if backend == remembered:
                            unpin(domain)
                            remembered = None
                        deferred = FetchResult(
                            backend, text, status,
                            final_url=final_url or url, headers=headers,
                            page_html=body,
                        )
                        if best is None or len(text) > len(best.text):
                            best = deferred
                        continue
                    _tick(f"  {backend}: ok ({len(text)} chars{', whole page' if whole else ''})")
                    # clean win, stop here — sanitize untrusted content before return
                    return _with_auth(
                        FetchResult(
                            backend,
                            text,
                            status,
                            final_url=final_url or url,
                            headers=headers,
                            page_html=None if backend == "Jina Reader" else body,
                        )
                    )
                # Real but thin (e.g. JS-rendered or genuinely short): keep as a
                # fallback and escalate in case a richer backend renders more.
                if body and not app_shell:
                    app_shell = _is_app_shell(body, text)
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
                # A rung that REFUSES by raising still counts toward the repeat
                # limit. Jina is the common case: urllib raises HTTPError on a 4xx
                # rather than returning it, so before this the refusal count only
                # ever advanced on curl, the fail-fast in #338 fired on one rung,
                # and stackoverflow still paid a browser launch - 29.9s where the
                # intent was to stop at two.
                refused = getattr(e, "code", None)
                if not isinstance(refused, int):
                    refused = getattr(getattr(e, "status", None), "code", None)
                if (
                    isinstance(refused, int)
                    and 400 <= refused < 500
                    and refused not in (404, 429)
                ):
                    if refused == refusal_status:
                        refusal_count += 1
                    else:
                        refusal_status = refused
                        refusal_count = 1
                if refused in (403, 405, 401) and _is_vendor_wall(_raised_body(e)):
                    # A vendor wall is the one case where the browser is expected to
                    # answer differently, because it renders a challenge instead of
                    # repeating the status. See browser_would_differ above.
                    browser_would_differ = True
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
        with progress_phase("trying human-browser…", enabled=bool(progress)):
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
                page_hit = None
                text = ""
                if not hop:
                    # F5c/F5f: listing, batch, thread, profile or search (human
                    # rung). Wins even if short, and even when an earlier rung left
                    # a longer thin `best`. A page that is a wall reports itself, so
                    # a private or quarantined community never reads as its nav bar.
                    # A wall is not ticked here: one rung says its one reason, below,
                    # so the page's own name cannot be answered by "empty-extract"
                    # underneath it.
                    try:
                        page_hit = _reddit_listing.extract_page(url, html)
                        if page_hit is not None:
                            if not page_hit.failure:
                                _tick(page_hit.label)
                                text = page_hit.markdown
                        if not text and page_hit is None:
                            text = html_to_text(html, url)
                    except Exception as e:  # noqa: BLE001 - fail loud, not a traceback
                        text = ""
                        human_error = human_error or f"extract failed ({type(e).__name__}: {e})"
                wall = looks_blocked(200, text, login_wall=True, final_url=final_url) if text else None
                if (
                    text
                    and wall is None
                    and (
                        page_hit is not None
                        or best is None
                        or len(text) > len(best.text)
                    )
                ):
                    human = FetchResult(
                        backend="human-browser", text=text, status=status,
                        final_url=final_url or url,
                        page_html=None if page_hit is not None else html,
                        next_url=page_hit.next_url if page_hit is not None else None,
                        more=page_hit.as_dicts() if page_hit is not None else [],
                        index_keys=(page_hit.keys or None) if page_hit is not None else None,
                    )
                    if page_hit is not None or len(text) >= min_chars:
                        return _with_auth(human)
                    best = human
                    attempts.append(("human-browser", f"thin-{len(text)}b"))
                    _tick(f"  human-browser: thin-{len(text)}b")
                else:
                    # One rung, one line. The reason is decided here and nowhere
                    # else: a page that is a wall is named by that wall, and the
                    # generic "nothing came out" answer cannot be printed under it.
                    # Printing both made one rung read as two failures, and the
                    # second was a lie about the page: it was not empty, it was
                    # refused.
                    if hop:
                        why = hop
                    elif human_error:
                        why = human_error
                    elif page_hit is not None and page_hit.failure:
                        why = page_hit.failure
                    elif not text:
                        why = "empty-extract"
                    elif wall is not None:
                        why = wall
                    else:
                        why = f"thin-{len(text)}b"
                    attempts.append(("human-browser", why))
                    _tick(f"  human-browser: {why}")

    if allow_thin and best is not None:
        return _with_auth(best)

    if deferred is not None:
        # Every rung after the one we stepped over failed, including the
        # browser that was asked to open the folds. The page was read; only
        # the extra text is missing, and the attempts above say why.
        deferred.headers = dict(deferred.headers or {})
        deferred.headers["x-searchts-expand-deferred"] = "; ".join(
            f"{b}: {w}" for b, w in attempts[-2:]
        )
        if expand and not expand_sink.buttons and not _scroll.browser_available():
            # F23d, fail loud. The page may well hold text behind a "Show more"
            # it builds in JavaScript: nothing in the markup says so, the rung
            # that could have pressed it never ran, and the read would otherwise
            # come back as a clean success with the folds still shut. Saying
            # what to run is the whole point of `--expand` not existing yet.
            deferred.extra_notes = list(deferred.extra_notes or []) + [
                "[expand: this page may hold text behind a control only the "
                "browser can see, and no browser is installed, so nothing was "
                "opened. Run: searchts install --browser]"
            ]
        elif expand and _scroll.browser_available():
            # The browser is installed and still could not open the page (a
            # challenge, a timeout). The markup pass's own line says "nothing
            # in this page's markup answered", which is true and reads as "the
            # page has nothing to open". Measured on kickstarter.com/discover/
            # advanced from a datacenter address: the browser rung got a
            # Cloudflare Turnstile, and the text said only that line.
            why = attempts[-1][1] if attempts else "unknown"
            deferred.extra_notes = list(deferred.extra_notes or []) + [
                "[expand: the browser could not open this page, so only the "
                f"markup was expanded and a control built in JavaScript was not "
                f"pressed ({attempts[-1][0] if attempts else 'browser'}: {why})]"
            ]
        return _with_auth(deferred)

    raise UnlockerError(
        url, attempts, _final_hint(cookie_header, attempts, url, app_shell=app_shell)
    )


def _final_hint(
    cookie_header: str, attempts: List[Tuple[str, str]], url: str,
    app_shell: bool = False,
) -> str:
    """The one sentence that says what to do next, when the reasons do not.

    Two cases, checked in order. A cookie read that still landed on a login page
    has one cause and one next step, and three copies of "login-wall" do not say
    either. A Reddit notice a person has to accept (a quarantine, an over-18
    gate, a banned community) is the same shape: the ladder is right that it
    cannot read it, and only the person can move it.

    Within Reddit's reasons the *named content* state wins over the humanity
    check, and that ordering is the whole point. Measured 2026-10-17 on
    /r/gryffindor/: curl got the interstitial and the browser rung got the real
    page, which is a private community. Reporting the first reason said
    "Prove your humanity" about a page whose answer is "there is no public page
    to fetch" - true of the request, useless about the URL.
    """
    cookie = _cookie_login_hint(cookie_header, attempts)
    if cookie:
        return cookie
    if app_shell:
        return _app_shell_hint()
    from searchts.known_hosts import reddit as _reddit

    fallback = ""
    for _backend, why in attempts:
        if not why.startswith("reddit-"):
            continue
        if why == "reddit-challenge":
            # Held back, not thrown away: when every rung got the interstitial
            # this is the whole answer, and there is nothing better to say.
            fallback = fallback or _reddit.state_note(why, url)
            continue
        note = _reddit.state_note(why, url)
        if note:
            return note
    return fallback


def _app_shell_hint() -> str:
    """The one sentence for a page the address only ever sends to a browser.

    Two facts, and both of them are needed. The markup carries no text, so no
    rung that speaks HTTP can do better. And the browser rung is sent no
    cookies, which is the fence that keeps a cookie from reaching a third
    party, so "sign in and the browser will read it" is not a plan here. What
    the browser can do is render the page, and the command to install it is
    what is actually missing when it is not there.
    """
    from searchts import scroll as _scroll

    if _scroll.browser_available():
        return (
            "this page is a JS app: the markup it served carries almost none "
            "of its text, so only the browser tier can read it, and that tier "
            "is sent no cookies. The browser rung did not manage this page "
            "either."
        )
    return (
        "this page is a JS app: the markup it served carries almost none of "
        "its text, so only the browser tier can read it, and that tier is sent "
        "no cookies, so there is no rung left that can. Run: searchts install "
        "--browser"
    )


def _cookie_login_hint(
    cookie_header: str, attempts: List[Tuple[str, str]]
) -> str:
    """The one sentence a cookie read needs when it still lands on a login page.

    Cookies were scoped to this host and attached to the direct request, and the
    site answered with its login page anyway. Every rung then reports
    "login-wall" and the caller is left guessing which of the three causes it
    is: the session expired, the cookies went to the wrong profile, or the
    browser rung simply cannot carry them (the fence). That last one is the
    common case and it is invisible from the report, so it is named here
    rather than left to be discovered from a third failed read.

    Empty unless cookies were actually sent, so an anonymous read is unchanged.
    """
    if not cookie_header:
        return ""
    if not any("login-wall" in why for _, why in attempts):
        return ""
    return (
        "cookies were sent for this host and the site still returned a login "
        "page: the session is probably expired, or these cookies belong to a "
        "different profile. They ride the direct request only - the browser "
        "tier is sent no cookies at all - so a logged-in read cannot be fixed "
        "by making the browser logged in."
    )


_MAX_PAGES = 5


def read_pages(url: str, pages: int = 1, **kwargs) -> List[FetchResult]:
    """Read this page and follow its next page, curl only, up to ``pages``.

    Stops on a loop, a missing next link, or the cap. The first page uses the
    caller's backends. Later pages are curl only: a browser on every next page
    is not this change. The cap is said out loud: a walk that hits it with a
    live next link would otherwise look like the list ended.

    F23e: the cap is the user's, not the product's. ``SEARCHTS_MAX_PAGES`` or a
    ``more:`` block in the config lowers it; nothing can raise it above the
    product cap; and a request over it is clamped **on page one**, which is the
    text every caller actually reads. It used to land on the last page, so
    ``read --json`` reported a truncated read with exit 0 and a ``text`` field
    that never mentioned it.
    """
    from searchts import knobs
    from searchts.progress import note as progress_note
    from searchts.progress import wanted as progress_wanted

    asked = max(1, int(pages or 1))
    limits = knobs.resolve(pages=asked)
    wanted = max(1, int(limits.pages))
    show_progress = progress_wanted(kwargs.get("progress"))
    seen = set()
    out: List[FetchResult] = []
    current = url
    # The copy of each page the walk read, so a page that serves one of them
    # again is recognised as the copy and not as more of the document.
    said: set = set()
    repeated = 0
    last_next = ""
    for i in range(wanted):
        if show_progress and wanted > 1:
            progress_note(f"reading page {i + 1} of {wanted}…")
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
            # F5f: one known host judges the request itself on a next-page
            # cursor, so the hop is worth a second ask on the rung that has a
            # profile. Nothing else changes: a hop that fails again is reported
            # exactly as it would have been.
            retry = _retry_hop_on_browser(current, e, call) if i else None
            if retry is not None:
                result = retry
            else:
                # Page one is the URL the caller asked for: nothing to return,
                # so the error stands. A later hop failing means the caller
                # already has real content, and throwing it away to report a URL
                # they never asked for is a bad trade. Keep the pages, say why
                # the walk ended.
                if i == 0 or _is_refusal(e):
                    raise
                _note_walk_stopped(out[-1], current, e)
                break
        last_next = result.next_url or ""
        # A page that serves the copy we already have is not more of the
        # document: it is the same page under another address. It is still
        # returned - the walk read it, and the caller asked for pages, not for
        # pages that differ - but the walk says so, because a page list that
        # hid four copies of one page would be a claim the reader cannot
        # check.
        fingerprint = _page_fingerprint(result)
        if fingerprint and fingerprint in said:
            repeated += 1
        else:
            said.add(fingerprint)
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
        # The loop ran out with pages still coming. Only worth saying when the
        # cap actually cut the request short: asking for 1 and getting 1 is not
        # a truncation, and read_pages(url, 1) is the default single-page read
        # on both the CLI and the MCP tool. Noting it there put a false "you
        # hit a cap" line on every ordinary read of a paginated page. `asked`,
        # not `wanted`: the sentence is about what the caller asked for, and the
        # clamp note on page one is the one that names the ceiling.
        if out and len(out) < asked and last_next:
            _note_walk_capped(out[-1], len(out), asked, last_next)
    if repeated and out:
        # On page one: that is the page every caller reads first (the CLI's
        # stdout, the MCP envelope's ``text``), so the warning about the copies
        # comes before the copies do.
        _note_walk_repeated(out[0], repeated)
    if out:
        _note_knobs(out[0], limits)
    return out


def _retry_hop_on_browser(url: str, err: "UnlockerError", call: Dict[str, Any]):
    """One browser retry of a next-page hop a known host walled off. None if no.

    F5f. A next-page walk is curl-only after the first page (F23b), which is
    right for a static pager and wrong for a site that judges the request rather
    than the address: Reddit answers a direct request for its own
    ``/svc/shreddit/…`` cursor with "Prove your humanity", and the same URL is 24
    cards in the browser rung. Without this, ``--items`` on Reddit stops at the
    first window forever.

    Whether the wall is that kind is Reddit's own answer, asked the way
    :func:`_host_wall_reason` asks it: import the one file that knows the host,
    check the host, call it. Nothing here knows what Reddit is and the ring gains
    no hook for it (**N4**). The retry carries the same cookies-free, proxy-free
    arguments the first hop had - a proxy or cookies the walk cannot carry is
    dropped by the same rules the scroll uses - and returns ``None`` if it fails,
    so the caller reports the original failure, with the retry's own reasons
    appended to its attempts.
    """
    try:
        from searchts.known_hosts import reddit as _reddit
    except Exception:  # noqa: BLE001 - the ring must never break a walk
        return None
    try:
        if not _reddit.is_reddit_url(url or ""):
            return None
        if not _reddit.hop_needs_browser(url, err.attempts):
            return None
    except Exception:  # noqa: BLE001
        return None
    retry = dict(call)
    retry["backends"] = ["stealth-browser"]
    retry["allow_human"] = False
    retry["use_memory"] = False
    try:
        return fetch(url, **retry)
    except UnlockerError as again:
        # The caller reports the original error, so the retry's own reason has
        # to travel on it: a browser that is not installed, or a profile that is
        # still challenged, is a different next step from "curl was refused".
        for rung, why in again.attempts or [("stealth-browser", str(again))]:
            err.attempts.append((f"{rung} (retry)", why))
        return None


def _note_knobs(page: "FetchResult", limits) -> None:
    """Write a clamped-request note onto the page the caller reads.

    Page one, always. The old place was the last page of the walk, which the
    CLI printed after the main text and the MCP envelope put in ``pages[1]`` -
    so a caller that read ``text`` (the normal way) never saw that its request
    had been cut down. A note about the request belongs with the request.
    """
    note = limits.note()
    if not note:
        return
    from searchts import sanitize

    scrubbed = sanitize.scrub(note, redact=True)
    page.warnings = list(page.warnings or []) + scrubbed.findings
    page.text = (page.text or "").rstrip() + f"\n\n{scrubbed.text}"


def _note_walk_capped(
    last: "FetchResult", got_pages: int, asked: int, nxt: str, rows: str = ""
) -> None:
    """Say the walk stopped at a cap, not because the list ended.

    Only called when the caller asked for more than it got, so the wording is
    always "asked N, got M". Scrubbed for the same reason as
    :func:`_note_walk_stopped`: the note lands after _finalize, and the
    next-page URL is page-supplied.
    """
    from searchts import sanitize

    if rows:
        # A row walk: ``asked`` is rows here, not pages, so "asked for 70, got
        # 5" set a row count beside a page count. Rows against the ceiling that
        # applied, and the pages as pages.
        got = f"{rows}, stopped after {got_pages} page{'s' if got_pages != 1 else ''}"
    else:
        got = f"asked for {asked}, got {got_pages}"
    note = sanitize.scrub(f"[pages: {got}. The next page is {nxt}]", redact=True)
    last.warnings = list(last.warnings or []) + note.findings
    last.text = (last.text or "").rstrip() + f"\n\n{note.text}"


_MAX_ITEMS = 300
# Both markdown list shapes the extractor emits: unordered "- [" and ordered
# "1. [". Matching only the unordered form counted every ordered list as zero
# rows, so --items walked the whole page cap and reported nothing.
_ITEM_LINE = re.compile(r"(?m)^(?:-|\d+\.)\s+\[")
# A table-shaped feed (Discourse's /latest, a forum index, a ranking) extracts
# to one pipe row per item, not to a list. Matching only list lines counted
# every one of those rows as zero, so `--items` and the user's ceiling never
# saw a row, and the walk ran to the page cap. A row counts when it carries a
# link: the header and the `| --- |` rule do not, and a table of plain data is
# not a list of things to open.
_TABLE_ROW = re.compile(r"(?m)^[ \t]*\|[^\n]*\]\(https?://")
# A link target on a row: with the row's words, its identity across the scroll
# and the pages that follow it (see _row_key).
_ROW_LINK = re.compile(r"\]\((https?://[^)\s]+)\)")
#: A list marker with nothing after it on its line: a card list writes "- " on
#: one line and the title with its link on the next.
_BARE_MARKER = re.compile(r"(?:-|\d+\.)\s*$")


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


def _note_walk_repeated(page: "FetchResult", pages: int) -> None:
    """Say that pages served a copy of a page the walk had already read.

    The pages are still returned: the walk read them and the caller asked for
    pages, not for pages that differ. The note is there so a reader can tell
    that the site sent the same copy more than once.

    Scrubbed for the same reason as :func:`_note_walk_stopped`: the note lands
    after _finalize, so nothing scans it.
    """
    from searchts import sanitize

    note = sanitize.scrub(
        f"[read: {pages} page{'s' if pages != 1 else ''} served the same content "
        "as a page already read]",
        redact=True,
    )
    page.warnings = list(page.warnings or []) + note.findings
    page.text = (page.text or "").rstrip() + f"\n\n{note.text}"


def item_count(text: str) -> int:
    """Index rows already rendered as markdown links."""
    text = text or ""
    return len(_ITEM_LINE.findall(text)) + len(_TABLE_ROW.findall(text))


def _row_key(line: str) -> tuple:
    """What makes a row the same row: every link on it, and its words.

    The first link alone is not enough. A table whose first column is an author
    or a category puts the same link at the head of many distinct rows, and one
    seen row then took every later row that shared it. The whole line is too
    much: reply, view and age columns drift between the scroll and the page
    walk, and a row that only changed its count is still the same row. So the
    key is all the row's link targets plus its words, with every token that
    carries a digit (a count, an age, ``2h``, ``1.2k``) left out.
    """
    links = tuple(_ROW_LINK.findall(line))
    words = tuple(
        t
        for t in re.split(r"[\s|\[\]()]+", _ROW_LINK.sub("]", line))
        if t and not any(c.isdigit() for c in t)
    )
    return links, words


def _row_keys(text: str) -> set:
    """The key of every row in ``text``, for :func:`_drop_repeated_rows`."""
    keys = set()
    for line in (text or "").splitlines():
        if (_ITEM_LINE.match(line) or _TABLE_ROW.match(line)) and _ROW_LINK.search(line):
            keys.add(_row_key(line))
    return keys


def _drop_repeated_rows(text: str, seen: set) -> str:
    """``text`` without the rows already in ``seen`` or repeated inside it.

    A list row drags its indented byline and snippet lines with it; a table row
    is one line. A card list writes the marker on one line and the title with
    its link on the next, and that pair is one row. A row the page handed back
    twice is a repeat the same way a row from an earlier page is one: the first
    copy is the one that stays, so the caller gets every row once and the count
    note matches the text. ``seen`` itself is never changed: the key of each row
    this text keeps is remembered in a local copy of it. Everything that is not
    a repeated row stays byte for byte.
    """
    local: set = set(seen or ())
    out: List[str] = []
    lines = (text or "").splitlines()
    skipping = False
    for i, line in enumerate(lines):
        is_row = bool(_ITEM_LINE.match(line) or _TABLE_ROW.match(line))
        if is_row:
            # Every row line is checked, including the row that follows a
            # card. The card's link line is indented, so it is not a row
            # line, and a flag remembered on the marker would still be set
            # here and would let this row skip the check.
            if _ROW_LINK.search(line):
                key = _row_key(line)
                if key in local:
                    skipping = True
                    continue
                # Each row that stays has its key remembered, so a copy of it
                # later on this page is dropped with the first one kept.
                local.add(key)
            skipping = False
        elif _BARE_MARKER.match(line):
            # A card row: "- " on this line, the title and its link on the
            # next. The pair is one row and the key is on the second line.
            # That line does not itself match a row, so the key is recorded
            # here, and the next real row line is checked against it.
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if _ROW_LINK.search(nxt):
                key = _row_key(nxt)
                if key in local:
                    skipping = True
                    continue
                local.add(key)
                skipping = False
            else:
                skipping = False
        elif line.strip() and not line.startswith((" ", "\t")):
            skipping = False
        if skipping:
            continue
        out.append(line)
    return "\n".join(out)


def _row_key_lines(text: str) -> List[str]:
    """The line that holds each row's link, one per row, in the order they come.

    A row is what :func:`item_count` counts: a list marker with a link after
    it, or a table row that carries a link. The link is often on the line
    *after* the marker (a card list writes "- " on one line and the title on
    the next), so a row is a span and not a line, and the line that holds the
    link is the one that identifies it.
    """
    lines: List[str] = []
    for pattern in (_ITEM_LINE, _TABLE_ROW):
        for match in pattern.finditer(text or ""):
            start = text.rfind("\n", 0, match.end()) + 1
            end = text.find("\n", match.end())
            lines.append(text[start : len(text) if end < 0 else end])
    return lines


def _row_count(text: str, seen: set) -> Tuple[int, int, set]:
    """(new rows, repeated rows, the keys the new rows had) in ``text``.

    The rows are the ones :func:`item_count` counts, so the count of a page
    that has no repeats is the count it always was. What is new here is that
    a row the walk has already read is counted once.

    A row is keyed by the links and the words on the line that holds its link
    (the scroll path's rule), so the same row on two pages is one row. A row
    with no link at all cannot be told apart from another row with no link,
    so it counts as new: a count that dropped rows it cannot identify would
    be short of the truth the other way.
    """
    new = 0
    repeated = 0
    fresh: set = set()
    for line in _row_key_lines(text):
        if _ROW_LINK.search(line):
            key = _row_key(line)
            if key in seen or key in fresh:
                repeated += 1
                continue
            fresh.add(key)
        new += 1
    return new, repeated, fresh


def _rows_added(
    result: "FetchResult", seen_rows: set, seen_index: set
) -> Tuple[int, int, set]:
    """(new rows, repeated rows, the keys the new rows had) in this read.

    A known host can name every row it added (``FetchResult.index_keys``), and a
    site's own cursor sometimes hands back a row the previous window had, so the
    count is of *new* rows. Without keys it is the markdown row count, which is
    what every read that was not produced by a host with its own cursor has
    always used.

    A generic page counts its rows by key now, the way the scroll path does, so
    a next page that serves rows the previous page already had is not counted
    as more of the list. A count that included them would claim to have read
    more of the list than it did, which is the same lie the known-host path
    already refused to tell.
    """
    if result.index_keys is not None:
        added = 0
        repeated = 0
        fresh: set = set()
        for key in result.index_keys:
            if key in seen_index or key in fresh:
                repeated += 1
                continue
            fresh.add(key)
            added += 1
        return added, repeated, fresh
    return _row_count(result.text, seen_rows)


def _own_text(result: "FetchResult") -> str:
    """The page's own text, without the notes this pass appended to it.

    The notes are ours, not the page's: the next-page line names the URL we
    are about to fetch, so two copies of the same page never read the same
    while those lines are still on them.
    """
    text = (result.text or "").rstrip()
    for block in (
        "\n".join(result.extra_notes or []),
        "\n".join(
            str(m.get("note") or "") for m in (result.more or []) if isinstance(m, dict)
        ),
    ):
        if block and text.endswith(block):
            text = text[: -len(block)].rstrip()
    return text


def _page_fingerprint(result: "FetchResult") -> frozenset:
    """The page's own copy, in a form two copies of the same page share.

    The lines, without the notes this pass appended: the next-page line
    names the URL we are about to fetch, so two copies of one page never read
    the same while those lines are still on them.
    """
    text = _own_text(result)
    return frozenset(line.strip() for line in text.splitlines() if line.strip())


def read_items(url: str, items: int = _MAX_ITEMS, **kwargs) -> List[FetchResult]:
    """Follow next-page links until ``items`` list rows, curl only after the first.

    The ceiling is the user's (``SEARCHTS_MAX_ITEMS``, or a ``more:`` block in
    the config) and never above 300. A request over the ceiling is clamped and
    the read says so, on the page the caller reads.

    F23c: when the next-page walk comes up short and the browser is installed,
    the same URL is opened in the stealth Chromium and scrolled. See
    :mod:`searchts.scroll` for the loop and why each rule is there. The scroll
    runs on the *original* URL, not on a next-page URL: a feed is the feed's
    own page, and scrolling page 3 of a static list adds nothing.
    """
    from searchts import knobs
    from searchts.progress import note as progress_note
    from searchts.progress import wanted as progress_wanted

    # `pages` is the user's ceiling here, never something the caller asked
    # for: passing the product cap as a request made any lower ceiling look
    # like a clamp and printed "[pages: asked for 5 ...]" on a read that never
    # mentioned pages.
    limits = knobs.resolve(items=items)
    want = limits.items
    asked = max(1, int(items or 1))
    seen = set()
    # Row keys are a different namespace from page URLs: one set for both let a
    # row whose key was a later page's URL end the walk as a "loop".
    seen_rows: set = set()
    # A known host names its rows; a generic page is keyed by the scroll path's
    # rule. Two namespaces, because a row key and a post id are not the same
    # thing and one set for both let a row's key collide with a host's id.
    seen_index: set = set()
    out: List[FetchResult] = []
    current = url
    got = 0
    repeats = 0
    feed_repeats = 0
    broke = False
    looped = False
    # Pages whose every row was a row the walk had already read.
    repeated_pages = 0
    fetched = 0
    last_next = ""
    show_progress = progress_wanted(kwargs.get("progress"))
    for i in range(limits.pages):
        if show_progress and i:
            progress_note(f"reading page {i + 1}…")
        key = current.split("#", 1)[0].rstrip("/")
        if key in seen:
            # The cursor pointed at a page this walk already read. A list that
            # never grows is the one case where a second pass cannot help, and
            # saying so is the difference between "asked 300, got 11" and a lie
            # about the list ending there.
            looped = True
            break
        seen.add(key)
        call = dict(kwargs)
        if i:
            call["backends"] = ["curl_cffi"]
            call["allow_human"] = False
        elif not call.get("backends"):
            # F23c: a rows-first read wants the page's markup. The relay returns
            # markdown with no `role=feed`, no "Load more" control and no row
            # markup, so a relay win is both uncountable and unscannable for a
            # feed. It moves last rather than off the ladder: when the DOM
            # rungs cannot read the page, a relay win still beats no read.
            #
            # Domain memory is off for this page too, and the reason is the same
            # one. A pin records "the best rung for this domain is X", which is a
            # claim about getting *text*. A rows-first read needs the page's own
            # markup, and a pin that answers a different question must not decide
            # it. Measured: with meta.discourse.org pinned to the relay from an
            # earlier read, `--items 90` came back with 83 rows of relay markdown
            # and no scroll, because the pin outranked the intent.
            call["backends"] = _markup_first(call.get("backends"))
            call["use_memory"] = False
        try:
            result = fetch(current, **call)
        except UnlockerError as e:
            # F5f: see ``read_pages``. One known host can refuse a curl hop for
            # a reason a browser does not share, and a row count that stops at
            # the first window is the quiet failure this whole feature is for.
            retry = _retry_hop_on_browser(current, e, call) if i else None
            if retry is not None:
                result = retry
            else:
                if i == 0 or _is_refusal(e):
                    raise
                _note_walk_stopped(out[-1], current, e)
                broke = True
                break
        fetched += 1
        last_next = result.next_url or ""
        added, again, fresh = _rows_added(result, seen_rows, seen_index)
        rows_here = (
            len(result.index_keys) if result.index_keys is not None else item_count(result.text)
        )
        # The rows the previous pages had are the rows this page repeats, and
        # so is a second copy on this page. Both are dropped here, so each row
        # is returned once, in the place it came first. Page one runs it too:
        # the page itself can hand a row back twice, and the count note above
        # already said the second copy was not counted.
        result.text = _drop_repeated_rows(result.text, seen_rows)
        if result.index_keys is not None:
            seen_index |= fresh
            feed_repeats += again
        else:
            seen_rows |= fresh
            repeats += again
        got += added
        out.append(result)
        if rows_here and not added:
            # Every row on this page was a row we already had: the page serves
            # the same list again under another address. Its rows are not
            # counted twice, and the walk says the page was one it had read.
            repeated_pages += 1
        nxt = result.next_url
        if got >= want or not nxt:
            break
        # No pre-check on nxt, same as read_pages: fetch guards it and raises.
        current = nxt
    else:
        # Out of pages with more to read. Say so: otherwise asking for 300 rows
        # and getting 150 is indistinguishable from the list ending there.
        if out and got < want and last_next and not broke:
            _note_walk_capped(
                out[-1], fetched, asked, last_next,
                # `want` is the ceiling that applied, not the unclamped ask:
                # the clamp note on page one already names the difference.
                rows=f"{got} row{'s' if got != 1 else ''} of {want}" if got else "no rows",
            )
    if not out:
        return out
    last = out[-1]
    extra = ""
    if looped and got < want:
        # F5f. Reddit's own feed cursor (``/svc/shreddit/…?after=…``) hands back
        # a batch the walk has already read when the feed has stopped moving, and
        # a walk that stops there says nothing. Named on page one, with the count.
        extra += (
            f"\n\n[items: {got} new row{'s' if got != 1 else ''} of the {asked} asked for. The feed's own "
            "cursor pointed back at a page this walk had already read, so the "
            "walk stopped there; the rows it did not have were never served]"
        )
    if feed_repeats:
        # The feed cursor handed back rows we already had. Saying so is the whole
        # point of counting new rows: a count that included them would claim to
        # have read more of the list than it did. The ceiling itself is named by
        # ``_note_knobs`` below, on this same page.
        extra += (
            f"\n\n[items: {got} new row{'s' if got != 1 else ''}; "
            f"{feed_repeats} row{'s' if feed_repeats != 1 else ''} the feed handed "
            "back again, not counted twice]"
        )
    if repeats:
        # A next page handed back rows the previous page already had. Same
        # reason, same place: the count is of rows the walk had not read.
        extra += (
            f"\n\n[items: {got} new row{'s' if got != 1 else ''}; "
            f"{repeats} row{'s' if repeats != 1 else ''} the pages handed back again, "
            "not counted twice]"
        )
    if repeated_pages:
        # Pages whose every row was one we already had. Their rows are not
        # counted twice, and the walk says the page was one it had read.
        extra += (
            f"\n\n[items: {repeated_pages} page{'s' if repeated_pages != 1 else ''} "
            "served rows this walk had already read]"
        )
    if (
        not broke
        and got < want
        # The scroll is the *second* mechanism, so it is tried whenever the
        # first one did not deliver: the walk ended with no next URL, or it ran
        # out of pages with rows still coming. A page that has both (Discourse's
        # `latest` scrolls and also links `?page=N`) gets both, and asking for
        # more than the page cap can carry is exactly the case where the
        # second mechanism is the answer.
        and (not last.next_url or fetched >= limits.pages)
    ):
        # F23c: the list did not fill by following URLs, so try the other
        # mechanism. The probe inside decides whether this page even is a feed,
        # which is why nothing here asks whether the walk "looked like a list":
        # a virtualized feed (measured on reddit.com) marks itself with neither
        # `role=feed` nor a "Load more" control, and the probe is the only
        # thing that can tell.
        #
        # The gate is deliberately *not* "the winning rung held the markup". A
        # relay win means the local rungs could not read the page at all, which
        # is the case where a browser is most likely to, and the old gate left
        # that read short with nothing on it saying why.
        if kwargs.get("proxy") or kwargs.get("cookies"):
            # The scroll opens its own Chromium, which carries neither the
            # proxy nor the cookies this read was given. Running it anyway sends
            # the user's real address to a site they routed around, and swaps an
            # authenticated page for an anonymous one. Say so instead.
            carried = "proxy" if kwargs.get("proxy") else "cookies"
            note, rep = (
                f"[scroll: not run. This read carries a {carried} and the "
                "scroll opens its own browser, which would not use it. Read "
                "the feed without it to scroll]"
            ), None
        else:
            # The scroll starts at the top of the feed, so it is asked for the
            # rows wanted in all, not for what the page walk left over: it
            # re-reads the rows the walk already has, and asking for the
            # remainder ended it early or handed back rows the walk repeated.
            note, rep = _scroll_feed(
                url, want, limits,
                relay_only=not _has_markup(out[0]),
                progress=kwargs.get("progress"),
            )
        if note:
            extra += f"\n\n{note}"
        if rep is not None and rep.stop != "not-a-feed" and rep.html:
            out[0] = _scrolled(out[0], rep, url, kwargs)
            # The scrolled page one is the feed from the top, so the later
            # pages of the walk (the same feed, a window further down) repeat
            # its rows. Each row is returned once, in the place it came first.
            seen = _row_keys(out[0].text)
            for later in out[1:]:
                later.text = _drop_repeated_rows(later.text, seen)
                seen |= _row_keys(later.text)
    if extra:
        first = out[0]
        first.text = (first.text or "").rstrip() + extra
    _note_knobs(out[0], limits)
    return out


def _scrolled(old: "FetchResult", rep, url: str, kwargs: Dict[str, Any]) -> "FetchResult":
    """The same page, with every row the scroll ever saw put back in.

    The collected HTML replaces the rung's, so the rows that unmounted on the
    way down are in the extract again. Re-extracting and re-running detection
    through :func:`_finalize` is the point: this is one read path with a longer
    page, not a second reader that knows about feeds.

    Only the *first* page is replaced. A feed is the feed's own URL; the
    later pages of a next-page walk are static lists of the same collection and
    have nothing to scroll.
    """
    text = html_to_text(rep.html, url)
    # The same known-host ring the rungs run, so a host with its own row format
    # (Reddit's F5e cards) still gets it - but only when it reads more. The ring
    # picks one known container, and a page the scroll rebuilt is a different
    # shape from the one it was written against, so on reddit.com the card
    # extractor returned a single post while the generic extract had all 24.
    try:
        from searchts.known_hosts import reddit as _ring

        hit = _ring.extract_from_html(url, rep.html)
    except Exception:  # noqa: BLE001 - the ring is fail-open, always
        hit = None
    if hit and len(hit[1]) > len(text):
        text = hit[1]
    result = FetchResult(
        backend=f"scroll:{old.backend}",
        text=text,
        status=old.status,
        final_url=old.final_url or url,
        headers=dict(old.headers or {}),
        authenticated=old.authenticated,
        page_html=rep.html,
    )
    from searchts.more import resolve_media_limit

    media_limit, media_clamp = resolve_media_limit(kwargs.get("media"))
    return _finalize(
        result, bool(kwargs.get("scrub")),
        media_limit=media_limit, media_clamp=media_clamp,
    )


def _markup_first(backends: Optional[List[str]]) -> Optional[List[str]]:
    """The default ladder with the relay moved to the end."""
    order = list(backends if backends is not None else DEFAULT_BACKENDS)
    relay = [b for b in order if b == "Jina Reader"]
    rest = [b for b in order if b != "Jina Reader"]
    return rest + relay if relay else rest


def _has_markup(page: "FetchResult") -> bool:
    """True when this result came from a rung that had the page's own markup.

    The relay is the only rung that does not, and a markdown answer from it
    cannot be scanned for a feed, so it is not a page the scroll pass could
    have grown. Only used to *word* the note: the scroll itself opens the URL
    in the browser and needs nothing from this result.
    """
    return "jina" not in (page.backend or "").lower()


def _scroll_feed(url: str, want: int, limits, *,
                  relay_only: bool = False,
                  progress: Optional[bool] = None) -> Tuple[str, Any]:
    """Scroll ``url`` for ``want`` more rows: ``(note, report)``.

    Every outcome is a note, including "this is not a feed": the caller asked
    for rows it did not get, and the difference between "the page stopped
    growing", "a login wall replaced the page" and "you have no browser
    installed" is exactly what makes the answer actionable. The report is
    ``None`` unless there is collected HTML worth reading.

    ``relay_only`` says the read that came back was the Jina relay's markdown
    and not the page's own markup. That changes only the wording, and only when
    there is no browser to scroll with: the relay's markdown is what the caller
    has, so saying "install a browser" without saying why the relay could not
    help would leave the obvious question open.
    """
    from searchts import scroll
    from searchts.progress import announce
    from searchts.progress import phase as progress_phase
    from searchts.progress import wanted as progress_wanted

    show = progress_wanted(progress)

    def say(msg: str) -> None:
        announce(msg)

    if not scroll.browser_available():
        if relay_only:
            return (
                "[scroll: this read came from the Jina relay, which returns "
                "markdown and cannot be scrolled for more rows, and no browser "
                "is installed to read the list itself. Run: "
                "searchts install --browser]"
            ), None
        return scroll.NO_BROWSER, None
    with progress_phase("scrolling the page for more rows…", enabled=show):
        rep, why = scroll.collect_url(
            url, want_rows=want, max_clicks=limits.expand_clicks,
            budget_seconds=limits.seconds, step_ms=limits.step_ms,
            empty_steps=limits.empty_steps, persistent=True,
            tick=say if show else None,
        )
    if rep is None:
        if why == "no-browser":
            return scroll.NO_BROWSER, None
        return f"[scroll: could not open the list in the browser ({why})]", None
    if rep.stop == "not-a-feed":
        return ("[scroll: the page did not grow when scrolled, so it has no "
                "more rows behind a scroll]"), None
    return rep.note(), rep
