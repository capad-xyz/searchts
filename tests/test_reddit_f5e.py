# -*- coding: utf-8 -*-
"""F5e: Reddit HTML reads say what each post is and where its link or media is.

Fixtures are trimmed from real saved pages (2026-09-30), not guessed markup.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from searchts.known_hosts import reddit

FIXTURES = Path(__file__).parent / "fixtures"
LISTING = "https://www.reddit.com/r/MachineLearning/hot/"
THREAD = "https://www.reddit.com/r/MachineLearning/comments/1wsejb7/functional_gradient_descent_with_adaptive/"


def _cards() -> str:
    md = reddit.parse_reddit_listing_html((FIXTURES / "reddit_cards.html").read_text(encoding="utf-8"), LISTING)
    assert md is not None
    return md


def _card(md: str, title_start: str) -> str:
    """One card's block, from its title line to the next card."""
    block = md.split(f"- **{title_start}", 1)[1]
    return block.split("\n- **", 1)[0]


def _thread() -> str:
    md = reddit.parse_reddit_thread_html(
        (FIXTURES / "reddit_thread_media.html").read_text(encoding="utf-8"), THREAD
    )
    assert md is not None
    return md


def test_thread_says_subreddit_flair_type_posted_and_media():
    md = _thread()
    for line in (
        "**Subreddit:** r/MachineLearning",
        "**Flair:** Research",
        "**Type:** gif",
        "**Posted:** 2026-09-28 13:23 UTC",
        "**Media:** https://i.redd.it/wom07k9ih9sh1.gif",
    ):
        assert line in md.splitlines()


def test_thread_read_more_is_a_css_clamp_so_no_truncation_note():
    # The saved page shows "Read more", yet the whole post is in the HTML.
    md = _thread()
    op = md.split("## Comments", 1)[0]
    assert "Read more" not in op
    assert "[truncated: Reddit folded" not in md
    assert op.rstrip().endswith("(First author here, happy to take any questions)")


def test_gallery_card_lists_each_image_once_and_no_card_chrome():
    card = _card(_cards(), "Concurrent Image Understanding")
    assert "Type: gallery" in card
    media = next(ln for ln in card.splitlines() if ln.strip().startswith("Media:"))
    assert media.strip() == "Media: https://i.redd.it/wabzt1np0msh1.gif · https://i.redd.it/2edyhexw0msh1.jpg"
    # The old whole-card fallback printed "u/<name> • 6 hr. ago <title> Research".
    assert "u/Upstairs_Theme2785 •" not in card and "hr. ago" not in card


@pytest.mark.parametrize(
    "title_start, line",
    [
        ("Functional Gradient Descent", "Media: https://i.redd.it/wom07k9ih9sh1.gif"),
        ("Are there machine learning subfields", "Media: https://i.redd.it/zfq29jgkn3sh1.png"),
        ("I trained a 500M VLM", "Outbound: https://github.com/bykof/peekaboolean"),
        ("Neurips Workshop Author Notification", "Flair: Discussion · Type: text · Posted: 2026-09-30 00:28 UTC"),
    ],
)
def test_cards_carry_type_media_and_outbound_lines(title_start, line):
    assert line in [ln.strip() for ln in _card(_cards(), title_start).splitlines()]


def test_card_from_another_subreddit_is_named():
    card = _card(_cards(), "Anthropic just dropped")
    assert "r/LocalLLaMA" in card.splitlines()[1]
    assert "Outbound: https://www.anthropic.com/research/" in card
    # Cards from the listing's own subreddit do not repeat it.
    assert "r/MachineLearning" not in _card(_cards(), "Neurips Workshop").splitlines()[1]


def test_media_post_without_a_url_says_so():
    html = (
        '<shreddit-post post-title="Clip one" post-type="video" permalink="/r/MachineLearning/comments/v1/one/"></shreddit-post>'
        '<shreddit-post post-title="Clip two" post-type="text" permalink="/r/MachineLearning/comments/v2/two/"></shreddit-post>'
    )
    md = reddit.parse_reddit_listing_html(html, LISTING)
    assert md is not None
    assert "Media: present, not resolved" in _card(md, "Clip one")
    assert "Media:" not in _card(md, "Clip two")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2026-09-28T13:23:54.777000+0000", "2026-09-28 13:23 UTC"),
        ("2026-09-28T15:23:54+0200", "2026-09-28 13:23 UTC"),
        ("2026-09-28T13:23:54Z", "2026-09-28 13:23 UTC"),
        ("yesterday", ""),
        ("", ""),
    ],
)
def test_posted_time_is_utc_or_left_out(raw, expected):
    assert reddit._posted({"created-timestamp": raw}) == expected


@pytest.mark.parametrize(
    "href, outbound",
    [
        ("https://notreddit.com/story", "https://notreddit.com/story"),
        ("https://www.reddit.com/r/x/comments/1/a/", ""),
        ("https://i.redd.it/abc123def.png", ""),
    ],
)
def test_outbound_is_any_host_off_reddit(href, outbound):
    assert reddit._post_links({"post-type": "link", "content-href": href})[0] == outbound
