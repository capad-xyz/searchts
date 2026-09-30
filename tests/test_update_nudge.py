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


def test_uvx_kind_points_at_latest(monkeypatch, tmp_path, capsys):
    """uvx reuses a cached build, so 'nothing to upgrade' would be false here."""
    err = _cached_nudge(monkeypatch, tmp_path, capsys, install_kind="uvx", pids=[])
    assert '"searchts[mcp]@latest"' in err
    assert "nothing to upgrade" not in err
    assert "pipx upgrade" not in err
    assert "pip install -U" not in err


def test_uv_tool_kind_upgrade_command(monkeypatch, tmp_path, capsys):
    err = _cached_nudge(monkeypatch, tmp_path, capsys, install_kind="uv_tool", pids=[])
    assert "uv tool upgrade searchts" in err


def test_did_not_take_effect_is_conditional(monkeypatch, tmp_path, capsys):
    """Nobody may have tried to upgrade yet: do not claim an upgrade failed."""
    err = _cached_nudge(monkeypatch, tmp_path, capsys, install_kind="pip", pids=[])
    assert "If you just upgraded, it did not take effect here." in err


def _fake_env(monkeypatch, executable, prefix, env=None):
    import searchts.browser_install as bi

    for key in ("UV_RUNNING", "UVX", "UV_PYTHON", "PIPX_HOME", "VIRTUAL_ENV"):
        monkeypatch.delenv(key, raising=False)
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(bi.sys, "executable", executable)
    monkeypatch.setattr(bi.sys, "prefix", prefix)
    monkeypatch.setattr(bi, "_is_editable_install", lambda: False)


def test_detect_install_kind_pip(monkeypatch):
    _fake_env(monkeypatch, r"C:\Python\python.exe", r"C:\Python")
    assert un.detect_install_kind() == "pip"


def test_detect_install_kind_uv_python_env_does_not_mean_uvx(monkeypatch):
    """UV_PYTHON is a normal uv setting; a pipx install must still say pipx."""
    _fake_env(
        monkeypatch,
        "/home/a/.local/share/pipx/venvs/searchts/bin/python",
        "/home/a/.local/share/pipx/venvs/searchts",
        env={"UV_PYTHON": "3.12", "UV_RUNNING": "1"},
    )
    assert un.detect_install_kind() == "pipx"


def test_detect_install_kind_custom_pipx_home(monkeypatch):
    _fake_env(
        monkeypatch,
        r"C:\Users\a\.pipx\venvs\searchts\Scripts\python.exe",
        r"C:\Users\a\.pipx\venvs\searchts",
        env={"PIPX_HOME": r"C:\Users\a\.pipx"},
    )
    assert un.detect_install_kind() == "pipx"


def test_detect_install_kind_from_uv_tool_path(monkeypatch):
    uv_tools = r"C:\Users\a\AppData\Roaming\uv\tools\searchts"
    _fake_env(monkeypatch, uv_tools + r"\Scripts\python.exe", uv_tools)
    assert un.detect_install_kind() == "uv_tool"


def test_detect_install_kind_from_posix_uvx_cache(monkeypatch):
    cache = "/home/a/.cache/uv/archive-v0/AbC123"
    _fake_env(monkeypatch, cache + "/bin/python", cache)
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
