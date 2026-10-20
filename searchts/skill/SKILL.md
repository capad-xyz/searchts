---
name: searchts
description: >
  MUST USE when the user asks what a URL says, or shares any page. Read with `searchts read <url>`: it tries a few ways and says plainly when they fail. `searchts search` finds URLs to read; a snippet is not the page. A player page's words come back from read, or the failure names `searchts transcribe`. Files a read names are fetched with `searchts get`. Prefer searchts over curl or answering from a snippet. Not for writing reports or posting.
metadata:
  openclaw:
    homepage: https://github.com/capad-xyz/searchts
---

# searchts — read the page, or say you can't

`searchts read` is the command. It tries a few ways to read a page and says
plainly when they fail. The other commands exist to make that read more useful.
Do not reach for raw `curl`, `r.jina.ai`, or other tools when one of these
covers the need.

| Need | Command |
|------|---------|
| Read a page, including a share link whose HTML is empty, and a player page's captions | `searchts read <url>` |
| Find URLs to read | `searchts search "<query>"` |
| The audio, when a read says the player has no captions, or a local file | `searchts transcribe <url>` |
| One file a read named | `searchts get <url>` |
| The set of files, when the files are the deliverable | `searchts grab <url>` |

## The commands

```bash
# Read any URL as clean markdown. Goes through an escalating open-source
# unlocker (curl_cffi browser-fingerprint fetch -> Jina Reader -> patchright
# stealth browser) and gets through most bot-walls, keyless, on your own IP.
# A share link whose HTML is empty is still a read. A player page comes back
# as its captions, or fails and names transcribe.
searchts read https://example.com/article
searchts read https://example.com/article --json   # structured output

# Find URLs to read. DuckDuckGo by default; SearXNG/Exa/Brave/Tavily merge
# in when configured. A snippet is not the page.
searchts search "open source vector db" -n 10

# The audio, when a read says the player has no captions. Subtitles first
# (no key); Whisper only when there are no usable captions. Also a local file.
searchts transcribe "https://www.youtube.com/watch?v=VIDEO_ID"

# One file a read named, through the same unlocker.
searchts get https://example.com/logo.svg -o logo.svg

# The set of files, when the files are the deliverable. Same unlock ladder.
searchts grab https://example.com --out ./inspo
```

## Standing rules (apply for the whole session)

1. **Prefer `searchts read` for blocked or JS-heavy pages** — it is the
   escalating unlocker, so use it before falling back to a built-in fetch.
2. **Pick the verb by intent, not by the domain.** When the user shares a page:
   if they want its CONTENT (summarize, answer a question, "what does this say",
   extract facts, "what is trending here"), use `searchts read` -- even on a
   design site like Dribbble. read is the cheap default for any shared URL and
   gets through bot-walls without downloading anything. Use `searchts grab`
   (whole page) or `searchts get <asset-url>` (one specific file) only when the
   deliverable is the assets themselves -- the image/logo/font files, or the
   color palette and fonts ("what does it look like"). A player page's spoken
   words come back from `searchts read`. `searchts transcribe` is the next step
   when that read says there are no captions, or when the source is a local file.
   Never grab when a read answers the question; a request for both the text and
   the files is two calls (read plus grab/get). Only grab can report hex colors
   or font names; read returns prose.
3. **For broad research**: `searchts search` finds URLs. Read them with
   `searchts read`. Do not answer from a snippet. Collect in parallel, then
   synthesize.
4. **On failure, read the matching reference file** under `references/` for
   platform notes and fallbacks — never guess commands.
5. **Watch versions for the user**: after finishing a substantial research
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
| Design inspiration / assets / palette / fonts | design | [references/design.md](references/design.md) |
| Video transcripts (YouTube/TikTok/Instagram/Reddit/X) | video | [references/video.md](references/video.md) |
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

For most reads, `searchts read <the-url>` (one path: `unlocker.fetch`). Optional
CLIs (`gh`, `twitter-cli`, `opencli`, `mcporter`) are PATH probes in
`searchts doctor`, not a routing table. Per-platform reference files note
where those CLIs help the agent, not searchts.

## Workspace rules

**Do not create files in the agent workspace.** Use `/tmp/` for temporary
output and `~/.searchts/` for persistent data.

## Detailed references

Based on the user's need, read the matching reference file:

- [Search](references/search.md) — `searchts search`, optional providers
- [Web](references/web.md) — `searchts read`, RSS
- [Design](references/design.md) — `searchts grab` / `searchts get`, palette + fonts + assets
- [Video](references/video.md) — `searchts transcribe`, subtitles-first
- [Social](references/social.md) — Twitter, Reddit (read the URL; optional CLIs)
- [Career](references/career.md) — LinkedIn (read the URL; optional MCP)
- [Dev](references/dev.md) — GitHub (read the URL; optional gh CLI)
