# -*- coding: utf-8 -*-
"""Browser detection, cookie presence, and the login-wall offer.

Every profile here is a fixture directory and every cookie database is a fake
SQLite file. Nothing opens a real browser profile, no socket is dialled, and
no request leaves the machine.
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

from searchts import browser_detect as bd
from searchts import browser_settings as bs
from searchts import cli
from searchts import login_wall as lw
from searchts.unlocker import UnlockerError

# ── fixture profiles ────────────────────────────────────────────────────────


def chromium_db(path: Path, hosts) -> Path:
    """A Chromium-shaped cookie DB. Only ``host_key`` is ever queried."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    try:
        con.execute(
            "CREATE TABLE cookies ("
            "host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB)"
        )
        con.executemany(
            "INSERT INTO cookies (host_key, name, value, encrypted_value) "
            "VALUES (?, 'sid', '', ?)",
            [(host, b"NOT-DECRYPTED") for host in hosts],
        )
        con.commit()
    finally:
        con.close()
    return path


def firefox_db(path: Path, hosts) -> Path:
    """A Firefox-shaped cookie DB with no value column at all.

    If the presence scan ever selected a value/encrypted column, this fixture
    would fail rather than quietly decrypt something.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    try:
        con.execute("CREATE TABLE moz_cookies (host TEXT, name TEXT)")
        con.executemany(
            "INSERT INTO moz_cookies (host, name) VALUES (?, 'sid')",
            [(host,) for host in hosts],
        )
        con.commit()
    finally:
        con.close()
    return path


def linux_env(home: Path) -> dict:
    return {"HOME": str(home)}


def macos_env(home: Path) -> dict:
    return {"HOME": str(home)}


def windows_env(home: Path) -> dict:
    return {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "APPDATA": str(home / "AppData" / "Roaming"),
        "PROGRAMFILES": str(home / "Program Files"),
    }


def detect(tmp_path, platform, env):
    return bd._detect_browsers(
        platform=platform,
        env=env,
        executable_finder=lambda _name: "",
        is_running=lambda _profile: False,
        probe=lambda _port: False,
    )


def browser_named(browsers, name):
    return next(b for b in browsers if b.name == name)


# ── detection: one layout per platform ─────────────────────────────────────


def test_chromium_profiles_linux_layout(tmp_path):
    home = tmp_path / "home"
    chromium_db(
        home / ".config" / "google-chrome" / "Default" / "Network" / "Cookies",
        [".example.com"],
    )
    chromium_db(
        home / ".config" / "vivaldi" / "Profile 1" / "Cookies",
        [".example.org"],
    )
    browsers = detect(tmp_path, "linux", linux_env(home))

    chrome = browser_named(browsers, "chrome")
    assert chrome.user_data == str(home / ".config" / "google-chrome")
    assert [Path(p.path).name for p in chrome.profiles] == ["Default"]
    assert chrome.profiles[0].has_cookies
    assert Path(chrome.profiles[0].cookie_db).name == "Cookies"

    vivaldi = browser_named(browsers, "vivaldi")
    assert vivaldi.profiles[0].has_cookies
    assert Path(vivaldi.profiles[0].cookie_db).name == "Cookies"


def test_chromium_profiles_macos_layout(tmp_path):
    home = tmp_path / "home"
    chromium_db(
        home / "Library" / "Application Support" / "Google" / "Chrome"
        / "Default" / "Network" / "Cookies",
        [".example.com"],
    )
    browsers = detect(tmp_path, "macos", macos_env(home))
    chrome = browser_named(browsers, "chrome")
    assert chrome.user_data == str(
        home / "Library" / "Application Support" / "Google" / "Chrome"
    )
    assert chrome.profiles[0].has_cookies


def test_chromium_profiles_windows_layout(tmp_path):
    home = tmp_path / "home"
    env = windows_env(home)
    chromium_db(
        Path(env["LOCALAPPDATA"]) / "Microsoft" / "Edge" / "User Data"
        / "Default" / "Network" / "Cookies",
        [".example.com"],
    )
    browsers = detect(tmp_path, "windows", env)
    edge = browser_named(browsers, "edge")
    assert edge.user_data == str(
        Path(env["LOCALAPPDATA"]) / "Microsoft" / "Edge" / "User Data"
    )
    assert edge.profiles[0].has_cookies


def test_firefox_family_profiles_follow_each_platform(tmp_path):
    home = tmp_path / "home"
    firefox_db(
        home / ".mozilla" / "firefox" / "abc.default-release" / "cookies.sqlite",
        [".example.com"],
    )
    firefox_db(
        home / ".zen" / "xyz.Default (release)" / "cookies.sqlite",
        [".example.org"],
    )
    browsers = detect(tmp_path, "linux", linux_env(home))

    firefox = browser_named(browsers, "firefox")
    assert Path(firefox.profiles[0].path).name == "abc.default-release"
    assert firefox.profiles[0].has_cookies
    zen = browser_named(browsers, "zen")
    assert zen.profiles and zen.profiles[0].has_cookies

    # The same fixture home under a Windows layout finds the APPDATA profile.
    win = windows_env(home)
    firefox_db(
        Path(win["APPDATA"]) / "Mozilla" / "Firefox" / "Profiles" / "win.default"
        / "cookies.sqlite",
        [".example.com"],
    )
    found = detect(tmp_path, "windows", win)
    names = sorted(p.path for p in browser_named(found, "firefox").profiles)
    assert any("win.default" in path for path in names)


def test_running_and_debugging_are_marked(tmp_path):
    home = tmp_path / "home"
    root = home / ".config" / "google-chrome"
    chromium_db(root / "Default" / "Network" / "Cookies", [".example.com"])
    (root / "DevToolsActivePort").write_text(
        "9333\n/devtools/browser/abc\n", encoding="utf-8"
    )
    browsers = bd._detect_browsers(
        platform="linux",
        env=linux_env(home),
        executable_finder=lambda _name: "",
        is_running=lambda profile: profile == str(root),
        probe=lambda port: port == 9333,
    )
    chrome = browser_named(browsers, "chrome")
    assert chrome.running is True
    assert chrome.debugging is True
    assert chrome.debug_port == 9333

    report = bd.format_report(browsers)
    assert "Chrome (chromium): running, remote debugging on (port 9333)" in report
    assert "profile:" in report


def test_a_stale_port_file_without_a_listener_is_not_debugging(tmp_path):
    home = tmp_path / "home"
    root = home / ".config" / "vivaldi"
    chromium_db(root / "Default" / "Network" / "Cookies", [".example.com"])
    (root / "DevToolsActivePort").write_text("9222\n", encoding="utf-8")
    browsers = bd._detect_browsers(
        platform="linux",
        env=linux_env(home),
        executable_finder=lambda _name: "",
        is_running=lambda _profile: True,
        probe=lambda _port: False,
    )
    vivaldi = browser_named(browsers, "vivaldi")
    assert vivaldi.running is True
    assert vivaldi.debugging is False


# ── presence: exists or not, never a value ─────────────────────────────────


def test_presence_is_per_registrable_domain(tmp_path):
    home = tmp_path / "home"
    chromium_db(
        home / ".config" / "google-chrome" / "Default" / "Network" / "Cookies",
        ["www.example.com", ".other.example.org"],
    )
    firefox_db(
        home / ".mozilla" / "firefox" / "p.default" / "cookies.sqlite",
        [".shop.example.co.uk"],
    )
    browsers = detect(tmp_path, "linux", linux_env(home))

    chrome_found = bd.cookie_presence(
        "https://app.example.com/private", browsers=browsers
    )
    assert [(p.browser, p.found) for p in chrome_found] == [("chrome", True)]

    uk_found = bd.cookie_presence(
        "https://shop.example.co.uk/cart", browsers=browsers
    )
    assert [(p.browser, p.found) for p in uk_found] == [("firefox", True)]

    nothing = bd.cookie_presence("https://unrelated.test/", browsers=browsers)
    assert nothing == []


def test_presence_does_not_need_a_value_column(tmp_path):
    """The Firefox fixture has no value column: selecting one would raise."""
    home = tmp_path / "home"
    firefox_db(
        home / ".mozilla" / "firefox" / "p.default" / "cookies.sqlite",
        [".example.com"],
    )
    browsers = detect(tmp_path, "linux", linux_env(home))
    found = bd.cookie_presence("https://example.com/", browsers=browsers)
    assert [p.browser for p in found] == ["firefox"]


def test_a_locked_database_is_copied_and_read(tmp_path):
    home = tmp_path / "home"
    db = chromium_db(
        home / ".config" / "google-chrome" / "Default" / "Network" / "Cookies",
        [".example.com"],
    )
    browsers = detect(tmp_path, "linux", linux_env(home))

    blocker = sqlite3.connect(str(db))
    try:
        blocker.execute("BEGIN EXCLUSIVE")
        found = bd.cookie_presence("https://example.com/", browsers=browsers)
    finally:
        blocker.rollback()
        blocker.close()

    assert [p.browser for p in found] == ["chrome"]
    assert found[0].found is True


def test_an_unreadable_database_is_named_not_guessed(tmp_path):
    home = tmp_path / "home"
    db = home / ".config" / "google-chrome" / "Default" / "Network" / "Cookies"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"this is not a SQLite database")
    browsers = detect(tmp_path, "linux", linux_env(home))

    found = bd.cookie_presence("https://example.com/", browsers=browsers)
    assert found and found[0].found is False
    assert "cookie database" in found[0].skipped


# ── settings: new names first, legacy aliases second ───────────────────────


def test_new_names_win_over_the_legacy_aliases(monkeypatch):
    monkeypatch.setenv(bs.BROWSER_ENV, "/usr/bin/vivaldi")
    monkeypatch.setenv(bs.LEGACY_BROWSER_ENV, "/usr/bin/google-chrome")
    monkeypatch.setenv(bs.PROFILE_ENV, "/profiles/new")
    monkeypatch.setenv(bs.LEGACY_PROFILE_ENV, "/profiles/old")

    assert bs.browser_executable() == "/usr/bin/vivaldi"
    assert bs.browser_profile() == "/profiles/new"
    assert bs.setting_source("browser") == bs.BROWSER_ENV
    assert bs.setting_source("profile") == bs.PROFILE_ENV


def test_legacy_names_apply_only_when_the_new_ones_are_unset(monkeypatch):
    monkeypatch.delenv(bs.BROWSER_ENV, raising=False)
    monkeypatch.delenv(bs.PROFILE_ENV, raising=False)
    monkeypatch.setenv(bs.LEGACY_BROWSER_ENV, "/usr/bin/google-chrome")
    monkeypatch.setenv(bs.LEGACY_PROFILE_ENV, "/profiles/old")

    assert bs.browser_executable() == "/usr/bin/google-chrome"
    assert bs.browser_profile() == "/profiles/old"
    assert bs.setting_source("browser") == bs.LEGACY_BROWSER_ENV


def test_the_settings_are_per_setting_and_expand_a_home(monkeypatch, tmp_path):
    monkeypatch.setattr(bd, "executable_for", lambda _name: "")
    monkeypatch.setenv(bs.BROWSER_ENV, "vivaldi")
    monkeypatch.delenv(bs.LEGACY_BROWSER_ENV, raising=False)
    monkeypatch.setenv(bs.LEGACY_PROFILE_ENV, "~/profile")
    monkeypatch.delenv(bs.PROFILE_ENV, raising=False)

    assert bs.browser_raw() == "vivaldi"
    assert bs.browser_executable() == "vivaldi"  # unresolved name is kept
    assert bs.browser_profile() == os.path.expanduser("~/profile")


# ── the login-wall offer ───────────────────────────────────────────────────


def _presence(browser, found=True):
    return bd.Presence(
        browser=browser,
        family="chromium" if browser != "firefox" else "firefox",
        profile=f"/profiles/{browser}",
        found=found,
    )


def test_non_interactive_prints_the_exact_command_and_copies_nothing():
    calls = []
    offer = lw.offer_login_copy(
        "https://app.example.com/private",
        interactive=False,
        scan=lambda _site: [_presence("chrome")],
        copy=lambda site, browser: calls.append((site, browser)) or "kept",
    )
    assert offer.kind == "commands"
    assert offer.copied is False
    assert calls == []
    assert offer.commands == (
        "searchts login keep example.com --cookies-from-browser chrome --yes",
    )
    assert (
        "searchts login keep example.com --cookies-from-browser chrome --yes"
        in offer.full_text
    )
    assert "Nothing was copied; the scan only checked whether a cookie exists." in offer.text


def test_json_mode_never_prompts_or_copies():
    class _Tty(io.StringIO):
        def isatty(self):
            return True

    offer = lw.offer_login_copy(
        "https://example.com/",
        json_mode=True,
        stdin=_Tty("1\ny\n"),
        scan=lambda _site: [_presence("chrome")],
        copy=lambda _site, _browser: pytest.fail("copy must not run"),
    )
    assert offer.kind == "commands"
    assert offer.copied is False


def test_interactive_copies_only_after_an_explicit_yes():
    calls = []
    stdin = io.StringIO("1\ny\n")
    stderr = io.StringIO()
    offer = lw.offer_login_copy(
        "https://example.com/",
        interactive=True,
        stdin=stdin,
        stderr=stderr,
        scan=lambda _site: [_presence("chrome"), _presence("firefox")],
        copy=lambda site, browser: calls.append((site, browser)) or "kept example.com",
    )
    assert offer.kind == "copied"
    assert offer.copied is True
    assert offer.copied_from == "chrome"
    assert calls == [("example.com", "chrome")]
    assert "1) Chrome" in stderr.getvalue()
    assert "2) Firefox" in stderr.getvalue()
    assert "keep them? [y/N]" in stderr.getvalue()


def test_interactive_no_copies_nothing():
    calls = []
    offer = lw.offer_login_copy(
        "https://example.com/",
        interactive=True,
        stdin=io.StringIO("1\nn\n"),
        stderr=io.StringIO(),
        scan=lambda _site: [_presence("chrome")],
        copy=lambda site, browser: calls.append((site, browser)) or "kept",
    )
    assert offer.kind == "skipped"
    assert calls == []


def test_enter_at_the_browser_prompt_skips():
    calls = []
    offer = lw.offer_login_copy(
        "https://example.com/",
        interactive=True,
        stdin=io.StringIO("\n"),
        stderr=io.StringIO(),
        scan=lambda _site: [_presence("chrome")],
        copy=lambda site, browser: calls.append((site, browser)) or "kept",
    )
    assert offer.kind == "skipped"
    assert calls == []


def test_a_copy_failure_keeps_the_reason_and_does_not_claim_success():
    def _fail(_site, _browser):
        raise RuntimeError("nope")

    offer = lw.offer_login_copy(
        "https://example.com/",
        interactive=True,
        stdin=io.StringIO("1\ny\n"),
        stderr=io.StringIO(),
        scan=lambda _site: [_presence("chrome")],
        copy=_fail,
    )
    assert offer.kind == "copy_failed"
    assert offer.copied is False
    assert "could not copy" in offer.text


def test_no_presence_means_no_offer():
    offer = lw.offer_login_copy(
        "https://example.com/",
        interactive=False,
        scan=lambda _site: [],
    )
    assert offer.kind == "none"
    assert offer.text == ""


def test_linkedin_is_excluded_from_the_scan_and_points_at_attach():
    def _must_not_scan(_site):
        pytest.fail("LinkedIn must never be scanned for cookies")

    offer = lw.offer_login_copy(
        "https://www.linkedin.com/feed/",
        interactive=True,
        stdin=io.StringIO("1\ny\n"),
        stderr=io.StringIO(),
        scan=_must_not_scan,
    )
    assert offer.kind == "linkedin"
    assert "SEARCHTS_LINKEDIN_ATTACH" in offer.text
    assert "://inspect/#remote-debugging" in offer.text
    assert "Allow remote debugging for this browser instance" in offer.text


# ── the read CLI wiring ────────────────────────────────────────────────────


def _login_wall(monkeypatch, presences):
    def _fetch(url, **_kwargs):
        raise UnlockerError(url, [("curl_cffi", "login-wall")])

    monkeypatch.setattr("searchts.unlocker.fetch", _fetch)
    monkeypatch.setattr(bd, "cookie_presence", lambda _site: presences)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)


def test_a_read_wall_prints_the_keep_command_unwrapped(capsys, monkeypatch):
    _login_wall(monkeypatch, [_presence("chrome")])
    monkeypatch.setattr(sys, "argv", ["searchts", "read", "https://app.example.com/private"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    err = capsys.readouterr().err
    command = "searchts login keep example.com --cookies-from-browser chrome --yes"
    # The receipt folds its detail at its own width; the command is printed
    # again whole, so a copy is one line and never two.
    assert command in err
    assert any(line == command for line in err.splitlines())


def test_a_read_wall_json_carries_the_exact_command(capsys, monkeypatch):
    _login_wall(monkeypatch, [_presence("chrome")])
    monkeypatch.setattr(
        sys, "argv", ["searchts", "read", "https://app.example.com/private", "--json"]
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    command = "searchts login keep example.com --cookies-from-browser chrome --yes"
    assert payload["error"]["kind"] == "login_wall"
    assert command in payload["error"]["login"]
