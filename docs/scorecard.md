# Unlocker benchmark

Two suites, two honest pass rates:

- **Smoke** — the ladder against open pages (a regression canary, not proof).
- **Walled** — a real pass rate against vendors that restrict bots. Failures
  here are expected and honest, not a defect.

> Run from a residential connection for a representative number: from a datacenter IP (CI, cloud VM) the curl_cffi tier is blocked more often than a real user sees.

See [how to interpret this scorecard](https://github.com/capad-xyz/searchts/blob/main/benchmarks/README.md#interpret-the-scorecard).

## Smoke

Read **12/12** pages (**100%**), keyless, on this machine's own IP.

> This is the smoke suite: open pages that exercise the ladder. It is NOT a
> claim about hard bot-walls — see the Walled section for that.

- `curl_cffi`: 5
- `Jina Reader`: 1
- `stealth-browser`: 1
- `share:chatgpt`: 1
- `share:claude`: 1
- `share:gemini`: 1
- `share:grok`: 1
- `share:poe`: 1

### Smoke — by category

- `ai-share`: 5/5 (100%)
- `cloudflare-fronted`: 1/1 (100%)
- `control`: 1/1 (100%)
- `open`: 5/5 (100%)

### Smoke — per page

| Page | Category | Read | Tier | Chars | Secs |
|------|----------|:----:|------|------:|-----:|
| example | control | yes | `Jina Reader` | 367 | 12.39 |
| wikipedia | open | yes | `curl_cffi` | 43818 | 3.63 |
| mdn | open | yes | `curl_cffi` | 12408 | 4.01 |
| hacker-news | open | yes | `curl_cffi` | 4075 | 2.85 |
| cloudflare-docs | cloudflare-fronted | yes | `curl_cffi` | 6939 | 0.53 |
| python-docs | open | yes | `curl_cffi` | 27285 | 1.25 |
| httpbin-html | open | yes | `stealth-browser` | 35 | 6.13 |
| chatgpt-share | ai-share | yes | `share:chatgpt` | 2149 | 3.79 |
| claude-share | ai-share | yes | `share:claude` | 11260 | 1.55 |
| gemini-share | ai-share | yes | `share:gemini` | 35780 | 1.23 |
| grok-share | ai-share | yes | `share:grok` | 41610 | 0.79 |
| poe-share | ai-share | yes | `share:poe` | 8934 | 1.97 |

## Walled

**Not yet measured.** This suite (Reddit hot, a public Reddit comments thread, the
LinkedIn login wall, a Cloudflare-fronted vendor site, a DataDome-class site, X,
and Booking) is a real pass-rate against vendors that restrict bots. Expected
failures are part of the result — there is no 100% trophy here.

To measure it for real, run from a residential IP (a datacenter IP would
understate the rate):

```bash
python -m benchmarks.run --suite all --out docs/
```

That writes both suite scorecards — including the real walled numbers and the
expected failures — under this section. Do not hand-edit a fake walled rate into
this file.
