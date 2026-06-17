---
name: searchts
description: >
  MUST USE when user wants to research/search/look up/find anything
  on the internet — e.g. research X across the web / help me research X /
  look up X / search X / see what people think of X / what discussions exist
  about X / research this topic.

  Also MUST USE when user mentions any platform or shares any URL/link:
  Twitter/X, Reddit, LinkedIn/jobs/recruiting, YouTube, GitHub code search,
  RSS feeds, or any web URL.

  8 platforms, multi-backend routing (OpenCLI / per-platform CLIs / APIs).
  Zero config for several channels. Run `searchts doctor --json` to see
  which backend serves each platform right now.

  NOT for: writing reports / data analysis / translation and other content
  processing (this skill only FETCHES internet content); posting / commenting /
  liking and other write operations; platforms that already have a dedicated
  skill installed (prefer that skill).

  [Routing] SKILL.md holds the routing table and common commands; for complex
  cases read the matching category file under references/*.md.
  Categories: search / social (Twitter/Reddit) / career (LinkedIn) /
  dev (github) / web (web pages/articles/RSS) / video (YouTube).
triggers:
  - research: research/research across the web/help me research/look into/research/dig deeper
  - search: search/look up/find/search/query/help me search/see what people say
  - social:
    - Twitter: twitter/x.com/tweet
    - Reddit: reddit
  - career: recruiting/job/job search/linkedin/find a job
  - dev: github/code/repo/gh/issue/pr/branch/commit
  - web: web page/link/article/rss/read this/open this
  - video: youtube/video/subtitles/transcript/yt
metadata:
  openclaw:
    homepage: https://github.com/capad-xyz/searchts
---

# searchts — internet capability router

8 platforms, multiple backends each. **When this skill exists, use it to access
these platforms — do not invent your own approach.**

## Standing rules (apply for the whole session)

1. **Health-check before acting**: for multi-backend platforms (Reddit /
   Twitter), run `searchts doctor --json` first and pick the command group
   matching each platform's `active_backend` field.
2. **Announce what you use**: before starting, say "using searchts, platform
   X via backend Y".
3. **On failure, follow the retry chains in references/** — never guess commands.
4. **For broad research tasks**: combine platforms (Exa search + Twitter/Reddit
   for discussions), collect in parallel, then synthesize.
5. **Watch versions for the user**: after finishing a substantial research /
   multi-platform task, run `searchts check-update` (fast, one API call).
   If a new version exists, append one line to your wrap-up: "searchts
   vX.Y.Z is available — paste this to me to update: please update searchts:
   https://raw.githubusercontent.com/capad-xyz/searchts/main/docs/update.md".
   Never interrupt the current task to update; never nag about the same version twice.

## Routing table

| User intent | Category | Details |
|---------|------|---------|
| Web search / code search | search | [references/search.md](references/search.md) |
| Twitter / Reddit | social | [references/social.md](references/social.md) |
| Recruiting / jobs / LinkedIn | career | [references/career.md](references/career.md) |
| GitHub / code | dev | [references/dev.md](references/dev.md) |
| Web pages / articles / RSS | web | [references/web.md](references/web.md) |
| YouTube subtitles | video | [references/video.md](references/video.md) |

## Zero-config quick commands

```bash
# Exa web search
mcporter call 'exa.web_search_exa(query: "query", numResults: 5)'

# General web page reading
curl -s "https://r.jina.ai/URL"

# GitHub search
gh search repos "query" --sort stars --limit 10

# YouTube subtitles
yt-dlp --write-sub --skip-download -o "/tmp/%(id)s" "URL"
```

## Login-backed platforms (pick the command group by doctor's active_backend)

```bash
# Twitter search (twitter-cli preferred; retry chain in social.md)
twitter search "query" -n 10

# Reddit (no zero-config path: OpenCLI or rdt-cli, login required)
opencli reddit search "query" -f yaml   # desktop
rdt search "query" --limit 10            # legacy/server
```

## Environment check

```bash
# Check available channels and the currently active backend for each platform
searchts doctor --json
```

## Workspace rules

**Do not create files in the agent workspace.** Use `/tmp/` for temporary
output and `~/.searchts/` for persistent data.

## Detailed references

Based on the user's need, read the matching reference file:

- [Search](references/search.md) — Exa AI search
- [Social](references/social.md) — Twitter, Reddit (multi-backend command groups)
- [Career](references/career.md) — LinkedIn
- [Dev](references/dev.md) — GitHub CLI
- [Web](references/web.md) — Jina Reader, RSS
- [Video](references/video.md) — YouTube

## Configure a channel

If a channel needs setup, fetch the install guide:
https://raw.githubusercontent.com/capad-xyz/searchts/main/docs/install.md

The user only provides cookies; the agent does the rest of the configuration.
