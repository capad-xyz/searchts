# CLAUDE.md

## Project
searchts — Python CLI + library + MCP server + Claude Code skill that gives an AI
agent first-party web superpowers via three commands:
- `searchts read <url>` — escalating open-source unlocker (curl_cffi browser-fingerprint
  fetch -> Jina Reader -> patchright stealth browser) that returns clean markdown and
  gets through most bot-walls, keyless, on your own IP.
- `searchts search "<query>"` — keyless multi-provider web search with reciprocal-rank
  fusion (DuckDuckGo default; optional SearXNG/Exa/Brave/Tavily).
- `searchts transcribe <url>` — subtitles-first video transcription (existing captions
  via yt-dlp need no key; falls back to hosted or keyless-local Whisper) for
  YouTube/TikTok/Instagram/Reddit.
- `searchts grab <url>` / `searchts get <url>` — on-demand asset + design-inspiration
  grabber: download a page's images/icons/css/fonts (or one asset file) through the same
  escalating unlock ladder, and extract a color palette + the fonts in use.
Surfaces: CLI, MCP server (tools: read_url, web_search, fetch_asset, grab_site), and a /searchts Claude Code skill.
Keyless and free by default. OPTIONAL: separately-installed platform CLIs (gh, twitter-cli,
opencli, mcporter) let it also reach GitHub/Twitter/Reddit/LinkedIn, and `searchts doctor`
reports them — but those are optional add-ons, not the core.
Repo: github.com/capad-xyz/searchts | License: MIT | Version: 0.4.1

## Commands
- `pip install -e .` — Dev install
- `pytest tests/ -v` — All tests
- `pytest tests/test_cli.py -v` — CLI tests only
- `bash test.sh` — Full integration test (creates venv, installs, runs doctor + channel tests)
- `python -m searchts.cli doctor` — Run diagnostics
- `python -m searchts.cli install --env=auto` — Auto-configure

## Structure
- `searchts/cli.py` — CLI entry point (argparse)
- `searchts/core.py` — Core read/search routing logic
- `searchts/config.py` — Config management (YAML, env vars)
- `searchts/doctor.py` — Diagnostics engine
- `searchts/channels/` — One file per platform (twitter.py, reddit.py, youtube.py, etc.)
- `searchts/channels/base.py` — Base channel class (all channels inherit from this)
- `searchts/integrations/mcp_server.py` — MCP server integration
- `searchts/skill/` — OpenClaw skill files
- `searchts/guides/` — Usage guides
- `tests/` — pytest tests
- `config/mcporter.json` — MCP tool config

## Conventions
- Python 3.10+ with type hints
- The web reading/search/transcription logic lives in `unlocker.py`, `search.py`,
  and `transcribe.py`; the CLI verbs in `cli.py` call them directly.
- `channels/` today mainly powers `searchts doctor` health checks: only the web
  channel implements `read()`, only the 4 video channels (youtube, tiktok,
  instagram, redditvideo) implement `transcribe()`, and `can_handle()` is NOT used
  for routing. Do not assume a channel-routing contract — there isn't one.
- Each channel is a single file in `channels/`, inherits from `BaseChannel`.
- Use `loguru` for logging, `rich` for CLI output
- Commit format: `type(scope): message` (one commit = one thing)
- Optional platform integrations go through their public CLI/API, never hack internals

## Rules
- NEVER modify upstream open source projects' source code
- Version in THREE places must match: `pyproject.toml`, `__init__.py`, `tests/test_cli.py`
- Always new branch for changes, PR to main, never push to main directly
- Run `pytest tests/ -v` before committing — all tests must pass
- Cookie-based auth (Twitter): use Cookie-Editor export method only, no QR scan
