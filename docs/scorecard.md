# Unlocker benchmark

> Two suites, two honest pass rates. **Smoke** exercises the ladder on open pages; **Walled** is a real pass rate against vendors that restrict bots (Reddit, LinkedIn, Cloudflare/DataDome-class, X, Booking). A low walled rate is truth, not a trophy.

> Run from a residential connection for a representative number: from a datacenter IP (CI, cloud VM) the curl_cffi tier is blocked more often than a real user sees.

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
| example | control | yes | `curl_cffi` | 156 | 1.51 |
| wikipedia | open | yes | `curl_cffi` | 43801 | 1.17 |
| mdn | open | yes | `curl_cffi` | 15136 | 0.46 |
| hacker-news | open | yes | `curl_cffi` | 3848 | 1.13 |
| cloudflare-docs | cloudflare-fronted | yes | `curl_cffi` | 7378 | 0.63 |
| python-docs | open | yes | `curl_cffi` | 32545 | 0.78 |
| httpbin-html | open | yes | `curl_cffi` | 3566 | 0.9 |
| chatgpt-share | ai-share | yes | `share:chatgpt` | 2149 | 2.35 |
| claude-share | ai-share | yes | `share:claude` | 11260 | 0.59 |
| gemini-share | ai-share | yes | `share:gemini` | 35780 | 1.5 |
| grok-share | ai-share | yes | `share:grok` | 41610 | 0.57 |
| poe-share | ai-share | yes | `share:poe` | 8934 | 1.21 |

## Walled

Read **2/7** pages (**29%**). — failures are expected on real bot-walls; a low rate is honest, not a defect.

## Walled — which tier carried it

- `stealth-browser`: 2

## Walled — by category

- `booking`: 0/1 (0%)
- `cloudflare-fronted`: 0/1 (0%)
- `datadome`: 0/1 (0%)
- `linkedin`: 0/1 (0%)
- `reddit`: 2/2 (100%)
- `twitter`: 0/1 (0%)

## Walled — per page

| Page | Category | Read | Tier | Chars | Secs |
|------|----------|:----:|------|------:|-----:|
| reddit-hot | reddit | yes | `stealth-browser` | 27836 | 12.93 |
| reddit-comments | reddit | yes | `stealth-browser` | 7110 | 17.4 |
| linkedin-feed | linkedin | no | — | 0 | 7.53 |
| g2-cloudflare | cloudflare-fronted | no | — | 0 | 27.22 |
| datadome-co | datadome | no | — | 0 | 22.7 |
| x-home | twitter | no | — | 0 | 3.8 |
| booking-home | booking | no | — | 0 | 10.95 |
