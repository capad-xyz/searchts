import inspect
import json

import pytest

from searchts import cli
from searchts.session_cookies import CookieReadError, CookieRecord, CookieSource
from searchts.unlocker import FetchResult


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


def test_read_browser_cookie_line_has_no_value(monkeypatch, capsys):
    record = CookieRecord("session", "SECRET-VALUE", ".example.com")
    source = CookieSource(
        site="https://example.com", cookies=[record], browser="zen",
        via="browser", count=1,
    )
    monkeypatch.setattr("searchts.session_cookies.for_site", lambda site, browser: source)
    monkeypatch.setattr("searchts.unlocker.fetch", _fake_fetch({}))

    _run(monkeypatch, ["read", "https://example.com", "--cookies-from-browser", "zen"])

    captured = capsys.readouterr()
    assert captured.err.count("cookies:") == 1
    assert "zen" in captured.err
    assert "SECRET-VALUE" not in captured.out
    assert "SECRET-VALUE" not in captured.err


def test_cookie_read_error_is_one_clean_line(monkeypatch, capsys):
    def fail(site, browser):
        raise CookieReadError("no cookies for example.com")

    monkeypatch.setattr("searchts.session_cookies.for_site", fail)

    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, ["read", "https://example.com", "--cookies-from-browser", "zen"])

    assert exc.value.code != 0
    captured = capsys.readouterr()
    assert captured.err.count("no cookies for example.com") == 1
    assert "Traceback" not in captured.err


def test_chromium_cookie_error_explains_cdp(monkeypatch, capsys):
    monkeypatch.setattr(
        "searchts.session_cookies.for_site",
        lambda site, browser: (_ for _ in ()).throw(
            CookieReadError("chrome's cookies are locked (App-Bound Encryption). Use --cdp-port <port>")
        ),
    )

    with pytest.raises(SystemExit):
        _run(monkeypatch, ["read", "https://example.com", "--cookies-from-browser", "chrome"])

    err = capsys.readouterr().err
    assert "App-Bound Encryption" in err
    assert "--cdp-port" in err


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
