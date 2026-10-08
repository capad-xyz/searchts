"""Hare's view past the diff (PLAN, the codebase graph, v1).

A diff shows what changed, not what the change touches. Most of what Hare has
missed sat in a file the diff never showed: a doc that still said the old rule
(#269), a workflow setting the new code collided with (#282). This module
reads the names a diff changes (functions, classes, constants, the function
named in each hunk header) and the files it changes, finds where those are
used in files the diff did not touch, and ranks the uses: code first, then
workflows and config, then docs.

It reads the trusted base checkout the Action already has, as text. Nothing
in it is run, and the PR's own code is never checked out for this. It is built
from the commit being reviewed on every run, so it is never stale.

A match is by name only, so every use is a possible use. Each model hop gets
the ranked list filled to its own budget (budget_for), never sized to one
model's limits.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

# Bounds (HARE.md: anything of unknown size has a bound).
MAX_FILES = 5_000
MAX_WALK = 50_000
MAX_FILE_BYTES = 1_000_000
MAX_USES = 240
MAX_LINES_PER_FILE = 12
MAX_LINE = 200
MAX_NAMES = 40
MAX_WHOLE = 12_000

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "dist", "build", "__pycache__", ".mypy_cache",
    ".ruff_cache", ".pytest_cache", ".tox", "site-packages", ".next", "target", "vendor", ".idea", ".vscode",
}
CODE = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".rb", ".php",
    ".cs", ".c", ".h", ".cc", ".cpp", ".hpp", ".swift", ".scala", ".sh", ".bash",
}
CONFIG = {".yml", ".yaml", ".toml", ".json", ".cfg", ".ini"}
CONFIG_NAMES = {"Dockerfile", "Makefile", "Procfile", ".pre-commit-config.yaml"}
DOCS = {".md", ".rst", ".txt", ".adoc"}

# Names too common to mean anything when matched as text.
STOP = {
    "main", "init", "self", "this", "that", "with", "from", "none", "true", "false", "args", "kwargs",
    "data", "value", "result", "print", "return", "index", "items", "update", "close", "open", "read",
    "write", "name", "path", "type", "list", "dict", "test", "setup", "config", "utils", "helper",
    "default", "object", "string", "error", "event", "token", "body", "text", "line", "lines",
}
GENERIC_STEMS = {"index", "utils", "main", "init", "__init__", "config", "setup", "conftest", "helpers", "common", "readme"}

MODS = r"(?:(?:export|default|public|private|protected|internal|static|final|abstract|sealed|open|override|virtual|async|synchronized|readonly|pub(?:\([^)]*\))?)\s+)*"
DEF = re.compile(
    rf"^\s*{MODS}(?:def|class|function|func|fun|fn|interface|struct|enum|trait|record|protocol)\s+(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]{{3,}})"
)
# A method with a return type: at least one modifier, so a plain call never matches.
METHOD = re.compile(
    r"^\s*(?:(?:public|private|protected|internal|static|final|abstract|synchronized|override|virtual|async)\s+)+"
    r"[\w<>\[\],.?]+\s+([A-Za-z_][A-Za-z0-9_]{3,})\s*\("
)
CALLISH = re.compile(r"([A-Za-z_][A-Za-z0-9_]{3,})\s*\(")
JS_FN = re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]{3,})\s*=\s*(?:async\s*)?(?:\(|function\b|[A-Za-z_$][\w$]*\s*=>)")
# A module constant: SCREAMING_CASE, with an optional leading underscore. The
# underscore matters more than it looks. Without it, `[A-Z]` fails at position
# 0 and every *private* module constant is invisible to the whole graph:
# _MIN_CHARS, _EXTRACT_MIN_RECALL, _AUTH_DENSITY_PER_100, _REFUSAL_REPEAT_LIMIT.
# On #338 a diff whose only new name was `_REFUSAL_REPEAT_LIMIT = 2` yielded
# zero names from the parser, so the graph had nothing to search for and
# returned a file list about paths instead. Measured over six real merges, one
# of them returned no names at all for exactly this reason.
CONST = re.compile(r"^\s*(?:export\s+)?(?:const\s+|let\s+|var\s+)?(_?[A-Z][A-Z0-9_]{2,})\s*(?::[^=]*)?=(?!=)")
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@ ?(.*)$")
FILE = re.compile(r"^diff --git a/(\S+) b/(\S+)")


def tier_of(path: str) -> int:
    """1 code, 2 workflows and config, 3 docs, 0 not read."""
    p = Path(path)
    if p.suffix in CODE:
        return 1
    if path.startswith("docs/") and p.suffix == ".json":
        return 3  # records (ledgers, logs, answer keys), not settings
    if p.suffix in CONFIG or p.name in CONFIG_NAMES or path.startswith(".github/"):
        return 2
    if p.suffix in DOCS:
        return 3
    return 0


def _keep(name: str) -> bool:
    """Only names distinctive enough to match as text: an underscore, an inner
    capital, all caps, or 8+ letters. A plain word like `link` matched every
    file on #282's replay and pushed the real uses out of the budget."""
    if name.lower() in STOP or name.lower().startswith(("test", "_test")):
        return False
    return "_" in name.strip("_") or bool(re.search(r"[a-z][A-Z]", name)) or (name.isupper() and len(name) >= 4) or len(name) >= 8


def changed(diff: str) -> tuple[list[str], list[str], dict[str, list[tuple[int, int]]]]:
    """(names, paths, base line ranges each hunk replaced) from a unified diff."""
    names: dict[str, None] = {}
    paths: dict[str, None] = {}
    ranges: dict[str, list[tuple[int, int]]] = {}
    current = ""
    for line in diff.splitlines():
        m = FILE.match(line)
        if m:
            current = m.group(2)
            paths[current] = None
            continue
        h = HUNK.match(line)
        if h:
            start, count = int(h.group(1)), int(h.group(2) or "1")
            ranges.setdefault(current, []).append((start, start + max(count, 1)))
            head = h.group(3) or ""
            got = DEF.match(head) or METHOD.match(head)
            name = got.group(1) if got else ((CALLISH.findall(head) or [""])[-1])
            if name and _keep(name):
                names[name] = None
            continue
        if line[:1] in "+-" and not line.startswith(("+++", "---")):
            body = line[1:]
            for rx in (DEF, METHOD, JS_FN, CONST):
                m2 = rx.match(body)
                if m2 and _keep(m2.group(1)):
                    names[m2.group(1)] = None
    return list(names)[:MAX_NAMES], list(paths), ranges


def _terms(names: list[str], paths: list[str]) -> tuple[re.Pattern[str] | None, re.Pattern[str] | None]:
    """(names, places). Names are matched everywhere. Places, a changed code
    file's path and distinctive module name, are matched only in workflows,
    config and docs: in code they mostly hit its own imports (#282's replay)."""
    by_name = re.compile("|".join(rf"\b{re.escape(n)}\b" for n in names)) if names else None
    parts: list[str] = []
    for p in paths:
        if tier_of(p) != 1:
            continue  # a changed doc's or config's path is named everywhere and says little
        parts.append(re.escape(p))
        stem = Path(p).stem
        if len(stem) >= 5 and stem.lower() not in GENERIC_STEMS:
            parts.append(rf"\b{re.escape(stem)}\b")
    by_place = re.compile("|".join(parts)) if parts else None
    return by_name, by_place


def _files(root: Path) -> list[str]:
    """Readable files in rank order (code, tests, config with .github first,
    docs), so the caps below drop the lowest-ranked files first, never a code
    caller that sorts late in the alphabet. The walk itself is bounded too."""
    seen: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".") or d == ".github")
        for f in sorted(filenames):
            rel = os.path.relpath(os.path.join(dirpath, f), root).replace(os.sep, "/")
            if tier_of(rel):
                seen.append(rel)
        if len(seen) >= MAX_WALK:
            break
    seen.sort(key=lambda r: (tier_of(r), "test" in r.lower(), not r.startswith(".github/"), r))
    return seen[:MAX_FILES]


def _defines(text: str, names: list[str]) -> bool:
    for rx in (DEF, METHOD, JS_FN, CONST):
        m = rx.match(text)
        if m and m.group(1) in names:
            return True
    return False


def uses(root: str | Path, diff: str, visible: str | None = None) -> list[dict[str, Any]]:
    """Every file outside the diff's own lines that names what the diff changes,
    ranked: code, then workflows and config, then docs; tests after other code;
    more distinct names matched first."""
    names, paths, ranges = changed(diff)
    if visible is not None and visible != diff:
        # Lines in a hunk (changed or context) are skipped because the model
        # sees them in the diff. When the prompt cuts the diff short, only the
        # hunks it kept are seen, so only those are skipped.
        ranges = changed(visible)[2]
    by_name, by_place = _terms(names, paths)
    if by_name is None and by_place is None:
        return []
    root = Path(root)
    found: list[dict[str, Any]] = []
    total = 0
    for rel in _files(root):
        full = root / rel
        try:
            if full.stat().st_size > MAX_FILE_BYTES:
                continue
            raw = full.read_bytes()
        except OSError:
            continue
        if b"\0" in raw[:4096]:
            continue
        skip = ranges.get(rel, [])
        tier = tier_of(rel)
        placed = False
        hits: list[tuple[int, str]] = []
        matched: dict[str, None] = {}
        for i, text in enumerate(raw.decode("utf-8", errors="replace").splitlines(), start=1):
            if any(a <= i < b for a, b in skip):
                continue  # this line is in the diff already
            if skip and _defines(text, names):
                continue  # the changed name's own definition, not a use of it
            got = [m.group(0) for m in by_name.finditer(text)] if by_name else []
            places = [m.group(0) for m in by_place.finditer(text)] if by_place and tier != 1 else []
            got += places
            placed = placed or bool(places)
            if got:
                hits.append((i, text.strip()[:MAX_LINE]))
                for g in got:
                    matched[g] = None
                if len(hits) >= MAX_LINES_PER_FILE:
                    break
        if hits:
            item: dict[str, Any] = {"file": rel, "tier": tier_of(rel), "test": "test" in rel.lower(), "names": list(matched), "lines": hits}
            # A workflow or config that names a changed file is read whole when
            # small: its triggers, concurrency and permissions sit on lines that
            # never mention the file (#282's miss was such a line).
            if tier == 2 and placed and len(raw) <= MAX_WHOLE:
                item["whole"] = raw.decode("utf-8", errors="replace")
            found.append(item)
            total += len(hits)
            if total >= MAX_USES:
                break
    found.sort(key=lambda u: (u["tier"], u["test"], not u["file"].startswith(".github/"), -len(u["names"]), u["file"]))
    return found


def budget_for(provider: str) -> int:
    """Characters of repo context each hop can take on top of the diff. Groq's
    free tier counts tokens per minute, so it gets little; Gemini takes the most."""
    return {"groq": 4_000, "gemini": 40_000}.get(provider, 20_000)


HEADER = (
    "## Elsewhere in the repo (not in this diff)\n"
    "Lines from files this diff did not change that use the names or files it changes: code first, then "
    "workflows and config, then docs. A match is by name only, so each is a possible use. Use them to judge "
    "whether the change breaks a caller, collides with a setting, or leaves a doc saying the old thing. "
    "Do not review these lines for their own sake.\n"
)


def section(found: list[dict[str, Any]], budget: int) -> str:
    """The ranked uses, as many whole files as fit in `budget` characters."""
    out = HEADER
    added = 0
    for u in found:
        lines = f"\n### {u['file']} (names: {', '.join(u['names'][:6])})\n```\n" + "\n".join(f"L{i}: {t}" for i, t in u["lines"]) + "\n```\n"
        block = lines
        if u.get("whole"):
            whole = f"\n### {u['file']} (whole file: it names a changed file)\n```\n{u['whole'].rstrip()}\n```\n"
            block = whole if len(out) + len(whole) <= budget else lines  # a small budget gets the lines
        if len(out) + len(block) > budget:
            continue  # a smaller file further down may still fit
        out += block
        added += 1
    return out if added else ""
