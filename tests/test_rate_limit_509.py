# -*- coding: utf-8 -*-
"""#509: a direct http-429 stops the read, cools the host, and guards LinkedIn.

No test here contacts a site. Rungs are stubs. The LinkedIn clock and the
cooldown file live in the per-test cache dir.
"""

import json
import threading
from email.utils import formatdate
from unittest.mock import patch

import pytest

from searchts import expand, knobs, linkedin, rate_limit, scroll, unlocker
from searchts.cli import main
from searchts.session_cookies import CookieRecord
from searchts.unlocker import UnlockerError, fetch

LONG = "A real paragraph about the list. " * 40
PAGE = (
    '<html><head><link rel="next" href="/blog/page/2/"></head>'
    "<body><p>page one</p></body></html>"
)
PAGE_URL = "https://example.test/blog/"
PAGE_NEXT = "https://example.test/blog/page/2/"


def _text(monkeypatch):
    monkeypatch.setattr(
        unlocker, "html_to_text", lambda body, url=None: LONG,
    )


def _no_later_rungs(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("a later rung must not run")

    monkeypatch.setattr(unlocker, "_fetch_jina", boom)
    monkeypatch.setattr(unlocker, "_fetch_stealth", boom)


def _curl(monkeypatch, fn):
    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", fn)


# ── point 1: any direct 429 stops; Jina's 429 does not ───────────────────────


def test_a_direct_429_records_a_host_cooldown_and_names_the_override(monkeypatch):
    _text(monkeypatch)
    _no_later_rungs(monkeypatch)
    _curl(monkeypatch, lambda url, **_k: (429, "slow", url, {"retry-after": "120"}))
    with pytest.raises(UnlockerError) as ei:
        fetch("https://example.test/a", use_memory=False, backends=["curl_cffi"])
    assert ei.value.attempts == [("curl_cffi", "http-429")]
    assert "example.test" in ei.value.hint
    assert "--ignore-cooldown" in ei.value.hint
    assert "--wait-on-429" in ei.value.hint
    rest = rate_limit.remaining("example.test")
    assert 100 < rest <= 120
    raw = rate_limit.state_path().read_text(encoding="utf-8")
    assert "http" not in raw
    assert "/" not in raw
    data = json.loads(raw)
    assert set(data) == {"example.test"}


def test_jina_429_is_the_relay_quota_and_does_not_cool_the_host(monkeypatch):
    _text(monkeypatch)
    calls = []

    def curl(url, **_k):
        calls.append("curl")
        return 503, "down", url, {}

    def jina(url, **_k):
        calls.append("jina")
        return 429, "quota", url, {}

    def stealth(url, timeout=60, progress=None, **_k):
        calls.append("stealth")
        return 200, "<p>ok</p>", url, {}

    _curl(monkeypatch, curl)
    monkeypatch.setattr(unlocker, "_fetch_jina", jina)
    monkeypatch.setattr(unlocker, "_fetch_stealth", stealth)
    result = fetch("https://example.test/a", use_memory=False)
    assert result.backend == "stealth-browser"
    assert calls == ["curl", "jina", "stealth"]
    assert rate_limit.remaining("example.test") == 0


def test_a_non_linkedin_999_does_not_cool_the_host(monkeypatch):
    _text(monkeypatch)

    def jina(url, **_k):
        return 200, LONG, url, {}

    _curl(monkeypatch, lambda url, **_k: (999, "vendor", url, {}))
    monkeypatch.setattr(unlocker, "_fetch_jina", jina)
    result = fetch("https://example.test/a", use_memory=False)
    assert result.backend == "Jina Reader"
    assert rate_limit.remaining("example.test") == 0


def test_the_human_rung_does_not_retry_a_429(monkeypatch):
    _no_later_rungs(monkeypatch)
    _curl(monkeypatch, lambda url, **_k: (429, "slow", url, {}))

    def human(url, timeout=180):
        raise AssertionError("human rung must not run after a 429")

    monkeypatch.setattr(unlocker, "_fetch_human", human)
    with pytest.raises(UnlockerError):
        fetch(
            "https://example.test/a", use_memory=False,
            allow_human=True, backends=["curl_cffi"],
        )


# ── point 2: cooldown file, Retry-After, cap, default, off, ignore ───────────


def test_retry_after_seconds_http_date_cap_and_default():
    assert rate_limit.parse_retry_after("120", now=1_000_000) == 120
    when = 1_000_000 + 90
    header = formatdate(when, usegmt=True)
    assert rate_limit.parse_retry_after(header, now=1_000_000) == pytest.approx(90, abs=1.5)
    assert rate_limit.parse_retry_after(formatdate(1_000_000 - 50, usegmt=True), now=1_000_000) == 0
    assert rate_limit.record("dated.test", None, now=1_000_000) == 1_000_000 + 300
    assert rate_limit.record("capped.test", "99999", now=1_000_000) == 1_000_000 + 1800


def test_an_expired_cooldown_is_pruned_and_a_zero_knob_records_nothing(monkeypatch):
    rate_limit.record("gone.test", "10", now=1_000)
    assert rate_limit.remaining("gone.test", now=2_000) == 0
    assert "gone.test" not in json.loads(rate_limit.state_path().read_text(encoding="utf-8"))
    monkeypatch.setenv("SEARCHTS_429_COOLDOWN", "0")
    assert rate_limit.record("fresh.test", "30", now=5_000) is None
    assert rate_limit.remaining("fresh.test", now=5_000) == 0


def test_a_cooldown_refuses_before_the_request_unless_ignored(monkeypatch):
    _text(monkeypatch)
    calls = []

    def curl(url, **_k):
        calls.append(url)
        return 200, "<p>ok</p>", url, {}

    _curl(monkeypatch, curl)
    rate_limit.record("example.test", "60")
    with pytest.raises(UnlockerError) as ei:
        fetch("https://example.test/a", use_memory=False, backends=["curl_cffi"])
    assert calls == []
    assert ei.value.attempts[0][0] == "cooldown"
    assert "example.test" in ei.value.hint
    assert "--ignore-cooldown" in ei.value.hint
    result = fetch(
        "https://example.test/a", use_memory=False,
        backends=["curl_cffi"], ignore_cooldown=True,
    )
    assert result.backend == "curl_cffi"
    assert calls == ["https://example.test/a"]


def test_cooldown_zero_still_stops_this_read_but_not_the_next(monkeypatch):
    _text(monkeypatch)
    monkeypatch.setenv("SEARCHTS_429_COOLDOWN", "0")
    n = {"i": 0}

    def curl(url, **_k):
        n["i"] += 1
        if n["i"] == 1:
            return 429, "slow", url, {}
        return 200, "<p>ok</p>", url, {}

    _curl(monkeypatch, curl)
    with pytest.raises(UnlockerError):
        fetch("https://example.test/a", use_memory=False, backends=["curl_cffi"])
    result = fetch("https://example.test/a", use_memory=False, backends=["curl_cffi"])
    assert result.backend == "curl_cffi"
    assert n["i"] == 2
    assert rate_limit.remaining("example.test") == 0


# ── point 3: --wait-on-429 ────────────────────────────────────────────────────


def _patch_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(unlocker.time, "sleep", lambda seconds: slept.append(seconds))
    return slept


def test_wait_on_429_is_off_by_default(monkeypatch):
    slept = _patch_sleep(monkeypatch)
    n = {"i": 0}

    def curl(url, **_k):
        n["i"] += 1
        return 429, "slow", url, {"retry-after": "1"}

    _curl(monkeypatch, curl)
    with pytest.raises(UnlockerError):
        fetch("https://example.test/a", use_memory=False, backends=["curl_cffi"])
    assert n["i"] == 1
    assert slept == []


def test_wait_on_429_backs_off_and_stops_at_the_cap(monkeypatch):
    _text(monkeypatch)
    slept = _patch_sleep(monkeypatch)
    n = {"i": 0}

    def curl(url, **_k):
        n["i"] += 1
        if n["i"] <= 3:
            return 429, "slow", url, {}
        return 200, "<p>ok</p>", url, {}

    _curl(monkeypatch, curl)
    result = fetch(
        "https://example.test/a", use_memory=False,
        backends=["curl_cffi"], wait_on_429=True,
    )
    assert result.backend == "curl_cffi"
    assert slept == [5.0, 10.0, 20.0]
    assert n["i"] == 4


def test_wait_on_429_will_not_sleep_past_the_cap(monkeypatch):
    slept = _patch_sleep(monkeypatch)
    n = {"i": 0}

    def curl(url, **_k):
        n["i"] += 1
        return 429, "slow", url, {"retry-after": "100"}

    _curl(monkeypatch, curl)
    with pytest.raises(UnlockerError) as ei:
        fetch(
            "https://example.test/a", use_memory=False,
            backends=["curl_cffi"], wait_on_429=True,
        )
    assert slept == [100.0]
    assert n["i"] == 2
    assert "http-429" in " ".join(why for _, why in ei.value.attempts)


def test_a_signed_in_read_waits_once(monkeypatch):
    slept = _patch_sleep(monkeypatch)
    n = {"i": 0}

    def curl(url, **_k):
        n["i"] += 1
        return 429, "slow", url, {"retry-after": "1"}

    _curl(monkeypatch, curl)
    with pytest.raises(UnlockerError) as ei:
        fetch(
            "https://example.test/a",
            use_memory=False,
            backends=["curl_cffi"],
            wait_on_429=True,
            cookies=[CookieRecord("sid", "value", ".example.test")],
        )
    assert n["i"] == 2
    assert slept == [1.0] or slept == [1]
    assert "one wait" in ei.value.hint
    assert "account" in ei.value.hint


# ── point 4: walks stop and keep what they have ──────────────────────────────


def test_a_page_walk_stops_at_the_first_429_and_keeps_page_one(monkeypatch):
    _text(monkeypatch)
    _no_later_rungs(monkeypatch)
    seen = []

    def curl(url, **_k):
        seen.append(url)
        if url.rstrip("/") == PAGE_NEXT.rstrip("/"):
            return 429, "slow", url, {"retry-after": "30"}
        return 200, PAGE, url, {}

    _curl(monkeypatch, curl)
    pages = unlocker.read_pages(PAGE_URL, 3, use_memory=False)
    assert seen == [PAGE_URL, PAGE_NEXT]
    assert len(pages) == 1
    assert "http-429" in pages[0].text
    assert "--ignore-cooldown" in pages[0].text
    assert rate_limit.remaining("example.test") > 0


def test_an_items_walk_does_not_scroll_after_a_429(monkeypatch):
    _text(monkeypatch)
    _no_later_rungs(monkeypatch)
    seen = []

    def curl(url, **_k):
        seen.append(url)
        if url.rstrip("/") == PAGE_NEXT.rstrip("/"):
            return 429, "slow", url, {}
        return 200, PAGE, url, {}

    def scroll_boom(*_a, **_k):
        raise AssertionError("scroll must not run after a 429")

    _curl(monkeypatch, curl)
    monkeypatch.setattr(scroll, "collect_url", scroll_boom)
    pages = unlocker.read_items(PAGE_URL, 20, use_memory=False)
    assert seen == [PAGE_URL, PAGE_NEXT]
    assert "stopped before" in pages[0].text
    assert "http-429" in pages[0].text


def test_expand_stops_on_a_429_even_when_it_is_the_last_click(monkeypatch):
    pressed = []

    class _Handle:
        def __init__(self, page, idx):
            self.page = page
            self.idx = idx

        def click(self, timeout=3000):
            pressed.append(self.idx)
            if self.idx == 1:
                self.page.cb(type("R", (), {
                    "status": 429, "headers": {"retry-after": "9"},
                })())

    class _Page:
        url = "https://example.test/item"

        def on(self, _event, callback):
            self.cb = callback

        def query_selector(self, selector):
            idx = int(selector.split('"')[1])
            return _Handle(self, idx)

        def wait_for_timeout(self, _ms):
            return None

    monkeypatch.setattr(expand, "find_in_page", lambda _page: [
        {"why": "yes", "label": "Show more", "idx": 1},
        {"why": "yes", "label": "See more", "idx": 2},
    ])
    report = expand.click_in_page(_Page(), max_clicks=8)
    assert pressed == [1]
    assert report.clicks == 1
    assert report.stop and "http-429" in report.stop
    assert 1 < rate_limit.remaining("example.test") <= 9


def test_a_rate_limit_wall_stops_the_scroll_and_a_note_says_so(monkeypatch):
    class _Page:
        def evaluate(self, js):
            if "challenge-form" in js:
                return "rate-limit"
            return None

        def content(self):
            return "too many requests"

    assert scroll._wall(_Page()) == "rate-limit"

    class _Quiet:
        def evaluate(self, js):
            if "challenge-form" in js:
                return "rate-limit"
            return None

        def content(self):
            return "an ordinary feed"

    assert scroll._wall(_Quiet()) == ""
    monkeypatch.setattr(scroll, "browser_available", lambda: True)
    monkeypatch.setattr(scroll, "collect_url", lambda *_a, **_k: (None, "rate-limited"))
    note, report = unlocker._scroll_feed(
        "https://example.test/feed", 10, knobs.resolve(),
    )
    assert report is None
    assert "http-429" in note
    assert "--ignore-cooldown" in note


# ── point 5: signed-in items ceiling ─────────────────────────────────────────


def test_signed_in_items_use_their_own_ceiling(monkeypatch):
    asked = knobs.resolve(items=80, signed_in=True)
    assert asked.items == 50
    assert asked.note() == "[signed-in items: asked for 80, the ceiling is 50]"
    under = knobs.resolve(items=40, signed_in=True)
    assert under.items == 40
    assert under.note() == ""
    monkeypatch.setenv("SEARCHTS_MAX_ITEMS_SIGNED_IN", "80")
    raised = knobs.resolve(items=90, signed_in=True)
    assert raised.items == 80
    _text(monkeypatch)
    _no_later_rungs(monkeypatch)
    _curl(monkeypatch, lambda url, **_k: (200, "<p>ok</p>", url, {}))
    pages = unlocker.read_items(
        "https://example.test/list",
        90,
        cookies=[CookieRecord("sid", "value", ".example.test")],
        use_memory=False,
    )
    assert "signed-in items" in pages[0].text
    assert "the ceiling is 80" in pages[0].text


# ── point 6: LinkedIn guard ───────────────────────────────────────────────────


def _linkedin_curl(monkeypatch, status, body, final=None, headers=None):
    _no_later_rungs(monkeypatch)

    def curl(url, **_k):
        return status, body, final or url, headers or {}

    _curl(monkeypatch, curl)


def test_stop_signal_names_429_999_pages_checkpoint_logout_and_restriction():
    page = "https://www.linkedin.com/feed/"
    phrase = (
        "It looks like you're visiting a very high number of pages on LinkedIn"
    )
    assert linkedin.stop_signal(429, "ok", page) == "rate-limit"
    assert linkedin.stop_signal(999, "ok", page) == "rate-limit"
    assert linkedin.stop_signal(200, phrase, page) == "rate-limit"
    assert linkedin.stop_signal(200, "this feature is restricted", page) is None
    assert linkedin.stop_signal(
        200, "Your account is temporarily restricted", page,
    ) == "restriction"
    assert linkedin.stop_signal(
        200, "ok", "https://www.linkedin.com/checkpoint/challenge/",
    ) == "checkpoint"
    assert linkedin.stop_signal(
        200, "ok", "https://www.linkedin.com/authwall", signed_in=True,
    ) == "checkpoint"
    assert linkedin.stop_signal(
        200, "ok", "https://www.linkedin.com/uas/login", signed_in=False,
    ) is None
    assert linkedin.stop_signal(
        200, "ok", "https://www.linkedin.com/uas/login", signed_in=True,
    ) == "logout"
    cleared = {"set-cookie": 'li_at=""; Max-Age=0'}
    assert linkedin.stop_signal(
        200, "ok", page, signed_in=False, headers=cleared,
    ) is None
    assert linkedin.stop_signal(
        200, "ok", page, signed_in=True, headers=cleared,
    ) == "logout"


def test_a_linkedin_429_sets_a_24h_stop_and_never_waits(monkeypatch):
    slept = _patch_sleep(monkeypatch)
    n = {"i": 0}

    def curl(url, **_k):
        n["i"] += 1
        return 429, "slow", url, {"retry-after": "1"}

    _no_later_rungs(monkeypatch)
    _curl(monkeypatch, curl)
    with pytest.raises(UnlockerError) as ei:
        fetch(
            "https://www.linkedin.com/in/someone/",
            use_memory=False,
            wait_on_429=True,
            ignore_cooldown=True,
        )
    assert n["i"] == 1
    assert slept == []
    stop = linkedin.current_stop()
    assert stop is not None
    assert stop.reason == "rate-limit"
    assert stop.until is not None
    assert stop.until - stop.since == linkedin.STOP_SECONDS
    assert "24" in ei.value.hint
    assert "--wait-on-429" in ei.value.hint
    raw = (rate_limit.state_dir() / "linkedin_guard.json").read_text(encoding="utf-8")
    assert "http" not in raw
    assert "someone" not in raw

    def boom(*_a, **_k):
        raise AssertionError("a stopped LinkedIn read must not send a request")

    _curl(monkeypatch, boom)
    with pytest.raises(UnlockerError) as again:
        fetch(
            "https://www.linkedin.com/feed/",
            use_memory=False,
            wait_on_429=True,
            ignore_cooldown=True,
        )
    assert again.value.attempts[0] == ("linkedin-stop", "rate-limit")
    assert "login resume" in again.value.hint


def test_linkedin_999_and_too_many_pages_set_the_same_stop(monkeypatch):
    _linkedin_curl(monkeypatch, 999, "no")
    with pytest.raises(UnlockerError):
        fetch("https://www.linkedin.com/in/someone/", use_memory=False)
    assert linkedin.current_stop().reason == "rate-limit"
    linkedin.clear_stop()
    rate_limit.forget("linkedin.com")
    phrase = (
        "It looks like you're visiting a very high number of pages on LinkedIn"
    )
    _linkedin_curl(monkeypatch, 200, phrase)
    with pytest.raises(UnlockerError) as ei:
        fetch("https://www.linkedin.com/in/someone/", use_memory=False)
    assert ei.value.attempts[0][1] == "linkedin-rate-limit"
    assert linkedin.current_stop().reason == "rate-limit"


def test_a_checkpoint_does_not_sign_in_again_and_a_restriction_waits_for_a_person(
    monkeypatch,
):
    _linkedin_curl(
        monkeypatch, 200, "ok",
        final="https://www.linkedin.com/checkpoint/challenge/",
    )
    with pytest.raises(UnlockerError) as ei:
        fetch("https://www.linkedin.com/in/someone/", use_memory=False)
    reasons = " ".join(why for _, why in ei.value.attempts)
    assert "linkedin-checkpoint" in reasons
    assert "login-wall" not in reasons
    assert "does not sign in again" in ei.value.hint
    assert "login keep" in ei.value.hint
    linkedin.clear_stop()
    _linkedin_curl(monkeypatch, 200, "Your account is temporarily restricted")
    with pytest.raises(UnlockerError) as held:
        fetch(
            "https://www.linkedin.com/in/someone/",
            use_memory=False,
            cookies=[CookieRecord("li_at", "secret", ".www.linkedin.com")],
        )
    stop = linkedin.current_stop()
    assert stop is not None and stop.until is None
    assert stop.reason == "restriction"
    assert linkedin.current_stop(now=stop.since + 10 * 86400) is not None
    assert "login resume" in held.value.hint
    assert "person" in held.value.hint


def test_login_resume_clears_one_linkedin_stop_and_leaves_other_hosts(capsys):
    linkedin.record_stop("restriction")
    rate_limit.record("linkedin.com", "60")
    rate_limit.record("example.test", "60")
    with pytest.raises(SystemExit) as ei:
        with patch("sys.argv", ["searchts", "login", "resume", "linkedin.com"]):
            main()
    assert ei.value.code == 0
    assert linkedin.current_stop() is None
    assert rate_limit.remaining("linkedin.com") == 0
    assert rate_limit.remaining("example.test") > 0
    out = capsys.readouterr().out
    assert "linkedin.com" in out
    with pytest.raises(SystemExit) as bad:
        with patch("sys.argv", ["searchts", "login", "resume", "not a site"]):
            main()
    assert bad.value.code == 2
    assert rate_limit.remaining("example.test") > 0


def test_profile_sections_book_a_linkedin_load_each(monkeypatch):
    _text(monkeypatch)
    calls = {"n": 0}
    real = linkedin.take_load

    def counted(**kwargs):
        calls["n"] += 1
        return real(**kwargs)

    monkeypatch.setattr(linkedin, "take_load", counted)

    def curl(url, **_k):
        return 200, "<p>profile</p>", url, {}

    def stealth(url, timeout=60, progress=None, **_k):
        return 200, "<p>education</p>", url, {}

    _curl(monkeypatch, curl)
    monkeypatch.setattr(unlocker, "_fetch_stealth", stealth)
    monkeypatch.setattr(unlocker, "_fetch_jina", lambda *_a, **_k: (429, "no", _a[0], {}))
    result = fetch(
        "https://www.linkedin.com/in/someone/",
        cookies=[CookieRecord("li_at", "secret", ".www.linkedin.com")],
        use_memory=False,
    )
    assert result.authenticated is True
    # Profile, Experience, Education. The nested section loads must not
    # deadlock on the lock the profile load is still holding.
    assert calls["n"] == 3


def test_a_linkedin_scroll_is_refused_while_a_stop_is_active():
    linkedin.record_stop("checkpoint")
    report, why = scroll.collect_url(
        "https://www.linkedin.com/feed/", want_rows=3,
    )
    assert report is None
    assert why.startswith("linkedin-stop:")
    assert "does not sign in again" in why


def test_a_paced_linkedin_scroll_is_a_note(monkeypatch):
    monkeypatch.setattr(
        scroll, "collect_url",
        lambda *_a, **_k: (None, "linkedin-paced: wait SEARCHTS_LINKEDIN_LOADS_PER_HOUR"),
    )
    monkeypatch.setattr(scroll, "browser_available", lambda: True)
    note, report = unlocker._scroll_feed(
        "https://www.linkedin.com/feed/", 5, knobs.resolve(),
    )
    assert report is None
    assert "SEARCHTS_LINKEDIN_LOADS_PER_HOUR" in note
    assert "stopped before another LinkedIn request" in note


def test_load_windows_sleep_the_minute_and_refuse_the_hour_and_day(monkeypatch):
    monkeypatch.setenv("SEARCHTS_LINKEDIN_LOADS_PER_MINUTE", "5")
    monkeypatch.setenv("SEARCHTS_LINKEDIN_LOADS_PER_HOUR", "100")
    monkeypatch.setenv("SEARCHTS_LINKEDIN_LOADS_PER_DAY", "0")
    assert linkedin.load_limits() == (5, 100, 0)
    clock = {"t": 10_000.0}
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        clock["t"] += seconds

    monkeypatch.setattr(linkedin, "_now", lambda: clock["t"])
    for _ in range(3):
        linkedin.take_load(sleep=sleep, rand=lambda: 0)
    # A higher per-minute cap is allowed: three loads only pay the 20 s gap.
    assert slept == [20, 20]

    monkeypatch.setenv("SEARCHTS_LINKEDIN_LOADS_PER_MINUTE", "1")
    clock["t"] = 20_000.0
    slept.clear()
    linkedin.take_load(sleep=sleep, rand=lambda: 0)
    linkedin.take_load(sleep=sleep, rand=lambda: 0)
    assert slept == [60]

    monkeypatch.setenv("SEARCHTS_LINKEDIN_LOADS_PER_MINUTE", "100")
    monkeypatch.setenv("SEARCHTS_LINKEDIN_LOADS_PER_HOUR", "100")
    linkedin.take_load(now=30_000, sleep=lambda _s: None, rand=lambda: 0)
    monkeypatch.setenv("SEARCHTS_LINKEDIN_LOADS_PER_HOUR", "1")
    with pytest.raises(linkedin.Paced) as hour:
        linkedin.take_load(now=30_010, sleep=lambda _s: None, rand=lambda: 0)
    assert "SEARCHTS_LINKEDIN_LOADS_PER_HOUR" in hour.value.hint

    monkeypatch.setenv("SEARCHTS_LINKEDIN_LOADS_PER_HOUR", "100")
    monkeypatch.setenv("SEARCHTS_LINKEDIN_LOADS_PER_DAY", "1")
    with pytest.raises(linkedin.Paced) as day:
        linkedin.take_load(now=30_020, sleep=lambda _s: None, rand=lambda: 0)
    assert "SEARCHTS_LINKEDIN_LOADS_PER_DAY" in day.value.hint
    assert "0 turns the daily cap off" in day.value.hint

    monkeypatch.setenv("SEARCHTS_LINKEDIN_LOADS_PER_DAY", "0")
    linkedin.take_load(now=40_000, sleep=lambda _s: None, rand=lambda: 0)


def test_the_minute_window_is_slept_so_a_third_load_is_not_refused(monkeypatch):
    monkeypatch.setenv("SEARCHTS_LINKEDIN_LOADS_PER_HOUR", "100")
    monkeypatch.setenv("SEARCHTS_LINKEDIN_LOADS_PER_DAY", "0")
    clock = {"t": 50_000.0}
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        clock["t"] += seconds

    monkeypatch.setattr(linkedin, "_now", lambda: clock["t"])
    linkedin.take_load(sleep=sleep, rand=lambda: 0)
    linkedin.take_load(sleep=sleep, rand=lambda: 0)
    linkedin.take_load(sleep=sleep, rand=lambda: 0)
    assert 20 in slept
    assert any(seconds >= 40 for seconds in slept)


def test_one_linkedin_load_at_a_time_and_a_nested_load_does_not_deadlock():
    started = threading.Event()
    release = threading.Event()
    entered = threading.Event()

    def hold():
        with linkedin.exclusive_load():
            started.set()
            release.wait(3)

    first = threading.Thread(target=hold)
    first.start()
    assert started.wait(3)

    def other():
        with linkedin.exclusive_load():
            entered.set()

    second = threading.Thread(target=other)
    second.start()
    assert not entered.wait(0.4)
    release.set()
    first.join(3)
    second.join(3)
    assert not first.is_alive()
    assert not second.is_alive()
    assert entered.is_set()

    done = threading.Event()

    def nested():
        with linkedin.exclusive_load():
            with linkedin.exclusive_load():
                done.set()

    third = threading.Thread(target=nested)
    third.start()
    third.join(3)
    assert not third.is_alive()
    assert done.is_set()


def test_a_paced_enter_does_not_keep_the_load_lock(monkeypatch):
    monkeypatch.setenv("SEARCHTS_LINKEDIN_LOADS_PER_HOUR", "1")
    monkeypatch.setenv("SEARCHTS_LINKEDIN_LOADS_PER_DAY", "0")
    linkedin.take_load(sleep=lambda _s: None, rand=lambda: 0)
    with pytest.raises(linkedin.Paced):
        with linkedin.exclusive_load():
            pass
    monkeypatch.setenv("SEARCHTS_LINKEDIN_LOADS_PER_HOUR", "100")
    done = threading.Event()

    def run():
        with linkedin.exclusive_load():
            done.set()

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(3)
    assert not thread.is_alive()
    assert done.is_set()


def test_feed_gap_minutes_is_defined_and_not_applied_to_a_page_load(monkeypatch):
    assert linkedin.FEED_GAP_MINUTES == 30
    assert linkedin.feed_gap_minutes() == 30
    monkeypatch.setenv("SEARCHTS_LINKEDIN_FEED_GAP_MINUTES", "45")
    assert linkedin.feed_gap_minutes() == 45
    monkeypatch.setenv("SEARCHTS_LINKEDIN_LOADS_PER_MINUTE", "100")
    monkeypatch.setenv("SEARCHTS_LINKEDIN_LOADS_PER_HOUR", "100")
    monkeypatch.setenv("SEARCHTS_LINKEDIN_LOADS_PER_DAY", "0")
    slept = []
    linkedin.take_load(now=60_000, sleep=slept.append, rand=lambda: 0)
    linkedin.take_load(now=60_000, sleep=slept.append, rand=lambda: 0)
    assert slept == [20]
