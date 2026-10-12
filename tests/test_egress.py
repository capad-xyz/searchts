# -*- coding: utf-8 -*-
"""Hermetic tests for the egress proxy module.

Every test here is pure: no network, no proxy is ever contacted, and no real
credential is used. The security-critical assertion in this file is that a
password never survives ``redact`` -- a value chosen to be loud is used so a
leak is unmistakable, and every redact() case asserts that value is absent.

``cookies_may_travel`` is listed in ``searchts.egress.__all__`` and is imported
here by name: the cookie fence is the whole reason this module exists, and a
non-recursive import is hermetic.
"""

from __future__ import annotations

import pytest

from searchts.egress import (
    ProxyError,
    ProxySpec,
    cookies_may_travel,
    curl_proxy_url,
    is_local_endpoint,
    normalize_proxy,
    playwright_proxy,
    redact,
)

# A credential value loud enough to be findable. If this survives into any
# redact() output, a real log line has leaked a secret; the assertions below are
# written to fail loudly on it.
SECRET = "s3cr3t-live-login-token"
USERNAME = "leakfinder"


# ── ProxySpec dataclass ──────────────────────────────────────────────────────


def test_proxy_spec_is_a_frozen_hashable_dataclass():
    spec = ProxySpec(scheme="http", host="h", port=8080)
    with pytest.raises(Exception):
        spec.scheme = "https"  # frozen: assignment must fail


def test_proxy_spec_properties_and_redacted():
    spec = ProxySpec(
        scheme="http", host="host", port=8080, username=USERNAME, password=SECRET
    )
    assert spec.has_credentials is True
    assert spec.endpoint == "host:8080"
    # redacted() swaps only the password for a marker; the username is retained
    # (it is not considered secret), but the password must be gone.
    rendered = spec.redacted()
    assert rendered == f"http://{USERNAME}:***@host:8080"
    assert SECRET not in rendered


def test_proxy_spec_redacted_without_credentials_drops_auth():
    spec = ProxySpec(scheme="http", host="host", port=8080)
    assert spec.has_credentials is False
    assert spec.redacted() == "http://host:8080"


# ── normalize_proxy: happy paths ─────────────────────────────────────────────


def test_normalize_scheme_host_port():
    spec = normalize_proxy("https://proxy.example:3128")
    assert spec == ProxySpec(scheme="https", host="proxy.example", port=3128)
    assert spec.has_credentials is False


@pytest.mark.parametrize("url", ["host:8080", "host:8080/path", "http://host:8080"])
def test_normalize_bare_host_port_defaults_to_http(url):
    spec = normalize_proxy(url)
    assert spec is not None
    assert spec.scheme == "http"
    assert spec.host == "host"
    assert spec.port == 8080


def test_normalize_decodes_percent_encoded_credentials():
    spec = normalize_proxy("http://us%40er:p%40ss@host:8080")
    assert spec.username == "us@er"
    assert spec.password == "p@ss"
    assert spec.has_credentials is True


def test_normalize_parses_ipv6_host():
    spec = normalize_proxy("http://[::1]:8080")
    assert spec.host == "::1"
    assert spec.port == 8080
    # a bracketed uppercase literal is normalised to lowercase by urlparse
    spec2 = normalize_proxy("http://[2001:DB8::1]:8080")
    assert spec2.host == "2001:db8::1"


@pytest.mark.parametrize("scheme", ["http", "https", "socks4", "socks5", "socks5h"])
def test_normalize_accepts_every_supported_scheme(scheme):
    spec = normalize_proxy(f"{scheme}://host:8080")
    assert spec is not None
    assert spec.scheme == scheme


# ── normalize_proxy: empty input ─────────────────────────────────────────────


@pytest.mark.parametrize("text", [None, "", "   ", "\t"])
def test_normalize_returns_none_for_empty_input(text):
    assert normalize_proxy(text) is None


# ── normalize_proxy: rejections are ProxyError, not a bare ValueError ────────
#
# ProxyError subclasses ValueError, so a naive ``except ValueError`` would still
# catch it: assert the *type* is exactly ProxyError so a refactor that raises a
# bare ValueError fails this test.


@pytest.mark.parametrize("url", ["ftp://host:8080", "ws://host:8080", "gopher://h:1"])
def test_normalize_rejects_unsupported_scheme(url):
    with pytest.raises(ProxyError, match="cannot use") as exc_info:
        normalize_proxy(url)
    assert type(exc_info.value) is ProxyError


@pytest.mark.parametrize("url", ["http://host", "http://[::1]", "socks5://h"])
def test_normalize_rejects_missing_port(url):
    with pytest.raises(ProxyError, match="needs a port") as exc_info:
        normalize_proxy(url)
    assert type(exc_info.value) is ProxyError


def test_normalize_rejects_empty_host():
    with pytest.raises(ProxyError, match="no host") as exc_info:
        normalize_proxy("http://:8080")
    assert type(exc_info.value) is ProxyError


def test_normalize_proxy_error_is_value_error_subclass():
    assert issubclass(ProxyError, ValueError)


# ── redact: the password must never leak ─────────────────────────────────────
#
# This is the security-critical guarantee. redact() is called on every proxy URL
# the ladder ever logs, including the ones that failed to parse, so it must be
# total: it never raises and never surfaces a credential.


@pytest.mark.parametrize(
    "url",
    [
        f"http://user:{SECRET}@host:8080",        # valid URL with creds
        f"https://u:{SECRET}@host:443/p",         # path present
        f"http://user:{SECRET}@host",             # portless URL with creds
        f"ftp://user:{SECRET}@host:1",            # malformed scheme, creds present
    ],
)
def test_redact_never_leaks_password(url):
    out = redact(url)
    assert isinstance(out, str)
    assert SECRET not in out, f"password leaked into a loggable string: {out!r}"


def test_redact_replaces_credentials_with_marker_on_valid_url():
    out = redact(f"http://user:{SECRET}@host:8080")
    assert out == "http://user:***@host:8080"


def test_redact_is_total_on_garbage_input():
    # redact must never raise, even on things that are not URLs at all.
    for bad in [None, "", "   ", "not-a-url", "://", "ftp://user:p@h:1"]:
        assert isinstance(redact(bad), str)


# ── the recursion guard ──────────────────────────────────────────────────────


def test_redact_does_not_recurse_when_normalize_raises():
    """Guard against the redact<->normalize mutual-recursion bug.

    The old code had redact() call normalize_proxy() and normalize's error path
    call back into redact(); on an unsupported scheme that looped forever, and
    the credentials leaked into the recursion before it blew the stack. redact
    now uses _shred() as a leaf, so a bad scheme must terminate immediately,
    return a plain string, and must not surface the password or raise.
    """
    out = redact(f"ftp://user:{SECRET}@h:1")
    assert isinstance(out, str)
    assert SECRET not in out, f"password leaked during recursion guard: {out!r}"
    assert "ftp://h:1" == out


# ── is_local_endpoint: the trust boundary ────────────────────────────────────


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "::1",
        "[::1]",  # bracketed form, as a literal IPv6 may arrive
        "10.0.0.1",
        "10.255.255.255",
        "192.168.0.1",
        "192.168.1.50",
        "172.16.0.1",
        "172.31.255.255",  # upper edge of the 172.16/12 private block
        "localhost",
        "localhost.localdomain",
        "169.254.169.254",  # link-local: treated as local by this module
    ],
)
def test_is_local_endpoint_accepts_local(host):
    assert is_local_endpoint(host) is True


@pytest.mark.parametrize(
    "host",
    [
        "1.2.3.4",
        "8.8.8.8",
        "8.8.4.4",
        "172.32.0.1",  # just outside the 172.16/12 private block
        "101.1.1.1",
        "example.com",
        "proxy.corp",
        "host.example",
        "",  # an empty host cannot earn local trust; the answer fails closed
    ],
)
def test_is_local_endpoint_rejects_remote(host):
    assert is_local_endpoint(host) is False


def test_is_local_endpoint_bare_hostname_is_remote():
    # A bare hostname is not an address and cannot earn local trust; the proxy
    # could be anywhere. This is the case the spec calls out by name.
    assert is_local_endpoint("proxy.corp") is False


# ── curl_proxy_url and playwright_proxy: shape + credentials ─────────────────


def test_curl_proxy_url_none_spec_is_none():
    assert curl_proxy_url(None) is None


def test_playwright_proxy_none_spec_is_none():
    assert playwright_proxy(None) is None


def test_curl_proxy_url_includes_credentials():
    spec = normalize_proxy(f"http://{USERNAME}:{SECRET}@host:8080")
    url = curl_proxy_url(spec)
    assert url == f"http://{USERNAME}:{SECRET}@host:8080"
    # curl needs the credentials to auth against the proxy, so they ride along.
    assert SECRET in url
    assert USERNAME in url


def test_playwright_proxy_includes_credentials():
    spec = normalize_proxy(f"http://{USERNAME}:{SECRET}@host:8080")
    proxy = playwright_proxy(spec)
    assert proxy == {
        "server": "http://host:8080",
        "username": USERNAME,
        "password": SECRET,
    }


def test_curl_proxy_url_without_credentials_omits_auth():
    spec = normalize_proxy("http://host:8080")
    assert curl_proxy_url(spec) == "http://host:8080"


def test_playwright_proxy_without_credentials_omits_auth():
    spec = normalize_proxy("http://host:8080")
    assert playwright_proxy(spec) == {"server": "http://host:8080"}


def test_playwright_proxy_shape_is_a_dict_with_server():
    spec = normalize_proxy(f"http://u:{SECRET}@h:1080")
    proxy = playwright_proxy(spec)
    assert isinstance(proxy, dict)
    assert proxy["server"] == "http://h:1080"
    assert proxy["username"] == "u"
    assert proxy["password"] == SECRET


# ── cookies_may_travel: the fence ────────────────────────────────────────────


def test_cookies_may_travel_without_proxy_is_allowed():
    # No proxy at all: nothing to leak through, cookies travel freely.
    assert cookies_may_travel(None) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080",
        "http://[::1]:8080",  # IPv6 must be bracketed inside a URL
        "http://10.0.0.1:8080",
        "http://192.168.1.50:8080",
    ],
)
def test_cookies_may_travel_through_local_proxy_is_allowed(url):
    spec = normalize_proxy(url)
    assert cookies_may_travel(spec) is True
    # a local proxy stays trusted even when the caller did not opt in
    assert cookies_may_travel(spec, trusted=False) is True


@pytest.mark.parametrize("host", ["1.2.3.4", "8.8.8.8", "proxy.corp"])
def test_cookies_may_travel_refuses_a_remote_proxy_unless_trusted(host):
    spec = normalize_proxy(f"http://{host}:8080")
    # THE FENCE: a third-party proxy must not get session cookies by default.
    # Assert loudly, because a False here that turns True silently ships a live
    # login to whoever runs that proxy.
    assert cookies_may_travel(spec) is False, (
        f"cookies would travel through a remote proxy at {host!r}; "
        f"this is the leak the egress fence exists to prevent"
    )
    # the one honest escape hatch: the caller explicitly trusts the remote proxy.
    assert cookies_may_travel(spec, trusted=True) is True


def test_malformed_port_is_a_proxy_error_not_a_bare_value_error():
    """A proxy URL can come from an agent, so a bad port must not traceback.

    urlparse's `.port` raises a plain ValueError on non-numeric input, which
    reaches the user as a raw traceback. Every rejection here is a ProxyError.
    """
    for bad in ("http://host:abc", "socks5://127.0.0.1:notaport"):
        with pytest.raises(ProxyError):
            normalize_proxy(bad)
        with pytest.raises(ProxyError):
            normalize_proxy(bad)  # and never ValueError escaping

    # Explicitly: not a bare ValueError-with-wrong-type
    try:
        normalize_proxy("http://host:abc")
    except ProxyError as e:
        assert isinstance(e, ValueError)
    except ValueError:
        pytest.fail("escaped as a non-ProxyError ValueError")


def test_cookies_may_travel_is_public_api():
    """It is the fence, so it belongs in __all__ like the rest of the surface."""
    from searchts import egress

    assert "cookies_may_travel" in egress.__all__
