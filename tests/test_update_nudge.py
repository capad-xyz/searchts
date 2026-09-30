# -*- coding: utf-8 -*-
from searchts import update_nudge as un


def _tty(monkeypatch, stdout_tty=True, stderr_tty=True):
    """Existing tests force both fds to a tty; reuse that shape."""
    monkeypatch.delenv("SEARCHTS_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(un.sys.stdout, "isatty", lambda: stdout_tty)
    monkeypatch.setattr(un.sys.stderr, "isatty", lambda: stderr_tty)


def _no_net(*a, **k):
    raise AssertionError("must not hit network")


def _cached_nudge(monkeypatch, tmp_path, capsys, **kwargs):
    """Run maybe_nudge against a warm cache holding a newer tag."""
    _tty(monkeypatch)
    path = tmp_path / "update-check.json"
    monkeypatch.setattr(un, "cache_path", lambda: path)
    monkeypatch.setattr(un, "__version__", "1.4.2")
    monkeypatch.setattr(un, "_fetch_latest", _no_net)
    un._write_cache(path, "1.5.0", now=1_000_000)
    un.maybe_nudge(command="doctor", now=1_000_000 + 60, **kwargs)
    return capsys.readouterr().err


def test_is_newer_version():
    # Fixture versions, not searchts.__version__. Same pair as test_cli.
    assert un.is_newer_version("1.5.0", "1.4.2") is True
    assert un.is_newer_version("1.4.2", "1.5.0") is False
    assert un.is_newer_version("1.5.0", "1.5.0") is False


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
    monkeypatch.setattr(un, "__version__", "1.4.2")
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("must not hit network on cache hit")

    monkeypatch.setattr(un, "_fetch_latest", boom)
    un._write_cache(tmp_path / "update-check.json", "1.5.0", now=1_000_000)
    un.maybe_nudge(command="doctor", now=1_000_000 + 60, install_kind="pipx", pids=[])
    err = capsys.readouterr().err
    assert "searchts v1.5.0 is available" in err
    assert "SEARCHTS_NO_UPDATE_CHECK=1" in err
    assert "still v1.4.2" in err
    assert "did not take effect" in err
    assert "pipx upgrade searchts" in err
    assert called["n"] == 0


def test_windows_pids_named_and_not_killed(monkeypatch, tmp_path, capsys):
    err = _cached_nudge(monkeypatch, tmp_path, capsys, install_kind="pip", pids=[4242])
    assert "PID 4242" in err
    assert "does not kill" in err
    assert 'pip install -U "searchts[mcp]"' in err


def test_no_pid_line_when_no_pids(monkeypatch, tmp_path, capsys):
    err = _cached_nudge(monkeypatch, tmp_path, capsys, install_kind="pip", pids=[])
    assert "PID" not in err
    assert "searchts.exe" not in err
    assert "did not take effect" in err


def test_uvx_kind_says_nothing_to_upgrade(monkeypatch, tmp_path, capsys):
    err = _cached_nudge(monkeypatch, tmp_path, capsys, install_kind="uvx", pids=[])
    assert "uvx already latest PyPI; nothing to upgrade" in err
    assert "pipx upgrade" not in err
    assert "pip install -U" not in err


def test_detect_install_kind(monkeypatch):
    for key in un.UV_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("PIPX_HOME", raising=False)
    monkeypatch.setattr(un.sys, "executable", r"C:\Python\python.exe")
    monkeypatch.setattr(un.sys, "prefix", r"C:\venv")
    assert un.detect_install_kind() == "pip"

    monkeypatch.setenv("UV_RUNNING", "1")
    assert un.detect_install_kind() == "uvx"

    monkeypatch.delenv("UV_RUNNING")
    monkeypatch.setenv("PIPX_HOME", r"C:\Users\a\pipx")
    assert un.detect_install_kind() == "pipx"


def test_detect_install_kind_from_uvx_path(monkeypatch):
    for key in un.UV_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("PIPX_HOME", raising=False)
    uv_tools = r"C:\Users\a\AppData\Roaming\uv\tools\searchts"
    monkeypatch.setattr(un.sys, "executable", uv_tools + r"\Scripts\python.exe")
    monkeypatch.setattr(un.sys, "prefix", uv_tools)
    assert un.detect_install_kind() == "uvx"


def test_nudge_prints_only_never_installs_or_kills(monkeypatch, tmp_path, capsys):
    _tty(monkeypatch)

    def explode(*a, **k):
        raise AssertionError("F19 must not kill")

    monkeypatch.setattr(un.os, "kill", explode, raising=False)
    err = _cached_nudge(monkeypatch, tmp_path, capsys, install_kind="pipx", pids=[4242])
    assert "mcp stop" not in err
    assert "killed" not in err
    assert "install" not in err.replace("pipx upgrade searchts", "")


def test_cache_hit_silent_when_current(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("SEARCHTS_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(un.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(un.sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr(un, "cache_path", lambda: tmp_path / "update-check.json")
    monkeypatch.setattr(un, "__version__", "1.5.0")
    monkeypatch.setattr(un, "_fetch_latest", lambda: (_ for _ in ()).throw(AssertionError("no net")))
    un._write_cache(tmp_path / "update-check.json", "1.5.0", now=1_000_000)
    un.maybe_nudge(command="read", now=1_000_000 + 60)
    assert capsys.readouterr().err == ""


def test_stale_cache_fetches(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("SEARCHTS_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(un.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(un.sys.stderr, "isatty", lambda: True)
    path = tmp_path / "update-check.json"
    monkeypatch.setattr(un, "cache_path", lambda: path)
    monkeypatch.setattr(un, "__version__", "1.4.2")
    monkeypatch.setattr(un, "_fetch_latest", lambda timeout=2.0: "1.5.0")
    un._write_cache(path, "1.4.2", now=1_000_000)
    un.maybe_nudge(command="doctor", now=1_000_000 + un.TTL_SECONDS + 1)
    err = capsys.readouterr().err
    assert "v1.5.0 is available" in err
    assert '"latest": "1.5.0"' in path.read_text(encoding="utf-8")


def test_fetch_fail_is_silent(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("SEARCHTS_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(un.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(un.sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr(un, "cache_path", lambda: tmp_path / "missing.json")
    monkeypatch.setattr(un, "_fetch_latest", lambda timeout=2.0: None)
    un.maybe_nudge(command="doctor", now=1.0)
    assert capsys.readouterr().err == ""
