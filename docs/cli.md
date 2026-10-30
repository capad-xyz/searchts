# searchts CLI reference

> Generated from the live argparse tree by `python -m searchts.helpgen --write`. Do not edit by hand.

searchts v0.24.3. Machine-readable: `searchts help --json` (`searchts.help.v1`). <!-- x-release-please-version -->

## Global flags

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |
| `--version` | Print the version and exit |

## Commands

### `read`

Fetch a page as markdown, or fail and say why.
Climbs the same three rungs the MCP server uses: curl_cffi with a browser TLS fingerprint, then the Jina reader relay, then a stealth browser. It stops at the first rung that returns real text. A wall, a login page, or a client-rendered shell is a failure, not a page.
- A player page comes back as its captions, or the failure names transcribe.
- A share link whose HTML is empty is still a read.
- On failure `--json` prints `{"url", "error": {kind, message, exit_code, attempts}}` on stdout; kind is bad_url, ssrf_refused, login_wall or read_failed.

```bash
searchts read <url> [--verbose] [--backend BACKEND] [--json] [--human] [--pages PAGES] [--items ITEMS] [--media MEDIA] [--expand] [--scrub] [--cookies-from-browser BROWSER] [--yes] [--cookies PATH] [--cdp-port PORT] [--proxy URL] [--proxy-trusted]
```

| Argument | Description |
|---|---|
| `url` | The URL to read |

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |
| `--backend` BACKEND | Force a single backend (e.g. curl_cffi, 'Jina Reader', stealth-browser) |
| `--json` | Print the result as JSON instead of raw text: url, final_url, fetched_at, backend, status, chars, text, next_url and more |
| `--human` | If no tier gets clean content, open a headful browser to clear it by hand |
| `--pages` PAGES | Follow the next page on the same site, curl only, up to this many (max 5) Default: `1`. |
| `--items` ITEMS | Keep following next pages, then scroll if the list only grows that way, until this many list rows (ceiling SEARCHTS_MAX_ITEMS, max 300) |
| `--media` MEDIA | How many image and video addresses the media note lists (default 4, ceiling 40). Does not download them; searchts grab saves the files. SEARCHTS_MAX_MEDIA or more.media in the config changes the default. |
| `--expand` | Open the text the page is holding back: closed <details> and buttons labelled read/show/see more, and a known host's own controls (a Reddit thread's 'more replies'). Off by default. Never follows a link, a form or a sign-in; a 'continue reading' paywall is named, not opened (ceiling SEARCHTS_MAX_EXPAND_CLICKS) |
| `--scrub` | Redact prompt-injection spans from the content (invisible-char stripping + indicator scanning always run regardless) |
| `--cookies-from-browser` BROWSER | Read YOUR browser's cookies for this site only (opt-in) Choices: zen, firefox, librewolf, waterfox, floorp, mullvad, vivaldi, chrome, edge, brave, opera, arc, chromium. |
| `--yes` | Approve copying cookies out of YOUR browser, this session only. Without it --cookies-from-browser is refused, because the copy is never silent. |
| `--cookies` PATH | Read a searchts-owned cookie file for this site only (opt-in) |
| `--cdp-port` PORT | Read this site's cookies from your localhost debugger port (opt-in) |
| `--proxy` URL | Route the read through a proxy (http/https/socks), e.g. socks5://127.0.0.1:7890. For blocks decided on your address, which no fingerprint can move. Falls back to the `proxy` config value. Omitted means your own IP, as before. |
| `--proxy-trusted` | Accept that a remote proxy operator can see the Cookie header |

Examples:

```bash
searchts read example.com
searchts read https://x.com/jack/status/20 --json
searchts read example.com --pages 3 --expand
```

| Exit | Meaning |
|---|---|
| `0` | the page was read |
| `1` | every rung failed (a wall, a login page, a network error) |
| `2` | bad usage, a malformed URL, or the SSRF guard refused the URL |

MCP: `read_url`.
MCP-only parameters: `cursor`, `page_items`.
CLI-only flags: `--human`, `--scrub`, `--backend`, `--json`.
- Same unlocker path as `searchts read`.
- The JSON has no `next_url`: a page-authored URL is not a safe next request. Use the signed `next_cursor`, or `searchts read --json` when a human wants the URL.
- `approve_cookie_copy` is CLI `--yes` for one call: set it only after the user said yes to a `cookies_from_browser` copy.

### `search`

Find URLs to read. A snippet is not the page.
Results are fused by rank across every provider that answers, so one provider having a bad day does not empty the list. A snippet is a pointer, not a page: read the URL before quoting it.

```bash
searchts search <query> [--verbose] [-n N] [--json] [--provider NAME]
```

| Argument | Description |
|---|---|
| `query` | The search query |

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |
| `-n` N | Maximum number of fused results to return (default: 10) Default: `10`. |
| `--json` | Print the list of result dicts as JSON instead of a numbered list |
| `--provider` NAME | Restrict to a provider (repeatable, or a comma-separated list); e.g. --provider duckduckgo --provider brave |

Examples:

```bash
searchts search "python asyncio timeout"
searchts search "stripe pricing" --provider duckduckgo -n 5
searchts search "rust 2026" --json
```

| Exit | Meaning |
|---|---|
| `0` | content or the requested output was returned |
| `1` | the command failed; the reasons are on stderr |
| `2` | bad usage, or a URL that cannot be read |

MCP: `web_search`.
CLI-only flags: `--provider`, `--json`.
- MCP default is max_results=5 (CLI `-n` default is 10).
- MCP has no `provider` parameter; the CLI does.

### `transcribe`

A player page's words: captions, then Whisper.
Captions come first and cost nothing. Audio goes to Groq, then OpenAI if a key is set, else whisper.cpp, which ships with searchts and runs locally with no key. Linux and Windows wheels are CPU builds; the macOS arm64 wheel ships Metal. Vulkan/CUDA wheels are a follow-up. A local file works the same way. The quantized small model (about 190 MB; --model turbo or base) downloads after approval: a terminal is asked, an agent passes --yes only after the user agreed. --json names the engine, model, device and detected language, and a cached newer release as `update_available`. --cleanup (temporary) removes the old faster-whisper fallback after showing what else uses it. Use --list-models to inspect the cache or --remove-model NAME --yes to remove one. --hint supplies names; --translate opts into English output (not supported by turbo). Use --provider local-fw to force the temporary faster-whisper fallback.

```bash
searchts transcribe [source] [--verbose] [--provider {auto,groq,openai,local,local-fw}] [--model {small,turbo,base}] [--hint WORDS] [--translate] [--yes] [--json] [--cleanup] [--list-models] [--remove-model {small,turbo,base}] [--dry-run] [--no-subtitles] [--output OUTPUT] [--cookies-from-browser BROWSER]
```

| Argument | Description |
|---|---|
| `[source]` | Audio/video URL or local file path |

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |
| `--provider` {auto,groq,openai,local,local-fw} | Audio transcription provider used when there are no subtitles (default: auto = hosted key if set, else keyless local whisper.cpp; `local` forces local, no API key; `local-fw` forces the temporary faster-whisper fallback) Choices: auto, groq, openai, local, local-fw. Default: `auto`. |
| `--model` {small,turbo,base} | Local whisper.cpp model (small q5_1, ~190 MB default; config whisper_model / SEARCHTS_WHISPER_MODEL). turbo is large-v3-turbo: most accurate, slowest on CPU Choices: small, turbo, base. |
| `--hint` WORDS | Words the audio contains, such as names from the page title, to bias local transcription toward them |
| `--translate` | Translate the speech to English (local engine; not with turbo). Default: transcribe in the spoken language |
| `--yes`, `-y` | Approve the one-time local model download (agents: only after the user said yes); with --cleanup, approve the removal |
| `--json` | Print searchts.transcribe.v1 JSON: the text plus which source, engine, model and device ran, and the language |
| `--cleanup` | Temporary: remove the faster-whisper fallback and its model cache. Shows what else uses them first, then asks |
| `--list-models` | List local whisper.cpp models, sizes, cache status and paths |
| `--remove-model` {small,turbo,base} | Remove a cached local model (requires --yes or a terminal yes) Choices: small, turbo, base. |
| `--dry-run` | With --cleanup: print the report only, remove nothing |
| `--no-subtitles` | Skip the video's existing captions and force audio transcription (captions otherwise come first and need no API key) Default: `True`. |
| `-o`, `--output` OUTPUT | Write transcript to a file instead of stdout |
| `--cookies-from-browser` BROWSER | Opt-in: pass this browser's cookies to yt-dlp. Accepts the browser names yt-dlp knows (chrome, chromium, firefox, edge, brave, opera, safari, vivaldi, whale); unlike read, the name is not checked against searchts's browser registry. Transcribe only. Never used by searchts read. |

Examples:

```bash
searchts transcribe https://www.youtube.com/watch?v=...
searchts transcribe talk.mp4 --provider local --model turbo
searchts transcribe https://www.instagram.com/reel/... --hint "Laurentius, Dark Souls"
searchts transcribe --list-models
searchts transcribe --remove-model small --yes
searchts transcribe --cleanup --dry-run
```

| Exit | Meaning |
|---|---|
| `0` | content or the requested output was returned |
| `1` | the command failed; the reasons are on stderr |
| `2` | bad usage, or a URL that cannot be read |

MCP: `transcribe`.
CLI-only flags: `-o`, `--json`, `--cleanup`, `--dry-run`, `--list-models`, `--remove-model`.
- `prefer_subtitles` mirrors CLI `--no-subtitles`.
- `cookies_from_browser` is passed to yt-dlp, same as the CLI flag.
- `yes` is CLI `--yes`: the user's approval to download the local model.
- A missing-model response is structured and names its size, source, cache path, and yes=true approval.
- The text ends with a `transcribed_by:` JSON line, the receipt CLI `--json` puts under `receipt`.
- Use provider=local-fw to force the temporary faster-whisper fallback.
- `--cleanup` (temporary faster-whisper removal) is CLI only.

### `grab`

Save the files a page uses: images, css, fonts.
Downloads images, icons, css, fonts and inline svg through the same unlocker, then extracts the palette, the fonts and the radius/shadow/ spacing values the page actually uses. Every URL is either saved, named as a failure, or listed as omitted with the reason, so a cap never truncates silently.

```bash
searchts grab <url> [--verbose] [--out OUT] [--kinds KINDS] [--scripts] [--read] [--max MAX_ASSETS] [--tokens MAX_TOKENS] [--json]
```

| Argument | Description |
|---|---|
| `url` | The page URL to grab |

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |
| `--out` OUT | Output directory (default: ./searchts-grab-<host>) |
| `--kinds` KINDS | Comma list of asset kinds to download (images,icons,css,fonts,svg,inline_svg,scripts) Default: `images,icons,css,fonts,svg,inline_svg`. |
| `--scripts` | Also download <script src> files |
| `--read` | Also save the page text as page.md |
| `--max` MAX_ASSETS | Maximum assets to download (default 120) Default: `120`. |
| `--tokens` MAX_TOKENS | Radius, shadow, and spacing values to keep (default 24, ceiling 200). The note names how many more a higher number returns. Default: `24`. |
| `--json` | Print the manifest JSON to stdout |

Examples:

```bash
searchts grab https://stripe.com --out stripe
searchts grab https://linear.app --kinds images,fonts
searchts grab https://example.com --tokens 60 --json
```

| Exit | Meaning |
|---|---|
| `0` | content or the requested output was returned |
| `1` | the command failed; the reasons are on stderr |
| `2` | bad usage, or a URL that cannot be read |

MCP: `grab_site`.
CLI-only flags: `--kinds`, `--scripts`, `--json`.
- `max_assets` mirrors CLI `--max`; `max_tokens` mirrors `--tokens`.
- MCP saves only inside the server working directory or $SEARCHTS_MCP_OUT_DIR.

### `get`

One file through the same unlocker.
Prints the saved path on stdout, so it pipes into anything.

```bash
searchts get <url> [--verbose] [--output OUTPUT]
```

| Argument | Description |
|---|---|
| `url` | The asset URL to download |

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |
| `-o`, `--output` OUTPUT | Output file or directory (default: filename from the URL, in the cwd) |

Examples:

```bash
searchts get https://example.com/logo.svg -o assets/
```

| Exit | Meaning |
|---|---|
| `0` | content or the requested output was returned |
| `1` | the command failed; the reasons are on stderr |
| `2` | bad usage, or a URL that cannot be read |

MCP: `fetch_asset`.
- MCP saves only inside the server working directory or $SEARCHTS_MCP_OUT_DIR, never to an absolute path.

### `mcp`

Run or wire up the searchts MCP server.
stdio by default. --http and --sse bind loopback only: there is no public URL, and that is on purpose.
- A bare `searchts mcp` prints the generated usage and exits 2.

```bash
searchts mcp {serve|install} [--verbose]
```

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |

Examples:

```bash
searchts mcp serve
searchts mcp install --client claude
```

| Exit | Meaning |
|---|---|
| `0` | the command finished |
| `1` | the command failed; the reason is on stderr |
| `2` | bad usage |

No MCP tool: parent verb for `mcp serve` / `mcp install`.
Subcommands: `mcp serve`, `mcp install`.

### `mcp serve`

Run the MCP server (stdio default; --http for loopback).
The server exposes the same read/search/download code as the CLI. stdio is what an agent host spawns; --http and --sse are for a custom connector on loopback only.

```bash
searchts mcp serve [--verbose] [--http] [--sse] [--host HOST] [--port PORT]
```

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |
| `--http` | Streamable HTTP on loopback (http://127.0.0.1:PORT/mcp). Not a public URL. |
| `--sse` | Legacy SSE on loopback (http://127.0.0.1:PORT/sse). Prefer --http. |
| `--host` HOST | Bind address for --http/--sse (loopback only; default 127.0.0.1) Default: `127.0.0.1`. |
| `--port` PORT | Port for --http/--sse (default 8765) Default: `8765`. |

Examples:

```bash
searchts mcp serve
searchts mcp serve --http --port 8765
```

| Exit | Meaning |
|---|---|
| `0` | the server stopped normally |
| `1` | the optional `mcp` extra is missing |
| `2` | bad usage, or a non-loopback bind was refused |

No MCP tool: this is the server itself; a tool for it would be the server.

### `mcp install`

Wire the MCP server into the agents on this machine.
Writes `searchts mcp serve` into each detected client's own config (Claude Code, Claude Desktop, Cursor, Codex, VS Code, Copilot, Gemini, OpenCode, Windsurf, Devin). It never creates a config for a client that is not installed and never touches a project file.
- --client json prints the mcpServers snippet and writes nothing.
- A config that does not parse, or already names a different command, is left alone.

```bash
searchts mcp install [--verbose] [--client {claude,cursor,json,desktop,codex,vscode,copilot,windsurf,devin,gemini,opencode}]
```

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |
| `--client` {claude,cursor,json,desktop,codex,vscode,copilot,windsurf,devin,gemini,opencode} | Write one client (default: every client already on this machine). json only prints the mcpServers snippet Choices: claude, cursor, json, desktop, codex, vscode, copilot, windsurf, devin, gemini, opencode. |

Examples:

```bash
searchts mcp install
searchts mcp install --client cursor
searchts mcp install --client json
```

| Exit | Meaning |
|---|---|
| `0` | the command finished |
| `1` | the command failed; the reason is on stderr |
| `2` | bad usage |

No MCP tool: writes client configs; the host does this once.

### `skill`

Manage agent skill registration.
`skill install` writes the Claude Code slash command and the shared SKILL.md bundle. The old `skill --install` / `--uninstall` flags still work for scripts; they are the legacy form of the same job.
- A bare `searchts skill` prints the generated usage and exits 2.

```bash
searchts skill {install} [--verbose] [--install] [--uninstall]
```

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |
| `--install` (legacy) | Install the SKILL.md bundle to agent skill directories |
| `--uninstall` (legacy) | Remove the SKILL.md bundle from agent skill directories |

Examples:

```bash
searchts skill install
searchts skill install --dir ~/.claude/commands
```

| Exit | Meaning |
|---|---|
| `0` | the command finished |
| `1` | the command failed; the reason is on stderr |
| `2` | bad usage |

No MCP tool: parent verb for `skill install`.
Subcommands: `skill install`.

### `skill install`

Write the slash command and the shared SKILL.md bundle.
Writes `searchts.md` into the commands directory (default ~/.claude/commands) and the SKILL.md bundle into the agent skill homes that exist. The slash command routes read, search, transcribe, login, grab and get.

```bash
searchts skill install [--verbose] [--dir DIR]
```

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |
| `--dir` DIR | Target commands directory (default: ~/.claude/commands) |

Examples:

```bash
searchts skill install
searchts skill install --dir ~/.config/opencode/commands
```

| Exit | Meaning |
|---|---|
| `0` | the command finished |
| `1` | the command failed; the reason is on stderr |
| `2` | bad usage |

No MCP tool: writes files on this machine for the host's slash command.

### `doctor`

Which channels are installed, configured, working.
Probes each optional channel. A tier-0 probe is a capability the reader can use; the CLIs are PATH checks, not a routing table.

```bash
searchts doctor [--verbose] [--json]
```

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |
| `--json` | Output machine-readable JSON instead of the text report |

Examples:

```bash
searchts doctor
searchts doctor --json
```

| Exit | Meaning |
|---|---|
| `0` | the health report was printed |
| `2` | bad usage |

MCP: `get_status`.
CLI-only flags: `--json`.
- The same health report `searchts doctor` prints.

### `install`

First-pass setup: one list, one approval; --system-deps for system packages.
Shows one list with sizes: Chromium for the stealth browser and the site tools (X, Reddit, LinkedIn, mcporter, GitHub), all checked by default. A terminal asks once; uncheck by id. Without a terminal nothing on the list is installed unless --yes is passed. --skip ids unchecks items. --dry-run --json prints the list as searchts.setup.v1. Site logins are not part of this approval. It also writes the agent skill files (~/.agents/skills/searchts, or each OpenClaw/Claude Code skills dir that exists) and the user-scope memory rule; both are listed up front, and --dry-run lists them and writes nothing. --browser installs only the stealth browser; --system-deps also installs system packages instead of printing the commands.
- --safe is a deprecated no-op; non-mutating is now the default.

```bash
searchts install [--verbose] [--env {local,server,auto}] [--proxy PROXY] [--system-deps] [--safe] [--dry-run] [--channels CHANNELS] [--browser] [--yes] [--skip IDS] [--json]
```

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |
| `--env` {local,server,auto} | Environment: local, server, or auto-detect Choices: local, server, auto. Default: `auto`. |
| `--proxy` PROXY | Network proxy saved for agents to export as HTTP(S)_PROXY in restricted networks (http://user:pass@ip:port) |
| `--system-deps`, `--apply` | Opt in to mutating the system (alias: --apply): install gh/Node.js, npm -g packages, apt sources, and yt-dlp config. Off by default (the keyless core needs none of this) — without it, install only prints the manual commands. |
| `--safe` (deprecated) | Deprecated no-op: safe (non-mutating) is now the default. Use --system-deps to opt in to system changes. |
| `--dry-run` | Show what would be done without making any changes |
| `--channels` CHANNELS | Comma-separated optional channels to install (twitter,reddit,opencli,linkedin,all) |
| `--browser` | Install Chromium for the stealth browser into this CLI's environment (patchright itself is already in the base install; same interpreter as the running searchts). Refuses ephemeral uvx. |
| `--yes`, `-y` | Approve the first-pass list without a prompt: Chromium and the site tools (X, Reddit, LinkedIn, mcporter, GitHub), minus any --skip. Without it and without a terminal, nothing on the list is installed |
| `--skip` IDS | Uncheck first-pass items, comma-separated: chromium,twitter,reddit,linkedin,mcporter,gh |
| `--json` | With --dry-run: print the first-pass list as searchts.setup.v1 JSON (sizes, installed state, approve command) and change nothing |

Examples:

```bash
searchts install
searchts install --yes --skip linkedin,mcporter
searchts install --dry-run --json
searchts install --browser
searchts install --system-deps --channels twitter,reddit
```

| Exit | Meaning |
|---|---|
| `0` | the command finished |
| `1` | the command failed; the reason is on stderr |
| `2` | bad usage |

No MCP tool: installing software is the user's act; the MCP server reports readiness instead.

### `setup`

Walk through search, GitHub, Reddit, and Groq in one pass.
Every prompt can be skipped with Enter. The summary says what was saved and what is still optional; it never installs a system package.

```bash
searchts setup [--verbose]
```

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |

Examples:

```bash
searchts setup
```

| Exit | Meaning |
|---|---|
| `0` | the command finished |
| `1` | the command failed; the reason is on stderr |
| `2` | bad usage |

No MCP tool: an interactive wizard needs a person at the terminal.

### `configure`

List the keys, set one, or copy cookies from a browser.
With no key it lists every key, its current source and whether it is set. With a key and a value it writes the key. --from-browser copies the platform cookies that browser holds.

```bash
searchts configure [key] [value...] [--verbose] [--from-browser BROWSER]
```

| Argument | Description |
|---|---|
| `[{proxy,github-token,groq-key,openai-key,twitter-cookies,youtube-cookies}]` | What to configure. Omit the key to list every key, its default, and set or unset. github-token and youtube-cookies are accepted so the refusal is discoverable, but are not stored: github-token -> export GITHUB_TOKEN/GH_TOKEN (or .env); youtube-cookies -> transcribe <url> --cookies-from-browser <browser> |
| `[value...]` | The value(s) to set |

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |
| `--from-browser` BROWSER | Auto-extract ALL platform cookies from browser (any supported browser: Zen, Firefox, Chrome, Vivaldi, Edge, Brave, Opera, Arc, ...) Choices: zen, firefox, librewolf, waterfox, floorp, mullvad, vivaldi, chrome, edge, brave, opera, arc, chromium. |

Examples:

```bash
searchts configure
searchts configure proxy http://user:pass@ip:port
searchts configure --from-browser firefox
```

| Exit | Meaning |
|---|---|
| `0` | the command finished |
| `1` | the command failed; the reason is on stderr |
| `2` | bad usage |

No MCP tool: keys are the user's; MCP reads only what is already configured.

### `login`

Site logins: list, status, keep, kill, signin, purge-scratch, sweep, check.
Nothing is copied out of your browser without --yes. A kept login stays on this machine: direct requests and a temporary local browser context can use it; the Jina relay never receives it. A bare `searchts login` is the same as `searchts login list`.

```bash
searchts login {list|status|keep|kill|signin|purge-scratch|sweep|check} [--verbose]
```

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |

Examples:

```bash
searchts login list
searchts login signin https://example.com
searchts login keep https://example.com --cookies-from-browser zen --yes
```

| Exit | Meaning |
|---|---|
| `0` | the requested login action finished |
| `1` | a cookie copy or sign-in failed |
| `2` | bad usage |
| `3` | consent is needed for a cookie copy |

No MCP tool: parent verb for the login tools and the CLI-only login verbs.
Subcommands: `login list`, `login status`, `login keep`, `login kill`, `login signin`, `login purge-scratch`, `login sweep`, `login check`.

### `login list`

Show kept sites, this session's copies, and leftover scratch.
Each kept site shows its live cookie count, whether it came from a browser or `login signin`, and its expiry (an upper bound, never a promise). No cookie value is printed.

```bash
searchts login list [--verbose]
```

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |

Examples:

```bash
searchts login list
```

| Exit | Meaning |
|---|---|
| `0` | the audit was printed |
| `2` | bad usage |

MCP: `login_status`.
MCP-only parameters: `url`.
- Same audit as `searchts login list`; never a cookie value.
- MCP-only `url` also reports which stored host the URL resolves to.

### `login status`

Show which stored host a URL's login resolves to.
An exact kept host wins. Otherwise the lookup can use a kept parent within the same registrable domain. The result names the stored host without exposing cookie values.

```bash
searchts login status <url> [--verbose]
```

| Argument | Description |
|---|---|
| `url` | The site to resolve against the store |

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |

Examples:

```bash
searchts login status https://www.example.com
searchts login status https://app.example.com
```

| Exit | Meaning |
|---|---|
| `0` | the resolution was printed |
| `2` | bad usage |

No MCP tool: the MCP `login_status` tool accepts `url` for the same lookup.

### `login keep`

Keep one site's login in the searchts store.
Copies only that site's cookies from the named browser, then keeps them. Copying is never silent: without a recorded yes for the site or --yes in this run, the command exits 3 and explains what it needs.

```bash
searchts login keep <url> [--verbose] [--cookies-from-browser BROWSER] [--yes]
```

| Argument | Description |
|---|---|
| `url` | The site whose login to keep |

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |
| `--cookies-from-browser` BROWSER | Copy from this browser, then keep the site (opt-in) Choices: zen, firefox, librewolf, waterfox, floorp, mullvad, vivaldi, chrome, edge, brave, opera, arc, chromium. |
| `--yes` | Approve copying this site's cookies and keep them in the searchts store |

Examples:

```bash
searchts login keep https://example.com --cookies-from-browser zen --yes
searchts login keep https://reddit.com --cookies-from-browser firefox
```

| Exit | Meaning |
|---|---|
| `0` | the login was kept |
| `1` | the browser copy failed |
| `2` | bad usage, or no browser was named |
| `3` | consent is needed for the cookie copy |

No MCP tool: MCP reaches the same login through `login_signin` or `read_url` + `cookies_from_browser`.

### `login kill`

Delete searchts's copy of one site's login.
Your own Firefox or Chrome cookies stay untouched unless --also-browser is passed, because those are yours.

```bash
searchts login kill <url> [--verbose] [--also-browser]
```

| Argument | Description |
|---|---|
| `url` | The site to forget |

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |
| `--also-browser` | Also delete that site's cookies in your own Firefox/Chrome. Off by default: those are yours, and searchts does not delete a login you did not ask it to. |

Examples:

```bash
searchts login kill https://example.com
searchts login kill https://example.com --also-browser
```

| Exit | Meaning |
|---|---|
| `0` | searchts's copy was removed |
| `2` | bad usage |

MCP: `login_kill`.
- `also_browser` mirrors CLI `--also-browser`.

### `login signin`

Sign in once for a site in a browser searchts opens.
The browser is searchts's own, not a copy of your profile. Signing in serves this one read and keeps nothing unless --yes is passed. The command reports what it observed; only a later read proves the login.

```bash
searchts login signin <url> [--verbose] [--browser BROWSER] [--yes]
```

| Argument | Description |
|---|---|
| `url` | The site to sign in to |

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |
| `--browser` BROWSER | Which browser searchts opens (default: chrome) Default: `chrome`. |
| `--yes` | Keep the login after signing in. Without this, signing in only serves this one read and nothing is kept. |

Examples:

```bash
searchts login signin https://example.com
searchts login signin https://example.com --browser firefox --yes
```

| Exit | Meaning |
|---|---|
| `0` | the sign-in browser closed |
| `1` | the browser or cookie read failed |
| `2` | bad usage |

MCP: `login_signin`.
MCP-only parameters: `wait_seconds`.
CLI-only flags: `--yes`.
- MCP keeps the login; CLI `login signin` keeps only with `--yes`.
- MCP has no terminal: the user closes the window to finish, and the call waits up to `wait_seconds` (default 180, 30 to 900).

### `login purge-scratch`

Delete every scratch copy now.
A read deletes its own scratch copy at the end, so this is for cleaning up after a process that was killed.

```bash
searchts login purge-scratch [--verbose]
```

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |

Examples:

```bash
searchts login purge-scratch
```

| Exit | Meaning |
|---|---|
| `0` | the scratch copies were deleted |
| `2` | bad usage |

No MCP tool: scratch copies are deleted at the end of every read.

### `login sweep`

Delete expired cookies now, offline.
Runs offline: no browser, no network, no daemon. searchts also sweeps on every command start; schedule this yourself if you want the receipt in a cron or Task Scheduler entry.

```bash
searchts login sweep [--verbose]
```

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |

Examples:

```bash
searchts login sweep
```

| Exit | Meaning |
|---|---|
| `0` | the sweep finished |
| `2` | bad usage |

No MCP tool: expired cookies are swept on every MCP result; a tool would duplicate it.

### `login check`

Read one signed-in-only page with the saved cookies.
Exit 0 means logged in, 1 logged out, 2 unknown. Expiry is only an upper bound (a server can end a session early), and this proves no login wall, not which account is signed in. A captcha or block is unknown, never a guess. Only direct requests carry the cookies; the Jina relay never receives them.

```bash
searchts login check <site> [--verbose] [--json] [--url CHECK_URL]
```

| Argument | Description |
|---|---|
| `site` | The site whose saved login to check |

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |
| `--json` | Print the result as JSON on stdout: host, status, why, page, exit_code. An invalid site prints the same url/error envelope read --json uses and exits 2. |
| `--url` CHECK_URL | A page only signed-in users see. Without it, a known account page is used for reddit.com, linkedin.com, github.com and x.com. For any other site (or a custom page) a no-wall result is reported as unknown, because a public page proves nothing about your account. |

Examples:

```bash
searchts login check reddit.com
searchts login check example.com --url https://example.com/account
```

| Exit | Meaning |
|---|---|
| `0` | logged in: the signed-in page was read without a login wall |
| `1` | logged out: no live saved cookies, or the site showed its login page |
| `2` | unknown: a captcha, block, network error, or no page could be chosen |

MCP: `login_check`.
CLI-only flags: `--json`.
- `check_url` mirrors CLI `--url`: a page only a signed-in account sees.
- Without it, the known account pages for reddit.com, linkedin.com, github.com and x.com are used.
- An invalid URL is a `bad_url` error envelope, not an `unknown` login.

### `uninstall`

Remove config, tokens and skill files.
Without flags it removes the config directory and the skill files. --keep-config removes only the skill files. --browser removes only what `install --browser` added.

```bash
searchts uninstall [--verbose] [--dry-run] [--browser] [--chromium] [--keep-config]
```

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |
| `--dry-run` | Show what would be removed without making any changes |
| `--browser` | Remove only what install --browser added. Chromium stays unless --chromium |
| `--chromium` | With --browser, also remove the shared Chromium cache |
| `--keep-config` | Remove skill files only, keep ~/.searchts/ config and tokens |

Examples:

```bash
searchts uninstall --dry-run
searchts uninstall
searchts uninstall --browser --chromium
```

| Exit | Meaning |
|---|---|
| `0` | the command finished |
| `1` | the command failed; the reason is on stderr |
| `2` | bad usage |

No MCP tool: removing software is the user's act.

### `update`

Update to the latest release (`upgrade` is the same command).
Detects the install shape (pipx, uv tool, editable checkout) and runs that install's own upgrade command. It does not kill a running searchts.exe; stop it first on Windows.
Alias: `upgrade`.

```bash
searchts update [--verbose] [--force] [--dry-run]
```

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |
| `--force` | Reinstall even when this copy is already the latest release |
| `--dry-run` | Print the upgrade command and do not run it |

Examples:

```bash
searchts update
searchts update --dry-run
searchts update --force
```

| Exit | Meaning |
|---|---|
| `0` | up to date, or the update finished |
| `1` | the update failed |
| `2` | this install shape cannot be updated |

No MCP tool: installing software is the user's act; MCP reports `update_available` instead.

### `check-update`

Is there a newer version?
One GitHub API call. Since 0.22.0 a newer release is also reported in `--json` output and in every successful MCP result as `update_available` (an `Error: ...` result does not carry it), so an agent does not need a separate call after each task. `search --json` keeps stdout a bare array, so it prints `{"update_available": ...}` as one JSON line on stderr instead.

```bash
searchts check-update [--verbose]
```

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |

Examples:

```bash
searchts check-update
```

| Exit | Meaning |
|---|---|
| `0` | the check finished (newer or current) |
| `2` | bad usage |

No MCP tool: MCP results already carry `update_available`; the CLI verb is for scripts.

### `watch`

Quick health check for a scheduled task.
Prints one line when everything is normal, a monitoring report when a channel is broken, and a one-line update note when a newer release exists. Designed to be run by cron or Task Scheduler.

```bash
searchts watch [--verbose]
```

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |

Examples:

```bash
searchts watch
```

| Exit | Meaning |
|---|---|
| `0` | the check finished |
| `2` | bad usage |

No MCP tool: a scheduled shell check, not an agent tool.

### `version`

Version.

```bash
searchts version [--verbose]
```

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |

Examples:

```bash
searchts version
```

| Exit | Meaning |
|---|---|
| `0` | the version was printed |
| `2` | bad usage |

No MCP tool: `get_status` carries the version.

### `help`

The command index, one command, or the machine-readable catalog.
`searchts help` is the same document as `searchts --help`. `searchts help <cmd>` renders that command. `--json` prints the stable catalog agents and tooling read.

```bash
searchts help [command...] [--verbose] [--json]
```

| Argument | Description |
|---|---|
| `[command...]` | Command path to show, e.g. login check. Omit for the index. |

| Flag | Description |
|---|---|
| `-v`, `--verbose` | Show debug logs |
| `--json` | Print the stable machine-readable catalog instead of the human screen |

Examples:

```bash
searchts help
searchts help login check
searchts help --json
```

| Exit | Meaning |
|---|---|
| `0` | the help was printed |
| `2` | unknown command path |

No MCP tool: the MCP tool list is the machine-readable surface.
