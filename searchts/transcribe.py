# -*- coding: utf-8 -*-
"""Whisper audio transcription: hosted (Groq → OpenAI) or keyless local.

Downloads audio (yt-dlp), compresses + chunks (ffmpeg), then turns each chunk
into text. With a hosted key it posts to a Whisper-compatible API (Groq's free
`whisper-large-v3`, falling back to OpenAI's `whisper-1`). With no key at all it
can run `faster-whisper` locally on the CPU — an optional dependency installed
via ``pip install "searchts[local-transcribe]"``.

Public entry point:
    transcribe(source, *, provider="auto", out_dir=None, config=None) -> str

Designed to be importable from channels (e.g. YouTubeChannel.transcribe).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

import requests

from searchts.config import Config

# Whisper API limit is 25MB; leave headroom for multipart overhead.
SIZE_LIMIT_BYTES = 24 * 1024 * 1024
CHUNK_SECONDS = 600  # 10 min — small enough that boundary cuts rarely lose meaning

#: The keyless, local backend (faster-whisper). Not in PROVIDERS because it has
#: no endpoint/key — it is selected explicitly and handled on its own path.
LOCAL_PROVIDER = "local"

#: Default faster-whisper model. "base" is a good CPU/quality balance and runs
#: comfortably on a 16GB machine. Override via config `whisper_model` or env
#: `SEARCHTS_WHISPER_MODEL`.
DEFAULT_LOCAL_MODEL = "base"

PROVIDERS = {
    "groq": {
        "endpoint": "https://api.groq.com/openai/v1/audio/transcriptions",
        "model": "whisper-large-v3",
        "key_field": "groq_api_key",
    },
    "openai": {
        "endpoint": "https://api.openai.com/v1/audio/transcriptions",
        "model": "whisper-1",
        "key_field": "openai_api_key",
    },
}


class TranscribeError(RuntimeError):
    """Raised when transcription cannot complete."""


class MissingDependency(TranscribeError):
    """Raised when a required external binary is missing."""


class NoProviderConfigured(TranscribeError):
    """Raised when no provider has an API key configured."""


#: Cached faster-whisper model, keyed by model size, so repeated chunks (and
#: repeated transcribe() calls in one process) do not reload the weights.
_LOCAL_MODEL_CACHE: dict = {}


def _local_model_size(config: Optional[Config]) -> str:
    """Resolve the faster-whisper model size from config/env, default `base`."""
    cfg = config or Config()
    return cfg.get("whisper_model") or os.environ.get(
        "SEARCHTS_WHISPER_MODEL"
    ) or DEFAULT_LOCAL_MODEL


def _import_faster_whisper():
    """Import faster-whisper, raising an actionable error when it is absent."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise MissingDependency(
            "local transcription needs faster-whisper. Install it with:\n"
            '  pip install "searchts[local-transcribe]"'
        ) from e
    return WhisperModel


def local_available() -> bool:
    """Return whether the keyless local backend (faster-whisper) is importable."""
    try:
        _import_faster_whisper()
    except MissingDependency:
        return False
    return True


def _load_local_model(model_size: str):
    """Load (and cache) a CPU faster-whisper model. int8 keeps RAM/CPU modest."""
    if model_size not in _LOCAL_MODEL_CACHE:
        WhisperModel = _import_faster_whisper()
        _LOCAL_MODEL_CACHE[model_size] = WhisperModel(
            model_size, device="cpu", compute_type="int8"
        )
    return _LOCAL_MODEL_CACHE[model_size]


def transcribe_chunk_local(
    chunk: Path,
    *,
    config: Optional[Config] = None,
) -> str:
    """Transcribe one chunk locally with faster-whisper. No API key needed.

    Raises MissingDependency (a TranscribeError) if faster-whisper is absent.
    """
    model_size = _local_model_size(config)
    model = _load_local_model(model_size)
    try:
        segments, _info = model.transcribe(str(chunk))
        return "".join(seg.text for seg in segments)
    except Exception as e:  # surface model/runtime failures as TranscribeError
        raise TranscribeError(f"local: faster-whisper failed: {e}") from e


def _require(binary: str) -> None:
    if not shutil.which(binary):
        raise MissingDependency(f"{binary} not found in PATH")


def _run(cmd: List[str], timeout: int = 600) -> None:
    """Run a subprocess, raising TranscribeError on nonzero exit or timeout.

    cmd carries user-supplied URLs/paths into yt-dlp/ffmpeg — a stalled
    network read or a hung probe must not block the CLI forever.
    """
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise TranscribeError(f"{cmd[0]} timed out after {timeout}s")
    if proc.returncode != 0:
        raise TranscribeError(
            f"{cmd[0]} failed (exit {proc.returncode}): {proc.stderr.strip()[:300]}"
        )


def download_audio(url: str, out_dir: Path) -> Path:
    """Download audio with yt-dlp into out_dir; return the resulting file path."""
    _require("yt-dlp")
    template = out_dir / "source.%(ext)s"
    _run(
        [
            "yt-dlp",
            "-x",
            "--audio-format",
            "m4a",
            "--audio-quality",
            "0",
            "-o",
            str(template),
            url,
        ],
        timeout=1800,  # long podcasts over slow networks — generous but bounded
    )
    files = sorted(out_dir.glob("source.*"))
    if not files:
        raise TranscribeError("yt-dlp produced no output file")
    return files[0]


def compress_audio(src: Path, out_dir: Path) -> Path:
    """Re-encode to mono / 16kHz / 32kbps m4a — keeps most content under 25MB."""
    _require("ffmpeg")
    dst = out_dir / "compressed.m4a"
    _run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "32k",
            str(dst),
        ]
    )
    return dst


def chunk_audio(src: Path, out_dir: Path, segment_seconds: int = CHUNK_SECONDS) -> List[Path]:
    """Split src into segments. Re-encodes each segment so cuts align to keyframes."""
    _require("ffmpeg")
    pattern = out_dir / "chunk_%03d.m4a"
    _run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-f",
            "segment",
            "-segment_time",
            str(segment_seconds),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "32k",
            str(pattern),
        ]
    )
    chunks = sorted(out_dir.glob("chunk_*.m4a"))
    if not chunks:
        raise TranscribeError("ffmpeg produced no chunks")
    return chunks


def _provider_key(provider: str, config: Config) -> Optional[str]:
    field = PROVIDERS[provider]["key_field"]
    val = config.get(field)
    return val or None


def transcription_readiness(config: Optional[Config]) -> str:
    """Build the doctor/check() suffix describing how audio can be transcribed.

    Reports configured hosted providers (groq/openai) and, separately, whether
    the keyless local backend is available. Returns "" when nothing is usable
    so callers can append it unconditionally.
    """
    if config is None:
        return ""
    providers = []
    if config.is_configured("groq_whisper"):
        providers.append("groq")
    if config.is_configured("openai_whisper"):
        providers.append("openai")

    parts = []
    if providers:
        if not shutil.which("ffmpeg"):
            return " (audio transcription requires ffmpeg)"
        parts.append(f"can transcribe audio ({'->'.join(providers)})")
    if local_available():
        parts.append("local Whisper available (no key needed)")
    if not parts:
        return ""
    return ", " + ", ".join(parts)


def transcribe_chunk(
    chunk: Path,
    provider: str,
    *,
    config: Optional[Config] = None,
    timeout: int = 120,
) -> str:
    """Transcribe one chunk via the named provider. Raises TranscribeError on failure."""
    if provider == LOCAL_PROVIDER:
        return transcribe_chunk_local(chunk, config=config)
    if provider not in PROVIDERS:
        raise TranscribeError(f"unknown provider: {provider}")
    cfg = config or Config()
    key = _provider_key(provider, cfg)
    if not key:
        raise NoProviderConfigured(
            f"{provider}: missing {PROVIDERS[provider]['key_field']} "
            f"(configure with `searchts configure {provider}-key ...`)"
        )

    info = PROVIDERS[provider]
    with chunk.open("rb") as fh:
        try:
            resp = requests.post(
                info["endpoint"],
                headers={"Authorization": f"Bearer {key}"},
                files={"file": (chunk.name, fh, "audio/m4a")},
                data={"model": info["model"], "response_format": "text"},
                timeout=timeout,
            )
        except requests.RequestException as e:
            raise TranscribeError(f"{provider}: network error: {e}") from e

    if not resp.ok:
        raise TranscribeError(f"{provider}: HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.text


def _provider_order(provider: str, config: Optional[Config] = None) -> List[str]:
    """Resolve `provider` into an ordered list of backends to try.

    `auto` prefers a hosted provider when its key is configured (groq, then
    openai — both faster than local CPU inference) and otherwise falls back to
    the keyless local backend when faster-whisper is importable.
    """
    if provider == "auto":
        cfg = config or Config()
        order = [p for p in ("groq", "openai") if _provider_key(p, cfg)]
        if order:
            return order
        if local_available():
            return [LOCAL_PROVIDER]
        # Nothing usable — return hosted order so validation raises a helpful error.
        return ["groq", "openai"]
    if provider == LOCAL_PROVIDER:
        return [LOCAL_PROVIDER]
    if provider in PROVIDERS:
        return [provider]
    raise TranscribeError(f"unknown provider: {provider} (use auto|groq|openai|local)")


def transcribe(
    source: str,
    *,
    provider: str = "auto",
    out_dir: Optional[Path] = None,
    config: Optional[Config] = None,
) -> str:
    """Transcribe a URL or local file path. Returns the joined transcript text.

    `provider` is one of `auto`, `groq`, `openai`, or `local`. `auto` prefers a
    configured hosted key (groq -> openai) and otherwise uses the keyless
    `local` backend (faster-whisper) when it is installed. `local` forces local
    transcription and needs no API key.

    Intermediate audio (the download, the compressed copy, and any chunks) is
    written to a private temporary directory that is deleted automatically when
    transcription finishes, whether it succeeds or fails, so nothing is left on
    the user's disk. Pass `out_dir` only if you want to keep the intermediates;
    in that case the directory is yours to manage.
    """
    cfg = config or Config()
    order = _provider_order(provider, cfg)

    # Validate a usable backend exists before doing expensive download/encode
    # work. Local needs no key, just an importable faster-whisper.
    usable = any(
        (p == LOCAL_PROVIDER and local_available()) or _provider_key(p, cfg)
        for p in order
    )
    if not usable:
        hosted = ", ".join(PROVIDERS[p]["key_field"] for p in order if p in PROVIDERS)
        raise NoProviderConfigured(
            f"no transcription backend available: configure a hosted key "
            f"(one of: {hosted}), or `pip install \"searchts[local-transcribe]\"` "
            "for keyless local transcription"
        )

    if out_dir is not None:
        # Caller-owned directory: use it as-is and leave the files in place.
        work_dir = Path(out_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        return _run_transcription(source, work_dir, order, cfg)

    # Default: an ephemeral workspace removed on exit (even on exception), so a
    # downloaded video/audio never lingers on disk. ignore_cleanup_errors guards
    # the classic Windows case where an antivirus scan or a slow-to-release
    # handle briefly locks a file: worst case a stray temp file waits for the OS
    # to reap it, instead of a lock turning a finished transcription into a crash.
    with tempfile.TemporaryDirectory(
        prefix="searchts-transcribe-", ignore_cleanup_errors=True
    ) as tmp:
        return _run_transcription(source, Path(tmp), order, cfg)


def _run_transcription(source: str, work_dir: Path, order: List[str], cfg: Config) -> str:
    """Locate/download audio, compress, chunk, and transcribe within work_dir."""
    src_path = Path(source)
    if src_path.is_file():
        audio = src_path  # a local file the caller owns; never deleted by us
    else:
        audio = download_audio(source, work_dir)

    compressed = compress_audio(audio, work_dir)
    if compressed.stat().st_size <= SIZE_LIMIT_BYTES:
        chunks = [compressed]
    else:
        chunks = chunk_audio(compressed, work_dir)

    pieces: List[str] = []
    for chunk in chunks:
        text = _transcribe_with_fallback(chunk, order, cfg)
        pieces.append(text.strip())
    return "\n".join(p for p in pieces if p)


def _transcribe_with_fallback(chunk: Path, order: List[str], config: Config) -> str:
    """Try each provider in order; return first success or raise the last error."""
    last_err: Optional[Exception] = None
    for p in order:
        # Local needs no key; hosted providers without a configured key are
        # skipped silently — caller already validated at least one is usable.
        if p != LOCAL_PROVIDER and not _provider_key(p, config):
            continue
        try:
            return transcribe_chunk(chunk, p, config=config)
        except TranscribeError as e:
            last_err = e
            continue
    raise TranscribeError(f"all providers failed for {chunk.name}: {last_err}")
