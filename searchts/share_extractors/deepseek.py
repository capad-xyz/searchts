# -*- coding: utf-8 -*-
"""DeepSeek share-link extractor (chat.deepseek.com/share/<id>).

The share page is a hard case for the plain unlocker ladder: ``curl_cffi`` gets
an HTTP **202** anti-bot shell with none of the conversation embedded, and the
real content only appears after the SPA hydrates and its ``ds-virtual-list``
mounts the message rows. So this extractor drives a headless undetected
Chromium (via ``_browser.render``), waits for the first ``ds-message`` to exist,
auto-scrolls the virtual list to force every row to mount, then parses the DOM.

Rendered DOM shape (verified against live pages):

- Every turn is a ``<div class="ds-message …">``.
- A **user** turn's text sits in a plain bubble ``<div>`` inside that message.
- An **assistant** turn wraps its markdown in
  ``<div class="ds-markdown ds-assistant-message-main-content">`` — the presence
  of that class is what distinguishes the two roles, and restricting assistant
  capture to it drops the copy/regenerate toolbar and any reasoning panel.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import List, Optional

from searchts.share_extractors import ShareResult, Turn, _render
from searchts.share_extractors._browser import (
    BLOCK_TAGS,
    VOID_TAGS,
    clean_text,
    has_class,
    render,
)

PATTERN = re.compile(r"^https?://chat\.deepseek\.com/share/([A-Za-z0-9]+)")

#: The conversation hydrated once at least one message bubble exists.
_READY_SELECTOR = "div.ds-message"
#: The virtualized, independently-scrolling message list.
_SCROLL_SELECTOR = "div.ds-virtual-list"

_ASSISTANT_MAIN = "ds-assistant-message-main-content"


class _DeepSeekParser(HTMLParser):
    """Split a rendered DeepSeek page into ordered ``(role, text)`` turns.

    For each ``ds-message`` region we accumulate two texts: the full bubble text
    and, separately, only the text inside the assistant main-content container.
    If the main-content text is non-empty the turn is DeepSeek's; otherwise it is
    the user's and we keep the full bubble.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._depth = 0
        self._skip_depth: Optional[int] = None
        self._stack: List[dict] = []
        self.turns: List[Turn] = []

    def handle_starttag(self, tag, attrs):
        ad = dict(attrs)
        if tag in ("script", "style", "template") and self._skip_depth is None:
            self._skip_depth = self._depth
        if tag in BLOCK_TAGS:
            for msg in self._stack:
                msg["full"].append("\n")
                msg["main"].append("\n")
        if has_class(ad, "ds-message"):
            self._stack.append(
                {"depth": self._depth, "full": [], "main": [], "main_depth": None})
        if has_class(ad, _ASSISTANT_MAIN) and self._stack:
            self._stack[-1]["main_depth"] = self._depth
        if tag not in VOID_TAGS:
            self._depth += 1

    def handle_endtag(self, tag):
        if tag not in VOID_TAGS:
            self._depth -= 1
        if self._skip_depth is not None and self._depth <= self._skip_depth:
            self._skip_depth = None
        for msg in self._stack:
            if msg["main_depth"] is not None and self._depth <= msg["main_depth"]:
                msg["main_depth"] = None  # left the main-content subtree
        while self._stack and self._stack[-1]["depth"] >= self._depth:
            msg = self._stack.pop()
            main = clean_text("".join(msg["main"]))
            full = clean_text("".join(msg["full"]))
            if main:
                self.turns.append(("DeepSeek", main))
            elif full:
                self.turns.append(("User", full))

    def handle_data(self, data):
        if self._skip_depth is not None:
            return
        for msg in self._stack:
            msg["full"].append(data)
            if msg["main_depth"] is not None:
                msg["main"].append(data)


def parse_deepseek_dom(html: str) -> Optional[ShareResult]:
    """Parse a rendered DeepSeek share page into conversation markdown."""
    parser = _DeepSeekParser()
    parser.feed(html)
    turns: List[Turn] = [(role, text) for role, text in parser.turns if text]
    return _render("deepseek", None, turns)


def extract_share(url: str, match: "re.Match[str]") -> Optional[ShareResult]:
    html = render(
        url,
        ready_selector=_READY_SELECTOR,
        scroll_selector=_SCROLL_SELECTOR,
        timeout=60,
    )
    if not html:
        return None
    return parse_deepseek_dom(html)
