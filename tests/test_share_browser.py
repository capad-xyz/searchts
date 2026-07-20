# -*- coding: utf-8 -*-
"""No-network tests for the Phase-3 browser-render share extractors.

Covers, for DeepSeek / Copilot / Perplexity:

- URL matching (the ``PATTERN`` gate) — positive and negative.
- The importable ``parse_<provider>_dom`` pure functions against trimmed
  rendered-DOM fixtures (no browser involved).
- Proof that ``extract`` never launches a browser when the URL doesn't match:
  each provider's ``render`` is replaced with a booby-trap and a non-share URL
  must fall through without ever calling it.

The patchright launch itself is never exercised here.
"""

from pathlib import Path

import pytest

from searchts import share_extractors
from searchts.share_extractors import ShareResult, copilot, deepseek, extract, matches, perplexity

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ── URL matching ─────────────────────────────────────────────────────────────


def test_matches_recognized_browser_render_urls():
    assert matches("https://chat.deepseek.com/share/khucvl0w79pqb0wtgp")
    assert matches("https://copilot.microsoft.com/shares/naWEFJwqRhycQ86dXjkFd")
    assert matches("https://www.perplexity.ai/search/phyllis-schlafly-era-72UeZXALQOaEFiXa7fKTNQ")
    assert matches("https://perplexity.ai/search/How-does-Perplexity-fPyCf621Qk")


def test_deepseek_pattern():
    assert deepseek.PATTERN.match("https://chat.deepseek.com/share/abc123XYZ")
    assert deepseek.PATTERN.match("https://chat.deepseek.com/share/abc123XYZ").group(1) == "abc123XYZ"
    assert not deepseek.PATTERN.match("https://chat.deepseek.com/")
    assert not deepseek.PATTERN.match("https://deepseek.com/share/abc123")


def test_copilot_pattern():
    m = copilot.PATTERN.match("https://copilot.microsoft.com/shares/naWEFJwqRhycQ86dXjkFd")
    assert m and m.group(1) == "naWEFJwqRhycQ86dXjkFd"
    assert not copilot.PATTERN.match("https://copilot.microsoft.com/")
    assert not copilot.PATTERN.match("https://copilot.microsoft.com/chats/abc")


def test_perplexity_pattern():
    m = perplexity.PATTERN.match("https://www.perplexity.ai/search/some-slug-Ab12")
    assert m and m.group(1) == "some-slug-Ab12"
    assert not perplexity.PATTERN.match("https://www.perplexity.ai/")
    assert not perplexity.PATTERN.match("https://www.perplexity.ai/search/")  # empty slug


def test_matches_rejects_unrelated_urls():
    assert not matches("https://example.com/")
    assert not matches("https://chat.deepseek.com/")
    assert not matches("https://copilot.microsoft.com/")


# ── DeepSeek DOM parse ───────────────────────────────────────────────────────


def test_parse_deepseek_dom():
    res = deepseek.parse_deepseek_dom(_read("deepseek_rendered.html"))
    assert isinstance(res, ShareResult)
    assert res.provider == "deepseek"
    assert res.markdown.count("**User:**") == 2
    assert res.markdown.count("**DeepSeek:**") == 2
    # Conversation order and content.
    assert res.markdown.index("boiling point of water") < res.markdown.index("100 degrees Celsius")
    assert res.markdown.index("Mount Everest") < res.markdown.index("68 degrees Celsius")
    # Paragraph break preserved inside the assistant markdown.
    assert "100 degrees Celsius" in res.markdown
    assert "atmospheric pressure decreases" in res.markdown
    # Reasoning panel and action-button labels are excluded from the answer.
    assert "basic physics fact" not in res.markdown
    assert "Regenerate" not in res.markdown
    assert "Copy" not in res.markdown


def test_parse_deepseek_dom_empty():
    assert deepseek.parse_deepseek_dom("<html><body>no messages</body></html>") is None
    assert deepseek.parse_deepseek_dom("") is None


# ── Perplexity DOM parse ─────────────────────────────────────────────────────


def test_parse_perplexity_dom():
    res = perplexity.parse_perplexity_dom(_read("perplexity_rendered.html"))
    assert isinstance(res, ShareResult)
    assert res.provider == "perplexity"
    assert res.title == "How do tides work?"
    assert res.markdown.count("**User:**") == 2
    # Each answer container is duplicated in the DOM; de-dupe keeps exactly one.
    assert res.markdown.count("**Perplexity:**") == 2
    assert "gravitational pull of the Moon" in res.markdown
    assert "Spring tides" in res.markdown
    # Interleaving preserved: first Q/A precedes the follow-up Q/A.
    assert res.markdown.index("How do tides work?") < res.markdown.index("bigger than others")


def test_parse_perplexity_dom_empty():
    assert perplexity.parse_perplexity_dom("<html><body>shell</body></html>") is None


# ── Copilot DOM parse ────────────────────────────────────────────────────────


def test_parse_copilot_dom():
    res = copilot.parse_copilot_dom(_read("copilot_rendered.html"))
    assert isinstance(res, ShareResult)
    assert res.provider == "copilot"
    assert res.markdown.count("**User:**") == 1
    assert res.markdown.count("**Copilot:**") == 1
    assert "beginner-friendly houseplant" in res.markdown
    assert "pothos" in res.markdown
    # sr-only role headings are peeled off the message bodies.
    assert "You said" not in res.markdown
    assert "Copilot said" not in res.markdown
    # The composer placeholder is not an article and must not leak in as a turn.
    assert "Continue the conversation" not in res.markdown


def test_parse_copilot_dom_empty():
    assert copilot.parse_copilot_dom("<html><body>shell only</body></html>") is None


# ── the browser is never launched for a non-matching URL ─────────────────────


def _boobytrap_renders(monkeypatch):
    """Replace every provider's render with one that fails loudly if called."""
    def boom(*args, **kwargs):
        raise AssertionError("render() launched a browser but should not have")

    monkeypatch.setattr(deepseek, "render", boom)
    monkeypatch.setattr(copilot, "render", boom)
    monkeypatch.setattr(perplexity, "render", boom)


def test_extract_non_share_url_never_renders(monkeypatch):
    _boobytrap_renders(monkeypatch)
    # No PATTERN matches, so no extract_share runs and no browser is launched.
    assert extract("https://example.com/") is None
    assert extract("https://chat.deepseek.com/") is None
    assert extract("https://copilot.microsoft.com/settings") is None


def test_extract_share_uses_render_and_parses(monkeypatch):
    # A matching URL routes to the provider's extract_share, which calls the
    # (here-stubbed) render and then the real DOM parser.
    monkeypatch.setattr(deepseek, "render", lambda *a, **k: _read("deepseek_rendered.html"))
    res = deepseek.extract_share(
        "https://chat.deepseek.com/share/abc123",
        deepseek.PATTERN.match("https://chat.deepseek.com/share/abc123"),
    )
    assert isinstance(res, ShareResult)
    assert res.provider == "deepseek"
    assert "100 degrees Celsius" in res.markdown


def test_extract_share_returns_none_when_render_fails(monkeypatch):
    # render() returning None (shell / bot-wall / no patchright) => fall through.
    monkeypatch.setattr(perplexity, "render", lambda *a, **k: None)
    res = perplexity.extract_share(
        "https://www.perplexity.ai/search/x-Ab12",
        perplexity.PATTERN.match("https://www.perplexity.ai/search/x-Ab12"),
    )
    assert res is None


def test_share_extractor_registry_includes_new_providers():
    # Sanity: the three modules were auto-discovered by the package registry.
    assert extract("https://example.com/") is None  # smoke: registry callable
    for url in (
        "https://chat.deepseek.com/share/abc123",
        "https://copilot.microsoft.com/shares/abc123",
        "https://www.perplexity.ai/search/slug-Ab12",
    ):
        assert share_extractors.matches(url)
