"""#439 (TEMPORARY): the faster-whisper notice and its opt-in removal.

Delete with searchts/fw_migration.py in the follow-up issue.
"""
import json
import os
import subprocess
from unittest.mock import patch

import pytest

from searchts import fw_migration as fw


class _Dist:
    def __init__(self, version, requires=()):
        self.version = version
        self.requires = list(requires)


def _env(*, shared=True, extra=None):
    dists = {
        "searchts": _Dist("0.22.2", ['faster-whisper>=1.0; extra == "local-transcribe"']),
        "faster-whisper": _Dist("1.1.1", ["ctranslate2<5,>=4.0", "av>=11", "onnxruntime<2,>=1.14"]),
        "ctranslate2": _Dist("4.6.0", ["numpy"]),
        "av": _Dist("15.0.0"),
        "onnxruntime": _Dist("1.22.0", ["numpy>=1.21"]),
    }
    dists.update(extra or {})
    return dists


@pytest.fixture
def hf_cache(tmp_path, monkeypatch):
    hub = tmp_path / "hub"
    fw_model = hub / "models--Systran--faster-whisper-small" / "blobs"
    fw_model.mkdir(parents=True)
    (fw_model / "model.bin").write_bytes(b"x" * 2048)
    other = hub / "models--bert-base-uncased"
    other.mkdir(parents=True)
    (other / "w.bin").write_bytes(b"y" * 10)
    monkeypatch.setenv("HF_HUB_CACHE", str(hub))
    return hub


def _shared(monkeypatch):
    monkeypatch.setattr("searchts.update_nudge.detect_install_kind", lambda: "pip")


def test_no_faster_whisper_means_no_report():
    assert fw.report(dists={"searchts": _Dist("1")}) is None


def test_migration_notice_stays_until_both_time_and_release_limits_pass():
    from datetime import datetime, timezone

    released = datetime.fromisoformat(fw.MIGRATION_WINDOW["release_date"]).replace(
        tzinfo=timezone.utc
    ).timestamp()
    before_release = fw._version_tuple(fw.MIGRATION_WINDOW["first_version"])
    after_two = fw.MIGRATION_WINDOW["after_two_releases_version"]
    assert not fw.migration_window_open(package_version="0.23.9", now=released)
    assert fw.migration_window_open(package_version=fw.MIGRATION_WINDOW["first_version"], now=released)
    assert fw.migration_window_open(
        package_version="0.25.0", now=released + fw.MIGRATION_WINDOW["days"] * 86400
    )
    assert fw.migration_window_open(
        package_version=after_two, now=released + fw.MIGRATION_WINDOW["days"] * 86400 - 1
    )
    assert not fw.migration_window_open(
        package_version=after_two, now=released + fw.MIGRATION_WINDOW["days"] * 86400
    )
    assert before_release == (0, 24, 0)


def test_report_lists_what_else_uses_each_package(monkeypatch, hf_cache):
    _shared(monkeypatch)
    dists = _env(extra={
        "whisperx": _Dist("3.1", ["faster-whisper>=1.0"]),
        "pyav-tools": _Dist("0.1", ['av>=10; extra == "video"']),
    })
    rep = fw.report(dists=dists)
    by = {p["name"]: p for p in rep["packages"]}
    assert by["faster-whisper"]["required_by"] == ["whisperx"]
    assert by["faster-whisper"]["remove"] is False
    assert by["av"]["required_by"] == ["pyav-tools (optional)"]
    assert by["ctranslate2"]["required_by"] == [] and by["ctranslate2"]["remove"] is True
    # searchts itself and the chain do not count as "something else".
    assert "searchts" not in json.dumps(by["faster-whisper"]["required_by"])
    assert rep["environment"]["own_environment"] is False
    assert "shared Python environment" in rep["environment"]["note"]


def test_own_uv_or_pipx_env_says_removal_is_safe(monkeypatch, hf_cache):
    monkeypatch.setattr("searchts.update_nudge.detect_install_kind", lambda: "uv_tool")
    rep = fw.report(dists=_env())
    assert rep["environment"]["own_environment"] is True
    assert "safe" in rep["environment"]["note"]


def test_a_dedicated_venv_is_searchts_own_environment(monkeypatch, hf_cache):
    """#488: a pip venv holding only searchts and its tree is not shared."""
    _shared(monkeypatch)
    dists = _env(extra={
        "pip": _Dist("24.0"),          # venv tooling, not another program
        "widget": _Dist("1.0"),
    })
    dists["searchts"] = _Dist("0.24.2", ["faster-whisper", "widget"])
    rep = fw.report(dists=dists)
    assert rep["environment"]["own_environment"] is True
    assert "safe" in rep["environment"]["note"]
    assert "shared Python environment" not in rep["environment"]["note"]


def test_unknown_environment_says_it_cannot_tell(monkeypatch, hf_cache):
    """#488: without searchts metadata, do not call the environment shared."""
    import importlib.metadata as metadata

    _shared(monkeypatch)
    dists = _env()
    dists.pop("searchts")
    monkeypatch.setattr(
        metadata, "requires",
        lambda name: (_ for _ in ()).throw(metadata.PackageNotFoundError(name)),
    )
    rep = fw.report(dists=dists)
    assert rep["environment"]["own_environment"] is False
    assert "cannot tell" in rep["environment"]["note"]
    assert "shared Python environment" not in rep["environment"]["note"]


def test_only_faster_whisper_model_folders_are_listed(monkeypatch, hf_cache):
    _shared(monkeypatch)
    rep = fw.report(dists=_env())
    caches = rep["model_caches"]
    assert [os.path.basename(c["path"]) for c in caches] == ["models--Systran--faster-whisper-small"]
    assert caches[0]["size_bytes"] == 2048 and caches[0]["modified"]
    assert "cannot tell" in rep["model_cache_note"]


def test_human_notice_says_it_plainly(monkeypatch, hf_cache):
    _shared(monkeypatch)
    text = fw.human_notice(fw.report(dists=_env()))
    assert "installed faster-whisper (and its Whisper models)" in text
    assert "no longer uses them" in text
    assert "searchts transcribe --cleanup --yes" in text
    assert "--dry-run" in text and "temporary" in text
    assert "Other apps on this machine may use these folders" in text


def test_notice_is_once_a_day_per_channel(monkeypatch, hf_cache, tmp_path):
    _shared(monkeypatch)
    monkeypatch.setattr(fw, "_distributions", _env)
    monkeypatch.setattr(fw, "migration_window_open", lambda **kw: True)
    assert fw.maybe_agent_note(now=1000.0) is not None
    assert fw.maybe_agent_note(now=2000.0) is None
    assert fw.maybe_agent_note(now=1000.0 + fw.NOTICE_TTL) is not None
    # The human channel has its own stamp.
    import io

    buf = io.StringIO()
    assert fw.maybe_print_notice(now=1500.0, stream=buf) is True
    assert fw.maybe_print_notice(now=1600.0, stream=buf) is False


def test_agent_note_carries_the_consent_rule(monkeypatch, hf_cache):
    _shared(monkeypatch)
    note = fw.agent_note(fw.report(dists=_env()))
    assert "only after the user says yes" in note["note"]
    assert "Nothing was removed" in note["note"]
    assert note["report"]["remove_command"] == "searchts transcribe --cleanup --yes"


def test_opt_out_env_silences_the_notice(monkeypatch, hf_cache):
    _shared(monkeypatch)
    monkeypatch.setattr(fw, "_distributions", _env)
    monkeypatch.setenv("SEARCHTS_NO_MIGRATION_NOTICE", "1")
    assert fw.maybe_agent_note(now=1.0) is None


def test_cleanup_removes_only_unused_packages_and_fw_caches(monkeypatch, hf_cache):
    _shared(monkeypatch)
    dists = _env(extra={"whisperx": _Dist("3.1", ["faster-whisper"])})
    rep = fw.report(dists=dists)
    ran = []

    def run(argv):
        ran.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    done = fw.cleanup(rep, run=run)
    assert ran and "faster-whisper" not in ran[0]
    assert set(done["removed_packages"]) == {"ctranslate2", "av", "onnxruntime"}
    assert done["kept_packages"] == [{"name": "faster-whisper", "reason": "required by whisperx"}]
    assert not (hf_cache / "models--Systran--faster-whisper-small").exists()
    assert (hf_cache / "models--bert-base-uncased").exists()


def _cli(argv, capsys):
    from searchts.cli import main

    with patch("sys.argv", ["searchts", *argv]):
        try:
            main()
            code = 0
        except SystemExit as e:
            code = e.code
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_dry_run_reports_and_removes_nothing(monkeypatch, capsys, hf_cache):
    _shared(monkeypatch)
    monkeypatch.setattr(fw, "_distributions", _env)
    monkeypatch.setattr(fw, "cleanup", lambda *a, **k: pytest.fail("removed on a dry run"))
    code, out, _ = _cli(["transcribe", "--cleanup", "--dry-run"], capsys)
    assert code == 0 and "used by nothing else here" in out and "nothing was removed" in out
    code, out, _ = _cli(["transcribe", "--cleanup", "--dry-run", "--json"], capsys)
    doc = json.loads(out)
    assert doc["schema"] == "searchts.fw_migration.v1" and doc["removed"] is False


def test_cli_without_yes_off_a_terminal_removes_nothing(monkeypatch, capsys, hf_cache):
    _shared(monkeypatch)
    monkeypatch.setattr(fw, "_distributions", _env)
    monkeypatch.setattr(fw, "cleanup", lambda *a, **k: pytest.fail("removed without a yes"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    code, _, err = _cli(["transcribe", "--cleanup"], capsys)
    assert code == 2 and "Nothing removed" in err


def test_cli_yes_removes(monkeypatch, capsys, hf_cache):
    _shared(monkeypatch)
    monkeypatch.setattr(fw, "_distributions", _env)
    seen = []
    monkeypatch.setattr(fw, "cleanup", lambda rep, **k: seen.append(rep) or {
        "removed_packages": ["faster-whisper"], "kept_packages": [],
        "removed_caches": [], "kept_caches": []})
    code, out, _ = _cli(["transcribe", "--cleanup", "--yes", "--json"], capsys)
    assert code == 0 and seen and json.loads(out)["removed"] is True


def test_nothing_installed_says_so(monkeypatch, capsys):
    monkeypatch.setattr(fw, "_distributions", lambda: {})
    code, out, _ = _cli(["transcribe", "--cleanup"], capsys)
    assert code == 0 and "not installed" in out


def test_mcp_results_carry_the_agent_note(monkeypatch, hf_cache):
    from searchts.integrations import mcp_server

    _shared(monkeypatch)
    monkeypatch.setattr(fw, "_distributions", _env)
    monkeypatch.setattr(fw, "migration_window_open", lambda **kw: True)
    text = mcp_server._with_update_info("plain result", None)
    assert "update_note: Note for the agent: searchts installed faster-whisper" in text
    assert "fw_migration_report: " in text
    data = json.loads(mcp_server._with_update_info(json.dumps({"ok": True}), None))
    # Once a day: the first call above already used today's note.
    assert "update_note" not in data


def test_read_json_carries_the_agent_note(monkeypatch, hf_cache):
    _shared(monkeypatch)
    monkeypatch.setattr(fw, "_distributions", _env)
    monkeypatch.setattr(fw, "migration_window_open", lambda **kw: True)
    payload = fw.add_agent_note({"text": "page"})
    assert "no longer uses them" in payload["update_note"]
    assert payload["fw_migration_report"]["packages"][0]["name"] == "faster-whisper"
