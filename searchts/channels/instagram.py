# -*- coding: utf-8 -*-
"""Instagram — download audio with yt-dlp and transcribe via Whisper.

Mirrors :mod:`searchts.channels.youtube`: the same yt-dlp probe and the same
audio -> Whisper path (no video understanding, no vision — transcript only).
Instagram is rate-limited and often gates media behind a login, so the check
notes that `--cookies-from-browser` may be required.
"""

from searchts.probe import probe_command

from .base import Channel

#: Instagram frequently rate-limits or requires a logged-in session for media.
_COOKIES_NOTE = (
    "Instagram is rate-limited and may require a login; if a download fails, pass "
    "`--cookies-from-browser <browser>` to yt-dlp (e.g. yt-dlp --cookies-from-browser chrome <url>)."
)


class InstagramChannel(Channel):
    name = "instagram"
    description = "Instagram reels and video posts (audio transcript)"
    backends = ["yt-dlp"]
    tier = 0

    def can_handle(self, url: str) -> bool:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if "instagram.com" not in parsed.netloc.lower():
            return False
        path = parsed.path.lower()
        return any(seg in path for seg in ("/reel/", "/reels/", "/p/", "/tv/"))

    def check(self, config=None):
        # Actually run yt-dlp --version to probe liveness, distinguishing not-installed / broken venv / won't-run.
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
        # The yt-dlp binary is alive; the transcription readiness below only affects ok/warn, not backend attribution.
        self.active_backend = "yt-dlp"
        # Surface transcription readiness so `doctor` reports it.
        from searchts.transcribe import transcription_readiness

        msg = "Can download Instagram video audio for transcription"
        msg += transcription_readiness(config)
        # Instagram-specific caveat about login / rate limits.
        msg += f". {_COOKIES_NOTE}"
        return "ok", msg

    def transcribe(self, url: str, *, provider: str = "auto", config=None) -> str:
        """Download an Instagram video's audio and return its transcript.

        Delegates to :func:`searchts.transcribe.transcribe` (the same audio ->
        Whisper pipeline used by YouTube). Imported lazily so the channel module
        stays cheap to import for users who never transcribe.
        """
        from searchts.transcribe import transcribe as _transcribe

        return _transcribe(url, provider=provider, config=config)
