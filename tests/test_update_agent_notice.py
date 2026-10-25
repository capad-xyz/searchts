# -*- coding: utf-8 -*-
"""Agent-facing update notice: --json, MCP results, opt-out and the TTL.

No real network. Every test points the cache at tmp_path and stubs
``_fetch_latest``. These tests clear ``PYTEST_CURRENT_TEST`` because the
agent surfaces apply the same test-run guard the stderr nudge has; the helper
itself does not, so unit tests can call it directly.
"""

from unittest.mock import patch

from searchts import update_nudge as un
from searchts.cli import main
from searchts.integrations import mcp_server
from searchts.search import SearchResult
from searchts.unlocker import FetchResult


def _enable_agent_checks(monkeypatch, tmp_path, latest="9.9.9"):
    """Point the cache at tmp_path and let the agent surfaces run under pytest."""
    monkeypatch.delenv("SEARCHTS_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    # Clearing PYTEST_CURRENT_TEST also wakes the CLI's Windows console setup,
    # which replaces sys.stdout with a new TextIOWrapper around the captured
    # buffer. Keep capsys as the stream under test, as test_cli.py does.
    monkeypatch.setattr("searchts.cli._ensure_utf8_console", lambda: None)
    cache = tmp_path / "update-check.json"
    monkeypatch.setattr(un, "cache_path", lambda: cache)
    calls = {"n": 0}

    def fetch(timeout=2.0):
        calls["n"] += 1
        return latest

    monkeypatch.setattr(un, "_fetch_latest", fetch)
    return cache, calls


def _read(monkeypatch, tmp_path, capsys, argv):
    with patch(
        "searchts.unlocker.fetch",
        return_value=FetchResult("curl_cffi", "page body", 200),
    ):
        with patch("sys.argv", argv):
            main()
    return capsys.readouterr()


# ── update_available helper ─────────────────────────────────────────────────


def test_update_available_newer(monkeypatch, tmp_path):
    monkeypatch.delenv("SEARCHTS_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(un, "__version__", "1.4.2")
    monkeypatch.setattr(un, "_fetch_latest", lambda timeout=2.0: "1.5.0")
    info = un.update_available(path=tmp_path / "update-check.json", now=1000)
    assert info == {
        "current": "1.4.2",
        "latest": "1.5.0",
        "command": "searchts update",
    }


def test_update_available_same(monkeypatch, tmp_path):
    monkeypatch.delenv("SEARCHTS_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(un, "__version__", "1.5.0")
    monkeypatch.setattr(un, "_fetch_latest", lambda timeout=2.0: "1.5.0")
    assert un.update_available(path=tmp_path / "c.json", now=1000) is None


def test_update_available_older(monkeypatch, tmp_path):
    monkeypatch.delenv("SEARCHTS_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(un, "__version__", "1.5.0")
    monkeypatch.setattr(un, "_fetch_latest", lambda timeout=2.0: "1.4.2")
    assert un.update_available(path=tmp_path / "c.json", now=1000) is None


def test_update_available_offline_is_silent(monkeypatch, tmp_path):
    monkeypatch.delenv("SEARCHTS_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(un, "_fetch_latest", lambda timeout=2.0: None)
    path = tmp_path / "c.json"
    assert un.update_available(path=path, now=1000) is None
    import json

    assert json.loads(path.read_text(encoding="utf-8"))["failed_at"] == 1000


def test_offline_failure_backs_off_for_an_hour(monkeypatch, tmp_path):
    monkeypatch.delenv("SEARCHTS_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(un, "__version__", "1.0.0")
    calls = {"n": 0}

    def fetch(timeout=2.0):
        calls["n"] += 1
        return None

    monkeypatch.setattr(un, "_fetch_latest", fetch)
    path = tmp_path / "c.json"
    assert un.update_available(path=path, now=1000) is None
    assert un.update_available(path=path, now=1000 + 60) is None
    assert calls["n"] == 1
    assert un.update_available(path=path, now=1000 + un.FAILURE_TTL_SECONDS + 1) is None
    assert calls["n"] == 2


def test_update_available_opt_out(monkeypatch, tmp_path):
    monkeypatch.setenv("SEARCHTS_NO_UPDATE_CHECK", "1")
    monkeypatch.setattr(un, "_fetch_latest", lambda timeout=2.0: "9.9.9")
    path = tmp_path / "c.json"
    assert un.update_available(path=path, now=1000) is None
    assert not path.exists()


def test_update_available_ttl_avoids_a_second_fetch(monkeypatch, tmp_path):
    monkeypatch.delenv("SEARCHTS_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(un, "__version__", "1.0.0")
    calls = {"n": 0}

    def fetch(timeout=2.0):
        calls["n"] += 1
        return "1.1.0"

    monkeypatch.setattr(un, "_fetch_latest", fetch)
    path = tmp_path / "c.json"
    first = un.update_available(path=path, now=1000)
    second = un.update_available(path=path, now=1000 + un.TTL_SECONDS - 1)
    assert first and second
    assert calls["n"] == 1


def test_update_available_stale_cache_fetches_once(monkeypatch, tmp_path):
    monkeypatch.delenv("SEARCHTS_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(un, "__version__", "1.0.0")
    calls = {"n": 0}

    def fetch(timeout=2.0):
        calls["n"] += 1
        return "1.1.0"

    monkeypatch.setattr(un, "_fetch_latest", fetch)
    path = tmp_path / "c.json"
    un._write_cache(path, "1.0.0", now=1000)
    un.update_available(path=path, now=1000 + un.TTL_SECONDS + 1)
    un.update_available(path=path, now=1000 + un.TTL_SECONDS + 2)
    assert calls["n"] == 1


def test_update_note_is_once_per_24h(monkeypatch, tmp_path):
    monkeypatch.delenv("SEARCHTS_NO_UPDATE_CHECK", raising=False)
    path = tmp_path / "update-check.json"
    info = {"current": "1.0.0", "latest": "1.1.0", "command": "searchts update"}
    first = un.update_note(info, path=path, now=1000)
    second = un.update_note(info, path=path, now=1000 + un.TTL_SECONDS - 1)
    third = un.update_note(info, path=path, now=1000 + un.TTL_SECONDS + 1)
    assert first and "Nothing was installed" in first
    assert "searchts update" in first
    assert second is None
    assert third == first


def test_update_note_new_release_gets_its_own_note(monkeypatch, tmp_path):
    monkeypatch.delenv("SEARCHTS_NO_UPDATE_CHECK", raising=False)
    path = tmp_path / "update-check.json"
    old = {"current": "1.0.0", "latest": "1.1.0", "command": "searchts update"}
    new = {"current": "1.0.0", "latest": "1.2.0", "command": "searchts update"}
    first = un.update_note(old, path=path, now=1000)
    repeated = un.update_note(old, path=path, now=1060)
    newer = un.update_note(new, path=path, now=1120)
    repeated_newer = un.update_note(new, path=path, now=1180)
    assert first and "v1.1.0" in first
    assert repeated is None
    assert newer and "v1.2.0" in newer
    assert repeated_newer is None


def test_update_note_opt_out(monkeypatch, tmp_path):
    monkeypatch.setenv("SEARCHTS_NO_UPDATE_CHECK", "1")
    info = {"current": "1.0.0", "latest": "1.1.0", "command": "searchts update"}
    path = tmp_path / "update-check.json"
    assert un.update_note(info, path=path, now=1000) is None
    assert not (tmp_path / un.NOTICE_NAME).exists()


def test_update_helpers_never_run_a_command(monkeypatch, tmp_path):
    monkeypatch.delenv("SEARCHTS_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(un, "__version__", "1.0.0")
    monkeypatch.setattr(un, "_fetch_latest", lambda timeout=2.0: "1.1.0")

    def explode(*args, **kwargs):
        raise AssertionError("the update check must never install or run anything")

    monkeypatch.setattr(un.os, "system", explode)
    monkeypatch.setattr(un.os, "kill", explode, raising=False)
    import subprocess

    monkeypatch.setattr(subprocess, "run", explode)
    monkeypatch.setattr(subprocess, "call", explode)

    path = tmp_path / "update-check.json"
    info = un.update_available(path=path, now=1000)
    assert info and info["command"] == "searchts update"
    assert un.update_note(info, path=path, now=1000)


def test_docs_and_mcp_descriptions_name_the_check():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    update_doc = (root / "docs" / "update.md").read_text(encoding="utf-8")
    mcp_doc = (root / "docs" / "mcp.md").read_text(encoding="utf-8")
    for text in (readme, update_doc, mcp_doc):
        flat = " ".join(text.split())
        assert "capad-xyz/searchts/releases/latest" in flat
        assert "~/.searchts/update-check.json" in flat
        assert "Nothing is installed" in flat
        assert "SEARCHTS_NO_UPDATE_CHECK=1" in flat
    description = mcp_server.UPDATE_CHECK_DESCRIPTION
    for needle in (
        "GitHub latest release of capad-xyz/searchts",
        "at most once per 24 hours",
        "~/.searchts/update-check.json",
        "Nothing is installed",
        "SEARCHTS_NO_UPDATE_CHECK=1",
    ):
        assert needle in description



# ── CLI --json ──────────────────────────────────────────────────────────────


def test_read_json_has_update_available_only_when_newer(monkeypatch, tmp_path, capsys):
    _enable_agent_checks(monkeypatch, tmp_path)
    captured = _read(
        monkeypatch, tmp_path, capsys,
        ["searchts", "read", "https://x.test", "--json"],
    )
    import json

    payload = json.loads(captured.out)
    assert payload["update_available"] == {
        "current": un.__version__,
        "latest": "9.9.9",
        "command": "searchts update",
    }


def test_read_json_absent_when_current(monkeypatch, tmp_path, capsys):
    _enable_agent_checks(monkeypatch, tmp_path, latest=un.__version__)
    captured = _read(
        monkeypatch, tmp_path, capsys,
        ["searchts", "read", "https://x.test", "--json"],
    )
    import json

    assert "update_available" not in json.loads(captured.out)


def test_read_plain_stdout_is_unchanged(monkeypatch, tmp_path, capsys):
    _enable_agent_checks(monkeypatch, tmp_path)
    captured = _read(monkeypatch, tmp_path, capsys, ["searchts", "read", "https://x.test"])
    assert captured.out == "page body\n"
    assert "update_available" not in captured.out


def test_search_json_stays_a_list(monkeypatch, tmp_path, capsys):
    _enable_agent_checks(monkeypatch, tmp_path)
    with patch(
        "searchts.search.search",
        return_value=[SearchResult("T", "https://x.test/1", "snip", "duckduckgo")],
    ):
        with patch("sys.argv", ["searchts", "search", "q", "--json"]):
            main()
    import json

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert isinstance(payload, list)
    assert payload == [
        {"title": "T", "url": "https://x.test/1", "snippet": "snip", "source": "duckduckgo"}
    ]
    # #445: the notice rides on stderr as one JSON line, stdout stays the array.
    notes = [json.loads(line) for line in captured.err.splitlines()
             if line.startswith("{")]
    assert notes == [{"update_available": {
        "current": un.__version__, "latest": "9.9.9", "command": "searchts update",
    }}]


def test_doctor_json_has_update_available_only_when_newer(monkeypatch, tmp_path, capsys):
    import json

    results = {"web": {"status": "ok", "name": "Any web page", "message": "ok",
                       "tier": 0, "backends": [], "active_backend": None}}
    monkeypatch.setattr("searchts.doctor.check_all", lambda *a, **k: results)
    _enable_agent_checks(monkeypatch, tmp_path)
    with patch("sys.argv", ["searchts", "doctor", "--json"]):
        main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["update_available"]["latest"] == "9.9.9"
    assert payload["web"]["status"] == "ok"

    _enable_agent_checks(monkeypatch, tmp_path, latest=un.__version__)
    (tmp_path / "update-check.json").unlink()
    with patch("sys.argv", ["searchts", "doctor", "--json"]):
        main()
    assert "update_available" not in json.loads(capsys.readouterr().out)


def test_grab_json_manifest_has_update_available(monkeypatch, tmp_path, capsys):
    _enable_agent_checks(monkeypatch, tmp_path)
    manifest = {"url": "https://x.test/", "downloaded": 0, "assets": []}
    monkeypatch.setattr("searchts.assets.grab", lambda url, out, **kw: manifest)
    with patch("sys.argv", ["searchts", "grab", "https://x.test/", "--json"]):
        main()
    import json

    payload = json.loads(capsys.readouterr().out)
    assert payload["update_available"]["latest"] == "9.9.9"
    assert payload["downloaded"] == 0


def test_json_opt_out_disables_the_key(monkeypatch, tmp_path, capsys):
    _, calls = _enable_agent_checks(monkeypatch, tmp_path)
    monkeypatch.setenv("SEARCHTS_NO_UPDATE_CHECK", "1")
    captured = _read(
        monkeypatch, tmp_path, capsys,
        ["searchts", "read", "https://x.test", "--json"],
    )
    import json

    assert "update_available" not in json.loads(captured.out)
    assert calls["n"] == 0


# ── MCP ─────────────────────────────────────────────────────────────────────


def _mcp_read(monkeypatch, url="https://x.test"):
    with patch(
        "searchts.unlocker.fetch",
        return_value=FetchResult("curl_cffi", "# body", 200, final_url=url),
    ):
        return mcp_server.read_url(url)


def test_mcp_read_carries_info_and_one_note(monkeypatch, tmp_path):
    _enable_agent_checks(monkeypatch, tmp_path)
    import json

    first = json.loads(_mcp_read(monkeypatch))
    second = json.loads(_mcp_read(monkeypatch))
    assert first["update_available"]["latest"] == "9.9.9"
    assert "update_note" in first
    assert "Nothing was installed" in first["update_note"]
    assert second["update_available"]["latest"] == "9.9.9"
    assert "update_note" not in second


def test_mcp_get_status_always_carries_the_structured_field(monkeypatch, tmp_path):
    _enable_agent_checks(monkeypatch, tmp_path)

    class FakeSearchts:
        def doctor_report(self):
            return "unlocker: ok"

    monkeypatch.setattr("searchts.core.Searchts", FakeSearchts)
    out = mcp_server.get_status()
    assert "unlocker: ok" in out
    assert '"latest": "9.9.9"' in out


def test_mcp_opt_out_disables_info_and_note(monkeypatch, tmp_path):
    _, calls = _enable_agent_checks(monkeypatch, tmp_path)
    monkeypatch.setenv("SEARCHTS_NO_UPDATE_CHECK", "1")
    import json

    data = json.loads(_mcp_read(monkeypatch))
    assert "update_available" not in data
    assert "update_note" not in data
    assert calls["n"] == 0


def test_mcp_offline_is_silent(monkeypatch, tmp_path):
    monkeypatch.delenv("SEARCHTS_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(un, "cache_path", lambda: tmp_path / "c.json")
    monkeypatch.setattr(un, "_fetch_latest", lambda timeout=2.0: None)
    import json

    data = json.loads(_mcp_read(monkeypatch))
    assert "update_available" not in data


def test_mcp_note_not_repeated_within_24h_even_for_a_new_fetch(monkeypatch, tmp_path):
    _enable_agent_checks(monkeypatch, tmp_path)
    import json

    assert "update_note" in json.loads(_mcp_read(monkeypatch))
    assert "update_note" not in json.loads(_mcp_read(monkeypatch))
