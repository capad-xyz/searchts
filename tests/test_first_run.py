"""Tests for the no-argument first run.

The zero-arg invocation is what a new user sees after installing, and it used
to be sixteen equal-weight subcommands under ``usage: searchts``. It is now the
same document as ``--help``: the belief, the two commands that do the work,
and one screen that fits a default terminal.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\]8;;.*?\x1b\\")


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "searchts", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT), timeout=180,
    )


def test_no_args_prints_one_screen_on_stdout():
    out = _run()
    assert out.returncode == 0
    assert out.stderr == ""
    assert "read <url>" in out.stdout
    assert "search" in out.stdout


def test_no_args_names_the_agent_wiring():
    """The product is aimed at agents, so the MCP server is on the same screen."""
    stdout = _run().stdout
    assert "mcp serve" in stdout
    assert "skill install" in stdout


def test_help_and_no_args_are_the_same_document():
    assert _run("--help").stdout == _run().stdout


def test_the_screen_states_the_belief():
    stdout = _run().stdout
    assert "The missing layer between AI and the web." in stdout
    assert "It reads the page, or it says it can't." in stdout
    assert "No API key" in stdout


def test_the_screen_fits_a_default_terminal():
    """A help screen that wraps is a help screen that is harder to skim."""
    lines = ANSI.sub("", _run().stdout).splitlines()
    assert lines
    assert max(len(line) for line in lines) <= 80


def test_the_reference_is_still_complete():
    """Orienting first must not hide a command."""
    stdout = _run().stdout
    for command in ("read", "search", "transcribe", "grab", "get", "mcp",
                    "skill", "doctor", "install", "setup", "configure",
                    "login", "uninstall", "upgrade", "check-update", "watch",
                    "version"):
        assert command in stdout, command


def test_orientation_is_not_shown_when_a_command_is_given():
    """A real invocation must not pay for the welcome screen."""
    out = _run("version")
    assert "The missing layer between AI and the web." not in out.stdout
    assert "The missing layer between AI and the web." not in out.stderr
    assert out.returncode == 0


def test_command_help_is_drawn_from_the_live_parser():
    out = _run("read", "--help")
    assert out.returncode == 0
    assert "searchts read" in out.stdout
    assert "--cookies-from-browser" in out.stdout
    assert "<url>" in out.stdout
    assert "Traceback" not in out.stderr


def test_every_command_renders_help_without_a_traceback(capsys):
    """In-process, because fifteen subprocesses for one assertion is a tax."""
    from unittest.mock import patch

    import pytest

    from searchts.cli import main

    for command in ("read", "search", "transcribe", "grab", "get", "mcp",
                    "doctor", "configure", "install", "uninstall", "login",
                    "watch", "upgrade", "check-update", "version"):
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["searchts", command, "--help"]):
                main()
        assert exc_info.value.code == 0, command
        assert capsys.readouterr().out.strip(), command


def test_version_is_unaffected():
    out = _run("--version")
    assert "searchts v" in (out.stdout + out.stderr)
