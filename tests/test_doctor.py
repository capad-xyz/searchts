# -*- coding: utf-8 -*-
"""Tests for doctor module."""

import pytest

import searchts.doctor as doctor
from searchts.config import Config


class _StubChannel:
    def __init__(self, name, description, tier, status, message, backends=None,
                 active_backend=None):
        self.name = name
        self.description = description
        self.tier = tier
        self._status = status
        self._message = message
        self.backends = backends or []
        self.active_backend = active_backend

    def check(self, config=None):
        return self._status, self._message


def test_check_all_uses_reported_backends(tmp_config, monkeypatch):
    ch = _StubChannel(
        "web", "Any web page", 0, "warn",
        "Jina Reader not available (http-401)",
        ["curl_cffi", "Jina Reader", "stealth-browser"],
        active_backend="curl_cffi",
    )
    ch.reported_backends = ["curl_cffi"]
    monkeypatch.setattr(doctor, "get_all_channels", lambda: [ch])
    out = doctor.check_all(tmp_config, progress=False)
    assert out["web"]["backends"] == ["curl_cffi"]
    assert "available" not in "".join(out["web"]["backends"])


@pytest.fixture
def tmp_config(tmp_path):
    return Config(config_path=tmp_path / "config.yaml")


class TestDoctor:
    def test_check_all_collects_channel_results(self, tmp_config, monkeypatch):
        monkeypatch.setattr(
            doctor,
            "get_all_channels",
            lambda: [
                _StubChannel("web", "Web page", 0, "ok", "Can scrape web pages", ["requests"],
                             active_backend="requests"),
                _StubChannel("github", "GitHub", 0, "warn", "gh is not installed", ["gh"]),
                _StubChannel("exa_search", "Web-wide semantic search", 1, "off", "mcporter is not configured", ["Exa"]),
            ],
        )

        results = doctor.check_all(tmp_config)

        assert results == {
            "web": {
                "status": "ok",
                "name": "Web page",
                "message": "Can scrape web pages",
                "tier": 0,
                "backends": ["requests"],
                "active_backend": "requests",
            },
            "github": {
                "status": "warn",
                "name": "GitHub",
                "message": "gh is not installed",
                "tier": 0,
                "backends": ["gh"],
                "active_backend": None,
            },
            "exa_search": {
                "status": "off",
                "name": "Web-wide semantic search",
                "message": "mcporter is not configured",
                "tier": 1,
                "backends": ["Exa"],
                "active_backend": None,
            },
        }

    def test_check_all_quiet_by_default(self, tmp_config, monkeypatch, capsys):
        monkeypatch.delenv("SEARCHTS_PROGRESS", raising=False)
        monkeypatch.setattr(
            doctor,
            "get_all_channels",
            lambda: [_StubChannel("web", "Web page", 0, "ok", "Can scrape web pages")],
        )

        doctor.check_all(tmp_config)

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_check_all_progress_ticks_on_stderr(self, tmp_config, monkeypatch, capsys):
        monkeypatch.setattr(
            doctor,
            "get_all_channels",
            lambda: [
                _StubChannel("web", "Web page", 0, "ok", "Can scrape web pages"),
                _StubChannel("github", "GitHub", 0, "warn", "gh is not installed"),
            ],
        )

        doctor.check_all(tmp_config, progress=True)

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "checking web…\nchecking github…\n"

    def test_check_all_progress_env_var(self, tmp_config, monkeypatch, capsys):
        monkeypatch.setenv("SEARCHTS_PROGRESS", "1")
        monkeypatch.setattr(
            doctor,
            "get_all_channels",
            lambda: [_StubChannel("web", "Web page", 0, "ok", "Can scrape web pages")],
        )

        doctor.check_all(tmp_config)

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "checking web…" in captured.err

    def test_check_all_progress_false_ignores_env(self, tmp_config, monkeypatch, capsys):
        monkeypatch.setenv("SEARCHTS_PROGRESS", "1")
        monkeypatch.setattr(
            doctor,
            "get_all_channels",
            lambda: [_StubChannel("web", "Web page", 0, "ok", "Can scrape web pages")],
        )

        doctor.check_all(tmp_config, progress=False)

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_format_report(self):
        report = doctor.format_report(
            {
                "web": {
                    "status": "ok",
                    "name": "Web page",
                    "message": "Can scrape web pages",
                    "tier": 0,
                    "backends": ["requests"],
                },
                "exa_search": {
                    "status": "off",
                    "name": "Web-wide semantic search",
                    "message": "mcporter is not configured",
                    "tier": 1,
                    "backends": ["Exa"],
                },
                "linkedin": {
                    "status": "warn",
                    "name": "LinkedIn",
                    "message": "MCP is configured, but the health check timed out",
                    "tier": 2,
                    "backends": ["mcporter"],
                },
            }
        )

        # Strip Rich markup tags for assertion (PR #170 added [bold], [yellow] etc.)
        import re
        plain = re.sub(r"\[[^\]]*\]", "", report)
        assert "searchts" in plain
        assert "Probes (not a routing table):" in plain
        assert "1/3 probes ok" in plain
        # Inactive optional channels should be summarized in one line
        assert "optional CLIs not present" in plain

    def test_lock_note_lists_pids_and_does_not_kill(self):
        csv = '"searchts.exe","4242","Console","1","20,000 K"\n"other.exe","9","Console","1","1 K"\n'
        pids = doctor.windows_searchts_pids(runner=lambda: csv, platform="win32")
        assert pids == [4242]
        note = doctor.format_lock_note(pids)
        assert "4242" in note
        assert "does not kill" in note
        assert doctor.windows_searchts_pids(platform="linux") == []
        assert doctor.format_lock_note([]) == ""
        report = doctor.format_report(
            {"web": {"status": "ok", "name": "Web", "message": "ok", "tier": 0}},
            lock_pids=[4242],
        )
        assert "4242" in report


def test_stale_active_backend_does_not_leak_into_errored_result(monkeypatch):
    """A channel singleton's active_backend from a previous round must not leak into this round's errored result (found in Codex review)."""
    from searchts import doctor

    class _ExplodingChannel:
        name = "boom"
        description = "Exploding channel"
        tier = 0
        backends = ["a", "b"]
        active_backend = "a"  # leftover from a previous successful round

        def check(self, config=None):
            raise RuntimeError("boom")

    monkeypatch.setattr(doctor, "get_all_channels", lambda: [_ExplodingChannel()])
    results = doctor.check_all(config=None)
    assert results["boom"]["status"] == "error"
    assert results["boom"]["active_backend"] is None
