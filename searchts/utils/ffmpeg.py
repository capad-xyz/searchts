"""Where searchts finds ffmpeg (#442).

ffmpeg on PATH wins, so a user's own build (with its codecs) is what runs.
Otherwise the binary bundled by the ``imageio-ffmpeg`` dependency is used, so
transcription needs no system install. That package ships ffmpeg only, no
ffprobe; nothing searchts runs needs ffprobe (yt-dlp falls back to ffmpeg for
the probe its audio extraction does).
"""

from __future__ import annotations

import os
import shutil
from typing import List, Optional


def bundled_ffmpeg() -> Optional[str]:
    """The imageio-ffmpeg binary, or None when the package or binary is absent."""
    try:
        import imageio_ffmpeg
    except Exception:  # noqa: BLE001 - a missing optional binary is not an error
        return None
    try:
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - e.g. no binary for this platform
        return None
    return exe if exe and os.path.isfile(exe) else None


def ffmpeg_exe() -> Optional[str]:
    """ffmpeg to run: PATH first, then the bundled one. None when neither."""
    return shutil.which("ffmpeg") or bundled_ffmpeg()


def ffmpeg_source() -> str:
    """``"PATH"``, ``"bundled (imageio-ffmpeg)"`` or ``""`` for doctor lines."""
    if shutil.which("ffmpeg"):
        return "PATH"
    if bundled_ffmpeg():
        return "bundled (imageio-ffmpeg)"
    return ""


def ytdlp_ffmpeg_args() -> List[str]:
    """``--ffmpeg-location`` for yt-dlp when ffmpeg is only the bundled one.

    yt-dlp looks on PATH itself; it only needs telling about a binary that is
    not there. A file path is accepted, and its missing ffprobe sibling makes
    yt-dlp use ffmpeg for probing.
    """
    if shutil.which("ffmpeg"):
        return []
    exe = bundled_ffmpeg()
    return ["--ffmpeg-location", exe] if exe else []
