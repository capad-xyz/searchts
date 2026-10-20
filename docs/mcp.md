# searchts as an MCP server

searchts ships a small [Model Context Protocol](https://modelcontextprotocol.io) server, so any
MCP-capable agent (Claude Code, Claude Desktop, Cursor, …) gets searchts's web tools as always-on,
first-class tools — no shelling out to the CLI. The default transport is stdio (JSON-RPC). Loopback
HTTP is optional (`--http`). Both call the exact same
`searchts.unlocker` / `searchts.search` / `searchts.assets` / `searchts.transcribe` code as the CLI, so behaviour is identical.

## Install & wire up

Keep the CLI (pipx, MCP extra included):

```bash
pipx install "searchts[mcp]"
searchts mcp install          # prints the exact wiring for your host
```

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
| `read_url(url, max_pages=1, max_items=0, cursor="", page_items=0, expand=false, cookies="", cookies_from_browser="", cdp_port="", proxy="", proxy_trusted=false)` | A page is blocked (403/429, a Cloudflare/DataDome/PerimeterX bot-wall, an "enable JavaScript" page) or is JS-rendered, and you want its text. | Clean Markdown. Invisible characters stripped; if prompt-injection indicators are found, the body is fenced as untrusted and a one-line warning is prepended. When the page has more than the read returned (a next page, a feed, folded text, a list it mostly dropped, a stated count like "showing 1–20 of 340"), the text ends with a bracketed note and the JSON carries `next_url` and `more`. A list page whose items the extractor lost (search results, a tag feed, a blog index) comes back as an index rebuilt from the page: each item's title, link, byline and snippet, with a note saying so. No note does not prove the page is complete. Behind a login, `cookies_from_browser` (a Firefox-family browser such as `firefox` or `zen`), `cdp_port` (a debugger port you opened on your own browser) or `cookies` (a cookie file path) read the login for that one URL's host. They are opt-in and host-fenced. The receipt says whether the read was `authenticated` and where the login came from. `proxy` routes the read through a proxy; it carries cookies only with `proxy_trusted`. `max_pages`, `max_items` and `expand` are intent, not mechanics: ask for more pages, more list rows (next-page links first, then scrolling when that is the only way the list grows), or the text behind closed `<details>` and read/show/see-more buttons. Each is capped by the user's own ceiling - `SEARCHTS_MAX_PAGES` (5), `SEARCHTS_MAX_ITEMS` (300), `SEARCHTS_MAX_EXPAND_CLICKS` (8) - which you cannot raise; ask for less than the ceiling. Over the ceiling the read comes back clamped with a note naming it, in the same `text` as everything else. `expand` is off by default, never follows a link, a form or a sign-in, and names a "continue reading" paywall rather than opening it. It also drops the Jina relay from the ladder, because a relay result cannot be told to press a button. A list that only grows by scrolling, or a fold only the DOM has, needs the browser, and the note says `searchts install --browser`. |
| `web_search(query, max_results=5)` | You need URLs to read. Keyless (DuckDuckGo) by default; SearXNG/Exa/Brave/Tavily merge in when configured. A snippet is not the page: call `read_url` on the URL. | A ranked, de-duplicated `title + URL + snippet` block, led by a line that says the snippet is not the page. `max_results` is clamped to 1–25. |
| `fetch_asset(url, out_dir="")` | You want one specific file (image, PDF, font, CSS) by its direct URL. | JSON `{path, content_type, bytes}`. Saves into `out_dir` (a relative folder inside the server's working directory, or inside `SEARCHTS_MCP_OUT_DIR` when you set it: no absolute paths, `..`, dot folders or autostart folders), else that folder itself. Never overwrites: a clash gets a `-1`, `-2` … suffix. |
| `grab_site(url, out_dir="", read=false, max_tokens=24)` | The files a read named are the deliverable: images, icons, css, fonts, and the palette those files use. For one URL, use `fetch_asset`. | JSON manifest with local paths, plus `out_dir` (the folder used). Saves into `out_dir` (same rules as `fetch_asset`), else `searchts-grab-<host>` inside it. Never writes into a folder that already has files: it uses `<folder>-2`, `-3` … instead. Set `read=true` to also save the page text as `page.md`. `max_tokens` is how many radius, shadow, and spacing values to keep (ceiling 200). `tokens_more` names how many more a higher number returns. |
| `get_status()` | A call fails, or you want to see what's configured before relying on an optional capability. | A human-readable health report (unlocker tiers, search providers, optional integrations). |
| `login_status()` | A `read_url` error mentions a login, and you want to know what searchts already holds before asking the user for anything. | JSON: kept sites, whether this session may copy logins, the sites it copied, and the scratch folder. Never a cookie value. |
| `login_signin(url, browser="chrome")` | A page is behind a login and the user has no browser session worth copying, or refuses a copy. The user must be at the machine to sign in. | JSON `{host, kept, cookies, why}`. Signs in once in a browser searchts opens and keeps that login (unlike the CLI, which keeps only with `--yes`). The user's own browser is not read. |
| `login_kill(url, also_browser=false)` | A `read_url` error says a saved login has expired. | JSON of what was removed. Deletes searchts's own copy for one site. The user's own Firefox or Chrome cookies are untouched unless `also_browser` is true. |
| `transcribe(source, provider="auto", prefer_subtitles=true, cookies_from_browser="")` | `read_url` said a player page has no captions, or the source is a local audio file. Subtitles-first (no key); Whisper only if there are no captions. | Transcript text, or an `Error:` string. `cookies_from_browser` is opt-in (this machine; `read_url` does not copy those cookies). |

Every tool returns an `Error: …` **string** instead of raising, so failures stay readable to the agent.

## MCP vs. the CLI and slash command

All three surfaces call the same core — pick by how your agent works:

- **MCP server** (above) — always-on tools, no subprocess per call. Best for agents that speak MCP.
- **Slash command** (`searchts skill install`) — a `/searchts` command for Claude Code that drives the CLI verbs.
- **CLI** (`searchts read` / `search` / `transcribe` / `grab`) — the underlying commands; scriptable and pipeable.

**Where MCP saves land.** Some hosts start the server with `/` as its working directory, where nothing can be saved. Set `SEARCHTS_MCP_OUT_DIR` in the server's environment (for example `SEARCHTS_MCP_OUT_DIR=~/Downloads/searchts`) to give `fetch_asset` and `grab_site` a folder of your choosing. The agent can still only pick relative folders inside it.
