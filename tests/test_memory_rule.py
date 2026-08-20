# -*- coding: utf-8 -*-
from searchts.integrations.memory_rule import (
    BEGIN,
    RULE,
    apply_one,
    install_memory_rules,
)


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
