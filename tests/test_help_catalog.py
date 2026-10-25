# -*- coding: utf-8 -*-
"""The help catalog, the generated surfaces and the drift guards.

These tests are the reason a command cannot be added in one place and left
undocumented in another: the parser, ``searchts/catalog.py``, ``llms.txt``, both
SKILL files and ``docs/cli.md`` are checked against each other.
"""

from __future__ import annotations

import contextlib
import inspect
import io
import json
import re
import subprocess

import pytest
import sys
from pathlib import Path

from searchts import catalog, helpgen, helptext
from searchts.cli import build_parser
from searchts.integrations import mcp_server

ROOT = Path(__file__).resolve().parents[1]
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\]8;;.*?\x1b\\")


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "searchts", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT), timeout=180,
    )


def _payload():
    return catalog.build_catalog(build_parser(), "0.22.0")


def test_the_catalog_has_no_problems():
    assert catalog.validate(build_parser(), "0.22.0") == []


def test_every_parser_command_has_a_catalog_record():
    parsed = {" ".join(path) for path, _ in catalog.walk_parsers(build_parser())}
    parsed.discard("")
    recorded = {record["name"] for record in _payload()["commands"]}
    assert recorded == parsed


def test_every_catalog_entry_names_a_parser_command():
    parser_paths = {" ".join(path) for path, _ in catalog.walk_parsers(build_parser())}
    for name in catalog.COMMANDS:
        assert name in parser_paths, name


def test_every_command_has_its_own_lead_and_example():
    payload = _payload()
    for record in payload["commands"]:
        assert record["description"], record["name"]
        assert record["examples"], record["name"]
        assert record["usage"].startswith("searchts " + record["name"]), record["name"]


def test_a_subcommand_does_not_reuse_the_parent_screen():
    parent = catalog.meta_for("login")
    assert parent is not None
    for verb in ("list", "keep", "kill", "signin", "purge-scratch", "sweep", "check"):
        child = catalog.meta_for(["login", verb])
        assert child is not None
        assert child.lead != parent.lead
        assert child.examples != parent.examples


def test_exit_codes_are_per_command():
    payload = {record["name"]: record for record in _payload()["commands"]}
    check = {item["code"]: item["meaning"] for item in payload["login check"]["exit_codes"]}
    keep = {item["code"]: item["meaning"] for item in payload["login keep"]["exit_codes"]}
    update = {item["code"]: item["meaning"] for item in payload["update"]["exit_codes"]}
    assert check["1"].startswith("logged out")
    assert "consent" in keep["3"]
    assert "install shape" in update["2"]


def test_json_catalog_has_the_documented_shape():
    data = json.loads(_run("help", "--json").stdout)
    assert data["schema"] == "searchts.help.v1"
    assert data["prog"] == "searchts"
    assert data["version"]
    assert data["global_flags"]
    assert data["commands"]
    required = {
        "name", "aliases", "group", "description", "body", "notes", "usage",
        "positionals", "flags", "examples", "exit_codes", "deprecated",
        "legacy", "mcp", "subcommands",
    }
    for record in data["commands"]:
        assert required <= set(record), record["name"]
        assert set(record["mcp"]) >= {
            "tools", "notes", "mcp_only_params", "cli_only_flags", "param_flags",
            "cli_only", "reason",
        }


def test_json_help_for_one_command_includes_its_verbs():
    data = json.loads(_run("help", "login", "--json").stdout)
    names = {record["name"] for record in data["commands"]}
    assert "login" in names
    assert "login check" in names
    assert "login sweep" in names
    assert len(names) == 8


def test_unknown_help_path_is_a_clean_exit_2():
    out = _run("help", "not-a-command")
    assert out.returncode == 2
    assert out.stdout == ""
    assert "unknown command" in out.stderr
    assert "Traceback" not in out.stderr


def test_help_and_root_help_are_the_same_document():
    assert _run("help").stdout == _run("--help").stdout


def test_root_help_lists_the_global_flags_and_update():
    stdout = ANSI.sub("", _run("--help").stdout)
    assert "GLOBAL FLAGS" in stdout
    assert "--version" in stdout
    assert "-v, --verbose" in stdout
    assert "update" in stdout
    assert "upgrade" in stdout
    assert "help" in stdout


def test_root_help_keeps_reads_exit_codes():
    stdout = ANSI.sub("", _run("--help").stdout)
    assert "0       content returned" in stdout
    assert "1       every rung failed; the reasons are on stderr" in stdout
    assert "2       bad usage, or a URL that cannot be read" in stdout
    assert "Other commands: searchts <command> --help or searchts help --json" in stdout


def test_no_help_screen_has_an_empty_heading():
    parser = build_parser()
    headings = {"GLOBAL FLAGS", "USAGE", "ARGUMENTS", "COMMANDS", "FLAGS",
                "EXAMPLES", "SEE ALSO", "EXIT CODES"}
    problems = []

    def inspect_screen(name, text):
        lines = ANSI.sub("", text).splitlines()
        for index, line in enumerate(lines):
            if line.strip() not in headings:
                continue
            next_index = index + 1
            while next_index < len(lines) and not lines[next_index].strip():
                next_index += 1
            following = lines[next_index].strip() if next_index < len(lines) else ""
            if not following or following in headings or following == "ALSO":
                problems.append(f"{name}: empty {line.strip()} heading")

    def render(name, target, path):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            if path:
                helptext.render_command(target, path, "0.22.0")
            else:
                helptext.render_root("0.22.0", parser)
        inspect_screen(name, buffer.getvalue())

    render("root", parser, ())
    for path, target in catalog.walk_parsers(parser):
        render(" ".join(path), target, path)
    assert not problems, "\n".join(problems)


def test_login_help_lists_all_seven_verbs_with_descriptions():
    stdout = ANSI.sub("", _run("login", "--help").stdout)
    for verb in ("list", "keep", "kill", "signin", "purge-scratch", "sweep", "check"):
        assert re.search(rf"^\s+{re.escape(verb)}\s{{2,}}\S", stdout, re.M), verb
    assert "Delete expired cookies now, offline." in stdout


def test_login_check_help_has_its_own_body_and_exit_codes():
    stdout = ANSI.sub("", _run("login", "check", "--help").stdout)
    assert "Read one signed-in-only page with the saved cookies." in stdout
    assert "logged out" in stdout
    assert "unknown" in stdout
    assert "searchts login check reddit.com" in stdout


def test_configure_help_shows_an_optional_key():
    stdout = ANSI.sub("", _run("configure", "--help").stdout)
    assert "[key]" in stdout


def test_mcp_install_help_is_about_installing():
    stdout = ANSI.sub("", _run("mcp", "install", "--help").stdout)
    assert "Wire the MCP server into the agents on this machine." in stdout
    assert "--client json prints the mcpServers snippet" in stdout


def test_skill_install_help_is_about_the_bundle():
    stdout = ANSI.sub("", _run("skill", "install", "--help").stdout)
    assert "Write the slash command and the shared SKILL.md bundle." in stdout


def test_transcribe_help_names_the_browsers_it_accepts():
    stdout = ANSI.sub("", _run("transcribe", "--help").stdout)
    for browser in ("chrome", "firefox", "edge", "brave", "opera", "safari", "vivaldi"):
        assert browser in stdout


def test_bare_mcp_usage_is_generated_not_a_hand_written_client_list():
    out = _run("mcp")
    assert out.returncode == 2
    assert "{serve|install}" in out.stdout
    assert "searchts mcp install" in out.stdout
    assert "--client" in out.stdout
    assert "desktop" in out.stdout
    assert "copilot" in out.stdout


def test_generated_surfaces_are_current():
    assert helpgen.check(ROOT) == []


def test_no_surface_names_a_command_that_does_not_exist():
    assert catalog.surface_problems(ROOT) == []


def test_llms_names_every_root_command_and_the_machine_catalog():
    text = (ROOT / "llms.txt").read_text(encoding="utf-8")
    for record in _payload()["commands"]:
        if " " in record["name"]:
            continue
        if record["name"] in ("mcp", "skill"):
            assert f"`searchts {record['name']} " in text, record["name"]
        else:
            assert f"`searchts {record['name']}`" in text, record["name"]
    assert "searchts help --json" in text
    assert "update_available" in text
    assert "login check" in text
    assert "docs/cli.md" in text


def test_skill_files_are_byte_identical():
    one = (ROOT / "searchts" / "skill" / "SKILL.md").read_bytes()
    two = (ROOT / "searchts" / "skill" / "SKILL_en.md").read_bytes()
    assert one == two


def test_both_skill_files_carry_the_same_generated_block():
    one = (ROOT / "searchts" / "skill" / "SKILL.md").read_text(encoding="utf-8")
    two = (ROOT / "searchts" / "skill" / "SKILL_en.md").read_text(encoding="utf-8")

    def block(text):
        start = text.index(helpgen.BEGIN)
        end = text.index(helpgen.END, start)
        return text[start:end]

    assert block(one) == block(two)
    for text in (one, two):
        assert "searchts login check" in text
        assert "searchts check-update" in text
        assert "update_available" in text
        assert "https://github.com/capad-xyz/searchts/blob/main/docs/cli.md" in text


def test_slash_command_routes_login_and_asset_requests():
    from searchts.cli import _SLASH_COMMAND_BODY

    assert "searchts login check" in _SLASH_COMMAND_BODY
    assert "searchts login signin" in _SLASH_COMMAND_BODY
    assert "searchts grab" in _SLASH_COMMAND_BODY
    assert "searchts get" in _SLASH_COMMAND_BODY


def test_mcp_docs_match_the_server():
    text = (ROOT / "docs" / "mcp.md").read_text(encoding="utf-8")
    for tool in catalog.mcp_tool_names():
        assert f"`{tool}" in text, tool
    assert "max_media" in text
    assert "max_assets" in text
    assert "check_url" in text
    assert "carries `next_url`" not in text
    assert "`next_cursor`" in text


def test_mcp_server_docstring_and_signature_match_the_catalog():
    doc = mcp_server.__doc__ or ""
    for tool in catalog.mcp_tool_names():
        assert tool in doc, tool
    assert "ten module-level tool functions" in inspect.getsource(mcp_server.create_server)
    params = inspect.signature(mcp_server.login_check).parameters
    assert "check_url" in params
    assert params["check_url"].default == ""


def test_mcp_mapping_accounts_for_every_param_and_flag():
    """#444: each MCP param maps to a CLI flag or is MCP-only, and each CLI flag
    maps to an MCP param or is CLI-only. Checked against the live tool schemas
    and the parser, so a renamed flag cannot leave help.v1 wrong."""
    from searchts.integrations import mcp_server

    if not mcp_server.HAS_MCP:
        pytest.skip("mcp extra not installed")
    import asyncio

    schemas = {
        t.name: set((getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {}).get("properties", {}))
        for t in asyncio.run(mcp_server.create_server().list_tools())
    }
    data = json.loads(_run("help", "--json").stdout)
    for record in data["commands"]:
        mcp = record["mcp"]
        if not mcp["tools"]:
            continue
        (tool,) = mcp["tools"]
        params = schemas[tool]
        mapped = mcp["param_flags"]
        positionals = {p["name"] for p in record["positionals"]}
        flags = {}  # option string -> dest
        for flag in record["flags"]:
            if flag["dest"] == "verbose":
                continue
            for opt in flag["option_strings"]:
                flags[opt] = flag["dest"]
        dest_of = {opt: dest for opt, dest in flags.items()}
        covered_dests = set()
        for param in params:
            if param in mapped:
                target = mapped[param]
                assert target in flags or target in positionals, (tool, param, target)
                covered_dests.add(dest_of.get(target, target))
                assert param not in mcp["mcp_only_params"], (tool, param)
            elif param in set(flags.values()) or param in positionals:
                covered_dests.add(param)
                assert param not in mcp["mcp_only_params"], (tool, param)
            else:
                assert param in mcp["mcp_only_params"], (tool, param)
        for opt in mcp["cli_only_flags"]:
            assert opt in flags, (tool, opt)
            assert flags[opt] not in covered_dests, (tool, opt)
        cli_only_dests = {flags[o] for o in mcp["cli_only_flags"]}
        for dest in set(flags.values()):
            assert dest in covered_dests or dest in cli_only_dests, (record["name"], dest)
