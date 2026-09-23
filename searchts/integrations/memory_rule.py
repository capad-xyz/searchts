# -*- coding: utf-8 -*-
"""User-scope memory rule: on a wall, call searchts — do not satisfice.

Written by `searchts install` / `searchts skill` when Claude Code or Cursor
is detected on the machine. Never project-scope (those files get committed).

A later `searchts` command replaces a block only when it is an older
official copy. An edited block is left alone. A missing block is not created
here. There is no Grok rules file to write.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Optional

BEGIN = "<!-- searchts:reach -->"
END = "<!-- /searchts:reach -->"

RULE = """<!-- searchts:reach -->
When the user asks what a URL says, call the searchts MCP tool `read_url`
(or run `searchts read <url>`) first. Do not start with a plain fetch.
A 200 that is a sign-in form, a join page, or a bot check is not the page.
A 403, 429, challenge, or thin/empty body is not the page either.
Do not answer from the login chrome or from a snippet. Do not skip the URL.
<!-- /searchts:reach -->
"""

# Official text this file used to write. A byte match (newlines normalized)
# may be replaced without asking. Anything else is the user's edit.
OLD_RULES = (
    """<!-- searchts:reach -->
When a page fetch returns 403, 429, a bot-challenge, or thin/empty content:
use the searchts MCP tool `read_url`, or run `searchts read <url>`.
Do not answer from the blocked snippet. Do not skip the URL.
<!-- /searchts:reach -->
""",
)


def claude_detected(home: Path) -> bool:
    return (home / ".claude.json").exists() or (home / ".claude").is_dir()


def cursor_detected(home: Path) -> bool:
    return (home / ".cursor").is_dir()


def _block_present(text: str) -> bool:
    return BEGIN in text and END in text


def _same_block(text: str) -> bool:
    return RULE.strip() in text.replace("\r\n", "\n")


def _block_text(text: str) -> Optional[str]:
    start = text.find(BEGIN)
    stop = text.find(END)
    if start == -1 or stop < start:
        return None
    return text[start : stop + len(END)].replace("\r\n", "\n").strip()


def _is_known_old(text: str) -> bool:
    body = _block_text(text)
    if body is None:
        return False
    old = {rule.replace("\r\n", "\n").strip() for rule in OLD_RULES}
    return body in old


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
        if _block_present(current) and not _is_known_old(current):
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

    Non-interactive: write if our block is missing, and replace a known
    older official block. Never overwrite an edit.
    Interactive: ask before replacing a block that is not a known older copy.
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


def refresh_known_rules(
    home: Optional[Path] = None,
    *,
    log: Callable[[str], None] = lambda message: print(message, file=sys.stderr),
) -> list[str]:
    """Replace an older official block. Do not create, append, or touch an edit."""
    home = Path(home) if home else Path.home()
    targets: list[Path] = []
    if claude_detected(home):
        targets.append(home / ".claude" / "CLAUDE.md")
    if cursor_detected(home):
        targets.append(home / ".cursor" / "rules" / "searchts.mdc")
    actions: list[str] = []
    for path in targets:
        if not path.is_file():
            continue
        current = path.read_text(encoding="utf-8")
        if not _is_known_old(current):
            continue
        new = _replace_or_append(current)
        if new == current:
            continue
        _write_file(path, new)
        log(f"searchts: updated reach rule in {path}")
        actions.append(str(path))
    return actions
