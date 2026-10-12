---
name: verify-login-lifecycle
description: Drive the real searchts logged-in-read lifecycle end to end and print a transcript proving each state, what prompts, and what is left on disk. Use before trusting a change to `searchts read`, `searchts login`, or the MCP login tools, and when asked whether the cookie feature is ready for a real user. Runs the real CLI against a throwaway HOME; opens no browser and reads no real cookie store.
---

# Verify the login lifecycle

The artifact this produces is a **transcript**, not a pass/fail line. It exists
because the review question for a safety feature is not "do the tests pass" but
"what does a person actually see, in what order, and what is left behind". A
green suite cannot answer that; this can.

Run it and paste the output into the PR. It is shorter than the diff and answers
the questions the diff raises.

## What it proves, and what it cannot

It drives the real `searchts` CLI and the real MCP surface, with a temporary
`USERPROFILE`, so:

- **Correctness.** Each of the four states produces its own distinct,
  recognisable output, and the two files that must never merge stay distinct.
- **Intent.** The consent question appears exactly where the design says it
  should, and nowhere else.
- **No residue.** Nothing is written to a real store.

It cannot prove a real site accepts a real login. That needs a human at a
browser, and the script says so rather than implying otherwise.

## Run it

```bash
python scripts/verify_login_lifecycle.py
```

Exit code 0 means every check held. Read the transcript either way: a check
that fails still tells you *which* behaviour changed, which is the part a pass
count throws away.

## The states, in the order the design names them

| state | setup | what the user should see |
|---|---|---|
| kept | seed the store, then a bare `read` | `owned store -> N cookies`, `already kept; no browser opened`, `(logged in)` |
| copy | not kept, `--cookies-from-browser`, no grant | refusal naming the per-session approval, exit 3, no network |
| copy, granted | grant, then the same read | `copied for this session only, not kept` |
| signin | not kept, nothing to copy | reads anonymously, then a login wall names both commands |
| kill | kept, then `login kill` | removed from the store; browser's own cookies explicitly left alone |

## Checking it can fail

The script prints a FAIL line and exits non-zero if any check breaks, so it is
usable as a gate and not only as a demo. To confirm that, break one thing on
purpose:

```bash
# in searchts/cli.py, make the bare read skip the store
#   return None   <-- instead of prepare(args.url)
python scripts/verify_login_lifecycle.py   # expect FAIL on "kept state"
git checkout searchts/cli.py
```

A verifier that cannot fail is a comment.

## On Windows

The script sets `USERPROFILE`, not `HOME`. `ntpath.expanduser` reads
`USERPROFILE` and ignores `HOME`, so a script that sets only `HOME` writes to
the real profile. This has bitten twice; the script refuses to run if it detects
it did not take effect.
