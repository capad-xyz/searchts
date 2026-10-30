"""#333: the recall fallback also leaves out the site header's account and promo
links ("Sign in", "Print subscriptions"), not the headlines a front page keeps
inside that same <header>.
"""
import pytest

from searchts import unlocker

HEADLINES = [
    f"Council approves plan number {i} for the new riverside housing scheme"
    for i in range(40)
]


def _stories(prefix="story"):
    return "".join(
        f'<li><a href="/{prefix}/{i}">{h}</a></li>' for i, h in enumerate(HEADLINES)
    )


@pytest.fixture(autouse=True)
def _article_extract_loses(monkeypatch):
    import trafilatura

    monkeypatch.setattr(trafilatura, "extract", lambda *a, **k: "Front page", raising=True)


def _read(body):
    html = f"<html><head><title>Front page</title></head><body>{body}</body></html>"
    return unlocker.html_to_text(html, "https://news.test/")


def test_header_account_links_are_dropped_and_its_headlines_kept():
    text = _read(
        "<header>"
        '<a href="/subscribe">Print subscriptions</a>'
        '<a href="/signin">Sign in</a>'
        f"<ul>{_stories()}</ul>"
        "</header>"
    )
    for headline in HEADLINES:
        assert headline in text
    assert "Print subscriptions" not in text
    assert "Sign in" not in text


def test_role_banner_counts_as_a_site_header():
    text = _read(
        '<div role="Banner"><button>Log in</button></div>'
        f"<main><ul>{_stories()}</ul></main>"
    )
    assert "Log in" not in text
    assert HEADLINES[0] in text


def test_a_short_headline_under_a_heading_stays():
    text = _read(
        '<header><h2><a href="/live">Election live</a></h2>'
        '<a href="/signin">Sign in</a></header>'
        f"<main><ul>{_stories()}</ul></main>"
    )
    assert "Election live" in text
    assert "Sign in" not in text


def test_a_header_inside_the_content_keeps_its_links():
    text = _read(
        f"<main><article><header><a href='/by/ann'>Ann Lee</a></header>"
        f"<ul>{_stories()}</ul></article></main>"
    )
    assert "Ann Lee" in text


def test_text_after_a_dropped_link_stays():
    text = _read(
        '<header><a href="/signin">Sign in</a>Tuesday 4 November edition</header>'
        f"<main><ul>{_stories()}</ul></main>"
    )
    assert "Tuesday 4 November edition" in text
    assert "Sign in" not in text
