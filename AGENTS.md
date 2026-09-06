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

**Name:** `Hare` (always). Display: 🐇‍❄️. Machine token for hourly jobs / remote Grok: `searchts-r1-review`.

The agent that **wrote** the PR does not rubber-stamp it. A **second** agent is Hare.

Hare **must** post a comment on the GitHub PR (`gh pr comment` / review API). Local chat is not enough — remote Grok and the ChatGPT hourly matcher only see GitHub.

First line of the comment **exactly**:

```
<!-- searchts-r1-review -->
```

Then:

```markdown
## 🐇‍❄️ Hare — R1 review

| | |
|---|---|
| **Name** | 🐇‍❄️ Hare |
| **Purpose** | Review and report. Do not fix unless asked. |
| **Model** | <exact model> |
| **Effort** | low / medium / high |

| Sev | File:line | Issue | Fix? |
|---|---|---|---|
| real / skip | … | one sentence | yes / no / later |
```

**Real:** wrong behavior, fail-loud lie, ticks on stdout, MCP break, test that cannot fail, scope creep.

**Skip:** docstring coverage %, Rich vs stderr, test `-> None`, style.

Do not push fixes unless asked (`fix the real rows`). Do not use any other reviewer display name.

## Commits / PRs

- `type(scope): message`. PRs are squash-merged; the title becomes the `main` commit.
- Co-author trailer: exact model, agent, effort.
- Never hand-edit version numbers. `docs` / `chore` / `test` do not cut a PyPI release.
- New branch, PR to `main`, never push to `main`.
