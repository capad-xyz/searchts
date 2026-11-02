# -*- coding: utf-8 -*-
"""#509: an http-429 is the host saying slow down, so the read stops and the host rests.

Before this, only LinkedIn stopped the ladder on a 429. Every other host got the
whole escalation anyway: curl_cffi, then a browser launch, then a relay request,
all to a server that had just asked for fewer requests. A next-page walk did it
again on every hop. That is three or four requests where one was refused, and
the next read arrives while the budget is still spent.

The rule here is one sentence: **a direct rung's 429 ends the read for that
host**. ``Jina Reader``'s own 429 is the relay's quota, not the site's answer,
and keeps the old handling. Nothing in this module makes a request.

Two pieces of local state, both small and value-free:

* ``host -> until`` in ``<state-dir>/rate_limits.json``. A host name and a unix
  time. No URL, no path, no cookie, no status text.
* the default wait when the site sent no ``Retry-After``: seconds from
  ``SEARCHTS_429_COOLDOWN`` (knobs.py), 5 minutes built in, 30 minutes at most.

``Retry-After`` is honoured in both forms the field allows: delta-seconds and
an HTTP date. A date in the past means "now", not a negative wait.

Opting out is explicit: ``--ignore-cooldown`` (MCP ``ignore_cooldown``) reads
the host anyway. Opting in to waiting is also explicit: ``--wait-on-429`` (MCP
``wait_on_429``) waits and retries the same rung, capped at
:data:`WAIT_CAP_SECONDS`. Neither is ever on by default, because both spend
something the caller owns: a request, or time.
"""

from __future__ import annotations

import json
import os
import time
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

__all__ = [
    "DEFAULT_SECONDS",
    "MAX_SECONDS",
    "WAIT_CAP_SECONDS",
    "human_seconds",
    "parse_retry_after",
    "record",
    "remaining",
    "forget",
    "clear",
    "refusal_hint",
    "stop_hint",
    "record_for_url",
    "state_dir",
    "state_path",
]

#: Cooldown when the host sent no ``Retry-After``. ``knobs.py`` reads
#: ``SEARCHTS_429_COOLDOWN`` for the user's own default; this is the built-in.
DEFAULT_SECONDS = 5 * 60

#: No single cooldown is longer than this, whatever the host asked for. A
#: ``Retry-After`` of an hour would otherwise take a site out for an hour on a
#: header one bad response can send.
MAX_SECONDS = 30 * 60

#: The whole ``--wait-on-429`` retry may spend at most this long waiting. Past
#: it the read stops and records the cooldown instead of holding a terminal.
WAIT_CAP_SECONDS = 180

#: What the file is called inside the state dir. The same dir the unlocker's
#: backend memory uses, so one folder is all searchts owns.
_FILE = "rate_limits.json"


def state_dir() -> Path:
    """The folder searchts keeps local state in, honouring ``SEARCHTS_CACHE_DIR``.

    The same override the backend memory honours (see ``unlocker._cache_path``),
    so a test or a sandbox points every small file at one temp dir and never
    touches the user's ``~/.searchts``.
    """
    override = os.environ.get("SEARCHTS_CACHE_DIR")
    if override:
        return Path(override)
    return Path.home() / ".searchts"


def state_path() -> Path:
    """Where the cooldown file lives. See :func:`state_dir`."""
    return state_dir() / _FILE


def human_seconds(seconds: float) -> str:
    """``4m 12s``: a time left a person can act on, never a raw float."""
    total = int(round(max(0.0, float(seconds))))
    if total < 60:
        return f"{total}s"
    minutes, rest = divmod(total, 60)
    if rest == 0:
        return f"{minutes}m"
    return f"{minutes}m {rest}s"


def parse_retry_after(value: Optional[str], now: Optional[float] = None) -> Optional[float]:
    """Seconds named by a ``Retry-After`` value, or None when it is not one.

    Both forms RFC 9110 allows: ``120`` (delta-seconds) and an HTTP date
    (``Wed, 21 Oct 2015 07:28:00 GMT``). A date already in the past is 0, not a
    negative wait. Anything unparsable is None, which lets the caller fall back
    to the default instead of inventing a number.
    """
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    base = time.time() if now is None else float(now)
    return max(0.0, when.timestamp() - base)


def _default_seconds() -> int:
    """The user's cooldown default, or 0 when the cooldown is turned off.

    ``SEARCHTS_429_COOLDOWN=0`` is the switch that says "record nothing": a
    machine that would rather retry immediately than keep local state. The
    clock is still whatever the host sends in ``Retry-After``... except that a
    host under a disabled cooldown is also not refused before the request,
    because there is nothing to refuse against.
    """
    try:
        from searchts import knobs

        return int(knobs.resolve().cooldown)
    except Exception:  # noqa: BLE001 - a broken config must not break a read
        return DEFAULT_SECONDS


def _load(now: Optional[float] = None) -> Dict[str, float]:
    """Live ``host -> until`` entries; expired ones are dropped from disk too.

    Best-effort like the backend memory: a missing, corrupt or unwritable file
    is "no cooldowns", never a failed read. Pruning happens on load so a file
    left alone for a day does not grow a grave of hosts nobody asked about.
    """
    base = time.time() if now is None else float(now)
    path = state_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:  # noqa: BLE001 - missing/corrupt state is non-fatal
        return {}
    if not isinstance(data, dict):
        return {}
    live: Dict[str, float] = {}
    for host, until in data.items():
        try:
            value = float(until)
        except (TypeError, ValueError):
            continue
        if not isinstance(host, str) or not host:
            continue
        if value > base:
            live[host] = value
    if len(live) != len(data):
        _save(live)
    return live


def _save(entries: Dict[str, float]) -> None:
    """Write the map atomically enough for a local state file. Never raises."""
    path = state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(entries, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001 - an unwritable state dir is not a read error
        return


def record(
    host: str, retry_after: Optional[str] = None, now: Optional[float] = None
) -> Optional[float]:
    """Remember that ``host`` said 429, and return the unix time it may be tried.

    ``Retry-After`` wins when present and readable; otherwise the user's
    default applies. Both are capped at :data:`MAX_SECONDS`. Returns None when
    the host is empty or ``SEARCHTS_429_COOLDOWN=0`` turned the feature off.
    """
    if not host:
        return None
    base = time.time() if now is None else float(now)
    default = _default_seconds()
    if default <= 0:
        return None
    asked = parse_retry_after(retry_after, now=base)
    seconds = asked if asked is not None else float(default)
    until = base + min(max(seconds, 1.0), float(MAX_SECONDS))
    entries = _load(now=base)
    entries[host] = until
    _save(entries)
    return until


def remaining(host: str, now: Optional[float] = None) -> float:
    """Seconds this host is still cooling down, or 0 when it is not.

    ``SEARCHTS_429_COOLDOWN=0`` means "no cooldown", so it also means "do not
    refuse a read against an entry an older setting already wrote": the switch
    has to work on a machine that has a file, not only on a fresh one.
    """
    if not host or _default_seconds() <= 0:
        return 0.0
    base = time.time() if now is None else float(now)
    until = _load(now=base).get(host)
    if until is None:
        return 0.0
    return max(0.0, until - base)


def check(host: str, now: Optional[float] = None) -> Tuple[float, Optional[float]]:
    """``(seconds left, unix until)`` for ``host``; ``(0, None)`` when it may read."""
    rest = remaining(host, now=now)
    if rest <= 0:
        return 0.0, None
    base = time.time() if now is None else float(now)
    return rest, base + rest


def clear() -> int:
    """Delete every cooldown. Returns 1 when a file was there, else 0.

    ``--ignore-cooldown`` is the per-read override; this is the blunt reset for
    every host at once. ``searchts login resume <site>`` uses
    :func:`forget` for one host instead.
    """
    try:
        state_path().unlink()
        return 1
    except FileNotFoundError:
        return 0
    except OSError:
        return 0


def record_for_url(url: str, retry_after: Optional[str] = None) -> Optional[float]:
    """Record a direct 429 for ``url``'s host, and a LinkedIn stop when it is one.

    Scroll and expand see the 429 on a response that is not the ladder's own
    rung return. They call this so the next read is refused the same way a
    rung's 429 is. No request is made here.
    """
    from searchts.unlocker import registrable_domain

    host = registrable_domain(url or "")
    until = record(host, retry_after)
    try:
        from searchts import linkedin

        if linkedin.matches(url or ""):
            linkedin.record_stop("rate-limit")
    except Exception:  # noqa: BLE001 - the cooldown above is the part that must land
        pass
    return until


def forget(host: str) -> bool:
    """Drop one host's cooldown. True when an entry was there to drop.

    The reset behind ``searchts login resume <site>``: clearing every host
    because one was retried would undo a cooldown the user did not ask about.
    """
    if not host:
        return False
    base = time.time()
    entries = _load(now=base)
    if host not in entries:
        return False
    del entries[host]
    _save(entries)
    return True


def refusal_hint(host: str, rest: float) -> str:
    """Why a read was refused before it was sent, and the two ways past it."""
    where = host or "this host"
    return (
        f"{where} is cooling down for another {human_seconds(rest)}: it answered "
        "http-429 (too many requests) on an earlier read, so no request was sent "
        "this time. Wait, or pass --ignore-cooldown (MCP ignore_cooldown=true) "
        "to read anyway. SEARCHTS_429_COOLDOWN is the default wait when a host "
        "sends no Retry-After."
    )


def stop_hint(host: str, rest: float, *, signed_in: bool = False) -> str:
    """Why the read stopped on a 429, where the cooldown came from, and the way past it."""
    where = host or "this host"
    cooling = (
        f"reads of {where} are refused for another {human_seconds(rest)}"
        if rest > 0
        else f"reads of {where} are refused until its cooldown expires"
    )
    hint = (
        f"{where} answered http-429 (too many requests), so the ladder stopped "
        "instead of sending another rung's request to the same host, and "
        f"{cooling}. Wait, or pass --ignore-cooldown (MCP ignore_cooldown=true) "
        "to try anyway; --wait-on-429 (MCP wait_on_429=true) waits per "
        "Retry-After, or backs off, and retries that rung."
    )
    if signed_in:
        hint += (
            " This read carried a login, so --wait-on-429 gets one wait and no "
            "more: every retry spends the user's own account."
        )
    return hint
