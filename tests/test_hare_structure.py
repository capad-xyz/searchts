"""The note's structure: what Hare may claim, and what it has to show.

Four defects, each evidenced on a real note:

1. a finding the owner called `wrong` came back. The owner killed it on #359 at
   20:32 (`/hare fate tests/test_hare_r1.py:63 wrong`); the same false finding was
   re-raised on #363 at 23:23, 01:12 and 01:53.
2. the ledger knew and the prompt did not, so the model re-derived what it was told.
3. one bubble read "PR promises a code change to `scripts/hare_r1.py` that is not in
   the diff" and was filed real, which is a remark about the description.
4. three notes claimed a test outcome none of them ran. Running that one file takes
   two seconds and disproves it.

Every string below that looks like a note is a real one, copied from those PRs, so
a change to the thresholds has to be argued against evidence rather than against a
fixture that was written to agree with it.
"""

import inspect
import io
import re
import sys
import tarfile
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import hare_ledger  # noqa: E402
import hare_r1  # noqa: E402
import pytest  # noqa: E402

# The owner's ruling on #359, comment 6101886265, 2026-10-10T20:32:05Z.
OWNER_FATE_LOC = "tests/test_hare_r1.py:63"
OWNER_FATE_WHY = (
    "The assertion is already 600, not 300: tests/test_hare_r1.py:65 reads assert "
    "hare_r1.LLM_TIMEOUT_SEC == 600, which is the new default in hare_r1.py:65 "
    '(HARE_LLM_TIMEOUT_S default "600"). CI test is green on 983490f (1269 passed), '
    "so this cannot be a failing test. Nothing to change."
)
OWNER_FATE = {"loc": OWNER_FATE_LOC, "fate": "wrong", "why": OWNER_FATE_WHY, "pr": "359", "by": "capad-xyz"}

TEST_FILE = "tests/test_hare_r1.py"

# Hare's own repeats of that finding on #363, verbatim from the notes.
REPEATS = [
    # 23:23 and 01:12, both real
    "test_hare_r1.py:65 still asserts LLM_TIMEOUT_SEC == 600, but the PR sets the default to 1,800.",
    # 01:12, real, worded differently
    "test_hare_r1.py:65 still asserts LLM_TIMEOUT_SEC == 600, but the PR sets the default to 1800 seconds.",
    # 01:53, skip
    "Test at line 65 asserts old LLM_TIMEOUT_SEC default of 600.",
]


def _f(rows, pr="359"):
    return [{**OWNER_FATE, "pr": pr}] if rows else []


# ── 1. a rejected finding does not come back ─────────────────────────────────


@pytest.mark.parametrize("issue", REPEATS)
def test_the_owners_ruling_kills_the_same_finding_reworded(issue: str) -> None:
    """Three notes, one claim. The line moved and the wording moved; the claim did
    not, so the owner's word still lands on all three."""
    finding = (TEST_FILE, 65, issue)
    assert hare_ledger.fate_matches(finding, OWNER_FATE_LOC, OWNER_FATE_WHY), issue


def test_a_ruling_does_not_reach_a_different_finding_on_the_same_line() -> None:
    """The salvaged draft matched this one: the owner's reason happens to name
    `tests/test_hare_r1.py:65` because that is where the bubble was, and that
    silenced an unrelated row. Identity is the claim, not the address."""
    unrelated = (TEST_FILE, 65, "test_hop_loop sends every provider its own options but the test only asserts two calls.")
    assert not hare_ledger.fate_matches(unrelated, OWNER_FATE_LOC, OWNER_FATE_WHY)


def test_a_ruling_does_not_reach_another_file_that_names_the_same_constant() -> None:
    same_words = ("tests/test_core.py", 65, "LLM_TIMEOUT_SEC is a module constant used by chat_complete without a guard.")
    assert not hare_ledger.fate_matches(same_words, OWNER_FATE_LOC, OWNER_FATE_WHY)


def test_the_exact_line_is_still_the_ledgers_own_key() -> None:
    """A bubble landed there and the owner ruled on it. That needs no wording to
    agree, and it is the behaviour the ledger had before."""
    assert hare_ledger.fate_matches((TEST_FILE, 63, "anything at all"), OWNER_FATE_LOC, "")
    assert not hare_ledger.fate_matches((TEST_FILE, 64, "anything at all"), OWNER_FATE_LOC, "")


def test_only_a_rejection_suppresses() -> None:
    """`fixed` is the owner saying the code changed, not that the finding was wrong."""
    fixed = {**OWNER_FATE, "fate": "fixed"}
    rows = [{"loc": f"{TEST_FILE}:65", "issue": REPEATS[0]}]
    assert hare_ledger.rejected_lines(rows, [fixed]) == []
    assert len(hare_ledger.rejected_lines(rows, [OWNER_FATE])) == 1


def test_the_rejection_is_scoped_to_the_files_it_was_about() -> None:
    rows = [{"loc": f"{TEST_FILE}:65", "issue": REPEATS[0]}, {"loc": "searchts/core.py:10", "issue": REPEATS[0]}]
    killed = hare_ledger.rejected_lines(rows, [OWNER_FATE])
    assert [k["loc"] for k in killed] == [f"{TEST_FILE}:65"]
    assert killed[0]["pr"] == "359"


def test_the_stack_is_walked_so_a_ruling_above_still_counts(monkeypatch) -> None:
    """#363 is based on `wren/hare-reasoning`, which is the head of #359, and the
    owner's ruling is a comment on #359. Reading only #363's own comments found
    nothing, which is the whole of the repeat."""

    def api(method, path, token, data=None, accept=None):
        if path.startswith("/repos/o/r/pulls?state=all&head=o:"):
            return [{"number": 359, "base": {"ref": "main"}}]
        if "/issues/359/comments" in path:
            return [{"user": {"login": "capad-xyz"}, "author_association": "OWNER", "created_at": "2026-10-10T20:32:05Z",
                     "body": f"/hare fate {OWNER_FATE_LOC} wrong {OWNER_FATE_WHY}"}]
        if "/issues/363/comments" in path:
            return []
        raise AssertionError(path)

    monkeypatch.setattr(hare_r1, "github_api", api)
    fates = hare_r1.stack_fates("o", "r", {"number": 363, "base": {"ref": "wren/hare-reasoning"}}, "t")
    assert [f["pr"] for f in fates] == ["359"]
    findings, ruled = hare_r1.drop_rejected(
        [{"path": TEST_FILE, "line": 65, "sev": "real", "issue": REPEATS[0]}], fates
    )
    assert findings == [] and ruled == [f"{TEST_FILE}:65 (owner called it wrong on #359)"]


def test_the_stack_walk_stops_at_main_and_never_raises(monkeypatch) -> None:
    def boom(method, path, token, data=None, accept=None):
        raise RuntimeError("500")

    monkeypatch.setattr(hare_r1, "github_api", boom)
    assert hare_r1.stack_prs("o", "r", {"base": {"ref": "main"}}, "t") == []
    assert hare_r1.stack_prs("o", "r", {"base": {"ref": "wren/a"}}, "t") == []


def test_the_stack_walk_stops_at_its_depth(monkeypatch) -> None:
    depth = {"n": 0}

    def api(method, path, token, data=None, accept=None):
        depth["n"] += 1
        return [{"number": depth["n"], "base": {"ref": f"wren/up{depth['n']}"}}]

    monkeypatch.setattr(hare_r1, "github_api", api)
    pr = {"base": {"ref": "wren/d1"}}
    assert len(hare_r1.stack_prs("o", "r", pr, "t", depth=2)) == 2
    assert len(hare_r1.stack_prs("o", "r", pr, "t", depth=4)) == 4


def test_a_stranger_cannot_silence_a_finding_with_a_fate() -> None:
    """A fate removes a finding, and a real finding is the one holding the merge, so
    the author list is the gate. Same reasoning as a `/hare score`."""
    assert hare_r1.is_fate_author("capad-xyz")
    assert hare_r1.is_fate_author("someone", "COLLABORATOR")
    assert not hare_r1.is_fate_author("a-stranger")
    assert not hare_r1.is_fate_author("a-stranger", "CONTRIBUTOR")


def test_nothing_is_dropped_silently(monkeypatch) -> None:
    """The fold names every finding this note is not carrying as a finding, so a
    wrong suppression is visible in the note instead of a row nobody can account
    for."""
    body = hare_r1.render_comment(
        "m", "low", "ship", [], "ok", [], "S", "abc1234", [],
        ruled=[f"{TEST_FILE}:65 (owner called it wrong on #359)"],
        refuted=[f"`{TEST_FILE}:65` - {TEST_FILE} ran here and passed"],
        demoted=["`scripts/hare_r1.py:65` - about the PR description, not the diff"],
    )
    fold = body.split("<summary>")[1]
    assert "findings dropped as already rejected by the owner: 1" in fold
    assert "findings dropped, disproved by the run above: 1" in fold
    assert "findings filed as skips because they are about the PR description: 1" in fold


def test_the_verdict_is_computed_after_the_rejections() -> None:
    """A rejected real finding must not hold a merge. Order is the whole rule."""
    src = inspect.getsource(hare_r1._hare_once)
    assert src.index("drop_rejected(") < src.index("intent = intent_for(")
    kept, _ = hare_r1.drop_rejected(
        [{"path": TEST_FILE, "line": 65, "sev": "real", "issue": REPEATS[0]}], _f(True)
    )
    assert hare_r1.intent_for("ok", kept) == "ship"


# ── 2. the prompt shows what the owner already ruled on ───────────────────────


def test_the_prompt_carries_the_rejections_with_the_owners_reason(monkeypatch) -> None:
    monkeypatch.setattr(hare_r1, "ledger_data", lambda: {})
    fates = [{**OWNER_FATE, "why": OWNER_FATE_WHY}]
    user = hare_r1.build_user("A", "t", "b", "diff", "ci", rejected=hare_r1.rejected_block("diff", fates))
    assert "## Rejected findings" in user and "#359" in user
    # The reason is the part that mattered: it is the answer to "this test breaks".
    assert "(1269 passed)" in user
    assert "Do not raise one of these again" in user


def test_a_stacks_rulings_reach_the_prompt_even_with_no_ledger(monkeypatch) -> None:
    monkeypatch.setattr(hare_r1, "ledger_data", lambda: {})
    user = hare_r1.build_user("A", "t", "b", "d", "c", rejected=hare_r1.rejected_block("d", _f(True)))
    assert "#359" in user


def test_the_ledger_contributes_its_own_rejections(monkeypatch) -> None:
    ledger = {"entries": [{"pr": 258, "findings": [
        {"loc": TEST_FILE, "sev": "real", "fate": "wrong", "issue": "asserts 600 while the diff sets 1800"},
        {"loc": "docs/x.md:3", "sev": "real", "fate": "wrong", "issue": "wrong about a doc"},
    ]}]}
    monkeypatch.setattr(hare_r1, "ledger_data", lambda: ledger)
    diff = f"--- a/{TEST_FILE}\n+++ b/{TEST_FILE}\n@@ -0,0 +1 @@\n+x = 1\n"
    block = hare_r1.rejected_block(diff, [])
    assert "#258" in block and "docs/x.md" not in block  # a file this diff does not touch


def test_no_rejections_means_no_section(monkeypatch) -> None:
    monkeypatch.setattr(hare_r1, "ledger_data", lambda: {})
    assert hare_r1.rejected_block("diff", []) == ""


def test_the_observed_run_reaches_the_prompt(monkeypatch) -> None:
    monkeypatch.setattr(hare_r1, "ledger_data", lambda: {})
    run = {"state": "pass", "files": [TEST_FILE], "summary": "266 passed in 3.10s", "detail": "", "seconds": 4.0, "note": ""}
    user = hare_r1.build_user("A", "t", "b", "d", "c", observed=hare_r1.test_run_block(run))
    assert "266 passed in 3.10s" in user and "not run" in user


def test_the_system_prompt_states_the_three_rules() -> None:
    assert "The diff decides what the change is" in hare_r1.SYSTEM
    assert 'about "description"' in hare_r1.SYSTEM
    assert "that block ran that file" in hare_r1.SYSTEM
    assert "Do not raise a finding the prompt already lists under Rejected findings" in hare_r1.SYSTEM


# ── 3. the description is not the diff ───────────────────────────────────────


def test_a_finding_about_the_description_is_not_a_real_finding() -> None:
    """Hare Bot's bubble on #363: "PR promises a code change to scripts/hare_r1.py
    that is not in the diff." Filed real, it held a merge on a remark."""
    rows = [{"sev": "real", "path": "scripts/hare_r1.py", "line": 65, "issue": "PR promises a code change to scripts/hare_r1.py that is not in the diff."}]
    kept, demoted = hare_r1.demote_description_findings(rows)
    assert [f["sev"] for f in kept] == ["skip"]
    assert "about the PR description" in demoted[0]


def test_the_row_survives_the_demotion() -> None:
    rows = [{"sev": "real", "path": "a.py", "line": 1, "issue": "PR promises a code change to a.py that is not in the diff."}]
    kept, _ = hare_r1.demote_description_findings(rows)
    assert kept[0]["issue"] == rows[0]["issue"]


def test_the_model_can_say_so_itself() -> None:
    rows = [{"sev": "real", "path": "a.py", "line": 1, "about": "description", "issue": "The checklist does not match."}]
    kept, demoted = hare_r1.demote_description_findings(rows)
    assert kept[0]["sev"] == "skip" and demoted


def test_a_finding_about_code_is_left_alone() -> None:
    """The wording fallback is timid on purpose. A finding that also says what the
    code does is about the code, and losing it would lose the merge blocker."""
    rows = [{"sev": "real", "path": "searchts/core.py", "line": 40,
             "issue": "The PR body promises a fallback, and read() returns half a page instead of raising."}]
    kept, demoted = hare_r1.demote_description_findings(rows)
    assert kept[0]["sev"] == "real" and demoted == []


def test_a_skip_about_the_description_is_left_alone() -> None:
    rows = [{"sev": "skip", "path": "a.py", "line": 1, "issue": "PR title says docs-only but the diff has code."}]
    kept, demoted = hare_r1.demote_description_findings(rows)
    assert kept == rows and demoted == []


def test_the_demotion_runs_before_the_verdict() -> None:
    src = inspect.getsource(hare_r1._hare_once)
    assert src.index("demote_description_findings(") < src.index("intent = intent_for(")


# ── 4. the tests are run, not guessed ─────────────────────────────────────────


def _head_tree(tmp_path: Path, name: str = "tests/test_sample.py", body: str = "def test_ok():\n    assert True\n") -> Path:
    root = tmp_path / "head"
    (root / "tests").mkdir(parents=True)
    (root / name).write_text(body, encoding="utf-8")
    return root


def test_the_affected_tests_are_named_from_the_diff() -> None:
    diff = (
        "--- a/tests/test_core.py\n+++ b/tests/test_core.py\n@@ -1 +1 @@\n+a\n"
        "--- a/searchts/unlocker.py\n+++ b/searchts/unlocker.py\n@@ -1 +1 @@\n+a\n"
        "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n+a\n"
    )
    assert hare_r1.affected_tests(diff) == ["tests/test_core.py", "tests/test_unlocker.py"]


def test_a_run_that_passes_is_reported_as_passing(monkeypatch, tmp_path) -> None:
    root = _head_tree(tmp_path)
    monkeypatch.setattr(hare_r1, "ensure_env", lambda base, timeout=0: "")
    run = hare_r1.run_tests(["tests/test_sample.py"], str(root))
    assert run["state"] == "pass" and run["files"] == ["tests/test_sample.py"]
    assert "1 passed" in run["summary"]


def test_a_run_that_cannot_start_is_never_reported_as_a_pass(monkeypatch, tmp_path) -> None:
    """`ok` and `could not start` must not read the same in a note whose promise is
    that its claims were observed."""
    monkeypatch.setattr(hare_r1, "ensure_env", lambda base, timeout=0: "pip install failed: boom")
    run = hare_r1.run_tests(["tests/test_sample.py"], str(_head_tree(tmp_path)))
    assert run["state"] == "error" and run["summary"] == "" and "pip install failed" in run["note"]
    assert "not run" in hare_r1.test_run_line(run, "abc1234")


def test_no_head_tree_means_no_run_and_no_claim(monkeypatch, tmp_path) -> None:
    run = hare_r1.run_tests(["tests/test_sample.py"], str(tmp_path / "nope"))
    assert run["state"] == "off"
    assert "Do not make one" in hare_r1.test_run_block(run)


def test_a_run_can_be_turned_off(monkeypatch) -> None:
    monkeypatch.setattr(hare_r1, "TESTS_ON", False)
    run = hare_r1.run_tests(["tests/test_sample.py"], "/tmp")
    assert run["state"] == "off" and run["note"] == "HARE_TESTS=0"


def test_the_fold_line_says_what_ran_before_what_it_said() -> None:
    run = {"state": "pass", "files": [TEST_FILE], "summary": "266 passed in 3.10s", "seconds": 4.4, "note": ""}
    line = hare_r1.test_run_line(run, "abc1234")
    assert line == f"- tests on `abc1234`: {TEST_FILE} -> 266 passed in 3.10s (4s)"


def test_a_run_refutes_the_finding_it_disproves() -> None:
    """The #363 repeat, on a head where CI was green and running the file took two
    seconds."""
    run = {"state": "pass", "files": [TEST_FILE], "summary": "266 passed in 3.10s"}
    rows = [{"sev": "real", "path": TEST_FILE, "line": 65,
             "issue": "test_hare_r1.py:65 still asserts LLM_TIMEOUT_SEC == 600, but the PR sets the default to 1,800."}]
    kept, refuted = hare_r1.refuted_by_run(rows, run)
    assert kept == [] and refuted and TEST_FILE in refuted[0]


def test_a_passing_run_says_nothing_about_a_test_that_cannot_fail() -> None:
    rows = [{"sev": "real", "path": TEST_FILE, "line": 300, "issue": "This test asserts nothing, so it cannot fail."}]
    kept, refuted = hare_r1.refuted_by_run(rows, {"state": "pass", "files": [TEST_FILE]})
    assert kept == rows and refuted == []


def test_only_a_pass_refutes() -> None:
    rows = [{"sev": "real", "path": TEST_FILE, "line": 65, "issue": "the test asserts old value 600 but the diff sets 1800"}]
    for state in ("fail", "collect-error", "timeout", "error", "off"):
        kept, refuted = hare_r1.refuted_by_run(rows, {"state": state, "files": [TEST_FILE]})
        assert kept == rows and refuted == [], state


def test_a_file_that_did_not_run_cannot_refute() -> None:
    rows = [{"sev": "real", "path": "tests/test_core.py", "line": 10, "issue": "the test asserts old value 600 but the diff sets 1800"}]
    kept, refuted = hare_r1.refuted_by_run(rows, {"state": "pass", "files": [TEST_FILE]})
    assert kept == rows and refuted == []


def test_a_refutation_is_never_silent() -> None:
    rows = [{"sev": "skip", "path": TEST_FILE, "line": 65, "issue": "Test at line 65 asserts old LLM_TIMEOUT_SEC default of 600."}]
    kept, refuted = hare_r1.refuted_by_run(rows, {"state": "pass", "files": [TEST_FILE]})
    assert kept == [] and "ran here and passed" in refuted[0]


def test_the_run_is_charged_to_the_review_wall_clock(monkeypatch) -> None:
    """The hop budget starts where the hops do, but the run spent wall clock before
    them and the caps are a promise about the review as a whole."""
    src = inspect.getsource(hare_r1._hare_once)
    assert "hops_start = time.time() - run_seconds" in src
    assert src.index("run_tests(") < src.index("hops_start = ")


def test_the_run_happens_before_the_prompt_is_built(monkeypatch) -> None:
    src = inspect.getsource(hare_r1._hare_once)
    assert src.index("run_tests(") < src.index("observed=test_run_block(tests)")


# ── the head tree the tests run on ───────────────────────────────────────────


def _tarball(root: str, files: dict[str, str], extra: list[tuple[str, bytes]] | None = None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, body in files.items():
            data = body.encode()
            info = tarfile.TarInfo(f"{root}/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for name, data in extra or []:
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = data.decode()
            tar.addfile(info)
    return buf.getvalue()


def _serve(monkeypatch, blob: bytes):
    class Resp:
        def read(self, n=-1):
            return blob if n < 0 else blob[:n]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(hare_r1.urllib.request, "urlopen", lambda req, timeout=0: Resp())


def test_the_head_tree_is_fetched_and_unpacked(monkeypatch, tmp_path) -> None:
    _serve(monkeypatch, _tarball("o-r-abc", {"tests/test_x.py": "def test_x():\n    assert True\n"}))
    root = hare_r1.fetch_head_tree("o", "r", "abc", "t", str(tmp_path / "dest"))
    assert root and (Path(root) / "tests/test_x.py").is_file()


def test_a_tarball_that_climbs_out_is_refused(monkeypatch, tmp_path, capsys) -> None:
    """A PR's tarball is author-controlled, so the unpack refuses anything that is
    not a plain file or directory under the destination."""
    blob = _tarball("o-r-abc", {"ok.py": "x = 1\n"}, extra=[("o-r-abc/../../escape.py", b"")])
    _serve(monkeypatch, blob)
    root = hare_r1.fetch_head_tree("o", "r", "abc", "t", str(tmp_path / "dest"))
    assert root and not (tmp_path / "escape.py").exists()


def test_a_symlink_in_the_tarball_is_refused(monkeypatch, tmp_path) -> None:
    blob = _tarball("o-r-abc", {"ok.py": "x = 1\n"}, extra=[("o-r-abc/link.py", b"/etc/passwd")])
    _serve(monkeypatch, blob)
    root = hare_r1.fetch_head_tree("o", "r", "abc", "t", str(tmp_path / "dest"))
    assert root and not (Path(root) / "link.py").exists()


def test_a_tarball_that_does_not_arrive_is_reported_not_guessed(monkeypatch, tmp_path, capsys) -> None:
    def boom(req, timeout=0):
        raise urllib.error.URLError("no route")

    monkeypatch.setattr(hare_r1.urllib.request, "urlopen", boom)
    assert hare_r1.fetch_head_tree("o", "r", "abc", "t", str(tmp_path / "dest")) == ""
    assert "not fetched" in capsys.readouterr().out  # the Action's own log, like every other line here


def test_no_sha_means_no_fetch(monkeypatch, tmp_path, capsys) -> None:
    assert hare_r1.fetch_head_tree("o", "r", "", "t", str(tmp_path / "dest")) == ""
    assert "no head sha" in capsys.readouterr().out


def test_the_head_tree_is_not_a_thing_anyone_commits() -> None:
    gitignore = (Path(__file__).resolve().parents[1] / ".gitignore").read_text(encoding="utf-8")
    assert ".hare-head/" in gitignore
    assert hare_r1.HEAD_DIR == ".hare-head"


def test_the_workflow_declares_the_run_rather_than_leaving_it_implicit() -> None:
    """A behaviour the note's whole promise rests on is a workflow env with a
    default, like every other cap, so turning it off is a visible choice."""
    wf = (Path(__file__).resolve().parents[1] / ".github/workflows/hare.yml").read_text(encoding="utf-8")
    assert re.search(r"^\s*HARE_TESTS:\s*'1'\s*$", wf, re.M)
    assert re.search(r"^\s*HARE_TEST_TIMEOUT_S:\s*'300'\s*$", wf, re.M)
    assert re.search(r"HARE_TESTS: '0'", wf)  # the off switch is documented where the switch is


# ── the ledger rebuild agrees with all of it ─────────────────────────────────


def test_the_ledger_build_records_a_fate_against_the_finding_it_meant() -> None:
    """`pr_rows` keys on `loc` today, so the salvaged draft's line window is what
    stops a finding filed at :65 from keeping fate `open` while the ledger says the
    owner ruled on it."""
    note = f"""{hare_r1.TOKEN}

### Findings

#### 🔴 real · `{TEST_FILE}:65`

**Issue:** {REPEATS[0]}

## Models

| Role | Model | Effort |
| --- | --- | --- |
| reviewer | x | low |
"""
    entry = hare_ledger.pr_rows(
        {"number": 359, "state": "open", "merged_at": None, "title": "t"},
        [{"submitted_at": "2026-10-10T00:00:00Z", "body": note, "html_url": "u"}],
        [{"user": {"login": "capad-xyz"}, "author_association": "OWNER", "created_at": "2026-10-10T20:32:05Z",
          "body": f"/hare fate {OWNER_FATE_LOC} wrong {OWNER_FATE_WHY}"}],
        [],
    )
    assert [f["fate"] for f in entry["findings"]] == ["wrong"]


def test_the_rescore_is_unchanged_and_its_trap_is_still_sprung() -> None:
    """Two things at once, because they are the same promise: the #258 finding the
    owner called wrong is never credited as real, and the numbers the owner reads
    have not moved. Detection and filing are separate questions and this change
    touches neither.
    """
    from subprocess import run

    out = run(
        [sys.executable, "scripts/hare_rescore.py"], cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=600,
    )
    assert out.returncode == 0, out.stdout[-2000:]
    assert "Trap check (#258, the known-wrong finding): clean" in out.stdout
    m = re.search(
        r"Across (\d+) answered runs: (\d+) of (\d+) expectations named, (\d+) credited as real in the right file,"
        r" (\d+) found but misfiled",
        out.stdout,
    )
    assert m, out.stdout[-800:]
    # These four numbers track the proof data in docs/proofs/, not the scoring
    # logic. Verified both ways while rebasing onto main: with this branch's own
    # proofs the row is (36, 62, 9, 11); with main's, which carry the newer
    # 2026-10-10 eval run from #360, it is (35, 62, 9, 12). One finding is filed
    # at a different path in the newer data, so it counts as misfiled rather
    # than credited. The trap check above is clean under either, which is the
    # part that would break if the identity scoring regressed.
    assert (m.group(2), m.group(3), m.group(4), m.group(5)) == ("35", "62", "9", "12")
