# -*- coding: utf-8 -*-
"""A navigation error must fail the rung, not escape as a raw Playwright error.

Measured while dogfooding the device-check work: `_fetch_stealth` against
`lululemon.com` raised `Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR` straight out
of the function. The ladder catches broadly so the user still gets a refusal
rather than a traceback, but the rung's own reason string is lost, and the
error is a crash rather than a verdict. It is the same class of defect as the
fence: the failure is real and the reporting of it is wrong.
"""

from __future__ import annotations

import pytest

from searchts import unlocker as u


def test_http2_protocol_error_is_classified_as_a_navigation_race() -> None:
    """The specific error we saw must be recognised as 'the page moved', so it
    gets the retry path rather than an immediate raise."""
    msg = "Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://www.lululemon.com/"
    assert u._is_nav_race(RuntimeError(msg)) is True


@pytest.mark.parametrize("needle", [
    "net::ERR_HTTP2_PROTOCOL_ERROR",
    "net::ERR_CONNECTION_RESET",
    "net::ERR_EMPTY_RESPONSE",
    "Unable to retrieve content because the page is navigating",
])
def test_the_navigation_race_covers_the_transport_errors_a_real_page_throws(
    needle: str,
) -> None:
    assert u._is_nav_race(RuntimeError(needle)) is True


def test_a_real_failure_is_not_mistaken_for_a_navigation_race() -> None:
    """Otherwise every genuine error would burn three retries and 6s first."""
    assert u._is_nav_race(RuntimeError("Target page, context or browser has been closed")) is False
    assert u._is_nav_race(ValueError("bad selector")) is False
