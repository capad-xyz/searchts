# -*- coding: utf-8 -*-
"""The cookie fence: session cookies reach the target host and nothing else.

`unlocker.fetch` can now be handed a jar of session cookies so a read looks
logged in. That is a real login to a real account, and the unlocker ladder has
a rung that is not the target host:

    curl_cffi       -> the target host itself            (direct)
    Jina Reader     -> POSTs the URL to r.jina.ai        (THIRD PARTY)
    stealth-browser -> a local browser, on the host      (direct)

The second rung sends the target URL to somebody else's server. If a Cookie
header rode along, r.jina.ai would receive a live login for the user's account
and could keep it. So the rule these tests hold is not "we filter carefully
before sending". It is that the relay rung has no parameter through which cookie
material could travel at all.

Everything here is hermetic. The backends are monkeypatched, so no request
leaves the machine and the assertions are about calls, not about the network.
"""

import inspect

import pytest

from searchts import unlocker
from searchts.session_cookies import CookieRecord, build_header, filter_for_host

#: A cookie value loud enough to be findable. If this string turns up in a relay
#: call, that is the leak, and the assertions are written to fail loudly on it.
SECRET = "s3cr3t-live-login-token"
COOKIE_NAME = "sessionid"

#: The cookie the caller owns for the site being read.
LOGIN = CookieRecord(name=COOKIE_NAME, value=SECRET, domain="site.test")

#: A cookie for a different site, sitting in the same jar.
OTHER_SITE = CookieRecord(name="bank_token", value="not-your-bank", domain="bank.test")

#: Long enough to clear ``_MIN_CHARS`` so a rung can actually win.
PAGE = "Ordinary page prose about invoices and receipts. " * 12

#: Short enough to stay thin, so a rung declines and the ladder escalates.
THIN = "word " * 20


# ── call capture ────────────────────────────────────────────────────────────


class Call:
    """One recorded backend call: what it was handed, and what it returned.

    Recording is deliberately separate from asserting. ``fetch`` wraps every
    ladder rung in ``except Exception``, so a stub that raised AssertionError
    would be swallowed and logged as an ordinary backend failure -- which is why
    tests/conftest.py keeps its tripwires on BaseException. These stubs never
    raise; they hand back the evidence and let the test body judge it.
    """

    def __init__(self):
        self.args = ()
        self.kwargs = {}
        self.result = None
        self.calls = 0

    def record(self, args, kwargs, result):
        self.calls += 1
        self.args = args
        self.kwargs = kwargs
        self.result = result
        return result

    def haystack(self):
        """Every string reachable from this call, flattened into one blob.

        Walks args, kwargs and the return value, and repr()s anything that is
        not a plain string, so a cookie hidden in a tuple or a nested dict is
        still found. A fence that inspects one known keyword is a fence a later
        refactor walks straight through.
        """
        found = []
        stack = [self.args, self.kwargs, self.result]
        while stack:
            item = stack.pop()
            if isinstance(item, str):
                found.append(item)
            elif isinstance(item, dict):
                stack.extend(item.keys())
                stack.extend(item.values())
            elif isinstance(item, (list, tuple, set, frozenset)):
                stack.extend(item)
            elif item is not None and not isinstance(item, (int, float, bool)):
                found.append(repr(item))
        return "\n".join(found)

    def request_headers(self):
        """Whatever this call offered as outbound request headers, or {}."""
        for key in ("extra_headers", "headers", "cookies", "cookies_dict"):
            value = self.kwargs.get(key)
            if isinstance(value, dict):
                return value
        return {}

    def cookie_header(self):
        """The Cookie header this call was handed, or None."""
        for name, value in self.request_headers().items():
            if str(name).strip().lower() == "cookie":
                return value
        return None


class Ladder:
    """The whole ladder, recorded, with each rung's reply under the test's hand.

    ``ladder.state["curl"] = (403, "blocked")`` before ``ladder.walk(...)`` sets
    what a rung returns. Mutating it after ``walk`` does nothing, so a test that
    means to prove a rung was reached has to say so with ``call.calls``.
    """

    def __init__(self, state, calls):
        self.state = state
        self.calls = calls

    def call(self, rung):
        return self.calls[rung]

    def walk(self, url, **kwargs):
        """Walk the ladder with the recorded stubs, ignoring a total failure.

        Several of these tests deliberately fail every rung; what they assert is
        what each rung was handed on the way past, not the outcome.
        """
        kwargs.setdefault("use_memory", False)
        try:
            return unlocker.fetch(url, **kwargs)
        except unlocker.UnlockerError:
            return None

    def must_reach(self, *rungs):
        """Assert these rungs actually ran, so the rest of the test means something."""
        for rung in rungs:
            assert self.call(rung).calls == 1, (
                f"the {rung} rung never ran, so nothing was proven"
            )


@pytest.fixture
def ladder(monkeypatch):
    """Every rung recorded, the ladder neutral, and no request sent anywhere.

    ``html_to_text`` and ``whole_short_page`` are stubbed so the length of a
    rung's reply decides thin-versus-win outright, with no extraction in the
    way, and Jina is forced on so the relay rung is reachable whatever the
    machine's config or env says.
    """
    monkeypatch.setattr(unlocker, "html_to_text", lambda body, url=None: body)
    monkeypatch.setattr(unlocker, "whole_short_page", lambda body, text: False)
    monkeypatch.setattr(unlocker, "jina_enabled", lambda: True)

    state = {"curl": (200, THIN), "jina": (200, THIN), "stealth": (200, THIN)}
    calls = {name: Call() for name in ("curl", "jina", "stealth", "human")}

    def _reply(rung, url):
        status, body = state[rung]
        return status, body, url, {}

    # Each stub records the arguments it ACTUALLY received, not a hand-written
    # guess at them. The first version of this file took *args/**kwargs and then
    # recorded a literal ``(url,), {}``, which meant a leak smuggled in as a
    # second positional argument was silently dropped by the recorder: the
    # mutation passed green. The stub has to see what really arrived.

    def _curl(*args, **kwargs):
        return calls["curl"].record(args, kwargs, _reply("curl", args[0]))

    def _jina(*args, **kwargs):
        return calls["jina"].record(args, kwargs, _reply("jina", args[0]))

    def _stealth(*args, **kwargs):
        return calls["stealth"].record(args, kwargs, _reply("stealth", args[0]))

    def _human(*args, **kwargs):
        # Recorded rather than raising: nothing here passes allow_human, and a
        # recorded zero is an assertion these tests can make instead of a guess.
        calls["human"].record(args, kwargs, None)
        return None, "", args[0] if args else ""

    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", _curl)
    monkeypatch.setattr(unlocker, "_fetch_jina", _jina)
    monkeypatch.setattr(unlocker, "_fetch_stealth", _stealth)
    monkeypatch.setattr(unlocker, "_fetch_human", _human)

    return Ladder(state, calls)


# ── F1: the fence itself ────────────────────────────────────────────────────


def test_f1_jina_relay_never_receives_cookie_material(ladder):
    """F1. Cookies go to the target host; the relay gets none of them.

    The failure this exists to prevent: a login for site.test leaves the
    machine inside a POST to r.jina.ai, a third party, holding a live session
    for the user's account.

    Both rungs are reached -- curl is made to refuse so the ladder escalates
    rather than winning on the first rung -- because a fence that is never
    exercised is not a fence.
    """
    ladder.state["curl"] = (403, "blocked")
    ladder.state["jina"] = (200, PAGE)

    ladder.walk("https://site.test/account", cookies=[LOGIN])

    ladder.must_reach("curl", "jina")

    # (a) curl_cffi, the direct-host rung, DID get the login.
    curl = ladder.call("curl")
    assert curl.cookie_header() == f"{COOKIE_NAME}={SECRET}", (
        f"the host rung did not get its own cookie; it got {curl.request_headers()!r}"
    )

    # (b) jina, the third-party relay, got NOTHING at all.
    jina = ladder.call("jina")
    assert jina.cookie_header() is None, "the relay was handed a Cookie header"
    assert jina.request_headers() == {}, (
        f"the relay was handed request headers at all: {jina.request_headers()!r}"
    )
    assert "cookie" not in jina.haystack().lower(), (
        "anything cookie-shaped reached the relay call:\n" + jina.haystack()
    )
    assert SECRET not in jina.haystack(), "a cookie VALUE reached the relay call"
    assert COOKIE_NAME not in jina.haystack(), "a cookie NAME reached the relay call"


def test_relay_fetcher_signature_admits_no_cookie_parameter():
    """The structural half of F1, which no call-site edit can undo.

    The test above is about what today's ladder does. This one is about what
    the relay function is able to do: ``_fetch_jina(url, timeout)`` has no
    headers parameter, no cookies parameter and no ``**kwargs`` to smuggle one
    through. Adding any of those would be the bug, not the feature.
    """
    params = inspect.signature(unlocker._fetch_jina).parameters

    assert set(params) == {"url", "timeout"}, (
        f"_fetch_jina gained a parameter: {sorted(params)}"
    )
    assert not any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
    ), "_fetch_jina gained **kwargs, which would swallow a cookie header"


# ── default is off ──────────────────────────────────────────────────────────


def test_no_cookies_passed_sends_no_cookie_header(ladder):
    """Default off: no cookies, no Cookie header, not even an empty one."""
    ladder.walk("https://site.test/page")

    ladder.must_reach("curl")
    assert ladder.call("curl").cookie_header() is None
    assert ladder.call("curl").request_headers() == {}, (
        "a cookie-free read grew request headers: "
        f"{ladder.call('curl').request_headers()!r}"
    )


def test_no_cookies_passed_matches_the_old_call_shape(ladder):
    """Without cookies the rung is called exactly as it was before this change.

    The keyword is only added when there is something to send, so the many
    existing stubs with the signature ``(url, timeout=30)`` keep working and a
    cookie-free read is byte-identical on the wire.
    """
    ladder.walk("https://site.test/page")

    curl = ladder.call("curl")
    assert curl.args == ("https://site.test/page",), f"positional args changed: {curl.args!r}"
    assert curl.kwargs == {}, f"a cookie-free read started passing kwargs: {curl.kwargs!r}"


# ── host scoping ────────────────────────────────────────────────────────────


def test_host_scoping_rejects_notamazon_in_when_host_is_amazon_in():
    """.amazon.in is not notamazon.in.

    This is the whole reason ``filter_for_host`` exists. A loose ``endswith`` on
    the cookie's domain would attach an Amazon login to notamazon.in, a site
    somebody else owns. A cookie's domain has to match the host as a DNS
    suffix, not as a string suffix.
    """
    cookie = CookieRecord(name="session-id", value=SECRET, domain="notamazon.in")

    assert filter_for_host([cookie], "notamazon.in") == [cookie], (
        "a cookie for notamazon.in should be sent to notamazon.in itself"
    )
    assert filter_for_host([cookie], "amazon.in") == [], (
        "notamazon.in's cookie was offered to amazon.in"
    )
    assert filter_for_host([cookie], "www.amazon.in") == [], (
        "notamazon.in's cookie was offered to www.amazon.in"
    )
    assert filter_for_host([cookie], "amazon.in.evil.test") == [], (
        "notamazon.in's cookie was offered to a host that merely ends in it"
    )


def test_host_scoping_sends_the_cookie_to_the_family_it_belongs_to():
    """The positive half of that rule, so the test above cannot pass merely
    because ``filter_for_host`` rejects everything."""
    cookie = CookieRecord(name="session-id", value=SECRET, domain=".amazon.in")

    assert filter_for_host([cookie], "amazon.in") == [cookie]
    assert filter_for_host([cookie], "www.amazon.in") == [cookie]
    assert filter_for_host([cookie], "smile.amazon.in") == [cookie]
    assert filter_for_host([cookie], "notamazon.in") == []


def test_a_jar_holding_another_site_s_cookie_contributes_nothing(ladder):
    """The jar is filtered before the header is built, not after it is sent.

    Both cookies go in one list, the way a real browser jar would be handed
    over. Only the one for this host may reach the wire.
    """
    ladder.state["curl"] = (200, PAGE)

    ladder.walk("https://site.test/account", cookies=[LOGIN, OTHER_SITE])

    ladder.must_reach("curl")
    sent = ladder.call("curl").cookie_header() or ""
    assert f"{COOKIE_NAME}={SECRET}" in sent, "the site's own cookie went missing"
    assert "bank_token" not in sent, "another site's cookie was attached"
    assert OTHER_SITE.value not in ladder.call("curl").haystack()


def test_a_jar_with_nothing_for_this_host_reads_anonymously(ladder):
    """Wrong-site cookies are not an error. They just mean an anonymous read."""
    ladder.state["curl"] = (200, PAGE)

    ladder.walk("https://site.test/account", cookies=[OTHER_SITE])

    ladder.must_reach("curl")
    assert ladder.call("curl").cookie_header() is None


# ── the browser rung is fenced too ──────────────────────────────────────────


def test_stealth_browser_never_receives_cookie_material(ladder):
    """Every rung is reached, and only the host rung has the login.

    curl and the relay are both left thin, so the walk reaches the browser rung
    without tripping the repeated-4xx fail-fast that would skip it. This
    change does not wire cookies into the browser; that is asserted, not
    assumed.
    """
    ladder.walk("https://site.test/account", cookies=[LOGIN])

    ladder.must_reach("curl", "jina", "stealth")
    assert ladder.call("curl").cookie_header() == f"{COOKIE_NAME}={SECRET}"
    assert ladder.call("stealth").cookie_header() is None
    assert SECRET not in ladder.call("stealth").haystack()


# ── it never leaks into anything a human reads ──────────────────────────────


def test_the_cookie_value_never_lands_on_the_result_or_in_an_error(ladder):
    """Not in a FetchResult, not in an UnlockerError. A login is not a diagnostic.

    Every rung stays thin here, so the walk ends in ``UnlockerError``, whose
    message lists every rung and its reason. Both that and the result object
    get printed, pasted into issues and handed to agents.
    """
    try:
        result = unlocker.fetch(
            "https://site.test/account", use_memory=False, cookies=[LOGIN]
        )
    except unlocker.UnlockerError as exc:
        rendered = str(exc) + repr(exc.attempts)
    else:
        rendered = "\n".join([
            result.text,
            repr(result.headers),
            repr(result.warnings),
            repr(result.more),
        ])

    ladder.must_reach("curl", "jina", "stealth")
    assert SECRET not in rendered, "the cookie value reached something a human reads"
    assert COOKIE_NAME not in rendered


def test_a_successful_read_returns_content_with_no_trace_of_the_cookie(ladder):
    """The happy path returns the page, not an echo of the jar."""
    ladder.state["curl"] = (200, PAGE)

    result = ladder.walk("https://site.test/account", cookies=[LOGIN])

    assert result is not None and result.backend == "curl_cffi"
    assert result.text == PAGE
    assert SECRET not in repr(result.__dict__)


def test_build_header_is_the_only_thing_that_renders_a_value(ladder):
    """Pin the seam: the header comes from one helper, and stays a local.

    Not a claim about every line of the package, just about this path. The
    value exists as a string in exactly one local, and ``fetch`` puts it on the
    wire in exactly one place.
    """
    assert build_header(filter_for_host([LOGIN], "site.test")) == f"{COOKIE_NAME}={SECRET}"

    ladder.state["curl"] = (200, PAGE)
    ladder.walk("https://site.test/account", cookies=[LOGIN])

    assert ladder.call("curl").cookie_header() == build_header([LOGIN])


# ── the host comes from the normalized URL, not the caller's string ──────────


@pytest.mark.parametrize("url", [
    "https://SITE.test/account",        # normalized case must still match
    "site.test/account",                # bare host, no scheme
    "https://site.test/account?utm=x",  # the query string must not reach the host
])
def test_the_host_is_derived_from_the_normalized_url(ladder, url):
    """Whatever shape the caller passed, the scoping host is site.test.

    A jar scoped to ``site.test`` has to survive a bare host and a shouting
    one. Had the host been parsed from the raw string instead of the normalized
    URL, ``SITE.test`` would silently have read anonymously.
    """
    ladder.state["curl"] = (200, PAGE)

    ladder.walk(url, cookies=[LOGIN])

    assert ladder.call("curl").cookie_header() == f"{COOKIE_NAME}={SECRET}", (
        f"lost the cookie for {url!r}"
    )