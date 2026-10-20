# -*- coding: utf-8 -*-
"""Classify a response as content or as a wall, without knowing the site.

The problem this exists to solve: the previous approach was a list of phrases
copied from the sites that happened to break. LinkedIn's login copy, Reddit's
interstitial, Google's bot-check, Slack's cookie banner. That list is a
liability, because it only ever contains the walls we have already been
killed by, and every entry is a site name in the hot path.

Measured, while building this: structural HTML signals do **not** separate
walls from content. ``text_per_tag`` on the Guardian front page is 0.139 and on
Google's bot-check is 2.2, so the good page scores worse. ``dup_ratio``,
``short_line_frac`` and ``links_per_100w`` overlap just as badly. A JS-heavy
article and a blocking interstitial are both "text-light HTML", and no
threshold between them is honest.

What does separate is *what the page is about*. A wall is a page whose subject
is the wall: it talks about signing in, about cookies, about being human, about
being rate limited. That is a property of the text, holds on a site nobody has
heard of, and does not need a name to look up.

So each wall is a vocabulary family plus a density threshold, and the
thresholds come from measured separation rather than taste. On the corpus the
gaps are 15x or better, which is what makes a threshold in the middle defensible
instead of a guess.

Site identity belongs here only as *data*, for genuine per-site protocol facts
(reddit's public ``.json`` endpoint, for instance), never as branching logic in
the classifier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

__all__ = [
    "Wall",
    "classify",
    "classify_all",
    "scrub",
    "strip_trailing_consent",
    "FAMILIES",
    "WALL_NAMES",
]

#: Script and style bodies are not page text, they are code. A wall is
#: something a page *shows* a person; the same sentence inside a locale bundle
#: is marketing copy describing a banner that is not there. Stripe's homepage
#: ships ``"cookie_description":"We use cookies to improve your experience"``
#: in a 698 KB script, which reads as a consent wall and is not one. Its real
#: extract is 7,356 characters of article prose.
_SCRIPTISH = re.compile(
    r"(?is)<(script|style|noscript|template)\b.*?</\1\s*>"
    r"|<(script|style|noscript|template)\b[^>]*/>"
)


def scrub(html: str) -> str:
    """Drop script and style bodies so classifiers see only what a reader sees.

    Cheap, linear, and deliberately does not try to be a parser. Removing these
    elements cannot remove a wall: every real interstitial renders its message
    in ordinary markup, because if it did not the user would not see it.
    """
    return _SCRIPTISH.sub(" ", html or "")


@dataclass(frozen=True)
class Family:
    """One kind of wall, and the evidence that identifies it."""

    name: str
    #: Generic vocabulary for the thing the page is *about*. Deliberately not
    #: vendor names: a new bot manager that says "verify you are human" is caught
    #: by these words, and one that says something else is not caught by any
    #: name we could have guessed.
    words: "re.Pattern[str]"
    #: Hits per 100 words at or above which the extract IS this wall.
    per_100: float
    #: Below this many words the ratio is noise, so the family does not fire.
    min_words: int = 60


# ── vocabularies ─────────────────────────────────────────────────────────────
# Each is a set of words that mean "this page is about the wall", not words a
# site happens to use.

_AUTH = re.compile(
    r"(?i)\b("
    r"sign in|sign-in|signing in|log in|log-in|login|log into|logged out|"
    r"password|forgot (?:your )?password|reset (?:your )?password|"
    r"username|user name|email address|enter your (?:email|password)|"
    r"create (?:a |an )?(?:new |free )?account|sign ?up|register|"
    r"join now|join (?:today|free|now)|continue with|remember me|"
    r"already have an account|don'?t have an account|need an account|"
    r"members? only|subscribers? only|"
    # Narrower than "to view this". "to view this article" is what an article
    # says about itself; the wall needs the login verb attached to it.
    r"(?:sign|log) in to (?:view|read|continue|see)|"
    r"must be (?:logged|signed) in|"
    r"(?:view|read|continue|see) (?:the )?(?:full|rest of (?:the|this)) "
    r"(?:page|article|story|content)"
    r")\b"
)

_CONSENT = re.compile(
    r"(?i)\b("
    r"cookies?|consent|gdpr|ccpa|privacy (?:policy|settings|choices?)|"
    r"cookie (?:policy|settings|preferences|banner|consent|notice)|"
    r"accept (?:all|additional|the optional)|reject all|decline all|allow all|"
    r"manage (?:preferences|cookies)|your privacy,? your choice|"
    r"always active|essential cookies|optional cookies|"
    r"use(?:d)? (?:essential )?cookies|this website uses cookies|"
    r"we (?:use|value) your privacy"
    r")\b"
)

_BOTCHECK = re.compile(
    r"(?i)\b("
    r"captcha|recaptcha|hcaptcha|turnstile|"
    r"are you (?:a )?(?:human|robot|real person)|"
    r"verify (?:that )?you (?:are|'re) (?:a )?(?:human|human|real|not a robot)|"
    r"confirm (?:that )?you(?:'re| are) (?:a )?human|"
    r"unusual traffic|automated (?:requests?|access)|"
    r"bot (?:detection|protection|management)|"
    r"security check|checking your browser|just a moment|"
    r"enable javascript and cookies|press (?:&|and) hold|"
    r"ray id|reference #\d"
    r")\b"
)

_RATELIMIT = re.compile(
    r"(?i)\b("
    r"rate limit|too many requests|"
    r"you'?ve (?:been )?exceeded|exceeded your|"
    r"slow down|try again (?:in|after|later)|"
    r"temporarily (?:blocked|unavailable|limited)|"
    r"access (?:to this (?:page|resource) )?(?:has been )?(?:temporarily )?(?:denied|restricted)|"
    r"request unsuccessful"
    r")\b"
)

#: Measured thresholds. The separation on the dogfood corpus was 15x or better
#: for every family, which is what puts the line in the middle rather than on
#: the edge of the observed data.
FAMILIES: Tuple[Family, ...] = (
    Family("auth", _AUTH, 2.0, 60),
    Family("consent", _CONSENT, 2.0, 60),
    Family("botcheck", _BOTCHECK, 1.5, 50),
    Family("ratelimit", _RATELIMIT, 1.5, 50),
)

#: Every wall kind, for callers that only need "content or not".
WALL_NAMES = frozenset(f.name for f in FAMILIES)


@dataclass(frozen=True)
class Wall:
    """A verdict: the extract is a wall, and which kind."""

    kind: str
    per_100: float
    words: int

    def __str__(self) -> str:
        return f"{self.kind}-wall"


def density(text: str, words: "re.Pattern[str]") -> Tuple[int, int, float]:
    """(hits, total words, hits per 100 words) for ``words`` in ``text``."""
    raw = text or ""
    n = len(raw.split())
    if not n:
        return 0, 0, 0.0
    found = words.findall(raw)
    return len(found), n, 100.0 * len(found) / n


def distinct_term_count(text: str, words: "re.Pattern[str]") -> int:
    """How many *different* pieces of this family's wording appear in ``text``.

    Breadth, not volume. "Log in to your account. Email address. Password.
    Forgot your password? New to this service? Create an account." is a
    thirty-one word auth shell that names six different things; "sign in" said
    forty times in one menu link is one thing said a lot. Counting distinct
    alternations is what tells those apart at a length where no ratio works.
    """
    raw = text or ""
    seen = set()
    for m in words.finditer(raw):
        seen.add(m.group(0).lower())
    return len(seen)


#: Phrases so specific that no *wall* contains them without anything else: these
#: are what catches a fourteen-word extract, because the density families below
#: cannot do that job. They need a word count to have a denominator, and a short
#: auth shell does not have one. That is why both layers exist.
#:
#: "Specific no ordinary page contains them" was the claim, and it was measured
#: false on 2026-10-18. ``searchts read https://github.com/psf/requests`` is a
#: public repo page, and its extract (845 words, 6,414 characters) contains
#: "You must be signed in to star a repository" and "You must be signed in to
#: change notification settings", because that is what GitHub's star button and
#: its notification button put in ``aria-label`` and a tooltip. Every rung
#: refused the page with ``login-wall`` and the CLI told the caller to sign in.
#: The page's auth density was 0.59 per 100 words against a threshold of 2.0, so
#: every layer that has a denominator already had it right; only the marker
#: layer, which had none, said no.
#:
#: So a marker is now what it was always for: the answer where a ratio cannot be
#: computed. See :func:`classify`.
MARKERS: "Dict[str, Tuple[str, ...]]" = {
    "auth": (
        "sign in to continue",
        "please sign in to continue",
        "log in to continue",
        "please log in to continue",
        "you must be logged in",
        "you must be signed in",
        "you need to sign in",
        "join now",
        "new to linkedin",
        "sign in to linkedin",
    ),
    "consent": (
        "we use cookies to",
        "this site uses cookies",
        "by continuing you accept our cookies",
        "accept all cookies",
        "your privacy, your choice",
    ),
    "botcheck": (
        "are you a robot",
        "are you a human",
        "verify you are human",
        "verify that you are human",
        "confirm you are human",
        "detected unusual traffic",
        "solving the above captcha",
        "unusual traffic from your",
    ),
    "ratelimit": (
        "too many requests",
        "rate limit exceeded",
        "you have exceeded",
    ),
}

#: Below a family's ``min_words``, a ratio has no denominator to be a ratio
#: against. The rule that works at that length is breadth instead: a short auth
#: shell names many *different* things it wants from you (log in, account,
#: password, email address, create an account), while prose about scraping
#: mentions one of them once and moves on. Counted as distinct families of
#: wording rather than raw occurrences, so "sign in" repeated twenty times in
#: one link does not reach the bar on its own.
SHORT_SHELL_MIN_TERMS = 3

#: Family lookup by name, for the one rule that needs a marker's own family.
_BY_NAME: Dict[str, Family] = {f.name: f for f in FAMILIES}


def _marker_wall(kind: str, raw: str) -> Optional[Wall]:
    """Does a marker in ``kind`` call this extract a wall?

    A marker exists for the extract with no denominator: "sign in to continue"
    is four words, and no ratio can be a ratio against four words. That is the
    whole of its job, and it is a good one. Past the family's own word floor
    there *is* a denominator, so the marker's family gets to vote, and the
    marker only carries the page when that family already says the page is
    about the wall.

    This is not a new threshold and it is not a list of sites. It is the
    sentence the module has claimed since it was written - a wall is a page
    whose *subject* is the wall - applied to the one layer that was not
    applying it. Measured on two real GitHub pages that are the same shape and
    opposite answers (2026-10-18, ``curl_cffi`` impersonating Chrome):

    * ``github.com/login``, a wall: 76 words, 6.58 auth hits per 100
    * ``github.com/psf/requests``, public and not a wall: 845 words, 0.59

    The wall is 3.3x over its threshold and the page that is not a wall is 3.4x
    under it, so the family threshold decides both and the marker is silent on
    both. Neither is near the line, which is what makes reusing the existing
    threshold here defensible rather than a guess.
    """
    fam = _BY_NAME[kind]
    _hits, total, per_100 = density(raw, fam.words)
    if total < fam.min_words or per_100 >= fam.per_100:
        return Wall(kind, 100.0, total)
    return None


def classify(text: str) -> Optional[Wall]:
    """Return the wall this extract is, or None if it looks like content.

    Three layers, because they fail in different ways. Markers are exact and
    fire where no ratio has a denominator yet, including a fourteen-word
    extract; above that floor they have to agree with their own family. Families
    are a ratio, so they catch the walls whose copy we never wrote down and are
    what makes this work on a site nobody has heard of. Breadth covers the gap
    between them, where a ratio has no denominator to divide by.

    Accepts either an extract or raw HTML. Script and style bodies are dropped
    first, because a wall is something a page shows a person and copy inside a
    script is not shown to anyone. See :func:`scrub`.
    """
    raw = scrub(text)
    if not raw.strip():
        return None
    low = raw.lower()
    for kind, phrases in MARKERS.items():
        if any(p in low for p in phrases):
            # Kept for the kind it named rather than breaking on the first
            # marker that matched: a page whose chrome carries one family's
            # marker can still be that family's wall, and the family layers
            # below are what decide it.
            found = _marker_wall(kind, raw)
            if found is not None:
                return found
    for fam in FAMILIES:
        hits, total, per_100 = density(raw, fam.words)
        if total < fam.min_words:
            if distinct_term_count(raw, fam.words) >= SHORT_SHELL_MIN_TERMS:
                return Wall(fam.name, round(per_100, 2), total)
            continue
        if per_100 >= fam.per_100:
            return Wall(fam.name, round(per_100, 2), total)
    return None


#: A consent dialog tacked onto a real page is not the page. The whole extract
#: being the dialog is a wall, and :func:`classify` already names that. This
#: only removes a short block that sits at the end, after a substantial body.
_BANNER_BODY_MIN = 2000
_BANNER_MAX_CHARS = 900
_BANNER_OPEN = re.compile(
    r"(?i)(?:by continuing to use this website, you agree\b|"
    r"by continuing you accept our cookies\b|"
    r"we use cookies to\b|"
    r"this (?:site|website) uses cookies\b|"
    r"your privacy, your choice\b)"
)
_BANNER_CHOICE_LINE = re.compile(
    r"(?im)^[ \t]*(?:[-*][ \t]+)?(?:\*\*)?"
    r"(?:necessary cookies only|accept all(?: cookies)?|reject all(?: cookies)?|"
    r"customize settings|cookie settings|manage preferences|only necessary)"
    r"(?:\*\*)?[ \t]*$"
)


def strip_trailing_consent(text: str) -> Tuple[str, bool]:
    """Drop a cookie dialog that follows a real page.

    Returns ``(text, True)`` when a short dialog was removed from the end, and
    ``(text, False)`` otherwise. A page that is itself the dialog is left
    whole: there is no substantial body in front of it, so this is not the
    function that decides it is a wall.
    """
    raw = text or ""
    if len(raw) < _BANNER_BODY_MIN + 40:
        return raw, False
    start_at = max(0, len(raw) - (_BANNER_MAX_CHARS + 200))
    found: Optional[int] = None
    for match in _BANNER_OPEN.finditer(raw[start_at:]):
        abs_at = start_at + match.start()
        prefix = raw[:abs_at]
        if prefix and not prefix.endswith("\n"):
            line_start = raw.rfind("\n", 0, abs_at) + 1
            if raw[line_start:abs_at].strip():
                continue
        rest = raw[abs_at:]
        if len(rest) > _BANNER_MAX_CHARS or len(prefix.strip()) < _BANNER_BODY_MIN:
            continue
        if _BANNER_CHOICE_LINE.search(rest) is None:
            continue
        found = abs_at
    if found is None:
        return raw, False
    return raw[:found].rstrip(), True


def classify_all(text: str) -> Dict[str, float]:
    """Every family's density, for reporting and for setting thresholds."""
    raw = scrub(text)
    out: Dict[str, float] = {}
    for fam in FAMILIES:
        _hits, total, per_100 = density(raw, fam.words)
        out[fam.name] = round(per_100, 2) if total >= fam.min_words else 0.0
    return out
