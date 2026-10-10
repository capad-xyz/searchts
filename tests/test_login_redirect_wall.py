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
from searchts.unlocker import _LOGIN_SEGMENTS, is_login_url, looks_blocked

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

    @pytest.mark.parametrize("url", [
        # Hare's finding on the first cut of this rule. `auth` and `session`
        # were in the segment set, and both are ordinary nouns on the rest of
        # the web: every URL below is a real page that this rule refused as a
        # login wall. A wrong answer, not a safe one -- the whole point of the
        # check is that /login means login, not that a suspicious word appeared.
        "https://example.com/docs/auth",
        "https://example.com/blog/auth/2024",
        "https://example.com/session/2024/notes",
        "https://example.com/podcast/session/12",
        "https://example.com/lecture/authentication-tokens",
        "https://example.com/papers/auth-2024.pdf",
    ])
    def test_ordinary_nouns_are_never_a_login_wall(self, url):
        assert is_login_url(url) is False, (
            "a documentation or content URL must not be refused as a login page"
        )

    def test_every_segment_in_the_set_names_the_act_of_authenticating(self):
        """The rule that keeps the set honest as it grows.

        A word joins this set only if no other page on the web would use it as a
        path segment of its own. That is why bare `auth` and `session` are out
        even though some sites really do put their login at `/auth`.

        The ordinary-noun list is spelled out rather than left to taste: a
        hand-picked pair would let `log` or `key` through, which is exactly the
        kind of word that reads as authentication and is a perfectly ordinary
        URL segment.
        """
        ordinary = {
            # the pair this rule actually turned on
            "auth", "session", "sessions", "authenticate", "authorization",
            # other words that read like authentication and are not
            "log", "key", "keys", "token", "tokens", "grant", "grants",
            "access", "permission", "permissions", "identity", "credential",
            "credentials", "certificate", "cert", "certs",
            # ordinary nouns a documentation or blog URL would use
            "user", "users", "account", "profile", "settings", "oauth",
            "member", "members", "group", "groups", "role", "roles",
            "signup", "register", "join", "guest", "admin", "dashboard",
        }
        assert not (_LOGIN_SEGMENTS & ordinary), (
            f"{sorted(_LOGIN_SEGMENTS & ordinary)} would refuse a content URL "
            f"as a login wall"
        )

    def test_the_accepted_miss_is_stated_where_a_reader_looks(self):
        """Hare on the second cut: the miss was load-bearing but undocumented.

        Dropping `auth`/`session` means a site whose login lives at a bare
        `/auth` is no longer caught. That is a real miss and it belongs next to
        the set, not only in the commit message.
        """
        import inspect

        source = inspect.getsource(unlocker)
        block = source.split("_LOGIN_SEGMENTS = ")[0][-2000:]
        assert "ACCEPTED MISS" in block, (
            "the trade-off must be written down where someone editing the set "
            "will actually see it"
        )

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
