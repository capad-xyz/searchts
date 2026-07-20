# -*- coding: utf-8 -*-
"""Shared lazy patchright render helper for browser-render share extractors.

Some providers' share pages are pure JS shells: the raw HTML that ``curl_cffi``
or Jina sees carries an anti-bot stub (DeepSeek returns a 202 shell) or a ~3KB
loader (Copilot) with nothing of the conversation embedded. The only way to get
the text is to run a real browser, let the SPA hydrate, and read the DOM.

This module mirrors ``unlocker._fetch_stealth``'s undetected-Chromium
construction (same user agent, locale, viewport) and adds the two things a
share page needs beyond a plain render:

1. **Auto-scroll** the message container top-to-bottom, repeatedly, until its
   scroll height stops growing — virtualized message lists (DeepSeek, Copilot)
   only mount the rows near the viewport, so a single ``page.content()`` right
   after load captures a fraction of a long conversation.
2. **Expand** any "show more" / "show reasoning" toggles via a provider-supplied
   selector list before the final read.

The whole thing is bounded (~60s wall clock) and the browser is always closed in
a ``finally``. Underscore-prefixed so the package's auto-discovery skips it — it
is a helper, not a provider plugin.
"""

from __future__ import annotations

import re
import time
from html.parser import HTMLParser
from typing import Callable, List, Optional, Sequence, Tuple

# Mirror the unlocker's tier-2 fingerprint exactly (kept in sync by copy, not
# import, so this module has no hard dependency on unlocker internals).
_UA_REAL = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def render(
    url: str,
    ready_selector: str,
    *,
    scroll_selector: Optional[str] = None,
    expand_selectors: Sequence[str] = (),
    timeout: int = 60,
    settle_ms: int = 600,
) -> Optional[str]:
    """Render ``url`` in a headless undetected Chromium and return final HTML.

    Blocks until ``ready_selector`` appears (proof the conversation hydrated),
    then auto-scrolls ``scroll_selector`` (or the window) top-to-bottom until the
    scroll height stabilizes, clicks every element matched by ``expand_selectors``
    to unfold collapsed content, and returns ``page.content()``.

    Returns ``None`` if patchright is unavailable or the ready selector never
    shows up within the time budget. Never raises for the ordinary
    "page didn't load" cases; the caller treats ``None`` as a fall-through.

    The total wall-clock cost is bounded by ``timeout`` seconds.
    """
    try:
        from patchright.sync_api import TimeoutError as PWTimeout
        from patchright.sync_api import sync_playwright
    except ImportError:  # pragma: no cover - environment dependent
        return None

    deadline = time.monotonic() + timeout
    ms = timeout * 1000

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(
                user_agent=_UA_REAL, locale="en-US",
                viewport={"width": 1280, "height": 800},
            )
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=ms)
            except PWTimeout:
                return None

            # Wait for the conversation to hydrate.
            try:
                remaining = max(1, int((deadline - time.monotonic()) * 1000))
                page.wait_for_selector(ready_selector, timeout=min(ms, remaining))
            except PWTimeout:
                return None

            _auto_scroll(page, scroll_selector, deadline, settle_ms)
            _expand_all(page, expand_selectors, deadline)
            # One more settle + scroll pass after expanding (unfolded content can
            # add height and mount new virtualized rows).
            _auto_scroll(page, scroll_selector, deadline, settle_ms)

            try:
                return page.content()
            except Exception:  # noqa: BLE001 - page may navigate mid-read
                return None
        finally:
            browser.close()


def _scroll_height_js(selector: Optional[str]) -> str:
    if selector:
        return (
            "() => { const el = document.querySelector(%r);"
            " return el ? el.scrollHeight : document.body.scrollHeight; }"
            % selector
        )
    return "() => document.body.scrollHeight"


def _scroll_step_js(selector: Optional[str]) -> str:
    if selector:
        return (
            "() => { const el = document.querySelector(%r);"
            " if (el) { el.scrollTop = el.scrollHeight; }"
            " else { window.scrollTo(0, document.body.scrollHeight); } }"
            % selector
        )
    return "() => window.scrollTo(0, document.body.scrollHeight)"


def _auto_scroll(page, scroll_selector: Optional[str], deadline: float,
                 settle_ms: int) -> None:
    """Scroll the container to the bottom repeatedly until height stabilizes."""
    height_js = _scroll_height_js(scroll_selector)
    step_js = _scroll_step_js(scroll_selector)
    last_height = -1
    stable_rounds = 0
    # Cap iterations so a page that keeps lazily growing can't run forever; the
    # deadline is the real guard.
    for _ in range(60):
        if time.monotonic() >= deadline:
            break
        try:
            page.evaluate(step_js)
        except Exception:  # noqa: BLE001
            break
        page.wait_for_timeout(settle_ms)
        try:
            height = page.evaluate(height_js)
        except Exception:  # noqa: BLE001
            break
        if height == last_height:
            stable_rounds += 1
            if stable_rounds >= 2:  # two consecutive no-growth rounds = done
                break
        else:
            stable_rounds = 0
            last_height = height
    # Return to the top so nothing stays scrolled out of a captured viewport
    # (content() reads the DOM, not the viewport, but this keeps state sane).
    try:
        if scroll_selector:
            page.evaluate(
                "() => { const el = document.querySelector(%r);"
                " if (el) el.scrollTop = 0; }" % scroll_selector)
        else:
            page.evaluate("() => window.scrollTo(0, 0)")
    except Exception:  # noqa: BLE001
        pass


def _expand_all(page, expand_selectors: Sequence[str], deadline: float) -> None:
    """Click every element matching each expand selector (best-effort)."""
    for selector in expand_selectors:
        if time.monotonic() >= deadline:
            break
        try:
            handles = page.query_selector_all(selector)
        except Exception:  # noqa: BLE001
            continue
        for h in handles:
            if time.monotonic() >= deadline:
                break
            try:
                h.click(timeout=1500)
                page.wait_for_timeout(150)
            except Exception:  # noqa: BLE001 - toggle may be off-screen/detached
                continue


# ── shared, network-free DOM-text helpers ────────────────────────────────────
#
# These are pure functions over an HTML string so the provider modules can keep
# their ``parse_<provider>_dom`` logic importable and unit-testable without ever
# launching a browser.

#: Tags that never open a container we need to close (self-closing / leaf), so
#: they must not perturb the depth counter used to delimit message regions. SVG
#: internals are lumped in because rendered pages are riddled with inline icons.
VOID_TAGS = frozenset({
    "br", "img", "hr", "input", "meta", "link", "source", "area", "base",
    "col", "embed", "param", "track", "wbr",
    "path", "circle", "rect", "svg", "use", "g", "line", "polyline", "polygon",
    "defs", "stop", "clippath", "lineargradient", "ellipse", "mask",
})

#: Block-level tags whose boundaries should become whitespace so words from
#: adjacent paragraphs / list items don't get glued together.
BLOCK_TAGS = frozenset({
    "p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote",
    "pre", "ul", "ol", "section", "article", "br", "table", "thead", "tbody",
    "figure", "figcaption",
})


def clean_text(text: str) -> str:
    """Collapse runs of spaces/blank lines from naive tag-boundary joining."""
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


#: ``classify(tag, attrs) -> role`` opens a capture region when it returns a
#: truthy role string; the empty string opens a region that is collected but
#: dropped (used to swallow a duplicate). ``None`` opens nothing.
Classifier = Callable[[str, dict], Optional[str]]


class _TurnCollector(HTMLParser):
    """Collect the text of every element a classifier accepts, in DOM order.

    Regions are delimited purely by tag nesting depth, so a message container
    and everything inside it is captured until its matching close tag. Text from
    ``<script>``/``<style>``/``<template>`` subtrees is ignored.
    """

    def __init__(self, classify: Classifier):
        super().__init__(convert_charrefs=True)
        self._classify = classify
        self._depth = 0
        self._skip_depth: Optional[int] = None
        self._active: List[dict] = []
        self.turns: List[Tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs):
        if tag in ("script", "style", "template") and self._skip_depth is None:
            self._skip_depth = self._depth
        if tag in BLOCK_TAGS:
            for region in self._active:
                region["parts"].append("\n")
        role = self._classify(tag, dict(attrs))
        if role is not None:
            self._active.append({"depth": self._depth, "role": role, "parts": []})
        if tag not in VOID_TAGS:
            self._depth += 1

    def handle_startendtag(self, tag: str, attrs):
        # Self-closing element: emit a block separator but never change depth and
        # never open a lasting region (it has no children to capture).
        if tag in BLOCK_TAGS:
            for region in self._active:
                region["parts"].append("\n")

    def handle_endtag(self, tag: str):
        if tag not in VOID_TAGS:
            self._depth -= 1
        if self._skip_depth is not None and self._depth <= self._skip_depth:
            self._skip_depth = None
        while self._active and self._active[-1]["depth"] >= self._depth:
            region = self._active.pop()
            if region["role"]:  # empty role => intentionally dropped duplicate
                text = clean_text("".join(region["parts"]))
                if text:
                    self.turns.append((region["role"], text))

    def handle_data(self, data: str):
        if self._skip_depth is not None:
            return
        for region in self._active:
            region["parts"].append(data)


def collect_turns(html: str, classify: Classifier) -> List[Tuple[str, str]]:
    """Return ``(role, text)`` turns for every region ``classify`` opens.

    ``classify(tag, attrs)`` receives each start tag and its attribute dict and
    returns the role label for a new message region, ``""`` to capture-and-drop
    a region (e.g. a duplicated node), or ``None`` to ignore the tag. A stateful
    callable (closure/instance) can therefore dedupe by id or alternate roles.
    """
    collector = _TurnCollector(classify)
    collector.feed(html)
    return collector.turns


def attr(attrs: dict, name: str) -> str:
    """Convenience: attribute value as a string ('' when absent)."""
    return attrs.get(name) or ""


def has_class(attrs: dict, token: str) -> bool:
    """True if the element's ``class`` attribute contains ``token`` verbatim."""
    return token in attr(attrs, "class").split()
