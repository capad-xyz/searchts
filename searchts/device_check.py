# -*- coding: utf-8 -*-
"""Clear a device-check's single click, on the stealth rung.

#354 corrected the docs: a DataDome device-check is a script the stealth browser
is supposed to finish, including one simple click. A puzzle that asks a person
to recognize images still needs a human. This module is the first half of that
sentence. The second half is :func:`_human_required`, and it is the stop.

What this does, and nothing more:

* wait for the challenge script to finish, which the ladder already did
* find a control that is one action - continue, verify, a checkbox, a
  press-and-hold button - and act on it once
* wait again, bounded, and hand back whatever the page is then showing

What this will not do, deliberately:

* solve an image grid, or any puzzle needing a person to recognize something
* send the challenge to a solving service
* click more than once, or click anything that looks like navigation

The distinction is measurable rather than a vibe. A one-action control has no
image grid inside it and no cross-origin iframe carrying the puzzle. So:

* a puzzle marker anywhere in the challenge DOM stops us before any click
* a clickable inside a third-party challenge iframe is not clicked
* at most one click is spent per read

Nothing here is evasion of a puzzle. It is finishing a script the browser was
already running and pressing the button a person would press once.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "human_required",
    "find_one_action_control",
    "click_once",
    "solve_simple_click",
    "CLICK_LABELS",
    "PUZZLE_MARKERS",
]


#: Labels a one-action control plausibly carries. Matched against the visible
#: text of the control, lowercased and whitespace-collapsed. Deliberately short:
#: every entry here is a word a person reads on a button, not a phrase a vendor
#: invented. A label we do not know is simply not clicked.
CLICK_LABELS: Tuple[str, ...] = (
    "continue",
    "verify",
    "verify you are human",
    "i am human",
    "i'm human",
    "are you a human",
    "confirm",
    "proceed",
    "accept",
    "allow",
    "yes, continue",
    "click to verify",
    "press and hold",
    "hold to verify",
    "unblock",
    "go",
    "next",
)

#: A control whose visible text contains one of these is doing something other
#: than confirming a person is present. Never clicked.
_REFUSAL_LABELS: Tuple[str, ...] = (
    "sign in",
    "log in",
    "login",
    "register",
    "subscribe",
    "buy",
    "purchase",
    "pay",
    "cookie",
    "accept all cookies",
    "privacy",
    "terms",
    "newsletter",
    "uninstall",
    "download",
)

#: Markers that mean a person has to look at something. If any of these is in
#: the challenge DOM, this is a puzzle and we stop. Checked before any click.
PUZZLE_MARKERS: Tuple[str, ...] = (
    # Turnstile / Cloudflare interactive
    "cf-turnstile",
    "challenges.cloudflare.com/turnstile",
    # DataDome's captcha iframe carries a real puzzle UI
    "geo.captcha-delivery.com/captcha",
    "captcha-delivery.com/captcha",
    # PerimeterX and HUMAN
    "px-captcha",
    "perimeterx",
    "press and hold to verify that you are human",
    # Arkose / FunCaptcha, always an image puzzle
    "arkoselabs",
    "funcaptcha",
    "funcaptcha.com",
    # Kasada, Radware, AWS WAF widget mounts
    "kpsdk",
    "validate.captcha.perfdrive.com",
    "perfdrive.com",
    "awswafcaptcha",
    "awswafchallenge",
    # hCaptcha
    "hcaptcha.com",
    "h-captcha",
)

# Longest first. "funcaptcha" is a substring of "funcaptcha.com" and
# "perfdrive.com" is a substring of "validate.captcha.perfdrive.com", so in
# tuple order the shorter one always wins and the stop reason names the vendor
# less precisely than it could. Sorting by length is the whole fix, and it is
# why the tests assert on the exact marker rather than a truthy value.
PUZZLE_MARKERS = tuple(sorted(PUZZLE_MARKERS, key=len, reverse=True))


def _norm(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def human_required(html: str, challenge_host: Optional[str] = None) -> Optional[str]:
    """Why a person is required, or None if a simple click might clear this.

    Returns the marker that stopped us, so the caller can name it rather than
    saying "blocked". The order is deliberate: puzzle markers are checked on the
    whole document first, because a page can show a one-action button *and* an
    image puzzle, and in that case the puzzle is the real gate.

    Only vendor markers count, and that is a measured choice rather than a
    shortcut. An earlier version also treated an empty ``<canvas>`` or ``<img>``
    as a puzzle, on the theory that a prompt renders into one before it draws.
    That rule eats ordinary articles: every chart widget ships an empty canvas
    waiting to be drawn into, so it fails on content and the failure is silent.
    A canvas is not evidence of a puzzle; a vendor's own markup is. The
    regression test for that is ``test_an_empty_canvas_is_not_a_puzzle``.
    """
    low = (html or "").lower()
    for marker in PUZZLE_MARKERS:
        if marker in low:
            return marker
    if challenge_host:
        # A challenge served from a different origin is third-party. Pressing a
        # button inside somebody else's iframe is not our call to make.
        return "third-party-challenge-frame:%s" % challenge_host
    return None


def _challenge_hosts(page) -> List[str]:
    """Origins of frames on the page that are not the origin we asked for."""
    hosts: List[str] = []
    try:
        for frame in page.frames:
            url = frame.url or ""
            if not url.startswith(("http://", "https://")):
                continue
            m = re.match(r"https?://([^/]+)", url)
            if m:
                hosts.append(m.group(1))
    except Exception:  # noqa: BLE001 - a frame list we cannot read is not fatal
        return hosts
    return hosts


def _visible_text(el) -> str:
    for getter in ("inner_text", "text_content"):
        try:
            val = getattr(el, getter)()
        except Exception:  # noqa: BLE001
            continue
        if val:
            return _norm(val)
    return ""


def find_one_action_control(page) -> Optional[Dict[str, Any]]:
    """The first control on the page that is one action, or None.

    A one-action control is a button, a checkbox, or a role=button element
    whose visible label is in :data:`CLICK_LABELS` and not in
    :data:`_REFUSAL_LABELS`. The refusal list matters more than the allow list:
    "accept all cookies" contains "accept", and clicking it would be rude and
    useless.
    """
    try:
        controls = page.query_selector_all(
            "button, input[type=submit], input[type=button], "
            "[role=button], input[type=checkbox]"
        )
    except Exception:  # noqa: BLE001
        return None
    for el in controls:
        try:
            if not el.is_visible():
                continue
            # A disabled control is a control the page has not armed yet.
            if el.is_disabled():
                continue
        except Exception:  # noqa: BLE001
            continue
        text = _visible_text(el)
        if not text:
            # A checkbox with a label element is common; a bare checkbox with no
            # text is the puzzle pattern, not a one-action confirm.
            continue
        if any(bad in text for bad in _REFUSAL_LABELS):
            continue
        if any(text == label or text.startswith(label) for label in CLICK_LABELS):
            return {"el": el, "label": text}
    return None


def click_once(page, control: Dict[str, Any]) -> bool:
    """Press the control once. Returns whether the press was delivered."""
    el = control.get("el")
    if el is None:
        return False
    try:
        el.click(timeout=4000)
        return True
    except Exception:  # noqa: BLE001 - a control that refuses the click is a stop
        return False


def solve_simple_click(
    page,
    html: str,
    budget_ms: int = 15000,
    step_ms: int = 1500,
    progress: bool = False,
) -> Tuple[str, Optional[str]]:
    """Try to finish a device-check with at most one click.

    Returns ``(html, stop_reason)``. ``stop_reason`` is None when the page
    cleared, and otherwise the marker naming what stopped us, so the ladder can
    say "an image puzzle" instead of "failed".

    The click budget is the whole call: one press, then polling. There is no
    retry, on purpose. A second click is not finishing a script, it is guessing.
    """
    # Re-check on the challenge DOM we were handed, before touching anything.
    stop = human_required(html)
    if stop:
        return html, stop
    control = find_one_action_control(page)
    if control is None:
        return html, None
    if not click_once(page, control):
        return html, "click-refused"
    waited = 0
    while waited < budget_ms:
        page.wait_for_timeout(step_ms)
        waited += step_ms
        try:
            html = page.content()
        except Exception:  # noqa: BLE001
            continue
        # The page may have navigated to the real article, which is the win.
        if not _still_challenge(html):
            return html, None
        stop = human_required(html)
        if stop:
            return html, stop
    return html, None


def _still_challenge(html: str) -> bool:
    """Cheap "has the challenge cleared" check that does not need page state.

    ``looks_blocked`` is the caller-facing judgement and needs a status; this is
    the narrow question "is this still an interstitial", asked after a click.
    """
    low = (html or "").lower()
    for marker in PUZZLE_MARKERS:
        if marker in low:
            return True
    for marker in ("captcha-delivery.com", "px-captcha", "challenge-platform"):
        if marker in low:
            return True
    return len(html or "") < 4000 and "verify" in low
