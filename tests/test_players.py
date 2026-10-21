# -*- coding: utf-8 -*-
"""A player page is a read: captions, or a named failure. No network."""

import pytest

from searchts import players, unlocker
from searchts.transcribe import SubtitleReport

WATCH = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
X_STATUS = "https://x.com/jack/status/20"
X_VIDEO = "https://x.com/user/status/1600649710662213632/video/1"
CAPTIONS = "these are enough spoken words to count as the page"


def _report(text="", note="", ok=True):
    return lambda url, work, **k: SubtitleReport(text=text or None, note=note, ok=ok)


def test_a_watch_url_is_a_player_and_a_channel_is_not():
    assert players.matches(WATCH)
    assert players.matches("https://youtu.be/dQw4w9WgXcQ")
    assert players.matches("https://www.youtube.com/shorts/dQw4w9WgXcQ")
    assert players.matches("https://www.youtube.com/embed/dQw4w9WgXcQ")
    assert players.matches("https://www.tiktok.com/@user/video/123456")
    assert players.matches("https://www.instagram.com/reel/AbCdEf/")
    assert players.matches("https://v.redd.it/abc123")
    assert players.matches(X_STATUS)
    assert players.matches("https://twitter.com/user/status/20")
    assert players.matches(X_VIDEO)
    assert players.matches("https://mobile.twitter.com/user/status/20")
    assert players.matches("https://x.com/i/web/status/20")
    assert players.matches("https://x.com/i/broadcasts/1yNGaQLWpejGj")
    assert not players.matches("https://x.com/user/status/20/photo/1")
    assert not players.matches("https://x.com/user")
    assert not players.matches("https://x.com/")
    assert not players.matches("https://x.com/i/grok/share/abc")
    assert not players.matches("https://x.com/i/article/2090")
    assert not players.matches("https://www.youtube.com/")
    assert not players.matches("https://www.youtube.com/@user")
    assert not players.matches("https://www.youtube.com/watch?v=dQw4w9WgXcQ_EXTRA")
    assert not players.matches("https://www.reddit.com/r/videos/comments/abc/title/")
    assert not players.matches("https://example.com/watch?v=dQw4w9WgXcQ")


def test_captions_come_back_as_the_read(monkeypatch):
    monkeypatch.setattr("searchts.transcribe.ytdlp_available", lambda: True)
    monkeypatch.setattr("searchts.transcribe.fetch_subtitle_report", _report(CAPTIONS))
    played = players.extract(WATCH)
    assert played is not None
    assert played.failure == ""
    assert CAPTIONS in played.markdown
    assert "searchts transcribe" in played.markdown
    assert "[spoken:" in played.markdown


def test_no_captions_is_a_named_failure(monkeypatch):
    monkeypatch.setattr("searchts.transcribe.ytdlp_available", lambda: True)
    monkeypatch.setattr("searchts.transcribe.fetch_subtitle_report", _report())
    played = players.extract(WATCH)
    assert played is not None
    assert played.markdown == ""
    assert "no captions" in played.failure
    assert f"searchts transcribe {WATCH}" in played.failure


def test_a_handful_of_caption_characters_is_not_the_page(monkeypatch):
    monkeypatch.setattr("searchts.transcribe.ytdlp_available", lambda: True)
    monkeypatch.setattr("searchts.transcribe.fetch_subtitle_report", _report("hi"))
    played = players.extract(WATCH)
    assert played is not None and "no captions" in played.failure


def test_missing_ytdlp_names_the_next_step(monkeypatch):
    monkeypatch.setattr("searchts.transcribe.ytdlp_available", lambda: False)

    def boom(*a, **k):
        raise AssertionError("captions were fetched without yt-dlp")

    monkeypatch.setattr("searchts.transcribe.fetch_subtitle_report", boom)
    played = players.extract(WATCH)
    assert played is not None
    assert "yt-dlp is not installed" in played.failure
    assert "searchts transcribe" in played.failure


def test_a_caption_crash_falls_through(monkeypatch):
    monkeypatch.setattr("searchts.transcribe.ytdlp_available", lambda: True)

    def boom(*a, **k):
        raise RuntimeError("yt-dlp blew up")

    monkeypatch.setattr("searchts.transcribe.fetch_subtitle_report", boom)
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


def test_tiktok_instagram_reddit_and_x_video_return_captions(monkeypatch):
    monkeypatch.setattr("searchts.transcribe.ytdlp_available", lambda: True)
    monkeypatch.setattr("searchts.transcribe.fetch_subtitle_report", _report(CAPTIONS))
    urls = [
        "https://www.tiktok.com/@user/video/123456",
        "https://www.instagram.com/reel/AbCdEf/",
        "https://v.redd.it/abc123",
        X_VIDEO,
        "https://x.com/i/broadcasts/1yNGaQLWpejGj",
    ]
    for url in urls:
        played = players.extract(url)
        assert played is not None
        assert played.failure == ""
        assert CAPTIONS in played.markdown


def test_an_x_post_with_no_video_falls_through(monkeypatch):
    monkeypatch.setattr("searchts.transcribe.ytdlp_available", lambda: True)
    monkeypatch.setattr(
        "searchts.transcribe.fetch_subtitle_report",
        _report(note="ERROR: No video could be found in this tweet", ok=True),
    )
    assert players.extract(X_STATUS) is None


def test_an_x_post_yt_dlp_cannot_see_falls_through(monkeypatch):
    monkeypatch.setattr("searchts.transcribe.ytdlp_available", lambda: True)
    monkeypatch.setattr(
        "searchts.transcribe.fetch_subtitle_report",
        _report(note="yt-dlp failed (exit 1): HTTP Error 403", ok=False),
    )
    assert players.extract(X_STATUS) is None


def test_an_x_video_with_no_captions_names_transcribe(monkeypatch):
    monkeypatch.setattr("searchts.transcribe.ytdlp_available", lambda: True)
    monkeypatch.setattr("searchts.transcribe.fetch_subtitle_report", _report(ok=True))
    played = players.extract(X_VIDEO)
    assert played is not None
    assert "no captions" in played.failure
    assert f"searchts transcribe {X_VIDEO}" in played.failure


def test_a_bare_x_status_with_captions_is_the_read(monkeypatch):
    monkeypatch.setattr("searchts.transcribe.ytdlp_available", lambda: True)
    monkeypatch.setattr("searchts.transcribe.fetch_subtitle_report", _report(CAPTIONS, ok=True))
    played = players.extract(X_STATUS)
    assert played is not None
    assert CAPTIONS in played.markdown
    assert played.failure == ""


def test_missing_ytdlp_leaves_a_bare_x_status_on_the_ladder(monkeypatch):
    monkeypatch.setattr("searchts.transcribe.ytdlp_available", lambda: False)

    def boom(*a, **k):
        raise AssertionError("captions were fetched without yt-dlp")

    monkeypatch.setattr("searchts.transcribe.fetch_subtitle_report", boom)
    assert players.extract(X_STATUS) is None


def test_an_x_post_with_no_video_is_read_as_a_page(monkeypatch):
    monkeypatch.setattr("searchts.transcribe.ytdlp_available", lambda: True)
    monkeypatch.setattr(
        "searchts.transcribe.fetch_subtitle_report",
        _report(note="No video could be found in this tweet", ok=True),
    )
    html = "<html><body><main><p>" + ("word " * 80) + "</p></main></body></html>"
    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", lambda url, **kw: (200, html, url, {}))
    result = unlocker.fetch(X_STATUS, backends=["curl_cffi"], use_memory=False, progress=False)
    assert result.backend == "curl_cffi"
    assert "word" in result.text
