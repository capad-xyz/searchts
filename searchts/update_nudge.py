# -*- coding: utf-8 -*-
"""F13: optional stderr update nudge. Never stdout. Never MCP protocol."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from searchts import __version__

TTL_SECONDS = 24 * 60 * 60
CACHE_NAME = "update-check.json"
RELEASES_URL = "https://api.github.com/repos/capad-xyz/searchts/releases/latest"
UPDATE_DOC = (
    "https://raw.githubusercontent.com/capad-xyz/searchts/main/docs/update.md"
)
SKIP_COMMANDS = frozenset({"check-update", "watch", "version"})


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


def maybe_nudge(
    *,
    command: Optional[str] = None,
    mcp_subcommand: Optional[str] = None,
    now: Optional[float] = None,
) -> None:
    """Best-effort stderr line when a newer GitHub release exists.

    Skips: env opt-out, pytest, pipes, mcp serve, check-update/watch/version.
    Failures are silent. Never writes stdout.
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
    print(
        f"searchts v{latest} is available. "
        f"SEARCHTS_NO_UPDATE_CHECK=1 hides this. {UPDATE_DOC}",
        file=sys.stderr,
        flush=True,
    )
