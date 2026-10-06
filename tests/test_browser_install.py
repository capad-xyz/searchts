# -*- coding: utf-8 -*-
"""F22: searchts install --browser (mocked; no live Chromium download)."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

import searchts.browser_install as bi
from searchts.cli import main


def _ok(cmd):
    return subprocess.CompletedProcess(list(cmd), 0, stdout="ok", stderr="")


def _fail(cmd, code=1, err="boom"):
    return subprocess.CompletedProcess(list(cmd), code, stdout="", stderr=err)


class TestDetectCliEnv:
    def test_uv_python_env_does_not_force_ephemeral_uvx(self):
        """UV_PYTHON alone must not refuse; pipx prefix wins."""
        env = bi.detect_cli_env(
            environ={"UV_PYTHON": "3.12", "UVX": "1"},
            executable="/home/u/.local/pipx/venvs/searchts/bin/python",
            prefix="/home/u/.local/pipx/venvs/searchts",
            editable=False,
        )
        assert env.kind == "pipx"

    def test_ephemeral_uvx_archive_path(self):
        env = bi.detect_cli_env(
            environ={},
            executable="/home/u/.cache/uv/archive-v0/abc/bin/python",
            prefix="/home/u/.cache/uv/archive-v0/abc",
            editable=False,
        )
        assert env.kind == "ephemeral_uvx"

    def test_uv_tool_persistent(self):
        env = bi.detect_cli_env(
            environ={},
            executable="/home/u/.local/share/uv/tools/searchts/bin/python",
            prefix="/home/u/.local/share/uv/tools/searchts",
            editable=False,
        )
        assert env.kind == "uv_tool"
        assert "uv tool" in env.label

    def test_pipx(self):
        env = bi.detect_cli_env(
            environ={},
            executable="/home/u/.local/pipx/venvs/searchts/bin/python",
            prefix="/home/u/.local/pipx/venvs/searchts",
            editable=False,
        )
        assert env.kind == "pipx"

    def test_pipx_home_alone_with_venv_is_venv(self):
        """PIPX_HOME must not force pipx when prefix is a normal venv."""
        env = bi.detect_cli_env(
            environ={"PIPX_HOME": "/opt/pipx", "VIRTUAL_ENV": "/repo/.venv"},
            executable="/repo/.venv/bin/python",
            prefix="/repo/.venv",
            editable=False,
        )
        assert env.kind == "venv"

    def test_custom_pipx_home_posix(self):
        """A custom PIPX_HOME like ~/.pipx still counts as pipx (location, not flag)."""
        env = bi.detect_cli_env(
            environ={"PIPX_HOME": "/home/u/.pipx"},
            executable="/home/u/.pipx/venvs/searchts/bin/python",
            prefix="/home/u/.pipx/venvs/searchts",
            editable=False,
        )
        assert env.kind == "pipx"

    def test_custom_pipx_home_windows(self):
        env = bi.detect_cli_env(
            environ={"PIPX_HOME": "C:\\Users\\u\\.pipx"},
            executable="C:\\Users\\u\\.pipx\\venvs\\searchts\\Scripts\\python.exe",
            prefix="C:\\Users\\u\\.pipx\\venvs\\searchts",
            editable=False,
        )
        assert env.kind == "pipx"

    def test_editable(self):
        env = bi.detect_cli_env(
            environ={},
            executable="/repo/.venv/bin/python",
            prefix="/repo/.venv",
            editable=True,
        )
        assert env.kind == "editable"

    def test_venv(self):
        env = bi.detect_cli_env(
            environ={"VIRTUAL_ENV": "/repo/.venv"},
            executable="/repo/.venv/bin/python",
            prefix="/repo/.venv",
            editable=False,
        )
        assert env.kind == "venv"

    def test_pip_fallback(self):
        env = bi.detect_cli_env(
            environ={},
            executable="/usr/bin/python",
            prefix="/usr",
            editable=False,
        )
        assert env.kind == "pip"


class TestInstallBrowser:
    def test_uvx_without_patchright_hints_uvx_from(self, monkeypatch, capsys):
        env = bi.CliEnv("ephemeral_uvx", "ephemeral uvx", "/tmp/archive-v0/py")
        monkeypatch.setattr(bi, "_patchright_importable", lambda: False)
        code = bi.install_browser(cli_env=env, runner=_ok)
        assert code == 2
        err = capsys.readouterr().err
        assert 'uvx --from "searchts[mcp,browser]@latest" searchts install --browser' in err
        # The everyday commands need the extra too, or later runs have no stealth tier.
        assert 'uvx --from "searchts[mcp,browser]" searchts mcp serve' in err

    def test_uvx_with_patchright_only_chromium(self, monkeypatch, capsys):
        env = bi.CliEnv("ephemeral_uvx", "ephemeral uvx", "/tmp/archive-v0/py")
        monkeypatch.setattr(bi, "_patchright_importable", lambda: True)
        monkeypatch.setattr(
            bi, "stealth_status", lambda: (True, "stealth installed: ok")
        )
        calls = []

        def runner(cmd):
            calls.append(list(cmd))
            return _ok(cmd)

        code = bi.install_browser(cli_env=env, runner=runner)
        assert code == 0
        assert len(calls) == 1
        assert calls[0] == ["/tmp/archive-v0/py", "-m", "patchright", "install", "chromium"]
        captured = capsys.readouterr()
        assert "downloading Chromium" in captured.err
        assert "checking stealth" in captured.err
        assert "stealth installed" in captured.out
        assert 'keep "browser" in your --from spec' in captured.err

    def test_dry_run_prints_commands(self, capsys, monkeypatch):
        env = bi.CliEnv("venv", "venv (/tmp/v)", "/tmp/v/bin/python")
        monkeypatch.setattr(bi, "browser_extra_requirements", lambda: ["patchright>=1.50"])
        calls = []

        def runner(cmd):
            calls.append(list(cmd))
            return _ok(cmd)

        code = bi.install_browser(dry_run=True, cli_env=env, runner=runner)
        assert code == 0
        assert calls == []
        err = capsys.readouterr().err
        assert "dry-run" in err
        assert "pip install patchright>=1.50" in err
        assert "searchts[browser]" not in err
        assert "patchright" in err
        assert "chromium" in err

    def test_venv_runs_pip_then_patchright(self, capsys, monkeypatch):
        env = bi.CliEnv("venv", "venv (/tmp/v)", "/tmp/v/bin/python")
        calls = []

        def runner(cmd):
            calls.append(list(cmd))
            return _ok(cmd)

        monkeypatch.setattr(bi, "stealth_status", lambda: (True, "stealth installed: ok"))
        monkeypatch.setattr(bi, "browser_extra_requirements", lambda: ["patchright>=1.50"])
        code = bi.install_browser(cli_env=env, runner=runner)
        assert code == 0
        assert calls[0] == ["/tmp/v/bin/python", "-m", "pip", "install", "patchright>=1.50"]
        assert calls[1] == ["/tmp/v/bin/python", "-m", "patchright", "install", "chromium"]
        captured = capsys.readouterr()
        assert "installing [browser] extra" in captured.err
        assert "downloading Chromium" in captured.err
        assert "checking stealth" in captured.err

    def test_success_prints_stealth_installed(self, capsys, monkeypatch):
        env = bi.CliEnv("venv", "venv (/tmp/v)", "/tmp/v/bin/python")
        monkeypatch.setattr(
            bi, "stealth_status", lambda: (True, "stealth installed: patchright importable")
        )
        code = bi.install_browser(cli_env=env, runner=_ok)
        assert code == 0
        captured = capsys.readouterr()
        assert "stealth installed" in captured.out
        assert "doctor stays read-only" in captured.out

    def test_pip_failure_returns_1(self, capsys):
        env = bi.CliEnv("venv", "venv (/tmp/v)", "/tmp/v/bin/python")

        def runner(cmd):
            if "pip" in cmd:
                return _fail(cmd, err="no network")
            return _ok(cmd)

        code = bi.install_browser(cli_env=env, runner=runner)
        assert code == 1
        assert "failed to install" in capsys.readouterr().err

    def test_chromium_failure_returns_1(self, capsys, monkeypatch):
        env = bi.CliEnv("venv", "venv (/tmp/v)", "/tmp/v/bin/python")

        def runner(cmd):
            if "patchright" in cmd:
                return _fail(cmd, err="download failed")
            return _ok(cmd)

        code = bi.install_browser(cli_env=env, runner=runner)
        assert code == 1
        assert "chromium failed" in capsys.readouterr().err

    def test_pipx_injects_metadata_reqs(self, monkeypatch):
        env = bi.CliEnv("pipx", "pipx env", "/opt/pipx/venvs/searchts/bin/python")
        monkeypatch.setattr(
            bi.shutil, "which", lambda name: "/usr/bin/pipx" if name == "pipx" else None
        )
        monkeypatch.setattr(bi, "browser_extra_requirements", lambda: ["patchright>=1.50"])
        calls = []

        def runner(cmd):
            calls.append(list(cmd))
            return _ok(cmd)

        monkeypatch.setattr(bi, "stealth_status", lambda: (True, "stealth installed"))
        assert bi.install_browser(cli_env=env, runner=runner) == 0
        assert calls[0] == ["/usr/bin/pipx", "inject", "searchts", "patchright>=1.50"]

    def test_pipx_without_pipx_on_path_notes_untracked(self, monkeypatch, capsys):
        env = bi.CliEnv("pipx", "pipx env", "/opt/pipx/venvs/searchts/bin/python")
        monkeypatch.setattr(bi.shutil, "which", lambda name: None)
        monkeypatch.setattr(bi, "browser_extra_requirements", lambda: ["patchright>=1.50"])
        monkeypatch.setattr(bi, "stealth_status", lambda: (True, "stealth installed"))
        calls = []

        def runner(cmd):
            calls.append(list(cmd))
            return _ok(cmd)

        assert bi.install_browser(cli_env=env, runner=runner) == 0
        assert calls[0] == [
            "/opt/pipx/venvs/searchts/bin/python",
            "-m",
            "pip",
            "install",
            "patchright>=1.50",
        ]
        assert "pipx will not track them" in capsys.readouterr().err

    def test_uv_tool_with_patchright_only_runs_chromium(self, monkeypatch, capsys):
        env = bi.CliEnv(
            "uv_tool",
            "uv tool env",
            "/home/u/.local/share/uv/tools/searchts/bin/python",
        )
        monkeypatch.setattr(bi, "_patchright_importable", lambda: True)
        monkeypatch.setattr(bi, "stealth_status", lambda: (True, "stealth installed"))
        calls = []

        def runner(cmd):
            calls.append(list(cmd))
            return _ok(cmd)

        assert bi.install_browser(cli_env=env, runner=runner) == 0
        err = capsys.readouterr().err
        # patchright is already there: no reinstall hint.
        assert "uv tool install" not in err
        # No uv pip install into the tool env.
        assert all("pip" not in c for c in calls)
        assert calls == [
            [
                "/home/u/.local/share/uv/tools/searchts/bin/python",
                "-m",
                "patchright",
                "install",
                "chromium",
            ]
        ]

    def test_uv_tool_without_patchright_returns_2(self, monkeypatch, capsys):
        env = bi.CliEnv(
            "uv_tool",
            "uv tool env",
            "/home/u/.local/share/uv/tools/searchts/bin/python",
        )
        monkeypatch.setattr(bi, "_patchright_importable", lambda: False)
        calls = []

        def runner(cmd):
            calls.append(list(cmd))
            return _ok(cmd)

        code = bi.install_browser(cli_env=env, runner=runner)
        assert code == bi.EXIT_ACTION_NEEDED == 2
        assert calls == []
        err = capsys.readouterr().err
        assert 'uv tool install "searchts[mcp,browser]" --force' in err
        assert "F11" in err

    def test_editable_installs_metadata_reqs(self, monkeypatch):
        env = bi.CliEnv("editable", "editable", "/repo/.venv/bin/python")
        monkeypatch.setattr(bi, "browser_extra_requirements", lambda: ["patchright>=1.50"])
        calls = []

        def runner(cmd):
            calls.append(list(cmd))
            return _ok(cmd)

        monkeypatch.setattr(bi, "stealth_status", lambda: (True, "stealth installed"))
        assert bi.install_browser(cli_env=env, runner=runner) == 0
        assert calls[0] == [
            "/repo/.venv/bin/python",
            "-m",
            "pip",
            "install",
            "patchright>=1.50",
        ]

    def test_stealth_status_invalidates_import_caches(self, monkeypatch):
        seen = []
        monkeypatch.setattr(bi.importlib, "invalidate_caches", lambda: seen.append(True))
        bi.stealth_status()
        assert seen == [True]

    def test_browser_extra_requirements_from_metadata(self):
        reqs = bi.browser_extra_requirements()
        assert any(r.startswith("patchright") for r in reqs)


class TestCliInstallBrowser:
    def test_cli_flag_dispatches(self, monkeypatch, capsys):
        seen = {}

        def fake_install(*, dry_run=False):
            seen["dry_run"] = dry_run
            return 0

        monkeypatch.setattr(
            "searchts.browser_install.install_browser",
            fake_install,
        )
        with pytest.raises(SystemExit) as exc:
            with patch("sys.argv", ["searchts", "install", "--browser"]):
                main()
        assert exc.value.code == 0
        assert seen == {"dry_run": False}

    def test_cli_dry_run_browser(self, monkeypatch):
        seen = {}

        def fake_install(*, dry_run=False):
            seen["dry_run"] = dry_run
            return 0

        monkeypatch.setattr(
            "searchts.browser_install.install_browser",
            fake_install,
        )
        with pytest.raises(SystemExit) as exc:
            with patch("sys.argv", ["searchts", "install", "--browser", "--dry-run"]):
                main()
        assert exc.value.code == 0
        assert seen == {"dry_run": True}

    def test_cli_propagates_refusal_code(self, monkeypatch):
        monkeypatch.setattr(
            "searchts.browser_install.install_browser",
            lambda *, dry_run=False: 2,
        )
        with pytest.raises(SystemExit) as exc:
            with patch("sys.argv", ["searchts", "install", "--browser"]):
                main()
        assert exc.value.code == 2


class TestStreamRunner:
    def test_child_stdout_goes_to_stderr(self, capfd):
        import sys

        proc = bi._stream_runner([sys.executable, "-c", "print('progress 42%')"])
        assert proc.returncode == 0
        out, err = capfd.readouterr()
        assert "progress 42%" in err
        assert "progress 42%" not in out


class TestUninstallBrowser:
    def _env(self, kind: str, python: str = "/usr/bin/python") -> bi.CliEnv:
        return bi.CliEnv(kind=kind, label=kind, python=python)

    def test_ephemeral_uvx_removes_nothing(self, capsys):
        calls = []
        code = bi.uninstall_browser(
            runner=lambda cmd: calls.append(cmd) or _ok(cmd),
            cli_env=self._env("ephemeral_uvx"),
        )
        assert code == 0 and calls == []
        assert "nothing to remove" in capsys.readouterr().out

    def test_dry_run_does_not_run(self, capsys):
        calls = []
        code = bi.uninstall_browser(
            dry_run=True,
            runner=lambda cmd: calls.append(cmd) or _ok(cmd),
            cli_env=self._env("venv"),
        )
        out = capsys.readouterr()
        assert code == 0 and calls == []
        assert "Dry run complete" in out.out
        assert "Chromium stays" in out.err

    def test_pipx_uninjects_the_extra_names(self, monkeypatch):
        seen = []
        monkeypatch.setattr(bi.shutil, "which", lambda cmd: "/usr/bin/pipx" if cmd == "pipx" else None)
        monkeypatch.setattr(bi, "browser_extra_requirements", lambda: ["patchright>=1.50", "foo[extra]"])

        def run(cmd):
            seen.append(list(cmd))
            return _ok(cmd)

        code = bi.uninstall_browser(runner=run, cli_env=self._env("pipx", "/opt/python"))
        assert code == 0
        assert seen == [["/usr/bin/pipx", "uninject", "searchts", "patchright", "foo"]]

    def test_pip_uninstalls_when_pipx_is_absent(self, monkeypatch):
        monkeypatch.setattr(bi.shutil, "which", lambda cmd: None)
        monkeypatch.setattr(bi, "browser_extra_requirements", lambda: ["patchright>=1.50"])
        seen = []
        code = bi.uninstall_browser(
            runner=lambda cmd: seen.append(list(cmd)) or _ok(cmd),
            cli_env=self._env("venv", "/venv/bin/python"),
        )
        assert code == 0
        assert seen == [["/venv/bin/python", "-m", "pip", "uninstall", "-y", "patchright"]]

    def test_a_failed_dep_removal_does_not_touch_chromium(self, monkeypatch, capsys):
        monkeypatch.setattr(bi.shutil, "which", lambda cmd: None)
        monkeypatch.setattr(bi, "browser_extra_requirements", lambda: ["patchright>=1.50"])
        seen = []

        def run(cmd):
            seen.append(list(cmd))
            return _fail(cmd, err="no package")

        code = bi.uninstall_browser(
            chromium=True,
            runner=run,
            cli_env=self._env("venv", "/venv/bin/python"),
        )
        assert code == 1 and len(seen) == 1
        assert "failed to remove browser deps" in capsys.readouterr().err

    def test_chromium_failure_is_its_own_error(self, monkeypatch, capsys):
        monkeypatch.setattr(bi.shutil, "which", lambda cmd: None)
        monkeypatch.setattr(bi, "browser_extra_requirements", lambda: ["patchright>=1.50"])

        def run(cmd):
            if "chromium" in cmd:
                return _fail(cmd, err="cache busy")
            return _ok(cmd)

        code = bi.uninstall_browser(
            chromium=True,
            runner=run,
            cli_env=self._env("venv", "/venv/bin/python"),
        )
        assert code == 1
        assert "Chromium uninstall failed" in capsys.readouterr().err
