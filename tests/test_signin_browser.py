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
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from searchts import signin_browser as sb


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


# ── the third finding: the default's meaning was not written down ───────────


def test_the_docstring_says_what_the_timeout_does_not_bound():
    """`timeout_s` bounds the port wait, not the person's sign-in."""
    doc = inspect.getdoc(sb.signin_window) or ""
    assert "sign in" in doc
    assert "unbounded" in doc
