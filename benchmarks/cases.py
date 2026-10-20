"""The benchmark's page set.

Cases are tagged with a `suite`:

- `smoke`   — public, robots-friendly pages that exercise the ladder. This is
  the committed default set. It is NOT evidence about hard bot-walls.
- `walled`  — real vendors that restrict bots (Reddit hot, LinkedIn login wall,
  a Cloudflare-fronted vendor site, a DataDome-class site, X, Booking). Failures
  here are expected and honest, not a defect.

A walled case passes only when the returned text contains one of its ``expect``
phrases, copied from the real page (PLAN P3.7d). Length alone is not a pass. A
walled case with no ``expect`` cannot pass: add the phrase once a real read of
that page has produced one. Do not write one from memory.

Walled targets you want to keep private can still go in a git-ignored
``benchmarks/cases.local.json`` (extras without a ``suite`` tag default to
``walled``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_KNOWN_FIELDS = {"name", "url", "category", "note", "allow_thin", "suite", "expect"}


@dataclass(frozen=True)
class Case:
    name: str
    url: str
    category: str
    note: str = ""
    allow_thin: bool = False
    suite: str = "smoke"
    # Phrases copied from the real page. Any one in the text is the proof.
    expect: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.expect, str) or not all(isinstance(p, str) and p.strip() for p in self.expect):
            raise ValueError("expect must be a list of non-empty phrases")
        if self.suite not in ("smoke", "walled"):
            raise ValueError(
                f"Invalid suite: {self.suite!r}. Must be \"smoke\" or \"walled\"."
            )


DEFAULT_CASES: list[Case] = [
    Case(
        "example",
        "https://example.com",
        "control",
        "plain static page; short on purpose",
        allow_thin=True,
        suite="smoke",
    ),
    Case("wikipedia", "https://en.wikipedia.org/wiki/Web_scraping", "open", "large open article", suite="smoke"),
    Case(
        "mdn", "https://developer.mozilla.org/en-US/docs/Web/HTTP", "open", "server-rendered docs", suite="smoke"
    ),
    Case("hacker-news", "https://news.ycombinator.com/news", "open", "light server-rendered page", suite="smoke"),
    Case(
        "cloudflare-docs",
        "https://developers.cloudflare.com/",
        "cloudflare-fronted",
        "public docs served behind Cloudflare (open to bots)",
        suite="smoke",
    ),
    Case(
        "python-docs",
        "https://docs.python.org/3/library/json.html",
        "open",
        "Python stdlib docs; server-rendered HTML",
        suite="smoke",
    ),
    Case(
        "httpbin-html",
        "https://httpbin.org/html",
        "open",
        "public HTML fixture endpoint; always available",
        suite="smoke",
    ),
    # AI-chat share links: SPAs whose conversation is invisible to generic HTML
    # extraction; read via the tier-0 share extractors. Public, owner-shared
    # conversations chosen for innocuous content.
    Case(
        "chatgpt-share",
        "https://chatgpt.com/share/67a4266c-dbcc-800f-9b92-f0a8a6480e16",
        "ai-share",
        "public ChatGPT share (turbo-stream extraction)",
        suite="smoke",
    ),
    Case(
        "claude-share",
        "https://claude.ai/share/805ee3e5-eb74-43b6-8036-03615b303f6d",
        "ai-share",
        "public Claude share (keyless snapshot API behind Cloudflare)",
        suite="smoke",
    ),
    Case(
        "gemini-share",
        "https://gemini.google.com/share/6d141b742a13",
        "ai-share",
        "public Gemini share (keyless batchexecute RPC)",
        suite="smoke",
    ),
    Case(
        "grok-share",
        "https://grok.com/share/bGVnYWN5_b8625806-94b3-4886-bc4c-0e559a77139e",
        "ai-share",
        "public Grok share (keyless share_links API)",
        suite="smoke",
    ),
    Case(
        "poe-share",
        "https://poe.com/s/XBaS4nMuAk8YAWevOFmi",
        "ai-share",
        "public Poe share (__NEXT_DATA__ extraction)",
        suite="smoke",
    ),
    # --- Walled suite: real vendors that restrict automated reads ---------------
    # Failures here are expected and honest, not a defect. Keep names stable.
    Case(
        "reddit-hot",
        "https://www.reddit.com/r/MachineLearning/hot/",
        "reddit",
        "public subreddit hot page; Reddit throttles bot reads",
        suite="walled",
        # Source: searchts read of this URL, 2026-10-17: every post links /r/MachineLearning/comments/<id>/.
        expect=("/r/MachineLearning/comments/",),
    ),
    Case(
        "reddit-comments",
        "https://www.reddit.com/r/MachineLearning/comments/5z8110/"
        "d_a_super_harsh_guide_to_machine_learning/",
        "reddit",
        "long-lived public comments thread",
        suite="walled",
        # Source: searchts read of this URL, 2026-10-17: the post title and its first paragraph.
        expect=("A Super Harsh Guide to Machine Learning", "Hastie, Tibshirani"),
    ),
    Case(
        "linkedin-feed",
        "https://www.linkedin.com/feed/",
        "linkedin",
        "login wall; unauthenticated reads are bounced to /uas/login",
        suite="walled",
        # No expect: the signed-out request lands on /uas/login (curl, 2026-10-17), so no feed text
        # was seen. This row cannot pass until a signed-in read gives a phrase.
    ),
    Case(
        "g2-cloudflare",
        "https://www.g2.com/",
        "cloudflare-fronted",
        "Cloudflare-fronted vendor directory; bots get a 403 block page",
        suite="walled",
        # No expect: curl, searchts and WebFetch all got a block page or nothing on 2026-10-17, so the
        # real page was not seen. Add a phrase from a real read.
    ),
    Case(
        "datadome-co",
        "https://datadome.co/",
        "datadome",
        "anti-bot vendor's own site; managed challenge in front of bots",
        suite="walled",
        # Source: searchts read of this URL, 2026-10-20 (curl_cffi, 3,873 chars): the
        # page's own title line and its opening paragraph.
        expect=("Bot Management & Agent Trust Platform", "Assess the intent behind your traffic"),
    ),
    Case(
        "x-home",
        "https://x.com/",
        "twitter",
        "heavy anti-bot JS challenge on the public home timeline",
        suite="walled",
        # Source: curl of https://x.com/ (HTTP 200), 2026-10-17: the signed-out home page.
        expect=("Happening now", "See what's happening"),
    ),
    Case(
        "booking-home",
        "https://www.booking.com/",
        "booking",
        "bot-challenge interstitial (202) in front of the public home page",
        suite="walled",
        # Source: searchts read of this URL, 2026-10-17 (stealth-browser), and curl (HTTP 200).
        expect=("Why Booking.com?", "List your property"),
    ),
]


def load_cases(extra_path: str | None = None, suite: str | None = None) -> list[Case]:
    """Return the default cases plus any from a local JSON file.

    ``suite`` filters the returned cases: ``"smoke"``, ``"walled"``, or ``"all"``
    (same as ``None``) returns all cases; invalid values raise ValueError.

    Extra cases come from ``extra_path`` when given, otherwise an optional,
    git-ignored ``benchmarks/cases.local.json``. The JSON is a list of objects:
    ``{"name": ..., "url": ..., "category": ..., "note": ..., "allow_thin": false,
    "suite": "walled", "expect": ["phrase from the real page"]}`` (``note``,
    ``allow_thin``, ``suite`` and ``expect`` optional). Extras without a ``suite``
    tag default to ``walled``, and a walled extra with no ``expect`` cannot pass.
    """
    if suite is not None and suite not in ("smoke", "walled", "all"):
        raise ValueError(f'Invalid suite: {suite!r}. Must be "smoke", "walled", or "all".')
    cases = list(DEFAULT_CASES)
    path = Path(extra_path) if extra_path else Path(__file__).with_name("cases.local.json")
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data:
            fields = {k: v for k, v in item.items() if k in _KNOWN_FIELDS}
            # extras default to the walled suite unless they tag one
            fields.setdefault("suite", "walled")
            if isinstance(fields.get("expect"), list):
                fields["expect"] = tuple(fields["expect"])
            cases.append(Case(**fields))
    if suite is not None and suite != "all":
        cases = [c for c in cases if c.suite == suite]
    return cases
