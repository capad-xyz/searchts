# Posts

What we say in public. Not the product plan.

Open work: [`PLAN.md`](../PLAN.md). What shipped: [`plan-shipped.md`](plan-shipped.md). The day-by-day log: [`freeze-log.md`](freeze-log.md).

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

## 5. Comms rules

| Beat | Trigger | Content |
|---|---|---|
| X1 | P0.7 merged | Scorecard was smoke; thin ≠ pass; smoke vs walled |
| X2 | P1 acceptance green | Demo: wall → `read_url` without being told (#22) |
| X3 | P3.1 + P3.2 | One before/after on a real wall; name the signal, not "we beat Vendor forever" |
| X4 | P2.3 + host smoke | One line: mcp 2.x no longer kills the server |

Article after P0 (better with one P1/P3 win). Draft free; publish when the repo matches the story.

**Reach rules (2026-10-03).** Posts were under 50 impressions on X and LinkedIn. Stories, not versions: one or two posts a week, each true for several releases; release notes stay in the changelog. Hook = a problem in one line, then real proof (a clip or a before/after), then the difference, then the install line; links in the first reply or comment. Real output only: styled screenshots of real runs are fine, generated terminal footage is not. Fifteen minutes a day of real replies on bigger accounts' posts about agents and MCP (a reply on a 1.1M account already got a DM). Post from `@aadarsh_io`; reserve a searchts handle, switch when there is an audience. Show HN when **F25** ships (0.13.1), on a weekday morning US time; P3.7c is done (#227).

Organic X / LinkedIn: draft here; publish from `@aadarsh_io` (and LI). **Distribution order (2026-09-30):** product is ahead of reach (few stars vs many releases). Next gains = first-run + proof + focus, not feature count. Loud campaigns lead with **fail-loud honesty** and **AI-chat share links** (proven, keyless). Reddit listing/parser is **proof of progress**, not the permanent homepage hook, and never "Reddit unlocked" (**N7**). **Show HN**: the gate is in the Reach rules above (2026-10-03). **F15** and **F16** are not searchts posts. **F18** is the hosted read in [`PLAN.md`](../PLAN.md); do not announce it until there is a price.

---
