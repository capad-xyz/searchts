# Hare: thinking off vs thinking on, measured

The open question was whether Hare's review hop should let the model reason or
not. Hare Bot's read was that thinking on is the good review. Another read was
that thinking off answers in 30 seconds. Neither had been compared, because
every thinking-on run had returned nothing.

This measures both on the same PRs, same prompt, same model, with only the
reasoning knob differing.

## Method

- Model: `poolside/laguna-s-2.1:free` on Nous, the one hop that answers for free
- Prompt: the real `SYSTEM` plus `build_user` (AGENTS.md, title, body, CI, diff)
- Off: `"reasoning": {"effort": "none"}`. On: no reasoning field at all
- Both at `max_tokens` 32000, timeout 900 s
- Ground truth: inline review comments by `coderabbitai[bot]` and `Copilot` on
  that PR. Score is a match on file plus or minus 8 lines.
- PRs chosen because they actually have bot findings to compare against: 234,
  222, 224, 221, 223, 217, 218. 29 bot comments between them.

## Thinking on: 6 for 6, nothing came back

| PR | diff | time | reasoning tokens | completion tokens | output |
| --- | --- | --- | --- | --- | --- |
| #231 | 2 lines | 594 s | 32000 | 32000 | empty |
| #233 | 17 add | 574 s | 32012 | 32000 | empty |
| #227 | 40 add | 596 s | 32000 | 32000 | empty |
| #230 | 14 add | 576 s | 32000 | 32000 | empty |
| #221 | 1.5 KB | 516 s | 32082 | 32000 | empty |
| #224 | 23 KB | 517 s | 32000 | 32000 | empty |

Every one spent the entire budget on reasoning, returned `finish_reason=length`
with empty content, took 8.6 to 10 minutes, and produced no review. That includes
a 1.5 KB docs diff. The same failures were recorded earlier at 2500 and 8000
`max_tokens`, so this is not a budget that is merely too small.

## Thinking off: it answers

| PR | diff | time | findings | real | matched bot findings |
| --- | --- | --- | --- | --- | --- |
| #234 | 29 KB | 27 s | 7 | 5 | 1 of 9 |
| #224 | 23 KB | 28 s | 0 | 0 | 0 of 7 |
| #222 | 53 KB | 63 s | 1 | 0 | 0 of 7 |
| #221 | 1.5 KB | 9 s | 1 | 0 | 1 of 2 |
| #223 | 2.7 KB | 16 s | 1 | 0 | 1 of 2 |
| #217 | 6.5 KB | 20 s | fail, prose not JSON | 0 | 0 of 1 |
| #218 | 19 KB | 16 s | 3 | 0 | 0 of 1 |

`reasoning_tokens` was 0 on all seven. 6 of 7 produced a review, in 9 to 63
seconds.

## What this settles, and what it does not

It settles the viability question. Thinking on cannot be made to work on this hop
by widening the budget, because the model spends the whole budget thinking and
returns empty content at 32000 exactly as it did at 2500. `effort=none` is the
change that makes the hop answer, and it is now wired into `build_provider_chain`
for Nous, Groq and Zen.

It does not settle quality. Thinking off agrees with CodeRabbit and Copilot on
3 of 29 of their inline findings. That is a weak result and it should not be
glossed: 14 findings, 5 marked real, roughly a tenth overlap.

Two honest limits on that number. Low overlap does not prove off is wrong, two
competent reviewers can legitimately find different things. And matching by file
plus or minus 8 lines will miss a real finding that sits a section away from a
bot's. Still, nobody should claim thinking off produces the better review. It
produces a review, quickly.

So: default off, because it is the only mode that has produced a review at all.
But a `/hare deep` thinking-on escape hatch cannot be promised, because there is
no working deep mode to point it at yet.

## What to try next

`effort=low` rather than `none`. "Off" and "deep" are the endpoints being
compared, and a middle setting that reasons *and* answers inside the budget is
plausible and untested. That is the cheapest next experiment and it is one flag.

A second option is a different model that can reason and still answer. `effort=none`
is a workaround for a hop that cannot hold a budget, not proof that reasoning
hurts review quality.

## Reproducing

```
python scripts/hare_local.py <pr> --model nous:poolside/laguna-s-2.1:free
```

Hare Bot's position deserves a fair hearing: it was not wrong that thinking is
probably worth something for review quality. It was untestable here, and the
measurement says the hop cannot afford it.