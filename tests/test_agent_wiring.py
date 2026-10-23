# -*- coding: utf-8 -*-
"""Tests for the agent-wiring detector (pure filesystem, no network)."""

import json

import pytest

from searchts.integrations.agent_wiring import (
    check_agent_wiring,
    format_wiring_report,
)


@pytest.fixture(autouse=True)
def _no_real_appdata(monkeypatch):
    """Keep this machine's agent configs out of every probe."""
    for key in ("APPDATA", "COPILOT_HOME", "OPENCLAW_HOME", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(key, raising=False)


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_empty_machine_reports_nothing(tmp_path):
    checks = check_agent_wiring(home=tmp_path / "home", cwd=tmp_path / "cwd")
    assert checks == []


def test_claude_code_user_scope_wired(tmp_path):
    home = tmp_path / "home"
    _write(home / ".claude.json", {"mcpServers": {"searchts": {"command": "searchts"}}})
    checks = check_agent_wiring(home=home, cwd=tmp_path)
    row = next(c for c in checks if c["client"] == "Claude Code (MCP)")
    assert row["wired"] is True


def test_claude_code_project_scope_wired(tmp_path):
    home = tmp_path / "home"
    _write(
        home / ".claude.json",
        {"projects": {"C:/x": {"mcpServers": {"searchts": {"command": "searchts"}}}}},
    )
    checks = check_agent_wiring(home=home, cwd=tmp_path)
    row = next(c for c in checks if c["client"] == "Claude Code (MCP)")
    assert row["wired"] is True


def test_claude_code_present_but_not_wired(tmp_path):
    home = tmp_path / "home"
    _write(home / ".claude.json", {"mcpServers": {"other": {}}})
    checks = check_agent_wiring(home=home, cwd=tmp_path)
    row = next(c for c in checks if c["client"] == "Claude Code (MCP)")
    assert row["wired"] is False
    assert "claude mcp add searchts" in row["hint"]


def test_corrupt_config_counts_as_not_wired(tmp_path):
    home = tmp_path / "home"
    path = home / ".claude.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    checks = check_agent_wiring(home=home, cwd=tmp_path)
    row = next(c for c in checks if c["client"] == "Claude Code (MCP)")
    assert row["wired"] is False


def test_project_mcp_json(tmp_path):
    cwd = tmp_path / "proj"
    _write(cwd / ".mcp.json", {"mcpServers": {"searchts": {"command": "searchts"}}})
    checks = check_agent_wiring(home=tmp_path / "home", cwd=cwd)
    row = next(c for c in checks if c["client"] == "Project .mcp.json")
    assert row["wired"] is True


def test_cursor_global_and_project(tmp_path):
    home, cwd = tmp_path / "home", tmp_path / "proj"
    _write(home / ".cursor" / "mcp.json", {"mcpServers": {}})
    checks = check_agent_wiring(home=home, cwd=cwd)
    row = next(c for c in checks if c["client"] == "Cursor")
    assert sum(c["client"] == "Cursor" for c in checks) == 1
    assert row["wired"] is False
    assert row["hint"] == "searchts mcp install --client cursor"
    _write(cwd / ".cursor" / "mcp.json", {"mcpServers": {"searchts": {}}})
    checks = check_agent_wiring(home=home, cwd=cwd)
    assert next(c for c in checks if c["client"] == "Cursor")["wired"] is True


def test_codex_toml_substring(tmp_path):
    home = tmp_path / "home"
    path = home / ".codex" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[mcp_servers.searchts]\ncommand = 'searchts'\n", encoding="utf-8")
    checks = check_agent_wiring(home=home, cwd=tmp_path)
    assert next(c for c in checks if c["client"] == "Codex CLI")["wired"] is True


def test_claude_desktop_via_appdata(tmp_path, monkeypatch):
    appdata = tmp_path / "AppData"
    monkeypatch.setenv("APPDATA", str(appdata))
    _write(appdata / "Claude" / "claude_desktop_config.json", {"mcpServers": {"searchts": {}}})
    checks = check_agent_wiring(home=tmp_path / "home", cwd=tmp_path)
    assert next(c for c in checks if c["client"] == "Claude Desktop")["wired"] is True


def test_skill_detection(tmp_path):
    home = tmp_path / "home"
    (home / ".claude" / "commands").mkdir(parents=True)
    checks = check_agent_wiring(home=home, cwd=tmp_path)
    row = next(c for c in checks if c["client"] == "Claude Code (/searchts skill)")
    assert row["wired"] is False
    (home / ".claude" / "commands" / "searchts.md").write_text("x", encoding="utf-8")
    checks = check_agent_wiring(home=home, cwd=tmp_path)
    row = next(c for c in checks if c["client"] == "Claude Code (/searchts skill)")
    assert row["wired"] is True


def test_codex_hint_names_the_toml_client(tmp_path):
    home = tmp_path / "home"
    path = home / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text('model = "gpt"\n', encoding="utf-8")
    checks = check_agent_wiring(home=home, cwd=tmp_path)
    row = next(c for c in checks if c["client"] == "Codex CLI")
    assert sum(c["client"] == "Codex CLI" for c in checks) == 1
    assert row["wired"] is False
    assert row["hint"] == "searchts mcp install --client codex"


def test_desktop_hint_names_desktop(tmp_path, monkeypatch):
    appdata = tmp_path / "AppData"
    monkeypatch.setenv("APPDATA", str(appdata))
    _write(appdata / "Claude" / "claude_desktop_config.json", {"mcpServers": {}})
    checks = check_agent_wiring(home=tmp_path / "home", cwd=tmp_path)
    row = next(c for c in checks if c["client"] == "Claude Desktop")
    assert row["wired"] is False
    assert row["hint"] == "searchts mcp install --client desktop"


def test_extra_clients_and_skill_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr("searchts.integrations.wire.sys.platform", "linux")
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    markers = {
        "VS Code": home / ".config" / "Code" / "User",
        "Copilot CLI": home / ".copilot",
        "Gemini CLI": home / ".gemini",
        "OpenCode": home / ".config" / "opencode",
        "Windsurf": home / ".codeium" / "windsurf",
        "Devin Desktop": home / ".config" / "devin",
    }
    for path in markers.values():
        path.mkdir(parents=True)
    (home / ".agents").mkdir()
    checks = {c["client"]: c for c in check_agent_wiring(home=home, cwd=cwd)}
    assert checks["Agent skill (SKILL.md)"]["wired"] is False
    assert checks["Agent skill (SKILL.md)"]["hint"] == "searchts skill install"
    for name in markers:
        assert checks[name]["wired"] is False
        assert checks[name]["hint"].startswith("searchts mcp install --client ")

    _write(
        markers["VS Code"] / "mcp.json",
        {"servers": {"searchts": {"type": "stdio", "command": "searchts", "args": ["mcp", "serve"]}}},
    )
    _write(
        markers["Copilot CLI"] / "mcp-config.json",
        {"mcpServers": {"searchts": {"command": "searchts", "args": ["mcp", "serve"]}}},
    )
    _write(
        markers["Gemini CLI"] / "settings.json",
        {"mcpServers": {"searchts": {"command": "searchts", "args": ["mcp", "serve"]}}},
    )
    _write(
        markers["OpenCode"] / "opencode.json",
        {"mcp": {"servers": {"searchts": {"type": "local", "command": ["searchts", "mcp", "serve"]}}}},
    )
    _write(markers["Windsurf"] / "mcp_config.json", {"mcpServers": {"searchts": {"command": "searchts"}}})
    _write(
        markers["Devin Desktop"] / "mcp_config.json",
        {"mcpServers": {"searchts": {"command": "searchts"}}},
    )
    skill = home / ".agents" / "skills" / "searchts" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("name: searchts\n", encoding="utf-8")
    checks = {c["client"]: c for c in check_agent_wiring(home=home, cwd=cwd)}
    for name in list(markers) + ["Agent skill (SKILL.md)"]:
        assert checks[name]["wired"] is True


def test_report_no_clients_nudges_oneliner():
    text = format_wiring_report([])
    assert "No supported agent configs found" in text
    assert "claude mcp add searchts" in text
    assert "VS Code" in text


def test_report_mixed_states():
    checks = [
        {"client": "Claude Code (MCP)", "wired": True, "hint": "x"},
        {"client": "Cursor", "wired": False, "hint": "searchts mcp install --client json"},
    ]
    text = format_wiring_report(checks)
    assert "Claude Code (MCP)" in text
    assert "searchts is registered" in text
    assert "Cursor" in text
    assert "Detected, but searchts is NOT registered." in text
    # at least one client is wired, so the "PATH is not enough" lecture is omitted
    assert "not enough" not in text


def test_report_none_wired_explains_why():
    checks = [{"client": "Claude Code (MCP)", "wired": False, "hint": "x"}]
    text = format_wiring_report(checks)
    assert "Installed on PATH is not enough" in text
