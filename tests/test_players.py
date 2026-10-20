# -*- coding: utf-8 -*-
"""A player page is a read: captions, or a named failure. No network."""

import pytest

from searchts import players, unlocker

WATCH = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
CAPTIONS = "these are enough spoken words to count as the page"


def test_a_watch_url_is_a_player_and_a_channel_is_not():
    assert players.matches(WATCH)
    assert players.matches("https://youtu.be/dQw4w9WgXcQ")
    assert players.matches("https://www.youtube.com/shorts/dQw4w9WgXcQ")
    assert players.matches("https://www.youtube.com/embed/dQw4w9WgXcQ")
    assert players.matches("https://www.tiktok.com/@user/video/123456")
    assert players.matches("https://www.instagram.com/reel/AbCdEf/")
    assert players.matches("https://v.redd.it/abc123")
    assert not players.matches("https://www.youtube.com/")
    assert not players.matches("https://www.youtube.com/@user")
    assert not players.matches("https://www.youtube.com/watch?v=dQw4w9WgXcQ_EXTRA")
    assert not players.matches("https://www.reddit.com/r/videos/comments/abc/title/")
    assert not players.matches("https://example.com/watch?v=dQw4w9WgXcQ")


def test_captions_come_back_as_the_read(monkeypatch):
    monkeypatch.setattr("searchts.transcribe.ytdlp_available", lambda: True)
    monkeypatch.setattr("searchts.transcribe.fetch_subtitles", lambda url, work, **k: CAPTIONS)
    played = players.extract(WATCH)
    assert played is not None
    assert played.failure == ""
    assert CAPTIONS in played.markdown
    assert "searchts transcribe" in played.markdown
    assert "[spoken:" in played.markdown


def test_no_captions_is_a_named_failure(monkeypatch):
    monkeypatch.setattr("searchts.transcribe.ytdlp_available", lambda: True)
    monkeypatch.setattr("searchts.transcribe.fetch_subtitles", lambda url, work, **k: None)
    played = players.extract(WATCH)
    assert played is not None
    assert played.markdown == ""
    assert "no captions" in played.failure
    assert f"searchts transcribe {WATCH}" in played.failure


def test_a_handful_of_caption_characters_is_not_the_page(monkeypatch):
    monkeypatch.setattr("searchts.transcribe.ytdlp_available", lambda: True)
    monkeypatch.setattr("searchts.transcribe.fetch_subtitles", lambda url, work, **k: "hi")
    played = players.extract(WATCH)
    assert played is not None and "no captions" in played.failure


def test_missing_ytdlp_names_the_next_step(monkeypatch):
    monkeypatch.setattr("searchts.transcribe.ytdlp_available", lambda: False)

    def boom(*a, **k):
        raise AssertionError("captions were fetched without yt-dlp")

    monkeypatch.setattr("searchts.transcribe.fetch_subtitles", boom)
    played = players.extract(WATCH)
    assert played is not None
    assert "yt-dlp is not installed" in played.failure
    assert "searchts transcribe" in played.failure


def test_a_caption_crash_falls_through(monkeypatch):
    monkeypatch.setattr("searchts.transcribe.ytdlp_available", lambda: True)

    def boom(*a, **k):
        raise RuntimeError("yt-dlp blew up")

    monkeypatch.setattr("searchts.transcribe.fetch_subtitles", boom)
    assert players.extract(WATCH) is None


def test_a_page_that_is_not_a_player_is_left_alone():
    assert players.extract("https://example.com/article") is None


def test_fetch_returns_captions_and_does_not_climb_the_ladder(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the ladder ran on a player page")

    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", boom)
    monkeypatch.setattr(
        "searchts.players.extract",
        lambda url: players.PlayerRead(markdown=CAPTIONS + "\n\n[spoken: x]"),
    )
    result = unlocker.fetch(WATCH, backends=["curl_cffi"], use_memory=False, progress=False)
    assert result.backend == "player:captions"
    assert CAPTIONS in result.text


def test_fetch_names_the_failure_and_returns_nothing(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the ladder ran after a named player failure")

    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", boom)
    monkeypatch.setattr(
        "searchts.players.extract",
        lambda url: players.PlayerRead(
            failure=f"this page's words are spoken and it has no captions. searchts transcribe {url} reads the audio."
        ),
    )
    with pytest.raises(unlocker.UnlockerError) as raised:
        unlocker.fetch(WATCH, backends=["curl_cffi"], use_memory=False, progress=False)
    assert raised.value.attempts[0][0] == "player"
    assert "no captions" in raised.value.hint
    assert "searchts transcribe" in raised.value.hint


def test_a_normal_page_does_not_ask_the_player_module(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("extract ran on a page that is not a player")

    monkeypatch.setattr("searchts.players.extract", boom)
    html = "<html><body><main><p>" + ("word " * 80) + "</p></main></body></html>"
    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", lambda url, **kw: (200, html, url, {}))
    result = unlocker.fetch(
        "https://example.org/article", backends=["curl_cffi"], use_memory=False, progress=False
    )
    assert "word" in result.text
    assert result.backend == "curl_cffi"
