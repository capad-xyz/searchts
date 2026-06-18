# -*- coding: utf-8 -*-
"""Tests for the audio-transcription video channels (TikTok, Instagram, Reddit video).

These mirror the YouTube channel tests: yt-dlp is probed via a mocked
shutil.which / subprocess.run, and transcribe() delegation is checked without
any real download or network call.
"""

import importlib.util
import shutil
import subprocess

import pytest

from searchts import probe as probe_mod
from searchts import transcribe as tr
from searchts.channels import get_all_channels, get_channel
from searchts.channels.instagram import InstagramChannel
from searchts.channels.redditvideo import RedditVideoChannel
from searchts.channels.tiktok import TikTokChannel
from searchts.config import Config


# --- Fixtures ----------------------------------------------------------- #


@pytest.fixture
def fake_config(tmp_path, monkeypatch):
    """A Config that writes to a temp dir and never touches the user's HOME."""
    cfg_path = tmp_path / "config.yaml"
    monkeypatch.setattr(Config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(Config, "CONFIG_FILE", cfg_path)
    return Config(config_path=cfg_path)


def _fake_run_version(cmd, **kwargs):
    """Pretend yt-dlp executes fine and prints a version."""
    return subprocess.CompletedProcess(cmd, 0, "2026.06.09", "")


def _which_factory(present):
    """Build a shutil.which stub where only the named commands resolve."""

    def fake_which(cmd):
        return f"/usr/bin/{cmd}" if cmd in present else None

    return fake_which


def _hide_ytdlp_module(monkeypatch):
    """Make `find_spec("yt_dlp")` return None so module-based detection misses.

    yt-dlp ships with searchts, so its module is genuinely importable in the
    test venv. Channel `check()` now detects it that way, so the "yt-dlp truly
    absent" path requires hiding the module AND keeping it off PATH.
    """
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name, *a, **k):
        if name == "yt_dlp":
            return None
        return real_find_spec(name, *a, **k)

    monkeypatch.setattr(probe_mod.importlib.util, "find_spec", fake_find_spec)


# --- can_handle: URL patterns ------------------------------------------ #


class TestTikTokCanHandle:
    def test_matches_tiktok_urls(self):
        ch = TikTokChannel()
        assert ch.can_handle("https://www.tiktok.com/@user/video/1234567890")
        assert ch.can_handle("https://vm.tiktok.com/ZMabcdef/")
        assert ch.can_handle("https://tiktok.com/@creator/video/999")

    def test_rejects_other_urls(self):
        ch = TikTokChannel()
        assert not ch.can_handle("https://youtube.com/watch?v=abc")
        assert not ch.can_handle("https://instagram.com/reel/abc/")
        assert not ch.can_handle("https://example.com/video/1")


class TestInstagramCanHandle:
    def test_matches_instagram_media_urls(self):
        ch = InstagramChannel()
        assert ch.can_handle("https://www.instagram.com/reel/Cabc123/")
        assert ch.can_handle("https://instagram.com/reels/Cabc123/")
        assert ch.can_handle("https://www.instagram.com/p/Cxyz789/")
        assert ch.can_handle("https://instagram.com/tv/Cabc/")

    def test_rejects_profile_and_other_urls(self):
        ch = InstagramChannel()
        # Bare profile / non-media paths should not match.
        assert not ch.can_handle("https://www.instagram.com/someuser/")
        assert not ch.can_handle("https://tiktok.com/@user/video/1")
        assert not ch.can_handle("https://example.com/p/abc/")


class TestRedditVideoCanHandle:
    def test_matches_video_urls(self):
        ch = RedditVideoChannel()
        assert ch.can_handle("https://v.redd.it/abc123")
        assert ch.can_handle(
            "https://www.reddit.com/r/aww/comments/abc123/cute_cat/"
        )

    def test_rejects_non_video_reddit_and_others(self):
        ch = RedditVideoChannel()
        # Subreddit listing is not a video post permalink.
        assert not ch.can_handle("https://www.reddit.com/r/python/")
        # redd.it short links (text posts) are handled by the text channel, not here.
        assert not ch.can_handle("https://redd.it/abc123")
        assert not ch.can_handle("https://youtube.com/watch?v=abc")


# --- check(): yt-dlp probe statuses ------------------------------------ #


_VIDEO_CHANNELS = [TikTokChannel, InstagramChannel, RedditVideoChannel]


@pytest.mark.parametrize("channel_cls", _VIDEO_CHANNELS)
class TestCheckStatuses:
    def test_off_when_ytdlp_missing(self, channel_cls, monkeypatch):
        # Truly absent: not on PATH AND the yt_dlp module is not importable.
        _hide_ytdlp_module(monkeypatch)
        monkeypatch.setattr(shutil, "which", lambda _: None)
        ch = channel_cls()
        status, msg = ch.check()
        assert status == "off"
        assert "yt-dlp is not installed" in msg
        assert ch.active_backend is None

    def test_ok_when_ytdlp_module_importable_not_on_path(
        self, channel_cls, monkeypatch, fake_config
    ):
        # The bug scenario: yt_dlp module importable (find_spec truthy) but the
        # console script is NOT on PATH (venv/pipx). check() must still detect it.
        monkeypatch.setattr(shutil, "which", _which_factory({"ffmpeg"}))
        monkeypatch.setattr(subprocess, "run", _fake_run_version)
        ch = channel_cls()
        status, msg = ch.check(fake_config)
        assert status == "ok"
        assert ch.active_backend == "yt-dlp"

    def test_error_when_ytdlp_broken(self, channel_cls, monkeypatch):
        # Hide the module so the probe falls back to the (broken) PATH binary,
        # exercising the broken-install classification.
        _hide_ytdlp_module(monkeypatch)
        monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/yt-dlp")

        def fake_run(cmd, **kwargs):
            raise FileNotFoundError(cmd[0])

        monkeypatch.setattr(subprocess, "run", fake_run)
        ch = channel_cls()
        status, msg = ch.check()
        assert status == "error"
        assert "cannot execute" in msg
        assert ch.active_backend is None

    def test_ok_when_ytdlp_alive_no_providers(self, channel_cls, monkeypatch, fake_config):
        # yt-dlp present, ffmpeg present, but no Whisper key configured.
        monkeypatch.setattr(shutil, "which", _which_factory({"yt-dlp", "ffmpeg"}))
        monkeypatch.setattr(subprocess, "run", _fake_run_version)
        ch = channel_cls()
        status, msg = ch.check(fake_config)
        assert status == "ok"
        assert ch.active_backend == "yt-dlp"
        # No provider configured -> readiness line is omitted.
        assert "can transcribe audio" not in msg

    def test_ok_reports_provider_when_configured(self, channel_cls, monkeypatch, fake_config):
        fake_config.set("groq_api_key", "gsk_test")
        monkeypatch.setattr(shutil, "which", _which_factory({"yt-dlp", "ffmpeg"}))
        monkeypatch.setattr(subprocess, "run", _fake_run_version)
        ch = channel_cls()
        status, msg = ch.check(fake_config)
        assert status == "ok"
        assert "can transcribe audio (groq)" in msg

    def test_ok_notes_missing_ffmpeg(self, channel_cls, monkeypatch, fake_config):
        fake_config.set("groq_api_key", "gsk_test")
        # yt-dlp present but ffmpeg absent.
        monkeypatch.setattr(shutil, "which", _which_factory({"yt-dlp"}))
        monkeypatch.setattr(subprocess, "run", _fake_run_version)
        ch = channel_cls()
        status, msg = ch.check(fake_config)
        assert status == "ok"
        assert "requires ffmpeg" in msg


class TestInstagramCookiesNote:
    def test_check_mentions_cookies_from_browser(self, monkeypatch, fake_config):
        monkeypatch.setattr(shutil, "which", _which_factory({"yt-dlp", "ffmpeg"}))
        monkeypatch.setattr(subprocess, "run", _fake_run_version)
        status, msg = InstagramChannel().check(fake_config)
        assert status == "ok"
        assert "--cookies-from-browser" in msg


# --- transcribe(): delegation to searchts.transcribe ------------------- #


@pytest.mark.parametrize(
    "channel_cls,url",
    [
        (TikTokChannel, "https://www.tiktok.com/@user/video/123"),
        (InstagramChannel, "https://www.instagram.com/reel/Cabc123/"),
        (RedditVideoChannel, "https://v.redd.it/abc123"),
    ],
)
class TestTranscribeDelegation:
    def test_delegates_to_transcribe(self, channel_cls, url, monkeypatch, fake_config):
        captured = {}

        def fake_transcribe(source, *, provider="auto", out_dir=None, config=None):
            captured["source"] = source
            captured["provider"] = provider
            captured["config"] = config
            return "delegated text"

        monkeypatch.setattr(tr, "transcribe", fake_transcribe)
        out = channel_cls().transcribe(url, provider="groq", config=fake_config)
        assert out == "delegated text"
        assert captured["source"] == url
        assert captured["provider"] == "groq"
        assert captured["config"] is fake_config


# --- Registry wiring --------------------------------------------------- #


class TestRegistryWiring:
    def test_new_channels_registered(self):
        names = [ch.name for ch in get_all_channels()]
        assert "tiktok" in names
        assert "instagram" in names
        assert "reddit-video" in names

    def test_get_channel_by_name(self):
        assert isinstance(get_channel("tiktok"), TikTokChannel)
        assert isinstance(get_channel("instagram"), InstagramChannel)
        assert isinstance(get_channel("reddit-video"), RedditVideoChannel)

    def test_reddit_video_listed_before_text_reddit(self):
        names = [ch.name for ch in get_all_channels()]
        assert names.index("reddit-video") < names.index("reddit")
