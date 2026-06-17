# -*- coding: utf-8 -*-
"""Tests for channel registry basics and health checks."""

import json
import shutil
import subprocess

from searchts.channels import get_all_channels, get_channel


class TestChannelRegistry:
    def test_get_channel_by_name(self):
        ch = get_channel("github")
        assert ch is not None
        assert ch.name == "github"

    def test_get_unknown_channel_returns_none(self):
        assert get_channel("not-exists") is None

    def test_all_channels_registered(self):
        channels = get_all_channels()
        names = [ch.name for ch in channels]
        assert "web" in names
        assert "github" in names
        assert "twitter" in names


class TestRedditChannel:
    """Multi-backend: OpenCLI > rdt-cli, no zero-config path."""

    @staticmethod
    def _isolate(monkeypatch, opencli=None):
        """Isolate the OpenCLI candidate (None = not installed) to focus on the rdt-cli path."""
        from searchts.channels.reddit import RedditChannel
        monkeypatch.setattr(RedditChannel, "_check_opencli", lambda self: opencli)

    def test_reports_off_when_nothing_installed(self, monkeypatch):
        self._isolate(monkeypatch)
        monkeypatch.setattr(shutil, "which", lambda _: None)
        from searchts.channels.reddit import RedditChannel
        status, msg = RedditChannel().check()
        assert status == "off"
        # Honest framing: explicitly says there is no zero-config path, recommends OpenCLI + rdt git source
        assert "zero-config" in msg
        assert "opencli" in msg
        assert "git+https://github.com/public-clis/rdt-cli.git" in msg

    def test_opencli_ready_wins(self, monkeypatch):
        self._isolate(monkeypatch, opencli=("ok", "OpenCLI available (reuses the browser's login session)"))
        monkeypatch.setattr(shutil, "which", lambda _: None)
        from searchts.channels.reddit import RedditChannel
        ch = RedditChannel()
        status, msg = ch.check()
        assert status == "ok"
        assert ch.active_backend == "OpenCLI"

    def test_reports_ok_when_authenticated(self, monkeypatch):
        self._isolate(monkeypatch)
        monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/rdt")
        fake_output = json.dumps({
            "ok": True,
            "schema_version": "1",
            "data": {"authenticated": True, "username": "testuser", "cookie_count": 1},
        })

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, fake_output, "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        from searchts.channels.reddit import RedditChannel
        ch = RedditChannel()
        status, msg = ch.check()
        assert status == "ok"
        assert "testuser" in msg
        assert ch.active_backend == "rdt-cli"

    def test_reports_warn_when_not_authenticated(self, monkeypatch):
        self._isolate(monkeypatch)
        monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/rdt")
        fake_output = json.dumps({
            "ok": True,
            "schema_version": "1",
            "data": {"authenticated": False, "username": None, "cookie_count": 0},
        })

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, fake_output, "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        from searchts.channels.reddit import RedditChannel
        ch = RedditChannel()
        status, msg = ch.check()
        assert status == "warn"
        assert "403" in msg
        assert "rdt login" in msg
        assert "Cookie-Editor" in msg
        assert "chromewebstore.google.com" in msg
        # Not logged in is a business state: the process is alive, so the backend still counts as usable
        assert ch.active_backend == "rdt-cli"

    def test_reports_error_when_status_check_fails(self, monkeypatch):
        """rdt non-zero exit with unparseable output -> tool error (error), no longer counts as warn."""
        self._isolate(monkeypatch)
        monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/rdt")

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, "not valid json{{{", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        from searchts.channels.reddit import RedditChannel
        ch = RedditChannel()
        status, msg = ch.check()
        assert status == "error"
        assert "rdt exited abnormally" in msg
        assert ch.active_backend is None

    def test_reports_error_with_reinstall_hint_when_broken(self, monkeypatch):
        """which hits but exec raises FileNotFoundError (broken venv) -> error + reinstall prescription."""
        self._isolate(monkeypatch)
        monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/rdt")

        def fake_run(cmd, **kwargs):
            raise FileNotFoundError("/usr/local/bin/rdt")

        monkeypatch.setattr(subprocess, "run", fake_run)
        from searchts.channels.reddit import RedditChannel
        ch = RedditChannel()
        status, msg = ch.check()
        assert status == "error"
        assert "cannot execute" in msg
        assert "pipx install --force" in msg  # rdt-specific git-source reinstall prescription
        assert "git+https://github.com/public-clis/rdt-cli.git" in msg
        assert ch.active_backend is None

    def test_reports_error_with_reinstall_hint_on_exit_127(self, monkeypatch):
        """Exit code 127 (found but won't run) is also treated as a broken install."""
        self._isolate(monkeypatch)
        monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/rdt")

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 127, "", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        from searchts.channels.reddit import RedditChannel
        ch = RedditChannel()
        status, msg = ch.check()
        assert status == "error"
        assert "pipx install --force" in msg
        assert ch.active_backend is None

    def test_can_handle_reddit_urls(self):
        from searchts.channels.reddit import RedditChannel
        ch = RedditChannel()
        assert ch.can_handle("https://www.reddit.com/r/python/comments/abc123/")
        assert ch.can_handle("https://redd.it/abc123")
        assert not ch.can_handle("https://github.com/user/repo")
        assert not ch.can_handle("https://example.com/t/123")


class TestYouTubeChannel:
    def test_reports_error_with_reinstall_hint_when_broken(self, monkeypatch):
        """yt-dlp which hits but exec raises FileNotFoundError -> error + reinstall prescription."""
        monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/yt-dlp")

        def fake_run(cmd, **kwargs):
            raise FileNotFoundError(cmd[0])

        monkeypatch.setattr(subprocess, "run", fake_run)
        from searchts.channels.youtube import YouTubeChannel
        ch = YouTubeChannel()
        status, msg = ch.check()
        assert status == "error"
        assert "cannot execute" in msg
        assert "uv tool install --force yt-dlp" in msg
        assert ch.active_backend is None


class TestGitHubChannel:
    def test_reports_error_with_reinstall_hint_when_broken(self, monkeypatch):
        """gh which hits but exec fails -> error + brew reinstall prescription (gh is not a pip package)."""
        monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/gh")

        def fake_run(cmd, **kwargs):
            raise FileNotFoundError(cmd[0])

        monkeypatch.setattr(subprocess, "run", fake_run)
        from searchts.channels.github import GitHubChannel
        ch = GitHubChannel()
        status, msg = ch.check()
        assert status == "error"
        assert "cannot execute" in msg
        assert "brew reinstall gh" in msg
        assert ch.active_backend is None

    def test_active_backend_set_when_authenticated(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/gh")

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, "Logged in to github.com", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        from searchts.channels.github import GitHubChannel
        ch = GitHubChannel()
        status, msg = ch.check()
        assert status == "ok"
        assert ch.active_backend == "gh CLI"

    def test_active_backend_set_when_unauthenticated(self, monkeypatch):
        """A non-zero exit from gh auth status is a normal business state (not logged in): warn, but the backend is usable."""
        monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/gh")

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, "", "You are not logged in")

        monkeypatch.setattr(subprocess, "run", fake_run)
        from searchts.channels.github import GitHubChannel
        ch = GitHubChannel()
        status, msg = ch.check()
        assert status == "warn"
        assert "gh auth login" in msg
        assert ch.active_backend == "gh CLI"


class TestLinkedInChannel:
    def test_reports_error_with_reinstall_hint_when_broken(self, monkeypatch):
        """mcporter which hits but exec fails -> error + npm reinstall prescription."""
        monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/mcporter")

        def fake_run(cmd, **kwargs):
            raise FileNotFoundError(cmd[0])

        monkeypatch.setattr(subprocess, "run", fake_run)
        from searchts.channels.linkedin import LinkedInChannel
        ch = LinkedInChannel()
        status, msg = ch.check()
        assert status == "error"
        assert "npm install -g mcporter" in msg
        assert ch.active_backend is None

    def test_active_backend_set_when_linkedin_configured(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/mcporter")

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, "linkedin  http://localhost:3000/mcp", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        from searchts.channels.linkedin import LinkedInChannel
        ch = LinkedInChannel()
        status, msg = ch.check()
        assert status == "ok"
        assert ch.active_backend == "linkedin-scraper-mcp"

    def test_off_without_backend_when_linkedin_not_configured(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/mcporter")

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, "exa  https://mcp.exa.ai/mcp", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        from searchts.channels.linkedin import LinkedInChannel
        ch = LinkedInChannel()
        status, msg = ch.check()
        assert status == "off"
        assert ch.active_backend is None


class TestExaSearchChannel:
    def test_reports_error_with_reinstall_hint_when_broken(self, monkeypatch):
        """mcporter which hits but exec fails -> error + npm reinstall prescription."""
        monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/mcporter")

        def fake_run(cmd, **kwargs):
            raise FileNotFoundError(cmd[0])

        monkeypatch.setattr(subprocess, "run", fake_run)
        from searchts.channels.exa_search import ExaSearchChannel
        ch = ExaSearchChannel()
        status, msg = ch.check()
        assert status == "error"
        assert "npm install -g mcporter" in msg
        assert ch.active_backend is None

    def test_active_backend_set_when_exa_configured(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/mcporter")

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, "exa  https://mcp.exa.ai/mcp", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        from searchts.channels.exa_search import ExaSearchChannel
        ch = ExaSearchChannel()
        status, msg = ch.check()
        assert status == "ok"
        assert ch.active_backend == "Exa via mcporter"
