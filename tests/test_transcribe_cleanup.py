# -*- coding: utf-8 -*-
"""The default transcribe() workspace must not leave files on the user's disk."""

import pytest

import searchts.transcribe as T


def test_transcribe_removes_temp_dir_on_success(monkeypatch):
    captured = {}

    def fake_run(source, work_dir, provider, cfg, prefer_subtitles):
        captured["dir"] = work_dir
        assert work_dir.exists(), "workspace should exist during transcription"
        return "transcript text"

    monkeypatch.setattr(T, "_run_transcription", fake_run)
    out = T.transcribe("https://example.com/video")
    assert out == "transcript text"
    assert captured["dir"].exists() is False, "temp workspace must be deleted afterward"


def test_transcribe_removes_temp_dir_on_failure(monkeypatch):
    captured = {}

    def boom(source, work_dir, provider, cfg, prefer_subtitles):
        captured["dir"] = work_dir
        raise T.TranscribeError("kaboom")

    monkeypatch.setattr(T, "_run_transcription", boom)
    with pytest.raises(T.TranscribeError):
        T.transcribe("https://example.com/video")
    assert captured["dir"].exists() is False, "temp workspace must be cleaned even on error"


def test_transcribe_keeps_explicit_out_dir(monkeypatch, tmp_path):
    def fake_run(source, work_dir, provider, cfg, prefer_subtitles):
        (work_dir / "leftover.m4a").write_bytes(b"x")
        return "t"

    monkeypatch.setattr(T, "_run_transcription", fake_run)
    T.transcribe("https://example.com/video", out_dir=tmp_path)
    # An explicitly provided directory is the caller's; we must not delete it.
    assert (tmp_path / "leftover.m4a").exists()
