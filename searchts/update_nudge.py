# -*- coding: utf-8 -*-
"""F13: optional stderr update nudge. Never stdout. Never MCP protocol.

F19: when the nudge fires it also says this process is still the old build,
names the searchts.exe PIDs on Windows, and prints the one install command.
It never installs and never kills.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Optional, Sequence

from searchts import __version__

TTL_SECONDS = 24 * 60 * 60
CACHE_NAME = "update-check.json"
RELEASES_URL = "https://api.github.com/repos/capad-xyz/searchts/releases/latest"
UPDATE_DOC = (
    "https://raw.githubusercontent.com/capad-xyz/searchts/main/docs/update.md"
)
SKIP_COMMANDS = frozenset({"check-update", "watch", "version"})

INSTALL_COMMANDS = {
    "pipx": "pipx upgrade searchts",
    "pip": 'pip install -U "searchts[mcp]"',
    "uvx": "uvx already latest PyPI; nothing to upgrade",
}
UV_ENV_KEYS = ("UV_RUNNING", "UVX", "UV_PYTHON")


def is_newer_version(remote: str, local: str) -> bool:
    """True if remote is strictly newer than local (semantic compare)."""

    def parse(v: str):
        try:
            return tuple(int(x) for x in v.strip().split("."))
        except ValueError:
            return None

    remote_version, local_version = parse(remote), parse(local)
    if remote_version is None or local_version is None:
        return remote != local
    return remote_version > local_version


def cache_path() -> Path:
    return Path.home() / ".searchts" / CACHE_NAME


def _read_cache(path: Path, now: float) -> Optional[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    try:
        checked = float(data.get("checked_at") or 0)
        latest = str(data.get("latest") or "").lstrip("v")
    except (TypeError, ValueError):
        return None
    if not latest or now - checked > TTL_SECONDS:
        return None
    return latest


def _write_cache(path: Path, latest: str, now: float) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"checked_at": now, "latest": latest}),
            encoding="utf-8",
        )
    except OSError:
        pass


def _fetch_latest(timeout: float = 2.0) -> Optional[str]:
    req = urllib.request.Request(
        RELEASES_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"searchts/{__version__} (update-nudge)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    tag = str(data.get("tag_name") or "").lstrip("v")
    return tag or None


def _path_parts(value: Optional[str]) -> list[str]:
    """Split a path using both Windows and POSIX rules.

    Host ``Path`` only understands local separators, so a ``C:\\...\\uv\\tools``
    string on Linux CI is one part and would miss the uvx marker.
    """
    if not value:
        return []
    parts: list[str] = []
    for parsed in (PureWindowsPath(value), PurePosixPath(value)):
        parts.extend(p.strip().lower() for p in parsed.parts if p.strip())
    return parts


def _has_uv_marker(parts: Sequence[str]) -> bool:
    for part in parts:
        if part == "uv" or part == "uvx" or part == "uv-tools" or part == "archive-v0":
            return True
        if "uv-cache" in part or part.startswith("uv-"):
            return True
    return False


def detect_install_kind() -> str:
    """How this interpreter was installed: uvx, pipx, or pip.

    uvx wins over pipx: a uv tool venv can also live under a pipx-ish path.
    """
    if any(os.environ.get(key) for key in UV_ENV_KEYS):
        return "uvx"

    for raw in (getattr(sys, "executable", ""), sys.prefix, sys.exec_prefix):
        if _has_uv_marker(_path_parts(raw)):
            return "uvx"

    if os.environ.get("PIPX_HOME"):
        return "pipx"
    for raw in (getattr(sys, "executable", ""), sys.prefix, sys.exec_prefix):
        parts = _path_parts(raw)
        if "pipx" in parts or "pipx" in raw.lower():
            return "pipx"

    return "pip"


def _searchts_pids() -> list[int]:
    """Windows searchts.exe PIDs. Empty off Windows. Never kills."""
    try:
        from searchts.doctor import windows_searchts_pids

        return list(windows_searchts_pids())
    except Exception:
        return []


def _nudge_lines(
    latest: str,
    local: str,
    *,
    install_kind: str,
    pids: Sequence[int],
) -> list[str]:
    lines = [
        f"searchts v{latest} is available. "
        f"SEARCHTS_NO_UPDATE_CHECK=1 hides this. {UPDATE_DOC}",
        f"This process is still v{local}: the update did not take effect here.",
    ]
    if pids:
        pid_text = ", ".join(f"PID {pid}" for pid in pids)
        lines.append(
            f"Windows: searchts.exe still open ({pid_text}). "
            "This message does not kill them."
        )
    lines.append(INSTALL_COMMANDS.get(install_kind, INSTALL_COMMANDS["pip"]))
    return lines


def maybe_nudge(
    *,
    command: Optional[str] = None,
    mcp_subcommand: Optional[str] = None,
    now: Optional[float] = None,
    install_kind: Optional[str] = None,
    pids: Optional[Sequence[int]] = None,
) -> None:
    """Best-effort stderr lines when a newer GitHub release exists.

    Skips: env opt-out, pytest, pipes, mcp serve, check-update/watch/version.
    Failures are silent. Never writes stdout. Never installs or kills.
    """
    if os.environ.get("SEARCHTS_NO_UPDATE_CHECK"):
        return
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    if command in SKIP_COMMANDS:
        return
    if command == "mcp" and mcp_subcommand in (None, "serve"):
        return
    if sys.stdout is None or sys.stderr is None:
        return
    try:
        if not sys.stdout.isatty() or not sys.stderr.isatty():
            return
    except Exception:
        return

    stamp = time.time() if now is None else now
    path = cache_path()
    latest = _read_cache(path, stamp)
    if latest is None:
        latest = _fetch_latest()
        if not latest:
            return
        _write_cache(path, latest, stamp)

    if not is_newer_version(latest, __version__):
        return
    kind = detect_install_kind() if install_kind is None else install_kind
    running_pids = _searchts_pids() if pids is None else list(pids)
    for line in _nudge_lines(
        latest, __version__, install_kind=kind, pids=running_pids
    ):
        print(line, file=sys.stderr, flush=True)
