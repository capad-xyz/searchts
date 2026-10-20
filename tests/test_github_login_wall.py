# -*- coding: utf-8 -*-
"""A GitHub login wall, and a public repo page that was mistaken for one.

The bug this file pins, measured 2026-10-18 from this box:

    $ searchts read https://github.com/psf/requests
    Failed to read https://github.com/psf/requests
      curl_cffi: login-wall
      Jina Reader: login-wall
      github.com is behind a login. Two ways past it, your call:
        searchts login signin https://github.com/psf/requests
        searchts read https://github.com/psf/requests --cookies-from-browser firefox

``psf/requests`` is public. Its README is in the served HTML. What the read
extracted was GitHub's navigation chrome plus the README, and the chrome carries
two labels that say "You must be signed in": the star button's tooltip and the
notification button's ``aria-label``. Those are 845 words of page with two auth
sentences in them, which is not a login page.

The cause was in :mod:`searchts.walls`, not in a host table. The marker layer
fired at any length because it exists for the extract with no denominator (a
four-word "sign in to continue" is a wall and no ratio can say so). Above the
family's own word floor there *is* a denominator, and the marker never asked it.

Two pages, the same shape, opposite answers, and the fix has to keep both:

* the wall is caught by its density, 6.58 auth hits per 100 words against a
  threshold of 2.0;
* the public page is not, 0.59 against the same 2.0.

So a marker now only carries a page it cannot outvote. Everything here is
hermetic: the rungs are stubbed, so nothing leaves the machine, and the fixtures
are saved pages.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from searchts import more, unlocker, walls
from searchts.session_cookies import CookieRecord

FIX = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

REPO_URL = "https://github.com/psf/requests"
LOGIN_URL = "https://github.com/login"

#: The auth threshold the families ship with, so these tests break when it moves
#: rather than when the numbers drift past it quietly.
AUTH_PER_100 = next(f.per_100 for f in walls.FAMILIES if f.name == "auth")
CONSENT_PER_100 = next(f.per_100 for f in walls.FAMILIES if f.name == "consent")


def fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def live_extract() -> str:
    """The extract the live read produced on 2026-10-18, saved verbatim."""
    return fixture("github_public_repo_extract.md")


@pytest.fixture(scope="module")
def live_login() -> str:
    return fixture("github_login_wall.html")


@pytest.fixture(scope="module")
def live_page() -> str:
    return fixture("github_public_repo.html")


# ── the false wall ──────────────────────────────────────────────────────────


def test_the_public_repo_page_is_not_a_wall(live_extract):
    """The page whose README is public must not be refused.

    This is the whole regression in one assertion: the exact text the live read
    produced is handed to the same classifier the ladder asks, and the answer is
    content.
    """
    assert walls.classify(live_extract) is None


def test_the_ladder_no_longer_calls_it_a_login_wall(live_extract):
    """What ``fetch`` asks, on the same text.

    ``fetch`` decides a wall with one call (``looks_blocked(200, text,
    login_wall=True)``), so this is the decision the run actually makes rather
    than a classifier reached in isolation.
    """
    assert unlocker.looks_blocked(200, live_extract, login_wall=True) is None


def test_the_marker_was_the_whole_cause(live_extract):
    """Pin why, so the test above cannot go green by accident.

    The old rule fired on the marker alone. The marker is still in the text, so
    if this ever stops holding, the extract is no longer the one that broke.
    """
    low = walls.scrub(live_extract).lower()
    assert "you must be signed in" in low
    assert walls.classify_all(live_extract)["auth"] < AUTH_PER_100


def test_the_page_markup_is_the_readme_plus_two_labels(live_page):
    """What the live page is: a real README, and two buttons that need a login.

    Both strings live in attributes on buttons in the repo header, which is why
    they reach an extract at all, and the README they sit next to is the page's
    own ``<article>``. Asserted on the markup rather than on the extract because
    this is a fact about the page, and it does not depend on what the extractor
    chose to keep.
    """
    doc = more._parse(live_page)
    readme = doc.xpath("//article[contains(@class,'markdown-body')]")
    assert readme, "the page slice lost the README element"
    assert "simple, yet elegant" in readme[0].text_content().lower()

    labels = [
        el.get("aria-label") or ""
        for el in doc.xpath("//*[@aria-label]")
    ]
    labels += [el.text_content() for el in doc.xpath("//*[@role='tooltip']")]
    said = [t for t in labels if "must be signed in" in t]
    assert said, "the page slice lost the star and notification labels"
    # Two of them, and both on controls rather than on prose.
    assert all(len(t.split()) >= 4 for t in said), said


def test_the_page_slice_extracts_to_content(live_page):
    """The slice is not refused either, on its own bytes."""
    text = unlocker.html_to_text(live_page, REPO_URL)
    assert walls.classify(text) is None
    assert "Requests allows you to send HTTP" in text


# ── the real wall, still a wall ─────────────────────────────────────────────


def test_the_login_page_is_still_an_auth_wall(live_login):
    """The cost of the fix, stated as a test: the true wall still reads.

    Same classifier, same extract path, real saved page. It is caught by the
    family, at 6.58 auth hits per 100 words against a threshold of 2.0, which is
    what is supposed to carry it.
    """
    text = unlocker.html_to_text(live_login, LOGIN_URL)
    found = walls.classify(text)
    assert found is not None and found.kind == "auth"
    assert walls.classify_all(text)["auth"] > AUTH_PER_100


def test_the_ladder_calls_the_login_page_a_login_wall(live_login):
    text = unlocker.html_to_text(live_login, LOGIN_URL)
    assert unlocker.looks_blocked(200, text, login_wall=True) == "login-wall"


def test_a_redirect_onto_the_login_path_is_still_the_wall(live_login, monkeypatch):
    """The other fact that names a wall needs no vocabulary at all."""
    text = unlocker.html_to_text(live_login, LOGIN_URL)
    assert unlocker.looks_blocked(
        200, "a page that says nothing about signing in",
        login_wall=True,
        final_url="https://github.com/login?return_to=%2Fpsf%2Frequests",
    ) == "login-wall"
    assert walls.classify(text) is not None  # the fixture is still a wall itself


# ── the rule, on its own, with no host in it ─────────────────────────────────


def test_a_marker_still_carries_an_extract_with_no_denominator():
    """Four words cannot be a ratio against anything. The marker is the answer."""
    found = walls.classify("Please sign in to continue")
    assert found is not None and found.kind == "auth"


def test_a_shell_at_the_word_floor_is_still_a_wall():
    """Just above the floor the family abstains, so breadth carries the shell."""
    shell = (
        "Welcome back\nLog in to your account\nEmail address\nPassword\n"
        "Forgot your password?\nNew to this service? Create an account\n"
        "Remember me on this device. By continuing you accept the terms.\n"
    )
    assert len(shell.split()) >= walls.SHORT_SHELL_MIN_TERMS
    assert walls.classify(shell) is not None


def test_a_long_page_that_is_about_signing_in_is_still_a_wall():
    """The rule is not "a long page is never a wall".

    A long auth page repeats the family's own wording, so the family reaches its
    threshold on its own and the marker is not what decides it. That is the half
    of the measurement that keeps the fix honest: the login page is 3.3x over
    and the public repo page is 3.4x under, and both are far from the line.
    """
    long_shell = (
        "Sign in to continue. Username. Password. Remember me. "
        "Forgot your password? New here? Create an account. "
    ) * 40
    found = walls.classify(long_shell)
    assert found is not None and found.kind == "auth"
    assert walls.classify_all(long_shell)["auth"] >= AUTH_PER_100


def test_a_long_page_whose_nav_says_sign_in_is_content():
    """The same rule with no host, and no login page anywhere in it.

    One sentence in the chrome of a long page is what GitHub's star button puts
    there, and it is not the page's subject. The old rule could not tell this
    from a login wall; the density can, and now the marker asks it.
    """
    nav = ("Navigation Menu Platform Marketplace Explore Docs Blog Careers "
           "Pricing Status Enterprise About ")
    page = nav * 24 + "You must be signed in to star a repository\n" + nav * 12
    assert len(page.split()) > 200
    assert "you must be signed in" in walls.scrub(page).lower()
    assert walls.classify(page) is None


def test_the_same_phrase_repeated_is_not_chrome():
    """The other side of the line, so the rule above is not read as a blanket.

    A page whose own text says the sentence forty times *is* about signing in.
    Density catches it whether or not the marker does.
    """
    shell = ("Sign in to continue. Username. Password. Remember me. "
             "Forgot your password? New here? Create an account. ") * 40
    assert walls.classify(shell) is not None


def test_the_marker_asks_its_own_family_and_no_other():
    """One rule for every family, not a rule that happens to fit auth."""
    prose = (
        "The council met on Tuesday to review the measurements the engineers "
        "had taken in the second week, and nobody expected the spread to be "
        "this wide. " * 20
    )
    assert walls.classify(prose + "We use cookies to improve your experience.") is None
    assert walls.classify("We use cookies to improve your experience.") is not None


def test_a_script_decoy_is_still_not_a_wall():
    """Unchanged by this change, and worth keeping beside it."""
    decoy = (
        '<html><script>var m={"cookie_description":'
        '"We use cookies to improve your experience and for marketing"};</script>'
        "<article>" + "Real prose about payments and invoices. " * 40 + "</article>"
        "</html>"
    )
    assert walls.classify(decoy) is None


# ── the read path, driven: fail loud on the wall, and the way past it ────────


@pytest.fixture
def gh_login_ladder(monkeypatch):
    """Every rung answers with the saved login page. No request leaves the box."""
    page = fixture("github_login_wall.html")

    def _rung(*args, **kwargs):
        return 200, page, args[0] if args else LOGIN_URL, {}

    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", _rung)
    monkeypatch.setattr(unlocker, "_fetch_jina", _rung)
    monkeypatch.setattr(unlocker, "_fetch_stealth", _rung)
    monkeypatch.setattr(unlocker, "jina_enabled", lambda: True)


def test_every_rung_refuses_the_login_page_by_name(gh_login_ladder):
    """Fail loud: non-zero, and every rung says which wall it hit."""
    with pytest.raises(unlocker.UnlockerError) as raised:
        unlocker.fetch(LOGIN_URL, use_memory=False)
    reasons = dict(raised.value.attempts)
    assert reasons.get("curl_cffi") == "login-wall", raised.value.attempts
    assert reasons.get("Jina Reader") == "login-wall", raised.value.attempts


def test_the_public_repo_page_is_not_refused_by_the_ladder(live_extract, monkeypatch):
    """The same ladder, served the live extract, reads instead of refusing."""
    def _rung(*args, **kwargs):
        return 200, live_extract, args[0] if args else REPO_URL, {}

    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", _rung)
    monkeypatch.setattr(unlocker, "_fetch_stealth", _rung)
    monkeypatch.setattr(unlocker, "jina_enabled", lambda: False)

    result = unlocker.fetch(REPO_URL, use_memory=False)
    assert "Requests allows you to send HTTP" in result.text
    assert result.backend == "curl_cffi"


def test_the_cli_refuses_loud_and_names_the_cookie_way_past(
    gh_login_ladder, capsys, monkeypatch, tmp_home
):
    """The deliverable, through the command a user types.

    Exit non-zero, nothing on stdout, and the reason plus both ways past it on
    stderr: sign in once, or copy cookies from a browser already signed in.
    """
    from searchts import cli

    monkeypatch.setattr("sys.argv", [
        "searchts", "read", LOGIN_URL, "--backend", "curl_cffi",
    ])
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    out = capsys.readouterr()

    assert exit_info.value.code == 1
    assert out.out == "", "a refused read must leave stdout empty"
    assert "login-wall" in out.err
    assert f"searchts login signin {LOGIN_URL}" in out.err
    assert f"searchts read {LOGIN_URL} --cookies-from-browser" in out.err
    # The fence, said out loud: a logged-in browser is not the fix.
    assert "the browser tier is sent none of them" in out.err


def test_a_cookie_read_of_the_same_page_names_the_fence_instead(
    gh_login_ladder, monkeypatch
):
    """The 0.15.0 logged-in read: cookies sent, still a login page.

    One sentence, and it is a different one, because the cause is different: the
    session expired, or the browser tier cannot carry the login at all.
    """
    with pytest.raises(unlocker.UnlockerError) as raised:
        unlocker.fetch(
            LOGIN_URL,
            use_memory=False,
            cookies=[CookieRecord(name="user_session", value="x", domain="github.com")],
        )
    hint = raised.value.hint
    assert "browser tier is sent no cookies at all" in hint
    assert "expired" in hint


def test_no_fixture_carries_a_token(live_page, live_login):
    """Fixtures are committed. Nothing shaped like a credential goes in one.

    The saved login page really did ship a live ``authenticity_token`` and a
    ``data-hydro-click-hmac``, and the public repo page shipped one of the
    latter. All three were stripped before the fixtures were committed, and this
    is the check that says so rather than a comment that says so. Attributes are
    inspected on the parsed document, so the provenance comment naming them is not
    what is being measured.
    """
    secret_attr = re.compile(r"hmac|token|secret|csrf|password|credential", re.I)
    opaque = re.compile(r"^[A-Za-z0-9+/=_-]{32,}$")
    for name, page in (("repo", live_page), ("login", live_login)):
        doc = more._parse(page)
        for el in doc.iter():
            if not isinstance(el.tag, str):
                continue
            for attr, value in el.attrib.items():
                if not secret_attr.search(attr):
                    continue
                # The attribute name is allowed to exist (GitHub ships
                # ``data-csrf="true"``); a credential does not.
                assert not opaque.match(value or ""), (
                    f"{name} fixture has {attr} on <{el.tag}> holding a "
                    f"32-character opaque value"
                )
        for probe in ("user_session=", "client_secret", "private_key", "Bearer ",
                      "Authorization"):
            assert probe not in page, f"{name} fixture carries {probe!r}"
