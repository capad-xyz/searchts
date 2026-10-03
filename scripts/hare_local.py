#!/usr/bin/env python3
"""Run Hare on a PR from this machine, with the keys already here. No Action, no credits.

    python scripts/hare_local.py 231                 # dry run, prints the review
    python scripts/hare_local.py 231 --post          # post it as your gh user
    python scripts/hare_local.py 231 --model nous:poolside/laguna-s-2.1:free
    python scripts/hare_local.py 231 --skip-checks   # do not wait on CI

Dry run is the default: nothing is written to GitHub and only the model hop costs
anything, which on the free keys is nothing. Keys come from the environment, or
from the opencode auth store so you do not have to go looking for them.

The Action is still the product path. This is the loop you can drive in a
terminal while the Action is on someone else's timer.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hare_r1 as H  # noqa: E402

# Hare's body is emoji-bearing and a Windows console defaults to cp1252.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

AUTH_STORE = Path(os.path.expanduser("~/.local/share/opencode/auth.json"))
PROVIDER_ALIASES = {"nous": "nous", "zen": "opencode", "opencode": "opencode", "or": "openrouter"}


def _from_auth_store(provider: str) -> str:
    """Best-effort local key lookup, so a dry run needs no setup."""
    alias = PROVIDER_ALIASES.get(provider)
    if not alias or not AUTH_STORE.is_file():
        return ""
    try:
        data = json.loads(AUTH_STORE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    entry = data.get(alias)
    if isinstance(entry, dict):
        key = entry.get("key")
        if isinstance(key, str) and key.strip():
            return key.strip()
    return ""


def _gh_token() -> str:
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        val = os.environ.get(name, "").strip()
        if val:
            return val
    proc = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
    return proc.stdout.strip()


def _resolve_hops(spec: str | None) -> list[tuple[str, str, str, str]]:
    """[(name, base, key, model)] from an explicit spec or the default free order."""
    if spec:
        out = []
        for item in spec.split(","):
            item = item.strip()
            if not item:
                continue
            if ":" not in item:
                raise SystemExit(f"--model wants provider:model, got {item!r}")
            provider, model = item.split(":", 1)
            provider = provider.strip()
            base = {"nous": H.NOUS_BASE, "zen": H.ZEN_BASE, "openrouter": H.OR_BASE}.get(provider)
            if base is None:
                raise SystemExit(f"unknown provider {provider!r}; use nous, zen or openrouter")
            key = (
                os.environ.get(
                    {
                        "nous": "SEARCHTS_HARE_API_KEY_NOUS",
                        "zen": "SEARCHTS_HARE_API_KEY_ZEN",
                        "openrouter": "SEARCHTS_HARE_API_KEY_OR",
                    }[provider],
                    "",
                ).strip()
                or _from_auth_store(provider)
            )
            out.append((provider, base, key, model.strip()))
        return out

    hops: list[tuple[str, str, str, str]] = []
    for name, base, env, default in (
        ("nous", H.NOUS_BASE, "SEARCHTS_HARE_API_KEY_NOUS", H.HARE_NOUS_DEFAULT),
        ("zen", H.ZEN_BASE, "SEARCHTS_HARE_API_KEY_ZEN", H.HARE_ZEN_DEFAULT),
        ("openrouter", H.OR_BASE, "SEARCHTS_HARE_API_KEY_OR", H.HARE_OR_DEFAULT),
    ):
        key = os.environ.get(env, "").strip() or _from_auth_store(name)
        if not key:
            continue
        hops.extend((name, base, key, m) for m in H._csv_models(f"HARE_{name.upper()}_MODEL", default))
    return hops


def main() -> int:
    ap = argparse.ArgumentParser(description="Run Hare on a PR locally.")
    ap.add_argument("pr", help="PR number")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "capad-xyz/searchts"))
    ap.add_argument("--model", help="provider:model[,provider:model...]. Overrides the default order.")
    ap.add_argument("--post", action="store_true", help="Post the review. Default is a dry run.")
    ap.add_argument("--ask", default="", help="A scoped maintainer ask, same as an @hare comment.")
    ap.add_argument("--skip-checks", action="store_true", help="Do not wait for CI to settle.")
    args = ap.parse_args()

    token = _gh_token()
    if not token:
        raise SystemExit("no GitHub token: run `gh auth login` or set GITHUB_TOKEN")
    hops = _resolve_hops(args.model)
    if not hops:
        raise SystemExit("no keys: set SEARCHTS_HARE_API_KEY_NOUS or run with --model nous:<slug>")

    if args.skip_checks:
        H.CHECK_WAIT_S = 0

    owner, repo = args.repo.split("/", 1)
    n = int(args.pr)

    original_post = H.post_needed
    original_deliver = H.deliver_review
    posted: list[str] = []

    def dry_needed(o: str, r: str, num: int, tok: str, why: str) -> None:
        posted.append(why)
        print("--- what the Action would have posted as the nag ---")
        print(H.needed_body(why))

    def dry_deliver(o: str, r: str, num: int, tok: str, sha: str, comment: str, bubbles: list[dict[str, Any]]) -> str:
        print("--- review body ---")
        print(comment)
        print(f"\n--- {len(bubbles)} inline bubble(s) ---")
        for b in bubbles:
            print(f"{b['path']}:{b['line']}\n{b['body']}")
        if not args.post:
            print("\ndry run. re-run with --post to write this to the PR.")
        return "review"

    H.post_needed = dry_needed
    H.deliver_review = dry_deliver

    # A local run is a manual run: skip the push cadence and the quiet period, the
    # same way workflow_dispatch does in the Action.
    os.environ["GITHUB_EVENT_NAME"] = "workflow_dispatch"
    if args.ask:
        os.environ["HARE_ASK"] = f"@hare {args.ask}"

    def keys_for(provider: str) -> str:
        return next((h[2] for h in hops if h[0] == provider), "")

    def models_for(provider: str) -> list[str]:
        return [h[3] for h in hops if h[0] == provider]

    print(f"hare local: {args.repo}#{n}  hops={[f'{h[0]}:{h[3]}' for h in hops]}")
    print(f"max_tokens={H.LLM_MAX_TOKENS} timeout={H.LLM_TIMEOUT_SEC}s budget={H.HOP_BUDGET_S}s")
    if args.post:
        print("POSTING: this writes a review to the PR as your gh user, not as the bot.")

    rc = H._hare_once(
        owner,
        repo,
        n,
        token,
        "",
        keys_for("nous"),
        keys_for("openrouter"),
        keys_for("zen"),
        models_for("nous"),
        models_for("openrouter"),
        models_for("zen"),
    )

    H.post_needed = original_post
    H.deliver_review = original_deliver
    if not args.post and posted:
        print("dry run. nothing was written to GitHub.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())