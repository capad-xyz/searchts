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

The read opens one tab in a normal browser window and closes only that tab.
An installed app/PWA window, an extension popup, DevTools and background
pages are never reused, and that tab is the only target closed. The browser
process, its other tabs, and its windows stay as the user left them.
Nothing in this module navigates anywhere.

Chromium shows the "being controlled by automated test software" infobar
for every window of a browser started with ``--enable-automation``, so the
infobar can appear on an app window even when this read did not use it.
That infobar is browser-wide and cannot be avoided by choosing a window.
"""

from __future__ import annotations

import os
import socket
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlparse

from searchts.session_cookies import FIREFOX_FAMILY

__all__ = [
    "ALLOW_REMOTE_DEBUGGING",
    "ATTACH_BROWSERS",
    "ActivePort",
    "AttachError",
    "Decision",
    "OpenedTab",
    "WindowTarget",
    "browser_is_running",
    "browser_of",
    "candidate_user_data_dirs",
    "cdp_timeout_ms",
    "cdp_timeout_seconds",
    "connect_failure_message",
    "decide",
    "endpoint_for",
    "inspect_url",
    "kept_browser",
    "new_tab",
    "open_tab",
    "page_windows",
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
        f"({names}) stay on cookie copy only. Set SEARCHTS_BROWSER to Chrome, "
        "Vivaldi, Edge, Brave or Chromium (SEARCHTS_LINKEDIN_CHROME is the "
        "legacy alias), or set SEARCHTS_LINKEDIN_ATTACH=off."
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


def candidate_user_data_dirs(
    browser: str,
    *,
    platform: Optional[str] = None,
    env: Optional[dict] = None,
) -> list[str]:
    """User-data directories for ``browser``, this platform first.

    Every Chromium-family browser has directories here, including Opera and
    Arc, so browser detection and the cookie-presence scan use the same list
    the attach path does. ``platform`` and ``env`` exist for tests: by default
    the current platform and environment are used. The first entry that
    exists is the one a discovery looks at. A configured profile is never
    replaced by this list.
    """
    key = (browser or "").strip().lower()
    environ = os.environ if env is None else env
    home = (
        environ.get("HOME")
        or environ.get("USERPROFILE")
        or os.path.expanduser("~")
    )
    local = environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    roaming = environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
    linux = {
        "chrome": os.path.join(home, ".config", "google-chrome"),
        "chromium": os.path.join(home, ".config", "chromium"),
        "edge": os.path.join(home, ".config", "microsoft-edge"),
        "brave": os.path.join(home, ".config", "BraveSoftware", "Brave-Browser"),
        "vivaldi": os.path.join(home, ".config", "vivaldi"),
        "opera": os.path.join(home, ".config", "opera"),
        "arc": os.path.join(home, ".config", "Arc"),
    }
    mac = {
        "chrome": os.path.join(home, "Library", "Application Support", "Google", "Chrome"),
        "chromium": os.path.join(home, "Library", "Application Support", "Chromium"),
        "edge": os.path.join(home, "Library", "Application Support", "Microsoft Edge"),
        "brave": os.path.join(
            home, "Library", "Application Support", "BraveSoftware", "Brave-Browser"
        ),
        "vivaldi": os.path.join(home, "Library", "Application Support", "Vivaldi"),
        "opera": os.path.join(
            home, "Library", "Application Support", "com.operasoftware.Opera"
        ),
        "arc": os.path.join(home, "Library", "Application Support", "Arc", "User Data"),
    }
    win = {
        "chrome": os.path.join(local, "Google", "Chrome", "User Data"),
        "chromium": os.path.join(local, "Chromium", "User Data"),
        "edge": os.path.join(local, "Microsoft", "Edge", "User Data"),
        "brave": os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data"),
        "vivaldi": os.path.join(local, "Vivaldi", "User Data"),
        "opera": os.path.join(roaming, "Opera Software", "Opera Stable"),
        "arc": os.path.join(local, "Arc", "User Data"),
    }
    if key not in linux:
        return []
    chosen = platform
    if chosen is None:
        chosen = (
            "windows" if os.name == "nt"
            else "macos" if sys.platform == "darwin"
            else "linux"
        )
    if chosen == "windows":
        return [win[key]]
    if chosen == "macos":
        return [mac[key], linux[key]]
    return [linux[key], mac[key]]


def default_user_data(browser: str) -> str:
    """The first existing user-data directory for ``browser``, or ``""``."""
    for path in candidate_user_data_dirs(browser):
        if os.path.isdir(path):
            return path
    return ""


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
        from searchts.browser_settings import browser_profile

        profile = browser_profile()
    if executable is None:
        from searchts.browser_settings import browser_executable

        executable = browser_executable()
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


def new_tab(browser: Any, browser_name: str = "") -> "OpenedTab":
    """One new tab in a normal browser window, or a named refusal.

    A fresh context would be a second client, with a different cookie jar
    from the window that is already signed in. This never calls
    ``new_context``. ``browser_name`` is the browser that owns the port
    (``vivaldi``, ``edge``, ``brave``, …), so a refusal names that browser
    and its inspect page.

    A tab is never opened by asking Chromium for "the last used window": an
    installed app/PWA window, an extension popup, DevTools or a background
    page can be that window. The browser-wide DevTools session lists the
    targets, :func:`page_windows` keeps only pages in normal-looking windows,
    and the tab this module made is checked with ``display-mode: browser``
    before it is handed back. When no normal window exists, one is opened
    with ``Target.createTarget(newWindow=True)``.
    """
    contexts = list(getattr(browser, "contexts", []) or [])
    if not contexts:
        raise AttachError(_no_window(browser_name))
    context = contexts[0]
    cdp = _browser_session(browser, browser_name)
    try:
        for window in page_windows(cdp)[:_WINDOW_ATTEMPTS]:
            _activate(cdp, window.target_id)
            tab = _tab_in_browser_window(context, cdp, browser_name)
            if tab is not None:
                return tab
        return _tab_in_new_window(context, cdp, browser_name)
    except BaseException:
        _detach(cdp)
        raise


def _close_page(page: Any) -> None:
    try:
        page.close()
    except Exception:  # noqa: BLE001 - the user may already have closed the tab
        pass


@dataclass(frozen=True)
class WindowTarget:
    """One page target that marks a browser window we may use.

    ``Browser.getWindowForTarget`` is the only window identity Chromium puts
    on the DevTools protocol: it returns a window id and bounds, not a window
    type. The target behind it is kept so the window can be activated before
    a tab is created in it.
    """

    window_id: int
    target_id: str
    url: str

    @property
    def rank(self) -> int:
        """A web page is a stronger sign of a normal window than about:blank."""
        return 0 if _scheme(self.url) in ("http", "https") else 1


class OpenedTab:
    """The one tab this module made, and the handle that closes only it.

    ``target_id`` is the CDP target id of that tab. ``close`` asks the
    browser to close that target and nothing else, then drops this process's
    DevTools session. It never closes the browser, another tab or a window.
    """

    def __init__(self, page: Any, cdp: Any = None, target_id: str = "") -> None:
        self.page = page
        self.target_id = target_id
        self._cdp = cdp

    def close(self) -> None:
        closed = False
        if self._cdp is not None and self.target_id:
            try:
                self._cdp.send("Target.closeTarget", {"targetId": self.target_id})
                closed = True
            except Exception:  # noqa: BLE001 - fall back to the page handle
                closed = False
        if not closed:
            _close_page(self.page)
        _detach(self._cdp)


#: Schemes that belong to browser UI, extension UI, DevTools or an installed
#: app's own page. Vivaldi's UI is an extension page
#: (``chrome-extension://mpognobbkildjkofajifpdfhcoklimli/...``) and its own
#: pages are ``vivaldi://``, so both are skipped. So is every other browser's
#: UI scheme, in case a page target points there.
_BROWSER_UI_SCHEMES = frozenset(
    {
        "arc",
        "brave",
        "chrome",
        "chrome-extension",
        "chrome-search",
        "chrome-untrusted",
        "devtools",
        "edge",
        "filesystem",
        "isolated-app",
        "opera",
        "view-source",
        "vivaldi",
    }
)

#: Schemes a normal tab can hold. ``about:blank`` is what Chromium opens in a
#: new normal window, and a window that only has one is still a normal window.
_PAGE_SCHEMES = frozenset({"about", "blob", "data", "file", "http", "https"})

#: How many existing windows to try before opening one. The first is the
#: common case; a second covers a window that only looked normal.
_WINDOW_ATTEMPTS = 2

#: The web-platform display mode of a tab. Chromium answers ``browser`` for a
#: tab in a normal browser window and ``standalone``, ``minimal-ui``,
#: ``fullscreen`` or ``window-controls-overlay`` for a page inside an installed
#: web app window. It is evaluated on the blank tab this module made, never on
#: the user's own page.
_DISPLAY_MODE_BROWSER = "matchMedia('(display-mode: browser)').matches"


def _scheme(url: Any) -> str:
    try:
        return (urlparse(str(url or "")).scheme or "").lower()
    except ValueError:
        return ""


def _is_page_target(info: Any) -> bool:
    """True for a ``page`` target whose URL a normal tab could hold.

    Chromium's other target types are not a tab: ``app`` (a hosted, legacy
    packaged or platform app, or an Isolated Web App), ``browser_ui``,
    ``webview``, ``iframe``, ``other``, the worker types and
    ``background_page``. Only ``page`` survives here, and the URL must be one
    a normal tab can hold.
    """
    if not isinstance(info, dict):
        return False
    if str(info.get("type") or "") != "page":
        return False
    scheme = _scheme(info.get("url"))
    return scheme in _PAGE_SCHEMES and scheme not in _BROWSER_UI_SCHEMES


def page_windows(cdp: Any) -> List[WindowTarget]:
    """Browser windows that hold a page we may put a tab in, best first.

    Chromium's protocol has no window type, so the filter is made of what it
    does expose: a target's ``type`` and ``url``, and the window id from
    ``Browser.getWindowForTarget``. Installed apps are ``type: "app"``;
    extension UI, DevTools and the browsers' own pages are non-web schemes or
    ``browser_ui``; frames, workers and background pages are not tabs. Each
    window appears once, with the target used to activate it before the tab
    is created.

    A PWA window that hosts an ordinary http(s) page still looks like a page
    target here. :func:`new_tab` therefore checks the display mode of the tab
    it made, and never hands back a tab inside an app window.
    """
    try:
        reply = cdp.send("Target.getTargets") or {}
    except Exception as exc:  # noqa: BLE001 - name the attach fault
        raise AttachError(_windows_failure(exc)) from exc
    infos = list(reply.get("targetInfos") or [])
    windows: Dict[int, WindowTarget] = {}
    for info in infos:
        if not _is_page_target(info):
            continue
        target_id = str(info.get("targetId") or "")
        if not target_id:
            continue
        try:
            found = cdp.send("Browser.getWindowForTarget", {"targetId": target_id}) or {}
        except Exception:  # noqa: BLE001 - browser UI targets have no window
            continue
        window_id = found.get("windowId")
        if not isinstance(window_id, int):
            continue
        candidate = WindowTarget(window_id, target_id, str(info.get("url") or ""))
        current = windows.get(window_id)
        if current is None or (candidate.rank, candidate.target_id) < (
            current.rank,
            current.target_id,
        ):
            windows[window_id] = candidate
    return sorted(windows.values(), key=lambda window: (window.rank, window.window_id))


def _browser_session(browser: Any, browser_name: str) -> Any:
    try:
        return browser.new_browser_cdp_session()
    except Exception as exc:  # noqa: BLE001 - the connection is the failure
        raise AttachError(_windows_failure(exc, browser_name)) from exc


def _activate(cdp: Any, target_id: str) -> None:
    """Make this window the last active one, so Chromium puts the tab there."""
    try:
        cdp.send("Target.activateTarget", {"targetId": target_id})
    except Exception:  # noqa: BLE001 - the display-mode check still decides
        pass


def _tab_in_browser_window(
    context: Any, cdp: Any, browser_name: str
) -> Optional["OpenedTab"]:
    """One new tab, or None when it landed in an app/PWA window."""
    try:
        page = context.new_page()
    except Exception as exc:  # noqa: BLE001 - name the refusal, not a stack
        raise AttachError(_could_not_open(browser_name, exc)) from exc
    if _page_is_in_browser_window(page) is False:
        _close_page(page)
        return None
    return OpenedTab(page, cdp, _target_id_of(context, page))


def _tab_in_new_window(context: Any, cdp: Any, browser_name: str) -> "OpenedTab":
    """A normal window opened for this tab, then a tab next to its blank one."""
    anchor = _create_window(cdp)
    try:
        tab = _tab_in_browser_window(context, cdp, browser_name)
    finally:
        _close_target(cdp, anchor)
    if tab is None:
        raise AttachError(_no_normal_window(browser_name))
    return tab


def _create_window(cdp: Any) -> str:
    """Open a normal browser window; return the blank target inside it.

    ``newWindow`` makes Chromium create a normal tabbed window, not an app
    window. The blank target only holds that window open until the real tab
    exists; it is closed by target id right after.
    """
    params: Dict[str, Any] = {"url": "about:blank", "newWindow": True}
    context_id = _default_context_id(cdp)
    if context_id:
        params["browserContextId"] = context_id
    try:
        made = cdp.send("Target.createTarget", params) or {}
    except Exception:  # noqa: BLE001 - the caller falls back to the display check
        return ""
    return str(made.get("targetId") or "")


def _default_context_id(cdp: Any) -> str:
    """The default browser context id, from a target that already exists.

    Passing it keeps the tab in the profile that is already signed in. No id
    is fine too: Chromium then uses the last used profile.
    """
    try:
        reply = cdp.send("Target.getTargets") or {}
    except Exception:  # noqa: BLE001 - an omitted id is the fallback
        return ""
    infos = list(reply.get("targetInfos") or [])
    for info in infos:
        if isinstance(info, dict) and _is_page_target(info):
            context_id = str(info.get("browserContextId") or "")
            if context_id:
                return context_id
    for info in infos:
        if isinstance(info, dict):
            context_id = str(info.get("browserContextId") or "")
            if context_id:
                return context_id
    return ""


def _page_is_in_browser_window(page: Any) -> Optional[bool]:
    """True/False from the page's window, or None when it cannot be read.

    ``display-mode: browser`` is the web-platform way to tell a tab in a
    normal window from a page inside an installed web app. Chromium reports
    the window's own display mode, so a tab created in a PWA window answers
    False even though its target is ``type: "page"`` with an https URL.
    """
    try:
        value = page.evaluate(_DISPLAY_MODE_BROWSER)
    except Exception:  # noqa: BLE001 - an unreadable blank tab stays usable
        return None
    return value if isinstance(value, bool) else None


def _target_id_of(context: Any, page: Any) -> str:
    """The CDP target id behind ``page``, or "" when it cannot be read."""
    session = None
    try:
        session = context.new_cdp_session(page)
        info = session.send("Target.getTargetInfo") or {}
        return str((info.get("targetInfo") or {}).get("targetId") or "")
    except Exception:  # noqa: BLE001 - closing falls back to the page handle
        return ""
    finally:
        _detach(session)


def _close_target(cdp: Any, target_id: str) -> None:
    if cdp is None or not target_id:
        return
    try:
        cdp.send("Target.closeTarget", {"targetId": target_id})
    except Exception:  # noqa: BLE001 - the window may already be gone
        pass


def _detach(session: Any) -> None:
    if session is None:
        return
    try:
        session.detach()
    except Exception:  # noqa: BLE001 - detaching only drops this socket
        pass


def _windows_failure(exc: BaseException, browser: str = "") -> str:
    known = (browser or "").strip().lower()
    label = _display(known) if known else "The browser"
    return (
        f"{label} could not list its windows over the DevTools port "
        f"({type(exc).__name__}). The browser and its tabs were left alone. "
        "Nothing was requested from LinkedIn."
    )


def _could_not_open(browser: str, exc: BaseException) -> str:
    known = (browser or "").strip().lower()
    if known:
        label = _display(known)
        return (
            f"{label} did not open a tab in a normal window "
            f"({type(exc).__name__}). Open a normal {label} window (not an "
            "installed app window) and read again. The browser and its other "
            "tabs were left open. Nothing was requested from LinkedIn."
        )
    return (
        "The browser did not open a tab in a normal window "
        f"({type(exc).__name__}). Open a normal browser window (not an "
        "installed app window) and read again. The browser and its other "
        "tabs were left open. Nothing was requested from LinkedIn."
    )


def _no_normal_window(browser: str) -> str:
    """A new window was opened, and even that tab was not a browser tab."""
    known = (browser or "").strip().lower()
    if known:
        label = _display(known)
        return (
            f"{label} did not give the read a tab in a normal window. An "
            "installed app, PWA, popup, DevTools or extension window is never "
            f"used. Open a normal {label} window and read again. The browser "
            "and its windows were left open. Nothing was requested from "
            "LinkedIn."
        )
    return (
        "The browser did not give the read a tab in a normal window. An "
        "installed app, PWA, popup, DevTools or extension window is never "
        "used. Open a normal browser window and read again. The browser and "
        "its windows were left open. Nothing was requested from LinkedIn."
    )


def cdp_timeout_seconds() -> float:
    """How long to wait for the browser's Allow click, in seconds.

    Chromium's approval dialog blocks the DevTools WebSocket until a person
    answers, so this is a person's reaction time rather than a network
    timeout. ``SEARCHTS_LINKEDIN_CDP_TIMEOUT_SECONDS`` sets it (1-300).
    """
    raw = os.environ.get("SEARCHTS_LINKEDIN_CDP_TIMEOUT_SECONDS", "60")
    try:
        seconds = float(raw)
    except ValueError:
        seconds = 60.0
    if seconds <= 0:
        seconds = 60.0
    return max(1.0, min(seconds, 300.0))


def cdp_timeout_ms() -> int:
    return int(cdp_timeout_seconds() * 1000)


def _is_timeout(exc: BaseException) -> bool:
    # Playwright raises ``TimeoutError``, but an underlying client error can
    # carry the same wording with a generic type name.
    return "timeout" in type(exc).__name__.lower() or "timeout" in str(exc).lower()


def connect_failure_message(exc: BaseException) -> str:
    """One sentence for a failed DevTools handshake.

    A timeout means the approval dialog was not answered: the WebSocket hangs
    while Chromium waits for the click, so the wait is named with the exact
    configured number. Any other client error keeps the generic prompt.
    """
    if _is_timeout(exc):
        seconds = cdp_timeout_seconds()
        return (
            f"could not attach to the browser over the DevTools port: no Allow "
            f"click within {seconds:g} s. The browser asked to allow remote "
            f"debugging and the request timed out. Click Allow in the browser, "
            f"then read again. Nothing was requested from LinkedIn. "
            f"SEARCHTS_LINKEDIN_CDP_TIMEOUT_SECONDS sets the wait."
        )
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
            raise AttachError(connect_failure_message(exc)) from exc
        tab = new_tab(browser, browser_name)
        try:
            yield tab.page
        finally:
            tab.close()
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
            browser = pw.chromium.connect_over_cdp(
                endpoint, timeout=cdp_timeout_ms(),
            )
        except AttachError:
            raise
        except Exception as exc:  # noqa: BLE001 - name the attach fault, not a stack
            raise AttachError(connect_failure_message(exc)) from exc
        tab = new_tab(browser, browser_name)
        try:
            yield tab.page
        finally:
            tab.close()
    finally:
        if entered:
            try:
                playwright.__exit__(None, None, None)
            except Exception:  # noqa: BLE001 - disconnecting the socket is best-effort
                pass
