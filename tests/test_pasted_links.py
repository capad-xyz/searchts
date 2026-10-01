"""A link pasted inside <...> or [...] reads as the link (F22c)."""

import pytest

from searchts import ssrf, unlocker


@pytest.mark.parametrize(
    "pasted",
    [
        "[https://www.djangoproject.com/weblog/]",
        "<https://www.djangoproject.com/weblog/>",
        "  [ https://www.djangoproject.com/weblog/ ]  ",
    ],
)
def test_wrapped_link_reads_as_the_link(pasted):
    assert unlocker.normalize(pasted) == "https://www.djangoproject.com/weblog/"


def test_brackets_inside_a_link_stay():
    url = "https://example.com/a[1]"
    assert unlocker.normalize(url) == url
    assert unlocker.normalize(f"[{url}]") == url


def test_bare_ipv6_brackets_are_not_unwrapped():
    assert ssrf.unwrap_link("[::1]") == "[::1]"


def test_other_junk_says_it_is_not_a_url():
    with pytest.raises(ValueError, match="not a URL"):
        unlocker.normalize("(https://example.com)")
    with pytest.raises(ValueError, match="scheme 'ftp://' is not allowed"):
        unlocker.normalize("ftp://example.com/x")


@pytest.mark.parametrize("pasted", ["<http://127.0.0.1/>", "[http://0.0.0.0/]", "<http://169.254.169.254/latest/>"])
def test_mcp_guard_checks_the_unwrapped_link(pasted):
    # The guard must see what the fetch will use, or a wrapper would slip past it.
    out = ssrf.guard_mcp_url(pasted, resolve_dns=False)
    assert out and out.startswith("Error: SSRF guard"), out


def test_mcp_guard_lets_a_wrapped_public_link_through():
    assert ssrf.guard_mcp_url("<https://example.com/>", resolve_dns=False) is None
