# -*- coding: utf-8 -*-
"""whisper.cpp, the keyless local transcription engine (#439).

The engine ships in the base install as the ``pywhispercpp`` wheel, which
bundles the native whisper.cpp library per OS/arch. Only the model file is
fetched, once, after the user approves it: what, from where, and how big are
said first, and nothing is downloaded silently. A cached model needs no network.

The Linux and Windows PyPI wheels are CPU builds. The macOS arm64 wheel
ships the Metal backend (an embedded metallib), so an Apple Silicon wheel
install can run on the GPU; this machine drives Linux, so metal receipts
stay unproven here. Locally built bindings can enable Metal, Vulkan or CUDA,
and runtime detection uses those backends when present. GPU model
initialization falls back to CPU.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

#: Pinned to a whisper.cpp model repo revision so the bytes behind a checksum
#: cannot change under us.
_HF_REPO = (
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/"
    "5359861c739e955e79d9a303bcbc70fb988958b1"
)


@dataclass(frozen=True)
class ModelSpec:
    name: str
    filename: str
    size_bytes: int
    sha256: str
    translates: bool
    blurb: str

    @property
    def url(self) -> str:
        return f"{_HF_REPO}/{self.filename}"


#: Sizes and SHA-256 from the Hugging Face LFS metadata of each file.
MODELS: Dict[str, ModelSpec] = {
    "small": ModelSpec(
        "small", "ggml-small-q5_1.bin", 190_085_487,
        "ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb",
        True, "the default: quantized q5_1, mostly right",
    ),
    "turbo": ModelSpec(
        "turbo", "ggml-large-v3-turbo-q5_0.bin", 574_041_195,
        "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2",
        False, "large-v3-turbo: most accurate, slowest on CPU, no --translate",
    ),
    "base": ModelSpec(
        "base", "ggml-base-q5_1.bin", 59_707_625,
        "422f1ae452ade6f30a004d7e5c6a43195e4433bc370bf23fac9cc591f01a8898",
        True, "fastest, mishears more",
    ),
}

DEFAULT_MODEL = "small"
MODEL_CHOICES = tuple(MODELS)


class WhisperCppError(RuntimeError):
    """whisper.cpp could not load or run."""


class ModelConsentNeeded(WhisperCppError):
    """The model is not cached and nobody approved the download yet."""

    def __init__(self, spec: ModelSpec, path: Path):
        self.spec = spec
        self.path = path
        super().__init__(
            f"local transcription needs the whisper.cpp model '{spec.name}' "
            f"({spec.filename}, {format_bytes(spec.size_bytes)}), not downloaded yet. "
            f"It comes from {spec.url} and is saved to {path}. "
            "Ask the user, then re-run with --yes (MCP: yes=true) to download it "
            "once; later runs use the cached file offline."
        )


def model_dir() -> Path:
    """Where models are cached: ``~/.searchts/models`` (``SEARCHTS_MODEL_DIR`` overrides)."""
    override = os.environ.get("SEARCHTS_MODEL_DIR")
    if override:
        return Path(override).expanduser()
    from searchts.config import Config

    return Path(Config.CONFIG_DIR) / "models"


def resolve_model(name: Optional[str], config: Any = None) -> ModelSpec:
    """--model, then config ``whisper_model``, then ``SEARCHTS_WHISPER_MODEL``, then small."""
    chosen = name
    if not chosen and config is not None:
        try:
            chosen = config.get("whisper_model")
        except Exception:  # noqa: BLE001 - a broken config must not block transcribe
            chosen = None
    chosen = (chosen or os.environ.get("SEARCHTS_WHISPER_MODEL") or DEFAULT_MODEL).strip().lower()
    if chosen in ("large-v3-turbo", "large-turbo"):
        chosen = "turbo"
    if chosen not in MODELS:
        raise WhisperCppError(
            f"unknown whisper.cpp model '{chosen}'; choose one of: {', '.join(MODELS)} "
            "(--model, config whisper_model, or SEARCHTS_WHISPER_MODEL)"
        )
    return MODELS[chosen]


def model_path(spec: ModelSpec) -> Path:
    return model_dir() / spec.filename


def format_bytes(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1000 or unit == "GB":
            return f"{size:.0f} {unit}" if unit != "GB" else f"{size:.1f} {unit}"
        size /= 1000
    return f"{size:.1f} GB"


def model_cached(spec: ModelSpec) -> bool:
    """A cached model has the expected size and SHA-256."""
    path = model_path(spec)
    try:
        return (
            path.is_file()
            and path.stat().st_size == spec.size_bytes
            and _sha256(path) == spec.sha256
        )
    except OSError:
        return False


def model_status() -> List[dict]:
    """Every known model: name, size, cached or not, path. For doctor and --json."""
    return [
        {
            "name": spec.name,
            "file": spec.filename,
            "size_bytes": spec.size_bytes,
            "size": format_bytes(spec.size_bytes),
            "cached": model_cached(spec),
            "path": str(model_path(spec)),
            "translates": spec.translates,
        }
        for spec in MODELS.values()
    ]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


Opener = Callable[[urllib.request.Request], Any]


def download_model(
    spec: ModelSpec,
    *,
    progress: Optional[Callable[[int, int], None]] = None,
    opener: Optional[Opener] = None,
    retries: int = 2,
) -> Path:
    """Download ``spec`` to the cache: resumable ``.part`` file, SHA-256 checked,
    then renamed into place. Only call after the user approved it."""
    dest = model_path(spec)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    open_url = opener or (lambda req: urllib.request.urlopen(req, timeout=60))
    last: Optional[Exception] = None
    for _attempt in range(retries + 1):
        have = part.stat().st_size if part.exists() else 0
        if have > spec.size_bytes:
            part.unlink()
            have = 0
        headers = {"User-Agent": "searchts (whisper.cpp model)"}
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            if have < spec.size_bytes:
                with open_url(urllib.request.Request(spec.url, headers=headers)) as resp:
                    status = getattr(resp, "status", 200)
                    mode = "ab" if have and status == 206 else "wb"
                    done = have if mode == "ab" else 0
                    with part.open(mode) as fh:
                        while True:
                            block = resp.read(1 << 20)
                            if not block:
                                break
                            fh.write(block)
                            done += len(block)
                            if progress:
                                progress(done, spec.size_bytes)
            if part.stat().st_size != spec.size_bytes:
                raise WhisperCppError(
                    f"download of {spec.filename} stopped at "
                    f"{format_bytes(part.stat().st_size)} of {format_bytes(spec.size_bytes)}"
                )
            if _sha256(part) != spec.sha256:
                part.unlink()
                raise WhisperCppError(
                    f"{spec.filename} failed its SHA-256 check and was deleted; "
                    "nothing was kept. Try again."
                )
            os.replace(part, dest)
            return dest
        except (urllib.error.URLError, OSError, WhisperCppError) as e:
            last = e
            if isinstance(e, WhisperCppError) and "SHA-256" in str(e):
                break
    raise WhisperCppError(f"could not download {spec.filename} from {spec.url}: {last}")


def ask_tty(spec: ModelSpec) -> bool:
    """One question on a terminal: download this model now?"""
    if not (sys.stdin and sys.stdin.isatty() and sys.stderr and sys.stderr.isatty()):
        return False
    print(
        f"Local transcription needs the whisper.cpp model '{spec.name}' "
        f"({spec.filename}, {format_bytes(spec.size_bytes)}).\n"
        f"  from: {spec.url}\n"
        f"  to:   {model_path(spec)}\n"
        "  One-time download; later runs work offline. Switch models with "
        "--model turbo|small|base, config whisper_model, or SEARCHTS_WHISPER_MODEL.",
        file=sys.stderr,
        flush=True,
    )
    try:
        answer = input("Download it now? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("y", "yes")


def ensure_model(
    spec: ModelSpec,
    *,
    yes: bool = False,
    ask: Optional[Callable[[ModelSpec], bool]] = None,
    progress: Optional[Callable[[int, int], None]] = None,
) -> Path:
    """The cached model path, downloading it only with approval.

    ``yes`` is the approval (CLI ``--yes``, MCP ``yes=true``, or the install
    list). ``ask`` may get it interactively (the CLI passes :func:`ask_tty`
    outside its live display). Otherwise :class:`ModelConsentNeeded` says what
    would be fetched and how to approve.
    """
    if model_cached(spec):
        return model_path(spec)
    approved = yes or (ask(spec) if ask else False)
    if not approved:
        raise ModelConsentNeeded(spec, model_path(spec))
    return download_model(spec, progress=progress)


def remove_model(spec: ModelSpec) -> List[str]:
    """Remove this searchts-owned model and any interrupted partial download."""
    removed = []
    for path in (
        model_path(spec),
        model_path(spec).with_name(spec.filename + ".part"),
    ):
        try:
            path.unlink()
            removed.append(str(path))
        except FileNotFoundError:
            pass
    return removed


# ── the engine ─────────────────────────────────────────────────────────────


def _import_binding():
    # importlib, not import statements: the binding's stubs pull numpy's,
    # which need a newer Python than the one mypy checks against.
    import importlib

    try:
        pw = importlib.import_module("_pywhispercpp")
        Model = importlib.import_module("pywhispercpp.model").Model
    except ImportError as e:
        raise WhisperCppError(
            "local transcription needs pywhispercpp (whisper.cpp), which ships "
            f"with searchts, but importing it failed in {sys.executable}: {e}. "
            "Reinstall searchts (`searchts update`) to restore it."
        ) from e
    return pw, Model


def unavailable_reason() -> str:
    try:
        _import_binding()
    except WhisperCppError as e:
        return str(e)
    return ""


def available() -> bool:
    return not unavailable_reason()


def binding_version() -> str:
    try:
        from importlib.metadata import version

        return version("pywhispercpp")
    except Exception:  # noqa: BLE001
        return ""


_GPU_MARKERS = (("metal", re.compile(r"\b(metal|mtl)\b", re.I)),
                ("cuda", re.compile(r"\bcuda\b", re.I)),
                ("vulkan", re.compile(r"\bvulkan\b", re.I)))


def device(system_info: Optional[str] = None) -> str:
    """The backend whisper.cpp runs on here: metal, cuda, vulkan, or cpu.

    Read from the library's own build report, so it names what this install
    can use. whisper.cpp turns a built-in GPU backend on by default.
    """
    if system_info is None:
        try:
            pw, _ = _import_binding()
            system_info = str(pw.whisper_print_system_info())
        except Exception:  # noqa: BLE001
            return "cpu"
    for name, pattern in _GPU_MARKERS:
        for match in pattern.finditer(system_info):
            tail = system_info[match.end():match.end() + 12]
            if "= 0" in tail.split("|")[0]:
                continue
            return name
    return "cpu"


_MODEL_CACHE: Dict[str, Any] = {}
_DEVICE_CACHE: Dict[str, str] = {}

#: whisper.cpp's native log lines ("whisper_lang_id: unknown language 'auto'")
#: are fd-2 output from its C code. They are intercepted with the library's own
#: log callback (``whisper_log_set``), not by redirecting fd 2: a redirect also
#: swallows searchts's own progress ticks, which can be written from another
#: thread while a chunk is transcribing (#486, #452 follow-up). Off by default;
#: ``-v`` / debug logging turns them back on.
_SHOW_NATIVE_LOGS = False

#: The callback object must outlive the C pointer handed to whisper_log_set.
_NATIVE_LOG_CALLBACK: Optional[Callable[..., None]] = None
_NATIVE_LOG_SINK_INSTALLED = False


def show_native_logs(enabled: bool) -> None:
    """The CLI wiring for native whisper.cpp log output: on with ``-v``, else off."""
    global _SHOW_NATIVE_LOGS
    _SHOW_NATIVE_LOGS = bool(enabled)
    if enabled:
        _install_native_log_sink()


def _native_log(level: Any, text: Any, *_rest: Any) -> None:
    """One whisper.cpp log line: plain stderr with ``-v``, nowhere otherwise."""
    if not _SHOW_NATIVE_LOGS:
        return
    try:
        line = str(text)
    except Exception:  # noqa: BLE001 - a native callback never raises
        return
    if not line:
        return
    stream = sys.stderr
    if stream is None:
        return
    try:
        stream.write(line if line.endswith("\n") else line + "\n")
        stream.flush()
    except Exception:  # noqa: BLE001 - a closed stderr must never abort a run
        pass


def _install_native_log_sink() -> bool:
    """Point whisper.cpp's logger at :func:`_native_log`, once per process.

    True when the callback is in place, so callers know they must not fall back
    to the fd-2 redirect. False on a pywhispercpp too old to expose the setter.
    """
    global _NATIVE_LOG_CALLBACK, _NATIVE_LOG_SINK_INSTALLED
    if _NATIVE_LOG_SINK_INSTALLED:
        return True
    try:
        pw, _ = _import_binding()
        setter = getattr(pw, "whisper_log_set", None)
        if setter is None:
            return False

        def callback(*args: Any) -> None:
            _native_log(*args)

        setter(callback)
        _NATIVE_LOG_CALLBACK = callback
        _NATIVE_LOG_SINK_INSTALLED = True
        return True
    except Exception:  # noqa: BLE001 - fall back to the old redirect below
        return False


def _quiet_stderr():
    """Keep whisper.cpp's native logs off stderr, and nothing else.

    With the log callback installed (the normal case) nothing is redirected:
    the callback drops whisper.cpp's own lines while every other writer to fd 2
    keeps its voice. With ``-v`` the callback forwards them. The old fd-2
    redirect remains only for a pywhispercpp without the callback API, and is
    skipped when the user asked to see the native lines.
    """
    from contextlib import nullcontext

    if _install_native_log_sink() or _SHOW_NATIVE_LOGS:
        return nullcontext()
    from pywhispercpp.utils import redirect_stderr

    return redirect_stderr(to=None)


def _load(path: Path) -> Any:
    key = str(path)
    if key not in _MODEL_CACHE:
        pw, Model = _import_binding()
        # With our log callback in place, initialization logs are filtered at
        # the source; there is no fd-2 redirect to make (which would also mute
        # another thread's progress tick). Without it, keep #486's redirect.
        quiet_to = False if _install_native_log_sink() or _SHOW_NATIVE_LOGS else None
        backend = device(str(pw.whisper_print_system_info()))
        context_params = {"use_gpu": backend != "cpu"}
        try:
            model = Model(
                key,
                redirect_whispercpp_logs_to=quiet_to,
                print_progress=False,
                print_realtime=False,
                context_params=context_params,
            )
            if model._ctx is None:
                raise WhisperCppError("GPU model initialization returned no context")
        except Exception as e:
            if backend == "cpu":
                raise WhisperCppError(f"whisper.cpp model initialization failed: {e}") from e
            try:
                model = Model(
                    key,
                    redirect_whispercpp_logs_to=quiet_to,
                    print_progress=False,
                    print_realtime=False,
                    context_params={"use_gpu": False},
                )
                if model._ctx is None:
                    raise WhisperCppError("CPU model initialization returned no context")
            except Exception as cpu_error:
                raise WhisperCppError(
                    f"whisper.cpp GPU initialization failed ({e}); CPU fallback "
                    f"also failed ({cpu_error})"
                ) from cpu_error
            backend = "cpu"
        _MODEL_CACHE[key] = model
        _DEVICE_CACHE[key] = backend
    return _MODEL_CACHE[key]


@dataclass
class Transcript:
    text: str
    language: str
    model: str
    device: str
    engine: str = "whisper.cpp"


def transcribe_samples(
    samples: Any,
    spec: ModelSpec,
    path: Path,
    *,
    hint: Optional[str] = None,
    translate: bool = False,
    language: Optional[str] = None,
) -> Transcript:
    """Transcribe 16 kHz mono float32 samples. Language is auto-detected unless given."""
    if translate and not spec.translates:
        raise WhisperCppError(
            f"the '{spec.name}' model was not trained to translate; use "
            "--model small (or base) with --translate"
        )
    pw, _ = _import_binding()
    model = _load(path)
    try:
        with _quiet_stderr():
            # Set every per-call param: pywhispercpp keeps overrides across calls.
            segments = model.transcribe(
                samples,
                language=language or "auto",
                translate=bool(translate),
                initial_prompt=hint or "",
            )
            detected = language or ""
            if not detected:
                try:
                    detected = str(pw.whisper_lang_str(
                        pw.whisper_full_lang_id(model._ctx)
                    ))
                except Exception:  # noqa: BLE001
                    detected = ""
    except Exception as e:  # noqa: BLE001 - surface any native failure as ours
        raise WhisperCppError(f"whisper.cpp failed: {e}") from e
    text = "".join(getattr(s, "text", "") for s in segments).strip()
    return Transcript(
        text=text,
        language=detected or "unknown",
        model=spec.name,
        device=_DEVICE_CACHE.get(str(path), device()),
    )
