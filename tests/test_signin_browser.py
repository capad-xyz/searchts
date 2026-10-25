"""Sign-in browser: the two dead parameters the review caught, pinned.

Both were real. A parameter that is accepted and never read is worse than no
parameter at all: it tells a caller their value is in effect when it is not, and
in the sign-in path a caller waiting on a timeout that will never arrive is a
person staring at a browser window that has already given up.

These tests run no browser. They substitute the launcher and the port wait and
assert on what got forwarded, which is the only thing the review was about.
"""

from __future__ import annotations

import inspect
import io
import sys
from contextlib import nullcontext as _nullcontext
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from searchts import signin_browser as sb
from searchts.session_cookies import CookieReadError


class _FakeLaunched:
    def close(self):  # the real one kills a process tree; there is none here
        pass


@pytest.fixture
def no_browser(monkeypatch):
    """Substitute the launcher so no window opens and no binary is needed."""
    import searchts.cdp_profile as cdp

    monkeypatch.setattr(cdp, "_launch_browser", lambda *a, **k: _FakeLaunched())
    monkeypatch.setattr(cdp, "browser_executable", lambda b: "fake")
    monkeypatch.setattr(cdp, "_free_port", lambda: 55555)
    return cdp


# ── the review's first finding: `persist` was accepted and never read ────────


def test_signin_has_no_persist_parameter():
    """Keeping is the caller's yes. A flag here would imply this decides it."""
    params = inspect.signature(sb.signin).parameters
    assert "persist" not in params
    assert set(params) == {"site", "browser"}


def test_the_word_persist_appears_only_in_prose():
    """No executable reference survives; the docstring is allowed to say it."""
    import inspect as _i

    src = _i.getsource(sb.signin)
    code_lines = [
        ln for ln in src.splitlines()
        if "persist" in ln and not ln.lstrip().startswith(("#", '"', "*"))
    ]
    assert code_lines == [], f"persist still referenced in code: {code_lines}"


# ── the review's second finding: `timeout_s` was accepted and hardcoded ─────


def test_timeout_reaches_the_debugger_wait(no_browser, monkeypatch):
    """The value the caller passes is the value the wait is given."""
    seen = []
    monkeypatch.setattr(sb, "_wait_for_debugger", lambda port, t: (seen.append(t), True)[1])

    with sb.signin_window("example.com", browser="chrome", timeout_s=0.25):
        pass

    assert seen == [0.25], f"timeout_s not forwarded, saw {seen}"


def test_a_zero_timeout_is_not_silently_replaced_by_the_default(no_browser, monkeypatch):
    """A caller asking for no wait gets no wait, not the 20s default."""
    seen = []
    monkeypatch.setattr(sb, "_wait_for_debugger", lambda port, t: (seen.append(t), True)[1])

    with sb.signin_window("example.com", browser="chrome", timeout_s=0.0):
        pass

    assert seen == [0.0]


def test_a_timeout_that_expires_names_itself(no_browser, monkeypatch):
    """A failed launch must say how long it waited, or the retry is guesswork."""
    monkeypatch.setattr(sb, "_wait_for_debugger", lambda port, t: False)

    from searchts.session_cookies import CookieReadError

    with pytest.raises(CookieReadError) as e:
        with sb.signin_window("example.com", browser="chrome", timeout_s=7.0):
            pass
    assert "7s" in str(e.value)


def test_the_wait_returns_false_rather_than_looping_forever():
    """Bound by the caller's timeout; an unused port must not hang the process."""
    assert sb._wait_for_debugger(1, 0.0) is False
    assert sb._wait_for_debugger(1, 0.05) is False


def test_the_signin_window_opens_the_site(no_browser, monkeypatch):
    """The window must open the site. A blank window cannot take a sign-in,
    so the cookies a later read needs are never saved."""
    seen = {}

    def launch(exe, port, profile, **kw):
        seen.update(kw)
        return _FakeLaunched()

    monkeypatch.setattr(no_browser, "_launch_browser", launch)
    monkeypatch.setattr(sb, "_wait_for_debugger", lambda port, t: True)

    with sb.signin_window("example.com", browser="chrome"):
        pass

    assert seen["open_url"] == "https://example.com"
    assert seen["extra_args"] == ["--disable-sync"]


def test_a_new_sign_in_profile_starts_empty(tmp_path, monkeypatch):
    """A leftover profile restores its own tabs and hides the site."""
    monkeypatch.setattr(sb, "signin_root", lambda: str(tmp_path))
    stale = tmp_path / "chrome" / "Default"
    stale.mkdir(parents=True)
    (stale / "Cookies").write_text("old", encoding="utf-8")

    path = sb._profile_for("chrome")

    assert path == str(tmp_path / "chrome")
    assert not (tmp_path / "chrome" / "Default").exists()


def test_the_signin_window_closes_even_when_the_block_raises(no_browser, monkeypatch):
    """A failed sign-in must still close the browser it opened."""
    closed = []

    class L(_FakeLaunched):
        def close(self):
            closed.append(True)

    import searchts.cdp_profile as cdp

    monkeypatch.setattr(cdp, "_launch_browser", lambda *a, **k: L())
    monkeypatch.setattr(sb, "_wait_for_debugger", lambda port, t: True)

    with pytest.raises(RuntimeError):
        with sb.signin_window("example.com", browser="chrome"):
            raise RuntimeError("boom")
    assert closed == [True]


# ── the wait for the person, which was missing entirely ─────────────────────


def _rec():
    from searchts.session_cookies import CookieRecord

    return CookieRecord("session", "v", ".example.com")


def test_the_person_is_asked_before_any_cookie_is_read(monkeypatch):
    """The read must not happen until the wait has happened.

    This is the defect the running of it found. `signin` yielded as soon as the
    debugger port answered and read straight away, so the window opened and
    closed in 2.1 s and the flow reported whatever guest cookies the sign-in
    page had set on its own as though a person had signed in.

    Order is the whole assertion: a wait that ran *after* the read would leave
    the reported bug in place while looking like a fix.
    """
    order = []
    monkeypatch.setattr(sb, "_read_after_signin",
                        lambda port, url, host: order.append("read") or [_rec()])
    monkeypatch.setattr(sb, "wait_for_the_person",
                        lambda site, *, browser: order.append("wait"))
    monkeypatch.setattr(sb, "signin_window",
                        lambda site, **k: _nullcontext(("profile", 1234)))
    monkeypatch.setattr(sb, "_wipe_one", lambda profile: None)

    sb.signin("https://example.com", browser="chrome")

    assert order == ["wait", "read"], f"got {order}, expected the wait before the read"


def test_a_non_terminal_refuses_instead_of_reading_anyway(monkeypatch):
    """No terminal means no way to ask, so it must not pretend to have asked.

    The MCP server is the case that matters: its stdin is the JSON-RPC channel,
    so an `input()` there would eat protocol messages. A piped script cannot
    complete a human sign-in either. Both get a sentence rather than a cookie.
    """
    read = []
    monkeypatch.setattr(sys, "stdin", io.StringIO())  # isatty() is False
    monkeypatch.setattr(sb, "_read_after_signin", lambda *a: read.append(a) or [])

    with pytest.raises(CookieReadError) as exc:
        sb.wait_for_the_person("https://example.com", browser="zen")

    assert read == []
    assert "terminal" in str(exc.value)
    assert "searchts login signin" in str(exc.value)


def test_a_terminal_waits_for_the_person(monkeypatch):
    """With a terminal, the wait blocks until they press Enter."""

    class _Tty(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", _Tty("\n"))
    sb.wait_for_the_person("https://example.com", browser="zen")  # returns


# ── the third finding: the default's meaning was not written down ───────────


def test_the_docstring_says_what_the_timeout_does_not_bound():
    """`timeout_s` bounds the port wait, not the person's sign-in."""
    doc = inspect.getdoc(sb.signin_window) or ""
    assert "sign in" in doc
    assert "unbounded" in doc


# The missing-trailing-newline finding that followed the three above is not
# pinned here. It was first written as a test reading bytes off disk, and the
# review was right that it was lint wearing a test's clothes: it asserted on
# the file rather than on any behaviour, so a pytest run would fail on
# something no test could explain.
#
# It is ruff's rule (W292), enforced in pyproject with per-file-ignores for the
# six files that already ended mid-line before this branch. `ruff check
# searchts tests` covers it for every current and future file, which a
# parametrised test over a hand-listed set could not.
