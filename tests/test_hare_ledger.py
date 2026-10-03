import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import hare_ledger  # noqa: E402
import hare_r1  # noqa: E402

NOTE_1 = f"""{hare_r1.TOKEN}

## Summary

S.

### Findings

#### 🔴 real · `scripts/a.py:12`

**Issue:** The retry escapes bare.

#### 🟡 skip · `docs/x.md:3`

**Issue:** A nit.

<details>
<summary>🐰 checks & computer run</summary>

- head `abc1234`
- cost: 11,670 prompt + 183 answer + 0 reasoning tokens on `gemini:gemini-3.1-flash-lite`, 17 s
- cut at the budget (seam) after 4 findings, finished by one continuation call

</details>

## Models

| Role | Model | Effort |
| --- | --- | --- |
| reviewer | Hare (GitHub App) · purpose: review and report · `gemini:gemini-3.1-flash-lite` | high |
"""

NOTE_2 = f"""{hare_r1.TOKEN}

## Summary

S2.

### Since `abc1234`

New commits only. The note on `abc1234` stays.

- 🔴 `scripts/a.py:12`: fixed
- 🟡 `docs/x.md:3`: still applies

### Findings

#### 🟡 skip · `scripts/b.py:7`

**Issue:** Another nit.

## Models

| Role | Model | Effort |
| --- | --- | --- |
| reviewer | Hare (GitHub App) · purpose: review and report · `nous:poolside/laguna-s-2.1:free` | low |
"""


def test_score_from_reads_the_owners_verdict() -> None:
    assert hare_ledger.score_from("/hare score 2 thin on the tests") == (2, "thin on the tests")
    assert hare_ledger.score_from("@hare score 5") == (5, "")
    assert hare_ledger.score_from("/hare deep") == (None, "")
    assert hare_ledger.score_from("/hare score 9 out of range") == (None, "")
    assert hare_r1.is_score("/hare score 1 missed the error path") and not hare_r1.is_score("/hare")


def test_note_meta_reads_hop_effort_cost_and_cut() -> None:
    m = hare_ledger.note_meta(NOTE_1)
    assert m["hop"] == "gemini:gemini-3.1-flash-lite" and m["effort"] == "high"
    assert m["cost"].startswith("11,670 prompt") and m["cut"].startswith("(seam) after 4 findings")
    assert hare_ledger.since_statuses(NOTE_2) == {"scripts/a.py:12": "fixed", "docs/x.md:3": "still applies"}


def test_pr_rows_follows_a_finding_from_note_to_note() -> None:
    reviews = [
        {"body": NOTE_1, "submitted_at": "2026-10-03T20:00:00Z", "html_url": "u1"},
        {"body": "not hare", "submitted_at": "2026-10-03T20:01:00Z"},
        {"body": NOTE_2, "submitted_at": "2026-10-03T21:00:00Z", "html_url": "u2"},
    ]
    comments = [{"body": "/hare score 2 thin on the tests", "user": {"login": "owner"}, "created_at": "2026-10-03T22:00:00Z"}]
    threads = [{"isResolved": True, "path": "scripts/b.py", "line": 7, "comments": {"nodes": [{"body": hare_r1.TOKEN}]}}]
    e = hare_ledger.pr_rows({"number": 7, "title": "t", "merged_at": "x", "state": "closed"}, reviews, comments, threads)
    fates = {f["loc"]: f["fate"] for f in e["findings"]}
    assert fates == {"scripts/a.py:12": "fixed", "docs/x.md:3": "still applies", "scripts/b.py:7": "resolved"}
    assert len(e["notes"]) == 2 and e["notes"][0]["hop"].startswith("gemini") and e["notes"][1]["findings"] == 1
    assert e["scores"] == [{"score": 2, "text": "thin on the tests", "by": "owner", "at": "2026-10-03T22:00:00Z"}]
    s = hare_ledger.summarize([e])
    assert s["real"] == 1 and s["real_fixed_or_resolved"] == 1 and s["score_avg"] == 2.0 and s["cut_notes"] == 1
    md = hare_ledger.render_md([e], s, "2026-10-04")
    assert "1 of 1 real findings fixed or resolved (100%)" in md and "| #7 | 2 | 1 | 2 |" in md and "thin on the tests" in md
    assert "\u2014" not in md


def test_the_ledger_primes_the_next_note(tmp_path, monkeypatch) -> None:
    reviews = [{"body": NOTE_1, "submitted_at": "2026-10-03T20:00:00Z"}, {"body": NOTE_2, "submitted_at": "2026-10-03T21:00:00Z"}]
    comments = [{"body": "/hare score 2 thin on the tests", "user": {"login": "owner"}, "created_at": "2026-10-03T22:00:00Z"}]
    e = hare_ledger.pr_rows({"number": 7, "title": "t", "state": "open"}, reviews, comments, [])
    ledger = {"entries": [e]}
    path = tmp_path / "hare-ledger.json"
    path.write_text(json.dumps(ledger), encoding="utf-8")
    monkeypatch.setattr(hare_r1, "LEDGER_PATH", str(path))
    diff = "diff --git a/scripts/a.py b/scripts/a.py\n--- a/scripts/a.py\n+++ b/scripts/a.py\n+x\n"
    block = hare_r1.ledger_block(diff)
    assert "#7 scored 2/5: thin on the tests" in block
    assert "#7 real `scripts/a.py:12` (fixed)" in block and "docs/x.md" not in block
    assert "## Ledger" in hare_r1.build_user("A", "t", "b", diff, "ok", ledger=block)
    monkeypatch.setattr(hare_r1, "LEDGER_PATH", str(tmp_path / "missing.json"))
    assert hare_r1.ledger_block(diff) == ""


def test_low_scores_with_a_reason_become_rules_in_hare_md() -> None:
    ledger = {"entries": [
        {"pr": 7, "scores": [{"score": 2, "text": "thin on the tests", "at": "2026-10-03T22:00:00Z"}, {"score": 5, "text": "good", "at": "2026-10-03T23:00:00Z"}]},
        {"pr": 9, "scores": [{"score": 1, "text": "Thin on the tests.", "at": "2026-10-04T10:00:00Z"}, {"score": 2, "text": "", "at": "2026-10-04T11:00:00Z"}]},
        {"pr": 11, "scores": [{"score": 2, "text": "missed the error path", "at": "2026-10-05T10:00:00Z"}]},
    ]}
    rules = hare_ledger.proposed_rules(ledger)
    assert rules == [
        "- missed the error path. (#11, scored 2/5 on 2026-10-05)",
        "- Thin on the tests. (#9, scored 1/5 on 2026-10-04)",
    ]  # newest first, duplicates folded on the reason, no reason means no rule, high scores are not rules
    fresh = hare_ledger.apply_rules("", rules)
    assert fresh.startswith("# HARE.md") and fresh.count(hare_ledger.RULES_START) == 1 and "missed the error path" in fresh
    owner = fresh.replace("- (none yet)", "- Always read the test file next to a changed module.")
    twice = hare_ledger.apply_rules(owner, ["- only this one. (#12, scored 1/5 on 2026-10-06)"])
    assert twice.count(hare_ledger.RULES_START) == 1 and "missed the error path" not in twice and "only this one" in twice
    assert "Always read the test file" in twice  # the owner's own lines survive the run
    assert "\u2014" not in twice
    assert "none yet: a `/hare score" in hare_ledger.apply_rules("", [])


def test_hare_md_reaches_the_model() -> None:
    user = hare_r1.build_user("A", "t", "b", "+x", "ok", hare_md="- Always read the tests.")
    assert "## HARE.md" in user and "Always read the tests." in user and user.index("## HARE.md") < user.index("## Diff")
    assert "## HARE.md" not in hare_r1.build_user("A", "t", "b", "+x", "ok")


def test_a_resolved_thread_resolves_one_finding_not_the_whole_file() -> None:
    body = NOTE_1.replace("#### 🟡 skip · `docs/x.md:3`", "#### 🟡 skip · `scripts/a.py:40`")
    reviews = [{"body": body, "submitted_at": "2026-10-03T20:00:00Z"}]
    threads = [{"isResolved": True, "path": "scripts/a.py", "line": 45, "originalLine": 40, "comments": {"nodes": [{"body": hare_r1.TOKEN}]}}]
    e = hare_ledger.pr_rows({"number": 8, "state": "open"}, reviews, [], threads)
    fates = {f["loc"]: f["fate"] for f in e["findings"]}
    assert fates == {"scripts/a.py:12": "open", "scripts/a.py:40": "resolved"}


def test_note_meta_reads_the_v1_note_shape_too() -> None:
    v1 = f"{hare_r1.TOKEN}\n\n**ship** · `nous:stealth/space-bunny-alpha` · effort low\n\nExpands the guidance.\n"
    assert hare_ledger.note_meta(v1)["hop"] == "nous:stealth/space-bunny-alpha" and hare_ledger.note_meta(v1)["effort"] == "low"
