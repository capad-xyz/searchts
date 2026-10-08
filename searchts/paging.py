"""Server-generated paging cursors for read_url (S1.3).

The problem this solves: the tool description used to say "read ``next_url``
to continue", which hands the next request back to the page. A page that
authors its own follow-up is a page that can steer the agent.

A cursor here is an opaque token the *server* issues and the *server* checks.
The agent cannot construct a valid one, cannot skip past the end, and cannot
point it somewhere else, because the only field that names a destination is a
fingerprint the server recomputes from what it just read.

## Why the fingerprint matters

The cursor carries an offset and a fingerprint of the thing it paginates. The
fingerprint is not a secret and is not meant to be; it is what stops a stale
token from silently paging through a document that has since changed underneath
it. Live front pages move. If BBC has 278 items now and 400 by the time the
cursor comes back, resuming at 40 is not obviously wrong, but resuming at 40
*into a different set of items* is. A mismatch is reported rather than guessed.

## Why it is signed, and what that actually buys

The first version of this file base64-encoded JSON with no signature. Anyone
reading the format could mint a cursor for any offset, so "opaque" was a claim
rather than a property. It is HMAC-signed now against a per-process key.

Being straight about what the signature protects, because the obvious version
of this argument overstates it. A model that can call ``read_url(url)`` can
already read the whole document in one call, so forging a cursor to reach
offset 40 buys **nothing an attacker did not already have**. The signature is
not a security boundary against the agent.

What it does buy is narrower and real:

- The **page** cannot author the next request. A page that emits a URL the
  agent should follow is the actual threat in S1.3, and a signed cursor means a
  token found in page text is inert rather than actionable.
- A **stale** cursor is refused rather than silently mis-resumed, so an agent
  following an old token gets an error instead of an off-by-one page.
- The cursor cannot be **replayed against a different URL**, which is what the
  fingerprint field is for.

None of that stops a model from being persuaded to call ``read_url`` on a URL
the page put in its text. That is a different problem, it is S1.4 (making
untrusted strings a type rather than a convention), and this does not pretend
to solve it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any, Dict, List, Optional

#: Items per page when the caller does not say. Small on purpose: the point is
#: that an agent reads the first page, decides it has what it needs, and stops.
#: A large default would make the cursor the path nobody takes.
DEFAULT_PAGE_ITEMS = 25

#: Hard ceiling on one page, so a caller cannot ask for the whole document and
#: get it back in one response, which is the thing the cursor exists to prevent.
MAX_PAGE_ITEMS = 100


class CursorError(Exception):
    """The cursor was malformed, tampered with, or does not fit this read."""


#: Per-process signing key. Generated at import, never written down, never sent.
#: A cursor therefore cannot outlive the process, which is the point: a page that
#: captured one has nothing to replay once the server restarts.
_KEY = os.urandom(32)


def _sign(body: str) -> str:
    return hmac.new(_KEY, body.encode(), hashlib.sha256).hexdigest()[:16]


def _b64encode(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"{body}.{_sign(body)}"


def _b64decode(token: str) -> Dict[str, Any]:
    body, _, sig = token.partition(".")
    if not sig:
        raise CursorError("cursor is unsigned")
    if not hmac.compare_digest(sig, _sign(body)):
        raise CursorError("cursor signature does not verify")
    pad = "=" * (-len(body) % 4)
    try:
        out = json.loads(base64.urlsafe_b64decode(body + pad))
    except Exception as e:  # noqa: BLE001 - any decode failure is one error
        raise CursorError(f"cursor is not readable: {e}") from e
    if not isinstance(out, dict):
        raise CursorError("cursor is not an object")
    return out


def fingerprint(url: str, items: List[str]) -> str:
    """Identity of the thing being paged: the URL plus how much of it there is.

    Deliberately not a hash of the content. Content changes on every read of a
    live page, so hashing it would invalidate a cursor every time and make the
    feature unusable. Length is the stable part: if the item count has moved,
    the offsets no longer mean what they meant.
    """
    digest = hashlib.sha256(f"{url}\x00{len(items)}".encode())
    return digest.hexdigest()[:16]


def make_cursor(url: str, items: List[str], offset: int) -> str:
    """Opaque token resuming at ``offset`` into ``items``."""
    return _b64encode(
        {"o": int(offset), "f": fingerprint(url, items), "n": len(items)}
    )


def read_cursor(url: str, items: List[str], cursor: str) -> int:
    """Offset named by ``cursor``, or raise :class:`CursorError`.

    Checks, in order: it decodes, it is shaped like a cursor, its fingerprint
    matches this URL and this many items, and its offset is inside the range.
    Every failure is a refusal, because the alternative is paging something the
    caller did not ask to page.
    """
    data = _b64decode(cursor)
    if not {"o", "f", "n"} <= set(data):
        raise CursorError("cursor is missing fields")
    offset, total = data["o"], data["n"]
    if not isinstance(offset, int) or not isinstance(total, int):
        raise CursorError("cursor fields are not integers")
    if total != len(items) or data["f"] != fingerprint(url, items):
        raise CursorError(
            "cursor does not match this page: it was issued for a different "
            "URL or a different number of items. Re-read from the start."
        )
    if not 0 <= offset < len(items):
        raise CursorError(f"cursor offset {offset} is outside 0..{len(items) - 1}")
    return offset


def paginate(
    url: str, items: List[str], cursor: Optional[str], page_items: int
) -> Dict[str, Any]:
    """One page of ``items``, plus the cursor for the next one.

    ``next_cursor`` is ``None`` at the end, which is the only honest signal that
    there is nothing more. There is no URL for the agent to follow because the
    page had no part in choosing one.
    """
    if page_items < 1:
        page_items = DEFAULT_PAGE_ITEMS
    if page_items > MAX_PAGE_ITEMS:
        page_items = MAX_PAGE_ITEMS
    start = read_cursor(url, items, cursor) if cursor else 0
    end = min(start + page_items, len(items))
    chunk = items[start:end]
    has_more = end < len(items)
    return {
        "items": chunk,
        "offset": start,
        "total_items": len(items),
        "has_more": has_more,
        "next_cursor": make_cursor(url, items, end) if has_more else None,
    }