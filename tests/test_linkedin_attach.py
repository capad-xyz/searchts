# -*- coding: utf-8 -*-
"""CDP attach for a LinkedIn read. No socket, and no request to LinkedIn.

Discovery is a file plus an injected probe. The tab helper is given a fake
browser. Profile wiring stubs the DevTools connection, so nothing here
dials 127.0.0.1 or asks linkedin.com for a page.
"""

from __future__ import annotations

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
    """Linux, macOS and Windows layouts, on whichever OS is running the test.

    ``os.path`` is this machine's path module. On Windows ``expanduser("~")``
    reads ``USERPROFILE``, not ``HOME``, and ``join`` uses backslashes, so a
    patched ``HOME=/home/ada`` still came out as ``C:\\Users\\...\\.config``.
    The posix cases use ``posixpath`` and the Windows case uses ``ntpath``,
    which is what ``os.path`` is on those systems. The directory layout is
    still the thing under test.
    """
    import ntpath
    import posixpath

    monkeypatch.setenv("HOME", "/home/ada")
    monkeypatch.delenv("USERPROFILE", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(la.os, "path", posixpath)
    monkeypatch.setattr(la.os, "name", "posix")
    monkeypatch.setattr(la.sys, "platform", "linux")
    assert la.candidate_user_data_dirs("vivaldi") == [
        "/home/ada/.config/vivaldi",
        "/home/ada/Library/Application Support/Vivaldi",
    ]

    monkeypatch.setattr(la.sys, "platform", "darwin")
    assert la.candidate_user_data_dirs("chrome") == [
        "/home/ada/Library/Application Support/Google/Chrome",
        "/home/ada/.config/google-chrome",
    ]

    monkeypatch.setattr(la.os, "name", "nt")
    monkeypatch.setattr(la.os, "path", ntpath)
    local = "C:\\Users\\ada\\AppData\\Local"
    monkeypatch.setenv("LOCALAPPDATA", local)
    assert la.candidate_user_data_dirs("edge") == [
        ntpath.join(local, "Microsoft", "Edge", "User Data")
    ]
    assert la.candidate_user_data_dirs("brave") == [
        ntpath.join(local, "BraveSoftware", "Brave-Browser", "User Data")
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


class _Cdp:
    """A browser-wide DevTools session over fixed targets.

    ``windows`` maps a target id to a window id. A target missing from it is
    one ``Browser.getWindowForTarget`` refuses, like a browser UI page.
    """

    def __init__(self, events, targets, windows=None, anchor="anchor-1"):
        self.events = events
        self.targets = targets
        self.windows = windows or {}
        self.anchor = anchor
        self.detached = False

    def send(self, method, params=None):
        self.events.append((method, params))
        if method == "Target.getTargets":
            return {
                "targetInfos": [
                    dict(info, browserContextId="ctx-1") for info in self.targets
                ]
            }
        if method == "Browser.getWindowForTarget":
            window_id = self.windows.get(params["targetId"])
            if window_id is None:
                raise RuntimeError("Browser window not found")
            return {"windowId": window_id, "bounds": {"windowState": "normal"}}
        if method in ("Target.activateTarget", "Target.closeTarget"):
            return {}
        if method == "Target.createTarget":
            return {"targetId": self.anchor}
        raise AssertionError(method)

    def detach(self):
        self.detached = True


class _PageCdp:
    """The session behind one page, enough to read its target id."""

    def __init__(self, events, target_id):
        self.events = events
        self.target_id = target_id
        self.detached = False

    def send(self, method, params=None):
        assert method == "Target.getTargetInfo"
        return {"targetInfo": {"targetId": self.target_id}}

    def detach(self):
        self.detached = True


class _Page:
    def __init__(self, display_mode=True):
        self.display_mode = display_mode
        self.closed = False

    def evaluate(self, script):
        assert script == la._DISPLAY_MODE_BROWSER
        return self.display_mode

    def close(self):
        self.closed = True


class _Context:
    def __init__(self, pages, sessions, events):
        self._pages = list(pages)
        self._sessions = list(sessions)
        self.events = events

    def new_page(self):
        self.events.append("new_page")
        return self._pages.pop(0)

    def new_cdp_session(self, _page):
        return self._sessions.pop(0)

    def new_context(self):
        raise AssertionError("a CDP attach must not open a new context")


class _Browser:
    def __init__(self, context, cdp):
        self.contexts = [context]
        self.cdp = cdp

    def new_browser_cdp_session(self):
        return self.cdp

    def close(self):
        raise AssertionError("a CDP attach must not close the browser")


def _normal_window_browser(events, *, page=None, target_id="tab-1", window_id=7):
    page = page or _Page()
    cdp = _Cdp(
        events,
        [{"targetId": "web", "type": "page", "url": "https://example.test/inbox"}],
        {"web": window_id},
    )
    context = _Context([page], [_PageCdp(events, target_id)], events)
    return _Browser(context, cdp), page


def test_page_windows_keeps_normal_pages_and_skips_app_and_browser_ui():
    targets = [
        {"targetId": "app", "type": "app", "url": "https://app.example.test/"},
        {"targetId": "ext", "type": "page", "url": "chrome-extension://mpognobbkildjkofajifpdfhcoklimli/panel.html"},
        {"targetId": "vivaldi", "type": "page", "url": "vivaldi://settings/"},
        {"targetId": "dev", "type": "page", "url": "devtools://devtools/bundled/inspector.html"},
        {"targetId": "chrome", "type": "page", "url": "chrome://settings/"},
        {"targetId": "edge", "type": "page", "url": "edge://settings/"},
        {"targetId": "ui", "type": "browser_ui", "url": "chrome://omnibox-popup.top-chrome/"},
        {"targetId": "sw", "type": "service_worker", "url": "chrome-extension://x/sw.js"},
        {"targetId": "bg", "type": "background_page", "url": "chrome-extension://x/bg.html"},
        {"targetId": "view", "type": "webview", "url": "https://example.test/embed"},
        {"targetId": "frame", "type": "iframe", "url": "https://example.test/frame"},
        {"targetId": "blank", "type": "page", "url": "about:blank"},
        {"targetId": "web", "type": "page", "url": "https://example.test/page"},
        {"targetId": "blank2", "type": "page", "url": "about:blank"},
        {"targetId": "orphan", "type": "page", "url": "https://example.test/orphan"},
    ]
    cdp = _Cdp([], targets, {"blank": 7, "web": 7, "blank2": 8})

    windows = la.page_windows(cdp)

    assert [(window.window_id, window.target_id) for window in windows] == [
        (7, "web"),
        (8, "blank2"),
    ]


def test_new_tab_activates_a_normal_window_and_closes_only_its_target():
    events = []
    browser, page = _normal_window_browser(events)

    tab = la.new_tab(browser, "vivaldi")

    assert tab.page is page
    assert tab.target_id == "tab-1"
    assert [event for event in events if event[0] == "Target.activateTarget"] == [
        ("Target.activateTarget", {"targetId": "web"})
    ]
    assert "Target.createTarget" not in [event[0] for event in events]
    assert page.closed is False

    tab.close()

    assert [event for event in events if event[0] == "Target.closeTarget"] == [
        ("Target.closeTarget", {"targetId": "tab-1"})
    ]
    assert page.closed is False


def test_new_tab_skips_a_window_whose_tab_reports_an_app_display_mode():
    events = []
    pwa_page = _Page(display_mode=False)
    normal_page = _Page()
    cdp = _Cdp(
        events,
        [
            {"targetId": "pwa", "type": "page", "url": "https://app.example.test/"},
            {"targetId": "web", "type": "page", "url": "https://example.test/"},
        ],
        {"pwa": 1, "web": 2},
    )
    context = _Context(
        [pwa_page, normal_page],
        [_PageCdp(events, "web-tab")],
        events,
    )

    tab = la.new_tab(_Browser(context, cdp))

    assert tab.page is normal_page
    assert pwa_page.closed is True
    activated = [
        event[1]["targetId"]
        for event in events
        if event[0] == "Target.activateTarget"
    ]
    assert activated == ["pwa", "web"]


def test_new_tab_opens_a_normal_window_when_every_window_is_an_app():
    events = []
    page = _Page()
    cdp = _Cdp(
        events,
        [
            {"targetId": "app", "type": "app", "url": "https://app.example.test/home"},
            {"targetId": "ui", "type": "page", "url": "chrome-extension://mpognobbkildjkofajifpdfhcoklimli/panel.html"},
            {"targetId": "vivaldi", "type": "page", "url": "vivaldi://settings/"},
        ],
        {},
    )
    context = _Context([page], [_PageCdp(events, "tab-9")], events)

    tab = la.new_tab(_Browser(context, cdp), "vivaldi")

    assert tab.page is page
    assert tab.target_id == "tab-9"
    assert [event for event in events if event[0] == "Target.createTarget"] == [
        (
            "Target.createTarget",
            {"url": "about:blank", "newWindow": True, "browserContextId": "ctx-1"},
        )
    ]
    assert [event for event in events if event[0] == "Target.closeTarget"] == [
        ("Target.closeTarget", {"targetId": "anchor-1"})
    ]
    assert page.closed is False

    tab.close()

    closed = [event[1]["targetId"] for event in events if event[0] == "Target.closeTarget"]
    assert closed == ["anchor-1", "tab-9"]


def test_new_tab_refuses_when_even_a_new_window_is_an_app_window():
    events = []
    first = _Page(display_mode=False)
    second = _Page(display_mode=False)
    cdp = _Cdp(
        events,
        [{"targetId": "pwa", "type": "page", "url": "https://app.example.test/"}],
        {"pwa": 1},
    )
    context = _Context([first, second], [], events)

    with pytest.raises(la.AttachError) as ei:
        la.new_tab(_Browser(context, cdp), "vivaldi")

    message = str(ei.value)
    assert "Vivaldi did not give the read a tab in a normal window" in message
    assert "installed app, PWA" in message
    assert "left open" in message
    assert "Nothing was requested from LinkedIn" in message
    assert first.closed is True and second.closed is True
    assert [event for event in events if event[0] == "Target.closeTarget"] == [
        ("Target.closeTarget", {"targetId": "anchor-1"})
    ]


def test_new_tab_names_a_browser_that_cannot_list_windows():
    class Browser:
        contexts = [object()]

        def new_browser_cdp_session(self):
            raise OSError("no session")

    with pytest.raises(la.AttachError) as ei:
        la.new_tab(Browser(), "edge")

    message = str(ei.value)
    assert "Edge could not list its windows over the DevTools port" in message
    assert "left alone" in message
    assert "Nothing was requested from LinkedIn" in message


def test_open_tab_closes_only_the_tab_it_opened():
    events = []
    browser, page = _normal_window_browser(events)

    def connect(endpoint):
        events.append(("connect", endpoint))
        return browser

    with la.open_tab("ws://127.0.0.1:9222/devtools/browser/abc", connect=connect) as opened:
        events.append("body")
        assert opened is page

    assert events[0] == ("connect", "ws://127.0.0.1:9222/devtools/browser/abc")
    assert "new_page" in events
    assert [event for event in events if event[0] == "Target.closeTarget"] == [
        ("Target.closeTarget", {"targetId": "tab-1"})
    ]
    assert events.index("body") < events.index(
        ("Target.closeTarget", {"targetId": "tab-1"})
    )
    assert page.closed is False
    assert browser.cdp.detached is True


def test_open_tab_closes_the_tab_when_the_body_fails():
    events = []
    browser, page = _normal_window_browser(events)

    with pytest.raises(RuntimeError, match="navigation failed"):
        with la.open_tab(
            "ws://127.0.0.1:9/devtools/browser/x", connect=lambda _e: browser
        ):
            raise RuntimeError("navigation failed")

    assert [event for event in events if event[0] == "Target.closeTarget"] == [
        ("Target.closeTarget", {"targetId": "tab-1"})
    ]
    assert page.closed is False


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
    assert "--remote-debugging-port" not in str(ei.value)
    assert "Open a window" in str(ei.value)
    assert "read again" in str(ei.value)

    def boom(_endpoint):
        raise OSError("refused")

    with pytest.raises(la.AttachError) as ei:
        with la.open_tab("ws://127.0.0.1:9/x", connect=boom):
            raise AssertionError("the body must not run")
    assert "allow remote debugging" in str(ei.value)
    assert "Nothing was requested from LinkedIn" in str(ei.value)


def test_no_window_names_that_browser_and_its_inspect_toggle():
    class Browser:
        contexts = []

        def new_context(self):
            raise AssertionError("a CDP attach must not open a new context")

    for name, label, url in (
        ("vivaldi", "Vivaldi", "vivaldi://inspect/#remote-debugging"),
        ("edge", "Edge", "edge://inspect/#remote-debugging"),
        ("brave", "Brave", "brave://inspect/#remote-debugging"),
    ):
        with pytest.raises(la.AttachError) as ei:
            with la.open_tab(
                "ws://127.0.0.1:9/x",
                connect=lambda _e: Browser(),
                browser_name=name,
            ):
                raise AssertionError("the body must not run")
        message = str(ei.value)
        assert f"Open a window in {label}" in message
        assert f"the toggle at {url} is already on" in message
        assert "read again" in message
        assert "Chrome" not in message
        assert "--remote-debugging-port" not in message


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

    def open_page(profile, executable, cdp, url, browser_name=""):
        seen["cdp"] = cdp
        seen["browser"] = browser_name
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
    def fake_tab(endpoint, *, connect=None, browser_name=""):
        events.append(("connect", endpoint))
        events.append(("named", browser_name))
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
    assert ("named", "vivaldi") in events


def test_profile_attach_books_the_load_between_connect_and_goto(monkeypatch, tmp_path):
    (tmp_path / "DevToolsActivePort").write_text("9222\n/devtools/browser/abc\n", encoding="utf-8")
    monkeypatch.setenv("SEARCHTS_LINKEDIN_PROFILE", str(tmp_path))
    monkeypatch.setenv("SEARCHTS_LINKEDIN_CHROME", "/usr/bin/google-chrome")
    monkeypatch.delenv("SEARCHTS_LINKEDIN_CDP", raising=False)
    monkeypatch.setattr(la, "browser_is_running", _running)
    monkeypatch.setattr(la, "probe_port", lambda port, timeout=0.2: True)
    order = []

    @contextmanager
    def fake_tab(endpoint, *, connect=None, browser_name=""):
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
    def fake_tab(endpoint, *, connect=None, browser_name=""):
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


def test_connect_failure_message_names_the_configured_wait(monkeypatch):
    monkeypatch.setenv("SEARCHTS_LINKEDIN_CDP_TIMEOUT_SECONDS", "75")

    msg = la.connect_failure_message(TimeoutError("Timeout 75000ms exceeded."))
    assert "no Allow click within 75 s" in msg
    assert "Click Allow in the browser, then read again" in msg
    assert "Nothing was requested from LinkedIn" in msg
    assert "SEARCHTS_LINKEDIN_CDP_TIMEOUT_SECONDS sets the wait" in msg

    # A generic client type that carries the timeout wording is still the
    # unanswered dialog, not an unspecified attach fault.
    class ClientError(Exception):
        pass

    assert "no Allow click within 75 s" in la.connect_failure_message(
        ClientError("Timeout 75000ms exceeded.")
    )

    refused = la.connect_failure_message(ConnectionRefusedError("refused"))
    assert "no Allow click" not in refused
    assert "accept that prompt and read again" in refused


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("75", 75.0), ("0", 60.0), ("-5", 60.0), ("9999", 300.0), ("nonsense", 60.0)],
)
def test_cdp_timeout_seconds_is_bounded(monkeypatch, raw, expected):
    monkeypatch.setenv("SEARCHTS_LINKEDIN_CDP_TIMEOUT_SECONDS", raw)
    assert la.cdp_timeout_seconds() == expected
    assert la.cdp_timeout_ms() == int(expected * 1000)
