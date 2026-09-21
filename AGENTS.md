# AGENTS.md

Standing rules for anyone **changing** this repo (Cursor, Codex, Claude, Grok, cheap-scouts).

This is **not** a skill. Skills (`SKILL.md`) are how to *use* searchts (`read_url`). This file is how to *change* it.

- Product / order of work: [`PLAN.md`](PLAN.md)
- Commands and Python conventions: [`CLAUDE.md`](CLAUDE.md)
- Who is who: [`NAMES.md`](NAMES.md)

## Identity

Free, open-source, **keyless** web layer for agents. Fetch a URL or admit you can't. Won by reliability and being easy to reach for, not by feature count.

## Do not violate

1. **One read path** — CLI and MCP call `unlocker.fetch`. Channels are doctor probes only. No `if host==reddit` router.
2. **Fail loud** — thin, challenge, login-wall, or Playwright "page is navigating" is an error unless the caller opts into thin. Do not return half-HTML as a pass.
3. **P4.6** — work that can sit >1s ticks on **stderr**. Never stdout. Never the MCP protocol. Plain stderr, not Rich, not loguru (`-v` is for loguru).
4. **No connector framework** (**N4**). Share extractors stay fail-open modules. Known-host JSON (F5b) is the same pattern, not a plugin system.
5. **Out of scope** unless the PR *is* that PLAN id: Solari (**F14**), hosted MCP (**N2**), cookies inside `read_url` (**F7** is transcribe-only), paid proxies (**N1**), "beat Reddit."

## R1 — Hare (`searchts-hare[bot]`)

GitHub shows the bot. Do not also print **Name** / a Hare heading in the body.

The agent that **wrote** the PR does not rubber-stamp it. Hare is the **R1c Action**, author `searchts-hare[bot]`.

**Orchestrator** = whoever is running the loop (dispatch, leftover finish, merge). Not a vendor name. If they are the orchestrator this turn, they are not Hare.

**Who is Hare:** the Action (`scripts/hare_r1.py`). Not the orchestrator. Not a laptop cheap-scout. Writer model ≠ Hare model.

**Orchestrator holds merge.** Do not run a review in-session as the user.

**Voice:** Emojis ok. **No em dashes** (U+2014). Use a colon, semicolon, or ASCII hyphen.

**Spawn (local or remote): this is the whole paste.** Comment `/hare` on the PR. The Action runs as `searchts-hare[bot]`. Do **not** `gh pr comment` a fake review as yourself. Do **not** spawn a cheap-scout named Hare.

```
gh pr comment <n> --body '/hare'
```

**Trigger (R1c):** Action `hare / r1` on `opened` / `synchronize` / `/hare` (same-repo PRs). Brain: Nous then OpenRouter then Zen. Fail -> nag `<!-- searchts-r1-needed -->` (issue comment). Do not post a fake review. Intent from Check Runs (red required job = hold). Fork PRs have no secrets: nag.

Hare posts **one GitHub Review** (CodeRabbit / Macroscope shaped). Author is the bot. Local chat is not enough.

1. **PR review** (`POST .../pulls/{n}/reviews`, event `COMMENT`). Body starts **exactly**:

```
<!-- searchts-r1-review -->
```

Then `**ship|hold** · \`model\` · effort low|medium|high` and the findings table. Shows on the Reviews tab as `searchts-hare[bot] reviewed`.

2. **Inline on Files changed: real *and* skip.** Same review's `comments[]` = `{path, line, side: RIGHT, body}` on lines that exist in `gh pr diff`. Invented lines 422: table only, no bubble.

   Bubble body starts **exactly**:

```
<!-- searchts-r1-review -->
**skip**: <one sentence>
```

   Use `**real**` instead of `**skip**` when it is real. No scores. No first person. No em dashes. No name line. The bot avatar is the identity.

3. **Skip never holds merge.** Nits stay on the line. Intent = **hold** only if there is a **real** row **or** a required check is red / still pending.

5. **Checks before Intent (#145):** `gh pr checks`. Red `ci / test` (or any required job) = **real**, Intent **hold**. Pending = wait or hold. Skipped `test-full` / `wheel-gate` on a PR is by design.

4. **Later SHA of the same PR (R1d):** post a **new Review**. Matcher = **latest** token. Do not edit the old table in place. Resolve threads whose finding is gone (outdated *and* not in the new diff). New bubbles only for what is still true. Do not delete old comments.

Zero rows → review body still posts (no inlines).

```markdown
<!-- searchts-r1-review -->

**ship** · `nous:poolside/laguna-s-2.1` · effort low

| Sev | File:line | Issue | Fix? |
|---|---|---|---|
| real / skip | … | one sentence | yes / no / later |
```

**Real:** wrong behavior, fail-loud lie, ticks on stdout, MCP break, test that cannot fail, scope creep, **PLAN-id intent miss**.

**Skip:** docstring coverage %, Rich vs stderr, test `-> None`, style.

Do not push fixes unless asked. Do not review as any other GitHub user.

## Commits / PRs

- `type(scope): message`. PRs are squash-merged; the title becomes the `main` commit.
- Co-author trailer: exact model, agent, effort.
- Never hand-edit version numbers. `docs` / `chore` / `test` do not cut a PyPI release.
- New branch, PR to `main`, never push to `main`.
