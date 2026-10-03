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
    threads = [{"isResolved": True, "path": "scripts/b.py", "comments": {"nodes": [{"body": hare_r1.TOKEN}]}}]
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
