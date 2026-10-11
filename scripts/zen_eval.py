#!/usr/bin/env python3
"""The 5-PR reasoning proof on the Zen free models: every published level, side by side.

Four of the five Zen free models answer a direct HTTP call with `FreeTierError:
OpenCode's free tier can only be used from within OpenCode`, so `hare_r1.py`
cannot reach them at all and a Zen hop in the Action would never carry a reasoning
field. `space-bunny-free` is the exception and answers a direct call (measured
2026-10-11; `docs/hare-next.md`). Either way this harness drives the client that
*is* inside OpenCode (`opencode run`), which is the only path that returns a
review for all five.

`--variant` is the reasoning control, and it is not a guess: it is the client
flag documented as "provider-specific reasoning effort", and the levels it
accepts per model come from the models.dev catalog the client itself reads
(`reasoning_options`, type `effort`). What each model publishes is recorded in
ZEN_REASONING below and printed in the report, so a model with no documented dial
says so instead of being measured at a level it does not have.

The no-variant arm is named `default`, not `off`. Zen publishes no way to turn
reasoning off for these models, so that arm sends no reasoning parameter at all:
it measures whatever the model does on its own, which is a real data point and
not the same thing as reasoning disabled. `--modes` therefore takes `default` or
any published level, checked per model, so one run can carry `default,max` for
Space Bunny and `default,xhigh` for Muse.

Four things the stream carries, all of which used to make a run look emptier or
cheaper than it was:

  - the answer can land in the `reasoning` part rather than the `text` part, so
    both are read and `answer_part` says which one it was. `--thinking` is what
    puts the reasoning part in a `--format json` stream at all: the client gates
    that event on it (`cli/cmd/run.ts`).
  - a run is several steps, so tokens are summed over every `step_finish`, not
    read off the last one.
  - usage is written where `scripts/hare_proof.py` reads it, under
    `usage.completion_tokens_details.reasoning_tokens`, so the table is not a
    column of zeroes. The seconds are written next to it and the table prints
    them.
  - stdin is closed. `opencode run` inherits this process's stdin and will sit
    on a prompt nobody is here to answer.

Posts nothing anywhere. Writes one raw file per run under --raw-dir, and a run
that errored or timed out is written as an error, never dropped.

Usage:
    python scripts/zen_eval.py --raw-dir docs/proofs/hare-reasoning/zen \
        --models space-bunny-free --modes default,max
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hare_eval  # noqa: E402
import hare_r1  # noqa: E402

# What each Zen model publishes, from models.dev (the catalog opencode reads),
# read 2026-10-10 and re-read 2026-10-11. `effort` is the list `--variant`
# accepts; empty means the model publishes no dial, so `default` is its only arm
# and there is nothing to A/B against it.
ZEN_REASONING: dict[str, dict[str, Any]] = {
    "space-bunny-free": {"effort": ["low", "medium", "high", "xhigh", "max"]},
    "muse-spark-1.3-contributor-free": {"effort": ["minimal", "low", "medium", "high", "xhigh"]},
    "step-5-preview-free": {"effort": ["low", "medium", "high"]},
    "mimo-v2.6-flash-free": {"effort": []},
}
DEFAULT_MODELS = ",".join(ZEN_REASONING)
# The arm that sends no reasoning parameter at all: the model's own default,
# which for a Zen model is never "off" and often is not even adjustable.
DEFAULT_MODE = "default"
# LongCat publishes a toggle, not an effort dial, and the client cannot express
# it: `--variant` sends `reasoning_effort`, which LongCat does not document, and
# four tiny calls at four settings answered identically (65/82/72/70 reasoning
# tokens, the same "equivalent" verdict). The one route that really switches
# thinking is a config-level `options.thinking.type` body, which is a second
# harness rather than a `--modes` value. Named here so `--models longcat...`
# says why it is not run instead of dropping the name.
ZEN_SKIPPED: dict[str, str] = {
    "longcat-2.5-preview-free": (
        "publishes a thinking toggle the client cannot send; --variant sends reasoning_effort "
        "and the arm would repeat the same request, so it proves nothing about reasoning"
    ),
}


def modes_for(model: str, modes: list[str]) -> list[str]:
    """The requested modes this model can actually run, in the order asked.

    `default` always runs. A published level runs on the model that publishes it,
    and is named as skipped on the ones that do not rather than silently dropped:
    a dropped mode is how `off,on` measured only `off` once and said nothing.
    """
    published = set(ZEN_REASONING.get(model, {}).get("effort") or [])
    return [m for m in modes if m == DEFAULT_MODE or m in published]


def published_note(model: str) -> str:
    levels = ZEN_REASONING.get(model, {}).get("effort") or []
    return ", ".join([DEFAULT_MODE, *levels]) if levels else f"{DEFAULT_MODE} only (no dial published)"


def _sum_tokens(tokens: dict[str, int], part: dict[str, Any]) -> None:
    """Add one step's usage onto the run total. A run is several steps and the
    last one is not the run."""
    for key in ("input", "output", "reasoning"):
        tokens[key] += int((part.get("tokens") or {}).get(key) or 0)


def read_stream(stdout: str) -> dict[str, Any]:
    """What one `opencode run --format json` stream carried.

    The answer is the `text` part when it has one, and the `reasoning` part when
    it does not: a model that writes its answer while thinking leaves the text
    part empty, and that run answered. `answer_part` says which happened, so the
    table can be read either way.
    """
    text = reasoning_text = err = ""
    tokens = {"input": 0, "output": 0, "reasoning": 0}
    steps = 0
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        part = ev.get("part") or {}
        kind = ev.get("type")
        if kind == "text" and part.get("text"):
            text += str(part["text"])
        elif kind == "reasoning" and part.get("text"):
            reasoning_text += str(part["text"])
        elif kind == "step_finish":
            steps += 1
            _sum_tokens(tokens, part)
        if kind in ("error", "step_finish") and part.get("error"):
            err = str(part.get("error"))[:300]
    text, reasoning_text = text.strip(), reasoning_text.strip()
    if text:
        answer, where = text, "text"
    elif reasoning_text:
        answer, where = reasoning_text, "reasoning"
    else:
        answer, where = "", ""
    return {
        "error": err,
        "text": answer,
        "answer_part": where,
        "reasoning_chars": len(reasoning_text),
        "tokens": tokens,
        "steps": steps,
    }


def ask(model: str, variant: str | None, prompt: str, timeout: int) -> dict[str, Any]:
    """One completion through the OpenCode client, with stdin closed."""
    cmd = ["opencode", "run", "--pure", "--thinking", "--format", "json", "-m", f"opencode/{model}"]
    if variant:
        cmd += ["--variant", variant]
    cmd += [prompt]
    try:
        p = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"error": f"timeout after {timeout}s", "text": "", "answer_part": "",
                "reasoning_chars": 0, "tokens": {}, "steps": 0}
    if p.returncode != 0:
        return {"error": f"exit {p.returncode}: {(p.stderr or p.stdout)[-300:]}", "text": "",
                "answer_part": "", "reasoning_chars": 0, "tokens": {}, "steps": 0}
    return read_stream(p.stdout)


def _rate_limited(error: str) -> bool:
    return bool(hare_eval.RATE.search(error or ""))


def run_one(
    raw_dir: Path,
    case_id: str,
    pr: int,
    model: str,
    mode: str,
    prompt: str,
    attempt: int,
    timeout: int,
    rate_retries: int,
    pause: float,
    sleeper=time.sleep,
) -> dict[str, Any]:
    """One cell of the matrix, retried once if the shared free tier said 429.

    A rate limit is not a result: it is another agent's call landing first, and
    the cell is retried once rather than written down as a model that could not
    answer. Every other error is the answer, and is written with its cause.
    """
    spec = ZEN_REASONING[model]
    variant = None if mode == DEFAULT_MODE else mode
    t0 = time.time()
    got: dict[str, Any] = {}
    for try_no in range(rate_retries + 1):
        got = ask(model, variant, prompt, timeout)
        if not _rate_limited(str(got.get("error") or "")) or try_no == rate_retries:
            break
        sleeper(max(pause, 20.0))
        t0 = time.time()
    toks = got.get("tokens") or {}
    body = {
        "case": case_id,
        "pr": pr,
        "provider": "zen",
        "model": model,
        "mode": mode,
        "graph": "off",
        "attempt": attempt,
        "request_options": {
            "transport": "opencode run --pure --thinking --format json",
            "variant": variant,
            "published_effort": spec["effort"],
        },
        "error": got.get("error") or "",
        "seconds": round(time.time() - t0, 1),
        "steps": got.get("steps") or 0,
        "answer_part": got.get("answer_part") or "",
        "reasoning_chars": got.get("reasoning_chars") or 0,
        "usage": {
            "prompt_tokens": toks.get("input") or 0,
            "completion_tokens": toks.get("output") or 0,
            "completion_tokens_details": {"reasoning_tokens": toks.get("reasoning") or 0},
        },
        "answer": got.get("text") or "",
    }
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{case_id}__zen__{model}__{mode}__g0__{attempt}")
    (raw_dir / f"{name}.json").write_text(json.dumps(body, indent=1), encoding="utf-8")
    return body


def _state(body: dict[str, Any]) -> str:
    if body["answer"] and not body["error"]:
        return f"ok ({body['answer_part']} part)"
    return f"ERR {body['error'][:90] or 'no answer'}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cases", default="docs/hare-proof-cases.json")
    ap.add_argument("--models", default=DEFAULT_MODELS)
    ap.add_argument("--modes", default="default,max")
    ap.add_argument("--raw-dir", default="docs/proofs/hare-reasoning/zen")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--pause", type=float, default=3.0, help="seconds between calls, for the free tier")
    ap.add_argument("--rate-retries", type=int, default=1, help="retries for a rate-limited call, which is not a result")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--tiny", metavar="FILE", default="", help="run one prompt file instead of the PR cases, as case `tiny-prompt`")
    args = ap.parse_args(argv)

    asked_models = [m.strip() for m in args.models.split(",") if m.strip()]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    unknown_models = [m for m in asked_models if m not in ZEN_REASONING and m not in ZEN_SKIPPED]
    for m in unknown_models:
        print(f"zen eval: {m} is not one of the Zen models measured here, skipped "
              f"({', '.join(ZEN_REASONING)}); {ZEN_SKIPPED.get(m, '')}")
    for m in asked_models:
        if m in ZEN_SKIPPED:
            print(f"zen eval: {m} is not run: {ZEN_SKIPPED[m]}")
    models = [m for m in asked_models if m in ZEN_REASONING]
    # A mode no model in the table publishes is a typo, and a typo that is dropped
    # is a run that measured less than it said.
    published_everywhere = {lvl for spec in ZEN_REASONING.values() for lvl in spec["effort"]}
    unknown_modes = [m for m in modes if m != DEFAULT_MODE and m not in published_everywhere]
    if unknown_modes:
        print(f"zen eval: not a published level, skipped: {', '.join(unknown_modes)} "
              f"(a mode is `{DEFAULT_MODE}` or a level some model publishes: {', '.join(sorted(published_everywhere))})")
    modes = [m for m in modes if m not in unknown_modes]
    if not models or not modes:
        print("zen eval: nothing to run")
        return 1

    units: list[tuple[str, int, str]] = []
    if args.tiny:
        # One prompt, every model and level, written as its own case so the raws
        # are evidence a reader can open rather than a claim in a table.
        units.append(("tiny-prompt", 0, Path(args.tiny).read_text(encoding="utf-8")))
    else:
        token = os.environ.get("GITHUB_TOKEN", "") or subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, stdin=subprocess.DEVNULL
        ).stdout.strip()
        if not token:
            print("zen eval: no GitHub token, so the review prompts cannot be rebuilt")
            return 1
        owner, _, repo = os.environ.get("GITHUB_REPOSITORY", "capad-xyz/searchts").partition("/")
        for case in json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]:
            built = hare_eval.build_case(owner, repo, case, token, with_graph=False)
            user = built["messages"][1]["content"]
            # The client sends one message; the contract and the prompt both
            # travel in it, so the model is asked for exactly the JSON the
            # Action wants.
            units.append((case["id"], case["pr"], hare_r1.SYSTEM + "\n\n" + user + "\n\nReturn only the JSON object."))

    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    print(f"zen eval: {len(models)} models, modes {', '.join(modes)}, "
          f"{len(units)} prompts, raws in {raw_dir}", flush=True)

    for case_id, pr, prompt in units:
        for model in models:
            runnable = modes_for(model, modes)
            dropped = [m for m in modes if m not in runnable]
            if dropped:
                print(f"zen eval: {model} does not publish {', '.join(dropped)}; "
                      f"skipped for that model (it takes: {published_note(model)})", flush=True)
            for mode in runnable:
                for attempt in range(args.repeat):
                    body = run_one(raw_dir, case_id, pr, model, mode, prompt, attempt,
                                   args.timeout, args.rate_retries, args.pause)
                    print(f"{case_id} {model} {mode} variant={body['request_options']['variant']} "
                          f"-> {_state(body)} ({body['seconds']}s, "
                          f"reasoning={body['usage']['completion_tokens_details']['reasoning_tokens']})", flush=True)
                    time.sleep(args.pause)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
