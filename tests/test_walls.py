"""Tests for the wall classifier.

These are the direct tests the PR body deferred. The corpus numbers in
``walls.py`` came from live pages; these are the ones that keep the rules
from drifting silently, and they are hermetic on purpose. A classifier that
only ever gets exercised against the network stops being tested the moment
the sites it was measured on change.
"""

import pytest

from searchts import walls

#: Real extracts, taken from the dogfood corpus. Each is a wall that renders
#: server-side text, which is the class the classifier exists to catch.
REAL_WALLS = [
    (
        "auth",
        "Log into Instagram\nPhone number, username, or email\nPassword\n"
        "Forgot password? Log in\nDon't have an account? Sign up\n"
        "See Instagram photos and videos from your friends and follow the "
        "accounts you love. Sign up to follow the people you already like.",
    ),
    (
        "auth",
        "Sign in\nNew to LinkedIn?\nJoin now\nBy continuing, you agree to "
        "LinkedIn's User Agreement, Privacy Policy and Cookie Policy.\n",
    ),
    (
        "auth",
        "Welcome back\nLog in to your account\nEmail address\nPassword\n"
        "Forgot your password?\nNew to this service? Create an account\n"
        "Remember me on this device. By continuing you accept the terms.",
    ),
    (
        "consent",
        "We use cookies to make our site work. Cookies help us deliver our "
        "services, analyse site traffic and improve your experience. Accept "
        "all cookies to consent to non-essential cookies, or manage your "
        "preferences. Reject all optional cookies. Your privacy, your choice.",
    ),
    (
        "botcheck",
        "Google Search\nSorry, our systems have detected unusual traffic from "
        "your computer network. This page checks to see if it's really you "
        "sending the requests, and not a robot. Please try again. To continue, "
        "solve the captcha below. If you are having trouble, please send us "
        "feedback about what you're seeing.",
    ),
]


@pytest.mark.parametrize("kind,text", REAL_WALLS)
def test_real_walls_are_classified(kind, text):
    found = walls.classify(text)
    assert found is not None, f"{kind} extract read as content"
    assert found.kind == kind


def test_markers_fire_below_the_density_floor():
    """A short auth shell has no denominator, so markers must carry it.

    This is the case the first version of the classifier got wrong, and the
    existing LinkedIn tests caught it. It is worth pinning on its own.
    """
    short = "Sign in to continue"
    found = walls.classify(short)
    assert found is not None
    assert found.kind == "auth"
    assert found.words == 4  # far below the 60-word floor


def test_content_is_not_a_wall():
    """Article prose mentioning the words must not trip the ratio."""
    good = (
        "Web scraping is the automated extraction of data from websites. "
        "Many sites require users to sign in before they will show content, "
        "and a scraper must respect that boundary. Cookie policies matter "
        "too: a crawler that ignores them is not scraping, it is trespassing, "
        "and the difference is the whole subject of this article. "
    ) * 4
    assert walls.classify(good) is None


def test_empty_and_blank_are_content():
    assert walls.classify("") is None
    assert walls.classify("   \n\t ") is None


def test_density_floor_suppresses_a_short_mention():
    """One cookie word in a short string is not a consent wall."""
    assert walls.classify("We use cookies here") is None


def test_classify_all_reports_every_family():
    """Every family is scored, including ones the extract is too short for.

    ``classify_all`` reports 0.0 below ``min_words`` because it has no ratio to
    report, but it still answers for every family so a caller can see the whole
    picture rather than guessing which ones were skipped.
    """
    scores = walls.classify_all(REAL_WALLS[0][1])
    assert set(scores) == set(walls.WALL_NAMES)
    assert scores["botcheck"] == 0.0  # the Instagram shell has no captcha in it


def test_short_shell_is_caught_by_breadth_not_volume():
    """A 31-word auth shell is a wall; a menu link repeating one word is not.

    This is the case between the marker layer and the density floor. Both
    families abstain here on their own: no marker phrase is present, and 31
    words is far too few for a ratio. Breadth of distinct wording is what
    catches it.
    """
    shell = REAL_WALLS[2][1]
    assert len(shell.split()) < 60  # below the auth density floor
    assert walls.classify(shell) is not None

    # Breadth is what caught the shell, so a menu that names one auth thing
    # among many nav words does not qualify: "sign in" appears once, and once
    # is not breadth.
    menu = "Home\nPricing\nDocs\nBlog\nCareers\nSign in\nAbout\nStatus\n"
    assert walls.distinct_term_count(menu, walls.FAMILIES[0].words) == 1
    assert walls.classify(menu) is None

    # Repeating "sign in" forty times *is* a wall, by the density rule, and
    # correctly so: a page that is nothing but "sign in" is a login page.
    assert walls.classify("Sign in\n" * 40) is not None
