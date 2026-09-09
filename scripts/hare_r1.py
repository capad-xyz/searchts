#!/usr/bin/env python3
"""Hare R1c doorbell: review a PR via Nous, then OpenRouter. Never required CI."""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any

TOKEN = "<!-- searchts-r1-review -->"
NEEDED = "<!-- searchts-r1-needed -->"
BUBBLE_HEAD = "<!-- searchts-r1-review -->\n🐇❄ Hare · automated R1 · not the PR author"
SKIP_CHECKS = frozenset({"test-full", "wheel-gate"})
HARE_JOB_MARKERS = frozenset({"hare", "r1"})
MAX_DIFF = 90_000
MAX_BUBBLES = 20
CHECK_WAIT_S = 480
CHECK_POLL_S = 20

NOUS_BASE = "https://inference-api.nousresearch.com/v1"
OR_BASE = "https://openrouter.ai/api/v1"
ZEN_BASE = "https://opencode.ai/zen/v1"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _no_em(s: str) -> str:
    return s.replace("\u2014", "-").replace("\u2013", "-")


def github_api(
    method: str,
    path: str,
    token: str,
    body: dict[str, Any] | None = None,
    accept: str = "application/vnd.github+json",
) -> Any:
    url = path if path.startswith("http") else f"https://api.github.com{path}"
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", accept)
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            if not raw:
                return {}
            if accept.startswith("application/vnd.github.v3.diff"):
                return raw.decode("utf-8", errors="replace")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub {method} {path} {e.code}: {err[:500]}") from e


def _is_hare_job(name: str) -> bool:
    low = name.lower()
    short = low.split("/")[-1].strip()
    first = low.split("/")[0].strip()
    return short in HARE_JOB_MARKERS or first in HARE_JOB_MARKERS


def classify_checks(runs: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """Return (ok|pending|fail, notes). Skip-by-design names never fail."""
    notes: list[str] = []
    pending = False
    failed = False
    seen = 0
    for run in runs:
        name = str(run.get("name") or "")
        short = name.split("/")[-1].strip().lower()
        if _is_hare_job(name):
            continue
        if short in SKIP_CHECKS or name.lower() in SKIP_CHECKS:
            continue
        seen += 1
        status = str(run.get("status") or "")
        conclusion = str(run.get("conclusion") or "")
        if status != "completed":
            pending = True
            notes.append(f"{name}: {status}")
            continue
        if conclusion in {"failure", "cancelled", "timed_out", "action_required"}:
            failed = True
            notes.append(f"{name}: {conclusion}")
    if failed:
        return "fail", notes
    if pending or seen == 0:
        if seen == 0:
            notes.append("no non-Hare checks yet")
        return "pending", notes
    return "ok", notes


def parse_plus_lines(diff: str) -> dict[str, set[int]]:
    """New-file line numbers that exist on the RIGHT side of the diff."""
    out: dict[str, set[int]] = {}
    path: str | None = None
    new_line = 0
    in_hunk = False
    for raw in diff.splitlines():
        if raw.startswith("diff --git "):
            path = None
            in_hunk = False
            new_line = 0
            continue
        if raw.startswith("+++ "):
            rest = raw[4:]
            if rest.startswith("b/"):
                rest = rest[2:]
            path = rest
            out.setdefault(path, set())
            in_hunk = False
            continue
        if (
            raw.startswith("--- ")
            or raw.startswith("index ")
            or raw.startswith("new file mode")
            or raw.startswith("deleted file mode")
            or raw.startswith("similarity index")
            or raw.startswith("rename ")
        ):
            continue
        if raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            new_line = int(m.group(1)) if m else 0
            in_hunk = True
            continue
        if path is None or not in_hunk:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            out[path].add(new_line)
            new_line += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            continue
        elif raw.startswith("\\"):
            continue
        else:
            out[path].add(new_line)
            new_line += 1
    return out


def extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    blob = fence.group(1) if fence else None
    if blob is None:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            blob = text[start : end + 1]
    if not blob:
        return None
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def normalize_findings(findings: list[Any]) -> list[dict[str, Any]]:
    """Keep every model row, including lines that cannot take a bubble."""
    out: list[dict[str, Any]] = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        path = str(f.get("path") or "").strip().removeprefix("./")
        try:
            line: int | None = int(f["line"]) if f.get("line") is not None else None
        except (TypeError, ValueError):
            line = None
        sev = str(f.get("sev") or "skip").lower()
        if sev not in {"real", "skip"}:
            sev = "skip"
        out.append({**f, "path": path, "line": line, "sev": sev})
    return out


def intent_for(check_state: str, findings: list[dict[str, Any]]) -> str:
    if check_state in {"fail", "pending"}:
        return "hold"
    if any(str(f.get("sev") or "").lower() == "real" for f in findings):
        return "hold"
    return "ship"


def filter_bubbles(
    findings: list[dict[str, Any]], plus: dict[str, set[int]]
) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for f in findings:
        path = str(f.get("path") or "")
        line = f.get("line")
        if not isinstance(line, int) or path not in plus or line not in plus[path]:
            continue
        kept.append(f)
        if len(kept) >= MAX_BUBBLES:
            break
    return kept


def render_comment(
    model: str,
    effort: str,
    intent: str,
    findings: list[dict[str, Any]],
    check_state: str,
    check_notes: list[str],
) -> str:
    rows = []
    for f in findings:
        loc = f"{f.get('path')}:{f.get('line')}" if f.get("line") is not None else str(f.get("path") or "-")
        issue = _no_em(str(f.get("issue") or "").strip() or "see bubble")
        fix = str(f.get("fix") or "later")
        rows.append(f"| {f.get('sev')} | {loc} | {issue} | {fix} |")
    if not rows:
        rows.append("| - | - | no line findings | - |")
    why = ""
    if intent == "hold" and check_state == "fail":
        why = "Required CI is red."
    elif intent == "hold" and check_state == "pending":
        why = "Required CI is still running."
    table = "\n".join(rows)
    notes = "; ".join(check_notes[:6])
    extra = f"\n\nChecks: `{check_state}`" + (f" ({notes})" if notes else "")
    if why:
        extra += f"\n{why}"
    return _no_em(
        f"""{TOKEN}

## 🐇❄ Hare · R1 review

| | |
|---|---|
| **Name** | 🐇❄ Hare |
| **Purpose** | Review and report. Do not fix unless asked. |
| **Model** | {model} |
| **Effort** | {effort} |
| **Intent** | {intent} |

| Sev | File:line | Issue | Fix? |
|---|---|---|---|
{table}
{extra}
"""
    )


def bubble_body(sev: str, issue: str) -> str:
    label = "real" if sev == "real" else "skip"
    return _no_em(f"{BUBBLE_HEAD}\n**{label}**: {issue.strip()}")


def chat_complete(base: str, key: str, model: str, messages: list[dict[str, str]]) -> str:
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 2500,
    }
    req = urllib.request.Request(
        f"{base.rstrip('/')}/chat/completions",
        data=json.dumps(body).encode(),
        method="POST",
    )
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "searchts-hare/1")
    req.add_header("HTTP-Referer", "https://github.com/capad-xyz/searchts")
    req.add_header("X-Title", "searchts-hare")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM {e.code} {base} {model}: {err[:400]}") from e
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError(f"LLM empty choices {base} {model}")
    content = choices[0].get("message", {}).get("content") or ""
    if not str(content).strip():
        raise RuntimeError(f"LLM empty content {base} {model}")
    return str(content)


SYSTEM = """You are Hare, an automated PR reviewer for the searchts repo.
Read AGENTS.md rules in the user message. Review and report. Do not fix.
Voice: no em dashes. No first person. Emojis ok.
Return ONLY a JSON object:
{"effort":"low|medium|high","findings":[{"sev":"real"|"skip","path":"file","line":123,"issue":"one sentence","fix":"yes|no|later"}]}
sev real = wrong behavior, fail-loud lie, ticks on stdout, MCP break, test that cannot fail, scope creep, PLAN intent miss.
sev skip = nits (docs, style). Skip never holds merge.
line = new-file line number on the + side of the diff. If unsure, omit the finding.
Zero findings is allowed: {"effort":"low","findings":[]}
"""


def build_user(agents: str, title: str, body: str, diff: str, checks: str) -> str:
    if len(diff) > MAX_DIFF:
        diff = diff[:MAX_DIFF] + "\n...[truncated]..."
    return (
        f"## AGENTS.md\n{agents[:20_000]}\n\n"
        f"## PR title\n{title}\n\n"
        f"## PR body\n{(body or '')[:4_000]}\n\n"
        f"## CI (Action will set Intent from this; still note lies)\n{checks}\n\n"
        f"## Diff\n```\n{diff}\n```\n"
    )


def wait_checks(owner: str, repo: str, sha: str, token: str) -> list[dict[str, Any]]:
    deadline = time.time() + CHECK_WAIT_S
    runs: list[dict[str, Any]] = []
    while True:
        data = github_api(
            "GET",
            f"/repos/{owner}/{repo}/commits/{sha}/check-runs?per_page=100",
            token,
        )
        runs = list(data.get("check_runs") or [])
        state, _ = classify_checks(runs)
        if state != "pending" or time.time() >= deadline:
            return runs
        time.sleep(CHECK_POLL_S)


def post_needed(owner: str, repo: str, n: int, token: str, why: str) -> None:
    github_api(
        "POST",
        f"/repos/{owner}/{repo}/issues/{n}/comments",
        token,
        {
            "body": (
                f"{NEEDED}\n\nHare R1c could not finish: {_no_em(why)}\n\n"
                "Spawn hare locally (ocx cheap-scout). Do not treat this as a review."
            )
        },
    )


def resolve_stale_threads(
    owner: str, repo: str, n: int, token: str, plus: dict[str, set[int]]
) -> None:
    query = """
    query($owner:String!,$name:String!,$n:Int!) {
      repository(owner:$owner, name:$name) {
        pullRequest(number:$n) {
          reviewThreads(first: 50) {
            nodes { id isResolved isOutdated path line comments(first:1) { nodes { body } } }
          }
        }
      }
    }
    """
    try:
        data = github_api(
            "POST",
            "/graphql",
            token,
            {"query": query, "variables": {"owner": owner, "name": repo, "n": n}},
        )
    except RuntimeError:
        return
    nodes = (
        (((data.get("data") or {}).get("repository") or {}).get("pullRequest") or {})
        .get("reviewThreads", {})
        .get("nodes")
        or []
    )
    mut = """
    mutation($id:ID!) { resolveReviewThread(input:{threadId:$id}) { thread { id } } }
    """
    for node in nodes:
        if node.get("isResolved"):
            continue
        comments = (node.get("comments") or {}).get("nodes") or []
        if not comments or TOKEN not in str(comments[0].get("body") or ""):
            continue
        path = str(node.get("path") or "")
        line = node.get("line")
        gone = node.get("isOutdated") or (
            line is not None and (path not in plus or int(line) not in plus.get(path, set()))
        )
        if not gone:
            continue
        try:
            github_api("POST", "/graphql", token, {"query": mut, "variables": {"id": node["id"]}})
        except RuntimeError:
            continue


def run() -> int:
    token = _env("GITHUB_TOKEN") or _env("GH_TOKEN")
    repo_full = _env("GITHUB_REPOSITORY")
    pr = _env("PR_NUMBER") or _env("GITHUB_EVENT_NUMBER")
    sha = _env("HEAD_SHA")
    nous_key = _env("SEARCHTS_HARE_API_KEY_NOUS")
    or_key = _env("SEARCHTS_HARE_API_KEY_OR")
    zen_key = _env("SEARCHTS_HARE_API_KEY_ZEN")
    nous_model = _env("HARE_NOUS_MODEL", "poolside/laguna-s-2.1")
    or_model = _env("HARE_OR_MODEL", "inclusionai/ling-3.0-flash-fin:free")
    zen_model = _env("HARE_ZEN_MODEL", "ling-3.0-flash-fin-free")
    if not token or not repo_full or not pr:
        print("missing GITHUB_TOKEN / GITHUB_REPOSITORY / PR_NUMBER")
        return 0
    owner, repo = repo_full.split("/", 1)
    n = int(pr)
    try:
        return _hare_once(
            owner,
            repo,
            n,
            token,
            sha,
            nous_key,
            or_key,
            zen_key,
            nous_model,
            or_model,
            zen_model,
        )
    except Exception as e:
        try:
            post_needed(owner, repo, n, token, f"crash: {type(e).__name__}: {e}")
        except Exception as post_err:
            print(f"hare crash and nag failed: {e}; {post_err}")
        return 0


def _hare_once(
    owner: str,
    repo: str,
    n: int,
    token: str,
    sha: str,
    nous_key: str,
    or_key: str,
    zen_key: str,
    nous_model: str,
    or_model: str,
    zen_model: str,
) -> int:
    if not nous_key and not or_key and not zen_key:
        post_needed(owner, repo, n, token, "no Hare API secrets on this run (forks have none).")
        return 0

    pr_data = github_api("GET", f"/repos/{owner}/{repo}/pulls/{n}", token)
    sha = sha or pr_data.get("head", {}).get("sha") or ""
    title = pr_data.get("title") or ""
    body = pr_data.get("body") or ""
    diff = github_api(
        "GET",
        f"/repos/{owner}/{repo}/pulls/{n}",
        token,
        accept="application/vnd.github.v3.diff",
    )
    if not isinstance(diff, str):
        diff = ""
    plus = parse_plus_lines(diff)

    agents = ""
    try:
        file = github_api("GET", f"/repos/{owner}/{repo}/contents/AGENTS.md?ref={sha}", token)
        agents = base64.b64decode(file.get("content") or "").decode("utf-8", errors="replace")
    except Exception:
        agents = "(AGENTS.md unread)"

    runs = wait_checks(owner, repo, sha, token)
    check_state, check_notes = classify_checks(runs)
    checks_txt = f"{check_state}: " + ", ".join(check_notes[:12])
    user = build_user(agents, title, body, diff, checks_txt)
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]

    providers: list[tuple[str, str, str, str]] = []
    if nous_key:
        providers.append(("nous", NOUS_BASE, nous_key, nous_model))
    if or_key:
        providers.append(("openrouter", OR_BASE, or_key, or_model))
    if zen_key:
        providers.append(("zen", ZEN_BASE, zen_key, zen_model))

    last_err = "no provider"
    errs: list[str] = []
    parsed: dict[str, Any] | None = None
    used = ""
    for name, base, key, model in providers:
        try:
            raw = chat_complete(base, key, model, messages)
            parsed = extract_json(raw)
            if parsed is None:
                raise RuntimeError("no JSON object in model output")
            used = f"{name}:{model}"
            break
        except Exception as e:
            errs.append(f"{name}:{model}: {e}")
            parsed = None
            continue

    if parsed is None:
        post_needed(owner, repo, n, token, " | ".join(errs) or last_err)
        return 0

    findings = normalize_findings(list(parsed.get("findings") or []) if isinstance(parsed.get("findings"), list) else [])
    effort = str(parsed.get("effort") or "low")
    if effort not in {"low", "medium", "high"}:
        effort = "low"
    bubbles = filter_bubbles(findings, plus)
    intent = intent_for(check_state, findings)
    comment = render_comment(used, effort, intent, findings, check_state, check_notes)
    if TOKEN not in comment:
        post_needed(owner, repo, n, token, "rendered comment missing token")
        return 0

    github_api(
        "POST",
        f"/repos/{owner}/{repo}/issues/{n}/comments",
        token,
        {"body": comment},
    )

    review_comments = [
        {
            "path": f["path"],
            "line": f["line"],
            "side": "RIGHT",
            "body": bubble_body(str(f["sev"]), str(f.get("issue") or "")),
        }
        for f in bubbles
    ]
    review_body = {
        "commit_id": sha,
        "event": "COMMENT",
        "body": "",
    }
    if review_comments:
        review_body["comments"] = review_comments
        try:
            github_api("POST", f"/repos/{owner}/{repo}/pulls/{n}/reviews", token, review_body)
        except RuntimeError as e:
            # 422 on a bad line: table already posted. Do not fake bubbles.
            print(f"review post failed (table stands): {e}")

    resolve_stale_threads(owner, repo, n, token, plus)
    print(f"hare ok model={used} intent={intent} bubbles={len(review_comments)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
