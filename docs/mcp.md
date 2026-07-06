# searchts as an MCP server

searchts ships a small [Model Context Protocol](https://modelcontextprotocol.io) server, so any
MCP-capable agent (Claude Code, Claude Desktop, Cursor, …) gets searchts's web tools as always-on,
first-class tools — no shelling out to the CLI. It speaks stdio (JSON-RPC) and calls the exact same
`searchts.unlocker` / `searchts.search` / `searchts.assets` code as the CLI, so behaviour is identical.

## Install & wire up

```bash
pip install "searchts[mcp]"
searchts mcp install          # prints the exact wiring for your host
```

For Claude Code that is:

```bash
claude mcp add searchts -- searchts mcp serve
```

For Cursor / Claude Desktop, add to your MCP config (see also `config/mcporter.json`):

```json
{
  "mcpServers": {
    "searchts": { "command": "searchts", "args": ["mcp", "serve"] }
  }
}
```

## Tools

| Tool | Use it when | Returns |
|------|-------------|---------|
| `read_url(url)` | A page is blocked (403/429, a Cloudflare/DataDome/PerimeterX bot-wall, an "enable JavaScript" page) or is JS-rendered, and you want its text. | Clean Markdown. Invisible characters stripped; if prompt-injection indicators are found, the body is fenced as untrusted and a one-line warning is prepended. |
| `web_search(query, max_results=5)` | You need to find URLs or answer an open-ended question. Keyless (DuckDuckGo) by default; SearXNG/Exa/Brave/Tavily merge in when configured. | A ranked, de-duplicated `title + URL + snippet` block. `max_results` is clamped to 1–25. |
| `fetch_asset(url, out_dir="")` | You want one specific file (image, PDF, font, CSS) by its direct URL. | JSON `{path, content_type, bytes}`. Saves into `out_dir`, else the current directory. |
| `grab_site(url, out_dir="", read=false)` | You want a whole page's design/assets at once — images, icons, css, fonts, a color palette, and the fonts in use. | JSON manifest with local paths. Saves into `out_dir`, else `searchts-grab-<host>`; set `read=true` to also save the page text as `page.md`. |
| `get_status()` | A call fails, or you want to see what's configured before relying on an optional capability. | A human-readable health report (unlocker tiers, search providers, optional integrations). |

Every tool returns an `Error: …` **string** instead of raising, so failures stay readable to the agent.

## MCP vs. the CLI and slash command

All three surfaces call the same core — pick by how your agent works:

- **MCP server** (above) — always-on tools, no subprocess per call. Best for agents that speak MCP.
- **Slash command** (`searchts skill install`) — a `/searchts` command for Claude Code that drives the CLI verbs.
- **CLI** (`searchts read` / `search` / `transcribe` / `grab`) — the underlying commands; scriptable and pipeable.
