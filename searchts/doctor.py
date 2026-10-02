# -*- coding: utf-8 -*-
"""Environment health checker — powered by channels.

Each channel knows how to check itself. Doctor just collects the results.
"""

import csv
import io
import os
import re
import subprocess
import sys
from typing import Callable, Dict, Optional, Sequence

from searchts.channels import get_all_channels
from searchts.config import Config

# Rich styles used by format_report. Do not match status tokens like [ok] / [X] / [!].
_RICH_TAG = re.compile(
    r"\[\/?(?:bold|italic|underline|strike|dim|"
    r"cyan|green|yellow|red|blue|magenta|white|black)"
    r"(?: [a-z]+)?\]",
    re.IGNORECASE,
)


def strip_rich_markup(text: str) -> str:
    """Drop Rich tags. Keep the [ok] / [!] / [X] tokens the report already uses."""
    return _RICH_TAG.sub("", text).replace("\\[", "[")


def _tick(msg: str) -> None:
    # Best-effort only: a closed/broken stderr must never abort a check.
    try:
        print(msg, file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass


def check_all(config: Config, progress: Optional[bool] = None) -> Dict[str, dict]:
    """Check all channels and return status dict.

    A single misbehaving channel must never take the whole report down,
    so per-channel exceptions degrade to status=\"error\".

    progress:
        True: stderr ticks. False: never ticks (CLI ``--json``). None: follow
        ``SEARCHTS_PROGRESS=1``. Library/MCP callers omit the arg so they stay
        quiet unless the env is set.
    """
    if progress is None:
        progress = os.environ.get("SEARCHTS_PROGRESS", "") in (
            "1", "true", "True", "yes",
        )

    results = {}
    for ch in get_all_channels():
        if progress:
            _tick(f"checking {ch.name}…")
        reported = None
        try:
            status, message = ch.check(config)
            active = getattr(ch, "active_backend", None)
            reported = getattr(ch, "reported_backends", None)
        except Exception as e:  # noqa: BLE001 — doctor must survive any channel
            status, message, active = "error", f"Health check error: {e}", None
            reported = None
        backends = list(reported) if reported is not None else list(ch.backends)
        results[ch.name] = {
            "status": status,
            "name": ch.description,
            "message": message,
            "tier": ch.tier,
            "backends": backends,
            "active_backend": active,
        }
    return results


def _name_msg(r: dict, escape) -> str:
    """Render one channel line; show the active backend when there is a choice."""
    text = f"[bold]{escape(r['name'])}[/bold] — {escape(r['message'])}"
    active = r.get("active_backend")
    if active and len(r.get("backends", [])) > 1:
        text += f" [dim](current backend: {escape(active)})[/dim]"
    return text


def _windows_parent_map() -> Dict[int, int]:
    """PID -> parent PID for every process (one Toolhelp snapshot). Empty off Windows or on error."""
    if sys.platform != "win32":
        return {}
    try:
        import ctypes
        from ctypes import wintypes

        class _Entry(ctypes.Structure):  # PROCESSENTRY32W
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Entry)]
        k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Entry)]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
        if not snap or snap == ctypes.c_void_p(-1).value:
            return {}
        parents: Dict[int, int] = {}
        try:
            entry = _Entry()
            entry.dwSize = ctypes.sizeof(_Entry)
            ok = k32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                ok = k32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            k32.CloseHandle(snap)
        return parents
    except Exception:  # noqa: BLE001 - fall back to this process and its parent
        return {}


def _ancestor_pids(pid: int, parents: Dict[int, int]) -> set:
    """Every process above `pid`. A pipx ``searchts.exe`` starts the venv's
    ``python.exe``, which starts the real one, so the launcher is the
    grandparent, not the parent (F11a)."""
    found: set = set()
    cur = parents.get(pid)
    while cur and cur not in found and cur != pid and len(found) < 64:
        found.add(cur)
        cur = parents.get(cur)
    return found


def windows_searchts_pids(
    *,
    runner: Optional[Callable[[], str]] = None,
    platform: Optional[str] = None,
    exclude: Optional[Sequence[int]] = None,
) -> list[int]:
    """PIDs whose image is searchts.exe, other than this command. Does not kill.

    Empty off Windows. This process and every process above it (the
    ``searchts.exe`` launcher may be the parent or the grandparent) are left
    out by default: telling someone to quit the command they are running is
    noise.
    """
    if exclude is not None:
        skip = set(exclude)
    else:
        me = os.getpid()
        skip = {me, os.getppid()} | _ancestor_pids(me, _windows_parent_map())
    if (platform if platform is not None else sys.platform) != "win32":
        return []

    def _default() -> str:
        try:
            done = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq searchts.exe", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return done.stdout or ""

    read = runner if runner is not None else _default
    pids: list[int] = []
    for row in csv.reader(io.StringIO(read())):
        if len(row) < 2 or row[0].strip().lower() != "searchts.exe":
            continue
        try:
            pid = int(row[1].strip())
        except ValueError:
            continue
        if pid not in skip:
            pids.append(pid)
    return pids


def format_lock_note(pids: Sequence[int]) -> str:
    if not pids:
        return ""
    lines = [
        "[yellow][!][/yellow] Windows: these PIDs have searchts.exe open. "
        "Quit them before a pip or pipx upgrade. This command does not kill them."
    ]
    lines.extend(f"  PID {pid}" for pid in pids)
    return "\n".join(lines)


def format_report(results: Dict[str, dict], lock_pids: Optional[Sequence[int]] = None) -> str:
    """Format results as a readable text report (with Rich markup)."""
    rich_escape: Optional[Callable[[str], str]]
    try:
        from rich.markup import escape as rich_escape_impl
    except ImportError:
        rich_escape = None
    else:
        rich_escape = rich_escape_impl

    def escape(value: str) -> str:
        return rich_escape(value) if rich_escape is not None else value

    lines = []
    lines.append("[bold cyan]searchts status[/bold cyan]")
    lines.append("[cyan]" + "=" * 40 + "[/cyan]")
    lines.append(r"Legend: [green]\[ok][/green] probe passed  [yellow][!][/yellow] present but needs login  [red][X][/red] not on PATH")

    ok_count = sum(1 for r in results.values() if r["status"] == "ok")
    total = len(results)

    lines.append("")
    lines.append(r"[bold]\[ok] Probes (not a routing table):[/bold]")
    for key, r in results.items():
        if r["tier"] == 0:
            name_msg = _name_msg(r, escape)
            if r["status"] == "ok":
                lines.append(rf"  [green]\[ok][/green] {name_msg}")
            elif r["status"] == "warn":
                lines.append(f"  [yellow][!][/yellow]  {name_msg}")
            elif r["status"] in ("off", "error"):
                lines.append(f"  [red][X][/red]  {name_msg}")

    tier1 = {k: r for k, r in results.items() if r["tier"] == 1}
    tier1_active = {k: r for k, r in tier1.items() if r["status"] == "ok"}
    tier1_inactive = {k: r for k, r in tier1.items() if r["status"] != "ok"}
    if tier1_active:
        lines.append("")
        lines.append("[bold]Optional CLIs present:[/bold]")
        for key, r in tier1_active.items():
            lines.append(rf"  [green]\[ok][/green] {_name_msg(r, escape)}")

    tier2 = {k: r for k, r in results.items() if r["tier"] == 2}
    tier2_active = {k: r for k, r in tier2.items() if r["status"] == "ok"}
    tier2_inactive = {k: r for k, r in tier2.items() if r["status"] != "ok"}
    if tier2_active:
        if not tier1_active:
            lines.append("")
            lines.append("[bold]Optional CLIs present:[/bold]")
        for key, r in tier2_active.items():
            lines.append(rf"  [green]\[ok][/green] {_name_msg(r, escape)}")

    lines.append("")
    status_color = "green" if ok_count == total else ("yellow" if ok_count > 0 else "red")
    lines.append(f"Status: [{status_color}]{ok_count}/{total}[/{status_color}] probes ok")

    all_inactive = list(tier1_inactive.values()) + list(tier2_inactive.values())
    if all_inactive:
        names = [r["name"] for r in all_inactive]
        lines.append(
            f"{len(names)} optional CLIs not present ({', '.join(names)}). "
            "These are PATH checks, not searchts platform readers."
        )

    import stat

    config_path = Config.CONFIG_DIR / "config.yaml"
    if config_path.exists() and sys.platform != "win32":
        try:
            mode = config_path.stat().st_mode
            if mode & (stat.S_IRGRP | stat.S_IROTH):
                lines.append("")
                lines.append(
                    "[bold red][!]  Security note: config.yaml permissions are too broad (readable by other users)[/bold red]"
                )
                lines.append("   Fix: chmod 600 ~/.searchts/config.yaml")
        except OSError:
            pass

    note = format_lock_note(windows_searchts_pids() if lock_pids is None else lock_pids)
    if note:
        lines.append("")
        lines.append(note)

    return "\n".join(lines)
