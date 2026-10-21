# -*- coding: utf-8 -*-
"""``searchts update`` / ``searchts upgrade``: move this install to the latest release.

The command that is running is the one that gets updated. pipx also upgrades
packages injected into that install. A venv keeps the extras already present.
A clean git checkout is fast-forwarded and reinstalled. uvx has no persistent
install; the uv cache for searchts is cleared so the next run resolves latest.

On Windows a running ``searchts.exe`` cannot be replaced. It is renamed aside
so the installer can write the new file. Processes are never killed. A copy
that is already newer than PyPI is not downgraded.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence

PYPI_JSON = "https://pypi.org/pypi/searchts/json"

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


def process_image() -> Optional[Path]:
    """The executable file of this process. Windows only; None elsewhere."""
    if sys.platform != "win32":
        return None
    import ctypes

    buf = ctypes.create_unicode_buffer(32768)
    n = ctypes.windll.kernel32.GetModuleFileNameW(None, buf, len(buf))
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
        dest = path.with_name(f"{path.name}.updating-{me}")
        if dest.exists():
            dest = path.with_name(f"{path.name}.updating-{me}-{len(parked)}")
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
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
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
        from searchts.doctor import windows_searchts_pids

        return list(windows_searchts_pids())
    except Exception:
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


def _print_pids(pids: Sequence[int], *, still_previous: bool) -> None:
    if not pids:
        return
    text = ", ".join(f"PID {pid}" for pid in pids)
    verb = "has" if len(pids) == 1 else "have"
    them = "it" if len(pids) == 1 else "them"
    if still_previous:
        print(
            f"{text} still {verb} searchts.exe open on the previous build. "
            f"This command does not kill {them}. A new command uses the updated install."
        )
        return
    print(f"Still open: {text}. This command does not kill {them}.")


def _blocked_message(pids: Sequence[int], plan: UpdatePlan) -> str:
    lines = [
        "Could not replace searchts.exe while it is still open. This command does not kill it.",
    ]
    if pids:
        lines.append("Still open: " + ", ".join(f"PID {pid}" for pid in pids) + ".")
    lines.append("Quit them, then run:")
    lines.extend("  " + format_argv(step.argv) for step in plan.steps)
    return "\n".join(lines)


def cmd_update(*, force: bool = False, dry_run: bool = False) -> int:
    """Update this install. ``searchts upgrade`` calls the same function."""
    import searchts as pkg
    from searchts.update_nudge import is_newer_version

    env = detect_env()
    local = pkg.__version__
    latest = fetch_pypi_version()
    if latest and env.kind != "editable" and is_newer_version(local, latest):
        print(f"This copy is v{local}, ahead of PyPI v{latest}. Not downgrading.")
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
        print(plan.message)
        return plan.code

    print(f"searchts v{local} ({kind_label(env.kind)})")
    print(plan.summary)
    _print_plan(plan)
    if dry_run:
        print("Dry run. Nothing was changed.")
        return 0

    if sys.stderr is not None:
        print("updating searchts…", file=sys.stderr, flush=True)

    parked: list[tuple[Path, Path]] = []
    if sys.platform == "win32" and env.kind != "ephemeral_uvx":
        image = process_image()
        parked = park_files(launcher_candidates(env.kind, env.python or sys.executable))
        if image_blocks_replace(image):
            settle_parked(parked)
            print(_blocked_message(other_lock_pids(), plan))
            return 2

    code = 0
    output = ""
    try:
        for step in plan.steps:
            try:
                code, output = run_step(step.argv, step.cwd)
            except OSError as exc:
                print(f"Could not run {format_argv(step.argv)}: {exc}")
                code, output = 2, str(exc)
            if code != 0:
                break
    finally:
        leftovers = settle_parked(parked)

    for path in leftovers:
        print(f"Left the previous executable at {path}. Delete it after this process exits.")

    if code != 0:
        if env.kind in {"pip", "venv", "editable"} and "externally-managed-environment" in output:
            print(_EXTERNALLY_MANAGED)
        print("Update did not finish.")
        _print_pids(other_lock_pids(), still_previous=False)
        return code

    if env.kind == "ephemeral_uvx":
        print("Cleared the uv cache for searchts. The next uvx run is the latest PyPI release.")
        print('Example: uvx --from "searchts[mcp]@latest" searchts --version')
        return 0

    launcher = primary_launcher(env.kind, env.python or sys.executable)
    installed = read_installed_version(launcher) if launcher is not None else None
    if installed is None:
        print("The installer finished, but the updated searchts --version could not be read.")
        _print_pids(other_lock_pids(), still_previous=False)
        _print_plan(plan)
        return 1
    if latest and is_newer_version(latest, installed):
        print(
            f"Upgrade did not take effect. This command is still v{installed}. "
            f"Latest on PyPI is v{latest}."
        )
        _print_pids(other_lock_pids(), still_previous=False)
        print("Run:")
        _print_plan(plan)
        return 1

    print(f"searchts v{installed}")
    copies: list[tuple[Path, Optional[str]]] = []
    for path in path_launchers():
        copies.append((path, read_installed_version(path)))
    for line in other_copy_notes(copies, launcher, installed):
        print(line)
    _print_pids(other_lock_pids(), still_previous=True)
    return 0
