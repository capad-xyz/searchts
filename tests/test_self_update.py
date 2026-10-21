# -*- coding: utf-8 -*-
"""searchts update / searchts upgrade. Plans are pure. Installers are not run."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from searchts import self_update as su
from searchts.cli import _run as cli_run


def _env(kind, python="/usr/bin/python"):
    return SimpleNamespace(kind=kind, python=python, label=kind)


def _tools(monkeypatch, pipx="/usr/bin/pipx", uv="/usr/bin/uv", git="/usr/bin/git"):
    found = {"pipx": pipx, "uv": uv, "git": git}

    def tool_path(name):
        return found.get(name)

    monkeypatch.setattr(su, "tool_path", tool_path)


def _runtime(monkeypatch, *, kind="pipx", local="1.0.0", pypi="2.0.0", installed="2.0.0", code=0):
    """Stub every side effect of cmd_update. Returns the installer calls."""
    monkeypatch.setattr(su, "detect_env", lambda: _env(kind))
    monkeypatch.setattr(su, "installed_extras", lambda: ())
    monkeypatch.setattr(su, "fetch_pypi_version", lambda timeout=15.0: pypi)
    monkeypatch.setattr(su, "inspect_repo", lambda: su.RepoState(None, False, "not a checkout"))
    monkeypatch.setattr(su, "other_lock_pids", lambda: [])
    monkeypatch.setattr(su, "path_launchers", lambda: [])
    monkeypatch.setattr(su, "primary_launcher", lambda *a, **k: Path("/usr/bin/searchts"))
    monkeypatch.setattr(su, "read_installed_version", lambda launcher: installed)
    monkeypatch.setattr("searchts.__version__", local)
    calls = []

    def run_step(argv, cwd=None):
        calls.append((tuple(argv), cwd))
        return code, ""

    monkeypatch.setattr(su, "run_step", run_step)
    return calls


def test_pip_spec_keeps_known_extras_in_order():
    assert su.pip_spec(()) == "searchts"
    assert su.pip_spec(["browser", "mcp", "nope"]) == "searchts[mcp,browser]"
    assert su.editable_spec(["mcp"]) == ".[mcp]"
    assert su.editable_spec(()) == "."


def test_format_argv_quotes_spaces():
    assert su.format_argv(["C:\\Program Files\\python.exe", "-m", "pip"]) == (
        '"C:\\Program Files\\python.exe" -m pip'
    )


def test_pipx_plan_upgrades_injected_packages():
    plan = su.build_plan(
        kind="pipx",
        force=False,
        extras=(),
        python="/usr/bin/python",
        pipx="/usr/bin/pipx",
        uv=None,
        git=None,
        repo=None,
    )
    assert plan.steps[0].argv == ("/usr/bin/pipx", "upgrade", "searchts", "--include-injected")


def test_pipx_force_reinstalls():
    plan = su.build_plan(
        kind="pipx",
        force=True,
        extras=(),
        python="/usr/bin/python",
        pipx="/usr/bin/pipx",
        uv=None,
        git=None,
        repo=None,
    )
    assert plan.steps[0].argv[-1] == "--force"
    assert "--include-injected" in plan.steps[0].argv


def test_pipx_missing_tool_refuses():
    plan = su.build_plan(
        kind="pipx",
        force=False,
        extras=(),
        python="/usr/bin/python",
        pipx=None,
        uv=None,
        git=None,
        repo=None,
    )
    assert isinstance(plan, su.UpdateRefusal)
    assert "pipx upgrade searchts --include-injected" in plan.message


def test_uv_tool_plan():
    plan = su.build_plan(
        kind="uv_tool",
        force=True,
        extras=(),
        python="/usr/bin/python",
        pipx=None,
        uv="/usr/bin/uv",
        git=None,
        repo=None,
    )
    assert plan.steps[0].argv == ("/usr/bin/uv", "tool", "upgrade", "searchts", "--reinstall")


def test_uvx_plan_clears_the_cache_even_while_in_use():
    plan = su.build_plan(
        kind="ephemeral_uvx",
        force=False,
        extras=("mcp",),
        python="/tmp/archive-v0/bin/python",
        pipx=None,
        uv="/usr/bin/uv",
        git=None,
        repo=None,
    )
    assert plan.steps[0].argv == ("/usr/bin/uv", "cache", "clean", "--force", "searchts")


def test_venv_plan_uses_that_interpreter_and_extras():
    plan = su.build_plan(
        kind="venv",
        force=False,
        extras=("browser", "mcp"),
        python="/venv/bin/python",
        pipx=None,
        uv=None,
        git=None,
        repo=None,
    )
    assert plan.steps[0].argv == (
        "/venv/bin/python",
        "-m",
        "pip",
        "install",
        "-U",
        "searchts[mcp,browser]",
    )


def test_editable_dirty_checkout_is_not_updated():
    plan = su.build_plan(
        kind="editable",
        force=False,
        extras=(),
        python="/usr/bin/python",
        pipx=None,
        uv=None,
        git="/usr/bin/git",
        repo=su.RepoState("/src/searchts", dirty=True),
    )
    assert isinstance(plan, su.UpdateRefusal)
    assert "uncommitted" in plan.message
    assert "pull" in plan.message


def test_editable_clean_checkout_pulls_then_reinstalls():
    plan = su.build_plan(
        kind="editable",
        force=False,
        extras=("mcp",),
        python="/usr/bin/python",
        pipx=None,
        uv=None,
        git="/usr/bin/git",
        repo=su.RepoState("/src/searchts", dirty=False),
    )
    assert plan.steps[0].argv == ("/usr/bin/git", "-C", "/src/searchts", "pull", "--ff-only")
    assert plan.steps[1].argv[-2:] == ("-e", ".[mcp]")
    assert plan.steps[1].cwd == "/src/searchts"


def test_update_runs_the_pipx_command_and_reports_the_new_version(monkeypatch, capsys):
    calls = _runtime(monkeypatch)
    _tools(monkeypatch)
    assert su.cmd_update() == 0
    assert calls == [(("/usr/bin/pipx", "upgrade", "searchts", "--include-injected"), None)]
    captured = capsys.readouterr()
    assert "updating searchts" in captured.err
    assert "searchts v2.0.0" in captured.out
    assert "injected" in captured.out


def test_dry_run_prints_the_command_and_does_not_run_it(monkeypatch, capsys):
    calls = _runtime(monkeypatch)
    _tools(monkeypatch)
    assert su.cmd_update(dry_run=True) == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "pipx upgrade searchts --include-injected" in out
    assert "Dry run. Nothing was changed." in out


def test_upgrade_alias_is_the_same_function(monkeypatch, capsys):
    calls = _runtime(monkeypatch, kind="uv_tool")
    _tools(monkeypatch)
    assert su.cmd_update(force=True) == 0
    assert calls[0][0] == ("/usr/bin/uv", "tool", "upgrade", "searchts", "--reinstall")


def test_same_version_still_upgrades_injected_packages(monkeypatch, capsys):
    """A matching version is not a reason to skip. Injected packages may be older."""
    calls = _runtime(monkeypatch, local="2.0.0", pypi="2.0.0", installed="2.0.0")
    _tools(monkeypatch)
    assert su.cmd_update() == 0
    assert calls == [(("/usr/bin/pipx", "upgrade", "searchts", "--include-injected"), None)]
    assert "searchts v2.0.0" in capsys.readouterr().out


def test_does_not_downgrade_when_local_is_ahead(monkeypatch, capsys):
    calls = _runtime(monkeypatch, local="3.0.0", pypi="2.0.0")
    _tools(monkeypatch)
    assert su.cmd_update(force=True) == 0
    assert calls == []
    assert "Not downgrading" in capsys.readouterr().out


def test_failed_installer_does_not_claim_success(monkeypatch, capsys):
    calls = _runtime(monkeypatch, code=1)
    _tools(monkeypatch)
    assert su.cmd_update() == 1
    assert len(calls) == 1
    assert "Update did not finish." in capsys.readouterr().out


def test_second_step_does_not_run_after_the_first_fails(monkeypatch, capsys):
    calls = _runtime(monkeypatch, kind="editable", code=1)
    _tools(monkeypatch)
    monkeypatch.setattr(su, "inspect_repo", lambda: su.RepoState("/src/searchts", dirty=False))
    monkeypatch.setattr(su, "installed_extras", lambda: ("mcp",))
    assert su.cmd_update() == 1
    assert len(calls) == 1
    assert calls[0][0][0].endswith("git") or calls[0][0][1] == "-C"


def test_open_exes_are_named_and_not_killed(monkeypatch, capsys):
    _runtime(monkeypatch)
    _tools(monkeypatch)
    monkeypatch.setattr(su, "other_lock_pids", lambda: [36744, 29700])
    assert su.cmd_update() == 0
    out = capsys.readouterr().out
    assert "PID 36744, PID 29700 still have" in out
    assert "does not kill them" in out


def test_stale_version_after_installer_is_a_failure(monkeypatch, capsys):
    _runtime(monkeypatch, pypi="2.0.0", installed="1.0.0")
    _tools(monkeypatch)
    monkeypatch.setattr(su, "other_lock_pids", lambda: [4242])
    assert su.cmd_update() == 1
    out = capsys.readouterr().out
    assert "did not take effect" in out
    assert "PID 4242" in out
    assert "does not kill" in out


def test_externally_managed_pip_names_pipx(monkeypatch, capsys):
    _runtime(monkeypatch, kind="pip", code=1)
    _tools(monkeypatch)

    def run_step(argv, cwd=None):
        return 1, "error: externally-managed-environment"

    monkeypatch.setattr(su, "run_step", run_step)
    assert su.cmd_update() == 1
    out = capsys.readouterr().out
    assert "externally managed" in out
    assert "pipx install" in out


def test_uvx_success_does_not_require_a_new_launcher(monkeypatch, capsys):
    calls = _runtime(monkeypatch, kind="ephemeral_uvx", installed=None)
    _tools(monkeypatch)
    assert su.cmd_update() == 0
    assert calls[0][0][-3:] == ("clean", "--force", "searchts")
    assert "next uvx run" in capsys.readouterr().out


def test_other_path_copy_is_named_and_not_upgraded():
    primary = Path("/home/a/.local/bin/searchts")
    other = Path("/usr/local/bin/searchts")
    notes = su.other_copy_notes(
        [(primary, "2.0.0"), (other, "1.0.0")],
        primary,
        "2.0.0",
    )
    assert len(notes) == 2
    assert "v1.0.0" in notes[0]
    assert "v2.0.0" not in notes[0]
    assert "copy that is running" in notes[1]


def test_park_and_restore_round_trip(tmp_path):
    exe = tmp_path / "searchts.exe"
    exe.write_text("old", encoding="utf-8")
    parked = su.park_files([exe], pid=99)
    assert parked
    assert not exe.exists()
    parked_path, original = parked[0]
    assert parked_path.exists()
    assert su.settle_parked(parked) == []
    assert exe.read_text(encoding="utf-8") == "old"
    assert not parked_path.exists()


def test_parked_copy_is_removed_once_the_new_file_is_in_place(tmp_path):
    exe = tmp_path / "searchts.exe"
    exe.write_text("old", encoding="utf-8")
    parked = su.park_files([exe], pid=7)
    exe.write_text("new", encoding="utf-8")
    assert su.settle_parked(parked) == []
    assert exe.read_text(encoding="utf-8") == "new"


def test_windows_lock_refuses_without_running_the_installer(monkeypatch, tmp_path, capsys):
    exe = tmp_path / "searchts.exe"
    exe.write_text("locked", encoding="utf-8")
    calls = _runtime(monkeypatch)
    _tools(monkeypatch)
    monkeypatch.setattr(su.sys, "platform", "win32")
    monkeypatch.setattr(su, "process_image", lambda: exe)
    monkeypatch.setattr(su, "launcher_candidates", lambda *a, **k: [exe])
    monkeypatch.setattr(su, "park_files", lambda paths, pid=None: [])
    monkeypatch.setattr(su, "other_lock_pids", lambda: [4242])
    assert su.cmd_update() == 2
    assert calls == []
    out = capsys.readouterr().out
    assert "does not kill" in out
    assert "PID 4242" in out
    assert "pipx upgrade searchts --include-injected" in out
    assert exe.read_text(encoding="utf-8") == "locked"


def test_run_step_refuses_a_real_installer_under_pytest():
    with pytest.raises(RuntimeError, match="refusing to run an installer"):
        su.run_step(["searchts", "--version"], None)


def test_launcher_candidates_are_empty_under_pytest():
    assert su.launcher_candidates("pipx", sys.executable) == []


def test_launcher_candidates_include_the_shim_and_the_venv_script(tmp_path, monkeypatch):
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    (scripts / "python.exe").write_text("py", encoding="utf-8")
    venv_exe = scripts / "searchts.exe"
    venv_exe.write_text("venv", encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    shim = bindir / "searchts.exe"
    shim.write_text("shim", encoding="utf-8")
    monkeypatch.setattr(su, "process_image", lambda: None)
    found = su._launcher_candidates(
        "pipx",
        str(scripts / "python.exe"),
        {"PIPX_BIN_DIR": str(bindir)},
    )
    resolved = {path.resolve() for path in found}
    assert venv_exe.resolve() in resolved
    assert shim.resolve() in resolved


def test_installed_extras_follow_what_is_importable(monkeypatch):
    present = {"mcp", "patchright"}

    def has(name):
        return name in present

    monkeypatch.setattr(su, "_has_distribution", has)
    assert su.installed_extras() == ("mcp", "browser")


def test_help_lists_update_and_upgrade(monkeypatch, capsys):
    monkeypatch.setattr(
        "searchts.integrations.memory_rule.refresh_known_rules",
        lambda *a, **k: [],
    )
    monkeypatch.setattr("searchts.config.load_dotenv_if_available", lambda: None)
    monkeypatch.setattr(sys, "argv", ["searchts", "--help"])
    with pytest.raises(SystemExit) as exc:
        cli_run()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "update" in out
    assert "upgrade" in out


class _PypiBody:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status
        self.limit = None

    def read(self, n=-1):
        self.limit = n
        if n is None or n < 0:
            return self.payload
        return self.payload[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_pypi(monkeypatch, payload, status=200):
    body = _PypiBody(payload, status)

    def urlopen(req, timeout=15):
        return body

    monkeypatch.setattr(su.urllib.request, "urlopen", urlopen)
    return body


def test_pypi_version_reads_at_most_one_mib(monkeypatch):
    body = _patch_pypi(monkeypatch, b'{"info": {"version": " 9.9.9 "}}')
    assert su.fetch_pypi_version() == "9.9.9"
    assert body.limit == su._PYPI_MAX_BYTES + 1


def test_pypi_version_rejects_a_body_past_one_mib(monkeypatch):
    raw = b'{"info":{"version":"9.9.9"}}' + (b" " * (su._PYPI_MAX_BYTES + 1))
    _patch_pypi(monkeypatch, raw)
    assert su.fetch_pypi_version() is None


def test_pypi_version_accepts_a_body_at_the_cap(monkeypatch):
    prefix = b'{"info":{"version":"1.2.3","pad":"'
    suffix = b'"}}'
    raw = prefix + (b"a" * (su._PYPI_MAX_BYTES - len(prefix) - len(suffix))) + suffix
    assert len(raw) == su._PYPI_MAX_BYTES
    _patch_pypi(monkeypatch, raw)
    assert su.fetch_pypi_version() == "1.2.3"


def test_update_help_mentions_force_and_dry_run(monkeypatch, capsys):
    monkeypatch.setattr(
        "searchts.integrations.memory_rule.refresh_known_rules",
        lambda *a, **k: [],
    )
    monkeypatch.setattr("searchts.config.load_dotenv_if_available", lambda: None)
    monkeypatch.setattr(sys, "argv", ["searchts", "upgrade", "--help"])
    with pytest.raises(SystemExit) as exc:
        cli_run()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--force" in out
    assert "--dry-run" in out
