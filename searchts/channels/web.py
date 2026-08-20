# -*- coding: utf-8 -*-
"""Web — any URL via an escalating open-source unlocker.

Ladder (see searchts.unlocker): curl_cffi -> Jina Reader -> stealth-browser.
curl_cffi + Jina are always available; stealth-browser needs the optional
``searchts[browser]`` extra (patchright + Chromium).
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


class WebChannel(Channel):
    name = "web"
    description = "Any web page"
    # Ordered ladder; the base-class failover/override machinery walks this list.
    backends = ["curl_cffi", "Jina Reader", "stealth-browser"]
    tier = 0

    def check(self, config=None):
        # Always report the keyless rungs; probe only whether stealth is installed.
        self.active_backend = self.backends[0]
        if _stealth_installed():
            return (
                "ok",
                "Escalating fetch unlocker: curl_cffi -> Jina Reader -> stealth-browser",
            )
        return (
            "warn",
            "Escalating fetch unlocker: curl_cffi -> Jina Reader available; "
            "stealth-browser not installed "
            "(pip install 'searchts[browser]' && patchright install chromium)",
        )

    def read(self, url: str, config=None) -> str:
        """Read the page body, escalating through backends in order until real content is obtained."""
        order = self.ordered_backends(config)
        result = unlocker.fetch(url, backends=order)
        self.active_backend = result.backend
        return result.text
