# -*- coding: utf-8 -*-
"""Fail-open read of a player page: the captions, or a named failure.

A watch URL, a short, a reel, or a ``v.redd.it`` file is a player. Its words
are spoken. ``unlocker.fetch`` asks this module before the ladder, the same
way it asks the share extractors. Captions come back as the read. No captions
is a failure that names ``searchts transcribe`` for the audio, rather than a
title and a shell handed back as the article.

``extract`` never raises. A crash returns ``None`` and the ladder runs.
A URL that is not a player returns ``None``. This is one module, not a
per-host router and not a plugin system.
"""

from __future__ import annotations

import re
import tempfile
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_PATH_KINDS = frozenset({"shorts", "embed", "live", "v"})


@dataclass
class PlayerRead:
    """A player read. Exactly one of ``markdown`` or ``failure`` is set.

    Both empty means the module could not decide; the caller falls through.
    """

    markdown: str = ""
    failure: str = ""


def _host(url: str) -> str:
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower().rstrip(".")
    except Exception:  # noqa: BLE001 - a bad URL is not a player
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _parts(url: str):
    try:
        return urllib.parse.urlparse(url)
    except Exception:  # noqa: BLE001
        return None


def _youtube_id(url: str) -> str:
    """The 11-character id, or "" when this URL is not one YouTube video."""
    parts = _parts(url)
    if parts is None:
        return ""
    host = _host(url)
    youtube = host == "youtube.com" or host.endswith(".youtube.com")
    nocookie = host == "youtube-nocookie.com" or host.endswith(".youtube-nocookie.com")
    if host == "youtu.be":
        vid = parts.path.lstrip("/").split("/")[0]
        return vid if _YT_ID.fullmatch(vid or "") else ""
    if not youtube and not nocookie:
        return ""
    qs = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
    if "v" in qs and _YT_ID.fullmatch(qs["v"][0] or ""):
        return qs["v"][0]
    segs = [s for s in parts.path.split("/") if s]
    if len(segs) >= 2 and segs[0] in _YT_PATH_KINDS and _YT_ID.fullmatch(segs[1]):
        return segs[1]
    return ""


def matches(url: str) -> bool:
    """True when the URL is one player, not a channel, a feed, or a homepage."""
    host = _host(url)
    if not host:
        return False
    if _youtube_id(url):
        return True
    parts = _parts(url)
    if parts is None:
        return False
    path = parts.path or ""
    if host == "tiktok.com" or host.endswith(".tiktok.com"):
        if host in {"vm.tiktok.com", "vt.tiktok.com"}:
            return bool(path.strip("/"))
        return "/video/" in path
    if host == "instagram.com":
        segs = [s for s in path.split("/") if s]
        return bool(segs) and segs[0] in {"reel", "reels", "tv"}
    if host == "v.redd.it":
        return bool(path.strip("/"))
    return False


def _no_captions(url: str) -> str:
    return (
        "this page's words are spoken and it has no captions. "
        f"searchts transcribe {url} reads the audio."
    )


def _no_ytdlp(url: str) -> str:
    return (
        "this page's words are spoken. No captions were read because "
        "yt-dlp is not installed. "
        f"searchts transcribe {url} is the next step once yt-dlp is installed."
    )


def _caption_markdown(url: str, text: str) -> str:
    note = (
        "[spoken: these are the player's captions. "
        f"searchts transcribe {url} reads the audio.]"
    )
    return f"{text.strip()}\n\n{note}"


def extract(url: str) -> Optional[PlayerRead]:
    """Captions for a player URL, a named failure, or ``None`` to fall through.

    Never raises. Subtitles only: no audio download and no Whisper. Those
    belong to ``searchts transcribe``, which the failure names.
    """
    if not matches(url):
        return None
    try:
        from searchts.transcribe import (
            MIN_SUBTITLE_CHARS,
            TranscribeError,
            assert_youtube_id_exact,
            fetch_subtitles,
            ytdlp_available,
        )
    except Exception:  # noqa: BLE001 - a broken import must not break fetch
        return None
    try:
        assert_youtube_id_exact(url)
    except TranscribeError as e:
        return PlayerRead(failure=str(e))
    if not ytdlp_available():
        return PlayerRead(failure=_no_ytdlp(url))
    try:
        with tempfile.TemporaryDirectory(
            prefix="searchts-player-", ignore_cleanup_errors=True
        ) as tmp:
            text = fetch_subtitles(url, Path(tmp))
    except Exception:  # noqa: BLE001 - fall through; do not hide the ladder
        return None
    if text and len(text.replace(" ", "")) >= MIN_SUBTITLE_CHARS:
        return PlayerRead(markdown=_caption_markdown(url, text))
    return PlayerRead(failure=_no_captions(url))
