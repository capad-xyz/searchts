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
| | | | | |
