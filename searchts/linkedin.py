# -*- coding: utf-8 -*-
"""LinkedIn: read the content, not the page's own furniture.

A signed-in LinkedIn page is mostly chrome. A profile's top card comes with a
notification count, a Premium upsell, owner-only buttons ("Enhance profile",
"Add section", "Open to"), an ad-options panel, the full language picker and a
footer; a company page repeats the ad panel and adds its own Premium upsell.
That is what a reader got back, and the actual profile was three lines at the
top (#443).

This module is the site's own file, in the same shape as :mod:`searchts.players`
and :mod:`searchts.walls`: no plugin registry, no router in the ladder. It
holds four small facts about one host:

* which URLs are LinkedIn (:func:`matches`), and which are a person's profile
  (:func:`is_profile`);
* the extra pages a profile keeps its sections on (:func:`detail_urls`);
* the product chrome lines that are safe to drop (:func:`strip_chrome`);
* how to join a profile's top card and its sections (:func:`assemble`).

``strip_chrome`` is deliberately line-based and exact-match. The only phrases
it removes are LinkedIn's own fixed UI strings, plus blocks whose *shape* is
known (the ad panel from "Ad Options" to "Submit", the language picker, the
profile-language panel). A post that happens to contain prose is never matched
by a block, because a block stops at the first line it does not recognise and
leaves that line and everything after it untouched.
"""

from __future__ import annotations

import re
from typing import List, Optional, Sequence, Tuple
from urllib.parse import urlparse

__all__ = [
    "matches",
    "is_profile",
    "browser_first",
    "detail_urls",
    "strip_chrome",
    "has_section_content",
    "assemble",
    "rate_limit_hint",
    "SECTION_DELAY",
]

_LINKEDIN = "linkedin.com"

#: Seconds to wait between the profile read and each extra section request.
#: LinkedIn rate-limits tightly (measured 2026-11-02: seven reads in three
#: minutes earned an http-429), so a profile assembly spends its two extra
#: requests slowly rather than in a burst.
SECTION_DELAY = 2.0

#: A person's profile, and only that: ``/in/<handle>/``. A details page
#: (``/in/<handle>/details/experience/``), a post, or an activity feed is not
#: a profile to assemble.
_PROFILE_PATH = re.compile(r"^/in/[^/]+/?$")

#: Routes whose content LinkedIn builds in the browser. Measured 2026-11-02:
#: ``/search/results/people/?keywords=`` failed on curl_cffi and returned 200
#: from the stealth browser. Asking the browser first saves the direct request
#: that is known to lose; the remaining rungs stay in place.
_BROWSER_FIRST_PREFIX = "/search/results/"

#: The Education section is the same: measured 2026-11-02, curl_cffi returned
#: HTTP 200 with only the page shell (title, profile link, language list), and
#: the school entries are rendered in the browser. Experience still renders in
#: the markup, so only this one section moves ahead of the direct rung.
_BROWSER_FIRST_SECTION = re.compile(r"^/in/[^/]+/details/education/?$")


def _host(url: str) -> str:
    """Lower-case host of `url` (a bare host is accepted), no trailing dot."""
    return (
        urlparse(url if "://" in url else "https://" + url).hostname or ""
    ).lower().rstrip(".")


def matches(url: str) -> bool:
    """True for linkedin.com and its subdomains, and nothing that looks like it."""
    host = _host(url)
    return host == _LINKEDIN or host.endswith("." + _LINKEDIN)


def is_profile(url: str) -> bool:
    """True when `url` is a person's main profile page."""
    path = urlparse(url if "://" in url else "https://" + url).path or ""
    return bool(_PROFILE_PATH.fullmatch(path))


def browser_first(url: str) -> bool:
    """True for a LinkedIn route only the browser renders.

    Search results and a profile's Education section. Every other route keeps
    the ordinary ladder, so a page whose markup carries the content still gets
    the cheap direct request first.
    """
    if not matches(url):
        return False
    path = urlparse(url if "://" in url else "https://" + url).path or ""
    return bool(
        path.startswith(_BROWSER_FIRST_PREFIX)
        or _BROWSER_FIRST_SECTION.fullmatch(path)
    )


def detail_urls(url: str) -> List[Tuple[str, str]]:
    """The ``(section, url)`` pages a profile keeps its sections on.

    Empty when `url` is not a profile, so a caller can treat "no sections" and
    "not a profile" the same way. Both URLs keep the profile's own scheme and
    host, which is what the read was already scoped to.
    """
    if not is_profile(url):
        return []
    parsed = urlparse(url if "://" in url else "https://" + url)
    handle = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if not handle:
        return []
    base = f"{parsed.scheme or 'https'}://{parsed.netloc or 'www.linkedin.com'}"
    root = f"{base}/in/{handle}/details"
    return [
        ("Experience", f"{root}/experience/"),
        ("Education", f"{root}/education/"),
    ]


def rate_limit_hint() -> str:
    """What a LinkedIn http-429 means, and what to do instead of queueing more."""
    return (
        "LinkedIn is rate limiting this address (http-429). Wait a few minutes "
        "and retry; this read stopped rather than spending more requests on the "
        "same host. A profile read adds one request per section."
    )


# ── chrome ──────────────────────────────────────────────────────────────────

#: A notification count in the header. Fixed shape, never prose.
_NOTIFICATIONS = re.compile(r"^\d[\d,]* notifications?$", re.IGNORECASE)
_TRY_PREMIUM = re.compile(r"^Try Premium(?: for .+)?$")
_ACTIVATE_PREMIUM = re.compile(r"^\[Activate Premium for ")
_CORPORATION = re.compile(r"^LinkedIn Corporation © \d{4}$")
#: One injected Premium card between feed posts. Matched inside a block that
#: begins at its own specific heading.
_PREMIUM_BOARD_LINE = re.compile(
    r"(?:Premium members are .* more likely to get hired"
    r"|and millions more use Premium$"
    r"|^\[Try for free\]\()"
)

#: UI labels that are unmistakably LinkedIn's own, wherever they appear. Short
#: ordinary words ("Resources", "Open to") are deliberately not here: those
#: need a neighbouring button before they count, see :func:`_button_context`.
_CHROME_EXACT = frozenset({
    "Enhance profile",
    "Enhance cover image",
    "Visit our Help Center.",
    "Go to your Settings.",
    "Learn more about Recommended Content.",
})

#: The whole ad-options panel, in page order. It starts at "Ad Options" and ends
#: at "Submit"; if LinkedIn changes a line the block stops there and keeps the
#: rest, which is the safe direction.
_AD_BLOCK = frozenset({
    "Why am I seeing this ad?",
    "Manage your ad preferences",
    "Hide or report this ad",
    "I don’t want to see this ad in my feed",
    "Don’t want to see this",
    "Tell us why you don’t want to see this",
    "Your feedback will help us improve your experience",
    "It’s annoying or not interesting",
    "I’ve seen the same ad too often",
    "If you think this goes against our Professional Community Policies, "
    "please let us know.",
    "Report this ad",
})

#: The English name of every language LinkedIn offers, which is the stable part
#: of its picker line. The text before the parenthesis is NOT stable: LinkedIn's
#: own extraction drops combining marks in some scripts, so `हिंदी (Hindi)`
#: arrives as `हिदी (Hindi)` and `తెలుగు (Telugu)` as `తలుగు (Telugu)` (measured
#: 2026-11-02). Matching the exact line stopped at Hindi and left the rest of
#: the list in the read. Only the block after "Select language" is filtered;
#: outside it a line ending in a parenthesis is content.
_LANGUAGE_NAMES = (
    "Arabic", "Bangla", "Czech", "Danish", "German", "Greek", "English",
    "Spanish", "Persian", "Finnish", "French", "Hindi", "Hungarian",
    "Indonesian", "Italian", "Hebrew", "Japanese", "Korean", "Marathi",
    "Malay", "Dutch", "Norwegian", "Punjabi", "Polish", "Portuguese",
    "Romanian", "Russian", "Swedish", "Telugu", "Thai", "Tagalog", "Turkish",
    "Ukrainian", "Vietnamese", "Chinese (Simplified)",
    "Chinese (Traditional)",
)

#: ``<anything> (<English name>)``, e.g. `English (English)`. Anchored at both
#: ends so prose that merely mentions a language keeps its line.
_LANGUAGE_LINE = re.compile(
    r"^.+ \((?:" + "|".join(re.escape(n) for n in _LANGUAGE_NAMES) + r")\)$"
)

#: Owner-only buttons. Only dropped when another one sits next to them, so a
#: single line that says "Resources" in a post survives.
_BUTTONS = frozenset({"Resources", "Open to", "Enhance profile", "Enhance cover image"})


def _next_content(lines: Sequence[str], i: int, step: int) -> int:
    j = i + step
    while 0 <= j < len(lines) and not lines[j].strip():
        j += step
    return j if 0 <= j < len(lines) else -1


def _button_context(lines: Sequence[str], i: int) -> bool:
    for step in (-1, 1):
        j = _next_content(lines, i, step)
        if j < 0:
            continue
        neighbour = lines[j].strip()
        if neighbour in _BUTTONS or neighbour.startswith("[Add section]("):
            return True
    return False


def _drop_footer_line(line: str) -> bool:
    return bool(
        _CORPORATION.match(line)
        or line.startswith((
            "[Questions?](",
            "[Manage your account and privacy](",
            "[Recommendation transparency](",
            "[Activate Premium for ",
            "[Add section](",
        ))
        or line.startswith("1-month free trial.")
    )


def _drop_simple(line: str, lines: Sequence[str], i: int) -> bool:
    return bool(
        _NOTIFICATIONS.match(line)
        or _TRY_PREMIUM.match(line)
        or line in _CHROME_EXACT
        or _drop_footer_line(line)
        or (line in _BUTTONS and _button_context(lines, i))
    )


def strip_chrome(text: str) -> str:
    """Remove LinkedIn's fixed page furniture, keeping every content line.

    The rule is the same one ``more.py`` uses for a side panel: only drop what
    is named, and stop a block at the first line that is not part of it. A
    profile's name, headline, location, connections, experience prose and
    company posts are never in any set here, so they cannot match.
    """
    lines = (text or "").split("\n")
    out: List[str] = []
    i = 0
    in_ad = False
    in_language = False
    in_premium = False
    while i < len(lines):
        line = lines[i]
        clean = line.strip()

        if in_ad:
            if not clean or clean in _AD_BLOCK:
                i += 1
                continue
            if clean == "Submit":
                in_ad = False
                i += 1
                continue
            in_ad = False

        if in_language:
            if not clean or _LANGUAGE_LINE.match(clean):
                i += 1
                continue
            in_language = False

        if in_premium:
            if not clean or _PREMIUM_BOARD_LINE.search(clean):
                if clean.startswith("[Try for free]("):
                    in_premium = False
                i += 1
                continue
            in_premium = False

        if clean == "Ad Options":
            in_ad = True
            i += 1
            continue
        if clean == "Select language":
            in_language = True
            i += 1
            continue
        if clean == "Boost your job search":
            in_premium = True
            i += 1
            continue

        if clean == "Profile language":
            # Owner-only panel: the language, then the public URL. Both are
            # page furniture, and both are only skipped when they are there.
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                j += 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and lines[j].strip() == "Public profile & URL":
                j += 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and re.fullmatch(
                    r"(?:www\.)?linkedin\.com/in/\S+/?", lines[j].strip()
                ):
                    j += 1
            i = j
            continue

        if _drop_simple(clean, lines, i):
            i += 1
            continue

        out.append(line)
        i += 1

    squeezed: List[str] = []
    blank = False
    for line in out:
        if not line.strip():
            if blank:
                continue
            blank = True
            squeezed.append("")
        else:
            blank = False
            squeezed.append(line.rstrip())
    return "\n".join(squeezed).strip()


# ── assembly ────────────────────────────────────────────────────────────────

#: The shell a JavaScript-rendered section page comes back as: a title, a link
#: to the profile itself, and bracketed notes. Nothing here can be a school,
#: employer, date or sentence, so ignoring these lines cannot drop content.
_SHELL_TITLE = re.compile(r".*\|\s*LinkedIn\s*$")
_SHELL_PROFILE_LINK = re.compile(
    r"^\[[^\]]*\]\(https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[^)]*\)$"
)
_SHELL_NOTE = re.compile(r"^\[(?:media|left out|linkedin)\b.*\]$")


def has_section_content(text: str) -> bool:
    """True when a section page holds more than its own header and notes.

    LinkedIn's Education page renders its entries in JavaScript. Measured
    2026-11-02: curl_cffi returned HTTP 200 with the title line
    ``Name | LinkedIn``, a link to the profile, the language picker and
    bracketed notes, and no schools. Joining that shell as the Education
    section would claim an empty education.

    Conservative by construction: a line counts as content unless it is one of
    the three known shell shapes, so any unexpected line keeps the section.
    """
    for line in strip_chrome(text).splitlines():
        clean = line.strip()
        if not clean:
            continue
        if _SHELL_TITLE.match(clean) or _SHELL_NOTE.match(clean):
            continue
        if _SHELL_PROFILE_LINK.match(clean):
            continue
        return True
    return False


def _without_heading(text: str, label: str) -> str:
    """Drop the section page's own leading heading, which becomes a Markdown one."""
    body = (text or "").strip()
    first, _, rest = body.partition("\n")
    if first.strip().lower() == label.lower():
        return rest.strip()
    return body


def assemble(
    base: str,
    sections: Sequence[Tuple[str, Optional[str], str]],
) -> Tuple[str, List[str]]:
    """Join a profile's top card and its section pages into one document.

    ``sections`` holds ``(label, text, reason)``: text when the section was
    read, reason when it was not. A failed section is named in a trailing note
    and never costs the caller the rest of the profile (fail loud about the
    missing part, not about the whole read).
    """
    parts = [(base or "").strip()]
    notes: List[str] = []
    for label, text, reason in sections:
        if not text:
            why = reason or "no text came back"
            notes.append(
                f"[linkedin: the {label} section could not be read ({why}); "
                f"the rest of the profile is here]"
            )
            continue
        parts.append(f"## {label}\n\n{_without_heading(text, label)}")
    return "\n\n".join(p for p in parts if p), notes
