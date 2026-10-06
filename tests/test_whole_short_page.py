"""A short page that is the whole page reads without a browser (F25).

``tests/fixtures/example_com.html`` is example.com as served on 2026-10-01: one
paragraph, a link and ``/s.js``, which adds the same notice in five more
languages once a browser runs it.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from searchts import unlocker
from searchts.unlocker import html_to_text, whole_short_page

FIXTURE = Path(__file__).parent / "fixtures" / "example_com.html"
EXAMPLE = FIXTURE.read_text(encoding="utf-8")

# example.com before its 2026 redesign: no script at all.
EXAMPLE_2025 = (
    '<!DOCTYPE html><html lang="en"><head><title>Example Domain</title></head><body><div>'
    "<h1>Example Domain</h1><p>This domain is for use in documentation examples without "
    "needing permission. Avoid use in operations.</p>"
    '<p><a href="https://iana.org/domains/example">Learn more</a></p></div></body></html>'
)

# What a browser shows after /s.js runs: the same notice, six languages.
RENDERED = EXAMPLE.replace(
    "<a href=",
    "<p>هذا النطاق مُخصص للاستخدام في أمثلة التوثيق دون الحاجة إلى إذن. هذه ليست خدمة، "
    "يُرجى تجنب الاعتماد عليها لأغراض الاختبار والمراقبة.</p>"
    "<p>该域名仅用于文档示例，无需获得许可。这并非一项服务，请勿将其用于测试和监控目的。</p>"
    "<p>L’usage de ce domaine est réservé à des exemples de documentation, sans autorisation "
    "préalable. Il ne s’agit pas d’un service; son utilisation à des fins de test ou de "
    "surveillance est à éviter.</p>"
    "<p>Данный домен предназначен для использования в примерах документации без необходимости "
    "получения предварительного разрешения. Это не сервис; не рекомендуется его использование "
    "для тестирования и мониторинга.</p>"
    "<p>Este dominio está destinado al uso en ejemplos de documentación sin necesidad de "
    "permiso. Esto no es un servicio, evitar utilizarlo para realizar pruebas o monitoreos.</p>"
    "<a href=",
    1,
)

TEASER = "<p>Plan, track and ship your team's work in one place, with boards that update live.</p>"


def _page(body: str, head: str = "") -> str:
    return f"<!doctype html><html><head><title>App</title>{head}</head><body>{body}</body></html>"


def test_example_com_today_is_the_whole_page():
    text = html_to_text(EXAMPLE, "https://example.com/")
    assert len(text) == 156  # the read 0.13.0 called thin
    assert whole_short_page(EXAMPLE, text)


def test_example_com_before_its_redesign_is_the_whole_page():
    assert whole_short_page(EXAMPLE_2025, html_to_text(EXAMPLE_2025, "https://example.com/"))


def test_the_same_teaser_on_a_plain_page_is_whole():
    # Control for the shells below: only their app signals make them thin.
    html = _page(TEASER)
    assert whole_short_page(html, html_to_text(html, "https://app.example/"))


@pytest.mark.parametrize(
    "html",
    [
        _page(TEASER + '<div id="root"></div><script src="/static/js/main.js"></script>'),
        _page(TEASER + "<noscript>You need to enable JavaScript to run this app.</noscript>"),
        _page(TEASER + '<script id="__NEXT_DATA__" type="application/json">{"props":{}}</script>'),
        _page(TEASER + '<script type="module" src="/assets/index-4f2a.js"></script>'),
        _page(TEASER + "".join(f'<script src="/js/{n}.js"></script>' for n in "abc")),
        _page(TEASER + "<script>" + "var a=1;" * 700 + "</script>"),
        _page(TEASER + '<iframe src="https://app.example/embed"></iframe>'),
        _page(TEASER + "<app-root></app-root>"),
    ],
    ids=["empty-root", "noscript", "next-data", "module", "three-scripts", "inline-app",
         "iframe", "app-root"],
)
def test_an_app_shell_stays_thin(html):
    text = html_to_text(html, "https://app.example/")
    assert text  # the teaser is there, so only the shell signals decide
    assert not whole_short_page(html, text)


def test_text_the_extract_left_out_keeps_it_thin():
    left_out = "<p>" + "A second paragraph the extractor never kept. " * 4 + "</p>"
    html = _page(TEASER + left_out)
    assert not whole_short_page(html, "Plan, track and ship your team's work in one place, with boards that update live.")


@pytest.mark.parametrize(
    "html, text",
    [
        (EXAMPLE, "Loading..."),  # a stub, not a page
        ("Plan, track and ship your team's work in one place, with boards that update live.",
         "Plan, track and ship your team's work in one place, with boards that update live."),
        ("", "Plan, track and ship your team's work in one place, with boards that update live."),
    ],
    ids=["stub", "not-html", "no-html"],
)
def test_no_page_to_vouch_for(html, text):
    assert not whole_short_page(html, text)


# ── the ladder ────────────────────────────────────────────────────────────────

URL = "https://example.test/"  # .test never resolves, so the SSRF guard stays offline


@pytest.fixture
def cache(monkeypatch, tmp_path):
    path = tmp_path / "unlocker_cache.json"
    monkeypatch.setattr(unlocker, "_CACHE_PATH", path)
    monkeypatch.setattr(unlocker, "_CACHE_DIR", tmp_path)
    monkeypatch.setenv("SEARCHTS_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("SEARCHTS_NO_MEMORY", raising=False)
    return path


def _rungs(monkeypatch, curl_html, browser_html=None):
    called = []

    def curl(url, timeout=30):
        called.append("curl_cffi")
        return 200, curl_html, url, {}

    def jina(url, timeout=40):
        called.append("Jina Reader")
        raise RuntimeError("HTTP Error 403: Forbidden")

    def stealth(url, timeout=60, progress=None):
        called.append("stealth-browser")
        if browser_html is None:
            raise ModuleNotFoundError("No module named 'patchright'")
        return 200, browser_html, url, {}

    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", curl)
    monkeypatch.setattr(unlocker, "_fetch_jina", jina)
    monkeypatch.setattr(unlocker, "_fetch_stealth", stealth)
    return called


def test_example_com_reads_on_curl_without_the_browser_extra(monkeypatch, cache):
    called = _rungs(monkeypatch, EXAMPLE)  # no browser installed, Jina says 403
    r = unlocker.fetch(URL)
    assert (r.backend, len(r.text)) == ("curl_cffi", 156)
    assert called == ["curl_cffi"]
    assert unlocker.load_memory() == {"example.test": "curl_cffi"}


def test_an_app_shell_still_climbs_the_ladder(monkeypatch, cache):
    shell = _page(TEASER + '<div id="root"></div><script src="/static/js/main.js"></script>')
    called = _rungs(monkeypatch, shell, browser_html=_page("<p>" + "Rendered board. " * 60 + "</p>"))
    r = unlocker.fetch(URL)
    assert r.backend == "stealth-browser"
    assert called == ["curl_cffi", "Jina Reader", "stealth-browser"]


def _pin(path, backend, hours_ago):
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(json.dumps({"example.test": {"backend": backend, "ts": ts}}), encoding="utf-8")
    return ts


def test_a_win_on_the_pinned_rung_does_not_extend_the_pin(monkeypatch, cache):
    ts = _pin(cache, "stealth-browser", hours_ago=2)  # pinned by 0.13.0
    called = _rungs(monkeypatch, EXAMPLE, browser_html=RENDERED)
    r = unlocker.fetch(URL)
    assert r.backend == "stealth-browser" and called == ["stealth-browser"]
    assert json.loads(cache.read_text(encoding="utf-8"))["example.test"]["ts"] == ts


def test_the_old_browser_pin_heals_once_it_expires(monkeypatch, cache):
    _pin(cache, "stealth-browser", hours_ago=25)
    called = _rungs(monkeypatch, EXAMPLE, browser_html=RENDERED)
    r = unlocker.fetch(URL)
    assert (r.backend, called) == ("curl_cffi", ["curl_cffi"])
    assert unlocker.load_memory() == {"example.test": "curl_cffi"}


def test_jina_403_skips_the_next_fetch(monkeypatch):
    import searchts.unlocker as unlocker
    unlocker._jina_spent = False
    called = []

    def fake(url, timeout=40):
        called.append("jina")
        return 403, "", url, {}

    monkeypatch.setattr(unlocker, "_fetch_jina", fake)
    monkeypatch.setattr(unlocker, "_fetch_curl_cffi", lambda url, timeout=30: (200, "<html><body>" + ("word " * 200) + "</body></html>", url, {}))
    monkeypatch.setattr(unlocker, "jina_enabled", lambda: True)
    unlocker.fetch("https://example.org/a", backends=["Jina Reader", "curl_cffi"], use_memory=False)
    assert unlocker._jina_spent is True
    called.clear()
    unlocker.fetch("https://example.org/b", backends=["Jina Reader", "curl_cffi"], use_memory=False)
    assert called == []
    unlocker._jina_spent = False


def test_an_mcp_read_does_not_keep_the_jina_403(monkeypatch):
    """A server stays up. The next tool call gets Jina again. A CLI process does not."""
    import searchts.unlocker as unlocker
    from searchts.integrations.mcp_server import read_url

    unlocker._jina_spent = False
    called = []

    def fake(url, timeout=40):
        called.append(url)
        return 403, "", url, {}

    monkeypatch.setattr(unlocker, "_fetch_jina", fake)
    monkeypatch.setattr(
        unlocker, "_fetch_curl_cffi",
        lambda url, timeout=30: (200, "<html><body>" + ("word " * 200) + "</body></html>", url, {}),
    )
    monkeypatch.setattr(unlocker, "jina_enabled", lambda: True)
    monkeypatch.setattr(unlocker, "_memory_enabled", lambda: False)
    monkeypatch.setattr(unlocker, "DEFAULT_BACKENDS", ["Jina Reader", "curl_cffi"])
    read_url("https://example.org/a")
    read_url("https://example.org/b")
    assert called == ["https://example.org/a", "https://example.org/b"]
    unlocker._jina_spent = False
