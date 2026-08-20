# -*- coding: utf-8 -*-
"""Network-free tests for the unlocker benchmark harness.

`unlocker.fetch` is mocked, so these exercise the scoring/rendering logic without
touching the network.
"""

from unittest.mock import patch

from benchmarks import run as bench
from benchmarks.cases import Case, load_cases
from searchts.unlocker import FetchResult, UnlockerError


def test_run_benchmark_records_success_and_failure():
    cases = [
        Case("ok", "https://ok.test", "control"),
        Case("bad", "https://bad.test", "cloudflare-fronted"),
    ]

    def fake_fetch(url, **kwargs):
        if "ok" in url:
            return FetchResult("curl_cffi", "x" * 5000, 200)
        raise UnlockerError(url, [("curl_cffi", "http-403"), ("jina-reader", "blocked")])

    with patch("searchts.unlocker.fetch", side_effect=fake_fetch):
        results = bench.run_benchmark(cases)

    ok, bad = results
    assert ok["ok"] and ok["backend"] == "curl_cffi" and ok["chars"] == 5000
    assert not bad["ok"] and bad["backend"] is None and "403" in bad["error"]


def test_summarize_computes_pass_rate_and_tiers():
    results = [
        {
            "name": "a",
            "url": "u",
            "category": "control",
            "ok": True,
            "backend": "curl_cffi",
            "status": 200,
            "chars": 5000,
            "seconds": 0.1,
            "error": None,
        },
        {
            "name": "b",
            "url": "u2",
            "category": "cloudflare-fronted",
            "ok": False,
            "backend": None,
            "status": None,
            "chars": 0,
            "seconds": 0.2,
            "error": "blocked",
        },
    ]
    s = bench.summarize(results)
    assert s["total"] == 2 and s["passed"] == 1 and abs(s["pass_rate"] - 0.5) < 1e-9
    assert s["by_tier"]["curl_cffi"] == 1
    assert s["by_category"]["cloudflare-fronted"] == {"passed": 0, "total": 1}


def test_render_markdown_has_headline_and_rows():
    results = [
        {
            "name": "a",
            "url": "u",
            "category": "control",
            "ok": True,
            "backend": "curl_cffi",
            "status": 200,
            "chars": 5000,
            "seconds": 0.1,
            "error": None,
        },
        {
            "name": "b",
            "url": "u2",
            "category": "datadome",
            "ok": False,
            "backend": None,
            "status": None,
            "chars": 0,
            "seconds": 0.2,
            "error": "blocked",
        },
    ]
    md = bench.render_markdown(results, bench.summarize(results))
    assert "# Unlocker benchmark" in md
    assert "50%" in md
    assert "curl_cffi" in md
    assert "benchmarks/README.md#interpret-the-scorecard" in md
    assert "## By category" in md
    assert "- `control`: 1/1 (100%)" in md
    assert "- `datadome`: 0/1 (0%)" in md


def test_load_cases_returns_defaults():
    cases = load_cases()
    assert cases and all(isinstance(c, Case) for c in cases)
    assert any(c.category == "control" for c in cases)


def test_thin_content_is_not_a_pass():
    from searchts.unlocker import _MIN_CHARS

    short = Case("thin", "https://thin.test", "control")
    allowed = Case("thin-ok", "https://thin.test", "control", allow_thin=True)
    fat = Case("fat", "https://fat.test", "control")

    calls = []

    def fake_fetch(url, **kwargs):
        calls.append(kwargs)
        if "fat" in url:
            return FetchResult("curl_cffi", "x" * _MIN_CHARS, 200)
        return FetchResult("curl_cffi", "x" * 35, 200)

    with patch("searchts.unlocker.fetch", side_effect=fake_fetch):
        thin = bench.run_case(short)
        opted = bench.run_case(allowed)
        enough = bench.run_case(fat)

    assert thin["ok"] is False
    assert thin["backend"] == "curl_cffi"
    assert thin["chars"] == 35
    assert "thin content" in thin["error"]
    assert opted["ok"] is True and opted["error"] is None
    assert enough["ok"] is True and enough["chars"] == _MIN_CHARS
    assert calls[0]["min_chars"] == _MIN_CHARS
    assert calls[1]["min_chars"] == 0
    assert calls[2]["min_chars"] == _MIN_CHARS


def test_load_cases_honors_allow_thin(tmp_path):
    extra = tmp_path / "cases.local.json"
    extra.write_text(
        '[{"name": "short", "url": "https://s.test", "category": "control", "allow_thin": true}]',
        encoding="utf-8",
    )
    loaded = load_cases(str(extra))
    assert any(c.name == "short" and c.allow_thin is True for c in loaded)
