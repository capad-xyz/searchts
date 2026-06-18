# -*- coding: utf-8 -*-
"""Transcription: subtitles-first, with a Whisper audio fallback.

For a URL we first try the video's EXISTING captions via yt-dlp (no API key,
no audio download, no model) — most YouTube videos and many TikToks ship with
them. Only when there are no usable subtitles do we fall back to the audio ->
Whisper pipeline: download audio (yt-dlp), compress + chunk (ffmpeg), then turn
each chunk into text. With a hosted key that posts to a Whisper-compatible API
(Groq's free `whisper-large-v3`, falling back to OpenAI's `whisper-1`). With no
key at all it can run `faster-whisper` locally on the CPU — an optional
dependency installed via ``pip install "searchts[local-transcribe]"``.

Public entry point:
    transcribe(source, *, provider="auto", out_dir=None, config=None,
               prefer_subtitles=True) -> str

Designed to be importable from channels (e.g. YouTubeChannel.transcribe).
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
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


def _ytdlp_module_available() -> bool:
    """Return whether the `yt_dlp` Python module is importable."""
    return importlib.util.find_spec("yt_dlp") is not None


def ytdlp_available() -> bool:
    """Return whether yt-dlp is usable at all.

    yt-dlp ships as a Python dependency of searchts, so its `yt_dlp` MODULE is
    always importable in our venv/pipx install even though its console script is
    NOT on the system PATH there. Prefer the module; accept a PATH binary too.
    """
    return _ytdlp_module_available() or bool(shutil.which("yt-dlp"))


def _ytdlp_cmd() -> List[str]:
    """Return the command prefix used to invoke yt-dlp.

    Prefer `[sys.executable, "-m", "yt_dlp"]` whenever the `yt_dlp` module is
    importable — that always works from a venv/pipx `searchts.exe` invoked by
    full path, where the bare `yt-dlp` console script is NOT on PATH. Only fall
    back to a PATH `yt-dlp` binary when the module is absent; raise an
    actionable MissingDependency when neither is available.
    """
    if _ytdlp_module_available():
        return [sys.executable, "-m", "yt_dlp"]
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    raise MissingDependency(
        "yt-dlp not found. It ships with searchts; reinstall searchts, or "
        'install it directly with `pip install yt-dlp`.'
    )


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
    template = out_dir / "source.%(ext)s"
    _run(
        [
            *_ytdlp_cmd(),
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


#: Minimum length (non-space chars) for a subtitle track to be worth returning
#: instead of falling back to audio transcription. A handful of stray chars from
#: a near-empty caption file should not pre-empt Whisper.
MIN_SUBTITLE_CHARS = 20

#: Inline cue tags such as <c>, <00:00:01.000>, </c> emitted in auto-captions.
_VTT_TAG_RE = re.compile(r"<[^>]+>")


def fetch_subtitles(
    url: str,
    work_dir: Path,
    *,
    config: Optional[Config] = None,
) -> Optional[str]:
    """Return a video's existing captions as plain text, or None if absent.

    Uses yt-dlp to grab any English subtitle track (manual or auto-generated)
    without downloading the video — no API key, no audio, no Whisper model. A
    nonzero yt-dlp exit (no subtitles, private video, network error, ...) is
    treated as "no subtitles" and returns None rather than raising, so the
    caller can fall back to the audio pipeline.
    """
    if not ytdlp_available():
        return None

    template = work_dir / "%(id)s"
    try:
        _run(
            [
                *_ytdlp_cmd(),
                "--write-sub",
                "--write-auto-sub",
                "--sub-lang",
                "en.*,en",
                "--sub-format",
                "vtt",
                "--skip-download",
                "--no-playlist",
                "-o",
                str(template),
                url,
            ],
            timeout=120,
        )
    except TranscribeError:
        # No subtitles / private / network hiccup — not fatal, fall back.
        return None

    vtts = sorted(work_dir.glob("*.vtt"))
    if not vtts:
        return None

    # Prefer a manually-authored track over an auto-generated one. yt-dlp names
    # auto-captions with markers like ".en-auto." / ".a.en." / ".auto.", so a
    # track lacking those is treated as manual and wins.
    def _is_auto(path: Path) -> bool:
        n = path.name.lower()
        return "auto" in n or ".a." in n

    manual = [p for p in vtts if not _is_auto(p)]
    chosen = manual[0] if manual else vtts[0]

    try:
        raw = chosen.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    text = _vtt_to_text(raw)
    return text or None


def _vtt_to_text(vtt: str) -> str:
    """Convert WebVTT cue data to clean prose.

    Drops the WEBVTT header, NOTE / Kind: / Language: metadata, timestamp cue
    lines, bare numeric cue indices, and inline tags; collapses consecutive
    duplicate lines (auto-captions repeat the rolling text from cue to cue).
    """
    out: List[str] = []
    prev: Optional[str] = None
    for raw_line in vtt.splitlines():
        line = _VTT_TAG_RE.sub("", raw_line).strip()
        if not line:
            continue
        if line.startswith("WEBVTT"):
            continue
        if line.startswith(("NOTE", "Kind:", "Language:")):
            continue
        if "-->" in line:  # timestamp cue line
            continue
        if line.isdigit():  # bare numeric cue index
            continue
        if line == prev:  # collapse rolling-text duplicates
            continue
        out.append(line)
        prev = line
    return "\n".join(out).strip()


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
    prefer_subtitles: bool = True,
) -> str:
    """Transcribe a URL or local file path. Returns the joined transcript text.

    Subtitles-first: for a URL (not a local file) and when `prefer_subtitles`
    is set, the video's EXISTING captions are fetched via yt-dlp and returned
    directly — no API key, no audio download, no Whisper model. Only when there
    are no usable subtitles does it fall back to the audio -> Whisper pipeline,
    and ONLY then is a transcription backend required.

    `provider` is one of `auto`, `groq`, `openai`, or `local`. `auto` prefers a
    configured hosted key (groq -> openai) and otherwise uses the keyless
    `local` backend (faster-whisper) when it is installed. `local` forces local
    transcription and needs no API key. Pass `prefer_subtitles=False` to skip
    captions and force audio transcription.

    Intermediate audio (the download, the compressed copy, and any chunks) plus
    any fetched .vtt subtitle files are written to a private temporary directory
    that is deleted automatically when transcription finishes, whether it
    succeeds or fails, so nothing is left on the user's disk. Pass `out_dir`
    only if you want to keep the intermediates; in that case the directory is
    yours to manage.
    """
    cfg = config or Config()

    if out_dir is not None:
        # Caller-owned directory: use it as-is and leave the files in place.
        work_dir = Path(out_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        return _run_transcription(source, work_dir, provider, cfg, prefer_subtitles)

    # Default: an ephemeral workspace removed on exit (even on exception), so a
    # downloaded video/audio (and any fetched .vtt) never lingers on disk.
    # ignore_cleanup_errors guards the classic Windows case where an antivirus
    # scan or a slow-to-release handle briefly locks a file: worst case a stray
    # temp file waits for the OS to reap it, instead of a lock turning a finished
    # transcription into a crash.
    with tempfile.TemporaryDirectory(
        prefix="searchts-transcribe-", ignore_cleanup_errors=True
    ) as tmp:
        return _run_transcription(source, Path(tmp), provider, cfg, prefer_subtitles)


def _validate_backend(order: List[str], cfg: Config) -> None:
    """Raise NoProviderConfigured if no backend in `order` can transcribe audio.

    Local needs no key, just an importable faster-whisper; hosted providers
    need their configured key. Only called on the audio fallback path, never
    when subtitles already satisfied the request.
    """
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


def _run_transcription(
    source: str,
    work_dir: Path,
    provider: str,
    cfg: Config,
    prefer_subtitles: bool,
) -> str:
    """Try subtitles first (URL only), else download audio and transcribe.

    A captioned URL returns here with NO provider validation, NO audio download,
    and NO key required. Provider validation and the audio -> Whisper pipeline
    run only on the fallback path.
    """
    src_path = Path(source)
    is_local_file = src_path.is_file()

    if not is_local_file and prefer_subtitles:
        subs = fetch_subtitles(source, work_dir, config=cfg)
        if subs and len(subs.replace(" ", "")) >= MIN_SUBTITLE_CHARS:
            return subs

    # Fallback: audio -> Whisper. Resolve provider order and require a usable
    # backend now — a captioned URL never reaches this point.
    order = _provider_order(provider, cfg)
    _validate_backend(order, cfg)

    if is_local_file:
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
