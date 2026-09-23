# -*- coding: utf-8 -*-
"""P1.4 fail-loud: five silent/wrong successes from the 0.9.0 hammer."""

import pytest

from searchts.transcribe import TranscribeError, assert_youtube_id_exact, transcribe
from searchts.unlocker import UnlockerError, fetch, normalize


def test_normalize_bare_host_still_https():
    assert normalize("example.com") == "https://example.com"
    assert normalize("http://x.test") == "http://x.test"
    assert normalize("example.com:8080") == "https://example.com:8080"


def test_normalize_refuses_file_and_data():
    with pytest.raises(ValueError, match="file"):
        normalize("file:///etc/passwd")
    with pytest.raises(ValueError, match="data"):
        normalize("data:text/html,hi")


def test_fetch_refuses_file_scheme_without_network():
    with pytest.raises(UnlockerError) as ei:
        fetch("file:///etc/passwd")
    assert "file" in str(ei.value).lower()


def test_fetch_refuses_localhost_without_network():
    with pytest.raises(UnlockerError) as ei:
        fetch("http://127.0.0.1/")
    assert "ssrf" in str(ei.value).lower() or "loopback" in str(ei.value).lower()


def test_fetch_refuses_hostname_that_resolves_to_loopback(monkeypatch):
    import socket

    monkeypatch.setattr(
        "searchts.ssrf.socket.getaddrinfo",
        lambda *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
        ],
    )
    with pytest.raises(UnlockerError) as ei:
        fetch("http://innocent.example.net/")
    msg = str(ei.value).lower()
    assert "127.0.0.1" in msg or "loopback" in msg


def test_youtube_junk_watch_id_is_rejected():
    with pytest.raises(TranscribeError, match="11 characters"):
        assert_youtube_id_exact(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ_private_fake"
        )


def test_youtube_youtu_be_junk_is_rejected():
    with pytest.raises(TranscribeError, match="11 characters"):
        assert_youtube_id_exact("https://youtu.be/dQw4w9WgXcQzzz")


def test_youtube_shorts_junk_is_rejected():
    with pytest.raises(TranscribeError, match="11 characters"):
        assert_youtube_id_exact("https://www.youtube.com/shorts/dQw4w9WgXcQzzz")


def test_youtube_blank_v_is_rejected():
    with pytest.raises(TranscribeError, match="11 characters"):
        assert_youtube_id_exact("https://www.youtube.com/watch?v=")
    with pytest.raises(TranscribeError, match="11 characters"):
        assert_youtube_id_exact("https://youtu.be/")
    assert_youtube_id_exact("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert_youtube_id_exact("https://youtu.be/dQw4w9WgXcQ")
    assert_youtube_id_exact("https://www.youtube.com/shorts/dQw4w9WgXcQ")


def test_youtube_junk_rejected_before_yt_dlp(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("yt-dlp must not run for a junk id")

    monkeypatch.setattr("searchts.transcribe.fetch_subtitles", boom)
    monkeypatch.setattr("searchts.transcribe.download_audio", boom)
    with pytest.raises(TranscribeError, match="11 characters"):
        transcribe("https://www.youtube.com/watch?v=dQw4w9WgXcQ_EXTRAJUNK")


def test_empty_whisper_is_error(monkeypatch, tmp_path):
    audio = tmp_path / "empty.m4a"
    audio.write_bytes(b"xxxx")
    monkeypatch.setattr("searchts.transcribe.Path.is_file", lambda self: True)
    monkeypatch.setattr("searchts.transcribe._provider_order", lambda *a, **k: ["local"])
    monkeypatch.setattr("searchts.transcribe._validate_backend", lambda *a, **k: None)
    monkeypatch.setattr("searchts.transcribe.compress_audio", lambda p, d: audio)
    monkeypatch.setattr(
        "searchts.transcribe._transcribe_with_fallback", lambda *a, **k: "  "
    )
    with pytest.raises(TranscribeError, match="empty transcript"):
        transcribe(str(audio), prefer_subtitles=False)
