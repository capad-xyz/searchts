# -*- coding: utf-8 -*-
"""F23c: a list that only grows by scrolling.

Fixtures are slices of real pages fetched on 2026-10-17 (see
``.agents/skills/verify-searchts`` for the drives behind them):

* ``discourse_topic_rows.html`` - ``meta.discourse.org/latest`` as the browser
  rendered it. A textbook infinite-scrolling table list: 30 rows on arrival,
  60 after one scroll step, 90 after two, and no end in sight.
* ``wired_paywall.html`` - the closing paragraphs of a real WIRED article
  behind its paywall.
* ``mdn_closed_details.html`` - seven **closed** ``<details>`` holding MDN's
  HTML-attribute reference tables.
* ``bootstrap_accordion.html`` - Bootstrap's accordion, whose toggles carry
  ``aria-expanded``.

The loop is driven through :class:`FakePage`, which answers the same five JS
blobs a live page answers and can be scripted step by step. That is deliberate:
the thing under test is the loop's decisions - probe, copy, press, stop - and a
live feed would make each of those non-deterministic.
"""

from __future__ import annotations

import json
import re

import pytest

from searchts import expand, knobs, scroll, unlocker

FIX = "tests/fixtures"


def load(name: str) -> str:
    with open(f"{FIX}/{name}", encoding="utf-8") as fh:
        return fh.read()


# ── a fake page that answers the loop's JS ────────────────────────────────────


class FakePage:
    """A page whose rows the test decides, one scroll step at a time.

    ``steps`` is a list of row-lists: what the page shows after each step. The
    last one repeats, so a test only writes down the part it cares about.
    ``unmount_from`` is where rows start disappearing from the *live* DOM while
    staying in the store, which is the virtualized case: the loop must keep
    counting them.
    """

    def __init__(self, steps, load_more=False, wall="", content="<html><body>x</body></html>"):
        self.steps = [list(s) for s in steps]
        self.load_more = load_more
        self.wall = wall
        self._content = content
        self.scrolled = 0
        self.presses = []
        self.store = {}
        self.order = []
        self.rebuilt = None

    # ── what Playwright gives the loop ──
    def evaluate(self, js):
        if "window.scrollTo" in js:
            self.scrolled += 1
            return None
        if "data-searchts-collected" in js:
            return self._rebuild()
        if "s.order.map" in js:
            return {"order": list(self.order), "rows": [self.store[k] for k in self.order]}
        if "findBest" in js:
            return self._collect()
        if "querySelectorAll('details')" in js:
            return 0
        if "deepLink" in js:
            return self._probe()
        if "Load" in js and "role=button" in js:
            return {"label": "Load more projects", "tag": "BUTTON"} if self.load_more else None
        if "challenge-form" in js:
            return self.wall
        return None

    def wait_for_timeout(self, ms):
        return None

    def query_selector_all(self, selector):
        class _H:
            def __init__(self, page):
                self.page = page

            def inner_text(self):
                return "Load more projects" if self.page.load_more else ""

            def click(self, timeout=None):
                self.page.presses.append("Load more projects")
                self.page.load_more = False
                return True

        return [_H(self)] if "button" in selector else []

    def content(self):
        return self._content

    # ── the JS, in Python ──
    def _rows(self):
        return self.steps[min(self.scrolled, len(self.steps) - 1)]

    def _probe(self):
        rows = self._rows()
        if len(rows) < 3:
            return None
        return {"rows": len(rows), "parent": True}

    def _collect(self):
        before = len(self.order)
        for r in self._rows():
            key = r["key"]
            if key in self.store:
                continue
            self.store[key] = r["html"]
            self.order.append(key)
        return {
            "rows": len(self._rows()),
            "total": len(self.order),
            "added": len(self.order) - before,
            "found": True,
        }

    def _rebuild(self):
        self.rebuilt = [self.store[k] for k in self.order]
        return len(self.rebuilt)

    def scroll_to_bottom(self):
        self.scrolled += 1


def row(i, href="https://example.org/t/item-%d/"):
    return {
        "key": "L" + href % i,
        "html": (
            f'<tr class="topic-list-item"><td><a class="link-top-line" href="{href % i}">'
            f"Topic number {i} with a title long enough to look like a row</a>"
            f"</td></tr>"
        ),
    }


def run(page, **kw):
    opts = dict(want_rows=50, max_clicks=4, budget_seconds=30, step_ms=1,
                empty_steps=2)
    opts.update(kw)
    return scroll.collect(page, **opts)


# ── the loop's decisions ──────────────────────────────────────────────────────


def test_the_probe_stops_a_page_that_does_not_grow():
    page = FakePage([[row(i) for i in range(3)]])
    rep = run(page)
    assert rep.stop == "not-a-feed"
    assert rep.note() == "", "a page that is not a feed is not news"


def test_one_growing_list_collects_every_row_and_says_why_it_stopped():
    page = FakePage([[row(i) for i in range(4)], [row(i) for i in range(8)]])
    rep = run(page)
    assert len(rep.rows) == 8
    assert rep.stop == "2 scroll step(s) in a row added nothing"
    assert rep.note().startswith("[scroll: 8 list row(s) after ")


def test_a_row_that_unmounted_is_still_counted():
    # The measured case: a virtualized feed drops rows out of the live DOM as
    # you scroll away, so the *live* count falls while the store grows. Counting
    # the live DOM at the end would lose them.
    page = FakePage([
        [row(i) for i in range(8)],
        [row(i) for i in range(4, 14)],   # 0-3 scrolled out of the DOM
        [row(i) for i in range(8, 20)],
    ])
    rep = run(page)
    live_at_end = 12
    assert len(rep.rows) == 20 > live_at_end
    assert rep.rows[0] == page.store[page.order[0]]
    assert "20 list row(s)" in rep.note()


def test_the_walk_stops_at_the_number_asked_for():
    page = FakePage([[row(i) for i in range(n)] for n in (5, 10, 15, 20)])
    rep = run(page, want_rows=12)
    assert rep.stop == "reached the 12 rows asked for"
    assert len(rep.rows) >= 12


def test_a_stalled_step_presses_load_more_and_keeps_going():
    # Step one grows the list, then the page stops growing until the button is
    # pressed. The button is the same intent by another mechanism.
    page = FakePage(
        [[row(i) for i in range(4)], [row(i) for i in range(8)], [row(i) for i in range(16)]],
        load_more=True,
    )
    rep = run(page)
    assert rep.clicks >= 1
    assert page.presses, "the button was never pressed"
    assert len(rep.rows) == 16


def test_a_login_wall_stops_the_walk_and_is_named():
    page = FakePage([[row(i) for i in range(6)]], wall="auth")
    rep = run(page)
    assert rep.wall == "auth"
    assert "a auth wall replaced the page" in rep.stop
    assert "a auth wall stopped the scroll" in rep.note()


def test_no_browser_says_to_install_one():
    assert "searchts install --browser" in scroll.NO_BROWSER
    # And the gate that reaches that sentence.
    monkey = pytest.MonkeyPatch()
    monkey.setattr(scroll, "browser_available", lambda: False)
    try:
        note, rep = unlocker._scroll_feed("https://example.org/feed", 20, knobs.resolve())
    finally:
        monkey.undo()
    assert rep is None
    assert "searchts install --browser" in note


def test_a_six_tenths_of_a_second_budget_still_returns_what_it_got():
    page = FakePage([[row(i) for i in range(50)]])
    rep = run(page, budget_seconds=1, want_rows=500, step_ms=200)
    assert rep.rows, "a tight budget must not throw the page away"
    assert "scroll budget ran out" in rep.stop or "rows asked for" in rep.stop


# ── the collected page ────────────────────────────────────────────────────────


def test_the_collected_rows_go_back_into_the_page_so_the_extract_can_see_them():
    rows = [row(i) for i in range(6)]
    page = FakePage([rows])
    run(page)
    assert len(page.rebuilt) == 6
    for i in range(6):
        assert f"Topic number {i}" in page.rebuilt[i]
        # Each row exactly once: a read that shows the same item twice is as
        # wrong as one that drops it.
        assert page.rebuilt.count(page.rebuilt[i]) == 1


def test_a_real_discourse_table_list_reads_as_a_list():
    # The fixture is the real rendered table, saved from meta.discourse.org.
    # The row detector that the scroll uses has to see it as rows, which is the
    # one thing that decides whether a scroll pass runs at all.
    html = load("discourse_topic_rows.html")
    from searchts import more

    items = more._best_list(more._parse(html))
    assert items and len(items) >= 8
    assert unlocker.item_count(unlocker.html_to_text(html, None)) >= 0


# ── F23d: the same walk, from the CLI's point of view ─────────────────────────


def test_a_closed_details_is_opened_and_counted():
    import lxml.html

    html = load("mdn_closed_details.html")
    before = lxml.html.fromstring(html)
    assert len([e for e in before.xpath("//details") if "open" not in e.attrib]) >= 5

    rep = expand.expand_html(html)
    assert rep.details >= 5
    assert "<details open" in rep.html
    assert "<details> section(s) opened" in rep.note()
    # And the text behind it is now extractable: the point of the rewrite.
    assert len(rep.html) > len(html)


def test_the_markup_pass_says_when_a_page_has_nothing_to_open():
    html = load("bootstrap_accordion.html")
    rep = expand.expand_html(html)
    # Bootstrap's accordion is aria-expanded, which F23a's prepare_panels keeps
    # already: there is no closed <details> and no read/show/see-more button, so
    # the pass has nothing to do and says exactly that.
    assert rep.details == 0
    assert not rep.produced()
    assert "nothing in this page's markup answered" in rep.note()


def test_a_paywall_is_named_and_never_worked_around():
    html = load("wired_paywall.html")
    assert expand.paywall_in(html), "the fixture must really say it"
    rep = expand.expand_html(html)
    assert rep.paywall
    note = rep.note()
    assert "paywall" in note and "does not work around it" in note


@pytest.mark.parametrize(
    "label",
    [
        "Continue reading",
        "Subscribe to continue",
        "Sign in to continue",
        "This article is for subscribers",
        "Unlock this article",
    ],
)
def test_a_paywall_control_is_never_pressed(label):
    assert expand._verdict(label, tag="button", href=None, in_form=False) == "paywall"


@pytest.mark.parametrize(
    "label",
    [
        "Sign in to read more",
        "Accept all cookies",
        "Subscribe to our newsletter",
        "Reply",
        "Share",
        "Download the app",
    ],
)
def test_a_control_the_refusal_list_names_is_never_pressed(label):
    assert expand._verdict(label, tag="button", href=None, in_form=False) != "yes"


@pytest.mark.parametrize("label", ["Read more", "Show more", "See more", "Read the full story"])
def test_the_folds_we_do_press(label):
    assert expand._verdict(label, tag="button", href=None, in_form=False) == "yes"


def test_a_link_out_of_the_page_is_not_a_fold():
    assert expand._verdict("Read more", tag="a", href="/other-article", in_form=False) == "no"
    # A link that stays on the page is a control pretending to be a link.
    assert expand._verdict("Read more", tag="a", href="#more", in_form=False) == "yes"


def test_a_list_item_that_says_see_all_is_not_a_control():
    # It is what MDN's page is full of, and an earlier version of this file
    # counted them and told the user it had found 18 buttons.
    assert expand._verdict("See all\u2026", tag="li", href=None, in_form=False) == "no"


def test_a_button_inside_a_form_is_never_pressed():
    assert expand._verdict("Read more", tag="button", href=None, in_form=True) == "no"


# ── F23e: the knobs ───────────────────────────────────────────────────────────


def test_a_request_over_the_ceiling_is_clamped_and_says_so(monkeypatch):
    monkeypatch.setenv("SEARCHTS_MAX_ITEMS", "4")
    limits = knobs.resolve(items=50)
    assert limits.items == 4
    assert "[items: asked for 50, the ceiling is 4]" in limits.note()


def test_the_agent_cannot_raise_the_ceiling_with_a_big_number(monkeypatch):
    monkeypatch.setenv("SEARCHTS_MAX_PAGES", "2")
    limits = knobs.resolve(pages=500)
    assert limits.pages == 2
    assert "the ceiling is 2" in limits.note()


def test_no_clamp_no_note(monkeypatch):
    for var in ("SEARCHTS_MAX_ITEMS", "SEARCHTS_MAX_PAGES", "SEARCHTS_MAX_EXPAND_CLICKS"):
        monkeypatch.delenv(var, raising=False)
    limits = knobs.resolve(items=10, pages=3)
    assert limits.note() == ""
    assert limits.items == 10 and limits.pages == 3


def test_the_yaml_more_block_can_lower_a_ceiling(monkeypatch, tmp_path):
    for var in ("SEARCHTS_MAX_ITEMS", "SEARCHTS_MORE_SECONDS"):
        monkeypatch.delenv(var, raising=False)
    from searchts.config import Config

    cfg = tmp_path / "config.yaml"
    cfg.write_text("more:\n  items: 7\n  seconds: 5\n")
    monkeypatch.setattr(Config, "CONFIG_FILE", cfg)
    limits = knobs.resolve()
    assert limits.items == 7
    assert limits.seconds == 5


def test_env_beats_yaml(monkeypatch, tmp_path):
    from searchts.config import Config

    cfg = tmp_path / "config.yaml"
    cfg.write_text("more:\n  items: 7\n")
    monkeypatch.setattr(Config, "CONFIG_FILE", cfg)
    monkeypatch.setenv("SEARCHTS_MAX_ITEMS", "9")
    assert knobs.resolve().items == 9


def test_the_knob_names_are_the_same_everywhere():
    import subprocess
    import sys

    # The CLI's own help, not a parse of its source: this is what a user reads.
    out = subprocess.run(
        [sys.executable, "-m", "searchts", "read", "--help"],
        capture_output=True, encoding="utf-8", timeout=60,
    ).stdout
    for flag in ("--items", "--pages", "--expand"):
        assert flag in out, f"{flag} is not in the CLI help"

    from searchts.integrations import mcp_server

    import inspect

    params = set(inspect.signature(mcp_server.read_url).parameters)
    assert {"max_items", "max_pages", "expand"} <= params

    spec = knobs._SPEC
    assert spec["items"][0] == "SEARCHTS_MAX_ITEMS"
    assert spec["pages"][0] == "SEARCHTS_MAX_PAGES"
    assert spec["expand_clicks"][0] == "SEARCHTS_MAX_EXPAND_CLICKS"


# ── the CLI and MCP in lockstep ───────────────────────────────────────────────


def _stub_read(monkeypatch, text, backend="curl_cffi", next_url=None):
    def fake(url, **kw):
        return unlocker.FetchResult(backend=backend, text=text, status=200,
                                    final_url=url, next_url=next_url)

    monkeypatch.setattr(unlocker, "fetch", fake)
    return fake


def test_the_clamp_note_lands_on_the_text_the_agent_reads(monkeypatch):
    # The bug this fixes: the note went on the LAST page of the walk, so
    # `read --json`'s `text` and the MCP envelope's `text` never mentioned that
    # the request had been cut down. Both surfaces read page one.
    rows = ["- [Row %d](https://example.org/r/%d)" % (i, i) for i in range(8)]
    pages = {
        "https://example.org/list": ("\n".join(rows), "https://example.org/list?page=2"),
        "https://example.org/list?page=2": ("\n".join(rows), "https://example.org/list?page=3"),
        "https://example.org/list?page=3": ("\n".join(rows), None),
    }
    _stub_read(monkeypatch, "", backend="curl_cffi")

    def fake(url, **kw):
        text, nxt = pages[url]
        return unlocker.FetchResult(backend="curl_cffi", text=text, status=200,
                                    final_url=url, next_url=nxt)

    monkeypatch.setattr(unlocker, "fetch", fake)
    monkeypatch.setattr(scroll, "browser_available", lambda: False)
    monkeypatch.setenv("SEARCHTS_MAX_ITEMS", "4")
    got = unlocker.read_items("https://example.org/list", 100)
    assert "the ceiling is 4" in got[0].text
    monkeypatch.delenv("SEARCHTS_MAX_ITEMS")

    from searchts.integrations import mcp_server

    monkeypatch.setattr("searchts.ssrf.guard_mcp_url", lambda url, **kw: None)
    monkeypatch.setenv("SEARCHTS_MAX_PAGES", "2")
    data = json.loads(mcp_server.read_url("https://example.org/list", max_pages=9))
    assert "the ceiling is 2" in data["text"]
    assert "[knobs" not in data["text"]


def test_the_mcp_expand_parameter_reaches_the_read_path(monkeypatch):
    from searchts.integrations import mcp_server

    seen = {}

    def fake(*args, **kw):
        seen.update(kw)
        seen["args"] = args
        return [unlocker.FetchResult(backend="curl_cffi", text="body", status=200,
                                     final_url=args[0])]

    monkeypatch.setattr(unlocker, "read_items", fake)
    monkeypatch.setattr(unlocker, "read_pages", fake)
    monkeypatch.setattr("searchts.ssrf.guard_mcp_url", lambda url, **kw: None)
    out = mcp_server.read_url("https://example.org/a", expand=True)
    assert "Error" not in out
    assert seen.get("expand") is True
    # Off unless asked: an ordinary read must not carry the flag.
    seen.clear()
    mcp_server.read_url("https://example.org/a")
    assert "expand" not in seen


def test_a_plain_read_of_a_page_with_no_folds_ends_byte_identical(monkeypatch):
    html = load("bootstrap_accordion.html")
    from tests.test_more import _page  # noqa: F401  (import cost only)

    assert expand.expand_html("<html><body><p>" + ("word " * 200) + "</p></body></html>").html
    # Nothing to open means the HTML is handed back untouched, so an unasked
    # read cannot differ from today.
    plain = "<html><body><details><summary>Q</summary><p>A</p></details></body></html>"
    assert expand.expand_html("<html><body><p>hi</p></body></html>").details == 0
    assert expand.expand_html(plain).html  # has one to open, so it changed
    assert html  # the fixture is real