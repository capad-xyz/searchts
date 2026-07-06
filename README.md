# searchts

**The missing layer between AI and the web.** A Python CLI and library that lets an AI agent read and search the internet, fronted by a fully open-source "unlocker" that gets through common bot-walls with no paid proxy and no API key.

[![CI](https://github.com/capad-xyz/searchts/actions/workflows/pytest.yml/badge.svg)](https://github.com/capad-xyz/searchts/actions/workflows/pytest.yml)
[![PyPI](https://img.shields.io/pypi/v/searchts.svg)](https://pypi.org/project/searchts/)
[![Python](https://img.shields.io/pypi/pyversions/searchts.svg)](https://pypi.org/project/searchts/)
[![Downloads](https://img.shields.io/pypi/dm/searchts.svg)](https://pypi.org/project/searchts/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

<p align="center">
  <img src="demo/demo1.gif" alt="A Claude agent's fetch hits a 403 bot wall, so it routes through searchts, reads the page, and answers the question" width="860">
</p>

## Why searchts?

- Reads pages behind common bot walls
- Works with Claude, Codex, and MCP agents
- Extracts clean Markdown, ready to feed a model
- Searches the web without API keys
- Downloads a page's assets (images, fonts, palette)
- Transcribes videos, subtitles-first

## Why it's free

AI agents constantly need to read web pages, but the naive way they fetch is trivially blocked by modern anti-bot systems (Cloudflare, PerimeterX, DataDome). Paid unlocker services solve this, but the thing they really charge for is a large pool of clean residential IP addresses. `searchts` runs on your own machine, from your own connection, at personal volume, so it sidesteps that cost and gets through most of those walls for free.

## The unlocker

`searchts` reads any URL through an escalating ladder and stops at the first tier that returns real content:

1. **curl_cffi**: a fetch that impersonates a real Chrome's TLS/JA3 and HTTP2 fingerprint. Beats user-agent and fingerprint filters. Fast, local, private.
2. **Jina Reader**: a JavaScript-rendering relay, for pages that only fill in content after running JS.
3. **stealth browser**: an undetected headless Chromium (patchright), launched lazily only when the cheaper tiers fail, for live JS / Cloudflare managed challenges.

If every tier is defeated by an interactive CAPTCHA, an optional human-in-the-loop step opens a real browser so you can solve it once and continue. Block detection is phrase-based (not vendor-name based), so legitimate pages that merely embed a bot-sensor script are not falsely rejected. Content is extracted to clean Markdown with `trafilatura`.

## Install

```bash
pipx install searchts            # recommended: global, isolated CLI
# or
pip install searchts

# optional extras
pip install "searchts[browser]" && patchright install chromium   # stealth-browser tier
pip install "searchts[mcp]"                                       # MCP server for agents
```

## Quickstart

```bash
searchts read https://example.com          # fetch any page as clean Markdown
searchts search "open source vector db"    # multi-provider web search (keyless by default)
searchts transcribe https://youtu.be/...   # transcript of a YouTube/TikTok/Instagram/Reddit video
searchts grab https://example.com          # download a page's assets + extract palette/fonts
searchts get https://example.com/logo.png  # download one asset (image/PDF/font/file)
searchts doctor                            # see what is configured and working
```

`read` flags: `--json`, `--backend <tier>`, `--human` (CAPTCHA handoff), `--scrub` (redact injection).
`search` flags: `-n <count>`, `--json`, `--provider <name>`. Content goes to stdout (pipeable); status to stderr.
`grab` flags: `--out <dir>`, `--kinds <images,icons,css,fonts,svg>`, `--read` (also save page.md), `--max <n>`, `--json`.

## Use it from your AI agent

Add searchts to your agent in one line - as an MCP server, or as a Claude Code slash command:

<p align="center">
  <img src="demo/demo2.gif" alt="Installing searchts as an MCP server with claude mcp add, or as a Claude Code slash command with searchts skill install" width="820">
</p>

Two ways, both one command:

```bash
# 1) MCP: gives the agent always-on read_url + web_search + fetch_asset + grab_site tools
pip install "searchts[mcp]"
searchts mcp install          # prints the wiring, e.g. for Claude Code:
                              #   claude mcp add searchts -- searchts mcp serve

# 2) Slash command: type /searchts <url-or-query> in Claude Code
searchts skill install        # writes ~/.claude/commands/searchts.md
```

## Features

- **Escalating open-source unlocker**: curl_cffi, then Jina Reader, then a stealth browser.
- **Multi-provider search with rank fusion**: DuckDuckGo (keyless default), plus SearXNG, Exa, Brave, and Tavily when configured; results merged with reciprocal rank fusion and de-duplicated.
- **Video transcription**: yt-dlp audio plus Whisper for YouTube, TikTok, Instagram, and Reddit videos.
- **Asset + design grabber**: `searchts grab <url>` downloads a page's images/icons/css/fonts and extracts a color palette plus the fonts in use; `searchts get <url>` pulls a single asset. Both go through the same escalating unlock ladder, so they work on fingerprint-gated CDNs, not just open ones.
- **Prompt-injection scrubbing**: strips invisible/bidi characters, flags injection indicators, optional redaction, so untrusted page content is safer to feed a model.
- **Per-domain backend memory**: remembers which tier worked per domain and tries it first (`SEARCHTS_NO_MEMORY=1` to disable).
- **Surfaces**: a CLI, an MCP server (`read_url`, `web_search`, `fetch_asset`, `grab_site`), and a Python library.

## Use as a library

```python
from searchts import unlocker
r = unlocker.fetch("https://example.com")
print(r.backend, r.status, r.text)

from searchts.search import search
for hit in search("open source vector db", max_results=5):
    print(hit.title, hit.url)
```

## How it works, and its limits

- It runs from your own residential IP at personal volume, which is why it needs no paid proxy pool. It is a personal-grade research tool, not a mass-scraping system.
- Interactive CAPTCHAs (DataDome / Turnstile press-and-hold) are the honest ceiling. Use `--human` for those.
- Some platforms (notably Instagram, and YouTube in 2026) may need your browser cookies or fail intermittently; that is platform-side.
- Anti-bot systems evolve; this is an arms race and the techniques may need occasional updates. Respect each site's terms of service and use responsibly.

## Configuration

Search works with no keys (DuckDuckGo). Everything else is optional, via `searchts configure` or a `.env` (see `.env.example`):

- **Search providers**: Exa, Brave, Tavily API keys, or a self-hosted `SEARXNG_URL`, for more and better results.
- **Transcription**: a Groq or OpenAI (Whisper) key, plus `ffmpeg` and `yt-dlp`.
- **GitHub token** for higher rate limits.

Run `searchts doctor` to check what is configured and working.

## Optional integrations

The core is `read` / `search` / `transcribe`, and for most reads you can just
`searchts read <the-url>` on the public page. As an optional extra, if you have
separately-installed platform CLIs (`gh`, `twitter-cli`, `opencli`, `mcporter`),
searchts can also reach GitHub, Twitter/X, Reddit, and LinkedIn through them, and
`searchts doctor` will report which are present. These are add-ons, not the core.

## Roadmap

See [ROADMAP.md](ROADMAP.md) for where searchts is headed — and what's deliberately out of scope.

## Credits

`searchts` builds on and extends [Agent-Reach](https://github.com/Panniantong/Agent-Reach) (MIT), reusing its channel, installer, and diagnostics architecture. The escalating open-source unlocker, multi-provider search with rank fusion, prompt-injection scrubbing, per-domain backend memory, the human-in-the-loop CAPTCHA flow, the video transcript channels, the `read_url` / `web_search` MCP tools, and the `read` / `search` CLI commands are additions in `searchts`. Thanks to the original authors.

## License

MIT. See [LICENSE](LICENSE). Original portions Copyright (c) 2025 Agent Eyes; modifications and additions Copyright (c) 2026 capad-xyz.

---

Built by [capad](https://github.com/capad-xyz). Questions or feedback: open an issue or email oss@capad.fyi.

> *Fun fact: "searchts" doesn't officially abbreviate anything. Off the record, it stands for "search this shit".*
