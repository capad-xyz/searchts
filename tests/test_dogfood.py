import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))


import dogfood  # noqa: E402


def test_a_healthy_extract_is_a_read():
    assert dogfood._classify("x" * 5000, 200, "curl_cffi", "") == "read"


def test_a_refusal_is_blocked_not_an_error():
    """A 403 is correct behaviour, not a failure of the tool."""
    assert dogfood._classify("", 403, "", "") == "blocked"


def test_a_wall_in_the_error_string_counts_as_blocked():
    assert dogfood._classify("", None, "", "all backends failed: cookie-wall") == "blocked"
    assert dogfood._classify("", None, "", "curl_cffi: http-403") == "blocked"


def test_an_unknown_failure_is_an_error_not_a_wall():
    """So drift reports the truth rather than blaming the site."""
    assert dogfood._classify("", None, "", "TypeError: something broke") == "error"


def test_a_short_extract_is_thin_even_on_a_200():
    assert dogfood._classify("x" * 499, 200, "curl_cffi", "") == "thin"


def test_probe_never_raises(monkeypatch):
    """One unreachable site must not abort a sweep of twenty."""

    def boom(url, **kw):
        raise RuntimeError("kaboom")

    monkeypatch.setattr("searchts.unlocker.fetch", boom)
    row = dogfood.probe({"url": "https://x.test/", "expect": "read"})
    assert row["outcome"] == "error"
    assert "kaboom" in row["error"]
    assert row["chars"] == 0


def test_probe_records_timing_and_counts(monkeypatch):
    from searchts.unlocker import FetchResult

    monkeypatch.setattr(
        "searchts.unlocker.fetch",
        lambda url, **kw: FetchResult("curl_cffi", "a\nb\n\nc", 200),
    )
    row = dogfood.probe({"url": "https://x.test/", "expect": "read"})
    assert row["chars"] == 6
    assert row["lines"] == 3, "blank lines must not count as content"
    assert row["seconds"] >= 0
    # Six characters is under THIN_CHARS, so this is a stub and the tool is
    # right to say so. Expecting "read" here would be asserting the wrong thing.
    assert row["outcome"] == "thin"
    assert row["matches_expectation"] is False


def test_diff_fires_on_outcome_change(tmp_path):
    """The whole point: text churn daily, outcome should not."""
    baseline = tmp_path / "b.json"
    baseline.write_text(
        json.dumps(
            {"probes": [{"url": "https://x.test/", "outcome": "blocked", "chars": 0}]}
        ),
        encoding="utf-8",
    )
    rows = [{"url": "https://x.test/", "outcome": "read", "chars": 9000}]
    changes = dogfood.diff(rows, baseline)
    assert changes == ["https://x.test/: blocked -> read"]


def test_diff_ignores_character_count(tmp_path):
    baseline = tmp_path / "b.json"
    baseline.write_text(
        json.dumps({"probes": [{"url": "https://x.test/", "outcome": "read", "chars": 9000}]}),
        encoding="utf-8",
    )
    rows = [{"url": "https://x.test/", "outcome": "read", "chars": 12000}]
    assert dogfood.diff(rows, baseline) == []


def test_diff_skips_urls_the_baseline_never_saw(tmp_path):
    baseline = tmp_path / "b.json"
    baseline.write_text(json.dumps({"probes": []}), encoding="utf-8")
    rows = [{"url": "https://new.test/", "outcome": "read"}]
    assert dogfood.diff(rows, baseline) == []


def test_an_unreadable_baseline_is_reported_not_silently_ignored(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    changes = dogfood.diff([{"url": "https://x.test/", "outcome": "read"}], bad)
    assert changes and "baseline unreadable" in changes[0]


def test_report_counts_drift_and_latency():
    rows = [
        {"outcome": "read", "matches_expectation": True, "seconds": 1.0},
        {"outcome": "read", "matches_expectation": True, "seconds": 3.0},
        {"outcome": "blocked", "matches_expectation": False, "seconds": 2.0},
    ]
    s = dogfood.report(rows)
    assert s["probes"] == 3
    assert s["drift"] == 1
    assert s["read"] == 2
    assert s["median_read_seconds"] == 3.0
    assert s["max_read_seconds"] == 3.0


def test_sweep_progress_goes_to_stderr_not_stdout(capsys, monkeypatch):
    """P4.6, and it applies because this imports searchts.unlocker.

    A probe can sit well over a second (gitlab reads in 7-15s), so progress on
    stdout would corrupt `--json` piped into jq. Found by Hare on #343.
    """
    monkeypatch.setattr(
        dogfood,
        "probe",
        lambda case: {
            "url": case["url"], "expect": case["expect"], "corpus": "",
            "outcome": "read", "chars": 1234, "lines": 5, "seconds": 1.0,
            "matches_expectation": True,
        },
    )
    dogfood.sweep(["browser"])
    captured = capsys.readouterr()
    assert captured.out == "", f"stdout must stay pipeable, got {captured.out!r}"
    assert "browser" in captured.err


def test_every_corpus_entry_declares_an_expectation():
    """A probe with no expectation cannot produce drift, so it is decoration."""
    for name, cases in dogfood.CORPORA.items():
        assert cases, f"corpus {name} is empty"
        for case in cases:
            assert case.get("expect") in ("read", "blocked", "thin"), case
            assert case.get("url", "").startswith("https://"), case


def test_walled_corpus_entries_expect_to_be_blocked():
    """The inversion that makes drift worth alerting on."""
    for case in dogfood.CORPORA["walled"]:
        assert case["expect"] == "blocked", case
    for case in dogfood.CORPORA["browser"]:
        assert case["expect"] == "read", "the browser rung must keep working"