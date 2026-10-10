# -*- coding: utf-8 -*-
"""A read that ended on /login is a login wall, whatever its text scores.

Measured live, not theorised. ``searchts read https://www.reddit.com/settings/account/``
with no cookies answered HTTP 200 and was reported as a successful 703-character
read whose content was Reddit's login page: "By continuing, you agree to our User
Agreement ... Continue with Phone Number ... New to Reddit? Sign Up". The same
run with cookies sent returned the same shape, so an agent holding a live session
was told the session worked.

The cause is in `walls.py`, and it is a shape rather than a threshold: a login
shell is 36 words, below the 60-word floor where a density ratio has a
denominator, so it is judged by breadth instead -- and it names two distinct
things ("continue with", "sign up") where the breadth bar is three. GitHub's
login page is long enough to be caught by density; Reddit's is not. One missed by
one term is still missed.

The redirect target is the fact that settles it, and it needs no vocabulary: a
page whose own URL is ``/login`` is a login page on every site, in every
language, whether or not anyone has written its copy down.
"""

import pytest

from searchts import unlocker
from searchts.unlocker import is_login_url, looks_blocked

# The exact extract searchts returned for Reddit's login page, captured from a
# live `searchts read` run. Kept verbatim (modulo the URLs) because the bug is a
# property of THIS text, not of a shape it resembles.
REDDIT_LOGIN_EXTRACT = """
By continuing, you agree to our
[User Agreement](https://www.redditinc.com/policies/user-agreement)
and acknowledge that you understand the
[Privacy Policy](https://www.redditinc.com/policies/privacy-policy).

Continue with Phone Number

Continue with Google

New to Reddit?

Sign Up
"""

REDDIT_LOGIN_URL = (
    "https://www.reddit.com/login/?dest=https%3A%2F%2Fwww.reddit.com%2Fsettings%2Faccount%2F"
)


class TestIsLoginUrl:
    @pytest.mark.parametrize("url", [
        "https://www.reddit.com/login/?dest=x",
        "https://www.reddit.com/login/",
        "https://github.com/login?return_to=%2Fsettings",
        "https://www.linkedin.com/login/",
        "https://www.instagram.com/accounts/login/",
        "https://example.com/signin",
        "https://example.com/SIGN-IN",
        "https://example.com/login.php",
    ])
    def test_fires_on_a_login_endpoint(self, url):
        assert is_login_url(url) is True

    @pytest.mark.parametrize("url", [
        "https://example.com/",
        "https://example.com/blog/login-tips",
        "https://example.com/blog/signin-guide",
        "https://example.com/news/login.html.amp",
        # A prefix/suffix match would be a false positive on a real article.
        "https://example.com/author",
        "https://example.com/oauth/callback",
        "https://example.com/sessions/2024/summary",
        "",
        None,
    ])
    def test_does_not_fire_on_content(self, url):
        assert is_login_url(url) is False

    def test_a_malformed_url_is_not_a_login_url(self):
        # urlparse raises ValueError on some shapes; a wall check must not be
        # the thing that turns a bad URL into a traceback.
        assert is_login_url("http://[::1") is False


class TestLooksBlockedWithFinalUrl:
    def test_reddit_login_extract_is_caught_only_by_the_url(self):
        """The bug, pinned: without final_url this is a silent pass."""
        without_url = looks_blocked(200, REDDIT_LOGIN_EXTRACT, login_wall=True)
        assert without_url is None, (
            "if the text alone now catches it, the fixture is stale and this "
            "test no longer describes the live bug"
        )
        assert looks_blocked(
            200, REDDIT_LOGIN_EXTRACT, login_wall=True, final_url=REDDIT_LOGIN_URL
        ) == "login-wall"

    def test_the_same_extract_at_a_real_url_still_reads(self):
        """The fix is the redirect, not a new phrase list."""
        assert looks_blocked(
            200, REDDIT_LOGIN_EXTRACT, login_wall=True,
            final_url="https://www.reddit.com/r/python/",
        ) is None

    def test_final_url_is_ignored_without_login_wall(self):
        """Raw HTML carries sign-in modals, so only the extract is judged."""
        assert looks_blocked(
            200, "<html><body>Sign in</body></html>", final_url=REDDIT_LOGIN_URL
        ) is None

    def test_a_login_url_does_not_override_a_hard_error(self):
        assert looks_blocked(403, "nope", final_url=REDDIT_LOGIN_URL) == "http-403"


class TestFetchReportsTheLoginWall:
    """The whole run, so the fix is measured where a user sees it."""

    def test_a_login_redirect_fails_loudly_instead_of_passing(self, monkeypatch):
        def _login_page(url, **kwargs):
            return 200, REDDIT_LOGIN_EXTRACT, REDDIT_LOGIN_URL, {}

        monkeypatch.setattr(unlocker, "_fetch_curl_cffi", _login_page)
        monkeypatch.setattr(unlocker, "_fetch_jina", lambda url, timeout=40: _login_page(url))
        with pytest.raises(unlocker.UnlockerError) as exc:
            unlocker.fetch(
                "https://www.reddit.com/settings/account/", progress=False
            )
        assert any("login-wall" in why for _, why in exc.value.attempts), (
            f"the ladder returned a login page as content: {exc.value.attempts}"
        )