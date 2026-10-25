# -*- coding: utf-8 -*-
"""Tests for searchts CLI."""

import json
import os
import pathlib
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
        assert "searchts doctor" in captured.out
        assert "probes passed" in captured.out
        # CLI output is plain ASCII — no decorative emoji glyphs.
        assert "✅" not in captured.out
        assert "❌" not in captured.out

    def test_doctor_does_not_install_skill(self, monkeypatch):
        called = {"skill": False}

        def _must_not_install():
            called["skill"] = True

        monkeypatch.setattr(cli, "_install_skill", _must_not_install)
        monkeypatch.setattr(
            "searchts.doctor.check_all",
            lambda config, progress=False: {                "web": {
                    "status": "ok",
                    "name": "Any web page",
                    "message": "ok",
                    "tier": 0,
                    "backends": ["curl_cffi"],
                    "active_backend": "curl_cffi",
                }
            },
        )
        monkeypatch.setattr(
            "searchts.integrations.agent_wiring.format_wiring_report",
            lambda: "",
        )
        with patch("sys.argv", ["searchts", "doctor"]):
            main()
        assert called["skill"] is False

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
        printed = capsys.readouterr().out
        assert str(out_file) in printed
        assert "[ok]" not in printed

    def test_transcribe_command_accepts_provider_local(self, capsys):
        seen = {}

        def fake_transcribe(source, *, provider="auto", prefer_subtitles=True,
                            progress=None, cookies_from_browser=None):
            seen["provider"] = provider
            seen["prefer_subtitles"] = prefer_subtitles
            return "local out"

        with patch("searchts.transcribe.transcribe", side_effect=fake_transcribe):
            with patch("sys.argv", ["searchts", "transcribe", "audio.mp3", "--provider", "local"]):
                main()
        assert seen["provider"] == "local"
        # Subtitles-first is the default; the flag was not passed.
        assert seen["prefer_subtitles"] is True
        assert "local out" in capsys.readouterr().out

    def test_transcribe_command_no_subtitles_flag(self, capsys):
        seen = {}

        def fake_transcribe(source, *, provider="auto", prefer_subtitles=True,
                            progress=None, cookies_from_browser=None):
            seen["prefer_subtitles"] = prefer_subtitles
            return "audio out"

        with patch("searchts.transcribe.transcribe", side_effect=fake_transcribe):
            with patch(
                "sys.argv",
                ["searchts", "transcribe", "https://youtu.be/x", "--no-subtitles"],
            ):
                main()
        # --no-subtitles forces the audio path.
        assert seen["prefer_subtitles"] is False
        assert "audio out" in capsys.readouterr().out

    def test_transcribe_command_rejects_unknown_provider(self):
        with patch("sys.argv", ["searchts", "transcribe", "audio.mp3", "--provider", "azure"]):
            with pytest.raises(SystemExit):
                main()

    def test_transcribe_command_passes_progress_true(self, capsys):
        seen = {}

        def fake_transcribe(source, *, provider="auto", prefer_subtitles=True,
                            progress=None, cookies_from_browser=None):
            seen["progress"] = progress
            return "out"

        with patch("searchts.transcribe.transcribe", side_effect=fake_transcribe):
            with patch("sys.argv", ["searchts", "transcribe", "audio.mp3"]):
                main()
        # CLI enables progress ticks (P4.6).
        assert seen["progress"] is True

    def test_transcribe_command_passes_cookies_from_browser(self, capsys):
        seen = {}

        def fake_transcribe(source, *, provider="auto", prefer_subtitles=True,
                            progress=None, cookies_from_browser=None):
            seen["cookies"] = cookies_from_browser
            return "out"

        with patch("searchts.transcribe.transcribe", side_effect=fake_transcribe):
            with patch(
                "sys.argv",
                ["searchts", "transcribe", "https://youtu.be/x",
                 "--cookies-from-browser", "chrome"],
            ):
                main()
        assert seen["cookies"] == "chrome"

    def test_read_has_no_cookies_from_browser_flag(self):
        with pytest.raises(SystemExit):
            with patch(
                "sys.argv",
                ["searchts", "read", "https://example.com",
                 "--cookies-from-browser", "chrome"],
            ):
                main()

    def test_unknown_subcommand_suggests_nearest_match(self, capsys, monkeypatch):
        monkeypatch.delenv("SEARCHTS_PROGRESS_TTY", raising=False)
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["searchts", "reserch", "x"]):
                main()
        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert "did you mean 'search'?" in captured.err
        assert "invalid choice" in captured.err

    def test_unknown_subcommand_draws_a_receipt_on_a_terminal(self, capsys, monkeypatch):
        monkeypatch.setenv("SEARCHTS_PROGRESS_TTY", "1")
        monkeypatch.delenv("TERM", raising=False)
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["searchts", "config"]):
                main()
        assert exc_info.value.code == 2
        err = capsys.readouterr().err
        assert "unknown command: config" in err
        assert "did you mean" in err
        assert "configure" in err
        # The list is rows a person can read, not argparse's one wrapped line.
        assert "COMMANDS" in err
        assert "Fetch a page as markdown, or fail and say why." in err
        assert "usage:" not in err
        assert "invalid choice" not in err

    def test_unknown_subcommand_without_a_match_still_lists_commands(self, capsys, monkeypatch):
        monkeypatch.setenv("SEARCHTS_PROGRESS_TTY", "1")
        monkeypatch.delenv("TERM", raising=False)
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["searchts", "zzzzzz"]):
                main()
        assert exc_info.value.code == 2
        err = capsys.readouterr().err
        assert "unknown command: zzzzzz" in err
        assert "did you mean" not in err
        assert "COMMANDS" in err
        assert "usage:" not in err

    def test_unknown_subcommand_stays_plain_on_a_dumb_terminal(self, capsys, monkeypatch):
        monkeypatch.setenv("SEARCHTS_PROGRESS_TTY", "1")
        monkeypatch.setenv("TERM", "dumb")
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["searchts", "config"]):
                main()
        assert exc_info.value.code == 2
        err = capsys.readouterr().err
        assert "usage:" in err
        assert "invalid choice" in err
        assert "COMMANDS" not in err

    def test_valid_subcommand_does_not_suggest_match(self, capsys):
        from searchts.search import SearchResult
        with patch("searchts.search.search", return_value=[SearchResult("T", "https://x.test", "", "")]):
            with patch("sys.argv", ["searchts", "search", "q"]):
                main()
        assert "did you mean" not in capsys.readouterr().err

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
                   return_value=FetchResult(
                       "Jina Reader", "markdown text", 200,
                       final_url="https://x.test/final",
                       fetched_at="2026-07-09T12:00:00Z",
                   )):
            with patch("sys.argv", ["searchts", "read", "https://x.test", "--json"]):
                main()
        import json as _json
        payload = _json.loads(capsys.readouterr().out)
        assert payload == {
            "url": "https://x.test",
            "final_url": "https://x.test/final",
            "fetched_at": "2026-07-09T12:00:00Z",
            "backend": "Jina Reader",
            "status": 200,
            "chars": len("markdown text"),
            # F27: the receipt says whether this answer came from a request
            # carrying session cookies, so a logged-in read and an anonymous one
            # are distinguishable. False here: no cookies were asked for.
            "authenticated": False,
            "text": "markdown text",
            "next_url": None,
            "more": [],
            "pages": [{"url": "https://x.test/final", "text": "markdown text", "next_url": None}],
            # #430: every automatic cookie action, or skip and why. Empty here:
            # this read asked for no cookies.
            "cookie_actions": [],
        }

    def test_read_command_forwards_flags(self, capsys):
        from searchts.unlocker import FetchResult
        seen = {}

        def fake_fetch(url, backends=None, allow_human=False, **kwargs):
            seen["url"] = url
            seen["backends"] = backends
            seen["allow_human"] = allow_human
            seen["progress"] = kwargs.get("progress")
            seen["echo_attempts"] = kwargs.get("echo_attempts")
            return FetchResult("stealth-browser", "x" * 10, 200)

        with patch("searchts.unlocker.fetch", side_effect=fake_fetch):
            with patch("sys.argv", ["searchts", "read", "https://x.test",
                                    "--backend", "stealth-browser", "--human"]):
                main()
        assert seen["backends"] == ["stealth-browser"]
        assert seen["allow_human"] is True
        # A captured stderr is not a terminal: the ladder stays quiet and the
        # failure block owns the reasons (see progress.Tracker.wants).
        assert seen["progress"] is False

    def test_read_json_does_not_narrate(self, capsys):
        from searchts.unlocker import FetchResult
        seen = {}

        def fake_fetch(url, backends=None, allow_human=False, **kwargs):
            seen["progress"] = kwargs.get("progress")
            return FetchResult("curl_cffi", "markdown text", 200)

        with patch("searchts.unlocker.fetch", side_effect=fake_fetch):
            with patch("sys.argv", ["searchts", "read", "https://x.test", "--json"]):
                main()
        assert seen["progress"] is False
        captured = capsys.readouterr()
        assert "trying" not in captured.err

    def test_read_command_failure_exits_nonzero(self, capsys):
        from searchts.unlocker import UnlockerError
        err = UnlockerError("https://x.test", [("curl_cffi", "http-403"), ("Jina Reader", "challenge")])
        with patch("searchts.unlocker.fetch", side_effect=err):
            with pytest.raises(SystemExit) as exc_info:
                with patch("sys.argv", ["searchts", "read", "https://x.test"]):
                    main()
        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert "curl_cffi" in captured.err
        assert "http-403" in captured.err
        assert "Jina Reader" in captured.err
        assert "challenge" in captured.err
        assert "\u2717 read" in captured.err
        assert captured.out == ""  # nothing on stdout on failure

    def test_read_json_failure_returns_machine_error_and_keeps_receipt_on_stderr(self, capsys):
        import json

        from searchts.unlocker import UnlockerError

        err = UnlockerError("https://x.test", [("curl_cffi", "ssrf: private address")])
        with patch("searchts.unlocker.fetch", side_effect=err):
            with pytest.raises(SystemExit) as exc_info:
                with patch("sys.argv", ["searchts", "read", "https://x.test", "--json"]):
                    main()
        captured = capsys.readouterr()
        assert exc_info.value.code == 1
        payload = json.loads(captured.out)
        assert payload["error"] == "URL could not be read"
        assert payload["url"] == "https://x.test"
        assert payload["attempts"] == [{"backend": "curl_cffi", "reason": "ssrf: private address"}]
        assert "curl_cffi" in captured.err

    def test_read_json_invalid_url_returns_machine_error_and_exit_two(self, capsys):
        import json

        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["searchts", "read", "not a url", "--json"]):
                main()
        captured = capsys.readouterr()
        assert exc_info.value.code == 2
        assert json.loads(captured.out)["error"]
        assert "searchts read:" in captured.err

    def test_search_command_prints_numbered_list(self, capsys):
        from searchts.search import SearchResult
        results = [
            SearchResult("First Hit", "https://x.test/1", "a snippet", "duckduckgo"),
            SearchResult("Second Hit", "https://x.test/2", "", "brave, exa"),
        ]
        with patch("searchts.search.search", return_value=results):
            with patch("sys.argv", ["searchts", "search", "my query"]):
                main()
        captured = capsys.readouterr()
        out = captured.out
        assert out.startswith("Snippets are not the page. Read each URL.")
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
        captured = capsys.readouterr()
        payload = _json.loads(captured.out)
        assert "Snippets are not the page." in captured.err
        assert payload == [
            {"title": "T", "url": "https://x.test/1", "snippet": "snip", "source": "duckduckgo"}
        ]

    def test_search_command_forwards_provider_and_n(self, capsys):
        from searchts.search import SearchResult
        seen = {}

        def fake_search(query, max_results=10, providers=None, progress=None):
            seen["query"] = query
            seen["max_results"] = max_results
            seen["providers"] = providers
            seen["progress"] = progress
            return [SearchResult("T", "https://x.test/1", "", "duckduckgo")]

        with patch("searchts.search.search", side_effect=fake_search):
            with patch("sys.argv", ["searchts", "search", "q", "-n", "3",
                                    "--provider", "duckduckgo", "--provider", "brave,exa"]):
                main()
        assert seen["max_results"] == 3
        assert seen["providers"] == ["duckduckgo", "brave", "exa"]
        assert seen["progress"] is True

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
        assert "\u2713 rdt-cli installed" in out

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


class TestInstallNonInvasive:
    """`searchts install` must NOT mutate the system unless --system-deps is given."""

    def _stub_install(self, monkeypatch):
        """Stub everything _cmd_install touches except the system-deps/mcporter
        branch, and record which variant (real vs safe) gets called."""
        calls = []
        monkeypatch.setattr(cli, "_install_system_deps", lambda: calls.append("system_real"))
        monkeypatch.setattr(cli, "_install_system_deps_safe", lambda: calls.append("system_safe"))
        monkeypatch.setattr(cli, "_install_system_deps_dryrun", lambda: calls.append("system_dry"))
        monkeypatch.setattr(cli, "_install_mcporter", lambda: calls.append("mcporter_real"))
        monkeypatch.setattr(cli, "_install_mcporter_safe", lambda: calls.append("mcporter_safe"))
        monkeypatch.setattr(cli, "_install_skill", lambda: None)
        monkeypatch.setattr(cli, "_detect_environment", lambda: "local")
        monkeypatch.setattr(
            "searchts.doctor.check_all",
            lambda config, **_k: {"web": {"status": "ok", "name": "Any web page", "message": "ok",
                                 "tier": 0, "backends": ["Jina Reader"], "active_backend": "Jina Reader"}},
        )
        return calls

    def test_default_is_non_invasive(self, capsys, monkeypatch):
        calls = self._stub_install(monkeypatch)
        with patch("sys.argv", ["searchts", "install"]):
            main()
        # No real (mutating) system installers ran; only the print-only variants.
        assert "system_real" not in calls
        assert "mcporter_real" not in calls
        assert "system_safe" in calls
        assert "mcporter_safe" in calls
        out = capsys.readouterr().out
        assert "Install (default)" in out
        assert "user-scope agent files may be written" in out
        assert "--system-deps" in out

    def test_system_deps_flag_opts_in(self, capsys, monkeypatch):
        calls = self._stub_install(monkeypatch)
        with patch("sys.argv", ["searchts", "install", "--system-deps"]):
            main()
        assert "system_real" in calls
        assert "mcporter_real" in calls
        assert "system_safe" not in calls

    def test_apply_alias_opts_in(self, capsys, monkeypatch):
        calls = self._stub_install(monkeypatch)
        with patch("sys.argv", ["searchts", "install", "--apply"]):
            main()
        assert "system_real" in calls
        assert "mcporter_real" in calls

    def test_safe_flag_is_noop_still_non_invasive(self, capsys, monkeypatch):
        """--safe is now the default behavior, so it must remain non-invasive."""
        calls = self._stub_install(monkeypatch)
        with patch("sys.argv", ["searchts", "install", "--safe"]):
            main()
        assert "system_real" not in calls
        assert "mcporter_real" not in calls

    def test_dry_run_lists_real_run_destinations_without_writing(
        self, capsys, monkeypatch, tmp_path
    ):
        calls = self._stub_install(monkeypatch)
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(
            "searchts.config.Config.CONFIG_FILE", tmp_path / ".searchts" / "config.yaml"
        )
        with patch("sys.argv", ["searchts", "install", "--dry-run"]):
            main()
        assert "system_real" not in calls
        assert "mcporter_real" not in calls
        assert "system_dry" in calls
        output = capsys.readouterr().out
        assert "Install destinations" in output
        assert ".searchts/tools" in output
        assert ".agents/skills/searchts" in output
        assert not (tmp_path / ".searchts").exists()


class TestSetupRecommendsFirstPartySearch:
    """`searchts setup` recommends the keyless first-party search, not mcporter/Exa."""

    def test_setup_recommends_searchts_search(self, capsys, monkeypatch):
        # No mcporter present -> the optional Exa block is skipped entirely.
        monkeypatch.setattr(shutil, "which", lambda _name: None)
        # Skip the interactive token/key prompts.
        monkeypatch.setattr("builtins.input", lambda *_a, **_k: "")
        with patch("sys.argv", ["searchts", "setup"]):
            main()
        out = capsys.readouterr().out
        assert "[Recommended]" in out
        assert "searchts search" in out
        # mcporter is not presented as the recommended path.
        assert "[Recommended] Web-wide search -- Exa (via mcporter)" not in out


class TestSetupWithoutAConsole:
    """`searchts setup` finishes when there is no console to ask.

    Measured 2026-10-20: `searchts setup` with stdin closed died with an
    EOFError traceback and exit 1. The wizard's own prompt says "press Enter
    to skip", so a closed stdin is the same answer as an empty line, and a
    script or a CI job should get the steps that need no answer rather than a
    stack trace.
    """

    def test_setup_finishes_when_stdin_is_closed(self, capsys, monkeypatch, tmp_home):
        monkeypatch.setattr(shutil, "which", lambda _name: None)

        def eof(_prompt=""):
            raise EOFError

        monkeypatch.setattr("builtins.input", eof)
        with patch("sys.argv", ["searchts", "setup"]):
            main()
        captured = capsys.readouterr()
        assert "Traceback" not in captured.err
        assert "EOFError" not in captured.err
        assert "Skipped" in captured.out
        assert "searchts doctor" in captured.out


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

    def test_release_rows_drops_the_repeated_whats_changed_copy(self):
        body = (
            "### Added\n"
            "* **cli:** live progression and receipts "
            "([#412](https://x/412)) ([7a9649b](https://x/7a9649b))\n"
            "### Fixed\n"
            "* **read:** keep looking ([#414](https://x/414)) "
            "([8b18035](https://x/8b18035))\n"
            "## What's Changed\n"
            "* feat(cli): live progression and receipts by @capad in "
            "https://x/pull/412\n"
            "* fix(read): keep looking by @capad in https://x/pull/414\n"
            "* chore(main): release 0.18.0 by @capad in https://x/pull/415\n"
            "**Full Changelog**: https://x/compare\n"
        )
        assert cli._release_rows(body) == [
            ("cli", "live progression and receipts"),
            ("read", "keep looking"),
        ]

    def test_check_update_live_block_has_one_loading_row(self, monkeypatch, capsys):
        class R:
            status_code = 200

            @staticmethod
            def json():
                return {
                    "tag_name": "v2.0.0",
                    "body": (
                        "## What's Changed\n"
                        "* feat(cli): add a live frame to check-update\n"
                        "* fix(read): keep the failure ladder\n"
                        "**Full Changelog**: https://example.test/compare\n"
                    ),
                }

        monkeypatch.setenv("SEARCHTS_PROGRESS_TTY", "1")
        monkeypatch.setenv("SEARCHTS_PROGRESS_WIDTH", "78")
        monkeypatch.setattr("searchts.__version__", "1.0.0")
        with patch("searchts.cli._github_get_with_retry", return_value=(R(), None, 0)):
            result = cli._cmd_check_update()

        captured = capsys.readouterr()
        assert result == "update_available"
        assert "checking GitHub releases" in captured.err
        assert "Current version:" not in captured.err
        assert "current" in captured.out
        assert "v2.0.0" in captured.out
        assert "cli" in captured.out
        assert "live frame" in captured.out
        assert "searchts update" in captured.out
        # GitHub markdown is source material, never the receipt.
        assert "## What's Changed" not in captured.out
        assert "Full Changelog" not in captured.out

    def test_check_update_ticks_on_stderr(self, capsys):
        with patch("searchts.cli._github_get_with_retry", return_value=(None, "timeout", 3)):
            cli._cmd_check_update()
        captured = capsys.readouterr()
        # Best-effort tick so a slow GitHub round-trip is not silent (P4.6).
        assert "checking for updates" in captured.err


    def test_update_instructions_are_pipx_first(self):
        text = cli._UPDATE_INSTRUCTIONS
        assert "searchts update" in text
        assert "searchts upgrade" in text
        assert "pipx upgrade searchts --include-injected" in text
        assert "main.zip" not in text
        assert "pip install -U" in text


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
            lambda config, **_k: {"web": {"status": "ok", "name": "Any web page", "message": "ok",
                                 "tier": 0, "backends": ["Jina Reader"], "active_backend": "Jina Reader"}},
        )
        cli._cmd_watch()
        captured = capsys.readouterr()
        out = captured.out
        assert "New version available" not in out
        assert "All systems normal" in out
        # P4.6: best-effort ticks so the channel + update round-trips are not silent.
        assert "checking channels" in captured.err
        assert "checking for updates" in captured.err


_HOME_ENV = ("APPDATA", "COPILOT_HOME", "OPENCLAW_HOME", "XDG_CONFIG_HOME")


def _real_home_snapshot():
    """Bytes of configs `mcp install` / `skill install` must not touch."""
    home = pathlib.Path.home()
    paths = [
        home / ".claude.json",
        home / ".claude" / "CLAUDE.md",
        home / ".claude" / "commands" / "searchts.md",
        home / ".claude" / "skills" / "searchts" / "SKILL.md",
        home / ".agents" / "skills" / "searchts" / "SKILL.md",
        home / ".cursor" / "mcp.json",
        home / ".codex" / "config.toml",
        home / ".gemini" / "settings.json",
        home / ".copilot" / "mcp-config.json",
        home / ".config" / "opencode" / "opencode.json",
        home / ".codeium" / "windsurf" / "mcp_config.json",
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        root = pathlib.Path(appdata)
        paths.extend([
            root / "Claude" / "claude_desktop_config.json",
            root / "Code" / "User" / "mcp.json",
            root / "devin" / "mcp_config.json",
        ])
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def _isolate_home(monkeypatch, home):
    monkeypatch.setattr(
        pathlib.Path, "home", classmethod(lambda cls, _home=home: _home),
    )
    for key in _HOME_ENV:
        monkeypatch.delenv(key, raising=False)


def _assert_home_unchanged(before):
    after = {path: path.read_bytes() if path.exists() else None for path in before}
    assert after == before


class TestMcpInstall:
    def test_mcp_install_text_all_clients(self):
        text = cli.mcp_install_text()
        # Claude Code one-liner.
        assert "claude mcp add searchts" in text
        # JSON snippet keys/args.
        assert '"searchts"' in text
        assert '"mcp"' in text
        assert '"serve"' in text
        # PATH note present: uvx or pipx which when the host cannot see pipx bin.
        assert "PATH" in text
        assert "uvx --from" in text
        assert "pipx which searchts" in text

    def test_mcp_install_text_claude_only(self):
        text = cli.mcp_install_text("claude")
        assert "claude mcp add searchts -- searchts mcp serve" in text
        assert "PATH" in text
        # No JSON snippet when claude-only.
        assert '"mcpServers"' not in text

    def test_mcp_install_text_cursor_json(self):
        for client in ("cursor", "json"):
            text = cli.mcp_install_text(client)
            assert '"mcpServers"' in text
            assert '"searchts"' in text
            assert '"mcp"' in text
            assert '"serve"' in text

    def test_mcp_install_command_prints(self, capsys, tmp_path, monkeypatch):
        before = _real_home_snapshot()
        _isolate_home(monkeypatch, tmp_path / "home")
        with patch("sys.argv", ["searchts", "mcp", "install"]):
            main()
        out = capsys.readouterr().out
        assert "claude mcp add searchts" in out
        assert '"searchts"' in out
        assert '"serve"' in out
        _assert_home_unchanged(before)

    def test_mcp_install_writes_a_client_already_on_the_machine(self, capsys, tmp_path, monkeypatch):
        before = _real_home_snapshot()
        home = tmp_path / "home"
        (home / ".cursor").mkdir(parents=True)
        _isolate_home(monkeypatch, home)
        monkeypatch.chdir(tmp_path)
        with patch("sys.argv", ["searchts", "mcp", "install"]):
            main()
        captured = capsys.readouterr()
        saved = json.loads((home / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
        assert saved["mcpServers"]["searchts"]["command"] == "searchts"
        assert saved["mcpServers"]["searchts"]["args"] == ["mcp", "serve"]
        assert "wrote" in captured.err
        assert "claude mcp add searchts" in captured.out
        _assert_home_unchanged(before)

    def test_mcp_serve_missing_mcp_exits_with_actionable_message(self, capsys, monkeypatch):
        """`mcp serve` without the mcp pkg must exit nonzero with a pip hint, not hang."""
        from searchts.integrations import mcp_server

        # Simulate the optional dependency being absent.
        monkeypatch.setattr(mcp_server, "HAS_MCP", False)

        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["searchts", "mcp", "serve"]):
                main()
        assert exc_info.value.code != 0
        err = capsys.readouterr().err
        assert 'pip install "searchts[mcp]"' in err

    def test_mcp_serve_invokes_serve_when_available(self, monkeypatch):
        """When mcp is importable, `mcp serve` calls serve() (no hang in tests)."""
        from searchts.integrations import mcp_server

        called = {}
        monkeypatch.setattr(mcp_server, "HAS_MCP", True)
        monkeypatch.setattr(mcp_server, "serve", lambda **k: called.setdefault("ran", True) or called.update(k))

        with patch("sys.argv", ["searchts", "mcp", "serve"]):
            main()
        assert called.get("ran") is True

    def test_mcp_serve_http_passes_transport(self, monkeypatch):
        from searchts.integrations import mcp_server

        seen = {}
        monkeypatch.setattr(mcp_server, "HAS_MCP", True)

        def fake_serve(**kwargs):
            seen.update(kwargs)

        monkeypatch.setattr(mcp_server, "serve", fake_serve)
        with patch("sys.argv", ["searchts", "mcp", "serve", "--http", "--port", "9001"]):
            main()
        assert seen.get("transport") == "http"
        assert seen.get("host") == "127.0.0.1"
        assert seen.get("port") == 9001

    def test_mcp_serve_http_rejects_public_host(self, capsys, monkeypatch):
        from searchts.integrations import mcp_server

        monkeypatch.setattr(mcp_server, "HAS_MCP", True)
        monkeypatch.setattr(mcp_server, "serve", lambda **k: (_ for _ in ()).throw(AssertionError("no")))
        with pytest.raises(SystemExit) as exc:
            with patch("sys.argv", ["searchts", "mcp", "serve", "--http", "--host", "0.0.0.0"]):
                main()
        assert exc.value.code == 2
        assert "loopback" in capsys.readouterr().err.lower()

    def test_mcp_serve_http_and_sse_conflict(self, capsys, monkeypatch):
        from searchts.integrations import mcp_server

        monkeypatch.setattr(mcp_server, "HAS_MCP", True)
        with pytest.raises(SystemExit) as exc:
            with patch("sys.argv", ["searchts", "mcp", "serve", "--http", "--sse"]):
                main()
        assert exc.value.code == 2
        assert "not both" in capsys.readouterr().err

    def test_mcp_install_text_mentions_loopback_http(self):
        text = cli.mcp_install_text()
        assert "mcp serve --http" in text
        assert "127.0.0.1:8765/mcp" in text


class TestSkillInstallSlashCommand:
    def test_skill_install_writes_searchts_md(self, capsys, tmp_path, monkeypatch):
        before = _real_home_snapshot()
        home = tmp_path / "home"
        _isolate_home(monkeypatch, home)
        target = tmp_path / "commands"
        with patch("sys.argv", ["searchts", "skill", "install", "--dir", str(target)]):
            main()
        captured = capsys.readouterr()
        out_file = target / "searchts.md"
        assert out_file.exists()
        body = out_file.read_text(encoding="utf-8")
        assert "searchts read" in body
        assert "searchts search" in body
        assert "searchts transcribe" in body
        # Prefer searchts over built-in fetch for blocked pages.
        assert "WebFetch" in body or "built-in fetch" in body
        # Stdout is the slash-command path. The bundle and the reach rule are stderr.
        assert captured.out.strip() == str(out_file)
        assert "reach rule" not in captured.out
        assert "skill install" in captured.err
        for skill in (
            home / ".agents" / "skills" / "searchts" / "SKILL.md",
            home / ".claude" / "skills" / "searchts" / "SKILL.md",
        ):
            assert skill.is_file()
            assert "name: searchts" in skill.read_text(encoding="utf-8")
        assert (home / ".agents" / "skills" / "searchts" / "references" / "web.md").is_file()
        assert (home / ".claude" / "CLAUDE.md").is_file()
        assert not (home / ".openclaw").exists()
        _assert_home_unchanged(before)

    def test_skill_install_creates_missing_dir(self, tmp_path):
        target = tmp_path / "nested" / "claude" / "commands"
        assert not target.exists()
        path = cli.write_slash_command(str(target))
        assert os.path.exists(path)
        assert os.path.basename(path) == "searchts.md"

    def test_skill_install_default_dir_not_touched_in_tests(self, tmp_path):
        """The slash-command default is ~/.claude/commands. Callers pass --dir."""
        default_dir = cli._slash_command_target_dir(None)
        assert default_dir.endswith(os.path.join(".claude", "commands"))
        # With an explicit dir we stay inside tmp_path.
        resolved = cli._slash_command_target_dir(str(tmp_path / "x"))
        assert str(tmp_path) in resolved


class TestYtdlpConfigInstall:
    """The yt-dlp JS-runtime installer must write to the OS-correct config path (B2)."""

    def _stub_system_commands(self, monkeypatch):
        """Make gh/node/npm look already-present so _install_system_deps reaches
        the yt-dlp config block without running any real installer."""
        monkeypatch.setattr(
            shutil, "which", lambda cmd: f"/usr/bin/{cmd}" if cmd in {"gh", "node", "npm"} else None
        )

        def fake_run(cmd, **kwargs):
            # `npm root -g` returns a path with no undici, so the undici branch
            # tries `npm install -g undici` — also stubbed here. stdout is empty
            # so the undici path check fails harmlessly.
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(subprocess, "run", fake_run)

    def test_install_writes_to_appdata_path_on_win32(self, tmp_path, monkeypatch, capsys):
        import searchts.utils.paths as paths

        appdata = tmp_path / "AppData" / "Roaming"
        appdata.mkdir(parents=True)
        monkeypatch.setattr(paths.sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", str(appdata))
        self._stub_system_commands(monkeypatch)

        cli._install_system_deps()

        expected = appdata / "yt-dlp" / "config"
        assert expected.exists(), "config must be written under %APPDATA%\\yt-dlp"
        assert "--js-runtimes node" in expected.read_text(encoding="utf-8")
        # The legacy ~/.config path must NOT be used on Windows.
        legacy = os.path.expanduser("~/.config/yt-dlp/config")
        assert not os.path.exists(legacy) or os.path.realpath(legacy) != os.path.realpath(expected)

    def test_install_uses_paths_helper_not_hardcoded(self, tmp_path, monkeypatch):
        """Regardless of OS, the installer routes through get_ytdlp_config_path."""

        target = tmp_path / "custom-ytdlp" / "config"
        monkeypatch.setattr(
            "searchts.utils.paths.get_ytdlp_config_path", lambda: target
        )
        monkeypatch.setattr(
            "searchts.utils.paths.get_ytdlp_config_dir", lambda: target.parent
        )
        self._stub_system_commands(monkeypatch)

        cli._install_system_deps()

        assert target.exists()
        assert "--js-runtimes node" in target.read_text(encoding="utf-8")


class TestEntryPointSignalHandling:
    """main() must turn Ctrl+C and a closed pipe into clean exits.

    Both reach the interpreter as exceptions, so without handling they print
    a traceback -- for `read`/`search`/`transcribe`, the two most likely ways
    a run ends.
    """

    def test_keyboard_interrupt_exits_130_without_traceback(self, monkeypatch, capsys):
        def _interrupt():
            raise KeyboardInterrupt()

        monkeypatch.setattr(cli, "_run", _interrupt)

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 130
        captured = capsys.readouterr()
        assert "Interrupted" in captured.err
        assert "Traceback" not in captured.err

    def test_broken_pipe_exits_quietly(self, monkeypatch, capsys):
        """`searchts read <url> | head` closes stdout early."""

        def _broken_pipe():
            raise BrokenPipeError()

        monkeypatch.setattr(cli, "_run", _broken_pipe)

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 141
        assert "Traceback" not in capsys.readouterr().err

    def test_normal_exit_code_passes_through(self, monkeypatch):
        """The wrapper must not swallow a handler's own sys.exit status."""

        def _fail():
            raise SystemExit(3)

        monkeypatch.setattr(cli, "_run", _fail)

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 3


class TestConfigureDeadKnobs:
    def test_youtube_cookies_does_not_write_config(self, tmp_path, monkeypatch, capsys):
        from types import SimpleNamespace

        from searchts.config import Config

        cfg = Config(config_path=tmp_path / "config.yaml")
        monkeypatch.setattr("searchts.config.Config", lambda: cfg)
        cli._cmd_configure(
            SimpleNamespace(from_browser=None, key="youtube-cookies", value=["chrome"])
        )
        out = capsys.readouterr().out
        assert "not wired" in out
        assert "youtube_cookies_from" not in cfg.data

    def test_github_token_does_not_write_config(self, tmp_path, monkeypatch, capsys):
        from types import SimpleNamespace

        from searchts.config import Config

        cfg = Config(config_path=tmp_path / "config.yaml")
        monkeypatch.setattr("searchts.config.Config", lambda: cfg)
        cli._cmd_configure(
            SimpleNamespace(from_browser=None, key="github-token", value=["ghp_test"])
        )
        out = capsys.readouterr().out
        assert "GITHUB_TOKEN" in out
        assert "github_token" not in cfg.data

    def test_dead_keys_do_not_require_a_value(self, tmp_path, monkeypatch, capsys):
        from types import SimpleNamespace

        from searchts.config import Config

        cfg = Config(config_path=tmp_path / "config.yaml")
        monkeypatch.setattr("searchts.config.Config", lambda: cfg)
        cli._cmd_configure(
            SimpleNamespace(from_browser=None, key="youtube-cookies", value=[])
        )
        yt = capsys.readouterr().out
        assert "not wired" in yt
        assert "Missing value" not in yt
        cli._cmd_configure(
            SimpleNamespace(from_browser=None, key="github-token", value=[])
        )
        gh = capsys.readouterr().out
        assert "GITHUB_TOKEN" in gh
        assert "Missing value" not in gh


_CONFIGURE_ENV = (
    "PROXY",
    "GROQ_API_KEY",
    "OPENAI_API_KEY",
    "TWITTER_AUTH_TOKEN",
    "TWITTER_CT0",
    "GITHUB_TOKEN",
    "GH_TOKEN",
)


class TestConfigureList:
    """Bare `searchts configure` is a stderr receipt. It does not print secrets."""

    @staticmethod
    def _flat(text):
        import re

        text = re.sub(r"\x1b\[[0-9;]*m", "", text)
        return " ".join(text.split())

    def _isolate(self, tmp_path, monkeypatch):
        from searchts.config import Config

        cfg = Config(config_path=tmp_path / "config.yaml")
        monkeypatch.setattr("searchts.config.Config", lambda: cfg)
        monkeypatch.setattr("searchts.config.load_dotenv_if_available", lambda: None)
        for name in _CONFIGURE_ENV:
            monkeypatch.delenv(name, raising=False)
        return cfg

    def _bare(self):
        with patch("sys.argv", ["searchts", "configure"]):
            main()

    def test_lists_every_accepted_key_on_stderr(self, tmp_path, monkeypatch, capsys):
        self._isolate(tmp_path, monkeypatch)

        self._bare()
        captured = capsys.readouterr()

        assert captured.out == ""
        err = self._flat(captured.err)
        assert err.count("default unset") == len(cli._CONFIGURE_KEYS)
        positions = [err.index(name) for name in cli._CONFIGURE_KEYS]
        assert positions == sorted(positions)
        assert "in the file; searchts does not apply it" in err
        assert "lives in GITHUB_TOKEN, not in the file" in err
        assert "not stored" in err
        assert "from-browser" not in err
        assert not (tmp_path / "config.yaml").exists()

    def test_secrets_stay_off_the_screen_and_the_proxy_url_is_shown(
        self, tmp_path, monkeypatch, capsys
    ):
        cfg = self._isolate(tmp_path, monkeypatch)
        groq = "gsk_test_secret_value_should_not_print"
        openai = "sk_test_openai_secret_value"
        auth = "auth_secret_value_zzzz"
        ct0 = "ct0_secret_value_zzzz"
        token = "ghp_secret_value_zzzz"
        password = "proxy_password_secret"
        cfg.set("groq_api_key", groq)
        cfg.set("openai_api_key", openai)
        cfg.set("twitter_auth_token", auth)
        cfg.set("twitter_ct0", ct0)
        cfg.set("proxy", f"http://user:{password}@127.0.0.1:8080")
        monkeypatch.setenv("GITHUB_TOKEN", token)
        before = dict(cfg.data)

        self._bare()
        err = self._flat(capsys.readouterr().err)

        for secret in (groq, openai, auth, ct0, token, password):
            assert secret not in err
        assert "http://user:***@127.0.0.1:8080" in err
        assert "set in config.yaml" in err
        assert "set in GITHUB_TOKEN" in err
        assert "lives in GITHUB_TOKEN, not in the file" in err
        assert "searchts does not apply it" in err
        assert cfg.data == before
        assert "github_token" not in cfg.data

    def test_env_name_wins_over_the_file(self, tmp_path, monkeypatch, capsys):
        cfg = self._isolate(tmp_path, monkeypatch)
        file_secret = "file_groq_secret_value"
        env_secret = "env_groq_secret_value"
        file_proxy = "http://file-proxy.example:1"
        env_proxy = "http://env-proxy.example:2"
        cfg.set("groq_api_key", file_secret)
        cfg.set("proxy", file_proxy)
        monkeypatch.setenv("GROQ_API_KEY", env_secret)
        monkeypatch.setenv("PROXY", env_proxy)

        self._bare()
        err = self._flat(capsys.readouterr().err)

        assert "set in GROQ_API_KEY over the file" in err
        assert "http://env-proxy.example:2 in PROXY over the file" in err
        assert file_secret not in err
        assert env_secret not in err
        assert file_proxy not in err

    def test_empty_env_hides_the_file_value(self, tmp_path, monkeypatch, capsys):
        cfg = self._isolate(tmp_path, monkeypatch)
        cfg.set("openai_api_key", "file_openai_secret_value")
        monkeypatch.setenv("OPENAI_API_KEY", "")

        self._bare()
        err = self._flat(capsys.readouterr().err)

        assert "unset in OPENAI_API_KEY over the file" in err
        assert "file_openai_secret_value" not in err

    def test_rejected_key_never_reaches_the_list(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["searchts", "configure", "not-a-key"]):
                main()

        assert exc_info.value.code == 2
        err = capsys.readouterr().err
        assert "invalid choice" in err
        assert "default unset" not in err

    def test_from_browser_stays_a_write(self, tmp_path, monkeypatch, capsys):
        self._isolate(tmp_path, monkeypatch)
        calls = {}

        def fake(browser, config):
            calls["browser"] = browser
            return [("Twitter/X", True, "auth_token + ct0")]

        monkeypatch.setattr("searchts.cookie_extract.configure_from_browser", fake)
        with patch("sys.argv", ["searchts", "configure", "--from-browser", "chrome"]):
            main()

        out, err = capsys.readouterr()
        assert calls["browser"] == "chrome"
        assert "Twitter/X" in out
        assert "default unset" not in out
        assert "default unset" not in err


class TestHelpMentionsRealSurface:
    """Help must name what the code actually accepts/installs."""

    def test_install_help_names_opencli(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["searchts", "install", "--help"]):
                main()
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "opencli" in out
        assert "all" in out

    def test_configure_help_says_dead_keys_are_not_stored(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["searchts", "configure", "--help"]):
                main()
        assert exc_info.value.code == 0
        raw = capsys.readouterr().out
        out = " ".join(raw.split())  # argparse hard-wraps help mid-phrase
        flat = "".join(raw.split())  # hard wrap can split "--flag" at the hyphen
        assert "github-token" in out
        assert "youtube-cookies" in out
        assert "not stored" in out
        # The supported alternative is discoverable from --help alone.
        assert "GITHUB_TOKEN" in out
        assert "--cookies-from-browser" in flat


class TestVerboseAfterSubcommand:
    """`-v` must be accepted both before and after the subcommand."""

    def _run_read(self, argv, monkeypatch):
        seen = {}
        monkeypatch.setattr(cli, "_cmd_read", lambda args: seen.setdefault("url", args.url))
        monkeypatch.setattr(cli, "_configure_logging", lambda verbose: seen.setdefault("verbose", verbose))
        with patch("sys.argv", argv):
            main()
        return seen

    def test_verbose_flag_after_subcommand(self, monkeypatch):
        seen = self._run_read(["searchts", "read", "-v", "https://example.com"], monkeypatch)
        assert seen["url"] == "https://example.com"
        assert seen["verbose"] is True

    def test_verbose_long_flag_after_subcommand(self, monkeypatch):
        seen = self._run_read(
            ["searchts", "read", "https://example.com", "--verbose"], monkeypatch
        )
        assert seen["url"] == "https://example.com"
        assert seen["verbose"] is True

    def test_verbose_flag_before_subcommand_still_works(self, monkeypatch):
        seen = self._run_read(["searchts", "-v", "read", "https://example.com"], monkeypatch)
        assert seen["url"] == "https://example.com"
        assert seen["verbose"] is True

    def test_no_verbose_flag_stays_false(self, monkeypatch):
        seen = self._run_read(["searchts", "read", "https://example.com"], monkeypatch)
        assert seen["verbose"] is False


def test_read_config_tip_quotes_the_note_and_keeps_its_ceiling():
    """The note owns the flag and its ceiling; the receipt repeats the sentence."""
    from searchts.cli import _read_config_tip

    class R:
        more = [{
            "kind": "media",
            "note": (
                "[media: 9 images in the main content: a, b. "
                "--media N (MCP max_media) lists more here, ceiling 40; "
                "searchts grab saves the files.]"
            ),
        }]

    tip = _read_config_tip(R())
    assert tip.startswith("--media N (MCP max_media)")
    assert "ceiling 40" in tip
    assert tip.endswith(".")


def test_read_config_tip_stays_quiet_without_a_lever_note():
    from searchts.cli import _read_config_tip

    class R:
        more = [{"kind": "count", "note": "[page says: 1,204 items]"}]

    assert _read_config_tip(R()) == ""


def test_tip_lines_hang_under_the_config_mark():
    from searchts.cli import _tip_lines
    from searchts.progress import Style

    lines = _tip_lines(
        "--media N (MCP max_media) lists more here, ceiling 40; "
        "searchts grab saves the files.",
        Style(False),
    )
    assert lines[0].startswith("  [CONFIG] Tip: ")
    assert all(len(line) <= 76 for line in lines)
    assert lines[1].startswith(" " * len("  [CONFIG] Tip: "))


def test_posix_console_replaces_a_glyph_the_locale_cannot_carry(monkeypatch):
    """LC_ALL=C is a real locale; an ellipsis must not end in a traceback."""
    import io
    import sys

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    fake = io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="strict")
    monkeypatch.setattr(sys, "stdout", fake)
    monkeypatch.setattr(
        sys, "stderr",
        io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="strict"),
    )

    cli._ensure_utf8_console()
    print("checking github…")
    fake.flush()

    assert fake.buffer.getvalue().strip() == b"checking github?"
