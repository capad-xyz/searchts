# -*- coding: utf-8 -*-
from pathlib import Path

import searchts

ROOT = Path(searchts.__file__).resolve().parent / "skill"
LIMIT = 1024


def _description(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.find("description:")
    end = text.find("\n---", start)
    block = text[start:end]
    lines = []
    for line in block.splitlines()[1:]:
        if line.startswith("metadata:") or line.startswith("triggers:"):
            break
        lines.append(line.strip())
    return " ".join(x for x in lines if x)


def test_skill_md_description_fits_agent_limit():
    desc = _description(ROOT / "SKILL.md")
    assert desc, "missing description"
    assert len(desc) <= LIMIT, f"SKILL.md description is {len(desc)} chars"


def test_skill_en_description_fits_agent_limit():
    desc = _description(ROOT / "SKILL_en.md")
    assert desc, "missing description"
    assert len(desc) <= LIMIT, f"SKILL_en.md description is {len(desc)} chars"
