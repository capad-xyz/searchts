import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import hare_r1  # noqa: E402


def test_llm_timeout_is_one_minute() -> None:
    assert hare_r1.LLM_TIMEOUT_SEC == 60


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
    assert "**hold**" in body


def test_extract_json_from_fence() -> None:
    raw = 'noise\n```json\n{"effort":"low","findings":[]}\n```\n'
    data = hare_r1.extract_json(raw)
    assert data == {"effort": "low", "findings": []}


def test_comment_has_token_and_no_em_dash() -> None:
    body = hare_r1.render_comment("nous:x", "low", "ship", [], "ok", [])
    assert body.startswith(hare_r1.TOKEN)
    assert "\u2014" not in body
    assert "**ship**" in body
    assert "`nous:x`" in body
    assert "**Name**" not in body
    assert "**Purpose**" not in body
    assert "Hare · R1" not in body
    assert "| **Intent** |" not in body


def test_bubble_is_token_plus_label() -> None:
    body = hare_r1.bubble_body("skip", "nit")
    assert body.startswith(hare_r1.TOKEN)
    assert "Hare" not in body
    assert "not the PR author" not in body
    assert "**skip**" in body


def test_run_nags_on_crash(monkeypatch: object) -> None:
    posted: list[str] = []

    def fake_needed(owner: str, repo: str, n: int, token: str, why: str) -> None:
        posted.append(why)

    def boom(*_a: object, **_k: object) -> int:
        raise RuntimeError("boom")

    monkeypatch.setenv("GITHUB_TOKEN", "t")  # type: ignore[attr-defined]
    monkeypatch.setenv("GITHUB_REPOSITORY", "capad-xyz/searchts")  # type: ignore[attr-defined]
    monkeypatch.setenv("PR_NUMBER", "147")  # type: ignore[attr-defined]
    monkeypatch.setattr(hare_r1, "post_needed", fake_needed)
    monkeypatch.setattr(hare_r1, "_hare_once", boom)
    assert hare_r1.run() == 0
    assert posted and posted[0].startswith("crash:")
    assert "boom" in posted[0]


def test_csv_models_splits_and_override(monkeypatch: object) -> None:
    monkeypatch.delenv("HARE_OR_MODEL", raising=False)  # type: ignore[attr-defined]
    assert hare_r1._csv_models("HARE_OR_MODEL", "a, b ,c") == ["a", "b", "c"]
    monkeypatch.setenv("HARE_OR_MODEL", "only-one")  # type: ignore[attr-defined]
    assert hare_r1._csv_models("HARE_OR_MODEL", "a,b") == ["only-one"]
    assert "qwen/qwen3.8-27b:free" in hare_r1.HARE_OR_DEFAULT.split(",")
    assert hare_r1.HARE_ZEN_DEFAULT == "ling-3.0-flash-fin-free"


def test_short_fail_hides_provider_json() -> None:
    raw = (
        'nous:poolside/laguna-s-2.1: LLM 401 https://x poolside/laguna-s-2.1: '
        '{"status":401,"message":"Your API key is invalid, blocked or out of funds."}'
    )
    assert hare_r1._short_fail(raw) == "nous: key invalid or empty"
    rate = (
        "openrouter:poolside/laguna-s-2.1:free: LLM 429 "
        '{"error":{"message":"temporarily rate-limited upstream"}}'
    )
    assert hare_r1._short_fail(rate) == "openrouter: rate limited"
    zen = (
        "zen:ling-3.0-flash-fin-free: LLM 403 "
        '{"type":"FreeTierError","message":"OpenCode\'s free tier can only be used from within OpenCode"}'
    )
    assert hare_r1._short_fail(zen) == "zen: free tier is TUI-only"


def test_needed_body_is_graceful_and_offers_retry() -> None:
    why = (
        "nous:x: LLM 401 {\"status\":401} | "
        "openrouter:y: LLM 429 rate-limited | "
        "zen:z: LLM 403 FreeTierError within OpenCode"
    )
    body = hare_r1.needed_body(why)
    assert body.startswith(hare_r1.NEEDED)
    assert "/hare" in body
    assert "not a review" in body.lower()
    assert "Run workflow" in body
    assert '{"status"' not in body
    assert "key invalid or empty" in body
    assert "rate limited" in body
    assert "TUI-only" in body
    assert "\u2014" not in body


def test_deliver_review_posts_pr_review(monkeypatch: object) -> None:
    calls: list[tuple[str, str]] = []

    def fake(method: str, path: str, token: str, body: object = None, **_k: object) -> dict:
        calls.append((method, path))
        return {}

    monkeypatch.setattr(hare_r1, "github_api", fake)
    out = hare_r1.deliver_review("o", "r", 1, "t", "sha", hare_r1.TOKEN + "\n**ship**", [])
    assert out == "review"
    assert calls == [("POST", "/repos/o/r/pulls/1/reviews")]


def test_deliver_review_retries_summary_only(monkeypatch: object) -> None:
    n = {"i": 0}

    def fake(method: str, path: str, token: str, body: object = None, **_k: object) -> dict:
        n["i"] += 1
        if n["i"] == 1:
            raise RuntimeError("422 bad line")
        assert isinstance(body, dict) and "comments" not in body
        return {}

    monkeypatch.setattr(hare_r1, "github_api", fake)
    bubbles = [{"path": "a.py", "line": 1, "side": "RIGHT", "body": "x"}]
    assert hare_r1.deliver_review("o", "r", 1, "t", "sha", hare_r1.TOKEN, bubbles) == "summary"


def test_deliver_review_nags_when_reviews_api_dead(monkeypatch: object) -> None:
    posted: list[str] = []

    def fake_api(method: str, path: str, token: str, body: object = None, **_k: object) -> dict:
        if "reviews" in path:
            raise RuntimeError("503")
        if isinstance(body, dict):
            posted.append(str(body.get("body") or ""))
        return {}

    monkeypatch.setattr(hare_r1, "github_api", fake_api)
    assert (
        hare_r1.deliver_review("o", "r", 1, "t", "sha", hare_r1.TOKEN + "\n**ship**", [])
        == "needed"
    )
    assert posted and posted[0].startswith(hare_r1.NEEDED)
    assert "**ship**" not in posted[0]


def test_already_reviewed_same_sha(monkeypatch: object) -> None:
    def fake(method: str, path: str, token: str, body: object = None, **_k: object) -> object:
        assert "reviews" in path
        return [
            {"commit_id": "aaa", "body": hare_r1.TOKEN + "\n**ship**"},
            {"commit_id": "bbb", "body": "unrelated"},
        ]

    monkeypatch.setattr(hare_r1, "github_api", fake)
    assert hare_r1.already_reviewed("o", "r", 1, "t", "aaa") is True
    assert hare_r1.already_reviewed("o", "r", 1, "t", "bbb") is False
    assert hare_r1.already_reviewed("o", "r", 1, "t", "ccc") is False


def test_already_reviewed_ignores_empty_sha(monkeypatch: object) -> None:
    monkeypatch.setattr(hare_r1, "github_api", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no net")))
    assert hare_r1.already_reviewed("o", "r", 1, "t", "") is False
