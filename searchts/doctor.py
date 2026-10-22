# -*- coding: utf-8 -*-
"""Environment health checker — powered by channels.

Each channel knows how to check itself. Doctor just collects the results.
"""

import csv
import io
import os
import subprocess
import sys
from typing import Callable, Dict, Optional, Sequence

from searchts.channels import get_all_channels
from searchts.config import Config


def _tick(msg: str) -> None:
    # Best-effort only: a closed/broken stderr must never abort a check.
    from searchts import progress as _progress

    _progress.narrate(msg)


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


def _wrap_plain(text: str, width: int) -> list:
    """Wrap one message to *width*, keeping explicit newlines as breaks."""
    import textwrap

    out = []
    for line in str(text).splitlines() or [""]:
        if not line.strip():
            out.append("")
            continue
        out.extend(
            textwrap.wrap(
                line, width=width, break_long_words=True, break_on_hyphens=False,
            ) or [""]
        )
    return out or [""]


def _status_mark(status: str, unicode_ok: bool) -> tuple:
    """The mark and its colour. The mark alone carries the verdict."""
    if status == "ok":
        return ("✓" if unicode_ok else "+"), "green"
    if status == "warn":
        return "!", "yellow"
    return ("X" if unicode_ok else "x"), "red"


def _report_row(lines: list, style, status: str, name: str, message: str,
                unicode_ok: bool, *, active=None) -> None:
    """One probe: the mark and the name, then the sentence under it.

    The continuation indent is the point. At 71 columns a sentence about
    Instagram wraps three times; under the mark it looks like the same row, at
    column zero it looks like a new section.
    """
    mark, tone = _status_mark(status, unicode_ok)
    lines.append(f"  {getattr(style, tone)(mark)}  {style.bold(name)}")
    for chunk in _wrap_plain(message, 71):
        lines.append("     " + chunk if chunk else "")
    if active:
        lines.append("     " + style.dim(f"current backend: {active}"))


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
    """Name the PIDs that hold searchts.exe open, in the doctor's plain style."""
    if not pids:
        return ""
    wrapped = _wrap_plain(
        "Windows: these PIDs have searchts.exe open. Quit them before a pip or "
        "pipx upgrade. This command does not kill them.",
        71,
    )
    out = [f"!  {wrapped[0]}"] if wrapped else []
    out.extend("   " + chunk for chunk in wrapped[1:])
    out.extend(f"   PID {pid}" for pid in pids)
    return "\n".join(out)


def _active(r: dict):
    """The backend name, but only when the channel actually chose one."""
    if len(r.get("backends") or []) > 1:
        return r.get("active_backend")
    return None


def format_report(results: Dict[str, dict], lock_pids: Optional[Sequence[int]] = None,
                  *, color: Optional[bool] = None) -> str:
    """Format results as the doctor screen: a mark, a name, the sentence under it.

    Plain text with ANSI colour, not Rich markup, so the wrapping is ours: a
    channel sentence about Instagram folds under its own name instead of where
    the terminal happens to end. ``color`` defaults to whether stdout is a
    terminal; library callers pass ``False``.
    """
    from searchts import progress

    if color is None:
        color = progress.use_color(sys.stdout)
    unicode_ok = progress.supports_unicode(sys.stdout)
    s = progress.Style(color)

    ok_count = sum(1 for r in results.values() if r["status"] == "ok")
    total = len(results)
    tone = "green" if ok_count == total else ("yellow" if ok_count else "red")

    lines = [
        "",
        "  " + s.bold("searchts doctor"),
        "  " + s.dim("What each reader can do here. Probes, not a routing table."),
        "",
        "  " + getattr(s, tone)(f"{ok_count}/{total} probes passed"),
    ]

    probes = [r for r in results.values() if r["tier"] == 0]
    if probes:
        lines += ["", "  " + s.dim("PROBES")]
        for r in probes:
            _report_row(lines, s, r["status"], r["name"], r["message"],
                        unicode_ok, active=_active(r))

    optional = [r for r in results.values() if r["tier"] in (1, 2)]
    present = [r for r in optional if r["status"] == "ok"]
    missing = [r for r in optional if r["status"] != "ok"]
    if present:
        lines += ["", "  " + s.dim("OPTIONAL CLIS")]
        for r in present:
            _report_row(lines, s, r["status"], r["name"], r["message"],
                        unicode_ok, active=_active(r))

    if missing:
        names = ", ".join(r["name"] for r in missing)
        lines.append("")
        for chunk in _wrap_plain(
            f"{len(missing)} not present: {names}. These are PATH checks, "
            "not searchts platform readers.",
            71,
        ):
            lines.append("  " + s.dim(chunk))

    import stat

    config_path = Config.CONFIG_DIR / "config.yaml"
    if config_path.exists() and sys.platform != "win32":
        try:
            mode = config_path.stat().st_mode
            if mode & (stat.S_IRGRP | stat.S_IROTH):
                lines += [
                    "",
                    "  " + s.yellow("!") + "  config.yaml is readable by other users",
                    "     " + s.dim("Fix: chmod 600 ~/.searchts/config.yaml"),
                ]
        except OSError:
            pass

    note = format_lock_note(windows_searchts_pids() if lock_pids is None else lock_pids)
    if note:
        lines += [""] + ["  " + line for line in note.splitlines()]

    return "\n".join(lines)
