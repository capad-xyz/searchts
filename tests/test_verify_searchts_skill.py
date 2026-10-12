"""The verification skill is wired in, and its map matches the real CLI.

A verification skill nobody can find is the same as no skill, and a feature map
that has drifted from the commands is worse than none: it sends the next agent
to prove a flag that was renamed. These tests read the files and the argparse
tree and check the two agree.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

SKILL = ROOT / ".agents/skills/verify-searchts/SKILL.md"
FEATURES = ROOT / ".agents/skills/verify-searchts/features"

# Every verb a user runs that reaches the network or their disk. Kept here as the
# list the map has to account for, so a new verb fails this test until the map
# says how to drive it or why it is out of scope.
USER_FACING = ("read", "search", "transcribe", "grab", "get", "doctor")


def test_agents_md_points_at_the_skill_and_the_rule() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert ".agents/skills/verify-searchts/SKILL.md" in agents
    assert "## Verification" in agents
    # The link and the rule are the same instruction, not a link to a link.
    assert "Drive, do not describe" in agents
    assert "A green exit code is not a proof" in agents


def test_the_skill_has_frontmatter_so_it_registers() -> None:
    body = SKILL.read_text(encoding="utf-8")
    assert body.startswith("---\n")
    front = body.split("---", 2)[1]
    assert "name: verify-searchts" in front
    # A description that does not name the surface cannot be matched to a task.
    assert "CLI" in front and "searchts" in front


def test_the_skill_says_how_to_launch_doctor_and_clean_up() -> None:
    body = SKILL.read_text(encoding="utf-8")
    for heading in ("## Launch", "## Doctor", "## Drive", "## Evidence", "## Cleanup"):
        assert heading in body, heading
    # The two traps this repo's own drives hit.
    assert "Never pipe" in body or "never pipe" in body
    assert "searchts-grab-" in body
    # Cleanup must not eat the proof.
    assert "never removes `artifacts/`" in body


def test_every_feature_has_a_file_and_the_index_lists_it() -> None:
    index = (FEATURES / "README.md").read_text(encoding="utf-8")
    files = {p.stem for p in FEATURES.glob("*.md")} - {"README"}
    assert files == set(USER_FACING), f"map has {sorted(files)}, CLI surface is {sorted(USER_FACING)}"
    for stem in files:
        assert f"{stem}.md" in index, f"{stem} has a file but no row in the index"


def test_every_feature_file_answers_the_four_questions() -> None:
    for path in FEATURES.glob("*.md"):
        if path.name == "README.md":
            continue  # the index is not a feature
        body = path.read_text(encoding="utf-8")
        for heading in ("## Sub-features", "## How to get to it (user POV)", "## Driving it", "## Gotchas"):
            assert heading in body, f"{path.name} is missing {heading}"
        # A feature file that does not say what proves it is not a proof.
        assert "Proof" in body, f"{path.name} never says what proves it"


def _help(verb: str) -> set[str]:
    import re
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, "-m", "searchts", verb, "--help"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0, f"`searchts {verb} --help` failed: {out.stderr[-300:]}"
    return set(re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", out.stdout))


def test_the_map_drives_the_commands_that_actually_exist() -> None:
    """The map's own drive lines are checked against the CLI's own help. A flag
    renamed in argparse makes this fail, rather than sending the next agent to
    pass something that no longer parses."""
    import re

    for path in FEATURES.glob("*.md"):
        if path.name == "README.md":
            continue
        # Only the drive commands, not the prose examples.
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip().lstrip("-* ").strip("`")
            if "searchts " not in line or "--help" in line:
                continue
            m = re.search(r"searchts ([a-z-]+)", line)
            if not m or m.group(1) not in USER_FACING:
                continue
            verb = m.group(1)
            flags = {f for f in re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", line) if f != "--help"}
            if not flags:
                continue
            help_flags = _help(verb)
            for flag in flags:
                assert flag in help_flags, f"{path.name}: `searchts {verb}` has no {flag}, and the map tells agents to pass it"


def test_the_output_flag_exists_on_the_two_that_need_it() -> None:
    """`transcribe` and `get` write files, and both feature files' proofs are "a
    file exists at the path you named". If `-o` goes, both proofs stop working."""
    for verb in ("transcribe", "get"):
        assert "--output" in _help(verb), f"`searchts {verb}` lost --output"


def test_the_map_says_what_is_not_covered_yet() -> None:
    """An honest map names its holes. A map that claims to be complete is not
    trusted, and the MCP surface genuinely is not driven here yet."""
    index = (FEATURES / "README.md").read_text(encoding="utf-8")
    assert "## What this map does not cover" in index
    assert "MCP" in index


def test_evidence_is_not_committed() -> None:
    """Proof artifacts are per-run. The durable record is the note in each feature
    file, so a drive does not leave megabytes of raw JSON in the repo."""
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".agents/skills/verify-searchts/artifacts/" in gitignore
