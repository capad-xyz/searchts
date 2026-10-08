"""Tests for the no-argument first run.

The zero-arg invocation is what a new user sees after installing, and it was
sixteen subcommands and no first action.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "searchts", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT), timeout=180,
    )


def test_no_args_names_the_two_commands_people_need():
    out = _run()
    assert out.returncode == 0
    err = out.stderr
    assert "searchts read <url>" in err
    assert "searchts search" in err


def test_no_args_names_the_agent_wiring():
    """The product is aimed at agents, so the MCP server is the headline."""
    err = _run().stderr
    assert "searchts mcp serve" in err
    assert "searchts skill install" in err


def test_orientation_does_not_displace_the_reference():
    """Still the full help on stdout, so nothing is hidden by orienting first."""
    out = _run()
    assert "usage: searchts" in out.stdout
    assert "transcribe" in out.stdout


def test_orientation_is_not_shown_when_a_command_is_given():
    """A real invocation must not pay for the welcome message."""
    out = _run("version")
    assert "Give your AI agent eyes" not in out.stdout
    assert "Give your AI agent eyes" not in out.stderr
    assert out.returncode == 0


def test_version_is_unaffected():
    out = _run("--version")
    assert "searchts v" in (out.stdout + out.stderr)
