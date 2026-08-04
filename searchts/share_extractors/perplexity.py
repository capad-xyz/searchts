# -*- coding: utf-8 -*-
"""Perplexity share/result extractor (perplexity.ai/search/<slug>).

A public Perplexity result page is a JS shell — the raw HTML the unlocker ladder
sees carries no answer text; the thread is rendered client-side. This extractor
renders the page in a headless undetected Chromium, waits for the answer body to
mount, auto-scrolls to pull in follow-up turns, then parses the DOM.

Rendered DOM shape (verified against live pages):

- Each question is a ``<div class="group/query …">`` heading.
- Each answer is a ``<div id="markdown-content-N">`` wrapping a
  ``<div class="prose …">``. Perplexity mounts each answer container **twice**
  (a measuring/visible pair), so answers are de-duplicated by their ``id``.

The first query doubles as the conversation title.
"""

from __future__ import annotations

import re
from typing import List, Optional

from searchts.share_extractors import ShareResult, Turn, _render
from searchts.share_extractors._browser import attr, collect_turns, has_class, render

#: Threads live at ``/search/``; a published Page is the same rendered shape at
#: ``/page/``. The trailing id uses ``.`` and ``_`` (never ``-``, which is the
#: slug separator), so a class without them captures only the slug — harmless
#: while ``extract_share`` renders the whole URL and ignores the group, but a
#: trap for anyone who later reaches for it.
#:
#: ``/spaces/`` (formerly ``/collections/``, which now 301s there) is
#: deliberately excluded: Spaces are restricted by default, and matching them
#: would spend a 60s headless render on a page that is usually private anyway.
PATTERN = re.compile(
    r"^https?://(?:www\.)?perplexity\.ai/(?:search|page)/([A-Za-z0-9._-]+)")

#: A ``.prose`` answer body means the first turn has hydrated.
_READY_SELECTOR = "div.prose"


class _Classifier:
    """Stateful classifier for ``collect_turns``.

    Queries (``group/query``) are user turns; answer containers
    (``id="markdown-content-N"``) are Perplexity turns, but each id appears twice
    in the DOM, so the second occurrence is captured-and-dropped (role ``""``).
    """

    def __init__(self):
        self._seen_ids: set[str] = set()

    def __call__(self, tag: str, attrs: dict) -> Optional[str]:
        if has_class(attrs, "group/query"):
            return "User"
        element_id = attr(attrs, "id")
        if element_id.startswith("markdown-content-"):
            if element_id in self._seen_ids:
                return ""  # duplicate render of the same answer — drop it
            self._seen_ids.add(element_id)
            return "Perplexity"
        return None


def parse_perplexity_dom(html: str) -> Optional[ShareResult]:
    """Parse a rendered Perplexity result page into conversation markdown."""
    turns: List[Turn] = collect_turns(html, _Classifier())
    if not turns:
        return None
    title = next((text for role, text in turns if role == "User"), None)
    if title and len(title) > 80:
        title = title[:77].rstrip() + "..."
    return _render("perplexity", title, turns)


def extract_share(url: str, match: "re.Match[str]") -> Optional[ShareResult]:
    html = render(url, ready_selector=_READY_SELECTOR, timeout=60)
    if not html:
        return None
    return parse_perplexity_dom(html)
