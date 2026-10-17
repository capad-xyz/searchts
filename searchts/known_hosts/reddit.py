# -*- coding: utf-8 -*-
"""Reddit public-document extractor — known-host ring (F5b, F5f).

The caller passes a **page**, not an API URL (same as share extractors).
HTML listing/thread/profile/search URLs (www / old / no-www, hot/new/top/rising,
``comments/<id>/…``, ``/user/<name>/``, ``/search/?q=…``) are read from the page
Reddit itself served; the ``.json`` ring still rewrites listing and thread URLs to
the public ``.json`` document first, then fails open to curl/Jina/stealth.

Also matches already-JSON shapes: ``/r/sub.json``, ``/r/sub/hot.json``,
``/r/sub/comments/<id>.json``, and ``/.json``.

**F5f**, built 2026-10-17 against saved pages of every state (see the module
tests): what works, what each wall is called, and the two cursors.

- **More posts than the first window.** The listing page ships its own cursor,
  ``faceplate-partial[slot=load-after]`` →
  ``/svc/shreddit/community-more-posts/<sort>/?after=…`` (the profile feed ships
  the same shape at ``/svc/shreddit/profiles/…-more-posts/…``). ``--items`` /
  ``max_items`` follows it with curl after the first page, the way F23b does,
  and every batch renders as the same index.
- **Deeper comments.** ``shreddit-comment`` nodes in the served HTML are the
  first window; the rest sit behind Reddit's own ``more-comments-partial``
  controls, which answer a POST with a minted cursor and a ``csrf_token``
  cookie. Opened in the browser (opt-in ``--expand``), a 195-comment thread
  went 25 → 127 comments; as a bare HTTP request that endpoint answers
  ``Page not found`` from curl *and* from the browser.
- **The walls, each named.** Private, banned, quarantined, gone, not-found and
  archived pages are states the page states about itself, so they fail with their
  own reason instead of handing back navigation chrome as if it were the
  community.

The ``.json`` ring is still fail-open and still unreachable from a datacenter IP
(measured 2026-10-17: ``www.reddit.com/r/x/hot.json`` and ``api.reddit.com``
both answer ``403`` with Reddit's "blocked by network security" page, in the
browser too). Nothing here claims every Reddit URL reads (**N7**).
"""

from __future__ import annotations

import html as html_lib
import json
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

from searchts.known_hosts import KnownResult

# HTML pages and JSON documents. Host: www / old / bare reddit.com.
# Listing: /r/<sub>[/hot|/new|/top|/rising]
# Thread:  /r/<sub>/comments[/<id>[/<slug>]]
# User:    /user/<user>
# JSON may be ``.json`` on the last segment or ``/.json``.

PATTERN = re.compile(
    r"^https://(?:www\.|old\.)?reddit\.com/"
    r"(?:"
    r"r/(?P<subreddit>[A-Za-z0-9_]+)"
    r"(?:"
    r"\.json"
    r"|/\.json"
    r"|/(?:hot|new|top|rising|controversial)(?:\.json|/\.json)?"
    r"|/comments(?:/(?P<post_id>[A-Za-z0-9]+)(?:/(?P<slug>[A-Za-z0-9_-]+))?)?(?:\.json|/\.json)?"
    r")?"
    r"/?"
    r"|"
    r"user/(?P<user>[A-Za-z0-9_-]+)(?:\.json|/\.json)?"
    r"/?"
    r")"
    r"(?:\?.*)?$",
    re.IGNORECASE,
)


def _to_json_url(url: str) -> str:
    """Map a Reddit page URL to the public ``.json`` document.

    ``/r/foo/hot/`` → ``/r/foo/hot.json``. Already-``.json`` paths are unchanged.
    """
    parts = urllib.parse.urlsplit(url)
    path = parts.path or "/"
    if path.endswith(".json"):
        return url
    path = path.rstrip("/") + ".json"
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, path, parts.query, "")
    )

#: Safety-interstitial signal from Reddit's JSON endpoint.
_BLOCK_SIGNALS = frozenset({"error", "message"})


def _fetch(url: str, timeout: int = 30) -> str:
    """Chrome-impersonated GET against the Reddit JSON API.

    Appends ``?raw_json=1`` to avoid Reddit's HTML interstitial on JSON requests.
    Uses the same impersonation and headers as the unlocker's ``_fetch_curl_cffi``.
    """
    from curl_cffi import requests as cr

    base, frag = urllib.parse.urldefrag(url)
    if "raw_json=1" not in base:
        sep = "&" if "?" in base else "?"
        base = base + sep + "raw_json=1"
    r = cr.get(base, impersonate="chrome", timeout=timeout,
                headers={"Accept-Language": "en-US,en;q=0.9",
                         "Accept": "application/json"})
    return r.text


def _is_block_interstitial(data: Any) -> bool:
    """True if `data` is Reddit's safety-interstitial JSON response.

    Reddit returns a JSON object like ``{"error": 403, "message": "blocked"}``
    or an HTML string when an interstitial is served. Treat both as a block so
    the ladder runs and the login-wall phrase logic applies as normal.
    """
    if isinstance(data, dict):
        if "error" in data or "message" in data:
            return True
        if not data:
            return True
    return False


def _listing_children(listing: Any) -> List[Dict[str, Any]]:
    """Return the ``data.children`` list from a Reddit listing, or empty list."""
    if not isinstance(listing, dict):
        return []
    data = listing.get("data")
    if not isinstance(data, dict):
        return []
    children = data.get("children")
    if not isinstance(children, list):
        return []
    return children


def _post_lines(post: Dict[str, Any]) -> List[str]:
    """Render a t3 post as markdown lines."""
    lines: List[str] = []
    title = post.get("title") or ""
    if title:
        lines.append(f"# {title}\n")
    author = post.get("author", "")
    if author:
        lines.append(f"**OP:** /u/{author}\n")
    subreddit = post.get("subreddit", "")
    if subreddit:
        lines.append(f"**Subreddit:** r/{subreddit}\n")
    score = post.get("score", 0)
    if isinstance(score, int):
        lines.append(f"**Score:** {score}\n")
    permalink = post.get("permalink", "")
    if permalink:
        if not permalink.startswith("http"):
            permalink = f"https://www.reddit.com{permalink}"
        lines.append(f"**Link:** {permalink}\n")
    selftext = post.get("selftext", "")
    if selftext:
        lines.append(f"\n{selftext}\n")
    return lines


def _unwrap_post(child: Dict[str, Any]) -> Dict[str, Any]:
    """Unwrap a {kind, data} child into a flat dict, or return bare object as-is."""
    if isinstance(child, dict) and "data" in child and isinstance(child.get("data"), dict):
        return child["data"]
    return child


def _comment_lines(comment: Dict[str, Any]) -> List[str]:
    """Render a t1 comment as markdown lines.

    Handles both bare t1 objects (direct fields) and wrapped {kind, data} listings.
    """
    lines: List[str] = []
    comment = _unwrap_post(comment)
    body = comment.get("body", "")
    if not body:
        return lines
    author = comment.get("author", "[deleted]")
    score = comment.get("score", 0)
    permalink = comment.get("permalink", "")
    if permalink and not permalink.startswith("http"):
        permalink = f"https://www.reddit.com{permalink}"
    score_str = str(score) if isinstance(score, int) else "?"
    header = f"**/u/{author}** ({score_str} pts)"
    if permalink:
        header += f" \u00b7 [permalink]({permalink})"
    lines.append(f"{header}\n")
    lines.append(f"{body}\n")
    return lines


def _render_thread(post: Dict[str, Any], comments: List[Dict[str, Any]]) -> str:
    """Render a thread (post + comments) as markdown.

    `comments` may be bare t1 dicts (real API) or {kind, data} wrappers (fixtures).
    """
    lines = _post_lines(post)
    if comments:
        cap = _row_ceiling()
        lines.append("\n## Comments\n")
        for i, child in enumerate(comments[:cap]):
            if not isinstance(child, dict):
                continue
            # Unwrap if needed; treat bare objects as already flat.
            if child.get("kind") == "t1":
                data = _unwrap_post(child)
                lines.extend(_comment_lines(data))
                lines.append("\n")
            elif child.get("kind") == "more":
                break
            elif child.get("body"):  # bare t1 object (flat format)
                lines.extend(_comment_lines(child))
                lines.append("\n")
    return "".join(lines).strip()


def _render_subreddit_from_children(children: List[Dict[str, Any]]) -> str:
    """Render a list of children (t3 dicts or {kind, data} wrappers) as a compact index.

    The row cap is the knobs ceiling (``SEARCHTS_MAX_ITEMS``, see
    :func:`_row_ceiling`), never a literal: a post is a row, and the user caps
    rows there (F5f).
    """
    lines: List[str] = []
    for child in children[: _row_ceiling()]:
        if not isinstance(child, dict):
            continue
        # Accept both bare t3 objects and {kind, data} wrappers.
        if child.get("kind") == "t3":
            data = child.get("data", child)  # prefer data, fall back to bare
        elif "data" in child:
            data = child["data"]
        else:
            data = child  # bare object (listing fixture format)
        kind = data.get("kind", "t3")
        if kind not in ("t3", "Link"):
            continue
        title = data.get("title", "")
        author = data.get("author", "[deleted]")
        score = data.get("score", 0)
        permalink = data.get("permalink", "")
        if permalink and not permalink.startswith("http"):
            permalink = f"https://www.reddit.com{permalink}"
        score_str = str(score) if isinstance(score, int) else "?"
        if title:
            lines.append(f"- **{title}** \u2014 /u/{author} ({score_str} pts)")
            if permalink:
                lines.append(f"  [`permalink`]({permalink})")
            lines.append("")
    return "".join(lines).strip() or ""


def _render_subreddit(listing: Any) -> str:
    """Render a subreddit listing (list or Listing dict) as a compact index."""
    if isinstance(listing, list):
        return _render_subreddit_from_children(listing)
    if isinstance(listing, dict):
        children = _listing_children(listing)
        return _render_subreddit_from_children(children)
    return ""


def _render_user(data: Dict[str, Any]) -> str:
    """Render a user about JSON payload as markdown."""
    lines: List[str] = []
    # /user/<name>/about.json returns a Listing wrapping a t2 child.
    children = data.get("children", [])
    if isinstance(children, list) and children:
        udata = children[0].get("data", {}) if isinstance(children[0], dict) else {}
        row = {**data, **udata}
    else:
        row = data

    name = row.get("id") or row.get("author") or ""
    if name:
        lines.append(f"# /u/{name}\n")

    icon_img = row.get("icon_img", "")
    if icon_img:
        img_url = re.sub(r"<[^>]+>", "", icon_img).strip()
        if img_url:
            lines.append(f"![avatar]({img_url})\n")

    # Karma fields live at the top level of the t2 user object.
    link_karma = row.get("link_karma", "")
    comment_karma = row.get("comment_karma", "")
    if link_karma or comment_karma:
        lines.append(f"**Link karma:** {link_karma}\n")
        lines.append(f"**Comment karma:** {comment_karma}\n")

    created_utc = row.get("created_utc", 0)
    if created_utc:
        try:
            from datetime import datetime, timezone
            ts = datetime.fromtimestamp(created_utc, tz=timezone.utc).strftime("%Y-%m-%d")
            lines.append(f"**Account created:** {ts}\n")
        except Exception:  # noqa: BLE001
            pass

    if len(lines) <= 1 and not icon_img:
        return ""
    return "".join(lines).strip()


def extract_known(url: str, match: "re.Match[str]") -> Optional[KnownResult]:
    """Fetch and render a Reddit `.json` URL to markdown, or None on any failure.

    Fail-open: returns None for any of: 403 JSON interstitial, malformed JSON,
    missing expected structure, empty body. The ladder runs in all these cases.
    """
    try:
        raw = _fetch(_to_json_url(url))
    except Exception:  # noqa: BLE001 - network failure → ladder
        return None

    if not raw or not raw.strip():
        return None

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None

    if isinstance(data, dict):
        if _is_block_interstitial(data):
            return None
        # Dict listing (e.g. subreddit or user about from fixtures / some API paths).
        # Determine which from the URL groups.
        subreddit = match.group("subreddit")
        user = match.group("user")
        if subreddit:
            children = _listing_children(data)
            md = _render_subreddit(children)
            if md:
                return KnownResult(provider="reddit", title=f"r/{subreddit}", markdown=md)
        elif user:
            udata = _listing_children(data)  # children holds the t2 user object
            if udata:
                inner = udata[0].get("data", {}) if isinstance(udata[0], dict) else {}
                md = _render_user({**data, **inner})
                if md:
                    return KnownResult(provider="reddit", title=f"/u/{user}", markdown=md)
        return None

    if not isinstance(data, list) or not data:
        return None

    # Thread: [post-listing, comments-listing]
    if len(data) >= 2:
        post_listing = data[0]
        comments_listing = data[1]
        post_children = _listing_children(post_listing)
        comment_children = _listing_children(comments_listing)
        if post_children:
            post_data = post_children[0].get("data", {})
            post_kind = post_children[0].get("kind", "")
            if post_kind == "t3":
                md = _render_thread(post_data, comment_children)
                if md:
                    return KnownResult(
                        provider="reddit",
                        title=post_data.get("title") or None,
                        markdown=md,
                    )

    # Subreddit or user listing: single list
    if len(data) == 1:
        kind0 = data[0].get("kind") if isinstance(data[0], dict) else None
        if kind0 in ("Listing", "Link", "t5", "t2"):
            children = _listing_children(data[0])
            subreddit = match.group("subreddit")
            user = match.group("user")
            if subreddit:
                md = _render_subreddit(children)
                if md:
                    return KnownResult(provider="reddit", title=f"r/{subreddit}", markdown=md)
            elif user and children:
                udata = children[0].get("data", {}) if isinstance(children[0], dict) else {}
                md = _render_user({**data[0], **udata})
                if md:
                    return KnownResult(provider="reddit", title=f"/u/{user}", markdown=md)

    return None


# ── F5c: Reddit listing HTML (shreddit-post) short-circuit for unlocker ladder ──

_LISTING_PATH_RE = re.compile(
    r"^/r/[A-Za-z0-9_]+(?:/(?:hot|new|top|rising|controversial))?/?$",
    re.IGNORECASE,
)

#: The hosts that serve Reddit's own pages. ``np.reddit.com`` is the no-participation
#: view and is the same application.
REDDIT_HOSTS = frozenset(
    {"reddit.com", "www.reddit.com", "old.reddit.com", "new.reddit.com", "np.reddit.com"}
)

#: A profile page: ``/user/<name>`` and its tabs (``/submitted``, ``/comments``).
_PROFILE_PATH_RE = re.compile(
    r"^/user/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*/?$", re.IGNORECASE
)
#: Reddit search, site-wide (``/search``) or inside one community.
_SEARCH_PATH_RE = re.compile(r"^/(?:r/[A-Za-z0-9_]+/)?search/?$", re.IGNORECASE)
#: A feed batch: the cursor endpoint behind ``faceplate-partial[slot=load-after]``
#: for both a community feed and a profile feed.
_BATCH_PATH_RE = re.compile(
    r"^/svc/shreddit/(?:(?P<community>community-more-posts)|profiles/[A-Za-z0-9_-]+-more-posts)/",
    re.IGNORECASE,
)


def _host_of(url: str) -> str:
    try:
        return (urllib.parse.urlsplit(url or "").netloc or "").lower()
    except Exception:  # noqa: BLE001 - a malformed URL is simply not a Reddit page
        return ""


def _path_of(url: str) -> str:
    try:
        return urllib.parse.urlsplit(url or "").path or ""
    except Exception:  # noqa: BLE001 - as above
        return ""


def is_reddit_batch_url(url: str) -> bool:
    """True for Reddit's own feed-batch cursor URL (``/svc/shreddit/…-more-posts/…``).

    Those pages are feed fragments, not documents: they hold more post cards and
    the next cursor, and they are only ever reached by following the cursor the
    first page printed (F5f).
    """
    return _host_of(url) in REDDIT_HOSTS and bool(_BATCH_PATH_RE.match(_path_of(url)))


def is_reddit_url(url: str) -> bool:
    """True for any URL on a host Reddit serves, whatever its path.

    Wider than :data:`PATTERN`, which is only the shapes the ``.json`` ring
    claims. A wall check needs the wider test: the ``/svc/shreddit/…`` cursors are
    Reddit pages too, and those are where the "Prove your humanity" interstitial
    was measured.
    """
    return _host_of(url) in REDDIT_HOSTS


def hop_needs_browser(url: str, reasons) -> bool:
    """True when this hop failed on a Reddit wall only the browser rung passes.

    Asked by :func:`unlocker._retry_hop_on_browser` after a next-page walk was
    refused, and it answers one thing: would opening the same URL in the browser
    be a different request? For Reddit's humanity check it is - that interstitial
    is decided from the browser profile's standing, not from the address - so the
    walk is worth one more try. Every other Reddit wall (private, banned,
    quarantined, gone, over-18) is the same page in a browser, and saying yes to
    those would spend a launch to learn nothing.
    """
    if not is_reddit_url(url):
        return False
    return any(
        str(why or "") == _STATE_CHALLENGE for _b, why in (reasons or ())
    )


def is_reddit_profile_batch_url(url: str) -> bool:
    """True for a profile feed batch, which mixes post cards and comment cards."""
    m = _BATCH_PATH_RE.match(_path_of(url)) if _host_of(url) in REDDIT_HOSTS else None
    return bool(m and not m.group("community"))


def is_reddit_profile_url(url: str) -> bool:
    """True for ``/user/<name>`` and its tabs, as HTML (never ``.json``)."""
    if _host_of(url) not in REDDIT_HOSTS:
        return False
    path = _path_of(url)
    if ".json" in path:
        return False
    return bool(_PROFILE_PATH_RE.match(path))


def is_reddit_search_url(url: str) -> bool:
    """True for Reddit's own search page, site-wide or inside one community."""
    if _host_of(url) not in REDDIT_HOSTS:
        return False
    path = _path_of(url)
    if ".json" in path:
        return False
    return bool(_SEARCH_PATH_RE.match(path))


def is_feed_html_url(url: str) -> bool:
    """True for a listing page **or** one of its feed batches.

    Both hold the same ``shreddit-post`` cards, so both render as the same
    index; a batch additionally carries the next cursor (F5f).
    """
    return is_reddit_listing_url(url) or is_reddit_batch_url(url)


def page_kind(url: str) -> str:
    """What kind of Reddit page this is: listing, batch, thread, profile, search.

    ``""`` for anything else, including every ``.json`` URL: those belong to the
    JSON ring (``extract_known``), not to this HTML entry point.
    """
    if not url or _host_of(url) not in REDDIT_HOSTS:
        return ""
    path = _path_of(url)
    if ".json" in path:
        return ""
    if is_reddit_batch_url(url):
        return "batch"
    if is_reddit_thread_url(url):
        return "thread"
    if is_reddit_profile_url(url):
        return "profile"
    if is_reddit_search_url(url):
        return "search"
    if is_reddit_listing_url(url):
        return "listing"
    return ""


def is_reddit_listing_url(url: str) -> bool:
    """True for Reddit subreddit listing pages served as HTML (not threads, not .json).

    Matches:
      https://www.reddit.com/r/sub/
      https://www.reddit.com/r/sub/hot
      https://old.reddit.com/r/sub/new/
      https://reddit.com/r/sub/controversial?foo=1

    Does NOT match:
      /r/sub/comments/...
      any .json URL
      other hosts
    """
    if not url:
        return False
    host = _host_of(url)
    if host not in REDDIT_HOSTS:
        return False
    path = _path_of(url)
    # Explicit .json never a listing for this path (JSON ring owns them)
    if ".json" in path:
        return False
    # Threads are never listings
    if "/comments/" in path.lower():
        return False
    # Must match a clean listing path (with optional sort and trailing slash)
    if not _LISTING_PATH_RE.match(path):
        return False
    return True


def is_reddit_thread_url(url: str) -> bool:
    """True for a Reddit comments thread served as HTML (not .json)."""
    if not url:
        return False
    host = _host_of(url)
    if host not in REDDIT_HOSTS:
        return False
    path = _path_of(url)
    if ".json" in path:
        return False
    return bool(_THREAD_PATH_RE.match(path))


_SKIP_TAGS = frozenset({"script", "style", "svg", "noscript"})
_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_SNIPPET_MIN = 40
_THREAD_PATH_RE = re.compile(
    r"^/r/[A-Za-z0-9_]+/comments/[A-Za-z0-9]+(?:/[A-Za-z0-9_-]+)?/?$",
    re.IGNORECASE,
)


def _parse_shreddit_posts(html: str) -> List[Dict[str, str]]:
    """Return attr dicts for every <shreddit-post>, plus inner card text.

    ``_text`` is all light-DOM text. ``_body`` is ``slot="text-body"`` when
    that slot exists. ``_flair`` is the ``shreddit-post-flair`` text,
    ``_gallery`` the ``gallery-carousel`` image URLs and ``_player`` the
    ``shreddit-player`` sources, newline-joined. Stdlib HTMLParser only.
    """

    class _P(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.posts: List[Dict[str, str]] = []
            self._depth = 0
            self._skip = 0
            self._body_depth = 0
            self._attrs: Optional[Dict[str, str]] = None
            self._all: List[str] = []
            self._body: List[str] = []
            self._flair_depth = 0
            self._gallery_depth = 0
            self._flair: List[str] = []
            self._gallery: List[str] = []
            self._player: List[str] = []

        def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
            t = tag.lower()
            if t in _SKIP_TAGS:
                self._skip += 1
            ad = {str(k).lower(): (v or "") for k, v in attrs}
            if t == "shreddit-post":
                if self._depth == 0:
                    self._attrs = ad
                    self._all = []
                    self._body = []
                    self._body_depth = 0
                    self._flair_depth = 0
                    self._gallery_depth = 0
                    self._flair = []
                    self._gallery = []
                    self._player = []
                self._depth += 1
            elif self._depth and t not in _VOID_TAGS:
                if self._body_depth:
                    self._body_depth += 1
                elif ad.get("slot", "").lower() == "text-body":
                    self._body_depth = 1
                if self._flair_depth:
                    self._flair_depth += 1
                elif t == "shreddit-post-flair":
                    self._flair_depth = 1
                if self._gallery_depth:
                    self._gallery_depth += 1
                elif t == "gallery-carousel":
                    self._gallery_depth = 1
                if t in ("shreddit-player", "shreddit-player-2") and ad.get("src"):
                    self._player.append(ad["src"])
            elif self._depth and t == "img" and self._gallery_depth:
                src = ad.get("src") or ad.get("data-lazy-src") or ""
                if "redd.it/" in src and src not in self._gallery:
                    self._gallery.append(src)

        def handle_endtag(self, tag: str) -> None:
            t = tag.lower()
            if t in _SKIP_TAGS:
                self._skip = max(0, self._skip - 1)
            if t not in _VOID_TAGS:
                if self._body_depth:
                    self._body_depth -= 1
                if self._flair_depth:
                    self._flair_depth -= 1
                if self._gallery_depth:
                    self._gallery_depth -= 1
            if t == "shreddit-post" and self._depth:
                self._depth -= 1
                if self._depth == 0 and self._attrs is not None:
                    self._attrs["_text"] = " ".join(self._all)
                    self._attrs["_body"] = " ".join(self._body)
                    self._attrs["_flair"] = " ".join(self._flair)
                    self._attrs["_gallery"] = "\n".join(self._gallery)
                    self._attrs["_player"] = "\n".join(self._player)
                    self.posts.append(self._attrs)
                    self._attrs = None

        def handle_data(self, data: str) -> None:
            if not self._depth or self._skip:
                return
            s = data.strip()
            if not s:
                return
            self._all.append(s)
            if self._body_depth:
                self._body.append(s)
            if self._flair_depth:
                self._flair.append(s)

    p = _P()
    try:
        p.feed(html or "")
    except Exception:  # noqa: BLE001 - malformed HTML must not explode
        pass
    return p.posts


def _card_body(title: str, body: str, all_text: str, *, require_min: bool = True) -> str:
    """Visible card/post body. Empty when the card is title-only.

    Uses ``slot="text-body"`` when present (the full card text Reddit mounted).
    Does not truncate. ``require_min`` drops leftover chrome on link cards.
    """
    slot = (body or "").strip()
    if slot:
        text = re.sub(r"\s+", " ", slot).strip()
        t = (title or "").strip()
        if t and text.startswith(t):
            text = re.sub(r"^[\s\-|]+", "", text[len(t) :]).strip()
        return text
    text = re.sub(r"\s+", " ", (all_text or "")).strip()
    if not text:
        return ""
    t = (title or "").strip()
    if t and text.startswith(t):
        text = re.sub(r"^[\s\-|]+", "", text[len(t) :]).strip()
    text = re.sub(
        r"\b(Share|Award|Give Award|Hide|Reply|Report)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s+", " ", text).strip()
    if require_min and len(text) < _SNIPPET_MIN:
        return ""
    return text


# Reddit's fold button text, exactly as shown (capital R). Case-sensitive so a
# post that really ends "...you can read more" is not marked truncated.
_READ_MORE_RE = re.compile(r"\s*\u2026?\s*\bRead more\s*$")


def _strip_read_more(text: str) -> Tuple[str, bool]:
    """Drop Reddit's trailing "Read more" fold marker. Returns (text, was_folded)."""
    if not text:
        return text, False
    stripped = _READ_MORE_RE.sub("", text)
    if stripped == text:
        return text, False
    return stripped.rstrip(), True


_REDDIT_MEDIA_HOSTS = frozenset({"i.redd.it", "v.redd.it", "preview.redd.it"})
_MEDIA_POST_TYPES = frozenset({"image", "gif", "video", "gallery"})
_MAX_MEDIA = 6


def _post_type(attrs: Dict[str, str]) -> str:
    return (attrs.get("post-type") or "").strip().lower()


def _post_links(attrs: Dict[str, str]) -> Tuple[str, List[str], bool]:
    """(outbound URL, media URLs, media present but not resolved) for one post.

    A link post points off Reddit through ``content-href``. Image, GIF and
    video posts point at ``i.redd.it`` / ``v.redd.it``; a gallery lists its
    ``preview.redd.it`` images in ``gallery-carousel``. An image or video post
    with none of those says so instead of going silent.
    """
    ptype = _post_type(attrs)
    href = (attrs.get("content-href") or "").strip()
    host = (urllib.parse.urlsplit(href).netloc or "").lower() if href else ""
    outbound = ""
    on_reddit = host == "reddit.com" or host.endswith(".reddit.com") or host in _REDDIT_MEDIA_HOSTS
    if ptype == "link" and host and not on_reddit:
        outbound = href
    media: List[str] = []
    if ptype in ("image", "gif", "video") and host in _REDDIT_MEDIA_HOSTS:
        media = [href]
    elif ptype == "gallery":
        media = _one_per_image([u for u in (attrs.get("_gallery") or "").split("\n") if u])
    if not media and ptype in _MEDIA_POST_TYPES:
        media = [u for u in (attrs.get("_player") or "").split("\n") if u]
    return outbound, media, ptype in _MEDIA_POST_TYPES and not media


_MEDIA_ID_RE = re.compile(r"([A-Za-z0-9]{8,20})\.(?:jpe?g|png|gif|webp|mp4)$", re.IGNORECASE)


def _one_per_image(urls: List[str]) -> List[str]:
    """One URL per gallery image, in order. A carousel shows each image twice
    (a ``preview.redd.it`` size and the ``i.redd.it`` original, same media id);
    keep the original."""
    best: Dict[str, str] = {}
    for u in urls:
        m = _MEDIA_ID_RE.search(urllib.parse.urlsplit(u).path or "")
        key = m.group(1).lower() if m else u
        if key not in best or (
            urllib.parse.urlsplit(u).netloc == "i.redd.it"
            and urllib.parse.urlsplit(best[key]).netloc != "i.redd.it"
        ):
            best[key] = u
    return list(best.values())


def _media_text(media: List[str]) -> str:
    shown = media[:_MAX_MEDIA]
    more = f" (+{len(media) - len(shown)} more)" if len(media) > len(shown) else ""
    return " · ".join(shown) + more


def _posted(attrs: Dict[str, str]) -> str:
    """``created-timestamp`` as ``2026-09-28 13:23 UTC``; empty when missing or odd."""
    raw = (attrs.get("created-timestamp") or "").strip()
    if not raw:
        return ""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            when = datetime.strptime(raw.replace("Z", "+0000"), fmt)
        except ValueError:
            continue
        return when.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return ""


_SUB_IN_PATH_RE = re.compile(r"^/r/([A-Za-z0-9_]+)", re.IGNORECASE)


def _url_subreddit(url: str) -> str:
    """``r/Name`` from a reddit URL path, or empty."""
    m = _SUB_IN_PATH_RE.match(urllib.parse.urlsplit(url or "").path or "")
    return f"r/{m.group(1)}" if m else ""


def _post_subreddit(attrs: Dict[str, str], url: str = "") -> str:
    name = (attrs.get("subreddit-prefixed-name") or "").strip()
    if name and not name.lower().startswith("r/"):
        name = f"r/{name}"
    return name or _url_subreddit(url)


def _canonical_reddit_permalink(perm: str) -> str:
    """Absolute ``https://www.reddit.com`` link. Other hosts stay as given."""
    perm = (perm or "").strip()
    if not perm:
        return ""
    if perm.startswith(("http://", "https://")):
        parts = urllib.parse.urlsplit(perm)
        host = (parts.netloc or "").lower()
        if host in ("reddit.com", "www.reddit.com", "old.reddit.com"):
            path = parts.path or "/"
            if not path.startswith("/"):
                path = "/" + path
            query = f"?{parts.query}" if parts.query else ""
            return "https://www.reddit.com" + path + query
        return perm
    if not perm.startswith("/"):
        perm = "/" + perm
    return "https://www.reddit.com" + perm


def listing_rows(html: str, url: str = "") -> List[Dict[str, str]]:
    """One dict per titled post card in a listing or feed batch.

    The row carries its ``key`` (the post id Reddit puts on the card), which is
    what ``--items`` dedupes on: the feed cursor can hand back a post the
    previous window already had, and a count that counted it twice would be a
    lie about how many posts were read.
    """
    posts = _parse_shreddit_posts(html)
    listing_sub = _url_subreddit(url)
    rows: List[Dict[str, str]] = []
    for attrs in posts:
        title = (attrs.get("post-title") or "").strip()
        if not title:
            continue
        perm = _canonical_reddit_permalink(
            attrs.get("permalink") or attrs.get("content-href") or ""
        )
        cc = (attrs.get("comment-count") or "").strip()
        score = (attrs.get("score") or attrs.get("upvote-count") or "").strip()
        author = (attrs.get("author") or "").strip()
        if author.startswith("u/"):
            author = author[2:]
        # Text body only: the whole-card fallback mixed usernames, ages, flair
        # and link domains into the snippet (F5e).
        snippet = _card_body(title, attrs.get("_body") or "", "")
        snippet, _folded = _strip_read_more(snippet)
        outbound, media, unresolved = _post_links(attrs)
        meta: List[str] = []
        flair = re.sub(r"\s+", " ", attrs.get("_flair") or "").strip()
        if flair:
            meta.append(f"Flair: {flair}")
        if _post_type(attrs):
            meta.append(f"Type: {_post_type(attrs)}")
        if _posted(attrs):
            meta.append(f"Posted: {_posted(attrs)}")
        sub = _post_subreddit(attrs)
        if sub and sub.lower() != listing_sub.lower():
            meta.append(sub)
        rows.append(
            {
                "key": (attrs.get("post-id") or "").strip() or perm or title,
                "title": title,
                "permalink": perm,
                "cc": cc,
                "score": score,
                "author": author,
                "snippet": snippet,
                "meta": " · ".join(meta),
                "outbound": outbound,
                "media": _media_text(media) if media else ("present, not resolved" if unresolved else ""),
            }
        )
    return rows


def _render_listing_rows(rows: List[Dict[str, str]]) -> str:
    """The compact index Markdown: one block per card."""
    lines: List[str] = []
    for v in rows:
        bits: List[str] = []
        if v["author"]:
            bits.append(f"/u/{v['author']}")
        if v["cc"]:
            bits.append(f"{v['cc']} comments")
        if v["score"]:
            bits.append(f"{v['score']} pts")
        suffix = f" ({', '.join(bits)})" if bits else ""
        lines.append(f"- **{v['title']}**{suffix}")
        if v["meta"]:
            lines.append(f"  {v['meta']}")
        if v["snippet"]:
            lines.append(f"  {v['snippet']}")
        if v["outbound"]:
            lines.append(f"  Outbound: {v['outbound']}")
        if v["media"]:
            lines.append(f"  Media: {v['media']}")
        if v["permalink"]:
            lines.append(f"  [`permalink`]({v['permalink']})")
        lines.append("")
    return "\n".join(lines).strip()


def _render_comment_rows(rows: List[Dict[str, str]]) -> str:
    """The same block shape for a comment card, which has no title of its own."""
    lines: List[str] = []
    for v in rows:
        suffix = f" ({v['meta']})" if v["meta"] else ""
        lines.append(f"- **Comment**{suffix}")
        if v["snippet"]:
            lines.append(f"  {v['snippet']}")
        if v["permalink"]:
            lines.append(f"  [`permalink`]({v['permalink']})")
        lines.append("")
    return "\n".join(lines).strip()


def parse_reddit_listing_html(html: str, url: str = "") -> Optional[str]:
    """If >=2 shreddit-post nodes have non-empty post-title, return compact MD index.

    Permalinks are normalized to absolute https://www.reddit.com/... form.
    comment-count and score appear when present. The full card body sits under
    the title when the light DOM has one. Returns None for <2 titled posts.

    When a URL is supplied, this returns None for thread URLs (/comments/) or .json URLs
    even if the HTML contains shreddit-post nodes (threads fall through; JSON ring owns .json).
    A Reddit feed-batch URL (``/svc/shreddit/…-more-posts/…``) is a listing: it
    carries the same cards and the next cursor (F5f).

    Does not change _render_subreddit_from_children output.
    Markdown print format only.
    """
    if url and not is_feed_html_url(url):
        return None
    rows = listing_rows(html, url)
    if len(rows) < 2:
        return None
    return _render_listing_rows(rows)


def count_titled_shreddit_posts(html: str) -> int:
    """Count shreddit-post nodes that carry a non-empty post-title attr."""
    posts = _parse_shreddit_posts(html)
    return sum(1 for a in posts if (a.get("post-title") or "").strip())


_COMMENT_CHROME_RE = re.compile(
    r"\b(?:"
    r"Share|Award|Give Award|Hide|Reply|Report|"
    r"More replies|More reply|"
    r"Just now|"
    r"Top \d+% Commenter"
    r")\b"
    r"|\b\d+\s*[smhdwy]\s+ago\b"
    r"|[•·]",
    re.IGNORECASE,
)


def _comment_body(author: str, body: str, all_text: str) -> str:
    """Own comment text. Prefers ``slot="comment"``; else leftover own-text.

    Chrome stripping is only for the light-DOM fallback, so a real comment
    can say "I'll reply" or "please share".
    """
    slot = (body or "").strip()
    if slot:
        return re.sub(r"\s+", " ", slot).strip()
    text = re.sub(r"\s+", " ", (all_text or "")).strip()
    if not text:
        return ""
    text = _COMMENT_CHROME_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" •·-|,")
    a = (author or "").strip()
    if a.lower().startswith("u/"):
        a = a[2:]
    if a and text.lower().startswith(a.lower()):
        text = text[len(a) :].lstrip(" •·-|,")
    text = re.sub(r"^OP\b\s*", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip(" •·-|,")


def _parse_shreddit_comments(html: str) -> List[Dict[str, str]]:
    """Every shreddit-comment as its own node, own text only, with nest depth.

    Nested replies are nested ``<shreddit-comment>`` tags. Emitting only at
    depth 0 mashed those replies into the parent blob.
    """

    class _P(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.comments: List[Dict[str, Any]] = []
            self._stack: List[Dict[str, Any]] = []
            self._skip = 0

        def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
            t = tag.lower()
            if t in _SKIP_TAGS:
                self._skip += 1
            ad = {str(k).lower(): (v or "") for k, v in attrs}
            if t == "shreddit-comment":
                node: Dict[str, Any] = dict(ad)
                node["_depth"] = str(len(self._stack))
                node["_all"] = []
                node["_body_parts"] = []
                node["_body_depth"] = 0
                self._stack.append(node)
                self.comments.append(node)
                return
            if not self._stack:
                return
            if t in _VOID_TAGS:
                return
            cur = self._stack[-1]
            if cur["_body_depth"]:
                cur["_body_depth"] += 1
            elif ad.get("slot", "").lower() == "comment":
                cur["_body_depth"] = 1

        def handle_endtag(self, tag: str) -> None:
            t = tag.lower()
            if t in _SKIP_TAGS:
                self._skip = max(0, self._skip - 1)
            if t in _VOID_TAGS:
                return
            if self._stack:
                cur = self._stack[-1]
                if cur["_body_depth"]:
                    cur["_body_depth"] -= 1
            if t == "shreddit-comment" and self._stack:
                self._finish(self._stack.pop())

        def handle_data(self, data: str) -> None:
            if not self._stack or self._skip:
                return
            s = data.strip()
            if not s:
                return
            cur = self._stack[-1]
            cur["_all"].append(s)
            if cur["_body_depth"]:
                cur["_body_parts"].append(s)

        def _finish(self, node: Dict[str, Any]) -> None:
            if "_text" in node:
                return
            node["_text"] = " ".join(node.pop("_all", []))
            node["_body"] = " ".join(node.pop("_body_parts", []))
            node.pop("_body_depth", None)

    p = _P()
    try:
        p.feed(html or "")
    except Exception:  # noqa: BLE001
        pass
    while p._stack:
        p._finish(p._stack.pop())
    out: List[Dict[str, str]] = []
    keep = {"_text", "_body", "_depth"}
    for n in p.comments:
        out.append(
            {str(k): str(v) for k, v in n.items() if not str(k).startswith("_") or k in keep}
        )
    return out


#: Comment bodies shorter than this are chrome, not a comment.
_COMMENT_MIN_CHARS = 8


def _row_ceiling() -> int:
    """How many rows any Reddit read may print. The knobs answer (F23e, F5f).

    A post card, a comment and a search result are all rows, and ``--items`` /
    ``SEARCHTS_MAX_ITEMS`` is what the user caps rows with. Every cap in this
    file reads this, so there is one number to lower and nothing here can raise
    it: a plain read and an ``--expand`` read take the same rows, and the flag
    decides whether searchts goes and *gets* more (see :func:`expand_more`)
    rather than deciding how many count.

    The old literals are gone rather than kept as a floor. A hidden second
    ceiling was a lie about the request: ``--items 250`` printed
    ``[items: asked for 250, the ceiling is 300]`` and then handed back 30
    comments with no note saying 30 was the real limit. Reddit reports how many
    comments a thread has, so every shortfall is still printed - the ceiling
    bounds the payload, it never hides the number.

    Resolved only on the paths that need it, so an ordinary read pays no config
    read. A broken config is answered by the built-in default, never an error
    (:mod:`searchts.knobs` swallows it for exactly this reason).
    """
    from searchts import knobs

    return max(1, int(knobs.resolve().items))


#: Where Reddit hides the rest of a thread. A ``faceplate-partial`` that answers
#: a POST with a minted cursor; clicking it is what loads the next layer.
_MORE_COMMENTS_SELECTOR = "faceplate-partial.more-comments-partial"
_TOP_LEVEL_MORE_SELECTOR = "faceplate-partial#top-level-more-comments-partial"

#: Reddit archived this post (its text is gone; comments may remain). The
#: signal is the ``archived`` attribute on the post element itself, and nothing
#: else. The words "Archived post. New comments cannot be posted" do sit on every
#: archived page, but they sit anywhere too, and Reddit serves threads *about*
#: archiving: measured live 2026-10-17 on r/NoStupidQuestions 1x4uke7, a post
#: whose own body quotes that phrase because its author was reading one. The
#: phrase said "Its text is not available" and the next line printed the text
#: (``tests/fixtures/reddit_post_quoting_archived.html``). A page that mentions
#: the words is not archived; the element is what says so.
_OP_TAG_RE = re.compile(r"<shreddit-post\b[^>]*>", re.IGNORECASE)
_ARCHIVED_ATTR = "archived"
_POST_TITLE_ATTR = "post-title"


def _op_is_archived(html: str) -> bool:
    """True when the OP element itself carries Reddit's ``archived`` attribute.

    Both attributes are required: ``archived`` alone also rides the post cards
    in a community's "more posts" strip, and ``post-title`` alone is every
    readable post. The element that has both is the post a thread URL is about.
    """
    for tag in _OP_TAG_RE.findall(html or ""):
        names = {k.lower() for k, _v in _attrs_of(tag)}
        if _ARCHIVED_ATTR in names and _POST_TITLE_ATTR in names:
            return True
    return False


def _has_titled_post(html: str) -> bool:
    """True when the page carries at least one post element with a title."""
    return any(
        _POST_TITLE_ATTR in {k.lower() for k, _v in _attrs_of(tag)}
        for tag in _OP_TAG_RE.findall(html or "")
    )


def _comment_body_count(html: str) -> int:
    """Comments in ``html`` that carry their own text (not chrome)."""
    return sum(
        1
        for c in _parse_shreddit_comments(html)
        if len(_comment_body(c.get("author") or "", c.get("_body") or "", c.get("_text") or ""))
        >= _COMMENT_MIN_CHARS
    )


def parse_reddit_thread_html(
    html: str, url: str = "", max_comments: Optional[int] = None
) -> Optional[str]:
    """OP plus a bounded comment tree from thread HTML. None if there is no titled post.

    Nested ``shreddit-comment`` nodes are indented entries, not mashed into the parent.

    ``max_comments`` is the caller's ceiling. Left out, it is the user's rows
    knob (``SEARCHTS_MAX_ITEMS``, :func:`_row_ceiling`), resolved at call time
    rather than at import: a literal default here was frozen before the user's
    environment was read, so a lowered ceiling could not lower a read that
    forgot to pass one. Whatever the cap is, the thread says how many comments
    Reddit reports, how many came back, and how many the cap cut (F5f).
    """
    if url and not is_reddit_thread_url(url):
        return None
    posts = _parse_shreddit_posts(html)
    op = next((a for a in posts if (a.get("post-title") or "").strip()), None)
    if op is None:
        return None
    archived = _ARCHIVED_ATTR in op
    title = (op.get("post-title") or "").strip()
    author = (op.get("author") or "").strip()
    if author.startswith("u/"):
        author = author[2:]
    score = (op.get("score") or op.get("upvote-count") or "").strip()
    cc = (op.get("comment-count") or "").strip()
    perm = _canonical_reddit_permalink(op.get("permalink") or op.get("content-href") or "")
    # Text body only, never the whole card. Reddit ships the full post even when
    # "Read more" shows (a CSS clamp, checked on saved threads), so the label is
    # dropped with no truncation note (F5e).
    body = _card_body(title, op.get("_body") or "", "", require_min=False)
    body, _folded = _strip_read_more(body)
    outbound, media, unresolved = _post_links(op)
    subreddit = _post_subreddit(op, url)
    flair = re.sub(r"\s+", " ", op.get("_flair") or "").strip()

    lines: List[str] = [f"# {title}", ""]
    if archived:
        # Said at the top, next to the title, because the body is simply not
        # there and a reader would otherwise assume this post was always empty.
        lines.append("**Post:** archived by Reddit. Its text is not available.")
        lines.append("")
    if author:
        lines.append(f"**OP:** /u/{author}")
    if subreddit:
        lines.append(f"**Subreddit:** {subreddit}")
    if flair:
        lines.append(f"**Flair:** {flair}")
    if _post_type(op):
        lines.append(f"**Type:** {_post_type(op)}")
    if _posted(op):
        lines.append(f"**Posted:** {_posted(op)}")
    if score:
        lines.append(f"**Score:** {score}")
    if cc:
        lines.append(f"**Comments:** {cc}")
    if perm:
        lines.append(f"**Link:** {perm}")
    if outbound:
        lines.append(f"**Outbound:** {outbound}")
    if media:
        lines.append(f"**Media:** {_media_text(media)}")
    elif unresolved:
        lines.append("**Media:** present, not resolved")
    if body:
        lines.extend(["", body])

    comments = _parse_shreddit_comments(html)
    cap = max(1, int(max_comments or _row_ceiling()))
    shown = 0
    in_page = 0
    comment_block: List[str] = []
    for c in comments:
        c_author = (c.get("author") or "[deleted]").strip()
        if c_author.startswith("u/"):
            c_author = c_author[2:]
        text = _comment_body(c_author, c.get("_body") or "", c.get("_text") or "")
        if len(text) < _COMMENT_MIN_CHARS:
            continue
        in_page += 1
        if shown >= cap:
            continue
        c_score = (c.get("score") or "").strip()
        try:
            depth = max(0, int(c.get("_depth") or "0"))
        except ValueError:
            depth = 0
        indent = "  " * depth
        header = f"{indent}**/u/{c_author}**"
        if c_score:
            header += f" ({c_score} pts)"
        comment_block.append(header)
        comment_block.append(f"{indent}{text}")
        comment_block.append("")
        shown += 1
    notes: List[str] = []
    if in_page > shown:
        notes.append(
            f"[truncated: {in_page - shown} more comments in the page were cut at the "
            f"{cap}-comment cap]"
        )
    claimed = int(cc) if cc.isdigit() else 0
    if claimed > in_page:
        if archived:
            # The OP is gone; what is left is the comment tree Reddit kept.
            notes.append(
                f"[removed: this post is archived on Reddit; its text is not "
                f"available. The {in_page} comments below are what remains]"
            )
        notes.append(
            f"[partial: Reddit reports {claimed} comments; {in_page} were in the page. "
            "Collapsed or not-yet-loaded replies are not included]"
        )
    if comment_block or notes:
        lines.extend(["", "## Comments", ""])
        lines.extend(comment_block)
        lines.extend(notes)
    return "\n".join(lines).strip()


def expand_more(page, want: int, clicks: int, tick=None) -> None:
    """Open Reddit's own "more replies" controls until the page holds ``want``
    comments, or Reddit stops giving more.

    Only ever called when the caller asked for deeper comments (F5f, riding the
    opt-in ``--expand`` bool from F23d). Each round scrolls every
    ``more-comments-partial`` into view and clicks it, which is what the page does
    for a person; it stops on the wanted count, on a round that added nothing
    (Reddit's "no more" answer), or on the round cap, and never raises.

    Both numbers arrive from the knobs (:mod:`searchts.knobs`) through
    :func:`unlocker._expand_known_host`, and neither has a default here:
    ``want`` is the row ceiling (``SEARCHTS_MAX_ITEMS``) and ``clicks`` the press
    budget (``SEARCHTS_MAX_EXPAND_CLICKS``). A default in this signature would be
    a second answer to "how many" that no knob could lower. ``tick`` is the
    caller's stderr narrator; each round waits on the network, so a loop that can
    sit for many seconds says so (P4.6). Nothing is printed from inside here.
    """
    want = max(1, int(want or 1))
    clicks = max(1, int(clicks or 1))
    for round_no in range(1, clicks + 1):
        try:
            html = page.content()
        except Exception:  # noqa: BLE001 - a mid-navigation page is not a reason to fail a read
            return
        had = _comment_body_count(html)
        if had >= want:
            return
        controls = list(page.query_selector_all(_MORE_COMMENTS_SELECTOR)) + list(
            page.query_selector_all(_TOP_LEVEL_MORE_SELECTOR)
        )
        if not controls:
            return
        if tick is not None:
            tick(
                f"  reddit: opening {len(controls)} more-replies control(s) "
                f"(round {round_no} of {clicks})"
            )
        before = len(html)
        for control in controls:
            try:
                control.scroll_into_view_if_needed(timeout=1500)
                control.click(timeout=1500, force=True)
            except Exception:  # noqa: BLE001 - one dead control is not a failed expand
                continue
        try:
            page.wait_for_timeout(3000)
        except Exception:  # noqa: BLE001 - missing API in a stub
            return
        try:
            after = page.content()
        except Exception:  # noqa: BLE001
            return
        if len(after) <= before and _comment_body_count(after) <= had:
            return  # stalled: Reddit is not handing over another layer


# ── F5f: the feed cursor ─────────────────────────────────────────────────────

_TAG_RE = re.compile(r"<faceplate-partial\b[^>]*>", re.IGNORECASE)


def next_batch_url(html: str, base: str = "https://www.reddit.com/") -> str:
    """Reddit's own next-feed cursor from a listing or profile page.

    Reddit ships it as ``faceplate-partial[slot="load-after"]`` with a relative
    ``src`` under ``/svc/shreddit/``; each batch carries the next one, so the
    walk is a chain rather than a page number. ``--items`` follows it with curl
    after the first page, exactly as F23b follows ``rel=next`` elsewhere.

    Only Reddit's own host is accepted. The cursor arrives in the page's markup
    and then travels as a ``next_url`` an agent can act on, so a src pointing
    anywhere else is dropped rather than passed on (SSRF guard still runs on it
    in ``fetch``; this is the narrower, earlier check).
    """
    for tag in _TAG_RE.findall(html or ""):
        attrs = {str(k).lower(): v for k, v in _attrs_of(tag)}
        if (attrs.get("slot") or "").lower() != "load-after":
            continue
        src = html_lib.unescape((attrs.get("src") or "").strip())
        if not src:
            continue
        absolute = urllib.parse.urljoin(base, src)
        if _host_of(absolute) in REDDIT_HOSTS and is_reddit_batch_url(absolute):
            return absolute
    return ""


def _attrs_of(tag: str) -> List[Tuple[str, str]]:
    """``name=value`` pairs of one start tag, as an HTMLParser would see them."""

    class _A(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.pairs: List[Tuple[str, str]] = []

        def handle_starttag(self, _t: str, attrs: Any) -> None:
            for k, v in attrs:
                self.pairs.append((str(k), v or ""))

    p = _A()
    try:
        p.feed(tag)
    except Exception:  # noqa: BLE001 - malformed markup means no attributes
        return []
    return p.pairs


# ── F5f: profiles and search, as cards ───────────────────────────────────────


def _profile_user(url: str) -> str:
    m = re.match(r"^/user/([A-Za-z0-9_-]+)", _path_of(url))
    return m.group(1) if m else ""


def _testid_text(html: str, testid: str) -> str:
    """The text inside the first element carrying ``data-testid``."""
    m = re.search(
        rf'data-testid="{re.escape(testid)}"[^>]*>(.*?)</', html, re.DOTALL | re.IGNORECASE
    )
    if not m:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()


def _testid_attr(html: str, testid: str, attr: str) -> str:
    """One attribute of the first element carrying ``data-testid``."""
    m = re.search(
        rf'<(\w[\w-]*)[^>]*data-testid="{re.escape(testid)}"[^>]*>', html, re.IGNORECASE
    )
    if not m:
        return ""
    pairs = dict((str(k).lower(), v or "") for k, v in _attrs_of(m.group(0)))
    return (pairs.get(attr.lower()) or "").strip()


#: ``2005-06-06T00:00:00.000Z`` as ``2005-06-06``.
def _iso_date(raw: str) -> str:
    return (raw or "")[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", raw or "") else ""


_PROFILE_COMMENT_RE = re.compile(r"<shreddit-profile-comment\b([^>]*)>", re.IGNORECASE)
_COMMENT_BODY_RE = re.compile(
    r'id="-post-rtjson-content"[^>]*>(.*?)</div>\s*</div>', re.DOTALL | re.IGNORECASE
)


def _profile_comment_cards(html: str) -> List[Dict[str, str]]:
    """One card per recent comment on a profile overview.

    Reddit renders these as ``shreddit-profile-comment``: the thread link and the
    comment id on the tag, the moment in a ``faceplate-timeago``, and the text in
    ``div#-post-rtjson-content``. Read from the saved page rather than from the
    rendered text, because the credit bar also carries the avatar and the badges.
    """
    out: List[Dict[str, str]] = []
    starts = [m.start() for m in _PROFILE_COMMENT_RE.finditer(html or "")]
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(html or "")
        chunk = (html or "")[start:end]
        attrs = {str(k).lower(): v for k, v in _attrs_of(chunk[: chunk.find(">") + 1] or "<x>")}
        body = _COMMENT_BODY_RE.search(chunk)
        text = ""
        if body:
            text = re.sub(
                r"\s+", " ", re.sub(r"<[^>]+>", " ", html_lib.unescape(body.group(1)))
            ).strip()
        if len(text) < _COMMENT_MIN_CHARS:
            continue
        ts = re.search(r'<faceplate-timeago\b[^>]*\bts="([^"]+)"', chunk)
        out.append(
            {
                "key": (attrs.get("comment-id") or "").strip() or text[:60],
                "title": "",
                "permalink": _canonical_reddit_permalink(attrs.get("href") or ""),
                "cc": "",
                "score": "",
                "author": "",
                "snippet": text,
                "meta": _iso(ts.group(1)) if ts else "",
                "outbound": "",
                "media": "",
            }
        )
    return out


def _iso(raw: str) -> str:
    """``2026-08-05T18:31:50.140000+0000`` as ``2026-08-05 18:31 UTC``."""
    if not raw:
        return ""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            when = datetime.strptime(raw.replace("Z", "+0000"), fmt)
        except ValueError:
            continue
        return when.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return ""


def profile_card(html: str, url: str = "") -> str:
    """A profile overview as cards: who the account is, then its recent posts
    and comments. Empty string when the page holds no such cards.

    "Cards or a loud failure" (F5f): a profile whose cards cannot be read must
    not come back as navigation chrome that reads like an answer.
    """
    user = _profile_user(url)
    posts = listing_rows(html, url)
    comments = _profile_comment_cards(html)
    if not posts and not comments:
        return ""
    lines: List[str] = []
    if user:
        lines += [f"# /u/{user}", ""]
    karma = _testid_text(html, "karma-number")
    contributions = _testid_text(html, "contribution-count")
    # The date lives in the <time datetime> the testid sits on; the visible text
    # is the age ("21 y"), which alone does not say when the account started.
    cake_iso = _iso_date(_testid_attr(html, "cake-day", "datetime"))
    cake_age = _testid_text(html, "cake-day")
    description = _testid_text(html, "profile-description")
    if karma:
        lines.append(f"**Karma:** {karma}")
    if contributions:
        lines.append(f"**Contributions:** {contributions}")
    if cake_iso:
        lines.append(f"**Cake day:** {cake_iso}" + (f" ({cake_age} ago)" if cake_age else ""))
    if description:
        lines.append(f"**Bio:** {description}")
    if posts:
        lines += ["", f"## Posts ({len(posts)})", ""]
        lines.append(_render_listing_rows(posts))
    if comments:
        lines += ["", f"## Comments ({len(comments)})", ""]
        lines.append(_render_comment_rows(comments))
    return "\n".join(lines).strip()


#: A search result. Reddit's own telemetry JSON carries title, author, subreddit
#: and the snippet, so the card is read from the attributes rather than scraped
#: out of the rendered text.
_SEARCH_CARD_RE = re.compile(
    r'<search-telemetry-tracker\b([^>]*data-thingid="[^"]+"[^>]*)>', re.IGNORECASE
)
_SEARCH_LINK_RE = re.compile(r'<a\b[^>]*data-testid="post-title"[^>]*href="([^"]+)"', re.IGNORECASE)
_SEARCH_NUMBER_RE = re.compile(r'<faceplate-number\b[^>]*\bnumber="([\d,]+)"', re.IGNORECASE)
_SEARCH_TS_RE = re.compile(r'<faceplate-timeago\b[^>]*\bts="([^"]+)"', re.IGNORECASE)


def _tracking_json(chunk: str) -> Dict[str, Any]:
    """The first ``data-faceplate-tracking-context`` in ``chunk``, decoded."""
    m = re.search(r'data-faceplate-tracking-context="([^"]*)"', chunk)
    if not m:
        return {}
    try:
        out = json.loads(html_lib.unescape(m.group(1)))
    except (ValueError, TypeError):
        return {}
    return out if isinstance(out, dict) else {}


def _section(ctx: Dict[str, Any], key: str) -> Dict[str, Any]:
    """One nested object of a telemetry payload, or ``{}`` when it is not one."""
    value = ctx.get(key)
    return value if isinstance(value, dict) else {}


def search_cards(html: str) -> List[Dict[str, str]]:
    """One card per search result, in the order Reddit listed them."""
    out: List[Dict[str, str]] = []
    starts = [m.start() for m in _SEARCH_CARD_RE.finditer(html or "")]
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(html or "")
        chunk = (html or "")[start:end]
        tag = (html or "")[start : (html or "").find(">", start) + 1]
        attrs = {str(k).lower(): v for k, v in _attrs_of(tag)}
        ctx = _tracking_json(chunk)
        post = _section(ctx, "post")
        profile = _section(ctx, "profile")
        community = _section(ctx, "subreddit")
        search = _section(ctx, "search")
        title = str(post.get("title") or "").strip()
        link = _SEARCH_LINK_RE.search(chunk)
        perm = _canonical_reddit_permalink(
            (link.group(1) if link else attrs.get("data-thingid") or "")
        )
        thing = (attrs.get("data-thingid") or "").strip()
        if not title or not perm or not thing:
            continue
        numbers = _SEARCH_NUMBER_RE.findall(chunk)
        flags: List[str] = []
        if post.get("nsfw"):
            flags.append("nsfw")
        if post.get("spoiler"):
            flags.append("spoiler")
        if community.get("quarantined"):
            flags.append("quarantined")
        meta: List[str] = []
        if community.get("name"):
            meta.append(f"r/{community['name']}")
        if profile.get("name"):
            meta.append(f"/u/{profile['name']}")
        ts = _SEARCH_TS_RE.search(chunk)
        if ts:
            meta.append(_iso(ts.group(1)))
        if numbers:
            meta.append(f"{numbers[0]} pts")
        if len(numbers) > 1:
            meta.append(f"{numbers[1]} comments")
        if flags:
            meta.append(" · ".join(flags))
        out.append(
            {
                "key": thing,
                "title": title,
                "permalink": perm,
                "cc": "",
                "score": "",
                "author": "",
                "snippet": str(search.get("snippet") or "").strip(),
                "meta": " · ".join(meta),
                "outbound": "",
                "media": "",
            }
        )
    return out


def search_card(html: str) -> str:
    """A Reddit search page as cards. Empty string when there are no results."""
    rows = search_cards(html)
    if not rows:
        return ""
    return "\n".join(["## Results", ""] + [_render_listing_rows([r]) for r in rows]).strip()


# ── F5f: the states a Reddit page can be in ───────────────────────────────────

#: Reddit's interstitial for a community it will not serve: private, banned,
#: quarantined. All three render as ``<guard-community-modal>`` with a title
#: that names the state, measured on saved pages (private_gryffindor,
#: banned_random, quarantine_incest).
_GUARD_MODAL_RE = re.compile(
    r"<guard-community-modal\b[^>]*>(.*?)</guard-community-modal>", re.IGNORECASE | re.DOTALL
)
_GUARD_TITLE_RE = re.compile(r'<div\b[^>]*\bslot="title"[^>]*>(.*?)</div>', re.IGNORECASE | re.DOTALL)

_STATE_NOT_FOUND = "reddit-community-not-found"
_STATE_POST_GONE = "reddit-post-gone"
_STATE_ARCHIVED = "reddit-post-archived"
_STATE_NSFW = "reddit-nsfw-gate"
#: Reddit's "Prove your humanity" interstitial. Measured 2026-10-17: HTTP 200,
#: a reCAPTCHA mount, and **zero** post cards, on a direct request for a
#: next-batch cursor. The same URL returned 24 cards to the browser rung in the
#: same minute, because Reddit decides this from the browser's persistent
#: profile. Without this state a batch of that kind reads as an empty feed,
#: which is the one answer that is both wrong and unfalsifiable from the page.
_STATE_CHALLENGE = "reddit-challenge"

_CHALLENGE_RE = re.compile(
    # The interstitial's own title, and nothing looser. Both saved copies
    # (2026-10-17, 3.4 KB trimmed and 167 KB raw) carry exactly this title, and
    # a thread whose *comments* quote the words is a thread about Reddit's
    # captcha, not a captcha: matching the bare phrase anywhere would fail a
    # readable page loudly, which is the one error this file must not make.
    r"<title>\s*reddit\s*-\s*prove your humanity\s*</title>",
    re.IGNORECASE,
)

# The same rule for the other three notices: the element Reddit puts them in,
# never the words alone. Every one of these strings is also something a readable
# Reddit page can carry in a comment or in a post's own body, because Reddit has
# threads about all four (one of them fetched live for this: a post quoting the
# archived notice in its selftext). Matching the bare string anywhere turns a
# thread about a wall into a wall.
_COMMUNITY_ERROR_RE = re.compile(
    r'<[a-z][\w-]*\b[^>]*\bclass="[^"]*\bsubreddit-content-error\b', re.IGNORECASE
)
_FORBIDDEN_RE = re.compile(r'<[a-z][\w-]*\b[^>]*\bid="shreddit-forbidden"', re.IGNORECASE)
#: The over-18 notice is a heading on a search page. A result snippet is a
#: ``<div>``, so a search page that merely *mentions* the sentence in a result
#: does not match this.
_NSFW_GATE_RE = re.compile(
    r"<h[12]\b[^>]*>(?:(?!</h[12]>).)*?NSFW search results are hidden",
    re.IGNORECASE | re.DOTALL,
)

#: Every state the page names about itself, in the order they are checked. The
#: reason is what the ladder reports, so it says which one it was.
_STATES = (
    ("is quarantined", "reddit-quarantined"),
    ("is private", "reddit-private"),
    ("is banned", "reddit-banned"),
)


def page_state(url: str, html: str) -> str:
    """The wall this page IS, or ``""`` when it is a page with content in it.

    Measured states and the copy that names them, from saved pages:

    - ``reddit-private``        ``r/Gryffindor is private`` (/r/gryffindor/)
    - ``reddit-banned``         ``r/random is banned`` (/r/Random/)
    - ``reddit-quarantined``    ``r/incest is quarantined.`` (/r/incest/)
    - ``reddit-community-not-found``
      ``Sorry, there aren't any communities on Reddit with that name.`` (/r/nsfw/)
    - ``reddit-post-gone``      ``Page not found`` on a comment URL
    - ``reddit-archived``       ``Archived post.`` on the OP of a removed post
    - ``reddit-nsfw-gate``      ``NSFW search results are hidden`` on a search
    - ``reddit-challenge``      ``<title>Reddit - Prove your humanity</title>``,
      served on HTTP 200 to a request the browser's profile does not vouch for

    A page that states one of these is not content, so it is reported as itself
    and the ladder keeps going rather than handing back the nav bar as a read.
    """
    text = html or ""
    for phrase, state in _STATES:
        if phrase not in text:
            continue
        for modal in _GUARD_MODAL_RE.findall(text):
            title = _GUARD_TITLE_RE.search(modal)
            if title and phrase in title.group(1).lower():
                return state
    if _CHALLENGE_RE.search(text):
        return _STATE_CHALLENGE
    # The two "this is not here" wrappers only count on a page with nothing in
    # it. A thread that explains the wrapper carries the class name and the id,
    # and it has a post of its own; a page Reddit refused has no post element at
    # all (checked on every wall fixture saved here). The cheap element match
    # runs first, so the scan for a post element is only spent on a page that
    # already looks like one of these walls.
    if _COMMUNITY_ERROR_RE.search(text) and not _has_titled_post(text):
        return _STATE_NOT_FOUND
    if _FORBIDDEN_RE.search(text) and not _has_titled_post(text):
        return _STATE_POST_GONE
    if _op_is_archived(text):
        return _STATE_ARCHIVED
    if _NSFW_GATE_RE.search(text):
        return _STATE_NSFW
    return ""


def state_note(state: str, url: str = "") -> str:
    """The one sentence that says what this wall is, and the next step if any.

    Only the two notices a *person* has to accept get the ``--human`` line: that
    rung opens a browser for the caller to click through, and nothing else here
    has a step a person can take.
    """
    what = {
        "reddit-private": "this community is private; only members approved by its "
        "moderators can read it, and there is no public page to fetch",
        "reddit-banned": "Reddit has banned this community; the page is a notice, "
        "not the community",
        "reddit-quarantined": "Reddit has quarantined this community; a person has "
        "to accept the notice before Reddit will serve it",
        _STATE_NOT_FOUND: "Reddit has no community at this name; it was renamed, "
        "banned or deleted",
        _STATE_POST_GONE: "this post is not on Reddit; it was deleted, removed, or "
        "never existed",
        _STATE_ARCHIVED: "Reddit archived this post; its text is gone",
        _STATE_NSFW: "Reddit hides these results behind an over-18 notice; a person "
        "has to accept it",
        "reddit-no-posts": "Reddit's next-batch cursor came back with no posts, so "
        "the feed ended there",
        _STATE_CHALLENGE: "Reddit answered with its 'Prove your humanity' check on "
        "this request. Whether a page gets that depends on the browser profile's "
        "standing with Reddit, so the same URL may read on a warm profile and be "
        "challenged on a fresh one",
    }.get(state, "")
    if not what:
        return ""
    if state in ("reddit-quarantined", _STATE_NSFW) and url:
        return f"{what}. Run: searchts read {url} --human"
    return what


# ── the HTML entry point ─────────────────────────────────────────────────────


@dataclass
class RedditPage:
    """One Reddit page read out of HTML the ladder already downloaded.

    Either ``markdown`` (the read) or ``failure`` (the wall this page is), never
    both. ``next_url`` is Reddit's own cursor when the page is longer than this
    read; ``more`` mirrors that as notes and structured entries.
    """

    label: str
    markdown: str
    next_url: Optional[str] = None
    more: List[Dict[str, str]] = field(default_factory=list)
    keys: List[str] = field(default_factory=list)
    failure: Optional[str] = None

    def as_dicts(self) -> List[Dict[str, str]]:
        return [dict(m) for m in self.more]


def _more(kind: str, note: str, url: str = "") -> Dict[str, str]:
    out: Dict[str, str] = {"kind": kind, "note": note}
    if url:
        out["url"] = url
    return out


def extract_page(url: str, html: str) -> Optional[RedditPage]:
    """Render an already-downloaded Reddit page, or name the wall it is.

    No knobs are read here and no ``expand`` flag is passed in: the rows a read
    may print are :func:`_row_ceiling` wherever they come from, and whether
    searchts goes and opens Reddit's "more replies" controls is the ladder's
    decision about the browser, not the parser's (F5f, riding F23d's ``--expand``
    **bool**; the ring owns the selectors, :mod:`searchts.knobs` owns the
    numbers). A thread this is handed has whatever comments Reddit put in the
    page, and says how many that was against how many the page claims.

    JSON URLs return None: they belong to :func:`extract_known`, and a URL this
    does not recognise is not a Reddit page, so the ladder owns it unchanged
    (fail-open).
    """
    state = page_state(url, html)
    if state and state != _STATE_ARCHIVED:
        return RedditPage(label=f"reddit: {state}", markdown="", failure=state)
    kind = page_kind(url)
    if kind in ("listing", "batch"):
        return _listing_page(url, html, batch=(kind == "batch"))
    if kind == "thread":
        return _thread_page(url, html)
    if kind == "profile":
        return _profile_page(url, html)
    if kind == "search":
        return _search_page(url, html, state)
    return None


def _listing_page(url: str, html: str, batch: bool) -> Optional[RedditPage]:
    rows = listing_rows(html, url)
    # A profile feed mixes post cards and comment cards; both are content, so
    # both are rendered. A community feed is posts only.
    comments = _profile_comment_cards(html) if is_reddit_profile_batch_url(url) else []
    if len(rows) + len(comments) < 2:
        if not batch:
            # A community page with no cards is not a batch Reddit handed us; it
            # is a page this parse cannot read, and F5c's rule stands: fall
            # through to the ladder rather than invent a failure.
            return None
        # A batch, on the other hand, is only ever reached by following a cursor
        # this ring printed, so an empty one means the feed is over and must say
        # so instead of reading as an empty page.
        return RedditPage(
            label="listing-batch: no posts",
            markdown="",
            failure="reddit-no-posts",
        )
    md = _render_listing_rows(rows)
    if comments:
        md = "\n\n".join([md, "### Comments", _render_comment_rows(comments)]).strip()
    label = f"listing-{'batch' if batch else 'html'}: {len(rows) + len(comments)} posts"
    page = RedditPage(
        label=label,
        markdown=md,
        keys=[r["key"] for r in rows + comments],
    )
    nxt = next_batch_url(html)
    if nxt:
        page.next_url = nxt
        page.more.append(
            _more(
                "next-page",
                # The count is the page just read, never the batch behind the
                # cursor: that one is Reddit's, and saying otherwise is a number
                # we do not have. Measured 2026-10-17 on /r/MachineLearning/hot
                # (artifacts f5f/r3/r3_listing_items): page one holds 3 cards,
                # the cursor it printed went on to serve 24, and the note said
                # "another 3-post batch".
                f"[more: after these {len(rows) + len(comments)} cards, Reddit's "
                f"own cursor for the next batch of this feed is {nxt}]",
                nxt,
            )
        )
    elif batch:
        # The cursor came back with no next one: this is the end of the feed.
        page.more.append(_more("count", "[page says: the last batch of this feed]"))
    else:
        page.more.append(
            _more(
                "count",
                f"[page says: {len(rows) + len(comments)} posts, and no further "
                "batch cursor. Reddit serves the rest of this feed by scrolling, "
                "which needs the browser: searchts install --browser]",
            )
        )
    return page


def _thread_page(url: str, html: str) -> Optional[RedditPage]:
    md = parse_reddit_thread_html(html, url, max_comments=_row_ceiling())
    if not md:
        # No titled post in a page that was fetched as a thread URL is not a
        # state Reddit named; it is a page this parse could not read (a bot
        # interstitial, a login page, a half-loaded document). Falling through
        # leaves the ladder to say which, instead of claiming one on its behalf.
        return None
    page = RedditPage(label="thread-html: op", markdown=md)
    for line in md.splitlines():
        if line.startswith("[truncated:"):
            page.more.append(_more("count", line))
        elif line.startswith("[partial:"):
            page.more.append(_more("partial", line))
        elif line.startswith("[removed:"):
            page.more.append(_more("removed", line))
    return page


def _profile_page(url: str, html: str) -> RedditPage:
    md = profile_card(html, url)
    if not md:
        return RedditPage(
            label="profile-html: no cards",
            markdown="",
            failure="reddit-profile-empty",
        )
    keys = [r["key"] for r in listing_rows(html, url)] + [
        r["key"] for r in _profile_comment_cards(html)
    ]
    page = RedditPage(label="profile-html: cards", markdown=md, keys=keys)
    nxt = next_batch_url(html)
    if nxt:
        page.next_url = nxt
        page.more.append(
            _more(
                "next-page",
                f"[more: this profile has more history after these cards; it is {nxt}]",
                nxt,
            )
        )
    return page


def _search_page(url: str, html: str, state: str) -> RedditPage:
    rows = search_cards(html)
    md = search_card(html)
    if not md:
        # An NSFW search is a notice, not a result list, and must not be
        # answered with the nav bar.
        if state == _STATE_NSFW:
            return RedditPage(label=f"reddit: {state}", markdown="", failure=state)
        return RedditPage(
            label="search-html: no results",
            markdown="",
            failure="reddit-search-empty",
        )
    page = RedditPage(
        label="search-html: cards", markdown=md, keys=[r["key"] for r in rows]
    )
    # Reddit pages search results behind its own script, so there is no cursor
    # in this HTML to follow. Say that rather than imply the list is the whole
    # result set.
    page.more.append(
        _more(
            "feed",
            "[feed: Reddit pages its search results; this read has the results on "
            "this page]",
        )
    )
    return page


def extract_from_html(url: str, html: str) -> Optional[Tuple[str, str]]:
    """``(stderr_label, markdown)`` or None, for callers that only want the text.

    Kept for the two places that predate :class:`RedditPage`. A page that is a
    wall returns None here, which is the pre-F5f behaviour and the reason
    :func:`extract_page` is the entry point the ladder uses.
    """
    page = extract_page(url, html)
    if page is None or page.failure or not page.markdown:
        return None
    return page.label, page.markdown
