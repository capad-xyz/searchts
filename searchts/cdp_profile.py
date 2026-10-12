# -*- coding: utf-8 -*-
"""Chromium cookies through a debugger port, asked for first.

Chrome, Edge, Brave, Vivaldi, Opera and Arc keep their cookie values behind
App-Bound Encryption (Chrome 127+): the file on disk is ciphertext another
process cannot unwrap, even with the user's own DPAPI key. Reading a Chromium
login therefore cannot be a file read. The way through is to let the browser
itself hand the values over, over the DevTools protocol (CDP), for one site,
and to throw the copy it used away afterwards.

So this module runs a SECOND instance of the user's own browser:

    1. ask. searchts never opens the port on its own; without a ``confirm``
       callable it aborts with a one-line reason.
    2. copy the profile into a throwaway scratch directory, so the running
       browser is never disturbed and the real profile is never written to.
    3. launch that browser with ``--remote-debugging-port`` and
       ``--user-data-dir=<scratch>``, connect over CDP, read the cookies for
       ONE host, close it.
    4. delete the scratch copy in a ``finally``. This is not tidiness. A
       leftover scratch profile is a second jar of every login the user has,
       readable by anything running as them.

The copy in step 2 is not an optimisation. Chrome 136+ ignores
``--remote-debugging-port`` against the default profile on purpose, so the
only way to get a browser that will talk to us is one pointed at a
user-data-dir that is not the default. Hence a scratch copy, hence its
mandatory deletion.

Two ways in, and the difference is who opened the port:

    cdp_read_site(...)        searchts opens the port, with consent, and closes
                              the browser itself. Nothing survives the call.
    connect_existing_cdp(...) attaches to a port the USER already opened (the
                              ``--cdp-port 9222`` case). Localhost only, and
                              searchts disconnects without closing their
                              browser.

Everything here is read-only with respect to the user's real profile and
never prints a cookie value. See ``session_cookies`` for the scoping rule that
keeps a cookie attached only to requests for the host that owns it.
"""

from __future__ import annotations

import ipaddress
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator, List, Optional, Tuple
from urllib.parse import urlparse

from searchts.session_cookies import (
    CHROMIUM_FAMILY,
    CookieReadError,
    CookieRecord,
    CookieSource,
    filter_for_host,
    for_site,
)

#: Where the CDP read gives up waiting for the debugger port to answer.
CDP_READY_TIMEOUT_S = 20.0

#: How often the wait re-checks. Short, because a Chromium that is going to
#: open the port does it in about a second.
_CDP_POLL_S = 0.1

#: Profile files that must not be copied. A lock file copied into the scratch
#: profile makes the new instance think another instance owns it, and the read
#: then returns the empty cookie jar of a browser that never loaded anything.
_PROFILE_NOISE = (
    "SingletonLock",
    "SingletonCookie",
    "SingletonSocket",
    "lockfile",
    "lockfiles",
)

#: Executable names per browser, for PATH lookup.
_EXE_NAMES = {
    "chrome": ("chrome", "google-chrome", "google-chrome-stable", "chrome.exe"),
    "edge": ("msedge", "microsoft-edge", "msedge.exe"),
    "brave": ("brave", "brave.exe", "brave-browser"),
    "vivaldi": ("vivaldi", "vivaldi.exe"),
    "opera": ("opera", "opera.exe"),
    "arc": ("arc", "arc.exe"),
    "chromium": ("chromium", "chromium.exe", "chrome"),
}

#: Windows install paths, for the browsers that are not on PATH.
_WINDOWS_EXE = {
    "chrome": r"Google\Chrome\Application\chrome.exe",
    "edge": r"Microsoft\Edge\Application\msedge.exe",
    "brave": r"BraveSoftware\Brave-Browser\Application\brave.exe",
    "vivaldi": r"Vivaldi\Application\vivaldi.exe",
    "opera": r"Opera\Opera Stable\Launcher.exe",
    "chromium": r"Chromium\Application\chrome.exe",
}


class ConsentRequired(Exception):
    """The debugger port was not authorised. Raised instead of opening it.

    Deliberately not a subclass of ``CookieReadError``: callers that catch the
    read failures would otherwise swallow the one answer that means "the user
    said no", and a refused consent would look like an unreadable site.
    """


def consent_prompt(browser: str, host: str, port: int) -> str:
    """The question, in full. Nothing here is skippable, so nothing is short.

    Two facts have to survive into the sentence the user actually reads: the
    browser will show a bar saying it is under automated control, and the port
    is open to every program on the machine until that browser quits. Both are
    true whether or not the user is technical enough to know what they mean.
    """
    return (
        f"{browser} has locked its cookie file (App-Bound Encryption), so "
        f"searchts cannot read it from disk.\n"
        f"Instead searchts can open a second {browser} window with a debugger "
        f"port on 127.0.0.1:{port}, and ask that window for {host} only.\n"
        f"Two things to know first:\n"
        f"  - {browser} will show a bar saying it is being controlled by "
        f"automated software.\n"
        f"  - while that window is open, any program on this computer can use "
        f"port {port} and read the logins in it.\n"
        f"searchts closes that window and deletes the profile copy when it is "
        f"done. Open it to read {host}?"
    )


# ── host, browser and executable ─────────────────────────────────────────────


def _host_of(site: str) -> str:
    host = (urlparse(site if "://" in site else "https://" + site).hostname or "").lower()
    if not host:
        raise CookieReadError(f"cannot work out a host from {site!r}")
    return host


def _need_chromium(browser: str) -> str:
    b = (browser or "").strip().lower()
    if b not in CHROMIUM_FAMILY:
        raise CookieReadError(
            f"{browser!r} is not a Chromium browser this path can read. "
            f"Supported: {', '.join(CHROMIUM_FAMILY)}. "
            "Firefox-derived browsers are read straight off disk instead."
        )
    return b


def browser_executable(browser: str) -> str:
    """Path to `browser`, or a CookieReadError naming how to fix it."""
    b = _need_chromium(browser)
    for name in _EXE_NAMES.get(b, ()):
        found = shutil.which(name)
        if found:
            return found
    for root_var in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
        root = os.environ.get(root_var) or os.environ.get(root_var.lower()) or ""
        rel = _WINDOWS_EXE.get(b)
        if not root or not rel:
            continue
        cand = os.path.join(root, rel)
        if os.path.isfile(cand):
            return cand
    mac_linux = {
        "chrome": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "edge": "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "brave": "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "vivaldi": "/Applications/Vivaldi.app/Contents/MacOS/Vivaldi",
        "arc": "/Applications/Arc.app/Contents/MacOS/Arc",
    }.get(b)
    if mac_linux and os.path.isfile(mac_linux):
        return mac_linux
    raise CookieReadError(
        f"could not find the {b} executable. Install it, or start it yourself "
        f"with --remote-debugging-port and pass the port to --cdp-port."
    )


# ── the scratch profile ──────────────────────────────────────────────────────


def _profile_source(browser: str) -> str:
    """The user-data-dir to copy. Chromium families differ only by path."""
    b = _need_chromium(browser)
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~") + "/Library/Application Support"
    roaming = os.environ.get("APPDATA") or os.path.expanduser("~") + "/.config"
    home = os.path.expanduser("~")
    if os.name == "nt":
        paths = {
            "chrome": [os.path.join(local, "Google", "Chrome", "User Data")],
            "edge": [os.path.join(local, "Microsoft", "Edge", "User Data")],
            "brave": [os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data")],
            "vivaldi": [os.path.join(local, "Vivaldi", "User Data")],
            "opera": [os.path.join(roaming, "Opera Software", "Opera Stable")],
            "arc": [os.path.join(roaming, "Arc", "User Data")],
            "chromium": [os.path.join(local, "Chromium", "User Data")],
        }
    else:
        paths = {
            "chrome": [
                os.path.join(local, "Google", "Chrome"),
                os.path.join(home, ".config", "google-chrome"),
            ],
            "edge": [
                os.path.join(local, "Microsoft", "Edge"),
                os.path.join(home, ".config", "microsoft-edge"),
            ],
            "brave": [
                os.path.join(local, "BraveSoftware", "Brave-Browser"),
                os.path.join(home, ".config", "BraveSoftware", "Brave-Browser"),
            ],
            "vivaldi": [os.path.join(local, "Vivaldi")],
            "opera": [os.path.join(local, "opera")],
            "arc": [os.path.join(home, ".arc")],
            "chromium": [os.path.join(home, ".config", "chromium")],
        }
    for p in paths.get(b, []):
        if os.path.isdir(p):
            return p
    raise CookieReadError(
        f"no {b} profile found (looked in {', '.join(paths.get(b, []))}). "
        "Log in to that site in the browser first."
    )


def _ignore_profile_noise(_dir: str, names: List[str]) -> set:
    return {n for n in names if n in _PROFILE_NOISE or n.endswith(".tmp")}


def copy_profile(src: str, dst: str) -> None:
    """Copy a Chromium user-data-dir into `dst`. The source is never written to.

    A running browser holds some files open, so this can fail even when the
    profile exists. The message says to close the browser, which is the fix
    and the only thing that helps.
    """
    try:
        shutil.copytree(src, dst, dirs_exist_ok=True, ignore=_ignore_profile_noise)
    except (OSError, shutil.Error) as e:
        raise CookieReadError(
            f"could not copy the {os.path.basename(src)} profile to a scratch "
            f"folder ({type(e).__name__}). Close the browser and try again."
        ) from None


def _scratch_dir() -> str:
    """Create the throwaway profile directory. Its owner deletes it, always."""
    return tempfile.mkdtemp(prefix="searchts-cdp-")


def _purge(path: str) -> Optional[str]:
    """Delete the scratch profile. Returns a reason string if it survived.

    Never raises. A failure to delete must not be able to mask the read's own
    failure, and a leftover has to be reported loudly instead: it is a second
    jar of every login the user has.
    """
    last: Optional[str] = None
    for attempt in range(5):
        try:
            shutil.rmtree(path)
            return None
        except FileNotFoundError:
            return None
        except OSError as e:
            last = f"{type(e).__name__}: {e}"
            # Windows releases a profile file a moment after the browser exits.
            time.sleep(0.2 * (attempt + 1))
    return last


@contextmanager
def _scratch_profile(
    src: str,
    copy_profile_fn: Callable[[str, str], None],
    scratch_fn: Optional[Callable[[], str]] = None,
) -> Iterator[str]:
    """A scratch copy of `src` that is gone on every exit path.

    Success, read failure, and exception all run the same delete. On a
    successful read a delete failure is raised, because returning cookies
    while a copy of the whole profile sits on disk is the worse outcome; on a
    failed read the original exception wins and the leftover is named on
    stderr, so the reason the read failed is never hidden by the cleanup.
    """
    scratch = (scratch_fn or _scratch_dir)()
    try:
        copy_profile_fn(src, scratch)
        yield scratch
    except BaseException:
        leftover = _purge(scratch)
        if leftover:
            _warn_leftover(scratch, leftover)
        raise
    leftover = _purge(scratch)
    if leftover:
        raise CookieReadError(
            f"read the cookies, but could not delete the profile copy at "
            f"{scratch} ({leftover}). Delete that folder now: it is a copy of "
            f"every login in the browser."
        )


def _warn_leftover(scratch: str, why: str) -> None:
    print(
        f"searchts: WARNING: the temporary profile copy at {scratch} could not "
        f"be deleted ({why}). Delete it by hand: it is a copy of every login "
        f"in that browser.",
        file=sys.stderr,
        flush=True,
    )


# ── the browser we launch, and the one the user launched ─────────────────────


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_for_debugger(port: int, clock: Callable[[], float], timeout: float) -> bool:
    """Wait until 127.0.0.1:<port> answers. True if it does before `timeout`."""
    deadline = clock() + timeout
    while clock() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.25)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(_CDP_POLL_S)
    return False


class LaunchedBrowser:
    """A browser this module started, and how to make sure it is gone.

    ``close`` kills the whole tree. A Chromium started this way spawns a dozen
    children, and killing only the parent leaves a window with the user's
    cookies sitting open after the module has returned.
    """

    def __init__(self, process: subprocess.Popen) -> None:
        self._process = process

    @property
    def pid(self) -> int:
        return self._process.pid

    def close(self) -> None:
        proc = self._process
        try:
            if proc.poll() is not None:
                return
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass


def _launch_browser(
    executable: str,
    port: int,
    scratch: str,
    *,
    clock: Optional[Callable[[], float]] = None,
) -> LaunchedBrowser:
    """Start `executable` on a scratch profile with a debugger port open."""
    # The address is pinned rather than left to a Chromium default: this port
    # hands over every login in the copied profile, and a default that changed
    # to 0.0.0.0 would put it on the network.
    args = [
        executable,
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={scratch}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    try:
        process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as e:
        raise CookieReadError(
            f"could not start {os.path.basename(executable)} ({type(e).__name__})."
        ) from None
    ready = _wait_for_debugger(port, clock or time.monotonic, CDP_READY_TIMEOUT_S)
    if not ready:
        LaunchedBrowser(process).close()
        raise CookieReadError(
            f"{os.path.basename(executable)} started but never opened a debugger "
            f"port on 127.0.0.1:{port}. Nothing was left running."
        )
    return LaunchedBrowser(process)


# ── reading through CDP ──────────────────────────────────────────────────────


def _started(pw: Any) -> Any:
    """Enter the object ``sync_playwright()`` hands back, when it needs entering.

    Playwright and patchright return a ``PlaywrightContextManager``. It has no
    ``.chromium`` and no ``.stop()``; entering it starts the driver and returns
    the ``Playwright`` object that has both. Without this step every real CDP
    read dies on ``pw.chromium`` with a bare AttributeError, which is what the
    test doubles hide by returning the started object already.
    """
    enter = getattr(pw, "__enter__", None)
    if callable(enter):
        return enter()
    return pw


def _playwright(playwright_module: Optional[Any]) -> Any:
    """A started Playwright, from an injected module or the real one."""
    if playwright_module is not None:
        return _started(playwright_module.sync_playwright())
    try:
        from patchright.sync_api import sync_playwright
    except ImportError:
        raise CookieReadError(
            "the debugger-port path needs a CDP client: "
            "searchts install --browser"
        ) from None
    return _started(sync_playwright())


def _records_from(cookies: Any) -> List[CookieRecord]:
    out: List[CookieRecord] = []
    for c in cookies:
        try:
            out.append(
                CookieRecord(
                    name=str(c.get("name") or ""),
                    value=str(c.get("value") or ""),
                    domain=str(c.get("domain") or ""),
                    path=str(c.get("path") or "/"),
                    secure=bool(c.get("secure")),
                    http_only=bool(c.get("httpOnly", c.get("http_only"))),
                )
            )
        except AttributeError:
            raise CookieReadError(
                "the CDP client returned something that is not a cookie list; "
                "expected dicts with name/value/domain"
            ) from None
    return out


def _read_one_site(browser_obj: Any, site: str, host: str, source: CookieSource) -> CookieSource:
    """Ask the connected browser for `host`'s cookies, and nothing else.

    Two independent narrowings, on purpose. The CDP call is already scoped to
    one URL, but a browser that has decided to serve us everything would be
    believed too readily, so the result is filtered through the same
    ``filter_for_host`` every other reader in searchts uses.
    """
    contexts = list(getattr(browser_obj, "contexts", None) or [])
    if not contexts:
        raise CookieReadError(
            "the browser exposed no cookie context over CDP; "
            "try starting it with --remote-debugging-address=127.0.0.1"
        )
    try:
        raw = contexts[0].cookies([site])
    except Exception as e:  # noqa: BLE001 - any client error, reported as one line
        raise CookieReadError(
            f"could not read cookies over CDP ({type(e).__name__})"
        ) from None
    scoped = filter_for_host(_records_from(raw), host)
    if not scoped:
        raise CookieReadError(
            f"no cookies for {host} in that browser. Log in to the site there "
            f"first, then read again."
        )
    return CookieSource(
        site=site,
        cookies=scoped,
        browser=source.browser,
        family="chromium",
        via=source.via,
        count=len(scoped),
        names=sorted({c.name for c in scoped}),
    )


def _connect(pw: Any, endpoint: str, port: Optional[int] = None) -> Any:
    try:
        return pw.chromium.connect_over_cdp(endpoint)
    except Exception as e:  # noqa: BLE001 - client error, reported as one line
        raise CookieReadError(_connect_reason(e, endpoint, port)) from None


def _connect_reason(exc: BaseException, endpoint: str, port: Optional[int]) -> str:
    """What to say when the CDP handshake failed, in the order it is likely.

    The raw client message for the common case is
    ``BrowserType.connect_over_cdp: connect ECONNREFUSED 127.0.0.1:9222`` and
    the wrapper used to reduce that to ``(Error)`` -- a class name, with the
    one fact that matters dropped. The overwhelmingly usual reason is that the
    port is closed because the browser was started without
    ``--remote-debugging-port``, so that is said first, with the command that
    fixes it. The reason is only asserted when a socket probe agrees, so a
    refusal is never guessed.

    The client's own message is NOT echoed. A CDP client quotes the request it
    made when it fails, and this module's rule is that nothing a client says
    about a failed handshake reaches a user: only the exception *type* is
    trusted. The two sentences below are fixed text plus that type name.
    """
    where = f"on {endpoint}"
    if port is not None and not _port_open(port):
        return (
            f"nothing is listening on port {port}, so there is no debugger to "
            f"read. Start your browser yourself with "
            f"--remote-debugging-port={port} (and --user-data-dir pointing at a "
            f"profile that is not your default one: Chrome 136+ ignores the flag "
            f"on the default profile), then read again. searchts never opens "
            f"this port for you."
        )
    return (
        f"something is listening {where} but the debugger handshake failed "
        f"({type(exc).__name__}). Is it a browser started with "
        f"--remote-debugging-port, and is that port the one you passed?"
    )


def _port_open(port: int, timeout: float = 0.5) -> bool:
    """Is something accepting connections on this machine's port right now?"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex(("127.0.0.1", int(port))) == 0
    except OSError:
        return False


# ── public: searchts opens the port, with consent ────────────────────────────


def cdp_read_site(
    url: str,
    browser: str,
    *,
    confirm: Optional[Callable[[str], bool]] = None,
    playwright_module: Optional[Any] = None,
    copy_profile_fn: Optional[Callable[[str, str], None]] = None,
    clock: Optional[Callable[[], float]] = None,
    launcher: Optional[Callable[..., Any]] = None,
    scratch_fn: Optional[Callable[[], str]] = None,
    executable: Optional[str] = None,
    profile_src: Optional[str] = None,
    port: Optional[int] = None,
) -> CookieSource:
    """Read `url`'s cookies from `browser`, opening a debugger port to do it.

    The order is the security property, so it is spelled out rather than left
    to the reader: no profile is read, no directory created, no process
    spawned and no connection made until `confirm` has returned True, and the
    scratch profile is deleted on every exit path from then on.

    `confirm` receives the full question (debugger bar, port open to other
    programs, one site) and returns a bool. With no `confirm` there is no way
    to ask, so this raises ConsentRequired instead of guessing yes.

    The remaining parameters are injection seams so tests never launch a real
    browser, or read the user's real profile: `playwright_module`,
    `copy_profile_fn`, `launcher`, `scratch_fn`, `clock`, `executable`,
    `profile_src`, `port`.
    """
    host = _host_of(url)
    browser = _need_chromium(browser)
    # Picked before the question because the question names the port. This is a
    # bind-and-release on loopback to learn a free number: nothing is listening
    # and no browser exists yet.
    port = _free_port() if port is None else int(port)

    if confirm is None:
        raise ConsentRequired(
            f"no way to ask for consent, so no debugger port was opened for "
            f"{browser}. Pass a confirm callback, or open the port yourself and "
            f"use --cdp-port."
        )
    if not confirm(consent_prompt(browser, host, port)):
        raise ConsentRequired(
            f"no debugger port opened: reading {host} from {browser} needs one, "
            f"and that was declined."
        )

    src = profile_src if profile_src is not None else _profile_source(browser)
    exe = executable or browser_executable(browser)
    copy_fn = copy_profile_fn or copy_profile
    start = launcher or _launch_browser

    with _scratch_profile(src, copy_fn, scratch_fn) as scratch:
        # The browser closes on every exit from here, including the one where
        # the read itself raised: nothing of ours survives the call.
        launched = start(exe, port, scratch, clock=clock or time.monotonic)
        try:
            pw = _playwright(playwright_module)
            try:
                connected = _connect(pw, f"http://127.0.0.1:{port}", port)
                try:
                    return _read_one_site(
                        connected,
                        url,
                        host,
                        CookieSource(site=url, browser=browser, via="debugger port"),
                    )
                finally:
                    _close_quietly(connected)
            finally:
                _stop_quietly(pw)
        finally:
            _close_quietly(launched)


def _close_quietly(thing: Any) -> None:
    close = getattr(thing, "close", None)
    if close is None:
        return
    try:
        close()
    except Exception:  # noqa: BLE001 - teardown must not mask the read's own error
        pass


def _stop_quietly(pw: Any) -> None:
    stop = getattr(pw, "stop", None)
    if stop is None:
        return
    try:
        stop()
    except Exception:  # noqa: BLE001 - see _close_quietly
        pass


# ── public: the user opened the port ─────────────────────────────────────────

#: The only hosts a CDP endpoint may name. 127.0.0.0/8 and ::1 are loopback;
#: "localhost" is the name for it. Anything else would be searchts reading
#: cookies off a machine it was pointed at, so it is refused before a socket
#: is opened rather than by a filter afterwards.
_LOOPBACK_NAMES = frozenset({"localhost"})


def _check_endpoint(host: str, port: Any) -> Tuple[str, int]:
    """Validate an endpoint the user supplied. Raises before connecting."""
    h = (host or "").strip().strip("[]").lower()
    if h not in _LOOPBACK_NAMES:
        try:
            loopback = ipaddress.ip_address(h).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            raise CookieReadError(
                f"refusing {host!r}: a debugger port must be on this machine "
                f"(127.0.0.1 or localhost). searchts will not attach a cookie "
                f"read to a remote host."
            )
    try:
        p = int(port)
    except (TypeError, ValueError):
        raise CookieReadError(f"{port!r} is not a port number") from None
    if not 1 <= p <= 65535:
        raise CookieReadError(f"{p} is not a port number (1-65535)")
    return ("127.0.0.1" if h in _LOOPBACK_NAMES else h), p


def endpoint_url(host: str, port: int) -> str:
    """The CDP HTTP endpoint for a validated loopback host and port."""
    return f"http://[{host}]:{port}" if ":" in host else f"http://{host}:{port}"


def parse_endpoint(port: Any) -> Tuple[str, int]:
    """Accept ``9222``, ``"9222"``, ``"127.0.0.1:9222"``, ``"[::1]:9222"``.

    Returns the validated ``(host, port)``. Raises CookieReadError on anything
    that is not this machine's loopback or not a real port.
    """
    if isinstance(port, int):
        return _check_endpoint("127.0.0.1", port)
    raw = str(port or "").strip()
    if not raw:
        raise CookieReadError("no debugger port given")
    if ":" not in raw:
        return _check_endpoint("127.0.0.1", raw)
    host, _, num = raw.rpartition(":")
    return _check_endpoint(host, num)


def connect_existing_cdp(
    port: Any,
    site: str,
    *,
    playwright_module: Optional[Any] = None,
) -> CookieSource:
    """Read `site`'s cookies from a debugger port the USER already opened.

    No consent is asked here, because no port is opened: the user ran
    ``chrome --remote-debugging-port=9222`` themselves and owns that window's
    lifetime. The port is still validated as loopback before a socket is
    opened, because a CDP endpoint hands over every cookie in the browser.

    The browser is not closed on the way out. It is not ours to close, and
    ``Browser.close()`` on a CDP connection tears down the browser itself.
    """
    host, number = parse_endpoint(port)
    target_host = _host_of(site)
    pw = _playwright(playwright_module)
    try:
        connected = _connect(pw, endpoint_url(host, number), number)
        try:
            return _read_one_site(
                connected, site, target_host, CookieSource(site=site, via="cdp port")
            )
        finally:
            _disconnect_quietly(connected)
    finally:
        _stop_quietly(pw)


def _disconnect_quietly(browser_obj: Any) -> None:
    """Detach without closing. ``close()`` here would close the user's browser.

    Only an explicit ``disconnect()`` is ever called. A CDP client without one
    is left alone: dropping the driver below is what tears the websocket down,
    and that leaves the user's window exactly as they started it.
    """
    fn = getattr(browser_obj, "disconnect", None)
    if fn is None:
        return
    try:
        fn()
    except Exception:  # noqa: BLE001 - teardown only
        pass


# ── public: everything that is not Chromium ──────────────────────────────────


def read_site_cookies(site: str, browser: str = "") -> CookieSource:
    """Best local source for `site`, delegating to ``session_cookies``.

    The owned store and the Firefox-derived browsers are read straight off
    disk by ``session_cookies.for_site``; a Chromium browser named here is
    refused there with the reason, pointing at the debugger port.
    """
    return for_site(site, browser)
