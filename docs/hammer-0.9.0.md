# 0.9.0 hammer catalog (P1.4)

Tess, 2026-09-23. ~42 live cases against PyPI **0.9.0**. Raw logs stay off-repo (`hammer-logs/`). **No stubs that freeze today's lies.**

**Next PR (one logical change):** fail-loud on the five silent/wrong successes. Not a 0.10.0 cut. Not F15. Not the full #22 agent harness.

| # | Lie | Repro ids | Loud behavior |
|---|-----|-----------|---------------|
| 1 | YouTube junk id → real 11-char transcript, exit 0 | `tx_private`, `tx_id_truncate_suffix`, `tx_youtu_be_junk` | Reject junk/overlong id **before** fetch. Never transcribe a truncated id. |
| 2 | Empty transcript, exit 0 | `tx_soundcloud` | Non-empty text or nonzero exit. |
| 3 | doctor “jina available” while live Jina is 403 | doctor + `read_wiki_force_jina` | Real probe. 403 ⇒ not available. |
| 4 | `file://` / `data:` rewritten to `https://…` | `read_file_scheme`, `read_data_uri` | Refuse non-http(s) **before** fetch. Never rewrite. CLI `normalize()` today prepends `https://` if the URL is not already http(s). MCP already refuses. |
| 5 | Loopback not refused | `read_localhost` | Hard refuse private/loopback **before** network. MCP `guard_mcp_url` already does this; CLI `read` does not. |

**Keep as honest fails (regressions, not this PR):** thin example.com, LinkedIn login-wall, age-gate without cookies, Cloudflare/bitly/facebook/instagram/x/nyt-class walls, missing stealth dep.

**Healthy:** Wikipedia long read, Shorts captions, age-gate + Chrome cookies contrast.

Counts: 24 honest/opaque · 8 healthy/mild · 2 contrast · **8 slots on the five lies** (3+1+1+2+1).

## Full 42 (id · exit · bucket)

1–4 `read_bitly/bloomberg/bloomberg_article/cloudflare_challenge` · 1 · honest fail
5 `read_data_uri` · 1 · **#4**
6–7 `read_example/facebook` · 1 · honest fail
8 `read_file_scheme` · 1 · **#4**
9 `read_http_redirect` · 1 · honest fail
10–11 `read_httpbin_delay/html` · 0 · healthy/mild
12–15 `read_httpbin_status403/instagram/linkedin/linkedin_profile` · 1 · honest fail
16 `read_localhost` · 1 · **#5**
17 `read_medium` · 1 · honest fail
18 `read_medium_member` · 0 · healthy/mild
19 `read_nowsecure` · 1 · honest fail
20–22 `read_nyt/robots_txt/spa_shell` · 0 · healthy/mild
23 `read_tinyurl` · 1 · honest fail
24 `read_wiki_force_jina` · 1 · **#3**
25 `read_wiki_force_stealth` · 1 · honest fail (missing dep)
26–27 `read_wikipedia/wsj` · 0 · healthy/mild
28 `read_x_status` · 1 · honest fail
29 `tx_age_nocookies` · 1 · honest fail
30 `tx_age_with_cookies` · 0 · contrast
31–33 `tx_bad_id/could_not_extract/garbage_url` · 1 · opaque fail
34 `tx_id_truncate_suffix` · 0 · **#1**
35–36 `tx_image/live_url` · 1 · honest fail
37 `tx_private` · 0 · **#1**
38 `tx_shorts` · 0 · healthy
39 `tx_soundcloud` · 0 · **#2**
40–41 `tx_unavailable/webpage` · 1 · honest fail
42 `tx_youtu_be_junk` · 0 · **#1**
