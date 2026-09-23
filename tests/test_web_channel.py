# -*- coding: utf-8 -*-
"""WebChannel doctor probe must report stealth and Jina honestly."""

import builtins
import sys
import types

from searchts.channels.web import WebChannel, _jina_probe, _stealth_installed


def test_stealth_probe_warns_when_patchright_missing(monkeypatch):
    monkeypatch.setattr("searchts.channels.web._jina_probe", lambda: ("ok", "ok"))
    real_import = builtins.__import__

    def _block_patchright(name, *args, **kwargs):
        if name == "patchright" or name.startswith("patchright."):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "patchright", raising=False)
    monkeypatch.setattr(builtins, "__import__", _block_patchright)
    ch = WebChannel()
    status, message = ch.check()
    assert status == "warn"
    assert "stealth-browser not installed" in message
    assert "searchts[browser]" in message
    assert ch.active_backend == "curl_cffi"


def test_stealth_probe_ok_when_patchright_present(monkeypatch):
    monkeypatch.setattr("searchts.channels.web._jina_probe", lambda: ("ok", "ok"))
    fake = types.ModuleType("patchright")
    monkeypatch.setitem(sys.modules, "patchright", fake)
    ch = WebChannel()
    status, message = ch.check()
    assert status == "ok"
    assert "stealth-browser" in message
    assert "not installed" not in message


def test_stealth_probe_warns_when_import_raises(monkeypatch):
    monkeypatch.setattr("searchts.channels.web._jina_probe", lambda: ("ok", "ok"))
    real_import = builtins.__import__

    def _boom(name, *args, **kwargs):
        if name == "patchright" or name.startswith("patchright."):
            raise RuntimeError("broken extra")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "patchright", raising=False)
    monkeypatch.setattr(builtins, "__import__", _boom)
    status, message = WebChannel().check()
    assert status == "warn"
    assert "stealth-browser not installed" in message


def test_jina_probe_uses_fetch_jina(monkeypatch):
    seen = {}

    def _ok(url, timeout=40):
        seen["url"] = url
        seen["timeout"] = timeout
        return 200, "ok", url, {}

    monkeypatch.setattr("searchts.unlocker.jina_enabled", lambda: True)
    monkeypatch.setattr("searchts.unlocker._fetch_jina", _ok)
    assert _jina_probe() == ("ok", "ok")
    assert seen == {"url": "https://example.com/", "timeout": 8}
    import urllib.error

    monkeypatch.setattr("searchts.unlocker.jina_enabled", lambda: True)

    def _forbidden(url, timeout=40):
        raise urllib.error.HTTPError(url, 403, "Forbidden", hdrs=None, fp=None)

    monkeypatch.setattr("searchts.unlocker._fetch_jina", _forbidden)
    assert _jina_probe() == ("blocked", "http-403")


def test_doctor_jina_403_is_not_available(monkeypatch):
    import urllib.error

    monkeypatch.setattr("searchts.unlocker.jina_enabled", lambda: True)

    def _forbidden(url, timeout=40):
        raise urllib.error.HTTPError(url, 403, "Forbidden", hdrs=None, fp=None)

    monkeypatch.setattr("searchts.unlocker._fetch_jina", _forbidden)
    monkeypatch.setitem(sys.modules, "patchright", types.ModuleType("patchright"))
    ch = WebChannel()
    status, message = ch.check()
    assert status == "warn"
    assert "Jina Reader not available (http-403)" in message
    assert "Jina Reader available" not in message
    assert "Jina Reader" not in ch.reported_backends
    assert ch.reported_backends == ["curl_cffi", "stealth-browser"]
    assert "Jina Reader" in ch.backends


def test_stealth_installed_helper_matches_import():
    assert isinstance(_stealth_installed(), bool)
