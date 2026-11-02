# -*- coding: utf-8 -*-
"""LinkedIn: the login's expiry, the page's own chrome, and the extra sections.

Three things are proven here, all offline (#443):

* a kept LinkedIn login follows ``li_at``, not the one-hour ``__cf_bm``
  tracker, so a good login is not listed, swept or marked expired;
* the reader returns the profile and company content without the page's own
  furniture, and never drops a content line that merely looks like a button;
* a logged-in profile is assembled from its Experience and Education pages,
  and a failed section is a named note rather than a failed read.

Every fixture is synthetic. No test opens a socket or a browser.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest
from conftest import tripwire

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from searchts import linkedin, unlocker
from searchts import login_store as ls
from searchts.session_cookies import (
    CookieRecord,
    _write_owned_store,
    describe_expiry,
    entry_expiry,
    read_owned_store,
    sweep_owned_store,
)
from searchts.unlocker import FetchResult, UnlockerError


@pytest.fixture(autouse=True)
def temp_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(home))
    yield home


def entry_cookie(name, expiry=None, domain=".www.linkedin.com"):
    return {
        "n": name,
        "v": "SECRET-VALUE",
        "d": domain,
        "p": "/",
        "s": True,
        "h": True,
        "expiry": expiry,
    }


def seed(host="linkedin.com", cookies=None, *, browser="chrome"):
    _write_owned_store({
        host: {
            "cookies": cookies if cookies is not None else [entry_cookie("li_at")],
            "browser": browser,
            "expiry_known": True,
            "consent": True,
        }
    })
    return host


# ── which URLs are LinkedIn ─────────────────────────────────────────────────


def test_matches_linkedin_and_its_subdomains_only():
    assert linkedin.matches("https://www.linkedin.com/in/someone/")
    assert linkedin.matches("https://linkedin.com/company/acme/")
    assert linkedin.matches("linkedin.com")
    assert not linkedin.matches("https://linkedin.com.attacker.test/in/x/")
    assert not linkedin.matches("https://notlinkedin.com/in/x/")
    assert not linkedin.matches("https://example.com/in/x/")


def test_is_profile_is_the_main_page_and_not_a_details_page():
    assert linkedin.is_profile("https://www.linkedin.com/in/someone/")
    assert linkedin.is_profile("https://www.linkedin.com/in/someone")
    assert not linkedin.is_profile(
        "https://www.linkedin.com/in/someone/details/experience/"
    )
    assert not linkedin.is_profile("https://www.linkedin.com/company/acme/")
    assert not linkedin.is_profile("https://www.linkedin.com/feed/")


def test_browser_first_only_for_search_results():
    assert linkedin.browser_first(
        "https://www.linkedin.com/search/results/people/?keywords=cto"
    )
    assert not linkedin.browser_first("https://www.linkedin.com/in/someone/")
    assert not linkedin.browser_first("https://www.linkedin.com/company/acme/")
    assert not linkedin.browser_first("https://example.com/search/results/")


def test_detail_urls_keep_the_reads_own_host_and_scheme():
    assert linkedin.detail_urls("https://www.linkedin.com/company/acme/") == []
    got = linkedin.detail_urls("https://www.linkedin.com/in/someone/")
    assert got == [
        ("Experience", "https://www.linkedin.com/in/someone/details/experience/"),
        ("Education", "https://www.linkedin.com/in/someone/details/education/"),
    ]
    assert linkedin.detail_urls("https://linkedin.com/in/someone/")[0][1] == (
        "https://linkedin.com/in/someone/details/experience/"
    )


def test_rate_limit_hint_says_rate_limit_not_expired_login():
    hint = linkedin.rate_limit_hint()
    assert "rate limiting" in hint
    assert "Wait" in hint
    assert "expired" not in hint.lower()


def test_login_check_calls_a_linkedin_429_unknown_not_logged_out():
    now = int(time.time())
    seed(cookies=[entry_cookie("li_at", now + 365 * 86400)])

    def fetch(url, **kwargs):
        raise UnlockerError(url, [("curl_cffi", "http-429")])

    check = ls.check_login("linkedin.com", fetch_fn=fetch)
    assert check.status == "unknown"
    assert check.exit_code == 2
    assert "rate limiting" in check.why
    assert "expired" not in check.why.lower()


# ── chrome ──────────────────────────────────────────────────────────────────

_PROFILE_PAGE = """0 notifications
Try Premium for free
Someone Example
Builds small tools
Berlin, Germany

Enhance profile
[Add section](https://www.linkedin.com/in/someone/edit/intro/)

About
Writes software for a living.

Ad Options
Why am I seeing this ad?
Manage your ad preferences
Hide or report this ad
Submit

Activity
1,234 followers

Select language
English (English)
Deutsch (German)
日本語 (Japanese)

LinkedIn Corporation © 2026
"""


def test_strip_chrome_keeps_the_content_and_drops_the_furniture():
    out = linkedin.strip_chrome(_PROFILE_PAGE)
    for kept in (
        "Someone Example",
        "Builds small tools",
        "Berlin, Germany",
        "About",
        "Writes software for a living.",
        "Activity",
        "1,234 followers",
    ):
        assert kept in out
    for gone in (
        "0 notifications",
        "Try Premium",
        "Enhance profile",
        "Add section",
        "Ad Options",
        "Why am I seeing this ad?",
        "Manage your ad preferences",
        "Select language",
        "English (English)",
        "日本語 (Japanese)",
        "LinkedIn Corporation",
    ):
        assert gone not in out


def test_strip_chrome_leaves_a_post_that_merely_mentions_a_button_word():
    text = (
        "Acme Corp\n\n"
        "We opened a new Resources page today.\n\n"
        "Resources\n\n"
        "Everyone is welcome to use it.\n"
    )
    out = linkedin.strip_chrome(text)
    assert "We opened a new Resources page today." in out
    assert "Resources" in out
    assert "Everyone is welcome to use it." in out


def test_strip_chrome_stops_the_ad_block_at_the_first_unknown_line():
    text = "Ad Options\nWhy am I seeing this ad?\nThis line is not ad chrome.\n"
    out = linkedin.strip_chrome(text)
    assert "Ad Options" not in out
    assert "Why am I seeing this ad?" not in out
    assert "This line is not ad chrome." in out


def test_strip_chrome_is_a_no_op_on_empty_text():
    assert linkedin.strip_chrome("") == ""
    assert linkedin.strip_chrome("Just a post.\n") == "Just a post."


# ── assembly ────────────────────────────────────────────────────────────────


def test_assemble_adds_sections_and_drops_their_own_heading():
    text, notes = linkedin.assemble(
        "Someone Example\nBuilds small tools",
        [
            ("Experience", "Experience\n\nEngineer at Acme\n2020 - 2024", ""),
            ("Education", "Education\n\nBSc, Somewhere\n2016 - 2020", ""),
        ],
    )
    assert notes == []
    assert text.startswith("Someone Example")
    assert "## Experience\n\nEngineer at Acme" in text
    assert "## Education\n\nBSc, Somewhere" in text
    assert text.count("Experience\n\nEngineer") == 1


def test_assemble_names_a_failed_section_and_keeps_the_rest():
    text, notes = linkedin.assemble(
        "Someone Example",
        [
            ("Experience", "Experience\n\nEngineer at Acme", ""),
            ("Education", None, "curl_cffi: http-429"),
        ],
    )
    assert "Engineer at Acme" in text
    assert len(notes) == 1
    assert "Education section could not be read (curl_cffi: http-429)" in notes[0]


def test_assemble_with_no_sections_returns_the_base_unchanged():
    text, notes = linkedin.assemble("Someone Example", [])
    assert text == "Someone Example"
    assert notes == []


# ── expiry follows the login cookie ─────────────────────────────────────────


def test_entry_expiry_follows_li_at_not_the_short_tracker():
    now = int(time.time())
    year = now + 365 * 86400
    entry = {
        "cookies": [
            entry_cookie("li_at", year),
            entry_cookie("__cf_bm", now + 3600),
            entry_cookie("bcookie", now + 86400),
        ]
    }
    at, known = entry_expiry(entry, now, host="linkedin.com")
    assert known is True
    assert at == year
    assert describe_expiry(entry, now, host="linkedin.com").startswith("expires in 36")


def test_entry_expiry_keeps_the_old_answer_without_a_login_cookie():
    now = int(time.time())
    entry = {
        "cookies": [
            entry_cookie("__cf_bm", now + 3600),
            entry_cookie("bcookie", now + 86400),
        ]
    }
    assert entry_expiry(entry, now, host="linkedin.com") == (now + 3600, True)


def test_entry_expiry_calls_a_session_login_cookie_a_session():
    now = int(time.time())
    entry = {"cookies": [entry_cookie("li_at", None), entry_cookie("__cf_bm", now + 3600)]}
    assert entry_expiry(entry, now, host="linkedin.com") == (None, True)
    assert describe_expiry(entry, now, host="linkedin.com") == "session"


def test_entry_expiry_ignores_the_host_hint_on_a_generic_site():
    now = int(time.time())
    entry = {"cookies": [entry_cookie("sid", now + 60), entry_cookie("pref", now + 3600)]}
    assert entry_expiry(entry, now, host="example.com") == (now + 60, True)


def test_login_list_follows_li_at_rather_than_the_one_hour_tracker():
    now = int(time.time())
    seed(cookies=[
        entry_cookie("li_at", now + 365 * 86400),
        entry_cookie("__cf_bm", now + 3600),
    ])
    kept = ls.list_kept()["linkedin.com"]
    assert kept["expiry"].startswith("expires in 36")
    assert kept["expired"] is False
    assert kept["expires_at"] == now + 365 * 86400
    assert ls.refresh_reason("linkedin.com", now=now) is None


def test_a_dead_tracker_is_swept_and_the_login_is_not_marked_expired():
    now = int(time.time())
    seed(cookies=[
        entry_cookie("li_at", now + 365 * 86400),
        entry_cookie("__cf_bm", now - 60),
    ])
    swept = sweep_owned_store(now)
    assert swept.removed == 1
    entry = read_owned_store()["linkedin.com"]
    assert [c["n"] for c in entry["cookies"]] == ["li_at"]
    assert not entry.get("expired")
    assert len(read_owned_store()["linkedin.com"]["cookies"]) == 1
    assert ls.list_kept()["linkedin.com"]["expired"] is False
    assert ls.refresh_reason("linkedin.com", now=now) is None


# ── the ladder's LinkedIn behaviour ─────────────────────────────────────────


def _set_curl(monkeypatch, status, body):
    monkeypatch.setattr(
        unlocker, "_fetch_curl_cffi",
        lambda url, timeout=30, _s=status, _b=body, **k: (_s, _b, url, {}),
    )


def _no_stealth(monkeypatch):
    monkeypatch.setattr(unlocker, "_fetch_stealth", tripwire("stealth must not run"))
    monkeypatch.setattr(unlocker, "_fetch_jina", tripwire("jina must not run"))


def _no_sleep(monkeypatch):
    monkeypatch.setattr(unlocker.time, "sleep", lambda _s: None)


def test_a_linkedin_429_stops_the_ladder_and_says_rate_limit(monkeypatch):
    _set_curl(monkeypatch, 429, "Too Many Requests")
    _no_stealth(monkeypatch)
    with pytest.raises(UnlockerError) as ei:
        unlocker.fetch("https://www.linkedin.com/in/someone/", use_memory=False)
    assert ei.value.attempts == [("curl_cffi", "http-429")]
    assert "rate limiting" in ei.value.hint
    assert "expired" not in str(ei.value).lower()


def test_linkedin_search_asks_the_browser_before_the_direct_request(monkeypatch):
    monkeypatch.setattr(unlocker, "html_to_text", lambda body, url=None: body)
    monkeypatch.setattr(
        unlocker, "_fetch_curl_cffi", tripwire("curl must not run for search")
    )
    monkeypatch.setattr(
        unlocker, "_fetch_stealth",
        lambda url, timeout=60, progress=None, **k: (200, "Search result " * 80, url, {}),
    )
    r = unlocker.fetch(
        "https://www.linkedin.com/search/results/people/?keywords=cto",
        use_memory=False,
    )
    assert r.backend == "stealth-browser"
    assert "Search result" in r.text


def _stub_profile(monkeypatch, body=_PROFILE_PAGE):
    monkeypatch.setattr(unlocker, "html_to_text", lambda html, url=None: html)
    # A real profile is far longer than the 500-char thin gate; the filler is
    # what keeps this a clean win instead of an escalation.
    _set_curl(monkeypatch, 200, body + "\n\n" + "Synthetic filler line. " * 40)
    _no_stealth(monkeypatch)
    _no_sleep(monkeypatch)


def test_a_logged_in_profile_is_assembled_from_its_sections(monkeypatch):
    _stub_profile(monkeypatch)
    calls = []

    def section(url, **kwargs):
        calls.append((url, kwargs))
        label = "Experience" if "experience" in url else "Education"
        return FetchResult("curl_cffi", f"{label}\n\nSynthetic {label} line", 200)

    monkeypatch.setattr(unlocker, "_read_linkedin_section", section)
    r = unlocker.fetch(
        "https://www.linkedin.com/in/someone/",
        cookies=[CookieRecord("li_at", "SECRET-VALUE", ".www.linkedin.com")],
        use_memory=False,
    )
    assert r.authenticated is True
    assert [u for u, _ in calls] == [
        "https://www.linkedin.com/in/someone/details/experience/",
        "https://www.linkedin.com/in/someone/details/education/",
    ]
    assert all(k["details"] is False for _, k in calls)
    assert all(k["cookies"] for _, k in calls)
    assert "## Experience\n\nSynthetic Experience line" in r.text
    assert "## Education\n\nSynthetic Education line" in r.text
    assert "Try Premium" not in r.text
    assert "SECRET-VALUE" not in r.text


def test_a_profile_read_can_skip_the_extra_requests(monkeypatch):
    _stub_profile(monkeypatch)
    monkeypatch.setattr(
        unlocker, "_read_linkedin_section", tripwire("details=False must not fetch")
    )
    r = unlocker.fetch(
        "https://www.linkedin.com/in/someone/",
        cookies=[CookieRecord("li_at", "SECRET-VALUE", ".www.linkedin.com")],
        use_memory=False,
        details=False,
    )
    assert "## Experience" not in r.text
    assert "Someone Example" in r.text


def test_an_anonymous_profile_read_fetches_no_sections(monkeypatch):
    _stub_profile(monkeypatch)
    monkeypatch.setattr(
        unlocker, "_read_linkedin_section", tripwire("anonymous read must not fetch details")
    )
    r = unlocker.fetch("https://www.linkedin.com/in/someone/", use_memory=False)
    assert r.authenticated is False
    assert "## Experience" not in r.text


def test_a_failed_section_is_a_note_not_a_failed_read(monkeypatch):
    _stub_profile(monkeypatch)

    def section(url, **kwargs):
        if "experience" in url:
            return FetchResult("curl_cffi", "Experience\n\nSynthetic line", 200)
        raise UnlockerError(url, [("curl_cffi", "http-429")])

    monkeypatch.setattr(unlocker, "_read_linkedin_section", section)
    r = unlocker.fetch(
        "https://www.linkedin.com/in/someone/",
        cookies=[CookieRecord("li_at", "SECRET-VALUE", ".www.linkedin.com")],
        use_memory=False,
    )
    assert "Synthetic line" in r.text
    assert "the Education section could not be read" in r.text
    assert "http-429" in r.text
