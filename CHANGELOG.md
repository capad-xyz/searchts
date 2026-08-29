# Changelog

All notable changes to searchts are documented here. This project follows semantic versioning.

## [0.8.0](https://github.com/capad-xyz/searchts/compare/v0.7.2...v0.8.0) (2026-08-28)


### Added

* **bench:** P3.7 walled scorecard with honest per-suite pass rates ([#111](https://github.com/capad-xyz/searchts/issues/111)) ([b13ca30](https://github.com/capad-xyz/searchts/commit/b13ca3015088676bdd1677ff2dc5f1660f958139))
* **bench:** TTY Rich scorecard with per-case stderr ticks ([#113](https://github.com/capad-xyz/searchts/issues/113)) ([7517c4b](https://github.com/capad-xyz/searchts/commit/7517c4b482cb1386c9f0bba91a96a32125ff3ac4))
* **cli:** doctor progress ticks ([#103](https://github.com/capad-xyz/searchts/issues/103)) ([c28daab](https://github.com/capad-xyz/searchts/commit/c28daabd2a6f6010f5586fe563fb5e1b48e8b1bc))
* **cli:** P4.6 phase ticks for transcribe/grab/get ([#109](https://github.com/capad-xyz/searchts/issues/109)) ([adabfc8](https://github.com/capad-xyz/searchts/commit/adabfc8d874d6ef8fb84d124afc519a0cbfa1ac1))
* **cli:** P4.6 search progress ticks ([#110](https://github.com/capad-xyz/searchts/issues/110)) ([3c36dca](https://github.com/capad-xyz/searchts/commit/3c36dcaffeb3e5962ed9d6e5a602cb1ab5f9ac01))
* **cli:** progress ticks on read + mcp serve banner ([#100](https://github.com/capad-xyz/searchts/issues/100)) ([5ab2c81](https://github.com/capad-xyz/searchts/commit/5ab2c81c52e94f69c69677e3c7357a4094de21fe))
* **install:** write user-scope reach rule for Claude and Cursor ([#86](https://github.com/capad-xyz/searchts/issues/86)) ([76ce119](https://github.com/capad-xyz/searchts/commit/76ce119fc4d6f144fa6b92cdd056e383d2a2f3ba))
* **mcp:** MCPServer on mcp 2.x (P2.3) ([#98](https://github.com/capad-xyz/searchts/issues/98)) ([afbe15a](https://github.com/capad-xyz/searchts/commit/afbe15a716efb7ec8b2b229dd9e5101319853306))
* **mcp:** tell agents to retry walled hits via read_url ([#88](https://github.com/capad-xyz/searchts/issues/88)) ([1c03d0e](https://github.com/capad-xyz/searchts/commit/1c03d0ee519087a10da37939434ac2e56db55ffd))


### Fixed

* **bench:** ladder ticks during a long case ([#114](https://github.com/capad-xyz/searchts/issues/114)) ([e80c0c3](https://github.com/capad-xyz/searchts/commit/e80c0c3ff1a69235b46d13cfaa4b2f3f3aef91a4))
* **benchmark:** thin content is not a pass; label smoke suite ([#79](https://github.com/capad-xyz/searchts/issues/79)) ([9dc6af4](https://github.com/capad-xyz/searchts/commit/9dc6af401f824384311c202475ec6b68b57d6ba0))
* **channels:** drop routing theater; doctor is a probe ([#85](https://github.com/capad-xyz/searchts/issues/85)) ([e5e32b1](https://github.com/capad-xyz/searchts/commit/e5e32b139ae30a5721da6e27386af3f112811db7))
* **config:** drop dead knobs; load .env without override ([#81](https://github.com/capad-xyz/searchts/issues/81)) ([3b4f333](https://github.com/capad-xyz/searchts/commit/3b4f33361c8f34159346b79c576015621200495d))
* **config:** environment variables beat YAML ([#82](https://github.com/capad-xyz/searchts/issues/82)) ([02463b9](https://github.com/capad-xyz/searchts/commit/02463b997b92644d22b9d680edeea3cf92bd9f3c))
* **deps:** pin curl_cffi, trafilatura, and ddgs ([#83](https://github.com/capad-xyz/searchts/issues/83)) ([c365dbc](https://github.com/capad-xyz/searchts/commit/c365dbcb0407885680b1c4f7a2fe23b594de29fb))
* **doctor:** honest stealth probe; stop skill install side effect ([#74](https://github.com/capad-xyz/searchts/issues/74)) ([102a94c](https://github.com/capad-xyz/searchts/commit/102a94cf1a3f4e0fd22edc179742145f429907a9))
* **mcp:** SSRF guards on MCP URL tools ([#105](https://github.com/capad-xyz/searchts/issues/105)) ([545ea35](https://github.com/capad-xyz/searchts/commit/545ea35c9961bcd5a19dfa94aa91a26d7e966538))
* **release:** fail if RELEASE_PLEASE_TOKEN is missing ([#84](https://github.com/capad-xyz/searchts/issues/84)) ([0fdeed0](https://github.com/capad-xyz/searchts/commit/0fdeed00a987ab776576d5d92c023b0e315d386c))
* **skill:** keep SKILL.md description under 1024 chars ([#89](https://github.com/capad-xyz/searchts/issues/89)) ([403ac8d](https://github.com/capad-xyz/searchts/commit/403ac8db55493fadb9307e56d851a0a90f62996a))
* **unlocker:** domain memory TTL and unpin on failure ([#102](https://github.com/capad-xyz/searchts/issues/102)) ([f565ee0](https://github.com/capad-xyz/searchts/commit/f565ee006a04dd0fcb9b908e9ddbca056d27acf2))
* **unlocker:** drop hardcoded Chrome 126 UA ([#104](https://github.com/capad-xyz/searchts/issues/104)) ([08515f0](https://github.com/capad-xyz/searchts/commit/08515f03409d037f9bbfab7c981f45e4353872e8))
* **unlocker:** fail loud on thin and challenge pages ([#93](https://github.com/capad-xyz/searchts/issues/93)) ([89fbb5e](https://github.com/capad-xyz/searchts/commit/89fbb5e01468be43e8bd1a8ff39943c2797f7e56))
* **unlocker:** login shells are not a pass ([#116](https://github.com/capad-xyz/searchts/issues/116)) ([fcac810](https://github.com/capad-xyz/searchts/commit/fcac8106547d2d730b07fd21360591302acf4788))
* **unlocker:** P3.5 Jina opt-out (default on) ([#107](https://github.com/capad-xyz/searchts/issues/107)) ([2013a4b](https://github.com/capad-xyz/searchts/commit/2013a4ba0e071984f1d3bdfdfd0f1ab345c2b357))
* **unlocker:** Playwright off asyncio for MCP (P3.10) ([#96](https://github.com/capad-xyz/searchts/issues/96)) ([2809ac7](https://github.com/capad-xyz/searchts/commit/2809ac76b6d1baef358225dff23778fc9453a254))

## [Unreleased]


### Added
- **unlocker(login-wall):** extracted Sign in / Join now shells (LinkedIn `/feed/` login chrome, "sign in to continue") are a fail, not a pass above `_MIN_CHARS`. Bare nav "Log in" on a real page is not a wall.
- **docs(install):** pipx keep / uvx try + MCP serve / pip labeled venv-only (F8).
- **bench(progress):** `run_case` passes `progress=` through to `unlocker.fetch`, so a long case prints ladder ticks (`trying curl_cffi…`) as well as the case name. `--json` still stays quiet.
- **bench(scorecard):** render the scorecard through Rich on a TTY so tables align and `**100%**` is not a literal string. `--json` and piped stdout stay raw; `--plain` forces raw markdown on a TTY; `--out DIR` always writes plain markdown (no Rich markup) so committed scorecards stay diffable. Per-case stderr ticks show live progress on an interactive TTY and stay silent for `--json` / piped runs.
- **cli(progress):** phase ticks for the long media verbs so they never look hung (P4.6). `transcribe` prints `fetching subtitles…` → (`downloading audio…`) → `transcribing…`; `get` prints `fetching asset…` → `saving asset…`; `grab` prints `fetching page…` → `downloading assets…`; `fetch_bytes` prints `trying <rung>…` per ladder rung. All go to **stderr** best-effort (never break pipeable stdout / MCP), follow `SEARCHTS_PROGRESS=1`, and stay quiet for `--json` / library / MCP callers. ([#109](https://github.com/capad-xyz/searchts/pull/109))
- **cli(progress):** a single best-effort stderr tick for `check-update` and `watch` before their GitHub round-trip (P4.6 audit of the other verbs). ([#109](https://github.com/capad-xyz/searchts/pull/109))
- **bench(walled):** split the benchmark into two honest suites — `smoke` (open pages, the existing default set) and `walled` (Reddit hot + a public comments thread, the LinkedIn login wall, a Cloudflare-fronted vendor site, a DataDome-class site, X, and Booking). `Case.suite` tags each case; `load_cases(suite=)` and `python -m benchmarks.run --suite smoke|walled|all` filter them; the scorecard renders a **separate** pass rate per suite and reports the walled rate truthfully (failures are expected, never a fake 100%). `docs/scorecard.md` keeps the committed smoke numbers and documents how to measure the walled suite from a residential IP. (P3.7)


## [0.7.2](https://github.com/capad-xyz/searchts/compare/v0.7.1...v0.7.2) (2026-08-04)


### Fixed

* **share:** capture full Grok share ids and read Perplexity Pages ([#71](https://github.com/capad-xyz/searchts/issues/71)) ([7106ed1](https://github.com/capad-xyz/searchts/commit/7106ed19e5d69fcff9fc14004281d2e1eb46da96))

## [0.7.1](https://github.com/capad-xyz/searchts/compare/v0.7.0...v0.7.1) (2026-08-04)


### Fixed

* **mcp:** cap the SDK below 2.0, which breaks the server on startup ([#60](https://github.com/capad-xyz/searchts/issues/60)) ([607db0a](https://github.com/capad-xyz/searchts/commit/607db0ad32844091944f8dc9ff8bca1996b29e30))
* **unlocker:** read ChatGPT /s/ shares and stop soft walls swallowing --human ([#68](https://github.com/capad-xyz/searchts/issues/68)) ([9057628](https://github.com/capad-xyz/searchts/commit/905762840dac613da2c492fe360b4a3beac9c0e7))

## [0.7.0] - 2026-07-31

### Added
- **AI-chat share links now read as complete conversations.** Share pages (`chatgpt.com/share`, `claude.ai/share`, `poe.com/s`, and others) are SPAs whose conversation never reaches the DOM as extractable text, so the generic ladder returned a thin shell or a partial render cut mid-chat. A tier-0 share-extractor step ahead of the ladder decodes each provider's own data channel into full conversation markdown. Eight providers are supported: ChatGPT, Claude, Poe, Grok, Gemini, DeepSeek, Perplexity, and Copilot.
  - Grok and Gemini go through keyless APIs the Chrome-impersonated fetch clears without a browser (Grok's `share_links` JSON endpoint; Gemini's WIZ `batchexecute` RPC).
  - DeepSeek, Perplexity, and Copilot are JS shells (DeepSeek serves a 202 anti-bot stub), so they use a lazy patchright render that mirrors the stealth tier's fingerprint, waits for a provider ready-selector, auto-scrolls until scroll height stabilizes to defeat list virtualization, and expands collapsed sections.
  - Extractors are auto-discovered plugin modules, so adding a provider is a single new file.
- `FetchResult` now carries normalized response `headers`. Thanks to @terminalchai (#39).
- Cloudflare challenge detection, so a challenge page is classified rather than returned as content. Thanks to @terminalchai (#40).
- A CDN challenge test matrix. Thanks to @terminalchai (#35).

### Fixed
- The CLI exits cleanly on Ctrl+C and on a closed pipe. Both previously escaped as a traceback: Ctrl+C exited `3221225786` on Windows instead of the conventional `130`, and piping into `head`/`less` printed an `Exception ignored ... BrokenPipeError` during interpreter shutdown, which contradicted the pipeable-stdout design of `read`. Now `130` and `141` with no traceback.
- Cleared 11 outstanding mypy findings. None were live defects; the notable one was `probe_command` returning `None` for a negative `retries`, which its `-> ProbeResult` signature forbids.

### CI
- Ruff now runs in CI and the tree is clean against it, closing a gap where the linter was configured in `pyproject.toml` but never enforced (53 findings had accumulated). Thanks to @terminalchai (#45, closes #44).
- mypy is gated the same way, closing the equivalent gap for type checking.
- Both linters pin through `constraints.txt`, so a new release cannot turn `main` red on an unrelated PR.
- `server.json` is republished to the MCP registry on tag push, so downstream indexes (PulseMCP, Forge, Glama) pick up new versions automatically.

### Docs
- Documented AI-chat share reading and added an `ai-share` benchmark category.
- A block-phrase guide in `CONTRIBUTING.md`. Thanks to @terminalchai (#30).
- Scorecard results are explained. Thanks to @terminalchai (#36).

## [0.6.0] - 2026-07-09

### Added
- `read --json` and MCP `read_url` now carry two source-receipt fields — `fetched_at` (ISO-8601 UTC timestamp of the successful fetch) and `final_url` (the URL after redirects) — so an agent can cite *what* it read, *when*, and the post-redirect source. `final_url` is tracked through every unlocker backend (and correctly reports the requested URL for the Jina relay, not the `r.jina.ai` wire URL). Thanks to @tapheret2 (#25, closes #24).
- Challenge-page detection for Fastly Bot Management, Akamai/EdgeSuite error interstitials, and an additional Cloudflare ("checking if the site connection is secure") phrasing. Thanks to @tapheret2 (#26).
- Two benchmark cases — `python-docs` (server-rendered stdlib docs) and `httpbin-html` (an always-up HTML fixture). Thanks to @tapheret2 (#27).
- `searchts doctor` now reports whether searchts is registered with the local AI agents it detects (Claude Code, Claude Desktop, Cursor, Codex, and the `/searchts` skill), and prints the one-liner to wire it in when it isn't (#21).
- The benchmark scorecard now breaks out per-category pass rates. Thanks to @terminalchai (#23).

### Changed
- MCP `read_url` now returns a JSON source-receipt object (`{url, final_url, fetched_at, backend, status, chars, text}`) instead of a bare markdown string; the page markdown is under `text`, with the prompt-injection warning/fence preserved inside it. This aligns `read_url` with the JSON-returning `fetch_asset`/`grab_site` tools and with `read --json`.

## [0.5.2] - 2026-07-07

### Added
- `server.json` and a README ownership marker so searchts can be published to the official MCP registry (registry.modelcontextprotocol.io).
- The `version-sync` CI gate now also covers `server.json`.

### Fixed
- README images and links use absolute URLs so the demo GIFs and doc links render on PyPI (#19).

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
