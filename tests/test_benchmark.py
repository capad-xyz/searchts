# -*- coding: utf-8 -*-
"""Network-free tests for the unlocker benchmark harness.

`unlocker.fetch` is mocked, so these exercise the scoring/rendering logic without
touching the network. Cases are tagged `smoke` vs `walled` and the runner can be
filtered with `load_cases(suite=)` and `python -m benchmarks.run --suite`.
"""

from unittest.mock import patch

import pytest

from benchmarks import run as bench
from benchmarks.cases import Case, load_cases
from searchts.unlocker import FetchResult, UnlockerError


def _ok_router(ok_urls):
    def fake_fetch(url, **kwargs):
        if any(tok in url for tok in ok_urls):
            return FetchResult("curl_cffi", "x" * 5000, 200)
        raise UnlockerError(url, [("curl_cffi", "http-403"), ("jina-reader", "blocked")])

    return fake_fetch


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
            "suite": "smoke",
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
            "suite": "walled",
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
    # per-suite pass rates
    assert s["by_suite"]["smoke"]["passed"] == 1 and s["by_suite"]["smoke"]["total"] == 1
    assert s["by_suite"]["walled"]["passed"] == 0 and s["by_suite"]["walled"]["total"] == 1
    assert abs(s["by_suite"]["walled"]["pass_rate"] - 0.0) < 1e-9


def test_render_markdown_has_two_suite_sections():
    results = [
        {
            "name": "a",
            "url": "u",
            "category": "control",
            "suite": "smoke",
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
            "suite": "walled",
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
    assert "## Smoke" in md
    assert "## Walled" in md
    # per-suite rates, not a single misleading 50%
    assert "100%" in md
    assert "0%" in md
    assert "curl_cffi" in md
    assert "benchmarks/README.md#interpret-the-scorecard" in md
    assert "## Smoke — by category" in md
    assert "- `control`: 1/1 (100%)" in md
    assert "## Walled — by category" in md
    # walled rate is honestly 0%
    assert "- `datadome`: 0/1 (0%)" in md


def test_render_markdown_walled_rate_can_be_zero():
    results = [
        {
            "name": "w1",
            "url": "u1",
            "category": "linkedin",
            "suite": "walled",
            "ok": False,
            "backend": None,
            "status": None,
            "chars": 0,
            "seconds": 1.0,
            "error": "blocked",
        },
        {
            "name": "w2",
            "url": "u2",
            "category": "datadome",
            "suite": "walled",
            "ok": False,
            "backend": None,
            "status": None,
            "chars": 0,
            "seconds": 1.0,
            "error": "blocked",
        },
    ]
    s = bench.summarize(results)
    assert s["by_suite"]["walled"]["pass_rate"] == 0.0
    md = bench.render_markdown(results, s)
    assert "0%" in md
    assert "Walled" in md


def test_load_cases_returns_defaults():
    cases = load_cases()
    assert cases and all(isinstance(c, Case) for c in cases)
    assert any(c.category == "control" for c in cases)


def test_load_cases_defaults_are_smoke():
    cases = load_cases()
    smoke = [c for c in cases if c.suite == "smoke"]
    walled = [c for c in cases if c.suite == "walled"]
    assert smoke and all(c.suite == "smoke" for c in smoke)
    assert walled and all(c.suite == "walled" for c in walled)
    # stable names from the brief
    names = {c.name for c in walled}
    for expected in {
        "reddit-hot",
        "reddit-comments",
        "linkedin-feed",
        "g2-cloudflare",
        "datadome-co",
        "x-home",
        "booking-home",
    }:
        assert expected in names, expected


def test_load_cases_suite_filter():
    smoke = load_cases(suite="smoke")
    walled = load_cases(suite="walled")
    assert smoke and all(c.suite == "smoke" for c in smoke)
    assert walled and all(c.suite == "walled" for c in walled)
    # no overlap
    assert not (set(c.name for c in smoke) & set(c.name for c in walled))


def test_load_cases_suite_all_equals_default():
    all_cases = load_cases(suite="all")
    default = load_cases()
    assert {c.name for c in all_cases} == {c.name for c in default}
    assert any(c.suite == "smoke" for c in all_cases)
    assert any(c.suite == "walled" for c in all_cases)


def test_load_cases_invalid_suite_raises():
    with pytest.raises(ValueError):
        load_cases(suite="bogus")
    for ok in (None, "smoke", "walled", "all"):
        load_cases(suite=ok)


def test_case_rejects_unknown_suite():
    with pytest.raises(ValueError):
        Case("x", "https://x.test", "open", suite="staging")


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


def test_load_cases_extra_defaults_to_walled(tmp_path):
    extra = tmp_path / "cases.local.json"
    extra.write_text(
        '[{"name": "priv", "url": "https://p.test", "category": "datadome"}]',
        encoding="utf-8",
    )
    loaded = load_cases(str(extra))
    priv = next(c for c in loaded if c.name == "priv")
    assert priv.suite == "walled"


def test_walled_run_all_fail_records_zero_rate():
    cases = [
        Case("w1", "https://w1.test", "linkedin", "", False, "walled"),
        Case("w2", "https://w2.test", "datadome", "", False, "walled"),
    ]

    def fake_fetch(url, **kwargs):
        raise UnlockerError(url, [("curl_cffi", "blocked")])

    with patch("searchts.unlocker.fetch", side_effect=fake_fetch):
        results = bench.run_benchmark(cases)
    s = bench.summarize(results)
    assert s["by_suite"]["walled"]["passed"] == 0
    assert s["by_suite"]["walled"]["total"] == 2
    assert s["by_suite"]["walled"]["pass_rate"] == 0.0
    assert all(not r["ok"] for r in results)
