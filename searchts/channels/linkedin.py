# -*- coding: utf-8 -*-
"""LinkedIn: the native reader, and whether a login is kept.

searchts reads LinkedIn profiles, companies, posts and people search itself,
through the same unlocker as every other site. A kept login is what makes those
reads complete; without one, public pages still read, but the signed-in
sections do not. The feed attaches to a running Chromium browser when
remote debugging is on for that instance, and otherwise is read in the
signed-in browser profile when ``SEARCHTS_BROWSER_PROFILE`` (or its legacy
alias ``SEARCHTS_LINKEDIN_PROFILE``) is set. The old
``linkedin-scraper-mcp`` bridge
is an optional fallback for write/inbox tools, and for the feed when that
profile is not available. It is not part of the first pass.
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
    "The feed attaches to a running Chromium browser, or is read in the "
    "signed-in browser (SEARCHTS_BROWSER_PROFILE; the legacy "
    "SEARCHTS_LINKEDIN_PROFILE alias works too) when that browser is not "
    "already open. linkedin-scraper-mcp remains the fallback "
    "for write/inbox tools, and for the feed when no profile is set: "
    "`searchts install --only linkedin`."
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
