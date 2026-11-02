# -*- coding: utf-8 -*-
"""#510: a signed token that resumes a scroll read where the last one stopped.

A scroll walk (:mod:`searchts.scroll`) always starts at the top of a feed. To
read further, a caller had to scroll past everything it already had, which
costs time and requests and, on a signed-in feed, looks like bulk scraping.
This module is the missing second half: a token that says "this read stopped
here", so the next walk can start after it.

## What the token carries

- **The page's own pagination cursor**, captured passively from JSON XHR /
  fetch responses the page made while scrolling. Nothing extra is requested to
  get it: the listener reads responses the page already earned.
- **The last-seen row keys**, the same keys :mod:`searchts.scroll` stores rows
  under, bounded to :data:`TAIL_KEYS` so a token stays small.
- **The URL position** when the URL carries one (``after=``, ``page=``,
  ``offset=``, ``cursor=``, and the numbered ``p=`` some lists use).
- The URL fingerprint, the issue time, and a version.

## Why it is signed

Same rule as :mod:`searchts.paging`: a token found in page text must be inert.
A page that could mint one could choose the agent's next request, and a token
that is replayed against a different URL is refused rather than silently
resuming the wrong list. The signature is HMAC-SHA256 over the payload, the
same construction paging uses. The key is not paging's per-process key: a
resume token is handed to a later ``searchts read``, and a key that dies with
the process would make the 24 h expiry a refusal of every real resume. The
key lives in the user's searchts directory, so a token from another machine
still does not verify.

## Why it expires

A cursor is a claim about a list that was true when it was issued. After a day
a front page has moved far enough that "continue after this row" is a guess.
:data:`TOKEN_TTL_SECONDS` is 24 h; an expired token is refused with a sentence
that says to read the URL again, not resumed at an offset that no longer means
what it did.

## Nothing here makes a request

:class:`Capture` only listens. Replaying a captured cursor is the scroll
module's job, and it does so once, in the page, against the same host, only
when the page's own request shape makes the replay meaningful.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from searchts import paging

__all__ = [
    "Capture",
    "ResumeError",
    "ResumeState",
    "TAIL_KEYS",
    "TOKEN_TTL_SECONDS",
    "TOKEN_VERSION",
    "mint",
    "next_position",
    "read",
    "replay_request",
    "url_at_position",
    "url_position",
]


#: Rows remembered in a token. A short tail is enough to recognise the seam
#: and keeps the token small enough to print in a note.
TAIL_KEYS = 20

#: A cursor is a claim about a list that was true when it was issued. A live
#: front page moves; after a day the claim is a guess.
TOKEN_TTL_SECONDS = 24 * 60 * 60

#: Bumped when the payload shape changes. An unknown version is refused, never
#: guessed at, because guessing at a cursor resumes the wrong window.
TOKEN_VERSION = 1

#: Query parameters that position a list. Ordered by how explicit they are;
#: the first one a URL carries is the one reported.
POSITION_PARAMS = ("after", "cursor", "page", "offset", "p", "next", "start")

#: Positions that are a page number, where "+1" is the next page.
_BUMPABLE_POSITIONS = ("page", "p", "start")


class ResumeError(paging.CursorError):
    """The token was malformed, tampered with, expired, or fits another URL."""


@dataclass(frozen=True)
class ResumeState:
    """What a verified token says the previous walk stopped after."""

    #: Row keys from the tail of the previous read, oldest first.
    keys: Tuple[str, ...] = ()
    #: The page's own pagination cursor, when one was captured.
    cursor: str = ""
    #: The data request that produced ``cursor``, as ``{u, m, b, f}``.
    replay: Optional[Dict[str, str]] = None
    #: ``(name, value)`` of the next page position in the URL, when known.
    position: Optional[Tuple[str, str]] = None
    #: When the token was issued (epoch seconds).
    issued: int = 0


# ── signing ──────────────────────────────────────────────────────────────────

def _fingerprint(url: str) -> str:
    """Identity of the feed: scheme, host, path, and non-position query.

    Position parameters are dropped on purpose. The token is issued for the
    feed, and a resumed read may be opened at ``?page=2``; refusing that would
    make the URL-position method impossible. Everything else has to match.
    """
    parts = urlsplit((url or "").strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in POSITION_PARAMS
    ]
    path = parts.path.rstrip("/") or "/"
    body = f"{parts.scheme.lower()}://{parts.netloc.lower()}{path}?{urlencode(query)}"
    return hashlib.sha256(body.encode()).hexdigest()[:16]


#: Last-resort key when the user's directory cannot be written. A token
#: minted with it only verifies in this process, which the note still says.
_PROCESS_KEY = os.urandom(32)
_KEY: Optional[bytes] = None


def _binary_flag() -> int:
    """``O_BINARY`` where the OS has a text mode, else 0.

    Windows ``os.open`` translates ``\\n`` to ``\\r\\n`` unless this flag is
    set. The key is random bytes, so that rewrite changes the key the next
    process reads and the token no longer verifies.
    """
    return getattr(os, "O_BINARY", 0)


def _read_key_file(path: Path) -> Optional[bytes]:
    """The 32 key bytes, or None when the file is missing or short."""
    try:
        fd = os.open(str(path), os.O_RDONLY | _binary_flag())
    except OSError:
        return None
    try:
        got = bytearray()
        while len(got) < 32:
            part = os.read(fd, 32 - len(got))
            if not part:
                break
            got.extend(part)
    finally:
        os.close(fd)
    if len(got) < 32:
        return None
    return bytes(got)


def _signing_key() -> bytes:
    """The HMAC key for resume tokens.

    Read from ``~/.searchts/resume.key``, created once. Two CLI processes
    then agree on a token for the 24 h it stays valid. A failure to read or
    write the file falls back to a process key so a read still works; that
    token simply will not survive the process. The file is opened in binary
    mode on every OS: a ``\\n`` byte in the key must be stored unchanged.
    """
    global _KEY
    if _KEY is not None:
        return _KEY
    try:
        from searchts.config import Config

        path = Path(Config.CONFIG_DIR) / "resume.key"
    except Exception:  # noqa: BLE001 - a broken config import still signs
        path = Path.home() / ".searchts" / "resume.key"
    raw = _read_key_file(path)
    if raw is not None:
        _KEY = raw
        return _KEY
    fresh = os.urandom(32)
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(
            str(path),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | _binary_flag(),
            0o600,
        )
        try:
            os.write(fd, fresh)
        finally:
            os.close(fd)
        _KEY = fresh
        return _KEY
    except FileExistsError:
        raw = _read_key_file(path)
        if raw is not None:
            _KEY = raw
            return _KEY
    except OSError:
        pass
    _KEY = _PROCESS_KEY
    return _KEY


def _sign(body: str) -> str:
    return hmac.new(_signing_key(), body.encode(), hashlib.sha256).hexdigest()[:16]


def _b64encode(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"{body}.{_sign(body)}"


def _b64(payload: Dict[str, Any]) -> str:
    return _b64encode(payload)


def _unb64(token: str) -> Dict[str, Any]:
    if not isinstance(token, str) or not token.strip():
        raise ResumeError("resume token is empty")
    body, _, sig = token.strip().partition(".")
    if not sig:
        raise ResumeError("resume token is not valid: cursor is unsigned")
    if not hmac.compare_digest(sig, _sign(body)):
        raise ResumeError("resume token is not valid: cursor signature does not verify")
    pad = "=" * (-len(body) % 4)
    try:
        out = json.loads(base64.urlsafe_b64decode(body + pad))
    except Exception as e:  # noqa: BLE001 - any decode failure is one error
        raise ResumeError(f"resume token is not valid: cursor is not readable: {e}") from e
    if not isinstance(out, dict):
        raise ResumeError("resume token is not valid: cursor is not an object")
    return out


def mint(
    url: str,
    *,
    keys: List[str],
    cursor: str = "",
    replay: Optional[Dict[str, str]] = None,
    position: Optional[Tuple[str, str]] = None,
    now: Optional[float] = None,
) -> str:
    """A signed token resuming a scroll of ``url`` after ``keys``."""
    payload: Dict[str, Any] = {
        "v": TOKEN_VERSION,
        "u": _fingerprint(url),
        "t": int(now if now is not None else time.time()),
        "k": [str(k) for k in list(keys)[-TAIL_KEYS:]],
    }
    if cursor:
        payload["c"] = str(cursor)
    if replay:
        req = {
            "u": str(replay.get("u") or ""),
            "m": str(replay.get("m") or "GET").upper(),
            "b": str(replay.get("b") or ""),
            "f": str(replay.get("f") or ""),
        }
        if req["u"]:
            payload["r"] = req
    if position:
        payload["p"] = [str(position[0]), str(position[1])]
    return _b64(payload)


def read(url: str, token: str, *, now: Optional[float] = None) -> ResumeState:
    """Verify ``token`` for ``url``, or raise :class:`ResumeError`."""
    data = _unb64(token)
    version = data.get("v")
    if version != TOKEN_VERSION:
        raise ResumeError(
            f"resume token version {version!r} is not supported; read the URL "
            "again without it"
        )
    if not {"u", "t", "k"} <= set(data):
        raise ResumeError("resume token is missing fields")
    issued = data.get("t")
    if not isinstance(issued, int) or isinstance(issued, bool):
        raise ResumeError("resume token has no issue time")
    current = float(now if now is not None else time.time())
    if current - issued > TOKEN_TTL_SECONDS:
        raise ResumeError(
            "resume token expired (older than 24 h); read the URL again without it"
        )
    if issued - current > 300:
        # A token from the future cannot be one this process issued; refusing
        # it is cheaper than reasoning about a clock we do not own.
        raise ResumeError("resume token is dated in the future; read the URL again")
    if data.get("u") != _fingerprint(url):
        raise ResumeError(
            "resume token was issued for a different URL; read that URL, or "
            "start a fresh read of this one"
        )
    raw_keys = data.get("k")
    if not isinstance(raw_keys, list) or not all(isinstance(k, str) for k in raw_keys):
        raise ResumeError("resume token row keys are not a list of strings")
    cursor = data.get("c")
    if cursor is not None and not isinstance(cursor, str):
        raise ResumeError("resume token cursor is not a string")
    replay = None
    raw_replay = data.get("r")
    if raw_replay is not None:
        if not isinstance(raw_replay, dict):
            raise ResumeError("resume token request is not an object")
        replay = {
            "u": str(raw_replay.get("u") or ""),
            "m": str(raw_replay.get("m") or "GET").upper(),
            "b": str(raw_replay.get("b") or ""),
            "f": str(raw_replay.get("f") or ""),
        }
        if not replay["u"] or not replay["f"]:
            replay = None
    position = None
    raw_position = data.get("p")
    if isinstance(raw_position, list) and len(raw_position) == 2:
        name, value = str(raw_position[0]), str(raw_position[1])
        if name and value:
            position = (name, value)
    return ResumeState(
        keys=tuple(raw_keys[-TAIL_KEYS:]),
        cursor=str(cursor or ""),
        replay=replay,
        position=position,
        issued=issued,
    )


# ── URL positions ────────────────────────────────────────────────────────────

def url_position(url: str) -> Optional[Tuple[str, str]]:
    """The first list-position parameter ``url`` carries, or ``None``."""
    try:
        pairs = parse_qsl(urlsplit(url or "").query, keep_blank_values=True)
    except Exception:  # noqa: BLE001 - a URL we cannot parse has no position
        return None
    low = {k.lower(): (k, v) for k, v in pairs}
    for name in POSITION_PARAMS:
        if name in low:
            key, value = low[name]
            if str(value).strip():
                return key, str(value)
    return None


def next_position(url: str, next_url: Optional[str] = None) -> Optional[Tuple[str, str]]:
    """Where the next read should start, from this URL or the page's next link.

    ``next_url`` wins because the page said where its own next page is. Without
    it, a URL that carries a numeric position is bumped by one. A cursor-like
    value (``after=``, ``cursor=``) is not bumped: appending ``+1`` to an opaque
    string is fiction. That case is what the captured cursor is for.
    """
    if next_url:
        found = url_position(next_url)
        if found is not None:
            return found
    found = url_position(url)
    if found is None:
        return None
    name, value = found
    # Only a page number is safe to add one to. ``offset`` is a stride whose
    # length this code does not know, and ``after`` / ``cursor`` / ``next`` are
    # opaque: adding one to either would silently read the wrong window.
    if name.lower() not in _BUMPABLE_POSITIONS:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return name, str(number + 1)


def url_at_position(url: str, position: Tuple[str, str]) -> str:
    """``url`` with its position parameter set to ``position``."""
    name, value = position
    parts = urlsplit(url or "")
    pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() != name.lower()
    ]
    pairs.append((name, value))
    return urlunsplit(parts._replace(query=urlencode(pairs), fragment=""))


# ── passive capture ──────────────────────────────────────────────────────────

_CURSOR_KEYS = (
    "endcursor",
    "end_cursor",
    "nextcursor",
    "next_cursor",
    "nextpagetoken",
    "next_page_token",
    "pagetoken",
    "page_token",
    "cursor",
    "after",
)


def _rank(key: str) -> Optional[int]:
    low = key.lower()
    if low in ("endcursor", "end_cursor"):
        return 0
    if low in ("nextcursor", "next_cursor", "nextpagetoken", "next_page_token"):
        return 1
    if low in ("pagetoken", "page_token"):
        return 2
    if low == "cursor":
        return 3
    if low == "after":
        return 4
    return None


def find_cursor(data: Any) -> Optional[Tuple[str, str]]:
    """``(value, field)`` of the best pagination cursor in ``data``, or None.

    Best means the most explicit name: ``endCursor`` wins over a plain
    ``cursor``, which wins over ``after``. The walk is bounded in depth and in
    nodes so a huge JSON body cannot make a read slow.
    """
    best: Optional[Tuple[int, str, str]] = None
    seen = 0

    def walk(node: Any, depth: int) -> None:
        nonlocal best, seen
        if depth > 6 or seen > 400:
            return
        seen += 1
        if isinstance(node, dict):
            for key, value in node.items():
                rank = _rank(str(key))
                if (
                    rank is not None
                    and isinstance(value, (str, int))
                    and not isinstance(value, bool)
                    and str(value).strip()
                    and len(str(value)) <= 512
                ):
                    if best is None or rank < best[0]:
                        best = (rank, str(value), str(key))
                if isinstance(value, (dict, list)):
                    walk(value, depth + 1)
        elif isinstance(node, list):
            for item in node[:50]:
                walk(item, depth + 1)

    walk(data, 0)
    if best is None:
        return None
    return best[1], best[2]


def same_site(a: str, b: str) -> bool:
    """True when both URLs name the same host (or a subdomain of it)."""
    try:
        host_a = (urlsplit(a).hostname or "").lower()
        host_b = (urlsplit(b).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return False
    if not host_a or not host_b:
        return False
    return (
        host_a == host_b
        or host_a.endswith("." + host_b)
        or host_b.endswith("." + host_a)
    )


class Capture:
    """A Playwright ``page.on("response", ...)`` listener, and nothing more.

    Bodies are not read in the event handler. A sync Playwright handler runs
    while the driver is dispatching; parsing a body there is the kind of
    re-entry that hangs a read. The handler only keeps the lightweight
    ``(response, request)`` pair, and :meth:`drain` reads the bodies from the
    loop's own thread between steps.
    """

    def __init__(self, page_url: str, limit: int = 20) -> None:
        self.host = (urlsplit(page_url or "").hostname or "").lower()
        self.limit = max(1, int(limit))
        self.pending: List[Tuple[Any, Any]] = []
        #: The last cursor seen, and the field it came from.
        self.cursor = ""
        self.field = ""
        #: The request that produced ``cursor``, replayed only if it can be.
        self.replay: Optional[Dict[str, str]] = None
        #: A same-site data response said 429. #509 territory, kept here only
        #: because this is where the response is already in hand.
        self.rate_limited = False
        self.rate_url = ""

    def __call__(self, response: Any) -> None:
        try:
            request = getattr(response, "request", None)
            url = str(getattr(response, "url", "") or "")
            if not same_site(url, "https://" + self.host):
                return
            kind = str(getattr(request, "resource_type", "") or "")
            if kind not in ("xhr", "fetch"):
                return
            if getattr(response, "status", None) == 429:
                self.rate_limited = True
                self.rate_url = url
                return
            headers = getattr(response, "headers", None) or {}
            ctype = str(headers.get("content-type", "")).lower()
            if "json" not in ctype:
                return
            self.pending.append((response, request))
            if len(self.pending) > self.limit:
                self.pending = self.pending[-self.limit:]
        except Exception:  # noqa: BLE001 - a listener never breaks a read
            return

    def drain(self) -> None:
        """Read the JSON bodies captured so far and keep the best cursor."""
        pending, self.pending = self.pending, []
        for response, request in pending:
            try:
                data = response.json()
            except Exception:  # noqa: BLE001 - a body may be gone or not JSON
                continue
            found = find_cursor(data)
            if found is None:
                continue
            value, field = found
            if not value:
                continue
            self.cursor = value
            self.field = field
            self.replay = {
                "u": str(getattr(request, "url", "") or getattr(response, "url", "") or ""),
                "m": str(getattr(request, "method", "") or "GET").upper(),
                "b": str(getattr(request, "post_data", "") or ""),
                "f": field,
            }


def replay_request(state: ResumeState) -> Optional[Dict[str, str]]:
    """The captured request with its cursor moved to the captured value.

    Returns ``None`` when there is nothing to replay, or when the request is
    not on the token's own host. The caller still checks the host against the
    live page before evaluating the fetch.
    """
    if not state.replay or not state.cursor:
        return None
    url = state.replay.get("u") or ""
    field = state.replay.get("f") or ""
    if not url or not field:
        return None
    method = (state.replay.get("m") or "GET").upper()
    body = state.replay.get("b") or ""
    if body:
        try:
            import json

            data = json.loads(body)
        except Exception:  # noqa: BLE001 - a body that is not JSON is left as is
            data = None
        if data is not None and _set_field(data, field, state.cursor):
            body = json.dumps(data, separators=(",", ":"))
            return {"u": url, "m": method, "b": body}
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    found = False
    moved: List[Tuple[str, str]] = []
    for key, value in pairs:
        if key.lower() == field.lower():
            moved.append((key, state.cursor))
            found = True
        else:
            moved.append((key, value))
    if not found:
        moved.append((field, state.cursor))
    return {
        "u": urlunsplit(parts._replace(query=urlencode(moved))),
        "m": method,
        "b": body,
    }


def _set_field(node: Any, field: str, value: str, depth: int = 0) -> bool:
    """Replace the first ``field`` in a decoded JSON body. True when it moved."""
    if depth > 6:
        return False
    if isinstance(node, dict):
        for key in list(node.keys()):
            if str(key).lower() == field.lower() and isinstance(node[key], (str, int)):
                node[key] = value
                return True
        for item in node.values():
            if _set_field(item, field, value, depth + 1):
                return True
    elif isinstance(node, list):
        for item in node[:50]:
            if _set_field(item, field, value, depth + 1):
                return True
    return False
