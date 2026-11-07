# -*- coding: utf-8 -*-
"""LinkedIn: read the content, not the page's own furniture.

A signed-in LinkedIn page is mostly chrome. A profile's top card comes with a
notification count, a Premium upsell, owner-only buttons ("Enhance profile",
"Add section", "Open to"), an ad-options panel, the full language picker and a
footer; a company page repeats the ad panel and adds its own Premium upsell.
That is what a reader got back, and the actual profile was three lines at the
top (#443).

This module is the site's own file, in the same shape as :mod:`searchts.players`
and :mod:`searchts.walls`: no plugin registry, no router in the ladder. It
holds four small facts about one host:

* which URLs are LinkedIn (:func:`matches`), and which are a person's profile
  (:func:`is_profile`);
* the extra pages a profile keeps its sections on (:func:`detail_urls`);
* the product chrome lines that are safe to drop (:func:`strip_chrome`);
* how to join a profile's top card and its sections (:func:`assemble`).

``strip_chrome`` is deliberately line-based and exact-match. The only phrases
it removes are LinkedIn's own fixed UI strings, plus blocks whose *shape* is
known (the ad panel from "Ad Options" to "Submit", the language picker, the
profile-language panel). A post that happens to contain prose is never matched
by a block, because a block stops at the first line it does not recognise and
leaves that line and everything after it untouched.
"""

from __future__ import annotations

import json
import os
import random
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Callable, Dict, List, Literal, Optional, Sequence, Tuple
from urllib.parse import urlparse

try:
    import fcntl
except ImportError:  # pragma: no cover - this tree's CI is Linux, which has flock
    fcntl = None  # type: ignore[assignment]

__all__ = [
    "matches",
    "is_profile",
    "is_feed",
    "browser_first",
    "detail_urls",
    "strip_chrome",
    "has_section_content",
    "assemble",
    "rate_limit_hint",
    "Stop",
    "Paced",
    "MIN_GAP_SECONDS",
    "MAX_JITTER_SECONDS",
    "STOP_SECONDS",
    "LOADS_PER_MINUTE",
    "LOADS_PER_HOUR",
    "LOADS_PER_DAY",
    "FEED_GAP_MINUTES",
    "current_stop",
    "record_stop",
    "clear_stop",
    "stop_signal",
    "stop_hint",
    "load_limits",
    "feed_gap_minutes",
    "take_load",
    "exclusive_load",
]

_LINKEDIN = "linkedin.com"

#: #509 point 6. A 429, a 999, a "too many pages" page, a checkpoint or a forced
#: logout pauses LinkedIn for this long before searchts asks it anything else.
STOP_SECONDS = 24 * 60 * 60

#: Every direct LinkedIn page load is one at a time, at least this far apart,
#: plus 0 to :data:`MAX_JITTER_SECONDS` at random. Measured 2026-11-02: seven
#: reads in three minutes earned an http-429, and the sections a profile read
#: adds were the second and third request in that burst.
MIN_GAP_SECONDS = 20.0
MAX_JITTER_SECONDS = 15.0

#: The load budget in every window. ``SEARCHTS_LINKEDIN_LOADS_PER_MINUTE``,
#: ``_PER_HOUR`` and ``_PER_DAY`` override each; 0 turns that window off (the
#: issue names the daily one). The gap still applies when a window is off.
LOADS_PER_MINUTE = 2
LOADS_PER_HOUR = 20
LOADS_PER_DAY = 100

#: How long the home feed is left alone between document loads. The feed
#: reader enforces it. A scroll step, and any other LinkedIn page, does not.
FEED_GAP_MINUTES = 30

#: Where the stop and the load timestamps live. One small JSON, next to the
#: 429 cooldowns, holding times and reasons: no URL, no cookie, no page text.
_GUARD_FILE = "linkedin_guard.json"

#: Kept load timestamps: the widest window is a day.
_KEEP_SECONDS = 24 * 60 * 60

#: What each persisted stop reason means, in one line a reader can act on.
_REASON_LABEL = {
    "rate-limit": (
        "LinkedIn is rate limiting this address (http-429, the 999 vendor "
        "code, or its too-many-pages page)"
    ),
    "checkpoint": "LinkedIn served a security checkpoint instead of the page",
    "logout": "LinkedIn ended or refused the kept login (checkpoint or forced logout)",
    "restriction": "LinkedIn restricted this account",
}

#: The text and URL shapes that are a stop rather than a page. Matched against
#: the raw body, because a checkpoint's copy is in the markup even when the
#: extract is empty. Narrow on purpose: these are LinkedIn's own words, and
#: they only ever decide a stop for a linkedin.com URL.
_RESTRICTION = re.compile(
    r"(?i)(?:"
    r"your account is temporarily restricted|"
    r"account (?:has been |is )?(?:temporarily )?restricted|"
    r"account restriction|"
    r"we(?:'ve| have) restricted your account"
    r")"
)
_TOO_MANY_PAGES = re.compile(
    r"(?i)(?:"
    r"very high number of pages|"
    r"too many pages|too many page (?:visits|requests|views)|"
    r"(?:reached|hit) (?:a|the) (?:daily )?limit of page|"
    r"you(?:'ve| have) (?:reached|hit) (?:the )?page limit"
    r")"
)
_CHECKPOINT_TEXT = re.compile(
    r"(?i)\b(?:security (?:check|verification)|quick security check|"
    r"verify (?:it'?s|it is) you|confirm your identity|"
    r"unusual activity on your account|account checkpoint)\b"
)
_CHECKPOINT_PATH = re.compile(r"(?i)^/(?:checkpoint|authwall)(?:/|$)")
_LOGOUT_TEXT = re.compile(
    r"(?i)\b(?:you(?:'ve| have) been (?:temporarily )?signed out|"
    r"your session (?:has )?expired|you are signed out|session timed out|"
    r"sign in to linkedin)\b"
)
_LOGOUT_PATH = re.compile(r"(?i)^/(?:uas/)?login(?:/|$)|^/authwall(?:/|$)")

#: Module-level clock, sleep and randomness, so a test can use a fake clock
#: instead of spending 20 real seconds between two stubbed page loads.
_now: Callable[[], float] = time.time
_sleep: Callable[[float], None] = time.sleep
_random: Callable[[], float] = random.random

#: A person's profile, and only that: ``/in/<handle>/``. A details page
#: (``/in/<handle>/details/experience/``), a post, or an activity feed is not
#: a profile to assemble.
_PROFILE_PATH = re.compile(r"^/in/[^/]+/?$")

#: Routes whose content LinkedIn builds in the browser. Measured 2026-11-02:
#: ``/search/results/people/?keywords=`` failed on curl_cffi and returned 200
#: from the stealth browser. Asking the browser first saves the direct request
#: that is known to lose; the remaining rungs stay in place.
_BROWSER_FIRST_PREFIX = "/search/results/"

#: The Education section is the same: measured 2026-11-02, curl_cffi returned
#: HTTP 200 with only the page shell (title, profile link, language list), and
#: the school entries are rendered in the browser. Experience still renders in
#: the markup, so only this one section moves ahead of the direct rung.
_BROWSER_FIRST_SECTION = re.compile(r"^/in/[^/]+/details/education/?$")


def _host(url: str) -> str:
    """Lower-case host of `url` (a bare host is accepted), no trailing dot."""
    return (
        urlparse(url if "://" in url else "https://" + url).hostname or ""
    ).lower().rstrip(".")


def matches(url: str) -> bool:
    """True for linkedin.com and its subdomains, and nothing that looks like it."""
    host = _host(url)
    return host == _LINKEDIN or host.endswith("." + _LINKEDIN)


def is_profile(url: str) -> bool:
    """True when `url` is a person's main profile page."""
    path = urlparse(url if "://" in url else "https://" + url).path or ""
    return bool(_PROFILE_PATH.fullmatch(path))


#: The signed-in home feed, and only it. ``/feed/update/...`` is one post and
#: keeps the ordinary ladder; ``/feed/`` is the list that only the browser
#: signed in to it can grow (#511).
_FEED_PATH = re.compile(r"^/feed/?$")


def is_feed(url: str) -> bool:
    """True when `url` is the LinkedIn home feed."""
    if not matches(url):
        return False
    path = urlparse(url if "://" in url else "https://" + url).path or ""
    return bool(_FEED_PATH.fullmatch(path))


def browser_first(url: str) -> bool:
    """True for a LinkedIn route only the browser renders.

    Search results and a profile's Education section. Every other route keeps
    the ordinary ladder, so a page whose markup carries the content still gets
    the cheap direct request first.
    """
    if not matches(url):
        return False
    path = urlparse(url if "://" in url else "https://" + url).path or ""
    return bool(
        path.startswith(_BROWSER_FIRST_PREFIX)
        or _BROWSER_FIRST_SECTION.fullmatch(path)
    )


def detail_urls(url: str) -> List[Tuple[str, str]]:
    """The ``(section, url)`` pages a profile keeps its sections on.

    Empty when `url` is not a profile, so a caller can treat "no sections" and
    "not a profile" the same way. Both URLs keep the profile's own scheme and
    host, which is what the read was already scoped to.
    """
    if not is_profile(url):
        return []
    parsed = urlparse(url if "://" in url else "https://" + url)
    handle = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if not handle:
        return []
    base = f"{parsed.scheme or 'https'}://{parsed.netloc or 'www.linkedin.com'}"
    root = f"{base}/in/{handle}/details"
    return [
        ("Experience", f"{root}/experience/"),
        ("Education", f"{root}/education/"),
    ]


def rate_limit_hint() -> str:
    """What a LinkedIn http-429 means, and what to do instead of queueing more."""
    return (
        "LinkedIn is rate limiting this address (http-429). Wait out the 24 h "
        "pause: a rate limit, a 999 or a too-many-pages page pauses LinkedIn "
        "for 24 h. This read stopped rather than spending more requests on the "
        "same host; a profile read adds one request per section. No automatic "
        "retry runs, and --wait-on-429 cannot override this stop. After that, "
        "or once the account is clear, `searchts login resume linkedin.com` "
        "lifts it early."
    )


# ── the LinkedIn guard (#509 point 6) ───────────────────────────────────────
#
# The general 429 stop is one sentence: a direct rung's 429 ends the read. On
# LinkedIn the same answer costs more than a random site's: the request carried
# the user's own account, so a second rung, a retry, or the two section pages a
# profile read adds are someone else's problem the next morning. This guard is
# the host-specific half of the rule, kept beside the wording that explains it.
#
# Two facts are persisted, both times and reasons in one small JSON under the
# searchts state dir: the stop (until when, and why) and the timestamps of the
# page loads already spent. No URL, no path, no cookie, no page text.


class Paced(Exception):
    """A LinkedIn page load the local budget does not allow right now.

    ``why`` is the one-line reason (which window, or the gap), and ``hint`` is
    the sentence a caller can act on, naming the env var that sets the window.
    Raised before the request, never after it.
    """

    def __init__(self, why: str, hint: str) -> None:
        super().__init__(why)
        self.why = why
        self.hint = hint


@dataclass(frozen=True)
class Stop:
    """A persisted LinkedIn stop: why, and when it ends (``None`` = a person)."""

    reason: str
    since: float
    until: Optional[float]

    def active(self, now: Optional[float] = None) -> bool:
        """True while this stop still says no request to LinkedIn."""
        if self.until is None:
            return True
        base = _now() if now is None else float(now)
        return self.until > base

    def seconds_left(self, now: Optional[float] = None) -> Optional[float]:
        """Seconds until it expires, or None for the restriction that needs a person."""
        if self.until is None:
            return None
        base = _now() if now is None else float(now)
        return max(0.0, self.until - base)


def _guard_path() -> Path:
    """The guard file, in the same state dir as the 429 cooldowns."""
    from searchts import rate_limit

    return rate_limit.state_dir() / _GUARD_FILE


def _load_guard() -> Dict[str, Any]:
    """The guard JSON, or an empty map when it is missing, broken or not a map."""
    try:
        with open(_guard_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:  # noqa: BLE001 - local state is never a read error
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _save_guard(state: Dict[str, Any]) -> None:
    """Write the guard JSON atomically enough for a local state file. Never raises."""
    path = _guard_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001 - an unwritable state dir is not a read error
        return


def _stop_from_state(state: Dict[str, Any]) -> Optional[Stop]:
    raw = state.get("stop")
    if not isinstance(raw, dict):
        return None
    reason = str(raw.get("reason") or "")
    if reason not in _REASON_LABEL:
        return None
    try:
        since = float(raw.get("since") or 0.0)
    except (TypeError, ValueError):
        since = 0.0
    until_raw = raw.get("until")
    until: Optional[float]
    if until_raw is None:
        until = None
    else:
        try:
            until = float(until_raw)
        except (TypeError, ValueError):
            return None
    return Stop(reason=reason, since=since, until=until)


def current_stop(now: Optional[float] = None) -> Optional[Stop]:
    """The active LinkedIn stop, or None. An expired one is pruned from disk."""
    base = _now() if now is None else float(now)
    state = _load_guard()
    stop = _stop_from_state(state)
    if stop is None:
        return None
    if not stop.active(base):
        state.pop("stop", None)
        _save_guard(state)
        return None
    return stop


def record_stop(reason: str, now: Optional[float] = None) -> Optional[Stop]:
    """Persist a LinkedIn stop and return it.

    ``restriction`` stops until a person clears it; every other reason stops
    for :data:`STOP_SECONDS` from now. A longer stop already on disk is kept,
    and a restriction is never downgraded to a timed one, because the account
    is still restricted until someone lifts it.
    """
    if reason not in _REASON_LABEL:
        return None
    base = _now() if now is None else float(now)
    state = _load_guard()
    existing = _stop_from_state(state)
    if existing is not None and existing.active(base):
        if existing.reason == "restriction" and reason != "restriction":
            return existing
        until = None if reason == "restriction" else base + STOP_SECONDS
        if (
            until is not None
            and existing.until is not None
            and existing.until > until
        ):
            until = existing.until
        stop = Stop(reason=reason, since=base, until=until)
    else:
        stop = Stop(
            reason=reason,
            since=base,
            until=None if reason == "restriction" else base + STOP_SECONDS,
        )
    state["stop"] = {"reason": stop.reason, "since": stop.since, "until": stop.until}
    _save_guard(state)
    return stop


def clear_stop() -> bool:
    """Drop any persisted LinkedIn stop. True when one was there."""
    state = _load_guard()
    if "stop" not in state:
        return False
    state.pop("stop", None)
    _save_guard(state)
    return True


def _li_at_cleared(headers: Optional[Any]) -> bool:
    """True when a response cookie drops the kept ``li_at`` session.

    LinkedIn ends a session by sending ``li_at`` back empty, deleted, or with
    ``Max-Age=0``. That is a forced logout only when this read actually sent
    the kept login; a public page has no such cookie to clear.
    """
    if not headers or not hasattr(headers, "items"):
        return False
    chunks: List[str] = []
    try:
        pairs = list(headers.items())
    except Exception:  # noqa: BLE001 - a broken header map is not a logout
        return False
    for key, value in pairs:
        if str(key).lower() != "set-cookie":
            continue
        if isinstance(value, (list, tuple)):
            chunks.extend(str(part) for part in value)
        else:
            chunks.append(str(value))
    for chunk in chunks:
        for match in re.finditer(r"(?i)(?:^|[\n,])\s*li_at=([^;,\n]*)", chunk):
            value = match.group(1).strip().strip('"')
            tail = chunk[match.end():match.end() + 80].lower()
            if value in ("", "deleted", "expired"):
                return True
            if "max-age=0" in tail or "max-age=-" in tail:
                return True
    return False


def stop_signal(
    status: Optional[int],
    body: str,
    final_url: str,
    *,
    signed_in: bool = False,
    headers: Optional[Any] = None,
) -> Optional[str]:
    """Which LinkedIn stop, if any, this answer is. ``None`` for an ordinary page.

    Checked against the body rather than the extract because a checkpoint's
    copy is in the markup and the extract can be empty. ``signed_in`` gates the
    logout read: a public page that says "Sign in to LinkedIn" is the ordinary
    login wall, not proof that a kept login was ended. A cleared ``li_at``
    cookie is the same fact when the request had sent one.
    """
    if status in (429, 999):
        return "rate-limit"
    text = body or ""
    if _TOO_MANY_PAGES.search(text):
        return "rate-limit"
    if _RESTRICTION.search(text):
        return "restriction"
    path = urlparse(final_url or "").path or ""
    if _CHECKPOINT_PATH.match(path) or _CHECKPOINT_TEXT.search(text):
        return "checkpoint"
    if signed_in and (
        _LOGOUT_PATH.match(path)
        or _LOGOUT_TEXT.search(text)
        or _li_at_cleared(headers)
    ):
        return "logout"
    return None


def _human(seconds: float) -> str:
    """``23h 59m``, so the stop says how long is left without a raw float."""
    total = int(round(max(0.0, float(seconds))))
    hours, rest = divmod(total, 3600)
    minutes = rest // 60
    if hours:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    if minutes:
        return f"{minutes}m"
    return f"{total}s"


def stop_hint(stop: Stop, now: Optional[float] = None) -> str:
    """What this stop means, and the one command that lifts it.

    A restriction needs a person, so no timer is promised. Every other reason
    expires on its own after 24 h, and ``searchts login resume`` clears it now.
    """
    label = _REASON_LABEL.get(stop.reason, "LinkedIn stopped this read")
    resume = "`searchts login resume linkedin.com`"
    if stop.reason == "restriction":
        return (
            f"LinkedIn read stop: {label}. searchts will not send another "
            f"LinkedIn request until a person clears it. Lift the restriction "
            f"on linkedin.com, then run {resume} to resume reads. No automatic "
            "retry runs, and --wait-on-429 never overrides this stop."
        )
    left = stop.seconds_left(now)
    when = f"for another {_human(left)}" if left else "until it expires"
    extra = ""
    if stop.reason in ("checkpoint", "logout"):
        extra = (
            " searchts does not sign in again on its own. Sign in by hand in "
            "your browser, then keep the login again (`searchts login keep`) "
            "or sign in once with `searchts login signin`, after the stop "
            "is lifted."
        )
    return (
        f"LinkedIn read stop: {label}, so searchts stopped the read and paused "
        f"LinkedIn {when} (24 h from the answer).{extra} No automatic retry "
        f"runs, and --wait-on-429 never overrides this stop. It expires on its "
        f"own; run {resume} to clear it early once the account is fine."
    )


def _env_int(name: str, default: int) -> int:
    """A non-negative integer from the environment, or ``default``.

    Invalid text is the default, not an error: a typo in a pacing knob must not
    make a read fail. A value at or below zero is 0, which turns that window
    off (the issue names the daily one).
    """
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return max(0, int(float(str(raw).strip())))
    except (TypeError, ValueError):
        return default


def load_limits() -> Tuple[int, int, int]:
    """``(per minute, per hour, per day)`` LinkedIn load caps; 0 means no cap."""
    return (
        _env_int("SEARCHTS_LINKEDIN_LOADS_PER_MINUTE", LOADS_PER_MINUTE),
        _env_int("SEARCHTS_LINKEDIN_LOADS_PER_HOUR", LOADS_PER_HOUR),
        _env_int("SEARCHTS_LINKEDIN_LOADS_PER_DAY", LOADS_PER_DAY),
    )


def feed_gap_minutes() -> int:
    """Minutes between LinkedIn home-feed document loads (default 30).

    ``SEARCHTS_LINKEDIN_FEED_GAP_MINUTES``. The feed reader enforces this.
    It is not a gap on every LinkedIn page, and a scroll step is not a load.
    """
    return _env_int("SEARCHTS_LINKEDIN_FEED_GAP_MINUTES", FEED_GAP_MINUTES)


def _load_stamps(state: Dict[str, Any], now: float) -> List[float]:
    """Page-load timestamps from the last day, newest last; junk is dropped."""
    raw = state.get("loads")
    if not isinstance(raw, list):
        return []
    stamps: List[float] = []
    for item in raw:
        try:
            value = float(item)
        except (TypeError, ValueError):
            continue
        # A stamp a little ahead of ``now`` is a load whose gap was booked
        # before the clock the caller is reading. An hour ahead is garbage.
        if now - _KEEP_SECONDS <= value <= now + 300:
            stamps.append(value)
    return sorted(stamps)


def _window_hint(window: str, spent: int, cap: int, env: str, wait: float) -> str:
    """The sentence a refused LinkedIn load shows, naming the env var that sets it."""
    daily = (
        " (0 turns the daily cap off)."
        if env == "SEARCHTS_LINKEDIN_LOADS_PER_DAY"
        else "."
    )
    return (
        f"LinkedIn load budget: {spent} page loads in the last {window}, "
        f"and the cap is {cap} ({env}). No further request was sent. Wait "
        f"{_human(wait)}, or raise {env}{daily} "
        "SEARCHTS_LINKEDIN_FEED_GAP_MINUTES (default 30) is the gap between "
        "LinkedIn feed reads."
    )


def take_load(
    *,
    now: Optional[float] = None,
    sleep: Optional[Callable[[float], None]] = None,
    rand: Optional[Callable[[], float]] = None,
) -> float:
    """Spend one LinkedIn page-load slot, waiting for the gap when needed.

    Called before a direct rung issues its request, so every request that
    reaches LinkedIn has passed through here. Returns the timestamp recorded.

    The gap (at least 20 s, plus up to 15 s of jitter) is slept. That wait is
    at most 35 s, so it is not checked against the read's remaining budget:
    sleeping is the simpler choice, and a read that is already loading a page
    can spare it. The minute window is slept out too (at most 60 s). A
    logged-in profile is three loads, and the third would otherwise land
    inside the same minute as the first and be refused; waiting for the slot
    is what makes that read finish in about a minute without going over 2
    loads a minute. An hour or a day is not a wait a read can sit through, so
    those windows refuse and name their env var. ``0`` turns a window off.
    """
    base = _now() if now is None else float(now)
    do_sleep = _sleep if sleep is None else sleep
    pick = _random if rand is None else rand
    state = _load_guard()
    stamps = _load_stamps(state, base)
    per_minute, per_hour, per_day = load_limits()
    refusing = (
        ("hour", per_hour, 3600.0, "SEARCHTS_LINKEDIN_LOADS_PER_HOUR"),
        ("day", per_day, 86400.0, "SEARCHTS_LINKEDIN_LOADS_PER_DAY"),
    )
    for window, cap, span, env in refusing:
        if cap <= 0:
            continue
        recent = [stamp for stamp in stamps if base - stamp < span]
        if len(recent) < cap:
            continue
        wait = max(0.0, recent[0] + span - base)
        why = (
            f"LinkedIn load budget spent: {len(recent)} in the last {window}, "
            f"cap {cap}"
        )
        raise Paced(why, _window_hint(window, len(recent), cap, env, wait))
    if per_minute > 0:
        recent = [stamp for stamp in stamps if base - stamp < 60.0]
        if len(recent) >= per_minute:
            wait = max(0.0, recent[0] + 60.0 - base)
            if wait <= 0:
                raise Paced(
                    f"LinkedIn load budget spent: {len(recent)} in the last "
                    f"minute, cap {per_minute}",
                    _window_hint(
                        "minute", len(recent), per_minute,
                        "SEARCHTS_LINKEDIN_LOADS_PER_MINUTE", wait,
                    ),
                )
            do_sleep(wait)
            base += wait
    if stamps:
        gap = MIN_GAP_SECONDS + max(0.0, min(1.0, float(pick()))) * MAX_JITTER_SECONDS
        wait = (stamps[-1] + gap) - base
        if wait > 0:
            do_sleep(wait)
            base += wait
    stamps.append(base)
    state["loads"] = [stamp for stamp in stamps if base - _KEEP_SECONDS <= stamp <= base + 300]
    _save_guard(state)
    return base


#: How many times this thread already holds the LinkedIn load lock. A profile
#: read fetches its sections from inside the load that fetched the profile, and
#: a second ``flock`` on a new descriptor would wait for the first one, which
#: this same thread is holding. The nested call still spends a slot.
_hold = threading.local()


class exclusive_load:
    """One LinkedIn page load at a time, across processes, via a lock file.

    The lock sits next to the guard file. It is held from the moment the slot
    is booked until the request that spends it has returned, so two reads
    cannot both decide the gap has elapsed and hit LinkedIn together. Use it
    as a context manager. :class:`Paced` from entering it means no request
    was sent and the lock is not held.
    """

    def __init__(self) -> None:
        self._nested = False
        self._fh: Optional[IO[str]] = None

    def __enter__(self) -> "exclusive_load":
        depth = int(getattr(_hold, "depth", 0) or 0)
        if depth:
            self._nested = True
            _hold.depth = depth + 1
            try:
                take_load()
            except BaseException:
                _hold.depth = depth
                raise
            return self
        self._fh = _acquire_load_lock()
        try:
            take_load()
        except BaseException:
            self._unlock()
            raise
        _hold.depth = 1
        return self

    def __exit__(self, *exc: object) -> Literal[False]:
        if self._nested:
            _hold.depth = max(0, int(getattr(_hold, "depth", 1) or 1) - 1)
            return False
        _hold.depth = 0
        self._unlock()
        return False

    def _unlock(self) -> None:
        fh = self._fh
        self._fh = None
        if fh is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()
            if fcntl is None:
                _thread_lock.release()


def _acquire_load_lock() -> IO[str]:
    """Block until this process holds the LinkedIn load lock file."""
    path = _guard_path().with_name("linkedin_load.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+", encoding="utf-8")
    if fcntl is None:
        _thread_lock.acquire()
        return fh
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    except BaseException:
        fh.close()
        raise
    return fh


_thread_lock = threading.Lock()


# ── chrome ──────────────────────────────────────────────────────────────────

#: A notification count in the header. Fixed shape, never prose.
_NOTIFICATIONS = re.compile(r"^\d[\d,]* notifications?$", re.IGNORECASE)
_TRY_PREMIUM = re.compile(r"^Try Premium(?: for .+)?$")
_ACTIVATE_PREMIUM = re.compile(r"^\[Activate Premium for ")
_CORPORATION = re.compile(r"^LinkedIn Corporation © \d{4}$")
#: One injected Premium card between feed posts. Matched inside a block that
#: begins at its own specific heading.
_PREMIUM_BOARD_LINE = re.compile(
    r"(?:Premium members are .* more likely to get hired"
    r"|and millions more use Premium$"
    r"|^\[Try for free\]\()"
)

#: UI labels that are unmistakably LinkedIn's own, wherever they appear. Short
#: ordinary words ("Resources", "Open to") are deliberately not here: those
#: need a neighbouring button before they count, see :func:`_button_context`.
#: The five skip links are the first lines of a section page rendered in the
#: browser (measured 2026-11-02); a signed-in page read over HTTP does not have
#: them, so they are no-ops there.
_CHROME_EXACT = frozenset({
    "Skip to search",
    "Skip to main content",
    "Skip to primary content",
    "Skip to aside",
    "Skip to footer",
    "Enhance profile",
    "Enhance cover image",
    "Visit our Help Center.",
    "Go to your Settings.",
    "Learn more about Recommended Content.",
})

#: The whole ad-options panel, in page order. It starts at "Ad Options" and ends
#: at "Submit"; if LinkedIn changes a line the block stops there and keeps the
#: rest, which is the safe direction.
_AD_BLOCK = frozenset({
    "Why am I seeing this ad?",
    "Manage your ad preferences",
    "Hide or report this ad",
    "I don’t want to see this ad in my feed",
    "Don’t want to see this",
    "Tell us why you don’t want to see this",
    "Your feedback will help us improve your experience",
    "It’s annoying or not interesting",
    "I’ve seen the same ad too often",
    "If you think this goes against our Professional Community Policies, "
    "please let us know.",
    "Report this ad",
})

#: The English name of every language LinkedIn offers, which is the stable part
#: of its picker line. The text before the parenthesis is NOT stable: LinkedIn's
#: own extraction drops combining marks in some scripts, so `हिंदी (Hindi)`
#: arrives as `हिदी (Hindi)` and `తెలుగు (Telugu)` as `తలుగు (Telugu)` (measured
#: 2026-11-02). Matching the exact line stopped at Hindi and left the rest of
#: the list in the read. Only the block after "Select language" is filtered;
#: outside it a line ending in a parenthesis is content.
_LANGUAGE_NAMES = (
    "Arabic", "Bangla", "Czech", "Danish", "German", "Greek", "English",
    "Spanish", "Persian", "Finnish", "French", "Hindi", "Hungarian",
    "Indonesian", "Italian", "Hebrew", "Japanese", "Korean", "Marathi",
    "Malay", "Dutch", "Norwegian", "Punjabi", "Polish", "Portuguese",
    "Romanian", "Russian", "Swedish", "Telugu", "Thai", "Tagalog", "Turkish",
    "Ukrainian", "Vietnamese", "Chinese (Simplified)",
    "Chinese (Traditional)",
)

#: ``<anything> (<English name>)``, e.g. `English (English)`. Anchored at both
#: ends so prose that merely mentions a language keeps its line.
_LANGUAGE_LINE = re.compile(
    r"^.+ \((?:" + "|".join(re.escape(n) for n in _LANGUAGE_NAMES) + r")\)$"
)

#: Owner-only buttons. Only dropped when another one sits next to them, so a
#: single line that says "Resources" in a post survives.
_BUTTONS = frozenset({"Resources", "Open to", "Enhance profile", "Enhance cover image"})


def _next_content(lines: Sequence[str], i: int, step: int) -> int:
    j = i + step
    while 0 <= j < len(lines) and not lines[j].strip():
        j += step
    return j if 0 <= j < len(lines) else -1


def _button_context(lines: Sequence[str], i: int) -> bool:
    for step in (-1, 1):
        j = _next_content(lines, i, step)
        if j < 0:
            continue
        neighbour = lines[j].strip()
        if neighbour in _BUTTONS or neighbour.startswith("[Add section]("):
            return True
    return False


def _drop_footer_line(line: str) -> bool:
    return bool(
        _CORPORATION.match(line)
        or line.startswith((
            "[Questions?](",
            "[Manage your account and privacy](",
            "[Recommendation transparency](",
            "[Activate Premium for ",
            "[Add section](",
        ))
        or line.startswith("1-month free trial.")
    )


def _drop_simple(line: str, lines: Sequence[str], i: int) -> bool:
    return bool(
        _NOTIFICATIONS.match(line)
        or _TRY_PREMIUM.match(line)
        or line in _CHROME_EXACT
        or _drop_footer_line(line)
        or (line in _BUTTONS and _button_context(lines, i))
    )


def strip_chrome(text: str) -> str:
    """Remove LinkedIn's fixed page furniture, keeping every content line.

    The rule is the same one ``more.py`` uses for a side panel: only drop what
    is named, and stop a block at the first line that is not part of it. A
    profile's name, headline, location, connections, experience prose and
    company posts are never in any set here, so they cannot match.
    """
    lines = (text or "").split("\n")
    out: List[str] = []
    i = 0
    in_ad = False
    in_language = False
    in_premium = False
    while i < len(lines):
        line = lines[i]
        clean = line.strip()

        if in_ad:
            if not clean or clean in _AD_BLOCK:
                i += 1
                continue
            if clean == "Submit":
                in_ad = False
                i += 1
                continue
            in_ad = False

        if in_language:
            if not clean or _LANGUAGE_LINE.match(clean):
                i += 1
                continue
            in_language = False

        if in_premium:
            if not clean or _PREMIUM_BOARD_LINE.search(clean):
                if clean.startswith("[Try for free]("):
                    in_premium = False
                i += 1
                continue
            in_premium = False

        if clean == "Ad Options":
            in_ad = True
            i += 1
            continue
        if clean == "Select language":
            in_language = True
            i += 1
            continue
        if clean == "Boost your job search":
            in_premium = True
            i += 1
            continue

        if clean == "Profile language":
            # Owner-only panel: the language, then the public URL. Both are
            # page furniture, and both are only skipped when they are there.
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                j += 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and lines[j].strip() == "Public profile & URL":
                j += 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and re.fullmatch(
                    r"(?:www\.)?linkedin\.com/in/\S+/?", lines[j].strip()
                ):
                    j += 1
            i = j
            continue

        if _drop_simple(clean, lines, i):
            i += 1
            continue

        out.append(line)
        i += 1

    squeezed: List[str] = []
    blank = False
    for line in out:
        if not line.strip():
            if blank:
                continue
            blank = True
            squeezed.append("")
        else:
            blank = False
            squeezed.append(line.rstrip())
    return "\n".join(squeezed).strip()


# ── assembly ────────────────────────────────────────────────────────────────

#: The shell a JavaScript-rendered section page comes back as: a title, a link
#: to the profile itself, and bracketed notes. Nothing here can be a school,
#: employer, date or sentence, so ignoring these lines cannot drop content.
_SHELL_TITLE = re.compile(r".*\|\s*LinkedIn\s*$")
_SHELL_PROFILE_LINK = re.compile(
    r"^\[[^\]]*\]\(https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[^)]*\)$"
)
_SHELL_NOTE = re.compile(r"^\[(?:media|left out|linkedin)\b.*\]$")


def has_section_content(text: str) -> bool:
    """True when a section page holds more than its own header and notes.

    LinkedIn's Education page renders its entries in JavaScript. Measured
    2026-11-02: curl_cffi returned HTTP 200 with the title line
    ``Name | LinkedIn``, a link to the profile, the language picker and
    bracketed notes, and no schools. Joining that shell as the Education
    section would claim an empty education.

    Conservative by construction: a line counts as content unless it is one of
    the three known shell shapes, so any unexpected line keeps the section.
    """
    for line in strip_chrome(text).splitlines():
        clean = line.strip()
        if not clean:
            continue
        if _SHELL_TITLE.match(clean) or _SHELL_NOTE.match(clean):
            continue
        if _SHELL_PROFILE_LINK.match(clean):
            continue
        return True
    return False


def _trim_section(text: str, label: str) -> str:
    """Drop a section page's repeated header and its own section label.

    A detail page arrives with the same shell as the profile: the browser's
    ``<Name> | LinkedIn`` title, a link back to the profile, and then the
    section label that :func:`assemble` already writes as a Markdown heading.
    Only *leading* lines of those known shapes are removed; the first real
    entry stops the trim, so an employer called "Experience" midway through the
    list is untouched.
    """
    lines = (text or "").strip().split("\n")
    i = 0
    while i < len(lines):
        clean = lines[i].strip()
        if not clean:
            i += 1
            continue
        heading = clean.lstrip("#").strip().lower()
        if (
            _SHELL_TITLE.match(clean)
            or _SHELL_PROFILE_LINK.match(clean)
            or heading == label.lower()
        ):
            i += 1
            continue
        break
    return "\n".join(lines[i:]).strip()


def assemble(
    base: str,
    sections: Sequence[Tuple[str, Optional[str], str]],
) -> Tuple[str, List[str]]:
    """Join a profile's top card and its section pages into one document.

    ``sections`` holds ``(label, text, reason)``: text when the section was
    read, reason when it was not. A failed section is named in a trailing note
    and never costs the caller the rest of the profile (fail loud about the
    missing part, not about the whole read).
    """
    parts = [(base or "").strip()]
    notes: List[str] = []
    for label, text, reason in sections:
        if not text:
            why = reason or "no text came back"
            notes.append(
                f"[linkedin: the {label} section could not be read ({why}); "
                f"the rest of the profile is here]"
            )
            continue
        parts.append(f"## {label}\n\n{_trim_section(text, label)}")
    return "\n\n".join(p for p in parts if p), notes
