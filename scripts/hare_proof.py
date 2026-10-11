#!/usr/bin/env python3
"""The reasoning proof table, built from the raw answers under a directory.

Each raw file is one run: `scripts/hare_eval.py --raw-dir` wrote what was asked,
what came back, what it cost and what the stream carried. This reads those files
and prints the table the PR quotes, so the table is derived from the runs rather
than typed over them. It reads only the raw directory: no network, no keys, and
a reader can re-run it against the committed files and get the same table.

`--by-model` is the other view: one row per model and level across every case,
with the cost beside the quality and #258's known-wrong finding on its own
column, because a run that reproduces it as `real` has not caught anything.

Usage:
    python scripts/hare_proof.py docs/proofs/hare-reasoning
    python scripts/hare_proof.py docs/proofs/hare-reasoning/zen --by-model
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def load(raw_dir: Path) -> list[dict[str, Any]]:
    """Every raw run, newest shape first. A file that will not parse is skipped
    rather than fatal: one truncated upload should not hide the other fifty."""
    runs: list[dict[str, Any]] = []
    for path in sorted(raw_dir.glob("*.json")):
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(body, dict) and body.get("provider"):
            body["_file"] = path.name
            runs.append(body)
    return runs


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def summarize(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per (case, provider, model, mode): did it answer, what did it cost."""
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in runs:
        key = (str(r.get("case")), str(r.get("provider")), str(r.get("model")), str(r.get("mode")))
        groups[key].append(r)
    rows: list[dict[str, Any]] = []
    for (case, provider, model, mode), rs in sorted(groups.items()):
        ok = [r for r in rs if not r.get("error") and str(r.get("answer") or "").strip()]
        reasoning = [
            int((r.get("usage") or {}).get("completion_tokens_details", {}).get("reasoning_tokens") or 0)
            for r in ok
        ]
        caps = sorted({e for r in rs for e in (r.get("caps_fired") or [])})
        rows.append(
            {
                "case": case,
                "pr": rs[0].get("pr"),
                "provider": provider,
                "model": model,
                "mode": mode,
                "runs": len(rs),
                "answered": len(ok),
                "seconds": _median([float(r.get("seconds") or 0) for r in ok]),
                "reasoning_tokens": _median([float(x) for x in reasoning]),
                "caps_fired": caps,
                "why": next((str(r.get("error")) for r in rs if r.get("error")), ""),
            }
        )
    return rows


def _cases(cases_file: Path) -> dict[str, Any]:
    try:
        return {c["id"]: c for c in json.loads(cases_file.read_text(encoding="utf-8"))["cases"]}
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return {}


def _hare_eval():
    """The matcher, imported the way this script already does it: the proof table
    runs out of a checkout with the scripts beside it, not out of a package."""
    sys_path = str(Path(__file__).resolve().parent)
    if sys_path not in __import__("sys").path:
        __import__("sys").path.insert(0, sys_path)
    try:
        import hare_eval  # noqa: PLC0415
    except ImportError:
        return None
    return hare_eval


def _scored(runs: list[dict[str, Any]], cases: dict[str, Any]):
    """(run, case, findings, caught) for every run whose answer still matches a
    case. The eval's own scoring needs the messages it sent, so this re-runs only
    the matcher over the stored answers."""
    hare_eval = _hare_eval()
    if hare_eval is None:
        return
    for r in runs:
        answer = r.get("answer")
        if not answer or r.get("error"):
            continue
        case = cases.get(str(r.get("case")))
        if not case:
            continue
        found = hare_eval.findings_of(hare_eval.hare_r1.extract_json(str(answer)))
        yield r, case, found, hare_eval.score(case, found)


def score_against_cases(rows: list[dict[str, Any]], raw_dir: Path, cases_file: Path) -> dict[str, Any]:
    """How each mode did against the ledger's ground truth, where the answers can
    still be matched. The eval's own scoring needs the messages it sent, so this
    re-runs only the matcher over the stored answers."""
    cases = _cases(cases_file)
    if not cases:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for r, case, _found, caught in _scored(load(raw_dir), cases):
        mode_key = f"{r.get('mode')}|{r.get('provider')}"
        slot = out.setdefault(mode_key, {"caught_real": 0, "caught_any": 0, "expected": 0, "false_reals": 0, "answers": 0})
        slot["answers"] += 1
        slot["caught_real"] += int(sum(c == "real" for c in caught.get("caught") or []))
        slot["caught_any"] += int(sum(bool(c) for c in caught.get("caught") or []))
        slot["expected"] += len(case.get("expect") or [])
        slot["false_reals"] += int(caught.get("false_reals") or 0)
    return out


def score_by_model(runs: list[dict[str, Any]], raw_dir: Path, cases_file: Path) -> dict[str, Any]:
    """One row per model and level, across every case: what it caught, what it
    wrote that was not there, and what it spent.

    #258 is why this is not the same sum as `score_against_cases`. That one
    finding is known to be wrong, so a run that reproduces it as `real` has made
    the same mistake again and counting it as caught would reward it. It is
    reported on its own column, and it is never in `expected`.
    """
    cases = _cases(cases_file)
    if not cases:
        return {}
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    answered: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in runs:
        # Only the answer key's cases are scored. A run of some other prompt (the
        # tiny re-check, say) has no ground truth to be caught against, and a row
        # that counted it would show "expected 0" against a model that looks blind.
        if str(r.get("case")) not in cases:
            continue
        key = (str(r.get("provider")), str(r.get("model")), str(r.get("mode")))
        answered[key].append(r)
    for key, rs in answered.items():
        ok = [r for r in rs if not r.get("error") and str(r.get("answer") or "").strip()]
        out[key] = {
            "runs": len(rs),
            "answered": len(ok),
            "median_s": _median([float(r.get("seconds") or 0) for r in ok]),
            "median_reasoning": _median([
                float(((r.get("usage") or {}).get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
                for r in ok
            ]),
            "answers": 0,
            "empty": 0,
            "caught_real": 0,
            "expected_real": 0,
            "wrong": 0,
            "reals": 0,
            "false_reals": 0,
        }
    for r, case, found, caught in _scored(runs, cases):
        slot = out[(str(r.get("provider")), str(r.get("model")), str(r.get("mode")))]
        marks = caught.get("caught") or []
        slot["answers"] += 1
        slot["empty"] += int(not found)
        slot["reals"] += int(caught.get("reals") or 0)
        slot["false_reals"] += int(caught.get("false_reals") or 0)
        for e, mark in zip(case.get("expect") or [], marks):
            if e.get("fate") == "wrong":
                slot["wrong"] += int(mark == "real")
            elif e.get("verdict") == "real":
                slot["expected_real"] += 1
                slot["caught_real"] += int(mark == "real")
    return out


def render_by_model(runs: list[dict[str, Any]], scores: dict[tuple[str, str, str], dict[str, Any]]) -> str:
    """Per model and level: the cost beside the quality, because one without the
    other is not a result."""

    def num(v: Any, suffix: str = "") -> str:
        return "-" if v is None else f"{v:,.0f}{suffix}"

    lines = [
        "| Model | Level | Answered | Empty | Real caught | Expected | Wrong (#258) | Reals written | Median reasoning tok | Median s |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for (provider, model, mode), s in sorted(scores.items()):
        lines.append(
            f"| `{model}` | {mode} | {s['answered']} of {s['runs']} | {s['empty']} | {s['caught_real']} "
            f"| {s['expected_real']} | {s['wrong']} | {s['reals']} "
            f"| {num(s['median_reasoning'])} | {num(s['median_s'])} |"
        )
    return "\n".join(lines) + "\n"


def render(runs: list[dict[str, Any]], scores: dict[str, Any]) -> str:
    rows = summarize(runs)
    lines = [
        "| Case | Provider | Model | Mode | Answered | Median s | Median reasoning tokens | Caps that fired |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        def num(v: Any) -> str:
            return "-" if v is None else f"{v:,.0f}"

        secs = r["seconds"]
        think = r["reasoning_tokens"]
        lines.append(
            f"| {r['case']} | {r['provider']} | `{r['model']}` | {r['mode']} | {r['answered']} of {r['runs']} | "
            f"{'-' if secs is None else f'{secs:.0f}'} | {num(think)} | {', '.join(r['caps_fired']) or '-'} |"
        )
    if scores:
        lines += [
            "",
            "## Against the ledger's ground truth",
            "",
            "| Mode | Provider | Answers | Caught as real | Caught at all | Expected | Reals on clean PRs |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for key in sorted(scores):
            mode, _, provider = key.partition("|")
            s = scores[key]
            lines.append(
                f"| {mode} | {provider} | {s['answers']} | {s['caught_real']} | {s['caught_any']} "
                f"| {s['expected']} | {s['false_reals']} |"
            )
    failures = [r for r in rows if r["answered"] == 0 and r["why"]]
    if failures:
        lines += ["", "## Cells that returned nothing (partial, never dropped)", ""]
        seen: set[tuple[str, str, str, str]] = set()
        for r in failures:
            marker = (r["provider"], r["model"], r["mode"], r["why"][:120])
            if marker in seen:
                continue
            seen.add(marker)
            lines.append(
                f"- `{r['provider']}` `{r['model']}` mode `{r['mode']}` ({r['runs']} runs): {r['why'][:300]}"
            )
    return "\n".join(lines) + "\n"


def document(runs: list[dict[str, Any]], scores: dict[tuple[str, str, str], dict[str, Any]], raw_dir: Path) -> str:
    """The whole markdown file for a `--by-model` proof, so the file on disk is
    produced by running the script rather than by typing the numbers over it."""
    arms: dict[str, set[str]] = defaultdict(set)
    cases: set[str] = set()
    runs_per_arm: dict[tuple[str, str], int] = defaultdict(int)
    for r in runs:
        model, mode = str(r.get("model")), str(r.get("mode"))
        arms[model].add(mode)
        cases.add(str(r.get("case")))
        runs_per_arm[(model, mode)] += 1
    ran = ["| Model | Arms | Calls |", "| --- | --- | --- |"]
    for model in sorted(arms):
        modes = sorted(arms[model], key=lambda m: (m != "default", m))
        ran.append(f"| `{model}` | {', '.join(modes)} | {sum(runs_per_arm[(model, m)] for m in modes)} |")
    # A cell that outlasted its own timeout is not a timeout: subprocess.run kills
    # the client and then waits for its pipes, so the cap is a soft wall. The raws
    # carry the seconds it really took, and this says so instead of hiding it.
    over = sorted(
        (r for r in runs if float(r.get("seconds") or 0) > 900 and not r.get("error")),
        key=lambda r: -float(r.get("seconds") or 0),
    )
    late = ["", "## Cells that outran their own timeout", ""]
    for r in over:
        late.append(f"- `{r['model']}` {r['mode']} on {r['case']}: {float(r['seconds']):,.0f} s, and it answered.")
    if len(over) == 1:
        late.append("")
        late.append("One cell like this is noise; several are a fact about the cap, not about the model.")
    return "\n".join([
        "# Zen reasoning proof: five PRs, every published level",
        "",
        "Built from the raw runs in [`zen/`](zen/) by",
        "",
        "```bash",
        "python scripts/hare_proof.py docs/proofs/hare-reasoning/zen --by-model \\",
        "    --out docs/proofs/hare-reasoning/zen-table.md",
        "```",
        "",
        "Nothing in this file is typed by hand. Re-run that command and it rewrites",
        "itself from the same files, the same way",
        "[`table.md`](table.md) is built from the runs above it.",
        "",
        "## What was run",
        "",
        "\n".join(ran),
        "",
        f"{len(cases)} prompts, the five PRs of the answer key plus the tiny one, one",
        "call per model per level per prompt. `default` is the no-variant arm: Zen",
        "publishes no way to turn reasoning off, so it is whatever the model does on",
        "its own, not a disabled state. A cell that errored or timed out is reported",
        "as partial: it is never dropped and never counted as an answer.",
        *late,
        "",
        "## Per model and level",
        "",
        render_by_model(runs, scores),
        "",
        "Scored against [`hare-proof-cases.json`](../../hare-proof-cases.json), the five",
        "PRs only. `Wrong (#258)` is the one column where a higher number is worse:",
        "that finding is known to be wrong, so a run that repeats it as `real` has made",
        "the same mistake again. `Empty` is an answer that parsed and carried no",
        "findings at all. `Expected` counts only the cases that answered, so a model",
        "is not charged for a finding it never had the chance to see.",
        "",
        "## Per case",
        "",
        render(runs, {}),
    ]) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("raw_dir", help="directory of raw run files written by --raw-dir")
    ap.add_argument("--cases", default="docs/hare-proof-cases.json", help="the answer key to score against")
    ap.add_argument("--by-model", action="store_true",
                    help="one row per model and level across every case, with the wrong finding on its own column")
    ap.add_argument("--out", default="", help="write the markdown here instead of printing it")
    args = ap.parse_args(argv)
    raw_dir = Path(args.raw_dir)
    if not raw_dir.is_dir():
        print(f"hare proof: {raw_dir} is not a directory")
        return 1
    runs = load(raw_dir)
    if not runs:
        print(f"hare proof: no runs in {raw_dir}")
        return 1
    if args.by_model:
        scores = score_by_model(runs, raw_dir, Path(args.cases))
        doc = document(runs, scores, raw_dir)
    else:
        doc = render(runs, score_against_cases(runs, raw_dir, Path(args.cases)))
    if args.out:
        Path(args.out).write_text(doc, encoding="utf-8")
        print(f"hare proof: wrote {args.out} from {len(runs)} runs")
    else:
        print(doc, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
