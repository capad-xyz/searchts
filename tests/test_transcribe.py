# -*- coding: utf-8 -*-
"""Tests for searchts.transcribe — provider routing, fallback, and errors."""

from typing import List

import pytest

from searchts import transcribe as tr
from searchts.config import Config

# --- Fixtures ----------------------------------------------------------- #


@pytest.fixture
def fake_config(tmp_path, monkeypatch):
    """A Config that writes to a temp dir and never touches the user's HOME."""
    cfg_path = tmp_path / "config.yaml"
    monkeypatch.setattr(Config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(Config, "CONFIG_FILE", cfg_path)
    cfg = Config(config_path=cfg_path)
    return cfg


@pytest.fixture
def chunk_file(tmp_path):
    p = tmp_path / "chunk.m4a"
    p.write_bytes(b"\x00fake-m4a-bytes")
    return p


class FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


# --- transcribe_chunk: provider routing -------------------------------- #


class TestTranscribeChunk:
    def test_routes_to_groq_endpoint(self, monkeypatch, fake_config, chunk_file):
        fake_config.set("groq_api_key", "gsk_test")
        captured = {}

        def fake_post(url, headers=None, files=None, data=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["model"] = data["model"]
            return FakeResponse(200, "hello world")

        monkeypatch.setattr(tr.requests, "post", fake_post)
        text = tr.transcribe_chunk(chunk_file, "groq", config=fake_config)
        assert text == "hello world"
        assert captured["url"] == tr.PROVIDERS["groq"]["endpoint"]
        assert captured["model"] == "whisper-large-v3"
        assert captured["headers"]["Authorization"] == "Bearer gsk_test"

    def test_routes_to_openai_endpoint(self, monkeypatch, fake_config, chunk_file):
        fake_config.set("openai_api_key", "sk-test")
        captured = {}

        def fake_post(url, headers=None, files=None, data=None, timeout=None):
            captured["url"] = url
            captured["model"] = data["model"]
            return FakeResponse(200, "openai output")

        monkeypatch.setattr(tr.requests, "post", fake_post)
        text = tr.transcribe_chunk(chunk_file, "openai", config=fake_config)
        assert text == "openai output"
        assert captured["url"] == tr.PROVIDERS["openai"]["endpoint"]
        assert captured["model"] == "whisper-1"

    def test_raises_when_key_missing(self, fake_config, chunk_file):
        with pytest.raises(tr.NoProviderConfigured):
            tr.transcribe_chunk(chunk_file, "groq", config=fake_config)

    def test_raises_on_http_error(self, monkeypatch, fake_config, chunk_file):
        fake_config.set("groq_api_key", "gsk_test")
        monkeypatch.setattr(
            tr.requests,
            "post",
            lambda *a, **k: FakeResponse(429, "rate limited"),
        )
        with pytest.raises(tr.TranscribeError, match="HTTP 429"):
            tr.transcribe_chunk(chunk_file, "groq", config=fake_config)

    def test_unknown_provider(self, fake_config, chunk_file):
        with pytest.raises(tr.TranscribeError, match="unknown provider"):
            tr.transcribe_chunk(chunk_file, "azure", config=fake_config)


# --- _transcribe_with_fallback ----------------------------------------- #


class TestFallback:
    def test_groq_succeeds_no_openai_call(self, monkeypatch, fake_config, chunk_file):
        fake_config.set("groq_api_key", "gsk_test")
        fake_config.set("openai_api_key", "sk-test")
        calls: List[str] = []

        def fake_post(url, headers=None, files=None, data=None, timeout=None):
            calls.append(url)
            return FakeResponse(200, "from-groq")

        monkeypatch.setattr(tr.requests, "post", fake_post)
        text = tr._transcribe_with_fallback(chunk_file, ["groq", "openai"], fake_config)
        assert text == "from-groq"
        assert calls == [tr.PROVIDERS["groq"]["endpoint"]]

    def test_groq_429_falls_back_to_openai(self, monkeypatch, fake_config, chunk_file):
        fake_config.set("groq_api_key", "gsk_test")
        fake_config.set("openai_api_key", "sk-test")
        calls: List[str] = []

        def fake_post(url, headers=None, files=None, data=None, timeout=None):
            calls.append(url)
            if url == tr.PROVIDERS["groq"]["endpoint"]:
                return FakeResponse(429, "rate limited")
            return FakeResponse(200, "from-openai")

        monkeypatch.setattr(tr.requests, "post", fake_post)
        text = tr._transcribe_with_fallback(chunk_file, ["groq", "openai"], fake_config)
        assert text == "from-openai"
        assert calls == [
            tr.PROVIDERS["groq"]["endpoint"],
            tr.PROVIDERS["openai"]["endpoint"],
        ]

    def test_skip_unconfigured_provider(self, monkeypatch, fake_config, chunk_file):
        # Only openai key configured — fallback should skip groq silently.
        fake_config.set("openai_api_key", "sk-test")
        calls: List[str] = []

        def fake_post(url, headers=None, files=None, data=None, timeout=None):
            calls.append(url)
            return FakeResponse(200, "via-openai")

        monkeypatch.setattr(tr.requests, "post", fake_post)
        text = tr._transcribe_with_fallback(chunk_file, ["groq", "openai"], fake_config)
        assert text == "via-openai"
        assert calls == [tr.PROVIDERS["openai"]["endpoint"]]

    def test_all_fail_raises_with_last_error(self, monkeypatch, fake_config, chunk_file):
        fake_config.set("groq_api_key", "gsk_test")
        fake_config.set("openai_api_key", "sk-test")
        monkeypatch.setattr(
            tr.requests,
            "post",
            lambda *a, **k: FakeResponse(500, "boom"),
        )
        with pytest.raises(tr.TranscribeError, match="all providers failed"):
            tr._transcribe_with_fallback(chunk_file, ["groq", "openai"], fake_config)


# --- transcribe (orchestrator) ---------------------------------------- #


class TestOrchestrator:
    def test_local_file_skips_yt_dlp(self, monkeypatch, fake_config, tmp_path, chunk_file):
        fake_config.set("groq_api_key", "gsk_test")

        def boom_download(*a, **k):
            raise AssertionError("yt-dlp must not be called for local files")

        # Stub heavy external steps to no-ops that keep file paths valid.
        compressed = tmp_path / "compressed.m4a"
        compressed.write_bytes(b"x" * 1024)

        def fake_compress(src, out_dir):
            return compressed

        monkeypatch.setattr(tr, "download_audio", boom_download)
        monkeypatch.setattr(tr, "compress_audio", fake_compress)
        monkeypatch.setattr(
            tr.requests,
            "post",
            lambda *a, **k: FakeResponse(200, "transcript text"),
        )

        text = tr.transcribe(
            str(chunk_file),
            out_dir=tmp_path / "work",
            config=fake_config,
        )
        assert text == "transcript text"

    def test_chunks_concatenated_with_newlines(
        self, monkeypatch, fake_config, tmp_path, chunk_file
    ):
        fake_config.set("groq_api_key", "gsk_test")
        # Force the "needs chunking" path by writing a file above the size limit.
        big = tmp_path / "compressed.m4a"
        big.write_bytes(b"x" * (tr.SIZE_LIMIT_BYTES + 1))
        monkeypatch.setattr(tr, "compress_audio", lambda src, out_dir: big)
        c1 = tmp_path / "chunk_001.m4a"
        c2 = tmp_path / "chunk_002.m4a"
        c1.write_bytes(b"a")
        c2.write_bytes(b"b")
        monkeypatch.setattr(tr, "chunk_audio", lambda src, out_dir: [c1, c2])

        responses = iter(["part one ", "part two "])
        monkeypatch.setattr(
            tr.requests,
            "post",
            lambda *a, **k: FakeResponse(200, next(responses)),
        )

        text = tr.transcribe(
            str(chunk_file),
            out_dir=tmp_path / "work",
            config=fake_config,
        )
        assert text == "part one\npart two"

    def test_no_provider_configured_fails_fast(self, monkeypatch, fake_config, chunk_file):
        # No hosted key AND no local backend -> fail fast before any work.
        monkeypatch.setattr(tr, "local_available", lambda: False)
        with pytest.raises(tr.NoProviderConfigured):
            tr.transcribe(str(chunk_file), config=fake_config)

    def test_invalid_provider_string(self, fake_config, chunk_file):
        with pytest.raises(tr.TranscribeError, match="unknown provider"):
            tr.transcribe(str(chunk_file), provider="azure", config=fake_config)


# --- local backend (faster-whisper) ----------------------------------- #


class _FakeSegment:
    def __init__(self, text):
        self.text = text


class _FakeWhisperModel:
    """Stand-in for faster_whisper.WhisperModel — records init + transcribe."""

    def __init__(self, model_size, device=None, compute_type=None, segments=None):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._segments = segments or [_FakeSegment("local "), _FakeSegment("transcript")]
        self.transcribe_calls = []

    def transcribe(self, path):
        self.transcribe_calls.append(path)
        return iter(self._segments), {"language": "en"}


@pytest.fixture(autouse=True)
def _clear_local_model_cache():
    """Keep the module-level model cache from leaking between tests."""
    tr._LOCAL_MODEL_CACHE.clear()
    yield
    tr._LOCAL_MODEL_CACHE.clear()


def _patch_local(monkeypatch, model=None):
    """Make the local backend importable and return canned segments."""
    fake = model or _FakeWhisperModel("base")
    monkeypatch.setattr(tr, "local_available", lambda: True)
    monkeypatch.setattr(tr, "_load_local_model", lambda size: fake)
    return fake


class TestLocalBackend:
    def test_transcribe_chunk_local_joins_segments(self, monkeypatch, fake_config, chunk_file):
        fake = _patch_local(monkeypatch)
        text = tr.transcribe_chunk_local(chunk_file, config=fake_config)
        assert text == "local transcript"
        assert fake.transcribe_calls == [str(chunk_file)]

    def test_transcribe_chunk_routes_local(self, monkeypatch, fake_config, chunk_file):
        _patch_local(monkeypatch)
        # provider="local" must not require any API key.
        text = tr.transcribe_chunk(chunk_file, "local", config=fake_config)
        assert text == "local transcript"

    def test_provider_local_end_to_end(self, monkeypatch, fake_config, tmp_path, chunk_file):
        # No hosted key at all; provider="local" should still produce text.
        _patch_local(monkeypatch)
        compressed = tmp_path / "compressed.m4a"
        compressed.write_bytes(b"x" * 1024)
        monkeypatch.setattr(tr, "compress_audio", lambda src, out_dir: compressed)

        def boom_post(*a, **k):
            raise AssertionError("local must not make HTTP calls")

        monkeypatch.setattr(tr.requests, "post", boom_post)
        text = tr.transcribe(
            str(chunk_file), provider="local", out_dir=tmp_path / "work", config=fake_config
        )
        assert text == "local transcript"

    def test_auto_falls_back_to_local_when_no_key(self, monkeypatch, fake_config):
        # No hosted key configured, faster-whisper present -> auto picks local.
        _patch_local(monkeypatch)
        assert tr._provider_order("auto", fake_config) == ["local"]

    def test_auto_prefers_hosted_when_key_set(self, monkeypatch, fake_config):
        # A groq key is set -> auto stays hosted even though local is available.
        fake_config.set("groq_api_key", "gsk_test")
        _patch_local(monkeypatch)
        assert tr._provider_order("auto", fake_config) == ["groq"]

    def test_auto_end_to_end_uses_local(self, monkeypatch, fake_config, tmp_path, chunk_file):
        _patch_local(monkeypatch)
        compressed = tmp_path / "compressed.m4a"
        compressed.write_bytes(b"x" * 1024)
        monkeypatch.setattr(tr, "compress_audio", lambda src, out_dir: compressed)
        monkeypatch.setattr(
            tr.requests, "post",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("no HTTP for local")),
        )
        text = tr.transcribe(
            str(chunk_file), provider="auto", out_dir=tmp_path / "work", config=fake_config
        )
        assert text == "local transcript"

    def test_missing_faster_whisper_actionable_error(self, monkeypatch, fake_config, chunk_file):
        # Simulate faster-whisper not installed.
        monkeypatch.setattr(tr, "local_available", lambda: False)

        def no_import():
            raise tr.MissingDependency(
                'local transcription needs faster-whisper. Install it with:\n'
                '  pip install "searchts[local-transcribe]"'
            )

        monkeypatch.setattr(tr, "_import_faster_whisper", no_import)
        with pytest.raises(tr.MissingDependency, match="searchts\\[local-transcribe\\]"):
            tr.transcribe_chunk_local(chunk_file, config=fake_config)

    def test_no_backend_at_all_actionable_error(self, monkeypatch, fake_config, chunk_file):
        # Neither a hosted key nor faster-whisper -> NoProviderConfigured mentioning both.
        monkeypatch.setattr(tr, "local_available", lambda: False)
        with pytest.raises(tr.NoProviderConfigured, match="local-transcribe"):
            tr.transcribe(str(chunk_file), provider="auto", config=fake_config)

    def test_model_size_from_config(self, monkeypatch, fake_config):
        fake_config.set("whisper_model", "small")
        assert tr._local_model_size(fake_config) == "small"

    def test_model_size_from_env(self, monkeypatch, fake_config):
        monkeypatch.setenv("SEARCHTS_WHISPER_MODEL", "medium")
        assert tr._local_model_size(fake_config) == "medium"

    def test_model_size_default(self, fake_config):
        assert tr._local_model_size(fake_config) == tr.DEFAULT_LOCAL_MODEL

    def test_model_cached_across_chunks(self, monkeypatch, fake_config, chunk_file):
        # _load_local_model must reuse the same instance for repeated chunks.
        loads = []

        class _Counter(_FakeWhisperModel):
            pass

        def fake_import():
            return lambda size, device=None, compute_type=None: (
                loads.append(size) or _Counter(size)
            )

        monkeypatch.setattr(tr, "_import_faster_whisper", fake_import)
        m1 = tr._load_local_model("base")
        m2 = tr._load_local_model("base")
        assert m1 is m2
        assert loads == ["base"]  # loaded exactly once


# --- YouTubeChannel integration --------------------------------------- #


class TestYouTubeChannelTranscribe:
    def test_delegates_to_transcribe(self, monkeypatch, fake_config):
        from searchts.channels.youtube import YouTubeChannel

        captured = {}

        def fake_transcribe(source, *, provider="auto", out_dir=None, config=None):
            captured["source"] = source
            captured["provider"] = provider
            captured["config"] = config
            return "delegated text"

        monkeypatch.setattr(tr, "transcribe", fake_transcribe)
        out = YouTubeChannel().transcribe(
            "https://youtu.be/abc", provider="groq", config=fake_config
        )
        assert out == "delegated text"
        assert captured["source"] == "https://youtu.be/abc"
        assert captured["provider"] == "groq"
        assert captured["config"] is fake_config


# --- Config feature requirement --------------------------------------- #


class TestConfigOpenAIWhisper:
    def test_openai_whisper_feature_registered(self, fake_config):
        assert "openai_whisper" in Config.FEATURE_REQUIREMENTS
        assert Config.FEATURE_REQUIREMENTS["openai_whisper"] == ["openai_api_key"]
        assert not fake_config.is_configured("openai_whisper")
        fake_config.set("openai_api_key", "sk-test")
        assert fake_config.is_configured("openai_whisper")
