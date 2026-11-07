# -*- coding: utf-8 -*-
"""The browser and profile settings, in browser-neutral names.

``SEARCHTS_BROWSER`` and ``SEARCHTS_BROWSER_PROFILE`` name any supported
browser. The old LinkedIn-shaped names are kept as aliases:

    SEARCHTS_BROWSER          preferred over  SEARCHTS_LINKEDIN_CHROME
    SEARCHTS_BROWSER_PROFILE  preferred over  SEARCHTS_LINKEDIN_PROFILE

The old name wins only when the new one is unset (or blank), so a machine that
already exports the legacy pair keeps working unchanged. Precedence is
per-setting: setting only ``SEARCHTS_BROWSER`` still leaves a legacy profile
in force.

``SEARCHTS_BROWSER`` accepts either an executable path or a supported browser
name (``vivaldi``, ``zen``, ...). A name is resolved to an installed
executable when one can be found; otherwise it is returned as written so the
caller can report what it was given rather than silently choosing Chrome.
"""

from __future__ import annotations

import os
from typing import Optional

from searchts.session_cookies import ALL_BROWSERS

__all__ = [
    "BROWSER_ENV",
    "LEGACY_BROWSER_ENV",
    "LEGACY_PROFILE_ENV",
    "PROFILE_ENV",
    "browser_executable",
    "browser_profile",
    "browser_raw",
    "profile_raw",
    "setting_source",
]

BROWSER_ENV = "SEARCHTS_BROWSER"
PROFILE_ENV = "SEARCHTS_BROWSER_PROFILE"
LEGACY_BROWSER_ENV = "SEARCHTS_LINKEDIN_CHROME"
LEGACY_PROFILE_ENV = "SEARCHTS_LINKEDIN_PROFILE"

_KNOWN = frozenset(ALL_BROWSERS)


def _value(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _first(*names: str) -> str:
    """The first non-blank setting, in precedence order."""
    for name in names:
        raw = _value(name)
        if raw:
            return raw
    return ""


def setting_source(setting: str) -> str:
    """The environment variable that supplied ``setting``, or ``""``.

    ``setting`` is ``"browser"`` or ``"profile"``. This exists so a message can
    name the variable the user actually set instead of always naming both.
    """
    if setting == "browser":
        if _value(BROWSER_ENV):
            return BROWSER_ENV
        if _value(LEGACY_BROWSER_ENV):
            return LEGACY_BROWSER_ENV
        return ""
    if setting == "profile":
        if _value(PROFILE_ENV):
            return PROFILE_ENV
        if _value(LEGACY_PROFILE_ENV):
            return LEGACY_PROFILE_ENV
        return ""
    raise ValueError(f"unknown browser setting {setting!r}")


def browser_raw() -> str:
    """The configured browser setting, a name or a path, or ``""``."""
    return _first(BROWSER_ENV, LEGACY_BROWSER_ENV)


def profile_raw() -> str:
    """The configured user-data/profile path, or ``""``."""
    return _first(PROFILE_ENV, LEGACY_PROFILE_ENV)


def browser_executable() -> Optional[str]:
    """The configured browser as an executable path, or ``None``.

    A supported browser name is resolved through
    :func:`searchts.browser_detect.executable_for`; an unresolvable name is
    returned unchanged rather than dropped, because the failure should name
    what the user asked for.
    """
    raw = browser_raw()
    if not raw:
        return None
    text = os.path.expanduser(raw)
    if os.sep in raw or "/" in raw or "\\" in raw or raw.startswith("."):
        return text
    if raw.lower() in _KNOWN:
        from searchts.browser_detect import executable_for

        found = executable_for(raw.lower())
        if found:
            return found
    return text


def browser_profile() -> Optional[str]:
    """The configured profile directory, expanded, or ``None``."""
    raw = profile_raw()
    if not raw:
        return None
    return os.path.expanduser(raw)
