"""The four states, driven through the CLI, against a real store on disk.

The unit tests call functions. These call the verbs a user or an agent types,
so the wiring is covered too: a state that works in ``login_store`` but is
never reached from ``searchts login`` is not a state that works.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from searchts import login_store as ls
from searchts.session_cookies import CookieRecord


@pytest.fixture(autouse=True)
def temp_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(home))
    yield home


def run(argv, capsys, monkeypatch):
    """Invoke the real entry point the way the console script does."""
    from searchts import cli

    monkeypatch.setattr("sys.argv", ["searchts", *argv])
    try:
        rc = cli.main()
    except SystemExit as e:  # argparse and the error paths both use this
        rc = e.code
    out = capsys.readouterr()
    return rc, out.out, out.err


def rec(domain="example.com"):
    return CookieRecord(name="sid", value="SECRETVALUE", domain=domain, secure=True)


def seed(site="example.com"):
    ls.keep(site, [rec(domain=site)])


# ── list ────────────────────────────────────────────────────────────────────


def test_list_on_an_empty_store_says_nothing_is_stored(capsys, monkeypatch):
    rc, out, _ = run(["login", "list"], capsys, monkeypatch)
    assert rc == 0
    assert "nothing is stored" in out.lower()


def test_list_names_a_kept_site_and_no_value(capsys, monkeypatch):
    seed()
    rc, out, _ = run(["login", "list"], capsys, monkeypatch)
    assert rc == 0
    assert "example.com" in out
    assert "SECRETVALUE" not in out


# ── keep ────────────────────────────────────────────────────────────────────


def test_keep_without_a_source_refuses_rather_than_guessing(capsys, monkeypatch):
    rc, _, err = run(["login", "keep", "example.com"], capsys, monkeypatch)
    assert rc == 2
    assert "cookies-from-browser" in err


def test_keep_without_consent_is_refused_and_stores_nothing(capsys, monkeypatch):
    """`login keep` must not become a way around the one approval."""
    from searchts import cdp_profile

    monkeypatch.setattr(
        cdp_profile, "read_site_cookies",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not copy")),
    )
    rc, _, err = run(
        ["login", "keep", "example.com", "--cookies-from-browser", "firefox"],
        capsys, monkeypatch,
    )
    assert rc == 3
    assert "approval once per session" in err
    assert ls.list_kept() == {}


def test_keep_with_consent_writes_one_site(capsys, monkeypatch):
    from searchts import cdp_profile
    from searchts.session_cookies import CookieSource

    monkeypatch.setattr(
        cdp_profile, "read_site_cookies",
        lambda s, b="", **kw: CookieSource(site=s, cookies=[rec()], count=1, via="test"),
    )
    ls.grant_session_copy()
    rc, out, _ = run(
        ["login", "keep", "example.com", "--cookies-from-browser", "firefox"],
        capsys, monkeypatch,
    )
    assert rc == 0
    assert "kept example.com" in out
    assert "SECRETVALUE" not in out
    assert sorted(ls.list_kept()) == ["example.com"]


def test_keep_vivaldi_with_yes_reads_profile_then_persists_it(capsys, monkeypatch):
    """The user's Vivaldi profile is the source, and only this host is kept."""
    from searchts import cdp_profile
    from searchts.session_cookies import CookieSource

    seen = {}

    def read_site(site, browser, *, confirm):
        seen["site"] = site
        seen["browser"] = browser
        seen["approved"] = confirm("Vivaldi debugger approval")
        return CookieSource(
            site=site, cookies=[rec()], browser=browser, count=1,
            via="debugger port",
        )

    monkeypatch.setattr(cdp_profile, "read_site_cookies", read_site)
    rc, out, err = run(
        ["login", "keep", "https://example.com/profile",
         "--cookies-from-browser", "vivaldi", "--yes"],
        capsys, monkeypatch,
    )

    assert rc == 0
    assert seen == {
        "site": "https://example.com/profile",
        "browser": "vivaldi",
        "approved": True,
    }
    assert "Vivaldi debugger approval" in err
    assert "kept example.com" in out
    assert "SECRETVALUE" not in out + err
    assert ls.list_kept() == {"example.com": {"cookies": 1, "browser": "vivaldi"}}
    assert ls.session_copied_sites() == ["example.com"]


# ── kill ────────────────────────────────────────────────────────────────────


def test_kill_removes_the_site_and_says_the_browser_was_left_alone(capsys, monkeypatch):
    seed()
    rc, out, _ = run(["login", "kill", "example.com"], capsys, monkeypatch)
    assert rc == 0
    assert "left alone" in out
    assert ls.list_kept() == {}


def test_kill_does_not_delete_another_sites_login(capsys, monkeypatch):
    seed("example.com")
    seed("other.com")
    run(["login", "kill", "example.com"], capsys, monkeypatch)
    assert sorted(ls.list_kept()) == ["other.com"]


def test_kill_rejects_a_malformed_site(capsys, monkeypatch):
    rc, _, err = run(["login", "kill", "not a url"], capsys, monkeypatch)
    assert rc == 2
    assert "not a site searchts can file" in err


# ── signin ──────────────────────────────────────────────────────────────────


def test_signin_without_yes_keeps_nothing(capsys, monkeypatch):
    """A sign-in that served one read must not quietly become a kept login."""
    from searchts import signin_browser
    from searchts.session_cookies import CookieSource

    monkeypatch.setattr(
        signin_browser, "signin",
        lambda s, **kw: CookieSource(site=s, cookies=[rec()], count=1, via="test"),
    )
    rc, out, _ = run(["login", "signin", "example.com"], capsys, monkeypatch)
    assert rc == 0
    assert "Nothing kept" in out
    assert ls.list_kept() == {}


def test_signin_with_yes_keeps_exactly_that_site(capsys, monkeypatch):
    from searchts import signin_browser
    from searchts.session_cookies import CookieSource

    monkeypatch.setattr(
        signin_browser, "signin",
        lambda s, **kw: CookieSource(site=s, cookies=[rec()], count=1, via="test"),
    )
    rc, out, _ = run(["login", "signin", "example.com", "--yes"], capsys, monkeypatch)
    assert rc == 0
    assert "kept example.com" in out
    assert sorted(ls.list_kept()) == ["example.com"]


def test_signin_never_reads_the_users_own_browser(capsys, monkeypatch):
    """The sign-in path must not go through the copy-from-your-browser route."""
    from searchts import session_cookies
    from searchts.session_cookies import CookieSource

    def _boom(*a, **k):
        raise AssertionError("signin must not call the browser-copy resolver")

    # Patched on the module the handler resolves at call time, so this fails if
    # `login signin` ever starts routing through for_site().
    monkeypatch.setattr(session_cookies, "for_site", _boom)
    monkeypatch.setattr(
        "searchts.signin_browser.signin",
        lambda s, **kw: CookieSource(site=s, cookies=[rec()], count=1, via="owned browser"),
    )
    rc, out, _ = run(["login", "signin", "example.com"], capsys, monkeypatch)
    assert rc == 0
    # Nothing copied, and nothing kept without the explicit yes.
    assert "Nothing kept" in out
    assert ls.list_kept() == {}


def test_signin_reports_a_browser_that_cannot_start(capsys, monkeypatch):
    """A missing browser is a clear error, not a traceback."""
    from searchts.session_cookies import CookieReadError

    monkeypatch.setattr(
        "searchts.signin_browser.signin",
        lambda s, **kw: (_ for _ in ()).throw(CookieReadError("chrome not installed")),
    )
    rc, _, err = run(["login", "signin", "example.com"], capsys, monkeypatch)
    assert rc == 1
    assert "chrome not installed" in err
    assert ls.list_kept() == {}


# ── scratch ─────────────────────────────────────────────────────────────────


def test_purge_scratch_removes_everything(capsys, monkeypatch):
    ls.new_scratch("a")
    ls.new_scratch("b")
    rc, out, _ = run(["login", "purge-scratch"], capsys, monkeypatch)
    assert rc == 0
    assert "Deleted 2" in out
    assert ls.scratch_paths() == []


def test_list_reports_leftover_scratch(capsys, monkeypatch):
    ls.new_scratch("leftover")
    rc, out, _ = run(["login", "list"], capsys, monkeypatch)
    assert "Scratch copies present: 1" in out


# ── the store on disk is not the scratch copy ───────────────────────────────


def test_the_two_files_are_distinct_on_disk():
    """The invariant, as bytes on disk rather than as a claim."""
    from searchts.session_cookies import owned_store_path

    seed()
    scratch = ls.new_scratch("example.com")
    try:
        store_file = Path(owned_store_path())
        assert store_file.is_file()
        assert store_file.read_text(encoding="utf-8").count("SECRETVALUE") == 1
        # The scratch dir holds no cookie store; it is a profile copy, not one.
        assert not (Path(scratch) / "owned.json").exists()
        assert os.path.abspath(store_file) != os.path.abspath(ls.scratch_root())
    finally:
        ls.purge_scratch()


def test_killing_a_site_leaves_another_sites_values_intact(capsys, monkeypatch):
    seed("example.com")
    seed("other.com")
    run(["login", "kill", "example.com"], capsys, monkeypatch)
    blob = json.dumps(ls.list_kept())
    assert "other.com" in blob
    assert "example.com" not in blob
