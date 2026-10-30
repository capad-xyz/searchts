# -*- coding: utf-8 -*-
"""A short-lived cache for the compressed audio a transcription downloads (#452).

``searchts transcribe`` downloads a video's audio into a temporary work folder
and deletes it when the transcript is done. Re-running the same URL, with a
different model or hint, pays the whole download again. This module keeps the
one file that is small and reusable: the 16 kHz mono m4a ``ffmpeg`` makes
before any chunking. The original video is never kept.

Three rules, and they are the whole design:

1. **Short and bounded.** An entry lives 24 hours, and the folder is capped at
   256 MB with the oldest entries dropped first. The sweep runs at the start of
   every transcribe, so a cache nobody uses empties itself.

2. **Only what a re-run can reuse.** Entries are keyed by the normalized source
   (a YouTube video id, or the URL without the tracking parameters), so
   ``youtu.be/<id>``, a watch link with ``&t=40`` and a ``/shorts/`` link are
   one key. A local file was never downloaded, so it never enters the cache.

3. **Never a login.** Audio fetched with ``--cookies-from-browser`` is not
   stored and the cache is not read for it: a kept copy of members-only audio
   is exactly the kind of file the cookie rule exists to avoid.

``audio_cache: off`` (config) or ``SEARCHTS_AUDIO_CACHE=0`` turns the whole
thing off, and ``--fresh`` skips the read for one run. Both are visible to an
agent as ``audio_cache: off`` / ``miss`` in the transcribe receipt.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import urllib.parse
from pathlib import Path
from typing import List, Optional

#: A kept entry outlives the run that made it by a day, then it goes.
DEFAULT_TTL_SECONDS = 24 * 60 * 60

#: The whole folder: a few hundred MB, oldest first when it is over.
DEFAULT_MAX_BYTES = 256 * 1024 * 1024

#: ``<root>/audio/<slug>-<hash>.m4a``.
CACHE_SUBDIR = "cache"
CACHE_NAME = "audio"
SUFFIX = ".m4a"

#: Query parameters that name a campaign or a client, not a video. Two links to
#: the same video should share one key however they were copied.
_TRACKING_PARAMS = frozenset({
    "fbclid", "gclid", "igshid", "si", "feature", "pp", "ref_src",
    "mc_cid", "mc_eid", "_hsenc", "_hsmi", "_r", "_t",
    "is_from_webapp", "sender_device", "share_id", "web_id",
})

_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_PATH_KINDS = frozenset({"shorts", "embed", "live", "v"})
_UNSAFE_RE = re.compile(r"[^a-z0-9]+")


def cache_dir(root: Optional[Path] = None) -> Path:
    """Where kept audio lives (``SEARCHTS_AUDIO_CACHE_DIR`` overrides).

    ``SEARCHTS_CACHE_DIR`` is the existing cache override searchts already
    honours for its other cache files; the audio cache is a folder under it.
    """
    if root is not None:
        return Path(root)
    override = os.environ.get("SEARCHTS_AUDIO_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    shared = os.environ.get("SEARCHTS_CACHE_DIR")
    if shared:
        return Path(shared).expanduser() / CACHE_NAME
    from searchts.config import Config

    return Path(Config.CONFIG_DIR) / CACHE_SUBDIR / CACHE_NAME


def enabled(config: object = None) -> bool:
    """Whether caching is on: config ``audio_cache`` / ``SEARCHTS_AUDIO_CACHE``.

    On unless turned off, because the point of #452 is that a re-run should not
    pay for the download again.
    """
    raw: object = os.environ.get("SEARCHTS_AUDIO_CACHE")
    if raw is None:
        if config is not None:
            try:
                raw = config.get("audio_cache")  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - a broken config must not block transcribe
                raw = None
        else:
            from searchts.config import Config

            raw = Config().get("audio_cache")
    if raw is None:
        return True
    return str(raw).strip().lower() not in ("", "0", "off", "false", "no", "never")


def _tracking(name: str) -> bool:
    key = name.lower()
    return key in _TRACKING_PARAMS or key.startswith("utm_")


def _youtube_id(host: str, parts: urllib.parse.SplitResult) -> str:
    """The 11-character video id a YouTube link names, or "".

    A malformed id is left to ``transcribe.assert_youtube_id_exact``, which
    refuses it before any work: nothing here invents a key for it.
    """
    if host == "youtu.be":
        vid = parts.path.lstrip("/").split("/")[0]
        return vid if _YT_ID_RE.fullmatch(vid or "") else ""
    if host != "youtube.com" and not host.endswith(".youtube.com"):
        return ""
    query = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
    if query.get("v"):
        vid = query["v"][0]
        return vid if _YT_ID_RE.fullmatch(vid) else ""
    segments = [s for s in parts.path.split("/") if s]
    if len(segments) >= 2 and segments[0] in _YT_PATH_KINDS:
        vid = segments[1]
        return vid if _YT_ID_RE.fullmatch(vid) else ""
    return ""


def normalize(source: str) -> str:
    """The cache key text for a URL: a video id, or the URL minus tracking.

    Returns "" for anything that should not be cached: a local path, or a
    scheme that is not http(s).
    """
    raw = (source or "").strip()
    if not raw or "://" not in raw:
        return ""
    try:
        parts = urllib.parse.urlsplit(raw)
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https"):
        return ""
    host = (parts.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return ""
    video_id = _youtube_id(host, parts)
    if video_id:
        return f"youtube:{video_id}"
    pairs = [
        (name, value)
        for name, values in urllib.parse.parse_qsl(
            parts.query, keep_blank_values=True
        )
        for value in values
        if not _tracking(name)
    ]
    path = parts.path.rstrip("/") or "/"
    query = urllib.parse.urlencode(sorted(pairs))
    return f"{host}{path}" + (f"?{query}" if query else "")


def _slug(normalized: str) -> str:
    slug = _UNSAFE_RE.sub("-", normalized.lower()).strip("-")
    return slug[:48].strip("-") or "audio"


def _key(normalized: str) -> str:
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def entry_path(source: str, *, root: Optional[Path] = None) -> Optional[Path]:
    """The file this source's audio would be kept in, or None if not cacheable."""
    normalized = normalize(source)
    if not normalized:
        return None
    return cache_dir(root) / f"{_slug(normalized)}-{_key(normalized)}{SUFFIX}"


def lookup(
    source: str,
    *,
    ttl: int = DEFAULT_TTL_SECONDS,
    now: Optional[float] = None,
    root: Optional[Path] = None,
) -> Optional[Path]:
    """A still-fresh kept file for ``source``, or None. Expired entries go."""
    path = entry_path(source, root=root)
    if path is None:
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    if stat.st_size <= 0:
        _unlink(path)
        return None
    stamp = _now(now)
    if stamp - stat.st_mtime > ttl:
        _unlink(path)
        return None
    return path


def store(
    source: str,
    audio: Path,
    *,
    ttl: int = DEFAULT_TTL_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    now: Optional[float] = None,
    root: Optional[Path] = None,
) -> Optional[Path]:
    """Copy ``audio`` in as this source's entry, then sweep. None on failure.

    A cache that cannot write is not a transcription that failed: the caller
    reports ``miss`` and the run carries on with its own copy.
    """
    dest = entry_path(source, root=root)
    if dest is None:
        return None
    stamp = _now(now)
    part = dest.with_name(dest.name + ".part")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(audio, part)
        if part.stat().st_size <= 0:
            _unlink(part)
            return None
        os.utime(part, (stamp, stamp))
        os.replace(part, dest)
    except OSError:
        _unlink(part)
        return None
    evict(ttl=ttl, max_bytes=max_bytes, now=stamp, root=root)
    return dest


def evict(
    *,
    ttl: int = DEFAULT_TTL_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    now: Optional[float] = None,
    root: Optional[Path] = None,
) -> List[Path]:
    """Drop expired entries, then the oldest until the folder is under cap.

    Runs at the start of every transcribe. Returns the paths removed.
    """
    folder = cache_dir(root)
    removed: List[Path] = []
    stamp = _now(now)
    entries: List[tuple] = []
    try:
        candidates = list(folder.iterdir())
    except OSError:
        return removed
    for path in candidates:
        try:
            stat = path.stat()
        except OSError:
            continue
        if not path.is_file():
            continue
        if path.name.endswith(SUFFIX + ".part"):
            # An interrupted store: worth nothing, gone once it is old.
            if stamp - stat.st_mtime > ttl:
                _unlink(path)
                removed.append(path)
            continue
        if not path.name.endswith(SUFFIX):
            continue
        if stamp - stat.st_mtime > ttl:
            _unlink(path)
            removed.append(path)
            continue
        entries.append((stat.st_mtime, stat.st_size, path))
    total = sum(size for _mtime, size, _path in entries)
    for _mtime, size, path in sorted(entries):
        if total <= max_bytes or len(entries) <= 1:
            break
        _unlink(path)
        removed.append(path)
        total -= size
        entries = [entry for entry in entries if entry[2] != path]
    return removed


def info(
    *,
    ttl: int = DEFAULT_TTL_SECONDS,
    now: Optional[float] = None,
    root: Optional[Path] = None,
) -> dict:
    """The folder, its size, and how long a kept entry lives. For --cleanup."""
    folder = cache_dir(root)
    files = 0
    size = 0
    try:
        for path in folder.iterdir():
            if not path.is_file():
                continue
            files += 1
            try:
                size += path.stat().st_size
            except OSError:
                pass
    except OSError:
        pass
    return {
        "path": str(folder),
        "exists": folder.is_dir(),
        "files": files,
        "size_bytes": size,
        "size": format_bytes(size),
        "ttl_hours": round(ttl / 3600, 1),
    }


def format_bytes(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1000 or unit == "GB":
            return f"{size:.0f} {unit}" if unit != "GB" else f"{size:.1f} GB"
        size /= 1000
    return f"{size:.1f} GB"


def clear(*, root: Optional[Path] = None) -> List[str]:
    """Remove the whole folder. Call only after a yes (``--cleanup``)."""
    folder = cache_dir(root)
    if not folder.exists():
        return []
    shutil.rmtree(folder)
    return [str(folder)]


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _now(now: Optional[float]) -> float:
    import time

    return time.time() if now is None else now
