#!/usr/bin/env python3
"""Hare's findings ledger (PLAN R2b).

Every finding Hare posted on this repo, what became of it, and what the owner
said about the note. Built from the notes themselves (GitHub reviews carrying
the Hare token), the "Since" lines of later notes, resolved review threads and
`/hare score` comments. No hidden memory: the ledger is a file in the repo.

    python scripts/hare_ledger.py --out docs/   # writes hare-ledger.json and .md

Reads with GITHUB_TOKEN and GITHUB_REPOSITORY. Does not post anything.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hare_r1  # noqa: E402

LEDGER_JSON = "hare-ledger.json"
LEDGER_MD = "hare-ledger.md"
RULES_START = "<!-- hare-ledger:rules -->"
RULES_END = "<!-- /hare-ledger:rules -->"
LOW_SCORE = 2
# A finding's fate, from the signals we have. "fixed" and "moved" come from a
# later note's Since line, "resolved" from the review thread, "open" otherwise.
FATES = ("fixed", "moved", "resolved", "still applies", "open")


def score_from(comment: str) -> tuple[int | None, str]:
    """`/hare score 2 thin on the tests` -> (2, "thin on the tests"); (None, "") otherwise."""
    m = re.search(r"(?:^|\s)[/@]hare\s+score\s+([1-5])\b[:,]?\s*(.*)", comment or "", re.I | re.S)
    if not m:
        return None, ""
    return int(m.group(1)), hare_r1._no_em(hare_r1._plain(m.group(2)))[:200]


def note_meta(body: str) -> dict[str, Any]:
    """Hop, effort, cost and cut from one note's fold and Models row."""
    out: dict[str, Any] = {"hop": "", "effort": "", "cost": "", "cut": ""}
    m = re.search(r"\| reviewer \|[^|]*`([^`]+)`[^|]*\| (\w+) \|", body or "")
    if m:
        out["hop"], out["effort"] = m.group(1), m.group(2)
    m = re.search(r"^- cost: (.+)$", body or "", re.M)
    if m:
        out["cost"] = m.group(1).strip()
    m = re.search(r"^- cut at the budget (.+)$", body or "", re.M)
    if m:
        out["cut"] = m.group(1).strip()
    return out


def since_statuses(body: str) -> dict[str, str]:
    """`- 🔴 \\`path:line\\`: fixed` lines of a note's Since section."""
    out: dict[str, str] = {}
    for m in re.finditer(r"^- (?:🔴|🟡) `([^`]+)`: (still applies|fixed|moved|not checked)$", body or "", re.M):
        out[m.group(1)] = m.group(2)
    return out


def pr_rows(pr: dict[str, Any], reviews: list[dict[str, Any]], comments: list[dict[str, Any]], threads: list[dict[str, Any]]) -> dict[str, Any]:
    """One PR's ledger entry from its reviews, comments and review threads."""
    notes = hare_r1.hare_notes(reviews)
    findings: dict[str, dict[str, Any]] = {}
    note_rows: list[dict[str, Any]] = []
    for note in notes:
        body = str(note.get("body") or "")
        meta = note_meta(body)
        for st_loc, st in since_statuses(body).items():
            if st_loc in findings and st != "not checked":
                findings[st_loc]["fate"] = st
        for f in hare_r1.parse_old_findings(body):
            row = findings.setdefault(f["loc"], {"loc": f["loc"], "sev": f["sev"], "issue": f["issue"], "fate": "open", "first": note.get("submitted_at", "")})
            row["sev"], row["issue"] = f["sev"], f["issue"]
        note_rows.append({"at": note.get("submitted_at", ""), "url": note.get("html_url", ""), **meta, "findings": len(hare_r1.parse_old_findings(body))})
    resolved = {t.get("path", ""): t for t in threads if t.get("isResolved")}
    for loc, row in findings.items():
        path = loc.rsplit(":", 1)[0]
        if row["fate"] == "open" and path in resolved:
            row["fate"] = "resolved"
    scores = []
    for c in comments:
        n, text = score_from(str(c.get("body") or ""))
        if n is not None:
            scores.append({"score": n, "text": text, "by": (c.get("user") or {}).get("login", ""), "at": c.get("created_at", "")})
    return {
        "pr": pr.get("number"),
        "title": pr.get("title", ""),
        "state": "merged" if pr.get("merged_at") else str(pr.get("state") or ""),
        "files": [],
        "notes": note_rows,
        "findings": list(findings.values()),
        "scores": scores,
    }


def summarize(entries: list[dict[str, Any]]) -> dict[str, Any]:
    reals = [f for e in entries for f in e["findings"] if f["sev"] == "real"]
    skips = [f for e in entries for f in e["findings"] if f["sev"] == "skip"]
    fates = Counter(f["fate"] for f in reals)
    hops = Counter(n["hop"] for e in entries for n in e["notes"] if n["hop"])
    scores = [s["score"] for e in entries for s in e["scores"]]
    cuts = sum(1 for e in entries for n in e["notes"] if n["cut"])
    return {
        "prs": len(entries),
        "notes": sum(len(e["notes"]) for e in entries),
        "real": len(reals),
        "skip": len(skips),
        "real_fates": dict(fates),
        "real_fixed_or_resolved": fates.get("fixed", 0) + fates.get("resolved", 0),
        "hops": dict(hops),
        "scores": len(scores),
        "score_avg": round(sum(scores) / len(scores), 2) if scores else None,
        "cut_notes": cuts,
    }


def render_md(entries: list[dict[str, Any]], summary: dict[str, Any], built: str) -> str:
    rate = ""
    if summary["real"]:
        rate = f"{summary['real_fixed_or_resolved']} of {summary['real']} real findings fixed or resolved ({100 * summary['real_fixed_or_resolved'] // summary['real']}%)"
    lines = [
        "# Hare ledger",
        "",
        "Every finding Hare posted here, what became of it, and what the owner said. Built by `scripts/hare_ledger.py` from the notes, the Since lines, resolved threads and `/hare score` comments. PLAN R2b.",
        "",
        f"Built {built}. {summary['prs']} PRs, {summary['notes']} notes, {summary['real']} real and {summary['skip']} skip findings, {summary['cut_notes']} notes cut at the budget.",
        "",
        f"**Hit rate:** {rate or 'no real findings yet'}.",
        f"**Owner scores:** {summary['scores']} given" + (f", average {summary['score_avg']} of 5" if summary["score_avg"] is not None else "") + ".",
        "",
        "| Hop | Notes |",
        "| --- | --- |",
    ]
    for hop, n in sorted(summary["hops"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| `{hop}` | {n} |")
    lines += ["", "## By PR", "", "| PR | Notes | Real | Skip | Fates of real | Scores |", "| --- | --- | --- | --- | --- | --- |"]
    for e in sorted(entries, key=lambda e: -int(e["pr"] or 0)):
        reals = [f for f in e["findings"] if f["sev"] == "real"]
        fates = ", ".join(f"{k} {v}" for k, v in sorted(Counter(f["fate"] for f in reals).items())) or ""
        scores = "; ".join(f"{s['score']}" + (f" ({s['text']})" if s["text"] else "") for s in e["scores"])
        lines.append(f"| #{e['pr']} | {len(e['notes'])} | {len(reals)} | {len(e['findings']) - len(reals)} | {fates} | {scores} |")
    lines += ["", "## Owner feedback", ""]
    fb = [(e["pr"], s) for e in entries for s in e["scores"]]
    if not fb:
        lines.append("None yet. `/hare score 1..5 <why>` on a PR records one.")
    for pr, s in sorted(fb, key=lambda x: x[1]["at"], reverse=True):
        lines.append(f"- #{pr}: {s['score']}/5" + (f", {s['text']}" if s["text"] else "") + f" ({s['by']}, {s['at'][:10]})")
    return "\n".join(lines) + "\n"


def owner_feedback(ledger: dict[str, Any], limit: int = 10) -> list[str]:
    """The last owner scores with a reason, newest first, for the review prompt."""
    fb = [(e["pr"], s) for e in ledger.get("entries", []) for s in e.get("scores", []) if s.get("text")]
    fb.sort(key=lambda x: x[1].get("at", ""), reverse=True)
    return [f"#{pr} scored {s['score']}/5: {s['text']}" for pr, s in fb[:limit]]


def prior_findings(ledger: dict[str, Any], paths: set[str], limit: int = 12) -> list[str]:
    """Earlier findings on the files in this diff, with their fate."""
    out: list[str] = []
    for e in sorted(ledger.get("entries", []), key=lambda e: -int(e.get("pr") or 0)):
        for f in e.get("findings", []):
            path = str(f.get("loc", "")).rsplit(":", 1)[0]
            if path in paths:
                out.append(f"#{e['pr']} {f['sev']} `{f['loc']}` ({f['fate']}): {f['issue'][:160]}")
    return out[:limit]


def proposed_rules(ledger: dict[str, Any]) -> list[str]:
    """R2c: every low score with a reason becomes a rule line, newest first,
    deduplicated on the reason. The owner wrote the reason; Hare only files it."""
    seen: set[str] = set()
    out: list[str] = []
    fb = [(e["pr"], s) for e in ledger.get("entries", []) for s in e.get("scores", []) if s.get("text") and s.get("score", 5) <= LOW_SCORE]
    fb.sort(key=lambda x: x[1].get("at", ""), reverse=True)
    for pr, sc in fb:
        key = sc["text"].strip().rstrip(".").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(f"- {sc['text'].strip().rstrip('.')}. (#{pr}, scored {sc['score']}/5 on {sc.get('at', '')[:10]})")
    return out


def rules_block(rules: list[str]) -> str:
    body = "\n".join(rules) if rules else "- (none yet: a `/hare score 1..5 <why>` of 2 or less with a reason lands here)"
    return (
        f"{RULES_START}\n"
        "**What the owner said Hare missed (from the ledger, PLAN R2c).** Each line is the reason behind a low score, filed by "
        "`scripts/hare_ledger.py` from `/hare score`. Hare reads these as rules for the next note. Each ledger run rewrites "
        "this block, so to retire a line, edit or delete the score comment it came from.\n\n"
        f"{body}\n"
        f"{RULES_END}"
    )


def apply_rules(agents: str, rules: list[str]) -> str:
    """AGENTS.md with the rules block replaced, or added after the Hare section's
    first paragraph when there is none. Everything else untouched."""
    block = rules_block(rules)
    if RULES_START in agents and RULES_END in agents:
        a = agents.index(RULES_START)
        b = agents.index(RULES_END) + len(RULES_END)
        return agents[:a] + block + agents[b:]
    anchor = "## R1 "
    k = agents.find(anchor)
    if k < 0:
        return agents.rstrip("\n") + "\n\n" + block + "\n"
    nl = agents.find("\n\n", k)
    nl = len(agents) if nl < 0 else nl
    return agents[:nl] + "\n\n" + block + agents[nl:]


def _threads(owner: str, repo: str, n: int, token: str) -> list[dict[str, Any]]:
    query = """
    query($owner:String!,$name:String!,$n:Int!) {
      repository(owner:$owner, name:$name) { pullRequest(number:$n) {
        reviewThreads(first: 100) { nodes { isResolved isOutdated path line comments(first:1) { nodes { body } } } } } } }
    """
    try:
        data = hare_r1.github_api("POST", "/graphql", token, {"query": query, "variables": {"owner": owner, "name": repo, "n": n}})
    except Exception:
        return []
    nodes = (((data.get("data") or {}).get("repository") or {}).get("pullRequest") or {}).get("reviewThreads", {}).get("nodes") or []
    return [t for t in nodes if hare_r1.TOKEN in str((((t.get("comments") or {}).get("nodes") or [{}])[0] or {}).get("body") or "")]


def build(owner: str, repo: str, token: str, max_prs: int = 200) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    page = 1
    while len(entries) < max_prs:
        prs = hare_r1.github_api("GET", f"/repos/{owner}/{repo}/pulls?state=all&sort=updated&direction=desc&per_page=50&page={page}", token)
        if not prs:
            break
        for pr in prs:
            n = int(pr["number"])
            reviews = hare_r1.github_api("GET", f"/repos/{owner}/{repo}/pulls/{n}/reviews?per_page=100", token)
            if not any(hare_r1.TOKEN in str(r.get("body") or "") for r in reviews):
                continue
            comments = hare_r1.github_api("GET", f"/repos/{owner}/{repo}/issues/{n}/comments?per_page=100", token)
            entry = pr_rows(pr, reviews, comments, _threads(owner, repo, n, token))
            entries.append(entry)
        page += 1
    from datetime import datetime, timezone

    built = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {"built": built, "repo": f"{owner}/{repo}", "summary": summarize(entries), "entries": entries}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="docs", help="directory for hare-ledger.json and hare-ledger.md")
    ap.add_argument("--max-prs", type=int, default=200)
    ap.add_argument("--agents", default="AGENTS.md", help="write the rules block into this file (R2c); empty to skip")
    args = ap.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN", "")
    full = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or "/" not in full:
        print("hare ledger: GITHUB_TOKEN and GITHUB_REPOSITORY are required", file=sys.stderr)
        return 2
    owner, repo = full.split("/", 1)
    ledger = build(owner, repo, token, args.max_prs)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / LEDGER_JSON).write_text(json.dumps(ledger, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / LEDGER_MD).write_text(render_md(ledger["entries"], ledger["summary"], ledger["built"]), encoding="utf-8")
    s = ledger["summary"]
    print(f"hare ledger: {s['prs']} PRs, {s['notes']} notes, {s['real']} real, {s['skip']} skip, {s['scores']} scores -> {out / LEDGER_MD}")
    if args.agents and Path(args.agents).exists():
        before = Path(args.agents).read_text(encoding="utf-8")
        after = apply_rules(before, proposed_rules(ledger))
        if after != before:
            Path(args.agents).write_text(after, encoding="utf-8")
            print(f"hare ledger: {len(proposed_rules(ledger))} rule(s) written to {args.agents}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
