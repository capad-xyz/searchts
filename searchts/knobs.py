# -*- coding: utf-8 -*-
"""F23e: the knobs. Intent in, a ceiling out, and the clamp said out loud.

The agent gets three ways to ask for more of a page, and they are named the
same everywhere:

| intent        | CLI             | MCP             | env              | ``~/.searchts/config.yaml``
|---------------|-----------------|-----------------|------------------|-------------------
| more pages    | ``--pages N``   | ``max_pages``   | ``SEARCHTS_MAX_PAGES``  | ``more.pages``
| more rows     | ``--items N``   | ``max_items``   | ``SEARCHTS_MAX_ITEMS``  | ``more.items``
| open the folds| ``--expand``    | ``expand``      | ``SEARCHTS_MAX_EXPAND_CLICKS`` | ``more.expand_clicks``

Two of these have a second, lower ceiling for a read that carries a kept login:
``items`` defaults to ``SEARCHTS_MAX_ITEMS_SIGNED_IN`` (50), because a list walk
on a signed-in host spends the user's account, not an anonymous address.

The 429 cooldown is not a read ceiling and is not in the table above: it is the
default wait recorded after a host says http-429, ``SEARCHTS_429_COOLDOWN``
(300 s, 1800 at most; 0 turns the cooldown off). It lives here because it is the
same kind of policy: the user sets it, a read cannot.

LinkedIn page-load pacing is not a knob here. The numbers live in
``searchts.linkedin``: ``SEARCHTS_LINKEDIN_LOADS_PER_MINUTE`` (2),
``SEARCHTS_LINKEDIN_LOADS_PER_HOUR`` (20), ``SEARCHTS_LINKEDIN_LOADS_PER_DAY``
(100, and 0 turns that cap off) and ``SEARCHTS_LINKEDIN_FEED_GAP_MINUTES``
(30; defined for a later change, not enforced by a read).

plus the ceilings the loop itself runs under (``seconds``, ``step_ms``,
``empty_steps``), which are the same three layers and are never a flag: they
are how the machine is allowed to spend time, not what the caller asked for.
Every scroll path (CLI ``--items``, MCP ``max_items``, the library's
``read_items``) resolves both through :func:`resolve`, so a user's ceiling
applies to a resumed read exactly as it does to a first one:

| loop ceiling    | env                       | ``~/.searchts/config.yaml``
|-----------------|---------------------------|--------------------------
| scroll budget   | ``SEARCHTS_MORE_SECONDS`` | ``more.seconds``
| scroll step gap | ``SEARCHTS_MORE_STEP_MS`` | ``more.step_ms``
| empty steps     | ``SEARCHTS_MORE_EMPTY_STEPS`` | ``more.empty_steps``

## The rule: the agent asks, the user caps

A caller may ask for anything up to the ceiling and may never raise the
ceiling. Nothing here is a *limit on the read*: every knob is a **maximum**.
Lowering one is how a user says "stop asking me for 300 rows"; it never makes
a read worse. That is why there is no per-call "how many" separate from the
flag: the flag is intent, the ceiling is the policy, and they meet here.

Resolution is flag, then env, then YAML, then the built-in default - the same
precedence every other config value uses (Q5: env beats YAML). A request that
came in over the ceiling is **clamped and named**, not silently reduced,
because a read that quietly returned 40 rows when 100 were asked for is a lie
about the page. The note is what ``note()`` builds and both surfaces print.

One rule the file will not bend: knobs describe intent, never mechanics. There
is no knob for scroll distance, item-list detection, or wait strategy. Those
are internal and stay internal.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

__all__ = ["Limits", "resolve", "hard_cap", "PAYWALL_NOTE", "INTENT_NAMES"]


#: The three things a caller can ask for. Each maps to one flag, one MCP
#: parameter and one env name, and the names are deliberately identical.
INTENT_NAMES = ("pages", "items", "expand")

#: ``name -> (env var, YAML key, default, hard cap, what one unit is)``.
#:
#: The hard cap is the product's own limit and is NOT a user policy: no policy
#: may raise it. Everything below it is the user's to set.
_SPEC: Dict[str, Tuple[str, str, int, int, str]] = {
    "pages": ("SEARCHTS_MAX_PAGES", "pages", 5, 5, "page"),
    "items": ("SEARCHTS_MAX_ITEMS", "items", 300, 300, "row"),
    "items_signed_in": (
        "SEARCHTS_MAX_ITEMS_SIGNED_IN", "items_signed_in", 50, 300, "row",
    ),
    "expand_clicks": ("SEARCHTS_MAX_EXPAND_CLICKS", "expand_clicks", 8, 40, "click"),
    "seconds": ("SEARCHTS_MORE_SECONDS", "seconds", 60, 300, "second"),
    "step_ms": ("SEARCHTS_MORE_STEP_MS", "step_ms", 1200, 8000, "ms"),
    "empty_steps": ("SEARCHTS_MORE_EMPTY_STEPS", "empty_steps", 2, 10, "step"),
    # #509: the default wait after a host says http-429, when it sent no
    # Retry-After. 0 is the off switch (no cooldown file is written).
    "cooldown": ("SEARCHTS_429_COOLDOWN", "cooldown", 300, 1800, "second"),
}

#: ``step_ms`` is milliseconds and ``seconds`` is seconds. The note reads in the
#: same units the env var does so a user can match it to what they set.
_UNITS = {name: unit for name, (_e, _y, _d, _h, unit) in _SPEC.items()}


@dataclass(frozen=True)
class Limits:
    """One resolved set of ceilings, plus what had to be clamped to reach it."""

    pages: int
    items: int
    expand_clicks: int
    seconds: int
    step_ms: int
    empty_steps: int
    #: The default wait after an http-429, for ``searchts.rate_limit``.
    cooldown: int = 300
    #: ``(knob, asked, ceiling)`` for every request that came in over the line.
    clamped: Tuple[Tuple[str, int, int], ...] = ()

    def note(self) -> str:
        """The line a clamped request ends with, or ``""`` when nothing moved."""
        return _note(self.clamped)

    def as_dict(self) -> Dict[str, int]:
        return {
            "pages": self.pages,
            "items": self.items,
            "expand_clicks": self.expand_clicks,
            "seconds": self.seconds,
            "step_ms": self.step_ms,
            "empty_steps": self.empty_steps,
        }


def _note(names) -> str:
    """The clamp line, one sentence per knob.

    The wording is the sentence ``--items`` has always printed ("asked for N,
    the ceiling is C"), because it is the one a user has already learned. What
    changed is *where* it lands: on page one, which is the text every caller
    reads, instead of on the last page of a walk that most callers never look
    at. See :func:`unlocker._note_knobs`.
    """
    if not names:
        return ""
    parts = []
    for name, asked, ceiling in names:
        parts.append(f"[{_LABEL[name]}: asked for {asked}, the ceiling is {ceiling}]")
    return "\n".join(parts)


#: What each knob is called in a sentence about itself. Same names as the flag,
#: the MCP parameter and the env var, minus the prefix.
_LABEL = {
    "pages": "pages",
    "items": "items",
    "items_signed_in": "signed-in items",
    "expand_clicks": "expand clicks",
    "seconds": "scroll seconds",
    "step_ms": "scroll step ms",
    "empty_steps": "empty steps",
    "cooldown": "429 cooldown",
}


def _yaml_block() -> Dict[str, Any]:
    """The user's ``more:`` block out of ``~/.searchts/config.yaml``.

    Env still beats YAML: :meth:`Config.get` checks the uppercased key first,
    but the env name here is ``SEARCHTS_MAX_ITEMS`` and the YAML key is
    ``items``, so they are read separately rather than through ``Config.get``.
    A missing or broken config is not an error - the defaults are the answer.
    """
    try:
        from searchts.config import Config

        block = Config().get("more")
    except Exception:  # noqa: BLE001 - a bad config must never break a read
        return {}
    if not isinstance(block, dict):
        return {}
    return block


def _read(name: str, yaml_block: Dict[str, Any]) -> Optional[int]:
    """The ceiling the *user* set for ``name``, or None to use the default."""
    env, yaml_key, _default, hard_cap, _unit = _SPEC[name]
    raw = os.environ.get(env)
    if raw is None or str(raw).strip() == "":
        raw = yaml_block.get(yaml_key)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        value = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return None
    if value < 1:
        # 0 is a real answer for the 429 cooldown: it turns the feature off.
        # Every other knob keeps its floor of 1, because a read asking for zero
        # rows or zero pages is not a request.
        return 0 if name == "cooldown" else 1
    return min(value, hard_cap)


def hard_cap(name: str) -> int:
    """The product ceiling for ``name``. A user policy can only lower it."""
    return _SPEC[name][3]


def _signed_in_ceiling() -> int:
    """The lower items ceiling for a read that carries a kept login."""
    ceiling = _read("items_signed_in", _yaml_block())
    if ceiling is None:
        ceiling = _SPEC["items_signed_in"][2]
    return ceiling


def resolve(*, signed_in: bool = False, **asked: Optional[int]) -> Limits:
    """Resolve every ceiling and apply what the caller asked for.

    ``asked`` holds the caller's *intent* (``pages=3``, ``items=250``,
    ``expand_clicks=40``). Anything above the ceiling is clamped and the
    ceiling's name is recorded, so the caller can be told. A ``None`` or an
    absent name means "not asked for", which is not the same as zero.

    ``signed_in`` applies the lower items ceiling (#509): a list walk that
    carries a kept login spends the user's account on a host that can rate-limit
    it, so it gets the same clamp machinery with its own name and its own env
    var (``SEARCHTS_MAX_ITEMS_SIGNED_IN``).
    """
    yaml_block = _yaml_block()
    values: Dict[str, int] = {}
    clamped: List[Tuple[str, int, int]] = []
    for name, (_env, _key, default, hard_cap, _unit) in _SPEC.items():
        ceiling = _read(name, yaml_block)
        if ceiling is None:
            ceiling = default
        want = asked.get(name)
        if want is None:
            values[name] = ceiling
            continue
        try:
            want_i = max(1, int(want))
        except (TypeError, ValueError):
            values[name] = ceiling
            continue
        if want_i > ceiling:
            clamped.append((name, want_i, ceiling))
        values[name] = min(want_i, ceiling)
    if signed_in:
        signed = _signed_in_ceiling()
        ordinary = values["items"]
        if signed < ordinary:
            asked_items = asked.get("items")
            try:
                shown = (
                    max(1, int(asked_items)) if asked_items is not None else ordinary
                )
            except (TypeError, ValueError):
                shown = ordinary
            values["items"] = signed
            if shown > signed:
                # The signed-in ceiling is the one that applied, so it is the
                # one the note must name; the ordinary items row, if any, was
                # replaced by this lower ceiling.
                clamped = [c for c in clamped if c[0] != "items"]
                clamped.append(("items_signed_in", shown, signed))
    return Limits(
        pages=values["pages"],
        items=values["items"],
        expand_clicks=values["expand_clicks"],
        seconds=values["seconds"],
        step_ms=values["step_ms"],
        empty_steps=values["empty_steps"],
        cooldown=values["cooldown"],
        clamped=tuple(clamped),
    )


#: What a paywall stop says. One string, so the CLI and the MCP envelope cannot
#: drift apart on the sentence a reader will quote back to the user.
PAYWALL_NOTE = (
    '[paywall: the rest of this article is behind a paywall ("continue reading"). '
    "searchts names it and does not work around it]"
)
