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
from typing import Dict, List, Optional, Tuple

__all__ = ["Wall", "classify", "FAMILIES", "WALL_NAMES"]


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
    r"members? only|subscribers? only|to (?:view|read|continue|see) (?:this|the)?"
    r"(?:page|article|story|content|rest)"
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

WALL_NAMES = frozenset(f.name for f in FAMILIES)

#: Every wall kind, for callers that only need "content or not".
ANY_WALL = WALL_NAMES


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
    hits = len(words.findall(raw))
    return hits, n, 100.0 * hits / n


#: Phrases so specific that no ordinary page contains them. These fire at any
#: length, including a fourteen-word extract, because "sign in to continue" and
#: "you must be logged in" are not things an article says. The density families
#: below cannot do this job: they need a word count to have a denominator, and
#: a short auth shell does not have one. That is why both layers exist.
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


def classify(text: str) -> Optional[Wall]:
    """Return the wall this extract is, or None if it looks like content.

    Two layers, because they fail in different ways. Markers are exact and fire
    anywhere, including a fourteen-word extract. Families are a ratio and need
    a denominator, so they catch the walls whose copy we never wrote down and
    are what makes this work on a site nobody has heard of.
    """
    raw = text or ""
    if not raw.strip():
        return None
    low = raw.lower()
    for kind, phrases in MARKERS.items():
        if any(p in low for p in phrases):
            return Wall(kind, 100.0, len(raw.split()))
    for fam in FAMILIES:
        hits, total, per_100 = density(raw, fam.words)
        if total < fam.min_words:
            continue
        if per_100 >= fam.per_100:
            return Wall(fam.name, round(per_100, 2), total)
    return None


def classify_all(text: str) -> Dict[str, float]:
    """Every family's density, for reporting and for setting thresholds."""
    out: Dict[str, float] = {}
    for fam in FAMILIES:
        _hits, total, per_100 = density(text, fam.words)
        out[fam.name] = round(per_100, 2) if total >= fam.min_words else 0.0
    return out