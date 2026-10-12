# Zen reasoning proof: five PRs, every published level

Built from the raw runs in [`zen/`](zen/) by

```bash
python scripts/hare_proof.py docs/proofs/hare-reasoning/zen --by-model \
    --out docs/proofs/hare-reasoning/zen-table.md
```

Nothing in this file is typed by hand. Re-run that command and it rewrites
itself from the same files, the same way
[`table.md`](table.md) is built from the runs above it.

## What was run

| Model | Arms | Calls |
| --- | --- | --- |
| `muse-spark-1.3-contributor-free` | default, xhigh | 10 |
| `space-bunny-free` | default, max | 10 |

5 prompts, the five PRs of the answer key plus the tiny one, one
call per model per level per prompt. `default` is the no-variant arm: Zen
publishes no way to turn reasoning off, so it is whatever the model does on
its own, not a disabled state. A cell that errored or timed out is reported
as partial: it is never dropped and never counted as an answer.

## Cells that outran their own timeout

- `space-bunny-free` max on 237-proof: 3,533 s, and it answered.

One cell like this is noise; several are a fact about the cap, not about the model.

## Per model and level

| Model | Level | Answered | Empty | Real caught | Expected | Wrong (#258) | Reals written | Median reasoning tok | Median s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `muse-spark-1.3-contributor-free` | default | 3 of 5 | 0 | 1 | 2 | 0 | 5 | 13,757 | 163 |
| `muse-spark-1.3-contributor-free` | xhigh | 4 of 5 | 0 | 2 | 3 | 0 | 8 | 13,570 | 76 |
| `space-bunny-free` | default | 5 of 5 | 0 | 2 | 4 | 0 | 8 | 14,738 | 127 |
| `space-bunny-free` | max | 3 of 5 | 0 | 2 | 2 | 0 | 4 | 20,985 | 208 |


Scored against [`hare-proof-cases.json`](../../hare-proof-cases.json), the five
PRs only. `Wrong (#258)` is the one column where a higher number is worse:
that finding is known to be wrong, so a run that repeats it as `real` has made
the same mistake again. `Empty` is an answer that parsed and carried no
findings at all. `Expected` counts only the cases that answered, so a model
is not charged for a finding it never had the chance to see.

## Per case

| Case | Provider | Model | Mode | Answered | Median s | Median reasoning tokens | Caps that fired |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 237-proof | zen | `muse-spark-1.3-contributor-free` | default | 0 of 1 | - | - | - |
| 237-proof | zen | `muse-spark-1.3-contributor-free` | xhigh | 1 of 1 | 179 | 17,511 | - |
| 237-proof | zen | `space-bunny-free` | default | 1 of 1 | 16 | 0 | - |
| 237-proof | zen | `space-bunny-free` | max | 1 of 1 | 3533 | 23,258 | - |
| 245-proof | zen | `muse-spark-1.3-contributor-free` | default | 1 of 1 | 262 | 21,214 | - |
| 245-proof | zen | `muse-spark-1.3-contributor-free` | xhigh | 0 of 1 | - | - | - |
| 245-proof | zen | `space-bunny-free` | default | 1 of 1 | 199 | 18,905 | - |
| 245-proof | zen | `space-bunny-free` | max | 1 of 1 | 208 | 20,985 | - |
| 247-proof | zen | `muse-spark-1.3-contributor-free` | default | 0 of 1 | - | - | - |
| 247-proof | zen | `muse-spark-1.3-contributor-free` | xhigh | 1 of 1 | 62 | 6,984 | - |
| 247-proof | zen | `space-bunny-free` | default | 1 of 1 | 100 | 9,837 | - |
| 247-proof | zen | `space-bunny-free` | max | 0 of 1 | - | - | - |
| 248-proof | zen | `muse-spark-1.3-contributor-free` | default | 1 of 1 | 163 | 13,757 | - |
| 248-proof | zen | `muse-spark-1.3-contributor-free` | xhigh | 1 of 1 | 82 | 19,148 | - |
| 248-proof | zen | `space-bunny-free` | default | 1 of 1 | 568 | 17,431 | - |
| 248-proof | zen | `space-bunny-free` | max | 0 of 1 | - | - | - |
| 258-proof | zen | `muse-spark-1.3-contributor-free` | default | 1 of 1 | 68 | 12,855 | - |
| 258-proof | zen | `muse-spark-1.3-contributor-free` | xhigh | 1 of 1 | 71 | 9,630 | - |
| 258-proof | zen | `space-bunny-free` | default | 1 of 1 | 127 | 14,738 | - |
| 258-proof | zen | `space-bunny-free` | max | 1 of 1 | 11 | 0 | - |

## Cells that returned nothing (partial, never dropped)

- `zen` `muse-spark-1.3-contributor-free` mode `default` (1 runs): timeout after 900s
- `zen` `muse-spark-1.3-contributor-free` mode `xhigh` (1 runs): timeout after 900s
- `zen` `space-bunny-free` mode `max` (1 runs): timeout after 900s

