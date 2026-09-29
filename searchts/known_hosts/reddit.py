# -*- coding: utf-8 -*-
"""Reddit public-document extractor — known-host ring (F5b).

The caller passes a **page**, not an API URL (same as share extractors).
HTML listing/thread URLs (www / old / no-www, hot/new/top/rising,
``comments/<id>/…``) are rewritten to the public ``.json`` document, fetched,
parsed, then fail-open to curl/Jina/stealth on any miss.

Also matches already-JSON shapes: ``/r/sub.json``, ``/r/sub/hot.json``,
``/r/sub/comments/<id>.json``, and ``/.json``.
"""

from __future__ import annotations

import json
import re
import urllib.parse
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

#: Max top-level comments to include in rendered output.
_MAX_COMMENTS = 30

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
        lines.append("\n## Comments\n")
        for i, child in enumerate(comments[:_MAX_COMMENTS]):
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
    """Render a list of children (t3 dicts or {kind, data} wrappers) as a compact index."""
    lines: List[str] = []
    for child in children[:_MAX_COMMENTS]:
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
    try:
        parts = urllib.parse.urlsplit(url)
    except Exception:  # noqa: BLE001
        return False
    host = (parts.netloc or "").lower()
    if host not in ("reddit.com", "www.reddit.com", "old.reddit.com"):
        return False
    path = parts.path or "/"
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
    try:
        parts = urllib.parse.urlsplit(url)
    except Exception:  # noqa: BLE001
        return False
    host = (parts.netloc or "").lower()
    if host not in ("reddit.com", "www.reddit.com", "old.reddit.com"):
        return False
    path = parts.path or "/"
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
    that slot exists. Stdlib HTMLParser only.
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
                self._depth += 1
            elif self._depth and t not in _VOID_TAGS:
                if self._body_depth:
                    self._body_depth += 1
                elif ad.get("slot", "").lower() == "text-body":
                    self._body_depth = 1

        def handle_endtag(self, tag: str) -> None:
            t = tag.lower()
            if t in _SKIP_TAGS:
                self._skip = max(0, self._skip - 1)
            if t not in _VOID_TAGS and self._body_depth:
                self._body_depth -= 1
            if t == "shreddit-post" and self._depth:
                self._depth -= 1
                if self._depth == 0 and self._attrs is not None:
                    self._attrs["_text"] = " ".join(self._all)
                    self._attrs["_body"] = " ".join(self._body)
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


def parse_reddit_listing_html(html: str, url: str = "") -> Optional[str]:
    """If >=2 shreddit-post nodes have non-empty post-title, return compact MD index.

    Permalinks are normalized to absolute https://www.reddit.com/... form.
    comment-count and score appear when present. The full card body sits under
    the title when the light DOM has one. Returns None for <2 titled posts.

    When a URL is supplied, this returns None for thread URLs (/comments/) or .json URLs
    even if the HTML contains shreddit-post nodes (threads fall through; JSON ring owns .json).

    Does not change _render_subreddit_from_children output.
    Markdown print format only.
    """
    if url:
        if not is_reddit_listing_url(url):
            return None
    posts = _parse_shreddit_posts(html)
    valid: List[Dict[str, str]] = []
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
        snippet = _card_body(title, attrs.get("_body") or "", attrs.get("_text") or "")
        valid.append(
            {
                "title": title,
                "permalink": perm,
                "cc": cc,
                "score": score,
                "author": author,
                "snippet": snippet,
            }
        )

    if len(valid) < 2:
        return None

    lines: List[str] = []
    for v in valid:
        bits: List[str] = []
        if v["author"]:
            bits.append(f"/u/{v['author']}")
        if v["cc"]:
            bits.append(f"{v['cc']} comments")
        if v["score"]:
            bits.append(f"{v['score']} pts")
        suffix = f" ({', '.join(bits)})" if bits else ""
        lines.append(f"- **{v['title']}**{suffix}")
        if v["snippet"]:
            lines.append(f"  {v['snippet']}")
        if v["permalink"]:
            lines.append(f"  [`permalink`]({v['permalink']})")
        lines.append("")
    return "\n".join(lines).strip()


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


def parse_reddit_thread_html(html: str, url: str = "") -> Optional[str]:
    """OP plus a bounded comment tree from thread HTML. None if there is no titled post.

    Nested ``shreddit-comment`` nodes are indented entries, not mashed into the parent.
    """
    if url and not is_reddit_thread_url(url):
        return None
    posts = _parse_shreddit_posts(html)
    op = next((a for a in posts if (a.get("post-title") or "").strip()), None)
    if op is None:
        return None
    title = (op.get("post-title") or "").strip()
    author = (op.get("author") or "").strip()
    if author.startswith("u/"):
        author = author[2:]
    score = (op.get("score") or op.get("upvote-count") or "").strip()
    cc = (op.get("comment-count") or "").strip()
    perm = _canonical_reddit_permalink(op.get("permalink") or op.get("content-href") or "")
    body = _card_body(title, op.get("_body") or "", op.get("_text") or "", require_min=False)

    lines: List[str] = [f"# {title}", ""]
    if author:
        lines.append(f"**OP:** /u/{author}")
    if score:
        lines.append(f"**Score:** {score}")
    if cc:
        lines.append(f"**Comments:** {cc}")
    if perm:
        lines.append(f"**Link:** {perm}")
    if body:
        lines.extend(["", body])

    comments = _parse_shreddit_comments(html)
    shown = 0
    comment_block: List[str] = []
    for c in comments:
        c_author = (c.get("author") or "[deleted]").strip()
        if c_author.startswith("u/"):
            c_author = c_author[2:]
        text = _comment_body(c_author, c.get("_body") or "", c.get("_text") or "")
        if len(text) < 8:
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
        if shown >= _MAX_COMMENTS:
            break
    if comment_block:
        lines.extend(["", "## Comments", ""])
        lines.extend(comment_block)
    return "\n".join(lines).strip()


def extract_from_html(url: str, html: str) -> Optional[Tuple[str, str]]:
    """Listing index or thread document from already-downloaded HTML.

    Returns ``(stderr_label, markdown)`` or None. JSON URLs stay with the JSON ring.
    """
    if is_reddit_listing_url(url):
        md = parse_reddit_listing_html(html, url)
        if md:
            n = count_titled_shreddit_posts(html)
            return f"listing-html: {n} posts", md
        return None
    if is_reddit_thread_url(url):
        md = parse_reddit_thread_html(html, url)
        if md:
            return "thread-html: op", md
    return None
