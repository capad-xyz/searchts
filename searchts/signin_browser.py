"""Sign in once, in a browser searchts owns.

The third state. Not kept, and nothing worth copying from the user's own browser:
the user signs in, once, in a window searchts opens. That sign-in is the
approval -- there is no second question, and nothing is read out of their real
Firefox or Chrome to get here.

Two properties this module is careful about:

- **The profile is searchts's, not the user's.** It is created under
  ``~/.searchts/cookies/signin`` rather than by copying an existing one, so a
  sign-in here cannot pick up the logins the user has everywhere else.
- **The profile is not the store.** After a successful sign-in the site's
  cookies are read out of the profile into the owned store, and the profile is
  deleted. What persists is the store entry the user then agreed to keep, not
  a whole browser profile sitting on disk. A kept login and a scratch profile
  are different files with different lifetimes, and this module is where that
  separation would be easiest to get wrong.
"""

from __future__ import annotations

import os
import shutil
import time
from contextlib import contextmanager
from typing import Iterator, List, Optional

from searchts.session_cookies import (
    CookieReadError,
    CookieRecord,
    CookieSource,
    filter_for_host,
)


def signin_root() -> str:
    """Where the owned sign-in profile lives between runs."""
    return os.path.join(os.path.expanduser("~"), ".searchts", "cookies", "signin")


def _profile_for(browser: str) -> str:
    """The user-data-dir for a sign-in browser, created empty.

    Never a copy of the user's real profile. A copy would drag in every login
    the user has, which is exactly what this path exists to avoid.
    """
    root = os.path.join(signin_root(), (browser or "chrome").strip().lower() or "chrome")
    # A leftover profile restores its own tabs and the URL we pass never
    # becomes the page. This directory is the sign-in window, not the store:
    # wiping it does not delete a login the user asked to keep.
    if os.path.isdir(root):
        try:
            shutil.rmtree(root)
        except OSError as e:
            raise CookieReadError(
                f"could not clear the old sign-in profile ({type(e).__name__}). "
                f"Close the {browser} window searchts opened and try again."
            ) from None
    os.makedirs(root, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(root, 0o700)
        except OSError:
            pass
    return root


def wipe_signin_profile(browser: str = "") -> int:
    """Delete the owned sign-in profile(s). Returns how many were removed."""
    root = signin_root()
    if not os.path.isdir(root):
        return 0
    targets: List[str] = []
    if browser:
        one = os.path.join(root, browser.strip().lower())
        if os.path.isdir(one):
            targets.append(one)
    else:
        targets = [
            os.path.join(root, name)
            for name in os.listdir(root)
            if os.path.isdir(os.path.join(root, name))
        ]
    removed = 0
    for path in targets:
        try:
            shutil.rmtree(path, ignore_errors=False)
            removed += 1
        except (OSError, shutil.Error):
            continue
    return removed


def _wait_for_debugger(port: int, timeout: float) -> bool:
    """Wait until 127.0.0.1:<port> answers, or give up."""
    import socket

    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.25)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.1)
    return False


@contextmanager
def signin_window(
    site: str,
    *,
    browser: str = "chrome",
    timeout_s: float = 20.0,
) -> Iterator[tuple]:
    """Open `site` in a browser searchts owns; yield ``(profile, port)``.

    The window stays open until the block exits, which is what gives the user
    time to sign in. 127.0.0.1 only: the debugger port hands over every login in
    this profile, so binding anything wider would put it on the network.

    ``timeout_s`` bounds how long to wait for the debugger port to answer, not
    how long the user has to sign in. The two are deliberately different: the
    browser failing to start is a fault worth reporting, and a person signing
    in is not a timeout. ``wait_for_the_person`` is where that unbounded wait
    actually happens, called from :func:`signin` before any cookie is read.
    Naming the two apart matters, because a single "timeout" on this function
    used to read as though the sign-in itself could be cut short -- and, while
    the wait was missing entirely, it was not merely cut short but absent.

    The profile is *not* deleted here. The caller reads the cookies out of it
    and then removes it, because a sign-in that failed has nothing worth
    keeping and a sign-in that worked still needs the user to agree before
    anything is kept.
    """
    from searchts.cdp_profile import (
        LaunchedBrowser,
        _free_port,
        _launch_browser,
        browser_executable,
    )

    host = site if "://" in site else "https://" + site
    profile = _profile_for(browser)
    port = _free_port()
    launched: Optional[LaunchedBrowser] = None
    try:
        executable = browser_executable(browser)
        # --disable-sync keeps Edge's first-run "sign in to sync" page from
        # replacing the site. Without the URL, the window opens on that page
        # and a sign-in never starts, so nothing is saved for a later read.
        launched = _launch_browser(
            executable, port, profile,
            open_url=host,
            extra_args=["--disable-sync"],
        )
        if not _wait_for_debugger(port, timeout_s):
            raise CookieReadError(
                f"the sign-in browser did not start within {timeout_s:.0f}s. "
                f"Close any {browser} window and try again."
            )
        # stderr, never stdout: under MCP stdout is the JSON-RPC channel.
        import sys

        print(
            f"A {browser} window opened on {host}. Sign in there. This window is "
            f"the approval; nothing is copied from your normal browser.",
            file=sys.stderr,
            flush=True,
        )
        yield profile, port
    finally:
        if launched is not None:
            launched.close()
        # The profile outlives the window on purpose: see the note above.


def signin(
    site: str,
    *,
    browser: str = "chrome",
    wait_s: Optional[float] = None,
) -> CookieSource:
    """Sign in once for `site` and return its cookies, ready for one read.

    Whether anything is *kept* is decided by the caller, not here: keeping is
    the user's yes and lives in :func:`searchts.login_store.keep`. This
    function only produces the values, and removes the profile it made.

    ``wait_s`` is for callers with no terminal (MCP). Instead of waiting for
    Enter, the person closes the window when they are signed in, and the wait
    gives up after ``wait_s`` seconds with nothing kept.
    """
    from searchts.login_store import host_of

    host = host_of(site)
    url = site if "://" in site else "https://" + site

    with signin_window(site, browser=browser) as (profile, port):
        # Before the read, not after. The cookies are whatever the page set by
        # the time we look, so asking afterwards would already be too late: a
        # sign-in that finished while we read is invisible, and a sign-in that
        # has not happened looks exactly the same as one that has.
        if wait_s is None:
            wait_for_the_person(site, browser=browser)
            records = _read_after_signin(port, url, host)
        else:
            records = wait_for_window_close(port, url, host, wait_s)
    # The profile has served its purpose either way. A profile left behind is a
    # login on disk that nobody agreed to keep.
    _wipe_one(profile)
    if not records:
        raise CookieReadError(
            f"signed-in read of {host} came back with no cookies for it. If the "
            f"site logged you in, the sign-in may not have completed."
        )
    return CookieSource(
        site=site,
        cookies=records,
        family="owned",
        via=f"sign-in browser ({browser})",
        count=len(records),
        names=sorted({c.name for c in records}),
    )


def _wipe_one(profile: str) -> None:
    try:
        shutil.rmtree(profile, ignore_errors=False)
    except (OSError, shutil.Error):
        pass


def wait_for_the_person(site: str, *, browser: str) -> None:
    """Block until the person says they have signed in, or refuse.

    This is the wait `signin_window`'s docstring promises when it says the time
    to sign in "is unbounded and is the user's to take". It was not there at
    all: the window opened, the cookies were read immediately, and the window
    closed in about two seconds. A person cannot type a password in two seconds,
    so the flow read the guest cookies the sign-in page sets on its own and
    reported the result as a sign-in.

    Refuses rather than reading anyway when stdin is not a terminal, because
    there is no way to ask. That matters for MCP in particular, where stdin is
    the JSON-RPC channel: an `input()` there would eat protocol messages, and a
    piped script cannot complete a human sign-in at all. Both get a sentence
    saying what to do instead.
    """
    import sys

    if not (hasattr(sys.stdin, "isatty") and sys.stdin.isatty()):
        raise CookieReadError(
            f"signing in to {site} has to wait for you, and there is no terminal "
            f"here to wait in. Run it from a terminal "
            f"(`searchts login signin {site}`), or keep a login you already have "
            f"in Firefox with `searchts login keep {site} --cookies-from-browser "
            f"firefox --yes`."
        )
    print()
    print(f"Sign in to {site} in the {browser} window above.")
    print("This waits for you. Press Enter once you are signed in, or close the")
    print("window and press Enter to give up.")
    try:
        input("  press Enter when you are signed in: ")
    except EOFError:
        print("  no input available, giving up.", flush=True)


def _open_pages(port: int) -> int:
    """How many page tabs the sign-in browser has open; 0 when it is gone."""
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(  # noqa: S310 - loopback debugger port only
            f"http://127.0.0.1:{int(port)}/json/list", timeout=2
        ) as resp:
            targets = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 - a closed browser refuses or resets
        return 0
    return sum(1 for t in targets if isinstance(t, dict) and t.get("type") == "page")


def _fingerprint(records: List[CookieRecord]) -> list:
    return sorted((c.domain, c.path, c.name, c.value) for c in records)


def wait_for_window_close(
    port: int,
    url: str,
    host: str,
    wait_s: float,
    *,
    poll_s: float = 3.0,
    read=None,
    pages=None,
    clock=time.monotonic,
    sleep=time.sleep,
) -> List[CookieRecord]:
    """The no-terminal wait: the person closes the window when signed in.

    The site's cookies are read every ``poll_s`` seconds while the window is
    open, and the last read is the answer once every tab is closed (two polls
    in a row, so one slow reply is not a close). Two outcomes keep nothing:
    the wait passing ``wait_s``, and a window closed with the same cookies it
    opened with, which is a window closed without signing in.
    """
    read = read or _read_after_signin
    pages = pages or _open_pages
    deadline = clock() + max(1.0, float(wait_s))
    first: Optional[List[CookieRecord]] = None
    last: Optional[List[CookieRecord]] = None
    closed_polls = 0
    read_error = ""
    failed_reads = 0
    while True:
        if pages(port) == 0:
            closed_polls += 1
            if closed_polls >= 2:
                break
        else:
            closed_polls = 0
            from searchts.cdp_profile import NoSiteCookies

            try:
                snap = read(port, url, host)
            except NoSiteCookies:
                snap = []  # answered, nothing set yet: a page before sign-in
            except CookieReadError as e:
                snap, read_error = None, str(e)
            except Exception as e:  # noqa: BLE001 - the window may be closing mid-read
                snap, read_error = None, f"{type(e).__name__}: {e}"
            failed_reads = failed_reads + 1 if snap is None else 0
            if snap is None:
                read_error = read_error.rstrip(".")
            # Three failures in a row before any read worked is a missing
            # piece (no CDP client), not a page still loading: say so now
            # instead of after the whole wait.
            if first is None and failed_reads >= 3:
                raise CookieReadError(
                    f"could not read cookies from the sign-in window for {host}: "
                    f"{read_error}. Nothing was kept."
                )
            if snap is not None:
                first = snap if first is None else first
                last = snap
        if clock() >= deadline:
            if first is None and read_error:
                raise CookieReadError(
                    f"could not read cookies from the sign-in window for {host}: "
                    f"{read_error}. Nothing was kept."
                )
            raise CookieReadError(
                f"no sign-in finished for {host} within {wait_s:.0f}s, so nothing "
                f"was kept. Call login_signin again, sign in, then close the window."
            )
        sleep(poll_s if closed_polls == 0 else 0.5)
    if first is None and read_error:
        raise CookieReadError(
            f"could not read cookies from the sign-in window for {host}: "
            f"{read_error}. Nothing was kept."
        )
    if not last or first is None or _fingerprint(last) == _fingerprint(first):
        raise CookieReadError(
            f"the {host} window was closed without a sign-in (its cookies did not "
            f"change), so nothing was kept."
        )
    return last


def _read_after_signin(port: int, url: str, host: str) -> List[CookieRecord]:
    """Read `host`'s cookies out of the signed-in browser over CDP.

    Uses the same Playwright-over-CDP route the rest of the cookie work uses,
    so a sign-in and a port read cannot disagree about how a cookie is found.
    The port comes from the caller that launched the browser rather than being
    rediscovered, because a second lookup is a second thing that can be wrong.
    """
    from searchts.cdp_profile import connect_existing_cdp

    source = connect_existing_cdp(f"127.0.0.1:{port}", url)
    return filter_for_host(source.cookies, host)
