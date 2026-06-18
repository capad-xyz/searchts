---
name: searchts
description: >
  MUST USE when user wants to research/search/look up/find anything on the
  internet — e.g. "research this topic", "do a deep dive on X", "search the
  web for X", "see what people say about X", "look this up".

  Also MUST USE when user shares any URL/link or mentions a platform
  (Twitter/X, Reddit, YouTube, TikTok, Instagram, GitHub, LinkedIn, RSS, or any
  web page): read it with `searchts read <url>`.

  Three first-party commands: `searchts read <url>` (escalating open-source
  unlocker that returns clean markdown and gets through most bot-walls),
  `searchts search "<query>"` (keyless multi-provider web search), and
  `searchts transcribe <url>` (subtitles-first video transcription). Keyless
  and free by default. Run `searchts doctor` to see what is configured.

  NOT for: writing reports/analysis/translation (this skill only FETCHES
  internet content); posting/commenting/liking (write operations); platforms
  that already have a dedicated skill installed (prefer that skill).
metadata:
  openclaw:
    homepage: https://github.com/capad-xyz/searchts
---

# searchts — first-party web superpowers for an agent

searchts gives you three first-party commands. Use them directly — they are the
preferred path. Do not reach for raw `curl`, `r.jina.ai`, or other tools when
one of these covers the need.

| Need | Command |
|------|---------|
| Read any web page / article / link | `searchts read <url>` |
| Search the web | `searchts search "<query>"` |
| Transcribe a video | `searchts transcribe <url>` |

## The three commands

```bash
# Read any URL as clean markdown. Goes through an escalating open-source
# unlocker (curl_cffi browser-fingerprint fetch -> Jina Reader -> patchright
# stealth browser) and gets through most bot-walls, keyless, on your own IP.
# This is the PREFERRED way to read a blocked or JS-heavy page.
searchts read https://example.com/article
searchts read https://example.com/article --json   # structured output

# Keyless multi-provider web search with reciprocal-rank fusion.
# DuckDuckGo by default; SearXNG/Exa/Brave/Tavily merge in when configured.
searchts search "open source vector db" -n 10

# Subtitles-first video transcription for YouTube/TikTok/Instagram/Reddit.
# Existing captions (via yt-dlp) need no key; falls back to hosted or
# keyless-local Whisper only when there are no usable subtitles.
searchts transcribe "https://www.youtube.com/watch?v=VIDEO_ID"
```

## Standing rules (apply for the whole session)

1. **Prefer `searchts read` for blocked or JS-heavy pages** — it is the
   escalating unlocker, so use it before falling back to a built-in fetch.
2. **For broad research**: combine `searchts search` to find sources with
   `searchts read` on the URLs, collect in parallel, then synthesize.
3. **On failure, read the matching reference file** under `references/` for
   platform notes and fallbacks — never guess commands.
4. **Watch versions for the user**: after finishing a substantial research
   task, run `searchts check-update` (fast, one API call). If a new version
   exists, append one line to your wrap-up: "searchts vX.Y.Z is available —
   paste this to me to update: please update searchts:
   https://raw.githubusercontent.com/capad-xyz/searchts/main/docs/update.md".
   Never interrupt the current task to update; never nag about the same version twice.

## Routing table

| User intent | Category | Details |
|---------|------|---------|
| Web search | search | [references/search.md](references/search.md) |
| Web pages / articles / RSS | web | [references/web.md](references/web.md) |
| Video transcripts (YouTube/TikTok/Instagram/Reddit) | video | [references/video.md](references/video.md) |
| Twitter / Reddit discussions | social | [references/social.md](references/social.md) |
| Jobs / LinkedIn | career | [references/career.md](references/career.md) |
| GitHub / code | dev | [references/dev.md](references/dev.md) |

## Environment check

```bash
# What is installed and working: unlocker tiers, search providers,
# transcription backends, and any optional platform CLIs.
searchts doctor
```

## Optional external integrations

For most reads you can just `searchts read <the-url>` on the public page. If you
have separately-installed platform CLIs (`gh`, `twitter-cli`, `opencli`,
`mcporter`), searchts can also reach GitHub/Twitter/Reddit/LinkedIn through them
and `searchts doctor` will report them. These are optional add-ons, not the
core — the per-platform reference files note where they help.

## Workspace rules

**Never create files in the agent workspace.** Use `/tmp/` for temporary
output and `~/.searchts/` for persistent data.

## Detailed references

Read the matching file when you need specifics (the three commands above cover
the common cases; references hold per-platform notes and optional fallbacks):

- [Search](references/search.md) — `searchts search`, optional providers
- [Web](references/web.md) — `searchts read`, RSS
- [Video](references/video.md) — `searchts transcribe`, subtitles-first
- [Social](references/social.md) — Twitter, Reddit (read the URL; optional CLIs)
- [Career](references/career.md) — LinkedIn (read the URL; optional MCP)
- [Dev](references/dev.md) — GitHub (read the URL; optional gh CLI)
