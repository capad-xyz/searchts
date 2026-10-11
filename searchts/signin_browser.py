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
    timeout_s: float = 300.0,
) -> Iterator[tuple]:
    """Open `site` in a browser searchts owns; yield ``(profile, port)``.

    The window stays open until the block exits, which is what gives the user
    time to sign in. 127.0.0.1 only: the debugger port hands over every login in
    this profile, so binding anything wider would put it on the network.

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
        launched = _launch_browser(executable, port, profile)
        if not _wait_for_debugger(port, 20.0):
            raise CookieReadError(
                f"the sign-in browser did not start. Close any {browser} window "
                f"and try again."
            )
        print(
            f"A {browser} window opened on {host}. Sign in there. This window is "
            f"the approval; nothing is copied from your normal browser.",
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
    persist: bool = True,
    timeout_s: float = 300.0,
) -> CookieSource:
    """Sign in once for `site` and return its cookies, ready for one read.

    ``persist`` is decided by the caller, not here: keeping is the user's yes
    and lives in :func:`searchts.login_store.keep`. This function only produces
    the values, and removes the profile it made.
    """
    from searchts.login_store import host_of

    host = host_of(site)
    url = site if "://" in site else "https://" + site

    with signin_window(site, browser=browser, timeout_s=timeout_s) as (profile, port):
        records = _read_after_signin(port, url, host)
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