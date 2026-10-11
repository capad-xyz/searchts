# How long the big AI PR reviewers take, and when they stop

Research for the timing caps in [`scripts/hare_r1.py`](../../scripts/hare_r1.py) and
[`docs/hare-next.md`](../hare-next.md). Measured 2026-10-11 against public GitHub data:
**581 product-PR observations across 564 unique public PRs, 16 products, 946 review messages**.

Every claim carries one of three labels:

| Label | Meaning |
| --- | --- |
| **MEASURED** | Computed from public GitHub API data by the harness in [Appendix A](#appendix-a-the-harness). The printed command reproduces the query method; exact historical raw snapshots are kept in ignored `.hare-timing/` work notes and are not committed. |
| **DOCUMENTED** | A cited public source says it: vendor docs, a changelog, source code, or a real posted comment. |
| **DERIVED** | Not published. Reasoned from the architecture, with the reasoning shown. |

No number here is estimated. Where a vendor does not publish a figure, the row says
**not public** and the gap is left open rather than filled with a guess. Where a number
came from the team rather than from this survey, it says so.

---

## The metric, and why it is not the obvious one

The obvious number, "PR opened to review posted", is **not** a measure of how long a
reviewer takes. A pull request sits open for days while a human works on it, so that gap
measures the PR's idle time, not the bot's queue. In our own CodeRabbit sample it
produced a maximum of **767 hours** on a bot whose median answer arrives in under five
minutes. A second trap: several reviewers re-review days later when someone asks, which
puts multi-hour and multi-day values into the same distribution as a real queue.

The harness therefore reports three things, and this document leans on the first:

| Metric | Definition | What it measures |
| --- | --- | --- |
| **reaction** (primary) | For every bot message: message time minus the latest commit time at or before message time + 60 s. The 60 s widens commit matching for near-simultaneous timestamps; it is not added to the reported gap. | How long the reviewer takes to answer a push. This is the number that sizes a timeout. |
| reaction, reactive subset | The same, restricted to messages that arrived within 3,600 s of their commit. | The distribution when the reviewer is actually running. |
| open to first | PR `created_at` to the bot's first message. | Idle time on the PR plus latency. Reported for context, never used for sizing. |

The 60-second matching window can yield a negative reaction when the matched commit is
slightly later than the bot message. The measured pool contains 39 such gaps, from -60 s
to -1 s; they are retained in the reported distributions.

### What the one-hour cut costs, and what that means for every number below

The reactive subset is what makes the table readable, and it is also the table's main
weakness: **every p99 and every max in this document is a lower bound.** The one-hour cut
removes 0% to 30% of each vendor's messages by construction, and it removes the slow ones.
We cannot prove the excluded messages are all non-push-triggered; some are plausibly
genuine slow reviews. A reviewer whose real latency is 90 minutes would show up here as
no data rather than as a 90 minute row. Read the max column as "the worst turn we saw
that completed within an hour", never as "the worst turn this reviewer takes".

| Product | messages | excluded (>1h) | excluded share |
| --- | --- | --- | --- |
| Cursor Bugbot | 93 | 28 | 30% |
| CodeRabbit | 169 | 21 | 12% |
| Korbit | 59 | 8 | 14% |
| Greptile | 54 | 7 | 13% |
| GitHub Copilot code review | 135 | 7 | 5% |
| Macroscope | 68 | 6 | 9% |
| Sourcery | 51 | 3 | 6% |
| Cubic | 24 | 2 | 8% |
| Gemini Code Assist | 22 | 2 | 9% |
| Qodo Merge | 122 | 2 | 2% |
| Mergify, Graphite Agent, Ellipsis, Codacy, Amazon Q Developer, DeepSource | 35, 32, 33, 24, 20, 5 | 0 | 0% |

The 3,600 s threshold is a judgement call, not a fact. A 5,400 s cut would fold more of
the tail in; a 1,800 s cut would hide more. It was fixed before the per-product results
were read, and it applies identically to all sixteen products, but a different author
would have produced a different table.

### Three known biases, stated rather than hidden

- **Merged PRs only.** The harness queries `states: [MERGED]`, excluding open PRs and
  PRs closed without merging. This conditions the sample on merged work; it does not show
  whether the resulting distribution represents all PRs or a typical repository.
- **The last 100 commits.** Reaction latency needs the most recent commit before each
  message, so the harness reads `commits(last: 100)`. A PR with more than 100 commits
  therefore contributes no sample for a message older than its 100th commit. An earlier
  version of the harness read the *oldest* 100, which silently dropped every message after
  the 100th commit and biased the tail down; that is fixed, and the table below was
  re-measured after the fix.
- **40 reviews and 60 issue comments per PR.** The query requests only the first 40
  reviews and 60 issue comments. Later bot messages would be omitted if a PR exceeded
  those limits. The snapshot does not record total connection sizes, so it cannot show
  whether any PR hit either cap.

### What reaction latency cannot tell you

It cannot separate "the bot queued for 40 minutes" from "the bot read a large diff and
thought about it for 40 minutes". Both are a 40 minute gap. For timeout sizing the
distinction does not matter: the timeout has to cover the larger of the two, and per-PR
queue time is not published by anyone.

---

## Summary table

**MEASURED**, reaction latency, reactive subset (messages arriving within an hour of
their commit), and therefore **lower bounds on the tail** as explained above. Percentiles
are computed from the local raw reaction snapshots in `.hare-timing/raw2/*.json` and
rounded to the nearest second, which is what the harness prints. Those snapshots are
ignored work notes and are not part of the committed report.

| Product | PRs | repos | messages (all) | messages (<=1h) | median | p90 | p99 | max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Mergify | 30 | 4 | 35 | 35 | 7m17s | 16m23s | 27m53s | 28m16s |
| Cursor Bugbot | 30 | 3 | 93 | 65 | 5m45s | 25m32s | 47m40s | 51m04s |
| CodeRabbit | 70 | 11 | 169 | 148 | 4m46s | 21m26s | 41m59s | 57m18s |
| Cubic | 20 | 1 | 24 | 22 | 3m58s | 21m08s | 24m32s | 25m11s |
| Gemini Code Assist | 30 | 4 | 22 | 20 | 2m48s | 12m44s | 45m22s | 48m37s |
| GitHub Copilot code review | 120 | 21 | 135 | 128 | 2m36s | 14m19s | 42m28s | 53m41s |
| Greptile | 34 | 5 | 54 | 47 | 2m25s | 15m53s | 42m32s | 42m34s |
| Macroscope | 30 | 5 | 68 | 62 | 2m22s | 24m42s | 30m37s | 35m53s |
| Qodo Merge | 32 | 6 | 122 | 120 | 2m08s | 11m53s | 36m51s | 39m01s |
| Graphite Agent | 30 | 3 | 32 | 32 | 2m04s | 3m52s | 10m52s | 13m54s |
| Sourcery | 32 | 6 | 51 | 48 | 1m54s | 22m02s | 42m36s | 53m57s |
| Korbit | 30 | 5 | 59 | 51 | 1m30s | 5m56s | 19m33s | 22m38s |
| Ellipsis | 30 | 4 | 33 | 33 | 82s | 3m20s | 27m33s | 31m21s |
| Codacy | 28 | 4 | 24 | 24 | 79s | 5m36s | 16m07s | 18m43s |
| Amazon Q Developer | 30 | 4 | 20 | 20 | 64s | 5m45s | 15m09s | 17m20s |
| DeepSource | 5 | 2 | 5 | 5 | 39s | 2m15s | 2m16s | 2m16s |

Three rows carry caveats that belong next to them, not in a footnote: **Mergify** is a
merge queue rather than a review, **Cubic** is one repository and has no product
documentation at all, and **DeepSource** is 5 messages from 2 repos, which is a smoke
test rather than a measurement.

For completeness, the next table shows **PR-open to first bot message** for the same
sampled PRs. These are real elapsed times, but they include how long a PR sat idle before
the bot's first message; they are context, not estimates of review runtime.

| Product | PRs | median open-to-first | p90 open-to-first | max open-to-first |
| --- | ---: | ---: | ---: | ---: |
| Mergify | 30 | 8m26s | 16m01s | 32m47s |
| Cursor Bugbot | 30 | 2h29m16s | 43h29m13s | 465h53m07s |
| CodeRabbit | 70 | 16s | 5m24s | 767h35m27s |
| Cubic | 20 | 3m04s | 10m12s | 19m15s |
| Gemini Code Assist | 30 | 1m26s | 4m02s | 5m39s |
| GitHub Copilot code review | 120 | 8s | 9m20s | 32h49m30s |
| Greptile | 34 | 2m43s | 9m29s | 1h24m41s |
| Macroscope | 30 | 2m04s | 20m15s | 1h55m34s |
| Qodo Merge | 32 | 36s | 1h33m51s | 43h24m18s |
| Graphite Agent | 30 | 1m34s | 3m06s | 5h07m18s |
| Sourcery | 32 | 6s | 21s | 25h07m35s |
| Korbit | 30 | 25s | 2m49s | 5m37s |
| Ellipsis | 30 | 36s | 1m55s | 21m47s |
| Codacy | 28 | 59s | 3m59s | 6m23s |
| Amazon Q Developer | 30 | 35s | 53s | 1m28s |
| DeepSource | 5 | 1m02s | 3m24s | 4m59s |

**MEASURED examples:** each link is a public PR whose bot message produced the product's
largest reaction gap within the one-hour subset. The reaction metric includes the 60 s
slack described above. The links let a reader inspect the commit and bot timestamps
directly; they are examples, not the full sample.

| Product | Public PR | Largest within-hour reaction |
| --- | --- | ---: |
| Mergify | [oaslananka/kicad-mcp-pro#1202](https://github.com/oaslananka/kicad-mcp-pro/pull/1202) | 28m16s |
| Cursor Bugbot | [BerriAI/litellm#42212](https://github.com/BerriAI/litellm/pull/42212) | 51m04s |
| CodeRabbit | [Synesthesias/PLATEAU-SDK-for-Unity#590](https://github.com/Synesthesias/PLATEAU-SDK-for-Unity/pull/590) | 57m18s |
| Cubic | [gosuda/bitcoin-rs#1476](https://github.com/gosuda/bitcoin-rs/pull/1476) | 25m11s |
| Gemini Code Assist | [GoogleCloudPlatform/scion#3191](https://github.com/GoogleCloudPlatform/scion/pull/3191) | 48m37s |
| GitHub Copilot code review | [valzargaming/valgorithms.com#4](https://github.com/valzargaming/valgorithms.com/pull/4) | 53m41s |
| Greptile | [CodesWhat/drydock#1252](https://github.com/CodesWhat/drydock/pull/1252) | 42m34s |
| Macroscope | [RaspberryPiFoundation/editor-api#1048](https://github.com/RaspberryPiFoundation/editor-api/pull/1048) | 35m53s |
| Qodo Merge | [containerbase/base#7659](https://github.com/containerbase/base/pull/7659) | 39m01s |
| Graphite Agent | [tscircuit/circuit-json#862](https://github.com/tscircuit/circuit-json/pull/862) | 13m54s |
| Sourcery | [kagemorikosame/sashimono-edit#292](https://github.com/kagemorikosame/sashimono-edit/pull/292) | 53m57s |
| Korbit | [RealDevSquad/website-backend#2492](https://github.com/RealDevSquad/website-backend/pull/2492) | 22m38s |
| Ellipsis | [ostis-ai/sc-machine#503](https://github.com/ostis-ai/sc-machine/pull/503) | 31m21s |
| Codacy | [Grid2op/grid2op#768](https://github.com/Grid2op/grid2op/pull/768) | 18m43s |
| Amazon Q Developer | [gosuda/bitcoin-rs#1495](https://github.com/gosuda/bitcoin-rs/pull/1495) | 17m20s |
| DeepSource | [kamihi-org/kamihi#101](https://github.com/kamihi-org/kamihi/pull/101) | 2m16s |

### Reading the table

- **The median is minutes.** Thirteen of sixteen products answer inside four minutes. The
  three that do not are Mergify (7m17s, a merge queue), Cursor Bugbot (5m45s) and
  CodeRabbit (4m46s).
- **The tail is tens of minutes.** Nine products have a p90 between 11 and 25 minutes.
  Six reach a p99 above 40 minutes: Bugbot, Gemini Code Assist, CodeRabbit, Copilot,
  Greptile and Sourcery.
- **Every tail number is a floor, not a ceiling.** The worst single turn that completed
  inside the one-hour cut is **57m18s** (CodeRabbit). That is not the worst turn any of
  these reviewers takes: it is the worst one in a sample that discards everything slower
  than an hour. Gaps beyond an hour may include queue delay or a later review unrelated
  to the latest commit; public timestamps alone do not distinguish those cases. Neither
  queue delay nor review duration is visible from a percentile alone.
- **Nobody publishes an SLA.** Not one of these vendors publishes a latency distribution,
  a p90, or a per-review timeout for its hosted reviewer. Every number in this table is
  MEASURED by us because the vendor did not.

---

## Per-product notes

Each section gives the bot identity, where it runs, the architecture, the caps, and what
it posts when it stops. The reproduce command is printed where one exists.

### CodeRabbit

```bash
python3 .hare-timing/measure_latency.py --author coderabbitai --label CodeRabbit \
  --repo ReactorKit/ReactorKit --repo crweiner/hacktoberfest-swag-list \
  --repo facioquo/stock-indicators-dotnet --repo pubnub/javascript \
  --repo zard-ui/zardui --repo aiidateam/aiida-core \
  --per-repo 8 --max-prs 40 --since 2025-06-01 \
  --json-out .hare-timing/raw2/coderabbit.json
python3 .hare-timing/measure_latency.py --author coderabbitai --label CodeRabbit \
  --repo ForgeRock/forgerock-android-sdk --repo NVlabs/gbrl \
  --repo RedHatInsights/digital-roadmap-frontend --repo SCAICT/SCAICT-uwu \
  --repo Synesthesias/PLATEAU-SDK-for-Unity --per-repo 8 --max-prs 30 \
  --since 2025-06-01 --json-out .hare-timing/raw2/coderabbit4.json
# The table pools reaction_s samples from these two outputs.
```

GitHub App, login `coderabbitai`, **runs on CodeRabbit's own infrastructure**, not on a
customer runner ([quickstart](https://docs.coderabbit.ai/getting-started/quickstart)).

- **Architecture (DOCUMENTED):** incremental by default: "CodeRabbit re-reviews a pull
  request after each new push, focusing on the commits added since the last review"
  ([auto-review](https://docs.coderabbit.ai/configuration/auto-review)). Multi-stage: a
  smaller model summarises and triages the diff, then a more expensive model reviews it,
  with the cheaper model used "as an advanced similarity filter before invoking the more
  expensive gpt-4 model"
  ([cost-effective](https://www.coderabbit.ai/blog/how-we-built-cost-effective-generative-ai-application)).
  The cache is that semantic comparison: a file whose new summary matches the last one is
  skipped.
- **Caps (DOCUMENTED, [plans](https://docs.coderabbit.ai/management/plans)):** files per
  review after path filters: Free 150, OSS 100 to 300 by popularity, Essentials 150,
  Team and above 300. "Reviews with more than 300 files are not supported through usage
  pricing." Reviews per developer per rolling hour: Free 1, OSS 1 to 10 by stars,
  Essentials 5, Team 8, Advanced 10, Enterprise 12. Fair usage drops the refill rate to
  one review per hour above a 7-day threshold
  ([rate limits](https://docs.coderabbit.ai/management/rate-limits#fair-usage-limits-policy)).
- **Stops with a comment, not silence.** Real strings on public PRs: "**Review skipped**
  / Auto incremental reviews are disabled on this repository"
  ([compressed-tensors#668](https://github.com/vllm-project/compressed-tensors/pull/668));
  "**Review skipped** / Draft detected"
  ([reinhardt-web#4754](https://github.com/kent8192/reinhardt-web/pull/4754));
  "**Review limit reached** ... More reviews will be available in **N minutes**"
  ([israeli-bank-scrapers#402](https://github.com/sergienko4/israeli-bank-scrapers-to-actual-budget/pull/402));
  "**Reviews paused** / It looks like this branch is under active development"
  ([kb-yaml-to-lens#1579](https://github.com/strawgate/kb-yaml-to-lens/pull/1579)). The commit
  status goes `success` when the review is rate limited or skipped, so a missing review
  never blocks a merge ([monorepo#2676](https://github.com/devantler-tech/monorepo/issues/2676)).
- **Free vs paid (DOCUMENTED):** Free $0, one review per hour, summary only, no inline
  review on the PR. OSS free on public repos, 1 to 10 reviews per hour by stars, enrolled
  through the dashboard ([oss](https://coderabbit.ai/oss)). Essentials $24 per user per
  month, Team $48, Advanced $72, Enterprise on request.
- **Not found:** a published per-review timeout, a token budget, or chunking behaviour
  for large diffs. Not public.

Diff-size correlation was not measured by this harness: its snapshot records timestamps
and PR URLs, not additions, deletions or changed-file counts.

### GitHub Copilot code review

Three runs, pooled into the row above (the harness has no pooling mode, so all three
commands are printed; the pool is the union of their raw reaction samples):

```bash
python3 .hare-timing/measure_latency.py --author copilot-pull-request-reviewer \
  --label "GitHub Copilot code review" --repo home-assistant/core \
  --repo nocobase/nocobase --repo tmc/langchaingo --repo tbphp/gpt-load \
  --repo Provenance-Emu/Provenance --repo github/gh-aw --per-repo 7 --max-prs 40 \
  --since 2025-06-01 --json-out .hare-timing/raw2/copilot.json
python3 .hare-timing/measure_latency.py --author copilot-pull-request-reviewer \
  --label "GitHub Copilot code review" --repo imogenlabs/homelabarr-ce \
  --repo maniator/verticopolis --repo Johnaverse/chains-api \
  --repo JacobCoffee/litestar-workflows --repo mandeeps/SU-WaterCam \
  --repo AFK-surf/still.fail --repo jmgirard/cairn --per-repo 6 --max-prs 40 \
  --since 2025-06-01 --json-out .hare-timing/raw2/copilot2.json
python3 .hare-timing/measure_latency.py --author copilot-pull-request-reviewer \
  --label "GitHub Copilot code review" --repo Jyerxa/agent-skills \
  --repo snehOP9/portfolio-website --repo mbeacom/adrkit-azure \
  --repo DavidDudson/pioneer --repo Shedrackeze002/EduCore \
  --repo Lucenx9/signaltty --repo quanho114/ohmyt --repo valzargaming/valgorithms.com \
  --per-repo 6 --max-prs 40 --since 2025-06-01 \
  --json-out .hare-timing/raw2/copilot3.json
```

The table pools all `rows[].reaction_s` from those three files, then filters to values
at most 3,600 seconds before computing the displayed percentiles.

- **Architecture (DOCUMENTED):** agentic, and this is the important line: "Copilot code
  review utilizes agentic capabilities ... Full project context gathering ... This
  capability analyzes your entire repository to better understand the context of code
  changes." It **runs in GitHub Actions on the customer's runner**: "Copilot code review
  uses GitHub Actions to run the agentic capabilities ... By default, Copilot code review
  uses standard GitHub-hosted runners." Degradation is documented too: if Actions fails,
  reviews are still generated without the agentic features. All quotes:
  [code review](https://docs.github.com/en/copilot/concepts/code-review/code-review).
- **Model (DOCUMENTED):** not disclosed and not choosable: "Model switching is not
  supported, as changing the model is likely to compromise reliability, user experience,
  and the quality of review comments." The org picks an effort level, not a model.
- **Size scaling:** not measured by this harness. Its snapshot does not include additions,
  deletions or changed-file counts.
- **Re-review frequency (MEASURED, local raw2 snapshot):** 16 of 120 PRs got more than
  one bot message. This count is reproducible from the per-PR `n_bot_msgs` values in the
  local JSON. The snapshot does not preserve per-message timestamps, so calculating the
  gaps between those messages needs a fresh GitHub query.
- **Per-push re-review latency (MEASURED, separate earlier pass):** across 30 repositories,
  13 of 120 PRs had more than one bot message. Of those, 23 gaps under 30 minutes are
  the clean rapid push-and-review cycles: median **9m41s**, p90 19m54s, max 27m18s.
  This is the number most like a second Hare run. It came from a different repository
  set than the raw2 sample. The old raw capture is in ignored work notes, not committed;
  a fresh query is needed to reproduce the per-message gaps.
- **Limits:** **no timeout, no wall-clock ceiling, no SLA is published. Not public.** The
  only implicit bound is the Actions job limit. The widely quoted per-hour table (free
  10/h, Pro 50/h, Pro+ 300/h, Enterprise 1000/h) is **obsolete**: GitHub moved to
  usage-based billing on 2026-06-01
  ([changelog](https://github.blog/changelog/2026-04-27-github-copilot-code-review-will-start-consuming-github-actions-minutes-on-june-1-2026/))
  and the current [usage-limits page](https://docs.github.com/en/copilot/concepts/usage-limits)
  publishes no numbers. The unit is AI credits: "A review typically consumes an estimated
  $0.05 USD to $1 USD worth of AI credits with 'Lite' effort, and $0.25 USD to $5 USD
  worth of AI credits with 'Balanced' effort" (code review page, linked above).
- **Free vs paid (DOCUMENTED):** **Copilot Free does not include code review on
  GitHub.com**: "This includes users who have no Copilot license and users on the Copilot
  Free plan, which does not include Copilot code review." Pro $10, Pro+ $39, Max $100,
  Business $19 per seat, Enterprise $39 per seat ([plans](https://docs.github.com/en/copilot/get-started/plans)).
  On public repositories Actions minutes stay free, but AI credits still come from the
  plan ([billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)).

### Qodo Merge and Qodo PR-Agent (open source)

Qodo Merge is hosted SaaS. PR-Agent is the open source tool it grew from, and PR-Agent is
the more useful comparison because its caps are in the source, not in marketing.

**PR-Agent caps, read from source and verified directly (DOCUMENTED, file and line):**

| Cap | Value | Where |
| --- | --- | --- |
| Per-call LLM timeout | **120 s** (`ai_timeout=120 # 2 minutes`) | [`pr_agent/settings/configuration.toml:32`](https://github.com/qodo-ai/pr-agent/blob/main/pr_agent/settings/configuration.toml#L32) |
| Attempts per model | **2** (`MODEL_RETRIES = 2`, `stop=stop_after_attempt(MODEL_RETRIES)`) | [`litellm_ai_handler.py:149`](https://github.com/qodo-ai/pr-agent/blob/main/pr_agent/algo/ai_handlers/litellm_ai_handler.py#L149) and `:2795` |
| Token ceiling per model | 32,000 (`max_model_tokens = 32000`) | [`configuration.toml:51`](https://github.com/qodo-ai/pr-agent/blob/main/pr_agent/settings/configuration.toml#L51) |
| Host HTTP timeout | 60 s default, capped at 600 s | [`request_timeout.py:6`](https://github.com/qodo-ai/pr-agent/blob/main/pr_agent/git_providers/request_timeout.py#L6) |
| Retry on timeout | `retry_same_model_on_timeout = true`; false moves straight to `fallback_models` | [`configuration.toml:34`](https://github.com/qodo-ai/pr-agent/blob/main/pr_agent/settings/configuration.toml#L34) |
| Nothing new to review | posts "Incremental Review Skipped / No files were changed since the previous PR Review" | `pr_reviewer.py:347` |

Verified against the live `main` tree on 2026-10-11, not from vendor docs. Two details
matter for Hare. **120 s per call is aggressive**: PR-Agent runs frontier models with a
small prompt, expects an answer inside two minutes, and has a fallback chain behind the
timeout (`retry_with_fallback_models`). And its token ceiling is 32,000, the same as
Hare's `HARE_MAX_TOKENS`. On failure, a `RateLimitError`, `BadRequestError` or
`UnprocessableEntityError` never retries the same model; an `APITimeoutError` retries only
when `retry_same_model_on_timeout` is true. Retries are immediate, with no backoff
(**DERIVED**: read the retry decorator and `_should_retry_same_model`; neither sleeps).

**Chunking and caching (DOCUMENTED, from source):** large diffs are chunked, and
`_prepare_chunked_prediction` / `_resize_pending_review_chunks` /
`_include_newly_reviewable_files` (`pr_reviewer.py:981-1145`) reuse successful chunks
across attempts, so a fallback model does not resend work already done.

**Incremental (DOCUMENTED, from source):** `synchronize` dispatches
`handle_push_trigger_for_new_commits`; `_get_incremental_commits`
(`github_provider.py:290-335`) finds the bot's own previous review and builds an
unreviewed-file map from only the new commits. With no previous review it logs "No
previous review found, will review an entire PR". A rebase that removes every earlier
commit falls back to a full review.

**Qodo Merge hosted (DOCUMENTED):** reviews on open and on every push, with a "Per commit"
trigger that updates the same review
([effort control](https://docs.qodo.ai/code-review/use-qodo-in-prs/control-review-effort)).
Metered in credits; "No rate limits" is claimed on the
[pricing page](https://www.qodo.ai/pricing/). No per-PR diff-size cap is published: not
public. 14-day trial, Pro Team $30/month, free for qualified open source.

### Sourcery

```bash
python3 .hare-timing/measure_latency.py --author 'sourcery-ai[bot]' --label Sourcery \
  --repo sportsdataverse/sportsdataverse-py --repo mindroom-ai/mindroom \
  --repo Heretek-AI/IUMBTEMS --repo amanthanvi/noctty \
  --repo framerslab/agentos-extensions --repo kagemorikosame/sashimono-edit \
  --per-repo 6 --max-prs 32 --since 2025-06-01 \
  --json-out .hare-timing/raw2/sourcery.json
```

Note for anyone reproducing: the REST API returns the login as `sourcery-ai[bot]` and
GraphQL returns `sourcery-ai`. The harness normalises the `[bot]` suffix; without it the
sample is silently empty.

- **Runs on vendor infrastructure**, as a hosted review bot
  ([trust](https://docs.sourcery.ai/trust/code-retention/)). A self-hosted Enterprise tier
  exists but does not change the hosted defaults.
- **Caps (DOCUMENTED, [plans](https://docs.sourcery.ai/admin/plans/)):** metered in diff
  **characters**, not tokens or files. Per pull request: Open Source 150,000, Pro 300,000,
  Team 500,000. Rolling 7-day budget: Open Source 250,000 per developer, Pro 1,500,000 per
  seat, Team 2,500,000 per seat. "A re-review costs a tenth of a normal review."
- **The stop-after-N rule (DOCUMENTED):** automatic re-reviews are capped at five per
  pull request ([plans](https://docs.sourcery.ai/admin/plans/)). Past the cap, the check
  reports `Skipped` ([anatomy](https://docs.sourcery.ai/reviews/anatomy-of-a-review/)).
  A rate limit "never blocks a merge" ([plans](https://docs.sourcery.ai/admin/plans/)). This is
  the only hard "stop after N reviews" rule found anywhere in this survey.
  `@sourcery-ai review` resets the counter.
- **Incremental (DOCUMENTED):** reviews on open and re-reviews after every commit; "a
  re-review does less than the first review".
- **Free vs paid (DOCUMENTED):** Open Source free on public repos; Pro $15/month, Team
  $30/month; Enterprise adds self-hosted, GHE Server, SSO, BYOK and on-prem.

### Greptile

```bash
python3 .hare-timing/measure_latency.py --author 'greptile-apps[bot]' --label Greptile \
  --repo CodesWhat/drydock --repo CodesWhat/sockguard --repo fussybeaver/roctokit \
  --repo theseedship/duckdb_mcp_node --repo prgrms-aibe-devcourse/AIBE4_FinalProject_Team4 \
  --per-repo 9 --max-prs 34 \
  --since 2025-06-01 --json-out .hare-timing/raw2/greptile_wide.json
```

- **Architecture (DOCUMENTED):** a codebase graph built at signup (directories, files,
  functions, classes, variables plus their relationships). At review time it queries three
  layers per changed function: dependencies, usage and pattern consistency
  ([how Greptile works](https://www.greptile.com/docs/how-greptile-works/graph-based-codebase-context)).
  Inference runs on Greptile's hosted service. The graph is cached and updated
  incrementally; a full re-index is only forced by a config reload.
- **Latency driver (DOCUMENTED):** indexing is asynchronous and is the real first-review
  cost. Greptile's own v5 write-up acknowledges "Review latency is a practical concern.
  Reviews taking several minutes versus 30 seconds changes the workflow dynamics", and a
  customer's first-review guide tags "Indexing complete (first time: ~1-2 hours)" as a
  prerequisite for automatic review
  ([first PR review](https://www.greptile.com/docs/code-review/first-pr-review)). A first
  review of a large repo is therefore much slower than the steady state in our table.
- **Caps:** `fileChangeLimit` is configurable and no hard line cap is published (not
  public). Drafts are skipped by default. The docs show "Analyzing" during review and
  the failed status "Tag @greptileai to retry"
  ([first PR review](https://www.greptile.com/docs/code-review/first-pr-review)).
- **Free vs paid (DOCUMENTED):** 14-day trial on signup, then paid; the free plan includes
  PR reviews only, and CLI reviews need a trial or a paid plan
  ([quickstart](https://www.greptile.com/quickstart)).

### Macroscope

```bash
python3 .hare-timing/measure_latency.py --author macroscopeapp --label Macroscope \
  --repo pydantic/pydantic-ai --repo pydantic/pydantic-ai-harness \
  --repo xmtp/libxmtp --repo strawgate/kb-yaml-to-lens \
  --repo RaspberryPiFoundation/editor-api --per-repo 7 --max-prs 30 \
  --since 2025-06-01 --json-out .hare-timing/raw2/macroscope.json
```

- **Architecture (DOCUMENTED):** AST-based reference graph, plus "web search for current
  library and API documentation" ([AI code review](https://macroscope.com/ai-code-review)).
  Four detection modes, Budget, Balanced, Precise and Ultra, where Ultra is "more parallel
  agents and advanced models" ([detection mode](https://docs.macroscope.com/code-review/detection-mode)),
  so wall time scales with the chosen mode. Re-reviews are differential: "Later pushes
  compare against the previously reviewed HEAD" ([pricing](https://docs.macroscope.com/pricing)).
  **Runs on vendor infrastructure.**
- **Caps (DOCUMENTED, [spend limits](https://docs.macroscope.com/spend-limits)):** a hard
  monthly workspace limit, a **$10 default per-review cap** and a **$50 default per-PR
  cap**. "Per-PR cost limit exceeded (workspace setting)" appears in the spend-limit docs;
  "Maximum runs reached" and "File too large (exceeds configured limit)" appear in the
  [bug-detection docs](https://docs.macroscope.com/bug-detection-and-fixes). One more, measured on a real PR
  ([kb-yaml-to-lens#1579](https://github.com/strawgate/kb-yaml-to-lens/pull/1579)): "Diff
  is too large for automated approval analysis. A human reviewer should evaluate this PR."
  No wall-clock timeout is published: not public.
- **Free vs paid (DOCUMENTED):** $100 free on signup, then usage pricing by diff size:
  Budget $0.025/KB, Balanced $0.05/KB, Precise $0.06/KB, Ultra $0.20/KB.

### Graphite Agent and Diamond

```bash
python3 .hare-timing/measure_latency.py --author graphite-app --label Graphite \
  --repo tscircuit/footprinter --repo tscircuit/jlcsearch \
  --repo tscircuit/circuit-json --per-repo 10 --max-prs 30 \
  --since 2025-06-01 --json-out .hare-timing/raw2/graphite.json
```

- **Architecture (DOCUMENTED):** multi-step rather than one shot. Anthropic's customer
  write-up: "Their architecture breaks complex code analysis into discrete steps, allowing
  Claude to excel at each specific task" ([Anthropic](https://www.anthropic.com/customers/graphite)).
  What is sent is the PR metadata, the changed code, and "Related or similar parts of your
  codebase", not a documented whole-repo dump
  ([privacy](https://graphite.com/docs/ai-privacy-and-security)). **Runs on vendor
  infrastructure** behind the Graphite App; AI reviews on new pull requests.
- **Caps:** no token budget, timeout, file cap or rate limit is published for AI reviews.
  Not public. The stop condition is plan gating: "Limited AI Reviews" on Free and Starter,
  "Unlimited AI Reviews" on Team ([pricing](https://graphite.com/pricing)). The March 2025
  Diamond launch offered "free for up to 100 PRs reviewed per month"; that number is no
  longer on the pricing page.
- **Free vs paid (DOCUMENTED):** Free, Starter $20/user/month, Team $40/user/month,
  Enterprise on request.
- **Incremental (MEASURED):** nearly every sampled PR got exactly one review, a few got
  two, so Graphite re-reviews far less than Macroscope or CodeRabbit.

### Cursor Bugbot

```bash
python3 .hare-timing/measure_latency.py --author 'cursor[bot]' --label "Cursor Bugbot" \
  --repo BerriAI/litellm --repo snyk/user-docs --repo reactive/data-client \
  --per-repo 10 --max-prs 30 \
  --since 2025-06-01 --json-out .hare-timing/raw2/bugbot-final.json
```

This row is the one the earlier draft got wrong, so it is worth reading carefully: Bugbot
**is** measurable, and it has by far the worst excluded fraction in the survey (28 of 93
messages arrived more than an hour after their commit, including on `snyk/user-docs`). The
timestamps do not show whether those were requested reviews or unusually slow automatic
runs. Its reactive median of 5m45s describes only messages within the one-hour cut.

- **Where it runs:** Cursor cloud, not a customer runner (**DERIVED**: reviews are queued
  through the dashboard Automations and an endpoint that returns when the review is
  *queued* and runs asynchronously; no self-hosted step is documented). Model names are
  not public.
- **Architecture (DOCUMENTED, [bugbot](https://cursor.com/docs/bugbot)):** incremental by
  default: "By default, Bugbot reviews only the changes since the previous Bugbot review.
  Turn off Incremental Review in Bugbot Automations to review the full pull request diff
  on every push." It reads existing PR comments "to avoid duplicate suggestions and build
  on prior feedback", and skips a diff it has already reviewed by git patch-id.
- **Effort levels (DOCUMENTED, same page):** Low, Default, High, Smart, and the trade is
  stated plainly: "Higher effort levels can find more bugs, but each review may take
  longer and take up more usage." This is an **operator's** choice made up front, not an
  automatic downgrade when a review runs long, and it is the clearest vendor statement in
  this survey that slow is bought deliberately rather than cut.
- **Caps (DOCUMENTED, same page):** each rule truncated at 30,000 characters, combined
  rules capped at 100,000; autofix makes at most 3 attempts per PR; files over 64 KB are
  ignored. Trigger API 30 requests/min/team. Token budget, max files or lines and
  per-plan review rate limits: **not public**.
- **Timeout (DOCUMENTED, a user report plus staff diagnosis, not an SLO):** runs fail
  after about 20 minutes. Cursor staff on the forum: "This looks like a known class of
  BugBot timeout failures. About 20 minutes until a generic error usually means either an
  unhandled exception or an infra timeout somewhere along the way." Staff later fixed "the
  parts of BugBot that were failing for you, including the step behind the 20-minute
  failures" ([thread](https://forum.cursor.com/t/bugbot-fails-after-20-minutes/160592)).
  **This is the one measured-ish timeout figure any vendor in this survey publishes, and
  it is smaller than Hare's proposed 1,800 s per call.** Bugbot buys that by reviewing
  only the diff and by offering effort levels that change the work, not by shortening a
  slow model.
- **Give-up wording (DOCUMENTED, same page):** the check concludes `neutral` when "Bugbot
  found issues, the run was cancelled by a newer commit, or Bugbot hit an internal error",
  and "Bugbot does not emit a `skipped` conclusion". Users see "Something went wrong. Try
  again by commenting 'Cursor review' or 'bugbot run'".
- **Free vs paid (DOCUMENTED, [pricing](https://cursor.com/pricing), [May 2026 change](https://cursor.com/blog/may-2026-bugbot-changes)):** usage-based since 2026-05-11; "The average Bugbot run costs $1.00-$1.50, depending on PR size and complexity". Included in Pro $20/mo, Pro+ $60/mo, Ultra $200/mo and Teams $40 per user; **the free Hobby plan does not include Bugbot**.

### Bito AI Code Review Agent

- **Latency (MEASURED status):** not measured. The public-repo probes found no eligible
  merged PR rows for the `bitoai` author across `microsoft/vscode`, `facebook/react` and
  code-search discovery. That is insufficient data for a median, p90 or max; it does not
  establish that Bito never reviews public PRs.
- **Where it runs and architecture (DOCUMENTED, [overview](https://docs.bito.ai/ai-code-reviews-in-git), [product](https://bito.ai/product/ai-code-review-agent/)):**
  the product is available as a GitHub App through Bito's cloud service, with an optional
  self-hosted Docker deployment. The vendor describes specialized reviewers for performance, structure,
  security, optimization and scalability, plus static-analysis and repository-context
  inputs. This is a multi-reviewer design, not evidence that every review runs in parallel.
- **Incremental review (DOCUMENTED, [commands](https://docs.bito.ai/ai-code-reviews-in-git/available-commands)):**
  `/review` checks changes since the previous review; `/review full` analyzes the entire
  PR. `/pause`, `/resume` and `/abort` control automatic or in-progress reviews.
- **Limits and stop conditions:** no public per-review timeout, token budget, file/line
  cap, rate limit, chunking or cache behavior found. A review can be cancelled with
  `/abort`; if enabled, formal request-changes comments can block merging under branch protection
  ([request-changes behavior](https://docs.bito.ai/ai-code-reviews-in-git/request-changes-comments)).
- **Free vs paid (DOCUMENTED, [overview](https://docs.bito.ai/ai-code-reviews-in-git), [product](https://bito.ai/product/ai-code-review-agent/)):**
  Free includes AI-generated PR summaries; the 14-day free trial exposes the Agent, and
  line-level suggestions are described as a Team-plan feature. Public pricing details
  were not established in the pages checked.

### Ellipsis

```bash
python3 .hare-timing/measure_latency.py --author 'ellipsis-dev[bot]' --label Ellipsis \
  --repo ostis-ai/sc-machine --repo onfleet/node-onfleet \
  --repo wallet-ui/wallet-ui --repo jellydn/vite-react-demo \
  --per-repo 10 --max-prs 30 \
  --since 2025-06-01 --json-out .hare-timing/raw2/ellipsis-final.json
```

- **Fastest reviewer in the survey by a wide margin**: median 1m22s, and no message in the
  sample took more than 31m21s. Its own customer data claims "Median review 2m"
  ([use cases](https://www.ellipsis.dev/use-cases/code-review)); that is vendor data, not
  public-repo data, and is not comparable to the measured sample.
- **Where it runs:** vendor infrastructure, a GitHub App, plus a documented **agent
  runtime** that runs each reviewer's work in a sandboxed environment
  ([code-review](https://docs.ellipsis.dev/code-review)).
- **Wall-clock timeout:** no public per-review or agent-environment timeout was found.
  An internal Ellipsis `SKILL.md` was mentioned during research, but it is not published
  on the public documentation site and cannot support a public product limit.
- **Caps (DOCUMENTED, [code-review](https://docs.ellipsis.dev/code-review), [budgets](https://docs.ellipsis.dev/budgets)):** a review file allows up to 8 reviewers; at most 30 comments per reviewer and 60 per review are posted. More than 30 from one reviewer fails that reviewer; comments beyond 60 remain in the review but are not posted. Session spend defaults to $250, cannot be set above $250 (or a lower account ceiling), and reaching the budget ends the turn with `budget_hit` (`failed` if working, `cancelled` if it had not started). Max files or lines, token budget per file and a per-review seconds limit: **not public**.
- **Failure wording (DOCUMENTED, [code-review](https://docs.ellipsis.dev/code-review)):** "A reviewer that fails or runs out of
  budget contributes nothing; the review still posts with the other reviewers' comments,
  never as an approval, and that reviewer covers the same commits again on the next
  push." and "When no reviewer finishes, nothing is posted and nothing is marked reviewed."
- **Free vs paid (DOCUMENTED):** the platform bills tokens at cost plus a 10% platform
  fee with no per-seat charge, and a legacy per-seat product is still documented at $20
  per developer per month with a 7-day trial. The marketing root still says "We're free
  for public GitHub repositories!", and the pricing page's "Is it free for open source?"
  answer did not render when fetched, so the current open-source position is **not
  established**.

### Korbit

```bash
python3 .hare-timing/measure_latency.py --author korbit-ai --label Korbit \
  --repo RealDevSquad/website-backend --repo guibranco/BancosBrasileiros-MergeTool \
  --repo ioncakephper/aidoccli --repo ioncakephper/markdown-cleaner-cli \
  --repo ioncakephper/cli-starter \
  --per-repo 8 --max-prs 30 --since 2025-06-01 --json-out .hare-timing/raw2/korbit-final.json
```

- **Reactive median 1m30s, p90 5m56s, max 22m38s** across 30 PRs in 5 repos. An earlier
  draft of this document claimed Korbit was unmeasurable; that was wrong, and the row
  above is the measured one.
- **Latest first-message timestamp in the sample.** The latest `first_bot_at` value is
  **2025-11-18** on `RealDevSquad/website-backend#2506`. The sample includes PRs
  #2492, #2499-2502, and #2504-2506; it does not store timestamps for every later bot
  message, so it cannot establish the latest Korbit activity across all messages.
  Separately, a public comment on `apache/superset#36172` was observed during research,
  but that repository is not in the latency sample. A `--since 2026-01-01` sweep of
  `RealDevSquad/website-backend` and `guibranco/BancosBrasileiros-MergeTool` returned
  nothing; this does not establish global silence.
- **What happened (DOCUMENTED):** Boost Security announced the acquisition of Korbit.ai
  on **2026-05-06**, with $4M of additional funding, and writes about the technology in
  the past tense
  ([announcement](https://www.prnewswire.com/news-releases/boost-security-announces-acquisitions-of-secureiqx-and-korbitai-and-4m-in-additional-funding-302764164.html),
  [Boost blog](https://boostsecurity.io/blog/announcing-two-acquisitions-and-a-funding-round)).
  `docs.korbit.ai` and `app.korbit.ai` were unreachable from this network on 2026-10-11
  and the get-started page 404s. **No first-party shutdown notice was found**, so the
  honest statement is: acquired, docs gone, public activity stops in November 2025, and
  the row describes how it behaved while it was running.
- **Architecture (DOCUMENTED):** an AI review agent over the PR diff, incremental by
  default, requestable with `/korbit-review`. Its free open-source tier had a documented
  two-scan queue, which is consistent with the multi-hour non-reactive gaps on
  `RealDevSquad/website-backend` (**DERIVED**: the shape of those gaps, not a
  measurement of the queue).

### Gemini Code Assist, Amazon Q Developer, Mergify, Codacy, Cubic, DeepSource

| Product | Login | Where it runs | Architecture | Caps and stop conditions |
| --- | --- | --- | --- | --- |
| Gemini Code Assist | `gemini-code-assist` | Vendor (Google Cloud, Developer Connect) | Single pass on open, with a conversational follow-up (`/gemini review`). Repo-level severity floor and file exclusions via `.gemini/config.yaml`. | No per-call timeout, token budget or file cap published: **not public**. Free during Preview above the Developer Connect free tier ([docs](https://docs.cloud.google.com/gemini/docs/code-review/use-code-assist-github)). |
| Amazon Q Developer | `amazon-q-developer` | Vendor (AWS) | **Single pass, on open and reopen only. Not incremental.** "Automatic code reviews are not triggered by subsequent commits made within an existing pull request." Filters unsupported languages and test code before the model; custom rules live in `.amazonq/rules`. | Quota in lines of code per month, number not published in docs. The only timing statement is qualitative: "It can take a few minutes for Amazon Q Developer to complete analyzing the pull request code." Free with a monthly cap; registering with an AWS account raises it ([tiers](https://docs.aws.amazon.com/amazonq/latest/qdeveloper-ug/q-tiers.html)). |
| Mergify | `mergify` | Mergify's own queue, with customer CI triggered on its queue branch | Merge queue, not a review: speculative merges and CI batching. | `max_checks_retries` defaults to 0 ([queue rules](https://docs.mergify.com/merge-queue/rules/)); `checks_timeout` and `batch_max_wait_time` exist as rules, defaults not public. Give-up string: "The queue request has been cancelled: new commits were pushed" ([kicad-mcp-pro#1207](https://github.com/oaslananka/kicad-mcp-pro/pull/1207)). Free for open source and teams up to 5 users, then $21 per seat. |
| Codacy | `codacy-production` | Vendor cloud, "entirely in the cloud, eliminating the need for servers or build steps" | Hybrid: deterministic analysis plus context-aware reasoning across security, coverage, complexity and duplication | Caps documented: 150 KB per source file, 5,000 files for duplication, 50 issues per file per tool, and **25 comments on the Git provider** ([limits](https://docs.codacy.com/faq/code-analysis/does-codacy-place-limits-on-the-code-analysis)). It stops because it hit an output cap, not a timeout. Open Source $0, Team $21 per user per month. |
| Cubic | `cubic-dev-ai` | Vendor | Not documented at all. One repository in the sample (`gosuda/bitcoin-rs`), so this is the weakest measured row in the table. | **No product documentation or free/paid details found. Not public.** |
| DeepSource | `deepsource-io` | Vendor, "activate a repository and analysis starts" | Hybrid: "5,000+ deterministic rules with a state-of-the-art AI review agent" ([marketplace](https://github.com/marketplace/deepsource-io)) | Nothing about timeouts, retry behavior or current free/paid tiers published in the pages checked: **not public**. 5 messages from 2 repos; a smoke test, not a measurement. |

Exact re-measurement commands for the grouped rows above:

```bash
python3 .hare-timing/measure_latency.py --author mergify --label Mergify \
  --repo oaslananka/kicad-mcp-pro --repo iamolegga/nestjs-session \
  --repo iamolegga/nestjs-roles --repo iamolegga/nestjs-cookie-session \
  --per-repo 8 --max-prs 30 --since 2025-06-01 --json-out .hare-timing/raw2/mergify.json
python3 .hare-timing/measure_latency.py --author cubic-dev-ai --label Cubic \
  --repo gosuda/bitcoin-rs --per-repo 20 --max-prs 20 --since 2025-06-01 \
  --json-out .hare-timing/raw2/cubic.json
python3 .hare-timing/measure_latency.py --author gemini-code-assist --label "Gemini Code Assist" \
  --repo GoogleCloudPlatform/scion --repo genkit-ai/genkit --repo gpustack/runner \
  --repo vllm-project/vllm-ascend --per-repo 8 --max-prs 30 --since 2025-06-01 \
  --json-out .hare-timing/raw2/gemini.json
python3 .hare-timing/measure_latency.py --author qodo-code-review --label "Qodo Merge" \
  --repo kstruck/MMPoolsV3 --repo vfarcic/dot-agent-deck --repo containerbase/base \
  --repo Medal-Social/Pilot --repo GlacierEQ/the-tower-of-babel \
  --repo the-newnormal/moduleone --per-repo 6 --max-prs 32 --since 2025-06-01 \
  --json-out .hare-timing/raw2/qodo-merge.json
python3 .hare-timing/measure_latency.py --author codacy-production --label Codacy \
  --repo facioquo/stock-indicators-dotnet --repo algolia/shipjs \
  --repo oaslananka/kicad-mcp-pro --repo Grid2op/grid2op \
  --per-repo 8 --max-prs 28 --since 2025-06-01 --json-out .hare-timing/raw2/codacy.json
python3 .hare-timing/measure_latency.py --author amazon-q-developer --label "Amazon Q Developer" \
  --repo gosuda/bitcoin-rs --repo ThePlenkov/bro --repo sinoda1114/stack-summary \
  --repo jbcom/declarative-hex-worlds --per-repo 8 --max-prs 30 --since 2025-06-01 \
  --json-out .hare-timing/raw2/amazonq.json
python3 .hare-timing/measure_latency.py --author deepsource-io --label DeepSource \
  --repo localzet/nestjs-supervisor --repo kamihi-org/kamihi --per-repo 4 --max-prs 20 \
  --since 2025-06-01 --json-out .hare-timing/raw2/deepsource.json
```

Among those products, Cubic and DeepSource have thin samples (Cubic: 20 PRs in one repo;
DeepSource: 5 bot messages across two repos). Treat those measurements as descriptive
only.

---

## What happens at the limit

The public stop signals vary: some products show a named skipped/failed status or comment,
some document silent no-post behavior, and several do not publish a timeout or oversized-
diff response. This is why Hare's give-up path should name the reason rather than rely on
users to infer what happened from silence.

| Product | Situation | What the user sees | Source |
| --- | --- | --- | --- |
| CodeRabbit | auto-review off | "**Review skipped** / Auto incremental reviews are disabled on this repository." | [compressed-tensors#668](https://github.com/vllm-project/compressed-tensors/pull/668) |
| CodeRabbit | draft PR | "**Review skipped** / Draft detected." | [reinhardt-web#4754](https://github.com/kent8192/reinhardt-web/pull/4754) |
| CodeRabbit | quota | "**Review limit reached** ... More reviews will be available in N minutes." Status stays green. | [israeli-bank-scrapers#402](https://github.com/sergienko4/israeli-bank-scrapers-to-actual-budget/pull/402) |
| CodeRabbit | active branch | "**Reviews paused** / It looks like this branch is under active development." | [kb-yaml-to-lens#1579](https://github.com/strawgate/kb-yaml-to-lens/pull/1579) |
| Sourcery | re-review cap or quota | the `Sourcery review` check reports `Skipped` | [anatomy](https://docs.sourcery.ai/reviews/anatomy-of-a-review/) |
| Macroscope | per-PR spend cap | "Per-PR cost limit exceeded (workspace setting)" | [spend limits](https://docs.macroscope.com/spend-limits) |
| Macroscope | run cap | "Maximum runs reached" | [bug detection](https://docs.macroscope.com/bug-detection-and-fixes) |
| Macroscope | diff too big to auto-approve | "Diff is too large for automated approval analysis. A human reviewer should evaluate this PR." | [kb-yaml-to-lens#1579](https://github.com/strawgate/kb-yaml-to-lens/pull/1579) |
| Qodo PR-Agent | no new commits | "Incremental Review Skipped / No files were changed since the previous PR Review" | `pr_reviewer.py:347` |
| Qodo PR-Agent | every model failed | raises "Failed to generate prediction with any model of ..." | `pr_processing.py:830` |
| Qodo Merge | close to the GitHub API limit | log line "Rate limit is too close to the limit, will not proceed"; user-visible wording not established | source log |
| Mergify | new commits during a queued merge | "The queue request has been cancelled: new commits were pushed." | [kicad-mcp-pro#1207](https://github.com/oaslananka/kicad-mcp-pro/pull/1207) |
| Greptile | review does not appear | docs recommend a manual `@greptileai` trigger; exact failure wording could not be verified | [first PR review](https://www.greptile.com/docs/code-review/first-pr-review) |
| Cursor Bugbot | internal error or timeout | a fast note: "Something went wrong. Try again by commenting 'Cursor review' or 'bugbot run'", check concludes `neutral`, and "Bugbot does not emit a `skipped` conclusion" | [forum thread](https://forum.cursor.com/t/bugbot-fails-after-20-minutes/160592), [bugbot](https://cursor.com/docs/bugbot) |
| Ellipsis | a reviewer fails or runs out of budget | "contributes nothing; the review still posts with the other reviewers' comments, never as an approval". With no reviewer finishing, "nothing is posted and nothing is marked reviewed" | [code-review](https://docs.ellipsis.dev/code-review) |
| Ellipsis | a session hits a spend cap | the turn ends "with reason set to `budget_hit`: failed when the agent was working, cancelled when it hadn't started" | [budgets](https://docs.ellipsis.dev/budgets) |
| Bito | review paused or cancelled by user | `/pause` stops automatic reviews; `/abort` cancels in-progress reviews. No timeout-failure wording found. | [commands](https://docs.bito.ai/ai-code-reviews-in-git/available-commands) |
| Amazon Q, Ellipsis, Graphite, Codacy, Cubic, DeepSource, Bito | timeout, too-big, rate-limited | **not found** in the pages fetched | |
| ADO Pilot (outside the brief) | run queued with no verdict | "Over 30 minutes with no progress means open a support request"; "a genuinely stuck review can hold that slot for up to 90 minutes before the system clears it automatically" | [stuck review](https://adopilot.dev/docs/troubleshooting/stuck-review) |

### Retry behaviour

- **Sourcery:** a re-review costs one tenth of a normal review against the 7-day budget,
  capped at 5 automatic re-reviews per PR.
- **CodeRabbit:** a superseded review still spends quota
  ([rate limits](https://docs.coderabbit.ai/management/rate-limits#superseded-reviews)).
- **Mergify:** `max_checks_retries` defaults to 0, that is, do not retry.
- **Qodo PR-Agent:** 2 attempts per model, immediate, no backoff, then a fallback model.
- **Qodo Merge:** a 429 drops that provider for the rest of the run.
- **Nobody publishes a p90 or an SLO.** Where a vendor has a number it is a plan limit,
  not a latency promise.

---

## Whether vendors give up on slow models

This was asked directly, because it decides whether a slow free model belongs in a chain
at all. **Public evidence does not support a universal rule.** A few products document
fixed effort selection or exception fallback; for several others, the public sources
reviewed do not describe what happens when a model is slow.

| Product | Drops or downgrades a slow model? | Evidence |
| --- | --- | --- |
| CodeRabbit | No | Evaluates latency per model during onboarding and rolls back bad rollouts, but publishes no per-review "too slow, switch model" rule. Over-limit reviews continue on paid usage, not a cheaper model ([rate limits](https://docs.coderabbit.ai/management/rate-limits)). |
| Copilot code review | No | No doc statement about reducing reasoning or swapping models for latency. It selects the model up front and never switches: "Model switching is not supported." |
| Qodo Merge | No | An **effort router picks Fast, Balanced or Deep per change risk in advance** ([control review effort](https://docs.qodo.ai/code-review/use-qodo-in-prs/control-review-effort)); it does not downgrade mid-review. |
| Qodo PR-Agent | Fallback exists, triggered by exception not slowness | `retry_with_fallback_models` catches `APIError`, `TimeoutError` and `FallbackEligibleError`. A slow model that answers is kept. |
| Sourcery | No | Depth is a static profile (Quiet, Balanced, Verbose), not an adaptive latency downgrade. |
| Greptile | No | No doc about dropping slow models, thinking budgets, or chain shortening. |
| Cursor Bugbot | Operator's choice, never automatic | The clearest statement in the survey, and it cuts the other way: "Higher effort levels can find more bugs, but each review may take longer and take up more usage" ([bugbot](https://cursor.com/docs/bugbot)). The operator buys the slowness up front rather than the product cutting it mid-review. |
| Amazon Q Developer | No | It limits **scope** instead: auto review only on open and reopen, never on later pushes. |
| Ellipsis | No, and it says so in the failure path | "A reviewer that fails or runs out of budget contributes nothing; the review still posts with the other reviewers' comments, never as an approval, and that reviewer covers the same commits again on the next push." A reviewer that dies is retried on the next push, not swapped for a cheaper one. |
| Bito | No public policy found | The reviewed sources document incremental/full commands and specialized reviewers, but not whether it swaps models when a reviewer is slow. |
| Macroscope, Graphite, Gemini Code Assist, Codacy | **no evidence found** | No page fetched states a slow-model fallback. This is "we looked and did not find it", not "it does not happen": absence of a published rule is not evidence of absence. |
| ADO Pilot | No faster-model fallback documented | Its troubleshooting page says a stuck review may hold a queue slot up to 90 minutes before it is cleared; this describes queue recovery, not model switching. |

Examples of documented work limits include Macroscope's effort mode selected in advance,
Amazon Q's lack of automatic re-review after later pushes, Sourcery's cap on automatic
re-reviews, and CodeRabbit's pause during an active burst of commits. These examples do
not establish how every product handles a slow model.

---

## Reviewers that run in your own runner

This is the class Hare belongs to: the review runs inside the customer's GitHub Actions
runner, so its timeout is a number in a YAML file rather than a vendor's internal budget.

| Product or platform | `timeout-minutes` | LLM request timeout | Source |
| --- | --- | --- | --- |
| **GitHub Actions, the ceiling itself** | **360**: "The maximum number of minutes to run the step before killing the process. Maximum: 360 for both GitHub-hosted and self-hosted runners." At job level, "The maximum number of minutes to let a job run before GitHub automatically cancels it. Default: 360." A GitHub-hosted **job** is separately "terminated at 6 hours of execution time". | n/a | [step timeout](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idstepsstepstimeout-minutes), [job timeout](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idtimeout-minutes), [job execution limit](https://docs.github.com/en/actions/reference/limits) |
| Qodo PR-Agent, self-hosted | **15** | 120 s per model, 2 attempts | [`pr-agent-review.yaml`](https://github.com/qodo-ai/pr-agent/blob/main/.github/workflows/pr-agent-review.yaml), [`configuration.toml:32`](https://github.com/qodo-ai/pr-agent/blob/main/pr_agent/settings/configuration.toml#L32) |
| GitHub Copilot code review | Not published. Falls back to a non-agentic review if Actions fails | Not published | [code review](https://docs.github.com/en/copilot/concepts/code-review/code-review) |
| CodeRabbit, Sourcery, Greptile, Bugbot, Gemini, Amazon Q, Macroscope, Graphite, Ellipsis, Korbit | n/a: hosted GitHub Apps, no customer workflow | Not published | |

Six hours is therefore the hard ceiling, and Hare at 120 minutes uses a third of it.

---

## What this means for Hare

Hare's free models are slower than every reviewer in the table. Step 5 Preview answers in
**13 to 15 minutes (780 to 900 s)** per review at reasoning on. That number is the
project's own measurement on live PRs, supplied by the team; **this survey did not
measure it**, and nothing below should be read as if it had. It is the one input to the
recommendation that is not independently reproducible.

Set against it: the fastest measured reviewer answers in 64 seconds, and the median
reviewer in two to five minutes. That is a fact, not a reason to drop Step 5. Public
evidence does not show a universal vendor policy for slow models. The owner has ruled
that only quality evidence (real catches, wrong findings, empty reviews) moves a model
down or out of the chain.

The owner also reports Space Bunny at 20 to 140 seconds per review. This is an
owner-supplied runtime range, not part of the vendor sample. It fits well within the
normal 1,800 s call ceiling; Step 5's longer reported runtime sets the timeout instead.

So the numbers below are sized to **fit** the slow model, not to prune it. This is a
project policy backed by Hare's own runtime measurement and the lack of quality evidence
for demoting that model, not a conclusion that surveyed vendors all do the same.

| Hare's ceiling | From | To | Why, with the evidence |
| --- | --- | --- | --- |
| `LLM_TIMEOUT_SEC` (per call) | 600 s | **1800 s** | Step 5 answers in 780 to 900 s (owner-supplied team measurement). At 600 s the per-call ceiling cuts the chain's best model off before it finishes, which is the one outcome the 300 to 600 s raise existed to prevent. 1800 s is **twice the slowest reported Hare hop**. It is deliberately *stricter* than the vendors' reactive tails rather than inside their band: CodeRabbit p99 41m59s, Copilot 42m28s, Sourcery 42m36s, Bugbot 47m40s. Hare is allowed to be slower than the median vendor review (2m36s to 4m46s) and should not also borrow their worst case, which is a lower bound on a tail this survey cannot fully see. |
| `BIG_LLM_TIMEOUT_SEC` | 900 s | **2700 s** | A big diff must get more time than a small one. Raising the normal tier to 1,800 s would overtake the old 900 s big-diff allowance, so the big tier rises to 2,700 s and stays larger. This is 45 minutes, three times Step 5's reported 900 s. It sits **above** Macroscope's (35m53s) and Qodo Merge's (39m01s) worst reactive turns and **below** the five that reach 48 to 58 minutes (Gemini 48m37s, Bugbot 51m04s, Copilot 53m41s, Sourcery 53m57s, CodeRabbit 57m18s). That is deliberate: this survey cannot see past its own one-hour cut, so a big-diff tier set from a tail it cannot observe would be set from a number that does not exist. 2700 s fits inside the 3,300 s big chain budget and the 3,600 s wall clock. |
| `HOP_BUDGET_S` (chain) | 1800 s | **2700 s** | The chain budget has to be at least one full slow call, or raising the per-call ceiling buys nothing: with an 1800 s budget and a 2700 s call, the second hop would only ever see the time the first one happened not to use. 2700 s leaves 900 s after an 1800 s first hop for a second and keeps the 150 s reserve for Groq and Gemini intact. |
| `BIG_HOP_BUDGET_S` | 3300 s | **3300 s** (unchanged) | Still above the big per-call timeout (2700 s), still under the wall clock (3600 s). |
| `HARE_REVIEW_WALL_CLOCK_S` | 3600 s | **3600 s** (unchanged) | Already 60 minutes, four times the slowest Hare hop. It is 2m42s above the worst reactive turn measured in this sample (57m18s), but that maximum is a lower bound because the sample excludes messages beyond one hour. The wall clock bounds each model hop and leaves time before the 120-minute job limit for CI and posting. Raising it is not needed to fit Step 5. |
| `timeout-minutes` in `hare.yml` | 90 | **120** | The 120-minute job limit is the final backstop. Under shipped defaults, the 2,700 s or 3,300 s chain budget ends model work before the 3,600 s wall-clock cap; the wall clock can bind when configured below the chain budget. An hour beyond the script caps leaves room for checkout, Python setup, CI, and posting. It costs nothing when a review finishes early, because a GitHub-hosted runner is billed per minute of compute actually used ([billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)), and 120 is a third of the documented 360 ceiling. |
| Diff size | `MAX_DIFF` 90,000 chars, `BIG_DIFF_LINES` 1000 | unchanged | Sourcery publishes a 150,000-character per-PR cap and CodeRabbit's free tier documents 150 files with a hard ceiling of 300. Other published size handling includes Macroscope and Codacy; counting only explicit per-diff size limits leaves 12 of 16 products without a public numeric diff cap. Amazon Q's monthly LOC allowance and Bugbot's per-file ignore rule are not counted as PR diff caps. |
| Attempts | 6 | unchanged | The chain is 5 providers and up to 11 models. 6 reaches three providers while one dead model cannot spend the list. |
| Chain order | slow models first | unchanged | Nothing in this survey says a reviewer should demote a model for being slow. |

### Give-up conditions

| Condition | Threshold | What it posts |
| --- | --- | --- |
| One call hangs | 1800 s normal, 2700 s big | the error names its own timeout, then the chain moves on |
| Model chain budget exhausted | 2700 s normal, 3300 s big | `searchts-r1-needed` with the one-line lead "Hare: no model answered, not reviewed"; detail names the spent hop budget |
| Review wall-clock backstop | 3600 s | Safety ceiling; the 2700 s or 3300 s chain budget normally ends model work first |
| Attempt cap | 6 calls | same needed note, naming the attempt cap |
| Every provider rate limited | any 429 | that provider is dropped for the run; the rest continue; if all drop, the needed note |
| Diff over the cap | 90,000 chars | the note says the diff was over the cap, and by how much |

The rule this survey supports is CodeRabbit's and Copilot's: **never post nothing.** A
skipped review whose status stays green is indistinguishable from an approved one, so Hare
posts a named reason every time, which is what `searchts-r1-needed` already does. Three of
the four code paths above already name their cause in the note; the harness change in this
PR is that the per-call ceilings now fit the slow model instead of cutting it off, so the
first path should fire far less often.

### What this survey did not settle

- **Every p99 and every max is a lower bound**, because the one-hour reactive cut drops
  0% to 30% of each vendor's messages, and it drops the slow ones. No vendor publishes
  the full distribution that would let us put the dropped tail back.
- **No vendor publishes a latency SLO**, so the tail numbers here are ours, not theirs.
- **The samples are small for the long tail.** Amazon Q (20 messages), Codacy (24),
  Gemini (22), DeepSource (5) and Cubic (24 from a single repo) cannot support a p99
  claim. Treat their max as the only defensible figure.
- **The one-hour threshold is a judgement call.** A 5,400 s cut would fold more of the
  tail in and raise every p99; a 1,800 s cut would hide more and lower them. It was fixed
  before the results were read, and it applies identically to all sixteen products, but a
  different author would have produced a different table.
- **Queue time and think time are not separable** from public data, so a 40 minute gap
  could be either.
- **Bito is the one product with no latency measurement.** The probes found no eligible
  merged PR rows across `microsoft/vscode`, `facebook/react` and code-search discovery;
  a missing sample is not evidence that the product has no public reviews.
- **Copilot's per-push re-review figure (9m41s median) needs a fresh run to reproduce**,
  because the raw JSON stores per-PR samples, not per-message timestamps.
- **Hare's own numbers are not in the table.** Step 5's 13 to 15 minutes is an
  owner-supplied team measurement. This survey measured the reviewers, not Hare.
- **Two Cursor Bugbot claims are user reports, not vendor statements**, and are labelled
  as such where they appear.

---

## Appendix A: the harness

`.hare-timing/measure_latency.py`, reproduced here so the table is checkable. Raw JSON per
product is written next to it.

```python
#!/usr/bin/env python3
"""Measure PR-open/push -> bot-review latency from public GitHub data (MEASURED).

Two steps:
  1. discovery: find public repos that use the bot (config file in code search,
     or an explicit --repo list)
  2. measurement: one GraphQL query per repo returns the PR's createdAt plus
     every review and issue comment with author login and timestamp.

Metrics
-------
reaction        = for every bot message, the gap from the most recent commit at
                  or before it (plus 60 s of slack). This is the number that
                  measures how long a reviewer takes, and it is what the
                  research table reports.
reaction_under_1h = the same, restricted to messages under 3600 s. The tail of
                  the full distribution is polluted by PRs where auto-review is
                  off or a human asked for a re-review hours later, so the
                  reactive subset is the one to quote. It is a lower bound.
push_to_first   = first bot message - head commit committer date (only counted
                  when >= -600 s). Reported as `head->first`. Needs the last
                  100 commits to be the real head, which commits(last:100) gives.
open_to_first   = first bot message - PR createdAt. Measures PR idle time plus
                  latency; never use it to size a timeout.

Usage
-----
  python3 measure_latency.py --author coderabbitai --discover .coderabbit.yaml --max-prs 25
  python3 measure_latency.py --author copilot-pull-request-reviewer[bot] \
      --repo cli/cli --repo microsoft/vscode --max-prs 30
  python3 measure_latency.py ... --json-out ../raw/coderabbit.json --label CodeRabbit
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from typing import Any
from urllib.parse import quote

GH = os.environ.get("GH_BIN", "gh")

PRQ = """
query($owner:String!,$repo:String!,$n:Int!,$cursor:String){
  repository(owner:$owner,name:$repo){
    pullRequests(first:$n,after:$cursor,orderBy:{field:UPDATED_AT,direction:DESC},states:[MERGED]){
      pageInfo{hasNextPage endCursor}
      nodes{
        number url createdAt
        reviews(first:40){nodes{author{login} submittedAt state}}
        comments(first:60){nodes{author{login} createdAt}}
        commits(last:100){nodes{commit{committer{date}}}}
      }
    }
  }
}
"""

def run(args: list[str]) -> Any:
    proc = subprocess.run([GH, *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip()[:300] or "gh failed")
    return json.loads(proc.stdout)


def discover(filename: str, limit: int) -> list[str]:
    repos: list[str] = []
    for page in (1, 2, 3):
        data = run(
            [
                "api",
                "-H",
                "Accept: application/vnd.github.v3+json",
                f"search/code?q=filename%3A{quote(filename)}&per_page=100&page={page}",
            ]
        )
        items = data.get("items", [])
        if not items:
            break
        for it in items:
            name = (it.get("repository") or {}).get("full_name")
            if name and name not in repos:
                repos.append(name)
        time.sleep(2)
        if len(repos) >= limit:
            break
    return repos[:limit]


def norm_login(login: str) -> str:
    """GraphQL returns `name`, REST returns `name[bot]` for the same account."""
    return (login or "").strip().lower().removesuffix("[bot]")


def parse(ts: str) -> float:
    """GitHub REST stamps are `...Z`; GraphQL committer dates carry an offset."""
    from datetime import datetime

    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    o = sorted(values)
    if len(o) == 1:
        return o[0]
    k = (len(o) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(o) - 1)
    return o[lo] + (o[hi] - o[lo]) * (k - lo)


def fmt(sec: float | None) -> str:
    if sec is None or sec != sec:
        return "n/a"
    sec = int(round(sec))
    if sec < 90:
        return f"{sec}s"
    if sec < 5400:
        return f"{sec // 60}m{sec % 60:02d}s"
    return f"{sec // 3600}h{(sec % 3600) // 60:02d}m"


def measure_repo(full: str, author: str, want: int, since: str) -> list[dict[str, Any]]:
    owner, name = full.split("/", 1)
    rows: list[dict[str, Any]] = []
    cursor = None
    pages = 0
    while len(rows) < want and pages < 3:
        args = ["api", "graphql", "-f", f"owner={owner}", "-f", f"repo={name}", "-F", "n=30"]
        if cursor:
            args += ["-F", f"cursor={cursor}"]
        args += ["-f", "query=" + PRQ]
        data = run(args)
        prs = ((data.get("data") or {}).get("repository") or {}).get("pullRequests") or {}
        nodes = prs.get("nodes") or []
        if not nodes:
            break
        pages += 1
        cursor = (prs.get("pageInfo") or {}).get("endCursor")
        for pr in nodes:
            if len(rows) >= want:
                break
            if since and pr["createdAt"] < since:
                continue
            stamps = []
            kinds = {}
            for r in (pr.get("reviews") or {}).get("nodes") or []:
                login = norm_login((r.get("author") or {}).get("login") or "")
                if login == norm_login(author) and r.get("submittedAt"):
                    stamps.append(r["submittedAt"])
                    kinds[r.get("state") or "review"] = kinds.get(r.get("state") or "review", 0) + 1
            for c in (pr.get("comments") or {}).get("nodes") or []:
                login = norm_login((c.get("author") or {}).get("login") or "")
                if login == norm_login(author) and c.get("createdAt"):
                    stamps.append(c["createdAt"])
                    kinds["comment"] = kinds.get("comment", 0) + 1
            if not stamps:
                continue
            stamps.sort()
            commits = (pr.get("commits") or {}).get("nodes") or []
            commit_dates = [
                ((c.get("commit") or {}).get("committer") or {}).get("date") for c in commits
            ]
            commit_dates = sorted(d for d in commit_dates if d)
            head_date = commit_dates[-1] if commit_dates else None
            row = {
                "repo": full,
                "pr": pr["number"],
                "url": pr["url"],
                "created_at": pr["createdAt"],
                "first_bot_at": stamps[0],
                "open_to_first_s": int(parse(stamps[0]) - parse(pr["createdAt"])),
                "n_bot_msgs": len(stamps),
                "kinds": kinds,
            }
            if head_date:
                row["head_commit_at"] = head_date
                row["push_to_first_s"] = int(parse(stamps[0]) - parse(head_date))
            # reaction latency: for every bot message, the gap since the most
            # recent commit at or before it. This is the number that says how
            # long the reviewer takes, and unlike open_to_first it is not
            # contaminated by a PR that sat open for days before the next push.
            reaction = []
            for stamp in stamps:
                prior = [d for d in commit_dates if parse(d) <= parse(stamp) + 60]
                if prior:
                    reaction.append(int(parse(stamp) - parse(prior[-1])))
            row["reaction_s"] = sorted(reaction)
            rows.append(row)
        if not (prs.get("pageInfo") or {}).get("hasNextPage"):
            break
        time.sleep(1)
    return rows


def summarize(label: str, author: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    vals = [r["open_to_first_s"] for r in rows]
    push = [
        r["push_to_first_s"]
        for r in rows
        if r.get("push_to_first_s") is not None and r["push_to_first_s"] >= -600
    ]
    reaction = [s for r in rows for s in r.get("reaction_s", [])]
    reactive = [s for s in reaction if s <= 3600]
    return {
        "label": label,
        "author": author,
        "n_prs": len(rows),
        "n_repos": len({r["repo"] for r in rows}),
        "reaction": {
            "n": len(reaction),
            "median_s": round(statistics.median(reaction)) if reaction else None,
            "p90_s": round(pct(reaction, 0.9)) if reaction else None,
            "p99_s": round(pct(reaction, 0.99)) if reaction else None,
            "max_s": int(max(reaction)) if reaction else None,
            "min_s": int(min(reaction)) if reaction else None,
            "over_1h": sum(1 for s in reaction if s > 3600),
        },
        "reaction_under_1h": {
            "n": len(reactive),
            "median_s": round(statistics.median(reactive)) if reactive else None,
            "p90_s": round(pct(reactive, 0.9)) if reactive else None,
            "p99_s": round(pct(reactive, 0.99)) if reactive else None,
            "max_s": int(max(reactive)) if reactive else None,
        },
        "open_to_first": {
            "n": len(vals),
            "median_s": round(statistics.median(vals)) if vals else None,
            "p90_s": round(pct(vals, 0.9)) if vals else None,
            "max_s": int(max(vals)) if vals else None,
            "min_s": int(min(vals)) if vals else None,
            "mean_s": round(statistics.fmean(vals)) if vals else None,
        },
        "push_to_first": {
            "n": len(push),
            "median_s": round(statistics.median(push)) if push else None,
            "p90_s": round(pct(push, 0.9)) if push else None,
            "max_s": int(max(push)) if push else None,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--author", required=True)
    ap.add_argument("--label", default=None)
    ap.add_argument("--repo", action="append", default=[])
    ap.add_argument("--discover", default=None, help="config filename for code search")
    ap.add_argument("--discover-limit", type=int, default=25)
    ap.add_argument("--max-prs", type=int, default=25)
    ap.add_argument(
        "--per-repo",
        type=int,
        default=8,
        help="cap PRs taken from one repo, so the sample spreads across repos",
    )
    ap.add_argument("--since", default="2025-06-01")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    author = args.author
    repos = list(args.repo)
    if args.discover:
        found = discover(args.discover, args.discover_limit)
        print(f"# discovered {len(found)} repos with {args.discover}", file=sys.stderr)
        repos += [r for r in found if r not in repos]

    rows: list[dict[str, Any]] = []
    used: list[str] = []
    for full in repos:
        if len(rows) >= args.max_prs:
            break
        try:
            got = measure_repo(
                full, author, min(args.per_repo, args.max_prs - len(rows)), args.since
            )
        except RuntimeError as exc:
            print(f"# skip {full}: {str(exc)[:120]}", file=sys.stderr)
            continue
        if got:
            used.append(full)
            rows.extend(got)
    label = args.label or author
    summary = summarize(label, author, rows)
    summary["repos_used"] = used
    print(f"== {label}  author={author}  n={len(rows)} PRs across {len(used)} repos")
    o = summary["open_to_first"]
    rx = summary["reaction"]
    if rx["n"]:
        print(
            f"   reaction(all): median {fmt(rx['median_s'])}  p90 {fmt(rx['p90_s'])}  "
            f"p99 {fmt(rx['p99_s'])}  max {fmt(rx['max_s'])}  min {fmt(rx['min_s'])}  "
            f"(n={rx['n']} messages, {rx['over_1h']} over 1 h)"
        )
    u = summary["reaction_under_1h"]
    if u["n"]:
        print(
            f"   reaction<=1h: median {fmt(u['median_s'])}  p90 {fmt(u['p90_s'])}  "
            f"p99 {fmt(u['p99_s'])}  max {fmt(u['max_s'])}  (n={u['n']} messages under 1 h)"
        )
    if o["n"]:
        print(
            f"   open->first : median {fmt(o['median_s'])}  p90 {fmt(o['p90_s'])}  "
            f"max {fmt(o['max_s'])}  min {fmt(o['min_s'])}  mean {fmt(o['mean_s'])}  "
            f"(contaminated when the PR idles before the next push)"
        )
    p = summary["push_to_first"]
    if p["n"]:
        print(
            f"   head->first : median {fmt(p['median_s'])}  p90 {fmt(p['p90_s'])}  "
            f"max {fmt(p['max_s'])}  (n={p['n']}, only valid when the bot reviewed the head SHA)"
        )
    worst = sorted(
        (s for r in rows for s in r.get("reaction_s", [])), reverse=True
    )[:6]
    for r in sorted(rows, key=lambda r: -max(r.get("reaction_s") or [0]))[:6]:
        top = max(r.get("reaction_s") or [0])
        print(f"   slow: {r['url']}  worst reaction {fmt(top)}  msgs={r['n_bot_msgs']}")
    print(f"   worst reaction gaps: {[fmt(s) for s in worst]}")
    if args.json_out:
        os.makedirs(os.path.dirname(args.json_out) or ".", exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump({"summary": summary, "rows": rows}, fh, indent=2)
    if args.json_out:
        os.makedirs(os.path.dirname(args.json_out) or ".", exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump({"summary": summary, "rows": rows}, fh, indent=2)
        print(f"wrote {args.json_out}")
    if not rows:
        print(
            f"NOT MEASURED: no message from {author!r} in any of the "
            f"{len(repos)} repo(s) tried. Either the login is wrong or the bot "
            f"does not post on public PRs there; this is not a zero-latency result."
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

Run it as:

```bash
python3 .hare-timing/measure_latency.py --author <bot-login> --label "<Product>" \
    [--discover <config-filename> | --repo OWNER/NAME ...] \
    --per-repo 6 --max-prs 40 --since 2025-06-01 --json-out <slug>.json
```

Five details that matter for anyone re-running it:

1. **GraphQL drops the `[bot]` suffix.** The REST API returns `sourcery-ai[bot]`, GraphQL
   returns `sourcery-ai`. The harness normalises with `norm_login()`; without it the
   sample comes back silently empty.
2. **`open_to_first` is not a latency measurement.** See the method section. Quote the
   `reaction<=1h` line.
3. **`--per-repo` matters.** Without it the harness takes every sample from the first
   repo that answers, and one busy repo sets the whole distribution.
4. **A discovery that finds nothing is not a zero.** The harness prints `NOT MEASURED`
   and exits 2, because a wrong bot login and a real "this bot never posted here" look
   identical otherwise. Three rows in an earlier draft of this document were wrong because
   a clean zero was printed where a failed discovery had happened.
5. **Timestamps are absolute.** `Z` stamps and offset timestamps go through the same
   `fromisoformat` path. An earlier version read `Z` stamps as local time, which shifted
   every gap by the host's UTC offset.

Repository discovery used GitHub code search on product config filenames for CodeRabbit
(`.coderabbit.yaml`) and Greptile (`greptile.yml`). Other repository lists came from web
search and direct probes; Copilot's came from a GraphQL PR search because it ships no
config file. The commands above record the exact repositories used for this snapshot.

## Appendix B: what a reader cannot check from here

Every claim labelled **DOCUMENTED** carries its URL inline. Claims that could not be
sourced say "not public" rather than carrying an estimate. The per-product raw JSON and
per-message timestamps remain in the untracked `.hare-timing/` work notes as requested.
The exact repository lists and commands above let a reader remeasure the samples against
live GitHub data; later runs can select different merged PRs, so they will not necessarily
recreate this dated 2026-10-11 snapshot row for row.
