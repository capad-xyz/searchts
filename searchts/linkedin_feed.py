# -*- coding: utf-8 -*-
"""#511: the LinkedIn feed, read by the browser that is already signed in.

LinkedIn's feed is not a page that can be fetched: ``/feed/`` answers http-429
to a bare client and a login wall to a fresh browser context. It is also the
one place where the wrong client costs more than a failed read. Copying the
``li_at`` cookie into another client (a different Chrome build, a different
user agent, a headless bundle) is the pattern that gets the session cleared,
sometimes within seconds, and can log out the browser that minted it.

So this module does one thing: it reads the feed in the user's own browser.
A Chromium browser that is already running with remote debugging allowed is
attached, and one new tab is opened for the read (see
:mod:`searchts.linkedin_attach`). Otherwise the user's own Chrome is launched,
headed, on the user's own profile directory, at the feed URL. The page itself
makes its own requests; this module only listens to them (``page.on("response")``)
and reads the DOM. It never calls an API, never pages with a request, and never
touches or copies the cookie store. Everything below is passive.

What comes back is a post list:

* **permalink** from ``urn:li:activity:<id>`` (a response body or the DOM),
  rendered as ``https://www.linkedin.com/feed/update/urn:li:activity:<id>/``;
* **author**, **text** and **relative time as shown** (``2h``, ``1d``), from
  the same passive capture, with the DOM as a fallback and a merge;
* **promoted** when the payload or the card says so.

## Pacing and resume

* :class:`FeedGuard` books the one document load through
  :mod:`searchts.linkedin`: ``current_stop`` before anything opens,
  ``feed_gap_minutes`` between feed reads, and one ``take_load`` for
  ``/feed/`` itself. A scroll step does not book another load. A stop
  signal is ``stop_signal``'s reason, written with ``record_stop``.
* ``resume`` has ``begin()`` and ``advance(cursor, posts)``. ``begin`` may
  return a cursor the previous read already consumed, and ``seen`` may list
  activity ids already returned. The walk drops those and scrolls this same
  page until the page's own responses move on. It never requests the cursor.
  :func:`resume_from_token` builds that hook from :mod:`searchts.resume`.

The browser itself is behind :func:`_browser_page`; :func:`walk` takes an
already-open page, which is what the offline tests drive with a fake.
"""

from __future__ import annotations

import contextlib
import json
import os
import random
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Dict, Iterator, List, Optional, Protocol, Tuple
from urllib.parse import urlparse

__all__ = [
    "FEED_URL",
    "DEFAULT_MAX_POSTS",
    "DEFAULT_MAX_STEPS",
    "DEFAULT_SECONDS",
    "Post",
    "FeedRead",
    "Limits",
    "Guard",
    "FeedGuard",
    "GuardRefused",
    "Resume",
    "NullResume",
    "TokenResume",
    "resume_from_token",
    "FeedUnavailable",
    "activity_id",
    "permalink",
    "detect_signal",
    "parse_capture",
    "parse_html",
    "render",
    "walk",
    "read_feed",
    "profile_path",
    "profile_problem",
    "chrome_executable",
]

FEED_URL = "https://www.linkedin.com/feed/"

#: One bounded scroll per read, as decided in #511: about 25 posts, 8 steps,
#: 90 seconds. Each is a separate stop so the note can name which one ran out.
DEFAULT_MAX_POSTS = 25
DEFAULT_MAX_STEPS = 8
DEFAULT_SECONDS = 90

#: Scroll steps are 2 to 5 seconds apart, jittered. A feed that is stepped
#: faster looks less like a person reading and more like a loop.
STEP_MIN_MS = 2000
STEP_MAX_MS = 5000
#: Time for the next batch to render after a step, before the DOM is copied.
SETTLE_MS = 1500

_UPDATE = "https://www.linkedin.com/feed/update/urn:li:activity:{activity}/"
_ACTIVITY = re.compile(r"urn:li:activity:(\d+)")
_RELATIVE = re.compile(r"\b\d+\s*(?:s|m|h|d|w|mo|y)\b", re.IGNORECASE)

#: ``record_stop`` reason that waits for a person rather than 24 h.
STOP_UNTIL_CLEARED = "restriction"

#: When the home feed was last booked. A time only, beside the load guard,
#: so a feed gap does not rewrite the load stamps ``take_load`` owns.
_FEED_STAMP = "linkedin_feed_at"


# ── the post ────────────────────────────────────────────────────────────────


def activity_id(value: str) -> str:
    """The numeric id inside ``urn:li:activity:<id>``, or ``""``."""
    match = _ACTIVITY.search(value or "")
    return match.group(1) if match else ""


def permalink(activity: str) -> str:
    """The feed permalink for an activity id or urn."""
    aid = activity_id(activity) or (activity or "").strip()
    return _UPDATE.format(activity=aid) if aid else ""


@dataclass
class Post:
    """One feed post, as the page and its own responses described it."""

    activity: str
    author: str = ""
    text: str = ""
    when: str = ""
    promoted: bool = False

    @property
    def permalink(self) -> str:
        return permalink(self.activity)

    def absorb(self, other: "Post") -> None:
        """Fill only what this copy is missing, keeping the first wording."""
        if not self.author and other.author:
            self.author = other.author
        if not self.when and other.when:
            self.when = other.when
        if len(other.text) > len(self.text):
            self.text = other.text
        self.promoted = self.promoted or other.promoted


@dataclass
class Captured:
    """What one passive response body held."""

    posts: List[Post] = field(default_factory=list)
    cursor: str = ""
    signal: str = ""


@dataclass
class Limits:
    """The bounded scroll, in one place so a test can shrink it."""

    max_posts: int = DEFAULT_MAX_POSTS
    max_steps: int = DEFAULT_MAX_STEPS
    max_seconds: int = DEFAULT_SECONDS
    step_min_ms: int = STEP_MIN_MS
    step_max_ms: int = STEP_MAX_MS
    settle_ms: int = SETTLE_MS


# ── stop signals ────────────────────────────────────────────────────────────


def detect_signal(
    text: str = "", *, status: Optional[int] = None, url: str = ""
) -> str:
    """The LinkedIn stop reason, or ``""`` for an ordinary page.

    :func:`searchts.linkedin.stop_signal` is the list of status codes and
    phrases. A feed read is signed in, so a sign-in wall here is a logout
    rather than the public login page.
    """
    from searchts.linkedin import stop_signal

    code = int(status) if status else None
    found = stop_signal(code, text or "", url or "", signed_in=True)
    return found or ""


# ── payload capture (never a request) ───────────────────────────────────────


def _as_text(value: Any) -> str:
    """A display string from a scalar or a small entity-shaped object."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "name", "title", "value"):
            got = _as_text(value.get(key))
            if got:
                return got
    return ""


def _get(node: Any, *path: str) -> Any:
    cur = node
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _index_entities(node: Any, index: Dict[str, Any]) -> None:
    """Map every ``urn:li:...`` entity to its object, for actor lookups."""
    if isinstance(node, dict):
        for key in ("entityUrn", "urn"):
            value = node.get(key)
            if isinstance(value, str) and value.startswith("urn:li:"):
                index.setdefault(value, node)
        for value in node.values():
            _index_entities(value, index)
    elif isinstance(node, list):
        for value in node:
            _index_entities(value, index)


def _node_activity(node: Dict[str, Any]) -> str:
    for key in (
        "entityUrn", "urn", "updateUrn", "activityUrn", "dataUrn",
        "permalink", "url",
    ):
        value = node.get(key)
        if isinstance(value, str):
            aid = activity_id(value)
            if aid:
                return aid
    return ""


def _author(node: Any, index: Dict[str, Any]) -> str:
    paths = (
        ("actor", "name", "text"),
        ("actor", "name"),
        ("actor", "title", "text"),
        ("author", "name", "text"),
        ("author", "name"),
        ("actorTitle",),
        ("authorName",),
        ("owner", "name", "text"),
        ("actor",),
        ("author",),
    )
    for path in paths:
        value = _get(node, *path)
        if isinstance(value, str) and value.startswith("urn:li:"):
            value = index.get(value)
            if isinstance(value, dict):
                value = value.get("name") or value
        got = _as_text(value)
        if got and not got.startswith("urn:li:"):
            return got
    return ""


def _relative_timestamp(value: Any) -> str:
    if isinstance(value, (int, float)) and value > 0:
        seconds = max(1.0, time.time() - (value / 1000.0 if value > 1e11 else value))
        for size, suffix in ((604800, "w"), (86400, "d"), (3600, "h"), (60, "m")):
            if seconds >= size:
                return f"{int(seconds // size)}{suffix}"
        return f"{int(seconds)}s"
    return ""


def _when(node: Any) -> str:
    paths = (
        ("actor", "subDescription", "text"),
        ("actor", "subDescription"),
        ("actor", "description", "text"),
        ("time", "text"),
        ("relativeTime",),
        ("createdAt",),
        ("publishedAt",),
    )
    for path in paths:
        value = _get(node, *path)
        if isinstance(value, (int, float)):
            got = _relative_timestamp(value)
            if got:
                return got
        text = _as_text(value)
        if not text:
            continue
        match = _RELATIVE.search(text)
        if match:
            return match.group(0).replace(" ", "")
        if re.match(r"^\d{4}-\d{2}-\d{2}", text):
            return text[:10]
    return ""


def _post_text(node: Any) -> str:
    for path in (
        ("commentary", "text"),
        ("commentary",),
        ("text",),
        ("body", "text"),
        ("description", "text"),
        ("content", "text"),
    ):
        value = _get(node, *path)
        if isinstance(value, dict):
            value = value.get("text")
        if isinstance(value, str) and value.strip():
            return _clean_text(value)
    return ""


def _promoted(node: Any) -> bool:
    for key in ("promoted", "isPromoted", "sponsored", "isSponsored"):
        if node.get(key) is True:
            return True
    kind = str(node.get("type") or "").strip().lower()
    if kind in ("promoted", "sponsored"):
        return True
    header = _as_text(_get(node, "header", "text")).lower()
    return header.startswith(("promoted", "sponsored"))


def _clean_text(value: str) -> str:
    text = (value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _cursor_in(node: Any) -> str:
    """The page's own next-page token, wherever its envelope put it."""
    found = ""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("paginationToken", "nextPageToken", "nextCursor"):
                if isinstance(value, str) and len(value) > 3:
                    found = value
            got = _cursor_in(value)
            if got:
                found = got
    elif isinstance(node, list):
        for value in node:
            got = _cursor_in(value)
            if got:
                found = got
    return found


def _collect_posts(node: Any, index: Dict[str, Any], out: Dict[str, Post]) -> None:
    if isinstance(node, dict):
        aid = _node_activity(node)
        if aid:
            post = Post(
                activity=aid,
                author=_author(node, index),
                text=_post_text(node),
                when=_when(node),
                promoted=_promoted(node),
            )
            if aid in out:
                out[aid].absorb(post)
            else:
                out[aid] = post
        for value in node.values():
            _collect_posts(value, index, out)
    elif isinstance(node, list):
        for value in node:
            _collect_posts(value, index, out)


def parse_capture(body: str, *, source: str = "") -> Captured:
    """Read one response body the page itself fetched.

    The envelope shapes differ between LinkedIn's own endpoints, so the reader
    does not require one: it indexes every entity by urn, then walks for
    ``urn:li:activity``. Fields are filled from the nearest entity that carries
    them, and the same activity met twice is merged instead of repeated.
    """
    text = (body or "").strip()
    if not text:
        return Captured()
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return Captured(signal=detect_signal(text, url=source))
    index: Dict[str, Any] = {}
    _index_entities(data, index)
    posts: Dict[str, Post] = {}
    _collect_posts(data, index, posts)
    return Captured(
        posts=list(posts.values()),
        cursor=_cursor_in(data),
        signal=detect_signal(_messages_in(data), url=source),
    )


def _messages_in(node: Any) -> str:
    """Only the envelope's own error/notice text, never a post's words.

    A feed post may say "too many pages" for its own reasons; a stop signal is
    read from the envelope's message fields so a post cannot trip the switch.
    """
    found: List[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("message", "error", "errorMessage", "notice",
                       "statusMessage", "detail") and isinstance(value, str):
                found.append(value)
            found.append(_messages_in(value))
    elif isinstance(node, list):
        for value in node:
            found.append(_messages_in(value))
    return " ".join(part for part in found if part)


# ── DOM fallback ────────────────────────────────────────────────────────────


_VOID = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
})


class _CardParser(HTMLParser):
    """Collect the feed cards from a rendered page, by activity urn."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.posts: List[Post] = []
        self._depth = 0
        self._card_depth: Optional[int] = None
        self._activity = ""
        self._buffers: Dict[str, List[str]] = {}
        self._targets: List[Tuple[int, Optional[str]]] = []
        self._target: Optional[str] = None
        self._promoted = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self._depth += 1
        self._open(tag, attrs)
        if tag in _VOID:
            self._close()
            self._depth -= 1
        else:
            self._targets.append((self._depth, self._target))

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self._depth += 1
        self._open(tag, attrs)
        self._close()
        self._depth -= 1

    def handle_endtag(self, tag: str) -> None:
        self._close()
        if self._depth:
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._card_depth is None:
            return
        self._buffers["all"].append(data)
        if self._target:
            self._buffers[self._target].append(data)

    def _open(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attr = {key: (value or "") for key, value in attrs}
        inherited = self._targets[-1][1] if self._targets else None
        self._target = inherited
        if self._card_depth is None:
            urn = (
                attr.get("data-urn")
                or attr.get("data-id")
                or attr.get("data-activity-urn")
                or ""
            )
            aid = activity_id(urn)
            if aid:
                self._card_depth = self._depth
                self._activity = aid
                self._buffers = {"author": [], "when": [], "text": [], "all": []}
                self._promoted = False
                self._target = None
        if self._card_depth is None:
            return
        classes = attr.get("class", "").lower()
        if "promoted" in classes or "sponsored" in classes:
            self._promoted = True
        if "actor__name" in classes or "actor__title" in classes:
            self._target = "author"
        elif tag == "time" or "sub-description" in classes:
            self._target = "when"
        elif (
            "update-components-text" in classes
            or "commentary" in classes
            or "feed-shared-text" in classes
        ):
            self._target = "text"
        elif "header__text" in classes:
            self._target = "text"

    def _close(self) -> None:
        if self._card_depth is None:
            return
        if self._targets:
            depth, _target = self._targets[-1]
            if depth == self._depth:
                self._targets.pop()
        if self._depth == self._card_depth:
            self._finish()

    def _finish(self) -> None:
        author = " ".join(part.strip() for part in self._buffers["author"] if part.strip())
        when = " ".join(part.strip() for part in self._buffers["when"] if part.strip())
        text = _clean_text("".join(self._buffers["text"]))
        if not text:
            fallback = _clean_text("".join(self._buffers["all"]))
            for line in (author, when):
                if line:
                    fallback = fallback.replace(line, "", 1)
            text = _clean_text(fallback)
        if not self._promoted:
            self._promoted = text.lower().startswith(("promoted", "sponsored"))
        if self._promoted:
            text = re.sub(r"^(?:promoted|sponsored)\s*[·:\-]?\s*", "", text, flags=re.I)
        match = _RELATIVE.search(when)
        if match:
            when = match.group(0).replace(" ", "")
        self.posts.append(Post(
            activity=self._activity,
            author=author,
            text=text,
            when=when,
            promoted=self._promoted,
        ))
        card_depth = self._card_depth
        assert card_depth is not None
        self._card_depth = None
        self._activity = ""
        self._buffers = {}
        self._targets = [t for t in self._targets if t[0] < card_depth]


def parse_html(html_text: str) -> List[Post]:
    """Feed cards from the rendered DOM, as a fallback to passive capture."""
    if not html_text:
        return []
    parser = _CardParser()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:  # noqa: BLE001 - a malformed DOM is a fallback, not a read
        return []
    return parser.posts


# ── rendering ───────────────────────────────────────────────────────────────


def render(posts: List[Post], *, stop: str = "", signal: str = "") -> str:
    """One block per post: author, relative time, text, permalink."""
    blocks: List[str] = []
    for post in posts:
        head = post.author or "(author not captured)"
        if post.when:
            head = f"{head} · {post.when}"
        if post.promoted:
            head = f"[promoted] {head}"
        block = [head]
        if post.text:
            block.append(post.text)
        block.append(post.permalink)
        blocks.append("\n".join(block))
    body = "\n\n".join(blocks)
    if not body:
        body = "[linkedin-feed: no posts were read]"
    note = f"[linkedin-feed: {len(posts)} post(s)"
    if stop:
        note += f"; stopped: {stop}"
    if signal:
        note += f"; LinkedIn's {_signal_words(signal)}"
    note += "]"
    return body.rstrip() + "\n\n" + note


def _signal_words(signal: str) -> str:
    return {
        "rate-limit": "rate limit (http-429, http-999, or too many pages)",
        "checkpoint": "checkpoint/challenge page",
        "logout": "forced logout or sign-in wall",
        "restriction": "account restriction notice",
    }.get(signal, signal)


# ── guard and resume seams (#509, #510) ─────────────────────────────────────


class GuardRefused(Exception):
    """The guard said no: a recorded stop or a feed gap is still in force."""


class Guard(Protocol):
    def before_load(self) -> None:
        """Refuse, or pace, before the one page load this read makes."""

    def record(self, signal: str) -> None:
        """Remember a stop signal so the next read refuses."""

    def successful(self) -> None:
        """Remember that feed content came back, if the guard tracks a gap."""


class Resume(Protocol):
    def begin(self) -> Optional[str]:
        """The cursor to continue from, or None to start at the top."""

    def advance(self, cursor: str, posts: List[Post]) -> None:
        """The page returned another cursor; the walk is still in-page."""


class NullResume:
    """The default: no token, no replay. #510 supplies the real one."""

    def begin(self) -> Optional[str]:
        return None

    def advance(self, cursor: str, posts: List[Post]) -> None:
        return None


class TokenResume:
    """A cursor and the activity ids already returned, scrolled in-page.

    Built by :func:`resume_from_token` from a verified #510 token, or by a
    test. ``advance`` remembers the latest cursor the page itself returned so
    a later mint can sign it. Nothing here is sent as a request.
    """

    def __init__(self, cursor: str = "", seen: Optional[List[str]] = None) -> None:
        self.cursor = (cursor or "").strip()
        self._seen = [str(item) for item in (seen or []) if str(item).strip()]
        self.latest = ""

    def begin(self) -> Optional[str]:
        return self.cursor or None

    def seen(self) -> List[str]:
        return list(self._seen)

    def advance(self, cursor: str, posts: List[Post]) -> None:
        if cursor:
            self.latest = cursor


def resume_from_token(url: str, token: str, *, module: Any = None) -> "Resume":
    """The in-page resume hook for a signed token, or :class:`NullResume`.

    An empty token starts at the top. A token that does not verify is a
    named refusal, before any browser starts. The cursor and the activity
    ids inside a verified token are handed to :class:`TokenResume`. The walk
    scrolls this same page. It does not replay the captured request.
    """
    if not (token or "").strip():
        return NullResume()
    from searchts import resume as resume_mod

    mod = resume_mod if module is None else module
    read = getattr(mod, "read", None)
    if not callable(read):
        raise FeedUnavailable(
            "a resume token needs searchts.resume. Read the feed without "
            "the token. The next posts come from scrolling this page."
        )
    try:
        state = read(url, token)
    except resume_mod.ResumeError as exc:
        raise FeedUnavailable(str(exc)) from exc
    except FeedUnavailable:
        raise
    except Exception as exc:
        if type(exc).__name__ == "ResumeError":
            raise FeedUnavailable(str(exc)) from exc
        raise FeedUnavailable(
            f"the resume token was refused ({type(exc).__name__}). Read the "
            "feed without it. No request was sent."
        ) from exc
    keys = getattr(state, "keys", None) or []
    seen = [str(item) for item in keys if str(item).strip()]
    return TokenResume(cursor=str(getattr(state, "cursor", "") or ""), seen=seen)


def _feed_stamp_path() -> str:
    """Where the last feed-read time lives, next to the LinkedIn load guard."""
    from searchts import rate_limit

    return os.path.join(str(rate_limit.state_dir()), _FEED_STAMP)


def _last_feed() -> float:
    try:
        with open(_feed_stamp_path(), encoding="utf-8") as handle:
            return float(handle.read().strip() or 0)
    except (OSError, ValueError):
        return 0.0


def _remember_feed(now: float) -> None:
    path = _feed_stamp_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(repr(float(now)))
    os.replace(tmp, path)


def _cdp_timeout_ms() -> int:
    """Approval dialogs need time for a person to respond (default 60 s)."""
    raw = os.environ.get("SEARCHTS_LINKEDIN_CDP_TIMEOUT_SECONDS", "60")
    try:
        seconds = float(raw)
    except ValueError:
        seconds = 60.0
    if seconds <= 0:
        seconds = 60.0
    return int(max(1.0, min(seconds, 300.0)) * 1000)


def _quiet_target_closed_futures(manager: Any) -> None:
    """Retrieve CDP teardown exceptions that Patchright can leave unobserved."""
    loop = getattr(manager, "_loop", None)
    if loop is None or not hasattr(loop, "set_exception_handler"):
        return
    previous = loop.get_exception_handler()

    def handle(loop: Any, context: Dict[str, Any]) -> None:
        future = context.get("future")
        exc = context.get("exception")
        if exc is None and future is not None:
            with contextlib.suppress(Exception):
                exc = future.exception()
        if exc is not None and _is_target_closed(exc):
            if future is not None and not future.done():
                future.cancel()
            return
        if previous is not None:
            previous(loop, context)
        else:
            loop.default_exception_handler(context)

    loop.set_exception_handler(handle)


def _feed_gap_refusal(now: float, last_feed: float, gap_minutes: int) -> str:
    """The feed-gap sentence, or ``""`` when another feed read is allowed."""
    if not gap_minutes or not last_feed or now - last_feed >= gap_minutes * 60:
        return ""
    wait = int((gap_minutes * 60 - (now - last_feed)) // 60) + 1
    return (
        f"the LinkedIn feed was read {int(now - last_feed)} s ago; feed "
        f"reads are at least {gap_minutes} min apart (about {wait} min "
        "to wait). SEARCHTS_LINKEDIN_FEED_GAP_MINUTES sets the gap."
    )


class FeedGuard:
    """One feed document load, booked through :mod:`searchts.linkedin`.

    ``check_read_allowed`` refuses an active stop or feed gap without spending
    a load slot. ``before_load`` repeats that check and spends exactly one
    :func:`searchts.linkedin.take_load` slot immediately before ``/feed/``.
    ``successful`` starts the feed gap only after content returns. Scroll
    steps never call these methods. ``record`` writes stop signals.
    """

    def __init__(self, *, clock: Any = None) -> None:
        self.clock = clock or time.time

    def before_load(self) -> None:
        from searchts import linkedin

        stop = linkedin.current_stop()
        if stop is not None:
            raise GuardRefused(linkedin.stop_hint(stop))
        self.check_read_allowed()
        try:
            # The lock books the slot and is released before the scroll.
            # Entering it calls take_load once. A step is not another load.
            with linkedin.exclusive_load():
                pass
        except linkedin.Paced as exc:
            raise GuardRefused(exc.hint or str(exc)) from exc

    def check_read_allowed(self) -> None:
        """Refuse active stops and feed gaps without spending a load slot."""
        from searchts import linkedin

        stop = linkedin.current_stop()
        if stop is not None:
            raise GuardRefused(linkedin.stop_hint(stop))
        now = float(self.clock())
        why = _feed_gap_refusal(now, _last_feed(), linkedin.feed_gap_minutes())
        if why:
            raise GuardRefused(why)

    def successful(self) -> None:
        """Start the feed gap only once usable content was read."""
        _remember_feed(float(self.clock()))

    def record(self, signal: str) -> None:
        from searchts import linkedin

        if signal in ("rate-limit", "checkpoint", "logout", "restriction"):
            linkedin.record_stop(signal)


# ── browser profile, and the one page we open ───────────────────────────────


class FeedUnavailable(Exception):
    """No feed read happened, and the sentence says why."""


def profile_path() -> Optional[str]:
    """The browser profile the kept LinkedIn login came from.

    Set ``SEARCHTS_BROWSER_PROFILE`` to that user-data directory (the legacy
    ``SEARCHTS_LINKEDIN_PROFILE`` still works when the new name is unset). It
    is deliberately not discovered by copying a cookie store: the browser that
    minted the session is the browser that reads with it.
    """
    from searchts.browser_settings import browser_profile

    return browser_profile()


def chrome_executable() -> Optional[str]:
    """An explicit Chromium-family binary, or None to let ``channel="chrome"`` find it.

    Any Chromium browser that minted the session works here (Chrome, Vivaldi,
    Edge, Brave): set ``SEARCHTS_BROWSER`` to its executable or name and
    ``SEARCHTS_BROWSER_PROFILE`` to its user-data directory. The legacy
    ``SEARCHTS_LINKEDIN_CHROME`` / ``SEARCHTS_LINKEDIN_PROFILE`` names still
    work when the new ones are unset.
    """
    from searchts.browser_settings import browser_executable

    return browser_executable()


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _windows_profile_locked(profile: str) -> bool:
    """True when a running Chromium on Windows holds the profile's ``lockfile``.

    Windows Chromium has no ``SingletonLock`` symlink. It keeps ``lockfile``
    in the user-data directory open without sharing, so opening it fails
    while the browser runs and succeeds once it has exited.
    """
    if os.name != "nt":
        return False
    lock = os.path.join(profile, "lockfile")
    if not os.path.exists(lock):
        return False
    try:
        with open(lock, "a"):
            pass
    except PermissionError:
        return True
    except OSError:
        return False
    return False


def _profile_label(browser: str) -> str:
    """Display name for a known browser, or ``browser`` when it is not named."""
    known = (browser or "").strip().lower()
    if not known:
        return "browser"
    from searchts.linkedin_attach import _display

    return _display(known)


def _locked_profile_message(profile: str, *, pid: int = 0, browser: str = "") -> str:
    """The profile is already open. Point at the inspect toggle, not a flag.

    Chrome 136+ ignores ``--remote-debugging-port`` on the default profile.
    The way to join the open browser is the per-instance checkbox.
    """
    from searchts.linkedin_attach import inspect_url

    known = (browser or "").strip().lower()
    label = _profile_label(known)
    if known:
        toggle = (
            "tick \"Allow remote debugging for this browser instance\" at "
            f"{inspect_url(known)}"
        )
    else:
        toggle = (
            "tick \"Allow remote debugging for this browser instance\" at "
            "chrome://inspect/#remote-debugging (vivaldi://, edge:// or "
            "brave:// on those browsers)"
        )
    where = f"the {label} profile at {profile} is already open"
    if pid:
        where += f" (process {pid})"
    return (
        f"{where}. Close that window, or leave it open, {toggle}, and leave "
        "SEARCHTS_LINKEDIN_ATTACH on auto. Or set SEARCHTS_LINKEDIN_CDP to the "
        "endpoint. The same LinkedIn session is never used by two clients at once."
    )


def profile_problem(profile: Optional[str], browser: str = "") -> str:
    """Why this profile cannot be opened, or ``""`` when it can.

    A ``SingletonLock`` whose pid is still running means the browser is open
    elsewhere. Using the same profile from a second client at the same time is
    the two-clients-one-session pattern that clears ``li_at``. ``browser``
    names the browser that owns the profile, so a Vivaldi or Edge window is
    not described as Chrome.
    """
    label = _profile_label(browser)
    if not profile:
        return (
            f"no {label} profile is configured for the LinkedIn feed. Set "
            "SEARCHTS_BROWSER_PROFILE to the user-data directory that holds "
            "the kept LinkedIn login (the profile the browser was signed in "
            "with; SEARCHTS_LINKEDIN_PROFILE still works as an alias). The "
            "feed is not read by copying that profile's cookies into another "
            "client."
        )
    if not os.path.isdir(profile):
        return (
            f"the configured browser profile points at {profile}, which is not "
            f"a directory. Point SEARCHTS_BROWSER_PROFILE at the {label} "
            "user-data directory that holds the kept LinkedIn login."
        )
    if _windows_profile_locked(profile):
        return _locked_profile_message(profile, browser=browser)
    lock = os.path.join(profile, "SingletonLock")
    if os.path.lexists(lock):
        target = ""
        try:
            target = os.readlink(lock)
        except OSError:
            target = ""
        pid = 0
        if "-" in target:
            try:
                pid = int(target.rsplit("-", 1)[-1])
            except ValueError:
                pid = 0
        if pid and _pid_alive(pid):
            return _locked_profile_message(profile, pid=pid, browser=browser)
    return ""


def _same_site(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def _cdp_page(browser: Any, browser_name: str = "") -> Any:
    """A new tab in the window already open on the debugging port.

    A fresh context would be a second client, with a different cookie jar
    from the window that is already signed in. If that browser has no window,
    attaching is refused. The tab rule lives in
    :func:`searchts.linkedin_attach.new_tab`.
    """
    from searchts.linkedin_attach import AttachError, new_tab

    try:
        return new_tab(browser, browser_name)
    except AttachError as exc:
        raise FeedUnavailable(str(exc)) from exc


@contextmanager
def _browser_page(
    profile: str,
    executable: Optional[str],
    cdp: Optional[str],
    url: str,
    browser_name: str = "",
) -> Iterator[Any]:
    """Open (or attach to) the signed-in Chrome and yield its live page.

    Launched with Patchright so the automation flags it can hide stay hidden,
    but on the installed Chrome (``channel="chrome"`` or an explicit binary),
    headed, on the user's profile. Locale and viewport stay the profile's own.
    The profile's cookie store is never read, copied, or written by this
    module; the browser owns it.
    """
    try:
        from patchright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001 - the extra is the normal case
        raise FeedUnavailable(
            "the LinkedIn feed needs the stealth browser. Run: "
            "searchts install --browser"
        ) from exc

    manager = sync_playwright()
    entered = False
    try:
        pw = manager.__enter__()
        entered = True
        _quiet_target_closed_futures(manager)
        if cdp:
            endpoint = cdp if "://" in cdp else f"http://{cdp}"
            browser = pw.chromium.connect_over_cdp(
                endpoint, timeout=_cdp_timeout_ms(), no_defaults=True,
            )
            page = _cdp_page(browser, browser_name)
            try:
                yield page
            finally:
                # CDP teardown only disconnects this client. Close just the
                # tab created by _cdp_page; leave the user's window intact.
                with contextlib.suppress(Exception):
                    page.close()
            return
        kwargs: Dict[str, Any] = {
            "user_data_dir": profile,
            "headless": False,
            "viewport": None,
        }
        if executable:
            kwargs["executable_path"] = executable
        else:
            kwargs["channel"] = "chrome"
        context = pw.chromium.launch_persistent_context(**kwargs)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            yield page
        finally:
            context.close()
    except FeedUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - name the browser fault, not a stack
        if cdp and _is_target_closed(exc):
            raise FeedUnavailable(_browser_closed_message()) from exc
        if cdp:
            raise FeedUnavailable(
                "could not attach to the browser over the DevTools port "
                f"({type(exc).__name__}). If the browser asked to allow remote "
                "debugging, accept that prompt and read again. Nothing was "
                "requested from LinkedIn."
            ) from exc
        raise FeedUnavailable(
            f"could not open the signed-in browser profile ({type(exc).__name__}). "
            "Close other windows using that profile, or set SEARCHTS_BROWSER "
            "to the browser's executable or name (Chrome, Vivaldi, Edge or "
            "Brave; SEARCHTS_LINKEDIN_CHROME is the legacy alias)."
        ) from exc
    finally:
        if entered:
            with contextlib.suppress(Exception):
                manager.__exit__(None, None, None)


# ── the walk ────────────────────────────────────────────────────────────────

_SCROLL_JS = "() => window.scrollTo(0, document.body.scrollHeight)"


def _merge(into: Dict[str, Post], posts: List[Post]) -> int:
    added = 0
    for post in posts:
        if not post.activity:
            continue
        if post.activity in into:
            into[post.activity].absorb(post)
        else:
            into[post.activity] = post
            added += 1
    return added


def _page_text(page: Any) -> str:
    try:
        return str(page.content() or "")
    except Exception as exc:  # noqa: BLE001 - a page that will not answer has no words
        if _is_target_closed(exc):
            raise FeedUnavailable(_browser_closed_message()) from exc
        return ""


def walk(
    page: Any,
    *,
    guard: Guard,
    resume: Optional[Resume] = None,
    limits: Optional[Limits] = None,
    url: str = FEED_URL,
    tick: Any = None,
    load_checked: bool = False,
    browser_name: str = "",
) -> FeedRead:
    """Drive one bounded scroll and return the posts the page showed.

    The page is already open (or is opened here). Nothing in this function
    makes a request of its own: it installs a passive response listener, calls
    ``goto`` once for the feed URL, then scrolls the same page. A stop signal
    ends the walk and is handed to the guard exactly once.
    """
    limits = limits or Limits()
    resume = resume or NullResume()
    posts: Dict[str, Post] = {}
    cursor = ""
    signal = ""
    started = time.monotonic()
    prior = ""
    seen_ids: set[str] = set()
    marker = resume.begin()
    if isinstance(marker, str):
        prior = marker.strip()
    seen_fn = getattr(resume, "seen", None)
    if callable(seen_fn):
        try:
            raw_seen = seen_fn() or []
        except Exception:  # noqa: BLE001 - a resume hook must not break the walk
            raw_seen = []
        for item in raw_seen:
            aid = activity_id(str(item)) or str(item).strip()
            if aid:
                seen_ids.add(aid)
    # A prior cursor means the page that carried it was already returned.
    # ``passed`` flips once a later response from the page itself moves on.
    passed = not bool(prior)
    resumed = bool(prior or seen_ids)

    def say(message: str) -> None:
        if tick is None:
            return
        try:
            tick(message)
        except Exception:  # noqa: BLE001 - narration never breaks a walk
            pass

    def accept(batch: List[Post], response_cursor: str = "") -> None:
        """Keep posts the resume hook has not already returned.

        A response whose cursor is the one ``begin`` handed back is the page
        already read. It is dropped, and so is the DOM, until a later response
        carries a different cursor. Activity ids from ``seen`` are dropped
        either way. No cursor is requested.
        """
        nonlocal cursor, passed
        if response_cursor:
            cursor = response_cursor
        if prior and response_cursor == prior:
            return
        if prior and not response_cursor and not passed:
            return
        if prior and response_cursor and response_cursor != prior:
            passed = True
        fresh = [post for post in batch if post.activity not in seen_ids]
        if fresh:
            _merge(posts, fresh)

    def capture(body: str, source: str, status: Optional[int]) -> None:
        nonlocal signal
        if not body:
            found = detect_signal("", status=status, url=source)
            if found:
                signal = signal or found
            return
        got = parse_capture(body, source=source)
        accept(got.posts, got.cursor)
        signal = signal or got.signal
        if not signal:
            signal = detect_signal("", status=status, url=source)

    def on_response(response: Any) -> None:
        nonlocal signal
        try:
            status = int(getattr(response, "status", 0) or 0)
        except (TypeError, ValueError):
            status = 0
        source = str(getattr(response, "url", "") or "")
        if status in (429, 999):
            if _same_site(source) or not source:
                signal = signal or detect_signal("", status=status, url=source)
        if not _same_site(source):
            return
        headers = getattr(response, "headers", None) or {}
        ctype = str(headers.get("content-type", "") if hasattr(headers, "get") else "")
        if ctype and not any(word in ctype for word in ("json", "javascript")):
            return
        if not ctype and not any(word in source for word in ("graphql", "/feed")):
            return
        try:
            body = response.text()
        except Exception:  # noqa: BLE001 - a body already gone is not a read
            return
        if isinstance(body, str):
            capture(body, source, status)

    try:
        page.on("response", on_response)
    except Exception:  # noqa: BLE001 - a page without events still has a DOM
        pass

    try:
        if not load_checked:
            # read_feed checks the guard before it starts a browser, so that a
            # recorded stop refuses without opening anything. A direct call (the
            # offline tests) checks here, at the same seam.
            guard.before_load()
        who = (browser_name or "").strip() or "browser"
        say(f"  linkedin: opening the feed in the signed-in {who}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=limits.max_seconds * 1000)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            if _is_target_closed(exc):
                raise FeedUnavailable(_browser_closed_message()) from exc
            raise
        _settle(page, limits.settle_ms)
        accept(parse_html(_page_text(page)))
        signal = signal or detect_signal(_page_text(page), url=str(getattr(page, "url", url)))

        steps = 0
        stop = ""
        while True:
            if signal:
                break
            if len(posts) >= limits.max_posts:
                stop = f"reached the {limits.max_posts} posts asked for"
                break
            if steps >= limits.max_steps:
                stop = f"the {limits.max_steps} scroll step limit"
                break
            if time.monotonic() - started >= limits.max_seconds:
                stop = f"the {limits.max_seconds}s scroll budget"
                break
            say(f"  linkedin: scroll step {steps + 1} of {limits.max_steps}")
            page.wait_for_timeout(random.randint(limits.step_min_ms, limits.step_max_ms))
            try:
                page.evaluate(_SCROLL_JS)
            except Exception as exc:  # noqa: BLE001 - a page that navigated away ends the walk
                if _is_target_closed(exc):
                    raise FeedUnavailable(_browser_closed_message()) from exc
                stop = "the page navigated away mid-scroll"
                break
            page.wait_for_timeout(limits.settle_ms)
            steps += 1
            accept(parse_html(_page_text(page)))
            if cursor:
                resume.advance(cursor, list(posts.values()))
            signal = signal or detect_signal(
                _page_text(page), url=str(getattr(page, "url", url))
            )

        if signal:
            guard.record(signal)
            stop = (
                "a person must clear the restriction before reading resumes"
                if signal == STOP_UNTIL_CLEARED
                else "stopped for 24 h, with no retry"
            )
        elif resumed and not posts:
            stop = "scrolled for the resume cursor and the page showed nothing new"
        elif not stop:
            stop = "the feed stopped growing"

        ordered = list(posts.values())[: max(1, limits.max_posts)]
        result = FeedRead(
            posts=ordered,
            text=render(ordered, stop=stop, signal=signal),
            cursor=cursor,
            signal=signal,
            stop=stop,
            steps=steps,
        )
        if ordered:
            successful = getattr(guard, "successful", None)
            if callable(successful):
                successful()
        return result

    finally:
        remove_listener = getattr(page, "remove_listener", None)
        if callable(remove_listener):
            with contextlib.suppress(Exception):
                remove_listener("response", on_response)


def _is_target_closed(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    detail = str(exc).lower()
    return (
        "targetclosed" in name
        or "browser closed" in detail
        or "browser has been closed" in detail
        or "target page, context or browser has been closed" in detail
        or "connection closed" in detail
        or "websocket" in detail and ("closed" in detail or "disconnect" in detail)
    )


def _browser_closed_message() -> str:
    return (
        "the browser closed the tab or remote-debugging connection. If it "
        "showed an ‘Allow remote debugging?’ prompt, click Allow and retry."
    )


def _settle(page: Any, ms: int) -> None:
    try:
        page.wait_for_timeout(ms)
    except Exception as exc:  # noqa: BLE001 - a page mid-navigation settles on its own
        if _is_target_closed(exc):
            raise FeedUnavailable(_browser_closed_message()) from exc
        pass


@dataclass
class FeedRead:
    """What one feed read returned, and why it stopped."""

    posts: List[Post] = field(default_factory=list)
    text: str = ""
    cursor: str = ""
    signal: str = ""
    stop: str = ""
    steps: int = 0
    notes: List[str] = field(default_factory=list)


def read_feed(
    url: str = FEED_URL,
    *,
    guard: Optional[Guard] = None,
    resume: Optional[Resume] = None,
    resume_token: str = "",
    limits: Optional[Limits] = None,
    profile: Optional[str] = None,
    executable: Optional[str] = None,
    cdp: Optional[str] = None,
    attach: Optional[str] = None,
    tick: Any = None,
) -> FeedRead:
    """Read the signed-in LinkedIn feed once, or say why it cannot.

    A recorded stop is named first, before any browser decision, and it does
    not book a load. ``attach`` (or ``SEARCHTS_LINKEDIN_ATTACH``) then chooses
    how the browser is used. Attaching joins the running browser over the
    DevTools port written when remote debugging is allowed for that instance.
    A running browser with that toggle off stops here, still before a load is
    booked and before any page is requested. Launching is the existing path:
    it refuses when there is no kept login, no profile, or the profile is
    already open in another client. An explicit debugging port
    (``SEARCHTS_LINKEDIN_CDP``) attaches even when the mode is off.
    ``resume_token`` is verified by :func:`resume_from_token` and then only
    scrolled; an explicit ``resume`` hook wins over the token.
    """
    from searchts import linkedin, linkedin_attach, login_store

    chosen = profile or profile_path()
    raw_cdp = (cdp or os.environ.get("SEARCHTS_LINKEDIN_CDP", "")).strip()
    # The 24 h stop and the restriction stop outrank the debugging toggle.
    # Neither books a load and neither opens a browser.
    stop = linkedin.current_stop()
    if stop is not None:
        raise FeedUnavailable(linkedin.stop_hint(stop))
    try:
        decision = linkedin_attach.decide(
            mode=attach,
            profile=chosen,
            executable=executable if executable is not None else chrome_executable(),
            endpoint=raw_cdp,
            kept_browser_name=None if not raw_cdp else "",
        )
    except ValueError as exc:
        raise FeedUnavailable(str(exc)) from exc
    if decision.action == "refuse":
        raise FeedUnavailable(decision.message)

    endpoint = ""
    if decision.action == "attach":
        # The caller's string is preserved when they named a port, so a
        # host:port stays host:port. A discovered port is already a URL.
        endpoint = raw_cdp or decision.endpoint
    else:
        # Pointing searchts at the signed-in browser (a profile or a debugging
        # port) is the consent for this read: the feed runs in that browser and
        # never copies its cookies. Without either, a kept login is required.
        # A discovered default directory is not a profile we may launch.
        if not chosen and not login_store.kept("linkedin.com"):
            raise FeedUnavailable(
                "the LinkedIn feed is read in the browser signed in to LinkedIn, "
                "and searchts has no kept LinkedIn login. Keep one with "
                "`searchts login keep linkedin.com` after a signed-in read, or "
                "set SEARCHTS_BROWSER_PROFILE to that browser's user-data "
                "directory (SEARCHTS_LINKEDIN_PROFILE is the legacy alias). "
                "Until then, linkedin-scraper-mcp remains the fallback "
                "for the feed."
            )
        problem = profile_problem(chosen, decision.browser)
        if problem:
            raise FeedUnavailable(problem)
    chosen = chosen or ""

    active_resume = resume
    if active_resume is None and resume_token.strip():
        active_resume = resume_from_token(url, resume_token)

    active_guard = guard if guard is not None else FeedGuard()
    check_read_allowed = getattr(active_guard, "check_read_allowed", None)
    load_checked = False
    if callable(check_read_allowed):
        try:
            check_read_allowed()
        except GuardRefused as exc:
            raise FeedUnavailable(str(exc)) from exc
    else:
        # Small third-party/test guards may only expose the original seam.
        # Preserve their early refusal behavior; FeedGuard itself delays its
        # load booking until immediately before navigation.
        try:
            active_guard.before_load()
            load_checked = True
        except GuardRefused as exc:
            raise FeedUnavailable(str(exc)) from exc

    try:
        who = (
            linkedin_attach._display(decision.browser)
            if decision.browser else ""
        )
        if endpoint:
            from searchts.progress import narrate

            narrate(
                "  linkedin: connecting to the signed-in browser; if it asks "
                '"Allow remote debugging?", click Allow'
            )
        with _browser_page(
            chosen, executable or chrome_executable(), endpoint, url,
            browser_name=decision.browser,
        ) as page:
            read = walk(
                page,
                guard=active_guard,
                resume=active_resume,
                limits=limits,
                url=url,
                tick=tick,
                load_checked=load_checked,
                browser_name=who,
            )
    except FeedUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - one named sentence for a browser fault
        if _is_target_closed(exc):
            raise FeedUnavailable(_browser_closed_message()) from exc
        raise FeedUnavailable(
            f"the LinkedIn feed could not be read ({type(exc).__name__}). "
            "No retry is made."
        ) from exc

    if not read.posts:
        raise FeedUnavailable(
            f"the LinkedIn feed returned no posts ({read.stop or 'no reason'}). "
            "Nothing is passed off as a read."
        )
    return read
