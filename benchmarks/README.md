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
