# -*- coding: utf-8 -*-
"""CDP attach for a LinkedIn read. No socket, and no request to LinkedIn.

Discovery is a file plus an injected probe. The tab helper is given a fake
browser. Profile wiring stubs the DevTools connection, so nothing here
dials 127.0.0.1 or asks linkedin.com for a page.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import pytest

from searchts import linkedin
from searchts import linkedin_attach as la
from searchts import linkedin_feed as lf
from searchts.unlocker import FetchResult, UnlockerError, fetch

CHECKBOX = 'Allow remote debugging for this browser instance'
PROFILE = "https://www.linkedin.com/in/ada-lovelace/"
PROSE = "Ada wrote notes about the engine. " * 40


def _running(_profile: str) -> bool:
    return True


def _stopped(_profile: str) -> bool:
    return False


def test_parse_active_port_reads_the_port_and_the_browser_path():
    parsed = la.parse_active_port("9222\n/devtools/browser/abc\n")
    assert parsed == la.ActivePort(9222, "/devtools/browser/abc")
    assert la.endpoint_for(parsed.port, parsed.ws_path) == (
        "ws://127.0.0.1:9222/devtools/browser/abc"
    )


def test_parse_active_port_accepts_a_port_only_file_and_crlf():
    assert la.parse_active_port("9333\r\n") == la.ActivePort(9333, "")
    assert la.endpoint_for(9333, "") == "http://127.0.0.1:9333"
    extra = la.parse_active_port("9222\r\n\r\n/devtools/browser/xyz\r\nignored\r\n")
    assert extra == la.ActivePort(9222, "/devtools/browser/xyz")


def test_parse_active_port_rejects_blank_and_garbage():
    assert la.parse_active_port("") is None
    assert la.parse_active_port("\n\n") is None
    assert la.parse_active_port("not-a-port\n/devtools/browser\n") is None
    assert la.parse_active_port("0\n/devtools/browser\n") is None
    assert la.parse_active_port("65536\n") is None
    # A path that is not a path does not invent a WebSocket URL.
    assert la.parse_active_port("9222\nnot a path\n") == la.ActivePort(9222, "")


def test_inspect_urls_name_each_browser():
    assert la.inspect_url("chrome") == "chrome://inspect/#remote-debugging"
    assert la.inspect_url("chromium") == "chrome://inspect/#remote-debugging"
    assert la.inspect_url("vivaldi") == "vivaldi://inspect/#remote-debugging"
    assert la.inspect_url("edge") == "edge://inspect/#remote-debugging"
    assert la.inspect_url("brave") == "brave://inspect/#remote-debugging"


def test_user_data_dirs_follow_the_platform(monkeypatch):
    monkeypatch.setenv("HOME", "/home/ada")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(la.os, "name", "posix")
    monkeypatch.setattr(la.sys, "platform", "linux")
    linux = la.candidate_user_data_dirs("vivaldi")
    assert linux[0] == "/home/ada/.config/vivaldi"
    assert linux[1].endswith("/Library/Application Support/Vivaldi")

    monkeypatch.setattr(la.sys, "platform", "darwin")
    mac = la.candidate_user_data_dirs("chrome")
    assert mac[0] == "/home/ada/Library/Application Support/Google/Chrome"

    monkeypatch.setattr(la.os, "name", "nt")
    # ``os.path.join`` uses this machine's separator. The layout is what
    # matters, and a Windows run joins with backslashes on its own.
    local = os.path.join("C:", "Users", "ada", "AppData", "Local")
    monkeypatch.setenv("LOCALAPPDATA", local)
    windows = la.candidate_user_data_dirs("edge")
    assert windows == [os.path.join(local, "Microsoft", "Edge", "User Data")]
    brave = la.candidate_user_data_dirs("brave")
    assert brave == [
        os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data")
    ]


def test_parse_mode_accepts_aliases_and_rejects_a_typo(monkeypatch):
    monkeypatch.delenv("SEARCHTS_LINKEDIN_ATTACH", raising=False)
    assert la.parse_mode(None) == "auto"
    assert la.parse_mode("on") == "on"
    assert la.parse_mode("YES") == "on"
    assert la.parse_mode("0") == "off"
    assert la.parse_mode("false") == "off"
    monkeypatch.setenv("SEARCHTS_LINKEDIN_ATTACH", "off")
    assert la.parse_mode(None) == "off"
    assert la.parse_mode("auto") == "auto"
    with pytest.raises(ValueError) as ei:
        la.parse_mode("sometimes")
    assert str(ei.value) == "SEARCHTS_LINKEDIN_ATTACH must be auto, on or off"


def _decide(tmp_path, **kwargs):
    kwargs.setdefault("profile", str(tmp_path))
    kwargs.setdefault("kept_browser_name", "")
    kwargs.setdefault("is_running", _stopped)
    kwargs.setdefault("probe", lambda _port: (_ for _ in ()).throw(AssertionError("probe")))
    return la.decide(**kwargs)


def test_auto_attaches_when_the_port_file_is_live(tmp_path):
    (tmp_path / "DevToolsActivePort").write_text(
        "9222\n/devtools/browser/abc\n", encoding="utf-8"
    )
    seen = {}

    def probe(port):
        seen["port"] = port
        return True

    decision = _decide(
        tmp_path,
        mode="auto",
        executable="/usr/bin/vivaldi",
        is_running=_running,
        probe=probe,
    )
    assert decision.action == "attach"
    assert decision.endpoint == "ws://127.0.0.1:9222/devtools/browser/abc"
    assert decision.browser == "vivaldi"
    assert seen["port"] == 9222
    assert decision.user_data == str(tmp_path)


def test_auto_refuses_when_the_browser_is_running_and_debugging_is_off(tmp_path):
    decision = _decide(
        tmp_path,
        mode="auto",
        executable="/usr/bin/vivaldi",
        is_running=_running,
    )
    assert decision.action == "refuse"
    assert "vivaldi://inspect/#remote-debugging" in decision.message
    assert CHECKBOX in decision.message
    assert "nothing was requested" in decision.message


def test_a_dead_port_is_the_same_refusal_as_a_missing_file(tmp_path):
    (tmp_path / "DevToolsActivePort").write_text("9222\n/devtools/browser/abc\n", encoding="utf-8")
    decision = _decide(
        tmp_path,
        mode="auto",
        executable="brave-browser",
        is_running=_running,
        probe=lambda _port: False,
    )
    assert decision.action == "refuse"
    assert "brave://inspect/#remote-debugging" in decision.message
    assert CHECKBOX in decision.message


def test_a_stale_port_file_is_ignored_when_the_browser_is_not_running(tmp_path):
    (tmp_path / "DevToolsActivePort").write_text("9222\n/devtools/browser/abc\n", encoding="utf-8")
    decision = _decide(tmp_path, mode="auto", executable="/usr/bin/google-chrome")
    assert decision.action == "launch"


def test_on_does_not_launch_a_browser_that_is_not_running(tmp_path):
    (tmp_path / "DevToolsActivePort").write_text("9222\n/devtools/browser/abc\n", encoding="utf-8")
    decision = _decide(tmp_path, mode="on", executable="/usr/bin/google-chrome-stable")
    assert decision.action == "refuse"
    assert "SEARCHTS_LINKEDIN_ATTACH=on will not launch one" in decision.message
    assert "chrome://inspect/#remote-debugging" in decision.message
    assert CHECKBOX in decision.message


def test_off_does_not_attach_even_when_the_port_is_live(tmp_path):
    (tmp_path / "DevToolsActivePort").write_text("9222\n/devtools/browser/abc\n", encoding="utf-8")
    decision = _decide(
        tmp_path,
        mode="off",
        executable="/usr/bin/google-chrome",
        is_running=_running,
        probe=lambda _port: True,
    )
    assert decision.action == "launch"


def test_an_explicit_endpoint_attaches_even_when_the_mode_is_off(tmp_path):
    decision = _decide(
        tmp_path,
        mode="off",
        endpoint="127.0.0.1:9222",
        is_running=_running,
    )
    assert decision.action == "attach"
    assert decision.endpoint == "http://127.0.0.1:9222"


def test_an_explicit_endpoint_has_to_be_on_this_machine():
    with pytest.raises(ValueError) as ei:
        la.decide(mode="on", endpoint="http://example.com:9222", kept_browser_name="")
    assert "127.0.0.1" in str(ei.value)
    assert "Nothing was requested" in str(ei.value)


def test_firefox_chosen_for_attach_stays_on_cookie_copy():
    on = la.decide(
        mode="on",
        executable="/usr/bin/zen",
        kept_browser_name="",
        is_running=_running,
    )
    assert on.action == "refuse"
    assert "Firefox-family" in on.message
    assert "cookie copy only" in on.message
    assert "zen, firefox, librewolf, waterfox, floorp, mullvad" in on.message

    auto = la.decide(
        mode="auto",
        profile="/home/ada/.librewolf",
        kept_browser_name="",
        is_running=_stopped,
    )
    assert auto.action == "refuse"
    assert "LibreWolf" in auto.message


def test_a_kept_firefox_login_in_auto_mode_still_launches():
    decision = la.decide(
        mode="auto",
        kept_browser_name="firefox",
        is_running=_running,
        probe=lambda _port: (_ for _ in ()).throw(AssertionError("probe")),
    )
    assert decision.action == "launch"
    assert decision.browser == "firefox"


def test_opera_is_not_attached_when_it_was_chosen():
    chosen = la.decide(
        mode="auto",
        executable="/usr/bin/opera",
        kept_browser_name="",
        is_running=_running,
    )
    assert chosen.action == "refuse"
    assert "Opera" in chosen.message
    assert "Chrome, Vivaldi, Edge, Brave or Chromium" in chosen.message

    kept = la.decide(mode="auto", kept_browser_name="opera", is_running=_running)
    assert kept.action == "launch"


def test_decide_looks_only_at_the_profile_it_was_given(tmp_path):
    seen = []

    def running(path):
        seen.append(path)
        return False

    decision = la.decide(
        mode="auto",
        profile=str(tmp_path),
        kept_browser_name="chrome",
        is_running=running,
    )
    assert decision.action == "launch"
    assert seen == [str(tmp_path)]


def test_open_tab_closes_only_the_tab_it_opened():
    events = []

    class Page:
        def close(self):
            events.append("page.close")

    class Context:
        def new_page(self):
            events.append("new_page")
            return Page()

    class Browser:
        contexts = []

        def __init__(self):
            self.contexts = [Context()]

        def new_context(self):
            raise AssertionError("a CDP attach must not open a new context")

        def close(self):
            raise AssertionError("a CDP attach must not close the browser")

    browser = Browser()

    def connect(endpoint):
        events.append(("connect", endpoint))
        return browser

    with la.open_tab("ws://127.0.0.1:9222/devtools/browser/abc", connect=connect) as page:
        events.append("body")
        assert page is not None
    assert events == [
        ("connect", "ws://127.0.0.1:9222/devtools/browser/abc"),
        "new_page",
        "body",
        "page.close",
    ]


def test_open_tab_closes_the_tab_when_the_body_fails():
    closed = []

    class Page:
        def close(self):
            closed.append("page")

    class Browser:
        def __init__(self):
            self.contexts = [type("C", (), {"new_page": lambda self: Page()})()]

        def close(self):
            raise AssertionError("a CDP attach must not close the browser")

    with pytest.raises(RuntimeError, match="navigation failed"):
        with la.open_tab("ws://127.0.0.1:9/devtools/browser/x", connect=lambda _e: Browser()):
            raise RuntimeError("navigation failed")
    assert closed == ["page"]


def test_open_tab_refuses_when_there_is_no_window_and_names_a_failed_connect():
    class Browser:
        contexts = []

        def new_context(self):
            raise AssertionError("a CDP attach must not open a new context")

    with pytest.raises(la.AttachError) as ei:
        with la.open_tab("ws://127.0.0.1:9/x", connect=lambda _e: Browser()):
            raise AssertionError("the body must not run")
    assert "no open window" in str(ei.value)
    assert "new browser context is not opened" in str(ei.value)

    def boom(_endpoint):
        raise OSError("refused")

    with pytest.raises(la.AttachError) as ei:
        with la.open_tab("ws://127.0.0.1:9/x", connect=boom):
            raise AssertionError("the body must not run")
    assert "allow remote debugging" in str(ei.value)
    assert "Nothing was requested from LinkedIn" in str(ei.value)


def test_attach_source_never_closes_the_browser_or_opens_a_context():
    text = Path(la.__file__).read_text(encoding="utf-8")
    assert "browser.close" not in text
    assert ".new_context(" not in text
    assert "page.close" in text


class _Guard:
    def __init__(self):
        self.calls = []

    def before_load(self):
        self.calls.append("before")

    def record(self, _signal):
        self.calls.append("record")


def test_read_feed_stops_before_a_browser_when_debugging_is_off(monkeypatch, tmp_path):
    monkeypatch.setattr(la, "browser_is_running", _running)
    monkeypatch.setattr(
        la, "probe_port", lambda port, timeout=0.2: (_ for _ in ()).throw(AssertionError("probe"))
    )
    opened = []
    monkeypatch.setattr(lf, "_browser_page", lambda *a, **k: opened.append(a))
    guard = _Guard()
    with pytest.raises(lf.FeedUnavailable) as ei:
        lf.read_feed(
            profile=str(tmp_path),
            executable="/usr/bin/vivaldi",
            attach="auto",
            guard=guard,
        )
    assert "vivaldi://inspect/#remote-debugging" in str(ei.value)
    assert CHECKBOX in str(ei.value)
    assert opened == []
    assert guard.calls == []


def test_a_recorded_stop_wins_over_the_debugging_toggle(monkeypatch, tmp_path):
    monkeypatch.setattr(
        linkedin,
        "current_stop",
        lambda now=None: linkedin.Stop("rate-limit", 0.0, 10**12),
    )
    monkeypatch.setattr(
        la, "browser_is_running", lambda _p: (_ for _ in ()).throw(AssertionError("decide"))
    )
    opened = []
    monkeypatch.setattr(lf, "_browser_page", lambda *a, **k: opened.append(a))
    with pytest.raises(lf.FeedUnavailable) as ei:
        lf.read_feed(profile=str(tmp_path), attach="auto", executable="/usr/bin/google-chrome")
    assert "remote debugging" not in str(ei.value)
    assert "login resume" in str(ei.value)
    assert opened == []


def test_read_feed_attach_books_the_guard_before_the_tab(monkeypatch, tmp_path):
    (tmp_path / "DevToolsActivePort").write_text(
        "9333\n/devtools/browser/abc\n", encoding="utf-8"
    )
    monkeypatch.setattr(la, "browser_is_running", _running)
    monkeypatch.setattr(la, "probe_port", lambda port, timeout=0.2: True)
    order = []
    seen = {}

    class Page:
        def goto(self, url, **_kwargs):
            order.append("goto")
            self.url = url

    class Opened:
        def __enter__(self):
            order.append("browser")
            return Page()

        def __exit__(self, *_exc):
            return False

    def open_page(profile, executable, cdp, url):
        seen["cdp"] = cdp
        return Opened()

    def walk(page, **_kwargs):
        order.append("walk")
        page.goto(lf.FEED_URL)
        return lf.FeedRead(
            posts=[lf.Post("1", "Ada", "notes", "1h")],
            text="Ada\nnotes",
            stop="done",
        )

    monkeypatch.setattr(lf, "_browser_page", open_page)
    monkeypatch.setattr(lf, "walk", walk)

    class Guard(_Guard):
        def before_load(self):
            order.append("guard")

    lf.read_feed(
        profile=str(tmp_path),
        executable="/usr/bin/google-chrome",
        attach="auto",
        guard=Guard(),
    )
    assert seen["cdp"] == "ws://127.0.0.1:9333/devtools/browser/abc"
    assert order == ["guard", "browser", "walk", "goto"]


def _page(events):
    class Page:
        url = PROFILE

        def route(self, *_args, **_kwargs):
            events.append("guard")

        def goto(self, url, **_kwargs):
            events.append(("goto", url))
            return None

        def content(self):
            return f"<html><body><p>{PROSE}</p></body></html>"

        def wait_for_load_state(self, *_args, **_kwargs):
            return None

        def wait_for_timeout(self, _ms):
            return None

        def evaluate(self, _script):
            return 0

        def close(self):
            events.append("page.close")

    return Page()


def test_a_profile_read_attaches_before_any_other_rung(monkeypatch, tmp_path):
    (tmp_path / "DevToolsActivePort").write_text(
        "9222\n/devtools/browser/abc\n", encoding="utf-8"
    )
    monkeypatch.setenv("SEARCHTS_LINKEDIN_PROFILE", str(tmp_path))
    monkeypatch.setenv("SEARCHTS_LINKEDIN_CHROME", "/usr/bin/vivaldi")
    monkeypatch.delenv("SEARCHTS_LINKEDIN_CDP", raising=False)
    monkeypatch.setattr(la, "browser_is_running", _running)
    monkeypatch.setattr(la, "probe_port", lambda port, timeout=0.2: True)
    events = []

    @contextmanager
    def fake_tab(endpoint, *, connect=None):
        events.append(("connect", endpoint))
        page = _page(events)
        try:
            yield page
        finally:
            page.close()

    monkeypatch.setattr(la, "open_tab", fake_tab)
    monkeypatch.setattr("searchts.unlocker.html_to_text", lambda body, url=None: PROSE)
    monkeypatch.setattr(
        "searchts.unlocker._fetch_curl_cffi",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("curl")),
    )
    monkeypatch.setattr(
        "searchts.unlocker._fetch_jina",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("jina")),
    )
    monkeypatch.setattr(
        "searchts.unlocker._fetch_stealth",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("launch")),
    )
    loads = []
    real_enter = linkedin.exclusive_load.__enter__

    def enter(self):
        loads.append("load")
        return real_enter(self)

    monkeypatch.setattr(linkedin.exclusive_load, "__enter__", enter)

    result = fetch(PROFILE, use_memory=False, linkedin_attach="auto")
    assert result.backend == "stealth-browser"
    assert "Ada wrote notes" in result.text
    assert loads == ["load"]
    kinds = [
        item[0] if isinstance(item, tuple) else item
        for item in events
        if item == "page.close" or item == "guard" or (
            isinstance(item, tuple) and item[0] in ("connect", "goto")
        )
    ]
    assert kinds == ["connect", "guard", "goto", "page.close"]


def test_profile_attach_books_the_load_between_connect_and_goto(monkeypatch, tmp_path):
    (tmp_path / "DevToolsActivePort").write_text("9222\n/devtools/browser/abc\n", encoding="utf-8")
    monkeypatch.setenv("SEARCHTS_LINKEDIN_PROFILE", str(tmp_path))
    monkeypatch.setenv("SEARCHTS_LINKEDIN_CHROME", "/usr/bin/google-chrome")
    monkeypatch.delenv("SEARCHTS_LINKEDIN_CDP", raising=False)
    monkeypatch.setattr(la, "browser_is_running", _running)
    monkeypatch.setattr(la, "probe_port", lambda port, timeout=0.2: True)
    order = []

    @contextmanager
    def fake_tab(endpoint, *, connect=None):
        order.append("connect")
        page = _page(order)
        try:
            yield page
        finally:
            page.close()

    class Slot:
        def __enter__(self):
            order.append("load")
            return self

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(la, "open_tab", fake_tab)
    monkeypatch.setattr(linkedin, "exclusive_load", Slot)
    monkeypatch.setattr("searchts.unlocker.html_to_text", lambda body, url=None: PROSE)
    result = fetch(PROFILE, use_memory=False, linkedin_attach="on")
    assert result.backend == "stealth-browser"
    kinds = [item[0] if isinstance(item, tuple) else item for item in order]
    assert kinds[0] == "connect"
    assert kinds.index("load") < kinds.index("guard") < kinds.index("goto")
    assert kinds.index("goto") < kinds.index("page.close")


def test_a_profile_read_stops_before_curl_when_debugging_is_off(monkeypatch, tmp_path):
    monkeypatch.setenv("SEARCHTS_LINKEDIN_PROFILE", str(tmp_path))
    monkeypatch.setenv("SEARCHTS_LINKEDIN_CHROME", "/usr/bin/vivaldi")
    monkeypatch.delenv("SEARCHTS_LINKEDIN_CDP", raising=False)
    monkeypatch.setattr(la, "browser_is_running", _running)
    called = []
    monkeypatch.setattr(
        "searchts.unlocker._fetch_curl_cffi",
        lambda *a, **k: called.append("curl"),
    )
    monkeypatch.setattr(
        "searchts.unlocker._fetch_stealth",
        lambda *a, **k: called.append("launch"),
    )
    with pytest.raises(UnlockerError) as ei:
        fetch(PROFILE, use_memory=False, linkedin_attach="auto")
    assert ei.value.attempts[0][0] == "linkedin-attach"
    assert "vivaldi://inspect/#remote-debugging" in ei.value.attempts[0][1]
    assert CHECKBOX in ei.value.attempts[0][1]
    assert called == []


def test_a_bad_attach_mode_is_a_usage_error_before_any_rung(monkeypatch):
    called = []
    monkeypatch.setattr(
        "searchts.unlocker._fetch_curl_cffi",
        lambda *a, **k: called.append("curl"),
    )
    with pytest.raises(UnlockerError) as ei:
        fetch(PROFILE, use_memory=False, linkedin_attach="sometimes")
    assert "SEARCHTS_LINKEDIN_ATTACH must be auto, on or off" in str(ei.value)
    assert called == []


def test_profile_sections_keep_the_callers_attach_mode(monkeypatch):
    from searchts import unlocker

    seen = []

    def section(url, **kwargs):
        seen.append(kwargs.get("linkedin_attach"))
        return FetchResult("curl_cffi", "Experience\n\nEngineer at Acme\n" + PROSE, 200)

    monkeypatch.setattr(unlocker, "_read_linkedin_section", section)
    result = FetchResult("stealth-browser", "Someone Example\n" + PROSE, 200)
    result.authenticated = True
    unlocker._linkedin_finish(
        result,
        site=PROFILE,
        cookies=[],
        backends=None,
        proxy=None,
        proxy_trusted=False,
        details=True,
        linkedin_attach="on",
    )
    assert seen
    assert set(seen) == {"on"}


def test_an_attached_load_that_is_paced_is_the_pacing_refusal(monkeypatch, tmp_path):
    (tmp_path / "DevToolsActivePort").write_text("9222\n/devtools/browser/abc\n", encoding="utf-8")
    monkeypatch.setenv("SEARCHTS_LINKEDIN_PROFILE", str(tmp_path))
    monkeypatch.setenv("SEARCHTS_LINKEDIN_CHROME", "/usr/bin/google-chrome")
    monkeypatch.delenv("SEARCHTS_LINKEDIN_CDP", raising=False)
    monkeypatch.setattr(la, "browser_is_running", _running)
    monkeypatch.setattr(la, "probe_port", lambda port, timeout=0.2: True)
    order = []

    @contextmanager
    def fake_tab(endpoint, *, connect=None):
        order.append("connect")
        page = _page(order)
        try:
            yield page
        finally:
            page.close()

    class Slot:
        def __enter__(self):
            order.append("load")
            raise linkedin.Paced("hour window", "LinkedIn load budget: wait")

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(la, "open_tab", fake_tab)
    monkeypatch.setattr(linkedin, "exclusive_load", Slot)
    with pytest.raises(UnlockerError) as ei:
        fetch(PROFILE, use_memory=False, linkedin_attach="on")
    assert ei.value.hint == "LinkedIn load budget: wait"
    assert any(backend == "linkedin-loads" for backend, _why in ei.value.attempts)
    assert "goto" not in [item[0] if isinstance(item, tuple) else item for item in order]
    assert "page.close" in order
    assert order[0] == "connect"
