# -*- coding: utf-8 -*-
"""A login wall, and the login already sitting in one of your browsers.

When a read hits a login wall on a site other than LinkedIn, searchts asks a
narrow question of every installed browser profile: does it hold a cookie for
this site's registrable domain? That is presence only -- the scan never
decrypts, prints, logs or copies a value, and it never opens a keychain.

If one or more profiles answer yes:

* on a terminal, the user is offered a numbered choice of browser, then one
  explicit ``[y/N]`` before anything is copied. A yes goes through the same
  ``login keep`` path the CLI uses, so the session grant, the host-scoped
  copy and the kept-login store are not reimplemented here.
* without a terminal, or with ``--json``, nothing is copied. The exact
  command that would copy one browser's cookies is printed instead.

LinkedIn is excluded on purpose. Its signed-in browser is reached by
attaching over CDP, not by copying a cookie store, so the wall names
``SEARCHTS_LINKEDIN_ATTACH`` and the browser's inspect page instead.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, TextIO, Tuple
from urllib.parse import urlparse

from searchts import browser_detect
from searchts.session_cookies import registrable

__all__ = [
    "Offer",
    "command_for",
    "copy_and_keep",
    "is_linkedin",
    "offer_login_copy",
    "site_of",
]

LINKEDIN_SITE = "linkedin.com"

#: ``scan`` returns one entry per profile that answered; only ``found`` ones
#: become a choice. ``copy`` is the keep path, injected by tests.
Scan = Callable[[str], Sequence[browser_detect.Presence]]
Copy = Callable[[str, str], str]


@dataclass
class Offer:
    """What a login wall offered, and what happened.

    ``text`` is safe to print: it names sites and browsers, never a cookie.
    ``commands`` holds the exact ``login keep`` lines for a ``commands``
    offer, kept separately so a caller can print them unwrapped.
    ``kind`` is ``linkedin``, ``commands``, ``copied``, ``skipped``,
    ``copy_failed`` or ``none``.
    """

    site: str
    kind: str
    text: str = ""
    browsers: Tuple[str, ...] = ()
    commands: Tuple[str, ...] = ()
    copied: bool = False
    copied_from: str = ""
    error: str = ""

    @property
    def found(self) -> bool:
        return bool(self.browsers)

    @property
    def full_text(self) -> str:
        """``text`` plus the exact commands, for one-field output such as JSON."""
        if not self.commands:
            return self.text
        return "\n".join((self.text, *self.commands))


def site_of(url: str) -> str:
    """The registrable domain of ``url``, or its host when it has none."""
    host = (urlparse(url if "://" in url else "https://" + url).hostname or "").lower()
    return registrable(host) or host.strip(".")


def is_linkedin(site: str) -> bool:
    key = (site or "").strip().lower().lstrip(".")
    return key == LINKEDIN_SITE or key.endswith("." + LINKEDIN_SITE)


def command_for(site: str, browser: str) -> str:
    """The exact command that copies one browser's login and keeps it."""
    return (
        f"searchts login keep {site} --cookies-from-browser {browser} --yes"
    )


def _display(browser: str) -> str:
    return browser_detect._display(browser)  # one label table, not a second


def _unique(presences: Sequence[browser_detect.Presence]) -> List[browser_detect.Presence]:
    """One entry per browser, first profile wins. The menu is per browser."""
    seen = set()
    out: List[browser_detect.Presence] = []
    for presence in presences:
        if presence.browser in seen:
            continue
        seen.add(presence.browser)
        out.append(presence)
    return out


def _commands_text(site: str, choices: Sequence[browser_detect.Presence]) -> str:
    names = ", ".join(_display(p.browser) for p in choices)
    return (
        f"{site} is behind a login, and {names} already "
        f"hold{'s' if len(choices) == 1 else ''} a cookie for it. "
        "Nothing was copied; the scan only checked whether a cookie exists. "
        "Copy one browser's login and keep it:"
    )


def _linkedin_text() -> str:
    """The attach route, never the cookie scan. LinkedIn only."""
    from searchts import browser_settings, linkedin_attach

    browser, _explicit = linkedin_attach.browser_of(
        browser_settings.browser_executable(),
        browser_settings.browser_profile(),
        "",
    )
    if browser not in linkedin_attach.ATTACH_BROWSERS:
        browser = "chrome"
    page = linkedin_attach.inspect_url(browser)
    return (
        "LinkedIn is excluded from the cookie-presence scan: its signed-in "
        "browser is reached by attaching, not by copying a cookie store.\n"
        "Set SEARCHTS_LINKEDIN_ATTACH=on, open "
        f"{page}, and tick \"Allow remote debugging for this browser "
        "instance\". Then read the LinkedIn page again."
    )


def _ask(
    prompt: str,
    *,
    stdin: TextIO,
    stderr: TextIO,
) -> str:
    stderr.write(prompt)
    stderr.flush()
    try:
        return stdin.readline().strip()
    except (OSError, ValueError):
        return ""


def offer_login_copy(
    url: str,
    *,
    interactive: Optional[bool] = None,
    json_mode: bool = False,
    stdin: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
    scan: Optional[Scan] = None,
    copy: Optional[Copy] = None,
) -> Offer:
    """Offer a kept login when the wall's site has a cookie in a local browser.

    Non-interactive (or ``--json``) never copies: it returns the exact commands
    instead. Interactive asks which browser, then asks for an explicit yes,
    and only then calls the existing keep path.
    """
    site = site_of(url)
    if not site:
        return Offer(site="", kind="none")

    if is_linkedin(site):
        return Offer(site=site, kind="linkedin", text=_linkedin_text())

    input_stream = stdin if stdin is not None else sys.stdin
    error_stream = stderr if stderr is not None else sys.stderr
    if interactive is None:
        interactive = (not json_mode) and bool(getattr(input_stream, "isatty", lambda: False)())

    scan_fn = scan or browser_detect.cookie_presence
    presences = [p for p in scan_fn(site) if p.found]
    choices = _unique(presences)
    if not choices:
        return Offer(site=site, kind="none")

    browsers = tuple(p.browser for p in choices)
    if not interactive:
        return Offer(
            site=site,
            kind="commands",
            text=_commands_text(site, choices),
            browsers=browsers,
            commands=tuple(command_for(site, p.browser) for p in choices),
        )

    lines = [f"{site} is behind a login. A cookie for it exists in:"]
    for index, presence in enumerate(choices, start=1):
        lines.append(f"  {index}) {_display(presence.browser)}")
    error_stream.write("\n".join(lines) + "\n")
    error_stream.flush()
    answer = _ask(
        "Which browser should searchts copy the login from? "
        "Enter a number, or press Enter to skip: ",
        stdin=input_stream,
        stderr=error_stream,
    )
    if not answer.isdigit():
        return Offer(site=site, kind="skipped", browsers=browsers)
    index = int(answer)
    if not 1 <= index <= len(choices):
        return Offer(site=site, kind="skipped", browsers=browsers)

    chosen = choices[index - 1]
    confirm = _ask(
        f"Copy {site}'s cookies from {_display(chosen.browser)} and keep "
        f"them? [y/N]: ",
        stdin=input_stream,
        stderr=error_stream,
    ).lower()
    if confirm not in ("y", "yes"):
        return Offer(site=site, kind="skipped", browsers=browsers)

    copy_fn = copy or copy_and_keep
    try:
        why = copy_fn(site, chosen.browser)
    except Exception as exc:  # noqa: BLE001 - the read still fails, with a reason
        message = (
            str(exc)
            if type(exc).__name__.endswith("Error")
            else f"copy failed ({type(exc).__name__})"
        )
        return Offer(
            site=site,
            kind="copy_failed",
            text=f"could not copy {site}'s login from {_display(chosen.browser)}: {message}",
            browsers=browsers,
            copied_from=chosen.browser,
            error=message,
        )
    return Offer(
        site=site,
        kind="copied",
        text=why,
        browsers=browsers,
        copied=True,
        copied_from=chosen.browser,
    )


def copy_and_keep(site: str, browser: str) -> str:
    """Copy one site's cookies from ``browser`` and keep them, with consent.

    This is the same sequence ``searchts login keep <site>
    --cookies-from-browser <browser> --yes`` runs: the session grant, the
    host-scoped copy through the browser's own reader, then the kept-login
    store. The caller has already asked for an explicit yes.
    """
    from searchts.cdp_profile import read_site_cookies
    from searchts.login_store import (
        grant_session_copy,
        keep,
        note_copied,
        require_copy_consent,
    )

    grant_session_copy()
    require_copy_consent(site)

    def confirm_debugger(prompt: str) -> bool:
        print(prompt, file=sys.stderr, flush=True)
        return True

    source = read_site_cookies(
        site, browser, confirm=confirm_debugger, family=True
    )
    note_copied(site)
    kept = keep(site, source.cookies, browser=browser)
    return kept.why
