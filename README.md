# searchts

**Give your AI agent eyes on the open web.** `searchts` is a Python CLI and library that lets an AI agent read and search the internet, fronted by a fully open-source "unlocker" that gets through common bot-walls without any paid proxy or unlocker service.

License: MIT. Python 3.10+.

## Why

AI agents constantly need to read web pages, but the naive way they fetch is trivially blocked by modern anti-bot systems (Cloudflare, PerimeterX, DataDome). Paid unlocker services solve this, but the thing they really charge for is a large pool of clean residential IP addresses. `searchts` runs on your own machine, from your own connection, at personal volume, so it sidesteps that cost and gets through most of those walls for free.

## The unlocker

`searchts` reads any URL through an escalating ladder and stops at the first tier that returns real content:

1. **curl_cffi** : a fetch that impersonates a real Chrome's TLS/JA3 and HTTP2 fingerprint. Beats user-agent and fingerprint filters. Fast, local, private.
2. **Jina Reader** : a JavaScript-rendering relay, for pages that only fill in content after running JS.
3. **stealth browser** : an undetected headless Chromium (patchright), launched lazily only when the cheaper tiers fail, for live JS / Cloudflare managed challenges.

If every tier is defeated by an interactive CAPTCHA, an optional human-in-the-loop step opens a real browser so you can solve it once and continue.

Block detection is phrase-based, not vendor-name based, so legitimate pages that merely embed a bot-sensor script are not falsely rejected. Content is extracted to clean Markdown with `trafilatura`.

## Install

```bash
pip install searchts
# optional: the stealth-browser tier
pip install "searchts[browser]" && patchright install chromium
```

For development:

```bash
pip install -e . --no-build-isolation
```

## Quickstart

```bash
searchts read https://example.com                       # clean Markdown to stdout
searchts read https://news.ycombinator.com --json       # structured: backend, status, chars, text
searchts read https://example.com --backend curl_cffi   # force a single tier
searchts read https://example.com --human               # human-in-the-loop CAPTCHA fallback
```

Content goes to stdout (pipeable); status goes to stderr.

## Features

- **Escalating open-source unlocker**: curl_cffi, then Jina Reader, then a stealth browser.
- **`searchts read <url>`**: run the unlocker from the command line and print clean Markdown.
- **MCP tool `read_url(url)`**: expose the unlocker to agents (Claude, Cursor, and others) so they can read any page directly.
- **Per-domain backend memory**: remembers which tier worked for each domain and tries it first; disable with `SEARCHTS_NO_MEMORY=1`.
- **Human-in-the-loop CAPTCHA**: on an interactive challenge, hand off to your real browser to solve once.
- **Read and search across sources**: web (any URL), search (Exa), GitHub, YouTube, Reddit, Twitter/X, LinkedIn, and RSS.

## Use as a library

```python
from searchts import unlocker

r = unlocker.fetch("https://example.com")
print(r.backend, r.status, len(r.text))
print(r.text)
```

## MCP

`searchts` ships an MCP server (`searchts/integrations/mcp_server.py`) that exposes `read_url(url)`. Point your MCP-capable client at it to give the agent a one-call web reader backed by the full unlocker ladder.

## How it works, and its limits

- It runs from your own residential IP at personal volume, which is why it needs no paid proxy pool. It is a personal-grade research tool, not a mass-scraping system.
- Interactive CAPTCHAs (DataDome / Turnstile press-and-hold) are the honest ceiling. Use `--human` for those.
- Anti-bot systems evolve; this is an arms race and the techniques may need occasional updates.
- Respect each site's terms of service and use responsibly.

## Configuration

Optional API keys, via `searchts configure` or a `.env` file (see `.env.example`):

- **Exa** for web search (free tier available)
- **GitHub token** for higher rate limits
- **Groq / OpenAI** for video transcription

Run `searchts doctor` to check what is configured and working.

## Credits

`searchts` builds on and extends [Agent-Reach](https://github.com/Panniantong/Agent-Reach) (MIT), reusing its channel, installer, and diagnostics architecture. The escalating open-source unlocker, per-domain backend memory, human-in-the-loop CAPTCHA flow, the `read_url` MCP tool, and the `read` CLI command are additions in `searchts`. Thanks to the original authors.

## License

MIT. See [LICENSE](LICENSE). Original portions Copyright (c) 2025 Agent Eyes; modifications and additions Copyright (c) 2026 capad-xyz.
