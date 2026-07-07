# -*- coding: utf-8 -*-
"""Detect whether the searchts MCP server is wired into local AI agents.

"Installed on PATH" is not the same as "legible to the agent": a model can
only reach for searchts proactively if a client config (or slash command)
puts its tools into the model's context. Otherwise the agent hits a bot-wall,
has nothing to trigger on, and routes around it via secondary sources.

Pure filesystem reads — no network, no subprocesses — so `doctor` stays fast
and every check is directly testable with a fake home/cwd.

Each check returns:
    True  — client config found and searchts is registered
    False — client config found but searchts is NOT registered
    None  — client not detected on this machine (skip silently)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

SERVER_KEY = "searchts"
CLAUDE_MCP_ONELINER = "claude mcp add searchts -- searchts mcp serve"


def _read_json(path: Path) -> Optional[dict]:
    """Parse a JSON file; None when missing/unreadable/not an object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _has_server(data: Optional[dict]) -> bool:
    if not isinstance(data, dict):
        return False
    servers = data.get("mcpServers")
    return isinstance(servers, dict) and SERVER_KEY in servers


def _claude_code_wired(home: Path) -> Optional[bool]:
    """searchts in Claude Code's user-scope or any per-project MCP config."""
    path = home / ".claude.json"
    if not path.exists():
        return None
    data = _read_json(path)
    if data is None:
        return False
    if _has_server(data):
        return True
    projects = data.get("projects")
    if isinstance(projects, dict):
        for proj in projects.values():
            if _has_server(proj if isinstance(proj, dict) else None):
                return True
    return False


def _project_mcp_wired(cwd: Path) -> Optional[bool]:
    """searchts in the current project's shared .mcp.json (absence = skip)."""
    path = cwd / ".mcp.json"
    if not path.exists():
        return None
    return _has_server(_read_json(path))


def _claude_desktop_wired(home: Path) -> Optional[bool]:
    """searchts in the Claude Desktop config for this platform."""
    appdata = os.environ.get("APPDATA")
    candidates = []
    if appdata:
        candidates.append(Path(appdata) / "Claude" / "claude_desktop_config.json")
    candidates.append(home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json")
    candidates.append(home / ".config" / "Claude" / "claude_desktop_config.json")
    for path in candidates:
        if path.exists():
            return _has_server(_read_json(path))
    return None


def _cursor_wired(home: Path, cwd: Path) -> Optional[bool]:
    """searchts in Cursor's global or project mcp.json."""
    paths = [home / ".cursor" / "mcp.json", cwd / ".cursor" / "mcp.json"]
    existing = [p for p in paths if p.exists()]
    if not existing:
        return None
    return any(_has_server(_read_json(p)) for p in existing)


def _codex_wired(home: Path) -> Optional[bool]:
    """searchts in Codex CLI's config.toml (substring check; tomllib is 3.11+)."""
    path = home / ".codex" / "config.toml"
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return f"[mcp_servers.{SERVER_KEY}]" in text or f'[mcp_servers."{SERVER_KEY}"]' in text


def _skill_wired(home: Path) -> Optional[bool]:
    """The /searchts slash command in Claude Code's commands dir."""
    claude_dir = home / ".claude"
    if not claude_dir.is_dir():
        return None
    return (claude_dir / "commands" / "searchts.md").exists()


def check_agent_wiring(home: Optional[Path] = None, cwd: Optional[Path] = None) -> list:
    """Probe known agent configs; report only clients present on this machine.

    Returns a list of {"client", "wired", "hint"} dicts. The hint is the
    one command that wires searchts into that client.
    """
    home = Path(home) if home else Path.home()
    cwd = Path(cwd) if cwd else Path(os.getcwd())

    probes = [
        ("Claude Code (MCP)", _claude_code_wired(home), CLAUDE_MCP_ONELINER),
        ("Claude Code (/searchts skill)", _skill_wired(home), "searchts skill install"),
        ("Project .mcp.json", _project_mcp_wired(cwd), "searchts mcp install --client json"),
        ("Claude Desktop", _claude_desktop_wired(home), "searchts mcp install --client json"),
        ("Cursor", _cursor_wired(home, cwd), "searchts mcp install --client json"),
        ("Codex CLI", _codex_wired(home), "searchts mcp install --client json"),
    ]
    return [
        {"client": client, "wired": bool(wired), "hint": hint}
        for client, wired, hint in probes
        if wired is not None
    ]


def format_wiring_report(checks: Optional[list] = None) -> str:
    """Render the wiring section for `doctor` (Rich markup, like format_report)."""
    if checks is None:
        checks = check_agent_wiring()

    lines = ["", "[bold]Agent wiring (is searchts visible to your AI agent?):[/bold]"]
    if not checks:
        lines.append("  [yellow][!][/yellow]  No supported agent configs found (Claude Code/Desktop, Cursor, Codex).")
        lines.append(f"      To wire one up: {CLAUDE_MCP_ONELINER}")
        return "\n".join(lines)

    for c in checks:
        if c["wired"]:
            lines.append(rf"  [green]\[ok][/green] {c['client']} — searchts is registered")
        else:
            lines.append(f"  [yellow][!][/yellow]  {c['client']} — detected, but searchts is NOT registered ({c['hint']})")

    if not any(c["wired"] for c in checks):
        lines.append(
            "      Installed on PATH is not enough: an agent only reaches for searchts "
            "proactively when it is registered as an MCP server or slash command."
        )
    return "\n".join(lines)
