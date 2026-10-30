# -*- coding: utf-8 -*-
"""TEMPORARY (#439): tell faster-whisper users it can go, and remove it on yes.

searchts installed faster-whisper (the ``local-transcribe`` extra) and its
Whisper models for local transcription. whisper.cpp replaces it. For 30 days
and at least 2 releases after the release that ships whisper.cpp (whichever is
later), people who still have faster-whisper get a notice, humans on stderr
and agents on the existing ``update_note`` channel in JSON and MCP results,
plus an opt-in
removal command. The follow-up issue deletes this module, the notice and the
command.

Nothing here removes anything without a yes: ``--yes`` (agents), a terminal
answer, or nothing at all.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

#: faster-whisper and the native chain it pulled in. A chain package is only
#: removed when nothing else installed here still requires it.
FW_PACKAGE = "faster-whisper"
FW_CHAIN = ("ctranslate2", "av", "onnxruntime")

REMOVE_COMMAND = "searchts transcribe --cleanup --yes"
DRY_RUN_COMMAND = "searchts transcribe --cleanup --dry-run"

# TODO(remove-after-window): set release_date to the actual first release date,
# then delete this constant, its gate and all marked call sites after the window.
MIGRATION_WINDOW: Dict[str, Any] = {
    "first_version": "0.24.0",
    "after_two_releases_version": "0.26.0",
    "release_date": "2026-10-30",
    "days": 30,
}

#: The notice repeats at most once a day.
NOTICE_TTL = 24 * 3600

_CACHE_NOTE = (
    "Hugging Face keeps one shared model cache. Other apps on this machine may "
    "use these folders and there is no record of which, so we cannot tell."
)


def _canon(name: str) -> str:
    return re.sub(r"[-_.]+", "-", (name or "").strip().lower())


def _version_tuple(value: str) -> tuple:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", value or "")
    return tuple(int(n) for n in match.groups()) if match else (0, 0, 0)


def migration_window_open(
    *, package_version: Optional[str] = None, now: Optional[float] = None
) -> bool:
    """TODO(remove-after-window): keep the notice until both limits pass."""
    if package_version is None:
        try:
            from importlib.metadata import version

            package_version = version("searchts")
        except Exception:  # noqa: BLE001
            return False
    current = _version_tuple(package_version)
    if current < _version_tuple(MIGRATION_WINDOW["first_version"]):
        return False
    released = datetime.fromisoformat(MIGRATION_WINDOW["release_date"]).replace(
        tzinfo=timezone.utc
    )
    stamp = time.time() if now is None else now
    thirty_days_passed = stamp >= (released + timedelta(days=MIGRATION_WINDOW["days"])).timestamp()
    two_releases_passed = current >= _version_tuple(
        MIGRATION_WINDOW["after_two_releases_version"]
    )
    return not (thirty_days_passed and two_releases_passed)


def _req_name(requirement: str) -> str:
    m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement or "")
    return _canon(m.group(1)) if m else ""


def _distributions() -> Dict[str, object]:
    from importlib.metadata import distributions

    out: Dict[str, object] = {}
    for dist in distributions():
        name = _canon(dist.metadata["Name"] or "" if dist.metadata else "")
        if name and name not in out:
            out[name] = dist
    return out


def installed_version(dists: Optional[Dict[str, object]] = None) -> Optional[str]:
    dists = _distributions() if dists is None else dists
    dist = dists.get(FW_PACKAGE)
    return getattr(dist, "version", None) if dist is not None else None


def _required_by(target: str, dists: Dict[str, object], ignore: set) -> List[str]:
    """Installed packages (other than ``ignore``) that declare ``target``.

    A requirement behind an extra (``; extra == ...``) is listed as optional:
    it matters only if that package was installed with the extra.
    """
    users = []
    for name, dist in dists.items():
        if name in ignore:
            continue
        for req in getattr(dist, "requires", None) or []:
            if _req_name(req) == target:
                users.append(f"{name} (optional)" if "extra ==" in req else name)
                break
    return sorted(set(users))


def _clearance_note() -> str:
    return (
        "searchts has its own environment here, so nothing else imports "
        "faster-whisper from it; removing it is safe."
    )


def _shared_note() -> str:
    return (
        "This is a shared Python environment: other programs in it may "
        "import faster-whisper. The packages that declare it are listed."
    )


def _unclear_note() -> str:
    return (
        "searchts cannot tell which other programs use this Python "
        "environment, so it does not call it shared: the packages that "
        "declare it are listed."
    )


def _searchts_tree(dists: Dict[str, object]) -> Optional[set]:
    """The canonical names searchts's own dependency tree covers.

    From searchts's declared requirements (its extras included, since this
    machine installed them the same way) closed over the installed dists.
    Used to tell a venv created for searchts apart from one another programs
    also live in: every installed package inside the tree, and nothing else.

    None when searchts's own metadata is missing or broken: only then is the
    caller allowed to say it cannot tell.
    """
    source = dists.get("searchts")
    if source is not None:
        try:
            roots = getattr(source, "requires") or []
        except AttributeError:
            # A distribution object without requirements metadata cannot tell
            # us what searchts brought in.
            return None
    else:
        try:
            from importlib.metadata import requires

            roots = requires("searchts") or []
        except Exception:  # noqa: BLE001 - no metadata, no claim
            return None
    try:
        tree = {"searchts"}
        pending = [_req_name(str(req)) for req in roots]
        seen: set = set()
        while pending:
            name = pending.pop()
            if not name or name in seen:
                continue
            seen.add(name)
            dist = dists.get(name)
            if dist is None:
                continue
            tree.add(name)
            pending.extend(
                _req_name(str(req)) for req in getattr(dist, "requires", None) or []
            )
        return tree
    except Exception:  # noqa: BLE001 - no metadata, no claim
        return None


#: Environment tooling that belongs to the venv itself, not another program's.
_ENV_TOOLING = {"pip", "setuptools", "wheel", "distribute"}


def _environment(dists: Optional[Dict[str, object]] = None) -> dict:
    dists = _distributions() if dists is None else dists
    try:
        from searchts.update_nudge import detect_install_kind

        kind = detect_install_kind()
    except Exception:  # noqa: BLE001
        kind = "pip"
    own = kind in ("uv_tool", "uvx", "pipx")
    note = _clearance_note()
    if not own:
        # Not an environment searchts owns by construction. The kind alone is
        # too conservative to shape the note (#488): a venv whose every
        # installed package is searchts and its tree was made for searchts.
        tree = _searchts_tree(dists)
        if tree is None:
            # No searchts metadata to walk: cannot tell, say so.
            return {
                "kind": kind,
                "python": sys.executable,
                "own_environment": False,
                "note": _unclear_note(),
            }
        if set(dists) - tree - _ENV_TOOLING:
            # A package outside searchts's tree is present, so this env is
            # shared with something else. That is a fact, not a guess.
            note = _shared_note()
        else:
            own = True
    return {
        "kind": kind,
        "python": sys.executable,
        "own_environment": own,
        "note": note,
    }


def _hf_cache_root() -> Path:
    hub = os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE")
    if hub:
        return Path(hub)
    home = os.environ.get("HF_HOME")
    if home:
        return Path(home) / "hub"
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "huggingface" / "hub"


def _folder_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += (Path(root) / f).lstat().st_size
            except OSError:
                pass
    return total


def model_caches(root: Optional[Path] = None) -> List[dict]:
    """faster-whisper model folders in the HF cache: path, size, last modified.

    Only folders whose repo name says faster-whisper (Systran/faster-whisper-*,
    and the community ct2 conversions it downloads) are listed; every other
    model in the cache is left alone.
    """
    from searchts.whispercpp import format_bytes

    root = _hf_cache_root() if root is None else root
    out: List[dict] = []
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return out
    for item in entries:
        name = item.name.lower()
        if not (item.is_dir() and name.startswith("models--") and "faster-whisper" in name):
            continue
        size = _folder_size(item)
        try:
            mtime = item.stat().st_mtime
        except OSError:
            mtime = 0.0
        out.append({
            "path": str(item),
            "size_bytes": size,
            "size": format_bytes(size),
            "modified": datetime.fromtimestamp(mtime, timezone.utc).strftime("%Y-%m-%d"),
        })
    return out


def audio_cache_entry() -> dict:
    """The #452 kept-audio folder: path, size, and how long an entry lives."""
    from searchts import audio_cache

    return audio_cache.info()


def audio_cache_only_report(cache: Optional[dict] = None) -> dict:
    """The cleanup report when faster-whisper is gone but kept audio remains.

    Without this, ``transcribe --cleanup`` said "nothing to remove" on a machine
    that never installed faster-whisper and still held cached audio (#452).
    """
    return {
        "schema": "searchts.fw_migration.v1",
        "temporary": True,
        "installed": False,
        "message": (
            "faster-whisper is not installed here. The only thing this cleanup "
            "can remove is the audio kept for transcription re-runs."
        ),
        "environment": _environment(),
        "packages": [],
        "model_caches": [],
        "model_cache_note": _CACHE_NOTE,
        "audio_cache": cache if cache is not None else audio_cache_entry(),
        "remove_command": REMOVE_COMMAND,
        "dry_run_command": DRY_RUN_COMMAND,
    }


def report(*, dists: Optional[Dict[str, object]] = None, cache_root: Optional[Path] = None) -> Optional[dict]:
    """What a removal would touch and what else uses it, or None without faster-whisper."""
    dists = _distributions() if dists is None else dists
    version = installed_version(dists)
    if not version:
        return None
    env = _environment(dists)
    retiring = {FW_PACKAGE, *FW_CHAIN}
    packages = []
    for name in (FW_PACKAGE, *FW_CHAIN):
        dist = dists.get(name)
        if dist is None:
            continue
        users = _required_by(name, dists, ignore=retiring | {"searchts"})
        packages.append({
            "name": name,
            "version": getattr(dist, "version", ""),
            "required_by": users,
            "remove": not users,
        })
    caches = model_caches(cache_root)
    return {
        "schema": "searchts.fw_migration.v1",
        "temporary": True,
        "message": (
            "searchts installed faster-whisper (and its Whisper models) for local "
            "transcription and no longer uses them: whisper.cpp is the local "
            "engine now. faster-whisper is only a fallback until it is removed."
        ),
        "environment": env,
        "packages": packages,
        "model_caches": caches,
        "audio_cache": audio_cache_entry(),
        "model_cache_note": _CACHE_NOTE,
        "remove_command": REMOVE_COMMAND,
        "dry_run_command": DRY_RUN_COMMAND,
    }


# ── the notice ─────────────────────────────────────────────────────────────


def _stamp_path() -> Path:
    override = os.environ.get("SEARCHTS_CACHE_DIR")
    if override:
        return Path(override) / "fw-migration-notice.json"
    from searchts.config import Config

    return Path(Config.CONFIG_DIR) / "fw-migration-notice.json"


def _due(channel: str, now: float, path: Optional[Path] = None) -> bool:
    """True at most once per NOTICE_TTL per channel (human, agent); records it."""
    if os.environ.get("SEARCHTS_NO_MIGRATION_NOTICE"):
        return False
    path = _stamp_path() if path is None else path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    last = data.get(channel)
    if last is not None and now - float(last) < NOTICE_TTL:
        return False
    data[channel] = now
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        return False
    return True


def human_notice(rep: dict) -> str:
    lines = ["searchts: " + rep["message"]]
    for pkg in rep["packages"]:
        users = ", ".join(pkg["required_by"]) or "nothing else here"
        lines.append(f"  {pkg['name']} {pkg['version']}: used by {users}")
    lines.append("  " + rep["environment"]["note"])
    for cache in rep["model_caches"]:
        lines.append(f"  model cache {cache['path']} ({cache['size']}, last modified {cache['modified']})")
    if rep["model_caches"]:
        lines.append("  " + rep["model_cache_note"])
    audio = rep.get("audio_cache") or {}
    if audio.get("files"):
        lines.append(
            f"  audio cache {audio['path']} ({audio['size']}, kept "
            f"{audio['ttl_hours']:g}h after a transcription)"
        )
    lines.append(f"  See what would go: {rep['dry_run_command']}")
    lines.append(f"  Remove it: {rep['remove_command']}  (nothing is removed without your yes)")
    lines.append("  This notice is temporary.")
    return "\n".join(lines)


def agent_note(rep: dict) -> dict:
    """The temporary agent message and its detailed removal report."""
    return {
        "note": (
            "Note for the agent: " + rep["message"] + " Tell the user. Removal "
            f"is opt-in: run `{rep['remove_command']}` only after the user says "
            "yes. Nothing was removed."
        ),
        "report": rep,
    }


def maybe_print_notice(*, now: Optional[float] = None, stream=None) -> bool:
    """Print the human notice to stderr, at most once a day. True when printed."""
    stamp = time.time() if now is None else now
    try:
        rep = report()
    except Exception:  # noqa: BLE001 - a notice must never break a command
        return False
    # TODO(remove-after-window): retire this human notice with the migration module.
    if not rep or not migration_window_open(now=stamp) or not _due("human", stamp):
        return False
    print(human_notice(rep), file=stream or sys.stderr, flush=True)
    return True


def maybe_agent_note(*, now: Optional[float] = None) -> Optional[dict]:
    """The agent entry, at most once a day, or None."""
    stamp = time.time() if now is None else now
    try:
        rep = report()
    except Exception:  # noqa: BLE001
        return None
    # TODO(remove-after-window): retire this agent note with the migration module.
    if not rep or not migration_window_open(now=stamp) or not _due("agent", stamp):
        return None
    return agent_note(rep)


# ── removal ────────────────────────────────────────────────────────────────


def _uninstall_argv(names: List[str]) -> Optional[List[str]]:
    import importlib.util

    if importlib.util.find_spec("pip") is not None:
        return [sys.executable, "-m", "pip", "uninstall", "-y", *names]
    uv = shutil.which("uv")
    if uv:
        return [uv, "pip", "uninstall", "--python", sys.executable, *names]
    return None


Runner = Callable[[List[str]], "subprocess.CompletedProcess[str]"]


def _run(argv: List[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(argv, capture_output=True, text=True, timeout=300)


def cleanup(rep: dict, *, run: Runner = _run) -> dict:
    """Remove what ``rep`` marks for removal. Call only after a yes."""
    names = [p["name"] for p in rep["packages"] if p["remove"]]
    result: dict = {
        "schema": "searchts.fw_migration.cleanup.v1",
        "removed_packages": [],
        "kept_packages": [
            {"name": p["name"], "reason": "required by " + ", ".join(p["required_by"])}
            for p in rep["packages"] if not p["remove"]
        ],
        "removed_caches": [],
        "kept_caches": [],
    }
    if names:
        argv = _uninstall_argv(names)
        if argv is None:
            result["kept_packages"] += [
                {"name": n, "reason": "no pip or uv to uninstall with"} for n in names
            ]
        else:
            proc = run(argv)
            if proc.returncode == 0:
                result["removed_packages"] = names
            else:
                detail = (proc.stderr or proc.stdout or "").strip()[:300]
                result["kept_packages"] += [
                    {"name": n, "reason": f"uninstall failed: {detail}"} for n in names
                ]
    for cache in rep["model_caches"]:
        try:
            shutil.rmtree(cache["path"])
            result["removed_caches"].append(cache["path"])
        except OSError as e:
            result["kept_caches"].append({"path": cache["path"], "reason": str(e)})
    audio = rep.get("audio_cache") or {}
    if audio.get("exists"):
        from searchts import audio_cache

        try:
            audio_cache.clear()
            result["removed_caches"].append(audio["path"])
        except OSError as e:
            result["kept_caches"].append({"path": audio["path"], "reason": str(e)})
    return result


def add_agent_note(payload: dict) -> dict:
    """Add the temporary migration message on the existing update_note channel."""
    note = maybe_agent_note()
    if note:
        current = payload.get("update_note")
        message = note["note"]
        payload = {
            **payload,
            "update_note": "\n\n".join(value for value in (current, message) if value),
            "fw_migration_report": note["report"],
        }
    return payload
