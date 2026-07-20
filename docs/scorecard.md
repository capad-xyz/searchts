# Unlocker benchmark

Read **12/12** pages (**100%**), keyless, on this machine's own IP.

> Run from a residential connection for a representative number: from a datacenter IP (CI, cloud VM) the curl_cffi tier is blocked more often than a real user sees.

See [how to interpret this scorecard](https://github.com/capad-xyz/searchts/blob/main/benchmarks/README.md#interpret-the-scorecard).

## Which tier carried it

- `curl_cffi`: 5
- `Jina Reader`: 1
- `stealth-browser`: 1
- `share:chatgpt`: 1
- `share:claude`: 1
- `share:gemini`: 1
- `share:grok`: 1
- `share:poe`: 1

## By category

- `ai-share`: 5/5 (100%)
- `cloudflare-fronted`: 1/1 (100%)
- `control`: 1/1 (100%)
- `open`: 5/5 (100%)

## Per page

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
