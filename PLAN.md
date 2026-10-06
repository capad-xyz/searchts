# searchts — master plan (frozen 2026-08-20)

**Repo:** https://github.com/capad-xyz/searchts  
**Identity:** free, open-source, keyless web layer for agents — won by reliability and being easy to reach for, not by feature count.  
**Status:** Decisions locked (see §0). Work ordered P0 → P1∥P2 → P3 → P4 → Later.

**Parked work:** If we skip something on purpose and it is still worth doing, it gets a PLAN id (`P*` / `F*` / `U*` / `N*` / `R*`) and a **revisit** (week / trigger). Chat is not the record. If it is not worth doing, put it in **N** (never) instead of “we’ll remember.” **Roles:** [`NAMES.md`](NAMES.md).

**Hard non-goals:** plugin/connector framework, paid-proxy defaults, hosted SaaS before **F18**, keyed backends as defaults, channel-based `read_url` routing, a public URL for the free CLI (**N2**; localhost HTTP is **F9**; a paid hosted `read` is **F18**), MCP resources/prompts before tools are trusted.

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
- [x] **P1.1b** A later `searchts` command replaces that block only when it is an older official copy. An edit is left alone. A missing block is not created. No Grok writer.
- [x] **P1.2** MCP tool descriptions: explicit retry-via-`read_url` language — #88
- [x] **P1.2b** Skill YAML `description` ≤ 1024 (Agent Skills hosts skip the skill otherwise) — #89
- [x] **P1.3** Acceptance gate: MCP-only session, no project SKILL.md, walled URL → `read_url` within first two tool calls. *zCode skill-off: agents called `read_url` first. **X2** posted 2026-08-27 (`@aadarsh_io`). Gate closed.*
- [ ] **P1.4** 0.9.0 hammer catalog: [`docs/hammer-0.9.0.md`](docs/hammer-0.9.0.md). **Fail-loud top 5** shipped in **0.10.0** / **0.10.1**. Honest walls stay. **U1** answered: where the tool was listed, the description alone did not make the model call `read_url` first. The reach paragraph did. Log: [`docs/u1-harness.md`](docs/u1-harness.md). **No stubs that freeze lies.**
- [x] **P1.5** The MCP server sends that same paragraph as `instructions` on connect. Counts only when that paragraph is not already in the model's rules. Tess 2026-09-24 (Grok call 2, OpenCode call 1). This laptop 2026-09-29: OpenCode `--pure`, skill denied, reach block absent for the run, `read_url` first. Log: [`docs/u1-harness.md`](docs/u1-harness.md). Do not rewrite the sentence again.

### P2 — MCP 2.x hygiene (parallel with P1)

**Verified:** low-level `@server.list_tools()` API is what 2.x deleted; pin is now `>=2,<3`

- [x] **P2.1** Rewrite `mcp_server.py` → FastMCP + `@tool` on existing five module-level functions; delete hand-written schema + `if name ==` switch; keep `"Error: …"` string contract; stay on `mcp>=1,<2` — #94
- [x] **P2.2** CI job: clean install `mcp>=2,<3`, build server, list tools (red until P2.3) — #97
- [x] **P2.3** Rename FastMCP → MCPServer; lift extra to `mcp>=2,<3`; pin in `constraints.txt` — #98. *Host stdio smoke done; **X4** posted 2026-08-26.*
- [x] **P2.4** Do **not** add `transcribe`, HTTP/SSE, or resources *in the MCP 2.x PRs*. Those are **P4.1** / **F9** / **N6**. Not an open P2 task.

### P3 — Unlocker quality (core product)

**Verified code issues**

- [x] **P3.1** Block detection: header/status signals (CF, DataDome, Akamai, Fastly) + body phrases; unit tests on **fixtures**, not live vendors — #93
- [x] **P3.2** Thin content = failure (`UnlockerError`), not success / best-effort return under `_MIN_CHARS` — #93
- [x] **P3.10** MCP stealth: async `read_url` + `asyncio.to_thread`; Reddit interstitial + login phrases; concurrency test via registered `call_tool` — #96
- [x] **P3.3** Domain memory: TTL (default 24h); un-pin remembered backend when that backend fails before walking the rest of the ladder
- [x] **P3.4** UA: remove hardcoded Chrome 126; single `_UA_REAL` in unlocker, imported elsewhere; updated to current stable Chrome 152
- [x] **P3.5** Jina: remain default; document third-party relay; `SEARCHTS_NO_JINA=1` / config `jina: false`
- [x] **P3.6** SSRF for **MCP only** (first layer): reject `file://`, `data:`, loopback, link-local, RFC1918, IPv6 ULA (`fc00::/7`), cloud metadata IPs; CLI stays unrestricted. Guard at MCP URL tools only — not the fetch ladder. *#105; hop checks are P3.6b.*
- [x] **P3.6b** Redirect / DNS-rebinding: a public URL must not be followed onto a private host, and a same-host DNS swap must not either. Distinct from **U5**.
  - [x] **P3.6b-hop** different-host redirect onto a private target is a failed rung (`private-redirect`), not a page. curl_cffi uses `CurlFollow.SAFE` (refuse the hop before following it). Browser rungs abort that request. The human rung is checked too. Direct same-host loopback stays whatever the start-url guard already does.
  - [x] **P3.6b-rebind** same-host DNS rebinding. curl and Chromium are pinned to the address we just checked. A later answer of `127.0.0.1` is not what they connect to. A different public hostname on a redirect is still the hop check, not this pin.
- [x] **P3.7** Walled scorecard: public suite of real walls; publish pass *rate*; smoke suite stays separate ([#111](https://github.com/capad-xyz/searchts/pull/111))
- [x] **P3.7c** Run the walled suite from a residential / home IP and **commit the real pass rate** into `docs/scorecard.md` (even if low). Honest number > marketing claim. **Gate for Show HN / loud "reads walls" posts.** Done 2026-10-03: the home run is [#227](https://github.com/capad-xyz/searchts/pull/227).
  - Home run 2026-10-03 (Tess on Bellami, #227): **Smoke 12/12**; **Walled 2/7**. Read: `reddit-hot`, `reddit-comments` (stealth browser). Failed, named: `linkedin-feed`, `x-home`, `g2-cloudflare`, `datadome-co`, `booking-home` (a challenge, then a thin capture). An earlier home run passed Booking with 559 chars, which the 500-char rule cannot confirm as the real page; this run failed it, so 2/7 is the number to quote. A datacenter run the same night (#226) matched: 12/12 and 2/7. To refresh: `python -m benchmarks.run --suite all --out docs/`, then commit only `docs/scorecard.md` (`docs/results.json` is gitignored).
- [ ] **P3.7d** A walled read passes only with text the real page has (2026-10-03). Today any read of 500+ chars passes, so a wall page that long would count. Give each walled case a phrase from the real page, and have the scorecard say where it was run. Unscheduled; not a Show HN gate.
- [x] **P3.7b** Login-shell honesty: HTTP 200 Sign in / Join now extracts (LinkedIn feed login chrome) fail as `login-wall`, not a scorecard pass. Not a ladder upgrade. *Live 2026-08-28: `/feed/` → `curl_cffi: login-wall`; Jina 403; stealth `login-wall`.*
- [x] **P3.11** Stealth `page.content()` navigation race: wait for settled load, retry `content()` on Playwright's "page is navigating", then fail loud (`UnlockerError`). Not a Reddit bypass — the race is our call during a redirect.

**Unverified measurements (run before over-building)**

- [ ] **P3.8** UA A/B (126 vs current) on a fixed URL set — only keep complexity if delta is real. **Revisit:** with **F12**, or skip forever if P3.4 is enough (**U2**).
- [ ] **P3.9** Log domain-memory hit/fail for a period of real use — validate TTL design. **Revisit:** after a month of real `read`s, or never if TTL is cheap enough (**U3**).

### P4 — Surface parity (after P1–P3)

- [x] **P4.1** MCP `transcribe` tool (same Error-string contract as other tools). Subtitles-first; SSRF on URL sources; cookies opt-in (F7); `progress=False`.
- [ ] **P4.2** Claude plugin packaging (`plugin.json` + skill + MCP) — distribution of P1, not a new architecture. **Revisit:** **U7** / marketplace traffic.
- [ ] **P4.3** CI job with `[browser]` extra (skip if no Chromium). **Revisit:** when stealth tests flake in CI for lack of Chromium.
- [ ] **P4.4** Docker: `slim` (current default) + `browser` tag. **Revisit:** if someone actually runs the image.
- [ ] **P4.5** Split `cli.py` only when a verb is being changed (`commands/read.py` etc.) — no big-bang rewrite. **Revisit:** next verb edit that hurts.
- [x] **P4.6** **CLI UX feedback** — long verbs must not look hung. Pattern from #100: stderr ticks, best-effort, never break pipeable stdout / MCP protocol.
  - [x] `read` ladder progress + `mcp serve` banner (#100)
  - [x] `doctor`: per-channel progress (`checking web…`, `checking github…`) while probes run
  - [x] `search`: provider attempt ticks (or one “searching…” if fusion is quick) — #110
  - [x] `transcribe` / `grab` / `get`: phase ticks (download / extract / whisper / assets) — #109
    - `transcribe`: `fetching subtitles…` → (`downloading audio…`) → `transcribing…`; `progress` threaded from `transcribe()` (None → `SEARCHTS_PROGRESS=1`), CLI passes `True`
    - `get`: `fetching asset…` → `saving asset…`
    - `grab`: `fetching page…` → `downloading assets…` (one tick for the whole asset batch, not per-asset)
    - `fetch_bytes`: `trying <rung>…` per ladder rung (shared by get/grab)
  - [x] Audit other verbs: same rule — silent only if sub-second by design — #109
    - `check-update`: one `checking for updates…` tick before the GitHub round-trip
    - `watch`: `checking channels…` + `checking for updates…` ticks
    - `install` / `setup` / `configure` / `skill` / `mcp` / `uninstall`: already chatty (print statements) — no ticks needed
  - [x] `python -m benchmarks.run`: same rule — per-case stderr ticks while the suite runs; TTY prints via Rich; `--out` / pipes stay plain Markdown. P4.6 applies to new long runners, not only `searchts` verbs. — #113
  - Do **not** route through loguru (suppressed without `-v`). Plain stderr is correct.

### Communications

- [x] **X1** After P0.7: smoke vs walled; thin is not a pass (posted 2026-08-20)
- [x] **X2** After P1 demo: 403 → agent calls `read_url` (issue #22). *Posted 2026-08-27 (`@aadarsh_io`).*
- [x] **X3** After P3.1+P3.2: one wall before/after. *Posted (`@aadarsh_io`). Honesty framing — do not claim permanent bypass.*
- [x] **X4** After P2.3: mcp 2.x no longer kills `mcp serve`. *Posted 2026-08-26 (`@aadarsh_io`). Host stdio smoke done.*
- [x] **X5** 0.8.0 on PyPI. *Posted 2026-08-30 (`@aadarsh_io`). Used `example.com` in the uvx line — that URL is thin (`_MIN_CHARS`); a copypaste looks like a broken install. Do not unpost. Next demo URL = Wikipedia. F8b/F13 later.*
- [x] **X6** 0.9.0 on PyPI. *Posted 2026-09-21 (`@aadarsh_io`). Wikipedia demo URL. HTTP MCP + transcribe.*
- [x] **X7** 0.12.0 Reddit listing cards + 0.11 MCP catch-up. *Posted 2026-09-30 (`@aadarsh_io`). Video: listing → Markdown cards. Honesty: listing parser, not "Reddit complete".*
- [x] **LI1** First LinkedIn post for searchts (same 0.12 story). *Posted 2026-09-30.* First LI beat; keep share-link / fail-loud as the long-form homepage pitch later.
- [ ] **LI2** (2026-10-03: version-free story, not "Latest 0.13"; Reddit hook, Bing inside; a motion video built only on real output and real numbers, captions burned in, 4:5, 20 to 25 s; links in the first comment; a weekday.) Earlier text: After 0.13 is on PyPI: fill "Latest" (0.13) and "Next up" (**F23**: pages that scroll, paginate or fold, on any site). 4:5 clip from real 0.13 output. Links and install in the first comment.
- [ ] **X8** Thread, version-free (drafted 2026-10-03). 1/ Reddit hook (blocked links; some agents fake a summary) with a real r/LocalLLaMA listing clip, browser step shown, waits sped up and labeled. 2/ Bing before/after screenshots: `trafilatura -u` vs `searchts read`, 0 of 10 titles vs 10 of 10 with real links. 3/ also new (has-more notes, Reddit fields, `install --browser`). 4/ MCP safety, 12/12 open, walled failures named. 5/ anthropics/claude-code#45070 as proof, install and repo. Say "free, no API key", not "runs on your machine": the Jina relay is a hosted tier.
- [ ] Cadence ≤2 *story* posts/week; no chore tweets (pins, dead keys, YAML). Quiet patch tags do not need a post. One user-facing release story every 1–2 weeks beats six internal tags in ten days.
- [x] **X1** posted 2026-08-20 (`@aadarsh_io`). Article live: https://x.com/i/article/2090756751675342848 (also linked 2026-09-06).
- [x] **CI** PRs: lint + typecheck + version-sync + ubuntu 3.12 tests. Full matrix + wheel-gate on `main` only.

- [x] Article: [X Article](https://x.com/i/article/2090756751675342848). PLAN had lagged (“drafted”). Demo URL = Wikipedia.
- [x] **PyPI 0.8.0** [#78](https://github.com/capad-xyz/searchts/pull/78) merged 2026-08-29; [pypi.org/project/searchts/0.8.0](https://pypi.org/project/searchts/0.8.0/).

- [x] **Install story** (docs, not a feature): **keep** = `pipx install "searchts[mcp]"`; **try / MCP** = `uvx --from "searchts[mcp]" searchts …`. `pip` is for venvs only.

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
7. **Long surfaces talk** — any new CLI or runner that can sit for more than a second inherits P4.6: stderr ticks while work runs; TTY output fit for a terminal; files/pipes stay machine-plain. Do not ship another silent `benchmarks.run`.

### Code shrink targets

| Area | Action | Phase |
|---|---|---|
| `can_handle` + routing docs | Delete theater; doctor probes only | P0.8–P0.11 |
| `mcp_server.py` dispatcher | FastMCP/`@tool` on five existing functions | P2 |
| Dead config / dotenv | Delete or wire; one precedence rule | P0.3–P0.4 |
| `cli.py` (~1949 lines) | Extract per verb only when editing that verb | P4.5 |
| Share extractors | Keep fail-open; document as extension point only | Footnote F5 |
| Known-host extractors (Reddit JSON, etc.) | Same fail-open *ring* as shares, not a router | **F5b** — after P3.11. Listing HTML index is **F5c**. |

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
| Domain memory has no TTL / no un-pin on failure | P3.3 (fixed) |
| Chrome 126 UA hardcoded | P3.4 |
| Jina third-party relay is default | P3.5 (keep + document + opt-out) |
| Share extractors fail-open | keep as-is |
| Channels/`can_handle` unused by CLI/MCP read | P0.8–P0.11 (Q1-B) |
| Dead knobs: REDDIT_PROXY, youtube_cookies_from write-only, github_token never sent, load_dotenv never called | P0.3 |
| YAML beats env | P0.4 |
| Doctor installs skill on text doctor | P0.2 |
| WebChannel always `ok`, names full ladder | P0.1 |
| MCP: no transcribe; Error strings as success text; low-level API breaks on mcp 2.x | P2.*, P4.1 |
| No MCP URL allowlist (MCP first layer) | P3.6 |
| Redirect / DNS-rebinding can skip the MCP URL check | P3.6b (parked) |
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
| SSRF matters beyond local stdio | P3.6 is cheap MCP prep; **U5** = expand past MCP if HTTP ships; hop/redirect = **P3.6b** | U5 |
| Thin "success" confuses models | Coupled to P3.2; re-run #22 session after | U6 |
| Demand for MCP transcribe / marketplace plugin | Wait for issues or own workflows | U7 |

---

## 4. Footnote — unverified tracks & future plans

*Not committed to a sprint. Do not schedule until the matching measurement or P0–P3 pressure says so. Every skip that is still worth doing lives here with a revisit; “not this week” without an id is a bug.*

### Later nudge — Laya (not a slice, not Hare)

**Worth later. Do not install on a whim.** Laya (Convai, Apache 2.0, ~421M, local) is a typed-decision encoder, same shape as OpenCode **Jev** (`jev-1.13-free` on `https://opencode.ai/zen/v1/systemone`: yes/no, pick-one, small score, plus a probability). It does not read the repo, call tools, or write a review.

Installing it does **not** give a private Jev. Zero-shot it does not beat `jev-1.13-free`. The number that matters needs labels and a fine-tune on **one question asked constantly** whose text must not leave the machine (sensitive diff, local gate). Until that question exists, the classifier is Jev free. Do not put Jev or Laya on the cheap-scout failover list. Do not post `searchts-r1-review` from either.

**Revisit:** when that one question has a handful of labeled examples. Noted 2026-09-28.

### U — Unverified tracks

- **U1 — #22 harness:** [`docs/u1-harness.md`](docs/u1-harness.md). **Answered 2026-09-23.** The reach paragraph made Laguna call `read_url` first. The tool description alone did not, on the one host where the tool was listed (called third). Bellami's run does not count: MCP was pending at init. The next live session is manual, on the user's machine, with the steps and the expected result written first. Tests in the repo are fine. No agent driving the host. No `CLAUDE.md` edit. Only after a new instruction path. Not **F18**.
- **U2 — UA A/B:** same URLs, stealth only, UA 126 vs current; ship P3.4 either way (stale UA is still wrong), invest further only if delta is large.
- **U3 — Memory telemetry:** count remember-hit then fail; justifies TTL complexity.
- **U4 — Jina default:** only flip to opt-in if privacy/rate-limit evidence appears.
- **U5 — SSRF scope:** expand beyond MCP if transport is no longer local-only. Per-hop redirect/rebinding on the ladder is **P3.6b**, not U5.
- **U6 — Thin-content × agents:** after P3.2, re-check whether models retry correctly.
- **U7 — Demand signals:** MCP `transcribe`, plugin installs, directory traffic — drive P4 priority, not vibes.

### R — Review (when CodeRabbit is dark)

- [x] **R1** Implementer ≠ reviewer. Second agent is **🐇‍❄️ Hare** — a **cheap-scout**, not the **orchestrator** (whoever is running the loop: dispatch / leftover finish / merge — not a vendor). Writer model ≠ Hare model. Orchestrator holds merge; orchestrator-as-Hare only if every cheap path is dead (say so in the **PR comment**). Two surfaces: (1) `gh pr comment` body starts with `<!-- searchts-r1-review -->` + table + Intent hold/ship; (2) **Files-changed bubbles** = **real and skip** (line must exist on `gh pr diff`). Each bubble is labeled Hare/automated, not the PR author. Skip never holds merge. Spec in [`AGENTS.md`](AGENTS.md). Revisit: whenever CodeRabbit is rate-limited.
- [ ] **R1c** Auto-Hare on `opened` / `synchronize`. **Built 2026-09-09** (proving): `.github/workflows/hare.yml` + `scripts/hare_r1.py`. Secrets: Nous then OpenRouter then **OpenCode Zen**. Writer ≠ Hare (CI token is `github-actions[bot]`, not the orchestrator). Skip never holds. **Not R1b**. **Not F15**. Do not run the orchestrator as Hare.
  - **Pipeline, not a harness.** The Action gathers (diff, AGENTS, Check Runs), one JSON completion, Python posts. The model never runs `gh`. No ocx in CI. A real agent in Actions is **F15 / F16**, not R1c.
  - **Failover (fixed list, not a router), as of 2026-10-06 (#309):** OpenRouter `nvidia/nemotron-3.5-lightning:free` → `google/gemma-4-31b-it:free` → Nous `poolside/laguna-s-2.1:free` → `meituan/longcat-2.5-preview:free` → Groq `openai/gpt-oss-120b` → Gemini `gemini-3.1-flash-lite` → `gemini-3.5-flash` → Zen `space-bunny-free`. qwen3.8-27b:free left the same day: the eval's OpenRouter rows were all 404. Nemotron Lightning is on the free catalog and is not measured yet. Owner's call: the slower models first, the fast hops (Groq, Gemini) as fallbacks; they answer in seconds and have missed what a slower reviewer caught on the same PR.
  - **Thinking is off by default; `/hare deep` turns it on one notch (#235, #240).** Nous hops send `reasoning: {effort: none}`; OpenRouter `{effort: low, exclude: true}`; Gemini a top-level `reasoning_effort: low`. A gateway that rejects the knob gets one retry without it. Measured in [`docs/hare-thinking-ab.md`](docs/hare-thinking-ab.md) (#238): thinking with no knob was 6 of 6 empty at 32,000 tokens on the free hops, after the same failure at 2,500 and 8,000 on PR 222; thinking off answered 6 of 7 in 9 to 63 s, overlapping 3 of 29 inline findings from CodeRabbit and Copilot. So off is the fast pass that answers, and deep (`low` on Nous, `medium` on OpenRouter and Gemini, from a maintainer's `/hare deep`, `@hare deep` or `think`) is the lowest effort that still reasons; its first live run is its test. The Models cell says `· deep` when it ran. The **Effort** cell in a note is the model's own rating of the review (`low|medium|high` in its JSON), not the reasoning knob.
  - **Space Bunny's free period ended 2026-10-05.** It is off OpenRouter and Nous (#280). Zen's `space-bunny-free` is a separate offer and stays until Zen retires it; a gone model fails in under a second and falls through.
  - **#147 spec:** ghost `real` (line not in the diff) stays in the **table** and can **hold**; bubbles only on `+` lines. Runner script from **base** after this lands; this PR bootstraps the file from HEAD if missing on main. **Consequence (seen 2026-10-03):** no PR tests its own change to `hare_r1.py`; the review on a PR is `main`'s script with the PR's workflow env. The first live test of a Hare change is the next PR after it merges.
  - **Not the hourly matcher.** ChatGPT's hourly job (scan `searchts-r1-needed`) is a **mention/nag doorbell**. The Action is PR events only. Do not mix them in diagrams.
  - **Retry:** a human PR comment **`/hare`** re-runs the Action (bots ignored so the nag cannot loop). Actions → hare → Run workflow for an optional OpenRouter slug. Needed nags stay short; provider JSON is behind `<details>`. Not F15.
  - **Boring first:** fires on every same-repo PR as a GitHub **Review** (`searchts-hare[bot] reviewed`). Nags when the list is exhausted. Job is `continue-on-error` (not required CI). Local backup is `/hare`, not an in-session cheap-scout.
  - **R1d (same Action, not a second product):** CodeRabbit-shaped *refresh*. Each Hare run on a new SHA: (1) **new GitHub Review** whose body starts with `<!-- searchts-r1-review -->` (matcher = **latest** token, do not edit the 6h-old table in place); (2) **resolve** threads whose finding is gone (hunk outdated *and* the issue is not in the new diff); (3) new bubbles only for what is still true; (4) do not delete history. Skip threads may stay. **Same SHA:** if a Review with the token already exists on that commit, skip (no second `/hare` clone). Push or a new commit to re-review. **#141** proved the hole: inject **real** stayed in the first comment after the line was deleted.
  - **Quick vs deep (have / should have) — discuss later, do not build on 147.** CodeRabbit = incremental (new commits only) + `@coderabbitai review` when auto is paused. Hare **is deep-only** (full diff every SHA). Incremental / mention-review is an F15 add-on. **Do not** copy "skip already-reviewed commits" into R1c (that is #141).
  - **Revisit:** tick `[x]` after a week of PRs without a paste. Wrong Nous model id = edit `HARE_NOUS_MODEL` (portal slug). **R1d** is in this Action.
  - **Appealing after boring:** **R1b** if the Author badge still bothers. **F15** only after boring holds *and* we want a second product.
- [x] **R1b** GitHub App **identity only** — reviews show as `searchts-hare[bot]` (not `github-actions[bot]` / not `capad-xyz`). App: `searchts-hare`. One install: `capad-xyz/searchts`. Workflow mints an install token; if mint fails, fall back to `GITHUB_TOKEN`. Not a review product. Secrets: `HARE_APP_ID` (numeric App ID, required by create-github-app-token@v2), `HARE_APP_PRIVATE_KEY` (full PEM, `BEGIN` not `START`). `HARE_APP_CLIENT_ID` unused until an action version that accepts `client-id`. Logo is the App avatar, not in git.

- [x] **R1e** Hare cadence (decision 2026-10-01; the before-0.13 hold lifted 2026-10-02; built in #222). Webhook stays. A push while a review is running supersedes it: do not post the stale SHA. Quiet period so an agent burst is one review. After a finished note, a later commit is a new note for commits since that note; the old note stays. One note per push. Skip drafts and closed PRs unless asked. Comment, do not submit a blocking review, unless the repo opted in. Pause after a few reviewed pushes until `/hare` or `@hare`. `@hare` from a human with write access may take a short instruction (this file, full review, skip the computer run). It does not override the contract. A tag inside the diff is not a tag. Dead model hop posts once, then stops. Spec: https://app.notion.com/p/3ecbc1b020d3814abf05ed87a053bdad **Decision 2026-10-04 (owner):** start on every push, no CI wait (the CI line says "still running" when it is); quiet 30 s, not 90 (cancel-in-progress already supersedes a stale head); drop pause-after-three; call ceilings are guards, not budgets, and size to the diff (job 20 min normal, 40 only for a very big diff); every note prints what it cost (prompt, answer, reasoning tokens, hop); `HARE_MAX_TOKENS` / `HARE_REASONING` are the owner's caps. Stop rules sit before the spend, never mid-answer: a token spent and thrown away is the one failure (#234's three bugs were all that). **Built in #243 (2026-10-04):** no CI wait, quiet 30 s, pause off (`HARE_PAUSE_AFTER` turns it on), big-diff tier, a cost line in every fold, `HARE_REASONING` as the owner's cap. The spec line "pause after a few reviewed pushes" above is superseded by the owner's call.
  - **Near the limit, wrap up (#244, #245).** The hop streams. Past 80% of the budget the stream stops at the next closed finding, the valid partial is kept, and one continuation call with the partial as the assistant's turn finishes the JSON in 800 tokens; if that fails the script closes it and posts what was finished. A hop still thinking at 60% of the budget with no answer is cut and named. The fold says when a note was cut. `HARE_STREAM=0` turns it off.
- [ ] **HareBot** Grok Bot template, not this app. Posts as the user. Triggers: routine on named repos, or they say so. Computer run uses the repo's documented test command and does not get the token. No app key in the template. Marketing after 0.13, not a searchts slice. Same Notion note.
- [ ] **R2** Hare as a product (2026-10-02; not scheduled, launch when funded). Borrowed and fine: summary first, inline bubbles, one-line suggestions, a details fold. Hare's own: real or skip only, and skips never hold; never the merge button (comment only, no approve, no LGTM, no score); cadence built for agent bursts (**R1e**); every review names its model; `AGENTS.md` and PLAN are the contract; evidence only, injections quoted; runs on your keys. The line: **the fast reviewer that knows when to wait** (the tortoise-and-hare twist).
  - [ ] **R2a** Name and mascot check before any branding. **First.** CodeRabbit owns the rabbit (name, logo, the rabbit poems it signs reviews with), and Hare is also a programming language (harelang.org). The 🐰 marker from #222 is provisional until this is decided.
  - [x] **R2b** Findings ledger (#246, 2026-10-04): `scripts/hare_ledger.py` reads every Hare note, follows each finding through later Since lines and resolved threads, collects `/hare score 1..5 <why>` comments, and writes `docs/hare-ledger.md` and `.json` (hit rate on real findings, hops that answered, notes cut at the budget, the owner's feedback). `hare-ledger.yml` rebuilds it every Sunday 03:00 UTC or on dispatch and opens a `chore(hare): ledger <date>` PR when it changed. At review time the prompt carries a Ledger block: the owner's recent scores with reasons and earlier findings on the files in the diff with their fate. `/hare score` is recorded, not reviewed. The ledger is Hare only (#254); runs where no hop answered are counted apart from the notes (#256). Ledger on 2026-10-04: 114 PRs, 85 notes, 5 real, 28 skip, 138 runs with no answer.
  - [x] **R2c** Rules live in the repo (#248, 2026-10-04): **`HARE.md`**, Hare's own file, read with AGENTS.md before every note. The owner writes rules by hand outside the marked block; the weekly ledger run rewrites the block from scores of 2 or less with a reason, newest first, deduplicated on the reason. To retire a line, edit or delete the score comment. AGENTS.md stays the contract every agent signs; a bot rewriting a block inside it was the wrong shape. Not yet: Hare opening a PR that proposes a rule from a pattern it noticed itself.
  - [ ] **R2d** Agent-author awareness: read the Co-authored-by and Models lines, and review agent-written PRs with that in mind.
  - [ ] **R2e** Two ways in, one contract: a free Action on your own keys (`uses: <owner>/hare@v1`), and a hosted app (paid) later. The same HARE.md works on both. Hare Bot is a separate product on another platform and is not a way into Hare (owner's call, 2026-10-04).

### F — Future (ROADMAP-aligned, after core is solid)

- **F1** Persistent stealth browser profile across reads. **Revisit:** **F12** step 2. → **DONE 2026-09-09** (F1a). `launch_persistent_context` with `~/.searchts/browser-profile`; `SEARCHTS_NO_BROWSER_PROFILE=1` opt-out; same dir for stealth + `--human`.
- **F2** First-class PDF / document URL reading. **Revisit:** when a real PDF URL is a support pain.
- **F3** Optional content cache for repeat URLs. **Revisit:** if the same URL is fetched in a loop and it hurts.
- **F4** Sitemap / small multi-page crawl (bounded). **Revisit:** demand, not a crawler product.
- **F5** Document share-extractors as the official fail-open extension point (one file pattern) — **not** a generic plugin system. **Revisit:** when adding the next share host.
- **F6** Claude/marketplace plugin polish beyond P4.2 minimum. **Revisit:** with **P4.2**.
- [x] **F7** Opt-in reuse of sessions already on the machine for **transcribe / extras only**. `searchts transcribe URL --cookies-from-browser chrome` (yt-dlp). Never silent (stderr line). Never inside `read_url` (**N5**). YAML `youtube-cookies` stays unwired. OpenCLI / `gh auth` stay doctor PATH probes. **F12** step 3.
- **F10** **WebMCP** (site-exposed tools in the browser / ChatGPT Sites). Complementary surface to local MCP, not a replacement. **Revisit:** after core reach + honesty; revenue/hosted is later and must not dilute the free CLI.
- [x] **F5b** Known-host extractors as another **ladder ring** (same pattern as shares): caller passes a **page** (e.g. `reddit.com/r/foo/hot/`) → try the public `.json` document → **fail open** to curl/Jina/stealth. Not `if host==reddit: skip unlocker` (**N4/N5**). Login shells stay `login-wall`.
- [x] **F5c** Reddit listing index from HTML already downloaded. The full card body sits under each title when the light DOM has one. A comments URL uses the same HTML for the OP (title, body, score, comment count, author) when the JSON ring misses. Nested ``shreddit-comment`` nodes are their own indented entries; Reply/Share/More replies chrome is stripped. Issue [#190](https://github.com/capad-xyz/searchts/issues/190). Measured 2026-09-29 on `r/MachineLearning/hot/`: stealth `page.content()` held 27 `shreddit-post` nodes and `post-title` in the light DOM (~1.1 MB). Trafilatura kept one post (527 chars) and `_MIN_CHARS` stamped `ok`. Shadow DOM is not where those posts live. Before `html_to_text` (ladder and the human rung), if the URL is a listing and the body has at least two `shreddit-post` nodes, render the compact index and skip Trafilatura. Zero or one node falls through, so a thread still reads as a thread. Markdown stays the print format. The JSON ring stays fail-open. No scroll. No cleaned-HTML output. No extra-region pass for unknown hosts. This does not claim every Reddit URL reads (**N7**).
  - **URL detect:** `/r/{sub}/`, `/r/{sub}/hot|new|top|rising|controversial/`. Do not fire on `/comments/` thread URLs.
  - **Fixture:** several `shreddit-post` nodes with `post-title` and a permalink attribute. The test fails if the Trafilatura path still wins. Not live Reddit.
  - **Loud:** if the listing parse runs, stderr says so (P4.6). It must not look like a silent generic read.
  - **Links:** permalinks are absolute (`https://www.reddit.com/...`), not `/r/...`. Read `post-title`, `permalink`, `content-href`, `comment-count`.
  - Tess 2026-09-30: ship **F5c** with those four checks. Scroll, cleaned HTML, and unknown-host regions are their own boxes below, each with a revisit. They are not part of #190.
- **F5d** → **F23** (2026-09-30). Scroll is not a Reddit box: any site can infinite-scroll. Its rules (cap it, copy rows on each step, never scroll every read) live in **F23c**.
- [x] **F5e** Reddit HTML, next slice ([#197](https://github.com/capad-xyz/searchts/issues/197)). **0.13.** Same known-host ring as **F5b**/**F5c**, still fail-open. Does not claim Reddit reads (**N7**). Build against saved real HTML of the four #197 URLs, not guessed markup. Shipped #212 (2026-10-01), fixtures trimmed from the saved pages.
  - [x] OP behind **Read more**: the label never reaches Markdown. Full text already in the HTML: strip the label, no note. Only part of it in the page: click it in stealth (first window only). Still folded after that: say so. The #204 note fires only in that last case. Checked 2026-10-01 on both saved threads: the full text ships even when the button shows (a CSS clamp, `max-h-[253px] overflow-hidden`), so strip the label with no note and no click. Build the click only if a saved page shows part of a post.
  - [x] Post type and outbound link on every post (text, link, image, video, gallery), from `shreddit-post` attributes and media nodes.
  - [x] Media: `i.redd.it` / `v.redd.it` / `preview.redd.it` URLs, or "media present, not resolved". Image and video cards never go silent.
  - [x] `**Subreddit:**` line on thread Markdown. The JSON path already prints it; the HTML path takes it from the URL.
  - [x] Truncation honesty: comment cap and claimed-vs-shown remainder lines (#204).
  - [x] Listing cards: age, flair and the outbound URL split out of the snippet. No whole-card text fallback.
- [ ] **F5f** Reddit, the rest (2026-10-03). **0.15.** Still the known-host ring, still fail-open, still **N7**. More posts than the first screen: Reddit's own next-page cursor on top of **F23c** (same caps, says how many it left out). Deeper comments: "more replies" on top of **F23d**. Walls: private, NSFW, quarantined and removed pages each fail with a precise note. User profiles and Reddit search pages: read as cards or fail loud. Every case tested on saved real pages. The browser stays required.
- [ ] **F20** Optional cleaned HTML for a person who wants a file. Default `read` stays Markdown of the extracted document. Strip `script`, `style`, `svg`, and hidden nodes, then cap the size. This does not recover posts the HTML is missing. **F5c** needs no HTML repair. **Revisit:** when someone asks for `--html`, or a structure-heavy page where the Markdown handoff is the wrong file.
- [ ] **F21** Unknown hosts. **0.14** for **F21c**, **F21a** and **F21d** (2026-10-02); **F21b** is unscheduled. Trafilatura stays pass 1. Pass 2 appends a dropped region only when it has a heading and real text (a card, an `aside`, a terms block). Cookie bars, global nav, and ads still go. Do not guess "this URL is a product" and refuse the article extract. **Revisit:** when a saved HTML fixture exists of a two-region page (headed card beside a form). The Flywheel assessment URL is closed and was never run through Trafilatura, so it is not evidence. Do not build this from memory of that screenshot.
  - Why it matters (2026-09-30): on the Flywheel test the task sat in the sidebar card (site, target market, known competitors, notes) beside the answer form. Grok read the page and did not know the task; only a computer-use agent looking at the screen saw it. An agent that misses the card answers the wrong question.
  - [ ] **F21c** Region map first: main column versus side panels (`aside`, `role=complementary`, nav, header, footer). One map, two users: **F21a** and the **F23f** list picker. **0.14.**
  - [ ] **F21d** Django weblog dates. The live read (2026-10-02) has no "Posted by … on <date>" lines: the sidebar archive (22 years of month links) is a bigger list than the 10 posts, the picker takes it, sees a side panel and gives up, and the posts measure 39% of a page that counts the sidebar. With the map, the picker skips side-panel lists and measures against the main column. Save the live page first; tests pin Bing, Hashnode, a related grid under an article, a list the extractor keeps whole, and a comment list. Not a regression: Django reads as in 0.12. **0.14.**
  - [ ] **F21a** Say so first, the **F23a** way (**0.14**): when a region with a heading and real text was dropped, the read ends with `[left out: a side panel headed "prommer.net"]` and `more` gets a `region` entry. No text added yet, but the agent knows the card exists. Same chrome rules: nav, cookie bars, ads and footers never count.
  - [ ] **F21b** Add it back (pass 2) once the fixture exists (after a Devpost or job-application page is saved). Unscheduled. The same test covers form questions: the extractor drops `<form>` whole, so an application page loses its questions. Keep the question text (labels, legends, headings inside the form); never field values or hidden inputs.
  - Fixture candidates (live HTML, not screenshots): a Devpost hackathon page (sidebar: deadline, prizes, who can enter; the page that started searchts) and a job application page with the role card beside the form.
- [x] **F9** Localhost HTTP/SSE: `searchts mcp serve --http` → `http://127.0.0.1:8765/mcp` (Streamable HTTP); `--sse` for the old path. Bind loopback only (`127.0.0.1` / `localhost` / `::1`); refuse `0.0.0.0` / LAN. **Consumer:** Grok / Claude custom connector that cannot spawn stdio. Public/hosted MCP URL is still **N2**. Auth for HTTPS connectors is later; P3.6 SSRF already guards tool URLs. Not in P2.1–P2.3.
- [x] **F8** Install/docs: pipx = keep the CLI; uvx = try + MCP one-shot. README + `mcp install` snippets. Do not ship an npm wrapper. Hosts that cannot see PATH need a full-path or uvx command. Skill install today writes `.claude/skills` and `.agents/skills`, not `.codex/skills`. **Revisit Codex path:** measure demand first (no id until someone asks).
- [x] **F8b** Install-copy leftovers: `llms.txt` / `docs/update.md` / `check-update` `_UPDATE_INSTRUCTIONS` match F8. No `main.zip`, no `search-twitter`, doctor is read-only. Did **not** rewrite contributor `pip install -e`. Extra-missing `pipx inject` skipped (hints still `pip install "searchts[extra]"` for venvs). **Revisit inject:** if pipx users miss the mcp extra.
- [x] **F8c** Remaining 2025 copy: `docs/install.md`, `CLAUDE.md`, `searchts/guides/setup-*.md`, **`docs/troubleshooting.md`**. Same honesty as F8b.
- [ ] **F11** Windows: `pip install -e .` / `pipx install --force` still fails while `searchts mcp serve` holds the shim (OS error 32). RUNBOOK has the workaround (close those clients, or kill the PIDs, then install from a folder that is not an old checkout). **Doctor** prints those `searchts.exe` PIDs and does not kill them. **Do not** add `--single-instance`, a machine-wide mutex, or `searchts mcp stop`. A stop command would kill every host's server, including the one you are typing in, and the process holding the file still cannot replace itself.
  - [ ] **F11a** Doctor skips every `searchts.exe` above it in the process chain, not only its parent. **0.13.** #204 says doctor no longer lists itself; that holds for `python -m`, not for pipx on Windows: pipx's `searchts.exe` starts the venv's `python.exe`, which starts the real one, so the launcher is the grandparent. Live check 2026-10-02: PIDs 6052, 20772 and 35056, a new one each run, with no MCP host registered; `python -m searchts doctor` clean. Test with a fake process tree.
- [x] **F17** Subtitle-first: `--sub-lang en,en-US,en-GB,en-orig` (not `en.*`); `--ignore-errors`; salvage a written `.vtt` if yt-dlp still exits nonzero. **Tess 2026-09-20 / #151.**
- [x] **F12** Wall playbook (docs): **P3.11** (done) → **F1** (persistent profile, code next) → **`--human` / F7** (extras only). Never **N1** / **N3** / **N7**. README unlocker section. Not a Reddit-green 0.8.1.
- [x] **F13** Optional update nudge: cached ~24h GitHub check, **stderr only**, skip `mcp serve` / pipes / `check-update`, `SEARCHTS_NO_UPDATE_CHECK=1`. Not bundled with F8b.
- [x] **F19** Say when an update did not land. **F13** only says a newer release exists. It does not say this process is still the old build. If `searchts --version` is behind the install that just ran, stderr says the update did not take effect, names the PID holding `searchts.exe` (**F11**, do not kill it), and prints the one command for how it was installed (`pipx`, `pip`, or `uvx`). Do not run that install. Do not add `searchts mcp stop`. `uvx` already picks up a new build on the next invoke. **Revisit:** next time the update nudge is touched. Not this week.
  - [ ] **F19b** Two installs (2026-10-03). `pip install -U searchts==0.13.0` updated the system Python while `searchts` on PATH was the pipx env, so `--version` still printed 0.12.0. Doctor names every `searchts` on PATH with its version and says which one runs. Candidate, unscheduled.
- [x] **F22** One-command browser tier for strangers: `searchts install --browser` installs the `[browser]` extra's requirements and Chromium into the env the CLI runs from (`pipx inject` when pipx is on PATH, else that env's pip). uv tool and ephemeral uvx are never pip-installed into; they get a one-line hint and exit 2. Chromium lives in the per-user ms-playwright cache. `doctor` shows stealth **installed** (an import probe; it does not launch Chromium). Shipped #201; plain source and review fixes #202, plus a test that fails on `exec(` / `b64decode(` in the package. Not Solari (**F14**). Not Docker (**P4.4**).
  - [ ] **F22b** `searchts uninstall --browser`. **0.14.** The undo for **F22**, same scope: remove only what `install --browser` added to this env (patchright: `pipx uninject`, else that env's pip). Ephemeral uvx has nothing to remove: drop `browser` from the spec. Chromium stays by default (a per-user cache other envs and tools share); remove it only behind an explicit flag. Say what it will change first, like install, and support `--dry-run`.
  - [ ] **F22c** A link pasted inside `[...]` or `<...>` (from chat or Markdown) reads as the link, or says plainly it is not a URL. **0.13.** Today `read "[https://…]"` fails with "scheme '://' is not allowed".
- [ ] **F23** More than the first window, on any site (2026-09-30). Infinite scroll, pagination, "Read more" folds and accordions are one problem: the page has more than what came back. **Always detect; fetch more only when asked.** This takes fail loud from "is this a wall" to "is this the whole page". Replaces **F5d**.
  - [x] **F23a** Detect and say. On by default, no extra requests. **0.13.** Shipped #206; live test on Bellami (Django weblog, Hashnode feed, Bootstrap accordion, Go blog silent, Bing SERP). Follow-up: Next links named by `aria-label`/`title` or sitting in a page-number pager (Bing, Google), and a next link only counts when it continues this URL, so WordPress's `rel="next"` to the next *post* and docs "next chapter" links are not a next page. Comparison run fixes (#209, 2026-10-01): an accordion button inside the page's own heading reads as that heading, a menu toggle ("On this page") is not a question, and headings or code fences the extractor printed indented or glued go back on their own line. A declared `rel="next"` link counts whatever it says (Hacker News "More").
    - Pagination: `rel="next"`, a numbered pager, `?page=N` or `/page/N/`. A trailing note in Markdown, `next_url` in `--json` and MCP.
    - Folds: a "Read more" button or collapsed control. Strip the label and note that text behind it may be missing. A "Read more" that links to another URL is a link, not a fold (blog indexes).
    - Feeds: `role="feed"` or a "Load more" control. Note: first N items, more load on scroll.
    - Accordions and tabs: text already in the HTML is kept, the question as a heading and the answer under it. Fixture tests so the extractor cannot drop hidden panels. A panel that is empty in the HTML counts as a fold.
    - List pages: many repeated items (cards, results, posts) but the extractor kept only a few. Say so ("kept 1 of 27 items"). On Reddit Trafilatura kept 1 of 27 posts and still passed `_MIN_CHARS`; any card page can do that. The index itself is **F23c** (same item detector).
    - Caps and counts: any cap searchts applies prints what it left out. When the page states a count ("36 comments", "Showing 1–20 of 340", "Page 2 of 9") and fewer came back, say so. Generalizes the #204 Reddit notes.
  - [x] **F23f** List index, first window. **0.13**, pulled forward from **F23c** (2026-10-01) after the comparison run. Curl gets every item; the extractor loses them. Bing kept 0 of 10 titles and links. Hashnode kept all 10 cards but no links, with words run together ("MUMuhammed Umerinumercodelabs.hashnode.dev"). Django dropped every "Posted by … on <date>" line.
    - On a list page, render each item from the HTML: title, link, a byline (author, date, read time) and the snippet. Join an item's text pieces with spaces so nothing runs together.
    - Bing result links go through `bing.com/ck/a`; print the target, which sits in the `u` parameter (`a1` plus base64url, checked on all 10 results).
    - Fixtures: curl-saved `hashnode.com/tag/web-development` and `bing.com/search?q=searchts`, a browser-saved `hashnode.com/tag/python`, and the Django weblog rebuilt from its own templates.
    - **F23c** keeps the multi-step `--items` collection (0.15).
    - Live check 2026-10-02 (Windows): Bing and Hashnode pass. Django still has no dates; see **F21d**. The rebuilt Django fixture had a one-item sidebar, so the tests missed the archive.
    - [ ] Bing redirects are decoded only on `bing.com` and its subdomains; lookalike hosts stay as written (#217, with the MCP Windows device-name refusal). **0.13.**
    - Shipped (2026-10-01): it replaces the extract only when the page is made of a list, the extract is mostly that list, and the extract lost most items' titles, links or dates. A related grid under an article, a list the extractor kept whole, and an article over a comment list are left alone (tests). The read says `[list: N items rebuilt from the page; …]` and `more` gets an `index` entry.
  - [x] **F23g** Table lists (Hacker News). **0.14.** Title row plus the detail row under it. The index keeps the title, the link, and the points. Items are `tr` rows with their details in the next row; the read prints one word per line with no links, and the index does not take table rows yet. Same as 0.12, not a regression.
  - [ ] **F23b** Pagination: `--pages N`, MCP `max_pages`. **0.14.** Follow `rel=next` on the same host, curl first (no browser). MCP SSRF check on every followed page. Stop on a loop, a wall or the cap. Each page keeps its own URL in the output.
  - [ ] **F23c** More items: `--items N`, MCP `max_items`. **0.15.** Cheapest way that works:
    - A next-batch URL in the HTML (`rel=next`, a "Load more" link, a cursor like `?after=`): fetch it with curl.
    - Content only through JavaScript: scroll in stealth. The `--human` browser can reuse the same engine.
    - That is needed but the browser tier is missing: say so and print `searchts install --browser` (**F22**).
    - Scroll: the first step is a probe (nothing new loads: not a feed, stop). Each step copies items keyed by link or text hash, so lists that unmount old rows still count. A stalled scroll with a "Load more" button clicks it (same intent). Stops at N, after 2 empty steps, on a sign-in wall or captcha, or at the ceiling. Always says what it got and why it stopped.
    - The same item detector renders a list page as an index (title, link, snippet) when the extractor kept only a few items. Generalizes **F5c**. The first window ships first as **F23f** (0.13).
    - JSON cursors differ per site and stay with known-host adapters (**F5b** ring, e.g. Reddit), not the generic engine. Reuse the scroll step from `share_extractors/_browser.py`; the loop is new (the page height never settles; rows are copied per step).
  - [ ] **F23d** Expand: `--expand`, MCP `expand`. **0.15.** Unknown sites get no auto-click by default: clicks can navigate away, hit consent, sign-in or vote buttons, and make reads slower and different each time. The opt-in opens accordions first (`<details>` via its `open` attribute, `aria-expanded` toggles), then buttons labelled read, show or see more. Never links, forms or sign-in. A few clicks at most. Share links and known hosts keep expanding by default with known selectors. "Continue reading" on news sites is usually a paywall: note it, never work around it.
  - [ ] **F23e** Knobs. **0.15.** Expose intent and limits, never mechanics.
    - Per call (flags and MCP): intent only, `--pages`, `--items`, `--expand`. Three MCP params; each extra one is another thing a model can get wrong.
    - User policy (env, then a `more:` block in the config; flag beats env beats YAML): defaults and ceilings for pages, items, clicks, seconds, delay between steps, and empty steps before giving up. Starting values: 300 items, 60 s, 1 s delay, 2 empty steps. Defaults stay off.
    - **The agent asks, the user caps.** MCP can request up to the ceiling, never raise it (same idea as `SEARCHTS_MCP_OUT_DIR`). A clamped request says so.
    - Same names everywhere: `--items`, `max_items`, `SEARCHTS_MAX_ITEMS`, `more.items`.
    - Internal, not exposed: item-list detection, scroll distance, wait logic.
  - Fixed, not configurable: same-host pagination, SSRF on every hop, never click links, forms or sign-in, no paywall workarounds, honest stop notes, P4.6 ticks per page and step.
  - **Revisit** per-site overrides and an item-selector escape hatch only when real sites need them. Not in v1.
- [x] **F25** A short page that is the whole page is not thin (2026-10-03). **0.13.1, before Show HN.** `searchts read https://example.com`: curl got 156 chars, called it thin, tried Jina (403) and the browser, and domain memory then sent example.com straight to the browser on the next read. People try example.com first. Thin should mean "the page has more than the extract", and a false thin must not pin a domain. Shipped #228: `whole_short_page()` on the curl rung, 19 tests. A win on a remembered rung no longer extends its pin, so the browser pin 0.13.0 gave example.com heals.
- [ ] **F26** Skip the Jina relay for the rest of a run after a 403 (2026-10-03). From the home connection it returned 403 on every escalation, so it only added wait. Candidate, unscheduled.
- [ ] **F24** Generic page fidelity: what Reddit got first, for unknown sites (2026-09-30). **0.15 or later.** Page signals, not per-host code (**N4**).
  - [ ] **F24a** Media. Generic reads drop images, video and embeds today (checked 2026-09-30: `include_images` is off, and `<video>` and YouTube iframes vanish). List main-content media with URLs (images with alt text, `<video>` and `og:video`, YouTube and Vimeo embeds), or "media present, not resolved". A video URL can go straight to `transcribe`. Generalizes the **F5e** type and media lines.
  - [ ] **F24b** Structured data already in the page, read before the extractor: JSON-LD (`articleBody`, `FAQPage`, `DiscussionForumPosting`, `QAPage`) and app state such as `__NEXT_DATA__`. No extra request, and it often holds the text behind folds and accordions. Share extractors already do this per provider. Generalizes the idea behind the **F5b** `.json` ring.
  - [ ] **F24c** Context line: site, section, author and date from page metadata. The extractor can return them; `read` does not ask today. Generalizes the **F5e** Subreddit line.
  - [ ] **F24d** Spacing next to inline code and bold: the extractor drops it ("the`.accordion-collapse`", "body.**It", Bootstrap docs, 2026-10-01). Low impact. A careful post-pass, never inside code.
  - **Revisit, not now:** domain memory learns which domains to leave unpinned (today `reddit.com` is hardcoded). Nested comment trees only for pages that declare a discussion in JSON-LD (flat comments are already kept). `.json`-style endpoints for other platforms (Discourse) one file each in the known-host ring, on demand. Never guess endpoints on unknown sites.
  - Stays Reddit-only: the `shreddit-post` and `shreddit-comment` selectors, score and flair, the old-to-www permalink rewrite, `?after=` cursors.
- [ ] **F14** Opt-in Solari (cloud Playwright) **only when local `[browser]`/patchright is missing**. `SOLARI_API_KEY`. Never default (**N3**). 2026-09-02 cookbook: Reddit/LinkedIn still walls. Artifact: https://github.com/capad-xyz/solari-cookbook/tree/main/examples/agent-read . **Article is live.** **Revisit:** if Harry replies, or keep-gate = would pay Starter to skip patchright (not Reddit green).
- [ ] **F15** Hare as a **review product** (other repos install an App, billed, CodeRabbit-shaped). **Different intent from searchts.** Own thread, own glossary: Model = provider + API model, not ocx / cheap-scout / this chat. R1d refresh **and** Checks-before-Intent (Check Runs API; never ship a red required job) or the product looks like #145. Do not mix sprints or tokens with the unlocker. **Revisit:** only as its own thread, after R1c has been boring. **Should-have (later):** incremental/"quick" vs full/"deep"; `@mention` doorbell like `@coderabbitai review`; paid failover across providers. Not R1c.
- [ ] **F16** Disposable remote workspace: GitHub Actions (or similar) as a **harness box** (shell, git, network) without shipping an agent. Different product from Hare and from searchts. **Revisit:** after F15 is a real question, not a side quest.
- [ ] **F18** Paid searchts. **Hosted `read` first.** The free CLI stays free and keyless. Walls are a second product and stay **N1** until a wall pass is real. **Not this week. No price in this file.** **Revisit:** when the free tool is something you would hand a stranger and it does what it claims (install, a real page, fail-loud where it cannot). Then design the hosted shape. Innovate on top of a product that already works. Not **F15**.

### N — Not planned (explicit)

- **N1** Paid residential proxy pools as defaults
- **N2** A public hosted URL for the free CLI. A paid hosted `read` is **F18**, not a default, and not before its trigger.
- **N3** Keyed commercial unlockers as default backends
- **N4** Generic plugin/connector architecture for platforms
- **N5** Routing `github.com` / Twitter through upstream CLIs inside `read_url`
- **N6** MCP resources/prompts before tools are trusted and reachable
- **N7** Cut **0.8.1** (or any release) claiming Reddit/LinkedIn now read. Honesty, not a trophy.

---

## 5. Comms rules

| Beat | Trigger | Content |
|---|---|---|
| X1 | P0.7 merged | Scorecard was smoke; thin ≠ pass; smoke vs walled |
| X2 | P1 acceptance green | Demo: wall → `read_url` without being told (#22) |
| X3 | P3.1 + P3.2 | One before/after on a real wall; name the signal, not "we beat Vendor forever" |
| X4 | P2.3 + host smoke | One line: mcp 2.x no longer kills the server |

Article after P0 (better with one P1/P3 win). Draft free; publish when the repo matches the story.

**Reach rules (2026-10-03).** Posts were under 50 impressions on X and LinkedIn. Stories, not versions: one or two posts a week, each true for several releases; release notes stay in the changelog. Hook = a problem in one line, then real proof (a clip or a before/after), then the difference, then the install line; links in the first reply or comment. Real output only: styled screenshots of real runs are fine, generated terminal footage is not. Fifteen minutes a day of real replies on bigger accounts' posts about agents and MCP (a reply on a 1.1M account already got a DM). Post from `@aadarsh_io`; reserve a searchts handle, switch when there is an audience. Show HN when **F25** ships (0.13.1), on a weekday morning US time; P3.7c is done (#227).

Organic X / LinkedIn: draft here; publish from `@aadarsh_io` (and LI). **Distribution order (2026-09-30):** product is ahead of reach (few stars vs many releases). Next gains = first-run + proof + focus, not feature count. Loud campaigns lead with **fail-loud honesty** and **AI-chat share links** (proven, keyless). Reddit listing/parser is **proof of progress**, not the permanent homepage hook, and never "Reddit unlocked" (**N7**). **Show HN**: the gate is in the Reach rules above (2026-10-03). Freeze **F15** / **F16** / **F18** side quests until real users show; F18 trigger unchanged.

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
| 2026-08-24 | P2.2 #97 + P3.10 #96 on main. |
| 2026-08-25 | P2.3 #98: MCPServer + mcp>=2,<3. Host smoke still for X4. |
| 2026-08-26 | F10: WebMCP = future complementary surface; revenue/hosted later. X3 ready to post. |
| 2026-08-26 | #100: `read` progress + mcp serve banner. **P4.6** CLI UX for doctor/search/transcribe/grab — schedule tomorrow. |
| 2026-08-26 | P3.3: domain memory TTL (24h default) + unpin on remembered-backend failure. |
| 2026-08-26 | P3.4: drop hardcoded Chrome 126 UA; `_UA_REAL` single-sourced in unlocker, imported by search.py + share_extractors/_browser.py; updated to Chrome 152 stable. |
| 2026-08-26 | P4.6 doctor slice: stderr ticks in check_all (progress=), CLI enables, --json keeps stdout clean. |
| 2026-08-26 | **P3.6b** parked: per-hop SSRF (redirect / DNS rebinding) after P3.6 first-layer MCP guard. Not U5. |
| 2026-08-26 | P3.5: Jina stays default; document r.jina.ai sees URLs; `SEARCHTS_NO_JINA=1` / config `jina: false`. |
| 2026-08-26 | **X3** posted: wall before/after honesty (no bypass claim). |
| 2026-08-26 | **X4** posted: mcp 2.x no longer kills `mcp serve`. |
| 2026-08-26 | P4.6 search: provider attempt ticks via progress param (stderr), --json silent — #110 |
| 2026-08-27 | P4.6 media + verb audit: transcribe/grab/get/check-update/watch stderr ticks — #109 |
| 2026-08-27 | **P3.7** walled scorecard: split smoke (open pages) vs walled (Reddit/LinkedIn/Cloudflare/DataDome/X/Booking) suites; per-suite honest pass rates; `--suite smoke` / `walled` / `all`; smoke-only committed numbers in docs/scorecard.md, walled documented as not-yet-measured (run from residential IP). |
| 2026-08-27 | P4.6 applies to new long runners (incl. `benchmarks.run`): ticks + TTY-fit output; `--out` stays plain MD. — #112 |
| 2026-08-27 | bench runner: TTY Rich scorecard, per-case stderr ticks, `--out`/pipes/`--json` plain. — #113 |
| 2026-08-27 | `benchmarks.run_case` forwards `progress=` into `unlocker.fetch` so ladder ticks during a long case; `--json` stays quiet. |
| 2026-08-27 | **F8** install story (docs): pipx keep / uvx try+MCP / pip venv-only. PATH note: uvx or `pipx which searchts`. |
| 2026-08-27 | **F8b** parked: llms.txt + update.md + extra-missing hints. Not F8. |
| 2026-08-28 | **P3.7b** login-wall: Sign in/Join now shells fail; LinkedIn `/feed/` login chrome is not a pass. |
| 2026-08-28 | Live: LinkedIn `/feed/` is `login-wall` (intended). Reddit stealth `page.content` nav race parked as **P3.11**. DataDome marketing + Booking homepage still yes. |
| 2026-09-06 | **P3.11**: stealth waits for load / retries `page.content()` on navigating; fail loud, no thin HTML. Does not claim Reddit now reads. |
| 2026-09-06 | **R1** + `AGENTS.md`: writer ≠ reviewer when CodeRabbit is dark. Not a skill. |
| 2026-09-06 | **Hare**: R1 reviews are GitHub PR comments with `<!-- searchts-r1-review -->` (Name / Purpose / Model / Effort). Hourly matcher: that token. Display: 🐇‍❄️. |
| 2026-09-06 | **Hare ≠ orchestrator.** Cheap-scout reviews. Orchestrator merge-only unless cheap path is dead. Role, not a vendor — Grok/Claude/Codex can be either. #132 Hare comment was the orchestrator — that was the miss. |
| 2026-09-07 | **NAMES.md** — orchestrator (remote/local), Hare, cheap-scout. Local spawn is still a step; R1c only covers remote push. |
| 2026-09-08 | **F8b** copy: llms.txt + update.md + `_UPDATE_INSTRUCTIONS` match F8. Article was already live. F13 not in this PR. Dropped wrong `pipx inject searchts mcp` comment. |
| 2026-09-09 | **Hare checks:** Intent ship only if required CI is green. #145 shipped while `ci / test` was red. F15: Check Runs API, not a paste. |
| 2026-09-09 | **R1c proving:** Action `hare / r1`. Secrets NOUS then OR then Zen (OpenCode). Ling Fin, not Muse (contributor trains). |
| 2026-09-09 | **R1c spec:** ghost real stays in table + holds; runner from base; pipeline not harness. Hourly GPT matcher ≠ Action. Quick vs deep parked (F15). F16 = remote harness box. |
| 2026-09-07 | **README** demo URL = Wikipedia (X5 leftover). `claude mcp add` try-path = uvx. example.com stays for grab/get only. |
| 2026-09-07 | **`python -m searchts`:** add `searchts/__main__.py`. Last night PATH was pipx 0.8.0; `-m searchts` had no `__main__`. `python -m searchts.cli` still works. |
| 2026-08-28 | **F11** parked: Windows editable install vs live `searchts.exe`; no `--single-instance` mutex. |
| 2026-08-28 | Park rule: skip + still worth it → PLAN id + revisit; else **N**. |
| 2026-08-28 | **X2** posted 2026-08-27; **P1.3** closed. PyPI 0.8.0 (#78) before article; do not wait on P3.11/F8b/F11. |
| 2026-08-29 | **F5b** known-host extractors (fail-open ring, after P3.11). **F12** wall playbook (P3.11 → F1 → human/F7; never N1). After 0.8 + article. |
| 2026-08-29 | **PyPI 0.8.0** (#78). Article draft filled in Notion; publish after uvx confirm. |
| 2026-08-30 | **X5** posted. **F13** parked (nudge after article, same PR as F8b). Demo URL `example.com` is thin — next time Wikipedia. |
| 2026-09-02 | **F9** consumer: Grok/Claude custom connector URL. **F14** Solari battery parked (cookbook only). |
| 2026-09-06 | **F5b**: known-host extractors ring (Reddit .json) — fail-open, no domain-memory pinning, no login-wall special-case; fixtures + tests; `known_hosts/` package mirrors `share_extractors/` |
| 2026-09-09 | **F1a**: persistent stealth/human browser profile — `launch_persistent_context` with `~/.searchts/browser-profile`; `SEARCHTS_NO_BROWSER_PROFILE=1` opt-out; same dir for stealth + `--human`; tests mock patchright |
| 2026-09-20 | **R1b** `searchts-hare[bot]` identity on main (#148). |
| 2026-09-20 | **R1c retry:** `/hare` comment + graceful `searchts-r1-needed`. |
| 2026-09-20 | **F9** localhost Streamable HTTP / SSE (`mcp serve --http`). Bind loopback only; hosted still **N2**. |
| 2026-09-20 | **F7** `transcribe --cookies-from-browser`. Opt-in, stderr, never `read`. YAML youtube-cookies still dead. |
| 2026-09-21 | **F17** subtitle salvage: no `en.*`; ignore-errors; keep a written `en.vtt` on 429. |
| 2026-09-21 | **P4.1** MCP `transcribe` tool. Error string; SSRF on URLs; cookies opt-in. |
| 2026-09-21 | **R1c hops:** Nous Laguna → Step 3.7 Flash; OR Laguna → Qwen3.8 27B → Nex-N2.5-Pro; Zen Ling Fin last hop. |
| 2026-10-01 | **R1c catalog:** Space Bunny on Nous / OR / Zen. Nous pins are `:free`. Dropped Nex (gone). LongCat 2.5 added. Ling Fin stays Zen last hop. |
| 2026-09-21 | **0.9.0** tagged + PyPI. **X6** posted (`@aadarsh_io`). Wikipedia demo URL. |
| 2026-09-21 | **F13** stderr update nudge, 24h cache, skip mcp serve / pipes. |
| 2026-09-21 | **R1c cap:** LLM hop 60s; job 10 min backstop. |
| 2026-09-22 | **R1b/c:** review posts as GitHub Review (no name table). Local spawn = `/hare`. |
| 2026-09-22 | **R1c:** concurrency key includes `event_name` so CodeRabbit comments do not cancel the PR review. |
| 2026-09-22 | **R1d:** skip a second Review on the same SHA (`/hare` no-ops if one exists). |
| 2026-09-23 | **P1.4** 0.9.0 hammer catalog (Tess). Next PR = fail-loud top 5. No stubs. |
| 2026-09-23 | **P1.4 fail-loud:** YouTube exact id; empty transcript errors; doctor Jina 403; no `https://` rewrite of `file://`/`data:`; CLI loopback refused. |
| 2026-09-23 | **P1.4 doctor JSON:** `backends` is the live probe, not the candidate ladder. SSRF text no longer says "via MCP" on CLI. |
| 2026-09-23 | **P1.4 Jina probe:** doctor calls `_fetch_jina` (same client as `read`). A 200 from a different User-Agent is not "available". |
| 2026-09-23 | **0.10.0** on PyPI. No post. Fail-loud slice is in the wheel. P1.4 stays open for the #22 harness (**U1**). |
| 2026-09-23 | **P3.6b-hop** started. F9 already shipped, so the redirect revisit fired. Same-host DNS rebinding stays open. |
| 2026-09-06 | **F5b rewrite**: HTML listing/thread (www/old/no-www, hot/new/top/rising, comments) try public `.json`, then fail-open. Caller passes a page. |
| 2026-09-23 | **F18** Paid searchts is hosted `read` first. Free CLI stays. Walls stay N1 until a pass is real. No price. Not this week. |
| 2026-09-23 | **P3.6b-rebind** pin curl and Chromium to the checked address. |
| 2026-09-23 | **F11** RUNBOOK: Windows editable install fails while `searchts.exe` is held. No mutex. |
| 2026-09-23 | **U1** protocol written. Not closed. A real MCP-only session still has to be logged. |
| 2026-09-23 | **U1** first session: FAIL. Laguna used `web_fetch`, got a 200 login form, never called `read_url`. Box stays open. |
| 2026-09-23 | **F11** note is not a fix. Install still fails while `searchts.exe` is held. Box reopened. |
| 2026-09-23 | **F11** no `searchts mcp stop`. It would kill every host. Doctor may later print the PIDs. Do not auto-kill. |
| 2026-09-23 | **U1** rule path: with the new paragraph in the rules, Laguna called `read_url` first. Login-wall was honest. Box stays open. MCP-description-only is still untested. |
| 2026-09-23 | **Hare** must say what the diff does. Nits are **skip** rows. An empty table is not a review. Skip still does not hold. |
| 2026-09-23 | **P1.1b** `searchts` replaces a reach block only when it is the old official 403 sentence. Edits stay. Missing files stay missing. |
| 2026-09-23 | **U1** answered. Where the tool was listed, the description alone called `read_url` third. Bellami does not count: MCP was pending. The paragraph is what worked. |
| 2026-09-24 | **F11** doctor prints `searchts.exe` PIDs. It does not kill them. The upgrade still fails while the file is held. |
| 2026-09-24 | The next **U1** session is manual. The user runs it. No test, no agent, no `CLAUDE.md` edit. Only after a new instruction path. |
| 2026-09-24 | Correction: tests are allowed. The user runs the live check. Steps and the expected result come first. Still no agent, and no `CLAUDE.md` edit. |
| 2026-09-24 | **P1.5** isolation pass on Tess's computer. Reach file absent. Grok CLI `read_url` second. OpenCode `read_url` first. |
| 2026-09-29 | **F19** parked. If an upgrade did not apply, say so, name the PID, print the one command. Do not auto-install or auto-kill. |
| 2026-09-29 | **P1.5** this laptop. OpenCode 1.18.33 `--pure`, searchts skill denied, reach block removed for the run and restored. `read_url` first, then a plain fetch of the login wall. |
| 2026-09-30 | **F5c** next unlocker slice. The hot-page HTML already has the posts. Parse `shreddit-post` before Trafilatura. Markdown stays. No HTML repair. |
| 2026-09-30 | **F19** nudge says the process is still old, names the PIDs, prints one install command. Does not auto-install or auto-kill. |
| 2026-09-30 | **F5d**, **F20**, **F21** are open boxes with a revisit each. Scroll-for-more, a cleaned-HTML file, and unknown-host regions. Not a buried "deferred" line, and not this week's build. |
| 2026-09-30 | **X7** + **LI1** posted (0.12 Reddit listing cards + 0.11 MCP catch-up). First LinkedIn beat. |
| 2026-09-30 | Distribution fold (Claude / Tess): **F22** one-command browser install; **P3.7c** publish real walled rates; quieter story releases; Show HN after P3.7c; lead long-form with honesty + share links; Reddit = proof not identity. |
| 2026-09-30 | **F23** more than the first window, on any site (not Reddit-only): always detect, fetch more only when asked; cheapest way first (a URL goes to curl, JavaScript to stealth); the agent asks, the user caps. Replaces **F5d**. |
| 2026-09-30 | **0.13 holds** (#198 stays open) for **F5e** (#197 Reddit HTML slice) and **F23a** (detect and say). Already in: **F22**, **F19**, #204 hardening. **0.14** = **F23b** to **F23e**. |
| 2026-09-30 | **F24** generic page fidelity (media, structured data, context line) and two **F23a** notes (list pages that kept few items; caps and claimed counts). What Reddit got first, for unknown sites. |
| 2026-09-30 | **F22** shipped (#201). #202 puts it back as plain source (it had shipped as base64 run through `exec`) with review fixes, and adds a guard test. Replaces #199, whose PLAN.md upload broke. |
| 2026-09-30 | Code review hardening (#204). MCP SSRF also refuses `0.0.0.0/8`, `::`, CGNAT, multicast, reserved, and IPv6 forms that carry an IPv4; `grab` assets go through the same guard. MCP saves stay inside one folder (working dir or `SEARCHTS_MCP_OUT_DIR`) and never overwrite. `--human` and MCP tool bodies fail loud with a named reason. Reddit HTML says when the post or comments were cut (#197 honesty part). |
| 2026-09-30 | **F21** gets its why (the Flywheel task sat in the sidebar card; Grok missed it), **F21a** a say-so note first, **F21b** add the region back with form questions, and fixture candidates (Devpost, a job application page). |
| 2026-10-01 | Comparison run (screenshots against reads: Django, Hashnode, Bootstrap). #209 fixes the accordion headings and code fences. Hacker News "More" counts as the next page. **F23f** list index pulled into 0.13 (Django dates, Hashnode links, Bing titles). 0.13 holds for **F5e** and **F23f**. **F21a** stays unscheduled. **F24d** inline spacing noted. |
| 2026-10-01 | **F5e** (#212): Reddit HTML prints type, flair, posting time, outbound and media URLs and the subreddit; listing snippets come from the post text only; the false "Read more" truncation note is gone (the whole post ships in the page). Not a Reddit-reads claim (**N7**). |
| 2026-10-01 | **F23f** list index shipped: Bing gets titles and real links (the `ck/a` redirect decoded), Hashnode gets links and stops running words together, the Django weblog gets its dates. Fixtures trimmed from the saved pages. |
| 2026-10-01 | **0.13 ready** on main: **F5e** (#212), **F23f** (#213), **F23a** (#206, #207, #209, #211), **F22**, **F19**, #204 hardening. #198 stays open for the owner's live checks and review; not merged. |
| 2026-10-01 | **R1e / HareBot** decided, not built. Hare: supersede in-flight, quiet period, incremental after a finished note, one note, no blocking review, `/hare` and `@hare`, dead hop once. HareBot: template, posts as the user, routine or chat, no app key. Notion: https://app.notion.com/p/3ecbc1b020d3814abf05ed87a053bdad 0.13 still first. |
| 2026-10-02 | Correction: **0.13** is not ready. Live checks on Windows: Reddit thread and listing, Bing, Hashnode, Hacker News next page, uvx and pipx `install --browser`, MCP saves and `0.0.0.0` pass. Django has no dates (**F21d**), and pipx `doctor` lists its own launcher (**F11a**). The 2026-10-01 line saying **F23f** gives Django its dates is wrong. |
| 2026-10-02 | **0.13 holds** (#198 open) for **F11a** (doctor), #217 (Bing host, Windows device names) and **F22c** (pasted links). Django dates move to **F21**. |
| 2026-10-02 | Release split. **0.14** = **F21c** region map, **F21a**, **F21d** Django dates (**F21b** stays unscheduled until a fixture is saved), **F23b** pagination, **F23g** table lists, **F22b** `uninstall --browser`. **0.15** = **F23c** to **F23e** (scroll, expand, knobs) and **F24**. Replaces "0.14 = F23b to F23e" (2026-09-30). Not tied to a release: **LI2** after 0.13 is on PyPI, **P3.7c** before Show HN, **HareBot** after 0.13. |
| 2026-10-03 | **0.13.0** on PyPI (2026-10-02). **P3.7c** done: home run Smoke 12/12, Walled 2/7 (named), committed in #227. Booking failed there, so the earlier 559-char pass is not quoted. |
| 2026-10-03 | Reddit gaps go to **F5f** in **0.15** (cursor on **F23c**, more replies on **F23d**, walls, profiles, search). **0.14** stays non-Reddit. 0.15 is heavy: **F24** may slip to 0.16 (its line says "0.15 or later"). |
| 2026-10-03 | Distribution: version-free stories (**X8** thread, **LI2** motion video on real output), reach rules in section 5. Show HN after **F25** (0.13.1); the scorecard is #227. |
| 2026-10-03 | #227, #225, #228, #229 merged. **F25** ticked. Both Show HN gates are clear; **0.13.1** is a `fix:` release-please tag off #228, so the gate is really "0.13.1 on PyPI". README now says why searchts exists (#229) and six docs stopped calling example.com thin. |
| 2026-10-04 | **Hare answers.** #235 (reasoning off on Nous, 300 s call, 600 s hop budget, brace-aware JSON reader, errors that name the cause), #236 (catalog from the live list and the live nag), #238 (thinking off vs on, measured), #239 (Models section names the slug), #240 (`/hare deep`). #234 closed with credit, #237 closed as a duplicate of #235 plus #238. Live reviews that night came from Groq gpt-oss-120b and Gemini 3.1 Flash-Lite. Cadence PR and `hare_local.py` next; **R2** (Hare as a product: format the Action enforces, findings ledger, rules in the repo) is the sitting after that. |
| 2026-10-04 | **Hare, second pass.** #242 (answer budget 32,000, owner's call), #243 (cadence: start at once, size the spend to the diff, cost line), #244 and #245 (wrap up at the limit: stream, seam, one continuation, repair), #246 (findings ledger, `/hare score`), #247 (Gemini is the fallback), #248 (`HARE.md`). **R1e**, **R2b**, **R2c** ticked. Live that night: cost lines in the fold (from #243; the note on #244 ran the base script, so the first streamed note is one on a PR after #244) on Gemini 3.1 Flash-Lite, and a `· deep` run at 18 s. Open: a real cut has not been seen live yet (needs a diff that pushes a free hop past 80% of 32,000); Groq's note quality is unmeasured and the ledger's per-hop scores decide its place. Next: R2d agent-author awareness, R2a name check before any branding. |
| 2026-10-04 | **Hare, third pass: the ledger is Hare's.** #254 took Hare Bot back out of the ledger (#252, #253 had put it there for one night's measurement): Hare and Hare Bot are different products on different platforms, same intent only, and a Hare user elsewhere has no Grok Bot. The comparison is `scripts/compare_reviewers.py`, repo-local, run by hand, writing `docs/reviewer-comparison.md`. What the clean ledger then said: of 82 notes only 23 found anything; laguna answered 18 times on OpenRouter and found nothing, nex-n2.5 24 times and nothing, while Groq found something on 10 of 10 and Gemini on 3 of 3. #255 moved the catalog to match (laguna off OpenRouter, last on Nous; Space Bunny first on Nous and second on OpenRouter for its last free day, dropped on the next pass). #256 counted the runs where no hop answered at all, which were invisible: 138 across 114 PRs. That is the number for the days lost to non-API trouble. Also fixed: the rules-block wording #250 hand-corrected in HARE.md was not in the script, so each Sunday run would have flipped it back. Checked: Hare cannot trigger herself (reviews are `pull_request_review`, which hare.yml does not listen to; `issue_comment` excludes the App and github-actions). Open: the weekly ledger PR is pushed with `GITHUB_TOKEN`, so it fires no CI and no Hare; merging it needs a human. Fixing that with the App token would make Hare review her own chore PR, which is the owner's call. |
| 2026-10-04 | **Hare, fourth pass: the loop closes.** #258 put the slow hops first (OpenRouter, Nous, then Groq, Gemini, Zen): owner's call, since the fast hops answer in seconds and missed what a slower reviewer caught; the ledger cannot rank hops yet because its notes predate the day's fixes. #259 was the first weekly ledger PR; it said 0 of 6 reals fixed, which was false, so #261 added fates: `/hare fate <path:line> fixed|wrong|wontfix <why>` is the owner's word and beats threads and Since lines, a PR closed unmerged drops its open findings, and the hit rate names judged, wrong, wontfix and dropped (live: 3 of 6). #262 then #265 settled the weekly run: its body says it is automated with no model, it asks Hare by dispatch on `GITHUB_TOKEN`, and it merges unless Hare finds a real problem; the App-token push from #262 was reversed before its first run, because a reviewer should not need write access to code. #263: the Models table's Purpose cell says what work the model did, not `AI wrote it`. #264: every note carries a Verdict, Ship or Hold from CI and real findings, then the model's own case. #266: one-click fixes pinned by their text, up to 8 lines, dropped if they would not parse. #267: every note ends with a collapsed how-to-answer fold written by the Action, and the prompt and HARE.md know the whole loop. #268: CI is read again just before posting, so the Verdict is not always 'CI not done'. Open: Hare has flagged an Action-script `print` as a P4.6 breach twice (#233, #268); marked wontfix, owner to confirm. |
| 2026-10-05 | **Hare, fifth pass: asked, answered, measured.** CodeRabbit's three findings on #269 (read only after merging) were fixed in #275 with a streamed, capped log read and a test that drives the real `_hare_once`; Hare Bot's endless-line catch and Hare's line-split point went in too. #277: `/hare` commands parsed only as `@hare` and an empty ask on a reviewed commit was skipped, so re-asking never worked; every command now runs. #274: when CI finishes after the note, a `workflow_run` job brings the note's CI line, Verdict and log tail up to date (no model call); #269 reads CI once, right before posting, and says Wait while it runs. #272: a one-click fix that changes a function's parameters gets no button. #278 and #279: the owner's rules in HARE.md (tests run real code, bounded reads, no stale copies, one read path, doctor reads only, honest over clever, CI scripts may print). #280: Space Bunny off OpenRouter and Nous. #281: `hare-eval`, old PRs with known answers per provider, thinking off and on (run by hand; first run pending). #282: a command gets 🐇, or 🐢 for thinking, at once, and the note quotes the request; a concurrency bug that would have let that comment cancel its own command was caught in review and fixed, and the flow was tested live on #283. #283: Re-run on Hare's check reviews again. #284: a model that dies mid-answer keeps the findings it finished, and if every model dies the salvage is posted. Also: #271 and #273, the F18 input (downloads are mostly release-day fetches, U8's first suspect the MCP registry fan-out our own release job starts). Process: every PR's Hare note is scored and its findings fated; a merge waits until every `/hare`, `@copilot` and `@coderabbit` request on the PR has answered (missed once, on #284). |
| 2026-10-05 | **Hare, sixth pass: the graph.** #287: the codebase graph, v1. Hare reads the names a diff changes and the code files it changes, finds their uses in the trusted base checkout (text only, never run), ranks them code, then workflows and config, then docs, and fills each hop's own budget (Groq 4k, Gemini 40k, the rest 20k); a small workflow that names a changed file goes in whole. Replayed on #282, an OpenRouter hop now sees hare.yml's `cancel-in-progress`, the line that 2-score miss needed. CodeRabbit's three (declarations in other languages, caps by walk order, truncated hunks) were fixed before merge. #291: the eval gives each case a worktree at its base and runs graphs off and on; #292: the note says how much of the graph the model saw. #286: the eval waits out 429s, stops on a spent daily quota, keeps a 240-minute deadline, and counts no answer as no answer; #295: it prefers its own keys, because a long run on the shared keys starved a live `/hare deep`. #288: slow hops leave 150 s for Groq and Gemini (that `/hare deep` had posted nothing). #290: Inkling off OpenRouter's list (its free endpoint serves only agentic harnesses). #289 and #293: HARE.md says line length is the formatter's, the prompt reviews any repo, and searchts's own idea of real lives in its HARE.md. #294: HARE.md is rules only, how Hare works is docs/hare.md, and the learned block survives the 8k cap. Baseline eval (no graph) dispatched 09:30; the graph comparison runs next. R2a: "Hare" is also a systems language (harelang.org) and Leveret is a hare-themed review bot; naming is the owner's call before R2e. |
