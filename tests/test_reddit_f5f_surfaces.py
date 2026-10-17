# -*- coding: utf-8 -*-
"""F5f surfaces: the CLI flag and the MCP parameter carry the same intent.

The knobs an agent may set (F23e's shape) reach Reddit the same way on both
surfaces: ``--items`` / ``max_items`` follow the cursor the page printed, and
``--expand`` / ``expand`` is the opt-in bool and off by default. F5f rides F23d's
bool rather than adding an int: how many comments or clicks that means comes
from the knobs, not from the flag. This file is about the wiring, not the
parsing: the parsing is in ``test_reddit_f5f.py`` against saved pages.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import searchts.integrations.mcp_server as mcp_server  # noqa: E402
from searchts import cli, unlocker  # noqa: E402

LISTING = "https://www.reddit.com/r/MachineLearning/hot/"
THREAD = (
    "https://www.reddit.com/r/MachineLearning/comments/1x4awlk/"
    "what_is_the_strongest_mechanistic_argument_that/"
)


def _read_kwargs(monkeypatch, argv):
    """Run the entry point over argv and return the keyword the read got."""
    seen: dict = {}

    def fake_fetch(url, **kw):
        seen.update(kw)
        return unlocker.FetchResult("curl_cffi", "# hi\n\nsome text here", 200, final_url=url)

    monkeypatch.setattr(unlocker, "fetch", fake_fetch)
    _run_cli(argv)
    return seen


def _run_cli(argv):
    """Call the real entry point; a read that succeeds does not exit."""
    saved = sys.argv
    sys.argv = ["searchts", *argv]
    try:
        cli.main()
    except SystemExit:
        pass
    finally:
        sys.argv = saved


def test_read_takes_expand_and_it_is_false_by_default(monkeypatch):
    assert _read_kwargs(monkeypatch, ["read", THREAD]).get("expand") is False
    assert _read_kwargs(monkeypatch, ["read", THREAD, "--expand"])["expand"] is True
    # Clicking things is never what an unasked-for read does.


def test_read_without_expand_keeps_the_old_call_shape(monkeypatch):
    """A stub written against the old signature must still work."""
    calls: list = []

    def old_signature(url, backends=None, allow_human=False, **kwargs):
        calls.append((url, backends, allow_human))
        return unlocker.FetchResult("curl_cffi", "# hi\n\ntext", 200, final_url=url)

    monkeypatch.setattr(unlocker, "fetch", old_signature)
    _run_cli(["read", THREAD])
    assert calls == [(THREAD, None, False)]


def test_read_items_and_expand_travel_together(monkeypatch):
    seen: dict = {}

    def fake_read_items(url, n, **kw):
        seen.update(kw)
        seen["items"] = n
        return [unlocker.FetchResult("curl_cffi", "- **[a](https://x.test/a)**", 200, final_url=url)]

    monkeypatch.setattr(unlocker, "read_items", fake_read_items)
    _run_cli(["read", LISTING, "--items", "40", "--expand"])
    assert seen["items"] == 40 and seen["expand"] is True


def test_mcp_expand_reaches_the_read_only_when_asked(monkeypatch):
    seen: dict = {}

    def fake_read_pages(url, pages, **kw):
        seen.update(kw)
        return [
            unlocker.FetchResult(
                "curl_cffi", "## Results\n\n- **[a title](https://x.test/a)**", 200, final_url=url
            )
        ]

    monkeypatch.setattr(unlocker, "read_pages", fake_read_pages)
    mcp_server.read_url(THREAD, expand=True)
    assert seen["expand"] is True
    seen.clear()
    mcp_server.read_url(THREAD)
    assert "expand" not in seen


def test_mcp_items_uses_the_reddit_cursor(monkeypatch):
    pages = [
        unlocker.FetchResult(
            "stealth-browser",
            "- **first post** (/u/a, 2 comments, 5 pts)"
            "\n  [`permalink`](https://www.reddit.com/r/a/comments/1/x/)",
            200,
            final_url=LISTING,
            next_url="https://www.reddit.com/svc/shreddit/community-more-posts/hot/?after=z",
            more=[{"kind": "next-page", "note": "[more: another batch]"}],
            index_keys=["t3_1"],
        ),
        unlocker.FetchResult(
            "curl_cffi",
            "- **second post** (/u/b, 1 comment, 3 pts)"
            "\n  [`permalink`](https://www.reddit.com/r/a/comments/2/y/)",
            200,
            final_url="https://www.reddit.com/svc/shreddit/community-more-posts/hot/?after=z",
            index_keys=["t3_2"],
        ),
    ]
    monkeypatch.setattr(unlocker, "read_items", lambda url, n, **kw: pages)
    out = json.loads(mcp_server.read_url(LISTING, max_items=5))
    assert "first post" in out["text"]
    # The cursor stays inside the fenced text, and ``more`` says what it is.
    assert out.get("next_url") is None
    assert any(m["kind"] == "next-page" for m in out["more"])


def test_the_mcp_description_names_the_three_intent_knobs():
    from searchts.integrations.mcp_server import READ_URL_DESCRIPTION

    for name in ("max_pages", "max_items", "expand"):
        assert name in READ_URL_DESCRIPTION
    assert "off by default" in READ_URL_DESCRIPTION
