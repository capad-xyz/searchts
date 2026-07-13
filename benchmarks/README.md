# Unlocker benchmark

How often does searchts actually read bot-walled pages, and which tier carries it?
This is a small, reproducible harness that runs the unlocker over a set of pages and
prints a scorecard — a proof point, a regression canary, and an easy first contribution.

## Run it

```bash
python -m benchmarks.run                 # print the markdown scorecard
python -m benchmarks.run --json          # raw JSON
python -m benchmarks.run --out results/  # also write scorecard.md + results.json
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

## Interpret the scorecard

The headline pass rate is a snapshot of one connection at one point in time, not a
service-level guarantee. Compare runs made from the same network to spot regressions.
The category breakdown helps locate a change, but small categories can move sharply
when a single page changes its defenses.

The tier counts show how much work the unlocker needed:

- `curl_cffi` is the fast, direct request from your own IP.
- `Jina Reader` is the JavaScript-rendering relay used when a direct request is blocked.
- `stealth-browser` is the local Chromium fallback for live JavaScript or managed
  challenges.

In the per-page table, `Chars` is a quick content sanity check, not a quality score, and
`Secs` is wall-clock time for that run. A datacenter, CI, or some VPN connections can
report a lower pass rate or more fallback-tier usage because their IP reputation and
TLS fingerprint differ from a normal residential connection.

Generate a local scorecard and its raw data with:

```bash
python -m benchmarks.run --out results/
```

## Add a case (a great first contribution)

The committed set (`cases.py`) is a conservative, public baseline. To benchmark against
your own, tougher targets **without committing a list of third-party sites**, drop a
git-ignored `benchmarks/cases.local.json`:

```json
[
  {"name": "some-site", "url": "https://example.org/page", "category": "datadome", "note": "press-and-hold on failure"}
]
```

Please keep additions **read-only, low-volume, and respectful of each site's terms** —
this is a personal-grade research tool, not a scraper.
