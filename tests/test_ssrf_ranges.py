# -*- coding: utf-8 -*-
"""SSRF ranges that reach this machine or a private network in practice."""

from __future__ import annotations

import pytest

from searchts import assets
from searchts.ssrf import guard_mcp_url


@pytest.mark.parametrize(
    "url",
    [
        "http://0.0.0.0:8080/",              # unspecified v4: Linux/macOS connect to localhost
        "http://0.1.2.3/",                    # rest of 0.0.0.0/8
        "http://[::]:8080/",                  # unspecified v6
        "http://100.100.100.100/",            # CGNAT / Tailscale
        "http://224.0.0.1/",                  # multicast
        "http://255.255.255.255/",            # broadcast (240.0.0.0/4)
        "http://[64:ff9b::7f00:1]/",          # NAT64 carrying 127.0.0.1
        "http://[64:ff9b::a9fe:a9fe]/",       # NAT64 carrying the metadata IP
        "http://[64:ff9b:1::1]/",             # local-use NAT64
        "http://[2002:7f00:1::]/",            # 6to4 carrying 127.0.0.1
        "http://[2002:c0a8:101::]/",          # 6to4 carrying 192.168.1.1
        "http://[::127.0.0.1]/",              # IPv4-compatible loopback
    ],
)
def test_blocked(url):
    assert guard_mcp_url(url, resolve_dns=False) is not None


@pytest.mark.parametrize(
    "url",
    [
        "http://8.8.8.8/",
        "http://[2606:4700:4700::1111]/",
        "http://[64:ff9b::808:808]/",         # NAT64 of a public address
        "http://[2002:808:808::]/",           # 6to4 of a public address
        "http://100.63.255.255/",             # just below CGNAT
    ],
)
def test_public_allowed(url):
    assert guard_mcp_url(url, resolve_dns=False) is None


def test_asset_fetch_refuses_private_ip_literal(monkeypatch):
    """grab() pulls asset URLs out of untrusted HTML; each one is guarded."""

    def must_not_connect(*a, **k):
        raise AssertionError("no rung may connect to a blocked URL")

    monkeypatch.setattr(assets, "_fetch_bytes_curl", must_not_connect)
    monkeypatch.setattr(assets, "_fetch_bytes_stealth", must_not_connect)
    monkeypatch.setattr(assets, "_fetch_bytes_jina_html", must_not_connect)
    with pytest.raises(assets.AssetError) as exc:
        assets.fetch_bytes("http://169.254.169.254/latest/meta-data/", backends=["curl_cffi"])
    assert exc.value.attempts and exc.value.attempts[0][0] == "ssrf"
