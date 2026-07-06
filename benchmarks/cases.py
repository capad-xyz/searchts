"""The benchmark's page set.

The committed list is a conservative, public, robots-friendly baseline — enough to
exercise the ladder and produce a repeatable number. Add tougher targets locally via
a git-ignored ``benchmarks/cases.local.json`` (see ``load_cases``), so we don't ship a
list of third-party sites to hammer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_KNOWN_FIELDS = {"name", "url", "category", "note"}


@dataclass(frozen=True)
class Case:
    name: str
    url: str
    category: str
    note: str = ""


DEFAULT_CASES: list[Case] = [
    Case("example", "https://example.com", "control", "plain static page; should always read"),
    Case("wikipedia", "https://en.wikipedia.org/wiki/Web_scraping", "open", "large open article"),
    Case(
        "mdn", "https://developer.mozilla.org/en-US/docs/Web/HTTP", "open", "server-rendered docs"
    ),
    Case("hacker-news", "https://news.ycombinator.com/news", "open", "light server-rendered page"),
    Case(
        "cloudflare-docs",
        "https://developers.cloudflare.com/",
        "cloudflare-fronted",
        "public docs served behind Cloudflare",
    ),
]


def load_cases(extra_path: str | None = None) -> list[Case]:
    """Return the default cases plus any from a local JSON file.

    Extra cases come from ``extra_path`` when given, otherwise an optional,
    git-ignored ``benchmarks/cases.local.json``. The JSON is a list of objects:
    ``{"name": ..., "url": ..., "category": ..., "note": ...}`` (``note`` optional).
    """
    cases = list(DEFAULT_CASES)
    path = Path(extra_path) if extra_path else Path(__file__).with_name("cases.local.json")
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        cases.extend(Case(**{k: v for k, v in item.items() if k in _KNOWN_FIELDS}) for item in data)
    return cases
