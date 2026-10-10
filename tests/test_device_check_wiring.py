# -*- coding: utf-8 -*-
"""The stealth rung spends at most one click, and only on a one-action check.

The integration tests above prove the classifier. These two prove the wiring,
because a correct module that nothing calls is the exact failure #354 had to
be corrected for: the docstring promised a click the code did not take.
"""

from __future__ import annotations

import inspect

from searchts import device_check as dc
from searchts import unlocker as u

_SOURCE = inspect.getsource(u._fetch_stealth_impl)


def test_the_stealth_impl_actually_calls_the_device_check() -> None:
    """The promise in the docstring must be a call in the body.

    This is a text check, deliberately. A behavioural test would need a live
    device-check page, which is the thing we do not have. A text check fails the
    moment someone deletes the call, which is the regression worth catching.
    """
    assert "device_check" in _SOURCE, "the click is not wired into the stealth rung"
    assert "solve_simple_click" in _SOURCE


def test_the_click_happens_after_the_script_has_had_its_time() -> None:
    """Order matters: wait for the script first, then click.

    Clicking first would press a button the page had not armed yet, which is a
    guess rather than finishing a script.
    """
    hydration = _SOURCE.index("_await_hydration")
    poll = _SOURCE.index("while waited < 15000")
    click = _SOURCE.index("solve_simple_click")
    assert hydration < poll < click, "hydrate, then let the script run, then click"


def test_a_named_stop_travels_back_in_the_headers() -> None:
    """The caller must be able to say WHICH wall this was.

    A bare 403 and "needs a person: arkoselabs" are different failures and a
    user acts on them differently. The stop reason is the only thing that makes
    them distinguishable, so it goes back in the headers.
    """
    assert "x-searchts-device-stop" in _SOURCE


def test_the_module_docstring_does_not_call_datadome_the_ceiling() -> None:
    """#354's regression, as a test.

    The module docstring was corrected to say a device-check is the stealth
    rung's job including one simple click. The _fetch_stealth docstring said the
    opposite, in the same file. Both cannot be true, and the wrong one was read.
    """
    doc = u.__doc__ or ""
    assert "honest ceiling" not in doc.lower()
    fn_doc = u._fetch_stealth.__doc__ or ""
    assert "honest ceiling" not in fn_doc.lower()
    # The wording is "one simple action" / "simple click"; match on "simple"
    # plus "click" separately so a rewording of the sentence does not fail a
    # test that is about the claim, not the phrasing.
    fn_low = fn_doc.lower()
    assert "simple" in fn_low and "click" in fn_low, fn_doc
    assert "one click" in fn_low or "at most one click" in fn_low, fn_doc


def test_a_stop_reason_names_the_vendor_not_just_the_class() -> None:
    stop = dc.human_required("<iframe src='https://geo.captcha-delivery.com/captcha'>")
    assert stop == "geo.captcha-delivery.com/captcha"


def test_no_solving_service_is_referenced_anywhere_in_the_module() -> None:
    """The promise is 'a person', not 'a service'. Hold the line in code.

    If a future edit wires a solving API in, this fails. It is the one thing
    here that must not become a dependency, and a docstring is not enforcement.
    """
    src = inspect.getsource(dc).lower()
    for banned in ("2captcha", "anti-captcha", "anticaptcha", "capsolver",
                   "solverapi", "captchaapi", "deathbycaptcha"):
        assert banned not in src, "%s must not appear: a puzzle needs a person" % banned
    # And nothing that could be an outbound call in the click path.
    for banned in ("requests.post", "urlopen", "http.client", "httpx"):
        assert banned not in src, "%s would send the challenge somewhere" % banned