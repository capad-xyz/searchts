# -*- coding: utf-8 -*-
"""Fail loud on Reddit HTML: a folded post or capped comments say so (#197 honesty part)."""

from __future__ import annotations

from searchts.known_hosts import reddit

THREAD = "https://www.reddit.com/r/MachineLearning/comments/abc123/some_title/"
LISTING = "https://www.reddit.com/r/MachineLearning/hot/"


def _post(title, body, **attrs):
    extra = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    return (
        f'<shreddit-post post-title="{title}" author="u/op" {extra}>'
        f'<div slot="text-body"><p>{body}</p></div></shreddit-post>'
    )


def _comment(i, depth_children=""):
    return (
        f'<shreddit-comment author="user{i}" score="{i}">'
        f'<div slot="comment"><p>comment number {i} with real text</p></div>'
        f"{depth_children}</shreddit-comment>"
    )


def test_read_more_label_is_dropped_without_a_note():
    # Reddit ships the whole post even when "Read more" shows (a CSS clamp,
    # checked on saved threads, F5e), so the label goes and no note is added.
    html = _post("A long post", "The first part of a long post. Read more", comment_count="0")
    md = reddit.parse_reddit_thread_html(html, THREAD)
    assert md is not None
    assert "Read more" not in md
    assert "[truncated" not in md
    assert "The first part of a long post." in md

def test_unfolded_op_has_no_truncation_note():
    html = _post("Short post", "Complete short body.", comment_count="0")
    md = reddit.parse_reddit_thread_html(html, THREAD)
    assert md is not None and "[truncated" not in md and "[partial" not in md


def test_comment_cap_is_reported():
    comments = "".join(_comment(i) for i in range(reddit._MAX_COMMENTS + 5))
    html = _post("Busy thread", "Body text here.", comment_count=str(reddit._MAX_COMMENTS + 5)) + comments
    md = reddit.parse_reddit_thread_html(html, THREAD)
    assert md is not None
    assert md.count("**/u/user") == reddit._MAX_COMMENTS
    assert f"[truncated: 5 more comments in the page were cut at the {reddit._MAX_COMMENTS}-comment cap]" in md
    assert "[partial" not in md


def test_claimed_comments_beyond_the_page_are_reported():
    html = _post("Thread", "Body text here.", comment_count="36") + "".join(_comment(i) for i in range(3))
    md = reddit.parse_reddit_thread_html(html, THREAD)
    assert md is not None
    assert "[partial: Reddit reports 36 comments; 3 were in the page." in md


def test_no_comments_in_page_but_reddit_claims_some():
    html = _post("Thread", "Body text here.", comment_count="12")
    md = reddit.parse_reddit_thread_html(html, THREAD)
    assert md is not None
    assert "## Comments" in md
    assert "Reddit reports 12 comments; 0 were in the page" in md


def test_listing_snippet_drops_the_fold_marker():
    html = _post("One", "Preview of the first post… Read more", permalink="/r/MachineLearning/comments/a1/one/") + _post(
        "Two", "Second preview", permalink="/r/MachineLearning/comments/a2/two/"
    )
    md = reddit.parse_reddit_listing_html(html, LISTING)
    assert md is not None
    assert "Read more" not in md
    assert "Preview of the first post" in md


def test_a_post_that_really_ends_with_read_more_is_not_marked():
    html = _post("Guide", "The full guide is on the wiki, where you can read more", comment_count="0")
    md = reddit.parse_reddit_thread_html(html, THREAD)
    assert md is not None
    assert "where you can read more" in md
    assert "[truncated" not in md
