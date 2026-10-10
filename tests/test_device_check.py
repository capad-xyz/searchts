# -*- coding: utf-8 -*-
"""A one-action device-check is cleared; a puzzle stops with a reason.

These tests are hermetic: a fake page, no browser, no network. The point is
the two halves of #354's sentence, and specifically that the *stop* is as
careful as the click. A test suite that only proves the happy path would pass a
module that clicks "accept all cookies" and one that solves image grids.
"""

from __future__ import annotations

from typing import List, Optional

import pytest

from searchts import device_check as dc


class FakeEl:
    """Enough of a Playwright element for the find/click path."""

    def __init__(self, text: str = "", visible: bool = True,
                 disabled: bool = False, clickable: bool = True,
                 kind: str = "button") -> None:
        self._text = text
        self._visible = visible
        self._disabled = disabled
        self._clickable = clickable
        self.kind = kind
        self.clicks = 0

    def is_visible(self) -> bool:
        return self._visible

    def is_disabled(self) -> bool:
        return self._disabled

    def inner_text(self) -> str:
        return self._text

    def text_content(self) -> str:
        return self._text

    def click(self, timeout: int = 4000) -> None:
        if not self._clickable:
            raise RuntimeError("element is not clickable")
        self.clicks += 1


#: An interstitial that is NOT yet a puzzle: the vendor script is present but
#: has not mounted its image UI. This is the state a click is meant to resolve,
#: and it is deliberately distinct from the puzzle bodies above, so a test using
#: it exercises the click path rather than the stop path.
CHALLENGE_BODY = (
    "<html><head><script src='https://geo.captcha-delivery.com/api.js'></script></head>"
    "<body><p>Checking your browser before accessing.</p>"
    "<button>Continue</button>" + ("<p>filler</p>" * 200) + "</body></html>"
)


class FakePage:
    """A page whose content the test swaps, to simulate a challenge clearing."""

    def __init__(self, controls: Optional[List[FakeEl]] = None,
                 html: str = "<html>article</html>") -> None:
        self._controls = controls or []
        self.html = html
        self.waited: List[int] = []

    def query_selector_all(self, selector: str) -> List[FakeEl]:
        return self._controls

    def content(self) -> str:
        return self.html

    def wait_for_timeout(self, ms: int) -> None:
        self.waited.append(ms)


# ── the stop half ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("marker", [
    "cf-turnstile",
    "geo.captcha-delivery.com/captcha",
    "px-captcha",
    "arkoselabs",
    "funcaptcha.com",
    "kpsdk",
    "validate.captcha.perfdrive.com",
    "hcaptcha.com",
])
def test_every_puzzle_vendor_stops_us(marker: str) -> None:
    html = "<html><body><iframe src='https://%s'></iframe></body></html>" % marker
    assert dc.human_required(html) == marker


def test_a_plain_continue_button_is_not_a_puzzle() -> None:
    html = "<html><body><button>Continue</button></body></html>"
    assert dc.human_required(html) is None


def test_an_empty_canvas_is_not_a_puzzle() -> None:
    """A canvas is not evidence of a puzzle, and this is the regression.

    An earlier version of ``human_required`` flagged an empty ``<canvas>`` or
    ``<img>`` as a picture prompt waiting to be drawn into. Every chart widget
    ships an empty canvas, so the rule failed on ordinary articles and the
    failure was silent: the page read as a challenge instead of as content.
    Only a vendor's own markup counts now.
    """
    assert dc.human_required("<html><body><canvas id=chart></canvas>ok</body></html>") is None
    assert dc.human_required("<div><canvas></canvas></div>") is None
    assert dc.human_required("<div><img></img></div>") is None


def test_a_real_image_in_an_article_is_not_a_puzzle() -> None:
    """An <img src=...> is content, and the vendor markers do not fire on it."""
    html = "<html><body><img src='https://cdn/hero.jpg'><p>story</p></body></html>"
    assert dc.human_required(html) is None


def test_third_party_frame_is_named_in_the_stop_reason() -> None:
    stop = dc.human_required("<html>ok</html>", challenge_host="geo.captcha-delivery.com")
    assert stop is not None
    assert "geo.captcha-delivery.com" in stop


# ── finding the control ──────────────────────────────────────────────────────

def test_continue_button_is_found() -> None:
    page = FakePage([FakeEl("  Continue  ")])
    found = dc.find_one_action_control(page)
    assert found is not None and found["label"] == "continue"


@pytest.mark.parametrize("label", ["Verify", "I am human", "Press and hold",
                                   "Confirm", "Proceed", "Unblock"])
def test_common_one_action_labels(label: str) -> None:
    page = FakePage([FakeEl(label)])
    assert dc.find_one_action_control(page) is not None


@pytest.mark.parametrize("label", [
    "Sign in", "Log in", "Subscribe", "Buy now", "Pay",
    "Accept all cookies", "Privacy policy", "Terms", "Download",
])
def test_a_label_we_refuse_is_never_clicked(label: str) -> None:
    """The refusal list outranks the allow list, and 'accept' is the trap.

    'Accept all cookies' contains 'accept', which is in CLICK_LABELS. If the
    refusal list were checked second, this would be a click on every site with
    a cookie banner, which is both useless and rude.
    """
    page = FakePage([FakeEl(label)])
    assert dc.find_one_action_control(page) is None


def test_an_invisible_or_disabled_control_is_not_clicked() -> None:
    assert dc.find_one_action_control(FakePage([FakeEl("Continue", visible=False)])) is None
    assert dc.find_one_action_control(FakePage([FakeEl("Continue", disabled=True)])) is None


def test_a_control_with_no_text_is_left_alone() -> None:
    """A bare checkbox is the puzzle shape, not a confirm button."""
    assert dc.find_one_action_control(FakePage([FakeEl("")])) is None


# ── clicking ─────────────────────────────────────────────────────────────────

def test_one_click_is_spent_and_the_page_is_polled() -> None:
    btn = FakeEl("Continue")
    page = FakePage([btn])
    page.html = CHALLENGE_BODY
    html, stop = dc.solve_simple_click(page, page.html, budget_ms=3000, step_ms=500)
    assert btn.clicks == 1, "exactly one click"
    assert page.waited, "and then we wait for the script"


def test_no_click_when_the_dom_is_already_a_puzzle() -> None:
    """The stop happens BEFORE the click, not after.

    This is the ordering that matters. Checking after would mean we already
    pressed something on a page we should have refused.
    """
    btn = FakeEl("Continue")
    page = FakePage([btn], html="<iframe src='https://arkoselabs.com'></iframe>")
    html, stop = dc.solve_simple_click(page, page.html)
    assert btn.clicks == 0
    assert stop == "arkoselabs"


def test_a_control_that_refuses_the_click_is_reported_not_retried() -> None:
    btn = FakeEl("Continue", clickable=False)
    page = FakePage([btn])
    html, stop = dc.solve_simple_click(page, "<html><iframe src='https://challenges.cloudflare.com/turnstile'></iframe>")
    # The turnstile marker stops us first; use a non-puzzle challenge body here.
    page2 = FakePage([FakeEl("Continue", clickable=False)])
    html2, stop2 = dc.solve_simple_click(page2, "<html>checking...</html>")
    assert stop2 == "click-refused"
    assert btn.clicks == 0


def test_a_clear_page_is_not_polled_at_all() -> None:
    """Nothing to click means no waiting: an already-good page costs nothing."""
    page = FakePage([])
    html, stop = dc.solve_simple_click(page, "<html>checking...</html>")
    assert stop is None
    assert page.waited == []


def test_budget_is_the_whole_call() -> None:
    """One click, then bounded polling. There is no second click by design.

    The fixture body must stay clear of PUZZLE_MARKERS, otherwise the stop fires
    first and the click never happens, which is correct behaviour and makes this
    a useless test. A non-puzzle challenge body is what the click path needs.
    """
    btn = FakeEl("Continue")
    page = FakePage([btn])
    page.html = CHALLENGE_BODY
    html, stop = dc.solve_simple_click(page, page.html, budget_ms=2000, step_ms=500)
    assert btn.clicks == 1
    assert len(page.waited) == 4


def test_whitespace_in_a_label_is_normalised() -> None:
    page = FakePage([FakeEl("  Verify   you\n are human  ")])
    found = dc.find_one_action_control(page)
    assert found is not None
    assert found["label"] == "verify you are human"
