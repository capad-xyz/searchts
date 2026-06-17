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
        assert "Ready to use out of the box:" in plain
        assert "1/3 channels available" in plain
        # Inactive optional channels should be summarized in one line
        assert "optional channels can be unlocked" in plain


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
