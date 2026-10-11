#!/usr/bin/env python3
"""The reasoning proof table, built from the raw answers under a directory.

Each raw file is one run: `scripts/hare_eval.py --raw-dir` wrote what was asked,
what came back, what it cost and what the stream carried. This reads those files
and prints the table the PR quotes, so the table is derived from the runs rather
than typed over them. It reads only the raw directory: no network, no keys, and
a reader can re-run it against the committed files and get the same table.

Usage:
    python scripts/hare_proof.py docs/proofs/hare-reasoning
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


def score_against_cases(rows: list[dict[str, Any]], raw_dir: Path, cases_file: Path) -> dict[str, Any]:
    """How each mode did against the ledger's ground truth, where the answers can
    still be matched. The eval's own scoring needs the messages it sent, so this
    re-runs only the matcher over the stored answers."""
    try:
        cases = {c["id"]: c for c in json.loads(cases_file.read_text(encoding="utf-8"))["cases"]}
    except (OSError, json.JSONDecodeError, KeyError):
        return {}
    sys_path = str(Path(__file__).resolve().parent)
    if sys_path not in __import__("sys").path:
        __import__("sys").path.insert(0, sys_path)
    try:
        import hare_eval  # noqa: PLC0415
    except ImportError:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for r in load(raw_dir):
        answer = r.get("answer")
        if not answer or r.get("error"):
            continue
        case = cases.get(str(r.get("case")))
        if not case:
            continue
        parsed = hare_eval.hare_r1.extract_json(str(answer))
        found = hare_eval.findings_of(parsed)
        caught = hare_eval.score(case, found)
        mode_key = f"{r.get('mode')}|{r.get('provider')}"
        slot = out.setdefault(mode_key, {"caught_real": 0, "caught_any": 0, "expected": 0, "false_reals": 0, "answers": 0})
        slot["answers"] += 1
        slot["caught_real"] += int(sum(c == "real" for c in caught.get("caught") or []))
        slot["caught_any"] += int(sum(bool(c) for c in caught.get("caught") or []))
        slot["expected"] += len(case.get("expect") or [])
        slot["false_reals"] += int(caught.get("false_reals") or 0)
    return out


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
        lines += ["", "## Runs that returned nothing", ""]
        seen: set[tuple[str, str, str]] = set()
        for r in failures:
            marker = (r["provider"], r["mode"], r["why"][:120])
            if marker in seen:
                continue
            seen.add(marker)
            lines.append(f"- `{r['provider']}` mode `{r['mode']}` ({r['runs']} runs): {r['why'][:300]}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("raw_dir", help="directory of raw run files written by --raw-dir")
    ap.add_argument("--cases", default="docs/hare-proof-cases.json", help="the answer key to score against")
    args = ap.parse_args(argv)
    raw_dir = Path(args.raw_dir)
    if not raw_dir.is_dir():
        print(f"hare proof: {raw_dir} is not a directory")
        return 1
    runs = load(raw_dir)
    if not runs:
        print(f"hare proof: no runs in {raw_dir}")
        return 1
    scores = score_against_cases(runs, raw_dir, Path(args.cases))
    print(render(runs, scores))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
