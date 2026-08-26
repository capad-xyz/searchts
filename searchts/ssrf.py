# -*- coding: utf-8 -*-
"""SSRF guard for the MCP URL tools.

Imported ONLY from ``searchts/integrations/mcp_server.py``. The CLI and the
library ``unlocker.fetch`` stay unrestricted so a human can still read local
files and LAN hosts; this guard is the boundary an *agent* drives through MCP.

``guard_mcp_url`` returns an ``"Error: ..."`` string when the URL must be
rejected and ``None`` when it is allowed. MCP tool handlers return that error
string directly (never raise), preserving the existing Error-string contract.

Rejected:
- anything that is not http/https (``file://``, ``data:``, ``ftp://``, ...)
- loopback (127.0.0.0/8, ::1, localhost)
- IPv4/IPv6 link-local (169.254.0.0/16, fe80::/10)
- RFC1918 (10/8, 172.16/12, 192.168/16)
- cloud metadata endpoints (169.254.169.254 and the well-known metadata
  hostnames/IPv6 address shared by AWS/GCP/Azure IMDS)
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.parse
from typing import Optional

#: Cloud metadata hostnames (exact, plus the GCP metadata subdomain).
_METADATA_HOSTS = frozenset({"localhost", "metadata", "metadata.google.internal"})
_METADATA_HOST_SUFFIX = ".metadata.google.internal"

#: Cloud metadata IPv6 (GCP IMDS). The IPv4 169.254.169.254 is covered by the
#: link-local range but is called out explicitly for a clearer message.
_METADATA_V6 = frozenset({"fd00:fd00:fd00::a9fe:a9fe", "fd00:fd00:fd00:0:a9fe:a9fe"})

_LOOPBACK_V4 = ipaddress.ip_network("127.0.0.0/8")
_LINKLOCAL_V4 = ipaddress.ip_network("169.254.0.0/16")
_LINKLOCAL_V6 = ipaddress.ip_network("fe80::/10")
_RFC1918 = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)


def _classify(ip: "ipaddress.IPv4Address | ipaddress.IPv6Address") -> Optional[str]:
    """Return a human-readable reason if `ip` is a blocked address, else None."""
    # Cloud metadata endpoints (most specific first).
    if ip.version == 4 and str(ip) == "169.254.169.254":
        return "cloud metadata endpoint 169.254.169.254"
    if str(ip) in _METADATA_V6:
        return "cloud metadata endpoint (GCP IPv6)"

    # Loopback.
    if ip.version == 4 and ip in _LOOPBACK_V4:
        return "loopback address (127.0.0.0/8)"
    if ip.version == 6 and str(ip) == "::1":
        return "loopback address (::1)"

    # Link-local.
    if ip.version == 4 and ip in _LINKLOCAL_V4:
        return "link-local address (169.254.0.0/16)"
    if ip.version == 6 and ip in _LINKLOCAL_V6:
        return "link-local address (fe80::/10)"

    # RFC1918 private ranges.
    for net in _RFC1918:
        if ip.version == net.version and ip in net:
            return "private RFC1918 address"

    return None


def _encoded_ip(host: str) -> "Optional[ipaddress.IPv4Address]":
    """Recognize decimal/hex integer IPv4 encodings (classic SSRF bypasses).

    e.g. ``2130706433`` -> 127.0.0.1, ``0x7f000001`` -> 127.0.0.1. Dotted
    forms are left to the normal parser. Returns None when `host` is not a
    single encoded integer.
    """
    h = host.strip()
    if h and h.isdigit():
        try:
            return ipaddress.IPv4Address(int(h))
        except (ValueError, ipaddress.AddressValueError):
            return None
    if h.startswith("0x") or h.startswith("0X"):
        try:
            return ipaddress.IPv4Address(int(h, 16))
        except ValueError:
            return None
    return None


def _classify_host(host: str) -> Optional[str]:
    """Classify a parsed lowercase host (no scheme) as dangerous or None."""
    # Encoded integer IPs (decimal / hex) bypass the normal IPv4 parser.
    encoded = _encoded_ip(host)
    if encoded is not None:
        return _classify(encoded)

    # Straight IP literal.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    # IPv4-mapped / IPv4-compatible IPv6 (e.g. ::ffff:127.0.0.1).
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped
        if mapped is not None:
            return _classify(mapped)
    return _classify(ip)


def guard_mcp_url(url: str, *, resolve_dns: bool = True) -> Optional[str]:
    """Return an ``"Error: ..."`` string if `url` is unsafe for MCP, else None.

    Only ``http``/``https`` schemes are allowed. Everything else (``file://``,
    ``data:``, ``ftp://``, ...) is rejected. The host is checked against the
    loopback / link-local / RFC1918 / cloud-metadata ranges; a hostname that
    resolves to a dangerous IP is also rejected.

    DNS behavior: a public hostname that does NOT resolve is allowed through
    (the normal fetch will fail with its own error — documented fail-open, so
    an unresolvable name never becomes a hard block). A hostname that DOES
    resolve to a blocked IP fails closed. IP literals never touch DNS.
    """
    if not url:
        return None  # the tool's own "requires url" check owns the empty case

    parsed = urllib.parse.urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme and scheme not in ("http", "https"):
        return (
            f"Error: SSRF guard: scheme '{scheme}://' is not allowed "
            "(only http/https may be fetched via MCP)."
        )

    # A bare host (no scheme) like ``example.com`` is treated as https, matching
    # the unlocker's own normalize() so humans and agents agree on what's public.
    if not scheme:
        parsed = urllib.parse.urlparse("https://" + url)
        host = (parsed.hostname or "").lower().rstrip(".")
    else:
        host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return "Error: SSRF guard: could not parse a host from the URL."

    # Explicit metadata / loopback hostnames (don't depend on /etc/hosts).
    if host in _METADATA_HOSTS or host.endswith(_METADATA_HOST_SUFFIX):
        return f"Error: SSRF guard: '{host}' is a cloud metadata endpoint."

    reason = _classify_host(host)
    if reason is not None:
        return f"Error: SSRF guard: {reason} ('{host}') is not allowed via MCP."

    # Hostname: resolve and reject if any resolved IP is dangerous. If DNS
    # fails, fail open (documented) — the subsequent fetch errors naturally.
    if not resolve_dns:
        return None
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, OSError, ValueError):
        return None
    for info in infos:
        sockaddr = info[4] if info and len(info) > 4 else None
        addr = sockaddr[0] if sockaddr else None
        if not isinstance(addr, str):
            continue
        reason = _classify_host(addr)
        if reason is not None:
            return (
                f"Error: SSRF guard: '{host}' resolves to {reason} "
                f"('{addr}') and is not allowed via MCP."
            )
    return None
