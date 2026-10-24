"""Expiry, sweep, check, consent and the receipts that make them honest.

These cover the states in #430: a cookie that dies, a site whose last cookie
died, a login that can be refreshed only after a recorded yes, and a check that
refuses to call a public page "logged in". No test opens a browser or a socket:
the direct fetch is a stub, and every store lives under a throwaway HOME.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from searchts import cli
from searchts import login_store as ls
from searchts.session_cookies import (
    CookieReadError,
    CookieRecord,
    CookieSource,
    _write_owned_store,
    describe_expiry,
    filter_for_host,
    normalize_expiry,
    read_owned_site,
    read_owned_store,
    save_owned_site,
    sweep_owned_store,
)
from searchts.unlocker import FetchResult, UnlockerError


@pytest.fixture(autouse=True)
def temp_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(home))
    yield home


def rec(name="sid", value="SECRET-VALUE", domain="example.com", expiry=None):
    return CookieRecord(name=name, value=value, domain=domain, expiry=expiry)


def entry_cookie(expiry=None, value="SECRET-VALUE", domain="example.com"):
    return {
        "n": "sid",
        "v": value,
        "d": domain,
        "p": "/",
        "s": True,
        "h": False,
        "expiry": expiry,
    }


def seed(
    host="example.com",
    cookies=None,
    *,
    browser="firefox",
    consent=True,
    expiry_known=True,
    legacy=False,
):
    cookie = entry_cookie()
    if legacy:
        cookie.pop("expiry")
    _write_owned_store(
        {
            host: {
                "cookies": cookies if cookies is not None else [cookie],
                "browser": browser,
                "expiry_known": expiry_known,
                "consent": consent,
            }
        }
    )
    return host


def run(argv, capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["searchts", *argv])
    try:
        rc = cli.main()
    except SystemExit as e:
        rc = e.code
    out = capsys.readouterr()
    return rc, out.out, out.err


# ── the expiry model ───────────────────────────────────────────────────────


def test_normalize_expiry_turns_milliseconds_into_seconds_and_keeps_none():
    assert normalize_expiry(None) is None
    assert normalize_expiry(0) is None
    assert normalize_expiry(-1) is None
    assert normalize_expiry(1_700_000_000) == 1_700_000_000
    assert normalize_expiry(1_700_000_000_000) == 1_700_000_000


def test_filter_for_host_drops_expired_and_keeps_session_and_live():
    now = int(time.time())
    records = [
        rec("dead", expiry=now - 60),
        rec("live", expiry=now + 3600),
        rec("session", expiry=None),
    ]
    out = filter_for_host(records, "example.com")
    assert {c.name for c in out} == {"live", "session"}


# ── save and read ──────────────────────────────────────────────────────────


def test_saved_cookie_keeps_its_expiry_and_a_session_cookie_is_not_guessed():
    now = int(time.time())
    save_owned_site("example.com", [rec("live", expiry=now + 3600), rec("session")])
    source = read_owned_site("example.com")
    assert source.count == 2
    assert source.expiry_known is True
    assert source.expires_at == now + 3600
    assert source.browser == ""


def test_legacy_entry_without_expiry_still_loads_and_is_unknown():
    seed(expiry_known=False, legacy=True)
    source = read_owned_site("example.com")
    assert source.count == 1
    assert source.expires_at is None
    assert source.expiry_known is False


def test_all_cookies_expired_says_so_and_names_login_signin():
    now = int(time.time())
    seed(cookies=[entry_cookie(now - 1)])
    with pytest.raises(CookieReadError) as e:
        read_owned_site("example.com")
    assert "expired" in str(e.value)
    assert "login signin" in str(e.value)


def test_describe_expiry_says_days_hours_session_unknown_and_expired():
    now = int(time.time())
    assert describe_expiry({"cookies": [entry_cookie(now + 2 * 86400)]}, now) == "expires in 2 days"
    assert describe_expiry({"cookies": [entry_cookie(now + 3 * 3600)]}, now) == "expires in 3 hours"
    assert (
        describe_expiry({"cookies": [entry_cookie(None)], "expiry_known": True}, now) == "session"
    )
    legacy = entry_cookie(None)
    legacy.pop("expiry")
    assert describe_expiry({"cookies": [legacy], "expiry_known": False}, now) == "unknown"
    assert describe_expiry({"expired": True}, now) == "expired"


# ── list and sweep ─────────────────────────────────────────────────────────


def test_list_kept_adds_expiry_fields_without_dropping_the_old_ones():
    now = int(time.time())
    seed(cookies=[entry_cookie(now + 3600)])
    info = ls.list_kept()["example.com"]
    assert info["cookies"] == 1
    assert info["browser"] == "firefox"
    assert info["expiry_known"] is True
    assert info["expires_at"] == now + 3600
    assert info["expired"] is False


def test_sweep_deletes_expired_cookies_and_marks_the_site():
    now = int(time.time())
    seed(cookies=[entry_cookie(now - 1), entry_cookie(now + 3600)])
    result = sweep_owned_store(now=now)
    assert result.removed == 1
    assert result.actions[0]["action"] == "deleted"
    assert result.actions[0]["reason"] == "expired"
    store = read_owned_store()
    assert len(store["example.com"]["cookies"]) == 1
    assert store["example.com"].get("expired") is None


def test_sweep_marks_a_site_whose_last_cookie_died():
    now = int(time.time())
    seed(cookies=[entry_cookie(now - 1)], browser="")
    result = sweep_owned_store(now=now)
    assert result.removed == 1
    assert result.expired_sites == 1
    assert read_owned_store()["example.com"]["expired"] is True
    assert read_owned_store()["example.com"]["cookies"] == []


def test_sweep_never_touches_session_or_live_cookies():
    now = int(time.time())
    seed(cookies=[entry_cookie(None), entry_cookie(now + 60)])
    before = read_owned_store()
    result = sweep_owned_store(now=now)
    assert result.removed == 0
    assert read_owned_store() == before


def test_sweep_does_not_create_a_store_or_daemon():
    assert sweep_owned_store().removed == 0
    assert read_owned_store() == {}


# ── consent ────────────────────────────────────────────────────────────────


def test_a_browser_keep_records_consent_and_a_signin_keep_does_not():
    ls.keep("example.com", [rec()], browser="firefox")
    assert ls.site_consent("example.com") is True
    ls.keep("other.com", [rec(domain="other.com")], browser="")
    assert ls.site_consent("other.com") is False


def test_legacy_entry_without_consent_is_not_a_silent_yes():
    seed(consent=False)
    allowed, why = ls.consent_for_auto("example.com", "firefox", interactive=False)
    assert allowed is False
    assert "no consent" in why


def test_recorded_consent_allows_one_automatic_action():
    seed(consent=True)
    assert ls.consent_for_auto("example.com", "firefox", interactive=False) == (
        True,
        "recorded consent",
    )


def test_yes_allows_the_run_without_recording_a_standing_yes():
    seed(consent=False)
    assert ls.consent_for_auto("example.com", "firefox", yes=True, interactive=False) == (
        True,
        "--yes",
    )
    assert ls.site_consent("example.com") is False


def test_a_terminal_prompt_is_the_last_gate(monkeypatch):
    seed(consent=False)
    monkeypatch.setattr(ls, "ask_site_consent", lambda *a, **k: True)
    assert ls.consent_for_auto(
        "example.com",
        "firefox",
        interactive=True,
    ) == (True, "approved just now")
    monkeypatch.setattr(ls, "ask_site_consent", lambda *a, **k: False)
    assert ls.consent_for_auto(
        "example.com",
        "firefox",
        interactive=True,
    ) == (False, "declined")


def test_refresh_reason_only_for_a_browser_login_near_expiry():
    now = int(time.time())
    seed(browser="firefox", cookies=[entry_cookie(now + 2 * 3600)])
    assert "expiring" in (ls.refresh_reason("example.com", now=now) or "")
    seed(browser="", cookies=[entry_cookie(now + 2 * 3600)])
    assert ls.refresh_reason("example.com", now=now) is None
    assert "expiring" in (ls.signin_reason("example.com", now=now) or "")


# ── login sweep and check through the CLI ──────────────────────────────────


def test_cli_sweep_reports_what_it_deleted_and_never_a_value(capsys, monkeypatch):
    now = int(time.time())
    seed(cookies=[entry_cookie(now - 1), entry_cookie(now + 3600)])
    rc, out, err = run(["login", "sweep"], capsys, monkeypatch)
    assert rc == 0
    assert "removed 1" in out
    assert "offline" in out
    assert "SECRET-VALUE" not in out + err
    assert len(read_owned_store()["example.com"]["cookies"]) == 1


def test_every_command_start_reports_a_sweep_without_being_asked(capsys, monkeypatch):
    now = int(time.time())
    seed(cookies=[entry_cookie(now - 1)])
    rc, out, err = run(["login", "list"], capsys, monkeypatch)
    assert rc == 0
    assert "cookie: deleted 1" in err
    assert "expired" in err
    assert "SECRET-VALUE" not in out + err
    assert read_owned_store()["example.com"]["expired"] is True


def test_check_logged_in_reads_directly_with_host_cookies(capsys, monkeypatch):
    now = int(time.time())
    seed("reddit.com", cookies=[entry_cookie(now + 3600, domain="reddit.com")])
    seen = {}

    def fetch(url, **kwargs):
        seen.update(kwargs, url=url)
        return FetchResult("curl_cffi", "body", 200)

    monkeypatch.setattr("searchts.unlocker.fetch", fetch)
    rc, out, err = run(["login", "check", "reddit.com"], capsys, monkeypatch)
    assert rc == 0
    assert "logged in" in out
    assert seen["url"] == "https://www.reddit.com/settings"
    assert seen["backends"] == ["curl_cffi", "stealth-browser"]
    assert seen["use_memory"] is False
    assert all("reddit.com" in c.domain for c in seen["cookies"])
    assert "SECRET-VALUE" not in out + err


def test_check_a_login_wall_is_logged_out(capsys, monkeypatch):
    seed("reddit.com", cookies=[entry_cookie(domain="reddit.com")])

    def fetch(url, **kwargs):
        raise UnlockerError(url, [("curl_cffi", "login-wall")])

    monkeypatch.setattr("searchts.unlocker.fetch", fetch)
    rc, out, err = run(["login", "check", "reddit.com"], capsys, monkeypatch)
    assert rc == 1
    assert "logged out" in out
    assert "SECRET-VALUE" not in out + err


def test_check_a_block_is_unknown_not_logged_in(capsys, monkeypatch):
    seed("reddit.com", cookies=[entry_cookie(domain="reddit.com")])

    def fetch(url, **kwargs):
        raise UnlockerError(url, [("curl_cffi", "captcha")])

    monkeypatch.setattr("searchts.unlocker.fetch", fetch)
    rc, out, _ = run(["login", "check", "reddit.com"], capsys, monkeypatch)
    assert rc == 2
    assert "unknown" in out
    assert "logged in" not in out


def test_check_a_custom_public_page_is_unknown_not_logged_in(capsys, monkeypatch):
    seed("example.com")
    monkeypatch.setattr(
        "searchts.unlocker.fetch",
        lambda url, **kw: FetchResult("curl_cffi", "body", 200),
    )
    rc, out, _ = run(
        ["login", "check", "example.com", "--url", "https://example.com/about"],
        capsys,
        monkeypatch,
    )
    assert rc == 2
    assert "unknown" in out
    assert "logged in" not in out


def test_check_without_a_saved_login_is_logged_out_and_offline(capsys, monkeypatch):
    def fetch(url, **kwargs):
        raise AssertionError("must not fetch without a saved login")

    monkeypatch.setattr("searchts.unlocker.fetch", fetch)
    rc, out, _ = run(["login", "check", "reddit.com"], capsys, monkeypatch)
    assert rc == 1
    assert "logged out" in out


# ── read --json receipts ───────────────────────────────────────────────────


def test_read_json_carries_cookie_actions_and_retries_a_wall_once(
    capsys,
    monkeypatch,
):
    source = SimpleNamespace(via="owned store", browser="firefox", count=1)
    monkeypatch.setattr(
        cli,
        "_read_command_cookies",
        lambda args: setattr(args, "_cookie_source", source) or {"sid": "SECRET-VALUE"},
    )
    calls = []

    def fetch(url, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise UnlockerError(url, [("curl_cffi", "login-wall")])
        return FetchResult("curl_cffi", "x" * 600, 200)

    def retry(args):
        cli._report_cookie_action(
            args,
            {
                "site": "example.com",
                "browser": "firefox",
                "action": "recopied",
                "count": 1,
                "reason": "login wall",
            },
        )
        return {"sid": "SECRET-VALUE"}

    monkeypatch.setattr("searchts.unlocker.fetch", fetch)
    monkeypatch.setattr(cli, "_retry_after_login_wall", retry)
    rc, out, err = run(["read", "https://example.com", "--json"], capsys, monkeypatch)
    assert rc in (0, None)
    payload = json.loads(out)
    assert payload["cookie_actions"] == [
        {
            "site": "example.com",
            "browser": "firefox",
            "action": "recopied",
            "count": 1,
            "reason": "login wall",
        }
    ]
    assert len(calls) == 2
    assert "SECRET-VALUE" not in out + err


# ── the real consent gate, driven through read ──────────────────────────────


def _cookie_value(records):
    return {c.value for c in (records or [])}


def _seed_near(host="example.com", *, consent=True, browser="firefox", value="SECRET-VALUE"):
    now = int(time.time())
    save_owned_site(
        host,
        [rec(value=value, domain=host, expiry=now + 2 * 3600)],
        browser=browser,
        consent=consent,
    )


def _fake_refresh(calls, value="FRESH-VALUE-430"):
    def refresh(site, *, browser="", force=False):
        calls.append((site, browser, force))
        return CookieSource(
            site=site,
            cookies=[rec(value=value, expiry=int(time.time()) + 86400)],
            browser=browser,
            family="firefox",
            via="browser",
            count=1,
            names=["sid"],
        )

    return refresh


def _noninteractive(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)


def test_near_expiry_without_consent_skips_and_still_reads(capsys, monkeypatch):
    _seed_near(consent=False)
    _noninteractive(monkeypatch)
    refresh = []
    monkeypatch.setattr("searchts.login_store.refresh_kept", _fake_refresh(refresh))
    seen = []

    def fetch(url, **kwargs):
        seen.append(_cookie_value(kwargs.get("cookies")))
        return FetchResult("curl_cffi", "x" * 600, 200)

    monkeypatch.setattr("searchts.unlocker.fetch", fetch)
    rc, out, err = run(["read", "https://example.com", "--json"], capsys, monkeypatch)
    assert rc in (0, None)
    assert refresh == []
    action = json.loads(out)["cookie_actions"][0]
    assert action["action"] == "skipped"
    assert "login keep" in action["reason"]
    assert "expiring" in action["reason"]
    assert "not refreshed" in err and "no consent" in err
    assert seen and "SECRET-VALUE" in seen[0]


def test_near_expiry_with_recorded_consent_refreshes_once(capsys, monkeypatch):
    _seed_near(consent=True)
    _noninteractive(monkeypatch)
    refresh = []
    monkeypatch.setattr("searchts.login_store.refresh_kept", _fake_refresh(refresh))
    seen = []

    def fetch(url, **kwargs):
        seen.append(_cookie_value(kwargs.get("cookies")))
        return FetchResult("curl_cffi", "x" * 600, 200)

    monkeypatch.setattr("searchts.unlocker.fetch", fetch)
    rc, out, _ = run(["read", "https://example.com", "--json"], capsys, monkeypatch)
    assert rc in (0, None)
    assert len(refresh) == 1
    action = json.loads(out)["cookie_actions"][0]
    assert action["action"] == "refreshed"
    assert action["count"] == 1
    assert action["reason"].startswith("expiring in ")
    assert seen == [{"FRESH-VALUE-430"}]


def test_yes_refreshes_but_does_not_record_standing_consent(capsys, monkeypatch):
    _seed_near(consent=False)
    _noninteractive(monkeypatch)
    calls = []
    original = ls.refresh_kept

    def counted(site, **kwargs):
        calls.append(site)
        return original(site, **kwargs)

    monkeypatch.setattr(ls, "refresh_kept", counted)
    monkeypatch.setattr(
        "searchts.cdp_profile.read_site_cookies",
        lambda site, browser, **kwargs: CookieSource(
            site=site,
            cookies=[rec(value="FRESH-VALUE-430", expiry=int(time.time()) + 86400)],
            browser=browser,
            family="firefox",
            via="browser",
            count=1,
            names=["sid"],
        ),
    )
    monkeypatch.setattr(
        "searchts.unlocker.fetch",
        lambda url, **kwargs: FetchResult("curl_cffi", "x" * 600, 200),
    )
    rc, out, _ = run(
        ["read", "https://example.com", "--yes", "--json"], capsys, monkeypatch,
    )
    assert rc in (0, None)
    assert len(calls) == 1
    assert ls.site_consent("example.com") is False
    assert json.loads(out)["cookie_actions"][0]["action"] == "refreshed"


def test_signin_sourced_near_expiry_only_hints(capsys, monkeypatch):
    _seed_near(browser="", consent=False)
    _noninteractive(monkeypatch)
    refresh = []
    monkeypatch.setattr("searchts.login_store.refresh_kept", _fake_refresh(refresh))
    monkeypatch.setattr(
        "searchts.unlocker.fetch",
        lambda url, **kwargs: FetchResult("curl_cffi", "x" * 600, 200),
    )
    rc, out, err = run(["read", "https://example.com", "--json"], capsys, monkeypatch)
    assert rc in (0, None)
    assert refresh == []
    action = json.loads(out)["cookie_actions"][0]
    assert action["browser"] == "signin"
    assert action["action"] == "skipped"
    assert "expiring" in action["reason"]
    assert "login signin" in err


def test_real_wall_retry_copies_once_then_gives_up(capsys, monkeypatch):
    _seed_near(consent=True)
    now = int(time.time())
    save_owned_site(
        "example.com",
        [rec(expiry=now + 7 * 86400)],
        browser="firefox",
        consent=True,
    )
    _noninteractive(monkeypatch)
    refresh = []
    monkeypatch.setattr("searchts.login_store.refresh_kept", _fake_refresh(refresh))
    fetches = []

    def fetch(url, **kwargs):
        fetches.append(1)
        raise UnlockerError(url, [("curl_cffi", "login-wall")])

    monkeypatch.setattr("searchts.unlocker.fetch", fetch)
    rc, out, err = run(["read", "https://example.com"], capsys, monkeypatch)
    assert rc == 1
    assert out == ""
    assert len(fetches) == 2
    assert len(refresh) == 1
    assert "retrying once" in err
    assert "Sign in again" in err


def test_real_wall_retry_without_consent_does_not_copy(capsys, monkeypatch):
    now = int(time.time())
    save_owned_site(
        "example.com",
        [rec(expiry=now + 7 * 86400)],
        browser="firefox",
        consent=False,
    )
    _noninteractive(monkeypatch)
    refresh = []
    monkeypatch.setattr("searchts.login_store.refresh_kept", _fake_refresh(refresh))
    fetches = []

    def fetch(url, **kwargs):
        fetches.append(1)
        raise UnlockerError(url, [("curl_cffi", "login-wall")])

    monkeypatch.setattr("searchts.unlocker.fetch", fetch)
    rc, _, err = run(["read", "https://example.com"], capsys, monkeypatch)
    assert rc == 1
    assert len(fetches) == 1
    assert refresh == []
    assert "cookie: skipped 0 firefox" in err
    assert "no consent" in err


def test_secret_never_leaks_through_sweep_refresh_or_wall_retry(capsys, monkeypatch):
    now = int(time.time())
    secret = "SECRET-VALUE-430"
    save_owned_site(
        "example.com",
        [
            rec(value=secret, expiry=now - 1),
            rec(value=secret, expiry=now + 2 * 3600),
        ],
        browser="firefox",
        consent=True,
    )
    _noninteractive(monkeypatch)
    refresh = []
    monkeypatch.setattr("searchts.login_store.refresh_kept", _fake_refresh(refresh))
    monkeypatch.setattr(
        "searchts.unlocker.fetch",
        lambda url, **kwargs: FetchResult("curl_cffi", "x" * 600, 200),
    )
    rc, out, err = run(["read", "https://example.com", "--json"], capsys, monkeypatch)
    assert rc in (0, None)
    assert secret not in out + err

    fetches = []

    def wall(url, **kwargs):
        fetches.append(1)
        raise UnlockerError(url, [("curl_cffi", "login-wall")])

    monkeypatch.setattr("searchts.unlocker.fetch", wall)
    rc, out, err = run(["read", "https://example.com"], capsys, monkeypatch)
    assert rc == 1
    assert len(fetches) == 2
    assert secret not in out + err
