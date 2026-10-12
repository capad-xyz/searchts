"""The MCP surface an agent has, for a page behind a login.

Every test here drives ``read_url`` the way a tool call does and asserts on
what comes back, because the thing being tested is what the agent can act on.
The unit tests in test_login_store cover the state machine; these cover the
translation of that machine into strings and JSON a model reads.

They use the real ``read_url`` with ``unlocker.read_pages`` substituted, so no
network and no browser. The store is a temporary USERPROFILE, because on
Windows that -- not HOME -- is what ``expanduser`` reads, and a test that leaves
the real profile in play can pick up a real saved login for the same host.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from searchts.integrations import mcp_server
from searchts.unlocker import FetchResult, UnlockerError


@pytest.fixture(autouse=True)
def temp_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("HOME", raising=False)
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(home))
    return home


def ok_page(url="https://example.com/a", authenticated=False, **kw):
    """A page the receipt builder will accept.

    Every field ``FetchResult`` actually has, because a partial one raises
    inside the receipt builder and the test then fails decoding an error string
    instead of on the thing it meant to check.
    """
    return FetchResult(
        backend="curl_cffi", text="the page body", status=200,
        warnings=[], final_url=url, fetched_at="now", more=None,
        authenticated=authenticated, **kw,
    )


def serves(monkeypatch, pages=None, error=None):
    """Replace the network with a fixed outcome."""
    import searchts.unlocker as unlocker

    if error is not None:
        monkeypatch.setattr(
            unlocker, "read_pages",
            lambda *a, **k: (_ for _ in ()).throw(error),
        )
        return
    monkeypatch.setattr(unlocker, "read_pages", lambda *a, **k: pages or [ok_page()])


def login_wall():
    return UnlockerError(
        url="https://example.com/a",
        attempts=[("curl_cffi", "login-wall"), ("Jina Reader", "HTTP 403")],
    )


# ── a kept login is used, with no argument from the agent ───────────────────


def test_a_kept_login_is_used_by_a_bare_read(monkeypatch):
    """The reason a login is kept: the agent does not have to know it exists."""
    from searchts.login_store import keep
    from searchts.session_cookies import CookieRecord

    keep("example.com", [CookieRecord("sid", "SECRET", "example.com", secure=True)])
    serves(monkeypatch, pages=[ok_page(authenticated=True)])

    out = json.loads(mcp_server.read_url("https://example.com/a"))
    assert out["authenticated"] is True
    assert out["login_via"] == "owned store"
    assert "SECRET" not in json.dumps(out)


def test_login_via_is_empty_on_an_anonymous_read(monkeypatch):
    serves(monkeypatch)
    out = json.loads(mcp_server.read_url("https://example.com/a"))
    assert out["authenticated"] is False
    assert out["login_via"] == ""


# ── a copy is refused, and the refusal is actionable ────────────────────────


def test_a_copy_without_approval_returns_an_error_not_a_read(monkeypatch):
    serves(monkeypatch)
    out = mcp_server.read_url(
        "https://example.com/a", cookies_from_browser="firefox",
    )
    assert out.startswith("Error:")
    # The agent needs to know it can retry differently, not just that it failed.
    assert "approval" in out
    assert "login_signin" in out


def test_a_refused_copy_does_not_reach_the_network(monkeypatch):
    called = []
    import searchts.unlocker as unlocker

    monkeypatch.setattr(unlocker, "read_pages", lambda *a, **k: called.append(a) or [ok_page()])
    mcp_server.read_url("https://example.com/a", cookies_from_browser="firefox")
    assert called == []


# ── a login wall names the next step ────────────────────────────────────────


def test_a_login_wall_names_both_ways_forward(monkeypatch):
    serves(monkeypatch, error=login_wall())
    out = mcp_server.read_url("https://example.com/a")
    assert out.startswith("Error:")
    assert "behind a login" in out
    # Both routes, because which one is right depends on the user, not the agent.
    assert "cookies_from_browser" in out
    assert "login_signin" in out


def test_an_expired_kept_login_says_so_instead_of_offering_a_fresh_copy(monkeypatch):
    """The generic advice is wrong here: the login exists, it has just died."""
    from searchts.login_store import keep
    from searchts.session_cookies import CookieRecord

    keep("example.com", [CookieRecord("sid", "SECRET", "example.com", secure=True)])
    serves(monkeypatch, error=login_wall())
    out = mcp_server.read_url("https://example.com/a")
    assert "expired" in out
    assert "login_kill" in out
    # Re-copying is the advice we are not giving.
    assert "cookies_from_browser" not in out


def test_a_non_login_failure_is_left_alone(monkeypatch):
    """A 404 is not a login problem and must not be dressed up as one."""
    err = UnlockerError(
        url="https://example.com/a", attempts=[("curl_cffi", "404")],
    )
    serves(monkeypatch, error=err)
    out = mcp_server.read_url("https://example.com/a")
    assert "behind a login" not in out


def test_the_error_never_carries_a_cookie_value(monkeypatch):
    from searchts.login_store import keep
    from searchts.session_cookies import CookieRecord

    keep("example.com", [CookieRecord("sid", "SUPERSECRET", "example.com", secure=True)])
    serves(monkeypatch, error=login_wall())
    out = mcp_server.read_url("https://example.com/a")
    assert "SUPERSECRET" not in out


# ── the login tools ─────────────────────────────────────────────────────────


def test_login_status_reports_what_is_held_and_no_values():
    from searchts.login_store import keep
    from searchts.session_cookies import CookieRecord

    keep("example.com", [CookieRecord("sid", "TOPSECRET", "example.com", secure=True)])
    blob = mcp_server.login_status()
    data = json.loads(blob)
    assert "example.com" in data["kept"]
    assert "TOPSECRET" not in blob
    assert data["session_copy_granted"] is False


def test_login_kill_removes_and_says_the_browser_was_left_alone():
    from searchts.login_store import keep
    from searchts.session_cookies import CookieRecord

    keep("example.com", [CookieRecord("sid", "S", "example.com", secure=True)])
    data = json.loads(mcp_server.login_kill("https://example.com"))
    assert data["removed_from_store"] is True
    assert data["browser_copies_touched"] is False
    assert "left alone" in data["why"]
    assert json.loads(mcp_server.login_status())["kept"] == {}


def test_login_kill_rejects_a_malformed_site():
    out = mcp_server.login_kill("not a url")
    assert out.startswith("Error:")


def test_login_signin_keeps_only_after_a_successful_signin(monkeypatch):
    from searchts import signin_browser
    from searchts.session_cookies import CookieSource

    monkeypatch.setattr(
        signin_browser, "signin",
        lambda s, **kw: CookieSource(site=s, cookies=[
            __import__("searchts.session_cookies", fromlist=["CookieRecord"])
            .CookieRecord("sid", "S", "example.com", secure=True),
        ], count=1, via="test"),
    )
    data = json.loads(mcp_server.login_signin("https://example.com"))
    assert data["kept"] is True
    assert data["host"] == "example.com"
    assert json.loads(mcp_server.login_status())["kept"]


def test_login_signin_reports_a_failure_without_raising(monkeypatch):
    from searchts import signin_browser
    from searchts.session_cookies import CookieReadError

    monkeypatch.setattr(
        signin_browser, "signin",
        lambda s, **kw: (_ for _ in ()).throw(CookieReadError("chrome not installed")),
    )
    out = mcp_server.login_signin("https://example.com")
    assert out.startswith("Error:")
    assert "chrome not installed" in out
    assert json.loads(mcp_server.login_status())["kept"] == {}


def _tool_names():
    """The live tool list. ``list_tools`` is a coroutine on this SDK."""
    import asyncio

    return {t.name for t in asyncio.run(mcp_server.create_server().list_tools())}


def test_the_three_login_tools_are_registered():
    assert {"login_status", "login_signin", "login_kill"} <= _tool_names()


def test_the_login_wall_error_names_a_registered_tool():
    """An error naming a tool that does not exist is worse than no advice."""
    names = _tool_names()
    msg = mcp_server._login_wall_error("https://example.com", login_wall(), had_cookies=False)
    assert "login_signin" in names and "login_signin" in msg
    # cookies_from_browser is a read_url argument, not a tool, so it is checked
    # separately: naming a flag is fine, naming a missing tool is not.
    assert "cookies_from_browser" in msg
