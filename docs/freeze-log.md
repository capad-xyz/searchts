# Freeze log

This is the diary of what landed. It is not a plan.

A plan says what is true now and what is next. This file says what already happened. The freeze log used to sit at the bottom of [`PLAN.md`](../PLAN.md), so every merge made the plan longer and agents treated old build notes as current rules. That is why it is here.

Append a new row under the right heading. Do not append it to either plan.

| You are writing | File |
|---|---|
| A searchts decision, a checklist item, parked work with a revisit | [`PLAN.md`](../PLAN.md) |
| Hare's behavior, the model list, cadence, what Hare should do next | [`docs/hare-next.md`](hare-next.md) |
| What merged, a build note, a dated "we did X" | this file |
| What a user sees in a release | [`CHANGELOG.md`](../CHANGELOG.md) |

## searchts

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
| 2026-09-08 | **F8b** copy: llms.txt + update.md + `_UPDATE_INSTRUCTIONS` match F8. Article was already live. F13 not in this PR. Dropped wrong `pipx inject searchts mcp` comment. |
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
| 2026-09-20 | **F9** localhost Streamable HTTP / SSE (`mcp serve --http`). Bind loopback only; hosted still **N2**. |
| 2026-09-20 | **F7** `transcribe --cookies-from-browser`. Opt-in, stderr, never `read`. YAML youtube-cookies still dead. |
| 2026-09-21 | **F17** subtitle salvage: no `en.*`; ignore-errors; keep a written `en.vtt` on 429. |
| 2026-09-21 | **P4.1** MCP `transcribe` tool. Error string; SSRF on URLs; cookies opt-in. |
| 2026-09-21 | **0.9.0** tagged + PyPI. **X6** posted (`@aadarsh_io`). Wikipedia demo URL. |
| 2026-09-21 | **F13** stderr update nudge, 24h cache, skip mcp serve / pipes. |
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
| 2026-10-02 | Correction: **0.13** is not ready. Live checks on Windows: Reddit thread and listing, Bing, Hashnode, Hacker News next page, uvx and pipx `install --browser`, MCP saves and `0.0.0.0` pass. Django has no dates (**F21d**), and pipx `doctor` lists its own launcher (**F11a**). The 2026-10-01 line saying **F23f** gives Django its dates is wrong. |
| 2026-10-02 | **0.13 holds** (#198 open) for **F11a** (doctor), #217 (Bing host, Windows device names) and **F22c** (pasted links). Django dates move to **F21**. |
| 2026-10-02 | Release split. **0.14** = **F21c** region map, **F21a**, **F21d** Django dates (**F21b** stays unscheduled until a fixture is saved), **F23b** pagination, **F23g** table lists, **F22b** `uninstall --browser`. **0.15** = **F23c** to **F23e** (scroll, expand, knobs) and **F24**. Replaces "0.14 = F23b to F23e" (2026-09-30). Not tied to a release: **LI2** after 0.13 is on PyPI, **P3.7c** before Show HN, **HareBot** after 0.13. |
| 2026-10-03 | **0.13.0** on PyPI (2026-10-02). **P3.7c** done: home run Smoke 12/12, Walled 2/7 (named), committed in #227. Booking failed there, so the earlier 559-char pass is not quoted. |
| 2026-10-03 | Reddit gaps go to **F5f** in **0.15** (cursor on **F23c**, more replies on **F23d**, walls, profiles, search). **0.14** stays non-Reddit. 0.15 is heavy: **F24** may slip to 0.16 (its line says "0.15 or later"). |
| 2026-10-03 | Distribution: version-free stories (**X8** thread, **LI2** motion video on real output), reach rules in section 5. Show HN after **F25** (0.13.1); the scorecard is #227. |
| 2026-10-03 | #227, #225, #228, #229 merged. **F25** ticked. Both Show HN gates are clear; **0.13.1** is a `fix:` release-please tag off #228, so the gate is really "0.13.1 on PyPI". README now says why searchts exists (#229) and six docs stopped calling example.com thin. |
| 2026-10-10 | Hare's operating record left this file. R1, R1c, cadence, the model list, HareBot, Laya, F15's detail, The diary of what landed, searchts and Hare, is docs/freeze-log.md. This file stays the searchts plan. |
| 2026-10-10 | DataDome is not the ceiling. A device-check, including one simple click, is the stealth rung. An image puzzle still stops. The address is a separate layer: no bought IP in that PR. **N1** is "not a default of the free CLI", not "never an exit" (**F18**). `docs/mcp.md` tunnel line is HTTPS-to-loopback only. |

## Hare

| Date | Change |
|---|---|
| 2026-09-06 | **R1** + `AGENTS.md`: writer ≠ reviewer when CodeRabbit is dark. Not a skill. |
| 2026-09-06 | **Hare**: R1 reviews are GitHub PR comments with `<!-- searchts-r1-review -->` (Name / Purpose / Model / Effort). Hourly matcher: that token. Display: 🐇‍❄️. |
| 2026-09-06 | **Hare ≠ orchestrator.** Cheap-scout reviews. Orchestrator merge-only unless cheap path is dead. Role, not a vendor — Grok/Claude/Codex can be either. #132 Hare comment was the orchestrator — that was the miss. |
| 2026-09-07 | **NAMES.md** — orchestrator (remote/local), Hare, cheap-scout. Local spawn is still a step; R1c only covers remote push. |
| 2026-09-09 | **Hare checks:** Intent ship only if required CI is green. #145 shipped while `ci / test` was red. F15: Check Runs API, not a paste. |
| 2026-09-09 | **R1c proving:** Action `hare / r1`. Secrets NOUS then OR then Zen (OpenCode). Ling Fin, not Muse (contributor trains). |
| 2026-09-09 | **R1c spec:** ghost real stays in table + holds; runner from base; pipeline not harness. Hourly GPT matcher ≠ Action. Quick vs deep parked (F15). F16 = remote harness box. |
| 2026-09-20 | **R1b** `searchts-hare[bot]` identity on main (#148). |
| 2026-09-20 | **R1c retry:** `/hare` comment + graceful `searchts-r1-needed`. |
| 2026-09-21 | **R1c hops:** Nous Laguna → Step 3.7 Flash; OR Laguna → Qwen3.8 27B → Nex-N2.5-Pro; Zen Ling Fin last hop. |
| 2026-10-01 | **R1c catalog:** Space Bunny on Nous / OR / Zen. Nous pins are `:free`. Dropped Nex (gone). LongCat 2.5 added. Ling Fin stays Zen last hop. |
| 2026-09-21 | **R1c cap:** LLM hop 60s; job 10 min backstop. |
| 2026-09-22 | **R1b/c:** review posts as GitHub Review (no name table). Local spawn = `/hare`. |
| 2026-09-22 | **R1c:** concurrency key includes `event_name` so CodeRabbit comments do not cancel the PR review. |
| 2026-09-22 | **R1d:** skip a second Review on the same SHA (`/hare` no-ops if one exists). |
| 2026-09-23 | **Hare** must say what the diff does. Nits are **skip** rows. An empty table is not a review. Skip still does not hold. |
| 2026-10-01 | **R1e / HareBot** decided, not built. Hare: supersede in-flight, quiet period, incremental after a finished note, one note, no blocking review, `/hare` and `@hare`, dead hop once. HareBot: template, posts as the user, routine or chat, no app key. Notion: https://app.notion.com/p/3ecbc1b020d3814abf05ed87a053bdad 0.13 still first. |
| 2026-10-04 | **Hare answers.** #235 (reasoning off on Nous, 300 s call, 600 s hop budget, brace-aware JSON reader, errors that name the cause), #236 (catalog from the live list and the live nag), #238 (thinking off vs on, measured), #239 (Models section names the slug), #240 (`/hare deep`). #234 closed with credit, #237 closed as a duplicate of #235 plus #238. Live reviews that night came from Groq gpt-oss-120b and Gemini 3.1 Flash-Lite. Cadence PR and `hare_local.py` next; **R2** (Hare as a product: format the Action enforces, findings ledger, rules in the repo) is the sitting after that. |
| 2026-10-04 | **Hare, second pass.** #242 (answer budget 32,000, owner's call), #243 (cadence: start at once, size the spend to the diff, cost line), #244 and #245 (wrap up at the limit: stream, seam, one continuation, repair), #246 (findings ledger, `/hare score`), #247 (Gemini is the fallback), #248 (`HARE.md`). **R1e**, **R2b**, **R2c** ticked. Live that night: cost lines in the fold (from #243; the note on #244 ran the base script, so the first streamed note is one on a PR after #244) on Gemini 3.1 Flash-Lite, and a `· deep` run at 18 s. Open: a real cut has not been seen live yet (needs a diff that pushes a free hop past 80% of 32,000); Groq's note quality is unmeasured and the ledger's per-hop scores decide its place. Next: R2d agent-author awareness, R2a name check before any branding. |
| 2026-10-04 | **Hare, third pass: the ledger is Hare's.** #254 took Hare Bot back out of the ledger (#252, #253 had put it there for one night's measurement): Hare and Hare Bot are different products on different platforms, same intent only, and a Hare user elsewhere has no Grok Bot. The comparison is `scripts/compare_reviewers.py`, repo-local, run by hand, writing `docs/reviewer-comparison.md`. What the clean ledger then said: of 82 notes only 23 found anything; laguna answered 18 times on OpenRouter and found nothing, nex-n2.5 24 times and nothing, while Groq found something on 10 of 10 and Gemini on 3 of 3. #255 moved the catalog to match (laguna off OpenRouter, last on Nous; Space Bunny first on Nous and second on OpenRouter for its last free day, dropped on the next pass). #256 counted the runs where no hop answered at all, which were invisible: 138 across 114 PRs. That is the number for the days lost to non-API trouble. Also fixed: the rules-block wording #250 hand-corrected in HARE.md was not in the script, so each Sunday run would have flipped it back. Checked: Hare cannot trigger herself (reviews are `pull_request_review`, which hare.yml does not listen to; `issue_comment` excludes the App and github-actions). Open: the weekly ledger PR is pushed with `GITHUB_TOKEN`, so it fires no CI and no Hare; merging it needs a human. Fixing that with the App token would make Hare review her own chore PR, which is the owner's call. |
| 2026-10-04 | **Hare, fourth pass: the loop closes.** #258 put the slow hops first (OpenRouter, Nous, then Groq, Gemini, Zen): owner's call, since the fast hops answer in seconds and missed what a slower reviewer caught; the ledger cannot rank hops yet because its notes predate the day's fixes. #259 was the first weekly ledger PR; it said 0 of 6 reals fixed, which was false, so #261 added fates: `/hare fate <path:line> fixed|wrong|wontfix <why>` is the owner's word and beats threads and Since lines, a PR closed unmerged drops its open findings, and the hit rate names judged, wrong, wontfix and dropped (live: 3 of 6). #262 then #265 settled the weekly run: its body says it is automated with no model, it asks Hare by dispatch on `GITHUB_TOKEN`, and it merges unless Hare finds a real problem; the App-token push from #262 was reversed before its first run, because a reviewer should not need write access to code. #263: the Models table's Purpose cell says what work the model did, not `AI wrote it`. #264: every note carries a Verdict, Ship or Hold from CI and real findings, then the model's own case. #266: one-click fixes pinned by their text, up to 8 lines, dropped if they would not parse. #267: every note ends with a collapsed how-to-answer fold written by the Action, and the prompt and HARE.md know the whole loop. #268: CI is read again just before posting, so the Verdict is not always 'CI not done'. Open: Hare has flagged an Action-script `print` as a P4.6 breach twice (#233, #268); marked wontfix, owner to confirm. |
| 2026-10-05 | **Hare, fifth pass: asked, answered, measured.** CodeRabbit's three findings on #269 (read only after merging) were fixed in #275 with a streamed, capped log read and a test that drives the real `_hare_once`; Hare Bot's endless-line catch and Hare's line-split point went in too. #277: `/hare` commands parsed only as `@hare` and an empty ask on a reviewed commit was skipped, so re-asking never worked; every command now runs. #274: when CI finishes after the note, a `workflow_run` job brings the note's CI line, Verdict and log tail up to date (no model call); #269 reads CI once, right before posting, and says Wait while it runs. #272: a one-click fix that changes a function's parameters gets no button. #278 and #279: the owner's rules in HARE.md (tests run real code, bounded reads, no stale copies, one read path, doctor reads only, honest over clever, CI scripts may print). #280: Space Bunny off OpenRouter and Nous. #281: `hare-eval`, old PRs with known answers per provider, thinking off and on (run by hand; first run pending). #282: a command gets 🐇, or 🐢 for thinking, at once, and the note quotes the request; a concurrency bug that would have let that comment cancel its own command was caught in review and fixed, and the flow was tested live on #283. #283: Re-run on Hare's check reviews again. #284: a model that dies mid-answer keeps the findings it finished, and if every model dies the salvage is posted. Also: #271 and #273, the F18 input (downloads are mostly release-day fetches, U8's first suspect the MCP registry fan-out our own release job starts). Process: every PR's Hare note is scored and its findings fated; a merge waits until every `/hare`, `@copilot` and `@coderabbit` request on the PR has answered (missed once, on #284). |
| 2026-10-05 | **Hare, sixth pass: the graph.** #287: the codebase graph, v1. Hare reads the names a diff changes and the code files it changes, finds their uses in the trusted base checkout (text only, never run), ranks them code, then workflows and config, then docs, and fills each hop's own budget (Groq 4k, Gemini 40k, the rest 20k); a small workflow that names a changed file goes in whole. Replayed on #282, an OpenRouter hop now sees hare.yml's `cancel-in-progress`, the line that 2-score miss needed. CodeRabbit's three (declarations in other languages, caps by walk order, truncated hunks) were fixed before merge. #291: the eval gives each case a worktree at its base and runs graphs off and on; #292: the note says how much of the graph the model saw. #286: the eval waits out 429s, stops on a spent daily quota, keeps a 240-minute deadline, and counts no answer as no answer; #295: it prefers its own keys, because a long run on the shared keys starved a live `/hare deep`. #288: slow hops leave 150 s for Groq and Gemini (that `/hare deep` had posted nothing). #290: Inkling off OpenRouter's list (its free endpoint serves only agentic harnesses). #289 and #293: HARE.md says line length is the formatter's, the prompt reviews any repo, and searchts's own idea of real lives in its HARE.md. #294: HARE.md is rules only, how Hare works is docs/hare.md, and the learned block survives the 8k cap. Baseline eval (no graph) dispatched 09:30; the graph comparison runs next. R2a: "Hare" is also a systems language (harelang.org) and Leveret is a hare-themed review bot; naming is the owner's call before R2e. |
