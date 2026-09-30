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
- [ ] **P3.7c** Run the walled suite from a residential / home IP and **commit the real pass rate** into `docs/scorecard.md` (even if low). Suite exists; numbers still say not-yet-measured. Honest number > marketing claim. **Gate for Show HN / loud "reads walls" posts.** **Revisit:** before the next distribution push after **F22**.
- [x] **P3.7b PLACEHOLDER_RESTORE_INCOMPLETE
