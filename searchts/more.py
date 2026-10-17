"""F23a: say when a page has more than this read returned.

Detection only. No extra requests and no clicks: the page HTML we already
have is checked for a next page, a feed, folded text, a list the extractor
mostly dropped, how much of the page's own text the read kept, and counts the
page states. Each finding becomes a short bracketed note under the text and a
structured entry for ``--json`` / MCP.

Also keeps accordion and tab text through extraction (``prepare_panels``):
Trafilatura drops ``<button>`` labels (the questions) and inline
``display:none`` panels (the answers). ``tidy_markdown`` puts headings and
code fences back on their own lines after extraction, and
:func:`space_after_inline` puts back a space the extractor drops next to
inline code or bold. :func:`structured_text` reads the page's own JSON-LD, so
a page that ships its body as data instead of markup can still be read from
the bytes already downloaded.

No note is not a promise that the page is complete. These are page signals,
not per-host code (Reddit keeps its own ring in ``known_hosts``).
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from searchts.expand import EXPAND_EXACT_RE as _EXPAND_EXACT_RE
from searchts.expand import EXPAND_RE as _EXPAND_RE
from searchts.expand import FEED_FOLD_RE as _FEED_FOLD_RE
from searchts.expand import FEED_NOUNS as _FEED_NOUNS

#: Page chrome. A control or list inside these never counts.
_CHROME_TAGS = frozenset({"header", "footer", "aside", "form", "dialog", "menu", "template"})
_CHROME_ROLES = frozenset(
    {"navigation", "banner", "contentinfo", "menu", "menubar", "dialog", "search", "complementary"}
)
_SIDE_CLASS = re.compile(r"(?:^|\s)(?:sidebar|aside|complementary|side-panel)(?:\s|$)", re.I)
_SKIP_TEXT_TAGS = frozenset({"script", "style", "noscript", "template", "svg"})

#: "Load more" and "Show more posts": more items, not more of one item.
_FEED_RE = re.compile(
    r"^(?:load\s+more\b.*|(?:show|see|view)\s+more\s+(?:" + "|".join(_FEED_NOUNS) + r"))[\s.…]*$",
    re.I,
)
#: "Read more" and "Show more": the rest of one item. Imported from
#: :mod:`searchts.expand` so the fold this names is the fold ``--expand`` opens.
#: The exact form is kept for :func:`_accordion_toggles`, which must not mistake
#: a fold for a question to open; the wide form counts folds for the note.
_FOLD_RE = _EXPAND_EXACT_RE
_FOLD_ANY_RE = _EXPAND_RE
_NEXT_TEXT_RE = re.compile(r"^(?:next(?:\s+page)?|older(?:\s+(?:posts|entries))?|[›»>])[\s›»>]*$", re.I)
_PAGER_HINT_RE = re.compile(r"pagination|pager|paging|page\s+navigation|more\s+results", re.I)
#: A link's own name (aria-label or title) that says it is the next page (Bing, Google).
_NEXT_LABEL_RE = re.compile(r"^next(?:\s+(?:page|results?))?[\s›»>]*$", re.I)
#: Trailing page markers: /page/2, /page-2, /2 (a short number).
_PAGE_SEG_RE = re.compile(r"/(?:page[-_/]?\d{1,4}|\d{1,3})$", re.I)
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

    kind: str  # next-page | feed | fold | list | count | index | region
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
        if _SIDE_CLASS.search(node.get("class") or ""):
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


def _page_base(u: str) -> str:
    """Path with trailing page markers removed: /blog/page/3/ and /blog/ -> /blog."""
    path = (urlsplit(u).path or "/").lower().rstrip("/")
    for _ in range(2):
        stripped = _PAGE_SEG_RE.sub("", path).rstrip("/")
        if stripped == path:
            break
        path = stripped
    return path


def _continues(target: str, url: str) -> bool:
    """True when ``target`` is this URL's next page, not another document.

    A next page keeps the path and changes a page marker (``?page=3``,
    ``&first=11``, ``/page/3/``, ``/2/``). WordPress puts ``rel="next"`` on the
    next *post* of every single post, and docs sites on the next *chapter*;
    those have their own path, so they are not "more of this page".
    """
    return _page_base(target) == _page_base(url)


def _good_next(href: str, base: str, url: str) -> Optional[str]:
    href = (href or "").strip()
    if not href or href.startswith("#") or href.lower().startswith(("javascript:", "mailto:")):
        return None
    target = urljoin(base, href)
    if urlsplit(target).scheme not in ("http", "https"):
        return None
    if _host(target) != _host(url) or _same_page(target, url) or not _continues(target, url):
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


_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})


def _heading_around(el):
    """The heading a toggle already sits in (up to three levels up), or None."""
    node = el.getparent()
    for _ in range(3):
        if node is None or not isinstance(node.tag, str):
            return None
        if node.tag.lower() in _HEADING_TAGS:
            return node
        node = node.getparent()
    return None


def _swap_for_text(el, text: str) -> None:
    """Replace ``el`` with plain ``text``, keeping its tail."""
    parent = el.getparent()
    joined = f" {text} {el.tail or ''}"
    prev = el.getprevious()
    if prev is not None:
        prev.tail = (prev.tail or "") + joined
    else:
        parent.text = (parent.text or "") + joined
    parent.remove(el)


def _is_link_list(panel) -> bool:
    """A table of contents or menu: a ``nav`` whose links are nearly all the text.

    An FAQ answer made of links ("Read the docs", a list of guides) has no
    ``nav``, so it is still an answer.
    """
    if not (_in_nav(panel) or panel.xpath(".//nav|.//*[@role='navigation']")):
        return False
    text = _norm(panel.text_content())
    link_text = sum(len(_norm(a.text_content())) for a in panel.xpath(".//a[@href]"))
    return bool(text) and link_text >= 0.8 * len(text)


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
        if _is_link_list(panel):  # "On this page" / menu toggles open links, not an answer
            continue
        yield toggle, panel, label


def prepare_panels(html: str) -> str:
    """Return HTML whose accordion and tab text survives Trafilatura.

    Each disclosure button becomes a heading (Trafilatura drops buttons, so an
    FAQ lost its questions), its panel is un-hidden (inline ``display:none``
    panels were dropped whole), and each tab label moves to the top of its
    panel. A button that already sits in a heading (Bootstrap's
    ``<h2 class="accordion-header"><button>``) becomes that heading's text,
    never a second heading nested inside it. Anything unexpected returns the
    HTML unchanged.
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
                if _heading_around(toggle) is not None:
                    _swap_for_text(toggle, label)
                else:
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


_FENCE_LINE_RE = re.compile(r"^([ \t]*)(`{3,}|~{3,})[^`]*$")
_GLUED_FENCE_RE = re.compile(r"^(.*[^`\s])[ \t]*```[ \t]*$")
_HEADING_LINE_RE = re.compile(r"^([ \t]*)(#{1,6} \S.*)$")


def _indent(prefix: str) -> int:
    return len(prefix.expandtabs(4))


def tidy_markdown(markdown: str) -> str:
    """Undo two layout slips Trafilatura makes after inline text.

    It keeps the whitespace in front of a heading or a code fence, so
    ``## Item`` can come out indented four spaces or more, which Markdown
    reads as code. It can also glue a code fence to the end of the text line
    before it (``...application.```), so the fence never opens. Both are put
    on their own line after a blank line. Code inside a fence is left alone.
    """
    lines = markdown.split("\n")
    standalone = [i for i, ln in enumerate(lines) if _FENCE_LINE_RE.match(ln)]
    out: List[str] = []
    fenced = False

    def _own_line(text: str) -> None:
        if out and out[-1].strip():
            out.append("")
        out.append(text)

    for i, line in enumerate(lines):
        fence = _FENCE_LINE_RE.match(line)
        if fenced:
            out.append(line)
            if fence and _indent(fence.group(1)) <= 3:
                fenced = False
            continue
        if fence:
            fenced = True
            if _indent(fence.group(1)) >= 4:
                _own_line(line.lstrip())
            else:
                out.append(line)
            continue
        glued = _GLUED_FENCE_RE.match(line)
        if glued and any(j > i for j in standalone):  # a closing fence follows
            out.append(glued.group(1))
            _own_line("```")
            fenced = True
            continue
        heading = _HEADING_LINE_RE.match(line)
        if heading and _indent(heading.group(1)) >= 4:
            _own_line(heading.group(2))
            continue
        out.append(line)
    return space_after_inline("\n".join(out))


#: An inline code span or a bold run: the two things an extractor can leave
#: glued to the word next to them. ``searchts`read`` comes from markup with no
#: whitespace node between the ``<code>`` and the text; the tags are real and
#: the space is not. Measured on real extracts from docs pages and wikis.
_TOKEN_RE = re.compile(r"(`+[^`\n]*`+|\*\*|__)")


def space_after_inline(markdown: str) -> str:
    """Put back the space an extractor drops next to inline code or bold.

    One pass per line, over the inline code spans and the bold runs only:

    - a **closing** code span followed immediately by a word gets a space
      (``searchts`read`` -> ``searchts` read``). The span is left byte for
      byte: the space belongs between the span and the word, never inside the
      code.
    - a bold run gets a space after it when it closes and a word follows
      (``**bold**text`` -> ``**bold** text``), and not when it opens one
      (``**bold** more`` is already right and stays as it is).

    Never inside a fenced block. A fence is code the page wrote on purpose and
    is left exactly as it is, which is also why a code sample that really does
    read ``foo``bar`` is not "repaired".
    """
    if not markdown or not _TOKEN_RE.search(markdown):
        return markdown
    lines = markdown.split("\n")
    out: List[str] = []
    fenced = False
    for line in lines:
        fence = _FENCE_LINE_RE.match(line)
        if fenced:
            out.append(line)
            if fence and _indent(fence.group(1)) <= 3:
                fenced = False
            continue
        if fence:
            fenced = True
            out.append(line)
            continue
        out.append(_space_line(line))
    return "\n".join(out)


def _space_line(line: str) -> str:
    out: List[str] = []
    pos = 0
    bold_open = False
    for m in _TOKEN_RE.finditer(line):
        out.append(line[pos : m.start()])
        token = m.group(0)
        glued = line[m.end() : m.end() + 1].isalnum()
        out.append(token + (" " if glued and (token.startswith("`") or bold_open) else ""))
        if not token.startswith("`"):
            bold_open = not bold_open
        pos = m.end()
    out.append(line[pos:])
    return "".join(out)


# ── detection ───────────────────────────────────────────────────────────────


def _is_pager(el) -> bool:
    """A pagination block: named like one, or holding several page-number links."""
    hint = " ".join(el.get(a) or "" for a in ("aria-label", "class", "id"))
    if _PAGER_HINT_RE.search(hint):
        return True
    links = el.xpath(".//a[@href]")
    if not links or len(links) > 40:
        return False
    return sum(1 for a in links if re.fullmatch(r"\d{1,3}", _norm(a.text_content()))) >= 2


def _pager_of(a):
    """The pager this link sits in (up to three levels up), or None."""
    node = a.getparent()
    for _ in range(3):
        if node is None or not isinstance(node.tag, str):
            return None
        if _is_pager(node):
            return node
        node = node.getparent()
    return None


def _current_page(pager) -> Optional[int]:
    """The page this pager marks as current (``aria-current``, or a number that is not a link)."""
    for cur in pager.xpath(".//*[@aria-current='page']"):
        txt = _norm(cur.text_content())
        if txt.isdigit():
            return int(txt)
    for el in pager.iter():
        if not isinstance(el.tag, str) or len(el):
            continue
        txt = _norm(el.text_content())
        if txt.isdigit() and len(txt) <= 3 and not (el.tag == "a" and el.get("href")):
            return int(txt)
    return None


def _in_header(el) -> bool:
    node = el
    while node is not None:
        if isinstance(node.tag, str) and node.tag.lower() == "header":
            return True
        node = node.getparent()
    return False


def _next_page(doc, base: str, url: str) -> Optional[str]:
    # 1. <link rel="next"> (head).
    for el in doc.xpath("//link[@rel][@href]"):
        if "next" in (el.get("rel") or "").lower().split():
            good = _good_next(el.get("href"), base, url)
            if good:
                return good
    # 2. A link that names itself the next page. Only these few links pay for the
    #    pager walk, so a page of thousands of links stays cheap.
    for a in doc.xpath("//a[@href]"):
        txt = _norm(a.text_content())
        label = _norm(a.get("aria-label") or a.get("title") or "")
        says_next = bool(_NEXT_TEXT_RE.match(txt) or re.search(r"\bnext\b", label.lower()))
        rel_next = "next" in (a.get("rel") or "").lower().split()
        if not (says_next or rel_next) or _in_header(a):
            continue
        if label and _NEXT_LABEL_RE.match(label):
            is_next = True  # aria-label / title "Next page" (Bing, Google)
        elif rel_next:
            # The page declares it, whatever the link says (Hacker News: "More").
            # A rel=next to another post or chapter fails _good_next's same-URL rule.
            is_next = True
        else:
            is_next = says_next and _pager_of(a) is not None
        if is_next:
            good = _good_next(a.get("href"), base, url)
            if good:
                return good
    # 3. A named pager with no Next link: the page after the current one.
    for pager in doc.iter():
        if not isinstance(pager.tag, str):
            continue
        hint = " ".join(pager.get(a) or "" for a in ("aria-label", "class", "id"))
        if not _PAGER_HINT_RE.search(hint):
            continue
        current = _current_page(pager)
        if current is None:
            continue
        for a in pager.xpath(".//a[@href]"):
            txt = _norm(a.text_content())
            if txt.isdigit() and int(txt) == current + 1:
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
    """(count, first label) of the controls that say the rest of it is behind them.

    A fold is the phrase whatever noun follows it: ``Show all reviews`` is the
    same claim as ``Show more``, and only the exact form used to be counted, so
    a product page named one fold where it had five.
    """
    count, first = 0, ""
    for el in _controls(doc):
        if _in_chrome(el) or _in_nav(el):
            continue
        label = _norm(el.text_content())
        if len(label) <= 60 and _FOLD_ANY_RE.match(label) and not _FEED_FOLD_RE.match(label):
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


def _is_title_row(row) -> bool:
    """A Hacker News title row, not the byline under it."""
    if "athing" in (row.get("class") or "").split():
        return True
    return bool(row.xpath(
        ".//span[contains(@class, 'titleline')]"
        " | .//a[contains(@class, 'titleline') or contains(@class, 'storylink')]"
    ))


def _following_detail_row(row):
    """The next row when it is a byline, not another title.

    Link length is not the test. A username or a comment link can be long,
    and that byline is still the detail row.
    """
    nxt = row.getnext()
    if nxt is None or not isinstance(nxt.tag, str) or nxt.tag.lower() != "tr":
        return None
    if _is_title_row(nxt):
        return None
    return nxt


def _table_rows(doc) -> Optional[List]:
    """Title rows of a table list, Hacker News shape: title row, details in the next.

    A data table or a pager does not qualify. The rows must be most of the page.
    """
    body = doc.find(".//body")
    root = body if body is not None else doc
    page_len = len(_visible_text(root))
    if page_len < 400:
        return None
    best: Optional[List] = None
    best_len = 0
    for table in root.iter("table"):
        rows = [r for r in table.xpath("./tr | ./tbody/tr") if isinstance(r.tag, str)]
        titles = []
        for row in rows:
            link = row.xpath(".//span[contains(@class,'titleline')]//a[@href] | .//a[@href]")
            if not link:
                continue
            if len(_norm(link[0].text_content())) < 8:
                continue
            if _following_detail_row(row) is None and "athing" not in (row.get("class") or ""):
                continue
            titles.append(row)
        if len(titles) < _LIST_MIN_ITEMS:
            continue
        total = 0
        for row in titles:
            total += len(_visible_text(row))
            detail = _following_detail_row(row)
            if detail is not None:
                total += len(_visible_text(detail))
        if total > best_len:
            best, best_len = titles, total
    if not best or _in_chrome(best[0]) or _in_nav(best[0]):
        return None
    if best_len < _LIST_MIN_SHARE * page_len:
        return None
    return best


def _best_list(doc) -> Optional[List]:
    """The repeated items the page is made of (results, cards, posts), or None."""
    body = doc.find(".//body")
    main = doc.find(".//main")
    root = body if body is not None else doc
    measure = main if main is not None else root
    page_len = len(_visible_text(measure))
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
    if not best or _in_chrome(best[0]) or _in_nav(best[0]) or best_len < _LIST_MIN_SHARE * page_len:
        best = None
    table = _table_rows(doc)
    # Title-row pairs beat a grab of the detail rows. A card list is left alone.
    if table is not None and (best is None or best[0].tag.lower() == "tr"):
        return table
    return best


def _list_kept(doc, text: str) -> Optional[Tuple[int, int]]:
    """(items on the page, items the extract kept) for a list the page is made of."""
    best = _best_list(doc)
    if not best:
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


def _is_side_region(el) -> bool:
    """A side panel: aside, complementary, or a sidebar class. Not the article."""
    tag = el.tag.lower() if isinstance(el.tag, str) else ""
    if tag == "aside" or (el.get("role") or "").lower() == "complementary":
        return True
    return bool(_SIDE_CLASS.search(el.get("class") or ""))


_JUNK_REGION = re.compile(
    r"(?:cookie|consent|gdpr|advert|ads|ad-slot)",
    re.I,
)


def _junk_region(el) -> bool:
    """Nav, header, footer, a cookie bar or an ad. Those are not a left-out card."""
    if _in_nav(el):
        return True
    node = el
    while node is not None:
        tag = node.tag.lower() if isinstance(node.tag, str) else ""
        role = (node.get("role") or "").lower()
        if tag in {"footer", "header"} or role in {"contentinfo", "banner"}:
            return True
        if _JUNK_REGION.search(f"{node.get('class') or ''} {node.get('id') or ''}"):
            return True
        node = node.getparent()
    return False


def _region_heading(el) -> str:
    for h in el.xpath(".//h1|.//h2|.//h3|.//h4|.//h5|.//h6"):
        title = _norm(h.text_content()).replace('"', "'")
        if len(title) >= 2:
            return title[:80]
    return ""


def _nested_side(el) -> bool:
    parent = el.getparent()
    while parent is not None:
        if isinstance(parent.tag, str) and _is_side_region(parent):
            return True
        parent = parent.getparent()
    return False


def left_out(doc, text: str) -> List[More]:
    """Headed side panels the extract did not keep. The text is not added back.

    Nav, cookie bars, ads and footers never count. F21b is the pass that
    would append the text, and it waits on a saved two-region page.
    """
    lowered = _norm(text).lower()
    out: List[More] = []
    for el in doc.iter():
        if not isinstance(el.tag, str) or not _is_side_region(el):
            continue
        if _nested_side(el) or _junk_region(el):
            continue
        heading = _region_heading(el)
        if not heading or len(_visible_text(el)) < 80:
            continue
        if heading.lower() in lowered:
            continue
        out.append(More("region", f'[left out: a side panel headed "{heading}"]'))
        if len(out) >= 3:
            break
    return out


# ── F24: how much of the page this read actually kept ────────────────────────

#: Below this a share means nothing: a 900-character page read down to 300 is a
#: page, not a thin read. Measured over 26 unknown hosts, the first page where
#: the numbers mean something is around 3,000 characters of the page's own text.
_GAP_MIN_REGION_CHARS = 3_000
#: The read keeps less than this share of that text. A read is allowed to drop
#: ad slots, captions and chrome inside the content region; measured, a complete
#: read on this corpus keeps 60-100% of it.
_GAP_MIN_KEEP = 0.55
#: ...and leaves at least this many characters behind. Without it, a ratio on a
#: small page is a rounding error wearing a percentage.
_GAP_MIN_LOST = 2_000
#: A last line shorter than this cannot be "cut mid-sentence": it is a heading,
#: a byline or a one-word footer.
_TAIL_MIN_CHARS = 60

#: Chrome, plus ``nav``: everything around the content rather than in it. Kept
#: separate from :func:`_in_chrome` on purpose, so measuring the page's own text
#: cannot change which controls count as folds.
_CONTENT_SKIP_TAGS = _CHROME_TAGS | {"nav"}


def _content_chars(el) -> int:
    """Visible characters under ``el``, with the page's chrome left out."""
    parts: List[str] = []

    def walk(node) -> None:
        tag = node.tag.lower() if isinstance(node.tag, str) else ""
        if tag in _SKIP_TEXT_TAGS or not isinstance(node.tag, str):
            if node.tail:
                parts.append(node.tail)
            return
        if tag in _CONTENT_SKIP_TAGS or (node.get("role") or "").lower() in _CHROME_ROLES:
            if node.tail:
                parts.append(node.tail)
            return
        if _SIDE_CLASS.search(node.get("class") or ""):
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
    return len(_norm(" ".join(parts)))


def plain_len(markdown: str) -> int:
    """Visible length of an extract: link targets and Markdown marks do not count.

    Shared with the extractor's own recall gate so "how much of this page is
    this read" means the same thing on both sides of the comparison.
    """
    t = re.sub(r"\]\([^)]*\)", "]", markdown or "")
    t = re.sub(r"[\[\]#*_>`|]", "", t)
    return len(re.sub(r"\s+", " ", t).strip())


def content_region(doc):
    """``(element, characters)`` for the page's own content region.

    ``main``, ``article`` and ``role=main`` are the same claim three ways, and a
    page may use one, two or none of them, so the largest is taken rather than
    the first. Chrome inside a region is dropped, and nothing is mutated: the
    same document still has to be right for every other finding.
    """
    best, best_n = None, 0
    if doc is None:
        return None, 0
    for xp in (".//main", ".//article", "//*[@role='main']", ".//body"):
        for el in doc.xpath(xp)[:1]:
            n = _content_chars(el)
            if n > best_n:
                best, best_n = el, n
    if best is None:
        return doc, _content_chars(doc)
    return best, best_n


def page_text_chars(doc) -> int:
    """The page's own content in characters, for callers that only want a count."""
    return content_region(doc)[1]


def _stops_mid_sentence(text: str) -> bool:
    """True when the extract's last line stops in the middle of a thought.

    False positives are everywhere: a byline ends with a date, a footer ends
    with a product name, a list ends with a link. So the line has to be long
    enough to be a sentence and end on a bare word or comma.
    """
    lines = [ln for ln in (text or "").rstrip().split("\n") if ln.strip()]
    if not lines:
        return False
    last = lines[-1].rstrip().rstrip("`*~ ").strip()
    if len(last) < _TAIL_MIN_CHARS:
        return False
    return bool(re.search(r"[A-Za-z0-9,'’-]$", last))


def short_read(doc, text: str, region=None) -> Optional[More]:
    """The read kept far less of the page than the page holds. Names both numbers.

    A list page rebuilt from its own HTML, an article whose related links
    swallowed the body, a shell that came back as prose: three different
    failures, one honest way to say it. The extract is compared against the
    page's own content region with the chrome out, because a page whose nav is
    longer than its article has not lost content to the extractor.

    This is a note and never a refusal. The read is real text; the claim is
    only that a person opening the page sees more of it, and how much more.

    ``region`` is ``content_region(doc)`` when the caller already has it, so a
    read that asks for several things about the same page walks it once.
    """
    kept = plain_len(text)
    have = (region or content_region(doc))[1]
    lost = have - kept
    if have < _GAP_MIN_REGION_CHARS or kept >= _GAP_MIN_KEEP * have or lost < _GAP_MIN_LOST:
        return None
    share = round(100.0 * kept / have)
    tail = (
        "; the last line also stops mid-sentence"
        if _stops_mid_sentence(text)
        else ""
    )
    return More(
        "share",
        f"[kept {kept:,} of {have:,} characters of the page's own text "
        f"({share}%); {lost:,} characters are in blocks this read did not "
        f"return{tail}]",
    )


# ── F24a: the media in the main content ───────────────────────────────────────

#: How many URLs one note may carry. A product page has ninety images and an
#: agent needs to know they are there, not to read ninety URLs.
_MEDIA_MAX_LISTED = 4
#: A "URL" this long is a data URI or an inline blob, not an address.
_MEDIA_MAX_URL = 300
_MEDIA_URL_ATTRS = (
    "src", "data-src", "data-original", "data-lazy-src", "data-srcset", "srcset", "data", "poster",
)
#: ``source`` is absent on purpose: it is a child of ``video`` and of
#: ``picture``, so counting it tripled the images on a measured front page (658
#: sources against 112 pictures) and told a reader nothing true.
_MEDIA_TAGS = {"img": "image", "video": "video", "audio": "audio", "iframe": "embed",
               "embed": "embed", "object": "embed"}
_MEDIA_HIDDEN_RE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)


def _is_hidden(el) -> bool:
    """Not shown to anyone: a tracking frame, a hidden player, a lazy placeholder."""
    if el.get("hidden") is not None or (el.get("aria-hidden") or "").lower() == "true":
        return True
    if _MEDIA_HIDDEN_RE.search(el.get("style") or ""):
        return True
    for attr in ("width", "height"):
        value = (el.get(attr) or "").strip().rstrip("px")
        if value.isdigit() and int(value) <= 2:
            return True
    return False


def _media_url(el, base: str = "") -> str:
    for attr in _MEDIA_URL_ATTRS:
        raw = (el.get(attr) or "").strip()
        if not raw:
            continue
        # A srcset is a list of candidates; the last is normally the largest.
        url = raw.split(",")[-1].strip().split(" ")[0].strip()
        if url.lower().startswith(("data:", "javascript:", "about:", "blob:", "#")):
            continue  # an inline blob, not an address anyone can fetch
        if len(url) > _MEDIA_MAX_URL:
            continue
        if base and not url.startswith(("http://", "https://")):
            url = urljoin(base, url)  # protocol-relative or root-relative
        return url
    return ""


def media_note(region, base: str = "") -> Optional[More]:
    """The images, video and embeds in the main content, by URL.

    F24a. A read returns text, so a photo essay comes back as its captions and
    an embedded video as nothing at all; both are real content the page holds.
    The note lists the addresses the markup already carries and never fetches
    one, and a page whose media has no address to give says so in the words
    PLAN.md uses rather than pretending there is none.
    """
    if region is None:
        return None
    counts: Dict[str, int] = {}
    urls: List[str] = []
    try:
        nodes = region.xpath(".//img | .//video | .//iframe | .//embed | .//object | .//audio")
    except Exception:  # noqa: BLE001 - an unparsable region has no media to name
        return None
    for el in nodes:
        if _in_chrome(el):
            continue
        kind = _MEDIA_TAGS.get(el.tag.lower() if isinstance(el.tag, str) else "")
        if not kind or _is_hidden(el):
            continue
        counts[kind] = counts.get(kind, 0) + 1
        if len(urls) < _MEDIA_MAX_LISTED:
            url = _media_url(el, base)
            if url and url not in urls:
                urls.append(url)
    if not counts:
        return None
    total = sum(counts.values())
    said = ", ".join(
        f"{counts[k]} {_plural(counts[k], k, k + 's')}" for k in ("image", "video", "audio", "embed") if k in counts
    )
    if not urls:
        return More("media", f"[media: {said} in the main content; media present, not resolved]")
    listed = ", ".join(urls)
    rest = f", and {total - len(urls)} more" if total > len(urls) else ""
    return More("media", f"[media: {said} in the main content: {listed}{rest}]")


def detect(html: str, url: str, text: str) -> List[More]:
    """Findings for one read: the page HTML, its URL, and the extracted text."""
    doc = _parse(html)
    if doc is None:
        return []
    found: List[More] = []
    try:
        where = context_line(doc, html, url)
        if where:
            # First, so it reads as a header on the notes rather than as one
            # more thing the page was missing.
            found.append(More("context", where))
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
        region = content_region(doc)
        short = short_read(doc, text, region=region)
        if short:
            found.append(short)
        seen_media = media_note(region[0], base)
        if seen_media:
            found.append(seen_media)
        found.extend(left_out(doc, text))
    except Exception:  # noqa: BLE001 - a detection bug must never fail a read
        return found
    return found


# ── F23f: list index ─────────────────────────────────────────────────────────

#: Words that are controls, not part of an item's byline.
_ITEM_CHROME_RE = re.compile(
    r"^(?:read\s+more|continue\s+reading|more|share|save|reply|bookmark|follow|"
    r"like|comment|comments)[\s.…›»]*$",
    re.I,
)
#: Something a byline would carry: a date, a relative time or a read time.
_DATEISH_RE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b"
    r"|\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    r"|\b\d+\s*(?:s|m|h|d|w|mo|y|sec|min|mins|hour|hours|day|days|week|weeks|month|months|year|years)\.?\s+ago\b"
    r"|\b\d+\s+min(?:ute)?s?\s+read\b",
    re.I,
)
_BREADCRUMB_RE = re.compile(r"^https?://\S+(?:\s+›\s+\S+)+$")
_INDEX_MIN_COVERAGE = 0.6


def _text_pieces(item) -> List[Tuple[Any, str]]:
    """(owning element, text) for each visible text run in ``item``, in order."""
    out: List[Tuple[Any, str]] = []
    for t in item.xpath(".//text()"):
        el = t.getparent()
        if el is None:
            continue
        if getattr(t, "is_tail", False):
            el = el.getparent()  # tail text belongs to the element around it
            if el is None:
                continue
        node = el
        skip = False
        while node is not None and node is not item.getparent():
            if isinstance(node.tag, str) and node.tag.lower() in _SKIP_TEXT_TAGS:
                skip = True
                break
            node = node.getparent()
        txt = _norm(str(t))
        if not skip and txt:
            out.append((el, txt))
    return out


def _clean_item_url(url: str) -> str:
    """The real target of a search-engine redirect, without ``utm_*`` tags."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    # Only Bing itself: "notbing.com" and "bing.com.attacker.net" are not Bing.
    if (host == "bing.com" or host.endswith(".bing.com")) and parts.path.startswith("/ck/"):
        u = dict(parse_qsl(parts.query)).get("u", "")
        if u.startswith("a1"):
            raw = u[2:] + "=" * (-len(u[2:]) % 4)
            try:
                target = base64.urlsafe_b64decode(raw).decode("utf-8")
            except Exception:  # noqa: BLE001 - keep the redirect when it does not decode
                target = ""
            if target.startswith(("http://", "https://")):
                parts = urlsplit(target)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    query = [(k, v) for k, v in pairs if not k.lower().startswith("utm_")]
    if len(query) == len(pairs):
        return urlunsplit(parts)  # nothing to drop: keep the query exactly as written
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _item_parts(item, base: str) -> Optional[Dict[str, str]]:
    """Title, link, byline and snippet of one list item, or None."""
    heading = next(
        (h for h in item.xpath(".//h1|.//h2|.//h3|.//h4") if len(_norm(h.text_content())) >= 3), None
    )
    link = None
    if heading is not None:
        inside = heading.xpath(".//a[@href]")
        around = [a for a in heading.iterancestors("a") if a.get("href")]
        link = (inside or around or [None])[0]
        title = _norm(heading.text_content())
    if link is None:
        links = [a for a in item.xpath(".//a[@href]") if len(_norm(a.text_content())) >= 8]
        if not links:
            return None
        link = max(links, key=lambda a: len(_norm(a.text_content())))
        if heading is None:
            title = _norm(link.text_content())
    href = (link.get("href") or "").strip()
    if not href or href.startswith(("#", "javascript:")):
        return None
    url = _clean_item_url(urljoin(base, href))

    title_el = heading if heading is not None else link
    pieces = [(el, t) for el, t in _text_pieces(item) if el is not title_el and title_el not in el.iterancestors()]
    detail = _following_detail_row(item) if isinstance(item.tag, str) and item.tag.lower() == "tr" else None
    if detail is not None:
        pieces.extend(_text_pieces(detail))
    snippet_i = max(range(len(pieces)), key=lambda i: len(pieces[i][1]), default=None)
    snippet = ""
    if snippet_i is not None and len(pieces[snippet_i][1]) >= 40:
        snippet = re.sub(r"^[\s·•|…\-–—]+", "", pieces[snippet_i][1])
        pieces = pieces[:snippet_i] + pieces[snippet_i + 1 :]
    texts = [t for _, t in pieces]
    kept: List[str] = []
    for i, t in enumerate(texts):
        if _ITEM_CHROME_RE.match(t) or t.isdigit() or _BREADCRUMB_RE.match(t) or len(t) > 160:
            continue
        if t.startswith(("http://", "https://")) and urlsplit(t).netloc.lower() == urlsplit(url).netloc.lower():
            continue  # the result's own address, already in the link
        nxt = texts[i + 1] if i + 1 < len(texts) else ""
        initials = "".join(w[0] for w in nxt.split()[:3] if w).upper()
        if re.fullmatch(r"[A-Z]{1,2}", t) or (re.fullmatch(r"[A-Z]{3}", t) and initials.startswith(t)):
            continue  # an avatar's initials, alone or right before the name
        kept.append(t)
    byline = re.sub(r"\s+([·•|])", r" \1", " ".join(kept))
    byline = re.sub(r"(?:\s*[·•|]\s*){2,}", " · ", byline).strip(" ·•|")
    if len(byline) > 200:
        byline = byline[:200].rsplit(" ", 1)[0] + "…"
    return {"title": title, "url": url, "byline": byline, "snippet": snippet}


def _strip_md_links(text: str) -> str:
    return re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)


def list_index(html: str, url: str, text: str) -> Optional[Tuple[str, More]]:
    """Rebuild a list page from its HTML when the extract lost the items.

    Returns (index Markdown, note) or None. It replaces the extract only when
    the page is made of a list, the extract is mostly that list, and the
    extract dropped most of the items' titles, links or dates.
    """
    doc = _parse(html)
    if doc is None:
        return None
    try:
        items = _best_list(doc)
        if not items:
            return None
        base = _base_url(doc, url)
        parts = [p for p in (_item_parts(it, base) for it in items) if p]
        if len(parts) < _LIST_MIN_ITEMS:
            return None
        plain = _norm(_strip_md_links(text)).lower()
        n = len(parts)
        lost: List[str] = []
        if sum(1 for p in parts if p["title"][:60].lower() in plain) <= _LIST_MAX_KEPT * n:
            lost.append("titles")
        if sum(1 for p in parts if p["url"] in text or p["url"].split("?")[0] in text) < 0.5 * n:
            lost.append("links")
        dated = [p for p in parts if _DATEISH_RE.search(p["byline"])]
        if len(dated) >= 0.5 * n:
            kept_dates = sum(
                1 for p in dated if (m := _DATEISH_RE.search(p["byline"])) and m.group(0).lower() in plain
            )
            if kept_dates < 0.5 * len(dated):
                lost.append("dates")
        if not lost:
            return None
        titles_present = sum(1 for p in parts if p["title"][:60].lower() in plain) > 0.5 * n
        # A Hacker News table loses the coverage window: the rank on the row
        # makes the window miss the row. Any other list still has to be most
        # of the extract. Titles in the text and missing links are not enough,
        # or an article that repeats a card list's titles gets rebuilt.
        table_list = isinstance(items[0].tag, str) and items[0].tag.lower() == "tr"
        if not (lost == ["links"] and titles_present and table_list):
            # The extract must be mostly this list; otherwise it is an article with a list under it.
            item_text = " ".join(_norm(_visible_text(it)) for it in items).lower()
            paras = [_norm(_strip_md_links(p)).lower() for p in re.split(r"\n\s*\n", text or "")]
            paras = [p for p in paras if len(p) >= 30]
            total = sum(len(p) for p in paras)
            covered = sum(len(p) for p in paras if p[len(p) // 2 - 15 : len(p) // 2 + 15] in item_text)
            if not total and _norm(text or ""):
                # Every paragraph is short (a brief post, a caption): nothing proves the
                # extract is this list, so an article next to a related grid stays an article.
                # Only an extract with no text at all is replaced outright.
                return None
            if total and covered < _INDEX_MIN_COVERAGE * total:
                return None
        heading = next(
            (h for h in doc.xpath("//h1") if _norm(h.text_content()) and not _in_chrome(h)
             and not any(h is d or h in d.iterdescendants() for d in items)),
            None,
        )
        title_el = doc.find(".//title")
        head = _norm(heading.text_content()) if heading is not None else _norm(title_el.text_content() if title_el is not None else "")
        lines: List[str] = [f"# {head}", ""] if head else []
        for p in parts:
            lines.append(f"- [{p['title']}]({p['url']})")
            if p["byline"]:
                lines.append(f"  {p['byline']}")
            if p["snippet"]:
                lines.append(f"  {p['snippet']}")
            lines.append("")
        what = ", ".join(lost[:-1]) + (" and " if len(lost) > 1 else "") + lost[-1]
        note = More(
            "index",
            f"[list: {n} items rebuilt from the page; the extractor dropped their {what}]",
        )
        return "\n".join(lines).strip(), note
    except Exception:  # noqa: BLE001 - never lose a read over the index
        return None


def annotate(text: str, found: List[More]) -> str:
    """Text with one note line per finding appended."""
    if not found:
        return text
    return (text or "").rstrip() + "\n\n" + "\n".join(m.note for m in found)


def summary(found: List[More]) -> str:
    """Short stderr tick, e.g. ``more: next page, folded``."""
    names = {"next-page": "next page", "feed": "feed", "fold": "folded", "list": "partial list", "count": "page count", "index": "list index", "region": "left out", "share": "short read", "context": "context",
           "media": "media"}
    seen: List[str] = []
    for m in found:
        name = names.get(m.kind, m.kind)
        if name not in seen:
            seen.append(name)
    return "more: " + ", ".join(seen)


# ── F24b: the page's own structured data ──────────────────────────────────────

#: Below this a structured body is a teaser, not the page's text.
_STRUCTURED_MIN_CHARS = 400
_LD_SCRIPT_RE = re.compile(
    r"<script[^>]*type\s*=\s*[\"']application/ld\+json[\"'][^>]*>(.*?)</script\s*>",
    re.I | re.S,
)
#: schema.org types, compared on the last segment so a full URL and a bare name
#: are the same type. Everything ending in "article" counts too, which is how
#: ReportageNewsArticle and TechArticle are reached without naming them.
_ARTICLE_TYPES = frozenset({"blogposting", "socialmediaposting", "liveblogposting", "newsarticle", "article"})
_RECIPE_TYPES = frozenset({"recipe"})
_FAQ_TYPES = frozenset({"faqpage", "qapage"})
_DISCUSSION_TYPES = frozenset({"discussionforumposting", "socialmediaposting"})
_VIDEO_TYPES = frozenset({"videoobject", "podcastepisode", "podcastseries"})


def _norm_type(value: str) -> str:
    return str(value or "").strip().lower().rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def _node_kind(node: Dict[str, Any]) -> str:
    declared = node.get("@type")
    names = {_norm_type(t) for t in (([declared] if isinstance(declared, str) else declared) or [])}
    if names & _RECIPE_TYPES:
        return "recipe"
    if names & _FAQ_TYPES:
        return "faq"
    if names & _DISCUSSION_TYPES:
        return "discussion"
    if names & _VIDEO_TYPES:
        return "video"
    if names & _ARTICLE_TYPES or any(n.endswith("article") for n in names):
        return "article"
    return ""


def _ld_blobs(html: str) -> List[str]:
    """The bodies of every JSON-LD script in ``html``.

    A regex, not a parse, on purpose: this runs on every read of a page that
    ships data, and re-parsing a megabyte of markup to find one script is not
    worth it. A ``</script>`` inside the JSON truncates it and ``json.loads``
    then refuses it, which is the right way to fail.
    """
    return [
        m.group(1).strip()
        for m in _LD_SCRIPT_RE.finditer(html or "")
        if m.group(1).strip()
    ]


def _ld_nodes(html: str) -> List[Dict[str, Any]]:
    """Every JSON-LD object the page ships, ``@graph`` included."""
    import json

    out: List[Dict[str, Any]] = []
    for raw in _ld_blobs(html):
        try:
            data = json.loads(raw)
        except Exception:  # noqa: BLE001 - a page's own malformed JSON is not a failure
            continue
        for node in (data if isinstance(data, list) else [data]):
            if not isinstance(node, dict):
                continue
            out.append(node)
            graph = node.get("@graph")
            if isinstance(graph, list):
                out.extend(n for n in graph if isinstance(n, dict))
    return out


def _strings(node: Any) -> List[str]:
    """Every prose string under ``node``: a string, a dict's text, or a list."""
    out: List[str] = []
    if isinstance(node, str):
        if node.strip():
            out.append(node.strip())
    elif isinstance(node, dict):
        for key in ("text", "name", "itemListElement", "acceptedAnswer", "suggestedAnswer"):
            out.extend(_strings(node.get(key)))
    elif isinstance(node, list):
        for item in node:
            out.extend(_strings(item))
    return out


def _node_lines(node: Dict[str, Any], kind: str) -> List[str]:
    """Markdown for one JSON-LD node, or nothing when it carries no body."""
    lines: List[str] = []
    title = _norm(str(node.get("headline") or node.get("name") or ""))
    if kind == "article":
        body = _strings(node.get("articleBody") or node.get("text"))
        if not body:
            return []
        if title:
            lines += [f"# {title}", ""]
        lines += [b for b in body if b]
    elif kind == "recipe":
        ingredients = [str(i).strip() for i in (node.get("recipeIngredient") or []) if str(i).strip()]
        steps = _strings(node.get("recipeInstructions"))
        if not ingredients and not steps:
            return []
        if title:
            lines += [f"# {title}", ""]
        if ingredients:
            lines.append("## Ingredients")
            lines += [f"- {i}" for i in ingredients]
            lines.append("")
        if steps:
            lines.append("## Directions")
            lines += [f"{n}. {s}" for n, s in enumerate(steps, 1)]
            lines.append("")
    elif kind == "faq":
        main_entity = node.get("mainEntity")
        entities = main_entity if isinstance(main_entity, list) else [main_entity]
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            question = _norm(str(entity.get("name") or ""))
            answers = _strings(entity.get("acceptedAnswer"))
            if not question or not answers:
                continue
            lines += [f"## {question}", ""]
            lines += answers
            lines.append("")
    elif kind == "discussion":
        body = _strings(node.get("articleBody") or node.get("text"))
        comments = _strings(node.get("comment"))
        if not body and not comments:
            return []
        if title:
            lines += [f"# {title}", ""]
        lines += body
        for comment in comments:
            lines += [f"> {comment}", ""]
    elif kind == "video":
        body = _strings(node.get("description"))
        if not body and not title:
            return []
        if title:
            lines += [f"# {title}", ""]
        lines += body
    return lines


def _pays_for_the_rest(html_or_text: str) -> bool:
    """True when the page says the rest of it is sold.

    The words a wall puts in a button (:data:`searchts.expand.PAY_LABELS`) and
    the sentences it puts in the body (``PAY_TEXT_RE``) are both checked, on
    the page with script and style bodies dropped, so a phrase that only
    appears inside a locale bundle does not count.
    """
    from searchts.expand import PAY_LABELS, paywall_in
    from searchts.walls import scrub

    if paywall_in(html_or_text):
        return True
    low = scrub(html_or_text or "").lower()
    return any(label in low for label in PAY_LABELS)


def structured_text(html: str) -> str:
    """The page's own JSON-LD as Markdown, or ``""`` when it holds no body.

    F24b. No second request and no guess about the host: the bytes already
    downloaded often carry the whole article as data, and a client-rendered
    page serves almost nothing else. This only *supplies* text; it never
    replaces a longer extract, so a page whose markup reads well is untouched.

    A paywalled page is refused here on purpose. Its structured body is the
    copy the paywall is charging for, and reading it out of the markup would be
    the thing ``--expand`` refuses to do with a "continue reading" button.
    """
    if not html or "application/ld+json" not in html:
        return ""
    try:
        if _pays_for_the_rest(html):
            return ""
        lines: List[str] = []
        for node in _ld_nodes(html):
            kind = _node_kind(node)
            if not kind:
                continue
            lines.extend(_node_lines(node, kind))
        text = "\n".join(lines).strip()
        return text if len(_norm(text)) >= _STRUCTURED_MIN_CHARS else ""
    except Exception:  # noqa: BLE001 - structured data is an extra, never a failure
        return ""


# ── F24c: one line saying where this page came from ───────────────────────────

#: A field longer than this is a sentence or a keyword list, not a name.
_CONTEXT_MAX_FIELD = 60
#: The whole line stops being one line past this.
_CONTEXT_MAX_CHARS = 200

_SITE_KEYS = ("og:site_name", "application-name", "twitter:site")
_SECTION_KEYS = ("article:section", "og:article:section", "section", "parsely-section")
_AUTHOR_KEYS = ("author", "article:author", "og:article:author", "byl", "parsely-author")
_DATE_KEYS = ("article:published_time", "og:article:published_time", "date", "pubdate", "dc.date")


def _meta(doc) -> Dict[str, str]:
    """The page's own ``<meta>`` values, first one wins for a name."""
    out: Dict[str, str] = {}
    for el in doc.xpath("//meta[@content]"):
        key = (el.get("property") or el.get("name") or el.get("itemprop") or "").strip().lower()
        value = _norm(el.get("content") or "")
        if key and value and key not in out:
            out[key] = value
    return out


def _field(value: str) -> str:
    """A name, or nothing: a value too long for one is a sentence or a tag list.

    Truncated, it would read as a complete name that is not one.
    """
    value = _norm(str(value or ""))
    return value if 0 < len(value) <= _CONTEXT_MAX_FIELD else ""


def _first(meta: Dict[str, str], keys) -> str:
    for key in keys:
        value = _field(meta.get(key, ""))
        if value and not value.lower().startswith(("http://", "https://")):
            return value
    return ""


def _first_string(value: Any) -> str:
    """The first string in a JSON-LD value, which may be a list of them."""
    if isinstance(value, str):
        return _field(value)
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return _field(item)
    return ""


def _ld_meta(html: str) -> Dict[str, str]:
    """``siteName``/``articleSection``/``author``/``datePublished`` from the data."""
    out: Dict[str, str] = {}
    for node in _ld_nodes(html):
        name = _field(str(node.get("name") or ""))
        publisher = node.get("publisher")
        if isinstance(publisher, dict):
            out.setdefault("site", _field(str(publisher.get("name") or "")))
        if name:
            out.setdefault("site", name)
        for src, key in (
            ("siteName", "site"),
            ("articleSection", "section"),
            ("datePublished", "date"),
        ):
            value = _first_string(node.get(src))
            if value:
                out.setdefault(key, value)
        author = node.get("author") or node.get("creator")
        if isinstance(author, dict):
            author = author.get("name")
        if isinstance(author, list) and author:
            author = author[0].get("name") if isinstance(author[0], dict) else author[0]
        value = _field(str(author)) if isinstance(author, (str, int)) else ""
        if value:
            out.setdefault("author", value)
    return out


def context_line(doc, html: str, url: str = "") -> str:
    """One line: the site, the section, the author and the date, or ``""``.

    F24c. Every field comes out of the bytes already downloaded: the ``<meta>``
    the page ships and the JSON-LD beside it. Nothing is looked up, nothing is
    inferred from the content, and a field the page does not state is left out
    rather than guessed at, so the site is never filled in from the URL the
    caller already has.

    Fewer than two fields is not context, it is a repetition: a line naming
    only the site says nothing the caller does not already have, so there is
    no line.
    """
    if not html or doc is None:
        return ""
    try:
        meta = _meta(doc)
        data = _ld_meta(html)
        site = _first(meta, _SITE_KEYS) or data.get("site", "")
        # The data first for a section: a CMS meta tag on a real page read
        # "tags" while its own JSON-LD said "security".
        section = data.get("section", "") or _first(meta, _SECTION_KEYS)
        author = _first(meta, _AUTHOR_KEYS) or data.get("author", "")
        date = _first(meta, _DATE_KEYS) or data.get("date", "")
        if date and len(date) >= 10 and date[4] == "-" and date[7] == "-":
            date = date[:10]
        parts = []
        if site:
            parts.append(site)
        if section and section.lower() != site.lower():
            parts.append(section)
        if author and author.lower() not in (site.lower(), section.lower()):
            parts.append(f"by {author}")
        if date:
            parts.append(date)
        if len(parts) < 2:
            # One field is not context: it repeats what the page already says.
            return ""
        line = "[page: " + " · ".join(parts) + "]"
        return line if len(line) <= _CONTEXT_MAX_CHARS else ""
    except Exception:  # noqa: BLE001 - context is an extra, never a failure
        return ""
