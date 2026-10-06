# -*- coding: utf-8 -*-
"""F22: install the ``[browser]`` extra and Chromium into the running CLI env.

One keep-path command: ``searchts install --browser``. Detects pipx / uv tool /
venv / editable / ephemeral uvx. Chromium itself lives in the per-user
ms-playwright cache, so every env only needs patchright importable. uv tool and
ephemeral uvx envs are never pip-installed into; they get a one-line hint
instead. Doctor stays read-only.
"""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Callable, Mapping, Optional, Sequence

from searchts.update_nudge import _path_parts

#: Fallback if package metadata cannot be read.
_BROWSER_REQ_FALLBACK = "patchright>=1.50"

#: Exit code when the user has to act first. Nothing was changed.
EXIT_ACTION_NEEDED = 2

#: Hint when ephemeral uvx lacks patchright (re-run with the browser extra).
EPHEMERAL_UVX_HINT = (
    "This searchts is an ephemeral uvx run without patchright.\n"
    "Chromium is shared per-user (ms-playwright), but patchright only exists in "
    "a uvx env whose --from spec has the browser extra. Use that spec here and "
    "in your everyday commands:\n"
    '  uvx --from "searchts[mcp,browser]@latest" searchts install --browser\n'
    '  uvx --from "searchts[mcp,browser]" searchts read <url>\n'
    '  claude mcp add searchts -- uvx --from "searchts[mcp,browser]" searchts mcp serve'
)

#: Reminder after a uvx install: other --from specs resolve an env without patchright.
UVX_KEEP_NOTE = (
    'uvx: keep "browser" in your --from spec (for example "searchts[mcp,browser]"), '
    "including the MCP command. A spec without it has no stealth tier."
)

#: Hint when a persistent uv tool lacks patchright (never uv-pip into the tool env).
UV_TOOL_HINT = (
    "This searchts is a uv tool install without patchright. Adding it inside the "
    "tool env would be wiped on the next upgrade, so reinstall with the browser "
    "extra (on Windows, quit searchts.exe and mcp serve first, F11):\n"
    '  uv tool install "searchts[mcp,browser]" --force\n'
    "Then re-run: searchts install --browser"
)

#: Note when pipx is not on PATH, so the fallback install is not tracked by pipx.
PIPX_UNTRACKED_NOTE = (
    "pipx is not on PATH, so browser deps go straight into the pipx venv. "
    "pipx will not track them, and `pipx reinstall searchts` would drop them. "
    "Put pipx on PATH and re-run to have them tracked."
)

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


@dataclass(frozen=True)
class CliEnv:
    """Where this CLI's interpreter lives and how we mutate it."""

    kind: str  # ephemeral_uvx | uv_tool | pipx | editable | venv | pip
    label: str
    python: str


def _tick(msg: str) -> None:
    try:
        print(msg, file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass


def _default_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    """Capture stdout/stderr (pip / inject). Not for the Chromium download."""
    return subprocess.run(
        list(cmd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _stderr_fd() -> Optional[int]:
    """File descriptor behind ``sys.stderr``, or None when it has no real fd."""
    try:
        return sys.stderr.fileno()
    except (AttributeError, OSError, ValueError):
        return None


def _stream_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    """Run the Chromium download with all child output on stderr (P4.6).

    Progress streams live when stderr has a real fd. Otherwise the output is
    captured and replayed to stderr, so stdout stays clean either way.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (AttributeError, OSError, ValueError):
            pass
    fd = _stderr_fd()
    if fd is not None:
        return subprocess.run(list(cmd), stdout=fd, check=False)
    proc = subprocess.run(
        list(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.stdout:
        _tick(proc.stdout.rstrip())
    return proc


def _is_ephemeral_uvx(
    *,
    executable: Optional[str] = None,
    prefix: Optional[str] = None,
) -> bool:
    """True only for uv's ephemeral archive-v0 cache path.

    Do not key off UV_PYTHON / UVX / UV_RUNNING: those also appear under
    persistent pipx / uv tool / venv runs.
    """
    for raw in (executable or getattr(sys, "executable", ""), prefix or sys.prefix):
        if "archive-v0" in _path_parts(raw):
            return True
    return False


def _is_uv_tool_path(raw: str) -> bool:
    """True for persistent ``uv tool install`` prefixes (…/uv/tools/<pkg>)."""
    parts = _path_parts(raw)
    for i, part in enumerate(parts):
        if part == "uv" and i + 1 < len(parts) and parts[i + 1] == "tools":
            return True
        if part == "uv-tools":
            return True
    return False


def _is_pipx_venv_prefix(prefix: str) -> bool:
    """True when *prefix* is a default-location pipx app venv (…/pipx/venvs/<app>)."""
    parts = _path_parts(prefix)
    for i, part in enumerate(parts):
        if part == "pipx" and i + 1 < len(parts) and parts[i + 1] == "venvs":
            return True
    return False


def _split_path(value: str) -> list[str]:
    """Lower-cased parts of one path, parsed Windows-style when it looks Windows."""
    if not value:
        return []
    looks_windows = "\\" in value or (len(value) > 1 and value[1] == ":")
    pure = PureWindowsPath(value) if looks_windows else PurePosixPath(value)
    return [p.lower() for p in pure.parts if p.strip()]


def _is_under_pipx_home(prefix: str, environ: Mapping[str, str]) -> bool:
    """True when *prefix* sits in ``$PIPX_HOME/venvs`` (custom homes like ``~/.pipx``).

    PIPX_HOME is used as a location, never as a flag: a venv elsewhere stays a venv.
    """
    home = environ.get("PIPX_HOME")
    if not home or not prefix:
        return False
    base = _split_path(os.path.expanduser(home)) + ["venvs"]
    parts = _split_path(prefix)
    return len(parts) > len(base) and parts[: len(base)] == base


def _is_editable_install() -> bool:
    """True when the importable searchts tree is not under site/dist-packages."""
    try:
        import searchts
    except Exception:
        return False
    origin = getattr(searchts, "__file__", None)
    if not origin:
        return False
    from pathlib import Path

    parts = [p.lower() for p in Path(origin).resolve().parts]
    if "site-packages" in parts or "dist-packages" in parts:
        return False
    return True


def detect_cli_env(
    *,
    environ: Mapping[str, str] | None = None,
    executable: Optional[str] = None,
    prefix: Optional[str] = None,
    editable: Optional[bool] = None,
) -> CliEnv:
    """Classify the running CLI environment for browser install.

    Order: ephemeral uvx (archive-v0) -> uv tool -> pipx -> editable -> venv -> pip.
    """
    env = environ if environ is not None else os.environ
    exe = executable if executable is not None else getattr(sys, "executable", "")
    pref = prefix if prefix is not None else sys.prefix

    if _is_ephemeral_uvx(executable=exe, prefix=pref):
        return CliEnv(
            kind="ephemeral_uvx",
            label="ephemeral uvx (archive-v0)",
            python=exe,
        )

    if _is_uv_tool_path(exe) or _is_uv_tool_path(pref):
        return CliEnv(
            kind="uv_tool",
            label=f"uv tool env ({pref})",
            python=exe,
        )

    if (
        _is_pipx_venv_prefix(pref)
        or _is_pipx_venv_prefix(exe)
        or _is_under_pipx_home(pref, env)
    ):
        return CliEnv(
            kind="pipx",
            label=f"pipx env ({pref})",
            python=exe,
        )

    is_editable = _is_editable_install() if editable is None else editable
    if is_editable:
        return CliEnv(
            kind="editable",
            label=f"editable/source install ({pref})",
            python=exe,
        )

    if env.get("VIRTUAL_ENV"):
        return CliEnv(
            kind="venv",
            label=f"venv ({env.get('VIRTUAL_ENV')})",
            python=exe,
        )

    return CliEnv(
        kind="pip",
        label=f"pip/python env ({pref})",
        python=exe,
    )


def browser_extra_requirements() -> list[str]:
    """Requirement strings for the ``browser`` extra from package metadata.

    Every env installs these (e.g. ``patchright>=1.50``), never
    ``searchts[browser]``, so pip does not re-resolve searchts itself.
    """
    try:
        from importlib.metadata import requires
    except ImportError:  # pragma: no cover
        return [_BROWSER_REQ_FALLBACK]

    try:
        reqs = requires("searchts") or []
    except Exception:  # noqa: BLE001
        return [_BROWSER_REQ_FALLBACK]

    out: list[str] = []
    for raw in reqs:
        marker = ""
        spec = raw
        if ";" in raw:
            spec, marker = raw.split(";", 1)
            marker = marker.strip().lower()
        spec = spec.strip()
        if not spec:
            continue
        # importlib.metadata: 'patchright>=1.50; extra == "browser"'
        if 'extra == "browser"' in marker or "extra == 'browser'" in marker:
            out.append(spec)
    return out or [_BROWSER_REQ_FALLBACK]


def _patchright_importable() -> bool:
    try:
        import patchright  # noqa: F401
    except Exception:
        return False
    return True


def _extra_install_cmd(cli_env: CliEnv) -> list[str]:
    """Command that installs the browser extra's requirements into *cli_env*.

    pipx on PATH -> ``pipx inject`` (tracked). Anything else -> the env's own pip.
    Not used for uv tool / ephemeral uvx: those never get pip-installed into.
    """
    reqs = browser_extra_requirements()
    if cli_env.kind == "pipx":
        pipx = shutil.which("pipx")
        if pipx:
            return [pipx, "inject", "searchts", *reqs]
    return [cli_env.python, "-m", "pip", "install", *reqs]


def _chromium_install_cmd(cli_env: CliEnv) -> list[str]:
    return [cli_env.python, "-m", "patchright", "install", "chromium"]


def stealth_status() -> tuple[bool, str]:
    """Read-only stealth probe used after install (and printable without doctor).

    Returns (installed, message). Does not download or install anything.
    """
    # patchright may have been installed a moment ago by a child process.
    importlib.invalidate_caches()
    try:
        import patchright  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, f"stealth missing: patchright not importable ({type(exc).__name__})"
    return True, "stealth installed: patchright importable (Chromium install attempted)"


def _run_chromium(
    cmd: Sequence[str],
    *,
    runner: Optional[Runner],
) -> subprocess.CompletedProcess:
    """Run Chromium install; stream progress unless a test runner is injected."""
    if runner is not None:
        return runner(cmd)
    return _stream_runner(cmd)


def _install_chromium_and_check(
    chromium_cmd: Sequence[str],
    *,
    runner: Optional[Runner],
    dry_run: bool,
) -> int:
    """Shared tail for every env: Chromium download, then the read-only stealth check."""
    if dry_run:
        _tick(f"[dry-run] would run: {' '.join(chromium_cmd)}")
        _tick("[dry-run] would check stealth status")
        print("Dry run complete. No changes were made.")
        return 0

    _tick("downloading Chromium…")
    chromium = _run_chromium(chromium_cmd, runner=runner)
    if chromium.returncode != 0:
        err = ""
        if runner is not None:
            err = (chromium.stderr or chromium.stdout or "").strip()
        print(
            "[X] patchright install chromium failed.\n"
            f"  command: {' '.join(chromium_cmd)}\n"
            f"  {err or f'exit {chromium.returncode}'}",
            file=sys.stderr,
        )
        return 1

    _tick("checking stealth…")
    installed, message = stealth_status()
    marker = "[ok]" if installed else "[!]"
    print(f"{marker} {message}")
    if installed:
        print("Run searchts doctor for the full probe report (doctor stays read-only).")
        return 0
    print(
        "Stealth still missing after install. "
        "Try: python -m patchright install chromium",
        file=sys.stderr,
    )
    return 1


def install_browser(
    *,
    dry_run: bool = False,
    runner: Optional[Runner] = None,
    cli_env: Optional[CliEnv] = None,
) -> int:
    """Install the browser extra + Chromium into the CLI env. Returns the exit code."""
    run = runner or _default_runner
    env = cli_env or detect_cli_env()

    _tick(f"mutating: {env.label}")
    chromium_cmd = _chromium_install_cmd(env)

    # uv tool and ephemeral uvx are never pip-installed into. patchright must
    # already be on the env; Chromium itself goes to the per-user cache.
    if env.kind in ("ephemeral_uvx", "uv_tool"):
        if not _patchright_importable():
            hint = EPHEMERAL_UVX_HINT if env.kind == "ephemeral_uvx" else UV_TOOL_HINT
            print(hint, file=sys.stderr)
            return EXIT_ACTION_NEEDED
        code = _install_chromium_and_check(chromium_cmd, runner=runner, dry_run=dry_run)
        if code == 0 and env.kind == "ephemeral_uvx" and not dry_run:
            _tick(UVX_KEEP_NOTE)
        return code

    extra_cmd = _extra_install_cmd(env)
    untracked_pipx = env.kind == "pipx" and extra_cmd[1:2] != ["inject"]

    if dry_run:
        _tick(f"[dry-run] would run: {' '.join(extra_cmd)}")
        if untracked_pipx:
            _tick(PIPX_UNTRACKED_NOTE)
        return _install_chromium_and_check(chromium_cmd, runner=runner, dry_run=True)

    if untracked_pipx:
        _tick(PIPX_UNTRACKED_NOTE)
    _tick("installing [browser] extra…")
    extra = run(extra_cmd)
    if extra.returncode != 0:
        err = (extra.stderr or extra.stdout or "").strip()
        print(
            f"[X] failed to install browser deps into {env.kind} env.\n"
            f"  command: {' '.join(extra_cmd)}\n"
            f"  {err or f'exit {extra.returncode}'}",
            file=sys.stderr,
        )
        if env.kind == "pipx":
            print(
                "  Windows tip (F11): quit every searchts.exe / mcp serve before inject.",
                file=sys.stderr,
            )
        return 1

    return _install_chromium_and_check(chromium_cmd, runner=runner, dry_run=False)


def _req_name(spec: str) -> str:
    return spec.split(">=")[0].split("==")[0].split("[")[0].strip()


def uninstall_browser(
    *,
    dry_run: bool = False,
    chromium: bool = False,
    runner: Optional[Runner] = None,
    cli_env: Optional[CliEnv] = None,
) -> int:
    """Undo ``install --browser`` in this env. Chromium stays unless asked.

    Ephemeral uvx has nothing installed into it. pipx uses ``uninject``.
    Anything else uses that env's pip. The Chromium cache is shared, so it
    is removed only with ``chromium=True``.
    """
    run = runner or _default_runner
    env = cli_env or detect_cli_env()
    _tick(f"mutating: {env.label}")
    if env.kind == "ephemeral_uvx":
        print("ephemeral uvx has nothing to remove. Drop browser from the spec.")
        return 0
    names = [_req_name(spec) for spec in browser_extra_requirements()]
    pipx = shutil.which("pipx")
    if env.kind == "pipx" and pipx:
        cmd = [pipx, "uninject", "searchts", *names]
    else:
        cmd = [env.python, "-m", "pip", "uninstall", "-y", *names]
    chrome = [env.python, "-m", "patchright", "uninstall", "chromium"]
    if dry_run:
        _tick(f"[dry-run] would run: {' '.join(cmd)}")
        if chromium:
            _tick(f"[dry-run] would run: {' '.join(chrome)}")
        else:
            _tick("Chromium stays. It is a shared cache. Pass --chromium to remove it.")
        print("Dry run complete. No changes were made.")
        return 0
    extra = run(cmd)
    if extra.returncode != 0:
        err = (extra.stderr or extra.stdout or "").strip()
        print(f"[X] failed to remove browser deps.\n  {' '.join(cmd)}\n  {err or extra.returncode}", file=sys.stderr)
        return 1
    if not chromium:
        print("Chromium stays. It is a shared cache. Pass --chromium to remove it.")
        return 0
    dropped = run(chrome)
    if dropped.returncode != 0:
        err = (dropped.stderr or dropped.stdout or "").strip()
        print(f"[X] browser deps removed; Chromium uninstall failed.\n  {err or dropped.returncode}", file=sys.stderr)
        return 1
    print("browser deps and Chromium removed.")
    return 0
