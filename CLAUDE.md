# CLAUDE.md

## Project
searchts — Python CLI + library that gives AI agents read/search access to 8 platforms.
Positioning: installer + doctor + config tool. NOT a wrapper — after install, agents call upstream tools directly.
Repo: github.com/capad-xyz/searchts | License: MIT | Version: 0.3.0

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
- Each channel is a single file in `channels/`, inherits from `BaseChannel`
- Channel contract: must implement `can_handle(url)`, `read(url)`, `search(query)`, `check()` methods
- Use `loguru` for logging, `rich` for CLI output
- Commit format: `type(scope): message` (one commit = one thing)
- All upstream tool calls go through public API/CLI, never hack internals

## Rules
- NEVER modify upstream open source projects' source code
- searchts is a "glue layer" — only route and call, don't reimagine
- Version in THREE places must match: `pyproject.toml`, `__init__.py`, `tests/test_cli.py`
- Always new branch for changes, PR to main, never push to main directly
- Run `pytest tests/ -v` before committing — all tests must pass
- Cookie-based auth (Twitter): use Cookie-Editor export method only, no QR scan
