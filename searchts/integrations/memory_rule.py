# -*- coding: utf-8 -*-
"""User-scope memory rule: on a wall, call searchts — do not satisfice.

Written by `searchts install` / `searchts skill` when Claude Code or Cursor
is detected on the machine. Never project-scope (those files get committed).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Optional

BEGIN = "<!-- searchts:reach -->"
END = "<!-- /searchts:reach -->"

RULE = """<!-- searchts:reach -->
When a page fetch returns 403, 429, a bot-challenge, or thin/empty content:
use the searchts MCP tool `read_url`, or run `searchts read <url>`.
Do not answer from the blocked snippet. Do not skip the URL.
<!-- /searchts:reach -->
"""


def claude_detected(home: Path) -> bool:
    return (home / ".claude.json").exists() or (home / ".claude").is_dir()


def cursor_detected(home: Path) -> bool:
    return (home / ".cursor").is_dir()


def _block_present(text: str) -> bool:
    return BEGIN in text and END in text


def _same_block(text: str) -> bool:
    return RULE.strip() in text.replace("\r\n", "\n")


def _replace_or_append(existing: str) -> str:
    if _block_present(existing):
        start = existing.find(BEGIN)
        stop = existing.find(END)
        if stop == -1:
            return existing.rstrip() + "\n\n" + RULE
        stop += len(END)
        return existing[:start] + RULE.strip() + existing[stop:]
    if not existing.strip():
        return RULE
    return existing.rstrip() + "\n\n" + RULE


def _write_file(path: Path, new_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_text, encoding="utf-8")


def apply_one(
    path: Path,
    *,
    interactive: bool,
    prompt: Callable[[str], str],
    log: Callable[[str], None],
) -> str:
    """Write or skip one user-scope file. Returns action: wrote|skipped|kept."""
    if path.exists():
        current = path.read_text(encoding="utf-8")
        if _same_block(current):
            log(f"  -- memory rule already present: {path}")
            return "kept"
        if _block_present(current):
            if not interactive:
                log(f"  -- memory rule exists; not overwriting (non-interactive): {path}")
                return "skipped"
            answer = prompt(f"  Overwrite searchts reach rule in {path}? [y/N]: ")
            if answer.strip().lower() not in ("y", "yes"):
                log("  -- left existing rule")
                return "skipped"
        elif not interactive and current.strip():
            # File exists without our block: append is not overwrite. Allowed.
            pass
        new = _replace_or_append(current)
    else:
        new = RULE
    _write_file(path, new)
    log(f"  [ok] wrote reach rule: {path}")
    return "wrote"


def install_memory_rules(
    home: Optional[Path] = None,
    *,
    interactive: Optional[bool] = None,
    prompt: Callable[[str], str] = input,
    log: Callable[[str], None] = print,
) -> list[str]:
    """Detect Claude Code / Cursor and write user-scope rules.

    Non-interactive: write only if our block is missing; never overwrite.
    Interactive: ask before replacing an existing searchts block.
    Writes even if MCP is not wired.
    """
    home = Path(home) if home else Path.home()
    if interactive is None:
        interactive = bool(sys.stdin.isatty() and sys.stdout.isatty())

    actions: list[str] = []
    targets: list[Path] = []
    if claude_detected(home):
        targets.append(home / ".claude" / "CLAUDE.md")
    if cursor_detected(home):
        targets.append(home / ".cursor" / "rules" / "searchts.mdc")
    if not targets:
        log("  -- no Claude Code or Cursor user dir; skipped memory rule")
        return actions
    for path in targets:
        actions.append(apply_one(path, interactive=interactive, prompt=prompt, log=log))
    return actions
