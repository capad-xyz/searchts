# -*- coding: utf-8 -*-
"""Tests for searchts.transcribe — provider routing, fallback, and errors."""

import sys
from typing import List

import pytest

from searchts import transcribe as tr
from searchts.config import Config


def _hide_ytdlp_module(monkeypatch):
    """Make `find_spec("yt_dlp")` return None (module genuinely absent).

    yt-dlp ships with searchts, so its module is importable in the test venv;
    these tests must explicitly hide it to exercise the PATH-binary fallback.
    """
    import importlib.util

    real_find_spec = tr.importlib.util.find_spec

    def fake_find_spec(name, *a, **k):
        return None if name == "yt_dlp" else real_find_spec(name, *a, **k)

    monkeypatch.setattr(tr.importlib.util, "find_spec", fake_find_spec)

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


# --- yt-dlp invocation: module vs PATH binary -------------------------- #


class TestYtdlpCmd:
    def test_cmd_uses_module_when_importable_even_without_path(self, monkeypatch):
        # The headline fix: module importable, console script NOT on PATH
        # (the venv/pipx reality) -> invoke via `python -m yt_dlp`.
        monkeypatch.setattr(tr.shutil, "which", lambda name: None)
        assert tr._ytdlp_cmd() == [sys.executable, "-m", "yt_dlp"]

    def test_available_true_when_module_importable_without_path(self, monkeypatch):
        monkeypatch.setattr(tr.shutil, "which", lambda name: None)
        assert tr.ytdlp_available() is True

    def test_cmd_falls_back_to_path_binary_when_module_absent(self, monkeypatch):
        _hide_ytdlp_module(monkeypatch)
        monkeypatch.setattr(tr.shutil, "which", lambda name: "/usr/bin/yt-dlp")
        assert tr._ytdlp_cmd() == ["yt-dlp"]
        assert tr.ytdlp_available() is True

    def test_cmd_raises_when_neither_available(self, monkeypatch):
        _hide_ytdlp_module(monkeypatch)
        monkeypatch.setattr(tr.shutil, "which", lambda name: None)
        assert tr.ytdlp_available() is False
        with pytest.raises(tr.MissingDependency, match="yt-dlp not found"):
            tr._ytdlp_cmd()

    def test_download_audio_builds_module_command(self, monkeypatch, tmp_path):
        # download_audio must prefix the command with `python -m yt_dlp`.
        monkeypatch.setattr(tr.shutil, "which", lambda name: None)
        captured = {}

        def fake_run(cmd, timeout=600):
            captured["cmd"] = cmd
            (tmp_path / "source.m4a").write_bytes(b"x")

        monkeypatch.setattr(tr, "_run", fake_run)
        out = tr.download_audio("https://youtu.be/x", tmp_path)
        assert captured["cmd"][:3] == [sys.executable, "-m", "yt_dlp"]
        assert out.name == "source.m4a"


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


# --- _vtt_to_text ------------------------------------------------------- #


class TestVttToText:
    def test_strips_headers_timestamps_tags(self):
        vtt = (
            "WEBVTT\n"
            "Kind: captions\n"
            "Language: en\n"
            "\n"
            "NOTE this is a note\n"
            "\n"
            "1\n"
            "00:00:00.000 --> 00:00:02.000\n"
            "<c>Hello</c> <00:00:01.000>there\n"
            "\n"
            "2\n"
            "00:00:02.000 --> 00:00:04.000\n"
            "general <v Roger>Kenobi</v>\n"
        )
        out = tr._vtt_to_text(vtt)
        assert "WEBVTT" not in out
        assert "Kind:" not in out
        assert "Language:" not in out
        assert "NOTE" not in out
        assert "-->" not in out
        assert "<" not in out and ">" not in out
        assert out == "Hello there\ngeneral Kenobi"

    def test_collapses_consecutive_duplicate_lines(self):
        # Auto-captions repeat the rolling text from cue to cue.
        vtt = (
            "WEBVTT\n\n"
            "00:00:00.000 --> 00:00:01.000\n"
            "the quick brown\n\n"
            "00:00:01.000 --> 00:00:02.000\n"
            "the quick brown\n\n"
            "00:00:02.000 --> 00:00:03.000\n"
            "fox jumps\n"
        )
        out = tr._vtt_to_text(vtt)
        assert out == "the quick brown\nfox jumps"

    def test_empty_vtt_returns_empty_string(self):
        assert tr._vtt_to_text("WEBVTT\n\n") == ""


# --- fetch_subtitles ---------------------------------------------------- #


class TestFetchSubtitles:
    def test_returns_none_when_yt_dlp_missing(self, monkeypatch, tmp_path):
        # Truly absent: not on PATH AND the yt_dlp module is not importable.
        _hide_ytdlp_module(monkeypatch)
        monkeypatch.setattr(tr.shutil, "which", lambda name: None)
        assert tr.fetch_subtitles("https://youtu.be/x", tmp_path) is None

    def test_uses_module_form_when_importable_not_on_path(self, monkeypatch, tmp_path):
        # The bug scenario: module importable, no PATH binary. fetch_subtitles
        # must still run and build the command via `python -m yt_dlp`.
        monkeypatch.setattr(tr.shutil, "which", lambda name: None)
        captured = {}

        def fake_run(cmd, timeout=600):
            captured["cmd"] = cmd

        monkeypatch.setattr(tr, "_run", fake_run)
        # No *.vtt is produced -> returns None, but the point is the command ran.
        assert tr.fetch_subtitles("https://youtu.be/x", tmp_path) is None
        assert captured["cmd"][:3] == [sys.executable, "-m", "yt_dlp"]

    def test_returns_none_on_yt_dlp_failure(self, monkeypatch, tmp_path):
        def boom(cmd, timeout=600):
            raise tr.TranscribeError("yt-dlp failed (exit 1): no subtitles")

        monkeypatch.setattr(tr, "_run", boom)
        assert tr.fetch_subtitles("https://youtu.be/x", tmp_path) is None

    def test_returns_none_when_no_vtt_produced(self, monkeypatch, tmp_path):
        monkeypatch.setattr(tr, "_run", lambda cmd, timeout=600: None)
        # No *.vtt files written to tmp_path.
        assert tr.fetch_subtitles("https://youtu.be/x", tmp_path) is None

    def test_reads_and_cleans_vtt(self, monkeypatch, tmp_path):
        def fake_run(cmd, timeout=600):
            (tmp_path / "vid.en.vtt").write_text(
                "WEBVTT\n\n"
                "00:00:00.000 --> 00:00:02.000\n"
                "hello world\n",
                encoding="utf-8",
            )

        monkeypatch.setattr(tr, "_run", fake_run)
        out = tr.fetch_subtitles("https://youtu.be/x", tmp_path)
        assert out == "hello world"

    def test_prefers_manual_over_auto_track(self, monkeypatch, tmp_path):
        def fake_run(cmd, timeout=600):
            (tmp_path / "vid.en-auto.vtt").write_text(
                "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nauto track\n",
                encoding="utf-8",
            )
            (tmp_path / "vid.en.vtt").write_text(
                "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nmanual track\n",
                encoding="utf-8",
            )

        monkeypatch.setattr(tr, "_run", fake_run)
        out = tr.fetch_subtitles("https://youtu.be/x", tmp_path)
        assert out == "manual track"


# --- transcribe: subtitles-first --------------------------------------- #


class TestSubtitlesFirst:
    def test_captioned_url_needs_no_provider(self, monkeypatch, fake_config, tmp_path):
        """The headline behavior: a captioned URL transcribes with NO key and NO
        local model — subtitles short-circuit before any provider validation."""
        # No hosted key configured; faster-whisper simulated absent.
        monkeypatch.setattr(tr, "local_available", lambda: False)
        monkeypatch.setattr(
            tr, "fetch_subtitles",
            lambda url, work_dir, *, config=None: "these are the existing captions of the video",
        )

        def boom_download(*a, **k):
            raise AssertionError("must not download audio when subtitles exist")

        monkeypatch.setattr(tr, "download_audio", boom_download)
        monkeypatch.setattr(
            tr.requests, "post",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("no HTTP for captions")),
        )

        text = tr.transcribe(
            "https://youtu.be/abc", out_dir=tmp_path / "work", config=fake_config
        )
        assert text == "these are the existing captions of the video"

    def test_short_subtitles_fall_back_to_audio(self, monkeypatch, fake_config, tmp_path):
        # A near-empty caption track (< MIN_SUBTITLE_CHARS) should not pre-empt Whisper.
        fake_config.set("groq_api_key", "gsk_test")
        monkeypatch.setattr(
            tr, "fetch_subtitles", lambda url, work_dir, *, config=None: "hi"
        )
        compressed = tmp_path / "compressed.m4a"
        compressed.write_bytes(b"x" * 1024)
        monkeypatch.setattr(tr, "download_audio", lambda url, out_dir: tmp_path / "src.m4a")
        monkeypatch.setattr(tr, "compress_audio", lambda src, out_dir: compressed)
        monkeypatch.setattr(
            tr.requests, "post", lambda *a, **k: FakeResponse(200, "audio transcript")
        )

        text = tr.transcribe(
            "https://youtu.be/abc", out_dir=tmp_path / "work", config=fake_config
        )
        assert text == "audio transcript"

    def test_no_subtitles_no_backend_raises(self, monkeypatch, fake_config, tmp_path):
        # No subtitles AND no backend -> NoProviderConfigured, as before.
        monkeypatch.setattr(tr, "fetch_subtitles", lambda url, work_dir, *, config=None: None)
        monkeypatch.setattr(tr, "local_available", lambda: False)

        def boom_download(*a, **k):
            raise AssertionError("should fail validation before downloading")

        monkeypatch.setattr(tr, "download_audio", boom_download)
        with pytest.raises(tr.NoProviderConfigured):
            tr.transcribe(
                "https://youtu.be/abc", out_dir=tmp_path / "work", config=fake_config
            )

    def test_no_subtitles_with_backend_transcribes(self, monkeypatch, fake_config, tmp_path):
        # No subtitles but a (mocked) backend present -> returns transcribed text.
        fake_config.set("groq_api_key", "gsk_test")
        monkeypatch.setattr(tr, "fetch_subtitles", lambda url, work_dir, *, config=None: None)
        compressed = tmp_path / "compressed.m4a"
        compressed.write_bytes(b"x" * 1024)
        monkeypatch.setattr(tr, "download_audio", lambda url, out_dir: tmp_path / "src.m4a")
        monkeypatch.setattr(tr, "compress_audio", lambda src, out_dir: compressed)
        monkeypatch.setattr(
            tr.requests, "post", lambda *a, **k: FakeResponse(200, "from whisper")
        )

        text = tr.transcribe(
            "https://youtu.be/abc", out_dir=tmp_path / "work", config=fake_config
        )
        assert text == "from whisper"

    def test_no_subtitles_flag_bypasses_captions(self, monkeypatch, fake_config, tmp_path):
        # prefer_subtitles=False must skip fetch_subtitles entirely and go to audio.
        fake_config.set("groq_api_key", "gsk_test")

        def boom_subs(*a, **k):
            raise AssertionError("fetch_subtitles must not be consulted with prefer_subtitles=False")

        monkeypatch.setattr(tr, "fetch_subtitles", boom_subs)
        compressed = tmp_path / "compressed.m4a"
        compressed.write_bytes(b"x" * 1024)
        monkeypatch.setattr(tr, "download_audio", lambda url, out_dir: tmp_path / "src.m4a")
        monkeypatch.setattr(tr, "compress_audio", lambda src, out_dir: compressed)
        monkeypatch.setattr(
            tr.requests, "post", lambda *a, **k: FakeResponse(200, "forced audio")
        )

        text = tr.transcribe(
            "https://youtu.be/abc",
            out_dir=tmp_path / "work",
            config=fake_config,
            prefer_subtitles=False,
        )
        assert text == "forced audio"

    def test_local_file_skips_subtitle_attempt(self, monkeypatch, fake_config, tmp_path, chunk_file):
        # A local file must never trigger a subtitle fetch.
        fake_config.set("groq_api_key", "gsk_test")

        def boom_subs(*a, **k):
            raise AssertionError("fetch_subtitles must not run for local files")

        monkeypatch.setattr(tr, "fetch_subtitles", boom_subs)
        compressed = tmp_path / "compressed.m4a"
        compressed.write_bytes(b"x" * 1024)
        monkeypatch.setattr(tr, "compress_audio", lambda src, out_dir: compressed)
        monkeypatch.setattr(
            tr.requests, "post", lambda *a, **k: FakeResponse(200, "local file audio")
        )

        text = tr.transcribe(
            str(chunk_file), out_dir=tmp_path / "work", config=fake_config
        )
        assert text == "local file audio"
