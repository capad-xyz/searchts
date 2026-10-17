# -*- coding: utf-8 -*-
"""F23d: open the text the page is holding back, when someone asks for it.

A page can hold text behind three things, and only three:

1. a **native** ``<details>`` that is closed. The text is in the HTML. Nothing
   to click: set ``open`` and the extractor can see it.
2. an **accordion** toggle (``aria-expanded="false"``) whose panel is
   ``display:none``. Also in the HTML. ``more.prepare_panels`` already un-hides
   these so the questions and answers survive Trafilatura; this module is the
   opt-in that says how many there were.
3. a **button** labelled read/show/see more. This one is JavaScript. The label
   is in the HTML, the text behind it is not, so it needs a browser to press.

## What is never pressed

* a **link**. A control whose ``href`` leaves the page is navigation, and
  following it means the read stops being a read of the URL it was given.
* anything in a **form**, or a submit/button that posts. A form button is a
  vote, a subscribe, a comment box, a search box.
* **sign-in**. The refusal list is checked before the allow list, because
  "accept" is in "accept all cookies" and "sign in to continue reading"
  contains "continue".
* a **paywall**. ``continue reading`` on a news article is a subscription gate,
  not a fold. It is *named* - the read says there is a paywall here - and left
  alone. Working around a paywall is not this module's job and never will be.

## Why it is opt-in

Auto-clicking changes the read: it makes it slower, it makes it different every
time, and on a page full of "Show more" trackers it makes it click things. So a
site nobody has a selector for gets no clicks unless the caller asked. Known
hosts keep their own selectors (``known_hosts``) and expand by default, which
is the one exception and it is a known-selector exception, not a universal one.

Two surfaces, one module: :func:`expand_html` is the whole of it with no
browser, and :func:`click_in_page` is the browser half. Both are importable
without ``patchright``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "Report",
    "expand_html",
    "eligible_labels",
    "find_in_page",
    "click_in_page",
    "paywall_in",
    "PAY_LABELS",
    "REFUSE_LABELS",
    "EXPAND_RE",
    "EXPAND_EXACT_RE",
    "FEED_NOUNS",
    "FEED_FOLD_RE",
]


#: The phrase that says "the rest of this item is behind me", before any noun
#: that follows it. Shared with the detector in :mod:`searchts.more` so the note
#: a read prints and the control ``--expand`` presses are the same list, by
#: construction rather than by a comment staying true.
_FOLD_PHRASE = r"(?:read|show|see|view)\s+(?:more|all|full|the\s+(?:rest|full\s+\w+))"

#: A control whose whole label is that phrase and nothing else.
EXPAND_EXACT_RE = re.compile(rf"^{_FOLD_PHRASE}[\s.…»›>]*$", re.I)

#: The same phrase with one word after it, which is how the noun arrives on a
#: real page: "Show all reviews", "See full compatibility", "Show all 42
#: comments". Measured on 26 unknown hosts this adds the folds the exact form
#: missed and nothing else: "Show Search", "load()", "See also" and "Open
#: source" are all rejected, because the phrase has to come first.
#:
#: "Load more" is excluded here on purpose: that is a feed, and
#: :mod:`searchts.scroll` owns it.
EXPAND_RE = re.compile(rf"^{_FOLD_PHRASE}(?:\s+\w+)?[\s.…»›>]*$", re.I)

#: Nouns that make "Show more X" a request for more items, not more of one
#: item: that is a feed, and :mod:`searchts.scroll` owns it. One list, read by
#: the detector's feed test in :mod:`searchts.more`, by :func:`_verdict` and by
#: the browser finder, so none of the three can drift from the others.
FEED_NOUNS: Tuple[str, ...] = (
    "posts", "stories", "results", "items", "articles", "comments", "replies",
    "products", "videos", "news",
)

#: "Show more results", "See all products": the fold phrase followed by one of
#: :data:`FEED_NOUNS`. Never a fold, whether the label says "more" or "all".
FEED_FOLD_RE = re.compile(
    r"^(?:show|see|view)\s+(?:more|all)\s+(?:" + "|".join(FEED_NOUNS) + r")[\s.…]*$",
    re.I,
)

#: Labels that mean the rest of the page is sold, not folded. Named, never
#: pressed. ``read more`` is deliberately absent: on its own it is a fold.
PAY_LABELS: Tuple[str, ...] = (
    "continue reading",
    "continue to read",
    "read the rest with a subscription",
    "subscribe to continue",
    "subscribe to read",
    "sign in to continue",
    "unlock this article",
    "unlock this story",
    "this article is for subscribers",
    "for subscribers only",
    "become a subscriber to read",
)

#: Controls whose label means "do something to the account or to the page".
#: Checked before the allow list, so a refusal always wins.
REFUSE_LABELS: Tuple[str, ...] = (
    "sign in",
    "sign up",
    "log in",
    "log on",
    "register",
    "subscribe",
    "buy",
    "purchase",
    "pay",
    "checkout",
    "donate",
    "tip",
    "accept",
    "agree",
    "consent",
    "cookie",
    "newsletter",
    "uninstall",
    "download",
    "vote",
    "reply",
    "comment",
    "share",
    "save",
    "bookmark",
    "follow",
    "like",
)

#: Wording a paywall puts in the page *text* when the button is an image or an
#: anchor with no useful label. Observed on a real article:
#: wired.com/story/announcing-wired-paywall served "subscribe to read further"
#: and "for unlimited access, subscribe here" for a body that stopped mid
#: article. Those sentences are the signal; the read names them and stops.
PAY_TEXT_RE = re.compile(
    r"(?i)\b(?:subscribe\s+to\s+read\s+further|for\s+(?:full|unlimited)\s+access[,.]?\s*"
    r"subscribe|this\s+(?:story|article)\s+is\s+for\s+subscribers|"
    r"subscribers?\s+only|continue\s+reading\s+to\s+access)\b"
)

#: Chrome a closed ``<details>`` inside is *not* expanded from.
#:
#: Deliberately narrower than the chrome list the fold detector uses, and the
#: difference is measured rather than stylistic. On
#: developer.mozilla.org/.../Elements/details the seven closed ``<details>``
#: elements holding the "Attributes by element", "<script type>" and
#: "<meta name>" tables all sit inside an ``<aside>``; excluding that tag left
#: every one of them closed and missing from the read. What is left here is the
#: set where a ``<details>`` is a form, a cookie bar or a legal notice rather
#: than reference content. The *button* half keeps the wide list (see
#: :data:`_FIND_JS`), because a "See all…" in a nav is navigation even when the
#: label fits: clicking is an action, opening a ``<details>`` is a rewrite of
#: the HTML we were already given.
_FOLD_CHROME_TAGS = frozenset({"header", "footer", "form", "dialog", "template"})
_FOLD_CHROME_RE = re.compile(
    r"(?:^|\s)(?:cookie|consent|gdpr|newsletter|signup)(?:\s|$)", re.I
)


@dataclass
class Report:
    """What an expand pass did, and what it refused to do."""

    #: HTML after opening closed ``<details>``. Always a string, even when
    #: nothing changed, so a caller never has to check.
    html: str = ""
    #: ``<details>`` elements this pass opened.
    details: int = 0
    #: Characters the extract gained from opening them, when the pass measured
    #: it (the markup half does: it extracts before and after). ``None`` means
    #: not measured, as on the browser half, where a live DOM was really opened.
    added_chars: Optional[int] = None
    #: Buttons this pass pressed (browser half only).
    clicks: int = 0
    #: Eligible buttons seen in the HTML. With no browser they are named in the
    #: note instead of pressed, so the caller learns why the text is still short.
    buttons: int = 0
    #: Labels it pressed, in order, for the note and for tests.
    clicked: List[str] = field(default_factory=list)
    #: A paywall was seen: the reason the text is still missing.
    paywall: bool = False
    #: Why the pass stopped early, or "" when it did not.
    stop: str = ""
    #: A "continue reading" control seen and deliberately not pressed, on a page
    #: with no subscription wording of its own. Kept apart from ``paywall`` so a
    #: site that folds with a button reading "continue reading" is not told it
    #: is paywalled.
    skipped: str = ""

    def pin_paywall(self, page_html: str = "") -> "Report":
        """Decide the paywall claim from evidence, and set it.

        Two kinds of evidence, and the strong one wins:

        * the page's own wording ("subscribe to read further"), which is what a
          real paywall says; or
        * a control whose label is unambiguously about a subscription
          ("subscribe to continue", "for subscribers only").

        A bare "continue reading" is not enough on its own. Some sites fold an
        article behind a button with that name and nothing is for sale, and
        telling the reader there is a paywall there would be a lie in the
        direction that matters: it would teach them that a named wall is
        sometimes not a wall. So that case is recorded in ``skipped`` and the
        button is left alone either way.
        """
        html = page_html or ""
        if paywall_in(html):
            self.paywall = True
            return self
        if any("subscri" in p for p in PAY_LABELS) and self._saw_pay_label:
            self.paywall = True
        return self

    _saw_pay_label: bool = False

    def note(self) -> str:
        """The trailing line for the read, or ``""`` when nothing happened."""
        bits: List[str] = []
        if self.details and self.added_chars is not None and self.added_chars <= 0:
            # The markup already held their text and the extractor already read
            # it closed. "Opened" would suggest text came out of it.
            bits.append(
                f"{self.details} <details> section(s) were already readable in "
                "the markup; opening them added no text"
            )
        elif self.details and self.added_chars:
            bits.append(
                f"{self.details} <details> section(s) opened "
                f"(+{self.added_chars} chars of text)"
            )
        elif self.details:
            bits.append(f"{self.details} <details> section(s) opened")
        if self.clicks:
            said = ", ".join(f'"{c}"' for c in self.clicked[:3])
            bits.append(f"{self.clicks} button(s) pressed ({said})")
        elif self.buttons:
            bits.append(
                f"{self.buttons} read/show/see-more button(s) need a browser: "
                "searchts install --browser"
            )
        if self.paywall:
            from searchts.knobs import PAYWALL_NOTE

            bits.append(PAYWALL_NOTE[len("[paywall: ") : -1])
        if self.skipped:
            bits.append(self.skipped)
        if self.stop:
            bits.append(self.stop)
        if not bits:
            return ""
        return "[expand: " + "; ".join(bits) + "]"

    def produced(self) -> bool:
        """True when this pass found evidence of text being held back.

        A control the page builds in JavaScript is not in the HTML, so the HTML
        pass can find none and still the page be holding text back. Measured:
        "Show more" on kickstarter.com/discover/advanced appears zero times in
        the served HTML and twice in the rendered DOM, where one press is worth
        +4,102 characters. The ladder uses this to decide whether the markup
        rung answered the question or whether the browser has to be asked.

        A page with nothing to open is False, which is the point: silence from
        the markup is what sends the ladder up.
        """
        return bool(self.details or self.clicks or self.buttons or self.paywall
                    or self.skipped)


def _norm(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _in_chrome(el) -> bool:
    node = el
    while node is not None:
        tag = node.tag.lower() if isinstance(node.tag, str) else ""
        if tag in _FOLD_CHROME_TAGS:
            return True
        if _FOLD_CHROME_RE.search(node.get("class") or ""):
            return True
        node = node.getparent()
    return False


def eligible_labels(html: str) -> Tuple[int, str]:
    """(how many expandable controls, the first label) in one HTML string.

    Used on the curl rung to decide whether a read could have more text, so it
    is the same predicate the browser half applies: something that can be
    pressed at all, carrying a label :data:`EXPAND_RE` accepts, that
    :data:`PAY_LABELS` and :data:`REFUSE_LABELS` do not veto, that is not page
    chrome and is not a link out of the page and not inside a form.
    """
    try:
        import lxml.html

        doc = lxml.html.fromstring(html or "")
    except Exception:  # noqa: BLE001 - counting never fails a read
        return 0, ""
    count, first = 0, ""
    for el in doc.iter():
        if not isinstance(el.tag, str):
            continue
        label = _norm(el.text_content())
        if not label or len(label) > 60:
            continue
        if _verdict(label, tag=el.tag.lower(), href=el.get("href"),
                    role=(el.get("role") or "").lower(),
                    in_form=bool(el.xpath("ancestor::form"))) == "yes":
            count += 1
            first = first or label
    return count, first


def _verdict(label: str, tag: str, href: Optional[str], in_form: bool,
             role: str = "") -> str:
    """``"paywall"``, ``"no"`` or ``"yes"`` for one control label.

    Split out from the DOM walk so the browser half, which has a label, a tag
    and a role, and the HTML half, which has a tree, reach the same verdict.

    The tag test comes first, before the label test. A ``<li>`` holding "See
    all…" matches :data:`EXPAND_RE` and is not a control, and a version of this
    file that only looked at labels reported "18 read/show/see-more buttons"
    on a page that has none.
    """
    low = label.lower().strip(" .…»›>")
    if not low:
        return "no"
    if any(bad in low for bad in PAY_LABELS):
        return "paywall"
    pressable = (
        tag in ("button", "summary")
        or role in ("button", "link")
        or (tag == "a" and ((href or "").startswith("#")
                            or (href or "").lower().startswith("javascript:")))
    )
    if not pressable:
        return "no"
    if any(bad in low for bad in REFUSE_LABELS):
        return "no"
    if not EXPAND_RE.match(label) or FEED_FOLD_RE.match(label):
        return "no"
    if in_form:
        return "no"
    if tag == "a":
        # A link out of the page is navigation, and the pressable test above
        # already admitted only the ones that stay put.
        href = (href or "").strip()
        if href and not href.startswith("#") and not href.lower().startswith("javascript:"):
            return "no"
    if tag in ("input", "select", "textarea"):
        return "no"
    return "yes"


def paywall_in(html_or_text: str) -> bool:
    """True when this page says in so many words that the rest is sold."""
    from searchts.walls import scrub

    low = scrub(html_or_text or "").lower()
    return bool(PAY_TEXT_RE.search(low))


# ── the HTML half: no browser needed ──────────────────────────────────────────


def expand_html(html: str, max_details: int = 200) -> Report:
    """Open every closed ``<details>`` in ``html`` and report what was there.

    This is the part of ``--expand`` that works on the curl rung, and it is not
    a click: the text behind a native ``<details>`` is already in the HTML, and
    the extractor drops it only because the element is closed. Setting ``open``
    is a rewrite of what we were given, not a request to somebody's server.
    """
    rep = Report(html=html or "")
    if not html or not html.strip():
        return rep
    try:
        import lxml.html

        doc = lxml.html.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", html))
    except Exception:  # noqa: BLE001 - an unparsable page is simply not expanded
        rep.paywall = paywall_in(html)
        return rep
    try:
        for el in doc.iter("details"):
            if "open" in el.attrib:
                continue
            if _in_chrome(el):
                continue
            el.set("open", "")
            rep.details += 1
            if rep.details >= max_details:
                break
        if rep.details:
            rep.html = lxml.html.tostring(doc, encoding="unicode")
        rep.paywall = paywall_in(html)
        # Buttons are counted even though nothing can be pressed here: the note
        # then says why the text behind them is still missing, which is the
        # difference between "this is the whole page" and "we did not have a
        # browser". Counted on the *closed* html so the number is the page's.
        rep.buttons, _first = eligible_labels(html)
    except Exception:  # noqa: BLE001 - never lose a read over a preprocessing step
        return Report(html=html)
    if not rep.produced():
        rep.stop = (
            "nothing in this page's markup answered to <details> or a "
            "read/show/see-more button"
        )
    return rep


# ── the browser half ──────────────────────────────────────────────────────────

#: In-page finder. One JS blob, evaluated against the live DOM, so the labels
#: that matter are the ones a person can actually see, and the same
#: :func:`_verdict` shape decides. A control that is hidden, disabled, inside a
#: form, or an anchor that navigates is skipped here as well as in Python, so
#: the two halves cannot disagree about the same button.
_FIND_JS_TEMPLATE = r"""
() => {
  const PAY = __PAY__;
  const NO = __NO__;
  const RE = new RegExp(__RE__, "i");
  const FEED = new RegExp(__FEED__, "i");
  const seen = new Set();
  const out = [];
  let n = 0;
  const walk = (root) => {
    for (const el of root.querySelectorAll('button,summary,[role=button],[role=link],a')) {
      if (seen.has(el)) continue;
      seen.add(el);
      const raw = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
      if (!raw || raw.length > 60) continue;
      const low = raw.toLowerCase().replace(/[ .…»›>]+$/, '');
      if (PAY.some((x) => low.includes(x))) { out.push({label: raw, why: 'paywall'}); continue; }
      if (NO.some((x) => low.includes(x))) continue;
      if (!RE.test(raw) || FEED.test(raw)) continue;
      if (el.closest('form, header, footer, aside, nav, dialog')) continue;
      if (el.tagName === 'A') {
        const href = el.getAttribute('href') || '';
        if (href && !href.startsWith('#') && !/^javascript:/i.test(href)) continue;
      }
      let off = false;
      try { off = !(el.offsetWidth || el.offsetHeight || el.getClientRects().length); } catch (e) { off = true; }
      if (off) continue;
      try { if (el.disabled) continue; } catch (e) { continue; }
      // Only an element a press can reach is marked, and the mark is what
      // the press finds again. A label is not an identity: a form, a nav or an
      // aside can hold a button with the same words, and pressing the first
      // match by label presses that one instead of this one.
      let idx = null;
      if (el.matches('button,[role=button]')) {
        idx = n++;
        el.setAttribute('data-searchts-expand', String(idx));
      }
      out.push({label: raw, why: 'yes', tag: el.tagName, idx: idx});
    }
  };
  walk(document);
  return out;
}
"""

#: The finder as the browser runs it. Every list and pattern is generated from
#: the Python ones above, so ``--expand`` presses what the HTML count named.
_FIND_JS = (
    _FIND_JS_TEMPLATE
    .replace("__PAY__", json.dumps(list(PAY_LABELS)))
    .replace("__NO__", json.dumps(list(REFUSE_LABELS)))
    .replace("__RE__", json.dumps(EXPAND_RE.pattern))
    .replace("__FEED__", json.dumps(FEED_FOLD_RE.pattern))
)


def find_in_page(page) -> List[Dict[str, Any]]:
    """Controls this page shows that ``--expand`` is allowed to press.

    Reads the live DOM. Never raises: a page that will not answer is a page
    with no eligible controls, which the caller already handles.
    """
    try:
        out = page.evaluate(_FIND_JS)
    except Exception:  # noqa: BLE001 - a dead page has nothing to expand
        return []
    return [c for c in out if isinstance(c, dict)]


def click_in_page(page, max_clicks: int) -> Report:
    """Press up to ``max_clicks`` eligible controls and report what happened.

    One pass, one press per control, then a settle. There is no retry loop: a
    second press on the same control is guessing, and a control that says "read
    more" and then says it again has stopped giving us text.
    """
    rep = Report()
    found = find_in_page(page)
    paywall = [c for c in found if c.get("why") == "paywall"]
    wanted = [c for c in found if c.get("why") == "yes"]
    if paywall:
        rep._saw_pay_label = True
        rep.skipped = (
            f'{len(paywall)} paywall control(s) such as "{paywall[0].get("label")}" '
            "were named and left alone"
        )
    if not wanted:
        if not rep.produced():
            rep.stop = (
                "nothing on the rendered page answered to a read/show/see-more "
                "button"
            )
        return rep
    for control in wanted:
        if rep.clicks >= max_clicks:
            rep.stop = f"stopped at the ceiling of {max_clicks} press(es)"
            break
        label = control.get("label") or ""
        idx = control.get("idx")
        if idx is None:
            # Found, but not a button a press can reach (a ``<summary>`` or a
            # same-page anchor): counted by the finder, never pressed here.
            continue
        # The element the finder vetted, found by the mark it left on it, never
        # by its label (see _FIND_JS). Two controls can read "Show more" - on
        # kickstarter.com/discover/advanced both do - and each has its own mark,
        # so the second press cannot land on the element the first one used.
        try:
            handle = page.query_selector(f'[data-searchts-expand="{int(idx)}"]')
        except Exception:  # noqa: BLE001 - no handle means no click
            handle = None
        if handle is None:
            continue
        try:
            handle.click(timeout=3000)
        except Exception:  # noqa: BLE001 - an unclickable control is a skip
            continue
        try:
            page.wait_for_timeout(700)
        except Exception:  # noqa: BLE001
            pass
        rep.clicks += 1
        rep.clicked.append(label)
    return rep


def open_details_in_page(page) -> int:
    """Set ``open`` on every closed ``<details>`` the live page shows.

    The browser twin of :func:`expand_html`. A page that renders its ``<details>``
    client-side only has them after hydration, so the curl rung can never see
    those; that is why both exist.
    """
    try:
        n = page.evaluate(
            "() => { let n = 0;"
            " for (const d of document.querySelectorAll('details')) {"
            "   if (!d.open) { d.open = true; n++; } }"
            " return n; }"
        )
        return int(n or 0)
    except Exception:  # noqa: BLE001 - a page that will not answer has none
        return 0
