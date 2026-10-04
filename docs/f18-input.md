# F18 input: what we can measure, and what it says about paid searchts

**Written:** 2026-10-04. **Status:** input to **F18**, not a plan for it. No price is proposed here.
**Not a slice.** Nothing in this file is scheduled. It exists because the number we would have planned
against turns out to be wrong, and that is worth writing down before anyone plans against it again.

---

## 1. The headline: our adoption number was never an adoption number

The obvious metric for a PyPI tool is download volume. Ours reads **1,337 downloads in the trailing 30
days**, which looks like a real audience. It is not. Two measurements from public data, both taken
2026-10-04.

### 1.1 Two thirds of downloads report no platform at all

[pypistats `system` endpoint](https://pypistats.org/api/packages/searchts/system), whole package life
(3,976 downloads):

| Platform | Downloads | Share |
|---|---:|---:|
| `null` (no platform in user-agent) | 2,665 | **67.0%** |
| Linux | 1,096 | 27.6% |
| Darwin | 132 | 3.3% |
| Windows | 83 | 2.1% |

`pip`, `uv`, and `pipx` all send a `User-Agent` that resolves to a platform. A `null` platform is not a
person running a package manager on a machine. It is a bot, an index scanner, or a directory.

Human-laptop platforms (Darwin + Windows) are **215 downloads, 5.4%**, across 108 days. Linux is 1,096
against those 215. That ratio is what a CI-shaped population looks like.

### 1.2 Half of all downloads land on release days

Same window, downloads bucketed by whether that date carried a GitHub release:

| | Days | Downloads | Mean/day |
|---|---:|---:|---:|
| Release days | 9 | 1,240 | **137.8** |
| Non-release days | 69 | 1,196 | 17.3 |

A release day carries **7.9x** a normal day. **50.9%** of every download the project has ever received
happened on the nine days we shipped a version.

**We checked whether we inflated this ourselves.** Every CI install in `.github/workflows/` and the
root `Dockerfile` is either `pip install -e .` or a local `dist/*.whl` wheel, neither of which resolves
`searchts` from PyPI. `demo/Dockerfile` does install the PyPI release (`pip3 install searchts`), but no
workflow builds it: it is built by hand to record the README GIFs, and pip inside it reports a Linux
platform, so it cannot be the null-platform rows. So the release-day bursts are not our test suite. They come from outside the
workflows, and we have not identified the requesters yet. **U8** tracks that.

### 1.3 What is left

Strip the nulls and the release-day bursts: roughly **17 downloads/day across all platforms**, of which
about 5% is a human laptop. Call it **under one real human install per day.**

GitHub traffic agrees. 30 unique viewers in 14 days; the single busiest day (24 uniques, 2026-09-26)
lines up with a post, not a trend. **2 stars**, 1 fork, 1 watcher, 3 open issues.

**The honest summary: a few dozen people have tried this in three months.** Not zero. Not a funnel.

---

## 2. Why the mean was the wrong number to watch

Two published findings, both relevant to reading our own series:

- **CI share.** Measured CI download share for library packages is **10-50%** monthly (Wagtail/Django
  10-30%, FastAPI 20-50%). The widely-quoted ">80% of traffic" figure is contested - the original speaker
  checked his own slide and found 27%. For a leaf CLI that nothing depends on, CI inflation should be
  *small*, which is the one piece of good news here.
- **Release frequency.** A package that releases constantly out-downloads a stable one at identical
  usage, because cache-busting forces re-downloads (Ruff downloads more than flake8 for this reason
  alone). We shipped **46 releases in 108 days** (~2.9/week). That is structurally inflating our own
  headline number, and it lands on the same days as our own automation re-resolving the package.

**Consequence:** the median day (14-18 downloads) is our real audience size, not the trailing-30-day
mean of 1,337. **Stop quoting the mean.** It is a release counter, not a user counter.

There is **no published dataset** mapping PyPI download spikes to retained users. The "HN spike decays"
claim is folklore from SEO content sites, not a measured result. We should not repeat it in either
direction.

---

## 3. The pricing landscape (research, 2026-10-04)

Verified against live vendor pricing pages. Per-page figures are arithmetic on confirmed unit prices and
plan volumes, so treat them as derived.

| Vendor | Metered unit | Entry price per page | Free tier |
|---|---|---|---|
| Crawl4AI Cloud | page credit | $0.0002 (hard sites $0.004) | $10 once |
| Zyte | 1k responses, 5-tier difficulty | $0.00013 PAYG simple, $0.00127 advanced | $5 |
| ZenRows | credit | $0.00036 | 5,000 cr/mo |
| Context.dev | credit | $0.00038 | 1,000 cr/mo |
| ScrapingBee | credit | $0.00025 | 1,000 cr |
| Firecrawl | credit | $0.0032 hobby, $0.0006 scale | 1,000 cr/mo |
| Exa | per page (Contents) | $0.001 | $10/mo |
| Tavily | credit | $0.0016 extract, $0.008 credit | 1,000 cr/mo |
| Bright Data Unlocker | request | $0.0015 | 5,000 req/mo |
| Browserbase | browser hour | ~$0.0067/page derived | 1 hr |

Two structural facts from that table:

- **The expensive tier is anti-bot infrastructure, not extraction.** Zyte prices a 5-tier *website
  difficulty* scale; Crawl4AI's "hard" tier is 20x its normal read. We would be reselling proxy egress.
- **Crawl4AI undercuts the incumbents 4-15x on list price.** It is Apache-2.0, 84,737 stars, and its
  hosted tier launched ~4 months ago with its subscription still marked "Coming soon."

### 3.1 Nobody prices on tokens except us

Two vendors meter a read by tokens: **Jina** (10,000-token minimum per request; $/token rate is not
published anywhere public) and **Crawl4AI** ($0.50/1M input, $3.00/1M output). Everyone else prices per
page, per credit, per request, per browser-hour, or per CU.

Token pricing aligns cost with the value delivered to an LLM caller, which is structurally right for an
agent tool. **It is also unoccupied.** That is an observation, not an argument that we should build it.

### 3.2 The compliance gap is real and empty

We checked every vendor above for anyone selling provenance, lawful-basis documentation, or a compliance
guarantee as a priced SKU. **Nobody does.** Across the whole category:

- DPA/SOC2/HIPAA are listed as **unpriced trust badges**, usually on the free plan (Firecrawl, Browserless).
- Firecrawl's zero-retention is **enterprise-only, no price**.
- Provenance exists as metadata and is used to **gate the subscription ladder**, never sold add-on
  (Lyrenth's domain-verification counts are the most elaborate example).
- Zyte's only axis is technical difficulty. **Nobody prices by data sensitivity or lawful-basis burden**,
  which is the axis a regulated buyer actually evaluates.

The market has split into bypass-as-product (ZenRows, Bright Data, Zyte) and restraint-as-brand (Jina,
Agent Web). **The middle is unoccupied**: a vendor that will tell you per request what it did, why it was
lawful, and what it cost you defensibly, and charges for that.

Two things that cut against us here and should be written down:

- **Jina's posture is restraint, not bypass, and it monetized anyway** - but via model licensing, now
  sold by Elastic as an on-prem SKU since 2026-08-10. Last funding round Nov 2021.
- **Agent Web (foomworks.app) is free, keyless, and sells restraint as its differentiator** - honors
  `robots.txt`, refuses disallowed paths, never spoofs, ships a `/policy` endpoint. "That restraint is
  the product." It prices the compliance posture at **zero**.

A compliance product assumes we would rather be the vendor a compliance officer approves than the vendor
that scales the bypass. That is a real fork and it is the owner's call, not a research finding.

---

## 4. What the comparable businesses actually did

| | Scale | Outcome |
|---|---|---|
| **Jina Reader** | keyless free relay, paid for throughput | Never a standalone business. Last raise Nov 2021. Monetized model licensing via Elastic. States in writing that **paying does not unlock more sites**. |
| **Crawl4AI** | 84,737 stars, Apache-2.0 + hosted | Hosted tier ~4 months old. Subscription "Coming soon." No revenue disclosed. |
| **Tavily** | OSS roots, 1M+ monthly downloads, $25M raised | **Acquired by Nebius Feb 2026 for $275M**, ~98x 2025 revenue (Sacra estimate) => roughly **$2.8M 2025 revenue**. |
| **n8n** | 206,624 stars, 7 years, $493M raised | ~$100M ARR (Sacra, Apr 2026), 1.7M MAU, 1,400+ enterprise. **~$59 ARR per active builder per year, blended.** |
| **LiteLLM** | 60,119 stars, OSS gateway | Enterprise is **self-hosted / air-gapped, custom pricing**. Sells governance on your infra, not a relay. |
| **Postlight Parser** | 5,791 stars | **Dead.** Last push Jul 2024. This is what a reader with no business looks like. |

**No public conversion data exists** for any of these. We checked Supabase, Vercel, Netlify, Sentry,
Railway, Render, Fly, Trigger.dev, n8n and LiteLLM. **None publish free-to-paid conversion.** The best
available anchor is n8n's blended ~$59 ARR per active builder.

The best real conversion benchmark we found is not about OSS: 200 B2B software products, Jan 2026, median
free-to-paid **8%** - but defined over *registered signups*, which cannot be mapped onto PyPI downloads
where nobody registers.

**Scaled honestly.** Tavily is the clean comparable, and going from 1,337 downloads/month to its 1M is a
**748x** multiplier on a business that took 2.5 years, $25M of VC, and an enterprise sales motion. Linear
extrapolation off our real median (~15/day) suggests single-digit dollars. The true figure is lower,
because revenue comes from a tiny fraction of heavy users.

---

## 5. The relay-demand measurement (first run, 2026-10-04)

Everything above is a reason not to price yet. This is the one measurement that would tell us whether to.

**Instrument `read` for failure rate, and log the hostname class on failure.** A first cut now exists as
[`benchmarks/measure_relay_demand.py`](../benchmarks/measure_relay_demand.py): read-only, reuses the
existing suites, no config change and no telemetry. It classifies each failure by whether a hosted relay
(residential egress plus managed challenge solving) could plausibly fix it.

### 5.1 Smoke suite: 12/12, all local tiers

| Case | Tier carried it |
|---|---|
| example | `stealth-browser` |
| wikipedia, mdn, hacker-news, cloudflare-docs, python-docs, httpbin-html | `curl_cffi` |
| chatgpt, claude, gemini, grok, poe share links | tier-0 share extractors |

**Six of twelve needed only `curl_cffi` from our own IP.** Nothing here needs a relay.

### 5.2 Walled suite: 2/7 to 3/7 across runs, and the failures split three ways

Run from this laptop, residential IP, 2026-10-04. **Three consecutive runs, because the first number
moved and that matters:**

| Run | Read | Failed |
|---|---:|---:|
| 1 | 2/7 | 5 |
| 2 | 3/7 | 4 |
| 3 | 3/7 | 4 |

The committed [scorecard](scorecard.md) says 2/7 from the 2026-10-03 home run, and our first run
reproduced that exactly. **Runs 2 and 3 then read `booking-home` successfully via `stealth-browser`,
where run 1 got `challenge` then `thin-312b`.** Same machine, same connection, minutes apart.

**So the honest range is 2/7 to 3/7 and it is not stable between runs.** That is a finding, not noise to
average away: a 500-char pass floor on an adversarial suite gives a pass rate whose confidence interval
is roughly plus-or-minus one case. Any single-run walled number, ours or anyone else's, should be quoted
as a range. Per-case classification is stable across all three runs:

| Case | Result | Last rung said | Relay class |
|---|---|---|---|
| reddit-hot | **ok** 26,375 chars | `stealth-browser` 21.5s | read |
| reddit-comments | **ok** 7,110 chars | `stealth-browser` 16.6s | read |
| g2-cloudflare | fail | `http-403` on all three rungs | **bot-wall, relay plausibly fixes** |
| datadome-co | fail | `http-403` on all three rungs | **bot-wall, relay plausibly fixes** |
| x-home | fail (3/3 runs) | `thin-0b` | thin, maybe |
| booking-home | fail 1/3, **ok 2/3** | `challenge` / `stealth-browser` | flaky |
| linkedin-feed | fail | `login-wall` + connection timeout | **login-wall, relay cannot fix** |

### 5.3 What the number actually says

**The two hard bot-walls are the stable part.** `g2-cloudflare` and `datadome-co` failed with `http-403`
on all three rungs in every run. `x-home` failed on all three. Those three are the signal, and they are
exactly the class a residential-egress relay would plausibly fix.

**The `linkedin-feed` failure is not relay-fixable at any price**: it is a `login-wall` plus a connection
timeout. That needs the user's own credentials, which is a different product entirely.

Across 19 cases in run 1 (14 read, 5 failed), **2 failures were relay-fixable: 40% of failures, 10.5% of
all measured reads.** Across runs 2 and 3 (15 read, 4 failed), it was **2 of 4 = 50% of failures, 10.5%
of all reads.** The absolute count is stable at **2**; the percentage moves only because the denominator
does.

Read that before quoting it. A 40-50% fix rate sounds like a market. But the walled suite is a curated
list of vendors that actively block bots, and the 2 stable failures are precisely the targets chosen
because they block. **The number that matters is the fix rate on the traffic real users bring, which we
still do not have.**

**The load-bearing conclusion is the smoke suite: 12/12 with six cases on a bare `curl_cffi` request
from our own IP.** The free tier already handles ordinary pages. A relay is only ever needed for the
residual, and that residual is small on normal traffic and only large on targets that are already
blocking us.

### 5.4 What this rules out, and what it does not

- **Ruled out:** "we cannot serve walled pages at all." We serve Reddit, the hardest common case, reliably
  via stealth. The walled rate understates real-world coverage because the suite is intentionally
  adversarial.
- **Ruled out:** a demand story built on the walled pass rate. Those failures are *supposed* to fail;
  PLAN already calls walls a second product under **N1** until a pass is real.
- **Ruled out:** quoting any single-run walled number. Ours moved 2/7 to 3/7 within minutes on one
  connection (section 5.2), so the pass rate's real precision is about plus-or-minus one case. Quote a
  range from repeated runs or not at all.
- **Still open, and the actual next measurement:** instrument real `read` usage for failure rate and
  hostname class. The benchmark answers "what happens on our worst cases"; it cannot answer "what
  happens on what real users ask for," and the latter is the demand signal.

### 5.5 If we instrument real usage, it must be local

**Local and opt-in, never a phone-home.** The MIT, keyless, own-IP identity is the product; a mandatory
telemetry beacon would violate the same invariant as **N1**. An env-gated flag defaulting off, or an
explicit `searchts read --stats` that prints locally and sends nothing, both fit. **Measuring this does
not require anyone's URLs leaving their machine**, and should not.

---

## 6. Recommendation

1. **Do not build F18 yet.** Its existing trigger - "when the free tool is something you would hand a
   stranger and it does what it claims" - has not fired, and section 1 says we now know why. That
   trigger was correct. It stays.
2. **Measure failure rate and hostname class on real traffic** (section 5). The benchmark harness exists
   now ([`measure_relay_demand.py`](../benchmarks/measure_relay_demand.py)); it answered the "worst
   cases" question (section 5.3) but the demand signal needs real user traffic. Cheap, local, no pricing
   decision.
3. **Retire the download count as a headline metric.** Quote the median. See **U9**.
4. **Identify the release-day requesters** (**U8**). 51% of our download history is unexplained and it
   is answerable.
5. **Only then pick a lane.** Token-metered reads and compliance-grade provenance are both genuinely
   unoccupied. They are also different companies. The market evidence says self-serve read pricing is
   capped near $10/1k by bundled Anthropic/OpenAI web search, and that durable revenue in this category
   comes from enterprise contracts and on-prem editions, not page volume.
6. **No price in this file**, matching F18's existing rule.

**Realistic expectation: $0 over the next 6 months.** That is not pessimism, it is what every comparable
shows at this stage, including Crawl4AI's first four months. Low hundreds per month is possible at
6-18 months *only if* a hosted relay exists and succeeds where a local machine cannot. The measured
relay-fixable share of our hardest cases is 2 of 19 (section 5.3), and the free tier already reads 6 of
12 ordinary pages on a bare `curl_cffi`. That is not a business case yet, and the honest read is that the
free tier plus reach may be the better outcome. The path to real money, per every comparable that reached
scale, is an on-prem or enterprise edition with provenance guarantees at $5k-25k/year (LiteLLM, n8n
Business shape). That needs design-partner conversations, not downloads.

---

## 7. Forks that are the owner's call, not research findings

- **Bypass or provenance?** Selling "I get past the wall" and selling "I can prove what I fetched and
  why it was lawful" are different businesses. One is a race you probably lose to Bright Data. The other
  is currently empty and slower. Section 3.2 lays out why it is open; it does not tell us which we want.
- **Is `searchts` the company, or is `Hare`?** F15 and F18 are explicitly separate products with separate
  intents. A hosted code reviewer selling enterprise governance (F15) and a hosted web reader selling
  provenance (F18) share a buyer but not a product. Two hosted products is a lot of surface for one
  maintainer with a few dozen users.
- **What is success?** If the goal is a business, section 5 is the gate. If the goal is a widely-used
  free tool that happens to be sustainable, then most of this document is the wrong document and the
  right move is reach, not instrumentation.

---

## Open questions

- **U8** Who are the release-day requesters? 51% of all downloads, unexplained. Answerable from PyPI
  user-agent strings and release-time correlation.
- **U9** Retire download mean as a reported metric; use median. Needs an owner decision to stick.
- **U10** No published conversion benchmark exists for OSS-download-to-paying. If we want one we have to
  be the first to publish it, which means shipping the hosted tier before we know the answer.
- **U11** Relay-fixable share on **real user traffic**, not the walled suite. Section 5.3 measures the
  deliberately adversarial set; the demand signal needs the ordinary one. Needs a local, opt-in,
  no-telemetry instrumentation (section 5.5) and the owner's go-ahead.

## Verified vs unverified

**Verified today, re-runnable:** every figure in sections 1, 1.2, 1.3, 2, 5.1, 5.2, 5.3, including the
three-run walled spread. The platform split and download-by-release-day bucketing come from public
pypistats endpoints and `gh api .../releases`. Smoke 12/12 reproduces the committed
[scorecard](scorecard.md); the walled range 2/7-3/7 brackets it.

**Verified from live vendor pages:** the pricing table (section 3), the token-pricing scarcity (3.1), the
empty compliance category (3.2). The comparable table (section 4) is mix: star counts, free-tier
sizes, and pricing are confirmed; **revenue and valuation figures are Sacra estimates, not company
reports**, and are labelled as such.

**Unverified / inference:** that a download spike does not convert to a retained user. **No published
dataset exists** on this either way; we have no conversion data of our own. The 40-50%-of-failures relay
figure in 5.3 is sound arithmetic, but those failures are on a suite built from targets chosen *because*
they block, so it is an **upper bound on relay demand, not a forecast**. Treat it that way. Section 5.2
additionally shows the pass rate itself moves plus-or-minus one case between runs on a fixed connection.
