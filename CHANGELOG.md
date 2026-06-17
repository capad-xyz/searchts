# Changelog

All notable changes to this project will be documented in this file.

---

## [1.1.0] - 2025-02-25

### New Channels

#### LinkedIn
- Read person profiles, company pages, and job details via [linkedin-scraper-mcp](https://github.com/stickerdaniel/linkedin-mcp-server)
- Search people and jobs via MCP, with Exa fallback
- Fallback to Jina Reader when MCP is not configured

### Improvements

- `searchts doctor` now detects the LinkedIn channel
- CLI: added `search-linkedin` subcommand
- Updated install guide with setup instructions for the new channel

---

## [1.0.0] - 2025-02-24

### Initial Release

- 8 channels: Web (Jina Reader), Search (Exa), GitHub, YouTube, Reddit, Twitter/X, LinkedIn, RSS
- CLI with `read`, `search`, `doctor`, `install` commands
- Unified channel interface — each platform is a single pluggable Python file
- Auto-detection of local vs server environments
- Built-in diagnostics via `searchts doctor`
- Skill registration for Claude Code / OpenClaw / Cursor
