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
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

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
    # A cookie domain with no dot is a host, not a suffix. "com" is not a parent
    # of example.com, so such a cookie matches exactly or not at all: a suffix
    # rule here would sweep a jar's stray single-label cookie onto every site
    # under that label. Browsers reject a domain cookie in that position too.
    if "." not in cd:
        return False
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
    # Quoted rather than string-surgery: SQLite reads %XX in a URI, so a profile
    # path carrying a % (or a ?, or a #) would otherwise be opened as a
    # different file than the one that was checked with isfile().
    uri = "file:" + quote(db.replace("\\", "/"), safe="/:")
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
    cookie values are not readable off disk. The debugger-port path in
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
        raise CookieReadError(chromium_locked_message(browser))
    return read_firefox_family(browser, site)


def chromium_locked_message(browser: str) -> str:
    """Why a Chromium browser cannot be read off disk, and what does work.

    Split by platform because the blanket "App-Bound Encryption" was a lie on
    two of the three: that wrapper is Windows-only since Chrome 127. On macOS
    and Linux the values are encrypted with a key from the system keyring, which
    a headless read cannot obtain without a prompt appearing on the user's
    screen. Either way the answer for the caller is the same and is the only
    part worth acting on, so it is the last sentence in both.
    """
    if os.name == "nt":
        why = (
            "Chrome wraps that key in App-Bound Encryption, which refuses to "
            "hand it to another program, so running as administrator does not "
            "help"
        )
    else:
        why = (
            "its cookie values are encrypted with a key that lives in the "
            "system keyring, and a keyring is not something a read can open "
            "quietly on your screen"
        )
    return (
        f"{browser}'s cookies are locked: {why}. "
        f"Read them through a debugger port you open instead: start "
        f"{browser} with --remote-debugging-port=9222 and pass --cdp-port 9222 "
        f"to read. Firefox-derived browsers (Zen, Firefox, LibreWolf) have no "
        f"such lock and can be read directly."
    )


# ── one resolver, so the CLI and the MCP tool cannot drift apart ──────────────


def read_cookie_file(path: str, site: str) -> CookieSource:
    """Read a searchts-owned JSON cookie file, scoped to `site`.

    Accepts the shapes searchts itself writes and the ones a person types: a
    bare list, ``{"cookies": [...]}``, or the owned store's
    ``{"host": {"cookies": [...]}}``. Short keys (``n``/``v``/``d``) are the
    owned store's own; long ones (``name``/``value``/``domain``) are what every
    cookie exporter on earth writes.
    """
    import json
    from pathlib import Path

    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise CookieReadError(
            f"could not read cookie file {path!r} ({type(e).__name__})"
        ) from None

    host = (urlparse(site if "://" in site else "https://" + site).hostname or "").lower()
    raw: object = data
    if isinstance(data, dict) and isinstance(data.get("cookies"), list):
        raw = data["cookies"]
    elif isinstance(data, dict):
        entry = data.get(host)
        if isinstance(entry, dict):
            raw = entry.get("cookies", [])
        elif isinstance(entry, list):
            raw = entry
        else:
            raw = []
    if not isinstance(raw, list):
        raw = []

    records = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name", item.get("n", ""))
        value = item.get("value", item.get("v", ""))
        domain = item.get("domain", item.get("d", host))
        if not name or not domain:
            continue
        records.append(CookieRecord(
            str(name), str(value), str(domain), str(item.get("path", item.get("p", "/"))),
            bool(item.get("secure", item.get("s", False))),
            bool(item.get("http_only", item.get("h", False))),
        ))
    scoped = filter_for_host(records, host)
    if not scoped:
        raise CookieReadError(
            f"no cookies for {host} in {path!r}. Cookies are host-scoped: a "
            f"file holding only other sites' cookies reads as nothing here."
        )
    return CookieSource(site=site, cookies=scoped, via="file", count=len(scoped),
                        names=sorted({c.name for c in scoped}))


def resolve_cookies(
    site: str,
    *,
    cookies: str = "",
    cookies_from_browser: str = "",
    cdp_port: object = None,
) -> Optional[List[CookieRecord]]:
    """Resolve one read's opt-in cookies. Returns None when none were asked for.

    The single entry point for every caller: the CLI flags, the MCP tool's
    arguments, and anything that drives ``unlocker.fetch`` from a library all
    come through here, so the scoping rules and the messages live in one place
    and a second surface cannot grow a second, laxer one.

    Raises :class:`CookieReadError` with one sentence a user can act on.
    """
    if not cookies and not cookies_from_browser and cdp_port in (None, ""):
        return None
    if cdp_port not in (None, ""):
        # Imported here: cdp_profile imports this module, so a top-level import
        # would be a cycle.
        from searchts.cdp_profile import connect_existing_cdp, parse_endpoint

        # Validate before importing/connecting to any CDP client. The connection
        # helper validates too; this keeps the rejection local.
        parse_endpoint(cdp_port)
        source = connect_existing_cdp(cdp_port, site)
    elif cookies:
        source = read_cookie_file(cookies, site)
    else:
        source = for_site(site, cookies_from_browser)
    if not source.cookies:
        raise CookieReadError("no cookies were found for this site")
    if not source.count:
        source.count = len(source.cookies)
    return source.cookies
