"""The verification skill is wired in, and its map still matches the real CLI.

A verification skill nobody can find is the same as no skill, and a map that has
drifted from the commands is worse than none: it sends the next agent to prove a
flag that was renamed. These tests read the files and ask the CLI itself, so a
renamed flag fails here rather than in the next agent's run.

The shape is not this repo's invention. It is the contract the installed
`create-verification-skill` ships in its `references/feature-map-example/README.md`:
a feature file is an H1, one paragraph, then exactly four H2 sections in a fixed
order. A generated skill that quietly grows a fifth section is a drifted one, and
that is what these tests are for.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents/skills/verify-searchts/SKILL.md"
FEATURES = ROOT / ".agents/skills/verify-searchts/features"

# Every verb a user runs that reaches the network or their disk. The map has to
# account for each one, so a new verb fails until the map says how to drive it or
# why it is out of scope.
USER_FACING = ("read", "search", "transcribe", "grab", "get", "doctor", "login")

# The feature entry contract, in order, exactly as the example specifies.
CONTRACT = (
    "## Sub-features",
    "## How to get to it (user POV)",
    "## Driving it with searchts",
    "## Gotchas",
)


def _help(command: str) -> set[str]:
    """The flags this command path really has, from the CLI itself."""
    out = subprocess.run(
        [sys.executable, "-m", "searchts", *command.split(), "--help"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0, f"`searchts {command} --help` failed: {out.stderr[-300:]}"
    return set(re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", out.stdout))


def test_agents_md_points_at_the_skill_and_the_rule() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert ".agents/skills/verify-searchts/SKILL.md" in agents
    assert "## Verification" in agents
    # The link and the rule are one instruction, not a link to a link.
    assert "Drive, do not describe" in agents
    assert "A green exit code is not a proof" in agents


def test_the_skill_has_frontmatter_so_it_registers() -> None:
    body = SKILL.read_text(encoding="utf-8")
    assert body.startswith("---\n")
    front = body.split("---", 2)[1]
    assert "name: verify-searchts" in front
    # A description that does not name the surface cannot be matched to a task.
    assert "CLI" in front and "searchts" in front


def test_the_skill_has_the_sections_the_methodology_requires() -> None:
    body = SKILL.read_text(encoding="utf-8")
    for heading in ("## Launch", "## Doctor", "## Drive", "## Evidence", "## Cleanup", "## Helpers"):
        assert heading in body, f"{heading} is missing from the skill"
    # The two traps this repo's own drives hit.
    assert "Never pipe a read" in body or "never pipe" in body.lower()
    assert "searchts-grab-" in body
    # Cleanup must not eat the proof, and the upkeep loop must be named.
    assert "never removes `artifacts/`" in body
    assert "/maintain-verification-skill" in body


def test_the_index_carries_the_methodologys_baseline_and_contract() -> None:
    index = (FEATURES / "README.md").read_text(encoding="utf-8")
    for heading in ("## Baseline preconditions", "## Driving conventions",
                    "## Proof and skip reporting", "## Feature entry contract", "## Features"):
        assert heading in index, f"{heading} is missing from the map index"


def test_every_feature_has_a_file_and_the_index_lists_it() -> None:
    index = (FEATURES / "README.md").read_text(encoding="utf-8")
    files = {p.stem for p in FEATURES.glob("*.md")} - {"README"}
    assert files == set(USER_FACING), f"map has {sorted(files)}, CLI surface is {sorted(USER_FACING)}"
    for stem in files:
        assert f"{stem}.md" in index, f"{stem} has a file but no entry in the index"


def test_every_feature_file_follows_the_four_section_contract() -> None:
    """Exactly four H2s, in order, and nothing else. This is the one that catches a
    hand-written file pretending to be a generated one."""
    for path in sorted(FEATURES.glob("*.md")):
        if path.name == "README.md":
            continue
        body = path.read_text(encoding="utf-8")
        found = re.findall(r"^(## .+)$", body, re.M)
        assert tuple(found) == CONTRACT, f"{path.name} has sections {found}, contract is {list(CONTRACT)}"
        assert body.startswith("# "), f"{path.name} has no H1"
        # An H1 then a paragraph, before the first H2.
        head = body.split("## ", 1)[0]
        assert len([ln for ln in head.splitlines() if ln.strip() and not ln.startswith("# ")]) >= 1, (
            f"{path.name} has a title and no sentence about the behavior"
        )


def test_every_feature_file_drives_from_preconditions_and_states_its_proof() -> None:
    for path in sorted(FEATURES.glob("*.md")):
        if path.name == "README.md":
            continue
        body = path.read_text(encoding="utf-8")
        assert "Preconditions:" in body, f"{path.name} has no preconditions block"
        assert "**Proof.**" in body, f"{path.name} never says what proves it"
        assert "searchts " in body, f"{path.name} never names a command"


def test_the_drive_lines_use_flags_the_cli_really_has() -> None:
    """Every flag a drive line tells an agent to pass, checked against that verb's
    own help. A renamed flag fails here rather than in the next agent's run."""
    for path in sorted(FEATURES.glob("*.md")):
        if path.name == "README.md":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip().lstrip("-* ").strip("`")
            m = re.search(r"searchts ([a-z-]+(?: [a-z-]+)*)", line)
            if not m or m.group(1).split()[0] not in USER_FACING:
                continue
            command = m.group(1)
            flags = {f for f in re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", line) if f != "--help"}
            if not flags:
                continue
            help_flags = _help(command)
            for flag in flags:
                assert flag in help_flags, f"{path.name}: `searchts {command}` has no {flag}"


def test_the_map_says_what_is_not_covered_yet() -> None:
    """An honest map names its holes, in a section it already has rather than a new
    one, so the four-section contract still holds. A map claiming completeness is
    not trusted, and the MCP surface genuinely has not been driven."""
    index = (FEATURES / "README.md").read_text(encoding="utf-8")
    assert "Not covered" in index
    assert "mcp" in index.lower()


def test_evidence_is_not_committed() -> None:
    """Proof artifacts are per-run. Keeping them would leave a drive's raw stdout in
    the repo forever; the map carries the durable finding instead."""
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".agents/skills/verify-searchts/artifacts/" in gitignore
