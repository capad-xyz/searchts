# -*- coding: utf-8 -*-
"""The browser rung renders a client app, or says it could not.

Everything here was measured against a real Chromium on 2026-10-18 before the
change was written, because each test names a defect that was measured rather
than a behaviour that was wished for.

**The wait stopped too early.** A served page whose module bundle mounts its
body 2.2s after load held the same 146 bytes of DOM through +0.25s, +0.50s ...
+2.00s, then jumped to 488 at +2.25s. ``_await_hydration`` stopped on "the
length did not change", which on a client app is what *not started yet* looks
like, so the rung returned the shell: 146 bytes and 8 characters of text, for a
page the browser was fully able to read. Fixtures:
``app_shell_paints_late.html`` and its rendered twin.

**A refusal was laundered into a thin page.** Against a host that answers the
browser with 403 and an empty document, ``page.goto`` reported 403, the DOM
stayed at 39 bytes for 48s, and the ladder said ``stealth-browser: thin-0b``.
The status was promoted to 200 on the way out because an empty document
contains no challenge phrase, so every block test passed it.

**A missing Chromium named the wrong command.** With patchright importable and
no browser downloaded, the rung raised Playwright's own box, which tells the
user to run ``patchright install``: a command that is not in their environment
and installs nothing searchts can use. The brief for this file is that the
error names ``pip install "searchts[browser]"` or ``searchts install --browser``.

Nothing here names a host. Every test drives a saved page or a double, so the
suite is hermetic: no request leaves the machine and no browser is launched.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from searchts import unlocker

FIXTURES = Path(__file__).parent / "fixtures"

#: The shell as served, and the same page after its bundle ran.
SHELL = (FIXTURES / "app_shell_paints_late.html").read_text(encoding="utf-8")
RENDERED = (FIXTURES / "app_shell_paints_late_rendered.html").read_text(
    encoding="utf-8"
)

#: What a server sends beside a 403 when it has nothing to say. The empty
#: document measured on the refused navigation.
EMPTY_DOC = "<html><head></head><body></body></html>"


# ── the wait ─────────────────────────────────────────────────────────────────


class _Page:
    """A page double whose ``content()`` reads follow a script.

    Frames model reads AFTER the first one, since ``_await_hydration`` is handed
    the first read by its caller, exactly as the real rung is.
    """

    def __init__(self, frames: List[Any]) -> None:
        self._frames = frames
        self._i = 0
        self.timeouts: List[int] = []

    def wait_for_timeout(self, ms: int) -> None:
        self.timeouts.append(ms)

    def content(self) -> str:
        frame = self._frames[min(self._i, len(self._frames) - 1)]
        self._i += 1
        if isinstance(frame, Exception):
            raise frame
        return frame


def test_a_page_that_paints_late_is_waited_for():
    """The defect, as a test: the shell held still, and stillness ended the wait.

    Eight polls of the *same* 146 bytes, then the real page. The old rule broke
    on the first of them.
    """
    frames = [SHELL] * 8 + [RENDERED, RENDERED]
    page = _Page(frames)
    out = unlocker._await_hydration(page, SHELL, budget_ms=8000, step_ms=500)
    assert out == RENDERED
    assert len(page.timeouts) >= 9, (
        "the wait ended before the page painted: "
        f"{len(page.timeouts)} poll(s)"
    )


def test_a_painted_page_still_costs_one_poll():
    """The other direction: a page that already has its text does not wait.

    Without this the fix would put the full budget in front of every ordinary
    page, which is the cost that would make it wrong.
    """
    page = _Page([RENDERED])
    out = unlocker._await_hydration(page, RENDERED, budget_ms=8000, step_ms=500)
    assert out == RENDERED
    assert len(page.timeouts) == 1


def test_a_shorter_painted_dom_replaces_a_longer_unpainted_shell():
    shell = "<html><body><script>" + ("loader " * 250) + "</script><p>Loading</p></body></html>"
    painted = "<html><body><main><p>" + ("The page is now painted with readable article text. " * 8) + "</p></main></body></html>"
    assert len(painted) < len(shell)
    page = _Page([painted])
    assert unlocker._await_hydration(page, shell, budget_ms=1000, step_ms=500) == painted


def test_a_shorter_header_does_not_end_a_later_hydration():
    shell = "<html><body><script>" + ("bootstrap " * 450) + "</script><p>Loading</p></body></html>"
    header = "<html><body><header>" + ("Site navigation, account, and a short welcome title. " * 8) + "</header></body></html>"
    article = "<html><body><main><p>" + ("The full article is now visible to readers. " * 30) + "</p></main></body></html>"
    assert len(header) < len(shell) and len(article) < len(shell)
    page = _Page([header, article, article])
    assert unlocker._await_hydration(page, shell, budget_ms=2000, step_ms=500) == article


def test_latest_shorter_painted_dom_survives_when_it_keeps_changing():
    shell = "<html><body><script>" + ("bootstrap " * 300) + "</script></body></html>"
    frames = [
        "<html><body><main><p>"
        + (f"Frame {i} shows an already painted page with readable article text. " * 5)
        + "</p></main></body></html>"
        for i in range(8)
    ]
    assert all(len(frame) < len(shell) for frame in frames)
    page = _Page(frames)
    assert unlocker._await_hydration(page, shell, budget_ms=4000, step_ms=500) == frames[-1]


def test_a_page_that_never_paints_is_bounded_by_its_budget():
    """Waiting longer must not mean waiting forever.

    A shell that never fills in ends at the budget and is then judged by the
    extractor, which is the honest verdict for it. It does not get an unbounded
    wait and it does not get a pass.
    """
    page = _Page([SHELL])
    out = unlocker._await_hydration(page, SHELL, budget_ms=3000, step_ms=500)
    assert out == SHELL
    assert len(page.timeouts) == 6, "the budget was not the bound"


def test_the_rung_returns_the_painted_page_not_the_shell(monkeypatch):
    """The user-visible half: the rung's own return value is the real page.

    Driving ``_fetch_stealth_impl`` with a double browser, so the whole rung
    runs: goto, settle, first read, hydration wait. Asserted on the extract the
    caller will judge, not on the wait's internals.
    """
    status, html, _final, _headers = _run_rung(
        monkeypatch, frames=[SHELL] * 6 + [RENDERED]
    )
    assert status == 200
    text = unlocker.html_to_text(html, "https://example.org/app")
    assert "Rendered paragraph number 5" in text, (
        f"the rung returned the shell, not the painted page: {text[:200]!r}"
    )
    assert len(text) > unlocker._APP_SHELL_MAX_CHARS


# ── a refusal is not a thin page ─────────────────────────────────────────────


def test_a_refusal_that_rendered_nothing_is_not_promoted_to_200():
    """The measured case: 403 from ``goto``, 39 bytes of empty document.

    Nothing cleared, so the status the server gave stays the status. Promoted to
    200 the ladder reads ``thin-0b``, which says "this page was short" about a
    page the server refused.
    """
    assert unlocker._is_refused_render(EMPTY_DOC, 403) is True
    assert unlocker.looks_blocked(
        200, EMPTY_DOC
    ) is None, "the premise: an empty document passes every block test"


def test_the_rung_reports_the_refusal_it_was_given(monkeypatch):
    status, _html, _final, _headers = _run_rung(
        monkeypatch, frames=[EMPTY_DOC], goto_status=403
    )
    assert status == 403, "a 403 that rendered nothing came back as a 200"
    assert unlocker.looks_blocked(status, _html) == "http-403"


def test_a_refusal_that_rendered_text_still_reports_200(monkeypatch):
    """A styled 403 page, or a challenge that cleared: real content, real 200.

    The old promotion was right about these, so it stays.
    """
    error_page = "<html><body><h1>403 Forbidden</h1><p>Access denied.</p></body></html>"
    assert unlocker._is_refused_render(error_page, 403) is False
    status, _html, _final, _headers = _run_rung(
        monkeypatch, frames=[error_page], goto_status=403
    )
    assert status == 200


def test_a_title_only_refusal_is_not_promoted_to_200(monkeypatch):
    title_only = "<html><head><title>403 Forbidden</title></head><body></body></html>"
    assert unlocker._is_refused_render(title_only, 403) is True
    status, _html, _final, _headers = _run_rung(
        monkeypatch, frames=[title_only], goto_status=403
    )
    assert status == 403


def test_a_broken_page_on_200_is_still_200(monkeypatch):
    """The other side of the rule: the fix keys on the refusal, not on emptiness.

    A 2xx that renders nothing is a broken page. It was already thin before this
    change and stays exactly as thin, so nothing here has quietly made one of
    these harder to see.
    """
    assert unlocker._is_refused_render(EMPTY_DOC, 200) is False
    status, _html, _final, _headers = _run_rung(
        monkeypatch, frames=[EMPTY_DOC], goto_status=200
    )
    assert status == 200


# ── the browser rung that is not there ───────────────────────────────────────

#: Playwright's own wording for a browser that was never downloaded, trimmed to
#: the two sentences the rung matches on.
_MISSING_BROWSER_ERROR = (
    "Executable doesn't exist at /home/u/.cache/ms-playwright/chromium-1248/"
    "chrome-linux/chrome\n"
    "║ Looks like Playwright was just installed or updated.\n"
    "║ Please run the following command to download new browsers:\n"
    "║ patchright install"
)


def test_a_missing_chromium_names_the_searchts_command():
    reason = unlocker._browser_missing_reason(RuntimeError(_MISSING_BROWSER_ERROR))
    assert reason, "a browser that was never installed was not named"
    assert 'pip install "searchts[browser]"' in reason
    assert "searchts install --browser" in reason
    assert "patchright install" not in reason.replace(
        "searchts install --browser", ""
    ), "the reason still tells the user to run a command searchts does not ship"


def test_another_launch_failure_is_not_called_a_missing_browser():
    """A browser that would not start and a browser that is not installed are
    different facts, and only one of them has a known fix."""
    assert unlocker._browser_missing_reason(
        RuntimeError("net::ERR_HTTP2_PROTOCOL_ERROR at https://example.org/")
    ) is None
    assert unlocker._browser_missing_reason(
        RuntimeError("Target page, context or browser has been closed")
    ) is None


def test_the_rung_raises_the_named_reason_for_a_missing_browser(monkeypatch):
    with pytest.raises(RuntimeError) as raised:
        _install_double_browser(monkeypatch, launch_error=RuntimeError(_MISSING_BROWSER_ERROR))
        unlocker._fetch_stealth_impl("https://example.org/app", timeout=5)
    assert 'pip install "searchts[browser]"' in str(raised.value)


def test_the_ladder_names_the_install_command_when_the_browser_is_missing(
    monkeypatch, cache
):
    """What the user actually reads on stderr for this read.

    Every rung refuses, the browser rung cannot start, and the reason the CLI
    prints has to say what to run. Asserted through ``fetch`` so the string that
    reaches the user is the one under test.
    """
    from searchts import scroll

    monkeypatch.setattr(
        unlocker, "_fetch_curl_cffi",
        lambda url, **kw: (200, SHELL, url, {}),
    )
    monkeypatch.setattr(
        unlocker, "_fetch_jina", lambda url, timeout=40: (403, "", url, {})
    )
    _install_double_browser(monkeypatch, launch_error=RuntimeError(_MISSING_BROWSER_ERROR))
    monkeypatch.setattr(scroll, "browser_available", lambda: True)

    with pytest.raises(unlocker.UnlockerError) as raised:
        unlocker.fetch(
            "https://example.org/app", backends=["curl_cffi", "stealth-browser"],
            use_memory=False,
        )
    reasons = " ".join(why for _b, why in raised.value.attempts)
    assert 'pip install "searchts[browser]"' in reasons, (
        f"the report never names the install command: {reasons}"
    )


# ── a saved shell is still a shell ───────────────────────────────────────────

#: A served app shell from a real site, trimmed to its shape. 41,371 bytes
#: served, 436 characters of visible markup, 106 characters of extract.
SERVED_SHELL = (FIXTURES / "app_shell_module_bundle.html").read_text(
    encoding="utf-8"
)


def test_the_saved_served_shell_is_still_recognised():
    """The fixture is a real shape, and the detectors still read it as one.

    Without this the fixture could rot into a page that is no longer the page
    it was saved from, and every test above would be passing on a shape that no
    site serves.
    """
    text = unlocker.html_to_text(SERVED_SHELL, "https://example.org/app")
    visible = unlocker._visible_markup_len(
        unlocker._SCRIPTISH_RE.sub(" ", SERVED_SHELL)
    )
    assert 400 <= visible <= 500, f"the saved shape drifted: {visible} visible chars"
    assert len(text) == 106, f"the saved extract drifted: {len(text)} chars"
    assert unlocker._is_app_shell(SERVED_SHELL, text) is False, (
        "this shell carries visible text of its own, so it is not the empty-shell "
        "shape; a fixture that stops being the shape it was saved as is worse "
        "than no fixture"
    )


def test_the_served_shell_is_thin_so_the_ladder_reaches_the_browser(
    monkeypatch, cache
):
    """The gap this file is about, end to end through ``fetch``.

    curl is handed the served shell, Jina refuses, and the browser rung hands
    back the painted page. The read must return the browser's text: a JS-shell
    page is rendered, not reported thin.
    """
    monkeypatch.setattr(
        unlocker, "_fetch_curl_cffi", lambda url, **kw: (200, SERVED_SHELL, url, {})
    )
    monkeypatch.setattr(
        unlocker, "_fetch_jina", lambda url, timeout=40: (403, "", url, {})
    )
    monkeypatch.setattr(
        unlocker, "_fetch_stealth",
        lambda url, **kw: (200, RENDERED, url, {}),
    )

    result = unlocker.fetch(
        "https://example.org/app", use_memory=False, progress=False,
        # The saved painted page is 304 characters of extract, so it is asked
        # for as a short read rather than at the 500-character default. What is
        # under test is which rung answered, not how long the page is.
        min_chars=200,
    )
    assert result.backend == "stealth-browser"
    assert "Rendered paragraph number 5" in result.text


def test_a_shell_the_browser_could_not_paint_is_not_a_read(monkeypatch, cache):
    """The other end: rendered and still a shell, so it fails loud.

    Fail-loud is the rule. A browser that painted a shell has said it has
    nothing, and handing that back as content is the silent thin pass the ladder
    exists to prevent.
    """
    monkeypatch.setattr(
        unlocker, "_fetch_curl_cffi", lambda url, **kw: (200, SHELL, url, {})
    )
    monkeypatch.setattr(
        unlocker, "_fetch_jina", lambda url, timeout=40: (403, "", url, {})
    )
    monkeypatch.setattr(
        unlocker, "_fetch_stealth", lambda url, **kw: (200, SHELL, url, {})
    )

    with pytest.raises(unlocker.UnlockerError) as raised:
        unlocker.fetch(
            "https://example.org/app", use_memory=False, progress=False,
            min_chars=200,
        )
    assert raised.value.attempts, "a failed read must say which rungs ran"
    assert "thin-" in " ".join(why for _b, why in raised.value.attempts)


# ── fences this change must not have moved ───────────────────────────────────

def test_the_hydration_change_did_not_add_a_print():
    """P4.6: work that can sit more than a second ticks on stderr, never stdout.

    The wait can now spend up to the budget where it used to spend one step, so
    it is a longer sit than it was. Nothing may be added to stdout, and the only
    narration stays on stderr.
    """
    import inspect

    source = inspect.getsource(unlocker._await_hydration)
    assert "print(" not in source, "the hydration wait grew a stdout print"


def test_the_cookie_fence_still_holds_on_the_browser_rung(monkeypatch, cache):
    """The stealth rung is still called with no cookie material of any kind.

    The browser rung gained a launch-failure path. A path added to a rung that
    can see a live login has to be re-checked, not assumed.
    """
    from searchts.session_cookies import CookieRecord

    seen: List[Dict[str, Any]] = []

    def _stealth(url, *args, **kwargs):
        seen.append({"args": args, "kwargs": kwargs})
        return 200, RENDERED, url, {}

    # curl is left thin rather than refused: two identical 4xx answers stop the
    # ladder before the browser runs (#338), and a rung that never runs proves
    # nothing about what it was handed.
    monkeypatch.setattr(
        unlocker, "_fetch_curl_cffi", lambda url, **kw: (200, SHELL, url, {})
    )
    monkeypatch.setattr(
        unlocker, "_fetch_jina", lambda url, timeout=40: (403, "", url, {})
    )
    monkeypatch.setattr(unlocker, "_fetch_stealth", _stealth)

    unlocker.fetch(
        "https://site.test/app",
        use_memory=False,
        min_chars=200,
        cookies=[CookieRecord(name="sessionid", value="s3cr3t", domain="site.test")],
    )
    assert seen, "the browser rung never ran, so nothing was proven"
    haystack = repr(seen)
    assert "s3cr3t" not in haystack, f"cookie material reached the rung: {haystack}"
    assert "cookie" not in haystack.lower(), (
        f"the browser rung was handed cookie material: {haystack}"
    )


# ── doubles ──────────────────────────────────────────────────────────────────

def _install_double_browser(
    monkeypatch, frames: Optional[List[Any]] = None,
    goto_status: int = 200, launch_error: Optional[BaseException] = None,
) -> None:
    """Put a double patchright in ``sys.modules`` and return its page.

    ``frames`` model ``content()`` reads after the first, which is what
    ``_await_hydration`` is handed by the caller.
    """
    reads = list(frames or [RENDERED])

    class _Resp:
        status = goto_status

        def all_headers(self) -> Dict[str, str]:
            return {}

    class _Page:
        def goto(self, url, **kw):
            return _Resp()

        def content(self):
            frame = reads.pop(0) if len(reads) > 1 else reads[0]
            if isinstance(frame, Exception):
                raise frame
            return frame

        @property
        def url(self):
            return "https://example.org/app"

        def wait_for_timeout(self, ms):
            pass

        def wait_for_load_state(self, state, timeout=None):
            pass

        def evaluate(self, _js):
            return 0

    class _Browser:
        def new_page(self):
            return _Page()

        def close(self):
            pass

    class _Chromium:
        def launch_persistent_context(self, *a, **kw):
            if launch_error is not None:
                raise launch_error
            return _Browser()

        def launch(self, *a, **kw):
            if launch_error is not None:
                raise launch_error
            return _Browser()

    class _Playwright:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        chromium = _Chromium()

    fake = types.ModuleType("patchright")
    sync_api = types.ModuleType("patchright.sync_api")
    sync_api.sync_playwright = lambda: _Playwright()
    fake.sync_api = sync_api
    monkeypatch.setitem(sys.modules, "patchright", fake)
    monkeypatch.setitem(sys.modules, "patchright.sync_api", sync_api)


def _run_rung(
    monkeypatch, frames: List[Any], goto_status: int = 200,
) -> Tuple[Optional[int], str, str, Dict[str, str]]:
    """Run the real stealth rung over a double page, no Chromium involved."""
    _install_double_browser(
        monkeypatch, frames=frames, goto_status=goto_status
    )
    monkeypatch.delenv("SEARCHTS_NO_BROWSER_PROFILE", raising=False)
    return unlocker._fetch_stealth_impl("https://example.org/app", timeout=5)


@pytest.fixture
def cache(monkeypatch, tmp_path):
    """The domain-memory cache in tmp, so a test never pins the real home."""
    monkeypatch.setattr(unlocker, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(unlocker, "_CACHE_PATH", tmp_path / "unlocker_cache.json")
    monkeypatch.setenv("SEARCHTS_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("SEARCHTS_NO_MEMORY", raising=False)
    return tmp_path / "unlocker_cache.json"
