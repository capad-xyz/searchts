# -*- coding: utf-8 -*-
"""Web — any URL via an escalating open-source unlocker.

Ladder (see searchts.unlocker): curl_cffi -> Jina Reader -> stealth-browser.
curl_cffi is always importable; Jina is probed with the same client as read.
stealth-browser needs the optional ``searchts[browser]`` extra.
"""

import urllib.error

from .. import unlocker
from .base import Channel


def _stealth_installed() -> bool:
    """True when the optional patchright package is importable.

    Does not launch Chromium — doctor must stay offline and fast. A broken
    browser install still surfaces later when the stealth tier is actually used.
    """
    try:
        import patchright  # noqa: F401
    except Exception:
        # Any import-time failure (missing extra, broken install) is "not available"
        # for this offline doctor probe. A real stealth fetch still surfaces later.
        return False
    return True


def _jina_probe() -> tuple[str, str]:
    """Probe Jina with the same client ``read`` uses (``unlocker._fetch_jina``).

    A separate ``requests`` call with a doctor User-Agent can get 200 while
    the real rung gets 403. Doctor must not call Jina available in that case.
    """
    if not unlocker.jina_enabled():
        return "off", "disabled"
    try:
        status, _body, _final, _headers = unlocker._fetch_jina(
            "https://example.com/", timeout=8
        )
    except urllib.error.HTTPError as e:
        return "blocked", f"http-{e.code}"
    except Exception as e:  # noqa: BLE001
        return "blocked", f"probe failed ({type(e).__name__})"
    if status == 200:
        return "ok", "ok"
    return "blocked", f"http-{status}"


class WebChannel(Channel):
    name = "web"
    description = "Any web page"
    # Ordered ladder; the base-class failover/override machinery walks this list.
    backends = ["curl_cffi", "Jina Reader", "stealth-browser"]
    tier = 0

    def check(self, config=None):
        self.active_backend = self.backends[0]
        jina_state, jina_detail = _jina_probe()
        stealth = _stealth_installed()
        # Candidate ladder stays on the class (fetch still walks it).
        # Doctor JSON reports only rungs this probe actually saw as up.
        live = ["curl_cffi"]
        if jina_state == "ok":
            live.append("Jina Reader")
        if stealth:
            live.append("stealth-browser")
        self.reported_backends = live
        jina_bit = (
            "Jina Reader"
            if jina_state == "ok"
            else f"Jina Reader not available ({jina_detail})"
        )
        if stealth and jina_state == "ok":
            return (
                "ok",
                "Escalating fetch unlocker: curl_cffi -> Jina Reader -> stealth-browser",
            )
        if stealth:
            return (
                "warn",
                f"Escalating fetch unlocker: curl_cffi -> {jina_bit}; stealth-browser installed",
            )
        extra = ""
        if jina_state == "ok":
            extra = "Jina Reader available; "
        else:
            extra = f"{jina_bit}; "
        return (
            "warn",
            "Escalating fetch unlocker: curl_cffi -> "
            f"{extra}stealth-browser not installed "
            "(pip install 'searchts[browser]' && patchright install chromium)",
        )

    def read(self, url: str, config=None) -> str:
        """Read the page body, escalating through backends in order until real content is obtained."""
        order = self.ordered_backends(config)
        result = unlocker.fetch(url, backends=order)
        self.active_backend = result.backend
        return result.text