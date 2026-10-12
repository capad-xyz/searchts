#!/usr/bin/env python3
"""Re-score the proof raws with detection split from severity.

One number was doing three jobs. `caught real` required a model to name the
issue AND agree with the ledger's severity AND file it against the same file. A
run that found everything and filed it against a neighbouring file read as
finding nothing, which is how "0 of 4" came to mean "does not detect".

This prints the three apart, and keeps #258 pinned: its finding is known to be
WRONG, so a matcher this looser must still refuse to credit it.

Usage:
    python scripts/hare_rescore.py
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hare_eval  # noqa: E402
import hare_r1  # noqa: E402

# The trap. #258's expected finding was judged wrong by the owner, so crediting
# it is the failure a looser matcher buys. Every rule below has to hold here.
TRAP = "258-proof"


def rescore(raw_glob: str, cases_file: Path) -> list[dict[str, Any]]:
    cases = {c["id"]: c for c in json.loads(cases_file.read_text(encoding="utf-8"))["cases"]}
    rows: list[dict[str, Any]] = []
    for path in sorted(glob.glob(raw_glob, recursive=True)):
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(d, dict) or not d.get("provider") or not d.get("case"):
            continue
        case = cases.get(str(d["case"]))
        if case is None:
            continue
        answer = str(d.get("answer") or "")
        answered = bool(answer.strip()) and not d.get("error")
        parsed = hare_r1.extract_json(answer) if answered else None
        findings = hare_eval.findings_of(parsed)
        s = hare_eval.score(case, findings) if answered else {}
        rows.append(
            {
                "case": d["case"],
                "provider": d.get("provider"),
                "model": d.get("model"),
                "mode": d.get("mode"),
                "answered": answered,
                "found": s.get("n_found", 0),
                "caught_real": s.get("n_caught_real", 0),
                "misfiled": s.get("n_misfiled", 0),
                "expected": len(case.get("expect") or []),
                "unexpected": s.get("unexpected", 0),
                "seconds": d.get("seconds") or 0,
            }
        )
    return rows


def check_trap(
    rows: list[dict[str, Any]], cases: dict[str, dict[str, Any]], raw_glob: str
) -> tuple[list[str], list[str]]:
    """Everything that would break if the matcher went too loose.

    The trap is ONE expectation on #258, the one the ledger records as `wrong`.
    The rest of that case is ordinary catchable material - two line-length
    findings - so matching those is correct and must not fail this check. The
    first version of it failed every run on #258 for exactly that reason, which
    is what a guard that cannot tell a trap from a fixture looks like.
    """
    problems: list[str] = []
    near: list[str] = []
    trap_expects = [e for e in cases.get(TRAP, {}).get("expect") or [] if e.get("fate") == "wrong"]
    if not trap_expects:
        return [f"{TRAP} has no expectation marked fate=wrong, so the trap cannot be tested"], []
    for path in sorted(glob.glob(raw_glob, recursive=True)):
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(d, dict) or d.get("case") != TRAP or d.get("error"):
            continue
        answer = str(d.get("answer") or "")
        if not answer.strip():
            continue
        findings = hare_eval.findings_of(hare_r1.extract_json(answer))
        for e in trap_expects:
            strict = [f for f in findings if hare_eval.matches(e, f)]
            loose = [f for f in findings if hare_eval.words_match(e, f)]
            as_real = [f for f in strict if f["sev"] == "real"]
            if as_real:
                problems.append(
                    f"{TRAP} {d.get('model')} {d.get('mode')}: called the known-wrong finding REAL - trap sprung"
                )
            elif strict:
                # Detected but not called real. That is the severity split doing
                # its job, and it is why "did it repeat the mistake" and "did it
                # mention it" are different questions.
                near.append(
                    f"{TRAP} {d.get('model')} {d.get('mode')}: named the known-wrong finding, filed it {e.get('path')} as skip"
                )
            elif loose:
                near.append(
                    f"{TRAP} {d.get('model')} {d.get('mode')}: word-matched it but filed at {[f['path'] for f in loose]}"
                )
    return problems, near


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--raw", default="docs/proofs/hare-reasoning/**/*.json")
    ap.add_argument("--cases", default="docs/hare-proof-cases.json")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)

    rows = rescore(args.raw, Path(args.cases))
    ok = [r for r in rows if r["answered"]]
    if not ok:
        print("hare rescore: no answered runs")
        return 1

    print("Detection vs severity vs filing, per cell group\n")
    print("| Provider | Model | Mode | Runs | Found | Real+right file | Misfiled | Expected | Unexpected reals |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in ok:
        groups[(str(r["provider"]), str(r["model"]), str(r["mode"]))].append(r)
    for key, rs in sorted(groups.items()):
        print(
            f"| {key[0]} | `{key[1]}` | {key[2]} | {len(rs)} | "
            f"{sum(r['found'] for r in rs)} | {sum(r['caught_real'] for r in rs)} | "
            f"{sum(r['misfiled'] for r in rs)} | {sum(r['expected'] for r in rs)} | "
            f"{sum(r['unexpected'] for r in rs)} |"
        )

    tot_found = sum(r["found"] for r in ok)
    tot_real = sum(r["caught_real"] for r in ok)
    tot_mis = sum(r["misfiled"] for r in ok)
    tot_exp = sum(r["expected"] for r in ok)
    tot_unexp = sum(r["unexpected"] for r in ok)
    print(
        f"\nAcross {len(ok)} answered runs: {tot_found} of {tot_exp} expectations named, "
        f"{tot_real} credited as real in the right file, {tot_mis} found but misfiled, "
        f"{tot_unexp} real findings naming nothing in the key."
    )

    cases_all = {c["id"]: c for c in json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]}
    problems, near = check_trap(rows, cases_all, args.raw)
    print("\nTrap check (#258, the known-wrong finding): " + ("clean" if not problems else "FAILED"))
    for p in problems:
        print(f"  {p}")
    if near:
        print("  near misses (detected, not called real - not failures):")
        for n in near:
            print(f"    {n}")

    if args.out:
        Path(args.out).write_text(
            json.dumps({"rows": rows, "trap_problems": problems}, indent=1), encoding="utf-8"
        )
        print(f"\nwrote {args.out}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())