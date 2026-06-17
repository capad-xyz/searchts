# Changelog

All notable changes to searchts are documented here. This project follows semantic versioning.

## [0.2.1] - 2026-06-18

### Added
- Tag-triggered PyPI auto-publish via GitHub Actions Trusted Publishing (OIDC, no stored token): push a `vX.Y.Z` tag and the release is built and published automatically.

### Docs
- README quickstart for `pipx install` and one-command agent wiring; clarified that search is keyless by default.

## [0.2.0] - 2026-06-18

### Added
- Multi-provider web search (`searchts search`) with reciprocal rank fusion and URL de-duplication: DuckDuckGo (keyless default), plus SearXNG, Exa, Brave, and Tavily when configured.
- Prompt-injection scrubbing of fetched and searched content: strips invisible/bidi characters, flags injection indicators, and optional redaction (`read --scrub`).
- Video transcription for TikTok, Instagram, and Reddit videos (mirroring YouTube): yt-dlp audio plus Whisper.
- One-command agent wiring: `searchts mcp serve|install` (MCP server exposing `read_url` and `web_search`) and `searchts skill install` (a Claude Code `/searchts` slash command).

### Fixed
- Wheel packaging gate in CI no longer requires a removed directory.

## [0.1.0] - 2026-06-17

### Added
- Initial release of searchts: an escalating open-source web unlocker (curl_cffi browser-fingerprinted fetch, then Jina Reader, then a patchright stealth browser) with `trafilatura` content extraction and phrase-based block detection.
- `searchts read <url>` CLI, an MCP `read_url` tool, and a Python library API.
- Per-domain backend memory and a human-in-the-loop CAPTCHA handoff.
- Read, search, and transcribe across web, search, GitHub, YouTube, Reddit, Twitter, LinkedIn, and RSS.
- Built on and extending [Agent-Reach](https://github.com/Panniantong/Agent-Reach) (MIT); see Credits in the README.
