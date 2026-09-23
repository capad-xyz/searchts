# U1 — #22 harness

Scripted check that an agent calls `read_url` on its own. Not a CI test. There is no Claude in GitHub Actions, and a stub that always passes would freeze a lie.

**P1.3** was one zCode session with the skill off. This is the repeatable version. The box stays open until a real session is pasted into the log below.

## Pass

MCP only. No project `SKILL.md`. If the host auto-loads a user skill, turn that off too. The prompt must not say searchts, `read_url`, or "use the tool."

Fixed URL: `https://www.linkedin.com/feed/`

Pass: `read_url` on that URL is the first or second tool call.

Fail: the agent answers from memory, uses curl / WebFetch / a browser, or calls `read_url` only after being told to.

A red page is fine. The gate is the call, not a successful read.

## Prompt

```text
Read this page and tell me what it says, in a few lines:
https://www.linkedin.com/feed/

Use whatever tools you already have. Do not install anything.
```

## Report

Host, model, and the tool calls in order. Quote the `read_url` arguments, or say it never happened. No fixes in the same turn.

## Log

| Date | Host | Model | Call order | Verdict |
|---|---|---|---|---|
| 2026-09-23 | Grok CLI, OCX. searchts MCP ready (`read_url` listed). P1.1 memory rule was in `user_rules` (`searchts:reach`). Not a clean MCP-only run. | `nous/poolside/laguna-s-2.1:free` | 1. `web_fetch` `https://www.linkedin.com/feed/` → HTTP 200, 1.9 KB login form. `read_url` never called. | **FAIL** |
| 2026-09-23 | Grok CLI restarted. `searchts v0.10.1` from home. Skill **disabled**. MCP `searchts` ready. | `nous/poolside/laguna-s-2.1:free` | 1. `wmux ping` (not running). 2. `web_fetch` the feed → HTTP 200, 1.4 KB login form. `read_url` never called. Asked after, it said searchts was an external CLI, not a tool it already had. | **FAIL** |
| 2026-09-23 | Grok CLI. Skill **disabled**. MCP ready. New `searchts:reach` text was in the rules (the model quoted it). Not MCP-description-only. | `nous/poolside/laguna-s-2.1:free` | 1. `read_url` `https://www.linkedin.com/feed/` → `login-wall`, Jina 403, stealth needs patchright. Then `web_fetch` (200 login form) and a web search. The summary was labeled as docs, not the page. | **PASS** of the new rule. Not a close of U1. |

The two fails used the old sentence: call `read_url` only after a 403 or a thin page. A 200 sign-in form never qualified.

The pass is the rewritten sentence. Laguna quoted it and called `read_url` before a plain fetch. The wall was named. U1 stays open: that paragraph was in the rules, so this is not a session with only the tool description.

Not this gate: OpenCode, skill **on**, called `searchts_read_url` first. curl_cffi said `login-wall`, Jina 403, stealth missing patchright. That is the skill path, and the wall was named honestly. It does not close U1.

A later OpenCode session, also skill **on** (`agent-reach` and `searchts`), showed `wmux ping`, Chrome page list, then `WebFetch` of the login form. No `read_url` result is in those frames. Not U1.
