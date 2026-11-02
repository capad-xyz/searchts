# -*- coding: utf-8 -*-
"""F23c: a list that only grows by scrolling.

``--items`` already follows a next-batch URL for list rows (F23b/F23f). This is
the other shape: a feed that grows when the window reaches the bottom and has
no URL for the next batch, because there is no next batch - it is the same page
with more of itself in it.

## The rules, and why each one is there

**Probe first.** One step, then look. A page that does not grow is not a feed,
and scrolling it forty times to be sure is forty wasted seconds on every
ordinary article. So the probe is a step like any other, and "nothing changed"
ends the walk on the first step.

**Copy rows every step.** A virtualized feed *unmounts* rows it has scrolled
past. Measured on reddit.com/r/python with a real Chromium on 2026-10-17: the
live row count went 7, 11, 24, 25, 25, 29, 29, **25**, 25 over eight steps - it
went *down* by four. A loop that counts rows at the end loses four real posts
and reports a smaller list than the page actually showed. So each step copies
the rows it can see into a page-side store keyed by link or text, and the store
is never pruned. The final HTML is the store, so the extractor sees all of them.

**Click a stalled "Load more".** Some feeds stop growing on scroll and put a
button there instead. A step that adds nothing but finds a "Load more" control
presses it once, which is the same intent by another mechanism. One press per
step, and the press is on a ``<button>``: a "Load more" *link* is a next-batch
URL, which the curl path already follows.

**Stop at N rows, after the configured empty steps, on a wall, or at the clock.**
Each stop names itself. "Stopped: the page stopped growing" and "stopped: a
login wall" are different facts and a caller acting on them does different
things.

**No browser, say so.** Content that only arrives with JavaScript needs the
stealth rung. When it is not installed the read says
``searchts install --browser`` instead of quietly returning the first window.

Nothing here runs on the curl rung and nothing here is a second read path: the
loop drives the same stealth Chromium the ladder already uses, and its output
is that rung's HTML, extracted by the same extractor.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from html import escape
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin

from searchts import resume as resume_mod

__all__ = ["ScrollReport", "collect", "NO_BROWSER", "LoadMore"]


#: What a read says when it needed a browser to see the rest and there is none.
NO_BROWSER = "[scroll: this list only grows in the browser. Run: searchts install --browser]"


@dataclass
class LoadMore:
    """A "Load more" control seen on the page."""

    label: str
    #: Set when the control is a ``<button>``. A link is a next-batch URL and is
    #: left to the curl path, which already follows one.
    is_button: bool = False


@dataclass
class ScrollReport:
    """What the scroll pass collected, and why it stopped."""

    #: HTML with every row seen at any step put back in.
    html: str = ""
    #: Rows the store holds, in first-seen order.
    rows: List[str] = field(default_factory=list)
    #: Rows the page showed when we started.
    start_rows: int = 0
    #: How many scroll steps ran.
    steps: int = 0
    #: "Load more" presses spent.
    clicks: int = 0
    #: ``(reason, sentence)``. Exactly one of these, and it is always set.
    stop: str = ""
    #: The wall that stopped it, when a wall did.
    wall: str = ""
    #: Milliseconds spent.
    elapsed_ms: int = 0
    #: Row keys the store held, in first-seen order. The resume token keeps a
    #: tail of these so the next walk can recognise the seam.
    keys: List[str] = field(default_factory=list)
    #: The page's own pagination cursor, captured passively from its JSON data
    #: responses while scrolling (never requested).
    cursor: str = ""
    #: The data request that produced :attr:`cursor`, as ``{u, m, b, f}``.
    replay: Optional[Dict[str, str]] = None
    #: The URL the walk actually read, after any position bump.
    page_url: str = ""
    #: How a resumed walk picked up: ``cursor``, ``fast-skip``,
    #: ``url-position`` or ``changed``. Empty on a first read.
    resume_method: str = ""
    #: True when a resumed walk recognised at least one key from its token.
    resume_found: bool = False
    #: A same-site data response said 429 (#509 applies to scroll too).
    rate_limited: bool = False

    def note(self) -> str:
        """The trailing line for the read, or ``""`` when nothing happened."""
        if self.stop == "not-a-feed":
            return ""  # a page that does not grow is not news; nothing to say
        got = len(self.rows)
        bits = [f"{got} list row(s) after {self.steps} scroll step(s)"]
        if self.clicks:
            bits.append(f"{self.clicks} \"Load more\" press(es)")
        if self.wall:
            bits.append(f"a {self.wall} wall stopped the scroll")
        if self.resume_method:
            bits.append(self._resume_sentence())
        if self.rate_limited:
            bits.append("the site rate-limited the feed (429); rows so far are kept")
        bits.append(self.stop)
        return "[scroll: " + "; ".join(b for b in bits if b) + "]"

    def _resume_sentence(self) -> str:
        if self.resume_method == "cursor":
            return "resumed at the feed's own captured cursor"
        if self.resume_method == "fast-skip":
            return "resumed after the last row this token had"
        if self.resume_method == "url-position":
            return "resumed at the next page in the URL"
        return (
            "the feed changed; resumed from the top of what is there now"
        )


# ── in-page helpers (JS, evaluated against the live DOM) ──────────────────────

#: Visibility, as the page sees it. Hidden nodes are not rows even when they
#: repeat: a collapsed list and its expanded copy are the same page.
_SHOWN_JS = r"""
  const shown = (el) => {
    let n = el;
    while (n && n !== document.documentElement) {
      const s = n.getAttribute && n.getAttribute('style');
      if (s && /display\s*:\s*none|visibility\s*:\s*hidden/.test(s)) return false;
      if (n.hasAttribute && (n.hasAttribute('hidden') || n.getAttribute('aria-hidden') === 'true')) return false;
      n = n.parentElement;
    }
    return true;
  };
"""

#: A row is something that links somewhere **inside** the site, at least two path
#: segments deep.
#:
#: This is what keeps page chrome out, rather than a "was this the container I
#: picked before" rule. A nav row points at /about or /explore; a feed row
#: points deep into an item (/r/python/comments/1abc/, /t/some-topic/1234).
#: Measured on reddit.com/r/python, where a nav rail and a "Popular / News /
#: Explore" column sit right beside the feed and would otherwise win.
#:
#: It was added because the first version's winner there was the container of
#: ``<p>`` post *bodies*: 24 of them, all long enough, all under one (tag, class)
#: key, and not one of them an item. The read collected 24 rows and delivered
#: nothing a caller could use.
_DEEP_LINK_JS = r"""
  const deepLink = (el) => {
    for (const a of el.querySelectorAll('a[href]')) {
      const href = a.getAttribute('href') || '';
      if (!href || href.startsWith('#') || /^(javascript:|mailto:)/i.test(href)) continue;
      let path = href;
      const q = path.indexOf('?');
      if (q >= 0) path = path.slice(0, q);
      const f = path.indexOf('#');
      if (f >= 0) path = path.slice(0, f);
      const scheme = path.indexOf('://');
      if (scheme >= 0) path = path.slice(scheme + 3).split('/').slice(1).join('/');
      if (path.split('/').filter(Boolean).length >= 2) return true;
    }
    return false;
  };
"""

#: The repeated-items walk. Picks the parent whose visible children repeat most
#: under one (tag, first class) key, where every one of those children is a row.
#: This is the browser twin of ``more._best_list``: same idea, no shared code,
#: because one runs on a DOM tree and the other on an HTML string and neither
#: can import the other.
_FIND_LIST_JS = "() => {\n" + _SHOWN_JS + _DEEP_LINK_JS + r"""
  let best = null, bestN = 0;
  const walk = (el) => {
    if (!el || !el.children) return;
    const groups = new Map();
    for (const c of el.children) {
      if (!shown(c)) continue;
      const t = (c.textContent || '').replace(/\s+/g, ' ').trim();
      if (t.length < 25) continue;
      if (!deepLink(c)) continue;
      const cls = (c.getAttribute('class') || '').split(/\s+/)[0] || '';
      const key = c.tagName + '|' + cls;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(c);
    }
    for (const items of groups.values()) {
      if (items.length > bestN) { bestN = items.length; best = items; }
    }
    for (const c of el.children) walk(c);
  };
  walk(document.body);
  if (!best || bestN < 3) return null;
  // Mark the rows so the next step can find the same set again even when the
  // container is re-rendered under us.
  const parent = best[0].parentElement;
  if (!parent) return null;
  if (!parent.hasAttribute('data-searchts-list')) parent.setAttribute('data-searchts-list', '1');
  for (const el of best) {
    if (!el.hasAttribute('data-searchts-row')) el.setAttribute('data-searchts-row', '1');
  }
  return {rows: best.length, parent: !!parent};
}
"""

#: Copy every currently-visible row into the page-side store, keyed so a row
#: that scrolls away and a row that scrolls back are the same row. The key is
#: the row's first real href when it has one, otherwise a hash of its text: a
#: link is the identity of a post and text is the identity of everything else.
#:
#: The list is **re-found on every step, not once**. A virtualized feed replaces
#: its own rows as you scroll: measured on reddit.com/r/python the container the
#: probe marked held 12 children at the start and the posts after it lived in a
#: different subtree, so a pass that trusted the mark stopped at 9 rows on a
#: page showing 25. There is no "only ever use the container I picked first"
#: guard, because :data:`_DEEP_LINK_JS` already keeps chrome out; switching
#: containers costs nothing and loses nothing, since the store keeps every row
#: every step saw.
_COLLECT_JS = r"""
() => {
  if (!window.__searchtsStore) {
    window.__searchtsStore = {key: new Map(), order: [], start: 0};
  }
  const store = window.__searchtsStore;
  if (typeof store.start !== 'number') store.start = 0;
""" + _SHOWN_JS + _DEEP_LINK_JS + r"""
  const findBest = () => {
    let best = null, bestN = 0;
    const walk = (el) => {
      if (!el || !el.children) return;
      const groups = new Map();
      for (const c of el.children) {
        if (!shown(c)) continue;
        const t = (c.textContent || '').replace(/\s+/g, ' ').trim();
        if (t.length < 25) continue;
        if (!deepLink(c)) continue;
        const cls = (c.getAttribute('class') || '').split(/\s+/)[0] || '';
        const key = c.tagName + '|' + cls;
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(c);
      }
      for (const items of groups.values()) {
        if (items.length > bestN) { bestN = items.length; best = items; }
      }
      for (const c of el.children) walk(c);
    };
    walk(document.body);
    return best;
  };
  // See the note on _COLLECT_JS: re-found every step, no first-container lock.
  const best = findBest();
  if (!best || best.length < 3) {
    return {rows: 0, total: store.order.length - store.start, added: 0, found: false};
  }
  const parent = best[0].parentElement;
  if (!parent.hasAttribute('data-searchts-list')) parent.setAttribute('data-searchts-list', '1');
  let added = 0;
  for (const el of best) {
    const text = (el.textContent || '').replace(/\s+/g, ' ').trim();
    if (text.length < 25) continue;
    let key = '';
    const a = el.querySelector('a[href]');
    if (a && a.getAttribute('href')) key = 'L' + a.href;
    if (!key) {
      let h = 0;
      for (let i = 0; i < text.length; i++) { h = (h * 31 + text.charCodeAt(i)) | 0; }
      key = 'T' + (h >>> 0) + ':' + text.slice(0, 40);
    }
    if (!el.hasAttribute('data-searchts-row')) el.setAttribute('data-searchts-row', '1');
    if (store.key.has(key)) continue;
    store.key.set(key, el.outerHTML);
    store.order.push(key);
    added++;
  }
  return {rows: best.length, total: store.order.length - store.start,
          added: added, found: true};
}
"""

#: Put the store back into the page so the extractor sees every row, including
#: the ones that unmounted. The live rows are removed first, so the page holds
#: each row exactly once: a read that shows the same post twice is as wrong as
#: one that drops it. Rows go back in first-seen order, so the order of the
#: read matches the order a person scrolled through.
_REBUILD_JS = r"""
() => {
  const store = window.__searchtsStore;
  if (!store) return 0;
  // Every container the loop marked, not just the last one: the feed swaps its
  // own rows under us, so there is usually more than one marked parent by the
  // end and the collected copy has to replace all of them.
  const parents = Array.from(document.querySelectorAll('[data-searchts-list]'));
  if (!parents.length) return 0;
  for (const parent of parents) {
    for (const el of Array.from(parent.children)) {
      if (el.hasAttribute('data-searchts-row')) el.remove();
    }
  }
  const holder = document.createElement('div');
  holder.setAttribute('data-searchts-collected', '1');
  let n = 0;
  const start = typeof store.start === 'number' ? store.start : 0;
  for (const key of store.order.slice(start)) {
    const html = store.key.get(key);
    if (!html) continue;
    const tpl = document.createElement('template');
    tpl.innerHTML = html;
    const node = tpl.content.firstElementChild;
    if (!node) continue;
    node.removeAttribute('data-searchts-row');
    holder.appendChild(node);
    n++;
  }
  parents[0].appendChild(holder);
  for (const parent of parents) parent.removeAttribute('data-searchts-list');
  return n;
}
"""

#: Find a "Load more" control that is a ``<button>``. Anchors are excluded on
#: purpose: an anchor with an href is a next-batch URL and the curl path
#: already follows it, and pressing one here would navigate away from the URL
#: the caller asked for.
_LOAD_MORE_JS = r"""
() => {
  const RE = /^(?:load|show|see|view)\s+more\b/i;
  const NO = /sign in|log ?in|register|subscribe|accept|cookie|consent|newsletter/i;
  for (const el of document.querySelectorAll('button,[role=button]')) {
    const t = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
    if (!t || t.length > 50) continue;
    if (!RE.test(t)) continue;
    if (NO.test(t)) continue;
    if (el.closest('form, header, footer, aside, nav, dialog')) continue;
    let off = false;
    try { off = !(el.offsetWidth || el.offsetHeight || el.getClientRects().length); } catch (e) { off = true; }
    if (off) continue;
    try { if (el.disabled) continue; } catch (e) { continue; }
    return {label: t, tag: el.tagName};
  }
  return null;
}
"""

#: The page-side store, read back out. Same shape as :data:`_COLLECT_JS` but
#: keys *and* html so the caller can build the note and the tests can assert.
_READ_STORE_JS = r"""
() => {
  const s = window.__searchtsStore;
  if (!s) return {order: [], rows: []};
  const start = typeof s.start === 'number' ? s.start : 0;
  const order = s.order.slice(start);
  // `s.order.map` is the shape the loop has always returned. Slicing after
  // the map keeps a resume's hidden head out of the report and still lets a
  // stand-in page recognise this script.
  return {order: order, rows: s.order.map((k) => s.key.get(k)).slice(start)};
}
"""

#: Drop everything up to and including the last row a resume token already
#: has. The feed is fresh at the top, so the walk has to recognise the seam
#: before it can call anything new. Rows before the seam are the old read.
_TRIM_JS = r"""
(keys) => {
  const s = window.__searchtsStore;
  if (!s || !keys || !keys.length) {
    return {dropped: 0, total: s ? s.order.length - (s.start || 0) : 0, found: false};
  }
  if (typeof s.start !== 'number') s.start = 0;
  let last = -1;
  for (let i = 0; i < s.order.length; i++) {
    if (keys.indexOf(s.order[i]) >= 0) last = i;
  }
  if (last < 0) {
    return {dropped: 0, total: s.order.length - s.start, found: false};
  }
  // Keep the old keys in the store, so a row that scrolls back is deduped
  // instead of counted twice. Only the *report* starts after the seam.
  if (last + 1 > s.start) s.start = last + 1;
  return {dropped: s.start, total: s.order.length - s.start, found: true};
}
"""

#: A cursor replay is an exact continuation, so the top-of-feed rows the page
#: rendered on arrival are not part of the report. Their keys stay in the
#: store, so a later scroll step dedupes them instead of counting them again.
#: Only the report's start moves, which is what the trim below does too.
_HIDE_SEEN_JS = r"""
() => {
  const s = window.__searchtsStore;
  if (!s) return 0;
  if (typeof s.start !== 'number') s.start = 0;
  const hidden = s.order.length - s.start;
  s.start = s.order.length;
  return hidden;
}
"""

#: Rows recovered by replaying the feed's own captured cursor, put where the
#: extractor will see them: the same page-side store the scroll loop uses.
_INJECT_JS = r"""
(rows) => {
  if (!window.__searchtsStore) {
    window.__searchtsStore = {key: new Map(), order: [], start: 0};
  }
  const s = window.__searchtsStore;
  if (typeof s.start !== 'number') s.start = 0;
  let added = 0;
  for (const row of rows || []) {
    if (!row || !row.key || !row.html) continue;
    if (s.key.has(row.key)) continue;
    s.key.set(row.key, row.html);
    s.order.push(row.key);
    added++;
  }
  return {added: added, total: s.order.length};
}
"""

#: Replay one captured data request from the page, so the site's own session
#: (credentials, CSRF, GraphQL operation headers) is what makes the call. This
#: is the only request a resume makes, and it is the site's own request shape
#: with the cursor moved, not a new one invented here.
_REPLAY_JS = r"""
async (req) => {
  const init = {method: req.m || 'GET', credentials: 'include', headers: {}};
  if (init.method !== 'GET' && init.method !== 'HEAD') {
    init.headers['content-type'] = 'application/json';
    if (req.b) init.body = req.b;
  }
  try {
    const r = await fetch(req.u, init);
    const text = await r.text();
    let json = null;
    try { json = JSON.parse(text); } catch (e) { json = null; }
    return {status: r.status, url: r.url, json: json};
  } catch (e) {
    return {status: 0, error: String(e)};
  }
}
"""

#: Which wall, if any, the page turned out to be. Cheap and in-page: it is
#: asked after every step, and ``walls.classify`` over the full HTML would cost
#: a ``page.content()`` per step to answer the same question. The Python side
#: re-checks with ``walls.classify`` before believing any of these names.
_WALL_JS = r"""
() => {
  const t = ((document.body && document.body.innerText) || '').toLowerCase();
  if (/verify you are human|checking your browser|just a moment\.\.\.|press and hold/
      .test(t) || document.querySelector('#challenge-form, .cf-browser-verification, iframe[src*="challenges.cloudflare.com"]')) {
    return 'challenge';
  }
  if (/you must log in|sign in to (continue|view|read|see)|create an account to|please log in/.test(t)) {
    return 'login';
  }
  if (/you (have been )?rate limited|too many requests|slow down/.test(t)) return 'rate-limit';
  return '';
}
"""


def _wall_from_html(html: str) -> str:
    """Which wall, from the same classifier the ladder uses. Empty when none."""
    try:
        from searchts.walls import classify, scrub

        hit = classify(scrub(html or ""))
    except Exception:  # noqa: BLE001 - no classifier, no wall claim
        return ""
    return hit.kind if hit else ""


def _wall(page) -> str:
    """The wall that replaced the feed, or "".

    The in-page check is the cheap one; the answer is only believed when the
    same classifier the ladder uses agrees. A feed with "sign in" in its own
    header is not a login wall, and the cheap check alone would call it one.
    """
    try:
        got = page.evaluate(_WALL_JS)
    except Exception:  # noqa: BLE001
        return ""
    if not got:
        return ""
    kind = str(got)
    if kind == "login":
        # The ladder's own name for this wall, so the two stop notes read the
        # same when one is printed by `read` and one by `scroll`.
        return "auth" if _wall_from_html(_content(page)) == "auth" else ""
    return kind if _wall_from_html(_content(page)) == kind else ""


def _settle(page, url: str, budget_seconds: int) -> None:
    """Wait for the same settling the ladder's own rung waits for.

    A feed that is still navigating has no rows to count, and the probe then
    answers "not a feed" about a page that simply had not hydrated yet. Measured
    on reddit.com/r/python: ``page.content()`` straight after
    ``domcontentloaded`` raises "the page is navigating and changing the
    content", so the very first probe failed and the read claimed there was
    nothing behind a scroll on a page that has an infinite feed.
    """
    from searchts import unlocker

    load_ms = max(1000, int(budget_seconds * 500))
    try:
        unlocker._wait_settled_load(page, timeout_ms=load_ms, progress=False)
    except Exception:  # noqa: BLE001 - settling is best effort, never a failure
        pass
    for getter in (lambda: page.content(), lambda: ""):
        try:
            html = getter()
        except Exception:  # noqa: BLE001 - mid-navigation; the loop retries
            html = ""
        if html:
            try:
                unlocker._await_hydration(page, html, progress=False)
            except Exception:  # noqa: BLE001
                pass
            return


def collect(
    page,
    *,
    want_rows: int,
    max_clicks: int = 8,
    budget_seconds: int = 60,
    step_ms: int = 1200,
    empty_steps: int = 2,
    tick: Optional[Callable[[str], None]] = None,
    resume: Optional[resume_mod.ResumeState] = None,
    capture: Optional[resume_mod.Capture] = None,
) -> ScrollReport:
    """Drive ``page`` down a feed and return every row it showed.

    ``page`` is a live Playwright page already at the URL. The loop is: probe
    once, then step, copying rows after each step. It ends for exactly one of
    five reasons, and :attr:`ScrollReport.stop` names which.

    ``resume`` is a verified token's state (#510). A resumed walk tries the
    site's captured cursor first, then skips to the seam where the old read
    stopped, and only reports "the feed changed" when neither works. The loop
    still never navigates; moving to a URL position is the caller's job.

    ``capture`` is the passive response listener. It is optional because a
    unit test drives a fake page, and a feed with no JSON data responses has
    nothing to capture either.

    The loop never navigates. Every URL on the page goes through the caller,
    which guards it (Q: SSRF on every hop), and the "Load more" press is on a
    ``<button>`` precisely because a button does not change where we are.
    """
    rep = ScrollReport()
    started = time.monotonic()
    deadline = started + max(1, int(budget_seconds))

    def say(msg: str) -> None:
        if tick is not None:
            try:
                tick(msg)
            except Exception:  # noqa: BLE001 - narration never breaks a walk
                pass

    def drain() -> None:
        if capture is not None:
            try:
                capture.drain()
            except Exception:  # noqa: BLE001 - a capture never fails a walk
                pass

    def probe() -> Optional[Dict[str, Any]]:
        # Two tries, because a page mid-navigation throws from `evaluate` and
        # answering "not a feed" on the first try is a claim about the site that
        # the site never got to make. One retry costs a second; being wrong
        # costs the caller the whole feed.
        for attempt in range(2):
            try:
                out = page.evaluate(_FIND_LIST_JS)
            except Exception:  # noqa: BLE001 - a page that will not answer is no feed
                out = None
            if isinstance(out, dict) and out.get("rows", 0) >= 3:
                return out
            if attempt == 0:
                try:
                    page.wait_for_timeout(1200)
                except Exception:  # noqa: BLE001
                    break
        return out if isinstance(out, dict) else None

    # ── probe ──
    first = probe()
    if first is None or first.get("rows", 0) < 3:
        rep.stop = "not-a-feed"
        rep.html = _content(page)
        if capture is not None:
            rep.rate_limited = bool(capture.rate_limited)
        return rep
    say(f"  scroll: probe found {first['rows']} list row(s)")
    drain()
    got = _collect_once(page)
    rep.start_rows = got.get("rows", 0)
    found = False
    halted = False
    stop = "the scroll budget ran out"  # pessimistic default; every exit sets it
    # A data response already said 429 before the first step. Stop here: the
    # rows copied above are the ones this read has, and another request would
    # only spend more of a limit the site just named.
    if capture is not None and capture.rate_limited:
        rep.rate_limited = True
        halted = True
        stop = "the site rate-limited the feed (429)"
    if resume is not None and not halted:
        # (a) replay the site's own data request when the token captured one.
        # It is the most exact continuation, but only if the request shape can
        # be replayed from this page at all. The old keys stay in the store so
        # a later step can keep scrolling without counting them again.
        outcome = _replay_cursor(page, resume)
        if outcome.rate_limited:
            rep.rate_limited = True
            halted = True
            stop = "the site rate-limited the feed (429)"
            # The page may already be showing rows past the seam. Drop the
            # ones the token has, and do not scroll any further.
            trimmed = _trim_to_new(page, resume.keys)
            if trimmed.get("found"):
                rep.resume_method = "fast-skip"
                found = True
                got = _collect_once(page)
        elif outcome.added:
            rep.resume_method = "cursor"
            found = True
            # The next token must carry the cursor the replay *returned*.
            # The one on this token was just spent; putting it back would
            # read the same batch again.
            rep.cursor = outcome.cursor
            rep.replay = outcome.replay
            got = {"rows": outcome.added, "total": outcome.added, "added": outcome.added}
            say(f"  scroll: resumed at the feed's own captured cursor "
                f"({outcome.added} row(s))")
        # (b) fast-skip: walk until the seam the token remembers, keeping only
        # what comes after it. A cursor replay that produced nothing falls
        # through to here.
        if not found and not halted:
            trimmed = _trim_to_new(page, resume.keys)
            if trimmed.get("found"):
                rep.resume_method = "fast-skip"
                found = True
                got = _collect_once(page)
                say(f"  scroll: resumed after the last row this token had "
                    f"({trimmed.get('dropped', 0)} already seen)")
    empty = 0
    clicks = 0

    while not halted:
        # While the seam is still missing, the store holds the top of the
        # feed, and calling that "rows read" would be a lie about the resume.
        if resume is None or found:
            if int(got.get("total") or 0) >= want_rows:
                stop = f"reached the {want_rows} rows asked for"
                break
        if time.monotonic() >= deadline:
            stop = f"the {budget_seconds}s scroll budget ran out"
            break
        if empty >= max(1, int(empty_steps)):
            stop = f"{empty_steps} scroll step(s) in a row added nothing"
            break
        say("  scroll: looking further down the page…")
        try:
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(max(200, int(step_ms)))
        except Exception:  # noqa: BLE001 - the page navigated mid-read
            stop = "the page navigated away mid-scroll"
            break
        rep.steps += 1
        drain()
        if capture is not None and capture.rate_limited:
            # #509 says a 429 stops the walk. The status came from a data
            # response already in hand, so the rows collected so far are real
            # and are kept rather than thrown away.
            rep.rate_limited = True
            stop = "the site rate-limited the feed (429)"
            break
        if rep.steps == 1:
            say(f"  scroll: step 1 -> {_page_rows(page)} live row(s)")
        wall = _wall(page)
        if wall:
            rep.wall = wall
            stop = f"a {wall} wall replaced the page"
            break
        step = _collect_once(page)
        if resume is not None and not found:
            trimmed = _trim_to_new(page, resume.keys)
            if trimmed.get("found"):
                rep.resume_method = "fast-skip"
                found = True
                empty = 0
                got = _collect_once(page)
                say(f"  scroll: found the seam after {trimmed.get('dropped', 0)} "
                    "row(s) this token already had")
                continue
        added = step.get("added", 0)
        if added:
            empty = 0
            say(f"  scroll: step {rep.steps} -> +{added} new row(s), "
                f"{step.get('total', 0)} collected")
            got = step
            continue
        empty += 1
        # A stalled step with a "Load more" button on the page is the same
        # intent by another mechanism, so press it once and try again.
        control = _load_more(page)
        if control and clicks < max(1, int(max_clicks)):
            if _press(page, control.get("label")):
                clicks += 1
                rep.clicks = clicks
                say(f'  scroll: step {rep.steps} stalled, pressed "Load more"')
                empty = 0
                continue
        got = step
        say(f"  scroll: step {rep.steps} -> +0 new row(s)")

    rep.stop = stop
    rep.elapsed_ms = int((time.monotonic() - started) * 1000)
    rep.resume_found = found
    # A 429 is not a feed that moved. Saying "changed" there would claim we
    # looked at the whole window and did not know it, which we did not.
    if (
        resume is not None
        and not found
        and not rep.resume_method
        and not rep.rate_limited
    ):
        rep.resume_method = "changed"
    if capture is not None:
        drain()
        rep.rate_limited = rep.rate_limited or bool(capture.rate_limited)
        if rep.rate_limited and rep.resume_method == "changed":
            rep.resume_method = ""
        spent = resume.cursor if resume is not None else ""
        if rep.resume_method == "cursor":
            # Prefer the cursor the replay body named. The listener's value is
            # often the one this read just sent, and replaying it repeats the
            # batch. Take the listener only when it saw a different cursor.
            if not rep.cursor and capture.cursor and capture.cursor != spent:
                rep.cursor = capture.cursor
                rep.replay = capture.replay or rep.replay
        elif not rep.cursor:
            rep.cursor = capture.cursor
            rep.replay = capture.replay
    _rebuild(page)
    store = _read_store(page)
    rep.rows = list(store.get("rows") or [])
    rep.keys = list(store.get("order") or [])
    rep.html = _content(page)
    return rep


def _trim_to_new(page, keys: Tuple[str, ...]) -> Dict[str, Any]:
    """Drop the store up to the last row ``keys`` already has."""
    if not keys:
        return {"found": False, "dropped": 0}
    try:
        out = page.evaluate(_TRIM_JS, list(keys))
    except Exception:  # noqa: BLE001 - a page that will not answer keeps its store
        return {"found": False, "dropped": 0}
    return out if isinstance(out, dict) else {"found": False, "dropped": 0}


@dataclass
class _ReplayOutcome:
    """What one in-page replay of the feed's own cursor produced."""

    added: int = 0
    rate_limited: bool = False
    #: The cursor the response named, when it is not the one just sent.
    cursor: str = ""
    replay: Optional[Dict[str, str]] = None


def _replay_cursor(page, state: resume_mod.ResumeState) -> _ReplayOutcome:
    """Replay the feed's captured cursor once and inject what it returns.

    ``added == 0`` and not rate-limited means "not replayable here", and the
    walk falls through to fast-skip. The request is the site's own, with its
    cursor moved; nothing is invented here and the host has to be the one the
    token was issued for. A 429 is returned as a stop, not as a miss: falling
    through would scroll a feed the site just refused.
    """
    request = resume_mod.replay_request(state)
    if not request:
        return _ReplayOutcome()
    try:
        here = str(getattr(page, "url", "") or "")
    except Exception:  # noqa: BLE001
        here = ""
    if here and not resume_mod.same_site(request["u"], here):
        return _ReplayOutcome()
    try:
        out = page.evaluate(_REPLAY_JS, request)
    except Exception:  # noqa: BLE001 - a replay the page refuses is not a failure
        return _ReplayOutcome()
    if not isinstance(out, dict):
        return _ReplayOutcome()
    if out.get("status") == 429:
        return _ReplayOutcome(rate_limited=True)
    rows = _json_rows(out.get("json"), base=str(out.get("url") or request["u"]))
    if not rows:
        return _ReplayOutcome()
    try:
        page.evaluate(_HIDE_SEEN_JS)
        injected = page.evaluate(_INJECT_JS, rows)
    except Exception:  # noqa: BLE001
        return _ReplayOutcome()
    if not isinstance(injected, dict):
        return _ReplayOutcome()
    added = int(injected.get("added") or 0)
    if not added:
        return _ReplayOutcome()
    # The response's cursor is the next window. The field name stays the one
    # the request used: the response often names the cursor differently
    # (``endCursor`` in the body, ``after`` in the request), and the next
    # replay has to move the request's field, not the response's.
    found = resume_mod.find_cursor(out.get("json"))
    cursor = ""
    replay = None
    if found and found[0] and found[0] != state.cursor and state.replay:
        cursor = found[0]
        replay = {
            "u": str(state.replay.get("u") or ""),
            "m": str(state.replay.get("m") or "GET"),
            "b": str(state.replay.get("b") or ""),
            "f": str(state.replay.get("f") or ""),
        }
    return _ReplayOutcome(added=added, cursor=cursor, replay=replay)


#: Keys a JSON row object may use for its address and its words. Deliberately
#: small: a replay is a recovery path, not a second extractor. When the JSON
#: does not look like a list of linked rows, nothing is invented.
_ROW_URL_KEYS = ("url", "href", "permalink", "link", "uri", "web_url", "canonical_url")
_ROW_TEXT_KEYS = ("title", "headline", "name", "text", "caption", "label")


def _json_rows(data: Any, base: str = "") -> List[Dict[str, str]]:
    """Row-shaped objects in a replayed JSON body, as store records.

    Each record is ``{key, html}`` using the same ``L<url>`` key the scroll
    store uses, so a row that later appears in the DOM is the same row. The
    walk is bounded; a body with no linked objects yields nothing.
    """
    rows: List[Dict[str, str]] = []
    seen: set = set()

    def walk(node: Any, depth: int) -> None:
        if depth > 6 or len(rows) >= 100:
            return
        if isinstance(node, dict):
            url = ""
            for key in _ROW_URL_KEYS:
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    url = value.strip()
                    break
            title = ""
            for key in _ROW_TEXT_KEYS:
                value = node.get(key)
                if isinstance(value, str) and len(value.strip()) >= 3:
                    title = value.strip()
                    break
            if url and title:
                absolute = urljoin(base, url)
                key = "L" + absolute
                if key not in seen:
                    seen.add(key)
                    rows.append({
                        "key": key,
                        "html": (
                            '<div class="searchts-resumed-row">'
                            f'<a href="{escape(absolute, quote=True)}">'
                            f"{escape(title)}</a></div>"
                        ),
                    })
            for value in node.values():
                walk(value, depth + 1)
        elif isinstance(node, list):
            for item in node[:100]:
                walk(item, depth + 1)

    walk(data, 0)
    return rows


def _page_rows(page) -> int:
    got = _collect_once(page)
    return int(got.get("rows") or 0)


def _collect_once(page) -> Dict[str, Any]:
    try:
        out = page.evaluate(_COLLECT_JS)
    except Exception:  # noqa: BLE001 - a page that will not answer has no rows
        return {"rows": 0, "total": 0, "added": 0, "order": [], "found": False}
    if not isinstance(out, dict):
        return {"rows": 0, "total": 0, "added": 0, "order": [], "found": False}
    out.setdefault("order", [])
    return out


def _read_store(page) -> Dict[str, Any]:
    try:
        out = page.evaluate(_READ_STORE_JS)
    except Exception:  # noqa: BLE001
        return {"order": [], "rows": []}
    return out if isinstance(out, dict) else {"order": [], "rows": []}


def _rebuild(page) -> int:
    try:
        return int(page.evaluate(_REBUILD_JS) or 0)
    except Exception:  # noqa: BLE001 - a page that will not answer keeps its own DOM
        return 0


def _load_more(page) -> Optional[Dict[str, str]]:
    try:
        out = page.evaluate(_LOAD_MORE_JS)
    except Exception:  # noqa: BLE001
        return None
    return out if isinstance(out, dict) else None


def _press(page, label: Optional[str]) -> bool:
    """Press the named "Load more" button once. False when it could not be."""
    try:
        handles = page.query_selector_all("button, [role=button]")
    except Exception:  # noqa: BLE001
        return False
    for h in handles:
        try:
            if (h.inner_text() or "").strip() != label:
                continue
            h.click(timeout=3000)
            return True
        except Exception:  # noqa: BLE001 - an unclickable control is a skip
            return False
    return False


def _content(page) -> str:
    try:
        return page.content()
    except Exception:  # noqa: BLE001 - page may navigate mid-read
        return ""


def _page_url(page) -> str:
    try:
        return str(getattr(page, "url", "") or "")
    except Exception:  # noqa: BLE001
        return ""


def browser_available() -> bool:
    """True when the stealth rung's driver is importable."""
    try:
        import patchright  # noqa: F401

        return True
    except Exception:  # noqa: BLE001 - a missing extra is the normal case
        return False


def collect_url(
    url: str,
    *,
    want_rows: int,
    max_clicks: int = 8,
    budget_seconds: int = 60,
    step_ms: int = 1200,
    empty_steps: int = 2,
    persistent: bool = False,
    tick: Optional[Callable[[str], None]] = None,
    resume: Optional[resume_mod.ResumeState] = None,
) -> Tuple[Optional[ScrollReport], str]:
    """Open ``url`` in the stealth Chromium and collect its rows.

    Returns ``(report, "")`` on success and ``(None, reason)`` when the page
    could not be opened at all. The caller decides what to do with a reason:
    ``read_items`` folds it into its own stop note, because a scroll that
    cannot start is not a read that failed.

    ``resume`` is the verified token state from #510. The walk tries the
    captured cursor and the seam first; when neither produces a new row and
    the URL has a next position, it opens that page instead. That is the one
    navigation this function makes on someone else's behalf, and the URL comes
    from the signed token, not from the page it is reading.
    """
    if not browser_available():
        return None, "no-browser"
    try:
        from patchright.sync_api import sync_playwright

        from searchts.ssrf import chromium_pin_args, guard_browser_page
        from searchts.unlocker import _UA_REAL, _profile_path, _use_persistent_profile
    except Exception:  # noqa: BLE001
        return None, "no-browser"
    try:
        with sync_playwright() as p:
            # One name for the thing that has to be closed, typed loosely on
            # purpose: the persistent path hands back a BrowserContext and the
            # launch path a Browser, and the ladder's own rung makes the same
            # two-way choice. Both expose ``close()``, which is all this needs.
            browser: Any = None
            if persistent and _use_persistent_profile():
                browser = p.chromium.launch_persistent_context(
                    str(_profile_path()), headless=True,
                    args=chromium_pin_args(url), user_agent=_UA_REAL, locale="en-US",
                    viewport={"width": 1280, "height": 800},
                )
                page = browser.new_page()
            else:
                browser = p.chromium.launch(headless=True, args=chromium_pin_args(url))
                ctx = browser.new_context(
                    user_agent=_UA_REAL, locale="en-US",
                    viewport={"width": 1280, "height": 800},
                )
                page = ctx.new_page()
            try:
                guard_browser_page(page, url)
                started = time.monotonic()
                deadline = started + max(1, int(budget_seconds))

                def say(msg: str) -> None:
                    if tick is None:
                        return
                    try:
                        tick(msg)
                    except Exception:  # noqa: BLE001 - narration never breaks a walk
                        pass

                # The listener is attached before the first request so the
                # feed's own first data response is captured too. It adds no
                # request of its own.
                capture: Optional[resume_mod.Capture] = resume_mod.Capture(url)
                try:
                    page.on("response", capture)
                except Exception:  # noqa: BLE001 - a page with no events still reads
                    capture = None

                say("scrolling: opening the page…")
                page.goto(url, wait_until="domcontentloaded",
                          timeout=int(budget_seconds * 1000))
                say("scrolling: waiting for the page…")
                _settle(page, url, budget_seconds)
                rep = collect(
                    page, want_rows=want_rows, max_clicks=max_clicks,
                    budget_seconds=max(1, int(deadline - time.monotonic())),
                    step_ms=step_ms, empty_steps=empty_steps, tick=tick,
                    resume=resume, capture=capture,
                )
                # (c) Cursor replay and fast-skip produced nothing new. When the
                # token knows the next position, open it: one exact page beats
                # scrolling a list that will never grow (a static front page
                # with ?p= paging). A 429 already stopped the walk; opening
                # another page would spend a limit the site just named.
                if (
                    resume is not None
                    and resume.position
                    and not rep.rate_limited
                    and (not rep.resume_found or not rep.rows)
                ):
                    nxt = resume_mod.url_at_position(url, resume.position)
                    if nxt and nxt != url:
                        try:
                            say("scrolling: opening the next page the token names…")
                            page.goto(nxt, wait_until="domcontentloaded",
                                      timeout=int(budget_seconds * 1000))
                            _settle(page, nxt, budget_seconds)
                            nxt_rep = collect(
                                page, want_rows=want_rows, max_clicks=max_clicks,
                                budget_seconds=max(1, int(deadline - time.monotonic())),
                                step_ms=step_ms, empty_steps=empty_steps,
                                tick=tick, capture=capture,
                            )
                            nxt_rep.resume_method = "url-position"
                            nxt_rep.resume_found = True
                            rep = nxt_rep
                        except Exception:  # noqa: BLE001 - keep what we had
                            pass
                rep.page_url = _page_url(page) or url
                if capture is not None:
                    try:
                        capture.drain()
                    except Exception:  # noqa: BLE001
                        pass
                    spent = resume.cursor if resume is not None else ""
                    if rep.resume_method == "cursor":
                        if (
                            not rep.cursor
                            and capture.cursor
                            and capture.cursor != spent
                        ):
                            rep.cursor = capture.cursor
                            rep.replay = rep.replay or capture.replay
                    else:
                        rep.cursor = rep.cursor or capture.cursor
                        rep.replay = rep.replay or capture.replay
                    rep.rate_limited = rep.rate_limited or capture.rate_limited
                    if rep.rate_limited and rep.resume_method == "changed":
                        rep.resume_method = ""
                rep.elapsed_ms = int((time.monotonic() - started) * 1000)
                return rep, ""
            finally:
                browser.close()
    except Exception as e:  # noqa: BLE001 - any browser failure is one reason
        return None, f"browser: {type(e).__name__}"
