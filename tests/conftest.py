# -*- coding: utf-8 -*-
"""Shared test helpers.

The important thing here is :class:`Tripwire`. Read its docstring before
writing a "must not be called" stub.

Two autouse guards keep a run independent of where it runs:

* :func:`isolate_runner_env` removes the GitHub Actions and Hare variables the
  code reads from the process. A runner sets ``GITHUB_RUN_ATTEMPT``,
  ``GITHUB_ACTOR`` and friends on every re-run, so without this a suite that is
  green on attempt 1 goes red on attempt 2 for a reason that is not in the diff.
* :func:`block_external_network` fails a test that reaches a host other than
  this machine. A live ``example.com`` read made the 3.12 job red on one main
  run and green on the next; a test that touches the internet is a test that
  depends on someone else's uptime.

Both are defence in depth: tests still stub the layer they are exercising. The
guards make forgetting to stub fail loudly and at the same spot on every OS.
"""

import ipaddress
import os
import socket
import urllib.parse

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


#: The runner and Hare read these by name. Prefixes cover the whole Actions
#: surface (GITHUB_*, RUNNER_*) rather than a list that rots as the workflow
#: grows. SEARCHTS_HARE_API_KEY_* is not a HARE_ prefix, so it is separate.
_RUNNER_ENV_PREFIXES = ("GITHUB_", "HARE_", "RUNNER_", "SEARCHTS_HARE_API_KEY_")
_RUNNER_ENV_NAMES = frozenset({"CI", "HEAD_SHA", "PR_NUMBER", "GH_TOKEN"})


def _runner_env_names(env=None):
    env = os.environ if env is None else env
    return [
        name
        for name in env
        if name in _RUNNER_ENV_NAMES or name.startswith(_RUNNER_ENV_PREFIXES)
    ]


def _clear_runner_env(env):
    for name in _runner_env_names(env):
        env.pop(name, None)


# Before collection, so a module that reads these at import time (hare_r1's
# HEAD_DIR and caps do) cannot bake a runner's values into a constant.
_clear_runner_env(os.environ)


@pytest.fixture(autouse=True)
def isolate_runner_env(monkeypatch):
    """A test never inherits the runner's GitHub/Hare environment.

    A test that needs one of these sets it with ``monkeypatch`` itself. The
    re-run case in test_hare_r1 does exactly that, which is why it still proves
    what it says. Deleting at import time is not enough for a test that sets
    ``os.environ`` directly and leaks into the next file.
    """
    for name in _runner_env_names():
        monkeypatch.delenv(name, raising=False)


class NetworkBlocked(BaseException):
    """A test tried to open a connection to somebody else's host.

    ``BaseException`` for the same reason as :class:`Tripwire`: the read ladder
    wraps a rung in ``except Exception`` and records the failure as a backend
    result. An ordinary exception would then let the test pass while proving
    nothing about whether the network was used.
    """


def _local_host(host) -> bool:
    if host is None:
        return True
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii")
        except UnicodeDecodeError:
            return False
    if not isinstance(host, str):
        return False
    host = host.strip("[]")
    if "%" in host:  # fe80::1%eth0
        host = host.split("%", 1)[0]
    if host.lower() in {"", "localhost", "localhost.localdomain"}:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host.lower().endswith(".localhost")
    return address.is_loopback or address.is_unspecified


def _local_address(address) -> bool:
    if isinstance(address, (str, bytes)):
        return True  # AF_UNIX path
    if isinstance(address, tuple) and address:
        return _local_host(address[0])
    return False


def _blocked(where) -> None:
    raise NetworkBlocked(
        f"test tried to reach {where!r} over the network. Stub the fetch or "
        "HTTP call the test goes through."
    )


def _guard_external_network(monkeypatch) -> None:
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create_connection = socket.create_connection

    def connect(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _local_address(address):
            _blocked(address)
        return real_connect(self, address)

    def connect_ex(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _local_address(address):
            _blocked(address)
        return real_connect_ex(self, address)

    def create_connection(address, *args, **kwargs):
        if not _local_address(address):
            _blocked(address)
        return real_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    # Name lookups stay allowed: the SSRF guard resolves hosts by design and a
    # lookup sends no request to the host. Connecting is what is blocked.

    # curl_cffi resolves and connects inside libcurl, below Python's socket
    # module, so the guard above cannot see it. This is the other rung that
    # can reach the network without a Python socket.
    try:
        from curl_cffi import requests as curl_requests
    except Exception:
        return

    def guard_call(name):
        real = getattr(curl_requests, name, None)
        if real is None:
            return
        def guarded(url, *args, _real=real, _name=name, **kwargs):
            host = urllib.parse.urlsplit(str(url)).hostname
            if not _local_host(host):
                _blocked(host)
            return _real(url, *args, **kwargs)
        monkeypatch.setattr(curl_requests, name, guarded)

    for name in ("get", "post", "request"):
        guard_call(name)


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch):
    """No test reaches the live internet."""
    _guard_external_network(monkeypatch)


@pytest.fixture(autouse=True)
def isolate_unlocker_cache(monkeypatch, tmp_path):
    """Each test gets its own backend memory, never ~/.searchts's.

    A test that won on Jina for site.test could write that to the real cache, and a
    later test that stubbed only curl_cffi then read Jina first and went to
    r.jina.ai live. Which test paid depended on the order they ran in.
    """
    monkeypatch.setenv("SEARCHTS_CACHE_DIR", str(tmp_path / "searchts-cache"))


@pytest.fixture
def offline_jina_probe(monkeypatch):
    """Doctor's web check probes r.jina.ai live. Tests answer for it instead."""
    monkeypatch.setattr(
        "searchts.channels.web._jina_probe", lambda: ("blocked", "probe stubbed in tests")
    )


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
