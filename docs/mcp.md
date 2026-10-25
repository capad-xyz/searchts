# searchts as an MCP server

searchts ships a small [Model Context Protocol](https://modelcontextprotocol.io) server, so any
MCP-capable agent (Claude Code, Claude Desktop, Cursor, …) gets searchts's web tools as always-on,
first-class tools — no shelling out to the CLI. The default transport is stdio (JSON-RPC). Loopback
HTTP is optional (`--http`). Both call the exact same
`searchts.unlocker` / `searchts.search` / `searchts.assets` / `searchts.transcribe` / `searchts.login_store` code as the CLI, so behaviour is identical.

## Install & wire up

Keep the CLI (pipx, MCP extra included):

```bash
pipx install "searchts[mcp]"
searchts mcp install          # writes the stdio server into agents already installed
```

`searchts mcp install` merges `searchts mcp serve` into the user config of each client it finds: Claude Code, Claude Desktop, Cursor, Codex (`~/.codex/config.toml`), VS Code (`servers` + `type: stdio`), Copilot CLI, Gemini CLI, OpenCode (`mcp` command array), Windsurf, and Devin Desktop. It does not create a config for a client that is not installed, and it does not touch a project file. `--client NAME` writes that one anyway. `--client json` only prints the `mcpServers` snippet. A config that does not parse, or that already points `searchts` at a different command, is left unchanged.

Try / no install / host cannot see the pipx bin:

```bash
uvx --from "searchts[mcp]" searchts mcp serve
```

For Claude Code after pipx:

```bash
claude mcp add searchts -- searchts mcp serve
```

Try / no install:

```bash
claude mcp add searchts -- uvx --from "searchts[mcp]" searchts mcp serve
```

If the agent host cannot see pipx's bin directory, use the `uvx` one-liner above, or point `command` at `pipx which searchts`. `pip install "searchts[mcp]"` is venv / packaging only.

Ask the agent to `read https://en.wikipedia.org/wiki/Ada_Lovelace`. `example.com` works too, but it is one short paragraph.

For Cursor / Claude Desktop, add to your MCP config (see also `config/mcporter.json`):

```json
{
  "mcpServers": {
    "searchts": { "command": "searchts", "args": ["mcp", "serve"] }
  }
}
```

## Loopback HTTP (F9)

Hosts that cannot spawn stdio (Grok / Claude custom connector, a phone talking to your laptop) use Streamable HTTP on **loopback only**:

```bash
searchts mcp serve --http
# URL: http://127.0.0.1:8765/mcp
```

Legacy SSE: `searchts mcp serve --sse` → `http://127.0.0.1:8765/sse`. Prefer `--http`.

`--host` must be `127.0.0.1`, `localhost`, or `::1`. `0.0.0.0` and LAN addresses are refused. There is **no public/hosted MCP URL** on this package ([PLAN.md](../PLAN.md) **N2**). A hosted read is **F18**, not this command.

Custom connectors that require HTTPS cannot use `http://127.0.0.1`. You run that tunnel yourself (cloudflared, ngrok). searchts does not bundle it. This line is about reaching the MCP server. It is not a ban on a proxy, a VPN, or a later hosted read.

## Tools

| Tool | Use it when | Returns |
|------|-------------|---------|
| `read_url(url, max_pages=1, max_items=0, cursor="", page_items=0, expand=false, cookies="", cookies_from_browser="", cdp_port="", proxy="", proxy_trusted=false, max_media=0)` | A page is blocked (403/429, a Cloudflare/DataDome/PerimeterX bot-wall, an "enable JavaScript" page) or is JS-rendered, and you want its text. | Clean Markdown. Invisible characters stripped; if prompt-injection indicators are found, the body is fenced as untrusted and a one-line warning is prepended. When the page has more than the read returned (a next page, a feed, folded text, a list it mostly dropped, a stated count like "showing 1–20 of 340"), the text ends with a bracketed note and the JSON carries `next_cursor` and `more`. There is deliberately no `next_url`: a page-authored URL is not a safe next request. A list page whose items the extractor lost (search results, a tag feed, a blog index) comes back as an index rebuilt from the page: each item's title, link, byline and snippet, with a note saying so. No note does not prove the page is complete. Behind a login, `cookies_from_browser` (a Firefox-family browser such as `firefox` or `zen`), `cdp_port` (a debugger port you opened on your own browser) or `cookies` (a cookie file path) read the login for that one URL's host. They are opt-in and host-fenced. The receipt says whether the read was `authenticated` and where the login came from. `proxy` routes the read through a proxy; it carries cookies only with `proxy_trusted`. `max_pages`, `max_items` and `expand` are intent, not mechanics: ask for more pages, more list rows (next-page links first, then scrolling when that is the only way the list grows), or the text behind closed `<details>` and read/show/see-more buttons. Each is capped by the user's own ceiling - `SEARCHTS_MAX_PAGES` (5), `SEARCHTS_MAX_ITEMS` (300), `SEARCHTS_MAX_EXPAND_CLICKS` (8) - which you cannot raise; ask for less than the ceiling. Over the ceiling the read comes back clamped with a note naming it, in the same `text` as everything else. `expand` is off by default, never follows a link, a form or a sign-in, and names a "continue reading" paywall rather than opening it. It also drops the Jina relay from the ladder, because a relay result cannot be told to press a button. A list that only grows by scrolling, or a fold only the DOM has, needs the browser, and the note says `searchts install --browser`. |
| `web_search(query, max_results=5)` | You need URLs to read. Keyless (DuckDuckGo) by default; SearXNG/Exa/Brave/Tavily merge in when configured. A snippet is not the page: call `read_url` on the URL. | A ranked, de-duplicated `title + URL + snippet` block, led by a line that says the snippet is not the page. `max_results` is clamped to 1–25. |
| `fetch_asset(url, out_dir="")` | You want one specific file (image, PDF, font, CSS) by its direct URL. | JSON `{path, content_type, bytes}`. Saves into `out_dir` (a relative folder inside the server's working directory, or inside `SEARCHTS_MCP_OUT_DIR` when you set it: no absolute paths, `..`, dot folders or autostart folders), else that folder itself. Never overwrites: a clash gets a `-1`, `-2` … suffix. |
| `grab_site(url, out_dir="", read=false, max_assets=120, max_tokens=24)` | The files a read named are the deliverable: images, icons, css, fonts, and the palette those files use. For one URL, use `fetch_asset`. | JSON manifest with local paths, plus `out_dir` (the folder used). Saves into `out_dir` (same rules as `fetch_asset`), else `searchts-grab-<host>` inside it. Never writes into a folder that already has files: it uses `<folder>-2`, `-3` … instead. Set `read=true` to also save the page text as `page.md`. `max_assets` mirrors CLI `--max`. `max_tokens` is how many radius, shadow, and spacing values to keep (ceiling 200). `tokens_more` names how many more a higher number returns. |
| `get_status()` | A call fails, or you want to see what's configured before relying on an optional capability. | A plain-text health report (unlocker tiers, search providers, optional integrations): one line per channel starting `ok`, `warn` or `error`, never wrapped, with a fix command on its own indented line so it can be copied as-is. Plus the cached update check when a newer release exists. |
| `login_status()` | A `read_url` error mentions a login, and you want to know what searchts already holds before asking the user for anything. | JSON: kept sites, live cookie count and expiry (an upper bound), whether each came from a browser or `login_signin`, whether the per-site consent for an automatic re-copy is recorded, whether this session may copy logins, the sites it copied, and the scratch folder. Never a cookie value. |
| `login_signin(url, browser="chrome")` | A page is behind a login and the user has no browser session worth copying, or refuses a copy. The user must be at the machine to sign in. | JSON `{host, kept, cookies, why}`. Signs in once in a browser searchts opens and keeps that login (unlike the CLI, which keeps only with `--yes`). The user's own browser is not read. A login kept this way is not refreshed automatically; near expiry the user is told to run `login_signin` again. |
| `login_check(url, check_url="")` | You need to know whether a saved login is still alive before asking the user for anything. | JSON `{host, status, why, page, exit_code}` where status is `logged in`, `logged out` or `unknown`. Reads one signed-in-only page directly with the saved cookies; the Jina relay never sees them. A captcha, block or network error is `unknown`. Expiry is an upper bound. For reddit.com, linkedin.com, github.com and x.com a known account page is used; other sites need `check_url`, a signed-in-only page, and a public page is `unknown`, not logged in. `check_url` mirrors CLI `login check <site> --url <page>`. |
| `login_kill(url, also_browser=false)` | A `read_url` error says a saved login has expired. | JSON of what was removed. Deletes searchts's own copy for one site. The user's own Firefox or Chrome cookies are untouched unless `also_browser` is true. |
| `transcribe(source, provider="auto", prefer_subtitles=true, cookies_from_browser="")` | `read_url` said a player page has no captions, or the source is a local audio file. Subtitles-first (no key); Whisper only if there are no captions. | Transcript text, or an `Error:` string. `cookies_from_browser` is opt-in (this machine; `read_url` does not copy those cookies). |

Every tool returns an `Error: …` **string** instead of raising, so failures stay readable to the agent.

### Update check in tool results

The server checks the GitHub latest release of
[capad-xyz/searchts](https://github.com/capad-xyz/searchts/releases/latest) at
most once per 24 hours: one `GET` with a `searchts/<version>` User-Agent and
nothing about the user, cached in `~/.searchts/update-check.json`. A failed check
is silent. When the release is newer, a tool result carries an
`update_available` object (`current`, `latest`, `command`) and, at most once per
24 hours per install, one line telling the agent to tell the user. The
once-a-day stamp is kept in `~/.searchts/update-notice.json`. **Nothing is
installed or changed automatically**; the user runs `searchts update`.
`SEARCHTS_NO_UPDATE_CHECK=1` turns the check, the note and the CLI's stderr
nudge off.

## MCP vs. the CLI and slash command

All three surfaces call the same core — pick by how your agent works:

- **MCP server** (above) — always-on tools, no subprocess per call. Best for agents that speak MCP.
- **Slash command and skill** (`searchts skill install`) — a `/searchts` command for Claude Code, plus the Agent Skills bundle at `~/.claude/skills/searchts` and `~/.agents/skills/searchts` (OpenCode reads both).
- **CLI** (`searchts read` / `search` / `transcribe` / `grab` / `get` / `login`) — the underlying commands; scriptable and pipeable.

| MCP tool | CLI command | Deliberate difference |
|---|---|---|
| `read_url` | `searchts read` | `max_pages`, `max_items`, `max_media` are CLI `--pages`, `--items`, `--media`; `expand`, `cookies`, `cookies_from_browser`, `cdp_port`, `proxy`, `proxy_trusted` match their flags. MCP-only `cursor`, `page_items`; CLI-only `--human`, `--scrub`, `--backend`, `--json`, `--yes`. |
| `web_search` | `searchts search` | `max_results` is CLI `-n`: MCP default 5, CLI default 10. MCP has no `provider`; the CLI does. |
| `fetch_asset` | `searchts get` | `out_dir` is CLI `-o`, but MCP saves only under the server working directory or `SEARCHTS_MCP_OUT_DIR`; CLI `-o` takes any path. |
| `grab_site` | `searchts grab` | `out_dir`, `max_assets`, `max_tokens` are CLI `--out`, `--max`, `--tokens`; `read` matches `--read`. MCP saves under the same safe folder. CLI-only `--kinds`, `--scripts`, `--json`. |
| `get_status` | `searchts doctor` | Same report. CLI-only `--json`. |
| `transcribe` | `searchts transcribe` | `provider` matches `--provider`; `prefer_subtitles` mirrors CLI `--no-subtitles`; `cookies_from_browser` is the same opt-in. CLI-only `-o`. |
| `login_status` | `searchts login list` | Same audit, never a cookie value. |
| `login_signin` | `searchts login signin` | MCP keeps the login; the CLI keeps only with `--yes`. |
| `login_check` | `searchts login check` | `url` is the CLI's `site` positional; `check_url` mirrors CLI `--url`. |
| `login_kill` | `searchts login kill` | `also_browser` mirrors CLI `--also-browser`. |

CLI-only by design (no tool): `setup`, `install`, `configure`, `uninstall`, `skill install`, `mcp serve`, `mcp install`, `login keep`, `login purge-scratch`, `login sweep`, `update`, `check-update`, `watch`, `version`, `help`. `searchts help --json` lists the same mapping (`mcp.tools`, `mcp.cli_only`, `mcp.reason`).

**Where MCP saves land.** Some hosts start the server with `/` as its working directory, where nothing can be saved. Set `SEARCHTS_MCP_OUT_DIR` in the server's environment (for example `SEARCHTS_MCP_OUT_DIR=~/Downloads/searchts`) to give `fetch_asset` and `grab_site` a folder of your choosing. The agent can still only pick relative folders inside it.
