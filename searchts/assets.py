# -*- coding: utf-8 -*-
"""On-demand asset + design-inspiration grabber.

Point it at a URL and it can:
  - download a single asset (image, PDF, font, CSS, anything) as raw bytes, or
  - "grab" a whole page: enumerate its assets (images/icons/css/fonts/svg),
    download them, extract a color palette + the fonts in use, and optionally
    read the page text.

Everything goes through the SAME escalating unlock ladder the reader uses:
``curl_cffi`` (browser TLS/JA3 fingerprint) first, then a lazy patchright
stealth browser when the fingerprinted fetch is blocked -- so assets behind
fingerprint-gated CDNs / Cloudflare come through, not just open ones.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from searchts.progress import phase as progress_phase
from searchts.ssrf import guard_mcp_url, private_hop
from searchts.unlocker import _UA_REAL, jina_enabled, looks_blocked, normalize


def _tick(progress: bool, msg: str) -> None:
    # Best-effort only: a closed/broken stderr must never abort a fetch/grab.
    # Routed through progress.py so a terminal gets a live ladder and a pipe
    # gets the same plain lines this function always printed.
    from searchts import progress as _progress

    _progress.tick(progress, msg)


def _progress_default(progress: Optional[bool]) -> bool:
    """Resolve a tri-state progress flag; None follows SEARCHTS_PROGRESS=1."""
    if progress is None:
        return os.environ.get("SEARCHTS_PROGRESS", "") in ("1", "true", "True", "yes")
    return progress


#: Asset fetch ladder: cheap fingerprinted GET, then the stealth browser.
DEFAULT_ASSET_BACKENDS: List[str] = ["curl_cffi", "stealth-browser"]

_TEXTUAL_CT = ("text/html", "application/xhtml", "text/xml", "application/xml")


@dataclass
class AssetResult:
    content: bytes
    content_type: str
    final_url: str
    backend: str


@dataclass
class AssetError(Exception):
    url: str
    attempts: List[Tuple[str, str]] = field(default_factory=list)

    def __str__(self) -> str:
        rungs = "; ".join(f"{b}: {why}" for b, why in self.attempts)
        return f"could not fetch {self.url} -> {rungs}"


# ── raw byte fetch through the unlock ladder ─────────────────────────────────

def _fetch_bytes_curl(url: str, timeout: int) -> AssetResult:
    from curl_cffi import requests as cr

    from searchts.ssrf import curl_resolve_options, curl_safe_redirects

    r = cr.get(url, impersonate="chrome", timeout=timeout,
               allow_redirects=curl_safe_redirects(),
               curl_options=curl_resolve_options(url),
               headers={"Accept-Language": "en-US,en;q=0.9"})
    final = str(getattr(r, "url", None) or url)
    hop = private_hop(url, final)
    if hop:
        raise AssetError(url, [("curl_cffi", hop)])
    if r.status_code >= 400:
        raise AssetError(url, [("curl_cffi", f"http-{r.status_code}")])
    ct = r.headers.get("content-type", "") or ""
    content = r.content or b""
    # Only HTML/text can be a challenge page; binary 200s are real bytes.
    if any(t in ct.lower() for t in _TEXTUAL_CT) or not ct:
        reason = looks_blocked(r.status_code, content.decode("utf-8", "replace"))
        if reason:
            raise AssetError(url, [("curl_cffi", reason)])
    if not content:
        raise AssetError(url, [("curl_cffi", "empty-body")])
    return AssetResult(content, ct, final, "curl_cffi")


def _fetch_bytes_stealth(url: str, timeout: int) -> AssetResult:
    """Fetch bytes with a lazy undetected Chromium (patchright).

    First tries the browser's request context (rides its fingerprint + any
    challenge-clearance cookies); if that is blocked and the target is an HTML
    page, falls back to a real navigation so a managed JS challenge can resolve.
    """
    try:
        from patchright.sync_api import sync_playwright
    except ImportError as e:  # pragma: no cover - environment dependent
        raise AssetError(url, [("stealth-browser",
                                'needs patchright: pip install "searchts[browser]"')]) from e

    from searchts.ssrf import chromium_pin_args, guard_browser_page
    ms = int(timeout * 1000)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=chromium_pin_args(url))
        try:
            ctx = browser.new_context(user_agent=_UA_REAL, locale="en-US",
                                      viewport={"width": 1280, "height": 800})
            guard_browser_page(ctx, url)
            resp = ctx.request.get(url, timeout=ms)
            if resp.ok:
                body = resp.body()
                ct = (resp.headers or {}).get("content-type", "") or ""
                # An empty content-type can still be a challenge; an empty body is
                # never real content (a flagged WAF answers 2xx with no body).
                textual = any(t in ct.lower() for t in _TEXTUAL_CT) or not ct
                blocked = textual and looks_blocked(resp.status, body.decode("utf-8", "replace"))
                if body and not blocked:
                    hop = private_hop(url, resp.url)
                    if hop:
                        raise AssetError(url, [("stealth-browser", hop)])
                    return AssetResult(body, ct, resp.url, "stealth-browser")
            # HTML page still walled: navigate so a JS challenge can clear.
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=ms)
            waited = 0
            html = page.content()
            # Wait until the challenge clears AND real content has rendered. A
            # too-thin page is an unresolved interstitial / CAPTCHA (e.g. AWS WAF
            # rate-limiting rapid hits), NOT content -- never accept it as success.
            # Match read's threshold (500 chars) so grab doesn't reject pages read accepts.
            while waited < 25000 and (looks_blocked(200, html) == "challenge" or len(html) < 500):
                page.wait_for_timeout(1500)
                waited += 1500
                try:
                    html = page.content()
                except Exception:  # noqa: BLE001
                    break
            if looks_blocked(200, html) is None and len(html) >= 500:
                hop = private_hop(url, page.url)
                if hop:
                    raise AssetError(url, [("stealth-browser", hop)])
                return AssetResult(html.encode("utf-8"), "text/html", page.url, "stealth-browser")
            raise AssetError(url, [("stealth-browser", "challenge unsolved or thin content")])
        finally:
            browser.close()


def _fetch_bytes_jina_html(url: str, timeout: int) -> AssetResult:
    """Fetch a page's rendered HTML through the keyless Jina Reader relay.

    Jina runs the page (incl. JS challenges like AWS WAF / Cloudflare) and can
    return raw HTML via ``X-Return-Format: html`` -- which keeps the asset tags
    we need to enumerate. Page-only: not meaningful for a binary asset.
    """
    import requests

    r = requests.get("https://r.jina.ai/" + url, timeout=timeout,
                     headers={"User-Agent": _UA_REAL, "X-Return-Format": "html",
                              "Accept-Language": "en-US,en;q=0.9"})
    if r.status_code >= 400:
        raise AssetError(url, [("jina-html", f"http-{r.status_code}")])
    html = r.text or ""
    reason = looks_blocked(r.status_code, html)
    if reason or len(html) < 500:
        raise AssetError(url, [("jina-html", reason or "thin")])
    return AssetResult(html.encode("utf-8"), "text/html", url, "jina-html")


def fetch_bytes(url: str, *, backends: Optional[List[str]] = None,
                timeout: int = 30, progress: Optional[bool] = None) -> AssetResult:
    """Fetch raw bytes for `url`, escalating through the unlock ladder.

    Same SSRF boundary as ``unlocker.fetch``: every URL is checked before any
    rung connects, including each asset URL ``grab`` pulls out of a page (an
    ``<img src="http://169.254.169.254/...">`` must not become a fetch).
    """
    progress = _progress_default(progress)
    try:
        url = normalize(url)
    except ValueError as e:
        raise AssetError(url, [("normalize", str(e))]) from e
    blocked = guard_mcp_url(url, resolve_dns=True)
    if blocked:
        why = blocked[7:] if blocked.startswith("Error: ") else blocked
        raise AssetError(url, [("ssrf", why)])
    order = list(backends or DEFAULT_ASSET_BACKENDS)
    if not jina_enabled():
        order = [b for b in order if b != "jina-html"]
    attempts: List[Tuple[str, str]] = []
    for backend in order:
        with progress_phase(f"trying {backend}…", enabled=bool(progress)):
            try:
                if backend == "curl_cffi":
                    return _fetch_bytes_curl(url, timeout)
                if backend == "jina-html":
                    return _fetch_bytes_jina_html(url, timeout)
                if backend == "stealth-browser":
                    return _fetch_bytes_stealth(url, timeout)
                attempts.append((backend, "unknown-backend"))
            except AssetError as e:
                attempts.extend(e.attempts or [(backend, "failed")])
            except Exception as e:  # noqa: BLE001 - any backend failure escalates
                attempts.append((backend, f"{type(e).__name__}: {e}"))
    raise AssetError(url, attempts)


# ── saving a single asset ────────────────────────────────────────────────────

_BAD_FN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def guess_filename(url: str, content_type: str = "",
                   content_disposition: Optional[str] = None) -> str:
    """Derive a safe, extensioned filename for a fetched asset."""
    name = ""
    if content_disposition:
        m = re.search(r'filename\*?=(?:[^\']*\'\')?["\']?([^"\';]+)', content_disposition)
        if m:
            name = urllib.parse.unquote(m.group(1))
    if not name:
        path = urllib.parse.urlparse(url).path
        name = path.rsplit("/", 1)[-1]
    name = name.split("?")[0].split("#")[0].strip()
    name = _BAD_FN.sub("_", name).lstrip(".") or ""
    if not name:
        import hashlib
        name = "asset-" + hashlib.sha1(url.encode()).hexdigest()[:10]
    if "." not in name:
        import mimetypes
        ext = mimetypes.guess_extension((content_type or "").split(";")[0].strip()) or ""
        name += ext
    return name[:120]


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix, i = path.stem, path.suffix, 1
    while True:
        cand = path.with_name(f"{stem}-{i}{suffix}")
        if not cand.exists():
            return cand
        i += 1


def get_asset(url: str, out_path: Optional[str] = None, *, timeout: int = 30,
              progress: Optional[bool] = None, overwrite: bool = True) -> Path:
    """Download one asset to disk; return the saved path.

    ``overwrite=False`` never replaces an existing file: the name gets a
    ``-1``, ``-2`` … suffix instead (the MCP tool uses this).
    """
    progress = _progress_default(progress)
    with progress_phase("fetching asset…", enabled=bool(progress)):
        res = fetch_bytes(url, timeout=timeout, progress=progress)
    if out_path:
        dest = Path(out_path)
        if dest.is_dir():
            dest = dest / guess_filename(res.final_url, res.content_type)
    else:
        dest = Path(guess_filename(res.final_url, res.content_type))
    if not overwrite:
        dest = _unique_path(dest)
    if dest.parent and not dest.parent.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
    with progress_phase("saving asset…", enabled=bool(progress)):
        dest.write_bytes(res.content)
    return dest


# ── HTML asset enumeration ───────────────────────────────────────────────────

ASSET_KINDS = ("images", "icons", "css", "fonts", "svg", "scripts", "inline_svg")


_FONT_DATA_PREFIXES = (
    "data:font/",
    "data:application/font",
    "data:application/vnd.ms-fontobject",
    "data:application/x-font",
)


def _parse_srcset(srcset: str) -> List[str]:
    """Pull every URL out of a srcset, descriptors and data URI commas included.

    A naive ``split(",")`` cuts a ``data:`` URI in half at its own comma. Scan
    URL tokens (which never contain whitespace) and skip each descriptor
    (``1x`` / ``640w``) up to the next comma instead.
    """
    urls: List[str] = []
    i, n = 0, len(srcset)
    while i < n:
        while i < n and srcset[i] in " \t\r\n,":
            i += 1
        if i >= n:
            break
        start = i
        while i < n and not srcset[i].isspace():
            i += 1
        candidate = srcset[start:i].rstrip(",")
        if candidate:
            urls.append(candidate)
        while i < n and srcset[i] != ",":
            i += 1
    return urls


def extract_assets(html: str, base_url: str) -> Dict[str, List[str]]:
    """Enumerate a page's assets as absolute URLs, grouped by kind."""
    out: Dict[str, List[str]] = {k: [] for k in ASSET_KINDS}

    def add(kind: str, href: Optional[str]) -> None:
        if not href:
            return
        u = urllib.parse.urljoin(base_url, href.strip().strip('\'"'))
        low = u.lower()
        # A data URI carries its bytes in the page; save it directly rather
        # than pretend it is a URL to fetch. Images and fonts are worth it.
        if not (low.startswith(("http://", "https://"))
                or low.startswith("data:image/")
                or low.startswith(_FONT_DATA_PREFIXES)):
            return
        if u not in out[kind]:
            out[kind].append(u)
        if low.startswith("data:"):
            return
        if u.split("?")[0].lower().endswith(".svg") and u not in out["svg"]:
            out["svg"].append(u)

    def add_srcset(kind: str, srcset: str) -> None:
        if not srcset:
            return
        for url_part in _parse_srcset(srcset):
            add(kind, url_part)

    try:
        import lxml.etree as ET
        import lxml.html as LH
        doc = LH.fromstring(html)
        # <img> with src, srcset, data-src, data-srcset
        for el in doc.iter("img"):
            add("images", el.get("src"))
            add("images", el.get("data-src"))
            ss = el.get("srcset")
            if ss:
                add_srcset("images", ss)
            dss = el.get("data-srcset")
            if dss:
                add_srcset("images", dss)
        # <picture> > <source srcset>
        for el in doc.iter("picture"):
            for source in el.iter("source"):
                ss = source.get("srcset")
                if ss:
                    add_srcset("images", ss)
                src = source.get("src")
                if src:
                    add("images", src)
                dss = source.get("data-srcset")
                if dss:
                    add_srcset("images", dss)
        # <video poster>
        for el in doc.iter("video"):
            add("images", el.get("poster"))
            for source in el.iter("source"):
                add("images", source.get("src"))
        # <source> outside picture/video
        for el in doc.iter("source"):
            ss = el.get("srcset") or el.get("src")
            if ss:
                add_srcset("images", ss)
        # meta tags for social images
        for el in doc.iter("meta"):
            prop = (el.get("property") or el.get("name") or "").lower()
            if prop in ("og:image", "og:image:url", "twitter:image", "twitter:image:src"):
                add("images", el.get("content"))
        # <link> for stylesheets, icons, fonts, preload
        for el in doc.iter("link"):
            rels = (el.get("rel") or "").lower().split()
            href = el.get("href")
            if "stylesheet" in rels:
                add("css", href)
            if any(r in rels for r in ("icon", "shortcut", "apple-touch-icon", "mask-icon", "fluid-icon")):
                add("icons", href)
            if (el.get("as") or "").lower() == "font":
                add("fonts", href)
            # preload images
            if "preload" in rels and (el.get("as") or "").lower() in ("image", "font"):
                add("images" if (el.get("as") or "").lower() == "image" else "fonts", href)
        # <script src>
        for el in doc.iter("script"):
            add("scripts", el.get("src"))
        # inline SVG elements - save as files
        for el in doc.iter("svg"):
            svg_html = ET.tostring(el, encoding="unicode")
            if svg_html:
                # Create a data URL for the inline SVG so it gets saved
                b64 = base64.b64encode(svg_html.encode("utf-8")).decode("ascii")
                data_url = f"data:image/svg+xml;base64,{b64}"
                add("inline_svg", data_url)
    except Exception:  # noqa: BLE001 - malformed HTML: fall back to regex
        for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)', html, re.I):
            add("images", m.group(1))
        for m in re.finditer(r'<img[^>]+data-src=["\']([^"\']+)', html, re.I):
            add("images", m.group(1))
        for m in re.finditer(r'<link[^>]+href=["\']([^"\']+\.css[^"\']*)', html, re.I):
            add("css", m.group(1))

    # inline background-image: url(...)
    for m in re.finditer(r"background(?:-image)?\s*:[^;}\"']*url\(([^)]+)\)", html, re.I):
        add("images", m.group(1))
    return out


# ── design tokens (palette + fonts) ──────────────────────────────────────────

_HEX = re.compile(r"#[0-9a-fA-F]{8}\b|#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")
_RGB = re.compile(r"rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)", re.I)
_HSL = re.compile(r"hsla?\(\s*([\d.]+)(?:deg)?[\s,]+([\d.]+)%[\s,]+([\d.]+)%", re.I)
_FONTFAM = re.compile(r"font-family\s*:\s*([^;{}]+)", re.I)
_CSS_VAR = re.compile(r"(--[\w-]+)\s*:\s*([^;{}]+)", re.I)
_GRADIENT_START = re.compile(r"(?:linear|radial|conic)-gradient\(", re.I)
_FONT_FACE = re.compile(r"@font-face\s*\{([^}]+)\}", re.I)
_GENERIC_FONTS = {"inherit", "initial", "unset", "serif", "sans-serif", "monospace",
                  "cursive", "fantasy", "system-ui", "ui-sans-serif", "ui-serif",
                  "ui-monospace", "-apple-system", "blinkmacsystemfont"}

# CSS property patterns for design tokens
_RADIUS = re.compile(r"border-radius\s*:\s*([^;{}]+)", re.I)
_SHADOW = re.compile(r"box-shadow\s*:\s*([^;{}]+)", re.I)
_SPACING = re.compile(r"(margin|padding|gap)\s*:\s*([^;{}]+)", re.I)
#: Selectors whose colors are what a person actually sees: page chrome, links,
#: buttons and headings. A color that only appears in a reset or a utility class
#: still counts, but it does not outrank the brand.
_SEMANTIC_SELECTOR = re.compile(
    r"(?:^|[,{}\s])(?:html|body|a|button|h[1-6])\b"
    r"|(?:^|[\s,.#\[])(?:btn|button|cta|link|heading|brand|primary|accent)[\w-]*",
    re.I,
)
_SEMANTIC_VAR = re.compile(r"--[\w-]*(?:brand|primary|accent|link|heading|button|cta)[\w-]*\s*:", re.I)
_CSS_BLOCK = re.compile(r"([^{}]+)\{([^{}]*)\}")
#: Radius, shadow and spacing are a design kit, not a dump of every declaration.
#: This many values is the default projection. A caller who needs the rest raises
#: it with ``--tokens`` / ``max_tokens``, up to ``_TOKEN_CAP_MAX``. One-off
#: lengths past the chosen cap are named, not appended forever.
_TOKEN_CAP = 24
_TOKEN_CAP_MAX = 200
#: A ``gap:`` or ``margin:`` match on raw HTML can run until the next brace.
#: A real token is a short declaration. Markup is not.
_TOKEN_VALUE_MAX = 160
_TOKEN_LISTS = ("radius", "shadow", "spacing")


def resolve_token_cap(value: int) -> int:
    """The radius/shadow/spacing cap, or ``ValueError`` when it is out of range.

    ``0`` keeps nothing. The ceiling is ``_TOKEN_CAP_MAX``: past that the list
    is a dump again. A bool is not an integer here (``True`` would be ``1``).
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"token cap must be an integer from 0 to {_TOKEN_CAP_MAX}, got {value!r}"
        )
    if value < 0 or value > _TOKEN_CAP_MAX:
        raise ValueError(
            f"token cap must be from 0 to {_TOKEN_CAP_MAX}, got {value}"
        )
    return value


def _token_value(raw: str) -> Optional[str]:
    """Return ``raw`` when it is a token value, else None."""
    val = " ".join((raw or "").split())
    if not val or len(val) > _TOKEN_VALUE_MAX:
        return None
    if any(ch in val for ch in "<>{}"):
        return None
    return val


def _tokens_more(cap: int, over: Dict[str, int]) -> Optional[str]:
    """How a caller gets the real values this cap hid, or None when none were."""
    if not over:
        return None
    parts = ", ".join(f"{n} more {kind}" for kind, n in over.items())
    return (
        f"kept {cap} per list; {parts}; "
        f"--tokens N (MCP max_tokens) raises it, ceiling {_TOKEN_CAP_MAX}"
    )


def _cap_token_lists(
    tokens: Dict[str, List[str]], cap: int,
) -> Tuple[Dict[str, List[str]], Dict[str, int], Optional[str]]:
    """Cap radius, shadow and spacing. Count what was left out.

    Markup that is not a token is counted in the omission and is not offered
    back: raising the cap cannot turn it into a value. Real values past ``cap``
    are named in the ``tokens_more`` sentence.
    """
    omitted: Dict[str, int] = {}
    over: Dict[str, int] = {}
    capped: Dict[str, List[str]] = dict(tokens)
    for key in _TOKEN_LISTS:
        kept: List[str] = []
        rejected = 0
        past = 0
        for raw in tokens.get(key) or []:
            val = _token_value(raw)
            if val is None:
                rejected += 1
                continue
            if val in kept:
                continue
            if len(kept) >= cap:
                past += 1
                continue
            kept.append(val)
        capped[key] = kept
        if rejected or past:
            omitted[key] = rejected + past
        if past:
            over[key] = past
    return capped, omitted, _tokens_more(cap, over)


def _norm_hex(h: str) -> str:
    h = h.lower()
    if len(h) == 4:  # #rgb -> #rrggbb
        h = "#" + "".join(c * 2 for c in h[1:])
    if len(h) == 9:  # #rrggbbaa -> drop alpha for palette grouping
        h = h[:7]
    return h


def _rgb_to_hex(r: float, g: float, b: float) -> str:
    return "#%02x%02x%02x" % (max(0, min(255, int(round(r)))),
                              max(0, min(255, int(round(g)))),
                              max(0, min(255, int(round(b)))))


def _hsl_to_hex(h: float, s: float, lum: float) -> str:
    s /= 100.0
    lum /= 100.0
    c = (1 - abs(2 * lum - 1)) * s
    hp = (h % 360) / 60.0
    x = c * (1 - abs(hp % 2 - 1))
    r = g = b = 0.0
    if hp < 1:
        r, g, b = c, x, 0
    elif hp < 2:
        r, g, b = x, c, 0
    elif hp < 3:
        r, g, b = 0, c, x
    elif hp < 4:
        r, g, b = 0, x, c
    elif hp < 5:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    m = lum - c / 2
    return _rgb_to_hex((r + m) * 255, (g + m) * 255, (b + m) * 255)


def _gradients_in(text: str) -> List[str]:
    """Full gradient calls, including nested color functions such as rgba()."""
    found: List[str] = []
    for m in _GRADIENT_START.finditer(text):
        i, depth = m.end(), 1
        while i < len(text) and depth:
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
            i += 1
        if depth == 0:
            grad = text[m.start():i].strip()
            if grad not in found:
                found.append(grad)
    return found


def _colors_in(text: str) -> set:
    """Every distinct color literal in a CSS declaration or SVG fragment."""
    found = {_norm_hex(m.group(0)) for m in _HEX.finditer(text)}
    for m in _RGB.finditer(text):
        try:
            found.add(_rgb_to_hex(float(m.group(1)), float(m.group(2)), float(m.group(3))))
        except ValueError:
            pass
    for m in _HSL.finditer(text):
        try:
            found.add(_hsl_to_hex(float(m.group(1)), float(m.group(2)), float(m.group(3))))
        except ValueError:
            pass
    return found


def extract_design(html: str, css_texts: Optional[List[str]] = None, *,
                   token_cap: int = _TOKEN_CAP) -> Dict:
    """Extract a color palette, the fonts in use, theme-color, and design tokens."""
    blobs = [html] + list(css_texts or [])
    colors: Counter = Counter()
    semantic: Counter = Counter()
    fonts: List[str] = []
    css_vars: Dict[str, str] = {}
    gradients: List[str] = []
    tokens: Dict[str, List[str]] = {
        "font_stacks": [],
        "radius": [],
        "shadow": [],
        "spacing": [],
    }

    for b in blobs:
        # Colors from hex, rgb, hsl
        for m in _HEX.finditer(b):
            colors[_norm_hex(m.group(0))] += 1
        for m in _RGB.finditer(b):
            try:
                colors[_rgb_to_hex(float(m.group(1)), float(m.group(2)), float(m.group(3)))] += 1
            except ValueError:
                pass
        for m in _HSL.finditer(b):
            try:
                colors[_hsl_to_hex(float(m.group(1)), float(m.group(2)), float(m.group(3)))] += 1
            except ValueError:
                pass
        # Font families
        for m in _FONTFAM.finditer(b):
            fam = m.group(1).split(",")[0].strip().strip('\'"')
            if (fam and fam.lower() not in _GENERIC_FONTS and fam not in fonts
                    and not fam.startswith(("$", "--")) and "var(" not in fam.lower()
                    and "<" not in fam and ">" not in fam
                    and not fam.lower().endswith(" fallback")):
                fonts.append(fam)
        # CSS variables (custom properties)
        for m in _CSS_VAR.finditer(b):
            var_name = m.group(1).strip()
            var_value = m.group(2).strip()
            if var_name not in css_vars:
                css_vars[var_name] = var_value
        # Gradients
        for grad in _gradients_in(b):
            if grad not in gradients:
                gradients.append(grad)
        # Font stacks (full font-family declarations)
        for m in _FONTFAM.finditer(b):
            stack = m.group(1).strip()
            if stack and stack not in tokens["font_stacks"]:
                tokens["font_stacks"].append(stack)
        # Border radius
        for m in _RADIUS.finditer(b):
            val = m.group(1).strip()
            if val and val not in tokens["radius"]:
                tokens["radius"].append(val)
        # Box shadow
        for m in _SHADOW.finditer(b):
            val = m.group(1).strip()
            if val and val not in tokens["shadow"]:
                tokens["shadow"].append(val)
        # Spacing (margin, padding, gap)
        for m in _SPACING.finditer(b):
            val = m.group(2).strip()
            if val and val not in tokens["spacing"]:
                tokens["spacing"].append(val)

    # Google Fonts <link href="...family=Roboto:...&family=Inter">
    for m in re.finditer(r"fonts\.googleapis\.com/css2?\?([^\"'> )]+)", html, re.I):
        for fm in re.finditer(r"family=([^&:]+)", m.group(1)):
            fam = urllib.parse.unquote_plus(fm.group(1)).split(":")[0].strip()
            if fam and fam not in fonts:
                fonts.append(fam)
    theme = None
    for m in re.finditer(r"<meta\b[^>]*>", html, re.I):
        tag = m.group(0)
        if not re.search(r'name=["\']theme-color["\']', tag, re.I):
            continue
        cm = re.search(r'content=["\']([^"\']+)', tag, re.I)
        if cm:
            theme = cm.group(1).strip()
            break
    if theme:
        for h in _colors_in(theme):
            colors[h] += 1
            semantic[h] += 100

    # Inline SVG fills and style attributes paint the page just as CSS does.
    for m in re.finditer(r"<svg\b[^>]*>.*?</svg>", html, re.I | re.S):
        for h in _colors_in(m.group(0)):
            semantic[h] += 2
    for m in re.finditer(r"""style\s*=\s*["']([^"']+)""", html, re.I):
        for h in _colors_in(m.group(1)):
            semantic[h] += 3

    # Prefer colors used on page chrome, links, buttons, headings and semantic
    # variables. Frequency alone puts a reset stylesheet's black and white on
    # top, which is not the brand a designer is looking for.
    for css in css_texts or []:
        for block in _CSS_BLOCK.finditer(css):
            selector = block.group(1).strip().lower()
            decls = block.group(2)
            boost = 0
            if selector == ":root" or selector.startswith(":root"):
                boost = 2
            elif re.search(r"(?:^|,)\s*(?:html|body)\b", selector):
                boost = 3
            if _SEMANTIC_SELECTOR.search(selector):
                boost = max(boost, 3)
            if boost:
                for h in _colors_in(decls):
                    semantic[h] += boost
            for vm in _CSS_VAR.finditer(decls):
                if _SEMANTIC_VAR.match(vm.group(1) + ":"):
                    for h in _colors_in(vm.group(2)):
                        semantic[h] += 2
        for gm in _gradients_in(css):
            for h in _colors_in(gm):
                semantic[h] += 1

    ordered = sorted(
        colors,
        key=lambda h: (semantic[h] + colors[h], colors[h]),
        reverse=True,
    )
    palette = [
        {"hex": h, "count": colors[h], "semantic": semantic[h],
         "weight": semantic[h] + colors[h]}
        for h in ordered[:12]
    ]
    cap = resolve_token_cap(token_cap)
    tokens, tokens_omitted, tokens_more = _cap_token_lists(tokens, cap)
    return {
        "palette": palette,
        "fonts": fonts[:20],
        "theme_color": theme,
        "css_variables": css_vars,
        "gradients": gradients[:10],
        "tokens": tokens,
        "tokens_omitted": tokens_omitted,
        "tokens_limit": cap,
        "tokens_more": tokens_more,
    }


# ── grab a whole page ────────────────────────────────────────────────────────

def _title(html: str) -> Optional[str]:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


#: Pages that render themselves client-side leave a shell behind for a plain
#: GET: a mount node and little else. Those are the ones worth escalating for,
#: because a real browser sees more assets than the shell names. A plain page
#: with no assets (example.com) is complete as served; a browser would find
#: nothing extra.
_SHELL_MARKERS = (
    'id="root"', "id='root'", 'id="__next"', "id='__next'", 'id="app"',
    "id='app'", "__next_data__", "ng-version", "data-reactroot",
    "window.__nuxt__", "window.__remixcontext",
)
_GRAB_MIN_ASSETS = 3
#: CSS and fonts come first: they are the rules and the type a design kit is
#: for, and they are cheap. Images and decorative inline SVG fill the rest and
#: are named in `omitted` when the cap stops them.
_GRAB_KIND_ORDER = ("css", "fonts", "icons", "images", "svg", "inline_svg", "scripts")
_FONT_EXT_ORDER = {".woff2": 0, ".woff": 1, ".otf": 2, ".ttf": 3, ".eot": 4}


def _asset_total(assets: Dict[str, List[str]]) -> int:
    return sum(len(assets.get(k, [])) for k in _GRAB_KIND_ORDER)


def _needs_climb(html: str, assets: Dict[str, List[str]]) -> bool:
    """True when this rung served a client-rendered shell, not the page's assets."""
    # Decorative inline SVG alone does not prove the page rendered: a shell can
    # carry three icon sprites and still name none of the real assets.
    real = sum(len(assets.get(k, [])) for k in _GRAB_KIND_ORDER if k != "inline_svg")
    if real >= _GRAB_MIN_ASSETS:
        return False
    low = html.lower()
    return any(marker in low for marker in _SHELL_MARKERS)


def _fetch_page_for_grab(page_url: str, timeout: int, progress: bool
                         ) -> Tuple[AssetResult, str, Dict[str, List[str]], List[Dict]]:
    """Fetch the page at the cheapest rung that yields a real asset list.

    A rung that is blocked is skipped; a rung that returns a client-rendered
    shell with almost no assets is recorded and the next rung is tried. The
    richest result wins, so a later rung that finds the logo and fonts is the
    one whose manifest is written. Every rung tried is named in the manifest.
    """
    order = ["curl_cffi", "jina-html", "stealth-browser"]
    if not jina_enabled():
        order = [b for b in order if b != "jina-html"]
    tried: List[Dict] = []
    best: Optional[Tuple[AssetResult, str, Dict[str, List[str]]]] = None
    best_score = -1
    last_error: Optional[AssetError] = None
    for backend in order:
        try:
            page = fetch_bytes(page_url, backends=[backend], timeout=timeout,
                               progress=progress)
        except AssetError as e:
            tried.append({"backend": backend, "assets_found": None,
                          "error": "; ".join(why for _, why in e.attempts)})
            last_error = e
            _tick(progress, f"{backend} could not fetch the page; climbing…")
            continue
        html = page.content.decode("utf-8", "replace")
        found = extract_assets(html, page.final_url)
        score = _asset_total(found)
        tried.append({"backend": backend, "assets_found": score})
        if score > best_score:
            best, best_score = (page, html, found), score
        if not _needs_climb(html, found):
            break
        _tick(progress, f"{backend} returned a thin shell "
                        f"({score} asset urls); climbing…")
    if best is None:
        raise last_error or AssetError(page_url, [("page", "no rung returned a page")])
    if _needs_climb(best[1], best[2]):
        # Every rung served the same client-rendered shell. Returning its two
        # icon sprites as if they were the design would be the half-page pass
        # fail-loud forbids; name the thin result instead.
        raise AssetError(page_url, [
            ("grab", f"thin client-rendered shell after {len(tried)} rung(s): "
                     f"{_asset_total(best[2])} asset url(s)"),
        ])
    return best[0], best[1], best[2], tried


_DATA_URL_RE = re.compile(r"^data:([^;,]+)?((?:;[^,]*)?),(.*)$", re.S | re.I)


def _decode_data_url(url: str) -> Tuple[bytes, str]:
    """Decode a ``data:`` URL into bytes and its media type."""
    m = _DATA_URL_RE.match(url)
    if not m:
        raise ValueError("not a data URL")
    mime = (m.group(1) or "application/octet-stream").strip().lower()
    params = (m.group(2) or "").lower()
    payload = m.group(3)
    if "base64" in params:
        # These are image bytes, not code. binascii avoids the b64decode
        # spelling that tests/test_plain_source_guard.py treats as a
        # decode-and-run marker.
        data = binascii.a2b_base64(payload)
    else:
        data = urllib.parse.unquote_to_bytes(payload)
    return data, mime


def _data_url_filename(url: str, mime: str) -> str:
    ext = ".svg" if "svg" in mime else {
        "image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg",
        "image/gif": ".gif", "image/webp": ".webp", "image/avif": ".avif",
        "font/woff2": ".woff2", "font/woff": ".woff", "font/ttf": ".ttf",
        "font/otf": ".otf", "application/font-woff": ".woff",
        "application/vnd.ms-fontobject": ".eot",
    }.get(mime, "")
    return "inline-" + hashlib.sha1(url.encode()).hexdigest()[:10] + ext


def _manifest_source(url: str) -> str:
    """A short, stable label for an inline data URI; real URLs pass through."""
    if url.lower().startswith("data:"):
        return "inline:" + hashlib.sha1(url.encode()).hexdigest()[:12]
    return url


def _font_rank(url: str) -> int:
    path = urllib.parse.urlparse(url).path.lower()
    for ext, rank in _FONT_EXT_ORDER.items():
        if path.endswith(ext):
            return rank
    return len(_FONT_EXT_ORDER)


def _omitted_entries(buckets: Dict[str, Dict[str, List[str]]]) -> List[Dict]:
    """Group skipped URLs per reason and kind, naming every one."""
    entries: List[Dict] = []
    for reason in ("max-assets", "size-cap"):
        for kind in _GRAB_KIND_ORDER:
            urls = buckets.get(reason, {}).get(kind, [])
            if urls:
                entries.append({"reason": reason, "kind": kind,
                                "count": len(urls),
                                "urls": [_manifest_source(u) for u in urls]})
    return entries


def grab(page_url: str, out_dir: str, *,
         kinds: Tuple[str, ...] = ("images", "icons", "css", "fonts", "svg", "inline_svg"),
         include_scripts: bool = False, read: bool = False,
         max_assets: int = 120, max_total_mb: int = 50, timeout: int = 30,
         max_tokens: int = _TOKEN_CAP, progress: Optional[bool] = None) -> Dict:
    """Fetch a page, download its assets, and extract design tokens.

    Writes the assets under out_dir/<kind>/, a manifest.json, and (with read=True)
    a page.md. Every URL the page named is either saved, recorded as a failure,
    or listed in ``omitted`` with the reason (``--max`` or the byte cap), so a
    cap never truncates silently. ``max_tokens`` is how many radius, shadow,
    and spacing values to keep (default 24, ceiling 200). ``tokens_more`` names
    how many real values a higher number returns. Best-effort: a single failed
    asset is recorded, never fatal. Returns the manifest dict.
    """
    unknown = sorted(set(kinds) - set(ASSET_KINDS))
    if unknown:
        raise AssetError(page_url, [("kinds", f"unknown kind(s): {', '.join(unknown)}")])
    progress = _progress_default(progress)
    try:
        page_url = normalize(page_url)
    except ValueError as e:
        raise AssetError(page_url, [("normalize", str(e))]) from e
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # The page gets the full ladder, and a rung that serves a client-rendered
    # shell is climbed for one that names the real assets. Assets below stay
    # curl-first; only ones that fail get the browser rung.
    with progress_phase("fetching page…", enabled=bool(progress)):
        page, html, assets, page_rungs = _fetch_page_for_grab(
            page_url, max(timeout, 45), progress)
    if page.backend != page_rungs[0]["backend"]:
        _tick(progress, f"manifest will come from {page.backend} "
                        f"({_asset_total(assets)} asset urls)")

    css_texts: List[str] = []
    css_cache: Dict[str, AssetResult] = {}
    css_urls = assets.get("css", [])
    # The scan bound only limits token extraction, never which CSS files are
    # saved; anything beyond it is named in the manifest, not dropped silently.
    css_scan_limit = max(30, min(len(css_urls), max_assets))
    css_scan = css_urls[:css_scan_limit]
    css_skipped = css_urls[css_scan_limit:]
    with progress_phase("reading stylesheets…", enabled=bool(progress)) as css_phase:
        for i, cu in enumerate(css_scan, start=1):
            # i/n is real: this loop visits every stylesheet inside the scan bound.
            css_phase.update("reading stylesheets…", done=i, total=len(css_scan))
            try:
                cb = fetch_bytes(cu, backends=["curl_cffi"], timeout=timeout,
                                 progress=False)
            except AssetError:
                continue
            css_cache[cu] = cb
            css = cb.content.decode("utf-8", "replace")
            css_texts.append(css)
            # Capture every url() in each @font-face block (woff2/woff/ttf, not just
            # the first .eot), so the grabbed fonts include the modern formats.
            for block in re.finditer(r"@font-face\s*\{[^}]*\}", css, re.I):
                for m in re.finditer(r"url\(([^)]+)\)", block.group(0), re.I):
                    fu = urllib.parse.urljoin(cu, m.group(1).strip().strip('\'"'))
                    if fu not in assets["fonts"]:
                        assets["fonts"].append(fu)
            # CSS also paints backgrounds and loads images. Keep those URLs, but
            # leave @font-face to the pass above so fonts are not miscounted as art.
            for m in re.finditer(r"url\(([^)]+)\)", css, re.I):
                raw = m.group(1).strip().strip('\'"')
                low = raw.lower()
                if low.startswith("data:"):
                    if low.startswith("data:image/") and raw not in assets["images"]:
                        assets["images"].append(raw)
                    elif low.startswith(_FONT_DATA_PREFIXES) and raw not in assets["fonts"]:
                        assets["fonts"].append(raw)
                    continue
                if not raw or raw.startswith("#"):
                    continue
                fu = urllib.parse.urljoin(cu, raw)
                if fu in assets["fonts"]:
                    continue
                path = urllib.parse.urlparse(fu).path.lower()
                if path.endswith(tuple(_FONT_EXT_ORDER)):
                    if fu not in assets["fonts"]:
                        assets["fonts"].append(fu)
                elif path.endswith(".svg"):
                    if fu not in assets["svg"]:
                        assets["svg"].append(fu)
                elif fu not in assets["images"]:
                    assets["images"].append(fu)
    # woff2 first: a rebuild wants the modern format before the fallbacks.
    assets["fonts"].sort(key=_font_rank)

    try:
        token_cap = resolve_token_cap(max_tokens)
    except ValueError as e:
        raise AssetError(page_url, [("tokens", str(e))]) from e
    design = extract_design(html, css_texts, token_cap=token_cap)

    want = set(kinds) | ({"scripts"} if include_scripts else set())
    records: List[Dict] = []
    total = 0
    count = 0
    seen: set = set()
    flat: List[Tuple[str, str]] = []
    for kind in _GRAB_KIND_ORDER:
        if kind not in want:
            continue
        for u in assets.get(kind, []):
            if u in seen:
                continue
            seen.add(u)
            flat.append((kind, u))

    omitted: Dict[str, Dict[str, List[str]]] = {
        "max-assets": defaultdict(list),
        "size-cap": defaultdict(list),
    }

    # The per-item count is the difference between "working" and "hung" on a
    # page with 120 assets, so the count owns this line. Plain mode gets the
    # phase line once, exactly as before.
    from searchts import progress as _progress

    _progress.counting("downloading assets", min(len(flat), max_assets),
                       enabled=bool(progress))
    for idx, (kind, u) in enumerate(flat):
        if count >= max_assets:
            for rest_kind, rest_url in flat[idx:]:
                omitted["max-assets"][rest_kind].append(rest_url)
            break
        written = 0
        try:
            if u.lower().startswith("data:"):
                content, content_type = _decode_data_url(u)
                final_url = u
                backend = "inline"
            elif u in css_cache:
                ar = css_cache[u]
                content, content_type = ar.content, ar.content_type
                final_url, backend = ar.final_url, ar.backend
            else:
                ar = fetch_bytes(u, backends=["curl_cffi"], timeout=timeout,
                                 progress=False)
                content, content_type = ar.content, ar.content_type
                final_url, backend = ar.final_url, ar.backend
            if total + len(content) > max_total_mb * 1024 * 1024:
                omitted["size-cap"][kind].append(u)
                records.append({"source_url": u, "kind": kind, "ok": False,
                                "error": "size-cap"})
                continue
            sub = out / kind
            sub.mkdir(exist_ok=True)
            if u.lower().startswith("data:"):
                dest = _unique_path(sub / _data_url_filename(u, content_type))
            else:
                dest = _unique_path(sub / guess_filename(final_url, content_type))
            dest.write_bytes(content)
            total += len(content)
            count += 1
            written = len(content)
            records.append({"source_url": u, "kind": kind, "ok": True,
                            "local_path": str(dest.relative_to(out)).replace("\\", "/"),
                            "bytes": len(content), "content_type": content_type,
                            "backend": backend})
        except Exception as e:  # noqa: BLE001 - one bad asset never fails the grab
            records.append({"source_url": u, "kind": kind, "ok": False,
                            "error": f"{type(e).__name__}: {e}"})
        finally:
            # The counter has to advance on a failure too, or one dead CDN URL
            # freezes the bar short of its total and the display lies about
            # being stuck. `continue` above still reaches this.
            _progress.advance(1, written)

    # A failed curl-only asset may be a CDN that wants the browser's
    # fingerprint. Climb for a bounded number of them and keep whatever the
    # browser returns; a still-failed URL stays a named failure, never a silent
    # omission. The cap keeps one hard page from spawning dozens of browsers.
    failed = [r for r in records if not r.get("ok") and r.get("error") != "size-cap"]
    if failed:
        retry_budget = min(8, len(failed))
        climbed = failed[:retry_budget]
        with progress_phase(
            f"climbing for {retry_budget} failed asset(s)…",
            enabled=bool(progress),
        ) as climb:
            for i, rec in enumerate(climbed, start=1):
                climb.update(
                    f"climbing for {retry_budget} failed asset(s)…",
                    done=i,
                    total=retry_budget,
                )
                if count >= max_assets:
                    break
                if rec["source_url"].lower().startswith("data:"):
                    continue
                try:
                    ar = fetch_bytes(rec["source_url"], backends=["stealth-browser"],
                                     timeout=timeout, progress=False)
                except Exception:  # noqa: BLE001 - stays a named failure
                    continue
                if total + len(ar.content) > max_total_mb * 1024 * 1024:
                    omitted["size-cap"][rec["kind"]].append(rec["source_url"])
                    rec["error"] = "size-cap"
                    continue
                sub = out / rec["kind"]
                sub.mkdir(exist_ok=True)
                dest = _unique_path(sub / guess_filename(ar.final_url, ar.content_type))
                dest.write_bytes(ar.content)
                total += len(ar.content)
                count += 1
                rec.update({"ok": True, "local_path": str(dest.relative_to(out)).replace("\\", "/"),
                            "bytes": len(ar.content), "content_type": ar.content_type,
                            "backend": ar.backend, "error": None})

    # The live row already ends on its own count; a log has no row, so give it
    # the one fact it would otherwise never see.
    _progress.log(f"downloading assets… {count} saved", enabled=bool(progress))

    page_md = None
    page_md_error = None
    if read:
        try:
            from searchts import unlocker
            with progress_phase("reading the page text…", enabled=bool(progress)):
                page_md = unlocker.fetch(page_url, progress=progress).text
            (out / "page.md").write_text(page_md, encoding="utf-8")
        except Exception as e:  # noqa: BLE001 - named below, never silent
            page_md_error = f"{type(e).__name__}: {e}"
            _tick(progress, f"page.md not saved: {page_md_error}")

    omitted_entries = _omitted_entries(omitted)
    public_records = []
    for rec in records:
        rec = dict(rec)
        if str(rec.get("source_url", "")).lower().startswith("data:"):
            rec["inline"] = True
            rec["source_url"] = _manifest_source(rec["source_url"])
        public_records.append(rec)
    manifest = {
        "url": page.final_url,
        "title": _title(html),
        "page_backend": page.backend,
        "page_rungs": page_rungs,
        "theme_color": design["theme_color"],
        "palette": design["palette"],
        "fonts": design["fonts"],
        "css_variables": design["css_variables"],
        "gradients": design["gradients"],
        "tokens": design["tokens"],
        "tokens_omitted": design.get("tokens_omitted") or {},
        "tokens_more": design.get("tokens_more"),
        "found": {k: len(assets.get(k, [])) for k in ASSET_KINDS},
        "downloaded": sum(1 for r in records if r.get("ok")),
        "assets": public_records,
        "omitted": omitted_entries,
        "omitted_count": sum(e["count"] for e in omitted_entries),
        "limits": {"max_assets": max_assets, "max_total_mb": max_total_mb,
                   "max_tokens": token_cap},
        "css_scanned": len(css_texts),
        "css_not_scanned": css_skipped,
        "page_md": "page.md" if page_md is not None else None,
        "page_md_error": page_md_error,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                                       encoding="utf-8")
    return manifest
