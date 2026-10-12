# -*- coding: utf-8 -*-
"""Shared test helpers.

The important thing here is :class:`Tripwire`. Read its docstring before
writing a "must not be called" stub.
"""

import pytest


class Tripwire(BaseException):
    """Raised by a stub that must never be called.

    Derives from ``BaseException``, NOT ``Exception``, and that is the whole
    point. The code under test is deliberately written to survive anything its
    collaborators throw:

    * ``unlocker.fetch`` wraps every ladder rung in ``except Exception``,
    * so does its tier-0 share hook and its human-in-the-loop rung,
    * and ``share_extractors.extract`` wraps each extractor the same way.

    ``AssertionError`` is an ``Exception``, so a tripwire raising one gets
    swallowed by those handlers and recorded as an ordinary backend failure.
    The guard test then passes whether or not the forbidden call happened,
    which is the exact opposite of its purpose. Verified by mutation: forcing
    ``fetch`` to call ``_fetch_human`` unconditionally left the guard green.

    ``BaseException`` is not caught by ``except Exception``, so it propagates
    out and fails the test the way it always should have.
    """


def tripwire(message):
    """A stub for any signature that fails loudly if it is ever called."""
    def _boom(*args, **kwargs):
        raise Tripwire(message)
    return _boom


@pytest.fixture(autouse=True)
def reset_jina_spent():
    import searchts.unlocker as unlocker
    unlocker._jina_spent = False
    yield
    unlocker._jina_spent = False


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    """Redirect every home-ish variable the cookie code reads into tmp_path.

    Promoted out of test_session_cookies.py because ``searchts read`` now
    consults the owned store, so any test that reads a URL can reach the real
    one -- and, worse, write to it. Nine files could, and two of them leaked
    into each other during a full run, with the assertion that failed naming a
    completely different host.

    HOME alone is not enough on Windows: ntpath.expanduser honours USERPROFILE
    and ignores HOME, so a test that only set HOME would create
    ~/.searchts/cookies/owned.json in the real user's profile. That happened
    twice during manual verification before this was written down.
    """
    home = tmp_path / "home"
    appdata = home / "AppData" / "Roaming"
    localappdata = home / "AppData" / "Local"
    for d in (home, appdata, localappdata):
        d.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(localappdata))
    return home
