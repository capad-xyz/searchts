"""#439: whisper.cpp as the local engine. No test downloads or runs a model."""
import hashlib
import io
import json
import sys
import types
from unittest.mock import patch

import pytest

import searchts.transcribe as tr
from searchts import whispercpp
from searchts.config import Config


@pytest.fixture
def fake_config(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.yaml"
    monkeypatch.setattr(Config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(Config, "CONFIG_FILE", cfg_path)
    return Config(config_path=cfg_path)


@pytest.fixture
def chunk_file(tmp_path):
    p = tmp_path / "chunk.m4a"
    p.write_bytes(b"\x00fake-m4a-bytes")
    return p


def _spec(data: bytes, name="tiny-test"):
    return whispercpp.ModelSpec(
        name, f"ggml-{name}.bin", len(data), hashlib.sha256(data).hexdigest(), True, "test",
    )


class _Resp(io.BytesIO):
    def __init__(self, data, status=200):
        super().__init__(data)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# ── models and consent ─────────────────────────────────────────────────────


def test_default_model_is_small_and_turbo_and_base_are_selectable(monkeypatch):
    assert whispercpp.resolve_model(None).name == "small"
    assert whispercpp.resolve_model("small").filename == "ggml-small-q5_1.bin"
    assert whispercpp.resolve_model("turbo").filename == "ggml-large-v3-turbo-q5_0.bin"
    assert whispercpp.resolve_model("large-v3-turbo").name == "turbo"
    monkeypatch.setenv("SEARCHTS_WHISPER_MODEL", "base")
    assert whispercpp.resolve_model(None).name == "base"
    # The flag beats the env var.
    assert whispercpp.resolve_model("turbo").name == "turbo"
    with pytest.raises(whispercpp.WhisperCppError, match="small, turbo, base"):
        whispercpp.resolve_model("medium")


def test_config_whisper_model_is_honoured(fake_config):
    fake_config.set("whisper_model", "turbo")
    assert whispercpp.resolve_model(None, fake_config).name == "turbo"


def test_models_carry_real_sizes_and_checksums():
    for spec in whispercpp.MODELS.values():
        assert len(spec.sha256) == 64 and int(spec.sha256, 16)
        assert spec.size_bytes > 50_000_000
        assert spec.url.startswith("https://huggingface.co/ggerganov/whisper.cpp/resolve/")
        assert "/resolve/main/" not in spec.url  # pinned revision
    assert whispercpp.MODELS["turbo"].translates is False


def test_missing_model_without_yes_raises_and_downloads_nothing(monkeypatch):
    spec = whispercpp.MODELS["small"]

    def no_download(*a, **k):
        raise AssertionError("must not download without approval")

    monkeypatch.setattr(whispercpp, "download_model", no_download)
    with pytest.raises(whispercpp.ModelConsentNeeded) as ei:
        whispercpp.ensure_model(spec)
    message = str(ei.value)
    assert "190 MB" in message and spec.url in message
    assert "--yes" in message and "yes=true" in message
    # A "no" at the terminal is the same answer.
    with pytest.raises(whispercpp.ModelConsentNeeded):
        whispercpp.ensure_model(spec, ask=lambda s: False)


def test_yes_or_a_terminal_yes_downloads(monkeypatch):
    spec = whispercpp.MODELS["base"]
    got = []
    monkeypatch.setattr(whispercpp, "download_model", lambda s, **k: got.append(s.name) or "p")
    whispercpp.ensure_model(spec, yes=True)
    whispercpp.ensure_model(spec, ask=lambda s: True)
    assert got == ["base", "base"]


def test_cached_model_needs_no_network_or_approval(monkeypatch):
    data = b"model-bytes" * 10
    spec = _spec(data)
    path = whispercpp.model_path(spec)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    monkeypatch.setattr(whispercpp, "download_model", lambda *a, **k: pytest.fail("network"))
    assert whispercpp.ensure_model(spec) == path


def test_cached_model_is_rechecked_against_checksum(monkeypatch):
    data = b"model-data" * 4
    spec = _spec(data)
    path = whispercpp.model_path(spec)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data[:-1] + b"x")
    assert whispercpp.model_cached(spec) is False


def test_tty_consent_shows_size_destination_and_switch_help(monkeypatch, capsys, tmp_path):
    spec = whispercpp.MODELS["small"]
    monkeypatch.setattr(whispercpp, "model_path", lambda s: tmp_path / s.filename)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stderr.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "yes")
    assert whispercpp.ask_tty(spec) is True
    err = capsys.readouterr().err
    assert "190 MB" in err and str(tmp_path / spec.filename) in err
    assert "--model turbo|small|base" in err


def test_no_tty_consent_does_not_prompt_or_download(monkeypatch):
    spec = whispercpp.MODELS["small"]
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("prompted without a TTY"))
    assert whispercpp.ask_tty(spec) is False


def test_download_verifies_sha256_and_resumes(monkeypatch):
    data = bytes(range(256)) * 40
    spec = _spec(data)
    part = whispercpp.model_path(spec).with_name(spec.filename + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(data[:1000])  # an interrupted earlier download
    seen = {}

    def opener(req):
        seen["range"] = req.headers.get("Range")
        return _Resp(data[1000:], status=206)

    path = whispercpp.download_model(spec, opener=opener)
    assert seen["range"] == "bytes=1000-"
    assert path.read_bytes() == data
    assert not part.exists()


def test_corrupt_download_is_deleted_not_kept(monkeypatch):
    data = b"a" * 500
    spec = _spec(data)
    with pytest.raises(whispercpp.WhisperCppError, match="SHA-256"):
        whispercpp.download_model(spec, opener=lambda req: _Resp(b"b" * 500))
    assert not whispercpp.model_path(spec).exists()
    assert not whispercpp.model_path(spec).with_name(spec.filename + ".part").exists()


# ── device ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("info, expected", [
    ("WHISPER : COREML = 0 | OPENVINO = 0 | CPU : SSE3 = 1 | AVX2 = 1 |", "cpu"),
    ("WHISPER : COREML = 0 | Metal : EMBED_LIBRARY = 1 | CPU : NEON = 1 |", "metal"),
    ("WHISPER : COREML = 0 | CUDA : ARCHS = 860 | CPU : AVX2 = 1 |", "cuda"),
    ("WHISPER : COREML = 0 | VULKAN = 0 | CPU : AVX2 = 1 |", "cpu"),
    ("Vulkan : 1 | CPU : AVX2 = 1 |", "vulkan"),
])
def test_device_reads_the_build_report(info, expected):
    assert whispercpp.device(info) == expected


def test_device_of_this_install_is_reported():
    assert whispercpp.device() in ("cpu", "metal", "cuda", "vulkan")


def test_gpu_model_initialization_falls_back_to_cpu(monkeypatch, tmp_path):
    calls = []

    class _Model:
        def __init__(self, path, **kwargs):
            calls.append(kwargs["context_params"]["use_gpu"])
            if kwargs["context_params"]["use_gpu"]:
                raise RuntimeError("GPU unavailable")
            self._ctx = object()

    pw = types.SimpleNamespace(whisper_print_system_info=lambda: "VULKAN = 1 | CPU = 1")
    monkeypatch.setattr(whispercpp, "_import_binding", lambda: (pw, _Model))
    whispercpp._MODEL_CACHE.clear()
    whispercpp._DEVICE_CACHE.clear()
    model = whispercpp._load(tmp_path / "model.bin")
    assert model._ctx is not None
    assert calls == [True, False]
    assert whispercpp._DEVICE_CACHE[str(tmp_path / "model.bin")] == "cpu"


# ── transcribing ───────────────────────────────────────────────────────────


class _Seg:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def __init__(self):
        self.calls = []
        self._ctx = object()

    def transcribe(self, samples, **params):
        self.calls.append(params)
        return [_Seg(" Laurentius "), _Seg("of the Great Swamp.")]


@pytest.fixture
def fake_binding(monkeypatch):
    model = _FakeModel()
    pw = types.SimpleNamespace(
        whisper_full_lang_id=lambda ctx: 3,
        whisper_lang_str=lambda i: "de",
        whisper_print_system_info=lambda: "CPU : AVX2 = 1 |",
    )
    monkeypatch.setattr(whispercpp, "_import_binding", lambda: (pw, object))
    monkeypatch.setattr(whispercpp, "_load", lambda path: model)
    return model


def test_transcribe_samples_passes_hint_and_auto_language(fake_binding, tmp_path):
    spec = whispercpp.MODELS["small"]
    got = whispercpp.transcribe_samples([0.0], spec, tmp_path / "m", hint="Laurentius")
    assert got.text == "Laurentius of the Great Swamp."
    assert got.language == "de" and got.model == "small" and got.device == "cpu"
    assert fake_binding.calls == [
        {"language": "auto", "translate": False, "initial_prompt": "Laurentius"}
    ]
    # pywhispercpp keeps overrides across calls, so every param is reset.
    whispercpp.transcribe_samples([0.0], spec, tmp_path / "m")
    assert fake_binding.calls[-1]["initial_prompt"] == ""


def test_translate_refuses_turbo(fake_binding, tmp_path):
    with pytest.raises(whispercpp.WhisperCppError, match="not trained to translate"):
        whispercpp.transcribe_samples([0.0], whispercpp.MODELS["turbo"], tmp_path, translate=True)
    whispercpp.transcribe_samples([0.0], whispercpp.MODELS["small"], tmp_path, translate=True)
    assert fake_binding.calls[-1]["translate"] is True


def test_native_whisper_logs_are_silenced_unless_verbose(
    monkeypatch, fake_binding, tmp_path
):
    """#486: whisper.cpp's C log lines stay off stderr; -v turns them back on."""
    import contextlib

    import pywhispercpp.utils as utils

    seen = []

    @contextlib.contextmanager
    def fake_redirect(to=False):
        seen.append(to)
        yield

    monkeypatch.setattr(utils, "redirect_stderr", fake_redirect)
    monkeypatch.setattr(whispercpp, "_SHOW_NATIVE_LOGS", False)
    whispercpp.transcribe_samples([0.0], whispercpp.MODELS["small"], tmp_path / "m")
    whispercpp.show_native_logs(True)
    whispercpp.transcribe_samples([0.0], whispercpp.MODELS["small"], tmp_path / "m")
    assert seen == [None, False]


def test_translate_refuses_turbo_before_model_download(monkeypatch, fake_config):
    monkeypatch.setattr(
        whispercpp, "ensure_model", lambda *a, **k: pytest.fail("downloaded unsupported model")
    )
    with pytest.raises(tr.TranscribeError, match="not trained to translate"):
        tr.prepare_local_model("turbo", config=fake_config, translate=True)


def _local_pipeline(monkeypatch, tmp_path, chunk_file):
    monkeypatch.setattr(tr, "chunk_audio", lambda src, out: [src])
    monkeypatch.setattr(tr, "_decode_chunk_ffmpeg", lambda chunk, **k: [0.0])
    monkeypatch.setattr(tr.requests, "post", lambda *a, **k: pytest.fail("no HTTP"))


def test_auto_without_a_key_runs_whispercpp_and_reports_it(
    monkeypatch, fake_binding, fake_config, tmp_path, chunk_file
):
    _local_pipeline(monkeypatch, tmp_path, chunk_file)
    monkeypatch.setattr(whispercpp, "ensure_model", lambda spec, **k: tmp_path / spec.filename)
    result = tr.transcribe_result(str(chunk_file), config=fake_config, hint="Laurentius")
    assert result.text == "Laurentius of the Great Swamp."
    assert result.receipt() == {
        "source": "audio", "provider": "local", "engine": "whisper.cpp",
        "model": "small", "device": "cpu", "language": "de", "translated": False,
    }


def test_no_approval_stops_before_any_audio_download(monkeypatch, fake_config, tmp_path):
    monkeypatch.setattr(tr, "fetch_subtitles", lambda *a, **k: "")
    monkeypatch.setattr(tr, "download_audio", lambda *a, **k: pytest.fail("audio downloaded"))
    with pytest.raises(tr.ModelDownloadNeeded) as ei:
        tr.transcribe("https://example.com/v.mp4", config=fake_config, out_dir=tmp_path)
    assert ei.value.model["name"] == "small"
    assert ei.value.model["size_bytes"] == 190_085_487


def test_model_approval_is_not_papered_over_by_another_backend(monkeypatch, fake_config, chunk_file):
    def needs(*a, **k):
        raise tr.ModelDownloadNeeded("needs a yes", {"name": "small"})

    monkeypatch.setattr(tr, "transcribe_chunk_detailed", needs)
    with pytest.raises(tr.ModelDownloadNeeded):
        tr._transcribe_with_fallback(chunk_file, ["local", "groq"], fake_config)


def test_captions_receipt_names_no_engine(monkeypatch, fake_config, tmp_path):
    monkeypatch.setattr(tr, "fetch_subtitles", lambda *a, **k: "caption text " * 5)
    result = tr.transcribe_result("https://example.com/v", config=fake_config, out_dir=tmp_path)
    assert result.source == "subtitles" and result.device is None


def test_local_fw_forces_the_fallback(monkeypatch, fake_config, chunk_file):
    monkeypatch.setattr(tr, "transcribe_chunk_faster_whisper", lambda c, **k: "fw text")
    text, meta = tr.transcribe_chunk_detailed(chunk_file, "local-fw", config=fake_config)
    assert text == "fw text" and meta["engine"] == "faster-whisper"


def test_local_engine_prefers_whispercpp_then_uses_faster_whisper(monkeypatch):
    monkeypatch.setattr(tr, "whispercpp_available", lambda: True)
    monkeypatch.setattr(tr, "faster_whisper_available", lambda: True)
    assert tr.local_engine() == "whisper.cpp"
    monkeypatch.setattr(tr, "whispercpp_available", lambda: False)
    assert tr.local_engine() == "faster-whisper"


def test_doctor_line_names_engine_model_and_device(fake_config):
    line = tr.local_status(fake_config)
    assert line.startswith("whisper.cpp small, ")
    assert "downloads on first use after a yes, 190 MB" in line
    assert "device " in line


# ── CLI and MCP ────────────────────────────────────────────────────────────


def _cli(argv, capsys):
    from searchts.cli import main

    with patch("sys.argv", ["searchts", *argv]):
        try:
            main()
            code = 0
        except SystemExit as e:
            code = e.code
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_json_reports_the_receipt(monkeypatch, capsys):
    result = tr.TranscribeResult(
        text="hallo", source="audio", provider="local", engine="whisper.cpp",
        model="small", device="metal", language="de", translated=True,
    )
    seen = {}

    def fake(source, **kw):
        seen.update(kw)
        return result

    monkeypatch.setattr(tr, "transcribe_result", fake)
    code, out, _ = _cli(["transcribe", "clip.mp3", "--json", "--model", "turbo",
                         "--hint", "Hollow", "--translate", "--yes"], capsys)
    assert code == 0
    doc = json.loads(out)
    assert doc["schema"] == "searchts.transcribe.v1" and doc["text"] == "hallo"
    assert doc["receipt"]["device"] == "metal" and doc["receipt"]["language"] == "de"
    assert doc["receipt"]["translated"] is True
    assert (seen["model"] == "turbo" and seen["hint"] == "Hollow"
            and seen["translate"] is True and seen["yes"] is True)


def test_cli_json_without_approval_names_the_download(monkeypatch, capsys):
    def needs(source, **kw):
        raise tr.ModelDownloadNeeded("needs a yes", {"name": "small", "size": "190 MB"})

    monkeypatch.setattr(tr, "transcribe_result", needs)
    code, out, _ = _cli(["transcribe", "clip.mp3", "--json", "--provider", "local",
                         "--model", "turbo", "--hint", "Laurentius, Dark Souls",
                         "--translate", "--no-subtitles"], capsys)
    assert code == 1
    doc = json.loads(out)
    assert doc["ok"] is False and doc["model_download"]["size"] == "190 MB"
    assert doc["consent_needed"] is True
    assert doc["model_download"]["approve_command"] == (
        "searchts transcribe clip.mp3 --provider local --model small --hint "
        "'Laurentius, Dark Souls' --translate --no-subtitles --yes --json"
    )


def test_cli_default_model_consent_command_names_the_resolved_model(monkeypatch, capsys):
    def needs(source, **kw):
        raise tr.ModelDownloadNeeded("needs a yes", {"name": "small", "size": "190 MB"})

    monkeypatch.setattr(tr, "transcribe_result", needs)
    code, out, _ = _cli(["transcribe", "clip.mp3", "--json"], capsys)
    doc = json.loads(out)
    assert code == 1
    assert doc["model_download"]["approve_command"] == (
        "searchts transcribe clip.mp3 --model small --yes --json"
    )


def test_cli_lists_models_as_json(monkeypatch, capsys):
    monkeypatch.setattr(whispercpp, "model_status", lambda: [
        {"name": "small", "size": "190 MB", "cached": False, "path": "/models/small"}
    ])
    code, out, _ = _cli(["transcribe", "--list-models", "--json"], capsys)
    doc = json.loads(out)
    assert code == 0 and doc["models"][0]["name"] == "small"


def test_cli_model_removal_needs_yes_and_reports_approval(monkeypatch, capsys, tmp_path):
    spec = whispercpp.MODELS["small"]
    path = tmp_path / spec.filename
    path.write_text("model")
    monkeypatch.setattr(whispercpp, "model_path", lambda s: path)
    code, out, _ = _cli(["transcribe", "--remove-model", "small", "--json"], capsys)
    doc = json.loads(out)
    assert code == 2 and doc["consent_needed"] is True
    assert doc["files"] == [str(path)]
    assert doc["approve_command"].endswith("--yes")
    assert path.exists()


def test_cli_model_removal_with_yes_removes_model_and_partial(monkeypatch, capsys, tmp_path):
    spec = whispercpp.MODELS["small"]
    path = tmp_path / spec.filename
    path.write_text("model")
    part = path.with_name(spec.filename + ".part")
    part.write_text("partial")
    monkeypatch.setattr(whispercpp, "model_path", lambda s: path)
    code, out, _ = _cli(["transcribe", "--remove-model", "small", "--yes", "--json"], capsys)
    doc = json.loads(out)
    assert code == 0 and len(doc["removed"]) == 2
    assert not path.exists() and not part.exists()


def test_cli_terminal_yes_retries_with_approval(monkeypatch, capsys):
    calls = []

    def fake(source, **kw):
        calls.append(kw["yes"])
        if not kw["yes"]:
            raise tr.ModelDownloadNeeded("needs a yes", {"name": "small"})
        return tr.TranscribeResult(text="done", source="audio", engine="whisper.cpp")

    monkeypatch.setattr(tr, "transcribe_result", fake)
    monkeypatch.setattr(whispercpp, "ask_tty", lambda spec: True)
    code, out, _ = _cli(["transcribe", "clip.mp3"], capsys)
    assert code == 0 and "done" in out and calls == [False, True]


def test_mcp_passes_options_and_appends_the_receipt(monkeypatch):
    from searchts.integrations.mcp_server import transcribe_source

    seen = {}

    def fake(source, **kw):
        seen.update(kw)
        return tr.TranscribeResult(text="words", source="audio", provider="local",
                                   engine="whisper.cpp", model="small", device="cpu",
                                   language="en")

    monkeypatch.setattr(tr, "transcribe_result", fake)
    out = transcribe_source("/tmp/x.m4a", model="turbo", hint="Hollow", yes=True,
                            update_info=None)
    assert out.startswith("words\n\ntranscribed_by: ")
    receipt = json.loads(out.split("transcribed_by: ", 1)[1].splitlines()[0])
    assert receipt["engine"] == "whisper.cpp" and receipt["language"] == "en"
    assert seen["model"] == "turbo" and seen["yes"] is True and seen["hint"] == "Hollow"


def test_mcp_without_yes_is_structured_consent_with_size_and_approval(monkeypatch):
    from searchts.integrations.mcp_server import transcribe_source

    monkeypatch.setattr(tr, "fetch_subtitles", lambda *a, **k: "")
    out = transcribe_source("https://example.com/v.mp4", update_info=None)
    doc = json.loads(out)
    assert doc["schema"] == "searchts.transcribe.v1"
    assert doc["consent_needed"] is True
    assert doc["model_download"]["size"] == "190 MB"
    assert "yes=true" in doc["model_download"]["approve"]


def test_engine_is_bundled_in_the_base_install():
    tomllib = pytest.importorskip("tomllib")
    from pathlib import Path

    doc = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert any(d.startswith("pywhispercpp") for d in doc["project"]["dependencies"])
    assert whispercpp.available(), whispercpp.unavailable_reason()
    assert sys.modules.get("pywhispercpp") is not None or whispercpp.binding_version()
