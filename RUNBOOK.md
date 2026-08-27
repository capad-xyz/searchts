# searchts Runbook

Operational guide for running, developing, and shipping `searchts` - a local,
keyless "unlocker" that reads bot-walled web pages as clean Markdown, searches
the web across several providers, transcribes videos, and grabs page assets. It
ships as one console script (`searchts`), a stdio MCP server, and a Claude Code
slash command. Status: released and published to PyPI (version 0.7.0, see
`pyproject.toml`), CI green on `main`, releases automated with release-please.
This file is the operational layer: `README.md` explains what the tool does,
`CONTRIBUTING.md` covers PR etiquette, `CLAUDE.md` holds the agent conventions,
and `docs/` holds install/MCP/troubleshooting detail. Read those for "what";
read this for "how do I get it running again".

## Stack

- Language: Python, `requires-python = ">=3.10"` (`pyproject.toml`).
- CI test matrix: 3.10 / 3.11 / 3.12 / 3.13 on ubuntu-latest, plus macos-latest
  3.12 and windows-latest 3.12. Lint and typecheck jobs run on 3.12
  (`.github/workflows/pytest.yml`).
- Local dev venv on this machine: `.venv` at the repo root, Python 3.12.8.
- Build backend: `hatchling` (`[build-system]` in `pyproject.toml`); wheel packs
  the `searchts` package only.
- Package manager: plain `pip`. There is NO lockfile - `constraints.txt` is the
  pinned tested dependency set and every CI job installs through it with
  `pip install -c constraints.txt`. `uv.lock` is explicitly gitignored; there is
  no Poetry or PDM config.
- Runtime deps (`pyproject.toml`): requests, feedparser, python-dotenv, loguru,
  pyyaml, rich, yt-dlp, curl_cffi, trafilatura, ddgs.
- Optional extras: `browser` (patchright), `cookies` (browser-cookie3), `mcp`
  (mcp[cli]), `local-transcribe` (faster-whisper), `all`, `dev` (pytest, ruff,
  mypy, type stubs).
- Database: none. No server, no daemon, no port - the MCP server speaks stdio
  JSON-RPC over the pipe the agent opens (`searchts mcp serve`).
- Lint / typecheck: ruff (`[tool.ruff]`, target py310, line-length 100, rules
  E/F/I) and mypy (`[tool.mypy]`, python_version 3.10, `exclude = ["^tests/"]`).
- Release automation: release-please + PyPI Trusted Publishing (OIDC) + MCP
  registry republish (`.github/workflows/`).

## Prerequisites

Author's machine is Windows 11, PowerShell primary, Git Bash available.

- Python 3.10-3.13. 3.12 is the version everything is tested on. Install from
  python.org or `winget install Python.Python.3.12`. Note the system `python` on
  this machine is 3.14.5, which is OUTSIDE the CI matrix - create the venv with
  an explicit 3.12 interpreter rather than whatever `python` resolves to.
- Git.
- No Docker, WSL, Rust toolchain, Android SDK, or Visual C++ build tools are
  required for the core: every runtime dependency ships prebuilt wheels on
  Windows/CPython 3.10-3.13.
- Optional, only for the stealth-browser tier: `pip install "searchts[browser]"`
  plus a Chromium downloaded by patchright (`patchright install chromium`).
  Nothing in the codebase installs or checks for that binary.
- Optional, only for audio transcription when a video has no captions: `ffmpeg`
  on PATH (`winget install Gyan.FFmpeg`). Verified present on this machine at
  `%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg...\bin\ffmpeg.exe`.
  Captions-only transcription needs neither ffmpeg nor a key.
- `yt-dlp` does NOT need to be on PATH: it ships as a dependency and is invoked
  as `python -m yt_dlp` when the module is importable
  (`searchts/transcribe.py`).
- Optional, for keyless local Whisper: `pip install "searchts[local-transcribe]"`.
  It runs CPU-only, hardcoded `device="cpu", compute_type="int8"`, default model
  `base`. UNVERIFIED: the model download location and size - searchts passes
  only the model name, so the cache path is whatever faster-whisper and
  huggingface_hub default to, and no size figure appears anywhere in the repo.
- Optional, only for YouTube: a JS runtime for yt-dlp - `deno` works as-is,
  `node` additionally needs `--js-runtimes node` in `%APPDATA%\yt-dlp\config`.
- Optional, only for agent wiring: the `claude` CLI (Claude Code) to register
  the MCP server.

## First-time setup

1. Clone the repo.

```bash
git clone https://github.com/capad-xyz/searchts.git
```

2. Enter it.

```bash
cd searchts
```

3. Create a virtualenv with an explicit Python 3.12 (do not rely on bare
   `python`, which is 3.14 on this machine).

```powershell
py -3.12 -m venv .venv
```

4. Activate it (PowerShell).

```powershell
.\.venv\Scripts\Activate.ps1
```

5. Install the package editable, against the tested dependency set CI uses.
   This is the exact command in `CLAUDE.md` and `CONTRIBUTING.md`.

```bash
pip install -c constraints.txt -e ".[dev]"
```

Success signal: `pip` ends with `Successfully installed ... searchts-0.7.0` and
`searchts version` prints `0.7.0`.

6. Confirm the console script resolves.

```bash
searchts version
```

7. Run the diagnostics. Best single "is it working" check, but note it is NOT
   read-only in text mode - it also writes the SKILL.md bundle into every
   detected agent skill directory. Use `searchts doctor --json` if you want a
   side-effect-free report.

```bash
searchts doctor
```

Success signal: a `searchts status` report ending in
`Status: N/11 channels available` plus an `Agent wiring` block. On this machine
it currently reports 6/11, with `[ok] Any web page` and the `/searchts` slash
command registered.

8. Optional - install the extras you actually want (skip if you only need
   `read` and `search`, which are keyless and need nothing extra).

```bash
pip install -c constraints.txt -e ".[all]"
```

9. Optional - download the stealth browser used by the third unlocker tier.

```bash
patchright install chromium
```

10. Optional - set any API keys you want. Do NOT copy `.env.example` to `.env`:
    nothing loads it (see Environment variables). Use `searchts configure` for
    the keys it supports, or export real environment variables.

```bash
searchts configure groq-key <redacted>
```

11. Smoke test the unlocker end to end (needs network).

```bash
searchts read https://example.com
```

Success signal: clean Markdown on stdout, with the backend that carried it
reported on stderr.

## Environment variables

Every variable is OPTIONAL. The core (`read`, `search`, `grab`, and
subtitles-first `transcribe`) is keyless by design and needs none of them.

READ THIS FIRST - a `.env` file does NOTHING. `python-dotenv` is a declared
dependency, but `load_dotenv` is never called anywhere in the package (verified:
zero matches for `dotenv` under `searchts/`). `.env.example` and `README.md`
both say to copy it to `.env`; that path is dead. Set real process environment
variables, or use `searchts configure`, which persists to
`~/.searchts/config.yaml` (on Windows `C:\Users\<you>\.searchts\config.yaml`).

Precedence is inverted from the usual convention (`searchts/config.py`, `get`):
the YAML config file wins, THEN the uppercased env var, then the default. So
once a key is in `config.yaml`, changing the environment variable has no effect.

| Name | Required? | What it is | Where to get it | Example / placeholder |
|------|-----------|------------|-----------------|-----------------------|
| `EXA_API_KEY` | No | Exa search provider key (free tier ~1000/month). Also readable from `config.yaml` as `exa_api_key` | https://exa.ai | `exa-<redacted>` |
| `BRAVE_API_KEY` | No | Brave Search provider. Env-only, no `configure` subcommand, missing from `.env.example` (`searchts/search.py`) | https://api-dashboard.search.brave.com | `<redacted>` |
| `TAVILY_API_KEY` | No | Tavily search provider. Env-only, missing from `.env.example` (`searchts/search.py`) | https://tavily.com | `tvly-<redacted>` |
| `SEARXNG_URL` | No | Base URL of a self-hosted SearXNG JSON API; the provider only activates when this is set. Env-only | Your own SearXNG instance | `http://localhost:8080` |
| `GROQ_API_KEY` | No | Hosted Whisper (`whisper-large-v3`) for `transcribe` when a video has no captions. `searchts configure groq-key <v>` | https://console.groq.com | `gsk_<redacted>` |
| `OPENAI_API_KEY` | No | Fallback hosted Whisper (`whisper-1`). `searchts configure openai-key <v>` | https://platform.openai.com | `sk-<redacted>` |
| `SEARCHTS_WHISPER_MODEL` | No | Local faster-whisper model size, default `base` | n/a | `small` |
| `WHISPER_MODEL` | No | Undocumented auto-generated twin of the `whisper_model` config key. It is consulted BEFORE `SEARCHTS_WHISPER_MODEL` and silently wins | n/a | `base` |
| `SEARCHTS_NO_MEMORY` | No | `1` disables the per-domain backend memory (`~/.searchts/unlocker_cache.json`) | n/a | `1` |
| `SEARCHTS_LANG` | No | Locale hint for `skill --install`: `en*` ships `SKILL_en.md`, else `SKILL.md`. Falls back to `LC_ALL` / `LC_MESSAGES` / `LANG` | n/a | `en_US` |
| `OPENCLAW_HOME` | No | If set, `$OPENCLAW_HOME/.openclaw/skills` is searched first when installing the SKILL.md bundle | n/a | `C:\Users\<you>` |
| `GITHUB_TOKEN` | No | Stored by `searchts configure github-token` and shown by `doctor`, but NO code path ever sends it in a request. Effectively cosmetic today | https://github.com/settings/tokens | `ghp_<redacted>` |
| `REDDIT_PROXY` | No | DEAD. Present in `.env.example` only; zero code references | n/a | n/a |
| `HTTP_PROXY` / `HTTPS_PROXY` | No | Never set or read by searchts itself. `docs/troubleshooting.md` tells YOU to export them before invoking the optional twitter/reddit CLIs | Your proxy | `http://user:<redacted>@host:port` |

Secrets that must never be committed: `EXA_API_KEY`, `BRAVE_API_KEY`,
`TAVILY_API_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY`, `GITHUB_TOKEN`, the Twitter
cookie values (`twitter_auth_token` / `twitter_ct0` in `config.yaml`), and any
credential embedded in a proxy URL. They live in the shell environment or in
`~/.searchts/config.yaml` - never in the tree. `.env` is gitignored, and no
`.env` or `~/.searchts/config.yaml` exists on this machine today, so searchts is
currently running fully keyless.

Note: `Config.save()` tries `os.open(..., 0o600)` and falls back to a plain
write on Windows, so `config.yaml` permissions are NOT enforced there - it
inherits the directory ACL.

CI secrets (GitHub Actions, not local): `RELEASE_PLEASE_TOKEN` - a fine-grained
PAT with contents + pull-requests write, used by
`.github/workflows/release-please.yml`. PyPI publishing and the MCP registry
push both use OIDC (Trusted Publishing / `mcp-publisher login github-oidc`) and
store no token.

## Running it

Everything is one console script: `searchts` (`[project.scripts]` maps it to
`searchts.cli:main`). There is no dev server and no port. `python -m searchts.cli <cmd>`
is an equivalent entry point.

Core verbs:

```bash
searchts read https://example.com
```

```bash
searchts search "open source vector db"
```

```bash
searchts transcribe https://youtu.be/VIDEOID
```

```bash
searchts grab https://example.com
```

```bash
searchts get https://example.com/logo.png
```

Diagnostics and maintenance: `searchts doctor` (add `--json`), `searchts setup`,
`searchts install`, `searchts configure`, `searchts check-update`,
`searchts watch`, `searchts version`, `searchts uninstall`.

MCP server (stdio, no port - the agent spawns it and talks over the pipe):

```bash
searchts mcp serve
```

Print the wiring for your agent client:

```bash
searchts mcp install
```

Register it with Claude Code:

```bash
claude mcp add searchts -- searchts mcp serve
```

Claude Code slash command (`/searchts <url | video url | query>`), which writes
`~/.claude/commands/searchts.md`:

```bash
searchts skill install
```

Tests. Scope them to `tests/` locally: bare `pytest -q` also collects the
gitignored `scratch/` directory and dies at collection time (see Common startup
failures). Verified on this machine: 411 passed, 8 skipped, ~35s.

```bash
pytest tests/ -q
```

Lint (CI gates on this):

```bash
ruff check searchts tests
```

Typecheck (CI gates on this):

```bash
mypy searchts
```

Full integration check (creates its own venv, installs, runs doctor - Bash only):

```bash
bash test.sh
```

Unlocker benchmark scorecard:

```bash
python -m benchmarks.run
```

## Common startup failures

`docs/troubleshooting.md` only covers twitter-cli proxies and documents none of
these. Symptoms below are literal strings from the source unless marked
otherwise; file references are where the string is produced.

| Symptom (literal) | Cause | Fix |
|-------------------|-------|-----|
| `ERROR collecting scratch/test_stealth.py` ... `ModuleNotFoundError: No module named 'agent_reach'`, then `Interrupted: 3 errors during collection` | Bare `pytest` also collects the gitignored `scratch/` dir, which holds pre-fork experiments importing the old `agent_reach` package. CI never sees it because `scratch/` is not committed | Run `pytest tests/ -q` (this is the command in `CLAUDE.md`). Expect 411 passed, 8 skipped |
| `The MCP server needs the optional "mcp" dependency. Install it with:` / `  pip install "searchts[mcp]"` (`searchts/integrations/mcp_server.py`) | `searchts mcp serve` without the `mcp` extra. In Claude Code this looks like an MCP server that dies the instant it connects | `pip install "searchts[mcp]"` |
| `all backends failed for <url> -> curl_cffi: challenge; Jina Reader: http-403; stealth-browser: RuntimeError: stealth-browser backend needs patchright: pip install patchright && patchright install chromium` (`searchts/unlocker.py`) | Top rung of the ladder is not installed, so nothing can beat a real bot-wall | `pip install "searchts[browser]"` then `patchright install chromium`. Nothing in the code installs the Chromium binary - it is a separate manual step |
| Same as above but with a patchright launch error instead of the ImportError | patchright is installed, the Chromium binary was never downloaded. No code checks for it, and `doctor` still advertises the tier | `patchright install chromium` |
| `[x] ffmpeg not found in PATH` (`searchts/transcribe.py` `_require`, printed by `cli.py`, exit 1) | Audio fallback needs ffmpeg (`compress_audio` and `chunk_audio` both shell out to it). Subtitle-based transcription does NOT | `winget install Gyan.FFmpeg`, then open a new shell so PATH refreshes |
| `[x] local transcription needs faster-whisper. Install it with:` / `  pip install "searchts[local-transcribe]"` (`searchts/transcribe.py`) | `--provider local`, or `auto` with no hosted key, without the extra | `pip install "searchts[local-transcribe]"` |
| doctor: `yt-dlp is installed but the JS runtime is not configured. Run:` followed by a multi-line PowerShell block (`searchts/channels/youtube.py` + `searchts/utils/paths.py`) | YouTube needs a JS runtime; node is on PATH but `--js-runtimes node` is not in the yt-dlp user config | Paste the emitted block into PowerShell - it is PowerShell syntax and will NOT run in cmd or Git Bash. Or append `--js-runtimes node` to `%APPDATA%\yt-dlp\config` |
| `The command exists but cannot execute -- usually the venv interpreter went missing after a system Python upgrade. Reinstall to fix:` / `  uv tool install --force <pkg>` / `or: pipx reinstall <pkg>` (`searchts/probe.py`) | A pipx/uv shim survives but its interpreter is gone; exec raises, or the shell returns 126/127. Wrapped per-tool for yt-dlp, gh, twitter-cli, mcporter, opencli, rdt | Reinstall that tool as the message says |
| Ctrl+C prints a full traceback and the shell reports exit code `3221225786` (`STATUS_CONTROL_C_EXIT`) | Pre-0.7.0 build without the signal handling from commit `5cf4ecc` | Upgrade. Current behaviour is `[!] Interrupted` on stderr and exit 130 |
| `Exception ignored ... BrokenPipeError` when piping, e.g. `searchts read <url> \| head` | Same vintage. Python re-raises on shutdown flush | Upgrade. Current behaviour is a silent exit 141 |
| Mojibake or `UnicodeEncodeError` in the console | `_ensure_utf8_console()` (`searchts/cli.py`) only rewraps stdout on win32 and is wrapped in a bare `try/except: pass`, so a failed patch degrades silently on a cp1252 console | `set PYTHONUTF8=1`, or `chcp 65001` before running |
| `error: externally-managed-environment` | PEP 668. Documented in `docs/install.md` and `docs/update.md` | Install with `pipx`, or create a venv first |
| `python3` opens the Microsoft Store instead of running Python | Windows Store app alias at `%LOCALAPPDATA%\Microsoft\WindowsApps\python3.exe`. Called out in `docs/install.md` | Use `py -3` (or `py -3.12`) everywhere instead of `python3` |
| MCP server registered but the agent cannot spawn it | `searchts` is inside `.venv\Scripts\` and is not on the agent's PATH. `searchts mcp install` warns to use `uvx --from "searchts[mcp]" searchts mcp serve` or `pipx which searchts` when the host cannot see the pipx bin. | `uvx` one-shot, or `pipx install "searchts[mcp]"` then register that path |
| doctor: `[!]  Claude Code (MCP) - detected, but searchts is NOT registered` | Installed on PATH is not the same as legible to the agent | `claude mcp add searchts -- searchts mcp serve`, and/or `searchts skill install` |
| `Search failed for '<query>'` with `  duckduckgo: ImportError: duckduckgo needs the 'ddgs' package: pip install ddgs` | `ddgs` is a declared runtime dependency but is NOT pinned in `constraints.txt`; a partial or skipped install leaves it out | `pip install ddgs` |
| `  searxng: RuntimeError: SEARXNG_URL not set` (also `EXA_API_KEY not set`, `BRAVE_API_KEY not set`, `TAVILY_API_KEY not set`) | `--provider <name>` named a keyed provider with no key configured | Set the env var, or drop `--provider` and use the keyless DuckDuckGo default |
| `  duckduckgo: no-results` and the whole search fails | DuckDuckGo is rate-limiting your IP | Wait and retry, or configure a second provider |
| `searchts install --env=auto` prints a list of commands and changes nothing | Since commit `668445b` the installer is non-mutating by default; `--safe` is a documented no-op | Re-run with `--system-deps` (alias `--apply`) if you actually want it to touch the system |
| `Failed to grab <url>` with `challenge unsolved or thin content`, on a page `searchts read` handles fine | The asset path requires >= 8000 chars of rendered HTML before accepting a page (`searchts/assets.py`); `read` only requires 500 | Use `searchts read`, or retry with requests spaced out |
| Reads succeed individually, then start failing in a rapid batch | AWS WAF rate-limits a flagged IP under back-to-back headless hits - about 6 requests in 10s trips it (`DEVLOG.md`, confirmed against Dribbble) | Space requests roughly 15s apart |
| A URL that used to work now fails on the first tier every time | Per-domain backend memory in `~/.searchts/unlocker_cache.json` pins the last winner to the front of the ladder, and all cache IO swallows exceptions so corruption is invisible | Set `SEARCHTS_NO_MEMORY=1`, or delete `~/.searchts/unlocker_cache.json` |
| `--human` "does nothing" - no browser opens | Fixed in 0.7.1. Before that the headful fallback only fired when the failure reason was exactly `challenge` or started with `http-403`, and any thin-but-real result returned ahead of it, so a login wall served as HTTP 200 (`thin-<n>b`) silently skipped the rung entirely (`searchts/unlocker.py`). It now runs whenever no tier returned clean content, and only wins if it got further. If patchright is missing, the browser cannot open and the automated best effort is returned instead | Upgrade to >= 0.7.1. If it still does not open, confirm patchright is installed (`searchts doctor`), then check the per-backend reasons on stderr |
| `bash test.sh` fails immediately on Windows | It does `python3 -m venv` and `source "$TEST_DIR/venv/bin/activate"`; Windows venvs put executables in `Scripts/` | Run it on Linux/macOS or in the container; on Windows use `pytest tests/ -q` instead |
| `[!] Could not check for updates (GitHub API rate limit, please try again later)` (`searchts/cli.py`) | Unauthenticated GitHub API is 60 requests/hour per IP | Wait, or ignore - it only affects `check-update` / `watch` |

Decoder ring for the per-backend reasons printed under `Failed to read <url>`
(`searchts/unlocker.py`):

- `no-response` - no status at all.
- `http-<n>` - any status >= 400 (403, 429, 503).
- `challenge` - a `cf-mitigated: challenge` header, or one of the block phrases
  matched in the first 8192 chars.
- `thin-<N>b` - real content, but under `_MIN_CHARS = 500`, so the ladder
  escalated.
- `unknown-backend` - a bad `--backend` value.
- `<ExcType>: <msg>` - any exception: missing patchright, DNS, TLS, timeout.

Two traps in the diagnostics themselves:

- `searchts doctor` is NOT read-only. In text mode it calls `_install_skill()`
  at the end and writes the SKILL.md bundle into every detected agent skill
  directory. `searchts doctor --json` returns before that and is side-effect
  free.
- `doctor` always reports the stealth-browser tier as available
  (`searchts/channels/web.py` returns `ok` unconditionally, no probe), so it
  cannot tell you whether patchright or its Chromium are actually installed.

## Committing

- Default / integration branch: `main`. Remote: `origin`
  https://github.com/capad-xyz/searchts.git.
- Git identity configured for this repo (`.git/config`): `user.name = capad.fyi`,
  `user.email = capad.xyz@gmail.com`. The global identity is `capad.io` with the
  same email, so the repo-local override is deliberate - do not remove it.
- Branch naming seen in `git log` / local branches: `type/short-slug`, e.g.
  `feat/landing-site`, `fix/mypy-clean`, `docs/tagline-missing-layer`,
  `ci/hardening`, `chore/release-0.5.1`.
- Commit message style: conventional commits, `type(scope): message`, one commit
  per thing. Examples from history: `fix(cli): exit cleanly on Ctrl+C and broken
  pipe`, `ci(lint): pin ruff via constraints.txt`, `docs(readme): use pepy.tech
  downloads badge`.
- Only `feat`, `fix`, `perf` and `revert` cut a release. `ci`, `docs`, `test`,
  `refactor`, `build`, `style` and `chore` ride along with the next one
  (`CLAUDE.md`, `.release-please-config.json`).
- `CLAUDE.md` rule: always branch, PR to `main`, never push to `main` directly.
  PRs are squash-merged, so the PR TITLE must be a conventional commit - it
  becomes the commit on `main` and release tooling parses it.
- Git hooks: none installed (`.git/hooks` contains only `.sample` files). There
  is no husky, pre-commit, or lint-staged. Nothing blocks a commit locally, so
  run the three gates by hand before pushing:

```bash
ruff check searchts tests && mypy searchts && pytest -q
```

- Do NOT add `Co-Authored-By` trailers.
- Never hand-edit version numbers. release-please owns all four version sites
  (`pyproject.toml`, `searchts/__init__.py`, and `server.json` twice); the
  `version-sync` CI job fails the build if they drift.

## Deployment

There is no web deploy target. `searchts` ships as a Python package.

- Where: PyPI (`searchts`), a GitHub Release, and the official MCP registry
  listing `io.github.capad-xyz/searchts`.
- Trigger: pushing a `v*` tag runs `.github/workflows/release.yml`, which
  verifies the tag matches `pyproject.toml`, builds sdist + wheel, publishes to
  PyPI via Trusted Publishing (OIDC, no stored token), creates the GitHub
  Release with `softprops/action-gh-release`, then republishes `server.json` to
  the MCP registry with `mcp-publisher` (retried 3x for PyPI CDN propagation).
- How a release is actually cut: `.github/workflows/release-please.yml` runs on
  every push to `main` and keeps a standing release PR up to date. Merging that
  PR tags the release, which fires `release.yml`.
- Required deploy secrets: `RELEASE_PLEASE_TOKEN` (fine-grained PAT, contents +
  pull-requests write). Without it the tag is created with `GITHUB_TOKEN`, which
  cannot trigger another workflow, so nothing publishes - the workflow prints a
  `::warning::` telling you to re-push the tag.
- Rollback: PyPI does not allow re-uploading a version. Yank the bad release on
  PyPI and ship a new patch version; do not try to overwrite.
- A docs-only commit pushed to `main` triggers CI (`pytest.yml`) and the
  release-please job, but because `docs:` is not a release-cutting type it only
  updates the standing release PR. Nothing is published.

## Gotchas

- **`.env` is decoration.** See Environment variables. `python-dotenv` is
  installed and `.env.example` exists, but nothing calls `load_dotenv`. Either
  export real env vars or use `searchts configure`.
- **Config file beats environment variable.** `Config.get` checks
  `~/.searchts/config.yaml` first. If someone once ran `searchts configure
  groq-key ...`, exporting `GROQ_API_KEY` will not change anything.
- **Four knobs that do nothing.** `REDDIT_PROXY` (in `.env.example`, no code
  reads it), config `proxy` (`cli.py` even comments "nothing reads this key at
  runtime"), `youtube_cookies_from` (written, never read), and `github_token`
  (stored and reported by `doctor`, never sent in a request).
- **Never run `ruff format`.** `CLAUDE.md` and `CONTRIBUTING.md` both say so:
  the tree is deliberately not format-clean and it would rewrite most files.
  Only `ruff check` is a gate.
- **Never hand-edit a version.** release-please owns `pyproject.toml`,
  `searchts/__init__.py`, and two places in `server.json`. The `version-sync` CI
  job fails on any drift.
- **Editable-install metadata goes stale.** On this machine `searchts version`
  prints `0.7.0` (read from `__init__.py`) while `pip show searchts` still says
  `0.1.0` with the old description and a dependency list missing `ddgs` - the
  `-e` install predates several dependency changes. Re-run
  `pip install -c constraints.txt -e ".[dev]"` after pulling; do not trust
  `pip show` for the version.
- **`scratch/` is a local-only landmine.** It is gitignored, contains stale test
  files importing the pre-fork `agent_reach` module, and bare `pytest` collects
  it. Always `pytest tests/`.
- **`test.sh` is Unix-only.** It does `python3 -m venv` and
  `source "$TEST_DIR/venv/bin/activate"`; on Windows the venv puts executables
  in `Scripts/`, so it fails even under Git Bash. Use it on Linux/macOS or in
  the container.
- **`searchts skill install` overwrites your customization.** It rewrites
  `~/.claude/commands/searchts.md` from a hardcoded string in `cli.py`. The copy
  currently on this machine was hand-edited to add a fallback to the venv
  executable path (`.venv\Scripts\searchts.exe`); re-running the installer drops
  that, and `/searchts` then only works if `searchts` is on PATH.
- **Two different "skill" mechanisms, easy to confuse.** `searchts skill install`
  writes a Claude Code SLASH COMMAND (`~/.claude/commands/searchts.md`). The
  legacy `searchts skill --install` copies the `SKILL.md` bundle into
  `~/.agents/skills/searchts` (or `~/.openclaw/skills`, `~/.claude/skills`).
  `doctor` reports both, plus MCP registration, separately.
- **MCP is not wired on this machine.** `doctor` currently reports
  `Claude Code (MCP) - detected, but searchts is NOT registered`, while
  `Claude Code (/searchts skill) - searchts is registered`. Only the slash
  command works today; run `claude mcp add searchts -- searchts mcp serve` if
  you want the always-on tools.
- **The MCP server has no port.** It is stdio JSON-RPC. Do not go looking for a
  listening socket; `searchts mcp serve` run by hand just sits on stdin.
- **Every MCP tool returns an `Error: ...` string instead of raising**
  (`docs/mcp.md`), so a failing tool looks like a successful call with sad text.
- **System Python here is 3.14.5, outside the CI matrix** (3.10-3.13). Build the
  venv with `py -3.12`.
- **Per-domain backend memory can pin you to a stale tier.** The winner per
  domain is cached in `~/.searchts/unlocker_cache.json`; if a site changes its
  defenses the cached tier is tried first. Delete the file or set
  `SEARCHTS_NO_MEMORY=1` when debugging a read.
- **Benchmark numbers only mean something on a residential connection**
  (`README.md`). A datacenter IP or a VPN reshapes the TLS fingerprint and
  blocks the fast curl_cffi tier far more than a real user sees.
- **The stealth-browser tier is lazy.** patchright's Chromium is only launched
  when the cheaper tiers fail, so a missing browser binary does not surface
  until some specific hard page needs it.
- **Working tree is dirty by default here.** 22 untracked files
  (`.coderabbit.yaml` plus a pile of `demo/*.mp4|.tape|.png` recordings) sit in
  the repo root. Never `git add -A`.
- **Docker image deliberately omits the browser tier** (`Dockerfile` comment),
  so `read_url` in the container only has curl_cffi and Jina Reader.
- **`constraints.txt` is thinner than it looks.** `docs/dependency-locking.md`
  calls it "a reproducible dependency baseline", but it pins 7 of the 10 runtime
  dependencies: `curl_cffi`, `trafilatura` and `ddgs` are unpinned, and so is
  every optional extra (patchright, mcp, faster-whisper, browser-cookie3). A
  fresh constrained install can still pull a breaking curl_cffi or ddgs.
- **CI never exercises the optional paths.** `.github/workflows/pytest.yml`
  installs only `-e ".[dev]"` - no patchright, no faster-whisper, no ffmpeg. A
  green CI run says nothing about the stealth-browser or audio-transcription
  code paths.
- **`docs/troubleshooting.md` is stale.** All of it is twitter-cli proxy advice
  and an `mcporter call exa...` recipe that the CLI itself now de-recommends. It
  documents none of the core `read` / `search` / `transcribe` / `grab` failures.
  This runbook's failures table is the replacement.
- **`docs/install.md` never mentions the extras.** No ffmpeg, whisper,
  patchright, chromium, `[browser]`, `[mcp]` or `[local-transcribe]` anywhere in
  `docs/`. Its "Directory Rules" table also assumes `/tmp/`, which is Unix-only.
- **`rookiepy` is preferred for cookie extraction but is not a declared
  dependency.** `searchts/cookie_extract.py` tries `rookiepy` first and falls
  back to `browser_cookie3` (the `cookies` extra). If cookie extraction fails,
  `pip install rookiepy` is the recommended fix even though pyproject never
  mentions it.

## Project map

```
searchts/                  the Python package
  cli.py                   argparse CLI, every subcommand, ~80KB - the big one
  unlocker.py              escalating fetch ladder + block-phrase detection
  search.py                multi-provider search + reciprocal rank fusion
  transcribe.py            subtitles-first video transcription
  assets.py                grab/get: asset download, palette, font extraction
  sanitize.py              prompt-injection scrubbing, invisible-char stripping
  config.py                config load/save (YAML + env)
  doctor.py                diagnostics engine behind `searchts doctor`
  probe.py                 capability probing helpers
  cookie_extract.py        browser cookie extraction (browser-cookie3)
  core.py                  thin Searchts facade exported from __init__
  channels/                one file per platform; mostly powers doctor checks
  share_extractors/        per-provider AI-chat share-link readers (plugins)
  backends/                opencli backend shim
  integrations/            mcp_server.py (stdio MCP), agent_wiring.py
  skill/                   SKILL.md bundle + references shipped in the wheel
  guides/                  setup-*.md guides shipped in the wheel
  utils/                   paths.py, process.py, text.py
tests/                     pytest suite, one file per module
benchmarks/                reproducible unlocker scorecard (run.py, cases.py)
docs/                      install, mcp, troubleshooting, update, scorecard
config/mcporter.json       mcporter MCP client config
scripts/sync-upstream.sh   upstream (Agent-Reach) sync helper
.github/workflows/         pytest.yml (CI), release.yml, release-please.yml
constraints.txt            pinned tested dependency set; CI installs through it
server.json                MCP registry manifest (version must match pyproject)
```
