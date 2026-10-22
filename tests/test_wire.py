# -*- coding: utf-8 -*-
"""`mcp install` merges each client's own file. `skill install` copies the bundle."""

import json

import pytest

from searchts.integrations.skill_bundle import install_shared_skills
from searchts.integrations.wire import apply_mcp


def test_writes_each_present_client_in_its_shape(tmp_path, monkeypatch):
    monkeypatch.setattr("searchts.integrations.wire.sys.platform", "linux")
    home = tmp_path / "home"
    (home / ".cursor").mkdir(parents=True)
    (home / ".config" / "Code" / "User").mkdir(parents=True)
    (home / ".config" / "opencode").mkdir(parents=True)
    (home / ".codex").mkdir()
    (home / ".claude.json").write_text(
        json.dumps({"numStartups": 3, "mcpServers": {"other": {"command": "other"}}}),
        encoding="utf-8",
    )
    rows = {row["id"]: row for row in apply_mcp(home, cwd=tmp_path, environ={})}
    assert set(rows) == {"claude", "cursor", "codex", "vscode", "opencode"}
    assert all(row["status"] == "wrote" for row in rows.values())
    assert not (home / ".gemini").exists()

    claude = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    assert claude["numStartups"] == 3
    assert claude["mcpServers"]["other"]["command"] == "other"
    assert claude["mcpServers"]["searchts"]["args"] == ["mcp", "serve"]
    assert "type" not in claude["mcpServers"]["searchts"]

    cursor = json.loads((home / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert cursor["mcpServers"]["searchts"]["command"] == "searchts"
    assert "type" not in cursor["mcpServers"]["searchts"]

    vscode = json.loads((home / ".config" / "Code" / "User" / "mcp.json").read_text(encoding="utf-8"))
    assert vscode["servers"]["searchts"]["type"] == "stdio"
    assert "mcpServers" not in vscode

    opencode = json.loads((home / ".config" / "opencode" / "opencode.json").read_text(encoding="utf-8"))
    assert opencode["mcp"]["searchts"]["type"] == "local"
    assert opencode["mcp"]["searchts"]["command"] == ["searchts", "mcp", "serve"]

    codex = (home / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert codex == '[mcp_servers.searchts]\ncommand = "searchts"\nargs = ["mcp", "serve"]\n'


def test_matching_entry_is_not_reformatted(tmp_path):
    home = tmp_path / "home"
    path = home / ".cursor" / "mcp.json"
    path.parent.mkdir(parents=True)
    compact = (
        '{"mcpServers":{"searchts":{"command":"searchts","args":["mcp","serve"]},'
        '"other":{"command":"x"}}}'
    )
    path.write_text(compact, encoding="utf-8")
    rows = apply_mcp(home, cwd=tmp_path, environ={})
    assert rows[0]["status"] == "already"
    assert path.read_text(encoding="utf-8") == compact
    again = apply_mcp(home, cwd=tmp_path, environ={})
    assert again[0]["status"] == "already"
    assert path.read_text(encoding="utf-8") == compact


def test_custom_command_corrupt_json_and_comments_are_left_alone(tmp_path):
    home = tmp_path / "home"
    cursor = home / ".cursor" / "mcp.json"
    cursor.parent.mkdir(parents=True)
    custom = '{"mcpServers": {"searchts": {"command": "uvx", "args": ["searchts"]}, "keep": true}}\n'
    cursor.write_text(custom, encoding="utf-8")
    rows = apply_mcp(home, cwd=tmp_path, environ={})
    assert rows[0]["status"] == "kept"
    assert cursor.read_text(encoding="utf-8") == custom

    partial_home = tmp_path / "partial"
    partial = partial_home / ".cursor" / "mcp.json"
    partial.parent.mkdir(parents=True)
    body = '{"mcpServers": {"searchts": {"command": "searchts"}}}\n'
    partial.write_text(body, encoding="utf-8")
    rows = apply_mcp(partial_home, cwd=tmp_path, environ={})
    assert rows[0]["status"] == "kept"
    assert partial.read_text(encoding="utf-8") == body

    broken_home = tmp_path / "broken"
    broken = broken_home / ".cursor" / "mcp.json"
    broken.parent.mkdir(parents=True)
    broken.write_text("{nope", encoding="utf-8")
    rows = apply_mcp(broken_home, cwd=tmp_path, environ={})
    assert rows[0]["status"] == "skipped"
    assert broken.read_text(encoding="utf-8") == "{nope"

    gemini = tmp_path / "jsonc"
    settings = gemini / ".gemini" / "settings.json"
    settings.parent.mkdir(parents=True)
    raw = '{ // comment\n"mcpServers": {}\n}\n'
    settings.write_text(raw, encoding="utf-8")
    rows = apply_mcp(gemini, cwd=tmp_path, environ={})
    assert rows[0]["status"] == "skipped"
    assert settings.read_text(encoding="utf-8") == raw


def test_codex_appends_once(tmp_path):
    home = tmp_path / "home"
    path = home / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text('model = "gpt"\n', encoding="utf-8")
    rows = apply_mcp(home, cwd=tmp_path, environ={})
    assert [row["id"] for row in rows] == ["codex"]
    assert rows[0]["status"] == "wrote"
    text = path.read_text(encoding="utf-8")
    assert text.startswith('model = "gpt"\n')
    assert '\n[mcp_servers.searchts]\ncommand = "searchts"\n' in text
    again = apply_mcp(home, cwd=tmp_path, environ={})
    assert again[0]["status"] == "already"
    assert path.read_text(encoding="utf-8") == text

    quoted_home = tmp_path / "quoted"
    quoted_path = quoted_home / ".codex" / "config.toml"
    quoted_path.parent.mkdir(parents=True)
    quoted = '[mcp_servers."searchts"]\ncommand = "uvx"\n'
    quoted_path.write_text(quoted, encoding="utf-8")
    rows = apply_mcp(quoted_home, cwd=tmp_path, environ={})
    assert rows[0]["status"] == "already"
    assert quoted_path.read_text(encoding="utf-8") == quoted


def test_json_client_and_absent_client_write_nothing(tmp_path):
    home = tmp_path / "home"
    (home / ".cursor").mkdir(parents=True)
    assert apply_mcp(home, client="json", cwd=tmp_path, environ={}) == []
    assert not (home / ".cursor" / "mcp.json").exists()
    assert apply_mcp(tmp_path / "empty", cwd=tmp_path, environ={}) == []
    assert not (tmp_path / "empty" / ".gemini").exists()


def test_forced_client_creates_its_file(tmp_path):
    home = tmp_path / "home"
    rows = apply_mcp(home, client="gemini", cwd=tmp_path, environ={})
    assert rows[0]["status"] == "wrote"
    saved = json.loads((home / ".gemini" / "settings.json").read_text(encoding="utf-8"))
    assert saved["mcpServers"]["searchts"]["args"] == ["mcp", "serve"]
    with pytest.raises(ValueError):
        apply_mcp(home, client="nope", cwd=tmp_path, environ={})


def test_project_cursor_file_is_not_edited(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "proj" / ".cursor" / "mcp.json"
    project.parent.mkdir(parents=True)
    original = '{"mcpServers": {"other": {"command": "other"}}}\n'
    project.write_text(original, encoding="utf-8")
    rows = apply_mcp(home, cwd=tmp_path / "proj", environ={})
    assert [row["id"] for row in rows] == ["cursor"]
    assert rows[0]["status"] == "wrote"
    assert project.read_text(encoding="utf-8") == original
    saved = json.loads((home / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert saved["mcpServers"]["searchts"]["command"] == "searchts"
    assert "other" not in saved["mcpServers"]


def test_desktop_appdata_keeps_other_keys(tmp_path, monkeypatch):
    monkeypatch.setattr("searchts.integrations.wire.sys.platform", "win32")
    appdata = tmp_path / "Roaming"
    path = appdata / "Claude" / "claude_desktop_config.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"theme": "dark", "mcpServers": {"other": {"command": "other"}}}),
        encoding="utf-8",
    )
    home = tmp_path / "home"
    rows = apply_mcp(home, cwd=tmp_path, environ={"APPDATA": str(appdata)})
    assert [row["id"] for row in rows] == ["desktop"]
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["theme"] == "dark"
    assert saved["mcpServers"]["other"]["command"] == "other"
    assert saved["mcpServers"]["searchts"]["command"] == "searchts"
    assert not (home / ".config" / "Claude").exists()


def test_skill_bundle_homes(tmp_path):
    home = tmp_path / "home"
    rows = install_shared_skills(home, environ={})
    assert [row["path"] for row in rows] == [
        home / ".agents" / "skills" / "searchts",
        home / ".claude" / "skills" / "searchts",
    ]
    assert all(row["ok"] for row in rows)
    for row in rows:
        text = (row["path"] / "SKILL.md").read_text(encoding="utf-8")
        assert "name: searchts" in text
        assert "searchts read" in text
        assert (row["path"] / "references" / "web.md").is_file()
    assert not (home / ".openclaw").exists()
    assert not (home / ".config").exists()

    (home / ".openclaw" / "skills").mkdir(parents=True)
    rows = install_shared_skills(home, environ={})
    assert (home / ".openclaw" / "skills" / "searchts" / "SKILL.md").is_file()

    oc = tmp_path / "oc"
    rows = install_shared_skills(home, environ={"OPENCLAW_HOME": str(oc)})
    assert oc / ".openclaw" / "skills" / "searchts" not in [row["path"] for row in rows]
    assert not oc.exists()

    (oc / ".openclaw" / "skills").mkdir(parents=True)
    rows = install_shared_skills(home, environ={"OPENCLAW_HOME": str(oc)})
    assert rows[0]["path"] == oc / ".openclaw" / "skills" / "searchts"
    assert (rows[0]["path"] / "SKILL.md").is_file()

    rows = install_shared_skills(home, environ={"OPENCLAW_HOME": str(home)})
    paths = [row["path"] for row in rows]
    assert paths.count(home / ".openclaw" / "skills" / "searchts") == 1
