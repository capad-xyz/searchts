"""F23a: say when a page has more than this read returned.

Detection only. No extra requests and no clicks: the page HTML we already
have is checked for a next page, a feed, folded text, a list the extractor
mostly dropped, and counts the page states. Each finding becomes a short
bracketed note under the text and a structured entry for ``--json`` / MCP.

Also keeps accordion and tab text through extraction (``prepare_panels``):
Trafilatura drops ``<button>`` labels (the questions) and inline
``display:none`` panels (the answers).

No note is not a promise that the page is complete. These are page signals,
not per-host code (Reddit keeps its own ring in ``known_hosts``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

#: Page chrome. A control or list inside these never counts.
_CHROME_TAGS = frozenset({"header", "footer", "aside", "form", "dialog", "menu", "template"})
_CHROME_ROLES = frozenset(
    {"navigation", "banner", "contentinfo", "menu", "menubar", "dialog", "search", "complementary"}
)
_SKIP_TEXT_TAGS = frozenset({"script", "style", "noscript", "template", "svg"})

#: "Load more" and "Show more posts": more items, not more of one item.
_FEED_RE = re.compile(
    r"^(?:load\s+more\b.*|(?:show|see|view)\s+more\s+"
    r"(?:posts|stories|results|items|articles|comments|replies|products|videos|news))[\s.…]*$",
    re.I,
)
#: "Read more" and "Show more": the rest of one item.
_FOLD_RE = re.compile(
    r"^(?:read|show|see|view)\s+(?:more|all|full|the\s+rest)"
    r"(?:\s+(?:post|article|text|story|description|details))?[\s.…>»›]*$",
    re.I,
)
_NEXT_TEXT_RE = re.compile(r"^(?:next(?:\s+page)?|older(?:\s+(?:posts|entries))?|[›»>])[\s›»>]*$", re.I)
_PAGER_HINT_RE = re.compile(r"pagination|pager|paging", re.I)
_SHOWING_RE = re.compile(
    r"\bshowing\s+(\d[\d,]*)\s*(?:-|–|—|to)\s*(\d[\d,]*)\s+of\s+(\d[\d,]*)", re.I
)
_PAGE_OF_RE = re.compile(r"\bpage\s+(\d{1,4})\s+of\s+(\d{1,4})\b", re.I)

#: Repeated-item check: a list must be this long and this much of the page.
_LIST_MIN_ITEMS = 8
_LIST_MIN_SHARE = 0.5
_LIST_MAX_KEPT = 0.3


@dataclass
class More:
    """One finding: what kind, the note text, and a URL when there is one."""

    kind: str  # next-page | feed | fold | list | count
    note: str
    url: Optional[str] = None

    def as_dict(self) -> Dict[str, str]:
        d = {"kind": self.kind, "note": self.note}
        if self.url:
            d["url"] = self.url
        return d


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _parse(html: str):
    """lxml document, or None when the HTML cannot be parsed."""
    if not html or not html.strip():
        return None
    try:
        import lxml.html

        cleaned = re.sub(r"^\s*<\?xml[^>]*\?>", "", html)
        return lxml.html.fromstring(cleaned)
    except Exception:  # noqa: BLE001 - detection is best effort, never a failure
        return None


def _in_chrome(el) -> bool:
    node = el
    while node is not None:
        tag = node.tag if isinstance(node.tag, str) else ""
        if tag.lower() in _CHROME_TAGS:
            return True
        if (node.get("role") or "").lower() in _CHROME_ROLES:
            return True
        node = node.getparent()
    return False


def _in_nav(el) -> bool:
    node = el
    while node is not None:
        tag = node.tag if isinstance(node.tag, str) else ""
        if tag.lower() == "nav" or (node.get("role") or "").lower() == "navigation":
            return True
        node = node.getparent()
    return False


def _is_control_link(el) -> bool:
    """True for a link that does not go anywhere (``#``, ``javascript:``, no href)."""
    href = (el.get("href") or "").strip()
    return not href or href.startswith("#") or href.lower().startswith("javascript:")


def _controls(doc):
    """Clickable things that stay on the page: buttons and non-navigating links."""
    for el in doc.iter():
        if not isinstance(el.tag, str):
            continue
        tag = el.tag.lower()
        role = (el.get("role") or "").lower()
        if tag == "button" or role == "button" or (tag == "a" and _is_control_link(el)):
            yield el


def _base_url(doc, url: str) -> str:
    base = doc.xpath("//base[@href]/@href")
    return urljoin(url, base[0].strip()) if base else url


def _host(u: str) -> str:
    host = (urlsplit(u).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _same_page(a: str, b: str) -> bool:
    return a.split("#", 1)[0].rstrip("/") == b.split("#", 1)[0].rstrip("/")


def _good_next(href: str, base: str, url: str) -> Optional[str]:
    href = (href or "").strip()
    if not href or href.startswith("#") or href.lower().startswith(("javascript:", "mailto:")):
        return None
    target = urljoin(base, href)
    if urlsplit(target).scheme not in ("http", "https"):
        return None
    if _host(target) != _host(url) or _same_page(target, url):
        return None
    return target.split("#", 1)[0]


# ── accordions and tabs: keep their text through extraction ─────────────────


def _unhide(el) -> None:
    for attr in ("hidden", "aria-hidden"):
        if attr in el.attrib:
            del el.attrib[attr]
    style = el.get("style")
    if style:
        kept = [
            part
            for part in style.split(";")
            if not re.match(r"\s*(display\s*:\s*none|visibility\s*:\s*hidden)\s*$", part, re.I)
        ]
        el.set("style", ";".join(kept))


def _panel_for(toggle, ids: Dict[str, object]):
    controls = (toggle.get("aria-controls") or "").split()
    if controls:
        return ids.get(controls[0])
    return toggle.getnext()


def _is_descendant(el, ancestor) -> bool:
    node = el.getparent()
    while node is not None:
        if node is ancestor:
            return True
        node = node.getparent()
    return False


def _accordion_toggles(doc):
    """(toggle, panel, label) for disclosure buttons outside page chrome.

    Menus (``aria-haspopup``) and "Read more" / "Load more" toggles are left
    alone: those are folds and feeds, not questions.
    """
    ids = {el.get("id"): el for el in doc.xpath("//*[@id]")}
    for toggle in doc.xpath("//*[@aria-expanded]"):
        if _in_chrome(toggle) or _in_nav(toggle):
            continue
        if (toggle.get("aria-haspopup") or "false").lower() != "false":
            continue
        label = _norm(toggle.text_content())
        if not label or len(label) > 200 or _FOLD_RE.match(label) or _FEED_RE.match(label):
            continue
        panel = _panel_for(toggle, ids)
        if panel is None or panel is toggle or not isinstance(panel.tag, str):
            continue
        yield toggle, panel, label


def prepare_panels(html: str) -> str:
    """Return HTML whose accordion and tab text survives Trafilatura.

    Each disclosure button becomes a heading (Trafilatura drops buttons, so an
    FAQ lost its questions), its panel is un-hidden (inline ``display:none``
    panels were dropped whole), and each tab label moves to the top of its
    panel. Anything unexpected returns the HTML unchanged.
    """
    doc = _parse(html)
    if doc is None:
        return html
    try:
        import lxml.html

        changed = False
        for toggle, panel, label in list(_accordion_toggles(doc)):
            _unhide(panel)
            parent = toggle.getparent()
            if parent is not None and not _is_descendant(panel, toggle):
                heading = lxml.html.Element("h3")
                heading.text = label
                heading.tail = toggle.tail
                parent.replace(toggle, heading)
            changed = True

        ids = {el.get("id"): el for el in doc.xpath("//*[@id]")}
        for tab in doc.xpath("//*[@role='tab'][@aria-controls]"):
            if _in_chrome(tab) or _in_nav(tab):
                continue
            panel = ids.get((tab.get("aria-controls") or "").split()[0] if tab.get("aria-controls") else "")
            label = _norm(tab.text_content())
            if panel is None or not label or len(label) > 120:
                continue
            heading = lxml.html.Element("h3")
            heading.text = label
            heading.tail = panel.text
            panel.text = None
            panel.insert(0, heading)
            _unhide(panel)
            tab.drop_tree()
            changed = True

        if not changed:
            return html
        return lxml.html.tostring(doc, encoding="unicode")
    except Exception:  # noqa: BLE001 - never lose a read over a preprocessing step
        return html


# ── detection ───────────────────────────────────────────────────────────────


def _next_page(doc, base: str, url: str) -> Optional[str]:
    for el in doc.xpath("//link[@rel][@href] | //a[@rel][@href]"):
        if "next" in (el.get("rel") or "").lower().split():
            good = _good_next(el.get("href"), base, url)
            if good:
                return good
    for pager in doc.iter():
        if not isinstance(pager.tag, str):
            continue
        hint = " ".join(pager.get(a) or "" for a in ("aria-label", "class", "id"))
        if not _PAGER_HINT_RE.search(hint):
            continue
        current = None
        for cur in pager.xpath(".//*[@aria-current='page']"):
            txt = _norm(cur.text_content())
            if txt.isdigit():
                current = int(txt)
        for a in pager.xpath(".//a[@href]"):
            txt = _norm(a.text_content())
            label = (a.get("aria-label") or "").lower()
            if _NEXT_TEXT_RE.match(txt) or re.search(r"\bnext\b", label) or (
                current is not None and txt.isdigit() and int(txt) == current + 1
            ):
                good = _good_next(a.get("href"), base, url)
                if good:
                    return good
    return None


def _feed(doc, base: str, url: str) -> Tuple[bool, Optional[str]]:
    """(is a feed, a "Load more" URL when the button is a real link)."""
    if doc.xpath("//*[@role='feed']"):
        return True, None
    for el in doc.iter("a"):
        if _in_chrome(el) or _is_control_link(el):
            continue
        if _FEED_RE.match(_norm(el.text_content())):
            good = _good_next(el.get("href"), base, url)
            if good:
                return False, good
    for el in _controls(doc):
        if not _in_chrome(el) and _FEED_RE.match(_norm(el.text_content())):
            return True, None
    return False, None


def _folds(doc) -> Tuple[int, str]:
    """(count, first label) of "Read more" style controls that stay on the page."""
    count, first = 0, ""
    for el in _controls(doc):
        if _in_chrome(el) or _in_nav(el):
            continue
        label = _norm(el.text_content())
        if len(label) <= 40 and _FOLD_RE.match(label) and not _FEED_RE.match(label):
            count += 1
            first = first or label
    return count, first


def _empty_panels(doc) -> int:
    return sum(1 for _t, panel, _l in _accordion_toggles(doc) if not _norm(panel.text_content()))


def _visible_text(el) -> str:
    parts: List[str] = []

    def walk(node) -> None:
        tag = node.tag.lower() if isinstance(node.tag, str) else ""
        if tag in _SKIP_TEXT_TAGS or not isinstance(node.tag, str):
            if node.tail:
                parts.append(node.tail)
            return
        if node.text:
            parts.append(node.text)
        for child in node:
            walk(child)
        if node.tail:
            parts.append(node.tail)

    walk(el)
    return _norm(" ".join(parts))


def _item_key(item) -> str:
    for xp in (".//h1|.//h2|.//h3|.//h4", ".//a[@href]"):
        for el in item.xpath(xp):
            txt = _norm(el.text_content())
            if len(txt) >= 8:
                return txt[:60].lower()
    return _norm(item.text_content())[:60].lower()


def _list_kept(doc, text: str) -> Optional[Tuple[int, int]]:
    """(items on the page, items the extract kept) for a list the page is made of."""
    body = doc.find(".//body")
    root = body if body is not None else doc
    page_len = len(_visible_text(root))
    if page_len < 400:
        return None
    best: Optional[List] = None
    best_len = 0
    for parent in root.iter():
        if not isinstance(parent.tag, str) or len(parent) < _LIST_MIN_ITEMS:
            continue
        groups: Dict[Tuple[str, str], List] = {}
        for child in parent:
            if not isinstance(child.tag, str):
                continue
            cls = (child.get("class") or "").split()
            groups.setdefault((child.tag.lower(), cls[0] if cls else ""), []).append(child)
        for items in groups.values():
            if len(items) < _LIST_MIN_ITEMS:
                continue
            real = [it for it in items if it.xpath(".//a[@href]") and len(_visible_text(it)) >= 25]
            if len(real) < 0.8 * len(items):
                continue
            total = sum(len(_visible_text(it)) for it in items)
            if total > best_len:
                best, best_len = items, total
    if not best or _in_chrome(best[0]) or _in_nav(best[0]):
        return None
    if best_len < _LIST_MIN_SHARE * page_len:
        return None
    lowered = _norm(text).lower()
    kept = sum(1 for it in best if _item_key(it) and _item_key(it) in lowered)
    if kept > _LIST_MAX_KEPT * len(best):
        return None
    return len(best), kept


def _counts(doc) -> List[str]:
    body = doc.find(".//body")
    text = _visible_text(body if body is not None else doc)
    notes: List[str] = []
    m = _SHOWING_RE.search(text)
    if m:
        lo, hi, total = (int(g.replace(",", "")) for g in m.groups())
        if lo <= hi < total:
            notes.append(f"showing {lo}\u2013{hi} of {total}")
    m = _PAGE_OF_RE.search(text)
    if m:
        page, pages = int(m.group(1)), int(m.group(2))
        if 1 <= page < pages:
            notes.append(f"page {page} of {pages}")
    return notes


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def detect(html: str, url: str, text: str) -> List[More]:
    """Findings for one read: the page HTML, its URL, and the extracted text."""
    doc = _parse(html)
    if doc is None:
        return []
    found: List[More] = []
    try:
        base = _base_url(doc, url)
        nxt = _next_page(doc, base, url)
        is_feed, load_more_url = _feed(doc, base, url)
        nxt = nxt or load_more_url
        if nxt:
            found.append(More("next-page", f"[more: the next page is {nxt}]", nxt))
        if is_feed:
            found.append(
                More(
                    "feed",
                    "[feed: more items load on scroll or \"Load more\"; this read has the first window]",
                )
            )
        folds, label = _folds(doc)
        if folds:
            found.append(
                More(
                    "fold",
                    f"[folded: {folds} {_plural(folds, 'control', 'controls')} like \"{label}\" on the "
                    "page; the text behind them may be missing]",
                )
            )
        empty = _empty_panels(doc)
        if empty:
            found.append(
                More(
                    "fold",
                    f"[folded: {empty} collapsed {_plural(empty, 'section was', 'sections were')} "
                    "empty in the page; that text loads on click]",
                )
            )
        listed = _list_kept(doc, text)
        if listed:
            total, kept = listed
            found.append(More("list", f"[partial: the page lists {total} items; this read kept {kept}]"))
        for said in _counts(doc):
            found.append(More("count", f"[page says: {said}]"))
    except Exception:  # noqa: BLE001 - a detection bug must never fail a read
        return found
    return found


def annotate(text: str, found: List[More]) -> str:
    """Text with one note line per finding appended."""
    if not found:
        return text
    return (text or "").rstrip() + "\n\n" + "\n".join(m.note for m in found)


def summary(found: List[More]) -> str:
    """Short stderr tick, e.g. ``more: next page, folded``."""
    names = {"next-page": "next page", "feed": "feed", "fold": "folded", "list": "partial list", "count": "page count"}
    seen: List[str] = []
    for m in found:
        name = names.get(m.kind, m.kind)
        if name not in seen:
            seen.append(name)
    return "more: " + ", ".join(seen)
