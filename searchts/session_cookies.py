"""Host-scoped session cookies, so a read can use a login without an agent
holding anyone's credentials.

Three sources, tried in this order:

    owned store    searchts --cookies <file>       a login searchts itself holds
    local browser  searchts --cookies-from-browser Zen, Firefox, ... on disk
    debugger port  searchts --cdp-port 9222       Chromium, via a port you opened

The invariant this module exists to keep: cookie material is attached only to
requests for the host that owns the cookie. Never to the unlocker relays
(r.jina.ai and friends), never to a different site in the same read, and never
printed. Every function that touches a value keeps it in the return value.

Reading from a browser is read-only. We open the cookie database with SQLite's
``mode=ro``; nothing here writes to a browser profile or refreshes a token.
"""

from __future__ import annotations

import glob
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from urllib.parse import urlparse

# ── browsers ────────────────────────────────────────────────────────────────
# One registry, not one dict per library. Adding a browser used to mean editing
# three dictionaries in sequence and forgetting the third.

#: Firefox-derived browsers. Cookie DB is an unencrypted SQLite file on Windows
#: and Linux (macOS keeps it in the keychain), so these need no crypto library.
FIREFOX_FAMILY = ("zen", "firefox", "librewolf", "waterfox", "floorp", "mullvad")

#: Chromium-derived browsers. Cookie values are DPAPI/AES-GCM encrypted and, on
#: Chrome 127+, wrapped in App-Bound Encryption that refuses to hand the key to
#: another process. Reaching these needs a debugger port, not this module.
CHROMIUM_FAMILY = ("vivaldi", "chrome", "edge", "brave", "opera", "arc", "chromium")

ALL_BROWSERS = FIREFOX_FAMILY + CHROMIUM_FAMILY


def family_of(browser: str) -> str:
    """Return "firefox", "chromium", or raise with the supported list."""
    b = (browser or "").strip().lower()
    if b in FIREFOX_FAMILY:
        return "firefox"
    if b in CHROMIUM_FAMILY:
        return "chromium"
    raise ValueError(
        f"Unknown browser {browser!r}. Supported: {', '.join(sorted(ALL_BROWSERS))}"
    )


# Where each Firefox-derived browser keeps its profiles on this machine.
def _firefox_profile_roots(browser: str) -> List[str]:
    home = os.path.expanduser("~")
    appdata = os.environ.get("APPDATA", "")
    if os.name == "nt":
        roots = {
            "zen": [os.path.join(appdata, "zen", "Profiles")],
            "firefox": [os.path.join(appdata, "Mozilla", "Firefox", "Profiles")],
            "librewolf": [os.path.join(appdata, "librewolf", "Profiles")],
            "waterfox": [os.path.join(appdata, "Waterfox", "Profiles")],
            "floorp": [os.path.join(appdata, "floorp", "Profiles")],
            "mullvad": [os.path.join(appdata, "Mullvad", "Profiles")],
        }
    else:
        mac = os.path.join(home, "Library", "Application Support")
        roots = {
            "zen": [os.path.join(mac, "zen", "Profiles"), os.path.join(home, ".zen")],
            "firefox": [os.path.join(mac, "Firefox", "Profiles"),
                        os.path.join(home, ".mozilla", "firefox")],
            "librewolf": [os.path.join(home, ".librewolf")],
            "waterfox": [os.path.join(home, ".waterfox")],
            "floorp": [os.path.join(home, ".floorp")],
            "mullvad": [os.path.join(home, ".mullvad")],
        }
    out = [r for r in roots.get(browser, []) if os.path.isdir(r)]
    if browser == "firefox":
        # Debian/Ubuntu package path.
        deb = os.path.join(home, ".mozilla", "firefox")
        if os.path.isdir(deb) and deb not in out:
            out.append(deb)
    return out


# ── what we read ────────────────────────────────────────────────────────────


@dataclass
class CookieRecord:
    """One cookie, scoped to the host that owns it."""

    name: str
    value: str
    domain: str
    path: str = "/"
    secure: bool = False
    http_only: bool = False

    @property
    def host(self) -> str:
        return self.domain.lstrip(".").lower()


@dataclass
class CookieSource:
    """Provenance for one site's cookies.

    ``browser`` is empty for a file or a port. ``count`` and ``names`` exist so
    a CLI can report what was used without ever printing a value.
    """

    site: str
    cookies: List[CookieRecord] = field(default_factory=list)
    browser: str = ""
    family: str = ""
    via: str = ""
    count: int = 0
    names: List[str] = field(default_factory=list)

    def describe(self) -> str:
        """One safe line for a human. Contains no cookie values."""
        if self.browser:
            return f"{self.via or 'browser'} ({self.browser}) -> {self.count} cookies for {self.site}"
        return f"{self.via or 'cookies'} -> {self.count} cookies for {self.site}"


# ── scoping ─────────────────────────────────────────────────────────────────


def registrable(host: str) -> str:
    """Approximate registrable domain. Good enough to keep a cookie in its family."""
    parts = [p for p in (host or "").lower().strip(".").split(".") if p]
    if len(parts) <= 2:
        return ".".join(parts)
    # Handle the common two-part public suffixes so example.co.uk stays whole.
    two = {"co", "com", "org", "net", "gov", "edu", "ac", "or", "ne"}
    if len(parts) >= 3 and parts[-2] in two and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _domain_matches(cookie_domain: str, host: str) -> bool:
    """True when a cookie for `cookie_domain` belongs on a request to `host`.

    This is the reason the module exists. A loose ``endswith`` here would hand
    every cookie in the jar to whatever host was being read, which is the
    failure mode where an agent opens your mail.
    """
    cd = (cookie_domain or "").lstrip(".").lower()
    h = (host or "").lower().strip(".")
    if not cd or not h:
        return False
    if cd == h:
        return True
    # .amazon.in must ride along on www.amazon.in, not on notamazon.in.
    return h.endswith("." + cd)


def filter_for_host(records: List[CookieRecord], host: str) -> List[CookieRecord]:
    """Keep only cookies this host would actually receive from a browser."""
    return [c for c in records if _domain_matches(c.domain, host)]


def build_header(records: List[CookieRecord]) -> str:
    """Render a Cookie header. The caller decides where this string goes."""
    return "; ".join(f"{c.name}={c.value}" for c in records)


# ── Firefox-family reader (zero dependencies, read-only) ────────────────────


class CookieReadError(RuntimeError):
    """A cookie store could not be read. Carries a sentence, not a traceback."""


def _open_ro(db: str) -> sqlite3.Connection:
    """Open a cookie DB read-only.

    Read-only matters for a reason beyond politeness: a plain connect() on a
    live WAL database can create -wal/-shm files and checkpoint, which is a
    write to the user's browser profile.
    """
    if not os.path.isfile(db):
        raise CookieReadError(f"no cookie database at {db}")
    uri = "file:" + db.replace("\\", "/").replace("?", "%3f").replace("#", "%23")
    return sqlite3.connect(uri + "?mode=ro", uri=True, timeout=2)


def _firefox_profiles(browser: str) -> List[Tuple[str, str]]:
    found: List[Tuple[str, str]] = []
    for root in _firefox_profile_roots(browser):
        for prof in sorted(glob.glob(os.path.join(root, "*"))):
            db = os.path.join(prof, "cookies.sqlite")
            if os.path.isfile(db):
                found.append((prof, db))
    return found


def _read_all_firefox_records(browser: str) -> List[CookieRecord]:
    """Every cookie the browser holds, across all its profiles, unscoped.

    Read-only: SQLite is opened with mode=ro and never written.
    """
    profiles = _firefox_profiles(browser)
    if not profiles:
        raise CookieReadError(
            f"no {browser} profile found (looked in "
            f"{', '.join(_firefox_profile_roots(browser)) or 'the usual places'})"
        )

    errors: List[str] = []
    best: List[CookieRecord] = []
    for prof, db in profiles:
        try:
            con = _open_ro(db)
        except Exception as e:
            errors.append(f"{os.path.basename(prof)}: {e}")
            continue
        try:
            rows = con.execute(
                "SELECT name, value, host, path, isSecure, isHttpOnly "
                "FROM moz_cookies"
            ).fetchall()
        except sqlite3.Error as e:
            errors.append(f"{os.path.basename(prof)}: {e}")
            continue
        finally:
            con.close()

        records = [
            CookieRecord(n, v, h, p or "/", bool(s), bool(ho))
            for (n, v, h, p, s, ho) in rows
        ]
        # Prefer the richest profile rather than the first with any rows.
        if len(records) > len(best):
            best = records
    if not best and errors:
        raise CookieReadError(errors[0])
    return best


def read_all_firefox(browser: str) -> List[CookieRecord]:
    """Unscoped cookie read, for tooling that filters by its own platform list.

    Callers must scope the result before it goes anywhere near a request.
    """
    fam = family_of(browser)
    if fam != "firefox":
        raise CookieReadError(
            f"{browser} is Chromium-derived; use --cdp-port to read it."
        )
    return _read_all_firefox_records(browser)


def read_firefox_family(browser: str, site: str) -> CookieSource:
    """Read `site`'s cookies from a Firefox-derived browser's own profile.

    Read-only: SQLite is opened with mode=ro and never written.
    """
    host = (urlparse(site if "://" in site else "https://" + site).hostname or "").lower()
    if not host:
        raise CookieReadError(f"cannot work out a host from {site!r}")

    records = _read_all_firefox_records(browser)
    scoped = filter_for_host(records, host)
    if scoped:
        return CookieSource(
            site=site,
            cookies=scoped,
            browser=browser,
            family="firefox",
            via="browser",
            count=len(scoped),
            names=sorted({c.name for c in scoped}),
        )

    raise CookieReadError(
        f"no cookies for {host} in {browser} "
        f"({len(_firefox_profiles(browser))} profile(s) scanned). "
        f"Log in to that site in {browser} first."
    )


# ── owned store (the login searchts itself holds) ──────────────────────────


def owned_store_path() -> str:
    """Where searchts keeps the logins it was given, owner-readable only."""
    d = os.path.join(os.path.expanduser("~"), ".searchts", "cookies")
    return os.path.join(d, "owned.json")


def _ensure_store_dir() -> str:
    d = os.path.dirname(owned_store_path())
    os.makedirs(d, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass
    return d


def read_owned_store() -> Dict[str, dict]:
    """Read the owned store. Never creates it."""
    import json

    path = owned_store_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_owned_site(site: str, records: List[CookieRecord], browser: str = "") -> int:
    """Persist one site's cookies to the owned store. Returns the count saved.

    Only the site asked for is written. Values live in this file and nowhere
    else; the caller owns the decision to call it at all.
    """
    import json

    host = (urlparse(site if "://" in site else "https://" + site).hostname or "").lower()
    if not host or not records:
        raise CookieReadError(f"nothing to save for {site!r}")
    scoped = filter_for_host(records, host)
    if not scoped:
        raise CookieReadError(f"refusing to save: no cookies match {host}")

    _ensure_store_dir()
    store = read_owned_store()
    store[host] = {
        "cookies": [
            {"n": c.name, "v": c.value, "d": c.domain, "p": c.path,
             "s": c.secure, "h": c.http_only}
            for c in scoped
        ],
        "browser": browser,
    }
    path = owned_store_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2, sort_keys=True)
    if os.name != "nt":
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
    os.replace(tmp, path)
    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return len(scoped)


def read_owned_site(site: str) -> CookieSource:
    """Return `site`'s cookies from the owned store."""
    host = (urlparse(site if "://" in site else "https://" + site).hostname or "").lower()
    entry = read_owned_store().get(host)
    if not entry:
        raise CookieReadError(f"no saved login for {host} in the searchts store")
    records = [
        CookieRecord(c["n"], c["v"], c["d"], c.get("p", "/"),
                     bool(c.get("s")), bool(c.get("h")))
        for c in entry.get("cookies", [])
    ]
    scoped = filter_for_host(records, host)
    return CookieSource(
        site=site,
        cookies=scoped,
        family="owned",
        via="owned store",
        count=len(scoped),
        names=sorted({c.name for c in scoped}),
    )


# ── top-level entry ────────────────────────────────────────────────────────


def for_site(site: str, browser: str = "") -> CookieSource:
    """Best local source for `site`: the owned store, else a local browser.

    Chromium-derived browsers are refused here, with the reason, because their
    cookies are behind App-Bound Encryption. The debugger-port path in
    cdp_profile.py is the way to read those, and it opens a port only after the
    user says so.
    """
    try:
        return read_owned_site(site)
    except CookieReadError:
        pass
    if not browser:
        raise CookieReadError(
            "no owned login for this site; pass --cookies-from-browser <browser>"
        )
    fam = family_of(browser)
    if fam == "chromium":
        raise CookieReadError(
            f"{browser}'s cookies are locked (App-Bound Encryption). "
            "Use --cdp-port <port> to read them through a debugger you open."
        )
    return read_firefox_family(browser, site)
