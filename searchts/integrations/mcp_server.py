# -*- coding: utf-8 -*-
"""
searchts MCP Server — expose doctor/status as MCP tool.

Run: python -m searchts.integrations.mcp_server

searchts is an installer + doctor tool. For actual reading/searching,
agents should call upstream tools directly (twitter-cli, yt-dlp, mcporter, etc.).
"""

import asyncio
import json
import sys

from searchts.config import Config
from searchts.core import Searchts

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    HAS_MCP = True
except ImportError:
    HAS_MCP = False


def create_server():
    if not HAS_MCP:
        print("MCP not installed. Install: pip install searchts[mcp]", file=sys.stderr)
        sys.exit(1)

    server = Server("searchts")
    config = Config()
    eyes = Searchts(config)

    @server.list_tools()
    async def list_tools():
        return [
            Tool(name="get_status",
                 description="Get searchts status: which channels are installed and active.",
                 inputSchema={"type": "object", "properties": {}}),
            Tool(name="read_url",
                 description="Fetch any URL through the escalating open-source unlocker "
                             "(curl_cffi -> Jina Reader -> stealth-browser) and return clean "
                             "markdown text. Beats common bot-walls; falls back gracefully.",
                 inputSchema={
                     "type": "object",
                     "properties": {
                         "url": {"type": "string", "description": "The URL to read"},
                     },
                     "required": ["url"],
                 }),
            Tool(name="web_search",
                 description="Multi-source web search, fusion-merged across providers "
                             "(DuckDuckGo by default; SearXNG/Exa/Brave/Tavily when configured). "
                             "Returns a ranked list of title + url + snippet.",
                 inputSchema={
                     "type": "object",
                     "properties": {
                         "query": {"type": "string", "description": "The search query"},
                         "max_results": {"type": "integer",
                                         "description": "Max results to return (default 5)"},
                     },
                     "required": ["query"],
                 }),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        try:
            if name == "get_status":
                result = eyes.doctor_report()
            elif name == "read_url":
                result = read_url(arguments.get("url", ""))
            elif name == "web_search":
                result = web_search(
                    arguments.get("query", ""),
                    int(arguments.get("max_results", 5) or 5),
                )
            else:
                result = f"Unknown tool: {name}"

            text = json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, (dict, list)) else str(result)
            return [TextContent(type="text", text=text)]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    return server


def read_url(url: str) -> str:
    """Fetch `url` via the unlocker and return markdown text.

    Returns a clear error string (rather than raising) when every backend fails,
    so the MCP layer surfaces a readable message to the agent.
    """
    from searchts import unlocker

    if not url:
        return "Error: read_url requires a 'url' argument."
    try:
        return unlocker.fetch(url).text
    except unlocker.UnlockerError as e:
        return f"Error: {e}"


def web_search(query: str, max_results: int = 5) -> str:
    """Run a fusion-merged multi-source web search; return a formatted text block.

    Module-level (like read_url) so it is testable without the optional `mcp`
    package. Returns a clear error string rather than raising when every
    provider fails.
    """
    from searchts import search as search_mod

    if not query:
        return "Error: web_search requires a 'query' argument."
    try:
        results = search_mod.search(query, max_results=max_results)
    except search_mod.SearchError as e:
        return f"Error: {e}"

    blocks = []
    for i, r in enumerate(results, start=1):
        lines = [f"{i}. {r.title or '(no title)'}", f"   {r.url}"]
        if r.snippet:
            lines.append(f"   {r.snippet}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


async def main():
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
