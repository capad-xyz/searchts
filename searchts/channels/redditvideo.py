# -*- coding: utf-8 -*-
"""Reddit video — download audio with yt-dlp and transcribe via Whisper.

Separate from the TEXT :class:`~searchts.channels.reddit.RedditChannel`, which
needs a logged-in session (anonymous .json is 403-blocked). Reddit *video*
(v.redd.it / DASH-hosted clips on post permalinks) is served by a CDN that
needs NO login, so yt-dlp can fetch it anonymously and feed the same audio ->
Whisper pipeline used by YouTube. Transcript only — no vision, no video
understanding.

Registered ahead of the text RedditChannel so video URLs route here first; the
text channel still handles ordinary reddit.com posts/comments and search.
"""

import shutil

from searchts.probe import probe_command

from .base import Channel


class RedditVideoChannel(Channel):
    name = "reddit-video"
    description = "Reddit videos (v.redd.it, audio transcript)"
    backends = ["yt-dlp"]
    tier = 0  # v.redd.it needs no login, unlike the text Reddit channel

    def can_handle(self, url: str) -> bool:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        d = parsed.netloc.lower()
        # v.redd.it is the direct video CDN host — always a video.
        if "v.redd.it" in d:
            return True
        # A reddit.com post permalink may host a video; treat /comments/ URLs as
        # transcribable candidates (yt-dlp returns nothing if there is no video).
        if "reddit.com" in d and "/comments/" in parsed.path.lower():
            return True
        return False

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
        msg = "Can download Reddit video audio for transcription (v.redd.it needs no login)"
        if config is not None:
            providers = []
            if config.is_configured("groq_whisper"):
                providers.append("groq")
            if config.is_configured("openai_whisper"):
                providers.append("openai")
            if providers:
                if not shutil.which("ffmpeg"):
                    msg += " (audio transcription requires ffmpeg)"
                else:
                    msg += f", can transcribe audio ({'->'.join(providers)})"
        return "ok", msg

    def transcribe(self, url: str, *, provider: str = "auto", config=None) -> str:
        """Download a Reddit video's audio and return its transcript.

        Delegates to :func:`searchts.transcribe.transcribe` (the same audio ->
        Whisper pipeline used by YouTube). Imported lazily so the channel module
        stays cheap to import for users who never transcribe.
        """
        from searchts.transcribe import transcribe as _transcribe

        return _transcribe(url, provider=provider, config=config)
