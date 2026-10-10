# -*- coding: utf-8 -*-
"""Tests for searchts/session_cookies.py: host-scoped session cookies.

Hermetic by construction. No real browser is launched, no real profile is read,
and no request leaves the machine. Every home-ish environment variable the
module consults is redirected into tmp_path, and the Firefox cookie database is
fabricated here with sqlite3 rather than copied out of a user's profile.

The weight sits on the scoping rules, because that is the whole reason the
module exists: a cookie for one host must never ride along on a request to
another. A loose ``endswith`` would pass every happy-path case in this file
while handing an agent the whole jar, so the look-alike cases (notamazon.com
vs amazon.com, notamazon.in vs amazon.in) are asserted rather than assumed.
Swapping _domain_matches for a bare endswith fails three tests here.

Reading a browser is read-only by construction (SQLite ``mode=ro``), and one
test below checks the profile's bytes and its sidecar files are unchanged after
a read, rather than trusting the comment in the module docstring.
"""

import hashlib
import json
import os
import sqlite3
import stat
import sys
from pathlib import Path

import pytest

from searchts import session_cookies as sc  # for the private helpers below
from searchts.session_cookies import (
    ALL_BROWSERS,
    CHROMIUM_FAMILY,
    FIREFOX_FAMILY,
    CookieReadError,
    CookieRecord,
    build_header,
    family_of,
    filter_for_host,
    for_site,
    owned_store_path,
    read_firefox_family,
    read_owned_site,
    registrable,
    save_owned_site,
)

# The scoping predicate is the one function here that decides whether someone
# else's cookie reaches a request, so it is tested directly rather than only
# through filter_for_host.
_domain_matches = sc._domain_matches

# ── fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    """Redirect every home-ish variable session_cookies reads into tmp_path.

    HOME alone is not enough on Windows: ntpath.expanduser honours USERPROFILE
    and ignores HOME, so a test that only set HOME would create
    ~/.searchts/cookies/owned.json in the real user's profile.
    """
    home = tmp_path / "home"
    appdata = home / "AppData" / "Roaming"
    localappdata = home / "AppData" / "Local"
    for d in (home, appdata, localappdata):
        d.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(localappdata))
    return home


# Every directory _firefox_profile_roots may consult for these two browsers, as
# (env var, path below it): Windows under %APPDATA%, macOS under
# ~/Library/Application Support, Linux under a dot directory. The profile is
# written into all of them so this test asserts the same thing on any OS.
_FIREFOX_LAYOUTS = {
    "zen": (
        ("APPDATA", "zen/Profiles"),
        ("HOME", "Library/Application Support/zen/Profiles"),
        ("HOME", ".zen"),
    ),
    "firefox": (
        ("APPDATA", "Mozilla/Firefox/Profiles"),
        ("HOME", "Library/Application Support/Firefox/Profiles"),
        ("HOME", ".mozilla/firefox"),
    ),
}


def _write_moz_cookies(db: Path, rows) -> None:
    """Create a Firefox-shaped cookies.sqlite. Only the six read columns matter."""
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db))
    try:
        con.execute(
            "CREATE TABLE moz_cookies (id INTEGER PRIMARY KEY, name TEXT,"
            " value TEXT, host TEXT, path TEXT, isSecure INTEGER,"
            " isHttpOnly INTEGER)"
        )
        con.executemany(
            "INSERT INTO moz_cookies (name, value, host, path, isSecure,"
            " isHttpOnly) VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        con.commit()
    finally:
        con.close()


def _fake_firefox_profile(home: Path, browser: str, rows, profile="testprofile"):
    """Fabricate a browser profile holding `rows`. Returns every db written."""
    env = {"HOME": str(home), "APPDATA": os.path.join(str(home), "AppData", "Roaming")}
    dbs = []
    for var, rel in _FIREFOX_LAYOUTS[browser]:
        db = Path(env[var]) / rel / profile / "cookies.sqlite"
        _write_moz_cookies(db, rows)
        dbs.append(db)
    return dbs


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── 1. host scoping, the security core ─────────────────────────────────────


def test_registrable_keeps_a_cookie_in_its_family():
    assert registrable("www.amazon.com") == "amazon.com"
    assert registrable("amazon.in") == "amazon.in"
    # The two-part public suffixes, so example.co.uk does not become co.uk and
    # then sweep up every .co.uk site.
    assert registrable("shop.example.co.uk") == "example.co.uk"
    assert registrable("") == ""


def test_cookie_for_a_parent_domain_matches_the_host():
    assert _domain_matches(".amazon.com", "www.amazon.com")
    assert _domain_matches("amazon.com", "amazon.com")
    assert _domain_matches(".AMAZON.COM", "www.amazon.com")


def test_cookie_for_amazon_does_not_match_notamazon():
    """The case a bare endswith gets wrong, which is the case that matters."""
    assert not _domain_matches(".amazon.com", "notamazon.com")
    assert not _domain_matches("amazon.com", "notamazon.com")


def test_look_alike_tld_is_not_a_parent_domain():
    """notamazon.in is a different site from amazon.in, not a subdomain."""
    assert not _domain_matches("notamazon.in", "amazon.in")
    assert not _domain_matches("amazon.in", "notamazon.in")


def test_cookie_for_a_child_domain_does_not_match_the_parent():
    """A cookie minted for shop.* must not ride along on the bare parent."""
    assert not _domain_matches("shop.www.amazon.com", "www.amazon.com")
    assert _domain_matches("shop.www.amazon.com", "checkout.shop.www.amazon.com")


def test_empty_domain_or_host_never_matches():
    assert not _domain_matches("", "amazon.com")
    assert not _domain_matches(".amazon.com", "")


def test_a_single_label_cookie_domain_is_not_a_parent_domain():
    """A domain with no dot is a host, never a suffix.

    "com" is not a parent of example.com. A suffix rule would sweep such a
    cookie out of the jar and onto every site under that label.
    """
    assert not _domain_matches("com", "example.com")
    assert not _domain_matches(".com", "shop.example.com")
    # An exact match is still a match, which is what a single-label host needs.
    assert _domain_matches("localhost", "localhost")


def test_filter_for_host_keeps_only_cookies_this_host_would_receive():
    records = [
        CookieRecord("sid", "v1", ".amazon.com"),
        CookieRecord("csrf", "v2", "www.amazon.com"),
        CookieRecord("nope", "v3", "notamazon.com"),
        CookieRecord("other", "v4", "example.org"),
        CookieRecord("deeper", "v5", "shop.www.amazon.com"),
    ]
    kept = filter_for_host(records, "www.amazon.com")
    assert [c.name for c in kept] == ["sid", "csrf"]
    assert filter_for_host(records, "example.org")[0].name == "other"
    assert filter_for_host(records, "notamazon.com")[0].name == "nope"
    # A deeper host receives both parent-domain cookies plus its own exact
    # match. Nothing narrower than the host ever comes back.
    assert [c.name for c in filter_for_host(records, "shop.www.amazon.com")] == [
        "sid",
        "csrf",
        "deeper",
    ]


def test_host_property_drops_the_leading_dot():
    assert CookieRecord("a", "b", ".Amazon.COM").host == "amazon.com"
    assert CookieRecord("a", "b", "amazon.com").host == "amazon.com"


# ── 2. header rendering ────────────────────────────────────────────────────


def test_build_header_renders_pairs_in_order():
    records = [
        CookieRecord("sid", "abc123", ".amazon.com", secure=True, http_only=True),
        CookieRecord("csrf", "tok", "www.amazon.com"),
        CookieRecord("empty", "", "www.amazon.com"),
    ]
    assert build_header(records) == "sid=abc123; csrf=tok; empty="
    assert build_header([]) == ""


# ── 3. the browser registry ────────────────────────────────────────────────


@pytest.mark.parametrize("browser", FIREFOX_FAMILY)
def test_family_of_known_firefox_browsers(browser):
    assert family_of(browser) == "firefox"


@pytest.mark.parametrize("browser", CHROMIUM_FAMILY)
def test_family_of_known_chromium_browsers(browser):
    assert family_of(browser) == "chromium"


def test_family_of_is_case_and_whitespace_insensitive():
    assert family_of("Zen") == "firefox"
    assert family_of("  FIREFOX  ") == "firefox"
    assert family_of("CHROME") == "chromium"
    assert family_of("Edge") == "chromium"


def test_family_of_unknown_browser_lists_what_is_supported():
    with pytest.raises(ValueError) as exc:
        family_of("netscape")
    message = str(exc.value)
    assert "netscape" in message
    for browser in ALL_BROWSERS:
        assert browser in message, f"the error should offer {browser}"
    # No overlap between the two registries, or a browser would resolve two ways.
    assert not set(FIREFOX_FAMILY) & set(CHROMIUM_FAMILY)


# ── 4. owned store round-trip ──────────────────────────────────────────────


def _amazon_cookies():
    return [
        CookieRecord("sid", "abc123", ".amazon.com", secure=True, http_only=True),
        CookieRecord("csrf", "tok", "www.amazon.com"),
    ]


def test_owned_store_round_trip(tmp_home):
    saved = save_owned_site("https://www.amazon.com", _amazon_cookies(), browser="zen")
    assert saved == 2

    src = read_owned_site("https://www.amazon.com")
    assert src.family == "owned"
    assert src.via == "owned store"
    assert src.count == 2
    assert src.names == ["csrf", "sid"]
    assert build_header(src.cookies) == "sid=abc123; csrf=tok"
    by_name = {c.name: c for c in src.cookies}
    assert by_name["sid"].domain == ".amazon.com"
    assert by_name["sid"].secure is True
    assert by_name["sid"].http_only is True
    assert by_name["csrf"].secure is False
    assert by_name["csrf"].path == "/"


def test_saving_one_site_does_not_clobber_another(tmp_home):
    save_owned_site("https://www.amazon.com", _amazon_cookies())
    save_owned_site(
        "https://github.com",
        [CookieRecord("user_session", "gh-value", "github.com")],
    )

    store = json.loads(Path(owned_store_path()).read_text(encoding="utf-8"))
    assert set(store) == {"www.amazon.com", "github.com"}, (
        "the store is a map keyed by host; saving one site must not rewrite the rest"
    )
    assert read_owned_site("https://www.amazon.com").count == 2
    assert read_owned_site("https://github.com").cookies[0].value == "gh-value"


def test_store_saves_only_the_cookies_that_match_the_site(tmp_home):
    """A stray cookie in the list must not be persisted for the site."""
    mixed = _amazon_cookies() + [CookieRecord("stowaway", "leak", "example.org")]
    assert save_owned_site("https://www.amazon.com", mixed) == 2
    store = json.loads(Path(owned_store_path()).read_text(encoding="utf-8"))
    names = [c["n"] for c in store["www.amazon.com"]["cookies"]]
    assert names == ["sid", "csrf"]


def test_site_spellings_resolve_to_one_store_key(tmp_home):
    """Save with a bare hostname, read with a full URL: same key, same cookies."""
    save_owned_site("example.com", [CookieRecord("sid", "v", "example.com")])
    assert read_owned_site("https://example.com/some/path?q=1").cookies[0].value == "v"
    assert read_owned_site("EXAMPLE.COM").cookies[0].value == "v"
    assert set(json.loads(Path(owned_store_path()).read_text(encoding="utf-8"))) == {
        "example.com"
    }


def test_owned_store_path_is_under_the_home_it_was_given(tmp_home):
    path = Path(owned_store_path())
    assert path == tmp_home / ".searchts" / "cookies" / "owned.json"
    assert not path.exists(), "naming the path must not create it"
    assert save_owned_site("example.com", [CookieRecord("sid", "v", "example.com")]) == 1
    assert path.is_file()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX perm semantics only")
def test_owned_store_is_owner_only(tmp_home):
    save_owned_site("example.com", [CookieRecord("sid", "v", "example.com")])
    path = Path(owned_store_path())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    # The staging file must not survive the atomic replace.
    assert not path.with_name(path.name + ".tmp").exists()


def test_reading_an_empty_store_does_not_create_it(tmp_home):
    with pytest.raises(CookieReadError):
        read_owned_site("https://example.com")
    assert not Path(owned_store_path()).exists()


# ── 5. save refuses what it cannot scope ───────────────────────────────────


def test_save_refuses_when_no_cookie_matches_the_host(tmp_home):
    with pytest.raises(CookieReadError) as exc:
        save_owned_site(
            "https://target.example",
            [CookieRecord("sid", "v", "other.example")],
        )
    assert "target.example" in str(exc.value)
    assert not Path(owned_store_path()).exists(), "a refusal must not leave a store"


def test_save_refuses_an_empty_list(tmp_home):
    with pytest.raises(CookieReadError):
        save_owned_site("https://example.com", [])


# ── 6. unknown sites ───────────────────────────────────────────────────────


def test_read_owned_site_unknown_site_raises(tmp_home):
    save_owned_site("https://www.amazon.com", _amazon_cookies())
    with pytest.raises(CookieReadError) as exc:
        read_owned_site("https://www.elsewhere.com")
    assert "www.elsewhere.com" in str(exc.value)


# ── 7. the Firefox-family reader against a real sqlite file ────────────────

# Two cookies for the target site, three that must not come back.
_ROWS = (
    ("sid", "target-value-1", ".amazon.com", "/", 1, 1),
    ("csrf", "target-value-2", "www.amazon.com", "/", 1, 0),
    ("decoy-suffix", "decoy-value-1", "notamazon.com", "/", 1, 0),
    ("decoy-other-site", "decoy-value-2", "example.org", "/", 0, 0),
    ("decoy-child", "decoy-value-3", "shop.www.amazon.com", "/", 0, 0),
)


def test_read_firefox_family_returns_only_the_targets_cookies(tmp_home):
    _fake_firefox_profile(tmp_home, "zen", _ROWS)
    src = read_firefox_family("zen", "https://www.amazon.com")

    assert src.browser == "zen"
    assert src.family == "firefox"
    assert src.via == "browser"
    assert src.count == 2
    assert src.names == ["csrf", "sid"]
    values = [c.value for c in src.cookies]
    assert values == ["target-value-1", "target-value-2"]
    for name in ("decoy-suffix", "decoy-other-site", "decoy-child"):
        assert name not in src.names, f"{name} is not this site's cookie"
    by_name = {c.name: c for c in src.cookies}
    assert by_name["sid"].domain == ".amazon.com"
    assert by_name["sid"].secure is True
    assert by_name["sid"].http_only is True
    assert by_name["csrf"].secure is True
    assert by_name["csrf"].http_only is False
    assert by_name["csrf"].path == "/"


def test_read_firefox_family_matches_a_bare_hostname(tmp_home):
    _fake_firefox_profile(tmp_home, "zen", _ROWS)
    assert read_firefox_family("zen", "www.amazon.com").count == 2


def test_read_firefox_family_does_not_write_to_the_profile(tmp_home):
    """A browser profile is not searchts' to change, so assert it did not change.

    Two things are checked: the database's bytes, and the set of files sitting
    next to it. Verified against two mutations of _open_ro, one that dirties a
    page and one that flips the profile to WAL; both fail this test.

    What it cannot distinguish is a read-write connect that only reads, which
    is observationally identical to mode=ro here. The fixture is deliberately in
    the default journal mode: in WAL mode SQLite writes a -shm index even for a
    read-only connection, so the second assertion would fire on correct code.
    """
    dbs = _fake_firefox_profile(tmp_home, "zen", _ROWS)
    before = {db: _digest(db) for db in dbs}
    listing_before = {db.parent: sorted(p.name for p in db.parent.iterdir()) for db in dbs}

    read_firefox_family("zen", "https://www.amazon.com")

    for db, digest in before.items():
        assert _digest(db) == digest, f"reading changed {db}"
        # A plain connect() on a live WAL database creates these and
        # checkpoints, which is a write to someone's browser profile.
        assert sorted(p.name for p in db.parent.iterdir()) == listing_before[db.parent]


def test_read_firefox_family_says_so_when_the_site_is_not_logged_in(tmp_home):
    _fake_firefox_profile(tmp_home, "zen", _ROWS)
    with pytest.raises(CookieReadError) as exc:
        read_firefox_family("zen", "https://www.nytimes.com")
    message = str(exc.value)
    assert "www.nytimes.com" in message
    assert "zen" in message


def test_read_firefox_family_reports_a_missing_profile(tmp_home):
    with pytest.raises(CookieReadError) as exc:
        read_firefox_family("firefox", "https://example.com")
    assert "firefox" in str(exc.value)


def test_every_profile_root_points_inside_the_tmp_home(tmp_home):
    """The hermeticity guard for this whole file.

    If the fixture ever stopped redirecting a variable the module reads, the
    tests above would quietly start reading the developer's real browser
    profile instead of failing. Build the profiles first, so the root lists are
    non-empty and the assertion below cannot pass by finding nothing at all.
    """
    _fake_firefox_profile(tmp_home, "zen", _ROWS)
    _fake_firefox_profile(tmp_home, "firefox", _ROWS)
    for browser in ("zen", "firefox"):
        roots = sc._firefox_profile_roots(browser)
        assert roots, f"{browser} should resolve at least one root here"
        for root in roots:
            assert str(tmp_home) in root, f"{browser} would search {root}"
    assert Path(owned_store_path()).is_relative_to(tmp_home)


def test_read_firefox_family_reads_firefox_too(tmp_home):
    """The registry maps several names to one family; the reader must follow it."""
    _fake_firefox_profile(tmp_home, "firefox", _ROWS)
    assert read_firefox_family("firefox", "https://www.amazon.com").count == 2


# ── for_site: which source wins, and what it refuses ───────────────────────


def test_for_site_prefers_the_owned_store(tmp_home):
    save_owned_site("https://www.amazon.com", _amazon_cookies())
    src = for_site("https://www.amazon.com", browser="zen")
    assert src.family == "owned"
    assert src.count == 2


def test_for_site_without_a_browser_says_what_to_pass(tmp_home):
    with pytest.raises(CookieReadError) as exc:
        for_site("https://www.amazon.com")
    message = str(exc.value)
    assert "--cookies-from-browser" in message


def test_for_site_refuses_chromium_and_names_the_alternative(tmp_home):
    """A Chromium browser is refused off disk, and the message says what works.

    The *reason* is platform-specific and the old test hard-coded the Windows
    one. App-Bound Encryption is a Windows-only wrapper (Chrome 127+); on macOS
    and Linux the key lives in the system keyring instead, so a message naming
    App-Bound Encryption there was simply false. What is true everywhere, and
    what the caller can act on, is the last sentence: open a debugger port.
    """
    import os

    with pytest.raises(CookieReadError) as exc:
        for_site("https://www.amazon.com", browser="chrome")
    message = str(exc.value)
    assert "--cdp-port" in message, "must name the path that does work"
    assert "keyring" in message or "App-Bound Encryption" in message, (
        "must say why the values are unreadable on this platform"
    )
    if os.name != "nt":
        assert "App-Bound Encryption" not in message, (
            "App-Bound Encryption is Windows-only; saying it here is a lie"
        )


def test_chromium_locked_message_does_not_name_a_cookie_value():
    from searchts.session_cookies import chromium_locked_message

    message = chromium_locked_message("chrome")
    assert "--cdp-port" in message and "9222" in message


def test_the_locked_message_still_names_something_when_the_browser_is_empty():
    """An empty name produced "''s cookies are locked".

    That is the sentence a user reads at the exact moment they have least idea
    what to do, so it has to survive a missing or blank browser name.
    """
    from searchts.session_cookies import chromium_locked_message

    for given in ("", "   "):
        message = chromium_locked_message(given)
        assert not message.startswith("'"), message
        assert "'s cookies are locked" in message
        assert "--cdp-port" in message


def test_describe_never_prints_a_cookie_value(tmp_home):
    """The one line safe for a human: a count and a site, never a value."""
    save_owned_site("https://www.amazon.com", _amazon_cookies(), browser="zen")
    owned = read_owned_site("https://www.amazon.com").describe()
    assert "2 cookies" in owned
    assert "www.amazon.com" in owned
    for secret in ("abc123", "tok"):
        assert secret not in owned

    _fake_firefox_profile(tmp_home, "zen", _ROWS)
    from_browser = read_firefox_family("zen", "https://www.amazon.com").describe()
    assert "zen" in from_browser
    for secret in ("target-value-1", "target-value-2"):
        assert secret not in from_browser
