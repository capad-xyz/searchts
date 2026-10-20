# -*- coding: utf-8 -*-
"""Tests for the on-demand asset + design grabber (no network)."""

import json

import pytest

from searchts import assets

# ── color / filename helpers ─────────────────────────────────────────────────

def test_norm_hex_expands_shorthand_and_drops_alpha():
    assert assets._norm_hex("#FFF") == "#ffffff"
    assert assets._norm_hex("#1a2B3c") == "#1a2b3c"
    assert assets._norm_hex("#11223344") == "#112233"  # alpha dropped for grouping


def test_rgb_and_hsl_to_hex():
    assert assets._rgb_to_hex(10, 10, 35) == "#0a0a23"
    assert assets._hsl_to_hex(210, 50, 40) == "#336699"


def test_guess_filename_strips_query_and_keeps_extension():
    assert assets.guess_filename("https://x.test/a/b/photo.JPG?v=2", "image/jpeg") == "photo.JPG"


def test_guess_filename_adds_extension_from_content_type():
    name = assets.guess_filename("https://x.test/", "image/png")
    assert name.startswith("asset-") and name.endswith(".png")


def test_guess_filename_blocks_path_traversal():
    name = assets.guess_filename("https://x.test/../../etc/passwd", "")
    assert "/" not in name and "\\" not in name and ".." not in name
    assert name == "passwd"


def test_guess_filename_honours_content_disposition():
    name = assets.guess_filename("https://x.test/x", "",
                                 'attachment; filename="report.pdf"')
    assert name == "report.pdf"


# ── asset enumeration ────────────────────────────────────────────────────────

PAGE_HTML = """
<html><head>
<title>Demo Site</title>
<meta name="theme-color" content="#0a0a23">
<meta property="og:image" content="https://cdn.test/og.png">
<link rel="stylesheet" href="/style.css">
<link rel="icon" href="/favicon.ico">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&family=Roboto+Mono" rel="stylesheet">
</head><body>
<img src="/img/logo.png">
<img srcset="/img/hero@2x.jpg 2x, /img/hero.jpg 1x">
<img src="/img/broken.png">
<div style="background-image:url('/img/bg.webp')"></div>
</body></html>
"""

CSS_TEXT = """
body { color: #fff; background: rgb(10, 10, 35); font-family: "Inter", sans-serif; }
.x { color: hsl(210, 50%, 40%); }
@font-face { font-family: 'Custom'; src: url('/fonts/custom.woff2'); }
"""


def test_extract_assets_resolves_and_categorizes():
    a = assets.extract_assets(PAGE_HTML, "https://demo.test/")
    assert "https://demo.test/img/logo.png" in a["images"]
    assert "https://demo.test/img/hero@2x.jpg" in a["images"]  # first srcset url
    assert "https://cdn.test/og.png" in a["images"]            # og:image
    assert "https://demo.test/img/bg.webp" in a["images"]      # inline background
    assert "https://demo.test/favicon.ico" in a["icons"]
    assert "https://demo.test/style.css" in a["css"]


def test_extract_assets_dedups():
    html = '<img src="/a.png"><img src="/a.png">'
    a = assets.extract_assets(html, "https://d.test/")
    assert a["images"].count("https://d.test/a.png") == 1


# ── design tokens ────────────────────────────────────────────────────────────

def test_extract_design_palette_fonts_theme():
    d = assets.extract_design(PAGE_HTML, [CSS_TEXT])
    hexes = [c["hex"] for c in d["palette"]]
    assert "#ffffff" in hexes          # #fff
    assert "#0a0a23" in hexes          # rgb(10,10,35)
    assert "#336699" in hexes          # hsl(210,50%,40%)
    assert "Inter" in d["fonts"]       # css font-family
    assert "Custom" in d["fonts"]      # @font-face family
    assert "Roboto Mono" in d["fonts"]  # google fonts link
    assert d["theme_color"] == "#0a0a23"


# ── fetch_bytes ladder ───────────────────────────────────────────────────────

def test_fetch_bytes_returns_curl_result(monkeypatch):
    monkeypatch.setattr(assets, "_fetch_bytes_curl",
                        lambda url, timeout: assets.AssetResult(b"ok", "image/png", url, "curl_cffi"))
    res = assets.fetch_bytes("https://x.test/a.png")
    assert res.content == b"ok" and res.backend == "curl_cffi"


def test_fetch_bytes_escalates_to_stealth_when_curl_blocked(monkeypatch):
    def blocked(url, timeout):
        raise assets.AssetError(url, [("curl_cffi", "challenge")])

    monkeypatch.setattr(assets, "_fetch_bytes_curl", blocked)
    monkeypatch.setattr(assets, "_fetch_bytes_stealth",
                        lambda url, timeout: assets.AssetResult(b"html", "text/html", url, "stealth-browser"))
    res = assets.fetch_bytes("https://x.test/")
    assert res.backend == "stealth-browser"


def test_fetch_bytes_raises_with_all_attempts(monkeypatch):
    monkeypatch.setattr(assets, "_fetch_bytes_curl",
                        lambda url, timeout: (_ for _ in ()).throw(assets.AssetError(url, [("curl_cffi", "http-403")])))
    monkeypatch.setattr(assets, "_fetch_bytes_stealth",
                        lambda url, timeout: (_ for _ in ()).throw(assets.AssetError(url, [("stealth-browser", "still blocked")])))
    with pytest.raises(assets.AssetError) as exc:
        assets.fetch_bytes("https://x.test/")
    rungs = dict(exc.value.attempts)
    assert "curl_cffi" in rungs and "stealth-browser" in rungs


# ── get_asset ────────────────────────────────────────────────────────────────

def test_get_asset_writes_bytes(monkeypatch, tmp_path):
    monkeypatch.setattr(assets, "fetch_bytes",
                        lambda url, timeout=30, progress=None: assets.AssetResult(b"DATA", "image/png",
                                                                   "https://x.test/p.png", "curl_cffi"))
    out = assets.get_asset("https://x.test/p.png", str(tmp_path))
    assert out.read_bytes() == b"DATA"
    assert out.name == "p.png"


# ── grab ─────────────────────────────────────────────────────────────────────

def _fake_fetch(url, *, backends=None, timeout=30, progress=None):
    if "googleapis" in url:
        return assets.AssetResult(b"/* gfont */", "text/css", url, "curl_cffi")
    if url.endswith(".css") or "/style.css" in url:
        return assets.AssetResult(CSS_TEXT.encode(), "text/css", url, "curl_cffi")
    if "broken" in url:
        raise assets.AssetError(url, [("curl_cffi", "http-404"), ("stealth-browser", "still blocked")])
    if "/img/" in url or url.endswith(".ico") or "/fonts/" in url:
        return assets.AssetResult(b"BINARYBYTES", "image/png", url, "curl_cffi")
    return assets.AssetResult(PAGE_HTML.encode(), "text/html", url, "curl_cffi")


def test_grab_writes_manifest_palette_fonts_and_assets(monkeypatch, tmp_path):
    monkeypatch.setattr(assets, "fetch_bytes", _fake_fetch)
    out = tmp_path / "grab"
    manifest = assets.grab("https://demo.test/", str(out))

    assert manifest["title"] == "Demo Site"
    assert manifest["theme_color"] == "#0a0a23"
    hexes = [c["hex"] for c in manifest["palette"]]
    assert "#ffffff" in hexes and "#0a0a23" in hexes
    assert "Inter" in manifest["fonts"] and "Custom" in manifest["fonts"]
    assert manifest["downloaded"] >= 4
    assert (out / "manifest.json").exists()
    saved = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert saved["url"]
    # the broken asset is recorded as a failure but never crashes the grab
    assert any(r["source_url"].endswith("broken.png") and not r["ok"] for r in manifest["assets"])
    # at least one real image file landed under images/
    assert any((out / "images").glob("*"))


def test_grab_respects_max_assets(monkeypatch, tmp_path):
    monkeypatch.setattr(assets, "fetch_bytes", _fake_fetch)
    manifest = assets.grab("https://demo.test/", str(tmp_path / "g"), max_assets=1)
    assert manifest["downloaded"] <= 1


# ── CLI: get / grab ──────────────────────────────────────────────────────────

from unittest.mock import patch  # noqa: E402

import searchts.cli as cli  # noqa: E402


def test_cli_get_prints_saved_path(monkeypatch, capsys, tmp_path):
    saved = tmp_path / "logo.png"
    saved.write_bytes(b"xxxxx")
    monkeypatch.setattr("searchts.assets.get_asset", lambda url, out=None, progress=True: saved)
    with patch("sys.argv", ["searchts", "get", "https://x.test/logo.png"]):
        cli.main()
    captured = capsys.readouterr()
    assert str(saved) in captured.out   # path to stdout
    assert "saved" in captured.err      # status to stderr


def test_cli_get_error_exits_nonzero(monkeypatch):
    def boom(url, out=None, progress=True):
        raise assets.AssetError(url, [("curl_cffi", "http-403")])

    monkeypatch.setattr("searchts.assets.get_asset", boom)
    with patch("sys.argv", ["searchts", "get", "https://x.test/x"]):
        with pytest.raises(SystemExit) as exc:
            cli.main()
    assert exc.value.code == 1


def test_cli_grab_prints_summary_and_manifest_path(monkeypatch, capsys, tmp_path):
    manifest = {"title": "Demo", "downloaded": 3,
                "palette": [{"hex": "#0a0a23", "count": 9}],
                "fonts": ["Inter"], "assets": []}
    seen = {}

    def fake_grab(url, out, **kw):
        seen["out"] = out
        seen["kinds"] = kw.get("kinds")
        return manifest

    monkeypatch.setattr("searchts.assets.grab", fake_grab)
    with patch("sys.argv", ["searchts", "grab", "https://demo.test/", "--out", str(tmp_path / "g")]):
        cli.main()
    captured = capsys.readouterr()
    assert "manifest.json" in captured.out
    assert "Demo" in captured.err and "#0a0a23" in captured.err
    assert seen["out"] == str(tmp_path / "g")
    assert "images" in seen["kinds"]


def test_cli_grab_json_outputs_manifest(monkeypatch, capsys):
    manifest = {"title": "Demo", "downloaded": 0, "palette": [], "fonts": [], "assets": []}
    monkeypatch.setattr("searchts.assets.grab", lambda url, out, **kw: manifest)
    with patch("sys.argv", ["searchts", "grab", "https://demo.test/", "--json"]):
        cli.main()
    data = json.loads(capsys.readouterr().out)
    assert data["title"] == "Demo"


# ── progress ticks (P4.6) ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _no_progress_env(monkeypatch):
    monkeypatch.delenv("SEARCHTS_PROGRESS", raising=False)


def test_get_asset_ticks_fetch_and_save(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(assets, "fetch_bytes",
                        lambda url, timeout=30, progress=None: assets.AssetResult(
                            b"DATA", "image/png", "https://x.test/p.png", "curl_cffi"))
    assets.get_asset("https://x.test/p.png", str(tmp_path), progress=True)
    captured = capsys.readouterr()
    # stdout stays clean (no pipeable content); ticks go to stderr.
    assert captured.out == ""
    assert captured.err == "fetching asset…\nsaving asset…\n"


def test_fetch_bytes_ticks_each_rung(monkeypatch, capsys):
    monkeypatch.setattr(assets, "_fetch_bytes_curl",
                        lambda url, timeout: (_ for _ in ()).throw(assets.AssetError(url, [("curl_cffi", "blocked")])))
    monkeypatch.setattr(assets, "_fetch_bytes_stealth",
                        lambda url, timeout: assets.AssetResult(b"x", "text/html", url, "stealth-browser"))
    assets.fetch_bytes("https://x.test/", progress=True)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "trying curl_cffi…\ntrying stealth-browser…\n"


def test_grab_ticks_fetch_and_assets(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(assets, "fetch_bytes", _fake_fetch)
    assets.grab("https://demo.test/", str(tmp_path / "g"), progress=True)
    captured = capsys.readouterr()
    assert captured.out == ""
    # Both phase ticks must land on stderr (not just "fetching page").
    assert "fetching page" in captured.err and "downloading assets" in captured.err


def test_get_asset_progress_false_is_quiet(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(assets, "fetch_bytes",
                        lambda url, timeout=30, progress=None: assets.AssetResult(
                            b"DATA", "image/png", "https://x.test/p.png", "curl_cffi"))
    assets.get_asset("https://x.test/p.png", str(tmp_path), progress=False)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_grab_progress_none_follows_env(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SEARCHTS_PROGRESS", "1")
    monkeypatch.setattr(assets, "fetch_bytes", _fake_fetch)
    assets.grab("https://demo.test/", str(tmp_path / "g"))
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "fetching page" in captured.err


def test_cli_get_ticks_through_real_get_asset(monkeypatch, capsys, tmp_path):
    # Drive the real get_asset (so its ticks run) but stub the network fetch.
    monkeypatch.setattr(assets, "fetch_bytes",
                        lambda url, timeout=30, progress=None: assets.AssetResult(
                            b"xxxxx", "image/png", "https://x.test/logo.png", "curl_cffi"))
    with patch("sys.argv", ["searchts", "get", "https://x.test/logo.png", "-o", str(tmp_path)]):
        cli.main()
    captured = capsys.readouterr()
    assert (tmp_path / "logo.png").exists()
    assert "fetching asset" in captured.err and "saving asset" in captured.err


def test_cli_grab_nonjson_ticks_on_stderr(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(assets, "fetch_bytes", _fake_fetch)
    with patch("sys.argv", ["searchts", "grab", "https://demo.test/", "--out", str(tmp_path / "g")]):
        cli.main()
    captured = capsys.readouterr()
    assert "fetching page" in captured.err and "downloading assets" in captured.err


# ── bot-wall detection (AWS WAF), empty-body + jina-html rung ─────────────────

from searchts.unlocker import looks_blocked  # noqa: E402


def test_looks_blocked_detects_aws_waf():
    # Dribbble-style AWS WAF JS challenge: 202 + goku/awsWaf token blob.
    body = "<html><script>window.awsWafCookieDomainList=[];window.gokuProps={};</script></html>"
    assert looks_blocked(202, body) == "challenge"


def test_looks_blocked_detects_more_waf_vendors():
    # Each is an interstitial that can be served on HTTP 200 (status alone would
    # not flag it) -- the phrase match is what catches the on-200/202/302 blocks.
    bodies = [
        "<html><h1>Pardon Our Interruption</h1></html>",                # F5 / Shape (Distil)
        "<html><body>Powered by Incapsula</body></html>",               # Imperva on-200
        '<p id="cmsg">Please enable JS and disable any ad blocker</p>',  # DataDome
        '<div id="px-captcha"></div>',                                  # PerimeterX / HUMAN
        "<title>Vercel Security Checkpoint</title>",                    # Vercel
        "Access Denied - Sucuri Website Firewall",                      # Sucuri
        "<script>window.KPSDK={};</script>",                            # Kasada
        "<html>You are now in line at https://x.queue-it.net</html>",   # Queue-it
    ]
    for body in bodies:
        assert looks_blocked(200, body) == "challenge", body[:48]


def test_curl_rejects_empty_body(monkeypatch):
    import curl_cffi.requests as cr

    class R:
        status_code = 200
        headers = {"content-type": "image/png"}
        content = b""
        url = "https://x.test/a.png"

    monkeypatch.setattr(cr, "get", lambda *a, **k: R())
    with pytest.raises(assets.AssetError):
        assets._fetch_bytes_curl("https://x.test/a.png", 10)


def test_fetch_bytes_jina_html_returns_html(monkeypatch):
    class R:
        status_code = 200
        text = "<html>" + ("x" * 600) + "<img src='/a.png'></html>"

    monkeypatch.setattr("requests.get", lambda *a, **k: R())
    res = assets.fetch_bytes("https://x.test/", backends=["jina-html"])
    assert res.backend == "jina-html" and b"<img" in res.content


def test_fetch_bytes_jina_html_detects_relayed_waf(monkeypatch):
    # Jina sometimes relays the WAF shell itself; we must treat that as blocked.
    class R:
        status_code = 200
        text = "<html>" + ("a" * 600) + "window.gokuProps={}</html>"

    monkeypatch.setattr("requests.get", lambda *a, **k: R())
    with pytest.raises(assets.AssetError):
        assets.fetch_bytes("https://x.test/", backends=["jina-html"])


# ── the design kit: saved fixtures for the new parsers ──────────────────────

from pathlib import Path  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "grab"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


GRAB_HTML = _fixture("design_page.html")
GRAB_CSS = _fixture("tokens.css")
BASE = "https://northwind.test/"


def test_srcset_parser_keeps_every_candidate_and_data_uri_commas():
    urls = assets._parse_srcset("/a.png 1x, /a@2x.png 2x, /a@3x.png 3x")
    assert urls == ["/a.png", "/a@2x.png", "/a@3x.png"]
    # A data URI carries its own commas; split(",") would cut it in half.
    urls = assets._parse_srcset("data:image/png;base64,AA,BB 1x, /b.png 2x")
    assert urls == ["data:image/png;base64,AA,BB", "/b.png"]


def test_extract_assets_collects_picture_srcset_lazy_poster_and_meta():
    a = assets.extract_assets(GRAB_HTML, BASE)
    for path in (
        "/media/hero.avif", "/media/hero@2x.avif",
        "/media/hero.webp", "/media/hero@2x.webp",
        "/media/hero.jpg", "/media/hero@2x.jpg", "/media/hero@3x.jpg",
        "/media/lazy-logo.png", "/media/lazy-logo@2x.png",
        "/media/poster.jpg", "/media/paper-texture.png",
    ):
        assert BASE.rstrip("/") + path in a["images"], path
    assert "https://cdn.northwind.test/social/og.png" in a["images"]
    assert "https://cdn.northwind.test/social/twitter.png" in a["images"]
    for path in ("/favicon.ico", "/favicon.svg", "/apple-touch-icon.png",
                 "/safari-pinned-tab.svg"):
        assert BASE.rstrip("/") + path in a["icons"], path
    assert BASE.rstrip("/") + "/fonts/Inter-Variable.woff2" in a["fonts"]
    assert any(u.startswith("data:font/woff2;base64,") for u in a["fonts"])
    assert BASE.rstrip("/") + "/assets/app.js" in a["scripts"]
    assert BASE.rstrip("/") + "/assets/site.css" in a["css"]


def test_extract_assets_keeps_data_uri_images_and_inline_svg():
    a = assets.extract_assets(GRAB_HTML, BASE)
    assert any(u.startswith("data:image/png;base64,") for u in a["images"])
    assert len(a["inline_svg"]) == 2
    data, mime = assets._decode_data_url(a["inline_svg"][0])
    assert mime == "image/svg+xml" and b"<svg" in data


def test_extract_design_reads_variables_tokens_and_semantic_palette():
    d = assets.extract_design(GRAB_HTML, [GRAB_CSS])
    assert d["css_variables"]["--brand"] == "#ff5500"
    assert d["css_variables"]["--radius-card"] == "12px"
    assert d["css_variables"]["--space-4"] == "16px"
    assert "Inter" in d["fonts"] and "IconGlyphs" in d["fonts"]
    hexes = [c["hex"] for c in d["palette"]]
    # The brand from :root/theme-color outranks a reset stylesheet's #000.
    assert "#ff5500" in hexes[:4], hexes
    assert "#d94800" in hexes, hexes
    assert any("linear-gradient" in g for g in d["gradients"])
    assert "12px" in d["tokens"]["radius"]
    assert d["tokens"]["shadow"]
    assert "24px" in d["tokens"]["spacing"] or "0 auto" in d["tokens"]["spacing"]
    assert any("Inter" in stack for stack in d["tokens"]["font_stacks"])
    assert d["tokens_omitted"] == {}
    assert d["tokens_limit"] == assets._TOKEN_CAP
    assert d["tokens_more"] is None


def test_radius_shadow_and_spacing_are_capped_and_named():
    """A stylesheet does not get to list every one-off, or a markup swallow."""
    rules = [
        f".s{i}{{margin:{i}px;border-radius:{i}px;box-shadow:{i}px 0 0 #000}}"
        for i in range(40)
    ]
    rules.append("gap:" + ("<div>not a token</div>" * 20))
    rules.append(".bad{padding:4px <span>}")
    d = assets.extract_design("", ["\n".join(rules)])
    for kind in ("radius", "shadow", "spacing"):
        assert len(d["tokens"][kind]) == assets._TOKEN_CAP
        assert all("<" not in v and len(v) < assets._TOKEN_VALUE_MAX
                   for v in d["tokens"][kind])
    assert d["tokens_omitted"]["spacing"] > d["tokens_omitted"]["radius"]
    assert "0px" in d["tokens"]["spacing"]
    assert "<div>" not in " ".join(d["tokens"]["spacing"])
    assert d["tokens_more"] is not None
    assert "more spacing" in d["tokens_more"]
    assert "--tokens" in d["tokens_more"]
    raised = assets.extract_design("", ["\n".join(rules)], token_cap=40)
    assert len(raised["tokens"]["radius"]) == 40
    assert len(raised["tokens"]["spacing"]) == 40
    assert "more radius" not in (raised["tokens_more"] or "")
    # The two spacing values that are markup stay omitted. Raising the cap
    # does not turn them into tokens.
    assert raised["tokens_omitted"]["spacing"] == 2
    assert raised["tokens_more"] is None


def test_token_cap_outside_the_ceiling_fails_loud():
    with pytest.raises(ValueError):
        assets.extract_design("", [], token_cap=assets._TOKEN_CAP_MAX + 1)
    with pytest.raises(ValueError):
        assets.extract_design("", [], token_cap=-1)
    with pytest.raises(ValueError):
        assets.resolve_token_cap(True)  # type: ignore[arg-type]


def test_gradients_keep_nested_color_functions():
    d = assets.extract_design(
        "", [".x{background:linear-gradient(90deg, rgba(255,0,0,.5), #00ff00)}"])
    grad = d["gradients"][0]
    assert grad.startswith("linear-gradient(") and grad.endswith(")")
    assert "rgba(255,0,0,.5)" in grad and "#00ff00" in grad


def test_theme_color_is_read_whatever_the_meta_order():
    d = assets.extract_design('<meta content="#123456" name="theme-color">', [])
    assert d["theme_color"] == "#123456"


def _design_fetch(url, *, backends=None, timeout=30, progress=None):
    if url.startswith("data:"):
        raise AssertionError("data URIs are saved directly, never fetched")
    if "googleapis" in url:
        return assets.AssetResult(b"/* gfont */", "text/css", url, "curl_cffi")
    if url.endswith(".css"):
        return assets.AssetResult(GRAB_CSS.encode(), "text/css", url, "curl_cffi")
    if url.endswith((".woff2", ".woff", ".ttf", ".otf", ".eot")):
        return assets.AssetResult(b"FONTDATA", "font/woff2", url, "curl_cffi")
    if url.endswith((".png", ".jpg", ".jpeg", ".webp", ".avif", ".ico", ".svg")):
        return assets.AssetResult(b"BINARY", "image/png", url, "curl_cffi")
    return assets.AssetResult(GRAB_HTML.encode(), "text/html", url, "curl_cffi")


def test_grab_writes_css_fonts_inline_svg_and_tokens(monkeypatch, tmp_path):
    monkeypatch.setattr(assets, "fetch_bytes", _design_fetch)
    out = tmp_path / "grab"
    manifest = assets.grab(BASE, str(out))

    # Every kind a designer needs is on disk, with the source URL in the manifest.
    saved_kinds = {r["kind"] for r in manifest["assets"] if r["ok"]}
    assert {"images", "icons", "css", "fonts", "inline_svg"} <= saved_kinds
    # Glob order is the filesystem's. Windows lists the Google font sheet
    # (css2.css) before site.css, so the brand variable is in one of them.
    css_files = list((out / "css").glob("*.css"))
    assert css_files and any(
        "--brand" in path.read_text(encoding="utf-8") for path in css_files
    )
    assert list((out / "inline_svg").glob("*.svg"))
    assert list((out / "images").glob("inline-*.png"))  # the data URI image
    assert list((out / "fonts").glob("inline-*.woff2"))  # the data URI font

    # Font files are saved, modern format first, not just the family name.
    font_records = [r for r in manifest["assets"] if r["kind"] == "fonts" and r["ok"]]
    assert any(r["source_url"].endswith(".woff2") for r in font_records)
    assert any(r["source_url"].endswith(".woff") for r in font_records)
    woff2_at = next(i for i, r in enumerate(font_records)
                    if r["source_url"].endswith(".woff2"))
    woff_at = next(i for i, r in enumerate(font_records)
                   if r["source_url"].endswith(".woff"))
    assert woff2_at < woff_at

    assert any(r["source_url"].endswith("/media/css-texture.png") and r["ok"]
               for r in manifest["assets"])
    assert manifest["css_variables"]["--brand"] == "#ff5500"
    assert manifest["tokens"]["radius"]
    assert manifest["page_rungs"][0]["backend"] == "curl_cffi"

    # Inline data URIs become files and a short label, not a huge manifest URL.
    inline = [r for r in manifest["assets"] if r["kind"] == "inline_svg" and r["ok"]]
    assert inline and all(r["inline"] and r["source_url"].startswith("inline:")
                          for r in inline)


def test_grab_names_what_max_left_out(monkeypatch, tmp_path):
    monkeypatch.setattr(assets, "fetch_bytes", _design_fetch)
    manifest = assets.grab(BASE, str(tmp_path / "g"), max_assets=3)
    assert manifest["downloaded"] == 3
    assert manifest["omitted_count"] > 0
    max_entries = [e for e in manifest["omitted"] if e["reason"] == "max-assets"]
    assert max_entries
    assert all(e["count"] == len(e["urls"]) and e["urls"] for e in max_entries)
    assert manifest["found"]["images"] > 3  # the page really had more to give
    # Nothing omitted is also claimed as saved.
    omitted_urls = {u for e in max_entries for u in e["urls"]}
    saved_urls = {r["source_url"] for r in manifest["assets"] if r["ok"]}
    assert not (omitted_urls & saved_urls)


def test_grab_names_what_the_byte_cap_left_out(monkeypatch, tmp_path):
    monkeypatch.setattr(assets, "fetch_bytes", _design_fetch)
    manifest = assets.grab(BASE, str(tmp_path / "g"), max_total_mb=0)
    assert manifest["downloaded"] == 0
    assert manifest["omitted_count"] > 0
    assert all(e["reason"] == "size-cap" for e in manifest["omitted"])
    assert manifest["limits"] == {"max_assets": 120, "max_total_mb": 0, "max_tokens": 24}


def test_grab_climbs_from_a_client_rendered_shell(monkeypatch, tmp_path):
    shell = '<html><body><div id="root"></div><script src="/app.js"></script></body></html>'
    calls = []

    def climbing_fetch(url, *, backends=None, timeout=30, progress=None):
        backend = (backends or ["curl_cffi"])[0]
        calls.append((backend, url))
        if url.endswith(".css"):
            return assets.AssetResult(GRAB_CSS.encode(), "text/css", url, backend)
        if backend == "curl_cffi":
            return assets.AssetResult(shell.encode(), "text/html", url, "curl_cffi")
        if backend == "jina-html":
            return assets.AssetResult(GRAB_HTML.encode(), "text/html", url, "jina-html")
        return assets.AssetResult(GRAB_HTML.encode(), "text/html", url, "stealth-browser")

    monkeypatch.setattr(assets, "fetch_bytes", climbing_fetch)
    manifest = assets.grab(BASE, str(tmp_path / "g"))

    # The shell's one script tag is not sold as the page's asset set.
    assert manifest["page_backend"] == "jina-html"
    assert [r["backend"] for r in manifest["page_rungs"]] == ["curl_cffi", "jina-html"]
    assert manifest["page_rungs"][0]["assets_found"] < manifest["page_rungs"][1]["assets_found"]
    assert manifest["found"]["images"] > 1


def test_grab_fails_loud_when_every_rung_is_a_shell(monkeypatch, tmp_path):
    shell = '<html><body><div id="root"></div><script src="/app.js"></script></body></html>'

    def shell_fetch(url, *, backends=None, timeout=30, progress=None):
        return assets.AssetResult(shell.encode(), "text/html", url,
                                  (backends or ["curl_cffi"])[0])

    monkeypatch.setattr(assets, "fetch_bytes", shell_fetch)
    with pytest.raises(assets.AssetError) as e:
        assets.grab("https://shell.test/", str(tmp_path / "g"))
    assert "thin client-rendered shell" in str(e.value)


def test_grab_keeps_a_short_static_page(monkeypatch, tmp_path):
    # example.com-shaped: tiny, complete as served, and no shell markers.
    tiny = ('<html><head><title>Example Domain</title></head><body>'
            '<h1>Example Domain</h1><p>This domain is for use in examples.</p>'
            '</body></html>')

    def tiny_fetch(url, *, backends=None, timeout=30, progress=None):
        return assets.AssetResult(tiny.encode(), "text/html", url, "curl_cffi")

    monkeypatch.setattr(assets, "fetch_bytes", tiny_fetch)
    manifest = assets.grab("https://example.com/", str(tmp_path / "g"))
    assert manifest["title"] == "Example Domain"
    assert manifest["page_backend"] == "curl_cffi"
    assert len(manifest["page_rungs"]) == 1


def test_cli_grab_names_omitted_assets(monkeypatch, capsys, tmp_path):
    manifest = {
        "title": "Demo", "downloaded": 2, "palette": [], "fonts": [], "assets": [],
        "omitted": [{"reason": "max-assets", "kind": "images", "count": 3,
                     "urls": ["https://d.test/a.png"]}],
        "omitted_count": 3,
    }
    monkeypatch.setattr("searchts.assets.grab", lambda url, out, **kw: manifest)
    with patch("sys.argv", ["searchts", "grab", "https://demo.test/", "--out", str(tmp_path)]):
        cli.main()
    err = capsys.readouterr().err
    assert "omitted: 3 asset(s) not saved" in err
    assert "3 images (max-assets)" in err


def test_cli_grab_names_tokens_left_out(monkeypatch, capsys, tmp_path):
    manifest = {
        "title": "Demo", "downloaded": 1, "palette": [], "fonts": [], "assets": [],
        "tokens_omitted": {"spacing": 33, "radius": 1},
    }
    monkeypatch.setattr("searchts.assets.grab", lambda url, out, **kw: manifest)
    with patch("sys.argv", ["searchts", "grab", "https://demo.test/", "--out", str(tmp_path)]):
        cli.main()
    err = capsys.readouterr().err
    assert "tokens left out: 33 spacing, 1 radius" in err


def test_cli_grab_forwards_a_higher_token_cap(monkeypatch, capsys, tmp_path):
    seen = {}

    def fake_grab(url, out, **kw):
        seen.update(kw)
        return {"title": "Demo", "downloaded": 0, "palette": [], "fonts": [], "assets": []}

    monkeypatch.setattr("searchts.assets.grab", fake_grab)
    with patch("sys.argv", ["searchts", "grab", "https://demo.test/", "--out",
                            str(tmp_path), "--tokens", "80"]):
        cli.main()
    assert seen["max_tokens"] == 80


def test_cli_grab_rejects_a_token_cap_past_the_ceiling(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("searchts.assets.grab", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("grab should not run")))
    with patch("sys.argv", ["searchts", "grab", "https://demo.test/", "--out",
                            str(tmp_path), "--tokens", "201"]):
        with pytest.raises(SystemExit) as exc:
            cli.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "200" in err and "201" in err


def test_cli_grab_json_warns_on_stderr_and_keeps_stdout_clean(monkeypatch, capsys, tmp_path):
    manifest = {
        "title": "Demo", "downloaded": 2, "palette": [], "fonts": [], "assets": [],
        "omitted": [{"reason": "max-assets", "kind": "fonts", "count": 6,
                     "urls": ["https://d.test/a.woff2"]}],
        "omitted_count": 6, "page_md_error": "OSError: disk full",
    }
    monkeypatch.setattr("searchts.assets.grab", lambda url, out, **kw: manifest)
    with patch("sys.argv", ["searchts", "grab", "https://demo.test/", "--out",
                            str(tmp_path), "--json"]):
        cli.main()
    captured = capsys.readouterr()
    assert json.loads(captured.out)["omitted_count"] == 6
    assert "omitted: 6 asset(s) not saved" in captured.err
    assert "6 fonts (max-assets)" in captured.err
    assert "page.md not saved" in captured.err


def test_grab_rejects_an_unknown_kind_fail_loud(monkeypatch, tmp_path):
    monkeypatch.setattr(assets, "fetch_bytes", _design_fetch)
    with pytest.raises(assets.AssetError) as e:
        assets.grab(BASE, str(tmp_path / "g"), kinds=("images", "imagez"))
    assert "imagez" in str(e.value)


def test_grab_scripts_flag_actually_saves_scripts(monkeypatch, tmp_path):
    monkeypatch.setattr(assets, "fetch_bytes", _design_fetch)
    manifest = assets.grab(BASE, str(tmp_path / "g"), include_scripts=True)
    assert any(r["kind"] == "scripts" and r["ok"] for r in manifest["assets"])


def test_grab_kinds_include_inline_svg_by_default(monkeypatch, tmp_path):
    seen = {}

    def fake_grab(url, out, **kw):
        seen.update(kw)
        return {"title": "x", "downloaded": 0, "palette": [], "fonts": [], "assets": []}

    monkeypatch.setattr("searchts.assets.grab", fake_grab)
    with patch("sys.argv", ["searchts", "grab", "https://demo.test/", "--out", str(tmp_path)]):
        cli.main()
    assert "inline_svg" in seen["kinds"]
