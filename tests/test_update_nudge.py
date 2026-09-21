# -*- coding: utf-8 -*-
from pathlib import Path

from searchts import update_nudge as un


def test_is_newer_version():
    assert un.is_newer_version("0.9.0", "0.8.0") is True
    assert un.is_newer_version("0.8.0", "0.9.0") is False
    assert un.is_newer_version("0.9.0", "0.9.0") is False


def test_skips_when_env_set(monkeypatch, capsys):
    monkeypatch.setenv("SEARCHTS_NO_UPDATE_CHECK", "1")
    monkeypatch.setattr(un.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(un.sys.stderr, "isatty", lambda: True)
    un.maybe_nudge(command="doctor")
    assert capsys.readouterr().err == ""


def test_skips_mcp_serve(monkeypatch, capsys):
    monkeypatch.delenv("SEARCHTS_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(un.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(un.sys.stderr, "isatty", lambda: True)
    un.maybe_nudge(command="mcp", mcp_subcommand="serve")
    assert capsys.readouterr().err == ""


def test_skips_pipes(monkeypatch, capsys):
    monkeypatch.delenv("SEARCHTS_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(un.sys.stdout, "isatty", lambda: False)
    monkeypatch.setattr(un.sys.stderr, "isatty", lambda: True)
    un.maybe_nudge(command="doctor")
    assert capsys.readouterr().err == ""


def test_cache_hit_nudge(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("SEARCHTS_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(un.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(un.sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr(un, "cache_path", lambda: tmp_path / "update-check.json")
    monkeypatch.setattr(un, "__version__", "0.8.0")
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("must not hit network on cache hit")

    monkeypatch.setattr(un, "_fetch_latest", boom)
    un._write_cache(tmp_path / "update-check.json", "0.9.0", now=1_000_000)
    un.maybe_nudge(command="doctor", now=1_000_000 + 60)
    err = capsys.readouterr().err
    assert "searchts v0.9.0 is available" in err
    assert "SEARCHTS_NO_UPDATE_CHECK=1" in err
    assert called["n"] == 0


def test_cache_hit_silent_when_current(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("SEARCHTS_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(un.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(un.sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr(un, "cache_path", lambda: tmp_path / "update-check.json")
    monkeypatch.setattr(un, "__version__", "0.9.0")
    monkeypatch.setattr(un, "_fetch_latest", lambda: (_ for _ in ()).throw(AssertionError("no net")))
    un._write_cache(tmp_path / "update-check.json", "0.9.0", now=1_000_000)
    un.maybe_nudge(command="read", now=1_000_000 + 60)
    assert capsys.readouterr().err == ""


def test_stale_cache_fetches(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("SEARCHTS_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(un.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(un.sys.stderr, "isatty", lambda: True)
    path = tmp_path / "update-check.json"
    monkeypatch.setattr(un, "cache_path", lambda: path)
    monkeypatch.setattr(un, "__version__", "0.8.0")
    monkeypatch.setattr(un, "_fetch_latest", lambda timeout=2.0: "0.9.0")
    un._write_cache(path, "0.8.0", now=1_000_000)
    un.maybe_nudge(command="doctor", now=1_000_000 + un.TTL_SECONDS + 1)
    err = capsys.readouterr().err
    assert "v0.9.0 is available" in err
    assert '"latest": "0.9.0"' in path.read_text(encoding="utf-8")


def test_fetch_fail_is_silent(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("SEARCHTS_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(un.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(un.sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr(un, "cache_path", lambda: tmp_path / "missing.json")
    monkeypatch.setattr(un, "_fetch_latest", lambda timeout=2.0: None)
    un.maybe_nudge(command="doctor", now=1.0)
    assert capsys.readouterr().err == ""
