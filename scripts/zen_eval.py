#!/usr/bin/env python3
"""The 5-PR reasoning proof on the Zen models, off vs max.

The Zen free tier answers `FreeTierError: OpenCode's free tier can only be used
from within OpenCode` to every direct HTTP call, so `hare_r1.py` cannot reach
these models at all and a Zen hop in the Action would never carry a reasoning
field. This harness therefore drives the client that *is* inside OpenCode
(`opencode run`), which is the only path that returns a review.

`--variant` is the reasoning control, and it is not a guess: it is the client
flag documented as "provider-specific reasoning effort", and the levels it
accepts per model come from the models.dev catalog the client itself reads
(`reasoning_options`, type `effort`). What each model publishes is recorded in
ZEN_REASONING below and printed in the report, so a model with no documented
dial says so instead of being measured at a level it does not have.

What "off" means here is stated in the report too: Zen publishes no way to turn
reasoning off for these models, so the off arm sends no reasoning parameter at
all. That is the default, not a disabled state.

Posts nothing anywhere. Writes one raw file per run under --raw-dir.

Usage:
    python scripts/zen_eval.py --raw-dir docs/proofs/hare-reasoning/zen
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
# read 2026-10-10. `variant` is what the max arm sends; None means the model
# publishes no effort dial, so max and off are the same request and the run
# proves nothing about reasoning on that model.
ZEN_REASONING: dict[str, dict[str, Any]] = {
    "step-5-preview-free": {"effort": ["low", "medium", "high"], "variant": "high"},
    "space-bunny-free": {"effort": ["low", "medium", "high", "xhigh", "max"], "variant": "max"},
    "mimo-v2.6-flash-free": {"effort": [], "variant": None},
    "muse-spark-1.3-contributor-free": {"effort": ["minimal", "low", "medium", "high", "xhigh"], "variant": "xhigh"},
}
DEFAULT_MODELS = ",".join(ZEN_REASONING)


def ask(model: str, variant: str | None, prompt: str, timeout: int) -> dict[str, Any]:
    """One completion through the OpenCode client. Returns the raw event text,
    the tokens the client reported, or the error."""
    cmd = ["opencode", "run", "--pure", "--format", "json", "-m", f"opencode/{model}"]
    if variant:
        cmd += ["--variant", variant]
    cmd += [prompt]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"error": f"timeout after {timeout}s", "text": "", "tokens": {}}
    if p.returncode != 0:
        return {"error": f"exit {p.returncode}: {(p.stderr or p.stdout)[-300:]}", "text": "", "tokens": {}}
    text: str = ""
    tokens: dict[str, Any] = {}
    err = ""
    for line in p.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        part = ev.get("part") or {}
        if ev.get("type") == "text" and part.get("text"):
            text += part["text"]
        if ev.get("type") == "step_finish":
            tokens = part.get("tokens") or {}
        if ev.get("type") in ("error", "step_finish") and part.get("error"):
            err = str(part.get("error"))[:300]
    return {"error": err, "text": text.strip(), "tokens": tokens}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cases", default="docs/hare-proof-cases.json")
    ap.add_argument("--models", default=DEFAULT_MODELS)
    ap.add_argument("--modes", default="off,max")
    ap.add_argument("--raw-dir", default="docs/proofs/hare-reasoning/zen")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--pause", type=float, default=3.0, help="seconds between calls, for the free tier")
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN", "") or subprocess.run(
        ["gh", "auth", "token"], capture_output=True, text=True
    ).stdout.strip()
    if not token:
        print("zen eval: no GitHub token, so the review prompts cannot be rebuilt")
        return 1
    owner_repo = os.environ.get("GITHUB_REPOSITORY", "capad-xyz/searchts")
    owner, _, repo = owner_repo.partition("/")
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    models = [m.strip() for m in args.models.split(",") if m.strip() in ZEN_REASONING]
    modes = [m.strip() for m in args.modes.split(",") if m.strip() in ("off", "max")]
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    for case in cases:
        built = hare_eval.build_case(owner, repo, case, token, with_graph=False)
        user = built["messages"][1]["content"]
        # The client sends one message; the contract and the prompt both travel
        # in it, so the model is asked for exactly the JSON the Action wants.
        prompt = hare_r1.SYSTEM + "\n\n" + user + "\n\nReturn only the JSON object."
        for model in models:
            spec = ZEN_REASONING[model]
            for mode in modes:
                # "off" sends no reasoning parameter: Zen publishes no way to
                # switch reasoning off for these models.
                variant = None if mode == "off" else spec["variant"]
                for attempt in range(args.repeat):
                    t0 = time.time()
                    got = ask(model, variant, prompt, args.timeout)
                    toks = got.get("tokens") or {}
                    body = {
                        "case": case["id"],
                        "pr": case["pr"],
                        "provider": "zen",
                        "model": model,
                        "mode": mode,
                        "graph": "off",
                        "attempt": attempt,
                        "request_options": {
                            "transport": "opencode run --pure --format json",
                            "variant": variant,
                            "published_effort": spec["effort"],
                        },
                        "error": got.get("error") or "",
                        "seconds": round(time.time() - t0, 1),
                        "usage": {
                            "prompt_tokens": toks.get("input") or 0,
                            "completion_tokens": toks.get("output") or 0,
                            "reasoning_tokens": toks.get("reasoning") or 0,
                        },
                        "answer": got.get("text") or "",
                    }
                    name = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{case['id']}__zen__{model}__{mode}__g0__{attempt}")
                    (raw_dir / f"{name}.json").write_text(json.dumps(body, indent=1), encoding="utf-8")
                    state = "ok" if body["answer"] and not body["error"] else f"ERR {body['error'][:80]}"
                    print(f"{case['id']} {model} {mode} variant={variant} -> {state} "
                          f"({body['seconds']}s, reasoning={body['usage']['reasoning_tokens']})", flush=True)
                    time.sleep(args.pause)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())