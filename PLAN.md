# searchts — master plan (frozen 2026-08-20)

**Repo:** https://github.com/capad-xyz/searchts  
**Identity:** free, open-source, keyless web layer for agents — won by reliability and being easy to reach for, not by feature count.  
**Status:** Decisions locked (see §0). Work ordered P0 → P1∥P2 → P3 → P4 → Later.

**Hard non-goals:** plugin/connector framework, paid-proxy defaults, hosted SaaS, keyed backends as defaults, channel-based `read_url` routing, HTTP MCP until local stdio is trusted, MCP resources/prompts before tools are trusted.

---

## 0. Locked decisions

| # | Topic | Choice |
|---|---|---|
| **Q1** | Channels | **B — Delete routing theater.** Drop unused `can_handle` (and any implied routing contract). Channels remain doctor probes only; doctor copy must not sound like searchts performs platform reads. |
| **Q2** | Agent reach (#22) | **A — Memory rule on install** (Claude Code + Cursor if present). Ask before overwrite. Claude plugin only in P4. |
| **Q3** | Scorecard | **A — Public walled suite** with real pass rates (not fake 100%). |
| **Q4** | Jina | **A — Default on**, document that r.jina.ai sees URLs, add opt-out. |
| **Q5** | Config / doctor | **A — Env beats YAML**; doctor is read-only (no skill install side effect). |

---

## 1. Complete checklist

### P0 — Honesty (ship first; no public narrative until P0.7 is on main)

**Verified fixes**

- [x] **P0.1** Doctor stealth: probe patchright/Chromium; `warn` if missing; never list an uninstalled tier as available — #74
- [x] **P0.2** Doctor: remove `_install_skill()`; skill only via `searchts install` / `searchts skill` — #74
- [x] **P0.3** Dead knobs: remove `REDDIT_PROXY` from `.env.example`; remove or implement `youtube_cookies_from`; remove or wire `github_token` → `GH_TOKEN` for `gh`; call `load_dotenv` or drop `python-dotenv`
- [x] **P0.4** Config: env wins over YAML (`fix` release note for anyone relying on YAML override)
- [x] **P0.5** Constraints: pin tested versions of `curl_cffi`, `trafilatura`, `ddgs`
- [x] **P0.6** Release: fail if `RELEASE_PLEASE_TOKEN` missing (no silent `GITHUB_TOKEN` tag)
- [x] **P0.7** Scorecard honesty: README splits smoke vs walled; benchmark `ok` requires `chars >= _MIN_CHARS` unless case sets `allow_thin` — #79

**Q1-B — Channel cleanup (verified: `can_handle` unused in production)**

- [x] **P0.8** Remove `can_handle` from channel base + implementations (tests only use it today)
- [x] **P0.9** Rewrite doctor messages: optional CLIs are "present on PATH / authenticated," not "searchts can read GitHub/Twitter"
- [x] **P0.10** Docs/CLAUDE.md/SKILL references: no channel-routing contract; one read path = `unlocker.fetch`
- [x] **P0.11** Tests: drop or rewrite `can_handle` contract tests; keep probe/`check()` tests

### P1 — Agent reach (highest product leverage)

**Verified gap + behavioral hypothesis (#22)**

- [x] **P1.1** Install path writes short memory rule (~8 lines): on 403/429/challenge/thin page → `read_url` / `searchts read`; do not satisfice on a snippet. Targets: Claude Code user memory + Cursor rule if detected. **Prompt before overwrite.** — #86
- [x] **P1.2** MCP tool descriptions: explicit retry-via-`read_url` language — #88
- [x] **P1.2b** Skill YAML `description` ≤ 1024 (Agent Skills hosts skip the skill otherwise) — #89
- [ ] **P1.3** Acceptance gate: MCP-only session, no project SKILL.md, walled URL → `read_url` within first two tool calls. *2026-08-24 GLM: `read_url` first (reach yes); not a clean skill-off X2 yet.*
- [ ] **P1.4** *(unverified track)* Scripted acceptance harness so #22 is pass/fail, not anecdote

### P2 — MCP 2.x hygiene (parallel with P1)

**Verified:** low-level `@server.list_tools()` API is what 2.x deleted; pin is `<2`

- [x] **P2.1** Rewrite `mcp_server.py` → FastMCP + `@tool` on existing five module-level functions; delete hand-written schema + `if name ==` switch; keep `"Error: …"` string contract; stay on `mcp>=1,<2` — #94
- [ ] **P2.2** CI job: clean install `mcp>=2,<3`, build server, list tools (red until P2.3)
- [ ] **P2.3** Rename FastMCP → MCPServer; lift extra to `mcp>=2,<3`; pin in `constraints.txt`; smoke stdio + one host
- [ ] **P2.4** Do **not** add `transcribe`, HTTP/SSE, or resources in these PRs

### P3 — Unlocker quality (core product)

**Verified code issues**

- [x] **P3.1** Block detection: header/status signals (CF, DataDome, Akamai, Fastly) + body phrases; unit tests on **fixtures**, not live vendors — #93
- [x] **P3.2** Thin content = failure (`UnlockerError`), not success / best-effort return under `_MIN_CHARS` — #93
- [x] **P3.10** MCP stealth: sync Playwright under FastMCP asyncio → `_call_sync_browser` worker thread for stealth + human. Reddit interstitial phrases tightened.
- [ ] **P3.3** Domain memory: TTL (default 24h); un-pin remembered backend when that backend fails before walking the rest of the ladder
- [ ] **P3.4** UA: remove hardcoded Chrome 126; current stable string or align with curl_cffi impersonate profile
- [ ] **P3.5** Jina: remain default; document third-party relay; `SEARCHTS_NO_JINA=1` / config `jina: false`
- [ ] **P3.6** SSRF for **MCP only**: reject `file://`, `data:`, loopback, link-local, RFC1918, cloud metadata IPs; CLI stays unrestricted
- [ ] **P3.7** Walled scorecard: public suite of real walls; publish pass *rate*; smoke suite stays separate

**Unverified measurements (run before over-building)**

- [ ] **P3.8** UA A/B (126 vs current) on a fixed URL set — only keep complexity if delta is real
- [ ] **P3.9** Log domain-memory hit/fail for a period of real use — validate TTL design

### P4 — Surface parity (after P1–P3)

- [ ] **P4.1** MCP `transcribe` tool (same Error-string contract as other tools)
- [ ] **P4.2** Claude plugin packaging (`plugin.json` + skill + MCP) — distribution of P1, not a new architecture
- [ ] **P4.3** CI job with `[browser]` extra (skip if no Chromium)
- [ ] **P4.4** Docker: `slim` (current default) + `browser` tag
- [ ] **P4.5** Split `cli.py` only when a verb is being changed (`commands/read.py` etc.) — no big-bang rewrite

### Communications

- [x] **X1** After P0.7: smoke vs walled; thin is not a pass (posted 2026-08-20)
- [ ] **X2** After P1 demo: 403 → agent calls `read_url` (issue #22). *Not posted. Need cleaner MCP-only / no-skill session than 2026-08-22/24 anecdotes.*
- [ ] **X3** After P3.1+P3.2: one wall before/after. *Evidence ready 2026-08-24: Reddit hot was “200 + challenge success” → now `Error: all backends failed` (thin-124 / Jina 403 / stealth asyncio). Not posted. Do not claim bypass.*
- [ ] **X4** After P2.3: mcp 2.x no longer kills `mcp serve`
- [ ] Cadence ≤2 posts/week; no chore tweets (pins, dead keys, YAML)
- [x] **X1** posted 2026-08-20 (`@aadarsh_io`). Article drafted in Notion; publish same week as X2/X3.
- [x] **CI** PRs: lint + typecheck + version-sync + ubuntu 3.12 tests. Full matrix + wheel-gate on `main` only.

- [ ] Article: drafted (Notion, parked). Publish same week as X2 or X3.
- [ ] **PyPI 0.7.3** when P0+P1.1/1.2/1.2b should be what `pip install` gets (index still 0.7.2).

- [ ] **Install story** (docs, not a feature): **keep** = `pipx install "searchts[mcp]"`; **try / MCP** = `uvx --from "searchts[mcp]" searchts …`. `pip` is for venvs only.

---

## 2. Plan by phase

### Why this order

| Phase | Job | If skipped |
|---|---|---|
| **P0** | Stop lying (doctor, scorecard, config, channels, release) | Public posts and article contradict the repo |
| **P1** | Agents actually call you | Reliability work is invisible |
| **P2** | Survive `pip install mcp` 2.x | Support foot-gun; not a product feature |
| **P3** | Unlocker tells the truth and clears real walls | Category claim is hollow |
| **P4** | Extra surfaces | Safe only after core is trusted and reachable |

```
P0 Honesty + channel delete-theater
    ├─► P1 Agent reach (#22)
    ├─► P2 MCP 2.x (parallel)
    └─► P3 Unlocker quality
            └─► P4 Surfaces
                    └─► Later / footnote
```

### Architecture invariants (do not violate in any phase)

1. **One read path** — CLI and MCP call `unlocker.fetch`; channels do not route reads.
2. **Fail loud** — thin or blocked content is failure unless the caller opts into thin.
3. **Doctor is read-only** — report health; never install skill/config as a side effect.
4. **Only real config** — every documented knob is read by code; env beats YAML.
5. **MCP is thin wrappers** — no second implementation of fetch/search/assets.
6. **No connector framework** — share extractors remain the only fail-open extension pattern.

### Code shrink targets

| Area | Action | Phase |
|---|---|---|
| `can_handle` + routing docs | Delete theater; doctor probes only | P0.8–P0.11 |
| `mcp_server.py` dispatcher | FastMCP/`@tool` on five existing functions | P2 |
| Dead config / dotenv | Delete or wire; one precedence rule | P0.3–P0.4 |
| `cli.py` (~1949 lines) | Extract per verb only when editing that verb | P4.5 |
| Share extractors | Keep fail-open; document as extension point only | Footnote F5 |

### MCP 2.x path (no mechanical `on_*` port)

1. FastMCP + `@tool` while pinned to 1.x
2. CI proves 2.x import/build
3. MCPServer rename + lift pin to `>=2,<3`

Keep returning `"Error: …"` strings from tool bodies so hosts surface failures as tool results (v2 turns uncaught exceptions into JSON-RPC errors).

---

## 3. Verified vs unverified map

### Verified (code-true on main — must fix)

| Finding | Plan items |
|---|---|
| Scorecard `ok` = fetch didn't raise; thin pages count as pass | P0.7, P3.2, P3.7 |
| Public cases are smoke (example/wiki), not bot-walls | P0.7, P3.7 |
| Block detection mostly body phrases + one CF header | P3.1 |
| Domain memory has no TTL / no un-pin on failure | P3.3 |
| Chrome 126 UA hardcoded | P3.4 |
| Jina third-party relay is default | P3.5 (keep + document + opt-out) |
| Share extractors fail-open | keep as-is |
| Channels/`can_handle` unused by CLI/MCP read | P0.8–P0.11 (Q1-B) |
| Dead knobs: REDDIT_PROXY, youtube_cookies_from write-only, github_token never sent, load_dotenv never called | P0.3 |
| YAML beats env | P0.4 |
| Doctor installs skill on text doctor | P0.2 |
| WebChannel always `ok`, names full ladder | P0.1 |
| MCP: no transcribe; Error strings as success text; low-level API breaks on mcp 2.x | P2.*, P4.1 |
| No MCP URL allowlist | P3.6 |
| Docker omits browser | P4.4 |
| constraints miss curl_cffi/trafilatura/ddgs | P0.5 |
| release-please can tag with GITHUB_TOKEN | P0.6 |
| `cli.py` ~1949 lines | P4.5 |
| MCP FastMCP + sync Playwright: stealth dies in asyncio loop | P3.10 |

### Unverified (hypothesis — measure, then maybe build)

| Hypothesis | What to do | Footnote |
|---|---|---|
| Agents satisfice and skip `read_url` in the wild | P1.1–P1.3 fix the gap; P1.4 harness proves it | U1 |
| Chrome 126 materially lowers stealth pass rate | P3.4 + P3.8 A/B | U2 |
| Domain-memory poisoning is common in real use | P3.3 + P3.9 counters | U3 |
| Jina privacy/rate limits pain users | Ship opt-out first; change default only on evidence | U4 |
| SSRF matters beyond local stdio | P3.6 is cheap prep; revisit if HTTP MCP ever ships | U5 |
| Thin "success" confuses models | Coupled to P3.2; re-run #22 session after | U6 |
| Demand for MCP transcribe / marketplace plugin | Wait for issues or own workflows | U7 |

---

## 4. Footnote — unverified tracks & future plans

*Not committed to a sprint. Do not schedule until the matching measurement or P0–P3 pressure says so.*

### U — Unverified tracks

- **U1 — #22 harness:** scripted Claude/Cursor session (MCP only, no SKILL.md, fixed walled URL). Gate for "#22 closed."
- **U2 — UA A/B:** same URLs, stealth only, UA 126 vs current; ship P3.4 either way (stale UA is still wrong), invest further only if delta is large.
- **U3 — Memory telemetry:** count remember-hit then fail; justifies TTL complexity.
- **U4 — Jina default:** only flip to opt-in if privacy/rate-limit evidence appears.
- **U5 — SSRF scope:** expand beyond MCP if transport is no longer local-only.
- **U6 — Thin-content × agents:** after P3.2, re-check whether models retry correctly.
- **U7 — Demand signals:** MCP `transcribe`, plugin installs, directory traffic — drive P4 priority, not vibes.

### F — Future (ROADMAP-aligned, after core is solid)

- **F1** Persistent stealth browser profile across reads
- **F2** First-class PDF / document URL reading
- **F3** Optional content cache for repeat URLs
- **F4** Sitemap / small multi-page crawl (bounded)
- **F5** Document share-extractors as the official fail-open extension point (one file pattern) — **not** a generic plugin system
- **F6** Claude/marketplace plugin polish beyond P4.2 minimum
- **F9** MCP transport: optional **localhost HTTP/SSE** only after P2 stdio is trusted. Public/hosted MCP URL is still N2 — add only if we explicitly break that non-goal. Not in P2.1–P2.3.
- **F8** Install/docs: pipx = keep the CLI; uvx = try + MCP one-shot. README + `mcp install` snippets. Do not ship an npm wrapper. Hosts that cannot see PATH need a full-path or uvx command. Skill install today writes `.claude/skills` and `.agents/skills`, not `.codex/skills` — Codex will not see the skill until we add that path (measure demand first).
- **F7** Opt-in reuse of sessions already on the machine (yt-dlp `--cookies-from-browser`, OpenCLI Chrome, `gh auth`) for **transcribe / extras only**. Never silent. Never inside `read_url` (see N5). Dead YAML keys stay deleted until this ships.

### N — Not planned (explicit)

- **N1** Paid residential proxy pools as defaults
- **N2** Hosted searchts service
- **N3** Keyed commercial unlockers as default backends
- **N4** Generic plugin/connector architecture for platforms
- **N5** Routing `github.com` / Twitter through upstream CLIs inside `read_url`
- **N6** MCP resources/prompts before tools are trusted and reachable

---

## 5. Comms rules

| Beat | Trigger | Content |
|---|---|---|
| X1 | P0.7 merged | Scorecard was smoke; thin ≠ pass; smoke vs walled |
| X2 | P1 acceptance green | Demo: wall → `read_url` without being told (#22) |
| X3 | P3.1 + P3.2 | One before/after on a real wall; name the signal, not "we beat Vendor forever" |
| X4 | P2.3 | One line: mcp 2.x no longer kills the server |

Article after P0 (better with one P1/P3 win). Draft free; publish when the repo matches the story.

Organic X: draft here; publish from `@aadarsh_io`.

---

## 6. Freeze log

| Date | Change |
|---|---|
| 2026-08-20 | Freeze: Q1=B, Q2=A, Q3=A, Q4=A, Q5=A; verified + unverified + future folded; full checklist |
| 2026-08-20 | P0.1 / P0.2 (#74) and P0.7 (#79) on main. F7: device sessions are P4/later, not P0.3. |
| 2026-08-21 | P0.3–P0.11 on main. CI: PR-slim / main-full. X1 posted; article parked. |
| 2026-08-22 | P1.1 #86, P1.2 #88, P1.2b #89 on main. P1.3 still a live gate. |
| 2026-08-22 | pipx = keep CLI; uvx = try/MCP. Folded, not scheduled. |
| 2026-08-22 | P3.1 + P3.2: fail loud on 999/challenge/thin. |
| 2026-08-23 | P2.1 FastMCP on mcp 1.x. |
| 2026-08-22 | F9: localhost HTTP later; hosted URL = break N2. |
| 2026-08-24 | Reddit re-eval: honesty pass; MCP stealth asyncio = P3.10; X2/X3 still unposted. |
| 2026-08-24 | P3.10: Playwright off asyncio for MCP. |
