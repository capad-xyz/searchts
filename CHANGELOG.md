# Changelog

All notable changes to searchts are documented here. This project follows semantic versioning.

## [0.5.1] - 2026-07-07

### Added
- The CLI suggests the nearest command on a typo (e.g. `searchts reserch ...` → "did you mean 'search'?"). Thanks to @terminalchai for the first community contribution (#16, closes #14).

### Docs
- Published an unlocker benchmark scorecard ([`docs/scorecard.md`](docs/scorecard.md)) and a "Does it actually work?" section in the README.

## [0.5.0] - 2026-07-07

### Added
- MCP `get_status` is now a first-class, documented tool (a module-level function, so it is unit-tested like the others).
- `docs/mcp.md`: a reference for the MCP server surface — the five tools, their inputs/outputs, wiring, and MCP-vs-CLI trade-offs.
- Reproducible unlocker benchmark (`python -m benchmarks.run`): a scorecard of how often searchts reads a set of (often bot-walled) pages and which tier carried each read.
- Public `ROADMAP.md`, GitHub issue/PR templates, and a `CONTRIBUTING.md` "what we merge (and what we don't)" section.
- `glama.json` and a `Dockerfile` so the MCP server can be claimed and deployed on Glama.
- `version-sync` CI job that fails if the version in `pyproject.toml` and `searchts/__init__.py` drift apart.

### Changed
- All five MCP tool descriptions rewritten (purpose, when-to-use, behaviour, parameter semantics) for agent clarity.
- `web_search` clamps `max_results` to 1–25.
- `config/mcporter.json` now includes searchts's own MCP server entry, not only Exa.

## [0.4.1] - 2026-06-24

### Added
- 13 interstitial block-page markers for more anti-bot vendors (Imperva/Incapsula, DataDome, PerimeterX/HUMAN, F5/Shape, Akamai, Vercel, Sucuri, Queue-it, Radware, Kasada, Arkose, and Cloudflare's managed challenge), so a 200/202/302 challenge page escalates instead of being accepted as content. Matches challenge-page copy, never vendor sensor-JS names.

## [0.4.0] - 2026-06-22

### Added
- On-demand asset + design-inspiration grabber: `searchts grab <url>` (a page's images/icons/css/fonts plus a colour palette and the fonts in use, with a manifest) and `searchts get <url>` (a single asset), plus `fetch_asset` and `grab_site` MCP tools. Assets go through the same escalating unlock ladder, so fingerprint-gated CDNs come through.

### Fixed
- AWS WAF challenge pages (HTTP 202 shells) are now detected and escalated instead of accepted as content; the stealth path rejects empty/thin bodies and requires real rendered content before succeeding.

### Changed
- Skill routing rule: route by intent, not domain — a content/summary request maps to `read` (even on a design site), while `grab`/`get` are only for the assets themselves.

## [0.3.1] - 2026-06-19

### Changed
- Realigned the bundled skill, docs, and MCP docstring to center the first-party verbs (`read` / `search` / `transcribe`) instead of the legacy "call upstream tools directly" model.
- `searchts install` is non-invasive by default; system-package and Node installs are gated behind explicit flags.
- CLI output is plain ASCII (`[ok]` / `[x]` / `[!]`) instead of emoji.

## [0.3.0] - 2026-06-18

### Fixed
- Probe timeouts no longer crash with a `NameError`.
- On Windows, yt-dlp's JS-runtime config is read from `%APPDATA%` instead of a hardcoded POSIX path.
- Transcription readiness reporting no longer demands `ffmpeg` when local Whisper captions suffice.

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
