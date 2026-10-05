import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import hare_eval  # noqa: E402
import hare_r1  # noqa: E402

CASE = {"id": "c1", "pr": 7, "head": "abc", "expect": [
    {"path": "scripts/a.py", "line": 40, "words": ["memory", "stream"], "what": "reads a whole log", "by": "x"},
    {"path": "AGENTS.md", "words": ["pending"], "what": "old rule", "by": "y"}]}
CLEAN = {"id": "c2", "pr": 8, "head": "def", "clean": True, "expect": []}


def test_findings_are_read_in_both_shapes_and_scored_against_the_key() -> None:
    fs = hare_eval.findings_of({"findings": [
        {"sev": "real", "path": "./scripts/a.py", "line": 50, "issue": "Reads the whole log into memory."},
        {"sev": "skip", "loc": "AGENTS.md:3", "issue": "Says a pending check means hold."},
        {"sev": "real", "path": "scripts/a.py", "line": 400, "issue": "memory, but far away"},
        "not a finding"]})
    assert [f["path"] for f in fs] == ["scripts/a.py", "AGENTS.md", "scripts/a.py"] and fs[1]["line"] == 3
    s = hare_eval.score(CASE, fs)
    assert s["caught"] == ["real", "skip"] and s["false_reals"] == 0 and s["reals"] == 2
    assert hare_eval.score(CLEAN, fs)["false_reals"] == 2  # every real on a clean case is a false alarm
    assert not hare_eval.matches(CASE["expect"][0], {"path": "scripts/b.py", "line": 40, "text": "memory"})


def test_run_builds_the_real_prompt_and_asks_each_provider_in_both_modes(monkeypatch) -> None:
    """Drives the real run() with only the network faked: GitHub and the model call."""
    def api(method, path, token, body=None, accept="application/vnd.github+json"):
        if "compare/main..." in path:
            return {"merge_base_commit": {"sha": "base1"}}
        if "compare/base1..." in path:
            return "diff --git a/scripts/a.py b/scripts/a.py\n+x = 1\n"
        if "/contents/" in path:
            raise RuntimeError("404")
        return {"title": "t", "body": "b"}

    calls = []

    def call(base, key, model, messages, opts, timeout=0):
        calls.append((model, opts))
        assert messages[0]["content"] == hare_r1.SYSTEM and "+x = 1" in messages[1]["content"]
        return json.dumps({"summary": "s", "findings": [{"sev": "real", "path": "scripts/a.py", "line": 41, "issue": "streams nothing, holds it in memory"}]})

    monkeypatch.setattr(hare_r1, "github_api", api)
    rows = hare_eval.run([CASE, CLEAN], ["openrouter", "groq"], ["off", "on"], {"openrouter": "k1", "groq": "k2"}, "t", "o", "r", call=call, pause=lambda s: None)
    assert len(rows) == 8 and {r["mode"] for r in rows} == {"off", "on"}
    assert {r["provider"] for r in rows} == {"openrouter", "groq"}
    first = next(r for r in rows if r["case"] == "c1")
    assert first["caught"] == ["real", ""] and not first["error"]
    assert any(opts != calls[0][1] for _, opts in calls)  # thinking on changes what is sent
    md = hare_eval.render(rows, [CASE, CLEAN], "2026-10-05")
    assert "| openrouter |" in md and "reads a whole log (x)" in md and "\u2014" not in md
    s = {(x["provider"], x["mode"]): x for x in hare_eval.summarize(rows)}
    assert s[("groq", "on")]["caught_real"] == 1 and s[("groq", "on")]["false_reals"] == 1


def test_a_failed_case_or_call_is_reported_not_fatal(monkeypatch) -> None:
    monkeypatch.setattr(hare_r1, "github_api", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    rows = hare_eval.run([CASE], ["groq"], ["off"], {"groq": "k"}, "t", "o", "r", call=lambda *a, **k: "", pause=lambda s: None)
    assert rows[0]["error"].startswith("case: down")


def test_the_answer_key_parses_and_every_case_names_files_and_words() -> None:
    cases = json.loads((Path(__file__).resolve().parents[1] / "docs" / "hare-eval-cases.json").read_text())["cases"]
    assert len(cases) >= 10 and any(c.get("clean") for c in cases)
    for c in cases:
        for e in c["expect"]:
            assert e["path"] and e["words"] and e["what"], c["id"]
