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

<!-- BEGIN GENERATED COMMANDS (python -m searchts.helpgen --write) -->
## The commands

| Command | What it does |
|---|---|
| `searchts read` | Fetch a page as markdown, or fail and say why. |
| `searchts search` | Find URLs to read. A snippet is not the page. |
| `searchts transcribe` | A player page's words: captions, then Whisper. |
| `searchts grab` | Save the files a page uses: images, css, fonts. |
| `searchts get` | One file through the same unlocker. |
| `searchts mcp serve` | Run the MCP server (stdio default; --http for loopback). |
| `searchts mcp install` | Wire the MCP server into the agents on this machine. |
| `searchts skill install` | Write the slash command and the shared SKILL.md bundle. |
| `searchts doctor` | Which channels are installed, configured, working. |
| `searchts install` | One-shot installer; --system-deps to change things. |
| `searchts setup` | Walk through search, GitHub, Reddit, and Groq in one pass. |
| `searchts configure` | List the keys, set one, or copy cookies from a browser. |
| `searchts login` | Site logins: list, keep, kill, signin, purge-scratch, sweep, check. |
| `searchts uninstall` | Remove config, tokens and skill files. |
| `searchts update` | Update to the latest release (`upgrade` is the same command). |
| `searchts check-update` | Is there a newer version? |
| `searchts watch` | Quick health check for a scheduled task. |
| `searchts version` | Version. |
| `searchts help` | The command index, one command, or the machine-readable catalog. |

### Login verbs

| Command | What it does |
|---|---|
| `searchts login list` | Show kept sites, this session's copies, and leftover scratch. |
| `searchts login keep` | Keep one site's login in the searchts store. |
| `searchts login kill` | Delete searchts's copy of one site's login. |
| `searchts login signin` | Sign in once for a site in a browser searchts opens. |
| `searchts login purge-scratch` | Delete every scratch copy now. |
| `searchts login sweep` | Delete expired cookies now, offline. |
| `searchts login check` | Read one signed-in-only page with the saved cookies. |

### Flags

| Command | Flags |
|---|---|
| `searchts read` | `--backend`, `--json`, `--human`, `--pages`, `--items`, `--media`, `--expand`, `--scrub`, `--cookies-from-browser`, `--yes`, `--cookies`, `--cdp-port`, `--proxy`, `--proxy-trusted` |
| `searchts grab` | `--out`, `--kinds`, `--scripts`, `--read`, `--max`, `--tokens`, `--json` |
| `searchts search` | `-n`, `--json`, `--provider` |
| `searchts transcribe` | `--provider`, `--no-subtitles`, `-o`, `--cookies-from-browser` |
| `searchts get` | `-o` |

### MCP tools

| Tool | CLI command |
|---|---|
| `read_url` | `searchts read` |
| `web_search` | `searchts search` |
| `fetch_asset` | `searchts get` |
| `grab_site` | `searchts grab` |
| `get_status` | `searchts doctor` |
| `transcribe` | `searchts transcribe` |
| `login_status` | `searchts login list` |
| `login_signin` | `searchts login signin` |
| `login_check` | `searchts login check` |
| `login_kill` | `searchts login kill` |

MCP-only parameters and the deliberate CLI differences are listed in `docs/cli.md`. `web_search` defaults to 5 results; CLI `-n` defaults to 10. MCP has no `provider` parameter. `read_url` has no `next_url`; use the signed `next_cursor`. MCP results and `--json` output carry `update_available`.

### Exit codes

| Commands | Exit codes |
|---|---|
| `read`, `search`, `transcribe`, `grab`, `get` | `0` content or the requested output was returned; `1` the command failed; the reasons are on stderr; `2` bad usage, or a URL that cannot be read |
| `mcp`, `mcp install`, `skill`, `skill install`, `install`, `setup`, `configure`, `uninstall` | `0` the command finished; `1` the command failed; the reason is on stderr; `2` bad usage |
| `mcp serve` | `0` the server stopped normally; `1` the optional `mcp` extra is missing; `2` bad usage, or a non-loopback bind was refused |
| `doctor` | `0` the health report was printed; `2` bad usage |
| `login` | `0` the requested login action finished; `1` a cookie copy or sign-in failed; `2` bad usage; `3` consent is needed for a cookie copy |
| `login list` | `0` the audit was printed; `2` bad usage |
| `login keep` | `0` the login was kept; `1` the browser copy failed; `2` bad usage, or no browser was named; `3` consent is needed for the cookie copy |
| `login kill` | `0` searchts's copy was removed; `2` bad usage |
| `login signin` | `0` the sign-in browser closed; `1` the browser or cookie read failed; `2` bad usage |
| `login purge-scratch` | `0` the scratch copies were deleted; `2` bad usage |
| `login sweep` | `0` the sweep finished; `2` bad usage |
| `login check` | `0` logged in: the signed-in page was read without a login wall; `1` logged out: no live saved cookies, or the site showed its login page; `2` unknown: a captcha, block, network error, or no page could be chosen |
| `update` | `0` up to date, or the update finished; `1` the update failed; `2` this install shape cannot be updated |
| `check-update` | `0` the check finished (newer or current); `2` bad usage |
| `watch` | `0` the check finished; `2` bad usage |
| `version` | `0` the version was printed; `2` bad usage |
| `help` | `0` the help was printed; `2` unknown command path |

Run `searchts help --json` for the stable machine-readable catalog. Full flags, defaults and examples: `docs/cli.md`.
<!-- END GENERATED COMMANDS -->

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
5. **Watch versions for the user**: since 0.22.0 every `--json` result and
   every MCP result carries `update_available` when a newer release exists, so
   read it instead of making a separate call. `searchts check-update` is still
   there for a script. If a new version exists, append one line to your
   wrap-up: "searchts vX.Y.Z is available — `searchts update` installs it
   (`searchts upgrade` is the same command)." Never interrupt the current task
   to update; never nag about the same version twice.

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
