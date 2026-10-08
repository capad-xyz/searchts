# -*- coding: utf-8 -*-
"""Auto-extract cookies from local browsers for all supported platforms.

Supports: Chrome, Firefox, Edge, Brave, Opera
Extracts: Twitter cookies in one shot.

Usage:
    searchts configure --from-browser chrome
"""

from typing import Dict, List, Optional, Tuple, TypedDict


class PlatformSpec(TypedDict):
    """One platform's cookie extraction rule.

    `cookies` is None when every cookie on the domain should be kept; the
    extraction loop branches on that.
    """

    name: str
    domains: List[str]
    cookies: Optional[List[str]]
    config_key: str


# Platform cookie specs: (platform_name, domain_pattern, needed_cookies)
PLATFORM_SPECS: List[PlatformSpec] = [
    {
        "name": "Twitter/X",
        "domains": [".x.com", ".twitter.com"],
        "cookies": ["auth_token", "ct0"],
        "config_key": "twitter",
    },
]


def _backend_for(browser: str):
    """Return a zero-arg callable that returns this browser's cookies.

    Chromium-derived browsers go through ``browser_cookie3`` (it handles the
    profile layout and the OS keychain). Firefox-derived ones need no library at
    all: their cookie database is an unencrypted SQLite file on Windows and
    Linux, so we read it directly rather than adding a dependency that cannot
    install on modern Python (rookiepy pins pyo3 0.20, which has no wheel for
    3.13+, and its build fails).

    Returns ``(callable, kind)`` where kind is ``"records"`` or ``"jar"``.
    """
    from searchts import session_cookies as sc

    fam = sc.family_of(browser)  # raises ValueError listing what is supported

    if fam == "firefox":
        return (lambda: sc.read_all_firefox(browser), "records")

    try:
        import browser_cookie3
    except ImportError as e:
        raise RuntimeError(
            f"Reading {browser} cookies needs browser-cookie3.\n"
            f"  pip install browser-cookie3\n"
            f"(rookiepy is no longer suggested: it does not install on "
            f"Python 3.13+.)"
        ) from e

    getter = getattr(browser_cookie3, browser, None)
    if getter is None:  # e.g. an Arc/Opera variant browser_cookie3 names differently
        raise RuntimeError(
            f"browser-cookie3 cannot read {browser} cookies on this machine. "
            f"For Chromium browsers whose cookies are locked, use --cdp-port."
        )
    return (getter, "jar")


#: What the underlying libraries say when a Chromium cookie store refuses to
#: open, mapped to what is actually true. The raw message is "This operation
#: requires admin", which sends people off to run a terminal as administrator
#: for a request that will still fail, because the real cause is that modern
#: Chromium wraps the key in App-Bound Encryption.
_LOCKED_MARKS = (
    "requires admin",
    "unable to get key",
    "decryption failed",
    "crypt",
    "permission denied",
)


def _as_records(raw, kind: str):
    """Normalise a backend result to objects with .name/.value/.domain."""
    if kind == "records":
        return raw  # already a list of CookieRecord
    return raw


def extract_all(browser: str = "chrome") -> Dict[str, dict]:
    """
    Extract cookies for all supported platforms from the specified browser.

    Returns:
        {
            "twitter": {"auth_token": "xxx", "ct0": "yyy"},
        }
    """
    browser = (browser or "").strip().lower()
    load, kind = _backend_for(browser)

    try:
        jar = _as_records(load(), kind)
    except Exception as e:
        detail = str(e)
        if any(m in detail.lower() for m in _LOCKED_MARKS):
            raise RuntimeError(
                f"{browser}'s cookie store is locked. Modern Chromium wraps the "
                f"decryption key in App-Bound Encryption, which refuses to hand it "
                f"to another program, so this cannot be fixed by running as admin.\n"
                f"  To read it: start the browser yourself with a debugger port and "
                f"use --cdp-port <port>.\n"
                f"  Firefox-family browsers (Zen, Firefox, LibreWolf) have no such lock."
            ) from e
        raise RuntimeError(
            f"Could not read {browser} cookies: {e}\n"
            f"Make sure {browser} is closed and you have permission."
        )

    results = {}

    for spec in PLATFORM_SPECS:
        platform_cookies = {}
        all_cookies_for_domain = []

        for cookie in jar:
            # Check if cookie belongs to this platform
            domain_match = any(
                cookie.domain.endswith(d) or cookie.domain == d.lstrip(".")
                for d in spec["domains"]
            )
            if not domain_match:
                continue

            all_cookies_for_domain.append(cookie)

            if spec["cookies"] is not None:
                if cookie.name in spec["cookies"]:
                    platform_cookies[cookie.name] = cookie.value

        if spec["cookies"] is None:
            # Grab all as header string
            if all_cookies_for_domain:
                cookie_str = "; ".join(
                    f"{c.name}={c.value}" for c in all_cookies_for_domain
                )
                results[spec["config_key"]] = {"cookie_string": cookie_str}
        else:
            if platform_cookies:
                results[spec["config_key"]] = platform_cookies

    return results


def _open_owner_only(path: str):
    """Open *path* for writing, atomically creating it with mode 0o600.

    Mirrors the pattern used by Config.save() in config.py: O_WRONLY|O_CREAT|
    O_TRUNC + an explicit mode argument so the file is never briefly
    world-readable between open() and a later os.chmod(). On Windows (or any
    OS that rejects the open flags) we fall back to a plain open().
    """
    import os
    import stat

    try:
        fd = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            stat.S_IRUSR | stat.S_IWUSR,  # 0o600
        )
        return os.fdopen(fd, "w", encoding="utf-8")
    except OSError:
        return open(path, "w", encoding="utf-8")


def _sync_xfetch_session(auth_token: str, ct0: str) -> None:
    """Sync Twitter credentials to ~/.config/xfetch/session.json (legacy xreach compat)."""
    import json
    import os

    try:
        xfetch_dir = os.path.join(os.path.expanduser("~"), ".config", "xfetch")
        os.makedirs(xfetch_dir, exist_ok=True)
        session_path = os.path.join(xfetch_dir, "session.json")
        session_data: dict = {}
        if os.path.exists(session_path):
            try:
                with open(session_path, "r", encoding="utf-8") as sf:
                    session_data = json.load(sf)
            except (json.JSONDecodeError, OSError):
                session_data = {}
        session_data["authToken"] = auth_token
        session_data["ct0"] = ct0
        with _open_owner_only(session_path) as sf:
            json.dump(session_data, sf, indent=2)
    except Exception:
        # Non-fatal: searchts config is the source of truth, xfetch sync is best-effort
        pass


def _sync_bird_env(auth_token: str, ct0: str) -> None:
    """Write Twitter credentials to ~/.config/bird/credentials.env for bird CLI.

    bird reads AUTH_TOKEN and CT0 from environment variables. This writes a
    shell-sourceable file so users can `source ~/.config/bird/credentials.env`.
    Values are passed through shlex.quote so a token containing a quote, $, or
    backtick cannot break out into shell syntax when the file is sourced.
    """
    import os
    import shlex

    try:
        bird_dir = os.path.join(os.path.expanduser("~"), ".config", "bird")
        os.makedirs(bird_dir, exist_ok=True)
        env_path = os.path.join(bird_dir, "credentials.env")
        with _open_owner_only(env_path) as f:
            f.write(f"AUTH_TOKEN={shlex.quote(auth_token)}\n")
            f.write(f"CT0={shlex.quote(ct0)}\n")
    except Exception:
        # Non-fatal: searchts config is the source of truth, bird env sync is best-effort
        pass


# Alias for callers expecting the name _sync_bird_credentials
_sync_bird_credentials = _sync_bird_env


def configure_from_browser(browser: str, config) -> List[Tuple[str, bool, str]]:
    """
    Extract cookies and configure all found platforms.
    
    Returns list of (platform_name, success, message) tuples.
    """
    results_list = []

    try:
        extracted = extract_all(browser)
    except Exception as e:
        return [("Browser", False, str(e))]

    if not extracted:
        return [("All platforms", False,
                 f"No platform cookies found in {browser}. "
                 f"Make sure you're logged into Twitter in {browser}.")]

    # Configure each found platform
    if "twitter" in extracted:
        tc = extracted["twitter"]
        if "auth_token" in tc and "ct0" in tc:
            config.set("twitter_auth_token", tc["auth_token"])
            config.set("twitter_ct0", tc["ct0"])
            # Legacy sync (best-effort)
            _sync_xfetch_session(tc["auth_token"], tc["ct0"])
            results_list.append(("Twitter/X", True, "auth_token + ct0"))
        else:
            found = ", ".join(tc.keys())
            missing = [k for k in ["auth_token", "ct0"] if k not in tc]
            results_list.append(("Twitter/X", False,
                                 f"Found {found}, but missing: {', '.join(missing)}. "
                                 f"Make sure you're logged into x.com in {browser}."))

    return results_list
