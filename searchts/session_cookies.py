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
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
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


#: A value above this is almost certainly milliseconds, not seconds. Firefox
#: writes seconds, but a copied jar or a test double can carry millis, and
#: interpreting those as seconds would make a cookie look alive for millennia.
_MILLIS_THRESHOLD = 100_000_000_000


def normalize_expiry(value: Any) -> Optional[int]:
    """Unix seconds for a cookie expiry, or None for a session cookie.

    ``None`` is the session-cookie marker. ``-1`` and ``0`` are what CDP and
    Firefox use for "no expiry", so both collapse to ``None`` too. Values large
    enough to be milliseconds are divided down once.
    """
    if value is None or value == "":
        return None
    try:
        seconds = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None
    if seconds <= 0:
        return None
    if seconds > _MILLIS_THRESHOLD:
        seconds //= 1000
    return seconds


def is_expired(record: "CookieRecord", now: Optional[int] = None) -> bool:
    """True only when the cookie carries an expiry that is at or before now.

    A session cookie (``expiry is None``) never expires here: it dies when the
    browser closes, which is not something this store can observe.
    """
    if record.expiry is None:
        return False
    return record.expiry <= int(time.time() if now is None else now)


@dataclass
class CookieRecord:
    """One cookie, scoped to the host that owns it.

    ``expiry`` is unix seconds, or ``None`` when the source called it a session
    cookie. Legacy store entries have no expiry at all; they load as ``None``
    and are never treated as dead on their own.
    """

    name: str
    value: str
    domain: str
    path: str = "/"
    secure: bool = False
    http_only: bool = False
    expiry: Optional[int] = None

    def __post_init__(self) -> None:
        self.expiry = normalize_expiry(self.expiry)

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
    #: Earliest expiry among the live cookies, or None when every cookie is a
    #: session cookie. ``expiry_known`` is False for a legacy entry that never
    #: recorded one, so a CLI can say "unknown" rather than lying "session".
    expires_at: Optional[int] = None
    expiry_known: bool = False
    expired: bool = False

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
    """Keep only cookies this host would receive, and only live ones.

    Expiry is checked here as well as in the sweep. A sweep that did not run,
    or a browser database that has not been vacuumed, must not be able to make
    a dead cookie reach a request.
    """
    now = int(time.time())
    return [c for c in records if _domain_matches(c.domain, host) and not is_expired(c, now)]


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
            # Old test fixtures (and very old profiles) can predate the expiry
            # column. Read it when it exists; otherwise every cookie is a
            # session cookie, which is the same thing the absence means.
            columns = {row[1] for row in con.execute("PRAGMA table_info(moz_cookies)")}
            expiry_expr = "expiry" if "expiry" in columns else "0"
            rows = con.execute(
                "SELECT name, value, host, path, isSecure, isHttpOnly, "
                f"{expiry_expr} FROM moz_cookies"
            ).fetchall()
        except sqlite3.Error as e:
            errors.append(f"{os.path.basename(prof)}: {e}")
            continue
        finally:
            con.close()

        records = [
            CookieRecord(n, v, h, p or "/", bool(s), bool(ho), expiry)
            for (n, v, h, p, s, ho, expiry) in rows
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


def _write_owned_store(store: Dict[str, dict]) -> None:
    """Write the whole owned store atomically, owner-readable only."""
    import json

    _ensure_store_dir()
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


def save_owned_site(
    site: str,
    records: List[CookieRecord],
    browser: str = "",
    *,
    consent: Optional[bool] = None,
) -> int:
    """Persist one site's cookies to the owned store. Returns the count saved.

    Only the site asked for is written. Values live in this file and nowhere
    else; the caller owns the decision to call it at all.

    ``consent`` records that the user or agent allowed this site's cookies to
    be copied. It is what lets a later refresh or login-wall retry happen
    without asking again. ``None`` keeps whatever the entry already said.
    """
    host = (urlparse(site if "://" in site else "https://" + site).hostname or "").lower()
    if not host or not records:
        raise CookieReadError(f"nothing to save for {site!r}")
    scoped = filter_for_host(records, host)
    if not scoped:
        raise CookieReadError(f"refusing to save: no cookies match {host}")

    store = read_owned_store()
    existing = store.get(host)
    allowed = (
        bool(existing.get("consent"))
        if consent is None and isinstance(existing, dict)
        else bool(consent)
    )
    store[host] = {
        "cookies": [
            {"n": c.name, "v": c.value, "d": c.domain, "p": c.path,
             "s": c.secure, "h": c.http_only, "expiry": c.expiry}
            for c in scoped
        ],
        "browser": browser,
        "expiry_known": True,
        "consent": allowed,
    }
    _write_owned_store(store)
    return len(scoped)


def entry_expiry(entry: dict, now: Optional[int] = None) -> Tuple[Optional[int], bool]:
    """Earliest expiry in a store entry, and whether the entry recorded one.

    ``(None, True)`` means every cookie is a session cookie; ``(None, False)``
    means a legacy entry that has no expiry information at all. A marked
    expired entry reports the moment it was marked so callers can still sort it.
    """
    if not isinstance(entry, dict):
        return None, False
    known = bool(entry.get("expiry_known"))
    values: List[int] = []
    for cookie in entry.get("cookies") or []:
        if not isinstance(cookie, dict):
            continue
        if "expiry" in cookie:
            known = True
        expiry = normalize_expiry(cookie.get("expiry"))
        if expiry is not None:
            values.append(expiry)
    if values:
        return min(values), True
    if entry.get("expired"):
        return None, known
    return None, known


def describe_expiry(entry: dict, now: Optional[int] = None) -> str:
    """One short human phrase: expired, expires in N days, session, unknown."""
    if not isinstance(entry, dict):
        return "unknown"
    now = int(time.time() if now is None else now)
    if entry.get("expired"):
        return "expired"
    at, known = entry_expiry(entry, now)
    if at is None:
        return "session" if known else "unknown"
    if at <= now:
        return "expired"
    seconds = at - now
    days = seconds // 86400
    if days >= 1:
        return f"expires in {days} day{'s' if days != 1 else ''}"
    hours = max(1, seconds // 3600)
    return f"expires in {hours} hour{'s' if hours != 1 else ''}"


@dataclass
class SweepResult:
    """What one sweep did. Counts and safe action rows, never a value."""

    removed: int = 0
    expired_sites: int = 0
    live_sites: int = 0
    total_sites: int = 0
    actions: List[dict] = field(default_factory=list)


def sweep_owned_store(now: Optional[int] = None) -> SweepResult:
    """Delete expired cookies from the store and mark sites left with none.

    Cheap and offline: no browser, no network, no daemon. Best effort by
    design: a store that cannot be read or written must not stop the command
    the user actually ran. An expired site keeps its entry, with no live
    cookies and an ``expired`` marker, so ``login list`` can say so and a read
    sends nothing for it.
    """
    now = int(time.time() if now is None else now)
    result = SweepResult()
    try:
        store = read_owned_store()
    except Exception:  # noqa: BLE001 - a sweep is never allowed to break a command
        return result
    if not store:
        return result

    changed = False
    for host, entry in list(store.items()):
        if not isinstance(entry, dict):
            continue
        result.total_sites += 1
        kept = []
        dropped = 0
        for cookie in entry.get("cookies") or []:
            if not isinstance(cookie, dict):
                continue
            expiry = normalize_expiry(cookie.get("expiry"))
            if expiry is not None and expiry <= now:
                dropped += 1
                continue
            kept.append(cookie)
        if dropped:
            changed = True
            result.removed += dropped
            entry["cookies"] = kept
            if not kept:
                entry["expired"] = True
                entry["expired_at"] = now
            else:
                entry.pop("expired", None)
                entry.pop("expired_at", None)
            result.actions.append({
                "site": host,
                "browser": entry.get("browser") or "signin",
                "action": "deleted",
                "count": dropped,
                "reason": "expired",
            })
        if entry.get("expired") and not kept:
            result.expired_sites += 1
        elif kept:
            entry.pop("expired", None)
            entry.pop("expired_at", None)
            result.live_sites += 1

    if changed:
        try:
            _write_owned_store(store)
        except Exception:  # noqa: BLE001 - see the docstring
            return result
    return result


def read_owned_site(site: str) -> CookieSource:
    """Return `site`'s live cookies from the owned store.

    Expired cookies are filtered here as well as by the startup sweep, so a
    stale file cannot put a dead cookie on a request. An entry whose cookies
    have all died (or that the sweep marked expired) raises a named error
    instead of pretending the site was never kept.
    """
    host = (urlparse(site if "://" in site else "https://" + site).hostname or "").lower()
    entry = read_owned_store().get(host)
    if not entry:
        raise CookieReadError(f"no saved login for {host} in the searchts store")
    raw = [c for c in entry.get("cookies", []) if isinstance(c, dict)]
    records = [
        CookieRecord(c.get("n", ""), c.get("v", ""), c.get("d", ""),
                     c.get("p", "/"), bool(c.get("s")), bool(c.get("h")),
                     c.get("expiry"))
        for c in raw
    ]
    scoped = filter_for_host(records, host)
    if not scoped and (entry.get("expired") or any(is_expired(c) for c in records)):
        raise CookieReadError(
            f"the saved login for {host} has expired; run "
            f"`searchts login signin {host}` to sign in again"
        )
    at, known = entry_expiry(entry)
    return CookieSource(
        site=site,
        cookies=scoped,
        browser=entry.get("browser", "") if isinstance(entry, dict) else "",
        family="owned",
        via="owned store",
        count=len(scoped),
        names=sorted({c.name for c in scoped}),
        expires_at=at,
        expiry_known=known,
        expired=bool(entry.get("expired")),
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

    ``browser`` is defaulted, not trusted: an empty name once produced a
    sentence that opened with "''s cookies are locked", which names nothing at
    all at the exact moment the user has least idea what to do.
    """
    name = (browser or "").strip() or "this browser"
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
        f"{name}'s cookies are locked: {why}. "
        f"Read them through a debugger port you open instead: start "
        f"{name} with --remote-debugging-port=9222 and pass --cdp-port 9222 "
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
    except FileNotFoundError:
        raise CookieReadError(
            f"no cookie file at {path!r}. Point --cookies at a JSON file of "
            f"cookies for this site, or drop the flag and use "
            f"--cdp-port / --cookies-from-browser instead."
        ) from None
    except IsADirectoryError:
        raise CookieReadError(f"{path!r} is a directory, not a cookie file.") from None
    except PermissionError:
        raise CookieReadError(
            f"not allowed to read the cookie file {path!r}."
        ) from None
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
        # No host fallback here. The `if not domain` guard below is written to
        # drop an entry that carries no domain, and a fallback to `host` makes
        # that guard unreachable: domain is then always a non-empty string, and
        # the cookie additionally matches *every* host, because it is scoped to
        # exactly whatever site is being read. A file shaped
        # [{"name":..,"value":..}] therefore passed filter_for_host for any URL,
        # and MCP read_url accepts a cookie path, so one such file carried a
        # login to whatever host an agent named next.
        #
        # Requiring the key is the documented contract: every cookie exporter
        # writes a domain, and searchts's own store writes `d`. An entry
        # without one is malformed, and dropping it is what the guard already
        # said should happen.
        domain = item.get("domain", item.get("d", ""))
        if not name or not domain:
            continue
        records.append(CookieRecord(
            str(name), str(value), str(domain), str(item.get("path", item.get("p", "/"))),
            bool(item.get("secure", item.get("s", False))),
            bool(item.get("http_only", item.get("h", False))),
            item.get("expiry", item.get("expires", item.get("expirationDate"))),
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

    The three sources are mutually exclusive and saying so beats picking one:
    ``--cookies f --cookies-from-browser firefox`` used to read the file, ignore
    the browser, and print a line about the file, so the person asking for a
    Firefox read got a file's cookies and no word about it. One precedence rule
    (``cdp_port`` > ``cookies`` > ``cookies_from_browser``) is kept for
    programmatic callers that cannot ask, but a caller that passed more than one
    is told.
    """
    if not cookies and not cookies_from_browser and cdp_port in (None, ""):
        return None
    asked = [
        # The flag spelling, not the parameter name: the same sentence reaches an
        # agent over MCP, and one list has to be readable to both.
        flag for flag, value in (
            ("--cdp-port", cdp_port), ("--cookies", cookies),
            ("--cookies-from-browser", cookies_from_browser),
        ) if value not in (None, "")
    ]
    if len(asked) > 1:
        raise CookieReadError(
            f"asked for cookies {len(asked)} ways ({', '.join(asked)}). One read "
            f"uses one source: --cdp-port for a debugger port you opened, "
            f"--cookies for a file, --cookies-from-browser for a "
            f"Firefox-family profile."
        )
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
