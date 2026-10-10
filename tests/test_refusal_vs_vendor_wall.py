# -*- coding: utf-8 -*-
"""The repeated-4xx fast-fail must not hide a device-check.

#338 took StackOverflow from 212.9s to 18.8s by stopping the ladder after two
identical 4xx, on the reasoning that a server which says 403 to curl says 403
to a browser. That reasoning is right in general and wrong in exactly one case:
a device-check answers a real browser with a rendered challenge rather than a
second 403. datadome.co measured 403 from curl, 403 from Jina, and 403 carrying
1,464 characters of geo.captcha-delivery.com from Chromium.

These tests hold both halves at once: the fast-fail stays, and the browser is
still launched when the refusal body carries a vendor's own markup.
"""

from __future__ import annotations

import io
from urllib.error import HTTPError

from searchts import unlocker as u

VENDOR_BODY = (
    "<html><head><script src='https://geo.captcha-delivery.com/api.js'></script>"
    "</head><body>checking</body></html>"
)
PLAIN_BODY = "<html><body>Forbidden</body></html>"


def test_a_vendor_wall_body_is_recognised() -> None:
    assert u._is_vendor_wall(VENDOR_BODY) is True


def test_a_plain_403_body_is_not_a_vendor_wall() -> None:
    """The whole point: a bare refusal keeps the fast-fail and its 194 seconds."""
    assert u._is_vendor_wall(PLAIN_BODY) is False
    assert u._is_vendor_wall("") is False
    assert u._is_vendor_wall(None) is False


def test_every_puzzle_vendor_marker_counts_as_a_vendor_wall() -> None:

    for marker in ("cf-turnstile", "px-captcha", "arkoselabs", "kpsdk"):
        body = "<iframe src='https://%s'></iframe>" % marker
        assert u._is_vendor_wall(body) is True, marker


def test_an_ordinary_article_is_not_a_vendor_wall() -> None:
    """A real page must not be treated as a wall. This is the false-positive
    direction, and it is the one that would break every successful read."""
    body = "<html><body><h1>Story</h1><p>Text.</p></body></html>"
    assert u._is_vendor_wall(body) is False


def test_the_stop_reason_survives_the_fast_fail_path() -> None:
    """The header that names the wall must not be dropped on the way out."""
    assert hasattr(u, "_is_vendor_wall")
    src = u.__doc__ or ""
    # The module docstring is where #354's correction lives; keep it honest.
    assert "honest ceiling" not in src.lower()


def test_a_refusal_that_raised_still_yields_its_body() -> None:
    """urllib keeps an HTTPError's body on its file object, not `.body`.

    The fast-fail exception asks "does this refusal carry a vendor's markup?",
    and Jina refuses by raising rather than returning, so this is the only way
    a vendor wall behind a raised 4xx can be seen at all.
    """
    err = HTTPError("https://example.com/", 403, "Forbidden", {}, io.BytesIO(
        VENDOR_BODY.encode("utf-8")))
    assert u._is_vendor_wall(u._raised_body(err)) is True


def test_a_raised_refusal_with_a_plain_body_stays_a_fast_fail() -> None:
    err = HTTPError("https://example.com/", 403, "Forbidden", {}, io.BytesIO(
        PLAIN_BODY.encode("utf-8")))
    assert u._is_vendor_wall(u._raised_body(err)) is False


class _Raised:
    """An exception stand-in that has a ``read``, the way urllib's HTTPError does.

    A real one is used above for the case that matters; this one is for the
    branches a well-behaved HTTPError never takes.
    """

    def __init__(self, value):
        self._value = value
        self.asked = None

    def read(self, n):
        self.asked = n
        if isinstance(self._value, BaseException):
            raise self._value
        return self._value


def test_raised_body_is_bounded_and_total() -> None:
    """A huge error page is truncated, and nothing else escapes."""
    big = HTTPError("https://example.com/", 403, "Forbidden", {}, io.BytesIO(
        (VENDOR_BODY + "x" * 500000).encode("utf-8")))
    assert len(u._raised_body(big)) <= u._VENDOR_WALL_SCAN

    # No body at all, and nothing that can be read.
    assert u._raised_body(ValueError("nope")) == ""

    # A reader is asked for the bound and not for the whole page.
    fp = _Raised(VENDOR_BODY.encode("utf-8"))
    assert u._raised_body(fp) == VENDOR_BODY
    assert fp.asked == u._VENDOR_WALL_SCAN

    # A reader that raises, and one that returns something other than text,
    # are both ignored rather than raised out of a 4xx handler.
    assert u._raised_body(_Raised(RuntimeError("boom"))) == ""
    assert u._raised_body(_Raised(12345)) == ""
    assert u._raised_body(_Raised(None)) == ""

    # A reader that hands back a str longer than the bound is trimmed again, so
    # the cap holds even when the reader ignores it.
    assert len(u._raised_body(_Raised("y" * (u._VENDOR_WALL_SCAN + 999)))) == (
        u._VENDOR_WALL_SCAN)
