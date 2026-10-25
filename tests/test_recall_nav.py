"""#333: the recall fallback leaves out the site navigation, not the content.

#331's fallback is the crude strip, which restores a link-list page's links and
its menus with them. A <nav> landmark is dropped only while it is a small share
of the page; a page whose content is a nav-wrapped index keeps it.
"""
import pytest

from searchts import unlocker

MENU = ["Sign in", "Newsletters", "Sport", "Culture", "Lifestyle", "Opinion"]
HEADLINES = [
    f"Council approves plan number {i} for the new riverside housing scheme"
    for i in range(40)
]


def _links(labels, prefix):
    return "".join(
        f'<li><a href="/{prefix}/{i}">{label}</a></li>' for i, label in enumerate(labels)
    )


def _front_page(nav_open="<nav>", nav_close="</nav>"):
    return (
        "<html><head><title>Front page</title></head><body>"
        f"<header>{nav_open}<ul>{_links(MENU, 'section')}</ul>{nav_close}</header>"
        f"<main><ul>{_links(HEADLINES, 'story')}</ul></main>"
        "</body></html>"
    )


@pytest.fixture(autouse=True)
def _article_extract_loses(monkeypatch):
    """trafilatura's precision heuristic keeps one line of a link-list page.

    That is the case #331's fallback exists for, and the only path this
    change touches.
    """
    import trafilatura

    monkeypatch.setattr(
        trafilatura, "extract", lambda *a, **k: "Front page", raising=True,
    )


def _lines(text):
    return {line.strip() for line in text.splitlines() if line.strip()}


def test_front_page_keeps_headlines_and_drops_the_menu():
    text = unlocker.html_to_text(_front_page(), "https://news.test/")
    for headline in HEADLINES:
        assert headline in text
    assert not any(label in line for line in _lines(text) for label in MENU)


def test_role_navigation_counts_as_a_nav_landmark():
    page = _front_page('<div role="Navigation">', "</div>")
    text = unlocker.html_to_text(page, "https://news.test/")
    assert HEADLINES[0] in text
    assert "Newsletters" not in text


def test_a_docs_index_inside_nav_is_the_page_and_stays():
    titles = [f"Utility {i} reference" for i in range(60)]
    page = (
        "<html><body><nav><ul>"
        f"{_links(titles, 'docs')}"
        "</ul></nav><main><h1>Docs</h1><p>Pick a page.</p></main></body></html>"
    )
    text = unlocker.html_to_text(page, "https://docs.test/")
    for title in titles:
        assert title in text


def test_page_without_nav_is_unchanged():
    page = _front_page("", "")
    text = unlocker.html_to_text(page, "https://news.test/")
    assert HEADLINES[-1] in text
    assert "Newsletters" in text


def test_menu_kept_when_dropping_it_would_leave_too_little():
    menu = [f"Section {i} of the site" for i in range(30)]
    page = (
        "<html><body><nav><ul>"
        f"{_links(menu, 'section')}"
        f"</ul></nav><main><ul>{_links(HEADLINES[:5], 'story')}</ul></main>"
        "</body></html>"
    )
    text = unlocker.html_to_text(page, "https://news.test/")
    assert "Section 29 of the site" in text
    assert HEADLINES[4] in text
