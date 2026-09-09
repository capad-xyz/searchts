import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import hare_r1  # noqa: E402


def test_classify_skips_full_matrix_and_hare_job() -> None:
    runs = [
        {"name": "ci / test-full", "status": "completed", "conclusion": "skipped"},
        {"name": "ci / wheel-gate", "status": "completed", "conclusion": "skipped"},
        {"name": "hare / r1", "status": "in_progress", "conclusion": None},
        {"name": "ci / test", "status": "completed", "conclusion": "success"},
        {"name": "ci / lint", "status": "completed", "conclusion": "success"},
    ]
    state, _ = hare_r1.classify_checks(runs)
    assert state == "ok"


def test_classify_red_test_is_fail() -> None:
    runs = [
        {"name": "ci / test", "status": "completed", "conclusion": "failure"},
        {"name": "ci / lint", "status": "completed", "conclusion": "success"},
    ]
    state, notes = hare_r1.classify_checks(runs)
    assert state == "fail"
    assert any("test" in n for n in notes)


def test_classify_empty_is_pending() -> None:
    state, notes = hare_r1.classify_checks([])
    assert state == "pending"
    assert notes


def test_classify_does_not_eat_share_named_jobs() -> None:
    runs = [
        {"name": "ci / share-extractors", "status": "completed", "conclusion": "failure"},
        {"name": "hare / r1", "status": "in_progress", "conclusion": None},
    ]
    state, notes = hare_r1.classify_checks(runs)
    assert state == "fail"
    assert any("share-extractors" in n for n in notes)


def test_parse_plus_lines_stops_at_next_file_header() -> None:
    diff = """\
diff --git a/foo.py b/foo.py
--- a/foo.py
+++ b/foo.py
@@ -1,1 +1,2 @@
 keep
+new
diff --git a/bar.py b/bar.py
index 1111111..2222222 100644
--- a/bar.py
+++ b/bar.py
@@ -1,1 +1,1 @@
 only
"""
    plus = hare_r1.parse_plus_lines(diff)
    assert plus["foo.py"] == {1, 2}
    assert plus["bar.py"] == {1}


def test_normalize_keeps_dotfile_paths() -> None:
    out = hare_r1.normalize_findings(
        [{"sev": "real", "path": "./.github/workflows/hare.yml", "line": 21}]
    )
    assert out[0]["path"] == ".github/workflows/hare.yml"


def test_intent_hold_on_red_even_without_findings() -> None:
    assert hare_r1.intent_for("fail", []) == "hold"
    assert hare_r1.intent_for("pending", []) == "hold"
    assert hare_r1.intent_for("ok", []) == "ship"
    assert hare_r1.intent_for("ok", [{"sev": "skip"}]) == "ship"
    assert hare_r1.intent_for("ok", [{"sev": "real"}]) == "hold"


def test_parse_plus_lines_counts_new_file_side() -> None:
    diff = """\
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
 keep
-old
+new
 ctx
"""
    plus = hare_r1.parse_plus_lines(diff)
    assert "foo.py" in plus
    # +1 keep, +2 new, +3 ctx
    assert plus["foo.py"] == {1, 2, 3}


def test_filter_drops_lines_not_in_diff() -> None:
    plus = {"foo.py": {10}}
    findings = hare_r1.normalize_findings(
        [
            {"sev": "real", "path": "foo.py", "line": 10, "issue": "bad"},
            {"sev": "real", "path": "foo.py", "line": 99, "issue": "ghost"},
            {"sev": "skip", "path": "nope.py", "line": 1, "issue": "nope"},
        ]
    )
    kept = hare_r1.filter_bubbles(findings, plus)
    assert len(kept) == 1
    assert kept[0]["line"] == 10


def test_ghost_real_stays_in_table_and_holds() -> None:
    findings = hare_r1.normalize_findings(
        [{"sev": "real", "path": "foo.py", "line": 99, "issue": "ghost"}]
    )
    assert hare_r1.filter_bubbles(findings, {"foo.py": {10}}) == []
    assert hare_r1.intent_for("ok", findings) == "hold"
    body = hare_r1.render_comment("nous:x", "low", "hold", findings, "ok", [])
    assert "foo.py:99" in body
    assert "| **Intent** | hold |" in body


def test_extract_json_from_fence() -> None:
    raw = 'noise\n```json\n{"effort":"low","findings":[]}\n```\n'
    data = hare_r1.extract_json(raw)
    assert data == {"effort": "low", "findings": []}


def test_comment_has_token_and_no_em_dash() -> None:
    body = hare_r1.render_comment("nous:x", "low", "ship", [], "ok", [])
    assert body.startswith(hare_r1.TOKEN)
    assert "\u2014" not in body
    assert "**Intent**" in body


def test_bubble_labeled_not_author() -> None:
    body = hare_r1.bubble_body("skip", "nit")
    assert body.startswith(hare_r1.TOKEN)
    assert "not the PR author" in body
    assert "**skip**" in body
