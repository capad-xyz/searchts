"""First-pass setup: one up-front list, one consent (#442).

Everything searchts needs to be good at reads is either a Python dependency
(patchright, browser-cookie3, mcp, ffmpeg via imageio-ffmpeg, deno via
yt-dlp[deno]) or an item on this list. The list is shown once, every item that
helps reads is checked by default, and the user (or an agent, through flags)
can uncheck any of them. Nothing on it is downloaded without approval: a
yes at the prompt, ``--yes``, or yolo mode.

Per-site logins are NOT part of this approval. They keep their own consent
flow (``login keep --yes``, ``login_signin``, ``--cookies-from-browser --yes``).

The same data backs ``searchts install --dry-run --json`` (schema
``searchts.setup.v1``), ``doctor`` and the channels' missing-tool messages.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Sequence

SCHEMA = "searchts.setup.v1"

#: The one command every missing-tool message points at.
SETUP_COMMAND = "searchts install"
APPROVE_COMMAND = "searchts install --yes"

_MB = 1_000_000


@dataclass(frozen=True)
class SetupItem:
    """One line of the up-front list."""

    id: str
    title: str
    what_it_unlocks: str
    size_bytes: int
    size_is_estimate: bool
    needs_login: bool
    needs_system_change: bool
    default_selected: bool
    #: "now" installs on approval; "first_use" is listed so nothing is hidden,
    #: and is asked for (with its size) the first time it is needed.
    when: str
    installed: Callable[[], bool]
    install: Optional[Callable[[], bool]] = None
    note: str = ""

    def as_dict(self, skip: Iterable[str] = ()) -> dict:
        skipped = self.id in set(skip)
        return {
            "id": self.id,
            "title": self.title,
            "what_it_unlocks": self.what_it_unlocks,
            "size_bytes": self.size_bytes,
            "size_is_estimate": self.size_is_estimate,
            "installed": bool(self.installed()),
            "needs_login": self.needs_login,
            "needs_system_change": self.needs_system_change,
            "default_selected": self.default_selected,
            "selected": self.default_selected and not skipped,
            "when": self.when,
            "approve_command": approve_command_for(self),
            "note": self.note,
        }


# ── installed probes (cheap: PATH and the browser cache, no subprocess) ──────


def _which(*names: str) -> bool:
    return any(shutil.which(n) for n in names)


def chromium_cache_dirs() -> List[str]:
    """Where patchright keeps its Chromium download, most specific first."""
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    out = [env] if env and env != "0" else []
    home = os.path.expanduser("~")
    system = platform.system().lower()
    if system == "darwin":
        out.append(os.path.join(home, "Library", "Caches", "ms-playwright"))
    elif system == "windows":
        local = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        out.append(os.path.join(local, "ms-playwright"))
    else:
        out.append(os.path.join(
            os.environ.get("XDG_CACHE_HOME") or os.path.join(home, ".cache"),
            "ms-playwright",
        ))
    return out


def chromium_installed() -> bool:
    for root in chromium_cache_dirs():
        try:
            if any(name.startswith("chromium") for name in os.listdir(root)):
                return True
        except OSError:
            continue
    return False


def _linkedin_installed() -> bool:
    return _which("linkedin-scraper-mcp", "linkedin-mcp-server")


# ── installers (each returns True when the tool is there afterwards) ─────────


def _run(cmd: Sequence[str], timeout: int = 300) -> bool:
    try:
        proc = subprocess.run(
            list(cmd), capture_output=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
    except Exception:  # noqa: BLE001 - reported by the caller's re-check
        return False
    return proc.returncode == 0


def _install_chromium() -> bool:
    from searchts.browser_install import install_browser

    return install_browser() == 0 and chromium_installed()


def _install_twitter() -> bool:
    from searchts.cli import _install_twitter_deps

    _install_twitter_deps()
    return _which("twitter")


def _install_reddit() -> bool:
    from searchts.cli import _install_rdt_cli

    _install_rdt_cli()
    return _which("rdt")


def _install_linkedin() -> bool:
    print("Setting up LinkedIn (linkedin-scraper-mcp)...")
    if _linkedin_installed():
        print("  ✓ linkedin-scraper-mcp already installed")
        return True
    for tool, cmd in (
        ("pipx", ["pipx", "install", "linkedin-scraper-mcp"]),
        ("uv", ["uv", "tool", "install", "linkedin-scraper-mcp"]),
    ):
        if shutil.which(tool) and _run(cmd) and _linkedin_installed():
            print("  ✓ linkedin-scraper-mcp installed")
            return True
    print("  !  linkedin-scraper-mcp install failed. Run: pipx install linkedin-scraper-mcp")
    return False


def _install_mcporter() -> bool:
    from searchts.cli import _install_mcporter as _cli_install_mcporter

    _cli_install_mcporter()
    return _which("mcporter")


def _install_gh() -> bool:
    print("Setting up GitHub (gh)...")
    if _which("gh"):
        print("  ✓ gh already installed")
        return True
    system = platform.system().lower()
    if system == "darwin" and shutil.which("brew"):
        _run(["brew", "install", "gh"], timeout=600)
    elif system == "windows" and shutil.which("winget"):
        _run(["winget", "install", "--id", "GitHub.cli", "-e", "--silent"], timeout=600)
    if _which("gh"):
        print("  ✓ gh installed")
        return True
    print(
        "  !  gh is a system package here. Run `searchts install --system-deps` "
        "or see https://cli.github.com"
    )
    return False


# ── the list ─────────────────────────────────────────────────────────────────


def items() -> List[SetupItem]:
    """The up-front list, in the order it is shown."""
    return [
        SetupItem(
            id="chromium",
            title="Chromium for the stealth browser (patchright)",
            what_it_unlocks="JavaScript-heavy pages, login walls and pages that block plain HTTP",
            size_bytes=170 * _MB, size_is_estimate=True,
            needs_login=False, needs_system_change=False, default_selected=True,
            when="now", installed=chromium_installed, install=_install_chromium,
        ),
        SetupItem(
            id="twitter",
            title="twitter-cli (X)",
            what_it_unlocks="X/Twitter posts, threads, search and timelines",
            size_bytes=39 * _MB, size_is_estimate=True,
            needs_login=True, needs_system_change=False, default_selected=True,
            when="now", installed=lambda: _which("twitter"), install=_install_twitter,
        ),
        SetupItem(
            id="reddit",
            title="rdt-cli (Reddit)",
            what_it_unlocks="Reddit posts, comments and search",
            size_bytes=15 * _MB, size_is_estimate=True,
            needs_login=True, needs_system_change=False, default_selected=True,
            when="now", installed=lambda: _which("rdt"), install=_install_reddit,
        ),
        SetupItem(
            id="linkedin",
            title="linkedin-scraper-mcp (LinkedIn)",
            what_it_unlocks="LinkedIn profiles, posts and jobs (through mcporter)",
            size_bytes=214 * _MB, size_is_estimate=True,
            needs_login=True, needs_system_change=False, default_selected=True,
            when="now", installed=_linkedin_installed, install=_install_linkedin,
        ),
        SetupItem(
            id="mcporter",
            title="mcporter (MCP bridge for LinkedIn and Exa search)",
            what_it_unlocks="the LinkedIn tool and Exa as an extra search provider",
            size_bytes=77 * _MB, size_is_estimate=True,
            needs_login=False, needs_system_change=True, default_selected=True,
            when="now", installed=lambda: _which("mcporter"), install=_install_mcporter,
            note="an npm global package; it needs Node.js, about 100 MB more if missing",
        ),
        SetupItem(
            id="gh",
            title="GitHub CLI (gh)",
            what_it_unlocks="GitHub repos, issues, PRs and code search",
            size_bytes=13 * _MB, size_is_estimate=True,
            needs_login=True, needs_system_change=True, default_selected=True,
            when="now", installed=lambda: _which("gh"), install=_install_gh,
            note="a system package: brew, winget, or apt with --system-deps",
        ),
        SetupItem(
            id="whisper-model",
            title="Local Whisper model (small)",
            what_it_unlocks="keyless local transcription",
            size_bytes=466 * _MB, size_is_estimate=True,
            needs_login=False, needs_system_change=False, default_selected=False,
            when="first_use", installed=lambda: False,
            note="asked for, with its size, the first time you transcribe locally",
        ),
    ]


def ids() -> List[str]:
    return [i.id for i in items()]


def parse_skip(raw: str) -> List[str]:
    """``--skip twitter,linkedin`` -> known ids. Unknown ids raise ValueError."""
    wanted = [p.strip().lower() for p in (raw or "").split(",") if p.strip()]
    known = set(ids())
    unknown = [w for w in wanted if w not in known]
    if unknown:
        raise ValueError(
            f"unknown setup item(s): {', '.join(unknown)}; known: {', '.join(ids())}"
        )
    return wanted


def approve_command_for(item: SetupItem) -> str:
    if item.when == "first_use":
        return ""
    others = [i.id for i in items() if i.default_selected and i.id != item.id and i.when == "now"]
    return f"{APPROVE_COMMAND} --skip {','.join(others)}"


def selected(skip: Iterable[str] = ()) -> List[SetupItem]:
    """Items an approval installs now: default-selected, not skipped, missing."""
    skipped = set(skip)
    return [
        i for i in items()
        if i.when == "now" and i.default_selected and i.id not in skipped
        and not i.installed()
    ]


def plan(skip: Iterable[str] = ()) -> dict:
    """The ``searchts.setup.v1`` document."""
    skip = list(skip)
    rows = [i.as_dict(skip) for i in items()]
    pending = [r for r in rows if r["selected"] and not r["installed"] and r["when"] == "now"]
    approve = APPROVE_COMMAND + (f" --skip {','.join(skip)}" if skip else "")
    return {
        "schema": SCHEMA,
        "items": rows,
        "pending": [r["id"] for r in pending],
        "pending_size_bytes": sum(r["size_bytes"] for r in pending),
        "approve_command": approve if pending else "",
        "deselect": "--skip " + ",".join(ids()),
        "logins": "not part of this approval; each site asks when a read needs it",
    }


def human_size(n: int, estimate: bool = False) -> str:
    text = f"{n / _MB:,.0f} MB"
    return f"~{text}" if estimate else text


def render(skip: Iterable[str] = ()) -> List[str]:
    """The list as lines for a terminal.

    ``[x]`` installs on approval, ``[ ]`` is unchecked, ``[=]`` is already
    installed, and ``[-]`` is asked for the first time it is needed.
    """
    skipped = set(skip)
    out: List[str] = []
    for item in items():
        if item.installed():
            mark = "[=]"
        elif item.when == "first_use":
            mark = "[-]"
        elif item.default_selected and item.id not in skipped:
            mark = "[x]"
        else:
            mark = "[ ]"
        size = human_size(item.size_bytes, item.size_is_estimate)
        out.append(f"  {mark} {item.id:<14}{size:>9}  {item.title}: {item.what_it_unlocks}")
        if item.note:
            out.append(f"  {'':<4}{'':<14}{'':>9}  note: {item.note}")
    out.append("  [x] installs on approval  [ ] unchecked  [=] installed  [-] asked at first use")
    return out


def missing_tool_hint(item_id: str) -> str:
    """The lines channels print when their tool is missing: the one setup
    command first, and the agent form that installs only this item."""
    item = next((i for i in items() if i.id == item_id), None)
    if item is None:
        return f"  {SETUP_COMMAND}"
    return f"  {SETUP_COMMAND}\n  (agents: {approve_command_for(item)})"


def run_install(skip: Iterable[str] = (), out: Callable[[str], None] = print) -> Dict[str, bool]:
    """Install every selected, missing item. Returns ``{id: ok}``."""
    results: Dict[str, bool] = {}
    for item in selected(skip):
        if item.install is None:
            continue
        try:
            results[item.id] = bool(item.install())
        except Exception as e:  # noqa: BLE001 - one tool must not stop the rest
            out(f"  !  {item.id}: {type(e).__name__}: {e}")
            results[item.id] = False
    return results


def interactive_choice(
    skip: Sequence[str], ask: Callable[[str], str] = input,
) -> Optional[List[str]]:
    """Ask once. Returns the final skip list, or None when the user declined.

    Enter or "y" approves everything checked; "n" declines; a comma list of
    ids unchecks those and approves the rest.
    """
    try:
        raw = ask(
            "Install the checked items? [Y/n], or type ids to uncheck "
            "(e.g. linkedin,gh): "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None
    if raw in ("", "y", "yes"):
        return list(skip)
    if raw in ("n", "no"):
        return None
    try:
        return sorted(set(skip) | set(parse_skip(raw)))
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return None
