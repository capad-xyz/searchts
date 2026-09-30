# -*- coding: utf-8 -*-
"""F22: install ``searchts[browser]`` + Chromium into the running CLI env.

One keep-path command: ``searchts install --browser``. Detects pipx / uv tool /
venv / editable, refuses ephemeral uvx (cannot persist), and leaves doctor
read-only.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

from searchts.update_nudge import UV_ENV_KEYS, _path_parts

#: Spec installed into the active environment for the stealth tier.
BROWSER_EXTRA_SPEC = "searchts[browser]"

#: Hint when the CLI is an ephemeral uvx cache that cannot keep Chromium.
EPHEMERAL_UVX_HINT = (
    "This searchts is an ephemeral uvx run; Chromium cannot be kept here.\n"
    "Keep-install first, then retry:\n"
    '  pipx install "searchts[mcp]"\n'
    "  searchts install --browser"
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
    return subprocess.run(
        list(cmd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _is_ephemeral_uvx(
    *,
    environ: Optional[dict] = None,
    executable: Optional[str] = None,
    prefix: Optional[str] = None,
) -> bool:
    env = environ if environ is not None else os.environ
    if any(env.get(key) for key in UV_ENV_KEYS):
        return True
    for raw in (executable or getattr(sys, "executable", ""), prefix or sys.prefix):
        parts = _path_parts(raw)
        if "archive-v0" in parts:
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


def _is_pipx_path(raw: str, *, environ: Optional[dict] = None) -> bool:
    env = environ if environ is not None else os.environ
    if env.get("PIPX_HOME"):
        return True
    parts = _path_parts(raw)
    return "pipx" in parts or "pipx" in raw.lower()


def _is_editable_install() -> bool:
    """True when the importable searchts tree is not under site/dist-packages."""
    try:
        import searchts
    except Exception:
        return False
    origin = getattr(searchts, "__file__", None)
    if not origin:
        return False
    parts = [p.lower() for p in Path(origin).resolve().parts]
    if "site-packages" in parts or "dist-packages" in parts:
        return False
    return True


def detect_cli_env(
    *,
    environ: Optional[dict] = None,
    executable: Optional[str] = None,
    prefix: Optional[str] = None,
    editable: Optional[bool] = None,
) -> CliEnv:
    """Classify the running CLI environment for browser install.

    Order: ephemeral uvx (refuse) -> uv tool -> pipx -> editable -> venv -> pip.
    """
    env = environ if environ is not None else os.environ
    exe = executable if executable is not None else getattr(sys, "executable", "")
    pref = prefix if prefix is not None else sys.prefix

    if _is_ephemeral_uvx(environ=env, executable=exe, prefix=pref):
        return CliEnv(
            kind="ephemeral_uvx",
            label="ephemeral uvx (not persistent)",
            python=exe,
        )

    if _is_uv_tool_path(exe) or _is_uv_tool_path(pref):
        return CliEnv(
            kind="uv_tool",
            label=f"uv tool env ({pref})",
            python=exe,
        )

    if _is_pipx_path(exe, environ=env) or _is_pipx_path(pref, environ=env):
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


def _extra_install_cmd(cli_env: CliEnv) -> list[str]:
    """Command that installs ``searchts[browser]`` into *cli_env*."""
    if cli_env.kind == "pipx":
        pipx = shutil.which("pipx")
        if pipx:
            return [pipx, "inject", "searchts", BROWSER_EXTRA_SPEC]
        return [cli_env.python, "-m", "pip", "install", BROWSER_EXTRA_SPEC]

    if cli_env.kind == "uv_tool":
        uv = shutil.which("uv")
        if uv:
            return [uv, "pip", "install", "--python", cli_env.python, BROWSER_EXTRA_SPEC]
        return [cli_env.python, "-m", "pip", "install", BROWSER_EXTRA_SPEC]

    if cli_env.kind == "editable":
        return [cli_env.python, "-m", "pip", "install", "patchright>=1.50"]

    return [cli_env.python, "-m", "pip", "install", BROWSER_EXTRA_SPEC]


def _chromium_install_cmd(cli_env: CliEnv) -> list[str]:
    return [cli_env.python, "-m", "patchright", "install", "chromium"]


def stealth_status() -> tuple[bool, str]:
    """Read-only stealth probe used after install (and printable without doctor).

    Returns (ready, message). Does not download or install anything.
    """
    try:
        import patchright  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, f"stealth missing: patchright not importable ({type(exc).__name__})"
    return True, "stealth ready: patchright importable (Chromium install attempted)"


def install_browser(
    *,
    dry_run: bool = False,
    runner: Optional[Runner] = None,
    cli_env: Optional[CliEnv] = None,
) -> int:
    """Install ``[browser]`` + Chromium into the CLI env. Returns process exit code."""
    run = runner or _default_runner
    env = cli_env or detect_cli_env()

    _tick(f"mutating: {env.label}")

    if env.kind == "ephemeral_uvx":
        print(EPHEMERAL_UVX_HINT, file=sys.stderr)
        return 2

    extra_cmd = _extra_install_cmd(env)
    chromium_cmd = _chromium_install_cmd(env)

    if dry_run:
        _tick(f"[dry-run] would run: {' '.join(extra_cmd)}")
        _tick(f"[dry-run] would run: {' '.join(chromium_cmd)}")
        _tick("[dry-run] would check stealth status")
        print("Dry run complete. No changes were made.")
        return 0

    _tick("installing [browser] extra…")
    extra = run(extra_cmd)
    if extra.returncode != 0:
        err = (extra.stderr or extra.stdout or "").strip()
        print(
            f"[X] failed to install {BROWSER_EXTRA_SPEC} into {env.kind} env.\n"
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

    _tick("downloading Chromium…")
    chromium = run(chromium_cmd)
    if chromium.returncode != 0:
        err = (chromium.stderr or chromium.stdout or "").strip()
        print(
            f"[X] patchright install chromium failed.\n"
            f"  command: {' '.join(chromium_cmd)}\n"
            f"  {err or f'exit {chromium.returncode}'}",
            file=sys.stderr,
        )
        return 1

    _tick("checking doctor…")
    ready, message = stealth_status()
    marker = "[ok]" if ready else "[!]"
    print(f"{marker} {message}")
    if ready:
        print("Run searchts doctor for the full probe report (doctor stays read-only).")
        return 0
    print(
        "Stealth still missing after install. "
        "Try: python -m patchright install chromium",
        file=sys.stderr,
    )
    return 1
