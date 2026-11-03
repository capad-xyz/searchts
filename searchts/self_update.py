# -*- coding: utf-8 -*-
"""``searchts update`` / ``searchts upgrade``: move this install to the latest release.

The command that is running is the one that gets updated. pipx also upgrades
packages injected into that install. A venv keeps the extras already present.
A clean git checkout is fast-forwarded and reinstalled. uvx has no persistent
install; the uv cache for searchts is cleared so the next run resolves latest.

On Windows a running exe can be renamed but not overwritten. Before ``uv tool
upgrade`` the entry-point ``searchts.exe`` is renamed to ``searchts.exe.old-<pid>``
so uv can write the new file at the old path. A detached helper is not used:
rename is one call and does not have to outlive this process. If uv fails
before the copy, the renamed file is put back. Leftover ``searchts.exe.old-*``
files are removed on the next start and at the next upgrade. Other searchts
processes are named (PID and command line) and are not killed. A copy that is
already newer than PyPI is not downgraded.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

PYPI_JSON = "https://pypi.org/pypi/searchts/json"
# One release document is a few kilobytes. Past this, the body is not a version.
_PYPI_MAX_BYTES = 1024 * 1024

#: Extra name -> distribution that means the extra is installed in this env.
_EXTRAS = (
    ("mcp", "mcp"),
    ("browser", "patchright"),
    ("cookies", "browser-cookie3"),
    ("local-transcribe", "faster-whisper"),
)

_KIND_LABEL = {
    "ephemeral_uvx": "uvx",
    "uv_tool": "uv tool",
    "pipx": "pipx",
    "editable": "editable checkout",
    "venv": "venv",
    "pip": "pip",
}

_EXTERNALLY_MANAGED = (
    "This Python is externally managed. The update did not pip install onto it.\n"
    '  pipx install "searchts[mcp]"\n'
    "  pipx upgrade searchts --include-injected"
)


@dataclass(frozen=True)
class Step:
    argv: tuple[str, ...]
    cwd: Optional[str] = None


@dataclass(frozen=True)
class UpdatePlan:
    kind: str
    steps: tuple[Step, ...]
    summary: str


@dataclass(frozen=True)
class UpdateRefusal:
    message: str
    code: int = 2


@dataclass(frozen=True)
class RepoState:
    root: Optional[str]
    dirty: bool
    error: Optional[str] = None


@dataclass(frozen=True)
class RunningSearchts:
    """One other ``searchts.exe``. ``command`` is empty when it could not be read."""

    pid: int
    command: str = ""


@dataclass(frozen=True)
class UvToolLayout:
    """Where a uv tool install keeps the env, and the exe uv will replace."""

    bin_dir: Optional[Path]
    bin_exe: Optional[Path]
    scripts_exe: Optional[Path]
    env_root: Optional[Path]
    env_version: Optional[str]
    had_bin: bool
    targets: tuple[Path, ...]


_TASKLIST_ARGV = (
    "tasklist",
    "/FO",
    "CSV",
    "/NH",
    "/FI",
    "IMAGENAME eq searchts.exe",
)
_PS_ARGV = (
    "powershell",
    "-NoProfile",
    "-NonInteractive",
    "-Command",
    (
        "Get-CimInstance Win32_Process -Filter \"Name = 'searchts.exe'\" "
        "| Select-Object ProcessId,CommandLine | ConvertTo-Csv -NoTypeInformation"
    ),
)
_WMIC_ARGV = (
    "wmic",
    "process",
    "where",
    "name='searchts.exe'",
    "get",
    "ProcessId,CommandLine",
    "/FORMAT:CSV",
)
_OLD_ENTRY = re.compile(r"searchts(?:\.exe)?\.old-\d+(?:-\d+)?\Z")
_METADATA_VERSION = re.compile(r"^Version:\s*(\S+)\s*$", re.MULTILINE)


def format_argv(argv: Sequence[str]) -> str:
    """One copy-pasteable command. Execution uses the list, not this string."""

    def quote(arg: str) -> str:
        if not arg or any(ch in arg for ch in ' \t"'):
            return '"' + arg.replace('"', r"\"") + '"'
        return arg

    return " ".join(quote(arg) for arg in argv)


def pip_spec(extras: Sequence[str]) -> str:
    """``searchts`` or ``searchts[mcp,browser]`` for extras this env already has."""
    wanted = set(extras)
    names = [extra for extra, _dist in _EXTRAS if extra in wanted]
    if not names:
        return "searchts"
    return "searchts[" + ",".join(names) + "]"


def editable_spec(extras: Sequence[str]) -> str:
    spec = pip_spec(extras)
    if spec == "searchts":
        return "."
    return ".[" + spec[len("searchts[") : -1] + "]"


def kind_label(kind: str) -> str:
    return _KIND_LABEL.get(kind, kind)


def _has_distribution(name: str) -> bool:
    from importlib.metadata import PackageNotFoundError, distribution

    try:
        distribution(name)
    except PackageNotFoundError:
        return False
    return True


def installed_extras() -> tuple[str, ...]:
    """Extras whose packages are installed in the environment that is running."""
    return tuple(extra for extra, dist in _EXTRAS if _has_distribution(dist))


def detect_env():
    """The running CLI environment (pipx, uv tool, uvx, editable, venv, pip)."""
    from searchts.browser_install import detect_cli_env

    return detect_cli_env()


def tool_path(name: str) -> Optional[str]:
    return shutil.which(name)


def inspect_repo() -> RepoState:
    """Git root of this source checkout, and whether tracked files are dirty."""
    try:
        import searchts
    except Exception:
        return RepoState(None, False, "searchts is not an importable checkout.")
    origin = getattr(searchts, "__file__", None)
    if not origin:
        return RepoState(None, False, "This is a source checkout without a file path.")
    start = Path(origin).resolve().parent
    root: Optional[Path] = None
    for parent in (start, *start.parents):
        if (parent / "pyproject.toml").is_file() and (parent / ".git").exists():
            root = parent
            break
    if root is None:
        return RepoState(None, False, "This is a source checkout without a git root.")
    git = tool_path("git")
    if not git:
        return RepoState(str(root), False, "git is not on PATH, so the checkout was not updated.")
    try:
        proc = subprocess.run(
            [git, "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        return RepoState(str(root), False, f"Could not read git status: {exc}")
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        return RepoState(str(root), False, detail or "Could not read git status.")
    return RepoState(str(root), bool(proc.stdout.strip()), None)


def build_plan(
    *,
    kind: str,
    force: bool,
    extras: Sequence[str],
    python: str,
    pipx: Optional[str],
    uv: Optional[str],
    git: Optional[str],
    repo: Optional[RepoState],
) -> UpdatePlan | UpdateRefusal:
    """The installer argv for this kind. No network and no subprocesses."""
    if kind == "pipx":
        if not pipx:
            return UpdateRefusal(
                "This copy is a pipx install, and pipx is not on PATH.\n"
                "  pipx upgrade searchts --include-injected"
            )
        argv = [pipx, "upgrade", "searchts", "--include-injected"]
        if force:
            argv.append("--force")
        return UpdatePlan(
            kind,
            (Step(tuple(argv)),),
            "Upgrade the pipx install and every package injected into it.",
        )

    if kind == "uv_tool":
        if not uv:
            return UpdateRefusal(
                "This copy is a uv tool install, and uv is not on PATH.\n  uv tool upgrade searchts"
            )
        argv = [uv, "tool", "upgrade", "searchts"]
        if force:
            argv.append("--reinstall")
        return UpdatePlan(
            kind,
            (Step(tuple(argv)),),
            "Upgrade the uv tool install to the latest release.",
        )

    if kind == "ephemeral_uvx":
        if not uv:
            return UpdateRefusal(
                "This copy is an ephemeral uvx run, and uv is not on PATH.\n"
                "  uv cache clean --force searchts\n"
                'Next run: uvx --from "searchts[mcp]@latest" searchts'
            )
        # --force: this process is using the cache, and a clean that bails
        # on in-use entries would leave the next run on the old build.
        return UpdatePlan(
            kind,
            (Step((uv, "cache", "clean", "--force", "searchts")),),
            "uvx has no persistent install. Clear its cache so the next run is the latest release.",
        )

    if kind == "editable":
        if repo is None or repo.error or not repo.root:
            message = repo.error if repo and repo.error else "This source checkout has no git root."
            return UpdateRefusal(message)
        if repo.dirty:
            return UpdateRefusal(
                "This checkout has uncommitted changes, so it was not updated.\n"
                f"  {format_argv((git or 'git', '-C', repo.root, 'pull', '--ff-only'))}\n"
                f"  {format_argv((python, '-m', 'pip', 'install', '-U', '-e', editable_spec(extras)))}"
            )
        if not git:
            return UpdateRefusal("git is not on PATH, so the checkout was not updated.")
        pip_argv = [python, "-m", "pip", "install", "-U"]
        if force:
            pip_argv.append("--force-reinstall")
        pip_argv.extend(["-e", editable_spec(extras)])
        return UpdatePlan(
            kind,
            (
                Step((git, "-C", repo.root, "pull", "--ff-only")),
                Step(tuple(pip_argv), cwd=repo.root),
            ),
            "Fast-forward this checkout and reinstall it in place.",
        )

    if not python:
        return UpdateRefusal("No Python interpreter for this install.")
    argv = [python, "-m", "pip", "install", "-U"]
    if force:
        argv.append("--force-reinstall")
    argv.append(pip_spec(extras))
    summary = "Upgrade this install in place, keeping the extras already installed."
    return UpdatePlan(kind, (Step(tuple(argv)),), summary)


def is_windows(platform: Optional[str] = None, name: Optional[str] = None) -> bool:
    """True on Windows. Tests pass ``platform`` / ``name`` or patch ``sys`` / ``os``."""
    plat = sys.platform if platform is None else platform
    os_name = os.name if name is None else name
    return plat == "win32" or os_name == "nt"


def process_image() -> Optional[Path]:
    """The executable file of this process. Windows only; None elsewhere."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(32768)
        n = ctypes.windll.kernel32.GetModuleFileNameW(None, buf, len(buf))
    except (AttributeError, OSError):
        return None
    if not n:
        return None
    return Path(buf.value)


def _launcher_candidates(
    kind: str,
    python: str,
    environ: Optional[Mapping[str, str]] = None,
) -> list[Path]:
    env = os.environ if environ is None else environ
    paths: list[Path] = []
    image = process_image()
    if image is not None:
        paths.append(image)
    if python:
        scripts = Path(python).parent
        paths.append(scripts / "searchts.exe")
        paths.append(scripts / "searchts")
    bin_dirs: list[Path] = []
    if kind in {"pipx", "uv_tool"}:
        raw = env.get("PIPX_BIN_DIR") or str(Path.home() / ".local" / "bin")
        bin_dirs.append(Path(raw))
        if kind == "uv_tool":
            bin_dirs.append(Path.home() / ".local" / "bin")
    for directory in bin_dirs:
        paths.append(directory / "searchts.exe")
        paths.append(directory / "searchts")

    found: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        if path.name.lower() not in {"searchts.exe", "searchts"}:
            continue
        key = os.path.normcase(os.path.abspath(str(path)))
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        found.append(path)
    return found


def launcher_candidates(
    kind: str,
    python: str,
    environ: Optional[Mapping[str, str]] = None,
) -> list[Path]:
    """Executables this update would replace.

    Under pytest this returns nothing, so a test cannot rename a real
    ``searchts.exe``. ``SEARCHTS_UPDATE_LIVE=1`` turns the real lookup back on.
    """
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("SEARCHTS_UPDATE_LIVE"):
        return []
    return _launcher_candidates(kind, python, environ)


def primary_launcher(kind: str, python: str) -> Optional[Path]:
    """The searchts executable a new command would run after this update."""
    found = _launcher_candidates(kind, python)
    if kind in {"pipx", "uv_tool"}:
        for path in reversed(found):
            if path.parent.name.lower() != "scripts":
                return path
    if found:
        return found[0]
    which = shutil.which("searchts")
    return Path(which) if which else None


def park_files(paths: Sequence[Path], pid: Optional[int] = None) -> list[tuple[Path, Path]]:
    """Rename each file aside. Returns ``(parked, original)`` for renames that worked.

    Windows allows a running executable to be renamed, and then a new file
    can be written at the old path. Deleting the running file fails, so the
    parked copy is removed only after the installer has replaced it.
    """
    me = os.getpid() if pid is None else pid
    parked: list[tuple[Path, Path]] = []
    for path in paths:
        if not path.is_file():
            continue
        dest = path.with_name(f"{path.name}.old-{me}")
        if dest.exists():
            dest = path.with_name(f"{path.name}.old-{me}-{len(parked)}")
        try:
            path.rename(dest)
        except OSError:
            continue
        parked.append((dest, path))
    return parked


def settle_parked(parked: Sequence[tuple[Path, Path]]) -> list[Path]:
    """Drop parked copies the installer replaced. Put back any it did not.

    Returns parked paths that could not be deleted (still mapped by this process).
    """
    leftovers: list[Path] = []
    for parked_path, original in parked:
        if not parked_path.exists():
            continue
        if original.exists():
            try:
                parked_path.unlink()
            except OSError:
                leftovers.append(parked_path)
        else:
            try:
                parked_path.rename(original)
            except OSError:
                leftovers.append(parked_path)
    return leftovers


def image_blocks_replace(image: Optional[Path]) -> bool:
    """True when this process's executable is still searchts.exe at its old path."""
    if image is None:
        return False
    if image.name.lower() not in {"searchts.exe", "searchts"}:
        return False
    return image.exists()


def _capture(argv: Sequence[str], timeout: float = 5) -> str:
    """stdout of a short helper. Empty on any failure. Never raises."""
    try:
        done = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout or ""


def _under_pytest() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) and not os.environ.get(
        "SEARCHTS_UPDATE_LIVE"
    )


def uv_tool_bin_dir(
    uv: str,
    *,
    capture: Optional[Callable[[Sequence[str]], str]] = None,
) -> Optional[Path]:
    """``uv tool dir --bin``. None when uv prints nothing."""
    if not uv:
        return None
    read = capture if capture is not None else _capture
    text = read((uv, "tool", "dir", "--bin")).strip()
    lines = [line.strip().strip('"') for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    return Path(lines[-1])


def _uv_bin_dir_for_update(uv: Optional[str]) -> Optional[Path]:
    """Bin dir for this upgrade. Under pytest this stays empty unless a test replaces it.

    Calling the real ``uv`` from a test would point at the machine install.
    """
    if not uv or _under_pytest():
        return None
    return uv_tool_bin_dir(uv)


def _live_which_searchts() -> Optional[str]:
    if _under_pytest():
        return None
    return shutil.which("searchts")


def _entry_points(paths: Sequence[Path]) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        if path.name.lower() not in {"searchts.exe", "searchts"}:
            continue
        key = os.path.normcase(os.path.abspath(str(path)))
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        found.append(path)
    return found


def uv_replace_targets(
    bin_dir: Optional[Path],
    argv0: str,
    which: Optional[str],
) -> list[Path]:
    """Entry-point exes ``uv tool upgrade`` will replace.

    The bin dir from ``uv tool dir --bin`` is the destination of the copy.
    ``argv0`` and ``which`` are used when that dir is unknown, and when they
    are the same directory (they are the file that is running). The tool
    env's ``Scripts\\searchts.exe`` is the source of the copy, not a target.
    """
    raw: list[Path] = []
    if bin_dir is not None:
        raw.append(bin_dir / "searchts.exe")
        raw.append(bin_dir / "searchts")
        for item in (argv0, which or ""):
            if not item:
                continue
            path = Path(item)
            try:
                if os.path.normcase(str(path.resolve().parent)) == os.path.normcase(
                    str(bin_dir.resolve())
                ):
                    raw.append(path)
            except OSError:
                continue
    else:
        for item in (argv0, which or ""):
            if item:
                raw.append(Path(item))
    return _entry_points(raw)


def tool_env_root(python: str) -> Optional[Path]:
    """``.../uv/tools/searchts`` from its ``Scripts/python.exe`` or ``bin/python``."""
    if not python:
        return None
    parent = Path(python).parent
    if parent.name.lower() in {"scripts", "bin"}:
        return parent.parent
    return None


def tool_scripts_exe(python: str) -> Optional[Path]:
    """The launcher inside the tool env, the file uv copies from."""
    if not python:
        return None
    parent = Path(python).parent
    names = ("searchts.exe", "searchts") if is_windows() else ("searchts", "searchts.exe")
    for name in names:
        candidate = parent / name
        if candidate.is_file():
            return candidate
    return None


def _version_key(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in version.split("."):
        digits = ""
        for ch in piece:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def dist_info_version(env_root: Optional[Path]) -> Optional[str]:
    """Version in the tool env's ``searchts-*.dist-info``, without running the exe."""
    if env_root is None:
        return None
    sites: list[Path] = []
    windows_site = env_root / "Lib" / "site-packages"
    if windows_site.is_dir():
        sites.append(windows_site)
    lib = env_root / "lib"
    if lib.is_dir():
        sites.extend(sorted(lib.glob("python*/site-packages")))
    found: list[str] = []
    for site in sites:
        for meta in site.glob("searchts-*.dist-info/METADATA"):
            try:
                text = meta.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            match = _METADATA_VERSION.search(text)
            if match:
                found.append(match.group(1))
    if not found:
        return None
    return max(found, key=_version_key)


def inspect_uv_tool_layout(
    python: str,
    uv: Optional[str],
    argv0: str,
    which: Optional[str],
    *,
    capture: Optional[Callable[[Sequence[str]], str]] = None,
) -> UvToolLayout:
    """Resolve the uv tool bin exe and the tool env. Does not rename anything."""
    if capture is not None and uv:
        bin_dir = uv_tool_bin_dir(uv, capture=capture)
    else:
        bin_dir = _uv_bin_dir_for_update(uv)
    targets = tuple(uv_replace_targets(bin_dir, argv0, which))
    bin_exe: Optional[Path] = None
    if bin_dir is not None:
        preferred = bin_dir / ("searchts.exe" if is_windows() else "searchts")
        alternate = bin_dir / ("searchts" if is_windows() else "searchts.exe")
        if preferred.is_file() or not alternate.is_file():
            bin_exe = preferred
        else:
            bin_exe = alternate
    elif targets:
        bin_exe = targets[0]
    root = tool_env_root(python)
    return UvToolLayout(
        bin_dir=bin_dir,
        bin_exe=bin_exe,
        scripts_exe=tool_scripts_exe(python),
        env_root=root,
        env_version=dist_info_version(root),
        had_bin=bool(bin_exe is not None and bin_exe.is_file()),
        targets=targets,
    )


def files_same(left: Path, right: Path) -> bool:
    """True when both paths are files with the same bytes."""
    try:
        if not left.is_file() or not right.is_file():
            return False
        if left.stat().st_size != right.stat().st_size:
            return False

        def digest(path: Path) -> bytes:
            hasher = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    hasher.update(chunk)
            return hasher.digest()

        return digest(left) == digest(right)
    except OSError:
        return False


def copy_outstanding(
    bin_exe: Optional[Path],
    scripts_exe: Optional[Path],
    *,
    had_bin: bool,
) -> bool:
    """True when the tool-env launcher is not the file in the bin dir."""
    if scripts_exe is None or not scripts_exe.is_file() or bin_exe is None:
        return False
    try:
        if bin_exe.resolve() == scripts_exe.resolve():
            return False
    except OSError:
        pass
    if not bin_exe.is_file():
        return had_bin
    return not files_same(bin_exe, scripts_exe)


def half_finished_message(env_version: Optional[str], retry: str) -> str:
    if env_version:
        head = (
            f"Half-finished upgrade: the uv tool environment is v{env_version}, "
            "but searchts.exe was not replaced."
        )
    else:
        head = (
            "Half-finished upgrade: the uv tool environment changed, "
            "but searchts.exe was not replaced."
        )
    return head + f"\nRetry: {retry}"


def _old_entry_name(name: str) -> bool:
    return _OLD_ENTRY.fullmatch(name) is not None


def sweep_old_entry_points(directories: Sequence[Path]) -> list[Path]:
    """Delete leftover ``searchts.exe.old-<pid>`` files. Best-effort. Never raises."""
    removed: list[Path] = []
    seen: set[str] = set()
    for directory in directories:
        try:
            key = os.path.normcase(os.path.abspath(str(directory)))
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        try:
            if not directory.is_dir():
                continue
            entries = list(directory.iterdir())
        except OSError:
            continue
        for path in entries:
            if not _old_entry_name(path.name):
                continue
            try:
                path.unlink()
            except OSError:
                continue
            removed.append(path)
    return removed


def stale_exe_dirs() -> list[Path]:
    """Directories that can hold a renamed entry point. Empty under pytest and off Windows."""
    if _under_pytest() or not is_windows():
        return []
    dirs: list[Path] = []
    argv0 = sys.argv[0] if sys.argv else ""
    if argv0:
        dirs.append(Path(argv0).resolve().parent)
    found = shutil.which("searchts")
    if found:
        dirs.append(Path(found).resolve().parent)
    dirs.append(Path.home() / ".local" / "bin")
    return dirs


def sweep_stale_exes() -> list[Path]:
    """Drop leftover renamed exes at process start. Silent on failure."""
    try:
        return sweep_old_entry_points(stale_exe_dirs())
    except Exception:  # noqa: BLE001 - a sweep must never break a command
        return []


def parse_tasklist_pids(text: str) -> list[int]:
    """PIDs from ``tasklist /FO CSV /NH`` rows whose image is ``searchts.exe``."""
    pids: list[int] = []
    for row in csv.reader(io.StringIO(text or "")):
        if len(row) < 2 or row[0].strip().lower() != "searchts.exe":
            continue
        try:
            pids.append(int(row[1].strip()))
        except ValueError:
            continue
    return pids


def parse_process_commands(text: str) -> dict[int, str]:
    """PID to command line from PowerShell ``ConvertTo-Csv`` or WMIC CSV."""
    found: dict[int, str] = {}
    rows = list(csv.reader(io.StringIO(text or "")))
    header_at: Optional[int] = None
    pid_col: Optional[int] = None
    cmd_col: Optional[int] = None
    for index, row in enumerate(rows):
        lowered = [cell.strip().lower() for cell in row]
        if "processid" not in lowered:
            continue
        header_at = index
        pid_col = lowered.index("processid")
        if "commandline" in lowered:
            cmd_col = lowered.index("commandline")
        break
    if header_at is None or pid_col is None:
        return found
    for row in rows[header_at + 1 :]:
        if pid_col >= len(row):
            continue
        raw = row[pid_col].strip()
        if not raw.isdigit():
            continue
        command = ""
        if cmd_col is not None and cmd_col < len(row):
            command = row[cmd_col].strip()
        found[int(raw)] = command
    return found


def _skip_pids() -> set[int]:
    """This process, its parent, and every ancestor. The running upgrade is not 'other'."""
    me = os.getpid()
    skip = {me}
    try:
        skip.add(os.getppid())
    except OSError:
        pass
    if not is_windows():
        return skip
    try:
        from searchts.doctor import _ancestor_pids, _windows_parent_map

        skip |= set(_ancestor_pids(me, _windows_parent_map()))
    except Exception:  # noqa: BLE001 - PIDs without the chain still exclude this process
        return skip
    return skip


def running_searchts(
    *,
    platform: Optional[str] = None,
    os_name: Optional[str] = None,
    capture: Optional[Callable[[Sequence[str]], str]] = None,
    exclude: Optional[Sequence[int]] = None,
) -> list[RunningSearchts]:
    """Other ``searchts.exe`` processes. Empty off Windows. Does not kill.

    Command lines come from PowerShell ``Get-CimInstance Win32_Process``, then
    WMIC if that prints nothing. A missing command line still keeps the PID.
    """
    if not is_windows(platform, os_name):
        return []
    read = capture if capture is not None else _capture
    pids = parse_tasklist_pids(read(_TASKLIST_ARGV))
    commands = parse_process_commands(read(_PS_ARGV))
    if not commands:
        commands = parse_process_commands(read(_WMIC_ARGV))
    skip = set(exclude) if exclude is not None else _skip_pids()
    return [
        RunningSearchts(pid, commands.get(pid, ""))
        for pid in pids
        if pid not in skip
    ]


def sharing_violation_message(
    output: str,
    procs: Sequence[RunningSearchts],
    retry: str,
) -> Optional[str]:
    """Plain text for a uv failure that is Windows error 32. None otherwise."""
    if "os error 32" not in (output or "").lower():
        return None
    lines = [
        "Windows could not replace searchts.exe because a program still has it open "
        "(os error 32). This command does not kill it.",
    ]
    if procs:
        lines.append("Still running:")
        for proc in procs:
            if proc.command:
                lines.append(f"PID {proc.pid}  {proc.command}")
            else:
                lines.append(f"PID {proc.pid}  searchts.exe")
    else:
        lines.append(
            "No other searchts.exe was listed. Close any agent that started searchts, then retry."
        )
    lines.append("If one is an MCP server, close the agent app or restart its MCP.")
    lines.append(f"Retry: {retry}")
    return "\n".join(lines)


def fetch_pypi_version(timeout: float = 15.0) -> Optional[str]:
    """Latest searchts version on PyPI, or None when PyPI cannot be read."""
    import searchts as pkg

    req = urllib.request.Request(
        PYPI_JSON,
        headers={
            "Accept": "application/json",
            "User-Agent": f"searchts/{pkg.__version__} (update)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            raw = resp.read(_PYPI_MAX_BYTES + 1)
            if len(raw) > _PYPI_MAX_BYTES:
                return None
            data = json.loads(raw.decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError, OSError):
        return None
    version = str((data.get("info") or {}).get("version") or "").strip()
    return version or None


def run_step(argv: Sequence[str], cwd: Optional[str] = None) -> tuple[int, str]:
    """Run one installer command. Refuses to do that under pytest."""
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("SEARCHTS_UPDATE_LIVE"):
        raise RuntimeError("refusing to run an installer under pytest")
    proc = subprocess.Popen(
        list(argv),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out, err = proc.communicate()
    if out:
        print(out, end="" if out.endswith("\n") else "\n")
    if err and sys.stderr is not None:
        print(err, end="" if err.endswith("\n") else "\n", file=sys.stderr)
    return proc.returncode, (out or "") + (err or "")


def read_installed_version(launcher: Path) -> Optional[str]:
    """Version printed by a launcher, with this process's PYTHONPATH removed."""
    import re

    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTEST_CURRENT_TEST", None)
    try:
        proc = subprocess.run(
            [str(launcher), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=str(Path.home()),
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    match = re.search(r"(\d+\.\d+\.\d+)", text)
    if proc.returncode != 0 or match is None:
        return None
    return match.group(1)


def other_lock_pids() -> list[int]:
    """Other searchts.exe PIDs. Empty off Windows. Never kills."""
    try:
        return [proc.pid for proc in running_searchts()]
    except Exception:  # noqa: BLE001 - a PID lookup must not abort the upgrade
        return []


def path_launchers() -> list[Path]:
    """Every searchts executable on PATH. Empty under pytest."""
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("SEARCHTS_UPDATE_LIVE"):
        return []
    found: list[Path] = []
    seen: set[str] = set()
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        base = Path(directory)
        for name in ("searchts.exe", "searchts"):
            candidate = base / name
            key = os.path.normcase(os.path.abspath(str(candidate)))
            if key in seen or not candidate.is_file():
                continue
            seen.add(key)
            found.append(candidate)
    return found


def other_copy_notes(
    copies: Sequence[tuple[Path, Optional[str]]],
    primary: Optional[Path],
    installed: str,
) -> list[str]:
    """Lines for PATH copies this command did not update."""
    notes: list[str] = []
    primary_key = None
    if primary is not None:
        try:
            primary_key = os.path.normcase(str(primary.resolve()))
        except OSError:
            primary_key = os.path.normcase(str(primary))
    for path, version in copies:
        try:
            key = os.path.normcase(str(path.resolve()))
        except OSError:
            key = os.path.normcase(str(path))
        if primary_key is not None and key == primary_key:
            continue
        if version and version != installed:
            notes.append(f"Another searchts on PATH is still v{version}: {path}")
    if notes:
        notes.append("This command updates the copy that is running.")
    return notes


def _print_plan(plan: UpdatePlan) -> None:
    for step in plan.steps:
        print("  " + format_argv(step.argv))


def _pids_text(pids: Sequence[int], *, still_previous: bool) -> str:
    if not pids:
        return ""
    text = ", ".join(f"PID {pid}" for pid in pids)
    verb = "has" if len(pids) == 1 else "have"
    them = "it" if len(pids) == 1 else "them"
    if still_previous:
        return (
            f"{text} still {verb} searchts.exe open on the previous build. "
            f"This command does not kill {them}. A new command uses the updated install."
        )
    return f"Still open: {text}. This command does not kill {them}."


def format_running_note(procs: Sequence[RunningSearchts], *, still_previous: bool) -> str:
    """PID sentence plus command lines, when another searchts is open."""
    head = _pids_text([proc.pid for proc in procs], still_previous=still_previous)
    if not head:
        return ""
    lines = [head]
    for proc in procs:
        if proc.command:
            lines.append(f"PID {proc.pid}  {proc.command}")
    lines.append("If one is an MCP server, close the agent app or restart its MCP.")
    return "\n".join(lines)


def _print_pids(pids: Sequence[int], *, still_previous: bool) -> None:
    text = _pids_text(pids, still_previous=still_previous)
    if text:
        print(text)


def _step_label(step: Step) -> str:
    """The row's short name for an installer command."""
    argv = list(step.argv)
    exe = Path(argv[0]).name.lower() if argv else ""
    if "pipx" in exe:
        return "pipx upgrade"
    if "uv" in exe:
        if "tool" in argv:
            return "uv tool upgrade"
        if "cache" in argv:
            return "uv cache clean"
        return "uv"
    if "git" in exe:
        return "git pull"
    if "python" in exe and "-m" in argv and "pip" in argv:
        return "pip install"
    return exe or "step"


def _last_log_line(text: str) -> str:
    """One useful line of installer output for a live row."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    preferred = (
        "Successfully installed",
        "Successfully uninstalled",
        "Installed",
        "Upgraded",
        "error",
        "ERROR",
        "failed",
        "Refused",
    )
    for line in reversed(lines):
        if any(token in line for token in preferred):
            return line
    return lines[-1]


def _update_receipt(tracker, command: str, rows, *, status: str, subject: str) -> str:
    from searchts import receipts

    style, unicode_ok = receipts.for_stream(sys.stdout)
    return receipts.block(
        style,
        command,
        rows,
        subject=subject,
        elapsed=tracker.elapsed(),
        status=status,
        unicode_ok=unicode_ok,
    )


def _emit_update(tracker, text: str) -> None:
    from searchts import receipts

    receipts.emit(tracker, text, stream=sys.stdout)


def _blocked_message(procs: Sequence[RunningSearchts], plan: UpdatePlan) -> str:
    lines = [
        "Could not replace searchts.exe while it is still open. This command does not kill it.",
    ]
    if procs:
        lines.append("Still open: " + ", ".join(f"PID {proc.pid}" for proc in procs) + ".")
        for proc in procs:
            if proc.command:
                lines.append(f"PID {proc.pid}  {proc.command}")
        lines.append("If one is an MCP server, close the agent app or restart its MCP.")
    lines.append("Quit them, then run:")
    lines.extend("  " + format_argv(step.argv) for step in plan.steps)
    return "\n".join(lines)


def uv_half_note(
    layout: Optional[UvToolLayout],
    *,
    bin_written: bool,
    retry: str,
) -> str:
    """Text when the bin exe was not replaced and the tool env moved. Empty otherwise.

    A file uv just wrote is trusted. Byte-comparing it with ``Scripts\\searchts.exe``
    would cry wolf when the bin launcher is not a raw copy of that file.
    """
    if layout is None or bin_written or not layout.had_bin:
        return ""
    version_now = dist_info_version(layout.env_root)
    outstanding = copy_outstanding(
        layout.bin_exe,
        layout.scripts_exe,
        had_bin=layout.had_bin,
    )
    version_changed = bool(
        version_now and layout.env_version and version_now != layout.env_version
    )
    if not outstanding and not version_changed:
        return ""
    return half_finished_message(version_now or layout.env_version, retry)


def cmd_update(
    *,
    force: bool = False,
    dry_run: bool = False,
    command: str = "update",
) -> int:
    """Update this install. ``searchts upgrade`` calls the same function."""
    import contextlib
    import io

    import searchts as pkg
    from searchts import progress, receipts
    from searchts.update_nudge import is_newer_version

    env = detect_env()
    local = pkg.__version__
    subject = f"searchts v{local} ({kind_label(env.kind)})"

    tracker = progress.live(command, summary_stream=sys.stdout)
    with tracker:
        # The PyPI round-trip is the first wait, so it is the first row.
        if tracker.is_live:
            tracker.stage("checking PyPI")
        latest = fetch_pypi_version()
        if tracker.is_live:
            tracker.settle(
                progress.ROW_OK if latest else progress.ROW_SKIP,
                f"v{latest}" if latest else "PyPI unreachable",
            )

        if latest and env.kind != "editable" and is_newer_version(local, latest):
            _emit_update(
                tracker,
                _update_receipt(
                    tracker,
                    command,
                    [receipts.Row(
                        progress.ROW_SKIP,
                        "ahead",
                        f"This copy is v{local}, ahead of PyPI v{latest}. Not downgrading.",
                    )],
                    status=progress.ROW_OK,
                    subject=subject,
                ),
            )
            return 0

        repo = inspect_repo() if env.kind == "editable" else None
        plan = build_plan(
            kind=env.kind,
            force=force,
            extras=installed_extras(),
            python=env.python or sys.executable,
            pipx=tool_path("pipx"),
            uv=tool_path("uv"),
            git=tool_path("git"),
            repo=repo,
        )
        if isinstance(plan, UpdateRefusal):
            _emit_update(
                tracker,
                _update_receipt(
                    tracker,
                    command,
                    [receipts.Row(progress.ROW_FAIL, "reason", plan.message)],
                    status=progress.ROW_FAIL,
                    subject=subject,
                ),
            )
            return plan.code

        if dry_run:
            commands = "\n".join(format_argv(step.argv) for step in plan.steps)
            _emit_update(
                tracker,
                _update_receipt(
                    tracker,
                    command,
                    [receipts.Row(
                        progress.ROW_SKIP,
                        "dry run",
                        f"Dry run. Nothing was changed.\nWould run:\n{commands}",
                    )],
                    status=progress.ROW_OK,
                    subject=subject,
                ),
            )
            return 0

        if not tracker.is_live and sys.stderr is not None:
            print("updating searchts…", file=sys.stderr, flush=True)

        procs = list(running_searchts())
        if procs and sys.stderr is not None and not tracker.is_live:
            print(
                format_running_note(procs, still_previous=False),
                file=sys.stderr,
                flush=True,
            )

        parked: list[tuple[Path, Path]] = []
        layout: Optional[UvToolLayout] = None
        bin_written = False
        if is_windows() and env.kind != "ephemeral_uvx":
            if env.kind == "uv_tool":
                layout = inspect_uv_tool_layout(
                    env.python or sys.executable,
                    tool_path("uv"),
                    sys.argv[0] if sys.argv else "",
                    _live_which_searchts(),
                )
                sweep_dirs = [path.parent for path in layout.targets]
                if layout.bin_dir is not None:
                    sweep_dirs.append(layout.bin_dir)
                sweep_old_entry_points(sweep_dirs)
                parked = park_files(layout.targets)
            else:
                parked = park_files(
                    launcher_candidates(env.kind, env.python or sys.executable)
                )
            image = process_image()
            if image_blocks_replace(image):
                settle_parked(parked)
                _emit_update(
                    tracker,
                    _update_receipt(
                        tracker,
                        command,
                        [receipts.Row(
                            progress.ROW_FAIL,
                            "reason",
                            _blocked_message(procs, plan),
                        )],
                        status=progress.ROW_FAIL,
                        subject=subject,
                    ),
                )
                return 2

        code = 0
        output = ""
        step_rows = []
        try:
            for step in plan.steps:
                label = _step_label(step)
                if tracker.is_live:
                    tracker.stage(label, format_argv(step.argv))
                try:
                    if tracker.is_live:
                        # run_step still prints the installer's own output;
                        # capture it so the cursor-up block is never mixed
                        # with a subprocess line. The row carries the last
                        # useful line, which is pip's verdict.
                        buf_out, buf_err = io.StringIO(), io.StringIO()
                        with contextlib.redirect_stdout(buf_out), \
                                contextlib.redirect_stderr(buf_err):
                            code, output = run_step(step.argv, step.cwd)
                        log = (buf_out.getvalue() + buf_err.getvalue()).strip()
                    else:
                        code, output = run_step(step.argv, step.cwd)
                        log = output
                except OSError as exc:
                    code = 2
                    output = str(exc)
                    log = f"Could not run {format_argv(step.argv)}: {exc}"
                    if not tracker.is_live:
                        print(log)
                detail = _last_log_line(log) if code == 0 else (
                    _last_log_line(log) or f"exit {code}"
                )
                if tracker.is_live:
                    tracker.settle(
                        progress.ROW_OK if code == 0 else progress.ROW_FAIL,
                        detail or format_argv(step.argv),
                    )
                step_rows.append(receipts.Row(
                    progress.ROW_OK if code == 0 else progress.ROW_FAIL,
                    label,
                    detail or format_argv(step.argv),
                ))
                if code != 0:
                    break
        finally:
            if layout is not None and layout.bin_exe is not None:
                bin_written = layout.bin_exe.exists()
            leftovers = settle_parked(parked)

        half = uv_half_note(
            layout,
            bin_written=bin_written,
            retry=f"searchts {command} --force",
        )
        retry = f"searchts {command} --force" if half else f"searchts {command}"

        leftover_rows = [
            receipts.Row(
                progress.ROW_WARN,
                "previous",
                f"Left the previous executable at {path}. Delete it after this process exits.",
            )
            for path in leftovers
        ]

        if code != 0:
            rows = list(step_rows)
            if env.kind in {"pip", "venv", "editable"} and "externally-managed-environment" in output:
                rows.append(receipts.Row(progress.ROW_WARN, "system Python", _EXTERNALLY_MANAGED))
            reason = sharing_violation_message(output, procs, retry)
            rows.append(receipts.Row(
                progress.ROW_FAIL,
                "reason",
                reason or "Update did not finish.",
            ))
            note = "" if reason else format_running_note(procs, still_previous=False)
            if note:
                rows.append(receipts.Row(progress.ROW_WARN, "still open", note))
            if half:
                rows.append(receipts.Row(progress.ROW_FAIL, "half-finished", half))
            rows.extend(leftover_rows)
            _emit_update(
                tracker,
                _update_receipt(
                    tracker,
                    command,
                    rows,
                    status=progress.ROW_FAIL,
                    subject=subject,
                ),
            )
            return code

        if half:
            rows = list(step_rows)
            rows.append(receipts.Row(progress.ROW_FAIL, "half-finished", half))
            note = format_running_note(procs, still_previous=False)
            if note:
                rows.append(receipts.Row(progress.ROW_WARN, "still open", note))
            rows.extend(leftover_rows)
            _emit_update(
                tracker,
                _update_receipt(
                    tracker,
                    command,
                    rows,
                    status=progress.ROW_FAIL,
                    subject=subject,
                ),
            )
            return 1

        if env.kind == "ephemeral_uvx":
            rows = list(step_rows)
            rows.extend(leftover_rows)
            rows.append(receipts.Row(
                progress.ROW_OK,
                "now on",
                "Cleared the uv cache for searchts. The next uvx run is the latest PyPI release.",
            ))
            _emit_update(
                tracker,
                _update_receipt(
                    tracker,
                    command,
                    rows,
                    status=progress.ROW_OK,
                    subject=subject,
                ),
            )
            return 0

        launcher = primary_launcher(env.kind, env.python or sys.executable)
        installed = read_installed_version(launcher) if launcher is not None else None
        if installed is None:
            rows = list(step_rows)
            rows.extend(leftover_rows)
            rows.append(receipts.Row(
                progress.ROW_FAIL,
                "version",
                "The installer finished, but the updated searchts --version could not be read.",
            ))
            note = format_running_note(procs, still_previous=False)
            if note:
                rows.append(receipts.Row(progress.ROW_WARN, "still open", note))
            rows.extend(
                receipts.Row(progress.ROW_SKIP, _step_label(step), format_argv(step.argv))
                for step in plan.steps
            )
            _emit_update(
                tracker,
                _update_receipt(
                    tracker,
                    command,
                    rows,
                    status=progress.ROW_FAIL,
                    subject=subject,
                ),
            )
            return 1

        if latest and is_newer_version(latest, installed):
            rows = list(step_rows)
            rows.append(receipts.Row(
                progress.ROW_FAIL,
                "version",
                f"Upgrade did not take effect. This command is still v{installed}. "
                f"Latest on PyPI is v{latest}.",
            ))
            note = format_running_note(procs, still_previous=False)
            if note:
                rows.append(receipts.Row(progress.ROW_WARN, "still open", note))
            rows.extend(leftover_rows)
            rows.extend(
                receipts.Row(progress.ROW_SKIP, _step_label(step), format_argv(step.argv))
                for step in plan.steps
            )
            _emit_update(
                tracker,
                _update_receipt(
                    tracker,
                    command,
                    rows,
                    status=progress.ROW_FAIL,
                    subject=subject,
                ),
            )
            return 1

        copies: list[tuple[Path, Optional[str]]] = []
        for path in path_launchers():
            copies.append((path, read_installed_version(path)))
        rows = list(step_rows)
        rows.extend(leftover_rows)
        rows.append(receipts.Row(progress.ROW_OK, "now on", f"v{installed}"))
        for line in other_copy_notes(copies, launcher, installed):
            rows.append(receipts.Row(progress.ROW_WARN, "other copy", line))
        note = format_running_note(procs, still_previous=True)
        if note:
            rows.append(receipts.Row(progress.ROW_WARN, "still open", note))
        _emit_update(
            tracker,
            _update_receipt(
                tracker,
                command,
                rows,
                status=progress.ROW_OK,
                subject=f"searchts v{installed} ({kind_label(env.kind)})",
            ),
        )
        return 0
