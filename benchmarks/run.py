"""Run the unlocker benchmark and print a scorecard.

    python -m benchmarks.run [--json] [--out DIR] [--cases FILE]

The scoring/rendering helpers take plain dicts so they can be unit-tested without
touching the network (see tests/test_benchmark.py).
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .cases import Case, load_cases


def run_case(case: Case) -> dict:
    """Fetch one case through the unlocker; never raises — records the outcome."""
    from searchts import unlocker

    t0 = time.perf_counter()
    try:
        # use_memory=False so a cached per-domain winner doesn't skew the ladder.
        r = unlocker.fetch(case.url, use_memory=False)
        return {
            "name": case.name,
            "url": case.url,
            "category": case.category,
            "ok": True,
            "backend": r.backend,
            "status": r.status,
            "chars": len(r.text or ""),
            "seconds": round(time.perf_counter() - t0, 2),
            "error": None,
        }
    except Exception as e:  # UnlockerError, or anything a rung raised
        return {
            "name": case.name,
            "url": case.url,
            "category": case.category,
            "ok": False,
            "backend": None,
            "status": None,
            "chars": 0,
            "seconds": round(time.perf_counter() - t0, 2),
            "error": str(e)[:200],
        }


def run_benchmark(cases: list[Case]) -> list[dict]:
    return [run_case(c) for c in cases]


def summarize(results: list[dict]) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r["ok"])
    by_tier = dict(Counter(r["backend"] for r in results if r["ok"] and r["backend"]))
    by_category: dict[str, dict] = {}
    for r in results:
        bucket = by_category.setdefault(r["category"], {"passed": 0, "total": 0})
        bucket["total"] += 1
        if r["ok"]:
            bucket["passed"] += 1
    return {
        "total": total,
        "passed": passed,
        "pass_rate": (passed / total) if total else 0.0,
        "by_tier": by_tier,
        "by_category": by_category,
    }


def render_markdown(results: list[dict], summary: dict) -> str:
    pct = round(summary["pass_rate"] * 100)
    lines = [
        "# Unlocker benchmark",
        "",
        f"Read **{summary['passed']}/{summary['total']}** pages (**{pct}%**), keyless, "
        "on this machine's own IP.",
        "",
        "> Run from a residential connection for a representative number: from a datacenter "
        "IP (CI, cloud VM) the curl_cffi tier is blocked more often than a real user sees.",
        "",
        "See [how to interpret this scorecard](https://github.com/capad-xyz/searchts/"
        "blob/main/benchmarks/README.md#interpret-the-scorecard).",
        "",
        "## Which tier carried it",
        "",
    ]
    if summary["by_tier"]:
        for tier, n in sorted(summary["by_tier"].items(), key=lambda kv: -kv[1]):
            lines.append(f"- `{tier}`: {n}")
    else:
        lines.append("- (nothing read)")
    lines += [
        "",
        "## By category",
        "",
    ]
    for category, counts in sorted(summary["by_category"].items()):
        category_pct = round(counts["passed"] / counts["total"] * 100)
        lines.append(f"- `{category}`: {counts['passed']}/{counts['total']} ({category_pct}%)")
    lines += [
        "",
        "## Per page",
        "",
        "| Page | Category | Read | Tier | Chars | Secs |",
        "|------|----------|:----:|------|------:|-----:|",
    ]
    for r in results:
        tier = f"`{r['backend']}`" if r["backend"] else "—"
        lines.append(
            f"| {r['name']} | {r['category']} | {'yes' if r['ok'] else 'no'} | "
            f"{tier} | {r['chars']} | {r['seconds']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m benchmarks.run",
        description="Measure how often searchts reads a set of (often bot-walled) pages.",
    )
    ap.add_argument("--out", metavar="DIR", help="also write scorecard.md + results.json here")
    ap.add_argument("--cases", metavar="FILE", help="JSON file of extra cases to include")
    ap.add_argument("--json", action="store_true", help="print raw JSON instead of the scorecard")
    args = ap.parse_args(argv)

    results = run_benchmark(load_cases(args.cases))
    summary = summarize(results)

    if args.json:
        print(json.dumps({"summary": summary, "results": results}, indent=2))
    else:
        print(render_markdown(results, summary))

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        (out / "scorecard.md").write_text(render_markdown(results, summary), encoding="utf-8")
        (out / "results.json").write_text(
            json.dumps({"generated": stamp, "summary": summary, "results": results}, indent=2),
            encoding="utf-8",
        )
        print(f"\nwrote {out / 'scorecard.md'} and {out / 'results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
