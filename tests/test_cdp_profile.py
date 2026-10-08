# -*- coding: utf-8 -*-
"""The debugger-port cookie path, with no browser anywhere near it.

Every case here injects a fake CDP client, a fake launcher and a fake profile
copy, so the guarantees are checked directly instead of inferred:

* a declined (or unaskable) consent launches nothing and creates nothing,
* the scratch profile is deleted after a successful read AND after a failed
  one, and the failure still propagates,
* a user-supplied port has to be this machine's loopback and a real port,
* cookies come back for the one requested host and nothing else,
* no cookie value reaches an exception message or a repr.

`Tripwire` is used for the "must never be called" stubs rather than
`AssertionError`, because the module wraps its browser work in
`except Exception`: a swallowed assertion would let the guard pass whether or
not the forbidden call happened. See tests/conftest.py for why that matters.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from conftest import Tripwire, tripwire

from searchts import cdp_profile
from searchts.session_cookies import CookieReadError, filter_for_host

SITE = "https://news.example.com/article"
HOST = "news.example.com"

#: Values planted in the fake cookie jar. If any of these turns up in an
#: exception message or a repr, the module is leaking.
SID = "SUPERSECRETSESSIONVALUE"
MAIL = "mailboxTOKENVALUE"
BANK = "bankingTOKENVALUE"

FAKE_JAR = [
    {"name": "sid", "value": SID, "domain": ".example.com", "path": "/",
     "secure": True, "httpOnly": True},
    {"name": "csrf", "value": "csrf123", "domain": ".example.com", "path": "/"},
    # Somebody else's sites. A CDP client asked for one host, so these must not
    # come back; the module filters again regardless of what it is handed.
    {"name": "mailbox", "value": MAIL, "domain": ".mail.example.org", "path": "/"},
    {"name": "banking", "value": BANK, "domain": ".bank.example.net", "path": "/"},
]


# ── fakes ────────────────────────────────────────────────────────────────────


def new_log() -> dict:
    return {
        "launched": [],
        "closed": [],
        "stopped": [],
        "endpoints": [],
        "cookie_calls": [],
        "copies": [],
        "scratch": [],
        "sync_calls": 0,
        "scratch_exists_at_launch": [],
    }


class FakeContext:
    def __init__(self, jar, log, boom=None):
        self._jar = jar
        self._log = log
        self._boom = boom

    def cookies(self, urls):
        self._log["cookie_calls"].append(list(urls))
        if self._boom is not None:
            raise self._boom
        return self._jar


class FakeBrowser:
    """A browser reached over CDP. Records what it was asked, and whether closed."""

    def __init__(self, log, jar=None, contexts=1, boom=None):
        self.log = log
        ctx = FakeContext(FAKE_JAR if jar is None else jar, log, boom)
        self.contexts = [ctx] * contexts

    def close(self):
        self.log["closed"].append("browser")


class FakeChromium:
    def __init__(self, log, browser, connect_raises=False):
        self._log = log
        self._browser = browser
        self._connect_raises = connect_raises

    def connect_over_cdp(self, endpoint):
        self._log["endpoints"].append(endpoint)
        if self._connect_raises:
            raise RuntimeError("connect refused")
        return self._browser


class FakePlaywright:
    def __init__(self, log, browser, connect_raises=False):
        self.chromium = FakeChromium(log, browser, connect_raises)
        self._log = log

    def stop(self):
        self._log["stopped"].append("pw")


class FakePlaywrightModule:
    """Stands in for `patchright.sync_api`, which is never imported here."""

    def __init__(self, log, jar=None, contexts=1, connect_raises=False, cookie_boom=None):
        self.log = log
        self._jar = jar
        self._contexts = contexts
        self._connect_raises = connect_raises
        self._cookie_boom = cookie_boom

    def sync_playwright(self):
        self.log["sync_calls"] += 1
        return FakePlaywright(
            self.log,
            FakeBrowser(self.log, self._jar, self._contexts, self._cookie_boom),
            self._connect_raises,
        )


class FakeLaunched:
    """What the launcher hands back: something with close()."""

    def __init__(self, log):
        self._log = log

    def close(self):
        self._log["closed"].append("process")


def make_launcher(log, boom=None):
    def _launcher(executable, port, scratch, *, clock=None):
        log["launched"].append((executable, port, scratch))
        log["scratch_exists_at_launch"].append(os.path.isdir(scratch))
        if boom is not None:
            raise boom
        return FakeLaunched(log)

    return _launcher


def make_copy(log, boom=None):
    """A fake copy that records the destination and puts a file in it.

    `boom` mimics the real copy_profile, which wraps an OSError into a
    CookieReadError of its own before anything downstream sees it.
    """

    def _copy(src, dst):
        log["copies"].append((src, dst))
        if boom is not None:
            raise CookieReadError("could not copy the profile to a scratch folder")
        Path(dst).mkdir(parents=True, exist_ok=True)
        (Path(dst) / "Cookies").write_text("login=1", encoding="utf-8")

    return _copy


def make_scratch(log, tmp_path):
    """A fake scratch dir under tmp_path, so nothing lands in the real TEMP."""

    def _scratch():
        path = tmp_path / f"scratch-{len(log['scratch'])}"
        path.mkdir(parents=True, exist_ok=True)
        log["scratch"].append(str(path))
        return str(path)

    return _scratch


def run_read(tmp_path, *, log=None, confirm=True, pw=None, launcher_boom=None,
             copy_boom=None, site=SITE, **overrides):
    """One cdp_read_site call with every collaborator faked.

    `confirm=True` is shorthand for "a callback that says yes"; pass a callable
    to say anything else, including None for "there is no way to ask".
    """
    log = new_log() if log is None else log
    kwargs = dict(
        confirm=(lambda prompt: True) if confirm is True else confirm,
        playwright_module=FakePlaywrightModule(log) if pw is None else pw,
        copy_profile_fn=make_copy(log, copy_boom),
        launcher=make_launcher(log, launcher_boom),
        scratch_fn=make_scratch(log, tmp_path),
        executable="fake-chrome.exe",
        profile_src="fake-profile-dir",
        port=9222,
        clock=lambda: 0.0,
    )
    browser = overrides.pop("browser", "chrome")
    kwargs.update(overrides)
    return cdp_profile.cdp_read_site(site, browser, **kwargs)


# ── 1. consent ───────────────────────────────────────────────────────────────


class TestConsent:
    def test_denied_launches_nothing_and_creates_nothing(self, tmp_path):
        log = new_log()
        with pytest.raises(cdp_profile.ConsentRequired) as e:
            run_read(tmp_path, log=log, confirm=lambda prompt: False)

        assert log["launched"] == [], "a declined consent must launch no browser"
        assert log["sync_calls"] == 0, "a declined consent must not start a CDP client"
        assert log["copies"] == [], "a declined consent must copy no profile"
        assert log["scratch"] == [], "a declined consent must not even make a scratch dir"
        assert not list(tmp_path.iterdir()), "the filesystem must be untouched"
        assert "declined" in str(e.value)

    def test_denied_never_reaches_the_launcher_at_all(self, tmp_path):
        """The strong form: tripwires, so a swallowed AssertionError cannot pass."""
        with pytest.raises(cdp_profile.ConsentRequired):
            run_read(
                tmp_path,
                confirm=lambda prompt: False,
                launcher=tripwire("the launcher ran on a declined consent"),
                scratch_fn=tripwire("a scratch dir was made on a declined consent"),
                copy_profile_fn=tripwire("a profile was copied on a declined consent"),
                playwright_module=tripwire("a CDP client was started"),
            )

    def test_no_confirm_callable_aborts_with_a_one_line_reason(self, tmp_path):
        with pytest.raises(cdp_profile.ConsentRequired) as e:
            run_read(tmp_path, confirm=None)
        msg = str(e.value)
        assert "no way to ask" in msg
        assert "--cdp-port" in msg, "must say what the user can do instead"

    def test_a_refusal_is_not_a_read_failure(self):
        """A caller catching read failures must not swallow 'the user said no'."""
        assert issubclass(cdp_profile.ConsentRequired, Exception)
        assert not issubclass(cdp_profile.ConsentRequired, CookieReadError)

    def test_the_question_names_the_bar_and_the_shared_port(self):
        prompt = cdp_profile.consent_prompt("chrome", HOST, 9222)
        assert "bar" in prompt, "the infobar the browser shows has to be said out loud"
        assert "automated" in prompt
        assert "any program on this computer" in prompt, "the port is not ours alone"
        assert "9222" in prompt
        assert HOST in prompt, "one site is being agreed to, so name it"

    def test_consent_comes_before_anything_is_created(self, tmp_path):
        seen = {}

        def confirm(prompt):
            seen["at_prompt_time"] = sorted(p.name for p in tmp_path.iterdir())
            return True

        log = new_log()
        run_read(tmp_path, log=log, confirm=confirm)
        assert seen["at_prompt_time"] == [], "asked before the scratch dir exists"
        assert len(log["launched"]) == 1

    def test_a_non_chromium_browser_is_refused_before_the_question(self, tmp_path):
        with pytest.raises(CookieReadError) as e:
            run_read(tmp_path, confirm=lambda p: True, browser="firefox")
        assert "Firefox-derived" in str(e.value)


# ── 2 + 3. the scratch profile does not survive ─────────────────────────────


class TestScratchProfileIsDeleted:
    def test_deleted_after_a_successful_read(self, tmp_path):
        log = new_log()
        source = run_read(tmp_path, log=log)

        assert log["scratch"], "a scratch dir must have been created"
        scratch = log["scratch"][0]
        assert log["scratch_exists_at_launch"] == [True], (
            "it must have existed while the browser was running"
        )
        assert not os.path.exists(scratch), (
            "the scratch profile is a copy of every login the user has; "
            "a successful read must leave nothing behind"
        )
        assert source.count == 2, "the two example.com cookies come back"

    def test_deleted_when_the_cdp_client_fails(self, tmp_path):
        log = new_log()
        pw = FakePlaywrightModule(log, connect_raises=True)
        with pytest.raises(CookieReadError) as e:
            run_read(tmp_path, log=log, pw=pw)

        assert "could not connect" in str(e.value)
        assert not os.path.exists(log["scratch"][0]), "a failed read leaves nothing either"

    def test_deleted_when_the_browser_will_not_start(self, tmp_path):
        log = new_log()
        with pytest.raises(Tripwire):
            run_read(tmp_path, log=log, launcher_boom=Tripwire("browser refused to start"))

        assert not os.path.exists(log["scratch"][0]), "cleanup cannot depend on the reason"

    def test_deleted_when_the_cookie_call_raises(self, tmp_path):
        log = new_log()
        pw = FakePlaywrightModule(log, cookie_boom=RuntimeError("context destroyed"))
        with pytest.raises(CookieReadError) as e:
            run_read(tmp_path, log=log, pw=pw)

        assert "could not read cookies over CDP" in str(e.value)
        assert not os.path.exists(log["scratch"][0])

    def test_deleted_when_the_browser_offers_no_cookie_context(self, tmp_path):
        log = new_log()
        pw = FakePlaywrightModule(log, contexts=0)
        with pytest.raises(CookieReadError) as e:
            run_read(tmp_path, log=log, pw=pw)

        assert "no cookie context" in str(e.value)
        assert not os.path.exists(log["scratch"][0])

    def test_deleted_when_the_profile_cannot_be_copied(self, tmp_path):
        log = new_log()
        with pytest.raises(CookieReadError):
            run_read(tmp_path, log=log, copy_boom=OSError("in use"))

        assert log["launched"] == [], "a failed copy must not lead to a launch"
        assert not os.path.exists(log["scratch"][0])

    def test_the_failure_still_propagates(self, tmp_path, monkeypatch):
        """Cleanup must not replace the real reason, even when cleanup also fails."""
        log = new_log()
        monkeypatch.setattr(cdp_profile, "_purge", lambda path: "OSError: file is in use")
        with pytest.raises(Tripwire) as e:
            run_read(tmp_path, log=log, launcher_boom=Tripwire("browser refused to start"))

        assert "browser refused to start" in str(e.value), (
            "the reason the read failed has to survive the cleanup attempt"
        )

    def test_a_leftover_after_a_good_read_is_an_error_not_a_quiet_return(self, tmp_path, monkeypatch):
        """Cookies in hand while a copy of the whole profile survives is the bad outcome."""
        log = new_log()
        monkeypatch.setattr(cdp_profile, "_purge", lambda path: "OSError: file is in use")
        with pytest.raises(CookieReadError) as e:
            run_read(tmp_path, log=log)

        msg = str(e.value)
        assert log["scratch"][0] in msg, "name the folder, so it can be deleted by hand"
        assert "Delete that folder" in msg

    def test_a_leftover_after_a_failed_read_is_warned_and_the_error_kept(
        self, tmp_path, monkeypatch, capsys
    ):
        log = new_log()
        monkeypatch.setattr(cdp_profile, "_purge", lambda path: "OSError: file is in use")
        with pytest.raises(Tripwire):
            run_read(tmp_path, log=log, launcher_boom=Tripwire("browser refused to start"))

        err = capsys.readouterr().err
        assert log["scratch"][0] in err, "a leftover has to be reported, not swallowed"
        assert "every login" in err


# ── nothing survives the call ────────────────────────────────────────────────


class TestNothingLeftRunning:
    def test_the_browser_and_the_client_are_closed_on_success(self, tmp_path):
        log = new_log()
        run_read(tmp_path, log=log)
        assert log["closed"] == ["browser", "process"]
        assert log["stopped"] == ["pw"]

    def test_the_browser_is_closed_even_when_the_read_failed(self, tmp_path):
        log = new_log()
        pw = FakePlaywrightModule(log, cookie_boom=RuntimeError("context destroyed"))
        with pytest.raises(CookieReadError):
            run_read(tmp_path, log=log, pw=pw)
        assert log["closed"] == ["browser", "process"]
        assert log["stopped"] == ["pw"]

    def test_launched_exactly_once(self, tmp_path):
        log = new_log()
        run_read(tmp_path, log=log)
        assert len(log["launched"]) == 1
        exe, port, _scratch = log["launched"][0]
        assert exe == "fake-chrome.exe"
        assert port == 9222


# ── 4. the localhost guard on a user-supplied port ───────────────────────────


class TestConnectExistingCdpGuard:
    @pytest.mark.parametrize(
        "given,expected",
        [
            (9222, "http://127.0.0.1:9222"),
            ("9222", "http://127.0.0.1:9222"),
            ("127.0.0.1:9222", "http://127.0.0.1:9222"),
            ("localhost:9222", "http://127.0.0.1:9222"),
            ("[::1]:9222", "http://[::1]:9222"),
            ("127.0.0.5:9333", "http://127.0.0.5:9333"),
        ],
    )
    def test_accepts_this_machine(self, given, expected):
        log = new_log()
        src = cdp_profile.connect_existing_cdp(
            given, SITE, playwright_module=FakePlaywrightModule(log)
        )
        assert log["endpoints"] == [expected]
        assert src.count == 2

    @pytest.mark.parametrize(
        "given",
        [
            "10.0.0.5:9222",
            "192.168.1.10:9222",
            "example.com:9222",
            "evil.example.com:9222",
            "0.0.0.0:9222",   # unspecified: binds every interface, not just this one
            "169.254.169.254:9222",
            "[::]:9222",
        ],
    )
    def test_refuses_anything_that_is_not_loopback(self, given):
        # Tripwire module: the refusal has to happen before a socket is opened.
        with pytest.raises(CookieReadError) as e:
            cdp_profile.connect_existing_cdp(
                given, SITE, playwright_module=tripwire(f"connected to {given}")
            )
        assert "loopback" in str(e.value) or "this machine" in str(e.value)

    @pytest.mark.parametrize("given", [0, -1, 65536, 99999, "0", "notaport", ""])
    def test_refuses_a_port_that_is_not_a_port(self, given):
        with pytest.raises(CookieReadError) as e:
            cdp_profile.connect_existing_cdp(
                given, SITE, playwright_module=tripwire(f"connected to {given}")
            )
        assert "port" in str(e.value)

    def test_the_guard_runs_before_the_site_is_even_parsed(self):
        with pytest.raises(CookieReadError) as e:
            cdp_profile.connect_existing_cdp(
                "example.com:9222", "not a url at all", playwright_module=tripwire("no")
            )
        assert "this machine" in str(e.value)

    def test_the_users_browser_is_not_closed(self, tmp_path):
        log = new_log()
        cdp_profile.connect_existing_cdp(9222, SITE, playwright_module=FakePlaywrightModule(log))
        assert log["closed"] == [], (
            "this browser belongs to the user; closing it would end their session"
        )
        assert log["stopped"] == ["pw"], "the driver is dropped, which is the detach"


# ── 5. scoping to the one host ───────────────────────────────────────────────


class TestOneHostOnly:
    def test_foreign_domains_are_filtered_out(self, tmp_path):
        src = run_read(tmp_path)
        assert {c.domain for c in src.cookies} == {".example.com"}
        assert {c.name for c in src.cookies} == {"sid", "csrf"}
        values = [c.value for c in src.cookies]
        assert SID in values, "the fake jar really does carry the other domains' cookies"
        assert MAIL not in values and BANK not in values, (
            "a CDP read is scoped to one host; another site's login must not ride along"
        )

    def test_the_filter_is_the_shared_one(self, tmp_path):
        """Same rule as every other reader: a loose endswith hands over the jar."""
        src = run_read(tmp_path)
        mine = filter_for_host(list(src.cookies), HOST)
        assert [c.name for c in mine] == [c.name for c in src.cookies]

    def test_the_cdp_call_asks_for_exactly_one_url(self, tmp_path):
        log = new_log()
        run_read(tmp_path, log=log)
        assert log["cookie_calls"] == [[SITE]], "one site, never a list, never a wildcard"

    def test_a_lookalike_host_does_not_ride_along(self, tmp_path):
        """notexample.com must not receive example.com's cookies."""
        jar = [
            {"name": "sid", "value": SID, "domain": ".example.com"},
            {"name": "other", "value": "other123", "domain": "notexample.com"},
        ]
        log = new_log()
        src = run_read(tmp_path, log=log, pw=FakePlaywrightModule(log, jar=jar))
        assert [c.name for c in src.cookies] == ["sid"]

    def test_existing_port_reads_are_scoped_the_same_way(self):
        log = new_log()
        src = cdp_profile.connect_existing_cdp(
            9222, SITE, playwright_module=FakePlaywrightModule(log)
        )
        assert log["cookie_calls"] == [[SITE]]
        assert {c.domain for c in src.cookies} == {".example.com"}

    def test_no_cookies_for_the_host_is_a_reason_not_an_empty_result(self, tmp_path):
        log = new_log()
        jar = [{"name": "sid", "value": SID, "domain": ".somewhere-else.test"}]
        with pytest.raises(CookieReadError) as e:
            run_read(tmp_path, log=log, pw=FakePlaywrightModule(log, jar=jar))
        assert HOST in str(e.value)
        assert "Log in" in str(e.value)


# ── 6. no cookie value in anything the module says ───────────────────────────


class TestNoCookieValueLeaks:
    def test_a_failing_connect_does_not_echo_the_failure_text(self, tmp_path, monkeypatch):
        """The client's own message can quote a header; only the type is trusted."""
        log = new_log()

        class Poisoned(FakePlaywrightModule):
            def sync_playwright(self):
                log["sync_calls"] += 1
                pw = super().sync_playwright()

                class Chromium:
                    def connect_over_cdp(self, endpoint):
                        raise RuntimeError(f"failed, sent Cookie: sid={SID}")

                pw.chromium = Chromium()
                return pw

        with pytest.raises(CookieReadError) as e:
            run_read(tmp_path, log=log, pw=Poisoned(log))
        assert SID not in str(e.value)
        assert "connect" in str(e.value).lower()

    def test_a_failing_cookie_call_does_not_echo_the_failure_text(self, tmp_path):
        log = new_log()
        pw = FakePlaywrightModule(log, cookie_boom=RuntimeError(f"sid={SID} was rejected"))
        with pytest.raises(CookieReadError) as e:
            run_read(tmp_path, log=log, pw=pw)
        assert SID not in str(e.value)

    def test_the_no_cookies_reason_has_no_value(self, tmp_path):
        log = new_log()
        jar = [{"name": "sid", "value": SID, "domain": ".elsewhere.test"}]
        with pytest.raises(CookieReadError) as e:
            run_read(tmp_path, log=log, pw=FakePlaywrightModule(log, jar=jar))
        assert SID not in str(e.value)

    def test_a_leftover_message_names_the_folder_and_nothing_from_the_jar(self, tmp_path, monkeypatch):
        """The purge reason is an OS error about a path; it never sees a cookie."""
        log = new_log()
        monkeypatch.setattr(cdp_profile, "_purge", lambda path: "OSError: file is in use")
        with pytest.raises(CookieReadError) as e:
            run_read(tmp_path, log=log)

        msg = str(e.value)
        assert log["scratch"][0] in msg, "name the folder, so it can be deleted by hand"
        assert "Delete that folder" in msg
        for secret in (SID, MAIL, BANK):
            assert secret not in msg

    def test_the_provenance_line_is_safe_to_print(self, tmp_path):
        src = run_read(tmp_path)
        line = src.describe()
        for secret in (SID, MAIL, BANK):
            assert secret not in line
        assert HOST in line
        assert "2 cookies" in line

    def test_the_rendered_traceback_never_prints_the_underlying_text(self, tmp_path):
        """`from None` on purpose: a chained message is what a traceback prints."""
        import traceback

        log = new_log()
        pw = FakePlaywrightModule(log, cookie_boom=RuntimeError(f"value was {SID}"))
        with pytest.raises(CookieReadError) as e:
            run_read(tmp_path, log=log, pw=pw)

        rendered = "".join(
            traceback.format_exception(type(e.value), e.value, e.value.__traceback__)
        )
        assert SID not in rendered, "the CDP client's own text must not reach the user"
        assert "could not read cookies over CDP" in rendered


# ── the real helpers, on real temp directories ───────────────────────────────


class TestRealHelpers:
    """The parts that are not faked in the read path above."""

    def test_copy_profile_skips_the_lock_files(self, tmp_path):
        """A copied SingletonLock makes the new instance load no profile at all."""
        src = tmp_path / "User Data"
        (src / "Default").mkdir(parents=True)
        (src / "Default" / "Cookies").write_text("db", encoding="utf-8")
        (src / "SingletonLock").write_text("host-pid", encoding="utf-8")
        dst = tmp_path / "scratch"

        cdp_profile.copy_profile(str(src), str(dst))
        assert (dst / "Default" / "Cookies").is_file()
        assert not (dst / "SingletonLock").exists(), (
            "the lock belongs to the running browser, not to the copy"
        )

    def test_copy_profile_never_writes_to_the_source(self, tmp_path):
        src = tmp_path / "User Data"
        src.mkdir()
        (src / "Preferences").write_text("{}", encoding="utf-8")
        before = sorted(p.name for p in src.iterdir())

        cdp_profile.copy_profile(str(src), str(tmp_path / "scratch"))
        assert sorted(p.name for p in src.iterdir()) == before

    def test_copy_profile_failure_says_to_close_the_browser(self, tmp_path, monkeypatch):
        def boom(*a, **k):
            raise OSError("being used by another process")

        monkeypatch.setattr(cdp_profile.shutil, "copytree", boom)
        with pytest.raises(CookieReadError) as e:
            cdp_profile.copy_profile(str(tmp_path / "User Data"), str(tmp_path / "s"))

        msg = str(e.value)
        assert "scratch folder" in msg
        assert "Close the browser" in msg
        assert "being used by another process" not in msg, (
            "the OS text is dropped; the fix is what the user needs"
        )

    def test_browser_executable_says_how_to_fix_a_missing_browser(self, monkeypatch):
        monkeypatch.setattr(cdp_profile.shutil, "which", lambda name: None)
        for var in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(cdp_profile.os.path, "isfile", lambda p: False)
        with pytest.raises(CookieReadError) as e:
            cdp_profile.browser_executable("chrome")
        msg = str(e.value)
        assert "--remote-debugging-port" in msg, "name the way out, not just the problem"
        assert "--cdp-port" in msg

    def test_browser_executable_finds_one_on_path(self, monkeypatch):
        monkeypatch.setattr(
            cdp_profile.shutil, "which", lambda name: "/usr/bin/" + name
        )
        assert cdp_profile.browser_executable("brave").endswith("brave")

    def test_the_debugger_wait_gives_up_instead_of_hanging(self):
        """A closed port has to fail fast enough to be reported, not waited on."""
        ticks = iter([0.0, 0.5, 1.0, 99.0, 99.0, 99.0])
        assert cdp_profile._wait_for_debugger(1, lambda: next(ticks), 2.0) is False

    def test_the_debugger_wait_notices_a_listening_port(self):
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            port = s.getsockname()[1]
            assert cdp_profile._wait_for_debugger(port, lambda: 0.0, 2.0) is True

    def test_an_already_dead_process_is_not_killed_again(self, monkeypatch):
        class DeadProc:
            pid = 0

            def poll(self):
                return 0

        monkeypatch.setattr(
            cdp_profile.subprocess, "run", tripwire("killed a process that had exited")
        )
        cdp_profile.LaunchedBrowser(DeadProc()).close()


# ── the non-Chromium path is somebody else's job ─────────────────────────────


class TestReadSiteCookies:
    def test_delegates_to_session_cookies(self, monkeypatch):
        seen = {}

        def fake_for_site(site, browser=""):
            seen["args"] = (site, browser)
            return "sentinel"

        monkeypatch.setattr(cdp_profile, "for_site", fake_for_site)
        assert cdp_profile.read_site_cookies("https://a.example/", "zen") == "sentinel"
        assert seen["args"] == ("https://a.example/", "zen")

    def test_defaults_to_no_browser(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            cdp_profile, "for_site", lambda site, browser="": seen.setdefault("b", browser)
        )
        cdp_profile.read_site_cookies("https://a.example/")
        assert seen["b"] == ""
