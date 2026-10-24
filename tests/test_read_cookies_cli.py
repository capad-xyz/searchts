import inspect
import json
import os

import pytest

from searchts import cli
from searchts.session_cookies import CookieReadError, CookieRecord, CookieSource
from searchts.unlocker import FetchResult


@pytest.fixture
def temp_home(tmp_path, monkeypatch):
    """Point the cookie store somewhere disposable.

    Needed because `read` now consults the store, so a test that does not
    isolate HOME can pick up a real saved login for the same host. On Windows
    that means USERPROFILE, which is what `expanduser` reads -- setting HOME
    alone leaves the real profile in play.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("HOME", raising=False)
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(home))
    return home


def _run(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["searchts", *argv])
    cli.main()


def _fake_fetch(seen):
    def fetch(url, **kwargs):
        seen["cookies"] = kwargs.get("cookies")
        return FetchResult("curl_cffi", "body", 200)

    return fetch


def test_read_without_cookie_flag_passes_none(monkeypatch):
    seen = {}
    monkeypatch.setattr("searchts.unlocker.fetch", _fake_fetch(seen))

    _run(monkeypatch, ["read", "https://example.com"])

    assert seen["cookies"] is None


def test_read_browser_cookie_line_has_no_value(monkeypatch, capsys, temp_home):
    """A copied read reports provenance, and never a value.

    Copying now needs the session's one approval, so the grant is set up here
    rather than only at the `login` verb. That is the behaviour change this
    branch exists for: the read that touches a real browser is the read that
    asks.
    """
    from searchts.login_store import grant_session_copy

    grant_session_copy()
    record = CookieRecord("session", "SECRET-VALUE", ".example.com")
    source = CookieSource(
        site="https://example.com", cookies=[record], browser="zen",
        via="browser", count=1,
    )
    monkeypatch.setattr(
        "searchts.cdp_profile.read_site_cookies",
        lambda site, browser, **kwargs: source,
    )
    monkeypatch.setattr("searchts.unlocker.fetch", _fake_fetch({}))

    _run(monkeypatch, ["read", "https://example.com", "--cookies-from-browser", "zen"])

    captured = capsys.readouterr()
    assert captured.err.count("cookies:") == 1
    assert "SECRET-VALUE" not in captured.out
    assert "SECRET-VALUE" not in captured.err
    # Provenance names the source, not the browser the user named.
    assert "browser" in captured.err


def test_read_without_the_session_approval_refuses_to_copy(monkeypatch, capsys, temp_home):
    """The whole point: a read that copies cookies must ask first.

    No grant, so the copy must not happen at all, and the reason must be the
    approval rather than a bare failure an agent would retry forever.
    """
    called = []
    monkeypatch.setattr(
        "searchts.cdp_profile.read_site_cookies",
        lambda site, browser, **kwargs: called.append(site),
    )

    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, ["read", "https://example.com", "--cookies-from-browser", "zen"])

    assert exc.value.code == 3
    assert called == [], "copied despite no session approval"
    err = capsys.readouterr().err
    assert "approval once per session" in err
    assert "Traceback" not in err


def test_yes_grants_the_copy_from_the_command_line(monkeypatch, capsys, temp_home):
    """`--yes` is how a person approves, and it is the only way.

    Every existing test above reached consent by calling
    `grant_session_copy()` directly, from inside the test process. Nothing in
    the shipped CLI did that: `read --cookies-from-browser` exited 3 on every
    invocation, forever, because the grant was defined and never called. The
    suite was green throughout, since the tests granted consent themselves and
    so never exercised the path a user actually takes.

    This drives the real argv, so it fails if the CLI stops granting.
    """
    from searchts.login_store import session_granted

    assert not session_granted(), "consent leaked in from an earlier test"

    record = CookieRecord("session", "SECRET-VALUE", ".example.com")
    source = CookieSource(
        site="https://example.com", cookies=[record], browser="zen",
        via="browser", count=1,
    )
    monkeypatch.setattr(
        "searchts.cdp_profile.read_site_cookies",
        lambda site, browser, **kwargs: source,
    )
    monkeypatch.setattr("searchts.unlocker.fetch", _fake_fetch({}))

    _run(monkeypatch, [
        "read", "https://example.com", "--cookies-from-browser", "zen", "--yes",
    ])

    captured = capsys.readouterr()
    assert "cookies:" in captured.err, "--yes did not reach the copy path"
    assert "SECRET-VALUE" not in captured.err


def test_yes_without_a_browser_still_copies_nothing(monkeypatch, temp_home):
    """`--yes` must not become a blanket approval for the whole session.

    The grant it writes is scoped to this PID, and `--yes` is only honoured
    when a browser was actually named. A plain `read --yes` is not a request
    to go read someone's browser.
    """
    from searchts.login_store import session_granted

    called = []
    monkeypatch.setattr(
        "searchts.cdp_profile.read_site_cookies",
        lambda site, browser, **kwargs: called.append(site),
    )
    # The read itself is not under test; a live example.com answered 503 on
    # one main run and made this red for a reason outside the code.
    seen = {}
    monkeypatch.setattr("searchts.unlocker.fetch", _fake_fetch(seen))

    _run(monkeypatch, ["read", "https://example.com", "--yes"])

    assert called == [], "--yes reached a copy with no browser named"
    assert seen["cookies"] is None, "--yes sent cookies on a read that named no browser"
    assert not session_granted(), "--yes granted consent for a read that named no browser"


def test_cookie_read_error_is_one_clean_line(monkeypatch, capsys, temp_home):
    from searchts.login_store import grant_session_copy

    grant_session_copy()

    def fail(site, browser, **kwargs):
        raise CookieReadError("no cookies for example.com")

    monkeypatch.setattr("searchts.cdp_profile.read_site_cookies", fail)

    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, ["read", "https://example.com", "--cookies-from-browser", "zen"])

    assert exc.value.code != 0
    captured = capsys.readouterr()
    assert captured.err.count("no cookies for example.com") == 1
    assert "Traceback" not in captured.err


def test_kept_login_is_used_by_a_bare_read_with_no_flag(monkeypatch, capsys, temp_home):
    """State 1, the reason a login is kept: no browser opens and no flag needed.

    The same command with no `--cookies-from-browser` used to read
    anonymously while a saved login sat unused. That was the gap this closes.
    """
    from searchts.login_store import keep
    from searchts.session_cookies import CookieRecord as _C

    keep("example.com", [_C(name="sid", value="KEPT-VALUE", domain="example.com", secure=True)])
    seen = {}
    monkeypatch.setattr("searchts.unlocker.fetch", _fake_fetch(seen))

    _run(monkeypatch, ["read", "https://example.com"])

    assert seen["cookies"], "kept login was ignored by a bare read"
    captured = capsys.readouterr()
    assert "already kept" in captured.err
    assert "KEPT-VALUE" not in captured.err
    assert "KEPT-VALUE" not in captured.out


def test_a_parent_login_serves_a_subdomain_and_says_which_host(monkeypatch, capsys, temp_home):
    """The read names the host it resolved to, not the child it was asked for."""
    from searchts.login_store import keep

    keep("example.com", [
        CookieRecord(name="sid", value="KEPT-VALUE", domain=".example.com", secure=True),
    ])
    seen = {}
    monkeypatch.setattr("searchts.unlocker.fetch", _fake_fetch(seen))

    _run(monkeypatch, ["read", "https://app.example.com"])

    assert seen["cookies"], "parent login was ignored by a child read"
    captured = capsys.readouterr()
    assert "app.example.com resolved to the login kept for example.com" in captured.err
    assert "already kept" not in captured.err
    assert "KEPT-VALUE" not in captured.err
    assert "KEPT-VALUE" not in captured.out


def test_chromium_cookie_copy_requires_explicit_approval(monkeypatch, capsys, tmp_home):
    called = []
    monkeypatch.setattr(
        "searchts.cdp_profile.cdp_read_site",
        lambda *a, **k: called.append(a),
    )

    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, [
            "read", "https://example.com", "--cookies-from-browser", "vivaldi",
        ])

    assert exc.value.code == 3
    assert called == []
    assert "approval once per session" in capsys.readouterr().err


def test_vivaldi_cookies_reach_the_direct_read_after_yes(monkeypatch, capsys, tmp_home):
    from searchts import cdp_profile

    seen = {}
    source = CookieSource(
        site="https://example.com/article",
        cookies=[CookieRecord("session", "SECRET-VALUE", ".example.com")],
        browser="vivaldi",
        via="debugger port",
        count=1,
    )

    def fake_cdp(site, browser, *, confirm):
        seen["source"] = (site, browser)
        seen["confirmed"] = confirm("Vivaldi CDP port 55123")
        return source

    def fake_fetch(url, **kwargs):
        seen["cookies"] = kwargs.get("cookies")
        return FetchResult("curl_cffi", "body", 200)

    monkeypatch.setattr(cdp_profile, "cdp_read_site", fake_cdp)
    monkeypatch.setattr("searchts.unlocker.fetch", fake_fetch)
    _run(monkeypatch, [
        "read", "https://example.com/article", "--cookies-from-browser", "vivaldi",
        "--yes", "--json",
    ])

    captured = capsys.readouterr()
    assert seen["source"] == ("https://example.com/article", "vivaldi")
    assert seen["confirmed"] is True
    assert len(seen["cookies"]) == 1
    assert "Vivaldi CDP port 55123" in captured.err
    assert "cookies: debugger port -> 1 cookies" in captured.err
    assert "SECRET-VALUE" not in captured.out + captured.err


def test_cdp_non_localhost_rejected_before_connect(monkeypatch, capsys):
    called = []
    monkeypatch.setattr(
        "searchts.cdp_profile.connect_existing_cdp",
        lambda *args, **kwargs: called.append(args),
    )

    with pytest.raises(SystemExit):
        _run(monkeypatch, ["read", "https://example.com", "--cdp-port", "192.0.2.10:9222"])

    assert called == []
    assert "remote host" in capsys.readouterr().err


# ── the CLI and the MCP tool resolve cookies the same way ────────────────────


def test_the_cli_resolver_is_the_shared_one(tmp_path):
    """One implementation, so a second surface cannot grow a laxer one.

    The CLI used to own the cookie resolution inline while the MCP tool had no
    way to ask for cookies at all. Both now call
    ``session_cookies.resolve_cookies``; this pins that, because the failure mode
    being avoided is a second, quietly different fence.
    """
    import searchts.cli as cli

    src = inspect.getsource(cli._read_command_cookies)
    assert "resolve_cookies" in src, (
        "the CLI grew its own cookie resolution again; the rules must live in "
        "session_cookies.resolve_cookies so both surfaces share them"
    )


def test_resolve_cookies_returns_nothing_when_nothing_was_asked_for():
    from searchts.session_cookies import resolve_cookies

    assert resolve_cookies("https://site.test/a") is None
    assert resolve_cookies("https://site.test/a", cookies="", cdp_port=None) is None


def test_resolve_cookies_refuses_an_empty_jar_loudly(tmp_path):
    """An empty jar is not a silent anonymous read.

    A read that asked for a login and silently got nothing would look exactly
    like a session that expired, which is the one thing the caller cannot guess.
    """
    from searchts.session_cookies import CookieReadError, resolve_cookies

    jar = tmp_path / "jar.json"
    jar.write_text(json.dumps({"cookies": [
        {"name": "bank", "value": "v", "domain": ".bank.test"},
    ]}), encoding="utf-8")
    with pytest.raises(CookieReadError) as e:
        resolve_cookies("https://site.test/a", cookies=str(jar))
    assert "site.test" in str(e.value)
    assert "host-scoped" in str(e.value)


def test_resolve_cookies_never_names_a_value(tmp_path):
    from searchts.session_cookies import resolve_cookies

    jar = tmp_path / "jar.json"
    jar.write_text(json.dumps({"cookies": [
        {"name": "sid", "value": "LIVE-TOKEN-VALUE", "domain": ".site.test"},
    ]}), encoding="utf-8")
    records = resolve_cookies("https://site.test/a", cookies=str(jar))
    assert [c.name for c in records] == ["sid"]
    assert "LIVE-TOKEN-VALUE" not in repr(records[0].name)


def test_a_cookie_file_that_is_not_there_says_what_to_pass_instead(tmp_path):
    """Live: `--cookies /no/such/file` printed "(FileNotFoundError)".

    An exception class name is not an answer. The two flags that would have
    worked are named, because the person who mistyped the path is one flag away
    from a working read and has no way to guess that.
    """
    from searchts.session_cookies import CookieReadError, resolve_cookies

    with pytest.raises(CookieReadError) as e:
        resolve_cookies("https://site.test/a", cookies=str(tmp_path / "nope.json"))
    message = str(e.value)
    assert "FileNotFoundError" not in message
    assert "--cdp-port" in message and "--cookies-from-browser" in message


def test_two_cookie_sources_is_refused_rather_than_silently_resolved(tmp_path):
    """Live: `--cookies f --cookies-from-browser chrome` read the file.

    The file won, the browser was ignored, and the line printed said the file.
    Someone asking for a Firefox read got a file's cookies and no word about it.
    """
    from searchts.session_cookies import CookieReadError, resolve_cookies

    jar = tmp_path / "jar.json"
    jar.write_text(json.dumps({"cookies": [
        {"name": "sid", "value": "v", "domain": ".site.test"},
    ]}), encoding="utf-8")

    with pytest.raises(CookieReadError) as e:
        resolve_cookies(
            "https://site.test/a", cookies=str(jar), cookies_from_browser="firefox"
        )
    message = str(e.value)
    assert "2 ways" in message
    assert "--cookies-from-browser" in message and "--cookies" in message


def test_cdp_port_plus_a_file_is_refused_too():
    from searchts.session_cookies import CookieReadError, resolve_cookies

    with pytest.raises(CookieReadError) as e:
        resolve_cookies(
            "https://site.test/a", cookies="/tmp/x.json", cdp_port="9222"
        )
    assert "--cdp-port" in str(e.value) and "--cookies" in str(e.value)


def test_the_json_receipt_says_whether_the_read_was_authenticated(monkeypatch, capsys):
    """Live: `--json` output was identical with and without cookies.

    So a script reading the receipt could not tell "this is your account's page"
    from "this is the public page", and would report one as the other.
    """
    import json

    def _fetch(url, **kwargs):
        return FetchResult("curl_cffi", "body", 200,
                           authenticated=bool(kwargs.get("cookies")))

    monkeypatch.setattr("searchts.unlocker.fetch", _fetch)
    monkeypatch.setattr(
        "searchts.session_cookies.resolve_cookies",
        lambda site, **kw: [CookieRecord("sid", "v", ".example.com")],
    )
    _run(monkeypatch, ["read", "https://example.com/a", "--cookies", "x.json", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["authenticated"] is True


def test_the_plain_status_line_marks_a_logged_in_read(monkeypatch, capsys):
    def _fetch(url, **kwargs):
        return FetchResult("curl_cffi", "body", 200, authenticated=True)

    monkeypatch.setattr("searchts.unlocker.fetch", _fetch)
    monkeypatch.setattr(
        "searchts.session_cookies.resolve_cookies",
        lambda site, **kw: [CookieRecord("sid", "v", ".example.com")],
    )
    _run(monkeypatch, ["read", "https://example.com/a", "--cookies", "x.json"])

    assert "logged in" in capsys.readouterr().err
