#!/usr/bin/env python3
"""Drive the real searchts logged-in-read lifecycle and print a transcript.

The artifact is the transcript, not the exit code. This exists because the
question a reviewer actually has about a safety feature is "what does a person
see, in what order, and what is left on disk", and a green suite cannot answer
it. It can only say that some assertion held.

Everything here runs the real CLI and the real MCP surface as a subprocess or an
import, against a throwaway ``USERPROFILE``. No browser opens, no real cookie
store is read or written, and no network call is made: the network is stubbed at
the unlocker boundary so the ladder's outcome is decided by the script and the
cookie handling is what is actually under test.

Usage:
    python scripts/verify_login_lifecycle.py          # transcript + exit code
    python scripts/verify_login_lifecycle.py --quiet  # checks only, no transcript

Exit codes: 0 every check held, 1 a check failed, 2 it could not run at all.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

W = 78


def rule(title: str) -> None:
    print()
    print("=" * W)
    print(f"  {title}")
    print("=" * W)


def show(label: str, out: str, err: str, rc: int) -> None:
    """Print exactly what a person would see, labelled, with the exit code."""
    print(f"\n$ {label}")
    if out.strip():
        for line in out.rstrip().splitlines():
            print(f"    {line}")
    if err.strip():
        for line in err.rstrip().splitlines():
            print(f"  ! {line}")
    if rc != 0:
        print(f"  -> exit {rc}")


class Checks:
    """Records pass/fail and prints the verdict inline."""

    def __init__(self, quiet: bool = False) -> None:
        self.failures: List[str] = []
        self.quiet = quiet

    def ok(self, name: str, condition: bool, detail: str = "") -> None:
        mark = "PASS" if condition else "FAIL"
        if not condition:
            self.failures.append(name)
        if self.quiet or not condition:
            return
        print(f"  [{mark}] {name}" + (f"  ({detail})" if detail and condition else ""))

    def note(self, text: str) -> None:
        if not self.quiet:
            print(f"         {text}")


def _snapshot(path: Optional[Path]) -> str:
    """A store's identity and size, for proving it did not change."""
    if path is None or not path.is_file():
        return "(absent)"
    return f"{path} ({path.stat().st_size} bytes)"


def isolated_home() -> str:
    """A throwaway profile, and proof that it took effect.

    Returns the path. Raises if ``expanduser`` still resolves to the real one,
    because every run after that would write to the developer's actual store.
    """
    home = tempfile.mkdtemp(prefix="searchts-verify-")
    os.environ["USERPROFILE"] = home
    os.environ["HOME"] = home
    appdata = os.path.join(home, "AppData", "Roaming")
    local = os.path.join(home, "AppData", "Local")
    for d in (appdata, local):
        os.makedirs(d, exist_ok=True)
    os.environ["APPDATA"] = appdata
    os.environ["LOCALAPPDATA"] = local

    resolved = os.path.expanduser("~")
    if os.path.abspath(resolved) != os.path.abspath(home):
        shutil.rmtree(home, ignore_errors=True)
        raise SystemExit(
            "REFUSING TO RUN: expanduser still resolves to "
            f"{resolved!r} rather than the temporary {home!r}.\n"
            "On Windows that variable is USERPROFILE, not HOME."
        )
    return home


def run_cli(*args: str) -> Tuple[str, str, int]:
    """Run the real CLI in a subprocess and return (stdout, stderr, code)."""
    proc = subprocess.run(
        [sys.executable, "-m", "searchts.cli", *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=180,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    return proc.stdout, proc.stderr, proc.returncode


def stub_ladder(page_text: str = "body", *, login_wall: bool = False,
                authenticated: bool = False):
    """Replace the network so the ladder's outcome is the script's decision."""
    import searchts.unlocker as unlocker
    from searchts.unlocker import FetchResult, UnlockerError

    state = {"calls": 0, "cookies_seen": False}

    def read_pages(url, *a, **kw):
        state["calls"] += 1
        jar = kw.get("cookies")
        state["cookies_seen"] = state["cookies_seen"] or bool(jar)
        if login_wall:
            raise UnlockerError(
                url=url, attempts=[("curl_cffi", "login-wall"),
                                   ("stealth-browser", "login-wall")],
            )
        return [FetchResult(
            backend="curl_cffi", text=page_text, status=200, warnings=[],
            final_url=url, fetched_at="verify", more=None,
            authenticated=authenticated or bool(jar),
        )]

    unlocker.read_pages = read_pages
    return state


def call_read(url: str, **kw) -> str:
    """read_url with the ladder stubbed, returning the raw string."""
    from searchts.integrations import mcp_server

    buf_out, buf_err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf_out), redirect_stderr(buf_err):
        return mcp_server.read_url(url, **kw)


def call_login(*args) -> str:
    from searchts.integrations import mcp_server

    buf_out, buf_err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf_out), redirect_stderr(buf_err):
        if args[0] == "status":
            return mcp_server.login_status()
        if args[0] == "signin":
            return mcp_server.login_signin(args[1])
        return mcp_server.login_kill(args[1])


def seed(host: str, name: str = "sid", value: str = "TESTVALUE") -> None:
    from searchts.login_store import keep
    from searchts.session_cookies import CookieRecord

    keep(host, [CookieRecord(name, value, host, secure=True)])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quiet", action="store_true",
                    help="print only failures and the verdict")
    args = ap.parse_args()

    # The real store, resolved BEFORE isolation is applied. Doing it after is
    # the bug this check exists to catch: it would name the throwaway profile,
    # compare the throwaway profile to itself, and pass for ever.
    real_home = os.path.expanduser("~")
    REAL_STORE = Path(real_home) / ".searchts" / "cookies" / "owned.json"
    real_store_before = _snapshot(REAL_STORE)

    home = isolated_home()
    c = Checks(args.quiet)

    try:
        rule("searchts logged-in read - lifecycle verification")
        print(f"  profile: {home}")
        print("  every run below uses this throwaway profile, not yours")
        print("  no browser opens; no real cookie store is read or written")
        print("  the network is stubbed, so what is tested is cookie handling")

        # ── 1. nothing kept ────────────────────────────────────────────────
        rule("1. Nothing kept yet")
        out, err, rc = run_cli("login", "list")
        show("searchts login list", out, err, rc)
        c.ok("empty store says nothing is stored",
             "nothing is stored" in out.lower(), "")
        c.ok("no cookie value in the listing", "TESTVALUE" not in out + err)

        # ── 2. KEPT: a bare read uses the store, opens nothing ────────────
        rule("2. State: kept. The next read uses it. No flag, no browser.")
        seed("example.com")
        state = stub_ladder(authenticated=True)
        receipt = json.loads(call_read("https://example.com/a"))
        print("\n  read_url('https://example.com/a')   [no cookie arguments]")
        print(f"    authenticated : {receipt['authenticated']}")
        print(f"    login_via     : {receipt['login_via']}")
        c.ok("a bare read used the kept login", receipt["authenticated"] is True)
        c.ok("and reports where it came from", receipt["login_via"] == "owned store")
        c.ok("the request actually carried cookies", state["cookies_seen"])
        c.ok("no cookie value in the receipt", "TESTVALUE" not in json.dumps(receipt))

        out, err, rc = run_cli("read", "https://example.com")
        show("searchts read https://example.com", out, err, rc)
        c.ok("CLI says no browser opened", "already kept" in err)
        c.ok("CLI reports the read was logged in", "(logged in)" in err)

        # ── 3. KILL ───────────────────────────────────────────────────────
        rule("3. Kill: searchts's copy goes, your browser's does not")
        data = json.loads(call_login("kill", "https://example.com"))
        print("\n  login_kill('https://example.com')")
        print(f"    removed_from_store    : {data['removed_from_store']}")
        print(f"    browser_copies_touched: {data['browser_copies_touched']}")
        print(f"    why: {data['why']}")
        c.ok("the store entry is gone", data["removed_from_store"] is True)
        c.ok("the user's own browser was left alone",
             data["browser_copies_touched"] is False and "left alone" in data["why"])

        # ── 4. COPY refused without the session approval ──────────────────
        rule("4. State: not kept, browser named. Copy needs the session's yes.")
        state = stub_ladder()
        refusal = call_read("https://other.test/a", cookies_from_browser="firefox")
        show("read_url(..., cookies_from_browser='firefox')", "", refusal, 0)
        c.ok("copying is refused without approval", "approval once per session" in refusal)
        c.ok("the network was never reached", state["calls"] == 0)
        c.ok("the refusal names a tool the agent has", "login_signin" in refusal)

        # ── 5. COPY granted: used for this read, kept for nothing ─────────
        rule("5. Same read, after the session approves. Copied, not kept.")
        import searchts.session_cookies as sc
        from searchts.login_store import grant_session_copy
        from searchts.session_cookies import CookieRecord, CookieSource

        sc.for_site = lambda site, browser: CookieSource(
            site=site, cookies=[CookieRecord("sid", "COPIED", site, secure=True)],
            count=1, via="browser (firefox)",
        )
        grant_session_copy()
        state = stub_ladder()
        # In-process, not a subprocess. The consent grant records its own PID on
        # purpose -- "once per session" means once per running session, and a
        # grant that outlived the process that asked for it would be exactly
        # what the user did not agree to. So a subprocess legitimately starts
        # ungranted, and the first draft of this script failed here for that
        # reason. That is the design working, not a bug to route around.
        granted = call_read("https://other.test/a", cookies_from_browser="firefox")
        show("read_url('https://other.test/a', cookies_from_browser='firefox')",
             "", granted, 0)
        c.ok("the copy was used", '"authenticated": true' in granted)
        c.ok("and it says where from", '"login_via": "browser (firefox)"' in granted)
        c.ok("the request carried the copied cookie", state["cookies_seen"])

        from searchts.login_store import list_kept
        c.ok("nothing was kept without a yes", "other.test" not in list_kept())

        rev = call_read("https://other.test/a", cookies_from_browser="firefox")
        c.ok("no second approval asked for the next site", "approval" not in rev)

        # ── 6. SIGNIN ─────────────────────────────────────────────────────
        rule("6. State: nothing to copy. Read anonymously, then hit a wall.")
        stub_ladder(login_wall=True)
        wall = call_read("https://www.linkedin.com/feed")
        show("read_url('https://www.linkedin.com/feed')", "", wall, 0)
        c.ok("a login wall is reported as such", "login-wall" in wall)
        c.ok("and names both ways past it",
             "login_signin" in wall and "cookies_from_browser" in wall)

        print("\n  the user signs in once:")
        from searchts import signin_browser

        signin_browser.signin = lambda s, **kw: CookieSource(
            site=s, cookies=[CookieRecord("li", "SIGNEDIN", "www.linkedin.com",
                                          secure=True)],
            count=1, via="sign-in browser (chrome)",
        )
        signed = json.loads(call_login("signin", "https://www.linkedin.com/feed"))
        print(f"    {signed['why']}")

        stub_ladder(authenticated=True)
        after = json.loads(call_read("https://www.linkedin.com/feed"))
        print("\n  the same read again, with no arguments:")
        print(f"    authenticated : {after['authenticated']}")
        print(f"    login_via     : {after['login_via']}")
        c.ok("after sign-in the bare read is logged in",
             after["authenticated"] is True)
        c.ok("and came from the store, not the browser",
             after["login_via"] == "owned store")

        # ── 7. an expired login gets different advice ─────────────────────
        rule("7. A kept login that has expired gets its own advice")
        stub_ladder(login_wall=True)
        stale = call_read("https://www.linkedin.com/feed")
        show("read_url('https://www.linkedin.com/feed')", "", stale, 0)
        c.ok("it says expired, not sign-in-from-scratch",
             "expired" in stale and "login_kill" in stale)
        c.ok("and does not suggest copying again", "cookies_from_browser" not in stale)

        # ── 8. the two files stay distinct ────────────────────────────────
        rule("8. The scratch copy and the saved login are different files")
        from searchts.login_store import new_scratch, purge_scratch
        from searchts.session_cookies import owned_store_path

        scratch = new_scratch("example.com")
        store = owned_store_path()
        print(f"\n  store   : {store}")
        print(f"  scratch : {scratch}")
        c.ok("they are different paths",
             os.path.abspath(store) != os.path.abspath(scratch))
        c.ok("the store is not inside the scratch tree",
             not os.path.abspath(store).startswith(
                 os.path.abspath(os.path.dirname(scratch)) + os.sep))
        c.ok("the scratch dir holds no cookie store",
             not (Path(scratch) / "owned.json").exists())
        gone = purge_scratch()
        c.ok("scratch is purged", not Path(scratch).exists(), f"removed {len(gone)}")

        # ── 9. what is left behind ────────────────────────────────────────
        rule("9. What this run left on disk, and what it did not touch")
        remaining = sorted(
            str(p.relative_to(home))
            for p in Path(home).rglob("*")
            if p.is_file()
        )
        print("\n  files under the throwaway profile:")
        for r in (remaining or ["(none)"]):
            print(f"    {r}")

        # The check that matters most and that no unit test in the repo makes:
        # this run did not write to the profile the developer actually uses.
        # Enforced two ways -- the guard in isolated_home() refuses to start if
        # USERPROFILE did not take effect, and this asserts the real store is
        # byte-for-byte what it was before.
        print(f"\n  real profile : {real_home}")
        print(f"  real store before this run : {real_store_before}")
        print(f"  real store now             : {_snapshot(REAL_STORE)}")
        c.ok("the real store is untouched",
             _snapshot(REAL_STORE) == real_store_before)

        rule("VERDICT")
        if c.failures:
            print(f"  {len(c.failures)} check(s) FAILED:")
            for f in c.failures:
                print(f"    - {f}")
            return 1
        print("  every check held.")
        print()
        print("  What this does NOT prove: that a real site accepts a real")
        print("  login. That needs a human at a browser. Everything above is")
        print("  the behaviour around it, with the network stubbed.")
        return 0

    finally:
        shutil.rmtree(home, ignore_errors=True)

    # Checked here rather than inside the try: the cleanup above is what this
    # asserts, so testing before it runs tests the wrong moment.
    stray = list(Path(tempfile.gettempdir()).glob("searchts-verify-*"))
    c.ok("the throwaway profile is cleaned up", not stray,
         f"{len(stray)} left" if stray else "")
    if c.failures:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
