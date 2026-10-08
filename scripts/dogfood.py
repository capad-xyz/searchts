#!/usr/bin/env python3
"""Read a fixed corpus of real URLs and report what came back.

The thresholds in ``walls.py`` and ``unlocker.py`` were measured against pages
that are already drifting: a front page changes every day, a docs index changes
whenever upstream ships. A threshold tuned once against a snapshot is a
threshold that rots silently, and the only defence is re-measuring on a cadence
and diffing against the last run.

This exists because that is exactly how the defects in #331-#342 were found.
Eleven of them were invisible to the unit tests, because the unit tests use
fixtures and fixtures do not change when a site redesigns.

Usage::

    python scripts/dogfood.py                     # all corpora, text summary
    python scripts/dogfood.py --corpus news docs  # a subset
    python scripts/dogfood.py --json              # machine-readable
    python scripts/dogfood.py --baseline out.json # diff against a prior run

Exit status is 0 when every probe either read or failed for a reason the
baseline already recorded, and 1 when a probe's *outcome class* changed
(read -> blocked, blocked -> read, ok -> thin). That is what a scheduled run
should alert on: not the text, which changes daily, but whether a page is still
readable at all.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

#: One representative URL per behaviour we care about. Not "the most popular
#: sites": each entry is here because it exercised a distinct code path.
#:
#: ``expect`` is the outcome class, not a pass/fail. A wall site failing is
#: correct behaviour; a wall site *reading* is the bug worth alerting on.
CORPORA: Dict[str, List[Dict[str, Any]]] = {
    # Pages whose content is a link list. These are what #331 fixed and what
    # #333 is still arguing about, so they are the ones most likely to regress.
    "reference": [
        {"url": "https://pypi.org/project/searchts/", "expect": "read"},
        {"url": "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference", "expect": "read"},
        {"url": "https://en.wikipedia.org/wiki/Rust_(programming_language)", "expect": "read"},
        {"url": "https://docs.python.org/3/library/asyncio.html", "expect": "read"},
        {"url": "https://react.dev/learn", "expect": "read"},
        {"url": "https://tailwindcss.com/docs", "expect": "read"},
        {"url": "https://docs.docker.com/get-docker/", "expect": "read"},
        {"url": "https://docs.djangoproject.com/en/5.0/", "expect": "read"},
    ],
    # Front pages and link lists: the #337 regression surface.
    "news": [
        {"url": "https://www.theguardian.com/uk", "expect": "read"},
        {"url": "https://www.bbc.com/news", "expect": "read"},
        {"url": "https://lite.cnn.com/", "expect": "read"},
        {"url": "https://news.ycombinator.com/", "expect": "read"},
        {"url": "https://www.nature.com/", "expect": "read"},
    ],
    # Pages that used to false-positive, each with a named cause.
    "regressed": [
        # #335: a locale string inside a <script>, not a cookie wall.
        {"url": "https://stripe.com/", "expect": "read"},
        # #337: was 7,364 characters on one line.
        {"url": "https://www.nytimes.com/", "expect": "read"},
        # Thin for the loader but real content.
        {"url": "https://duckduckgo.com/", "expect": "read"},
    ],
    # Walls. These SHOULD fail; if one starts reading, the classifier regressed.
    "walled": [
        {"url": "https://www.instagram.com/", "expect": "blocked"},
        {"url": "https://app.slack.com/client", "expect": "blocked"},
        {"url": "https://chatgpt.com/", "expect": "blocked"},
        {"url": "https://www.linkedin.com/feed/", "expect": "blocked"},
    ],
    # Needs the browser rung. #338 must not fail-fast these away.
    "browser": [
        {"url": "https://gitlab.com/gitlab-org/gitlab", "expect": "read"},
    ],
}

#: Below this an extract is a stub rather than a page, whatever the status says.
THIN_CHARS = 500


def _classify(text: str, status: Optional[int], backend: str, error: str) -> str:
    """read | blocked | thin | error. The outcome class, not the content."""
    if error:
        return "blocked" if "403" in error or "401" in error or "wall" in error else "error"
    if status is not None and status >= 400:
        return "blocked"
    if len(text) < THIN_CHARS:
        return "thin"
    return "read"


def probe(case: Dict[str, Any], timeout_note: str = "") -> Dict[str, Any]:
    """Read one URL and report its outcome class. Never raises."""
    from searchts.unlocker import UnlockerError, fetch

    url = case["url"]
    started = time.time()
    row: Dict[str, Any] = {"url": url, "expect": case["expect"], "corpus": case.get("corpus", "")}
    try:
        # Memory is off on purpose: a cached read would hide today's behaviour,
        # and this script exists to observe today's behaviour.
        result = fetch(url, progress=False, use_memory=False)
        text = result.text or ""
        row["outcome"] = _classify(text, result.status, result.backend, "")
        row["chars"] = len(text)
        row["lines"] = sum(1 for ln in text.splitlines() if ln.strip())
        row["status"] = result.status
        row["backend"] = result.backend
    except UnlockerError as e:
        row["outcome"] = _classify("", None, "", str(e))
        row["chars"] = 0
        row["lines"] = 0
        row["error"] = str(e)[:200]
    except Exception as e:  # noqa: BLE001 - a probe must not stop the sweep
        row["outcome"] = "error"
        row["chars"] = 0
        row["lines"] = 0
        row["error"] = f"{type(e).__name__}: {str(e)[:180]}"
    row["seconds"] = round(time.time() - started, 2)
    row["matches_expectation"] = row["outcome"] == row["expect"]
    return row


def sweep(corpora: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    os.environ.setdefault("SEARCHTS_NO_MEMORY", "1")
    wanted = corpora or list(CORPORA)
    rows: List[Dict[str, Any]] = []
    for name in wanted:
        for case in CORPORA.get(name, []):
            row = probe(case)
            row["corpus"] = name
            rows.append(row)
            print(
                f"  {'ok ' if row['matches_expectation'] else 'DRIFT'} "
                f"{name:<10}{row['outcome']:<8}{row['chars']:>8,} ch "
                f"{row['lines']:>5} ln {row['seconds']:>6.1f}s  {row['url'][:52]}",
                flush=True,
            )
    return rows


def diff(rows: List[Dict[str, Any]], baseline_path: Path) -> List[str]:
    """Outcome-class changes since the baseline. Text churn is not drift."""
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return [f"baseline unreadable ({type(e).__name__}), treating every row as new"]
    was = {r["url"]: r for r in baseline.get("probes", [])}
    changes: List[str] = []
    for row in rows:
        prev = was.get(row["url"])
        if prev is None:
            continue
        if prev.get("outcome") != row["outcome"]:
            changes.append(f"{row['url']}: {prev.get('outcome')} -> {row['outcome']}")
    return changes


def report(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    ok = [r for r in rows if r["matches_expectation"]]
    drift = [r for r in rows if not r["matches_expectation"]]
    read = [r for r in rows if r["outcome"] == "read"]
    secs = sorted(r["seconds"] for r in read)
    return {
        "probes": len(rows),
        "matched_expectation": len(ok),
        "drift": len(drift),
        "read": len(read),
        "median_read_seconds": secs[len(secs) // 2] if secs else 0,
        "max_read_seconds": max(secs) if secs else 0,
        "probes_detail": rows,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", nargs="*", choices=sorted(CORPORA), help="corpora to sweep")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--baseline", type=Path, help="a prior run's JSON to diff against")
    ap.add_argument("--out", type=Path, help="write this run's JSON here")
    args = ap.parse_args(argv)

    if not args.json:
        print(f"searchts dogfood: {len(args.corpus or CORPORA)} corpora")
    rows = sweep(args.corpus)
    summary = report(rows)
    changes = diff(rows, args.baseline) if args.baseline else []

    payload = {"summary": summary, "outcome_changes": changes, "probes": rows}
    if args.out:
        args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        s = summary
        print(
            f"\n{s['probes']} probes | {s['matched_expectation']} as expected | "
            f"{s['drift']} drift | median {s['median_read_seconds']}s "
            f"| max {s['max_read_seconds']}s"
        )
        for c in changes:
            print(f"  CHANGED: {c}")

    # Drift is the signal, not failure. A site redesign or a wall going up is
    # information; a run that returns non-zero should mean the *tool* is broken.
    return 1 if changes else 0


if __name__ == "__main__":
    raise SystemExit(main())