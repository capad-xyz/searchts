# -*- coding: utf-8 -*-
import sys

import pytest

from searchts.integrations.memory_rule import (
    BEGIN,
    OLD_RULES,
    RULE,
    apply_one,
    install_memory_rules,
    refresh_known_rules,
)


def test_rule_calls_read_url_before_a_plain_fetch():
    call = RULE.index("call the searchts MCP tool `read_url`")
    plain = RULE.index("Do not start with a plain fetch.")
    assert call < plain
    assert "sign-in" in RULE


def test_writes_claude_and_cursor_when_detected(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".cursor").mkdir(parents=True)
    logs = []
    actions = install_memory_rules(
        home=home, interactive=False, prompt=lambda _: "n", log=logs.append
    )
    assert actions == ["wrote", "wrote"]
    claude = (home / ".claude" / "CLAUDE.md").read_text()
    cursor = (home / ".cursor" / "rules" / "searchts.mdc").read_text()
    assert BEGIN in claude and "read_url" in claude
    assert BEGIN in cursor


def test_skips_when_no_clients(tmp_path):
    home = tmp_path / "empty"
    home.mkdir()
    actions = install_memory_rules(home=home, interactive=False, log=lambda _: None)
    assert actions == []
    assert not (home / ".claude" / "CLAUDE.md").exists()


def test_noninteractive_does_not_overwrite_existing_block(tmp_path):
    path = tmp_path / "CLAUDE.md"
    path.write_text(RULE.replace("thin/empty", "CHANGED"), encoding="utf-8")
    action = apply_one(path, interactive=False, prompt=lambda _: "y", log=lambda _: None)
    assert action == "skipped"
    assert "CHANGED" in path.read_text()


def test_interactive_overwrite_yes(tmp_path):
    path = tmp_path / "CLAUDE.md"
    path.write_text(BEGIN + "\nold\n" + "<!-- /searchts:reach -->", encoding="utf-8")
    action = apply_one(path, interactive=True, prompt=lambda _: "y", log=lambda _: None)
    assert action == "wrote"
    assert "read_url" in path.read_text()


def test_keeps_identical_block(tmp_path):
    path = tmp_path / "CLAUDE.md"
    path.write_text(RULE, encoding="utf-8")
    action = apply_one(path, interactive=True, prompt=lambda _: "y", log=lambda _: None)
    assert action == "kept"


def test_appends_to_existing_file_without_block(tmp_path):
    path = tmp_path / "CLAUDE.md"
    path.write_text("# my prefs\n", encoding="utf-8")
    action = apply_one(path, interactive=False, prompt=lambda _: "n", log=lambda _: None)
    assert action == "wrote"
    text = path.read_text()
    assert text.startswith("# my prefs")
    assert BEGIN in text


def test_known_old_is_the_403_sentence():
    assert len(OLD_RULES) == 1
    assert "bot-challenge" in OLD_RULES[0]
    assert "Do not start with a plain fetch" not in OLD_RULES[0]


def test_refresh_replaces_known_old_and_keeps_the_rest(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    path = home / ".claude" / "CLAUDE.md"
    path.write_text("# prefs\n\n" + OLD_RULES[0], encoding="utf-8")
    actions = refresh_known_rules(home=home, log=lambda _: None)
    text = path.read_text()
    assert actions == [str(path)]
    assert text.startswith("# prefs")
    assert "Do not start with a plain fetch" in text
    assert "bot-challenge" not in text


def test_refresh_leaves_an_edit_and_does_not_create(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    path = home / ".claude" / "CLAUDE.md"
    edited = OLD_RULES[0].replace("thin/empty", "CHANGED")
    path.write_text("# keep\n" + edited, encoding="utf-8")
    assert refresh_known_rules(home=home, log=lambda _: None) == []
    assert "CHANGED" in path.read_text()
    assert not (home / ".cursor" / "rules" / "searchts.mdc").exists()


def test_noninteractive_install_replaces_known_old(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    path = home / ".claude" / "CLAUDE.md"
    path.write_text("# prefs\n" + OLD_RULES[0], encoding="utf-8")
    actions = install_memory_rules(home=home, interactive=False, log=lambda _: None)
    assert actions == ["wrote"]
    text = path.read_text()
    assert text.startswith("# prefs")
    assert "bot-challenge" not in text


def test_cli_refreshes_before_the_command(monkeypatch):
    import searchts.cli as cli

    called = []
    monkeypatch.setattr(
        "searchts.integrations.memory_rule.refresh_known_rules",
        lambda: called.append(True),
    )
    monkeypatch.setattr(sys, "argv", ["searchts", "--help"])
    with pytest.raises(SystemExit):
        cli._run()
    assert called == [True]
