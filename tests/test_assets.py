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
                        lambda url, timeout=30: assets.AssetResult(b"DATA", "image/png",
                                                                   "https://x.test/p.png", "curl_cffi"))
    out = assets.get_asset("https://x.test/p.png", str(tmp_path))
    assert out.read_bytes() == b"DATA"
    assert out.name == "p.png"


# ── grab ─────────────────────────────────────────────────────────────────────

def _fake_fetch(url, *, backends=None, timeout=30):
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
    monkeypatch.setattr("searchts.assets.get_asset", lambda url, out=None: saved)
    with patch("sys.argv", ["searchts", "get", "https://x.test/logo.png"]):
        cli.main()
    captured = capsys.readouterr()
    assert str(saved) in captured.out   # path to stdout
    assert "saved" in captured.err      # status to stderr


def test_cli_get_error_exits_nonzero(monkeypatch):
    def boom(url, out=None):
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


# ── bot-wall detection (AWS WAF), empty-body + jina-html rung ─────────────────

from searchts.unlocker import looks_blocked  # noqa: E402


def test_looks_blocked_detects_aws_waf():
    # Dribbble-style AWS WAF JS challenge: 202 + goku/awsWaf token blob.
    body = "<html><script>window.awsWafCookieDomainList=[];window.gokuProps={};</script></html>"
    assert looks_blocked(202, body) == "challenge"


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
