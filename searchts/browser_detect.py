# -*- coding: utf-8 -*-
"""Find installed browsers and their profiles, and look for one site's cookie.

Two jobs, deliberately separated by how much they touch:

``installed_browsers``
    Paths only. It lists each supported Chromium-family and Firefox-family
    browser, the executable when one can be found, every profile directory
    with a cookie database, whether the browser is running, and (Chromium)
    whether ``DevToolsActivePort`` names a live debugging endpoint. It reads
    no cookie and opens no cookie database.

``cookie_presence``
    Answers one yes/no question per browser profile: does this profile hold a
    cookie for the site's registrable domain? It opens the cookie database
    read-only, selects the host column only, and never selects a name, value
    or encrypted blob. Nothing is decrypted, printed, logged or copied. A
    database the browser has locked is copied to a temporary file and read
    there; the copy is deleted immediately.

The path, lock and active-port helpers are the ones the LinkedIn attach path
already uses (:mod:`searchts.linkedin_attach`) and the Firefox profile layout
is the one the cookie reader already uses (:mod:`searchts.session_cookies`).
This module adds detection and the presence question, not a second copy of
either.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Callable, List, Mapping, Optional, Sequence
from urllib.parse import urlparse

from searchts import browser_settings as bs
from searchts import linkedin_attach as attach
from searchts import session_cookies as sc

__all__ = [
    "Browser",
    "Presence",
    "Profile",
    "CHROMIUM_BROWSERS",
    "FIREFOX_BROWSERS",
    "cookie_presence",
    "executable_for",
    "format_report",
    "installed_browsers",
]

#: Same order the rest of the project lists them in.
CHROMIUM_BROWSERS = (
    "chrome",
    "edge",
    "brave",
    "vivaldi",
    "opera",
    "arc",
    "chromium",
)
FIREFOX_BROWSERS = sc.FIREFOX_FAMILY

_DISPLAY = {
    "chrome": "Chrome",
    "chromium": "Chromium",
    "edge": "Edge",
    "brave": "Brave",
    "vivaldi": "Vivaldi",
    "opera": "Opera",
    "arc": "Arc",
    "firefox": "Firefox",
    "zen": "Zen",
    "librewolf": "LibreWolf",
    "waterfox": "Waterfox",
    "floorp": "Floorp",
    "mullvad": "Mullvad",
}

#: Executable names for the Firefox family, for PATH lookup.
_FIREFOX_EXE = {
    "firefox": ("firefox", "firefox.exe"),
    "zen": ("zen", "zen-browser", "zen.exe"),
    "librewolf": ("librewolf", "librewolf.exe"),
    "waterfox": ("waterfox", "waterfox.exe"),
    "floorp": ("floorp", "floorp.exe"),
    "mullvad": ("mullvad-browser", "mullvadbrowser", "mullvad-browser.exe"),
}

#: macOS application bundles for the Firefox family: (bundle, binary).
_MAC_FIREFOX = {
    "firefox": ("Firefox.app", "firefox"),
    "zen": ("Zen Browser.app", "zen"),
    "librewolf": ("LibreWolf.app", "librewolf"),
    "waterfox": ("Waterfox.app", "waterfox"),
    "floorp": ("Floorp.app", "floorp"),
    "mullvad": ("Mullvad Browser.app", "mullvad-browser"),
}

#: Windows install locations relative to %PROGRAMFILES%, for the Firefox family.
_WIN_FIREFOX = {
    "firefox": (r"Mozilla Firefox\firefox.exe",),
    "zen": (r"Zen Browser\zen.exe",),
    "librewolf": (r"LibreWolf\librewolf.exe",),
    "waterfox": (r"Waterfox\waterfox.exe",),
    "floorp": (r"Floorp\floorp.exe",),
    "mullvad": (r"Mullvad Browser\mullvad-browser.exe",),
}


def _platform() -> str:
    return (
        "windows" if os.name == "nt"
        else "macos" if sys.platform == "darwin"
        else "linux"
    )


def _display(name: str) -> str:
    return _DISPLAY.get(name, name.capitalize())


@dataclass
class Profile:
    """One browser profile: its directory and, when present, its cookie DB."""

    path: str
    cookie_db: str = ""

    @property
    def has_cookies(self) -> bool:
        return bool(self.cookie_db)


@dataclass
class Browser:
    """One installed browser, discovered from paths alone."""

    name: str
    family: str
    executable: str = ""
    user_data: str = ""
    profiles: List[Profile] = field(default_factory=list)
    running: bool = False
    debugging: bool = False
    debug_port: int = 0
    configured: bool = False

    @property
    def display(self) -> str:
        return _display(self.name)

    @property
    def installed(self) -> bool:
        """True when an executable or at least one profile was found."""
        return bool(self.executable or self.user_data or self.profiles)

    def as_dict(self) -> dict:
        """JSON-safe summary. No cookie is ever part of this."""
        return {
            "name": self.name,
            "display": self.display,
            "family": self.family,
            "installed": self.installed,
            "executable": self.executable,
            "user_data": self.user_data,
            "running": self.running,
            "debugging": self.debugging,
            "debug_port": self.debug_port,
            "configured": self.configured,
            "profiles": [
                {"path": p.path, "cookie_db": p.has_cookies}
                for p in self.profiles
            ],
        }


@dataclass
class Presence:
    """The answer to "does this profile hold a cookie for that site?".

    ``found`` is the whole answer. ``skipped`` is a reason a profile could not
    be asked; it is never a cookie value or a cookie name.
    """

    browser: str
    family: str
    profile: str
    found: bool
    skipped: str = ""

    def as_dict(self) -> dict:
        return {
            "browser": self.browser,
            "family": self.family,
            "profile": self.profile,
            "found": self.found,
            "skipped": self.skipped,
        }


# ── executables ─────────────────────────────────────────────────────────────


def _firefox_executable(
    name: str,
    *,
    platform: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    exists: Optional[Callable[[str], bool]] = None,
    which: Optional[Callable[[str], Optional[str]]] = None,
) -> str:
    """A Firefox-family executable path, or ``""`` when it is not installed."""
    plat = platform or _platform()
    environ = os.environ if env is None else env
    check = exists or os.path.exists
    find = which or shutil.which
    for exe in _FIREFOX_EXE.get(name, ()):
        found = find(exe)
        if found and check(found):
            return found
    home = (
        environ.get("HOME")
        or environ.get("USERPROFILE")
        or os.path.expanduser("~")
    )
    if plat == "macos":
        bundle, binary = _MAC_FIREFOX.get(name, ("", ""))
        if bundle:
            path = os.path.join(home, "Applications", bundle, "Contents", "MacOS", binary)
            if check(path):
                return path
            path = os.path.join("/Applications", bundle, "Contents", "MacOS", binary)
            if check(path):
                return path
    if plat == "windows":
        roots = [
            environ.get("PROGRAMFILES", ""),
            environ.get("PROGRAMFILES(X86)", ""),
            environ.get("LOCALAPPDATA", ""),
        ]
        for root in roots:
            if not root:
                continue
            for rel in _WIN_FIREFOX.get(name, ()):
                path = os.path.join(root, rel)
                if check(path):
                    return path
    return ""


def executable_for(name: str) -> str:
    """The executable for a supported browser, or ``""`` when it is missing.

    Chromium-family lookup is :func:`searchts.cdp_profile.browser_executable`,
    the same one ``login keep`` and ``login signin`` use, so detection never
    disagrees with the path that actually launches the browser.
    """
    key = (name or "").strip().lower()
    if key in sc.CHROMIUM_FAMILY:
        try:
            from searchts.cdp_profile import browser_executable

            return browser_executable(key)
        except Exception:  # noqa: BLE001 - "not installed" is not an error here
            return ""
    if key in sc.FIREFOX_FAMILY:
        return _firefox_executable(key)
    return ""


# ── profiles ────────────────────────────────────────────────────────────────


def _chromium_cookie_db(profile: str, exists: Callable[[str], bool]) -> str:
    """The cookie DB inside a Chromium profile, new layout first."""
    for rel in ("Network/Cookies", "Cookies"):
        path = os.path.join(profile, *rel.split("/"))
        if exists(path):
            return path
    return ""


def chromium_profiles(
    user_data: str,
    *,
    exists: Optional[Callable[[str], bool]] = None,
) -> List[Profile]:
    """Every profile below one Chromium user-data directory.

    A profile is a directory carrying a cookie DB or a ``Preferences`` file.
    ``System Profile`` is skipped: it belongs to the browser, not a person.
    """
    check = exists or os.path.exists
    if not os.path.isdir(user_data):
        return []
    found: List[Profile] = []
    for entry in sorted(os.listdir(user_data)):
        path = os.path.join(user_data, entry)
        if entry == "System Profile" or not os.path.isdir(path):
            continue
        db = _chromium_cookie_db(path, check)
        if db or check(os.path.join(path, "Preferences")):
            found.append(Profile(path=path, cookie_db=db))
    return found


def _firefox_running(profile: str) -> bool:
    """True when a Firefox-family browser holds this profile open.

    Firefox writes a ``lock`` symlink whose target ends in the pid, and a
    ``.parentlock`` file beside it. The pid check mirrors
    :func:`searchts.linkedin_attach.browser_is_running` rather than trusting a
    leftover file.
    """
    from searchts.linkedin_feed import _pid_alive

    lock = os.path.join(profile, "lock")
    if os.path.lexists(lock):
        try:
            target = os.readlink(lock)
        except OSError:
            target = ""
        pid = 0
        if "-" in target:
            try:
                pid = int(target.rsplit("-", 1)[-1])
            except ValueError:
                pid = 0
        if pid and _pid_alive(pid):
            return True
    return os.path.exists(os.path.join(profile, ".parentlock"))


def _firefox_root_exists(name: str, platform: str, env: Optional[Mapping[str, str]]) -> bool:
    env_map = dict(env) if env is not None else None
    return bool(sc._firefox_profile_roots(name, platform=platform, env=env_map))


def _configured_browser(
    executable: str,
    profile: str,
    *,
    exists: Callable[[str], bool],
    is_running: Optional[Callable[[str], bool]],
    probe: Callable[[int], bool],
) -> Browser:
    """The browser and user-data directory named by the settings.

    This is the same directory the attach path joins, so it is reported with
    the same checks: :func:`searchts.linkedin_attach.browser_is_running` for
    the profile lock, and ``DevToolsActivePort`` plus
    :func:`searchts.linkedin_attach.probe_port` for remote debugging.
    """
    name = attach.browser_of(executable or None, profile, None)[0]
    family = "firefox" if name in FIREFOX_BROWSERS else "chromium"
    if family == "firefox":
        profiles: List[Profile] = []
    else:
        profiles = chromium_profiles(profile, exists=exists)
    if is_running is not None:
        running = bool(is_running(profile))
    elif family == "firefox":
        running = _firefox_running(profile)
    else:
        running = attach.browser_is_running(profile)
    debugging = False
    port = 0
    if family == "chromium":
        active = attach.read_active_port(profile)
        if active is not None:
            port = active.port
            debugging = bool(probe(active.port))
    return Browser(
        name=name,
        family=family,
        executable=executable or "",
        user_data=profile,
        profiles=profiles,
        running=running,
        debugging=debugging,
        debug_port=port if debugging else 0,
        configured=True,
    )


def _detect_browsers(
    *,
    platform: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    exists: Optional[Callable[[str], bool]] = None,
    is_running: Optional[Callable[[str], bool]] = None,
    probe: Optional[Callable[[int], bool]] = None,
    executable_finder: Optional[Callable[[str], str]] = None,
    configured_browser: Optional[str] = None,
    configured_profile: Optional[str] = None,
) -> List[Browser]:
    """Discover installed browsers. Paths only; no cookie database is opened.

    ``env`` and ``platform`` build a fixture layout in tests. ``is_running``,
    ``probe`` and ``executable_finder`` are injection points so a test never
    looks at this machine's processes or browsers. ``configured_browser`` and
    ``configured_profile`` name the settings' choice; when given, that
    user-data directory is listed too, marked as configured.
    """
    plat = platform or _platform()
    environ = dict(env) if env is not None else None
    check = exists or os.path.exists
    finder = executable_finder or executable_for
    running_check = is_running
    port_check = probe or attach.probe_port

    out: List[Browser] = []
    for name in CHROMIUM_BROWSERS:
        roots = [
            root
            for root in attach.candidate_user_data_dirs(name, platform=plat, env=environ)
            if check(root)
        ]
        profiles: List[Profile] = []
        for root in roots:
            profiles.extend(chromium_profiles(root, exists=check))
        exe = finder(name) or ""
        if not roots and not exe:
            continue
        user_data = roots[0] if roots else ""
        if running_check is not None:
            running = bool(user_data and running_check(user_data))
        else:
            running = bool(user_data and attach.browser_is_running(user_data))
        debugging = False
        port = 0
        if user_data:
            active = attach.read_active_port(user_data)
            if active is not None:
                port = active.port
                debugging = bool(port_check(active.port))
        out.append(Browser(
            name=name,
            family="chromium",
            executable=exe,
            user_data=user_data,
            profiles=profiles,
            running=running,
            debugging=debugging,
            debug_port=port if debugging else 0,
        ))

    for name in FIREFOX_BROWSERS:
        env_map = dict(env) if env is not None else None
        pairs = sc._firefox_profiles(name, platform=plat, env=env_map)
        profiles = [Profile(path=path, cookie_db=db) for path, db in pairs]
        exe = finder(name) or ""
        root_exists = _firefox_root_exists(name, plat, env)
        if not profiles and not exe and not root_exists:
            continue
        if running_check is not None:
            running = any(running_check(p.path) for p in profiles)
        else:
            running = any(_firefox_running(p.path) for p in profiles)
        out.append(Browser(
            name=name,
            family="firefox",
            executable=exe,
            profiles=profiles,
            running=running,
        ))

    if configured_profile:
        existing = next(
            (b for b in out if b.user_data == configured_profile), None
        )
        if existing is not None:
            existing.configured = True
        else:
            out.append(_configured_browser(
                configured_browser or "",
                configured_profile,
                exists=check,
                is_running=running_check,
                probe=port_check,
            ))
    return out


def installed_browsers(
    *,
    platform: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    exists: Optional[Callable[[str], bool]] = None,
    is_running: Optional[Callable[[str], bool]] = None,
    probe: Optional[Callable[[int], bool]] = None,
    executable_finder: Optional[Callable[[str], str]] = None,
) -> List[Browser]:
    """Discover installed browsers and their profiles, this platform first."""
    return _detect_browsers(
        platform=platform,
        env=env,
        exists=exists,
        is_running=is_running,
        probe=probe,
        executable_finder=executable_finder,
        configured_browser=bs.browser_executable(),
        configured_profile=bs.browser_profile(),
    )


def format_report(browsers: Sequence[Browser]) -> str:
    """The doctor's browser section: paths, running, and debugging.

    Plain text and unwrapped commands-free, like the rest of the doctor
    report. Returns ``""`` when nothing was found, so a machine without a
    supported browser gets no empty heading.
    """
    if not browsers:
        return ""
    lines = ["", "  BROWSERS"]
    for browser in browsers:
        state = "running" if browser.running else "not running"
        if browser.debugging:
            state += f", remote debugging on (port {browser.debug_port})"
        elif browser.configured and browser.family == "chromium" and browser.running:
            state += ", remote debugging off"
        lines.append(f"  {browser.display} ({browser.family}): {state}")
        if browser.executable:
            lines.append(f"    executable: {browser.executable}")
        if browser.user_data:
            note = " (configured)" if browser.configured else ""
            lines.append(f"    user data: {browser.user_data}{note}")
        for profile in browser.profiles:
            note = " (cookies)" if profile.has_cookies else " (no cookie DB)"
            lines.append(f"    profile: {profile.path}{note}")
        if not browser.profiles:
            lines.append("    no profile found")
    return "\n".join(lines)


# ── presence: never a value, never a decrypt ────────────────────────────────


@dataclass(frozen=True)
class _Lookup:
    found: bool
    skipped: str = ""
    via_temp: bool = False


def _site_of(site: str) -> str:
    host = (urlparse(site if "://" in site else "https://" + site).hostname or "").lower()
    return sc.registrable(host) or host.strip(".")


def _same_site(domain: str, want: str) -> bool:
    """True when a cookie host belongs to ``want``'s registrable domain."""
    raw = (domain or "").strip().lower().lstrip(".")
    if not raw or not want:
        return False
    if raw == want:
        return True
    registered = sc.registrable(raw)
    return bool(registered and registered == want)


def _query_hosts(db: str, family: str) -> List[str]:
    """Read every distinct host from a cookie DB. Values are never selected."""
    con = sc._open_ro(db)
    try:
        if family == "chromium":
            rows = con.execute("SELECT DISTINCT host_key FROM cookies").fetchall()
        else:
            rows = con.execute("SELECT DISTINCT host FROM moz_cookies").fetchall()
    finally:
        con.close()
    return [str(row[0]) for row in rows if row and row[0]]


def _lookup_db(db: str, family: str, want: str) -> _Lookup:
    """Ask one cookie DB whether a cookie for ``want`` exists.

    The first read is read-only. A locked/busy database is copied with its
    WAL sidecars to a temporary directory and read there, then deleted. Any
    other failure is reported as a skip, never guessed as "no".
    """
    try:
        hosts = _query_hosts(db, family)
        return _Lookup(any(_same_site(host, want) for host in hosts))
    except sqlite3.Error as exc:
        text = str(exc).lower()
        if "locked" not in text and "busy" not in text:
            return _Lookup(False, f"could not read the cookie database ({type(exc).__name__})")
    except Exception as exc:  # noqa: BLE001 - a skip, not a failed read
        return _Lookup(False, f"could not read the cookie database ({type(exc).__name__})")

    scratch = ""
    try:
        scratch = tempfile.mkdtemp(prefix="searchts-cookie-presence-")
        copy = os.path.join(scratch, os.path.basename(db) or "Cookies")
        shutil.copy2(db, copy)
        for suffix in ("-wal", "-shm"):
            side = db + suffix
            if os.path.exists(side):
                shutil.copy2(side, copy + suffix)
        hosts = _query_hosts(copy, family)
        return _Lookup(any(_same_site(host, want) for host in hosts), via_temp=True)
    except Exception as exc:  # noqa: BLE001 - skip and say so
        return _Lookup(
            False,
            f"cookie database was locked and could not be read ({type(exc).__name__})",
        )
    finally:
        if scratch:
            shutil.rmtree(scratch, ignore_errors=True)


def cookie_presence(
    site: str,
    *,
    browsers: Optional[Sequence[Browser]] = None,
    platform: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    exists: Optional[Callable[[str], bool]] = None,
    is_running: Optional[Callable[[str], bool]] = None,
    probe: Optional[Callable[[int], bool]] = None,
    executable_finder: Optional[Callable[[str], str]] = None,
) -> List[Presence]:
    """Which browser profiles hold a cookie for ``site``'s registrable domain.

    Presence only: a cookie exists there or it does not. Nothing is
    decrypted, no cookie name is returned, and no cookie is copied.
    """
    want = _site_of(site)
    if not want:
        return []
    discovered = (
        list(browsers)
        if browsers is not None
        else installed_browsers(
            platform=platform,
            env=env,
            exists=exists,
            is_running=is_running,
            probe=probe,
            executable_finder=executable_finder,
        )
    )
    out: List[Presence] = []
    for browser in discovered:
        for profile in browser.profiles:
            if not profile.cookie_db:
                continue
            result = _lookup_db(profile.cookie_db, browser.family, want)
            if result.found or result.skipped:
                out.append(Presence(
                    browser=browser.name,
                    family=browser.family,
                    profile=profile.path,
                    found=result.found,
                    skipped=result.skipped,
                ))
    return out
