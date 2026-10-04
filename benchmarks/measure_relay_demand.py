"""F18 input: classify benchmark failures by whether a hosted relay could fix them.

Read-only measurement. No network mutation, no config change, no telemetry.
Run:  python benchmarks/measure_relay_demand.py --suite walled
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmarks.cases import load_cases  # noqa: E402
from searchts import unlocker  # noqa: E402
from searchts.unlocker import UnlockerError  # noqa: E402

# A hosted relay (residential egress + managed challenge solving) plausibly fixes:
#   - IP reputation blocks, which are the wall for most of these
# A relay does NOT fix:
#   - login walls (needs the user's own credentials, not a different IP)
#   - cases searchts already reads
RELAY_FIXABLE_MARKERS = (
    "403",
    "429",
    "challenge",
    "cloudflare",
    "datadome",
    "akamai",
    "fastly",
    "blocked",
    "captcha",
    "forbidden",
    "unusual traffic",
    "just a moment",
    "attention required",
    "perimeterx",
    "datadome-co",
)


def classify(url: str, attempts: list[tuple[str, str]]) -> str:
    if not attempts:
        return "unknown"
    last_backend, last_why = attempts[-1]
    blob = f"{last_why} {last_backend}".lower()
    if "login-wall" in blob or "login wall" in blob or "/uas/login" in blob or "sign in" in blob:
        return "login-wall (relay cannot fix: needs credentials)"
    if any(m in blob for m in RELAY_FIXABLE_MARKERS):
        return "bot-wall (relay plausibly fixes)"
    if "thin" in blob or "chars" in blob:
        return "thin (relay may help)"
    return f"other: {last_why[:70]}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default="walled", choices=["smoke", "walled", "all"])
    ap.add_argument("--extra", default=None)
    args = ap.parse_args()

    cases = load_cases(extra_path=args.extra, suite=args.suite)
    tally: Counter[str] = Counter()
    rows: list[tuple[str, str, str, str]] = []

    for case in cases:
        try:
            res = unlocker.fetch(case.url, min_chars=0 if case.allow_thin else unlocker._MIN_CHARS)
            backend = getattr(res, "backend", "?")
            tally["READ OK"] += 1
            rows.append((case.name, "ok", backend, "read"))
        except UnlockerError as e:
            kind = classify(case.url, e.attempts)
            tally[kind] += 1
            detail = "; ".join(f"{b}: {w}" for b, w in e.attempts)[:150]
            rows.append((case.name, "fail", kind, detail))
        except Exception as e:  # noqa: BLE001
            tally[f"error: {type(e).__name__}"] += 1
            rows.append((case.name, "error", type(e).__name__, str(e)[:100]))

    total = sum(tally.values())
    print(f"\n=== F18 relay-demand measurement, suite={args.suite} (n={total}) ===\n")
    for name, category in [(c.name, c.category) for c in cases]:
        for r in rows:
            if r[0] == name:
                print(f"  {r[0]:<18} {r[1]:<5} {r[2]:<45} {r[3]}")
    print("\n--- tally ---")
    for k, v in tally.most_common():
        print(f"  {v:>3}  {k}")

    fails = total - tally["READ OK"]
    fixable = sum(v for k, v in tally.items() if k.startswith("bot-wall"))
    if total:
        print(
            f"\nread ok        : {tally['READ OK']}/{total} = {100 * tally['READ OK'] / total:.1f}%"
        )
        print(f"failed         : {fails}/{total} = {100 * fails / total:.1f}%")
    if fails:
        print(f"of failures, bot-wall class: {fixable}/{fails} = {100 * fixable / fails:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
