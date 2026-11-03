# -*- coding: utf-8 -*-
"""Attach a LinkedIn read to a Chromium browser that is already running.

Chrome 136 and newer refuse ``--remote-debugging-port`` on the default
user-data directory (``NotStartedReason::kDisabledByDefaultUserDataDir``).
The supported switch is the per-instance checkbox at
``chrome://inspect/#remote-debugging`` (and the ``vivaldi://``, ``edge://``
and ``brave://`` pages of the same name). Turning it on sets
``prefs::kDevToolsRemoteDebuggingEnabled``. Chromium then starts an HTTP
server in approval mode, bound to ``127.0.0.1``, and writes
``DevToolsActivePort`` in the user-data directory: the first line is the
port, the second is the browser WebSocket path (``content/browser/devtools/devtools_http_handler.cc``
writes ``"<port>\\n<path>"``).

Approval mode answers ``/json`` and ``/json/version`` with 404, so the
endpoint is the WebSocket URL from that file, not a guessed port 9222.
A missing or empty file means debugging is off. A file left behind after
the browser exited is stale and is ignored.

The read opens one tab in the existing window and closes only that tab.
The browser process, its other tabs, and its windows stay as the user
left them. Nothing in this module navigates anywhere.
"""

from __future__ import annotations

import os
import socket
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional, Tuple
from urllib.parse import urlparse

from searchts.session_cookies import FIREFOX_FAMILY

__all__ = [
    "ALLOW_REMOTE_DEBUGGING",
    "ATTACH_BROWSERS",
    "ActivePort",
    "AttachError",
    "Decision",
    "browser_is_running",
    "browser_of",
    "candidate_user_data_dirs",
    "decide",
    "endpoint_for",
    "inspect_url",
    "kept_browser",
    "new_tab",
    "open_tab",
    "parse_active_port",
    "parse_mode",
    "probe_port",
]

#: The checkbox label on the inspect page. The refusal names it exactly.
ALLOW_REMOTE_DEBUGGING = "Allow remote debugging for this browser instance"

#: Browsers whose inspect page writes DevToolsActivePort. Opera and Arc are
#: Chromium too, but this path does not attach to them.
ATTACH_BROWSERS = ("chrome", "vivaldi", "edge", "brave", "chromium")

_UNSUPPORTED = ("opera", "arc")

_ON = {"on", "1", "true", "yes"}
_OFF = {"off", "0", "false", "no"}

_DISPLAY = {
    "chrome": "Chrome",
    "chromium": "Chromium",
    "vivaldi": "Vivaldi",
    "edge": "Edge",
    "brave": "Brave",
    "opera": "Opera",
    "arc": "Arc",
    "firefox": "Firefox",
    "zen": "Zen",
    "librewolf": "LibreWolf",
    "waterfox": "Waterfox",
    "floorp": "Floorp",
    "mullvad": "Mullvad",
}

_SCHEME = {
    "chrome": "chrome",
    "chromium": "chrome",
    "vivaldi": "vivaldi",
    "edge": "edge",
    "brave": "brave",
}

#: Executable basename, longest distinctive name first. ``chrome`` is after
#: ``chromium`` and ``google-chrome`` so those are not shortened to Chrome.
_BASENAMES = (
    ("google-chrome", "chrome"),
    ("chromium", "chromium"),
    ("microsoft-edge", "edge"),
    ("msedge", "edge"),
    ("brave-browser", "brave"),
    ("vivaldi", "vivaldi"),
    ("librewolf", "librewolf"),
    ("waterfox", "waterfox"),
    ("floorp", "floorp"),
    ("mullvad-browser", "mullvad"),
    ("mullvad", "mullvad"),
    ("firefox", "firefox"),
    ("opera", "opera"),
    ("chrome", "chrome"),
    ("brave", "brave"),
    ("edge", "edge"),
    ("zen", "zen"),
    ("arc", "arc"),
)

#: Path fragments that identify a user-data directory. Order matters:
#: ``chromium`` before a bare ``chrome`` would, and these fragments are
#: specific enough that a temporary test directory does not match.
_PATH_HINTS = (
    ("bravesoftware", "brave"),
    ("brave-browser", "brave"),
    ("microsoft edge", "edge"),
    ("microsoft-edge", "edge"),
    ("microsoft/edge", "edge"),
    ("google/chrome", "chrome"),
    ("google-chrome", "chrome"),
    ("google chrome", "chrome"),
    ("/chromium", "chromium"),
    ("vivaldi", "vivaldi"),
    ("librewolf", "librewolf"),
    ("waterfox", "waterfox"),
    ("floorp", "floorp"),
    ("mullvad", "mullvad"),
    ("firefox", "firefox"),
    ("/zen/", "zen"),
    ("opera", "opera"),
    ("/arc/", "arc"),
)

_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class AttachError(Exception):
    """The browser could not be joined, and no page was requested."""


@dataclass(frozen=True)
class ActivePort:
    """One ``DevToolsActivePort`` file: a port and an optional WebSocket path."""

    port: int
    ws_path: str = ""


@dataclass(frozen=True)
class Decision:
    """What a LinkedIn read should do with the browser.

    ``attach`` has an endpoint on this machine. ``launch`` keeps the
    existing profile launch (or the cookie-copy ladder). ``refuse`` is a
    finished answer: the message is the whole reason, and no request follows.
    """

    action: str
    endpoint: str = ""
    browser: str = ""
    message: str = ""
    user_data: str = ""


def parse_mode(override: Optional[str] = None) -> str:
    """``auto``, ``on`` or ``off``.

    An explicit ``override`` wins. Otherwise ``SEARCHTS_LINKEDIN_ATTACH``
    is read. A blank value is ``auto``. ``1`` / ``true`` / ``yes`` are
    ``on``; ``0`` / ``false`` / ``no`` are ``off``. Anything else is a
    usage error, not a silent ``auto``.
    """
    raw = override
    if raw is None:
        raw = os.environ.get("SEARCHTS_LINKEDIN_ATTACH", "")
    text = (raw or "").strip().lower()
    if not text or text == "auto":
        return "auto"
    if text in _ON:
        return "on"
    if text in _OFF:
        return "off"
    raise ValueError("SEARCHTS_LINKEDIN_ATTACH must be auto, on or off")


def parse_active_port(text: str) -> Optional[ActivePort]:
    """The port and browser path from a ``DevToolsActivePort`` file.

    The first non-empty line is the port (1–65535). The next non-empty
    line is the WebSocket path when it starts with ``/``. Further lines
    are ignored. A blank file, or a first line that is not a port, is
    not a debugging endpoint: callers must not assume port 9222.
    """
    content = [line.strip() for line in (text or "").splitlines()]
    content = [line for line in content if line]
    if not content or not content[0].isdigit():
        return None
    port = int(content[0])
    if not 1 <= port <= 65535:
        return None
    ws_path = ""
    if len(content) >= 2:
        second = content[1]
        if second.startswith("/") and "://" not in second and " " not in second:
            ws_path = second
    return ActivePort(port=port, ws_path=ws_path)


def endpoint_for(port: int, ws_path: str = "") -> str:
    """The loopback endpoint Playwright can connect to.

    A path from the active-port file is used as a WebSocket URL, because
    approval mode does not serve ``/json/version``. A port-only file (older
    builds) stays an HTTP URL so the classic discovery still works.
    """
    if ws_path:
        return f"ws://127.0.0.1:{port}{ws_path}"
    return f"http://127.0.0.1:{port}"


def inspect_url(browser: str) -> str:
    """The inspect page for ``browser``. Chromium uses the ``chrome://`` page."""
    scheme = _SCHEME.get((browser or "").strip().lower(), "chrome")
    return f"{scheme}://inspect/#remote-debugging"


def _display(browser: str) -> str:
    key = (browser or "").strip().lower()
    return _DISPLAY.get(key, key.capitalize() or "Chrome")


def _debug_off(name: str, url: str) -> str:
    return (
        f"{name} is running but remote debugging is off, so nothing was requested. "
        f"Open {url} and tick \"{ALLOW_REMOTE_DEBUGGING}\"."
    )


def _not_running(name: str, url: str) -> str:
    return (
        f"{name} is not running, and SEARCHTS_LINKEDIN_ATTACH=on will not launch one. "
        f"Start it, open {url} and tick \"{ALLOW_REMOTE_DEBUGGING}\"."
    )


def _firefox_message(name: str) -> str:
    names = ", ".join(FIREFOX_FAMILY)
    return (
        f"{name} is a Firefox-family browser. LinkedIn attach talks to a Chromium "
        "browser over the DevTools protocol; Firefox-family browsers "
        f"({names}) stay on cookie copy only. Set SEARCHTS_LINKEDIN_CHROME to "
        "Chrome, Vivaldi, Edge, Brave or Chromium, or set SEARCHTS_LINKEDIN_ATTACH=off."
    )


def _unsupported_message(name: str) -> str:
    return (
        f"{name} is not attached this way. LinkedIn attach connects to Chrome, "
        "Vivaldi, Edge, Brave or Chromium over the DevTools port written when "
        f"you tick \"{ALLOW_REMOTE_DEBUGGING}\". Set SEARCHTS_LINKEDIN_ATTACH=off "
        "to keep the launch path."
    )


def _from_basename(path: str) -> str:
    base = os.path.basename(path.replace("\\", "/")).lower()
    if base.endswith(".exe"):
        base = base[:-4]
    for needle, name in _BASENAMES:
        if base == needle or base.startswith(needle + "-") or base.startswith(needle + "."):
            return name
    return ""


def _from_path(path: str) -> str:
    text = path.replace("\\", "/").lower()
    if not text.endswith("/"):
        text = text + "/"
    for needle, name in _PATH_HINTS:
        if needle in text:
            return name
    return ""


def browser_of(
    executable: Optional[str],
    profile: Optional[str],
    kept: Optional[str],
) -> Tuple[str, bool]:
    """``(browser, explicit)`` for this read.

    The executable basename wins, then a hint in the profile path, then
    the kept login's browser when it is one this module knows, then Chrome.
    ``explicit`` is true only when the executable or the profile path named
    the browser. A kept login alone is not an explicit choice.
    """
    if executable:
        found = _from_basename(executable)
        if found:
            return found, True
    if profile:
        found = _from_path(profile)
        if found:
            return found, True
    kept_name = (kept or "").strip().lower()
    known = set(ATTACH_BROWSERS) | set(FIREFOX_FAMILY) | set(_UNSUPPORTED)
    if kept_name in known:
        return kept_name, False
    return "chrome", False


def candidate_user_data_dirs(browser: str) -> list[str]:
    """User-data directories for ``browser``, this platform first.

    Only the five attach browsers have directories here. The first entry
    that exists is the one a discovery looks at. A configured profile is
    never replaced by this list.
    """
    key = (browser or "").strip().lower()
    home = os.path.expanduser("~")
    local = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    linux = {
        "chrome": os.path.join(home, ".config", "google-chrome"),
        "chromium": os.path.join(home, ".config", "chromium"),
        "edge": os.path.join(home, ".config", "microsoft-edge"),
        "brave": os.path.join(home, ".config", "BraveSoftware", "Brave-Browser"),
        "vivaldi": os.path.join(home, ".config", "vivaldi"),
    }
    mac = {
        "chrome": os.path.join(home, "Library", "Application Support", "Google", "Chrome"),
        "chromium": os.path.join(home, "Library", "Application Support", "Chromium"),
        "edge": os.path.join(home, "Library", "Application Support", "Microsoft Edge"),
        "brave": os.path.join(
            home, "Library", "Application Support", "BraveSoftware", "Brave-Browser"
        ),
        "vivaldi": os.path.join(home, "Library", "Application Support", "Vivaldi"),
    }
    win = {
        "chrome": os.path.join(local, "Google", "Chrome", "User Data"),
        "chromium": os.path.join(local, "Chromium", "User Data"),
        "edge": os.path.join(local, "Microsoft", "Edge", "User Data"),
        "brave": os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data"),
        "vivaldi": os.path.join(local, "Vivaldi", "User Data"),
    }
    if key not in linux:
        return []
    if os.name == "nt":
        return [win[key]]
    if sys.platform == "darwin":
        return [mac[key], linux[key]]
    return [linux[key], mac[key]]


def default_user_data(browser: str) -> str:
    """The first existing user-data directory for ``browser``, or ``""``."""
    for path in candidate_user_data_dirs(browser):
        if os.path.isdir(path):
            return path
    return ""


def _env_path(name: str) -> Optional[str]:
    raw = os.environ.get(name, "").strip()
    return os.path.expanduser(raw) if raw else None


def browser_is_running(profile: str) -> bool:
    """True when a Chromium process holds ``profile``.

    POSIX is a live ``SingletonLock`` pid. Windows is a ``lockfile`` that
    cannot be opened because the browser still holds it. Both checks live
    in :mod:`searchts.linkedin_feed` so a test that patches that module's
    ``os.name`` still describes the same lock.
    """
    if not profile or not os.path.isdir(profile):
        return False
    from searchts import linkedin_feed as lf

    if lf._windows_profile_locked(profile):
        return True
    lock = os.path.join(profile, "SingletonLock")
    if not os.path.lexists(lock):
        return False
    try:
        target = os.readlink(lock)
    except OSError:
        return False
    pid = 0
    if "-" in target:
        try:
            pid = int(target.rsplit("-", 1)[-1])
        except ValueError:
            pid = 0
    return bool(pid and lf._pid_alive(pid))


def probe_port(port: int, timeout: float = 0.2) -> bool:
    """True when something accepts TCP on loopback at ``port``.

    ``127.0.0.1`` is tried first, then ``::1``. Chromium binds the inspect
    server to ``127.0.0.1`` and falls back to ``::1``. This does not speak
    HTTP: approval mode would 404 ``/json/version``, and a probe must not
    depend on that.
    """
    for host in ("127.0.0.1", "::1"):
        family = socket.AF_INET6 if host == "::1" else socket.AF_INET
        sock: Optional[socket.socket] = None
        try:
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, int(port)))
            return True
        except OSError:
            continue
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
    return False


def read_active_port(user_data: str) -> Optional[ActivePort]:
    """Parse ``DevToolsActivePort`` in ``user_data``, or None when it is absent."""
    if not user_data:
        return None
    path = os.path.join(user_data, "DevToolsActivePort")
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return None
    return parse_active_port(text)


def normalize_endpoint(endpoint: str) -> str:
    """An explicit debugging URL, required to be on this machine.

    ``host:port`` becomes ``http://host:port``. A WebSocket URL is kept.
    Anything that is not loopback is refused before a connection is tried.
    """
    raw = (endpoint or "").strip()
    if "://" not in raw:
        raw = "http://" + raw
    host = (urlparse(raw).hostname or "").lower().rstrip(".")
    if host not in _LOOPBACK:
        raise ValueError(
            "the DevTools endpoint has to be on this machine (127.0.0.1). "
            "Nothing was requested."
        )
    return raw


def kept_browser() -> str:
    """The browser that minted the kept LinkedIn login, or ``""``.

    A missing store, or a store with no LinkedIn entry, is not an error:
    the read then treats the browser as Chrome unless one was named.
    """
    try:
        from searchts.session_cookies import read_owned_site

        return str(read_owned_site("linkedin.com").browser or "").strip().lower()
    except Exception:  # noqa: BLE001 - no store is "no kept browser"
        return ""


def decide(
    *,
    mode: Optional[str] = None,
    profile: Optional[str] = None,
    executable: Optional[str] = None,
    endpoint: Optional[str] = None,
    kept_browser_name: Optional[str] = None,
    is_running: Optional[Callable[[str], bool]] = None,
    probe: Optional[Callable[[int], bool]] = None,
) -> Decision:
    """Choose attach, launch, or a refusal that sends nothing.

    An explicit endpoint (``SEARCHTS_LINKEDIN_CDP`` or ``endpoint``) attaches
    even when the mode is ``off``, and does not look for ``DevToolsActivePort``.
    ``auto`` attaches only when the chosen browser is running and its
    active-port file names a loopback port that accepts a connection. A
    running browser with no live port is a refusal that names the inspect
    page. A browser that is not running falls back to launch, including
    when a stale active-port file is still on disk. ``on`` never launches.

    When ``profile`` is given, only that directory is inspected. The
    default user-data directory is used only when no profile is configured.
    ``is_running`` and ``probe`` are injection points so a test never opens
    a socket and never looks at this machine's browser.
    """
    chosen_mode = parse_mode(mode)
    if profile is None:
        profile = _env_path("SEARCHTS_LINKEDIN_PROFILE")
    if executable is None:
        executable = _env_path("SEARCHTS_LINKEDIN_CHROME")
    if endpoint is None:
        endpoint = os.environ.get("SEARCHTS_LINKEDIN_CDP", "")
    endpoint = (endpoint or "").strip()
    if endpoint:
        return Decision(
            action="attach",
            endpoint=normalize_endpoint(endpoint),
            user_data=profile or "",
        )

    if kept_browser_name is None:
        kept = kept_browser()
    else:
        kept = kept_browser_name
    name, explicit = browser_of(executable, profile, kept)
    label = _display(name)

    if name in FIREFOX_FAMILY:
        if chosen_mode == "on" or (chosen_mode == "auto" and explicit):
            return Decision(action="refuse", browser=name, message=_firefox_message(label))
        return Decision(action="launch", browser=name)

    if name in _UNSUPPORTED:
        if chosen_mode == "off" or (chosen_mode == "auto" and not explicit):
            return Decision(action="launch", browser=name)
        return Decision(
            action="refuse", browser=name, message=_unsupported_message(label)
        )

    if chosen_mode == "off":
        return Decision(action="launch", browser=name)

    user_data = profile or ""
    if not user_data:
        user_data = default_user_data(name)
    running = False
    if user_data:
        check = is_running if is_running is not None else browser_is_running
        running = bool(check(user_data))
    if not running:
        if chosen_mode == "on":
            return Decision(
                action="refuse",
                browser=name,
                message=_not_running(label, inspect_url(name)),
                user_data=user_data,
            )
        return Decision(action="launch", browser=name, user_data=user_data)

    active = read_active_port(user_data)
    live = False
    if active is not None:
        check_port = probe if probe is not None else probe_port
        live = bool(check_port(active.port))
    if active is not None and live:
        return Decision(
            action="attach",
            endpoint=endpoint_for(active.port, active.ws_path),
            browser=name,
            user_data=user_data,
        )
    return Decision(
        action="refuse",
        browser=name,
        message=_debug_off(label, inspect_url(name)),
        user_data=user_data,
    )


def _no_window(browser: str) -> str:
    """The debugging port is up, and the browser has no window to attach to.

    Chrome 136+ ignores ``--remote-debugging-port`` on the default profile,
    so the message does not suggest that flag. The inspect toggle is already
    on (that is why the port exists). What is missing is a window.
    """
    known = (browser or "").strip().lower()
    if known:
        label = _display(known)
        url = inspect_url(known)
        return (
            f"{label} is listening on the debugging port, but it has no open "
            f"window. Open a window in {label} (the toggle at {url} is already "
            "on) and read again. A new browser context is not opened."
        )
    return (
        "The browser is listening on the debugging port, but it has no open "
        "window. Open a window in that browser (the toggle at "
        "chrome://inspect/#remote-debugging, or vivaldi://, edge:// or "
        "brave://, is already on) and read again. A new browser context is "
        "not opened."
    )


def new_tab(browser: Any, browser_name: str = "") -> Any:
    """One new tab in the window the debugging port already has.

    A fresh context would be a second client, with a different cookie jar
    from the window that is already signed in. No window means attaching
    is refused. This never calls ``new_context``. ``browser_name`` is the
    browser that owns the port (``vivaldi``, ``edge``, ``brave``, …), so
    the refusal names that browser and its inspect page.
    """
    contexts = list(getattr(browser, "contexts", []) or [])
    if not contexts:
        raise AttachError(_no_window(browser_name))
    return contexts[0].new_page()


def _close_page(page: Any) -> None:
    try:
        page.close()
    except Exception:  # noqa: BLE001 - the user may already have closed the tab
        pass


def _connect_failure(exc: BaseException) -> str:
    return (
        "could not attach to the browser over the DevTools port "
        f"({type(exc).__name__}). If the browser asked to allow remote "
        "debugging, accept that prompt and read again. Nothing was "
        "requested from LinkedIn."
    )


@contextmanager
def open_tab(
    endpoint: str,
    *,
    connect: Optional[Callable[[str], Any]] = None,
    browser_name: str = "",
) -> Iterator[Any]:
    """Connect to ``endpoint``, yield one new tab, and close only that tab.

    ``connect`` replaces the real DevTools connection in tests. The
    caller's body runs only after the connection and the tab exist. On
    the way out the tab is closed. The browser object is never closed,
    and exiting the DevTools session only drops this process's socket.
    """
    if connect is not None:
        try:
            browser = connect(endpoint)
        except AttachError:
            raise
        except Exception as exc:  # noqa: BLE001 - the connection is the failure
            raise AttachError(_connect_failure(exc)) from exc
        page = new_tab(browser, browser_name)
        try:
            yield page
        finally:
            _close_page(page)
        return

    try:
        from patchright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001 - the extra is the normal case
        raise AttachError(
            "the LinkedIn read needs the stealth browser. Run: "
            "searchts install --browser"
        ) from exc

    playwright = sync_playwright()
    entered = False
    try:
        try:
            pw = playwright.__enter__()
            entered = True
            browser = pw.chromium.connect_over_cdp(endpoint)
        except AttachError:
            raise
        except Exception as exc:  # noqa: BLE001 - name the attach fault, not a stack
            raise AttachError(_connect_failure(exc)) from exc
        page = new_tab(browser, browser_name)
        try:
            yield page
        finally:
            _close_page(page)
    finally:
        if entered:
            try:
                playwright.__exit__(None, None, None)
            except Exception:  # noqa: BLE001 - disconnecting the socket is best-effort
                pass
