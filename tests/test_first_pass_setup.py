"""#442: first-pass setup with one up-front consent."""
import json
import sys

import pytest

from searchts import setup_plan
from searchts.utils import ffmpeg as ffmpeg_mod


@pytest.fixture
def nothing_installed(monkeypatch):
    monkeypatch.setattr(setup_plan.shutil, "which", lambda name: None)
    monkeypatch.setattr(setup_plan, "chromium_installed", lambda: False)
    calls = []
    for name in ("_install_chromium", "_install_twitter", "_install_reddit",
                 "_install_linkedin", "_install_mcporter", "_install_gh"):
        monkeypatch.setattr(setup_plan, name, lambda n=name: calls.append(n) or True)
    return calls


def test_plan_is_versioned_and_complete(nothing_installed):
    doc = setup_plan.plan()
    assert doc["schema"] == "searchts.setup.v1"
    ids = [i["id"] for i in doc["items"]]
    assert ids == ["chromium", "twitter", "reddit", "linkedin", "mcporter", "gh", "whisper-model"]
    for item in doc["items"]:
        for key in ("what_it_unlocks", "size_bytes", "size_is_estimate", "installed",
                    "needs_login", "needs_system_change", "default_selected",
                    "approve_command"):
            assert key in item
        assert item["size_bytes"] > 0
    by_id = {i["id"]: i for i in doc["items"]}
    # The browser and every site tool are checked by default.
    assert all(by_id[i]["default_selected"] for i in ids[:-1])
    # The Whisper model is listed, never installed by this approval.
    assert by_id["whisper-model"]["when"] == "first_use"
    assert "whisper-model" not in doc["pending"]
    assert doc["approve_command"] == "searchts install --yes"
    assert doc["logins"].startswith("not part of this approval")


def test_skip_deselects_and_unknown_ids_are_refused(nothing_installed):
    doc = setup_plan.plan(setup_plan.parse_skip("twitter, LinkedIn"))
    assert "twitter" not in doc["pending"] and "linkedin" not in doc["pending"]
    assert doc["approve_command"] == "searchts install --yes --skip twitter,linkedin"
    with pytest.raises(ValueError, match="unknown setup item"):
        setup_plan.parse_skip("myspace")


def test_install_runs_only_selected_missing_items(nothing_installed):
    results = setup_plan.run_install(["gh", "linkedin"])
    assert set(results) == {"chromium", "twitter", "reddit", "mcporter"}
    assert "_install_gh" not in nothing_installed
    assert "_install_linkedin" not in nothing_installed


def test_interactive_choice_parses_answers():
    assert setup_plan.interactive_choice([], ask=lambda _: "") == []
    assert setup_plan.interactive_choice([], ask=lambda _: "n") is None
    assert setup_plan.interactive_choice(["gh"], ask=lambda _: "reddit") == ["gh", "reddit"]


def test_dry_run_json_prints_the_plan_and_changes_nothing(monkeypatch, capsys, nothing_installed):
    from searchts import cli

    monkeypatch.setattr(sys, "argv", ["searchts", "install", "--dry-run", "--json"])
    try:
        cli.main()
    except SystemExit as e:
        assert not e.code
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema"] == "searchts.setup.v1"
    assert nothing_installed == []


def test_no_terminal_without_yes_installs_nothing(monkeypatch, capsys, nothing_installed):
    from searchts import cli

    class Args:
        skip_ids = []
        yes = False

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    cli._first_pass(Args(), dry_run=False)
    out = capsys.readouterr().out
    assert "Not installed: no terminal to ask" in out
    assert "searchts install --yes" in out
    assert nothing_installed == []


def test_yes_installs_the_checked_items(monkeypatch, capsys, nothing_installed):
    from searchts import cli

    class Args:
        skip_ids = ["mcporter"]
        yes = True

    cli._first_pass(Args(), dry_run=False)
    assert "_install_mcporter" not in nothing_installed
    assert "_install_chromium" in nothing_installed and "_install_gh" in nothing_installed


def test_ffmpeg_falls_back_to_the_bundled_binary(monkeypatch, tmp_path):
    exe = tmp_path / "ffmpeg-linux-x86_64-v7"
    exe.write_text("")
    monkeypatch.setattr(ffmpeg_mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(ffmpeg_mod, "bundled_ffmpeg", lambda: str(exe))
    assert ffmpeg_mod.ffmpeg_exe() == str(exe)
    assert ffmpeg_mod.ytdlp_ffmpeg_args() == ["--ffmpeg-location", str(exe)]
    monkeypatch.setattr(ffmpeg_mod.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    assert ffmpeg_mod.ffmpeg_exe() == "/usr/bin/ffmpeg"
    assert ffmpeg_mod.ytdlp_ffmpeg_args() == []


def test_missing_tool_hints_point_at_the_setup_command():
    hint = setup_plan.missing_tool_hint("twitter")
    assert "searchts install" in hint
    assert "--skip chromium,reddit,linkedin,mcporter,gh" in hint
