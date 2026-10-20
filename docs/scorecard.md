# Unlocker benchmark

> Two suites, two honest pass rates. **Smoke** exercises the ladder on open pages; **Walled** is a real pass rate against vendors that restrict bots (Reddit, LinkedIn, Cloudflare/DataDome-class, X, Booking). A low walled rate is truth, not a trophy.

> Run from a residential connection for a representative number: from a datacenter IP (CI, cloud VM) the curl_cffi tier is blocked more often than a real user sees.

> Where this was run: Linux 6.12.94+, Python 3.12.15; network: cloud VM, datacenter network.

See [how to interpret this scorecard](https://github.com/capad-xyz/searchts/blob/main/benchmarks/README.md#interpret-the-scorecard).

## Smoke

Read **12/12** pages (**100%**).

## Smoke — which tier carried it

- `curl_cffi`: 7
- `share:chatgpt`: 1
- `share:claude`: 1
- `share:gemini`: 1
- `share:grok`: 1
- `share:poe`: 1

## Smoke — by category

- `ai-share`: 5/5 (100%)
- `cloudflare-fronted`: 1/1 (100%)
- `control`: 1/1 (100%)
- `open`: 5/5 (100%)

## Smoke — per page

| Page | Category | Read | Tier | Chars | Secs |
|------|----------|:----:|------|------:|-----:|
| example | control | yes | `curl_cffi` | 156 | 1.02 |
| wikipedia | open | yes | `curl_cffi` | 44461 | 0.4 |
| mdn | open | yes | `curl_cffi` | 15136 | 0.27 |
| hacker-news | open | yes | `curl_cffi` | 6083 | 0.34 |
| cloudflare-docs | cloudflare-fronted | yes | `curl_cffi` | 7527 | 0.36 |
| python-docs | open | yes | `curl_cffi` | 33544 | 0.29 |
| httpbin-html | open | yes | `curl_cffi` | 3566 | 1.45 |
| chatgpt-share | ai-share | yes | `share:chatgpt` | 2149 | 0.73 |
| claude-share | ai-share | yes | `share:claude` | 11260 | 0.3 |
| gemini-share | ai-share | yes | `share:gemini` | 35780 | 0.31 |
| grok-share | ai-share | yes | `share:grok` | 41610 | 0.26 |
| poe-share | ai-share | yes | `share:poe` | 8934 | 0.5 |

## Walled

Read **4/7** pages (**57%**). — a row counts only when the text holds a phrase from the real page; failures are expected on real bot-walls, and a low rate is honest, not a defect.

## Walled — which tier carried it

- `stealth-browser`: 2
- `curl_cffi`: 1
- `Jina Reader`: 1

## Walled — by category

- `booking`: 1/1 (100%)
- `cloudflare-fronted`: 0/1 (0%)
- `datadome`: 1/1 (100%)
- `linkedin`: 0/1 (0%)
- `reddit`: 2/2 (100%)
- `twitter`: 0/1 (0%)

## Walled — per page

| Page | Category | Read | Tier | Chars | Secs | Real-page phrase |
|------|----------|:----:|------|------:|-----:|------|
| reddit-hot | reddit | yes | `stealth-browser` | 31943 | 9.4 | `/r/MachineLearning/comments/` |
| reddit-comments | reddit | yes | `stealth-browser` | 7110 | 9.83 | `A Super Harsh Guide to Machine Learning` |
| linkedin-feed | linkedin | no | — | 0 | 6.75 | — |
| g2-cloudflare | cloudflare-fronted | no | — | 0 | 13.36 | — |
| datadome-co | datadome | yes | `curl_cffi` | 3873 | 2.46 | `Bot Management & Agent Trust Platform` |
| x-home | twitter | no | — | 0 | 9.64 | — |
| booking-home | booking | yes | `Jina Reader` | 120429 | 8.58 | `Why Booking.com?` |
