# -*- coding: utf-8 -*-
"""Tests for searchts CLI."""

import shutil
import subprocess
from unittest.mock import patch

import pytest
import requests
import searchts.cli as cli
from searchts.cli import main


class TestCLI:
    def test_version(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["searchts", "version"]):
                main()
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "searchts v" in captured.out

    def test_no_command_shows_help(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["searchts"]):
                main()
        assert exc_info.value.code == 0

    def test_doctor_runs(self, capsys):
        with patch("sys.argv", ["searchts", "doctor"]):
            main()
        captured = capsys.readouterr()
        assert "searchts" in captured.out
        assert "✅" in captured.out

    def test_transcribe_command_prints_text(self, capsys):
        with patch("searchts.transcribe.transcribe", return_value="hello transcript"):
            with patch("sys.argv", ["searchts", "transcribe", "audio.mp3"]):
                main()
        captured = capsys.readouterr()
        assert "hello transcript" in captured.out

    def test_transcribe_command_writes_output_file(self, capsys, tmp_path):
        out_file = tmp_path / "t.txt"
        with patch("searchts.transcribe.transcribe", return_value="saved text"):
            with patch("sys.argv", ["searchts", "transcribe", "audio.mp3", "-o", str(out_file)]):
                main()
        assert out_file.read_text(encoding="utf-8").strip() == "saved text"
        assert "Transcript written" in capsys.readouterr().out

    def test_read_command_prints_text_to_stdout(self, capsys):
        from searchts.unlocker import FetchResult
        with patch("searchts.unlocker.fetch",
                   return_value=FetchResult("curl_cffi", "# Hello\n\nbody", 200)):
            with patch("sys.argv", ["searchts", "read", "https://x.test"]):
                main()
        captured = capsys.readouterr()
        assert "# Hello" in captured.out            # content on stdout
        assert "curl_cffi" in captured.err          # status on stderr
        assert "curl_cffi" not in captured.out       # stdout stays clean/pipeable

    def test_read_command_json(self, capsys):
        from searchts.unlocker import FetchResult
        with patch("searchts.unlocker.fetch",
                   return_value=FetchResult("Jina Reader", "markdown text", 200)):
            with patch("sys.argv", ["searchts", "read", "https://x.test", "--json"]):
                main()
        import json as _json
        payload = _json.loads(capsys.readouterr().out)
        assert payload == {
            "url": "https://x.test",
            "backend": "Jina Reader",
            "status": 200,
            "chars": len("markdown text"),
            "text": "markdown text",
        }

    def test_read_command_forwards_flags(self, capsys):
        from searchts.unlocker import FetchResult
        seen = {}

        def fake_fetch(url, backends=None, allow_human=False, **kwargs):
            seen["url"] = url
            seen["backends"] = backends
            seen["allow_human"] = allow_human
            return FetchResult("stealth-browser", "x" * 10, 200)

        with patch("searchts.unlocker.fetch", side_effect=fake_fetch):
            with patch("sys.argv", ["searchts", "read", "https://x.test",
                                    "--backend", "stealth-browser", "--human"]):
                main()
        assert seen["backends"] == ["stealth-browser"]
        assert seen["allow_human"] is True

    def test_read_command_failure_exits_nonzero(self, capsys):
        from searchts.unlocker import UnlockerError
        err = UnlockerError("https://x.test", [("curl_cffi", "http-403"), ("Jina Reader", "challenge")])
        with patch("searchts.unlocker.fetch", side_effect=err):
            with pytest.raises(SystemExit) as exc_info:
                with patch("sys.argv", ["searchts", "read", "https://x.test"]):
                    main()
        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert "curl_cffi: http-403" in captured.err
        assert "Jina Reader: challenge" in captured.err
        assert captured.out == ""  # nothing on stdout on failure

    def test_search_command_prints_numbered_list(self, capsys):
        from searchts.search import SearchResult
        results = [
            SearchResult("First Hit", "https://x.test/1", "a snippet", "duckduckgo"),
            SearchResult("Second Hit", "https://x.test/2", "", "brave, exa"),
        ]
        with patch("searchts.search.search", return_value=results):
            with patch("sys.argv", ["searchts", "search", "my query"]):
                main()
        out = capsys.readouterr().out
        assert "1. First Hit" in out
        assert "https://x.test/1" in out
        assert "a snippet" in out
        assert "[duckduckgo]" in out
        assert "2. Second Hit" in out
        assert "[brave, exa]" in out

    def test_search_command_json(self, capsys):
        from searchts.search import SearchResult
        results = [SearchResult("T", "https://x.test/1", "snip", "duckduckgo")]
        with patch("searchts.search.search", return_value=results):
            with patch("sys.argv", ["searchts", "search", "q", "--json"]):
                main()
        import json as _json
        payload = _json.loads(capsys.readouterr().out)
        assert payload == [
            {"title": "T", "url": "https://x.test/1", "snippet": "snip", "source": "duckduckgo"}
        ]

    def test_search_command_forwards_provider_and_n(self, capsys):
        from searchts.search import SearchResult
        seen = {}

        def fake_search(query, max_results=10, providers=None):
            seen["query"] = query
            seen["max_results"] = max_results
            seen["providers"] = providers
            return [SearchResult("T", "https://x.test/1", "", "duckduckgo")]

        with patch("searchts.search.search", side_effect=fake_search):
            with patch("sys.argv", ["searchts", "search", "q", "-n", "3",
                                    "--provider", "duckduckgo", "--provider", "brave,exa"]):
                main()
        assert seen["max_results"] == 3
        assert seen["providers"] == ["duckduckgo", "brave", "exa"]

    def test_search_command_failure_exits_nonzero(self, capsys):
        from searchts.search import SearchError
        err = SearchError("q", [("duckduckgo", "RuntimeError: boom"), ("brave", "no-results")])
        with patch("searchts.search.search", side_effect=err):
            with pytest.raises(SystemExit) as exc_info:
                with patch("sys.argv", ["searchts", "search", "q"]):
                    main()
        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert "duckduckgo: RuntimeError: boom" in captured.err
        assert "brave: no-results" in captured.err
        assert captured.out == ""

    def test_parse_provider_flags_flattens_comma_lists(self):
        assert cli._parse_provider_flags(None) is None
        assert cli._parse_provider_flags(["duckduckgo", "Brave,EXA", "brave"]) == [
            "duckduckgo", "brave", "exa"
        ]

    def test_parse_twitter_cookie_input_separate_values(self):
        auth_token, ct0 = cli._parse_twitter_cookie_input("token123 ct0abc")
        assert auth_token == "token123"
        assert ct0 == "ct0abc"

    def test_parse_twitter_cookie_input_cookie_header(self):
        auth_token, ct0 = cli._parse_twitter_cookie_input(
            "auth_token=token123; ct0=ct0abc; other=value"
        )
        assert auth_token == "token123"
        assert ct0 == "ct0abc"

    def test_install_rdt_cli_prefers_github_source(self, monkeypatch, capsys):
        state = {"rdt_installed": False}
        commands = []

        def fake_which(name):
            if name == "rdt":
                return "/usr/local/bin/rdt" if state["rdt_installed"] else None
            if name == "pipx":
                return "/usr/local/bin/pipx"
            return None

        def fake_run(cmd, **kwargs):
            commands.append(cmd)
            state["rdt_installed"] = True
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(shutil, "which", fake_which)
        monkeypatch.setattr(subprocess, "run", fake_run)

        cli._install_rdt_cli()

        out = capsys.readouterr().out
        assert commands == [["pipx", "install", cli._RDT_GIT_SOURCE]]
        assert "✅ rdt-cli installed" in out

    def test_install_reddit_deps_routes_by_environment(self, monkeypatch):
        """Desktop -> OpenCLI; server -> rdt-cli (pinned git source)."""
        calls = []
        monkeypatch.setattr(cli, "_install_opencli_deps", lambda: calls.append("opencli"))
        monkeypatch.setattr(cli, "_install_rdt_cli", lambda: calls.append("rdt"))
        monkeypatch.setattr(shutil, "which", lambda _: None)

        monkeypatch.setattr(cli, "_detect_environment", lambda: "local")
        cli._install_reddit_deps()
        assert calls == ["opencli"]

        calls.clear()
        monkeypatch.setattr(cli, "_detect_environment", lambda: "server")
        cli._install_reddit_deps()
        assert calls == ["rdt"]


class TestCheckUpdateRetry:
    def test_retry_timeout_classification(self):
        sleeps = []

        def fake_sleep(seconds):
            sleeps.append(seconds)

        with patch("requests.get", side_effect=requests.exceptions.Timeout("timed out")):
            resp, err, attempts = cli._github_get_with_retry(
                "https://api.github.com/test",
                timeout=1,
                retries=3,
                sleeper=fake_sleep,
            )

        assert resp is None
        assert err == "timeout"
        assert attempts == 3
        assert sleeps == [1, 2]

    def test_retry_dns_classification(self):
        error = requests.exceptions.ConnectionError("getaddrinfo failed for api.github.com")
        with patch("requests.get", side_effect=error):
            resp, err, attempts = cli._github_get_with_retry(
                "https://api.github.com/test",
                retries=1,
                sleeper=lambda _x: None,
            )
        assert resp is None
        assert err == "dns"
        assert attempts == 1

    def test_retry_rate_limit_then_success(self):
        sleeps = []

        class R:
            def __init__(self, code, payload=None, headers=None):
                self.status_code = code
                self._payload = payload or {}
                self.headers = headers or {}

            def json(self):
                return self._payload

        sequence = [
            R(429, headers={"Retry-After": "3"}),
            R(200, payload={"tag_name": "v1.5.0"}),
        ]

        with patch("requests.get", side_effect=sequence):
            resp, err, attempts = cli._github_get_with_retry(
                "https://api.github.com/test",
                retries=3,
                sleeper=lambda s: sleeps.append(s),
            )

        assert err is None
        assert resp is not None
        assert resp.status_code == 200
        assert attempts == 2
        assert sleeps == [3.0]

    def test_classify_rate_limit_from_403(self):
        class R:
            status_code = 403
            headers = {"X-RateLimit-Remaining": "0"}

            @staticmethod
            def json():
                return {"message": "API rate limit exceeded"}

        assert cli._classify_github_response_error(R()) == "rate_limit"

    def test_check_update_reports_classified_error(self, capsys):
        with patch("searchts.cli._github_get_with_retry", return_value=(None, "timeout", 3)):
            result = cli._cmd_check_update()

        captured = capsys.readouterr()
        assert result == "error"
        assert "Network timeout" in captured.out
        assert "retried 3 times" in captured.out


class TestVersionCompare:
    def test_newer_remote_triggers_update(self):
        assert cli._is_newer_version("1.5.0", "1.4.2") is True

    def test_equal_versions_no_update(self):
        assert cli._is_newer_version("1.5.0", "1.5.0") is False

    def test_local_ahead_of_release_no_downgrade_prompt(self):
        """During a release window, when main (newer) is installed locally, it must not prompt "update available" and lure a downgrade."""
        assert cli._is_newer_version("1.4.2", "1.5.0") is False

    def test_unparseable_falls_back_to_inequality(self):
        assert cli._is_newer_version("2026.06-beta", "1.5.0") is True
        assert cli._is_newer_version("1.5.0", "1.5.0-dev") is True


class TestWatchVersionCompare:
    def test_watch_does_not_prompt_downgrade(self, monkeypatch, capsys):
        """watch has the same semantics as check-update: do not prompt for an update when local is ahead of the remote release."""
        class R:
            status_code = 200
            headers = {}

            @staticmethod
            def json():
                return {"tag_name": "v0.0.9", "body": ""}

        monkeypatch.setattr(cli, "_github_get_with_retry", lambda *a, **k: (R(), None, 1))
        monkeypatch.setattr(
            "searchts.doctor.check_all",
            lambda config: {"web": {"status": "ok", "name": "Any web page", "message": "ok",
                            "tier": 0, "backends": ["Jina Reader"], "active_backend": "Jina Reader"}},
        )
        cli._cmd_watch()
        out = capsys.readouterr().out
        assert "New version available" not in out
        assert "All systems normal" in out
