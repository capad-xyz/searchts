"""Run the unlocker benchmark and print a scorecard.

    python -m benchmarks.run [--json] [--out DIR] [--cases FILE] [--suite SUITE]

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

_SUMMARY_ORDER = ("smoke", "walled")


def run_case(case: Case) -> dict:
    """Fetch one case through the unlocker; never raises — records the outcome."""
    from searchts import unlocker

    t0 = time.perf_counter()
    try:
        # use_memory=False so a cached per-domain winner doesn't skew the ladder.
        # allow_thin cases accept the first rung's body; do not escalate for size.
        fetch_min = 0 if case.allow_thin else unlocker._MIN_CHARS
        r = unlocker.fetch(case.url, use_memory=False, min_chars=fetch_min)
        chars = len(r.text or "")
        min_chars = unlocker._MIN_CHARS
        thin = (not case.allow_thin) and chars < min_chars
        return {
            "name": case.name,
            "url": case.url,
            "category": case.category,
            "suite": case.suite,
            "ok": not thin,
            "backend": r.backend,
            "status": r.status,
            "chars": chars,
            "seconds": round(time.perf_counter() - t0, 2),
            "error": (f"thin content ({chars} < {min_chars} chars)" if thin else None),
        }
    except Exception as e:  # UnlockerError, or anything a rung raised
        return {
            "name": case.name,
            "url": case.url,
            "category": case.category,
            "suite": case.suite,
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
    # pass rate per suite (None when a suite was not run)
    by_suite: dict[str, dict] = {}
    for suite in _SUMMARY_ORDER:
        s_results = [r for r in results if r.get("suite") == suite]
        if not s_results:
            continue
        s_total = len(s_results)
        s_passed = sum(1 for r in s_results if r["ok"])
        by_suite[suite] = {
            "total": s_total,
            "passed": s_passed,
            "pass_rate": (s_passed / s_total) if s_total else 0.0,
        }
    return {
        "total": total,
        "passed": passed,
        "pass_rate": (passed / total) if total else 0.0,
        "by_tier": by_tier,
        "by_category": by_category,
        "by_suite": by_suite,
    }


def _render_section(title: str, results: list[dict], summary: dict) -> list[str]:
    s = summary["by_suite"].get(title.lower())
    lines: list[str] = [f"## {title}"]
    if s is None:
        lines += ["", "Not measured in this run.", ""]
        return lines
    pct = round(s["pass_rate"] * 100)
    honesty = ""
    if title.lower() == "walled":
        honesty = " — failures are expected on real bot-walls; a low rate is honest, not a defect."
    lines += [
        "",
        f"Read **{s['passed']}/{s['total']}** pages (**{pct}%**).{honesty}",
        "",
        "## " + title + " — which tier carried it",
        "",
    ]
    tiers = dict(Counter(r["backend"] for r in results if r.get("suite") == title.lower() and r["ok"] and r["backend"]))
    if tiers:
        for tier, n in sorted(tiers.items(), key=lambda kv: -kv[1]):
            lines.append(f"- `{tier}`: {n}")
    else:
        lines.append("- (nothing read)")
    lines += [
        "",
        "## " + title + " — by category",
        "",
    ]
    cats: dict[str, dict] = {}
    for r in results:
        if r.get("suite") != title.lower():
            continue
        bucket = cats.setdefault(r["category"], {"passed": 0, "total": 0})
        bucket["total"] += 1
        if r["ok"]:
            bucket["passed"] += 1
    for category, counts in sorted(cats.items()):
        category_pct = round(counts["passed"] / counts["total"] * 100)
        lines.append(f"- `{category}`: {counts['passed']}/{counts['total']} ({category_pct}%)")
    lines += [
        "",
        "## " + title + " — per page",
        "",
        "| Page | Category | Read | Tier | Chars | Secs |",
        "|------|----------|:----:|------|------:|-----:|",
    ]
    for r in results:
        if r.get("suite") != title.lower():
            continue
        tier = f"`{r['backend']}`" if r["backend"] else "—"
        lines.append(
            f"| {r['name']} | {r['category']} | {'yes' if r['ok'] else 'no'} | "
            f"{tier} | {r['chars']} | {r['seconds']} |"
        )
    lines.append("")
    return lines


def render_markdown(results: list[dict], summary: dict) -> str:
    lines = [
        "# Unlocker benchmark",
        "",
        "> Two suites, two honest pass rates. **Smoke** exercises the ladder on "
        "open pages; **Walled** is a real pass rate against vendors that restrict "
        "bots (Reddit, LinkedIn, Cloudflare/DataDome-class, X, Booking). A low "
        "walled rate is truth, not a trophy.",
        "",
        "> Run from a residential connection for a representative number: from a "
        "datacenter IP (CI, cloud VM) the curl_cffi tier is blocked more often "
        "than a real user sees.",
        "",
        "See [how to interpret this scorecard]"
        "(https://github.com/capad-xyz/searchts/blob/main/benchmarks/README.md"
        "#interpret-the-scorecard).",
        "",
    ]
    for suite in _SUMMARY_ORDER:
        lines += _render_section(suite.capitalize(), results, summary)
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m benchmarks.run",
        description="Measure how often searchts reads the smoke- and walled-suite pages.",
    )
    ap.add_argument("--out", metavar="DIR", help="also write scorecard.md + results.json here")
    ap.add_argument("--cases", metavar="FILE", help="JSON file of extra cases to include")
    ap.add_argument(
        "--suite",
        choices=["smoke", "walled", "all"],
        default="all",
        help="which suite to run (default: all — writes both sections)",
    )
    ap.add_argument("--json", action="store_true", help="print raw JSON instead of the scorecard")
    args = ap.parse_args(argv)

    suite_filter = None if args.suite == "all" else args.suite
    results = run_benchmark(load_cases(args.cases, suite=suite_filter))
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
