# -*- coding: utf-8 -*-
"""WebChannel doctor probe must report stealth honestly."""

import builtins
import sys
import types

from searchts.channels.web import WebChannel, _stealth_installed


def test_stealth_probe_warns_when_patchright_missing(monkeypatch):
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
    fake = types.ModuleType("patchright")
    monkeypatch.setitem(sys.modules, "patchright", fake)
    ch = WebChannel()
    status, message = ch.check()
    assert status == "ok"
    assert "stealth-browser" in message
    assert "not installed" not in message


def test_stealth_probe_warns_when_import_raises(monkeypatch):
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


def test_stealth_installed_helper_matches_import():
    assert isinstance(_stealth_installed(), bool)
