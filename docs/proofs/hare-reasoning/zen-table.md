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
| `mimo-v2.6-flash-free` | default | 5 |
| `muse-spark-1.3-contributor-free` | default, high, low, medium, minimal, xhigh | 22 |
| `space-bunny-free` | default, max, medium, xhigh | 20 |
| `step-5-preview-free` | default, high, low | 15 |

6 prompts, the five PRs of the answer key plus the tiny one, one
call per model per level per prompt. `default` is the no-variant arm: Zen
publishes no way to turn reasoning off, so it is whatever the model does on
its own, not a disabled state. A cell that errored or timed out is reported
as partial: it is never dropped and never counted as an answer.

## Cells that outran their own timeout

- `step-5-preview-free` high on 248-proof: 1,890 s, and it answered.

One cell like this is noise; several are a fact about the cap, not about the model.

## Per model and level

| Model | Level | Answered | Empty | Real caught | Expected | Wrong (#258) | Reals written | Median reasoning tok | Median s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `mimo-v2.6-flash-free` | default | 3 of 5 | 0 | 0 | 2 | 0 | 7 | 17,304 | 463 |
| `muse-spark-1.3-contributor-free` | default | 5 of 5 | 0 | 1 | 4 | 0 | 8 | 14,383 | 112 |
| `muse-spark-1.3-contributor-free` | low | 5 of 5 | 0 | 2 | 4 | 0 | 7 | 1,454 | 24 |
| `muse-spark-1.3-contributor-free` | medium | 5 of 5 | 0 | 1 | 4 | 0 | 6 | 3,402 | 31 |
| `muse-spark-1.3-contributor-free` | xhigh | 5 of 5 | 0 | 1 | 4 | 0 | 10 | 16,062 | 119 |
| `space-bunny-free` | default | 5 of 5 | 0 | 1 | 4 | 0 | 4 | 10,331 | 83 |
| `space-bunny-free` | max | 5 of 5 | 0 | 3 | 4 | 0 | 14 | 13,665 | 122 |
| `space-bunny-free` | medium | 5 of 5 | 0 | 1 | 4 | 0 | 3 | 3,137 | 33 |
| `space-bunny-free` | xhigh | 5 of 5 | 0 | 2 | 4 | 0 | 7 | 7,903 | 81 |
| `step-5-preview-free` | default | 3 of 5 | 0 | 1 | 2 | 0 | 8 | 24,778 | 694 |
| `step-5-preview-free` | high | 2 of 5 | 0 | 0 | 2 | 0 | 5 | 20,123 | 1,347 |
| `step-5-preview-free` | low | 4 of 5 | 0 | 0 | 3 | 0 | 4 | 14,060 | 470 |


Scored against [`hare-proof-cases.json`](../../hare-proof-cases.json), the five
PRs only. `Wrong (#258)` is the one column where a higher number is worse:
that finding is known to be wrong, so a run that repeats it as `real` has made
the same mistake again. `Empty` is an answer that parsed and carried no
findings at all. `Expected` counts only the cases that answered, so a model
is not charged for a finding it never had the chance to see.

## Per case

| Case | Provider | Model | Mode | Answered | Median s | Median reasoning tokens | Caps that fired |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 237-proof | zen | `mimo-v2.6-flash-free` | default | 0 of 1 | - | - | - |
| 237-proof | zen | `muse-spark-1.3-contributor-free` | default | 1 of 1 | 120 | 14,383 | - |
| 237-proof | zen | `muse-spark-1.3-contributor-free` | low | 1 of 1 | 42 | 1,454 | - |
| 237-proof | zen | `muse-spark-1.3-contributor-free` | medium | 1 of 1 | 31 | 3,402 | - |
| 237-proof | zen | `muse-spark-1.3-contributor-free` | xhigh | 1 of 1 | 63 | 16,110 | - |
| 237-proof | zen | `space-bunny-free` | default | 1 of 1 | 200 | 36,395 | - |
| 237-proof | zen | `space-bunny-free` | max | 1 of 1 | 233 | 41,985 | - |
| 237-proof | zen | `space-bunny-free` | medium | 1 of 1 | 33 | 3,845 | - |
| 237-proof | zen | `space-bunny-free` | xhigh | 1 of 1 | 15 | 0 | - |
| 237-proof | zen | `step-5-preview-free` | default | 0 of 1 | - | - | - |
| 237-proof | zen | `step-5-preview-free` | high | 0 of 1 | - | - | - |
| 237-proof | zen | `step-5-preview-free` | low | 0 of 1 | - | - | - |
| 245-proof | zen | `mimo-v2.6-flash-free` | default | 0 of 1 | - | - | - |
| 245-proof | zen | `muse-spark-1.3-contributor-free` | default | 1 of 1 | 69 | 11,215 | - |
| 245-proof | zen | `muse-spark-1.3-contributor-free` | low | 1 of 1 | 83 | 2,158 | - |
| 245-proof | zen | `muse-spark-1.3-contributor-free` | medium | 1 of 1 | 36 | 4,533 | - |
| 245-proof | zen | `muse-spark-1.3-contributor-free` | xhigh | 1 of 1 | 141 | 16,062 | - |
| 245-proof | zen | `space-bunny-free` | default | 1 of 1 | 104 | 10,331 | - |
| 245-proof | zen | `space-bunny-free` | max | 1 of 1 | 164 | 20,698 | - |
| 245-proof | zen | `space-bunny-free` | medium | 1 of 1 | 48 | 4,596 | - |
| 245-proof | zen | `space-bunny-free` | xhigh | 1 of 1 | 284 | 35,046 | - |
| 245-proof | zen | `step-5-preview-free` | default | 0 of 1 | - | - | - |
| 245-proof | zen | `step-5-preview-free` | high | 0 of 1 | - | - | - |
| 245-proof | zen | `step-5-preview-free` | low | 1 of 1 | 886 | 26,520 | - |
| 247-proof | zen | `mimo-v2.6-flash-free` | default | 1 of 1 | 463 | 11,343 | - |
| 247-proof | zen | `muse-spark-1.3-contributor-free` | default | 1 of 1 | 58 | 5,613 | - |
| 247-proof | zen | `muse-spark-1.3-contributor-free` | low | 1 of 1 | 20 | 643 | - |
| 247-proof | zen | `muse-spark-1.3-contributor-free` | medium | 1 of 1 | 30 | 2,818 | - |
| 247-proof | zen | `muse-spark-1.3-contributor-free` | xhigh | 1 of 1 | 40 | 6,021 | - |
| 247-proof | zen | `space-bunny-free` | default | 1 of 1 | 83 | 9,943 | - |
| 247-proof | zen | `space-bunny-free` | max | 1 of 1 | 74 | 11,261 | - |
| 247-proof | zen | `space-bunny-free` | medium | 1 of 1 | 35 | 3,137 | - |
| 247-proof | zen | `space-bunny-free` | xhigh | 1 of 1 | 73 | 7,597 | - |
| 247-proof | zen | `step-5-preview-free` | default | 1 of 1 | 504 | 17,363 | - |
| 247-proof | zen | `step-5-preview-free` | high | 1 of 1 | 805 | 18,550 | - |
| 247-proof | zen | `step-5-preview-free` | low | 1 of 1 | 240 | 9,065 | - |
| 248-proof | zen | `mimo-v2.6-flash-free` | default | 1 of 1 | 805 | 20,571 | - |
| 248-proof | zen | `muse-spark-1.3-contributor-free` | default | 1 of 1 | 130 | 17,858 | - |
| 248-proof | zen | `muse-spark-1.3-contributor-free` | low | 1 of 1 | 24 | 1,908 | - |
| 248-proof | zen | `muse-spark-1.3-contributor-free` | medium | 1 of 1 | 43 | 4,212 | - |
| 248-proof | zen | `muse-spark-1.3-contributor-free` | xhigh | 1 of 1 | 119 | 16,901 | - |
| 248-proof | zen | `space-bunny-free` | default | 1 of 1 | 74 | 11,702 | - |
| 248-proof | zen | `space-bunny-free` | max | 1 of 1 | 93 | 13,665 | - |
| 248-proof | zen | `space-bunny-free` | medium | 1 of 1 | 20 | 1,940 | - |
| 248-proof | zen | `space-bunny-free` | xhigh | 1 of 1 | 139 | 18,878 | - |
| 248-proof | zen | `step-5-preview-free` | default | 1 of 1 | 694 | 24,778 | - |
| 248-proof | zen | `step-5-preview-free` | high | 1 of 1 | 1890 | 21,696 | - |
| 248-proof | zen | `step-5-preview-free` | low | 1 of 1 | 578 | 17,177 | - |
| 258-proof | zen | `mimo-v2.6-flash-free` | default | 1 of 1 | 303 | 17,304 | - |
| 258-proof | zen | `muse-spark-1.3-contributor-free` | default | 1 of 1 | 112 | 16,407 | - |
| 258-proof | zen | `muse-spark-1.3-contributor-free` | low | 1 of 1 | 23 | 1,392 | - |
| 258-proof | zen | `muse-spark-1.3-contributor-free` | medium | 1 of 1 | 27 | 2,157 | - |
| 258-proof | zen | `muse-spark-1.3-contributor-free` | xhigh | 1 of 1 | 195 | 9,755 | - |
| 258-proof | zen | `space-bunny-free` | default | 1 of 1 | 11 | 0 | - |
| 258-proof | zen | `space-bunny-free` | max | 1 of 1 | 122 | 13,295 | - |
| 258-proof | zen | `space-bunny-free` | medium | 1 of 1 | 33 | 2,273 | - |
| 258-proof | zen | `space-bunny-free` | xhigh | 1 of 1 | 81 | 7,903 | - |
| 258-proof | zen | `step-5-preview-free` | default | 1 of 1 | 788 | 25,383 | - |
| 258-proof | zen | `step-5-preview-free` | high | 0 of 1 | - | - | - |
| 258-proof | zen | `step-5-preview-free` | low | 1 of 1 | 363 | 10,943 | - |
| tiny-prompt | zen | `muse-spark-1.3-contributor-free` | high | 1 of 1 | 10 | 600 | - |
| tiny-prompt | zen | `muse-spark-1.3-contributor-free` | minimal | 1 of 1 | 10 | 492 | - |

## Cells that returned nothing (partial, never dropped)

- `zen` `mimo-v2.6-flash-free` mode `default` (1 runs): timeout after 900s
- `zen` `step-5-preview-free` mode `default` (1 runs): timeout after 900s
- `zen` `step-5-preview-free` mode `high` (1 runs): timeout after 900s
- `zen` `step-5-preview-free` mode `low` (1 runs): timeout after 900s

