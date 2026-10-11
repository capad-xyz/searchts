# Hare reasoning proofs: raw runs

What reasoning on and off actually cost and caught, on five old PRs whose answers
are already known. The table in [#359](https://github.com/capad-xyz/searchts/pull/359)
is **built from the files in this directory** by `scripts/hare_proof.py`, so a
reader can rebuild it and get the same numbers:

```bash
python scripts/hare_proof.py docs/proofs/hare-reasoning
```

Nothing here is a secret. Each file holds the request options, the model's own
answer, the token usage and what the stream carried. No key, no header, no token:
a raw file can be read in a public PR.

## Where the runs come from

`.github/workflows/hare-eval.yml`, dispatched by hand. It replays each case
against a provider with the reasoning mode under test and writes one file per
run with `--raw-dir`. It posts nothing on any PR and runs no live review.

## The answer key

[`docs/hare-proof-cases.json`](../../hare-proof-cases.json). Ground truth is
Hare's own ledger, not another bot's opinion, and the five cases carry the three
outcomes a proof has to separate:

| Case | PR | What happened there |
| --- | --- | --- |
| `245-proof` | #245 | a real finding, judged right, thread resolved |
| `247-proof` | #247 | a real finding, judged right, thread resolved |
| `248-proof` | #248 | a real finding, judged right, fixed by the author |
| `258-proof` | #258 | a real finding the owner judged **wrong** |
| `237-proof` | #237 | a real finding on a PR that closed unmerged |

#258 is the one that separates a better reviewer from a more confident one:
reproducing its finding as `real` is the same mistake again.

## One file

```
<case>__<provider>__<model>__<mode>__g<graph>__<attempt>.json
```

| Field | What it is |
| --- | --- |
| `case`, `pr`, `provider`, `model`, `mode`, `graph`, `attempt` | which cell this is |
| `request_options` | the reasoning field actually sent to that gateway |
| `answer` | the model's raw text, unparsed |
| `usage` | prompt, answer and `reasoning_tokens` |
| `stream` | what the stream carried, when it was cut |
| `error` | why a run returned nothing, if it did |

`mode` is `off`, `effort`, `budget` or `max`. `effort` and `budget` are the two
bounded shapes measured apart: a gateway takes `effort` **or** `max_tokens`, not
both, and a run that cannot tell them apart proves nothing.

A run with no `answer` is not a miss. It is a rate limit, a quota, a dead pin or
a timeout, and it is reported as an error rather than scored.

## Reading a result

Compare `request_options` first. If two runs differ in nothing but that field,
any difference in `usage.reasoning_tokens` or in what was caught is the reasoning
knob and nothing else.