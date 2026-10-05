#!/usr/bin/env python3
"""Hare's eval: old PRs with known answers, run through each provider with
thinking off and on. Posts nothing anywhere.

Each review is built the way hare_r1 builds one: SYSTEM, build_user, the PR's
diff at the commit that was reviewed, AGENTS.md at that commit and HARE.md at
its merge base, with no ledger, so lessons learned later cannot leak in. Each
provider's first model answers once per mode (or `--repeat` times). Findings
are scored against docs/hare-eval-cases.json:

- caught: a finding names the expected file (and a line within 25, when the
  case gives one) and its text carries one of the case's words. Caught as a
  real finding counts apart from caught only as a skip.
- false real: a real finding on a case marked clean.

Run where the keys are: .github/workflows/hare-eval.yml, which opens a PR with
docs/hare-eval-<date>.md and .json.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import statistics
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hare_r1  # noqa: E402

PROVIDERS = ("openrouter", "nous", "groq", "gemini", "zen")
KEY_ENV = {
    "groq": "SEARCHTS_HARE_API_KEY_GROQ",
    "gemini": "SEARCHTS_HARE_API_KEY_GEMINI",
    "nous": "SEARCHTS_HARE_API_KEY_NOUS",
    "openrouter": "SEARCHTS_HARE_API_KEY_OR",
    "zen": "SEARCHTS_HARE_API_KEY_ZEN",
}
DEFAULTS = {
    "groq": hare_r1.HARE_GROQ_DEFAULT,
    "gemini": hare_r1.HARE_GEMINI_DEFAULT,
    "nous": hare_r1.HARE_NOUS_DEFAULT,
    "openrouter": hare_r1.HARE_OR_DEFAULT,
    "zen": hare_r1.HARE_ZEN_DEFAULT,
}
# The same words the real run gives the model about CI.
CHECKS_TXT = (
    "Not shown to you. The Action reads CI once, right before the note posts, and reports it in the CI and "
    "Verdict lines. Do not judge CI or tell anyone to wait for it."
)
LINE_SLACK = 25


def first_model(provider: str) -> str:
    return DEFAULTS[provider].split(",")[0].strip()


def _file(owner: str, repo: str, path: str, ref: str, token: str) -> str:
    try:
        f = hare_r1.github_api("GET", f"/repos/{owner}/{repo}/contents/{path}?ref={ref}", token)
        return base64.b64decode(f.get("content") or "").decode("utf-8", errors="replace")
    except Exception:
        return ""


def build_case(owner: str, repo: str, case: dict[str, Any], token: str) -> dict[str, Any]:
    """The messages a real run would have sent for this PR at this commit."""
    pr = hare_r1.github_api("GET", f"/repos/{owner}/{repo}/pulls/{case['pr']}", token)
    cmp = hare_r1.github_api("GET", f"/repos/{owner}/{repo}/compare/main...{case['head']}", token)
    base = str((cmp.get("merge_base_commit") or {}).get("sha") or "main")
    diff = str(
        hare_r1.github_api(
            "GET", f"/repos/{owner}/{repo}/compare/{base}...{case['head']}", token, accept="application/vnd.github.v3.diff"
        )
    )
    agents = _file(owner, repo, "AGENTS.md", case["head"], token) or "(AGENTS.md unread)"
    hare_md = _file(owner, repo, "HARE.md", base, token)
    user = hare_r1.build_user(
        agents, str(pr.get("title") or ""), str(pr.get("body") or ""), diff, CHECKS_TXT, "", [], "", "", hare_md
    )
    return {
        "messages": [{"role": "system", "content": hare_r1.SYSTEM}, {"role": "user", "content": user}],
        "diff_chars": len(diff),
    }


def _norm(path: Any) -> str:
    p = str(path or "").strip()
    while p.startswith("./"):
        p = p[2:]
    return p


def findings_of(parsed: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The model's findings as path, line, sev and searchable text."""
    out: list[dict[str, Any]] = []
    for f in (parsed or {}).get("findings") or []:
        if not isinstance(f, dict):
            continue
        path, line = _norm(f.get("path")), f.get("line")
        if not path and f.get("loc"):
            p, _, ln = str(f["loc"]).partition(":")
            path, line = _norm(p), ln
        try:
            line = int(line) if line not in (None, "") else None
        except (TypeError, ValueError):
            line = None
        text = " ".join(str(f.get(k) or "") for k in ("issue", "short", "change"))
        out.append({"sev": str(f.get("sev") or "").lower(), "path": path, "line": line, "text": text})
    return out


def matches(expect: dict[str, Any], f: dict[str, Any]) -> bool:
    want, got = _norm(expect.get("path")), f.get("path") or ""
    if not got or not (got == want or got.endswith("/" + want) or want.endswith("/" + got)):
        return False
    line = expect.get("line")
    if line and f.get("line") and abs(int(line) - int(f["line"])) > LINE_SLACK:
        return False
    text = str(f.get("text") or "").lower()
    return any(str(w).lower() in text for w in expect.get("words") or [])


def score(case: dict[str, Any], fs: list[dict[str, Any]]) -> dict[str, Any]:
    caught: list[str] = []
    for e in case.get("expect") or []:
        hits = [f for f in fs if matches(e, f)]
        caught.append("real" if any(h["sev"] == "real" for h in hits) else ("skip" if hits else ""))
    reals = sum(1 for f in fs if f["sev"] == "real")
    return {"caught": caught, "reals": reals, "findings": len(fs), "false_reals": reals if case.get("clean") else 0}


def run(
    cases: list[dict[str, Any]],
    providers: list[str],
    modes: list[str],
    keys: dict[str, str],
    token: str,
    owner: str,
    repo: str,
    call: Callable[..., str] = hare_r1.chat_complete,
    pause: Callable[[float], None] = time.sleep,
    repeat: int = 1,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        try:
            built = build_case(owner, repo, case, token)
        except Exception as e:  # a case that cannot be built is reported, not fatal
            rows.append({"case": case["id"], "pr": case["pr"], "provider": "-", "model": "-", "mode": "-", "error": f"case: {str(e)[:120]}"})
            continue
        for mode in modes:
            chain = hare_r1.build_provider_chain(
                {p: keys.get(p, "") if p in providers else "" for p in PROVIDERS},
                {p: [first_model(p)] if p in providers else [] for p in PROVIDERS},
                deep=mode == "on",
            )
            for name, base, key, model, opts in chain:
                for _ in range(max(1, repeat)):
                    hare_r1.LAST_USAGE.clear()
                    t0, err, parsed = time.time(), "", None
                    try:
                        raw = call(base, key, model, built["messages"], opts, timeout=300)
                        parsed = hare_r1.extract_json(raw)
                        if parsed is None:
                            err = "no JSON in the answer"
                    except Exception as e:
                        err = str(e)[:160]
                    usage = dict(hare_r1.LAST_USAGE)
                    fs = findings_of(parsed)
                    rows.append(
                        {
                            "case": case["id"],
                            "pr": case["pr"],
                            "provider": name,
                            "model": model,
                            "mode": mode,
                            "seconds": round(time.time() - t0, 1),
                            "error": err,
                            "diff_chars": built["diff_chars"],
                            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                            "answer_tokens": int(usage.get("completion_tokens") or 0),
                            "reasoning_tokens": int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0),
                            **score(case, fs),
                            "raw_findings": fs,
                        }
                    )
                    pause(4)
    return rows


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for r in rows:
        if r.get("provider") in (None, "-"):
            continue
        groups.setdefault((r["provider"], r["model"], r["mode"]), []).append(r)
    out = []
    for (provider, model, mode), rs in sorted(groups.items()):
        ok = [r for r in rs if not r.get("error")]
        secs = [r["seconds"] for r in ok]
        reasoning = [r["reasoning_tokens"] for r in ok]
        out.append(
            {
                "provider": provider,
                "model": model,
                "mode": mode,
                "runs": len(rs),
                "answered": len(ok),
                "expected": sum(len(r.get("caught") or []) for r in rs),
                "caught_real": sum(c == "real" for r in rs for c in r.get("caught") or []),
                "caught_any": sum(bool(c) for r in rs for c in r.get("caught") or []),
                "false_reals": sum(int(r.get("false_reals") or 0) for r in rs),
                "median_s": statistics.median(secs) if secs else None,
                "median_reasoning": statistics.median(reasoning) if reasoning else None,
            }
        )
    return out


def render(rows: list[dict[str, Any]], cases: list[dict[str, Any]], built: str) -> str:
    def cell(v: Any) -> str:
        return "-" if v is None else str(v)

    lines = [
        f"# Hare eval, {built}",
        "",
        "Old PRs with confirmed issues, each provider's first model, thinking off and on. Built by "
        "`scripts/hare_eval.py` in `.github/workflows/hare-eval.yml`; nothing was posted. Each cell is one run, so treat "
        "a difference of one or two catches as noise. The answer key is `docs/hare-eval-cases.json`.",
        "",
        "| Provider | Model | Thinking | Answered | Caught as real | Caught at all | False reals on clean PRs | Median s | Median reasoning tokens |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in summarize(rows):
        lines.append(
            f"| {s['provider']} | `{s['model']}` | {s['mode']} | {s['answered']} of {s['runs']} | {s['caught_real']} of {s['expected']} "
            f"| {s['caught_any']} of {s['expected']} | {s['false_reals']} | {cell(s['median_s'])} | {cell(s['median_reasoning'])} |"
        )
    combos = sorted({(r["provider"], r["mode"]) for r in rows if r.get("provider") not in (None, "-")})
    lines += ["", "## Per expected issue", "", "real = caught as a real finding, skip = caught only as a skip, miss = not caught, err = no answer.", ""]
    lines.append("| Case | Issue | " + " | ".join(f"{p} {m}" for p, m in combos) + " |")
    lines.append("| --- | --- | " + " | ".join("---" for _ in combos) + " |")
    for case in cases:
        for i, e in enumerate(case.get("expect") or []):
            cells = []
            for p, m in combos:
                r = next((x for x in rows if x["case"] == case["id"] and x.get("provider") == p and x.get("mode") == m), None)
                if r is None:
                    cells.append(" ")
                elif r.get("error"):
                    cells.append("err")
                else:
                    cells.append((r.get("caught") or [""] * (i + 1))[i] or "miss")
            lines.append(f"| {case['id']} | {e['what']} ({e.get('by', '')}) | " + " | ".join(cells) + " |")
    errors = [r for r in rows if r.get("error")]
    if errors:
        lines += ["", "## Errors", ""]
        lines += [f"- {r['case']} {r.get('provider')} {r.get('mode')}: {r['error']}" for r in errors]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cases", default="docs/hare-eval-cases.json")
    ap.add_argument("--only", default="", help="case ids, comma separated; empty runs all")
    ap.add_argument("--providers", default="openrouter,nous,groq,gemini")
    ap.add_argument("--modes", default="off,on")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--out", default="docs")
    args = ap.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN", "")
    owner, _, repo = os.environ.get("GITHUB_REPOSITORY", "capad-xyz/searchts").partition("/")
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    if only:
        cases = [c for c in cases if c["id"] in only]
    providers = [p.strip() for p in args.providers.split(",") if p.strip() in PROVIDERS]
    modes = [m.strip() for m in args.modes.split(",") if m.strip() in ("off", "on")]
    keys = {p: os.environ.get(KEY_ENV[p], "") for p in PROVIDERS}
    missing = [p for p in providers if not keys.get(p)]
    if missing:
        print(f"hare eval: no key for {', '.join(missing)}; those providers are skipped")
    rows = run(cases, providers, modes, keys, token, owner, repo, repeat=args.repeat)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = Path(args.out)
    (out / f"hare-eval-{day}.json").write_text(json.dumps({"built": day, "rows": rows}, indent=1), encoding="utf-8")
    (out / f"hare-eval-{day}.md").write_text(render(rows, cases, day), encoding="utf-8")
    print(f"hare eval: {len(rows)} runs -> {out}/hare-eval-{day}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
