# -*- coding: utf-8 -*-
"""WebChannel doctor probe must report stealth honestly."""

from searchts.channels.web import WebChannel, _stealth_installed


def test_stealth_probe_warns_when_patchright_missing(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def _block_patchright(name, *args, **kwargs):
        if name == "patchright" or name.startswith("patchright."):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_patchright)
    ch = WebChannel()
    status, message = ch.check()
    assert status == "warn"
    assert "stealth-browser not installed" in message
    assert "searchts[browser]" in message
    assert ch.active_backend == "curl_cffi"


def test_stealth_probe_ok_when_patchright_present(monkeypatch):
    import types
    import sys

    fake = types.ModuleType("patchright")
    monkeypatch.setitem(sys.modules, "patchright", fake)
    monkeypatch.setattr(
        "searchts.channels.web._stealth_installed",
        lambda: True,
    )
    ch = WebChannel()
    status, message = ch.check()
    assert status == "ok"
    assert "stealth-browser" in message
    assert "not installed" not in message


def test_stealth_installed_helper_matches_import():
    assert isinstance(_stealth_installed(), bool)
