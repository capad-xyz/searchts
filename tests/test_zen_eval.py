import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import hare_eval  # noqa: E402
import hare_proof  # noqa: E402
import hare_r1  # noqa: E402
import zen_eval  # noqa: E402

MUSE = "muse-spark-1.3-contributor-free"
BUNNY = "space-bunny-free"
MIMO = "mimo-v2.6-flash-free"
ANSWER = '{"summary":"s","findings":[]}'
CASE = {"id": "c1", "pr": 7, "head": "abc", "expect": [
    {"path": "scripts/a.py", "line": 40, "words": ["memory"], "what": "holds it in memory", "by": "x"}]}


def _ev(kind: str, text: str = "") -> str:
    part = {"type": kind.replace("_", "-"), "time": {"end": 1}}
    if text:
        part["text"] = text
    return json.dumps({"type": kind, "timestamp": 1, "part": part})


def _step(**tokens: int) -> str:
    return json.dumps({"type": "step_finish", "part": {"type": "step-finish", "reason": "stop", "tokens": dict(tokens)}})


def _cases_file(tmp_path: Path) -> str:
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"cases": [CASE]}), encoding="utf-8")
    return str(path)


def _fake_ask(record: list, answer: str = ANSWER, error: str = "", reasoning: int = 512):
    def ask(model, variant, prompt, timeout):
        record.append((model, variant))
        if error:
            return {"error": error, "text": "", "answer_part": "", "reasoning_chars": 0, "tokens": {}, "steps": 0}
        return {"error": "", "text": answer, "answer_part": "text", "reasoning_chars": 9,
                "tokens": {"input": 4000, "output": 120, "reasoning": reasoning}, "steps": 1}
    return ask


class _Clock:
    """20 s per reading, so every cell's wall clock is a known number rather than
    a rounding artefact of a test that runs in microseconds."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        self.t += 20.0
        return self.t


def test_an_answer_that_lands_in_the_reasoning_part_is_the_answer() -> None:
    """Zen models front-load the answer while thinking. Reading only the text part
    is what made Mimo and Step 5 look empty, and Space Bunny look free."""
    only_reasoning = "\n".join([
        _ev("reasoning", f"First I read the diff. The answer is:\n{ANSWER}\n"),
        _step(input=3781, output=149, reasoning=463),
    ])
    got = zen_eval.read_stream(only_reasoning)
    assert ANSWER in got["text"] and got["answer_part"] == "reasoning" and got["error"] == ""
    assert hare_r1.extract_json(got["text"]) == {"summary": "s", "findings": []}, "the scorer still finds the object"
    assert got["tokens"] == {"input": 3781, "output": 149, "reasoning": 463} and got["steps"] == 1

    both = "\n".join([_ev("reasoning", "thinking about it"), _ev("text", ANSWER), _step(input=1, output=2, reasoning=3)])
    got = zen_eval.read_stream(both)
    assert got["answer_part"] == "text" and got["reasoning_chars"] == len("thinking about it")


def test_tokens_are_summed_over_every_step_not_the_last() -> None:
    """A run is several steps, and keeping only the last one reported a fraction
    of what the model actually spent."""
    stream = "\n".join([
        _ev("reasoning", "step one"), _ev("text", "partial "),
        _step(input=100, output=20, reasoning=200),
        _ev("reasoning", "step two"), _ev("text", ANSWER),
        _step(input=100, output=5, reasoning=30),
        "{not json", "",
    ])
    got = zen_eval.read_stream(stream)
    assert got["tokens"] == {"input": 200, "output": 25, "reasoning": 230} and got["steps"] == 2
    assert got["text"] == "partial " + ANSWER  # streamed parts are joined


def test_the_client_is_run_with_stdin_closed_and_thinking_on(monkeypatch) -> None:
    """`opencode run` inherits this process's stdin, so a run inherits a prompt
    nobody is here to answer; and the reasoning part only reaches a --format json
    stream when --thinking is on (cli/cmd/run.ts gates that event on it)."""
    seen: dict = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"], seen["kwargs"] = cmd, kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout=_ev("text", ANSWER), stderr="")

    monkeypatch.setattr(zen_eval.subprocess, "run", fake_run)
    zen_eval.ask(BUNNY, "xhigh", "p", 5)
    assert seen["kwargs"]["stdin"] is subprocess.DEVNULL
    assert "--thinking" in seen["cmd"]
    assert seen["cmd"][seen["cmd"].index("--variant") + 1] == "xhigh"
    assert seen["cmd"][:2] == ["opencode", "run"] and seen["cmd"][-1] == "p"

    zen_eval.ask(BUNNY, None, "p", 5)
    assert "--variant" not in seen["cmd"], "the default arm sends no reasoning parameter"


def test_a_timeout_or_a_nonzero_exit_is_an_error_not_a_dropped_cell(monkeypatch) -> None:
    def times_out(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 5)

    monkeypatch.setattr(zen_eval.subprocess, "run", times_out)
    got = zen_eval.ask(BUNNY, "max", "p", 5)
    assert got["error"] == "timeout after 5s" and got["text"] == "" and got["tokens"] == {}

    monkeypatch.setattr(zen_eval.subprocess, "run",
                        lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom"))
    assert zen_eval.ask(BUNNY, "max", "p", 5)["error"].startswith("exit 1: boom")


def test_the_default_arm_is_not_called_off_and_levels_are_checked_per_model() -> None:
    """Zen publishes no way to turn reasoning off, so naming that arm `off` had the
    table claiming a switch that does not exist. `--variant` drops a level a model
    does not publish without a word, so the check is per model."""
    assert zen_eval.DEFAULT_MODE == "default"
    assert zen_eval.modes_for(BUNNY, ["off"]) == [], "`off` is not a level Zen publishes"
    assert zen_eval.modes_for(BUNNY, ["default", "medium", "xhigh", "max"]) == ["default", "medium", "xhigh", "max"]
    assert zen_eval.modes_for(MUSE, ["default", "medium", "xhigh", "max"]) == ["default", "medium", "xhigh"]
    assert zen_eval.modes_for(MIMO, ["default", "max"]) == ["default"], "Mimo publishes no dial at all"
    assert zen_eval.modes_for(MUSE, ["minimal", "high"]) == ["minimal", "high"], "the ladder is not one size"
    for model, spec in zen_eval.ZEN_REASONING.items():
        for level in spec["effort"]:
            assert level in ("minimal", "low", "medium", "high", "xhigh", "max"), (model, level)


def test_a_run_writes_what_the_table_reads_and_the_table_prints_it(tmp_path, monkeypatch, capsys) -> None:
    """A raw file is the evidence, so its usage has to sit where hare_proof.py
    looks: `usage.completion_tokens_details.reasoning_tokens`. Written anywhere else
    the column reads zero for a run that spent 512 reasoning tokens."""
    asked: list = []
    monkeypatch.setattr(zen_eval, "ask", _fake_ask(asked))
    monkeypatch.setattr(zen_eval.time, "sleep", lambda s: None)
    monkeypatch.setattr(zen_eval.time, "time", _Clock())
    monkeypatch.setattr(hare_eval, "build_case", lambda *a, **k: {
        "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "the diff"}]})
    assert zen_eval.main(["--cases", _cases_file(tmp_path), "--raw-dir", str(tmp_path), "--models", f"{BUNNY},{MIMO}",
                          "--modes", "default,max", "--pause", "0"]) == 0

    body = json.loads((tmp_path / f"c1__zen__{BUNNY}__default__g0__0.json").read_text())
    assert body["usage"]["completion_tokens_details"]["reasoning_tokens"] == 512
    assert body["usage"]["prompt_tokens"] == 4000 and body["seconds"] == 20.0 and body["answer_part"] == "text"
    assert ("mimo-v2.6-flash-free", "max") not in asked, "a level the model does not publish is never sent"
    assert ("space-bunny-free", "max") in asked and ("space-bunny-free", None) in asked
    out = capsys.readouterr().out
    assert "mimo-v2.6-flash-free does not publish max" in out, "a skipped mode is named, not dropped"

    md = hare_proof.render(hare_proof.load(tmp_path), {})
    assert "| c1 | zen | `space-bunny-free` | default | 1 of 1 | 20 | 512 | - |" in md


def test_a_mode_no_zen_model_publishes_is_named_not_dropped(tmp_path, monkeypatch, capsys) -> None:
    """`off,on` measured only `off` once because the unknown name vanished without a
    word. An unknown level has to be printed and the rest still run."""
    monkeypatch.setattr(zen_eval, "ask", _fake_ask([]))
    monkeypatch.setattr(zen_eval.time, "sleep", lambda s: None)
    monkeypatch.setattr(hare_eval, "build_case", lambda *a, **k: {
        "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "d"}]})
    assert zen_eval.main(["--cases", _cases_file(tmp_path), "--raw-dir", str(tmp_path), "--models", BUNNY,
                          "--modes", "default,turbo", "--pause", "0"]) == 0
    assert "not a published level, skipped: turbo" in capsys.readouterr().out
    assert [p.name for p in tmp_path.glob("*.json") if p.name.startswith("c1")] == [
        "c1__zen__space-bunny-free__default__g0__0.json"]


def test_a_model_this_harness_does_not_measure_says_why(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(zen_eval, "ask", _fake_ask([]))
    assert zen_eval.main(["--raw-dir", str(tmp_path), "--models", "longcat-2.5-preview-free", "--modes", "default"]) == 1
    out = capsys.readouterr().out
    assert "longcat-2.5-preview-free is not run" in out and "toggle" in out
    assert not list(tmp_path.glob("*.json"))


def test_a_rate_limited_call_is_retried_once_because_it_is_not_a_result(tmp_path, monkeypatch) -> None:
    tried: list = []
    waited: list = []

    def busy_once(model, variant, prompt, timeout):
        tried.append(variant)
        if len(tried) == 1:
            return {"error": "ProviderModelError: 429 rate limit exceeded on the free tier",
                    "text": "", "answer_part": "", "reasoning_chars": 0, "tokens": {}, "steps": 0}
        return {"error": "", "text": ANSWER, "answer_part": "reasoning", "reasoning_chars": 4,
                "tokens": {"input": 10, "output": 20, "reasoning": 30}, "steps": 1}

    monkeypatch.setattr(zen_eval, "ask", busy_once)
    body = zen_eval.run_one(tmp_path, "c1", 1, BUNNY, "max", "p", 0, 5, 1, 0.0, sleeper=waited.append)
    assert len(tried) == 2 and waited == [20.0] and body["error"] == "" and body["answer_part"] == "reasoning"

    tried.clear()
    monkeypatch.setattr(zen_eval, "ask", lambda *a: {"error": "429 rate limit", "text": "", "answer_part": "",
                                                     "reasoning_chars": 0, "tokens": {}, "steps": 0})
    body = zen_eval.run_one(tmp_path, "c2", 2, BUNNY, "max", "p", 0, 5, 1, 0.0, sleeper=waited.append)
    assert body["error"].startswith("429") and "ERR" in zen_eval._state(body)
    assert "c2__zen__space-bunny-free__max__g0__0.json" in [p.name for p in tmp_path.iterdir()]
