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
    Case(
        "python-docs",
        "https://docs.python.org/3/library/json.html",
        "open",
        "Python stdlib docs; server-rendered HTML",
    ),
    Case(
        "httpbin-html",
        "https://httpbin.org/html",
        "open",
        "public HTML fixture endpoint; always available",
    ),
    # AI-chat share links: SPAs whose conversation is invisible to generic HTML
    # extraction; read via the tier-0 share extractors. Public, owner-shared
    # conversations chosen for innocuous content.
    Case(
        "chatgpt-share",
        "https://chatgpt.com/share/67a4266c-dbcc-800f-9b92-f0a8a6480e16",
        "ai-share",
        "public ChatGPT share (turbo-stream extraction)",
    ),
    Case(
        "claude-share",
        "https://claude.ai/share/805ee3e5-eb74-43b6-8036-03615b303f6d",
        "ai-share",
        "public Claude share (keyless snapshot API behind Cloudflare)",
    ),
    Case(
        "gemini-share",
        "https://gemini.google.com/share/6d141b742a13",
        "ai-share",
        "public Gemini share (keyless batchexecute RPC)",
    ),
    Case(
        "grok-share",
        "https://grok.com/share/bGVnYWN5_b8625806-94b3-4886-bc4c-0e559a77139e",
        "ai-share",
        "public Grok share (keyless share_links API)",
    ),
    Case(
        "poe-share",
        "https://poe.com/s/XBaS4nMuAk8YAWevOFmi",
        "ai-share",
        "public Poe share (__NEXT_DATA__ extraction)",
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
