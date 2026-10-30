# -*- coding: utf-8 -*-
"""Transcription: subtitles-first, with a Whisper audio fallback.

For a URL we first try the video's EXISTING captions via yt-dlp (no API key,
no audio download, no model) — most YouTube videos and many TikToks ship with
them. Only when there are no usable subtitles do we fall back to the audio ->
Whisper pipeline: download audio (yt-dlp), compress + chunk (ffmpeg), then turn
each chunk into text. With a hosted key that posts to a Whisper-compatible API
(Groq's free `whisper-large-v3`, falling back to OpenAI's `whisper-1`). With no
key at all it runs whisper.cpp locally (keyless; bundled with searchts as the
pywhispercpp CPU wheel). GPU-enabled wheels are not yet published by this
project. The model file is downloaded once, after the user approves it (see
``searchts.whispercpp``).
faster-whisper (``searchts[local-transcribe]``) is a fallback during the
migration window and goes away after it.

Public entry point:
    transcribe(source, *, provider="auto", out_dir=None, config=None,
               prefer_subtitles=True, cookies_from_browser=None) -> str

Designed to be importable from channels (e.g. YouTubeChannel.transcribe).
"""

from __future__ import annotations

import contextvars
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from searchts.config import Config
from searchts.progress import phase as progress_phase

# Whisper API limit is 25MB; leave headroom for multipart overhead.
SIZE_LIMIT_BYTES = 24 * 1024 * 1024
CHUNK_SECONDS = 600  # 10 min — small enough that boundary cuts rarely lose meaning

#: The keyless, local backend: whisper.cpp, else faster-whisper while that
#: fallback exists. Not in PROVIDERS because it has no endpoint/key.
LOCAL_PROVIDER = "local"

#: TEMPORARY (#439): forces the faster-whisper fallback. Removed with it.
FASTER_WHISPER_PROVIDER = "local-fw"

#: Default local model (#439: `base` misheard too much). Override with
#: --model, config `whisper_model`, or env `SEARCHTS_WHISPER_MODEL`.
DEFAULT_LOCAL_MODEL = "small"

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
    """Raised when transcription cannot complete.

    ``output`` holds the process stderr and stdout when a command failed,
    so a caller can tell a text post from a video that has no captions.
    """

    output: str = ""


class MissingDependency(TranscribeError):
    """Raised when a required external binary is missing."""


class NoProviderConfigured(TranscribeError):
    """Raised when no provider has an API key configured."""


class ModelDownloadNeeded(TranscribeError):
    """The local model is not cached and the download was not approved.

    Carries the model's name, size, source and destination so a caller can
    ask the user once and retry with ``yes``.
    """

    def __init__(self, message: str, model: dict):
        super().__init__(message)
        self.model = model


@dataclass
class TranscribeResult:
    """A transcript plus what made it: the receipt for --json and MCP."""

    text: str
    source: str  # "subtitles" or "audio"
    provider: Optional[str] = None  # groq, openai, local, or None for subtitles
    engine: Optional[str] = None  # whisper.cpp, faster-whisper, or the hosted model
    model: Optional[str] = None
    device: Optional[str] = None  # metal, cuda, vulkan, cpu; None when hosted
    language: Optional[str] = None
    translated: bool = False

    def receipt(self) -> dict:
        return {
            "source": self.source,
            "provider": self.provider,
            "engine": self.engine,
            "model": self.model,
            "device": self.device,
            "language": self.language,
            "translated": self.translated,
        }


#: Cached faster-whisper model, keyed by model size, so repeated chunks (and
#: repeated transcribe() calls in one process) do not reload the weights.
_LOCAL_MODEL_CACHE: dict = {}


def _local_model_size(config: Optional[Config]) -> str:
    """Resolve the local model name from config/env, default `small`.

    faster-whisper takes the same names (small, base, turbo).
    """
    cfg = config or Config()
    return cfg.get("whisper_model") or os.environ.get(
        "SEARCHTS_WHISPER_MODEL"
    ) or DEFAULT_LOCAL_MODEL


def _local_import_error_message(error: ImportError) -> str:
    """Name the interpreter that lacks faster-whisper, plus the import error."""
    return (
        "the faster-whisper fallback needs faster-whisper, but importing it failed in "
        f"the Python running searchts ({sys.executable}): {error}\n"
        "Install the extra into that interpreter with:\n"
        f'  "{sys.executable}" -m pip install "searchts[local-transcribe]"'
    )


def _import_faster_whisper():
    """Import faster-whisper, raising an actionable error when it is absent."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise MissingDependency(_local_import_error_message(e)) from e
    return WhisperModel


def faster_whisper_unavailable_reason() -> str:
    """Why faster-whisper cannot be imported here, or "" when it can.

    A failure that reaches the user needs the ImportError and the interpreter
    path so a machine with several installs can tell which one lacks it.
    """
    try:
        _import_faster_whisper()
    except MissingDependency as e:
        return str(e)
    return ""


def faster_whisper_available() -> bool:
    return not faster_whisper_unavailable_reason()


def whispercpp_available() -> bool:
    """Whether whisper.cpp (pywhispercpp, a base dependency) imports here."""
    from searchts import whispercpp

    return whispercpp.available()


def local_engine() -> Optional[str]:
    """The local engine `--provider local` runs: whisper.cpp, else the
    faster-whisper fallback, else None."""
    if whispercpp_available():
        return "whisper.cpp"
    if faster_whisper_available():
        return "faster-whisper"
    return None


def local_unavailable_reason() -> str:
    """Why no local engine runs here, or "" when one does."""
    if local_engine():
        return ""
    from searchts import whispercpp

    return whispercpp.unavailable_reason() or faster_whisper_unavailable_reason()


def local_available() -> bool:
    """Return whether a keyless local engine is importable."""
    return local_engine() is not None


def _load_local_model(model_size: str):
    """Load (and cache) a CPU faster-whisper model. int8 keeps RAM/CPU modest."""
    if model_size not in _LOCAL_MODEL_CACHE:
        WhisperModel = _import_faster_whisper()
        _LOCAL_MODEL_CACHE[model_size] = WhisperModel(
            model_size, device="cpu", compute_type="int8"
        )
    return _LOCAL_MODEL_CACHE[model_size]


#: Seconds ffmpeg may spend decoding one chunk before we call it stuck.
LOCAL_DECODE_TIMEOUT = 600
LOCAL_PCM_OUTPUT_LIMIT_BYTES = 64 * 1024 * 1024
LOCAL_PCM_OUTPUT_HEADROOM_BYTES = 1024 * 1024


def _decode_chunk_ffmpeg(
    chunk: Path,
    *,
    timeout: int = LOCAL_DECODE_TIMEOUT,
):
    """Decode a chunk to 16 kHz mono float32 PCM for faster-whisper.

    faster-whisper decodes a path itself with PyAV, and PyAV 15 removed the
    ``metadata_errors`` keyword its decoder still passes, so ``open()`` fails
    before any audio is read. Samples keep PyAV out of the local path and work
    with every PyAV version. numpy is imported here, not at module import, so
    the core install does not need it.
    """
    ffmpeg = _ffmpeg()
    cmd = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(chunk),
        "-f",
        "f32le",
        "-ac",
        "1",
        "-ar",
        "16000",
        # Keep stdout's capture bounded even if a malformed or unexpectedly
        # long input reaches this decoder without the normal 10-minute split.
        "-fs",
        str(LOCAL_PCM_OUTPUT_LIMIT_BYTES - LOCAL_PCM_OUTPUT_HEADROOM_BYTES),
        "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise TranscribeError(
            f"ffmpeg timed out after {timeout}s decoding {chunk.name} "
            "for local transcription"
        )
    stderr = (proc.stderr or b"").decode("utf-8", "replace")
    if proc.returncode != 0:
        detail = stderr.strip()[:300]
        err = TranscribeError(
            f"ffmpeg failed (exit {proc.returncode}) decoding {chunk.name} "
            "for local transcription" + (f": {detail}" if detail else "")
        )
        err.output = stderr
        raise err
    if len(proc.stdout or b"") >= (
        LOCAL_PCM_OUTPUT_LIMIT_BYTES - LOCAL_PCM_OUTPUT_HEADROOM_BYTES
    ):
        raise TranscribeError(
            f"ffmpeg decoded too much audio from {chunk.name} for local "
            "transcription; searchts limits each local audio segment to 10 minutes"
        )
    if not proc.stdout:
        detail = stderr.strip()[:300]
        raise TranscribeError(
            f"ffmpeg produced no audio decoding {chunk.name} for local "
            "transcription" + (f": {detail}" if detail else "")
        )

    numpy = importlib.import_module("numpy")

    return numpy.frombuffer(proc.stdout, dtype=numpy.float32)


def transcribe_chunk_faster_whisper(
    chunk: Path,
    *,
    config: Optional[Config] = None,
    hint: Optional[str] = None,
) -> str:
    """Transcribe one chunk with the faster-whisper fallback. No API key needed.

    The audio is decoded with ffmpeg first; the model gets samples, never a
    path, so faster-whisper does not touch PyAV's decoder. Raises
    MissingDependency (a TranscribeError) if faster-whisper or ffmpeg is absent.
    """
    model_size = _local_model_size(config)
    model = _load_local_model(model_size)
    samples = _decode_chunk_ffmpeg(chunk)
    try:
        if hint:
            segments, _info = model.transcribe(samples, initial_prompt=hint)
        else:
            segments, _info = model.transcribe(samples)
        return "".join(seg.text for seg in segments)
    except Exception as e:  # surface model/runtime failures as TranscribeError
        raise TranscribeError(f"local: faster-whisper failed: {e}") from e


def _model_info(spec) -> dict:
    from searchts import whispercpp

    return {
        "name": spec.name,
        "file": spec.filename,
        "size_bytes": spec.size_bytes,
        "size": whispercpp.format_bytes(spec.size_bytes),
        "url": spec.url,
        "path": str(whispercpp.model_path(spec)),
    }


def prepare_local_model(
    model: Optional[str] = None,
    *,
    config: Optional[Config] = None,
    yes: bool = False,
    progress: bool = False,
    translate: bool = False,
):
    """Resolve and, with approval, download the whisper.cpp model.

    Called before any audio is downloaded, so a missing approval costs
    nothing. Raises ModelDownloadNeeded without approval.
    """
    from searchts import whispercpp

    try:
        spec = whispercpp.resolve_model(model, config)
    except whispercpp.WhisperCppError as e:
        raise TranscribeError(str(e)) from e
    if translate and not spec.translates:
        raise TranscribeError(
            f"the '{spec.name}' model was not trained to translate; use "
            "--model small (or base) with --translate"
        )

    def _show(done: int, total: int) -> None:
        if progress:
            pct = int(done * 100 / max(total, 1))
            if pct % 10 == 0:
                _tick(True, f"downloading model {spec.filename}: {pct}%")

    try:
        path = whispercpp.ensure_model(spec, yes=yes, progress=_show)
    except whispercpp.ModelConsentNeeded as e:
        raise ModelDownloadNeeded(str(e), _model_info(spec)) from e
    except whispercpp.WhisperCppError as e:
        raise TranscribeError(f"local: {e}") from e
    return spec, path


def transcribe_chunk_whispercpp(
    chunk: Path,
    *,
    config: Optional[Config] = None,
    model: Optional[str] = None,
    hint: Optional[str] = None,
    translate: bool = False,
    yes: bool = False,
):
    """Transcribe one chunk with whisper.cpp; returns a ``whispercpp.Transcript``.

    ffmpeg decodes the chunk to samples, the same path faster-whisper uses.
    """
    from searchts import whispercpp

    spec, path = prepare_local_model(
        model, config=config, yes=yes, translate=translate
    )
    samples = _decode_chunk_ffmpeg(chunk)
    try:
        return whispercpp.transcribe_samples(
            samples, spec, path, hint=hint, translate=translate,
        )
    except whispercpp.WhisperCppError as e:
        raise TranscribeError(f"local: {e}") from e


def _require(binary: str) -> None:
    if not shutil.which(binary):
        raise MissingDependency(f"{binary} not found in PATH")


def ytdlp_ffmpeg_args() -> List[str]:
    """``--ffmpeg-location`` when ffmpeg is only the bundled one (#442)."""
    from searchts.utils.ffmpeg import ytdlp_ffmpeg_args as _args

    return _args()


def _ffmpeg() -> str:
    """ffmpeg to run: PATH first, then the bundled imageio-ffmpeg binary (#442)."""
    from searchts.utils.ffmpeg import ffmpeg_exe

    exe = ffmpeg_exe()
    if not exe:
        raise MissingDependency(
            "ffmpeg not found in PATH and the bundled imageio-ffmpeg binary is "
            "missing; reinstall searchts or install ffmpeg"
        )
    return exe


def _tick(progress: bool, msg: str) -> None:
    # Best-effort only: a closed/broken stderr must never abort a transcription.
    if not progress:
        return
    if sys.stderr is None:
        return
    from searchts import progress as _progress

    _progress.narrate(msg)


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


#: Browsers yt-dlp --cookies-from-browser accepts. Profile suffix (`chrome:Default`) is ok.
_COOKIE_BROWSERS = frozenset({
    "chrome", "chromium", "firefox", "edge", "brave", "opera", "safari", "vivaldi", "whale",
})


def cookies_from_browser_args(browser: Optional[str]) -> List[str]:
    """Return yt-dlp argv for an explicit browser, or []. Never infers a browser.

    F7: opt-in only. Callers that omit `browser` must not attach cookies.
    ``chrome:Default`` / ``chrome+gnomekeyring`` keep the leading name.
    """
    if not browser:
        return []
    raw = str(browser).strip()
    if not raw or raw.startswith("-"):
        raise TranscribeError(
            f"invalid --cookies-from-browser {browser!r}. "
            f"Use one of: {', '.join(sorted(_COOKIE_BROWSERS))}"
        )
    name = raw.split(":", 1)[0].split("+", 1)[0].lower()
    if name not in _COOKIE_BROWSERS:
        raise TranscribeError(
            f"unknown browser {browser!r}. "
            f"Use one of: {', '.join(sorted(_COOKIE_BROWSERS))}"
        )
    return ["--cookies-from-browser", raw]


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


def _run(cmd: List[str], timeout: int = 600) -> str:
    """Run a subprocess, raising TranscribeError on nonzero exit or timeout.

    Returns the combined stderr and stdout. On failure the same text is on
    ``TranscribeError.output`` so a caller can read it after the raise.
    cmd carries user-supplied URLs/paths into yt-dlp/ffmpeg — a stalled
    network read or a hung probe must not block the CLI forever.
    """
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise TranscribeError(f"{cmd[0]} timed out after {timeout}s")
    output = f"{proc.stderr or ''}\n{proc.stdout or ''}"
    if proc.returncode != 0:
        err = TranscribeError(
            f"{cmd[0]} failed (exit {proc.returncode}): {(proc.stderr or '').strip()[:300]}"
        )
        err.output = output
        raise err
    return output


def download_audio(
    url: str,
    out_dir: Path,
    *,
    cookies_from_browser: Optional[str] = None,
) -> Path:
    """Download audio with yt-dlp into out_dir; return the resulting file path."""
    template = out_dir / "source.%(ext)s"
    _run(
        [
            *_ytdlp_cmd(),
            *cookies_from_browser_args(cookies_from_browser),
            *ytdlp_ffmpeg_args(),
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

_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_PATH_KINDS = frozenset({"shorts", "embed", "live", "v"})


def assert_youtube_id_exact(url: str) -> None:
    """Refuse YouTube URLs whose video id is not exactly 11 characters.

    yt-dlp truncates ``v=dQw4w9WgXcQ_private_fake`` to the real video. That
    is a silent wrong-transcript (P1.4). Non-YouTube URLs are ignored.
    """
    try:
        parts = urllib.parse.urlparse(url)
    except Exception:
        return
    host = (parts.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if host == "youtu.be":
        vid = parts.path.lstrip("/").split("/")[0]
        if not _YT_ID_RE.fullmatch(vid or ""):
            raise TranscribeError(
                f"YouTube id is not exactly 11 characters ({vid!r}); "
                "refusing to transcribe a truncated or junk id"
            )
        return
    if host != "youtube.com" and not host.endswith(".youtube.com"):
        return
    qs = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
    if "v" in qs:
        vid = qs["v"][0]
        if not _YT_ID_RE.fullmatch(vid):
            raise TranscribeError(
                f"YouTube id is not exactly 11 characters ({vid!r}); "
                "refusing to transcribe a truncated or junk id"
            )
        return
    segs = [s for s in parts.path.split("/") if s]
    if len(segs) >= 2 and segs[0] in _YT_PATH_KINDS:
        vid = segs[1]
        if not _YT_ID_RE.fullmatch(vid):
            raise TranscribeError(
                f"YouTube id is not exactly 11 characters ({vid!r}); "
                "refusing to transcribe a truncated or junk id"
            )


#: Inline cue tags such as <c>, <00:00:01.000>, </c> emitted in auto-captions.
_VTT_TAG_RE = re.compile(r"<[^>]+>")

#: Exact English tracks we ask yt-dlp for. `en.*` also matches `en-de` (and
#: other locale dumps); one 429 then aborted the whole job and dropped a good
#: `en.vtt` (F17 / Tess 2026-09-20).
_SUB_LANGS = "en,en-US,en-GB,en-orig"
_PREFERRED_SUB_LANGS = ("en", "en-us", "en-gb", "en-orig")


def _vtt_is_auto(path: Path) -> bool:
    n = path.name.lower()
    return "auto" in n or ".a." in n


def _vtt_lang_key(path: Path) -> str:
    """`vid.en.vtt` -> `en`; `vid.en-US.vtt` -> `en-us`; `vid.en-auto.vtt` -> `en-auto`."""
    name = path.name
    if name.lower().endswith(".vtt"):
        name = name[:-4]
    parts = name.split(".")
    return parts[-1].lower() if len(parts) >= 2 else name.lower()


def _choose_vtt(work_dir: Path) -> Optional[Path]:
    """Pick the best written .vtt. Manual + exact `en` beats `en-de` / auto."""
    vtts = list(work_dir.glob("*.vtt"))
    if not vtts:
        return None

    def rank(path: Path):
        lang = _vtt_lang_key(path)
        if lang in _PREFERRED_SUB_LANGS:
            pref = _PREFERRED_SUB_LANGS.index(lang)
        elif lang.startswith("en"):
            pref = 50
        else:
            pref = 90
        return (1 if _vtt_is_auto(path) else 0, pref, path.name)

    return sorted(vtts, key=rank)[0]


@dataclass
class SubtitleReport:
    """Captions from one yt-dlp pass, plus what yt-dlp said.

    ``ok`` is false when yt-dlp exits nonzero or never runs. ``note`` is the
    combined stderr and stdout, so a caller can tell "this post has no video"
    from "this video has no captions".
    """

    text: Optional[str] = None
    note: str = ""
    ok: bool = False


def fetch_subtitles(
    url: str,
    work_dir: Path,
    *,
    config: Optional[Config] = None,
    cookies_from_browser: Optional[str] = None,
) -> Optional[str]:
    """Return a video's existing captions as plain text, or None if absent.

    Uses yt-dlp to grab English captions (manual or auto-generated) without
    downloading the video — no API key, no audio, no Whisper model. A
    nonzero yt-dlp exit is not fatal: if a `.vtt` was already written (one
    language 429'd after another succeeded), we still return that track.
    """
    return fetch_subtitle_report(
        url,
        work_dir,
        config=config,
        cookies_from_browser=cookies_from_browser,
    ).text


def fetch_subtitle_report(
    url: str,
    work_dir: Path,
    *,
    config: Optional[Config] = None,
    cookies_from_browser: Optional[str] = None,
) -> SubtitleReport:
    """Same pass as ``fetch_subtitles``, with the yt-dlp note kept."""
    if not ytdlp_available():
        return SubtitleReport(note="yt-dlp is not installed")

    template = work_dir / "%(id)s"
    cookie_args = cookies_from_browser_args(cookies_from_browser)
    note = ""
    ok = False
    try:
        note = _run(
            [
                *_ytdlp_cmd(),
                *cookie_args,
                "--ignore-errors",
                "--write-sub",
                "--write-auto-sub",
                "--sub-lang",
                _SUB_LANGS,
                "--sub-format",
                "vtt",
                "--skip-download",
                "--no-playlist",
                "-o",
                str(template),
                url,
            ],
            timeout=120,
        ) or ""
        ok = True
    except TranscribeError as e:
        # Private / no subs / one lang 429'd. Fall through and salvage any .vtt.
        note = getattr(e, "output", "") or str(e)

    chosen = _choose_vtt(work_dir)
    if chosen is None:
        return SubtitleReport(note=note, ok=ok)

    try:
        raw = chosen.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return SubtitleReport(note=note, ok=ok)

    text = _vtt_to_text(raw)
    return SubtitleReport(text=text or None, note=note, ok=ok)


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
    ffmpeg = _ffmpeg()
    dst = out_dir / "compressed.m4a"
    _run(
        [
            ffmpeg,
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
    ffmpeg = _ffmpeg()
    pattern = out_dir / "chunk_%03d.m4a"
    _run(
        [
            ffmpeg,
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

    local = local_available()
    if not providers and not local:
        return ""

    from searchts.utils.ffmpeg import ffmpeg_exe

    has_ffmpeg = bool(ffmpeg_exe())

    # Subtitles-first needs no ffmpeg; audio transcription (hosted OR local)
    # does. If a backend is configured but ffmpeg is missing, captions still
    # work — say so without claiming audio transcription is ready.
    if not has_ffmpeg:
        return " (captions work; audio transcription requires ffmpeg)"

    parts = []
    if providers:
        parts.append(f"can transcribe audio ({'->'.join(providers)})")
    if local:
        parts.append(f"local Whisper available (no key needed): {local_status(config)}")
    return ", " + ", ".join(parts)


def local_status(config: Optional[Config] = None) -> str:
    """One line for doctor: engine, model and whether it is cached, device."""
    engine = local_engine()
    if engine != "whisper.cpp":
        return "faster-whisper fallback" if engine else "no local engine"
    from searchts import whispercpp

    try:
        spec = whispercpp.resolve_model(None, config)
    except whispercpp.WhisperCppError as e:
        return f"whisper.cpp; {e}"
    cached = (
        "model cached" if whispercpp.model_cached(spec)
        else f"model downloads on first use after a yes, {whispercpp.format_bytes(spec.size_bytes)}"
    )
    return f"whisper.cpp {spec.name}, {cached}, device {whispercpp.device()}"


def transcribe_chunk(
    chunk: Path,
    provider: str,
    *,
    config: Optional[Config] = None,
    timeout: int = 120,
    model: Optional[str] = None,
    hint: Optional[str] = None,
    translate: bool = False,
    yes: bool = False,
) -> str:
    """Transcribe one chunk via the named provider. Raises TranscribeError on failure."""
    text, _meta = transcribe_chunk_detailed(
        chunk, provider, config=config, timeout=timeout, model=model,
        hint=hint, translate=translate, yes=yes,
    )
    return text


def transcribe_chunk_detailed(
    chunk: Path,
    provider: str,
    *,
    config: Optional[Config] = None,
    timeout: int = 120,
    model: Optional[str] = None,
    hint: Optional[str] = None,
    translate: bool = False,
    yes: bool = False,
) -> tuple:
    """(text, receipt fields) for one chunk via the named provider."""
    if provider in (LOCAL_PROVIDER, FASTER_WHISPER_PROVIDER):
        engine = "faster-whisper" if provider == FASTER_WHISPER_PROVIDER else local_engine()
        if engine == "whisper.cpp":
            got = transcribe_chunk_whispercpp(
                chunk, config=config, model=model, hint=hint,
                translate=translate, yes=yes,
            )
            return got.text, {
                "provider": LOCAL_PROVIDER, "engine": got.engine, "model": got.model,
                "device": got.device, "language": got.language,
            }
        if translate:
            raise TranscribeError("--translate needs the whisper.cpp engine")
        text = transcribe_chunk_faster_whisper(chunk, config=config, hint=hint)
        return text, {
            "provider": LOCAL_PROVIDER, "engine": "faster-whisper",
            "model": _local_model_size(config), "device": "cpu", "language": None,
        }
    if translate:
        raise TranscribeError(
            "--translate runs on the local engine; use --provider local (or auto without a hosted key)"
        )
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
    return resp.text, {
        "provider": provider, "engine": info["model"], "model": info["model"],
        "device": None, "language": None,
    }


def _provider_order(provider: str, config: Optional[Config] = None) -> List[str]:
    """Resolve `provider` into an ordered list of backends to try.

    `auto` prefers a hosted provider when its key is configured (groq, then
    openai — both faster than local CPU inference) and otherwise falls back to
    the keyless local backend (whisper.cpp, else the faster-whisper fallback).
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
    if provider in (LOCAL_PROVIDER, FASTER_WHISPER_PROVIDER):
        return [provider]
    if provider in PROVIDERS:
        return [provider]
    raise TranscribeError(
        f"unknown provider: {provider} (use auto|groq|openai|local|local-fw)"
    )


def transcribe(
    source: str,
    *,
    provider: str = "auto",
    out_dir: Optional[Path] = None,
    config: Optional[Config] = None,
    prefer_subtitles: bool = True,
    progress: Optional[bool] = None,
    cookies_from_browser: Optional[str] = None,
    model: Optional[str] = None,
    hint: Optional[str] = None,
    translate: bool = False,
    yes: bool = False,
) -> str:
    """Transcribe a URL or local file path. Returns the joined transcript text.

    :func:`transcribe_result` takes the same arguments and also returns the
    receipt: which source, engine, model and device ran, and the language.

    Subtitles-first: for a URL (not a local file) and when `prefer_subtitles`
    is set, the video's EXISTING captions are fetched via yt-dlp and returned
    directly — no API key, no audio download, no Whisper model. Only when there
    are no usable subtitles does it fall back to the audio -> Whisper pipeline,
    and ONLY then is a transcription backend required.

    `provider` is one of `auto`, `groq`, `openai`, `local`, or `local-fw`.
    `auto` prefers a configured hosted key (groq -> openai) and otherwise uses
    the keyless `local` backend: whisper.cpp, bundled with searchts. `local`
    forces local transcription and needs no API key; `local-fw` forces the
    temporary faster-whisper fallback. Pass `prefer_subtitles=False` to skip
    captions and force audio transcription.

    Local options: `model` (small, turbo, base; default small), `hint` (words
    to bias the decoder toward, e.g. names from the page title), `translate`
    (to English; not with turbo), and `yes`, the user's approval to download a
    model that is not cached yet. Without `yes` a terminal is asked once;
    otherwise ModelDownloadNeeded says what would be fetched.

    Intermediate audio (the download, the compressed copy, and any chunks) plus
    any fetched .vtt subtitle files are written to a private temporary directory
    that is deleted automatically when transcription finishes, whether it
    succeeds or fails, so nothing is left on the user's disk. Pass `out_dir`
    only if you want to keep the intermediates; in that case the directory is
    yours to manage.
    """
    receipt = _RECEIPT.get()
    return _transcribe(
        source, {} if receipt is None else receipt, provider=provider,
        out_dir=out_dir, config=config, prefer_subtitles=prefer_subtitles,
        progress=progress, cookies_from_browser=cookies_from_browser,
        model=model, hint=hint, translate=translate, yes=yes,
    )


#: Where the running transcribe() writes its receipt for transcribe_result().
_RECEIPT: "contextvars.ContextVar[Optional[dict]]" = contextvars.ContextVar(
    "searchts_transcribe_receipt", default=None
)


def transcribe_result(source: str, **kwargs: Any) -> TranscribeResult:
    """:func:`transcribe`, plus the receipt (source, engine, model, device, language).

    Goes through the module's ``transcribe`` so there is one entry point;
    the local options are passed only when set.
    """
    for key in ("model", "hint", "translate", "yes"):
        if not kwargs.get(key):
            kwargs.pop(key, None)
    receipt: dict = {}
    token = _RECEIPT.set(receipt)
    try:
        text = transcribe(source, **kwargs)
    finally:
        _RECEIPT.reset(token)
    return TranscribeResult(
        text=text,
        source=receipt.get("source", "audio"),
        provider=receipt.get("provider"),
        engine=receipt.get("engine"),
        model=receipt.get("model"),
        device=receipt.get("device"),
        language=receipt.get("language"),
        translated=bool(kwargs.get("translate")),
    )


def _transcribe(
    source: str,
    receipt: dict,
    *,
    provider: str = "auto",
    out_dir: Optional[Path] = None,
    config: Optional[Config] = None,
    prefer_subtitles: bool = True,
    progress: Optional[bool] = None,
    cookies_from_browser: Optional[str] = None,
    model: Optional[str] = None,
    hint: Optional[str] = None,
    translate: bool = False,
    yes: bool = False,
) -> str:
    cfg = config or Config()
    local: Dict[str, Any] = {"model": model, "hint": hint, "translate": translate,
                             "yes": yes, "receipt": receipt}

    if not Path(source).is_file():
        assert_youtube_id_exact(source)

    if progress is None:
        progress = os.environ.get("SEARCHTS_PROGRESS", "") in (
            "1", "true", "True", "yes",
        )

    if cookies_from_browser:
        # Validate before any "using cookies" line and before subtitle fallback
        # swallows TranscribeError (unknown browser must fail loud).
        cookies_from_browser_args(cookies_from_browser)
        print(
            f"searchts transcribe: cookies from {cookies_from_browser} "
            "(opt-in; not used by read)",
            file=sys.stderr,
            flush=True,
        )

    if out_dir is not None:
        # Caller-owned directory: use it as-is and leave the files in place.
        work_dir = Path(out_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        return _run_transcription(
            source, work_dir, provider, cfg, prefer_subtitles, progress,
            cookies_from_browser=cookies_from_browser, **local,
        )

    # Default: an ephemeral workspace removed on exit (even on exception), so a
    # downloaded video/audio (and any fetched .vtt) never lingers on disk.
    # ignore_cleanup_errors guards the classic Windows case where an antivirus
    # scan or a slow-to-release handle briefly locks a file: worst case a stray
    # temp file waits for the OS to reap it, instead of a lock turning a finished
    # transcription into a crash.
    with tempfile.TemporaryDirectory(
        prefix="searchts-transcribe-", ignore_cleanup_errors=True
    ) as tmp:
        return _run_transcription(
            source, Path(tmp), provider, cfg, prefer_subtitles, progress,
            cookies_from_browser=cookies_from_browser, **local,
        )


def _validate_backend(order: List[str], cfg: Config) -> None:
    """Raise NoProviderConfigured if no backend in `order` can transcribe audio.

    Local needs no key, just an importable faster-whisper; hosted providers
    need their configured key. Only called on the audio fallback path, never
    when subtitles already satisfied the request.
    """
    usable = any(
        local_available() if p == LOCAL_PROVIDER
        else faster_whisper_available() if p == FASTER_WHISPER_PROVIDER
        else bool(_provider_key(p, cfg))
        for p in order
    )
    if not usable:
        if order == [FASTER_WHISPER_PROVIDER]:
            raise NoProviderConfigured(
                "no transcription backend available for --provider local-fw: "
                f"{faster_whisper_unavailable_reason()}\nUse --provider local "
                "(whisper.cpp, bundled) instead."
            )
        local_hint = local_unavailable_reason() or (
            "reinstall searchts to restore its bundled whisper.cpp"
        )
        hosted_order = [p for p in order if p in PROVIDERS]
        if not hosted_order:
            # --provider local: there is no hosted key to name, so say how to
            # get local working, then how to switch to a hosted provider.
            keys = ", ".join(PROVIDERS[p]["key_field"] for p in PROVIDERS)
            raise NoProviderConfigured(
                f"no transcription backend available for --provider local: "
                f"{local_hint}\nOr configure a hosted key "
                f"(one of: {keys}) and use --provider auto."
            )
        hosted = ", ".join(PROVIDERS[p]["key_field"] for p in hosted_order)
        raise NoProviderConfigured(
            f"no transcription backend available: configure a hosted key "
            f"(one of: {hosted}), or use keyless local transcription. {local_hint}"
        )


def _run_transcription(
    source: str,
    work_dir: Path,
    provider: str,
    cfg: Config,
    prefer_subtitles: bool,
    progress: bool = False,
    cookies_from_browser: Optional[str] = None,
    model: Optional[str] = None,
    hint: Optional[str] = None,
    translate: bool = False,
    yes: bool = False,
    receipt: Optional[dict] = None,
) -> str:
    """Try subtitles first (URL only), else download audio and transcribe.

    A captioned URL returns here with NO provider validation, NO audio download,
    and NO key required. Provider validation and the audio -> Whisper pipeline
    run only on the fallback path.
    """
    src_path = Path(source)
    is_local_file = src_path.is_file()

    receipt = {} if receipt is None else receipt
    if translate:
        # Captions are in the video's language; translation needs the audio.
        prefer_subtitles = False
    if not is_local_file and prefer_subtitles:
        sub_kw = {}
        if cookies_from_browser:
            sub_kw["cookies_from_browser"] = cookies_from_browser
        with progress_phase("fetching subtitles…", enabled=bool(progress)):
            subs = fetch_subtitles(source, work_dir, config=cfg, **sub_kw)
        if subs and len(subs.replace(" ", "")) >= MIN_SUBTITLE_CHARS:
            receipt.update(source="subtitles", provider=None, engine="captions")
            return subs

    # Fallback: audio -> Whisper. Resolve provider order and require a usable
    # backend now — a captioned URL never reaches this point.
    if translate and provider == "auto":
        order = [LOCAL_PROVIDER]  # hosted APIs here only transcribe
    else:
        order = _provider_order(provider, cfg)
    _validate_backend(order, cfg)
    # Ask for the model before downloading any audio: a "no" costs nothing.
    _preflight_local(
        order, cfg, model=model, yes=yes, progress=bool(progress), translate=translate
    )

    if is_local_file:
        audio = src_path  # a local file the caller owns; never deleted by us
    else:
        dl_kw = {}
        if cookies_from_browser:
            dl_kw["cookies_from_browser"] = cookies_from_browser
        with progress_phase("downloading audio…", enabled=bool(progress)):
            audio = download_audio(source, work_dir, **dl_kw)

    with progress_phase("preparing audio…", enabled=bool(progress)):
        if _uses_local_pcm(order):
            # Local engines decode to an in-memory float32 array. Always split
            # before that decode so PCM stays near 38 MB per 10-minute chunk.
            chunks = chunk_audio(audio, work_dir)
        else:
            compressed = compress_audio(audio, work_dir)
            if compressed.stat().st_size <= SIZE_LIMIT_BYTES:
                chunks = [compressed]
            else:
                chunks = chunk_audio(compressed, work_dir)

    pieces: List[str] = []
    many = len(chunks) > 1
    with progress_phase("transcribing…", enabled=bool(progress)) as spoken:
        for i, chunk in enumerate(chunks, start=1):
            if many:
                spoken.update("transcribing…", done=i, total=len(chunks))
            text = _transcribe_with_fallback(
                chunk, order, cfg, model=model, hint=hint, translate=translate,
                yes=True if _local_first(order) else yes, receipt=receipt,
            )
            pieces.append(text.strip())
    joined = "\n".join(p for p in pieces if p)
    if not joined.strip():
        raise TranscribeError("empty transcript")
    receipt["source"] = "audio"
    return joined


def _local_first(order: List[str]) -> bool:
    return bool(order) and order[0] == LOCAL_PROVIDER and local_engine() == "whisper.cpp"


def _uses_local_pcm(order: List[str]) -> bool:
    """Whether this provider path decodes audio to local float32 samples."""
    return any(provider in (LOCAL_PROVIDER, FASTER_WHISPER_PROVIDER) for provider in order)


def _preflight_local(
    order: List[str], cfg: Config, *, model: Optional[str], yes: bool, progress: bool,
    translate: bool = False,
) -> None:
    """When whisper.cpp will run, have its model (approved) before any audio work."""
    if _local_first(order):
        prepare_local_model(
            model, config=cfg, yes=yes, progress=progress, translate=translate
        )


def _transcribe_with_fallback(
    chunk: Path,
    order: List[str],
    config: Config,
    *,
    model: Optional[str] = None,
    hint: Optional[str] = None,
    translate: bool = False,
    yes: bool = False,
    receipt: Optional[dict] = None,
) -> str:
    """Try each provider in order; return first success or raise the last error.

    A model download that still needs a yes is not a provider failure: it is
    raised at once, never papered over by another backend.
    """
    last_err: Optional[Exception] = None
    for p in order:
        # Local needs no key; hosted providers without a configured key are
        # skipped silently — caller already validated at least one is usable.
        if p not in (LOCAL_PROVIDER, FASTER_WHISPER_PROVIDER) and not _provider_key(p, config):
            continue
        try:
            text, meta = transcribe_chunk_detailed(
                chunk, p, config=config, model=model, hint=hint,
                translate=translate, yes=yes,
            )
        except ModelDownloadNeeded:
            raise
        except TranscribeError as e:
            last_err = e
            continue
        if receipt is not None:
            receipt.update(meta)
        return text
    raise TranscribeError(f"all providers failed for {chunk.name}: {last_err}")
