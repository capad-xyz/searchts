#!/usr/bin/env python3
"""Hare against Hare Bot on this repo. Repo-local, run by hand. Not part of Hare.

Hare (the GitHub App) and Hare Bot (the Grok Bot template) are different
products on different platforms; they only share the intent. Hare's ledger
knows Hare alone. This script puts the two side by side when we want the
number, reading files that are already in the repo:

    docs/hare-ledger.json        Hare's side, built by scripts/hare_ledger.py
    docs/hare-bot-log-*.jsonl    Hare Bot's side, one row per pass (preferred)
    docs/hare-bot-log-*.md       the same passes in prose, read when no JSONL row

    python scripts/compare_reviewers.py            # prints the table
    python scripts/compare_reviewers.py --out docs/reviewer-comparison.md

No network, no token. Hare Bot's "fix: yes" is its own claim about a finding,
not a fate learned from the repo, so the two fate columns are not the same kind
of number; the table says so.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def hare_side(ledger: dict[str, Any]) -> dict[str, Any]:
    """Counts from Hare's ledger: notes, real, skip, real fixed or resolved,
    seconds per note from the cost line when it has one."""
    entries = ledger.get("entries", [])
    notes = [n for e in entries for n in e.get("notes", [])]
    fs = [f for e in entries for f in e.get("findings", [])]
    reals = [f for f in fs if f.get("sev") == "real"]
    fates = Counter(f.get("fate") for f in reals)
    secs = []
    for n in notes:
        m = re.search(r"(\d+(?:\.\d+)?) s\b", str(n.get("cost") or ""))
        if m:
            secs.append(float(m.group(1)))
    return {
        "notes": len(notes),
        "notes_with_findings": sum(1 for n in notes if n.get("findings")),
        "prs": len({e.get("pr") for e in entries}),
        "real": len(reals),
        "skip": len(fs) - len(reals),
        "real_done": fates.get("fixed", 0) + fates.get("resolved", 0),
        "done_means": "fixed or resolved, learned from later notes and threads",
        "minutes": round(sum(secs) / len(secs) / 60, 1) if secs else None,
    }


def bot_passes(docs: Path) -> dict[str, dict[str, Any]]:
    """Hare Bot's passes keyed by review URL. The JSONL row wins; the markdown
    fills in passes that have no row."""
    out: dict[str, dict[str, Any]] = {}
    for f in sorted(docs.glob("hare-bot-log-*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("type") != "review" or not row.get("review_url"):
                continue
            fs = [x for x in row.get("findings") or [] if isinstance(x, dict)]
            out[row["review_url"]] = {
                "pr": row.get("pr"),
                "minutes": float(row["minutes"]) if row.get("minutes") is not None else None,
                "tokens_est": int(row["estimate_tokens"]) if row.get("estimate_tokens") is not None else None,
                "real": sum(1 for x in fs if x.get("sev") == "real"),
                "skip": sum(1 for x in fs if x.get("sev") == "skip"),
                "real_fix_yes": sum(1 for x in fs if x.get("sev") == "real" and str(x.get("fix", "")).lower() == "yes"),
            }
    for f in sorted(docs.glob("hare-bot-log-*.md")):
        url, rec = "", None
        for line in f.read_text(encoding="utf-8").splitlines():
            m = re.match(r"- Review: (https://\S+)", line)
            if m:
                url = m.group(1)
                if url in out:
                    rec = None
                    continue
                m2 = re.search(r"/pull/(\d+)#", url)
                rec = out[url] = {"pr": int(m2.group(1)) if m2 else None, "minutes": None, "tokens_est": None, "real": 0, "skip": 0, "real_fix_yes": 0}
                continue
            if rec is None:
                continue
            m = re.match(r"- Clock: .*\(([\d.]+) min\)", line)
            if m:
                rec["minutes"] = float(m.group(1))
            m = re.match(r"- Token estimate: about ([\d,]+)", line)
            if m:
                rec["tokens_est"] = int(m.group(1).replace(",", ""))
            m = re.match(r"- (real|skip) `[^`]+` Fix (\w+)\.", line)
            if m:
                rec[m.group(1)] += 1
                if m.group(1) == "real" and m.group(2).lower() == "yes":
                    rec["real_fix_yes"] += 1
    return out


def bot_side(passes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    mins = [p["minutes"] for p in passes.values() if p.get("minutes")]
    toks = [p["tokens_est"] for p in passes.values() if p.get("tokens_est")]
    return {
        "notes": len(passes),
        "notes_with_findings": sum(1 for p in passes.values() if p["real"] or p["skip"]),
        "prs": len({p.get("pr") for p in passes.values()}),
        "real": sum(p["real"] for p in passes.values()),
        "skip": sum(p["skip"] for p in passes.values()),
        "real_done": sum(p["real_fix_yes"] for p in passes.values()),
        "done_means": "marked fix: yes in its own log, not checked against the repo",
        "minutes": round(sum(mins) / len(mins), 1) if mins else None,
        "tokens_est": round(sum(toks) / len(toks)) if toks else None,
    }


def render(hare: dict[str, Any], bot: dict[str, Any], built: str) -> str:
    def cell(v: Any) -> str:
        return "no record" if v is None else str(v)

    lines = [
        "# Hare and Hare Bot on this repo",
        "",
        "Two reviewers, two products, same intent. Built by `scripts/compare_reviewers.py` from `docs/hare-ledger.json` and `docs/hare-bot-log-*`; Hare's own ledger does not carry this table.",
        "",
        f"Built {built}.",
        "",
        "| | Hare (App) | Hare Bot (Grok Bot) |",
        "| --- | --- | --- |",
        f"| PRs | {hare['prs']} | {bot['prs']} |",
        f"| Notes | {hare['notes']} | {bot['notes']} |",
        f"| Notes with a finding | {hare['notes_with_findings']} | {bot['notes_with_findings']} |",
        f"| Notes with nothing | {hare['notes'] - hare['notes_with_findings']} | {bot['notes'] - bot['notes_with_findings']} |",
        f"| Real findings | {hare['real']} | {bot['real']} |",
        f"| Skip findings | {hare['skip']} | {bot['skip']} |",
        f"| Real done | {hare['real_done']} ({hare['done_means']}) | {bot['real_done']} ({bot['done_means']}) |",
        f"| Minutes per note | {cell(hare['minutes'])} (model call time, from the cost line) | {cell(bot['minutes'])} (wall clock, start to submit) |",
        f"| Tokens per note | from the cost line, see the ledger | {cell(bot.get('tokens_est'))} (its own chars/4 estimate) |",
        "",
        "The two Real done columns are different kinds of number and are not a hit-rate comparison. "
        "Notes with nothing is where Hare's count is padded: a hop that answered but found nothing still posts a note.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--docs", default="docs", help="where hare-ledger.json and hare-bot-log-* live")
    ap.add_argument("--out", default="", help="write the markdown here instead of printing it")
    args = ap.parse_args(argv)
    docs = Path(args.docs)
    ledger_path = docs / "hare-ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
    md = render(hare_side(ledger), bot_side(bot_passes(docs)), datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"compare reviewers: wrote {args.out}")
    else:
        print(md, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
