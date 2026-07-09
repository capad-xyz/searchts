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
    """Keep the real machine's Claude Desktop config out of every test."""
    monkeypatch.delenv("APPDATA", raising=False)


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
    assert next(c for c in checks if c["client"] == "Cursor")["wired"] is False
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


def test_report_no_clients_nudges_oneliner():
    text = format_wiring_report([])
    assert "No supported agent configs found" in text
    assert "claude mcp add searchts" in text


def test_report_mixed_states():
    checks = [
        {"client": "Claude Code (MCP)", "wired": True, "hint": "x"},
        {"client": "Cursor", "wired": False, "hint": "searchts mcp install --client json"},
    ]
    text = format_wiring_report(checks)
    assert "Claude Code (MCP) — searchts is registered" in text
    assert "Cursor — detected, but searchts is NOT registered" in text
    # at least one client is wired, so the "PATH is not enough" lecture is omitted
    assert "not enough" not in text


def test_report_none_wired_explains_why():
    checks = [{"client": "Claude Code (MCP)", "wired": False, "hint": "x"}]
    text = format_wiring_report(checks)
    assert "Installed on PATH is not enough" in text
