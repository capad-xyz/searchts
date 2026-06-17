# -*- coding: utf-8 -*-
"""YouTube — check if yt-dlp is available with JS runtime."""

import shutil

from searchts.probe import probe_command
from searchts.utils.paths import get_ytdlp_config_path, render_ytdlp_fix_command
from searchts.utils.text import read_utf8_text

from .base import Channel


def _has_js_runtime_config(config_path) -> bool:
    """Return whether yt-dlp config explicitly enables a JS runtime."""
    try:
        if not config_path.exists():
            return False
        return "--js-runtimes" in read_utf8_text(config_path)
    except OSError:
        return False


class YouTubeChannel(Channel):
    name = "youtube"
    description = "YouTube videos and subtitles"
    backends = ["yt-dlp"]
    tier = 0

    def can_handle(self, url: str) -> bool:
        from urllib.parse import urlparse

        d = urlparse(url).netloc.lower()
        return "youtube.com" in d or "youtu.be" in d

    def check(self, config=None):
        # Actually run yt-dlp --version to probe liveness, distinguishing not-installed / broken venv / won't-run
        probe = probe_command("yt-dlp", ["--version"], timeout=10, package="yt-dlp")
        if probe.status == "missing":
            self.active_backend = None
            return "off", "yt-dlp is not installed. Install: pip install yt-dlp"
        if probe.status == "broken":
            self.active_backend = None
            return "error", f"yt-dlp is installed but cannot execute\n{probe.hint}"
        if not probe.ok:  # timeout / error: installed but won't run
            self.active_backend = None
            detail = probe.hint or probe.output or probe.status
            return "error", f"yt-dlp does not run correctly: {detail}"
        # The yt-dlp binary is alive; the later JS runtime/transcription checks only affect ok/warn, not backend attribution
        self.active_backend = "yt-dlp"
        # Check JS runtime
        has_js = shutil.which("deno") or shutil.which("node")
        if not has_js:
            return "warn", (
                "yt-dlp is installed but lacks a JS runtime (required by YouTube).\n"
                "  Install Node.js or deno, then run: searchts install"
            )
        # Check yt-dlp config for --js-runtimes
        # Deno works out of the box; Node.js requires explicit config
        has_deno = shutil.which("deno")
        if not has_deno:
            ytdlp_config = get_ytdlp_config_path()
            if not _has_js_runtime_config(ytdlp_config):
                return "warn", (
                    f"yt-dlp is installed but the JS runtime is not configured. Run:\n  {render_ytdlp_fix_command()}"
                )
        # Surface transcription readiness so `doctor` reports it.
        from searchts.transcribe import transcription_readiness

        msg = "Can extract video info and subtitles"
        msg += transcription_readiness(config)
        return "ok", msg

    def transcribe(self, url: str, *, provider: str = "auto", config=None) -> str:
        """Download a YouTube video's audio and return its transcript.

        Delegates to :func:`searchts.transcribe.transcribe`. Imported lazily
        so the channel module stays cheap to import for users who never
        transcribe.
        """
        from searchts.transcribe import transcribe as _transcribe

        return _transcribe(url, provider=provider, config=config)

