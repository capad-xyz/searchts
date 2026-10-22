# -*- coding: utf-8 -*-
"""Write the searchts MCP server into agent configs that already exist.

``searchts mcp install`` used to print a Claude one-liner and one JSON
snippet. Codex, VS Code, and OpenCode do not read that snippet. This module
merges the stdio server into each client's own file when that client is
already on the machine, and leaves a file alone when it cannot be parsed or
when ``searchts`` is already pointed at a different command.

Project files (``.mcp.json``, ``.vscode/mcp.json``, ``.cursor/mcp.json`` in
the repo) are never written. Those get committed.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Mapping, Optional

SERVER = "searchts"

#: command + args. Clients that want a ``type`` field add it themselves.
STDIO = {"command": "searchts", "args": ["mcp", "serve"]}
STDIO_TYPED = {"type": "stdio", "command": "searchts", "args": ["mcp", "serve"]}
OPENCODE = {"type": "local", "command": ["searchts", "mcp", "serve"], "enabled": True}

CODEX_HEADER = "[mcp_servers.searchts]"
CODEX_HEADER_QUOTED = '[mcp_servers."searchts"]'
CODEX_BLOCK = (
    "[mcp_servers.searchts]\n"
    'command = "searchts"\n'
    'args = ["mcp", "serve"]\n'
)


def _env(environ: Optional[dict]) -> Mapping:
    return os.environ if environ is None else environ


def vscode_user_dir(home: Path, environ: Optional[dict] = None) -> Path:
    """VS Code user profile directory. The mcp.json file lives inside it."""
    env = _env(environ)
    if sys.platform == "win32":
        appdata = env.get("APPDATA")
        base = Path(appdata) if appdata else home / "AppData" / "Roaming"
        return base / "Code" / "User"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Code" / "User"
    xdg = env.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else home / ".config"
    return base / "Code" / "User"


def devin_config_path(home: Path, environ: Optional[dict] = None) -> Path:
    """Devin Desktop / Cascade mcp_config.json (the Windsurf docs now live here)."""
    env = _env(environ)
    if sys.platform == "win32":
        appdata = env.get("APPDATA")
        base = Path(appdata) if appdata else home / "AppData" / "Roaming"
        return base / "devin" / "mcp_config.json"
    xdg = env.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else home / ".config"
    return base / "devin" / "mcp_config.json"


def copilot_home(home: Path, environ: Optional[dict] = None) -> Path:
    env = _env(environ)
    override = env.get("COPILOT_HOME")
    return Path(override) if override else home / ".copilot"


def desktop_config_candidates(home: Path, environ: Optional[dict] = None) -> list:
    """Platform path first, then the other two, so a forced write lands in the right place."""
    env = _env(environ)
    appdata = env.get("APPDATA")
    windows = (
        Path(appdata) / "Claude" / "claude_desktop_config.json"
        if appdata
        else home / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"
    )
    mac = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    linux = home / ".config" / "Claude" / "claude_desktop_config.json"
    if sys.platform == "win32":
        ordered = [windows, mac, linux]
    elif sys.platform == "darwin":
        ordered = [mac, windows, linux]
    else:
        ordered = [linux, mac, windows]
    seen = []
    for path in ordered:
        if path not in seen:
            seen.append(path)
    return seen


def _same_stdio(current, expected: dict) -> bool:
    """True when the saved entry already launches ``searchts mcp serve``.

    Extra keys (env, timeout) are fine. A different command is not ours to
    replace.
    """
    if not isinstance(current, dict) or not isinstance(expected, dict):
        return False
    if current.get("command") != expected.get("command"):
        return False
    if list(current.get("args") or []) != list(expected.get("args") or []):
        return False
    if "type" in expected and current.get("type") not in (None, expected["type"]):
        return False
    return True


def merge_json(path: Path, container: str, entry: dict, *, create: bool) -> str:
    """Insert ``searchts`` under ``container``. Returns a status word.

    wrote, already, kept, skipped, absent.
    """
    if not path.exists():
        if not create:
            return "absent"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {container: {SERVER: entry}}
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return "wrote"
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        return "skipped"
    if not isinstance(data, dict):
        return "skipped"
    block = data.get(container)
    if block is None:
        block = {}
        data[container] = block
    if not isinstance(block, dict):
        return "skipped"
    current = block.get(SERVER)
    if _same_stdio(current, entry):
        return "already"
    if current is not None:
        return "kept"
    block[SERVER] = entry
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return "wrote"


def merge_codex(path: Path, *, create: bool) -> str:
    """Append the searchts table. Do not rewrite the rest of the file."""
    if not path.exists():
        if not create:
            return "absent"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(CODEX_BLOCK, encoding="utf-8")
        return "wrote"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "skipped"
    if CODEX_HEADER in text or CODEX_HEADER_QUOTED in text:
        return "already"
    if text and not text.endswith("\n"):
        text += "\n"
    if text.strip():
        text += "\n"
    path.write_text(text + CODEX_BLOCK, encoding="utf-8")
    return "wrote"


def _json_has(path: Path, container: str) -> Optional[bool]:
    """True/False when the file exists, None when it does not."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    block = data.get(container)
    return isinstance(block, dict) and SERVER in block


class _Target:
    def __init__(self, client_id, label, hint):
        self.id = client_id
        self.label = label
        self.hint = hint

    def present(self, home, cwd, env) -> bool:
        raise NotImplementedError

    def wired(self, home, cwd, env) -> Optional[bool]:
        raise NotImplementedError

    def write(self, home, cwd, env, *, create: bool) -> tuple:
        """Return (status, path or None)."""
        raise NotImplementedError


class _JsonTarget(_Target):
    def __init__(self, client_id, label, hint, container, entry, path_of, marker):
        super().__init__(client_id, label, hint)
        self.container = container
        self.entry = entry
        self.path_of = path_of
        self.marker = marker

    def present(self, home, cwd, env) -> bool:
        return self.marker(home, cwd, env)

    def wired(self, home, cwd, env) -> Optional[bool]:
        if not self.present(home, cwd, env):
            return None
        path = self.path_of(home, cwd, env)
        found = _json_has(path, self.container)
        return False if found is None else found

    def write(self, home, cwd, env, *, create: bool) -> tuple:
        path = self.path_of(home, cwd, env)
        if not create and not self.present(home, cwd, env):
            return "absent", path
        # Create the config file. Do not create the app directory unless asked.
        file_create = create or path.parent.exists() or path.exists()
        if not file_create:
            return "absent", path
        if not path.parent.exists():
            if not create:
                return "absent", path
            path.parent.mkdir(parents=True, exist_ok=True)
        return merge_json(path, self.container, self.entry, create=True), path


class _CodexTarget(_Target):
    def __init__(self):
        super().__init__(
            "codex",
            "Codex CLI",
            "searchts mcp install --client codex",
        )

    def _path(self, home) -> Path:
        return home / ".codex" / "config.toml"

    def present(self, home, cwd, env) -> bool:
        return (home / ".codex").is_dir() or self._path(home).exists()

    def wired(self, home, cwd, env) -> Optional[bool]:
        path = self._path(home)
        if not path.exists():
            return False if self.present(home, cwd, env) else None
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return False
        return CODEX_HEADER in text or CODEX_HEADER_QUOTED in text

    def write(self, home, cwd, env, *, create: bool) -> tuple:
        path = self._path(home)
        if not create and not self.present(home, cwd, env):
            return "absent", path
        if not path.parent.exists():
            if not create:
                return "absent", path
            path.parent.mkdir(parents=True, exist_ok=True)
        return merge_codex(path, create=True), path


def _targets() -> list:
    def claude_path(home, cwd, env):
        return home / ".claude.json"

    def claude_marker(home, cwd, env):
        return claude_path(home, cwd, env).exists() or (home / ".claude").is_dir()

    def cursor_path(home, cwd, env):
        return home / ".cursor" / "mcp.json"

    def cursor_marker(home, cwd, env):
        return (
            (home / ".cursor").is_dir()
            or cursor_path(home, cwd, env).exists()
            or (cwd / ".cursor" / "mcp.json").exists()
        )

    def desktop_path(home, cwd, env):
        existing = [p for p in desktop_config_candidates(home, env) if p.exists()]
        if existing:
            return existing[0]
        return desktop_config_candidates(home, env)[0]

    def desktop_marker(home, cwd, env):
        return any(p.exists() for p in desktop_config_candidates(home, env))

    def vscode_path(home, cwd, env):
        return vscode_user_dir(home, env) / "mcp.json"

    def vscode_marker(home, cwd, env):
        return vscode_user_dir(home, env).is_dir()

    def copilot_path(home, cwd, env):
        return copilot_home(home, env) / "mcp-config.json"

    def copilot_marker(home, cwd, env):
        return copilot_home(home, env).is_dir()

    def windsurf_path(home, cwd, env):
        return home / ".codeium" / "windsurf" / "mcp_config.json"

    def windsurf_marker(home, cwd, env):
        return (home / ".codeium" / "windsurf").is_dir()

    def devin_path(home, cwd, env):
        return devin_config_path(home, env)

    def devin_marker(home, cwd, env):
        return devin_config_path(home, env).parent.is_dir()

    def gemini_path(home, cwd, env):
        return home / ".gemini" / "settings.json"

    def gemini_marker(home, cwd, env):
        return (home / ".gemini").is_dir()

    def opencode_path(home, cwd, env):
        return home / ".config" / "opencode" / "opencode.json"

    def opencode_marker(home, cwd, env):
        return (home / ".config" / "opencode").is_dir()

    return [
        _JsonTarget(
            "claude", "Claude Code (MCP)", "claude mcp add searchts -- searchts mcp serve",
            "mcpServers", STDIO, claude_path, claude_marker,
        ),
        _JsonTarget(
            "cursor", "Cursor", "searchts mcp install --client cursor",
            "mcpServers", STDIO, cursor_path, cursor_marker,
        ),
        _JsonTarget(
            "desktop", "Claude Desktop", "searchts mcp install --client desktop",
            "mcpServers", STDIO, desktop_path, desktop_marker,
        ),
        _CodexTarget(),
        _JsonTarget(
            "vscode", "VS Code", "searchts mcp install --client vscode",
            "servers", STDIO_TYPED, vscode_path, vscode_marker,
        ),
        _JsonTarget(
            "copilot", "Copilot CLI", "searchts mcp install --client copilot",
            "mcpServers", STDIO, copilot_path, copilot_marker,
        ),
        _JsonTarget(
            "gemini", "Gemini CLI", "searchts mcp install --client gemini",
            "mcpServers", STDIO, gemini_path, gemini_marker,
        ),
        _JsonTarget(
            "opencode", "OpenCode", "searchts mcp install --client opencode",
            "mcp", OPENCODE, opencode_path, opencode_marker,
        ),
        _JsonTarget(
            "windsurf", "Windsurf", "searchts mcp install --client windsurf",
            "mcpServers", STDIO, windsurf_path, windsurf_marker,
        ),
        _JsonTarget(
            "devin", "Devin Desktop", "searchts mcp install --client devin",
            "mcpServers", STDIO, devin_path, devin_marker,
        ),
    ]


def targets():
    return _targets()


def mcp_probes(home: Path, cwd: Path, environ: Optional[dict] = None) -> list:
    """Doctor rows for clients this module knows, including the original four.

    ``wired`` is None when the client is not on the machine.
    """
    env = _env(environ)
    rows = []
    for target in _targets():
        wired = target.wired(home, cwd, env)
        if wired is None:
            continue
        rows.append({"client": target.label, "wired": bool(wired), "hint": target.hint, "id": target.id})
    return rows


def apply_mcp(
    home: Path,
    *,
    client: Optional[str] = None,
    cwd: Optional[Path] = None,
    environ: Optional[dict] = None,
) -> list:
    """Write configs. ``client`` forces one id. None writes every present client.

    ``json`` is print-only and writes nothing. Returns
    ``{client, id, status, path}`` for each client touched.
    """
    if client == "json":
        return []
    env = _env(environ)
    cwd = Path(cwd) if cwd else Path(os.getcwd())
    home = Path(home)
    force = client is not None
    out = []
    known = {t.id for t in _targets()}
    if client is not None and client not in known:
        raise ValueError(client)
    for target in _targets():
        if client is not None and target.id != client:
            continue
        if client is None and not target.present(home, cwd, env):
            continue
        status, path = target.write(home, cwd, env, create=force or target.present(home, cwd, env))
        if status == "absent":
            continue
        out.append({
            "client": target.label,
            "id": target.id,
            "status": status,
            "path": path,
        })
    return out
