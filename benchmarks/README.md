# Unlocker benchmark

How often does searchts actually read pages, and which tier carries it? This is a
small, reproducible harness — a regression canary, not proof against hard bot-walls.
It runs **two suites** with two honest pass rates:

- **Smoke** — the committed default set: public, robots-friendly pages that
  exercise the ladder. A regression canary, not evidence about hard walls.
- **Walled** — real vendors that restrict bots (Reddit hot, a public Reddit
  comments thread, the LinkedIn login wall, a Cloudflare-fronted vendor site, a
  DataDome-class site, X, and Booking). Failures here are expected and honest,
  not a defect.

The smoke number is NOT "does it work on walls." The two are reported separately
on purpose. See [docs/scorecard.md](https://github.com/capad-xyz/searchts/blob/main/docs/scorecard.md).

## Run it

```bash
python -m benchmarks.run                       # both suites, print the scorecard
python -m benchmarks.run --json                # raw JSON
python -m benchmarks.run --suite smoke         # smoke only
python -m benchmarks.run --suite walled       # walled only
python -m benchmarks.run --out results/       # write scorecard.md + results.json (both suites)
python -m benchmarks.run --suite walled --out results/  # measure the walled suite only
```

For the full ladder, install the stealth-browser tier:

```bash
pip install "searchts[browser]" && patchright install chromium
```

## Run it from your own connection

searchts's whole premise is *your own residential IP at personal volume*. Run this
benchmark from a normal connection — **not** from CI or a cloud VM, whose datacenter IPs
get blocked far more often than a real user sees (the number would understate reality).
That's also why there is no scheduled CI job here: to use the benchmark as a regression
canary, run it periodically yourself (or from a self-hosted runner on a residential IP)
and watch the pass rate.

The walled suite is honest about real vendor resistance: a low rate (even 0% on a given
day/connection) reflects the wall, not necessarily a bug. Compare runs from the
same connection and look at the per-case rows to understand any changes.

## Interpret the scorecard

The headline pass rate is a snapshot of one connection at one point in time, not a
service-level guarantee. Compare runs made from the same network to spot regressions.
The category breakdown helps locate a change, but small categories can move sharply
when a single page changes its defenses.

The two suites are reported separately. The smoke rate is the regression canary; the
walled rate is a real number against vendors that restrict bots, where failures are expected.

The tier counts show how much work the unlocker needed:

- `curl_cffi` is the fast, direct request from your own IP.
- `Jina Reader` is the JavaScript-rendering relay used when a direct request is blocked.
- `stealth-browser` is the local Chromium fallback for live JavaScript or managed
  challenges.

In the per-page table, `Chars` is a content sanity check, not a quality score.
A fetch that returns fewer than `unlocker._MIN_CHARS` characters fails
unless the case sets `allow_thin: true`. `Secs` is wall-clock time for that run.
A datacenter, CI, or some VPN connections can report a lower pass rate or more
fallback-tier usage because their IP reputation and TLS fingerprint differ from
a normal residential connection.

Generate a local scorecard and its raw data with:

```bash
python -m benchmarks.run --out results/
```

## Cases: smoke vs walled

Each case is tagged `suite: smoke | walled`. The committed `cases.py` ships the
smoke set as default and a public walled set. `load_cases(suite=...)` filters:

```python
from benchmarks.cases import load_cases

smoke = load_cases(suite="smoke")   # open pages only
walled = load_cases(suite="walled") # real bot-walls only
both = load_cases()                 # default: both
```

## Add a case (a great first contribution)

The committed smoke set (`cases.py`) is a smoke suite, not a walled-site scorecard.
To benchmark tougher targets **without committing a list of third-party sites**,
drop a git-ignored `benchmarks/cases.local.json`. Extras without a `suite` tag
default to `walled`:

```json
[
  {"name": "some-site", "url": "https://example.org/page", "category": "datadome", "note": "press-and-hold on failure"},
  {"name": "tiny", "url": "https://example.com", "category": "control", "allow_thin": true}
]
```

Please keep additions **read-only, low-volume, and respectful of each site's terms** —
this is a personal-grade research tool, not a scraper.
