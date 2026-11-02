# -*- coding: utf-8 -*-
"""LinkedIn: the native reader, and whether a login is kept.

searchts reads LinkedIn profiles, companies, posts and people search itself,
through the same unlocker as every other site. A kept login is what makes those
reads complete; without one, public pages still read, but the signed-in
sections do not. The old ``linkedin-scraper-mcp`` bridge is an optional
fallback for the feed and for write/inbox tools, not part of the first pass.
"""

from searchts import login_store

from .base import Channel

#: The kept site (registrable domain) and the two commands that set it up.
_SITE = "linkedin.com"
_SIGNIN = "searchts login signin https://www.linkedin.com"
_KEEP = (
    "searchts login keep https://www.linkedin.com "
    "--cookies-from-browser firefox --yes"
)
_FALLBACK = (
    "The LinkedIn feed and write/inbox tools are the optional "
    "linkedin-scraper-mcp fallback: `searchts install --only linkedin`."
)


class LinkedInChannel(Channel):
    name = "linkedin"
    description = "LinkedIn professional network"
    backends = ["native read", "linkedin-scraper-mcp"]
    tier = 2

    def check(self, config=None):
        """Read the kept-login store; no network and no subprocess.

        A live login is an ``ok``: the native reader has everything it needs.
        No login is a ``warn`` with the two login commands, because public
        pages still read and asking for a login is a suggestion, not a fault.
        """
        self.active_backend = None
        try:
            entry = login_store.list_kept().get(_SITE) or {}
        except Exception:  # noqa: BLE001 - doctor must survive a bad store
            entry = {}
        cookies = int(entry.get("cookies") or 0)
        if cookies > 0 and not entry.get("expired"):
            self.active_backend = "native read"
            expiry = entry.get("expiry") or "unknown"
            return "ok", (
                f"native read with a kept login ({cookies} cookies, {expiry}). "
                f"Profiles, companies, posts and people search read directly. {_FALLBACK}"
            )
        return "warn", (
            "no live LinkedIn login is kept, so only public pages read. "
            "Sign in once:\n"
            f"  {_SIGNIN}\n"
            f"  {_KEEP}\n"
            f"{_FALLBACK}"
        )
