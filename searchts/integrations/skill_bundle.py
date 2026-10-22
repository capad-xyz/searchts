# -*- coding: utf-8 -*-
"""Copy the Agent Skills bundle (SKILL.md + references/) into shared homes.

Claude Code loads ``~/.claude/skills/<name>/SKILL.md``. OpenCode also loads
``~/.agents/skills/<name>/SKILL.md`` and the Claude path. The slash command
written by ``skill install`` is a separate, older file and stays where it is.
"""

from __future__ import annotations

import importlib.resources
import os
import shutil
from pathlib import Path
from typing import Optional


def _is_english_locale(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized.startswith("en") or normalized.startswith("english")


def _skill_resource_name() -> str:
    locale_candidates = (
        os.environ.get("SEARCHTS_LANG", ""),
        os.environ.get("LC_ALL", ""),
        os.environ.get("LC_MESSAGES", ""),
        os.environ.get("LANG", ""),
    )
    if any(_is_english_locale(candidate) for candidate in locale_candidates):
        return "SKILL_en.md"
    return "SKILL.md"


def write_skill_bundle(target: Path) -> bool:
    """Replace ``target`` with the packaged skill. A symlink is unlinked, not followed."""
    target = Path(target)
    try:
        if target.is_symlink():
            target.unlink()
        elif target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
        skill_pkg = importlib.resources.files("searchts").joinpath("skill")
        try:
            body = skill_pkg.joinpath(_skill_resource_name()).read_text(encoding="utf-8")
        except FileNotFoundError:
            body = skill_pkg.joinpath("SKILL.md").read_text(encoding="utf-8")
        (target / "SKILL.md").write_text(body, encoding="utf-8")
        refs = skill_pkg.joinpath("references")
        refs_target = target / "references"
        refs_target.mkdir(parents=True, exist_ok=True)
        for ref_file in refs.iterdir():
            name = ref_file.name
            if name.endswith(".md"):
                body = ref_file.read_text(encoding="utf-8")
                (refs_target / name).write_text(body, encoding="utf-8")
        return True
    except OSError:
        return False


def bundle_dirs(home: Path, environ: Optional[dict] = None) -> list:
    """Homes ``skill install`` always fills, plus OpenClaw when that tree exists."""
    env = os.environ if environ is None else environ
    dirs = [
        home / ".agents" / "skills" / "searchts",
        home / ".claude" / "skills" / "searchts",
    ]
    openclaw = home / ".openclaw" / "skills"
    if openclaw.is_dir():
        dirs.append(openclaw / "searchts")
    openclaw_home = env.get("OPENCLAW_HOME")
    if openclaw_home:
        candidate = Path(openclaw_home) / ".openclaw" / "skills"
        if candidate.is_dir():
            dirs.insert(0, candidate / "searchts")
    unique = []
    for path in dirs:
        if path not in unique:
            unique.append(path)
    return unique


def install_shared_skills(home: Path, environ: Optional[dict] = None) -> list:
    """Write the bundle. Returns ``{path, ok}`` rows."""
    rows = []
    for path in bundle_dirs(home, environ):
        rows.append({"path": path, "ok": write_skill_bundle(path)})
    return rows


def bundle_wired(home: Path) -> Optional[bool]:
    """None when no skill home exists. True when either SKILL.md is present."""
    claude = home / ".claude"
    agents = home / ".agents"
    paths = [
        claude / "skills" / "searchts" / "SKILL.md",
        agents / "skills" / "searchts" / "SKILL.md",
    ]
    if not claude.is_dir() and not agents.is_dir() and not any(p.exists() for p in paths):
        return None
    return any(p.is_file() for p in paths)
