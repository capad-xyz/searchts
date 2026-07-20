# -*- coding: utf-8 -*-
"""Microsoft Copilot share-link extractor (copilot.microsoft.com/shares/<id>).

The share page is a ~3KB JS shell; ``curl_cffi``/Jina see nothing of the
conversation. This extractor renders it in a headless undetected Chromium and
parses the hydrated DOM.

Rendered DOM shape:

- Each turn is an element with ``role="article"``.
- A **user** turn carries ``class="group/user-message"`` / an id ending
  ``-user-message`` and an sr-only ``<h5 aria-label="You said">You said</h5>``
  heading before its text.
- A **Copilot** turn is the sibling article (sr-only ``Copilot said`` heading),
  holding the answer markdown.

The sr-only "You said" / "Copilot said" headings are stripped from the captured
text so only the message body remains.

Caveat: Copilot gates its share DOM behind bot detection that a headless browser
clears only intermittently — a render frequently returns the bare shell with no
articles. When nothing parses, ``extract_share`` returns ``None`` and the caller
falls through to the normal unlocker ladder. The user-turn structure above is
confirmed from a live render; the assistant-turn structure is inferred from
Copilot's symmetric "You said"/"Copilot said" markup and mirrored in the test
fixture, but was not captured end-to-end live (see the module's tests).
"""

from __future__ import annotations

import re
from typing import List, Optional

from searchts.share_extractors import ShareResult, Turn, _render
from searchts.share_extractors._browser import attr, collect_turns, has_class, render

PATTERN = re.compile(r"^https?://copilot\.microsoft\.com/shares/([A-Za-z0-9_-]+)")

#: The share page mounted its conversation once an article exists.
_READY_SELECTOR = '[role="article"]'

#: sr-only role headings to peel off the front of a captured turn.
_LABEL_RE = re.compile(r"^\s*(?:You said|Copilot said)\s*", re.IGNORECASE)


def _classify(tag: str, attrs: dict) -> Optional[str]:
    if attr(attrs, "role") != "article":
        return None
    element_id = attr(attrs, "id")
    if has_class(attrs, "group/user-message") or element_id.endswith("-user-message"):
        return "User"
    return "Copilot"


def parse_copilot_dom(html: str) -> Optional[ShareResult]:
    """Parse a rendered Copilot share page into conversation markdown."""
    turns: List[Turn] = []
    for role, text in collect_turns(html, _classify):
        text = _LABEL_RE.sub("", text).strip()
        if text:
            turns.append((role, text))
    return _render("copilot", None, turns)


def extract_share(url: str, match: "re.Match[str]") -> Optional[ShareResult]:
    html = render(url, ready_selector=_READY_SELECTOR, timeout=60)
    if not html:
        return None
    return parse_copilot_dom(html)
