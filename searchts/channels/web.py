# -*- coding: utf-8 -*-
"""Web — any URL via an escalating open-source unlocker.

Ladder (see searchts.unlocker): curl_cffi -> Jina Reader -> stealth-browser.
curl_cffi is always importable; Jina is probed live (403 ≠ available).
stealth-browser needs the optional ``searchts[browser]`` extra.
"""

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
    """Live probe of r.jina.ai. Returns (ok|off|blocked, detail).

    Doctor used to print "Jina Reader available" without a request. A 403
    means the rung is not available (P1.4).
    """
    if not unlocker.jina_enabled():
        return "off", "disabled"
    try:
        import requests
        r = requests.get(
            "https://r.jina.ai/https://example.com/",
            timeout=8,
            headers={"User-Agent": "searchts-doctor"},
        )
    except Exception as e:  # noqa: BLE001
        return "blocked", f"probe failed ({type(e).__name__})"
    if r.status_code == 200:
        return "ok", "ok"
    return "blocked", f"http-{r.status_code}"


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