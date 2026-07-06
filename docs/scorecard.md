# Unlocker benchmark

Read **5/5** pages (**100%**), keyless, on this machine's own IP.

> Run from a residential connection for a representative number: from a datacenter IP (CI, cloud VM) the curl_cffi tier is blocked more often than a real user sees.

## Which tier carried it

- `curl_cffi`: 4
- `Jina Reader`: 1

## Per page

| Page | Category | Read | Tier | Chars | Secs |
|------|----------|:----:|------|------:|-----:|
| example | control | yes | `Jina Reader` | 367 | 11.15 |
| wikipedia | open | yes | `curl_cffi` | 43156 | 0.64 |
| mdn | open | yes | `curl_cffi` | 12408 | 0.21 |
| hacker-news | open | yes | `curl_cffi` | 3633 | 0.84 |
| cloudflare-docs | cloudflare-fronted | yes | `curl_cffi` | 7099 | 0.42 |
