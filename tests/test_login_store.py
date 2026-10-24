"""The four states of a logged-in read, and the two files that must not merge.

Every test here pins a decision the user could otherwise have to reverse later
by hand: what stays, what is asked once, what is deleted every time, and what
is never touched because searchts did not create it.

The suite runs against a temporary HOME so it never reads or writes a real
login, and so "the store is empty" is an assertion rather than a hope.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from searchts import login_store as ls
from searchts.session_cookies import CookieReadError, CookieRecord


@pytest.fixture(autouse=True)
def temp_home(tmp_path, monkeypatch):
    """Point every path in the module at a throwaway HOME."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(home))
    yield home


def rec(name="sid", value="v", domain="example.com", secure=True):
    return CookieRecord(name=name, value=value, domain=domain, secure=secure)


# ── state 1: already kept ───────────────────────────────────────────────────


def test_kept_site_uses_the_saved_login():
    """A kept login takes precedence over any newly named source browser."""
    ls.keep("example.com", [rec()])
    d = ls.decide("example.com", browser="chrome")
    assert d.state == ls.KEPT
    assert "source browser is not consulted" in d.why.lower()


def test_kept_wins_even_when_a_browser_is_named():
    """Order matters. A kept login is used without consulting the browser."""
    ls.keep("example.com", [rec()])
    assert ls.decide("example.com", browser="firefox").state == ls.KEPT


def test_kept_returns_the_stores_cookies_host_scoped():
    ls.keep("example.com", [rec("a"), rec("b", domain="example.com")])
    src = ls.decide("example.com").source
    assert src is not None
    assert {c.name for c in src.cookies} == {"a", "b"}
    # A cookie for a different site never rides along.
    assert all("example.com" in c.domain for c in src.cookies)


def test_decide_uses_a_parent_login_for_a_subdomain():
    ls.keep("example.com", [rec(domain=".example.com")])
    d = ls.decide("app.example.com")
    assert d.state == ls.KEPT
    assert d.source is not None
    assert d.source.stored_host == "example.com"
    assert "resolved to the login kept for example.com" in d.why


def test_decide_does_not_use_a_host_only_parent_cookie_for_a_subdomain():
    ls.keep("example.com", [rec(domain="example.com")])
    assert ls.kept("example.com") is True
    assert ls.kept("app.example.com") is False
    assert ls.decide("app.example.com").state != ls.KEPT


def test_a_sibling_domain_is_not_the_same_site():
    """example.com must not pick up cookies scoped to a subdomain or a sibling.

    This is the fence, asserted rather than assumed: a kept login is written
    once and then read on every future call, so a scoping mistake here repeats
    forever instead of failing once.
    """
    ls.keep("example.com", [rec("mine", domain="example.com")])
    out = ls.decide("example.com").source
    assert {c.name for c in out.cookies} == {"mine"}

    # A subdomain's cookie is not readable as the parent, and keeping it is
    # refused rather than quietly stored under the wrong host.
    with pytest.raises(CookieReadError):
        ls.keep("parent.com", [rec("sub", domain="sub.parent.com")])
    assert ls.decide("parent.com").state != ls.KEPT


def test_a_cookie_for_another_site_cannot_be_saved_under_this_one():
    """The fence, from the keep side: saving is scoped exactly as reading is."""
    with pytest.raises(CookieReadError):
        ls.keep("other.com", [rec("b", domain="example.com")])
    assert ls.list_kept() == {}


def test_kept_requires_the_site_that_was_kept():
    ls.keep("example.com", [rec()])
    assert ls.decide("other.com").state != ls.KEPT


# ── state 2: not kept, but a local browser has it ───────────────────────────


def test_not_kept_with_browser_is_copy_state():
    d = ls.decide("example.com", browser="firefox")
    assert d.state == ls.COPY
    assert d.action == "copy"


def test_firefox_copy_reads_a_file_and_chrome_copy_opens_a_window():
    """The two families need different things, and the message must say which."""
    ff = ls.decide("example.com", browser="firefox").why.lower()
    chrome = ls.decide("example.com", browser="chrome").why.lower()
    assert "file" in ff
    assert "side by side" in chrome or "side-by-side" in chrome


def test_copy_without_session_consent_raises():
    with pytest.raises(ls.SessionConsentNeeded):
        ls.require_copy_consent("example.com")


def test_copy_consent_is_recorded_per_process_not_per_user():
    """'Once per session' means one running session, not this account forever."""
    ls.grant_session_copy()
    assert ls.session_granted() is True

    grant = json.loads(Path(ls.session_grant_path()).read_text())
    grant["pid"] = grant["pid"] + 1
    Path(ls.session_grant_path()).write_text(json.dumps(grant))

    assert ls.session_granted() is False


def test_consent_covers_the_sites_the_session_reads_not_the_machine():
    ls.grant_session_copy()
    ls.note_copied("example.com")
    assert ls.session_copied_sites() == ["example.com"]

    ls.note_copied("other.com")
    assert ls.session_copied_sites() == ["example.com", "other.com"]


def test_copying_a_site_does_not_keep_it():
    """Copy is not keep. The read works; nothing is kept without a yes."""
    ls.grant_session_copy()
    ls.note_copied("example.com")
    assert ls.decide("example.com").state != ls.KEPT
    assert ls.list_kept() == {}


def test_revoke_makes_the_next_copy_ask_again():
    ls.grant_session_copy()
    ls.revoke_session_copy()
    assert ls.session_granted() is False


# ── state 3: nothing to copy, so sign in once ───────────────────────────────


def test_no_browser_and_not_kept_is_signin_state():
    d = ls.decide("example.com")
    assert d.state == ls.SIGNIN
    assert d.needs_signin


def test_signin_state_says_nothing_is_copied_from_the_pc():
    why = ls.decide("example.com").why.lower()
    assert "copy" in why and "sign in" in why


def test_prepare_refuses_signin_when_no_window_can_be_opened():
    """Otherwise the read hangs on a question it cannot ask."""
    with pytest.raises(CookieReadError):
        ls.prepare("example.com", allow_signin=False)


# ── state 4: the question after the read works ──────────────────────────────


def test_keep_writes_exactly_one_site():
    ls.keep("example.com", [rec("a", domain="example.com")])
    ls.keep("other.com", [rec("b", domain="other.com")])
    assert sorted(ls.list_kept()) == ["example.com", "other.com"]


def test_keep_question_states_both_answers_and_their_consequence():
    q = ls.keep_question("example.com").lower()
    assert "keep" in q and "yes" in q and "no" in q
    assert "asks again" in q


def test_a_no_keeps_nothing_and_the_next_read_asks_again():
    assert ls.list_kept() == {}
    assert ls.decide("example.com").state == ls.SIGNIN


def test_keep_stores_the_value_while_scratch_stays_empty():
    """Keeping writes a value into the store; scratch is never handed the store."""
    scratch = ls.new_scratch("example.com")
    try:
        ls.keep("example.com", [rec("sid", "abc123")])
        assert ls.list_kept()["example.com"]["cookies"] == 1
        # The scratch dir is a profile copy and must never contain the store.
        assert os.listdir(scratch) == []
    finally:
        ls.purge_scratch()


def test_store_path_and_scratch_path_are_different_files():
    from searchts.session_cookies import owned_store_path

    assert os.path.abspath(owned_store_path()) != os.path.abspath(ls.scratch_root())
    # Nor is the store inside the scratch tree, which purge would then delete.
    assert not os.path.abspath(owned_store_path()).startswith(
        os.path.abspath(ls.scratch_root()) + os.sep
    )


# ── kill ────────────────────────────────────────────────────────────────────


def test_kill_removes_searchts_copy_only():
    ls.keep("example.com", [rec()])
    out = ls.kill("example.com")
    assert out.removed_from_store is True
    assert ls.list_kept() == {}


def test_kill_does_not_touch_the_users_own_browser():
    ls.keep("example.com", [rec()])
    out = ls.kill("example.com")
    assert "left alone" in out.why


def test_kill_of_a_site_that_was_never_kept_says_so():
    out = ls.kill("never-kept.com")
    assert out.removed_from_store is False
    assert "no saved login" in out.why


def test_kill_removes_scratch_every_time():
    ls.new_scratch("a")
    ls.new_scratch("b")
    ls.kill("example.com")
    assert ls.scratch_paths() == []


# ── scratch ─────────────────────────────────────────────────────────────────


def test_scratch_is_created_and_purged():
    p = ls.new_scratch("example.com")
    assert os.path.isdir(p)
    assert ls.scratch_paths() == [p]
    ls.purge_scratch()
    assert ls.scratch_paths() == []


def test_scratch_label_cannot_escape_its_root():
    p = ls.new_scratch("../../evil")
    assert os.path.abspath(p).startswith(os.path.abspath(ls.scratch_root()))
    ls.purge_scratch()


def test_purge_survives_a_directory_already_gone():
    p = ls.new_scratch("gone")
    os.rmdir(p)
    ls.purge_scratch()  # must not raise


def test_audit_reports_no_values():
    ls.keep("example.com", [rec("sid", "SUPERSECRET")])
    blob = json.dumps(ls.audit().as_dict())
    assert "SUPERSECRET" not in blob
    assert "example.com" in blob


def test_audit_lists_kept_scratch_and_consent():
    ls.keep("example.com", [rec()])
    ls.grant_session_copy()
    a = ls.audit()
    assert a.kept
    assert a.session_copy_granted is True
    assert a.store_dir and a.scratch_dir
    assert a.store_dir != a.scratch_dir


# ── prepare: the order, end to end ──────────────────────────────────────────


def test_prepare_uses_the_store_without_asking():
    ls.keep("example.com", [rec()])
    src = ls.prepare("example.com", browser="chrome")
    assert src.count == 1
    assert src.via == "owned store"


def test_prepare_copy_needs_consent_first(monkeypatch):
    from searchts import cdp_profile
    from searchts.session_cookies import CookieSource

    calls = []

    def fake_read_site(site, browser="", *, confirm=None):
        calls.append((site, browser, confirm is not None))
        return CookieSource(site=site, cookies=[rec()], count=1, via="test")

    ls.grant_session_copy()
    monkeypatch.setattr(cdp_profile, "read_site_cookies", fake_read_site)
    src = ls.prepare("example.com", browser="zen")
    assert src.count == 1
    assert calls == [("example.com", "zen", True)]
    # Copied, not kept.
    assert ls.list_kept() == {}


def test_prepare_does_not_copy_when_consent_is_missing(monkeypatch):
    from searchts import cdp_profile

    called = []
    monkeypatch.setattr(
        cdp_profile, "read_site_cookies", lambda *a, **k: called.append(a)
    )
    with pytest.raises(ls.SessionConsentNeeded):
        ls.prepare("example.com", browser="zen")
    assert called == []


def test_prepare_vivaldi_opens_a_confirmed_cdp_copy(monkeypatch, capsys):
    from searchts import cdp_profile
    from searchts.session_cookies import CookieSource

    calls = []

    def fake_cdp(site, browser, *, confirm):
        calls.append((site, browser, confirm("Vivaldi debugger")))
        return CookieSource(site=site, cookies=[rec()], count=1, via="debugger port")

    ls.grant_session_copy()
    monkeypatch.setattr(cdp_profile, "cdp_read_site", fake_cdp)
    src = ls.prepare("example.com", browser="vivaldi")
    captured = capsys.readouterr()

    assert src.via == "debugger port"
    assert calls == [("example.com", "vivaldi", True)]
    assert "Vivaldi debugger" in captured.err
    assert ls.session_copied_sites() == ["example.com"]


def test_unknown_browser_is_reported_not_crashed():
    d = ls.decide("example.com", browser="netscape")
    assert d.state == ls.NONE
    assert "netscape" in d.why


def test_not_a_url_is_none_state():
    assert ls.decide("not a url").state == ls.NONE


def test_a_one_call_grant_restores_the_grant_that_was_there(monkeypatch):
    """#451: the MCP one-call approval must not erase a CLI run's own grant."""
    other = {"copy": True, "pid": 424242, "at": 1}
    ls._write_json(ls.session_grant_path(), other, 0o600)
    with ls.grant_for_one_call():
        assert ls.session_granted() is True
    assert ls._read_json(ls.session_grant_path()) == other
    assert ls.session_granted() is False


def test_a_one_call_grant_leaves_nothing_when_there_was_none():
    with ls.grant_for_one_call():
        assert ls.session_granted() is True
    assert ls.session_granted() is False
    assert not os.path.exists(ls.session_grant_path())
