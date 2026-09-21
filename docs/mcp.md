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

Ask the agent to `read https://en.wikipedia.org/wiki/Ada_Lovelace` — `example.com` is thinner than `_MIN_CHARS` and looks like a failed install.

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

`--host` must be `127.0.0.1`, `localhost`, or `::1`. `0.0.0.0` and LAN addresses are refused. There is **no public/hosted MCP URL**.

Custom connectors that require HTTPS still need a tunnel you run yourself; searchts will not ship one.

## Tools

| Tool | Use it when | Returns |
|------|-------------|---------|
| `read_url(url)` | A page is blocked (403/429, a Cloudflare/DataDome/PerimeterX bot-wall, an "enable JavaScript" page) or is JS-rendered, and you want its text. | Clean Markdown. Invisible characters stripped; if prompt-injection indicators are found, the body is fenced as untrusted and a one-line warning is prepended. |
| `web_search(query, max_results=5)` | You need to find URLs or answer an open-ended question. Keyless (DuckDuckGo) by default; SearXNG/Exa/Brave/Tavily merge in when configured. | A ranked, de-duplicated `title + URL + snippet` block. `max_results` is clamped to 1–25. |
| `fetch_asset(url, out_dir="")` | You want one specific file (image, PDF, font, CSS) by its direct URL. | JSON `{path, content_type, bytes}`. Saves into `out_dir`, else the current directory. |
| `grab_site(url, out_dir="", read=false)` | You want a whole page's design/assets at once — images, icons, css, fonts, a color palette, and the fonts in use. | JSON manifest with local paths. Saves into `out_dir`, else `searchts-grab-<host>`; set `read=true` to also save the page text as `page.md`. |
| `get_status()` | A call fails, or you want to see what's configured before relying on an optional capability. | A human-readable health report (unlocker tiers, search providers, optional integrations). |
| `transcribe(source, provider="auto", prefer_subtitles=true, cookies_from_browser="")` | You want spoken words from a video URL or local audio file. Subtitles-first (no key); Whisper only if there are no captions. | Transcript text. `cookies_from_browser` is opt-in (this machine; never `read_url`). |

Every tool returns an `Error: …` **string** instead of raising, so failures stay readable to the agent.

## MCP vs. the CLI and slash command

All three surfaces call the same core — pick by how your agent works:

- **MCP server** (above) — always-on tools, no subprocess per call. Best for agents that speak MCP.
- **Slash command** (`searchts skill install`) — a `/searchts` command for Claude Code that drives the CLI verbs.
- **CLI** (`searchts read` / `search` / `transcribe` / `grab`) — the underlying commands; scriptable and pipeable.
