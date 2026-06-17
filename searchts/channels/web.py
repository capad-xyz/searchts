# -*- coding: utf-8 -*-
"""Web — any URL via an escalating open-source unlocker.

Ladder (see searchts.unlocker): curl_cffi -> Jina Reader -> stealth-browser.
Always available; falls back gracefully when a bot-wall blocks one backend.
"""

from .base import Channel
from .. import unlocker


class WebChannel(Channel):
    name = "web"
    description = "Any web page"
    # Ordered ladder; the base-class failover/override machinery walks this list.
    backends = ["curl_cffi", "Jina Reader", "stealth-browser"]
    tier = 0

    def can_handle(self, url: str) -> bool:
        return True  # Fallback — handles any URL

    def check(self, config=None):
        # Always-available fallback channel: no network probe, keeping overhead at zero.
        self.active_backend = self.backends[0]
        return "ok", "Escalating fetch unlocker: curl_cffi -> Jina Reader -> stealth-browser"

    def read(self, url: str, config=None) -> str:
        """Read the page body, escalating through backends in order until real content is obtained."""
        order = self.ordered_backends(config)
        result = unlocker.fetch(url, backends=order)
        self.active_backend = result.backend
        return result.text
