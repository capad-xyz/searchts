# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Optional

BROWSER_EXTRA_SPEC: str
EPHEMERAL_UVX_HINT: str
UV_TOOL_HINT: str

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]

@dataclass(frozen=True)
class CliEnv:
    kind: str
    label: str
    python: str

def detect_cli_env(
    *,
    environ: Mapping[str, str] | None = None,
    executable: Optional[str] = None,
    prefix: Optional[str] = None,
    editable: Optional[bool] = None,
) -> CliEnv: ...

def browser_extra_requirements() -> list[str]: ...

def stealth_status() -> tuple[bool, str]: ...

def install_browser(
    *,
    dry_run: bool = False,
    runner: Optional[Runner] = None,
    cli_env: Optional[CliEnv] = None,
) -> int: ...
