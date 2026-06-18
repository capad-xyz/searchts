# -*- coding: utf-8 -*-
"""Lightweight upstream command probing.

Distinguishes the three failure modes that look identical to shutil.which():
  - missing: command not on PATH
  - broken: command exists but cannot execute — most commonly a stale venv
    shebang after a system Python upgrade (pipx/uv tool installs break this
    way: which() finds the shim, but exec fails with FileNotFoundError
    pointing at the shim itself)
  - timeout/error: command runs but misbehaves

Channels use probe_command() inside check() so doctor reports real health,
not just file existence.
"""

import importlib.util
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional, Sequence

from searchts.utils.process import utf8_subprocess_env

#: Exit codes shells use for "found but not executable" / "not found".
_BROKEN_EXIT_CODES = (126, 127)


@dataclass
class ProbeResult:
    status: str  # "ok" | "missing" | "broken" | "timeout" | "error"
    output: str = ""
    hint: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def reinstall_hint(package: str) -> str:
    """Prescription for a broken (stale-venv) CLI install."""
    return (
        f"The command exists but cannot execute -- usually the venv interpreter went missing after a system Python upgrade. Reinstall to fix:\n"
        f"  uv tool install --force {package}\n"
        f"or: pipx reinstall {package}"
    )


def probe_command(
    cmd: str,
    args: Sequence[str] = ("--version",),
    timeout: int = 10,
    retries: int = 0,
    package: Optional[str] = None,
    module: Optional[str] = None,
) -> ProbeResult:
    """Actually execute `cmd *args` and classify the result.

    Intended for SIDE-EFFECT-FREE health probes only (version/status
    commands): retries re-run the command verbatim with no backoff, so a
    non-idempotent command would repeat its effect.

    package: pip/pipx package name used in the broken-install hint
             (defaults to cmd).
    module: when set, probe the tool as a Python module instead of a PATH
            binary. Presence is checked via importlib.util.find_spec(module)
            and the probe runs `[sys.executable, "-m", module, *args]`. This is
            how console-script tools that ship as Python dependencies (e.g.
            yt-dlp) are detected in a venv/pipx install, where the module is
            always importable even though the console script is not on PATH.
            If the module is importable, that is used; otherwise it falls back
            to a PATH binary named `cmd` if present, else reports "missing".
    """
    if module is not None:
        if importlib.util.find_spec(module) is not None:
            invocation = [sys.executable, "-m", module]
        elif shutil.which(cmd):
            invocation = [shutil.which(cmd)]
        else:
            return ProbeResult("missing")
    else:
        path = shutil.which(cmd)
        if not path:
            return ProbeResult("missing")
        invocation = [path]

    last: Optional[ProbeResult] = None
    for _ in range(retries + 1):
        last = _run_once(invocation, args, timeout, package or cmd)
        if last.ok:
            return last
        # missing/broken won't heal between retries — only transient
        # failures (timeout/error) are worth a second attempt
        if last.status in ("missing", "broken"):
            return last
    return last


def _run_once(
    invocation: Sequence[str], args: Sequence[str], timeout: int, package: str
) -> ProbeResult:
    try:
        r = subprocess.run(
            [*invocation, *args],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=utf8_subprocess_env(),
        )
    except FileNotFoundError:
        # which() found it but exec failed: the shebang interpreter is gone
        return ProbeResult("broken", hint=reinstall_hint(package))
    except OSError:
        return ProbeResult("broken", hint=reinstall_hint(package))
    except subprocess.TimeoutExpired:
        cmd_repr = " ".join(invocation)
        return ProbeResult("timeout", hint=f"`{cmd_repr}` response timed out (>{timeout}s)")

    if r.returncode in _BROKEN_EXIT_CODES:
        return ProbeResult("broken", hint=reinstall_hint(package))

    output = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        return ProbeResult("error", output=output.strip())
    return ProbeResult("ok", output=output.strip())
