# AGENTS.md

Standing rules for anyone **changing** this repo (Cursor, Codex, Claude, Grok, cheap-scouts).

This is **not** a skill. Skills (`SKILL.md`) are how to *use* searchts (`read_url`). This file is how to *change* it.

- Product / order of work: [`PLAN.md`](PLAN.md)
- Commands and Python conventions: [`CLAUDE.md`](CLAUDE.md)

## Identity

Free, open-source, **keyless** web layer for agents. Fetch a URL or admit you can't. Won by reliability and being easy to reach for, not by feature count.

## Do not violate

1. **One read path** — CLI and MCP call `unlocker.fetch`. Channels are doctor probes only. No `if host==reddit` router.
2. **Fail loud** — thin, challenge, login-wall, or Playwright "page is navigating" is an error unless the caller opts into thin. Do not return half-HTML as a pass.
3. **P4.6** — work that can sit >1s ticks on **stderr**. Never stdout. Never the MCP protocol. Plain stderr, not Rich, not loguru (`-v` is for loguru).
4. **No connector framework** (**N4**). Share extractors stay fail-open modules. Known-host JSON (F5b) is the same pattern, not a plugin system.
5. **Out of scope** unless the PR *is* that PLAN id: Solari (**F14**), HTTP MCP (**F9**), cookies-from-browser (**F7**), paid proxies (**N1**), "beat Reddit."

## R1 — 🐇‍❄️ Hare (you are CodeRabbit now)

**Name:** `Hare` (always). Display: 🐇‍❄️. Machine token for hourly jobs / orchestrator chat: `searchts-r1-review`.

The agent that **wrote** the PR does not rubber-stamp it. A **second** agent is Hare.

**Orchestrator** = whoever is running the loop (dispatch, leftover finish, merge). Not a vendor name. Grok, Claude, Codex, a local CLI — if they are the orchestrator this turn, they are not Hare.

**Who is Hare:** a **cheap-scout** (free catalog id on this host), **not** the orchestrator. Writer model ≠ Hare model. If the orchestrator also touched the PR (leftover finish after a scout died), they still are not Hare — spawn a different cheap id.

**Orchestrator holds merge.** The orchestrator is Hare only when every cheap path is dead (429 / 500 / no credits). The **PR comment** must then say that under **Model** / **Purpose** (`cheap-scout unavailable: …`).

**Trigger (until R1c):** a remote push does **not** run Hare. The agent that opened/pushed the PR posts a Conversation comment whose first line is `<!-- searchts-r1-needed -->` (PR URL + “spawn Hare”). Hourly matcher / human then runs a **different cheap-scout**. Merge bar: `<!-- searchts-r1-review -->` exists. **R1b/R1c/F15** parked — PLAN.md. R1c when built: Action + Zen/Nous free; 429 → this nag.

Hare posts **two** GitHub surfaces (CodeRabbit-shaped). Local chat is not enough.

1. **PR conversation comment** (`gh pr comment`). First line **exactly**:

```
<!-- searchts-r1-review -->
```

Then the table below. **Intent:** hold / ship. If hold, one sentence vs PLAN. Hourly matcher + orchestrator chat look here.

2. **Inline on Files changed — real *and* skip.** Submit a review on the head SHA whose `comments[]` are `{path, line, side: RIGHT, body}` on lines that exist in `gh pr diff`. Invented lines 422 → table only.

   Every bubble body starts **exactly** like this (so it does not read as the PR author talking):

```
<!-- searchts-r1-review -->
🐇❄ Hare · automated R1 · not the PR author
**skip** — <one sentence>
```

   Use `**real**` instead of `**skip**` when it is real. No scores. No first person.

3. **Skip never holds merge.** Nits stay on the line. Applying a minority of them is expected. Intent = **hold** only if there is a **real** row.

The review may have an empty body if the issue comment already carries the table. Do not skip (1). Zero rows → no bubbles (nothing to pin).




```markdown
## 🐇‍❄️ Hare — R1 review

| | |
|---|---|
| **Name** | 🐇‍❄️ Hare |
| **Purpose** | Review and report. Do not fix unless asked. |
| **Model** | <exact model> |
| **Effort** | low / medium / high |
| **Intent** | hold / ship |

| Sev | File:line | Issue | Fix? |
|---|---|---|---|
| real / skip | … | one sentence | yes / no / later |
```

**Real:** wrong behavior, fail-loud lie, ticks on stdout, MCP break, test that cannot fail, scope creep, **PLAN-id intent miss** (the PR did the narrow prompt, not the product).

**Skip:** docstring coverage %, Rich vs stderr, test `-> None`, style. Already-fixed pre-push bugs are not a review.

Do not push fixes unless asked (`fix the real rows`). Do not use any other reviewer display name.

## Commits / PRs

- `type(scope): message`. PRs are squash-merged; the title becomes the `main` commit.
- Co-author trailer: exact model, agent, effort.
- Never hand-edit version numbers. `docs` / `chore` / `test` do not cut a PyPI release.
- New branch, PR to `main`, never push to `main`.
