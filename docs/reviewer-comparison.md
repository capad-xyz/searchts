# Hare and Hare Bot on this repo

Two reviewers, two products, same intent. Built by `scripts/compare_reviewers.py` from `docs/hare-ledger.json` and `docs/hare-bot-log-*`; Hare's own ledger does not carry this table.

Built 2026-10-03.

| | Hare (App) | Hare Bot (Grok Bot) |
| --- | --- | --- |
| PRs | 53 | 13 |
| Notes | 82 | 13 |
| Notes with a finding | 23 | 12 |
| Notes with nothing | 59 | 1 |
| Real findings | 5 | 15 |
| Skip findings | 24 | 16 |
| Real done | 0 (fixed or resolved, learned from later notes and threads) | 14 (marked fix: yes in its own log, not checked against the repo) |
| Minutes per note | 0.7 | 3.9 |
| Tokens per note | from the cost line, see the ledger | 12482 (its own chars/4 estimate) |

The two Real done columns are different kinds of number and are not a hit-rate comparison. Notes with nothing is where Hare's count is padded: a hop that answered but found nothing still posts a note.
