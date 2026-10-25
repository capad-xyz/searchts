# -*- coding: utf-8 -*-
"""Generate the agent-facing command surfaces from the live CLI.

The parser in :func:`searchts.cli.build_parser` and the metadata in
:mod:`searchts.catalog` are the source. This module writes:

- ``docs/cli.md`` in full
- the marked block in ``llms.txt``
- the marked block in both ``searchts/skill/SKILL.md`` and ``SKILL_en.md``

Run ``python -m searchts.helpgen --write`` after changing a command, a flag,
an example or an exit code. ``--check`` is what CI runs: it writes nothing and
exits 1 naming every stale file. A hand edit to a generated block is therefore
caught before it ships.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Sequence

from searchts import __version__, catalog
from searchts.cli import build_parser

BEGIN = "<!-- BEGIN GENERATED COMMANDS (python -m searchts.helpgen --write) -->"
END = "<!-- END GENERATED COMMANDS -->"

MARKED_FILES = (
    ("llms.txt", "llms"),
    ("searchts/skill/SKILL.md", "skill"),
    ("searchts/skill/SKILL_en.md", "skill"),
)
CLI_DOC = "docs/cli.md"
CLI_DOC_URL = "https://github.com/capad-xyz/searchts/blob/main/docs/cli.md"


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> List[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |")
    return lines


def _flag_cell(flag: dict) -> str:
    label = ", ".join(f"`{item}`" for item in flag["option_strings"])
    if flag["metavar"]:
        label += f" {flag['metavar']}"
    if flag["deprecated"]:
        label += " (deprecated)"
    if flag["legacy"]:
        label += " (legacy)"
    return label


def _flag_notes(flag: dict) -> str:
    bits = [flag["help"]] if flag["help"] else []
    if flag["choices"]:
        bits.append("Choices: " + ", ".join(flag["choices"]) + ".")
    if flag["default"] not in (None, False, "", []):
        bits.append(f"Default: `{flag['default']}`.")
    if flag["required"]:
        bits.append("Required.")
    return " ".join(bits)


def _command_section(record: dict) -> List[str]:
    lines = [f"### `{record['name']}`", ""]
    lines.append(record["description"] or "No description.")
    body = " ".join(record["body"]).strip()
    if body:
        lines.append(body)
    if record["aliases"]:
        lines.append(
            "Alias: " + ", ".join(f"`{alias}`" for alias in record["aliases"]) + "."
        )
    if record["deprecated"]:
        lines.append("**Deprecated.**")
    if record["legacy"]:
        lines.append("**Legacy form.**")
    for note in record["notes"]:
        lines.append(f"- {note}")
    lines += ["", "```bash", record["usage"], "```", ""]
    if record["positionals"]:
        lines += _table(
            ["Argument", "Description"],
            [
                (f"`{item['metavar']}`", item["help"] or "")
                for item in record["positionals"]
            ],
        )
        lines.append("")
    if record["flags"]:
        lines += _table(
            ["Flag", "Description"],
            [(_flag_cell(flag), _flag_notes(flag)) for flag in record["flags"]],
        )
        lines.append("")
    if record["examples"]:
        lines += ["Examples:", "", "```bash"]
        lines += record["examples"]
        lines += ["```", ""]
    lines += _table(
        ["Exit", "Meaning"],
        [(f"`{item['code']}`", item["meaning"]) for item in record["exit_codes"]],
    )
    lines.append("")
    mcp = record["mcp"]
    if mcp["tools"]:
        lines.append("MCP: " + ", ".join(f"`{tool}`" for tool in mcp["tools"]) + ".")
        if mcp["mcp_only_params"]:
            lines.append(
                "MCP-only parameters: "
                + ", ".join(f"`{item}`" for item in mcp["mcp_only_params"])
                + "."
            )
        if mcp["cli_only_flags"]:
            lines.append(
                "CLI-only flags: "
                + ", ".join(f"`{item}`" for item in mcp["cli_only_flags"])
                + "."
            )
        for note in mcp["notes"]:
            lines.append(f"- {note}")
    elif mcp["cli_only"]:
        lines.append(f"No MCP tool: {mcp['reason']}.")
    if record["subcommands"]:
        lines.append(
            "Subcommands: "
            + ", ".join(f"`{item}`" for item in record["subcommands"])
            + "."
        )
    lines.append("")
    return lines


def render_cli_doc(payload: dict) -> str:
    lines = [
        "# searchts CLI reference",
        "",
        "> Generated from the live argparse tree by "
        "`python -m searchts.helpgen --write`. Do not edit by hand.",
        "",
        # The marker lets release-please bump this line in its release PR,
        # the way it bumps __init__.py; without it every release PR failed
        # the drift test on docs/cli.md.
        f"searchts v{payload['version']}. Machine-readable: "
        "`searchts help --json` (`searchts.help.v1`). <!-- x-release-please-version -->",
        "",
        "## Global flags",
        "",
    ]
    lines += _table(
        ["Flag", "Description"],
        [(_flag_cell(flag), _flag_notes(flag)) for flag in payload["global_flags"]],
    )
    lines += ["", "## Commands", ""]
    for record in _ordered(payload):
        lines += _command_section(record)
    return "\n".join(lines).rstrip() + "\n"


def _ordered(payload: dict) -> List[dict]:
    order = {name: index for index, name in enumerate(catalog.COMMANDS)}
    rank = {name: index for index, name in enumerate(catalog.GROUP_ORDER)}
    return sorted(
        payload["commands"],
        key=lambda record: (
            rank.get(record["group"], len(rank)),
            order.get(record["name"], len(order)),
        ),
    )


def _root_records(payload: dict) -> List[dict]:
    """The commands root help names, in root-help order."""
    by_name = {record["name"]: record for record in payload["commands"]}
    names = []
    for _, rows in catalog.root_groups():
        for label, _ in rows:
            parts = label.split()
            second = parts[1].lstrip('"') if len(parts) > 1 else ""
            name = parts[0] if second[:1] in ("<", "{") else label
            if name not in names:
                names.append(name)
    return [by_name[name] for name in names if name in by_name]


def render_llms_block(payload: dict) -> str:
    lines = ["## Commands", ""]
    rows = [
        (f"`searchts {record['name']}`", record["description"])
        for record in _root_records(payload)
    ]
    lines += _table(["Command", "What it does"], rows)
    lines += [
        "",
        "Every login verb: "
        + ", ".join(
            f"`searchts {record['name']}`"
            for record in payload["commands"]
            if record["name"].startswith("login ")
        )
        + ".",
        "",
        "MCP tools: "
        + ", ".join(f"`{tool}`" for tool in catalog.mcp_tool_names())
        + ". `read_url` has no `next_url`; use the signed `next_cursor`. "
        "MCP results and `--json` output carry `update_available`.",
        "",
        "Machine-readable catalog: `searchts help --json` (`searchts.help.v1`). "
        "Full flags, defaults and examples: "
        f"[docs/cli.md]({CLI_DOC_URL}).",
    ]
    return "\n".join(lines)


def render_skill_block(payload: dict) -> str:
    lines = ["## The commands", ""]
    rows = [
        (f"`searchts {record['name']}`", record["description"])
        for record in _root_records(payload)
    ]
    lines += _table(["Command", "What it does"], rows)
    lines += ["", "### Login verbs", ""]
    login_rows = [
        (f"`searchts {record['name']}`", record["description"])
        for record in _ordered(payload)
        if record["name"].startswith("login ")
    ]
    lines += _table(["Command", "What it does"], login_rows)
    lines += ["", "### Flags", ""]
    flag_rows = []
    for name in ("read", "grab", "search", "transcribe", "get"):
        record = next((r for r in payload["commands"] if r["name"] == name), None)
        if record is None:
            continue
        flags = [
            f"`{flag['option_strings'][0]}`"
            for flag in record["flags"]
            if flag["dest"] != "verbose"
        ]
        flag_rows.append((f"`searchts {name}`", ", ".join(flags)))
    lines += _table(["Command", "Flags"], flag_rows)
    lines += ["", "### MCP tools", ""]
    tool_rows = []
    for name, tool in catalog.MCP_TOOLS.items():
        tool_rows.append((f"`{name}`", f"`searchts {tool.command}`"))
    lines += _table(["Tool", "CLI command"], tool_rows)
    lines += [
        "",
        "MCP-only parameters and the deliberate CLI differences are listed in "
        f"[docs/cli.md]({CLI_DOC_URL}). `web_search` defaults to 5 results; CLI `-n` defaults "
        "to 10. MCP has no `provider` parameter. `read_url` has no `next_url`; "
        "use the signed `next_cursor`. MCP results and `--json` output carry "
        "`update_available`.",
        "",
        "### Exit codes",
        "",
    ]
    exit_rows = []
    seen = set()
    ordered = _ordered(payload)
    for record in ordered:
        codes = tuple((item["code"], item["meaning"]) for item in record["exit_codes"])
        if codes in seen:
            continue
        seen.add(codes)
        names = ", ".join(
            f"`{item['name']}`" for item in ordered
            if tuple((c["code"], c["meaning"]) for c in item["exit_codes"]) == codes
        )
        exit_rows.append((names, "; ".join(f"`{code}` {meaning}" for code, meaning in codes)))
    lines += _table(["Commands", "Exit codes"], exit_rows)
    lines += [
        "",
        "Run `searchts help --json` for the stable machine-readable catalog. "
        f"Full flags, defaults and examples: [docs/cli.md]({CLI_DOC_URL}).",
    ]
    return "\n".join(lines)


def render_marked(kind: str, payload: dict) -> str:
    body = render_llms_block(payload) if kind == "llms" else render_skill_block(payload)
    return f"{BEGIN}\n{body}\n{END}"


def replace_marked(text: str, generated: str, path: Path) -> str:
    start = text.find(BEGIN)
    end = text.find(END, start + 1) if start >= 0 else -1
    if start < 0 or end < 0:
        raise SystemExit(
            f"{path}: generated markers not found. Add\n{BEGIN}\n{END}\n"
            "around the command section."
        )
    return text[:start] + generated + text[end + len(END):]


def expected(root: Path) -> Dict[Path, str]:
    payload = catalog.build_catalog(build_parser(), __version__)
    out: Dict[Path, str] = {root / CLI_DOC: render_cli_doc(payload)}
    for relative, kind in MARKED_FILES:
        path = root / relative
        if not path.exists():
            raise SystemExit(f"{path}: file is missing")
        original = path.read_text(encoding="utf-8")
        out[path] = replace_marked(original, render_marked(kind, payload), path)
    return out


def check(root: Path) -> List[str]:
    stale = []
    for path, wanted in expected(root).items():
        actual = path.read_text(encoding="utf-8") if path.exists() else ""
        if actual != wanted:
            stale.append(str(path.relative_to(root)))
    return stale


def write(root: Path) -> List[str]:
    changed = []
    for path, wanted in expected(root).items():
        actual = path.read_text(encoding="utf-8") if path.exists() else ""
        if actual != wanted:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(wanted, encoding="utf-8")
            changed.append(str(path.relative_to(root)))
    return changed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m searchts.helpgen",
        description="Generate docs/cli.md, llms.txt and the SKILL command blocks.",
    )
    parser.add_argument("--root", default=".", help="Repository root (default: .)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="Rewrite stale files")
    mode.add_argument("--check", action="store_true", help="Fail when a file is stale")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.write:
        changed = write(root)
        if changed:
            print("updated: " + ", ".join(changed))
        else:
            print("all generated surfaces are current")
        return 0
    stale = check(root)
    if stale:
        print("stale generated surfaces:", file=sys.stderr)
        for item in stale:
            print(f"  {item}", file=sys.stderr)
        print(
            "Run `python -m searchts.helpgen --write` and commit the result.",
            file=sys.stderr,
        )
        return 1
    print("all generated surfaces are current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
