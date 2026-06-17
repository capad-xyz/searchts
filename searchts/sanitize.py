# -*- coding: utf-8 -*-
"""Prompt-injection scrubbing for untrusted web content.

Web pages and search-result snippets are *untrusted input*: they can carry
instructions aimed at the agent/model that will read them ("ignore previous
instructions", hidden zero-width text, fake ``<system>`` tags, credential
exfiltration lures, ...). This module neutralizes the obvious vectors before
the text reaches a model, and surfaces human-readable findings for the rest.

Two layers, in increasing aggressiveness:

* :func:`strip_invisibles` — removes zero-width, bidirectional-control, and
  other invisible/control characters. This is content-preserving for any
  legitimate page and is therefore ALWAYS safe to apply (and always applied
  by the integrations).
* :func:`scan` / :func:`scrub` — match a curated list of injection-indicator
  regexes. By default ``scrub`` only REPORTS (so a benign article that quotes
  "ignore previous instructions" as prose is flagged but left intact);
  ``redact=True`` replaces each matched span with a visible marker.

:func:`wrap_untrusted` fences a block of untrusted text with clear delimiters
so a downstream model can tell page content apart from its own instructions.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Tuple

# ── invisible / control character stripping (always safe) ─────────────────────

#: Explicit code points we always remove: zero-width chars and the bidirectional
#: control/override set. These never carry legitimate visible content but are a
#: classic way to hide instructions from a human reviewer while a model still
#: reads them.
_ZERO_WIDTH = (
    "​",  # ZERO WIDTH SPACE
    "‌",  # ZERO WIDTH NON-JOINER
    "‍",  # ZERO WIDTH JOINER
    "﻿",  # ZERO WIDTH NO-BREAK SPACE / BOM
)
_BIDI_CONTROLS = (
    "‪",  # LEFT-TO-RIGHT EMBEDDING
    "‫",  # RIGHT-TO-LEFT EMBEDDING
    "‬",  # POP DIRECTIONAL FORMATTING
    "‭",  # LEFT-TO-RIGHT OVERRIDE
    "‮",  # RIGHT-TO-LEFT OVERRIDE
    "⁦",  # LEFT-TO-RIGHT ISOLATE
    "⁧",  # RIGHT-TO-LEFT ISOLATE
    "⁨",  # FIRST STRONG ISOLATE
    "⁩",  # POP DIRECTIONAL ISOLATE
)

#: Whitespace control chars that are legitimate and must be preserved.
_KEEP_WHITESPACE = frozenset({"\n", "\t"})

_EXPLICIT_STRIP = frozenset(_ZERO_WIDTH + _BIDI_CONTROLS)


def strip_invisibles(text: str) -> str:
    """Remove invisible/control characters; ALWAYS safe to apply.

    Drops zero-width characters (U+200B-200D, U+FEFF), the bidirectional
    control/override set (U+202A-202E, U+2066-2069), and any other Unicode
    ``Cf`` (format) or ``Cc`` (control) character — except normal whitespace
    (``\\n`` and ``\\t``; ``\\r`` is also kept so CRLF line endings survive).

    Returns the cleaned text. Idempotent.
    """
    if not text:
        return text or ""
    out = []
    for ch in text:
        if ch in _KEEP_WHITESPACE or ch == "\r":
            out.append(ch)
            continue
        if ch in _EXPLICIT_STRIP:
            continue
        cat = unicodedata.category(ch)
        if cat in ("Cf", "Cc"):
            continue
        out.append(ch)
    return "".join(out)


def count_invisibles(text: str) -> int:
    """Number of characters :func:`strip_invisibles` would remove from ``text``."""
    if not text:
        return 0
    removed = 0
    for ch in text:
        if ch in _KEEP_WHITESPACE or ch == "\r":
            continue
        if ch in _EXPLICIT_STRIP:
            removed += 1
            continue
        if unicodedata.category(ch) in ("Cf", "Cc"):
            removed += 1
    return removed


# ── injection-indicator patterns ─────────────────────────────────────────────

#: Curated, maintainable list of prompt-injection indicator regexes. All are
#: matched case-insensitively (see :data:`_COMPILED`). Each targets a known
#: vector; keep entries narrow enough to limit false positives but broad enough
#: to catch common phrasings. Add new indicators here.
INJECTION_PATTERNS: Tuple[str, ...] = (
    r"ignore (all )?(the )?(previous|prior|above) instructions",
    r"disregard (the|your|all) (above|previous|system|prior)",
    r"you are now (a|an| )",
    r"new instructions:",
    r"system prompt",
    r"</?(system|assistant|user|im_start|im_end)>",
    r"do not (tell|inform|alert) the (user|human)",
    r"(send|exfiltrate|leak|reveal) (your|the|all) (api[_ ]?key|token|password|secret|credential)",
    r"print your (system prompt|instructions)",
    r"BEGIN (SYSTEM|PROMPT)",
)

#: Compiled once at import; case-insensitive. Paired (source, regex) so findings
#: can name the indicator that matched.
_COMPILED: Tuple[Tuple[str, "re.Pattern[str]"], ...] = tuple(
    (pat, re.compile(pat, re.IGNORECASE)) for pat in INJECTION_PATTERNS
)

#: How much surrounding text to show on either side of a match in a finding.
_SNIPPET_PAD = 30


def _snippet(text: str, start: int, end: int) -> str:
    """A short one-line excerpt around ``text[start:end]`` for a finding."""
    lo = max(0, start - _SNIPPET_PAD)
    hi = min(len(text), end + _SNIPPET_PAD)
    excerpt = text[lo:hi]
    # Collapse whitespace so the finding stays a single readable line.
    excerpt = re.sub(r"\s+", " ", excerpt).strip()
    prefix = "..." if lo > 0 else ""
    suffix = "..." if hi < len(text) else ""
    return f"{prefix}{excerpt}{suffix}"


def scan(text: str) -> List[str]:
    """Return human-readable findings for injection indicators in ``text``.

    Each finding names the matched indicator pattern and shows a short
    surrounding snippet. Returns an empty list when nothing matches. Does not
    modify ``text``.
    """
    if not text:
        return []
    findings: List[str] = []
    for pat, rx in _COMPILED:
        for m in rx.finditer(text):
            findings.append(
                f"injection indicator /{pat}/ matched: \"{_snippet(text, m.start(), m.end())}\""
            )
    return findings


# ── scrub: strip invisibles + scan, optionally redact ─────────────────────────

#: Replacement marker used when ``scrub(redact=True)`` neutralizes a matched span.
REDACTION_MARKER = "[redacted: possible prompt-injection]"


@dataclass
class ScrubResult:
    """Outcome of :func:`scrub`.

    text:
        The processed text. Invisibles are always stripped; injection spans are
        replaced with :data:`REDACTION_MARKER` only when ``redact=True``.
    findings:
        Human-readable findings from :func:`scan` (empty if none). Populated
        regardless of ``redact``.
    invisibles_removed:
        Count of invisible/control characters removed by :func:`strip_invisibles`.
    """

    text: str
    findings: List[str] = field(default_factory=list)
    invisibles_removed: int = 0


def scrub(text: str, *, redact: bool = False) -> ScrubResult:
    """Sanitize untrusted ``text``: always strip invisibles, scan, optionally redact.

    Invisible/control characters are always removed (safe). The cleaned text is
    then scanned for injection indicators. When ``redact=False`` (default) the
    text is returned intact with findings populated; when ``redact=True`` each
    matched injection span is replaced with :data:`REDACTION_MARKER`.
    """
    text = text or ""
    invisibles_removed = count_invisibles(text)
    cleaned = strip_invisibles(text)
    findings = scan(cleaned)

    if not redact:
        return ScrubResult(text=cleaned, findings=findings, invisibles_removed=invisibles_removed)

    # Redact: collect all matched spans, merge overlaps, replace right-to-left so
    # earlier indices stay valid.
    spans: List[Tuple[int, int]] = []
    for _pat, rx in _COMPILED:
        for m in rx.finditer(cleaned):
            spans.append((m.start(), m.end()))
    if not spans:
        return ScrubResult(text=cleaned, findings=findings, invisibles_removed=invisibles_removed)

    spans.sort()
    merged: List[Tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    redacted = cleaned
    for start, end in reversed(merged):
        redacted = redacted[:start] + REDACTION_MARKER + redacted[end:]

    return ScrubResult(text=redacted, findings=findings, invisibles_removed=invisibles_removed)


# ── fencing helper for the MCP layer ──────────────────────────────────────────

_UNTRUSTED_BEGIN = "----- BEGIN UNTRUSTED WEB CONTENT -----"
_UNTRUSTED_END = "----- END UNTRUSTED WEB CONTENT -----"


def wrap_untrusted(text: str) -> str:
    """Fence ``text`` with clear UNTRUSTED-WEB-CONTENT delimiters.

    Helps a downstream model treat the body as data, not instructions. Used by
    the MCP read tool when injection indicators are detected.
    """
    return f"{_UNTRUSTED_BEGIN}\n{text or ''}\n{_UNTRUSTED_END}"
