# -*- coding: utf-8 -*-
"""Route the ladder through a proxy, so egress IP is no longer fixed.

Why this exists: some walls are not about the request at all. Measured on this
machine, StackOverflow, The Economist, Science, ArsTechnica and Reuters are
refused by Cloudflare for the *address*, not for the headers: plain
``requests`` with no impersonation gets the identical 403 with ``cf-ray``, and
Wikipedia, GitHub and BBC read 200 from the same IP in the same minute. The
only thing that changes that verdict is the address the request comes from.

So this module does one thing: take a proxy URL and hand it to the rungs that
can use one, and decide whether cookies may travel through it.

The cookie rule
---------------
A proxy is a third party. Sending a ``Cookie`` header through one hands that
third party a live login, which is exactly the leak the jina fence exists to
prevent, and unlike jina there is no way to scope a session cookie to one site
on the far side.

The rule is derived from something an attacker cannot fake: **where the proxy
itself is.** A proxy on loopback or a private network is on your own machine,
almost always a VPN client or a local proxy daemon that you configured, so
cookies may travel. Anything else is refused, and the message says so.

Two escape hatches, both honest:

* A VPN in TUN/system mode needs no flag at all. ``curl_cffi`` has
  ``trust_env=True`` by default and already reads ``HTTPS_PROXY``, and a TUN
  device is invisible to searchts, so every rung routes through it for free.
* Pass ``trusted=True`` when you run a remote proxy and accept that its
  operator can see the cookie header.

Nothing here is obfuscation. The rungs keep impersonating the same Chrome; the
only thing that changes is the address.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlparse

__all__ = [
    "ProxySpec",
    "ProxyError",
    "normalize_proxy",
    "redact",
    "curl_proxy_url",
    "playwright_proxy",
    "is_local_endpoint",
    "cookies_may_travel",
]


class ProxyError(ValueError):
    """The proxy URL is unusable. Carries one sentence, not a traceback."""


#: Schemes we can actually route through. curl speaks http/https/socks;
#: patchright speaks http/socks5.
_SUPPORTED = ("http", "https", "socks4", "socks5", "socks5h")

_REDACTED = "***"


@dataclass(frozen=True)
class ProxySpec:
    """A parsed proxy. ``raw`` keeps the credentials; never print it."""

    scheme: str
    host: str
    port: int
    username: str = ""
    password: str = ""

    @property
    def has_credentials(self) -> bool:
        return bool(self.username or self.password)

    @property
    def endpoint(self) -> str:
        """host:port, with no credentials. Safe to log."""
        return f"{self.host}:{self.port}"

    def redacted(self) -> str:
        """A loggable form. Credentials become ***."""
        auth = f"{self.username}:{_REDACTED}@" if self.has_credentials else ""
        return f"{self.scheme}://{auth}{self.host}:{self.port}"


def is_local_endpoint(host: str) -> bool:
    """True when the proxy lives on this machine or a private network.

    This is the trust boundary for cookies. An off-box attacker cannot claim a
    loopback address, so "the proxy is local" is a property of the connection
    and not something the far side gets to assert.
    """
    h = (host or "").strip().strip("[]").lower()
    # An empty host is not local. normalize_proxy already refuses one, so this
    # only comes up for a hand-built ProxySpec -- and the answer there has to
    # fail closed, because this function is the cookie trust boundary.
    if h in ("localhost", "localhost.localdomain"):
        return True
    # A bare hostname is not an address; treat it as remote. Only a literal
    # loopback/private address earns local trust.
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def _shred(proxy: str) -> str:
    """Strip credentials without parsing. Never raises, never recurses.

    ``normalize_proxy`` calls this for its error messages and ``redact`` calls
    ``normalize_proxy``, so the two must not both call each other. This is the
    leaf: it only does string surgery on what is after an '@'.
    """
    raw = proxy.strip()
    if "@" in raw:
        scheme = ""
        # Two different types live here, so they get two names: reusing one
        # variable for the str and the list was a TypeError waiting to happen.
        after_at = raw.split("@", 1)[1]
        head, sep, _ = raw.partition("://")
        if sep:
            scheme = head + "://"
        return f"{scheme}{after_at}"
    return raw


def normalize_proxy(proxy: Optional[str]) -> Optional[ProxySpec]:
    """Parse and validate a proxy URL. Returns None for empty input.

    Accepts ``scheme://[user:pass@]host:port``. A missing port is an error for
    every supported scheme, because guessing one silently routes nowhere.
    """
    if proxy is None:
        return None
    raw = proxy.strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "http://" + raw

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in _SUPPORTED:
        raise ProxyError(
            f"cannot use a {scheme or 'missing'}:// proxy. "
            f"Supported: {', '.join(_SUPPORTED)}."
        )
    host = (parsed.hostname or "").strip()
    if not host:
        raise ProxyError(f"no host in the proxy URL ({_shred(raw)}).")
    # `.port` raises a bare ValueError on a non-numeric port, which would reach
    # the user as a traceback from a URL an agent supplied. Convert it here, so
    # every rejection from this function is a ProxyError with a sentence.
    try:
        port = parsed.port
    except ValueError:
        raise ProxyError(
            f"the proxy port is not a number ({_shred(raw)})."
        ) from None
    if port is None:
        raise ProxyError(
            f"the proxy URL needs a port ({_shred(raw)}). "
            f"Trying one silently routes nowhere."
        )
    return ProxySpec(
        scheme=scheme,
        host=host,
        port=port,
        username=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
    )


def redact(proxy: Optional[str]) -> str:
    """Strip credentials from a proxy URL so it can be logged or echoed."""
    if not proxy:
        return ""
    try:
        spec = normalize_proxy(proxy)
    except ProxyError:
        return _shred(proxy)
    return spec.redacted() if spec else ""


def curl_proxy_url(spec: Optional[ProxySpec]) -> Optional[str]:
    """The URL curl_cffi wants, credentials included (it needs them to auth)."""
    if spec is None:
        return None
    if not spec.has_credentials:
        return f"{spec.scheme}://{spec.host}:{spec.port}"
    from urllib.parse import quote

    return (
        f"{spec.scheme}://{quote(spec.username, safe='')}:"
        f"{quote(spec.password, safe='')}@{spec.host}:{spec.port}"
    )


def playwright_proxy(spec: Optional[ProxySpec]) -> Optional[Dict[str, Any]]:
    """The dict patchright/playwright wants for ``proxy=``."""
    if spec is None:
        return None
    out: Dict[str, Any] = {"server": f"{spec.scheme}://{spec.host}:{spec.port}"}
    if spec.username:
        out["username"] = spec.username
    if spec.password:
        out["password"] = spec.password
    return out


def cookies_may_travel(
    spec: Optional[ProxySpec], trusted: bool = False
) -> bool:
    """Whether a cookie header may be sent through this proxy.

    Refuses for a non-local proxy unless the caller explicitly trusts it. A
    local proxy is on this machine and is trusted by default.
    """
    if spec is None:
        return True
    return trusted or is_local_endpoint(spec.host)
