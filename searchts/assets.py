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

import json
import re
import urllib.parse
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from searchts.unlocker import _UA_REAL, looks_blocked, normalize

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

    r = cr.get(url, impersonate="chrome", timeout=timeout,
               headers={"Accept-Language": "en-US,en;q=0.9"})
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
    return AssetResult(content, ct, str(r.url), "curl_cffi")


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

    ms = int(timeout * 1000)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(user_agent=_UA_REAL, locale="en-US",
                                      viewport={"width": 1280, "height": 800})
            resp = ctx.request.get(url, timeout=ms)
            if resp.ok:
                body = resp.body()
                ct = (resp.headers or {}).get("content-type", "") or ""
                # An empty content-type can still be a challenge; an empty body is
                # never real content (a flagged WAF answers 2xx with no body).
                textual = any(t in ct.lower() for t in _TEXTUAL_CT) or not ct
                blocked = textual and looks_blocked(resp.status, body.decode("utf-8", "replace"))
                if body and not blocked:
                    return AssetResult(body, ct, resp.url, "stealth-browser")
            # HTML page still walled: navigate so a JS challenge can clear.
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=ms)
            waited = 0
            html = page.content()
            # Wait until the challenge clears AND real content has rendered. A
            # too-thin page is an unresolved interstitial / CAPTCHA (e.g. AWS WAF
            # rate-limiting rapid hits), NOT content -- never accept it as success.
            while waited < 25000 and (looks_blocked(200, html) == "challenge" or len(html) < 8000):
                page.wait_for_timeout(1500)
                waited += 1500
                try:
                    html = page.content()
                except Exception:  # noqa: BLE001
                    break
            if looks_blocked(200, html) is None and len(html) >= 8000:
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
                timeout: int = 30) -> AssetResult:
    """Fetch raw bytes for `url`, escalating through the unlock ladder."""
    url = normalize(url)
    order = backends or DEFAULT_ASSET_BACKENDS
    attempts: List[Tuple[str, str]] = []
    for backend in order:
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


def get_asset(url: str, out_path: Optional[str] = None, *, timeout: int = 30) -> Path:
    """Download one asset to disk; return the saved path."""
    res = fetch_bytes(url, timeout=timeout)
    if out_path:
        dest = Path(out_path)
        if dest.is_dir():
            dest = dest / guess_filename(res.final_url, res.content_type)
    else:
        dest = Path(guess_filename(res.final_url, res.content_type))
    if dest.parent and not dest.parent.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(res.content)
    return dest


# ── HTML asset enumeration ───────────────────────────────────────────────────

_ASSET_KINDS = ("images", "icons", "css", "fonts", "svg", "scripts")


def extract_assets(html: str, base_url: str) -> Dict[str, List[str]]:
    """Enumerate a page's assets as absolute URLs, grouped by kind."""
    out: Dict[str, List[str]] = {k: [] for k in _ASSET_KINDS}

    def add(kind: str, href: Optional[str]) -> None:
        if not href:
            return
        u = urllib.parse.urljoin(base_url, href.strip().strip('\'"'))
        if not u.lower().startswith(("http://", "https://")):
            return
        if u not in out[kind]:
            out[kind].append(u)
        if u.split("?")[0].lower().endswith(".svg") and u not in out["svg"]:
            out["svg"].append(u)

    try:
        import lxml.html as LH
        doc = LH.fromstring(html)
        for el in doc.iter("img"):
            add("images", el.get("src"))
            ss = el.get("srcset")
            if ss:
                add("images", ss.split(",")[0].strip().split(" ")[0])
        for el in doc.iter("source"):
            ss = el.get("srcset") or el.get("src")
            if ss:
                add("images", ss.split(",")[0].strip().split(" ")[0])
        for el in doc.iter("meta"):
            prop = (el.get("property") or el.get("name") or "").lower()
            if prop in ("og:image", "og:image:url", "twitter:image", "twitter:image:src"):
                add("images", el.get("content"))
        for el in doc.iter("link"):
            rels = (el.get("rel") or "").lower().split()
            href = el.get("href")
            if "stylesheet" in rels:
                add("css", href)
            if any(r in rels for r in ("icon", "shortcut", "apple-touch-icon", "mask-icon")):
                add("icons", href)
            if (el.get("as") or "").lower() == "font":
                add("fonts", href)
        for el in doc.iter("script"):
            add("scripts", el.get("src"))
    except Exception:  # noqa: BLE001 - malformed HTML: fall back to regex
        for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)', html, re.I):
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
_GENERIC_FONTS = {"inherit", "initial", "unset", "serif", "sans-serif", "monospace",
                  "cursive", "fantasy", "system-ui", "ui-sans-serif", "ui-serif",
                  "ui-monospace", "-apple-system", "blinkmacsystemfont"}


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


def extract_design(html: str, css_texts: Optional[List[str]] = None) -> Dict:
    """Extract a color palette, the fonts in use, and theme-color."""
    blobs = [html] + list(css_texts or [])
    colors: Counter = Counter()
    fonts: List[str] = []
    for b in blobs:
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
        for m in _FONTFAM.finditer(b):
            fam = m.group(1).split(",")[0].strip().strip('\'"')
            if (fam and fam.lower() not in _GENERIC_FONTS and fam not in fonts
                    and not fam.startswith(("$", "--")) and "var(" not in fam.lower()):
                fonts.append(fam)
    # Google Fonts <link href="...family=Roboto:...&family=Inter">
    for m in re.finditer(r"fonts\.googleapis\.com/css2?\?([^\"'> )]+)", html, re.I):
        for fm in re.finditer(r"family=([^&:]+)", m.group(1)):
            fam = urllib.parse.unquote_plus(fm.group(1)).split(":")[0].strip()
            if fam and fam not in fonts:
                fonts.append(fam)
    theme = None
    tm = re.search(r'<meta[^>]+name=["\']theme-color["\'][^>]+content=["\']([^"\']+)', html, re.I)
    if tm:
        theme = tm.group(1).strip()
    palette = [{"hex": h, "count": c} for h, c in colors.most_common(12)]
    return {"palette": palette, "fonts": fonts[:20], "theme_color": theme}


# ── grab a whole page ────────────────────────────────────────────────────────

def _title(html: str) -> Optional[str]:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


def grab(page_url: str, out_dir: str, *,
         kinds: Tuple[str, ...] = ("images", "icons", "css", "fonts", "svg"),
         include_scripts: bool = False, read: bool = False,
         max_assets: int = 60, max_total_mb: int = 50, timeout: int = 30) -> Dict:
    """Fetch a page, download its assets, and extract design tokens.

    Writes the assets under out_dir/<kind>/, a manifest.json, and (with read=True)
    a page.md. Best-effort: a single failed asset is recorded, never fatal.
    Returns the manifest dict.
    """
    page_url = normalize(page_url)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # The page itself gets the full ladder (curl -> Jina HTML relay -> stealth
    # browser): one justified solve for a walled site. Assets below stay
    # curl-only so a page with dozens of assets never spawns dozens of browsers.
    page = fetch_bytes(page_url, backends=["curl_cffi", "jina-html", "stealth-browser"],
                       timeout=max(timeout, 45))
    html = page.content.decode("utf-8", "replace")
    assets = extract_assets(html, page.final_url)

    css_texts: List[str] = []
    for cu in assets.get("css", [])[:20]:
        try:
            cb = fetch_bytes(cu, backends=["curl_cffi"], timeout=timeout)
            css = cb.content.decode("utf-8", "replace")
            css_texts.append(css)
            # Capture every url() in each @font-face block (woff2/woff/ttf, not just
            # the first .eot), so the grabbed fonts include the modern formats.
            for block in re.finditer(r"@font-face\s*\{[^}]*\}", css, re.I):
                for m in re.finditer(r"url\(([^)]+)\)", block.group(0), re.I):
                    fu = urllib.parse.urljoin(cu, m.group(1).strip().strip('\'"'))
                    if fu not in assets["fonts"]:
                        assets["fonts"].append(fu)
        except AssetError:
            pass

    design = extract_design(html, css_texts)

    want = set(kinds) | ({"scripts"} if include_scripts else set())
    records: List[Dict] = []
    total = 0
    count = 0
    seen: set = set()
    for kind in ("images", "icons", "svg", "css", "fonts", "scripts"):
        if kind not in want:
            continue
        for u in assets.get(kind, []):
            if u in seen:
                continue
            seen.add(u)
            if count >= max_assets:
                break
            try:
                ar = fetch_bytes(u, backends=["curl_cffi"], timeout=timeout)
                if total + len(ar.content) > max_total_mb * 1024 * 1024:
                    records.append({"source_url": u, "kind": kind, "ok": False, "error": "size-cap"})
                    continue
                sub = out / kind
                sub.mkdir(exist_ok=True)
                dest = _unique_path(sub / guess_filename(ar.final_url, ar.content_type))
                dest.write_bytes(ar.content)
                total += len(ar.content)
                count += 1
                records.append({"source_url": u, "kind": kind, "ok": True,
                                "local_path": str(dest.relative_to(out)).replace("\\", "/"),
                                "bytes": len(ar.content), "content_type": ar.content_type,
                                "backend": ar.backend})
            except Exception as e:  # noqa: BLE001 - one bad asset never fails the grab
                records.append({"source_url": u, "kind": kind, "ok": False,
                                "error": f"{type(e).__name__}: {e}"})

    page_md = None
    if read:
        try:
            from searchts import unlocker
            page_md = unlocker.fetch(page_url).text
            (out / "page.md").write_text(page_md, encoding="utf-8")
        except Exception:  # noqa: BLE001
            page_md = None

    manifest = {
        "url": page.final_url,
        "title": _title(html),
        "page_backend": page.backend,
        "theme_color": design["theme_color"],
        "palette": design["palette"],
        "fonts": design["fonts"],
        "found": {k: len(assets.get(k, [])) for k in _ASSET_KINDS},
        "downloaded": sum(1 for r in records if r.get("ok")),
        "assets": records,
        "page_md": "page.md" if page_md is not None else None,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                                       encoding="utf-8")
    return manifest
