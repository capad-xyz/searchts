# searchts — Installation Guide

## For Humans

Copy this to your AI Agent:

```
Help me install searchts: https://raw.githubusercontent.com/capad-xyz/searchts/main/docs/install.md
```

> **Security-conscious?** Use safe mode — it won't auto-install system packages:
> ```
> Help me install searchts (safe mode): https://raw.githubusercontent.com/capad-xyz/searchts/main/docs/install.md
> Use the --safe flag when installing
> ```

---

## For AI Agents

### Goal

Install searchts and all upstream tools so your user's agent has full internet access. After installation, you'll use the upstream tools directly (twitter-cli, rdt-cli, yt-dlp, mcporter, gh CLI, etc.) — searchts is the selector, installer, health checker and router, never a wrapper.

### Boundaries

When fixing issues, stay within these limits:

- **DO NOT** run commands with `sudo` unless the user explicitly approved
- **DO NOT** modify system files outside `~/.searchts/`
- **DO NOT** install packages not listed in this guide
- **DO NOT** disable firewalls, security settings, or system protections
- **DO NOT** clone repos, create files, or run commands inside the agent workspace / working directory
- If something requires elevated permissions, **tell the user** what's needed and let them decide

### Directory Rules

All searchts files go in dedicated directories — **never in the agent workspace**:

| Purpose | Directory | Example |
|---------|-----------|---------|
| Config & tokens | `~/.searchts/` | `~/.searchts/config.json` |
| Upstream tool repos | `~/.searchts/tools/` | `~/.searchts/tools/` |
| Temporary files | `/tmp/` | `/tmp/yt-dlp-output/` |
| Skills | `~/.openclaw/skills/searchts/` | SKILL.md |

**Why?** If you clone repos or create files in the workspace, it pollutes the user's project directory and can break their agent over time. Keep the workspace clean.

### Step 1: Install the basics

```bash
# Recommended: pipx (easiest)
pipx install https://github.com/capad-xyz/searchts/archive/main.zip
searchts install --env=auto

# If your Python comes from Homebrew, or you hit PEP 668 (externally-managed-environment),
# install inside a virtual environment:
python3 -m venv ~/.searchts-venv
source ~/.searchts-venv/bin/activate
pip install https://github.com/capad-xyz/searchts/archive/main.zip
searchts install --env=auto
```

> **Windows / Microsoft Store Python alias?**
> If `python3 --version` opens the Microsoft Store, or `where python3` points to
> `...\AppData\Local\Microsoft\WindowsApps\python3.exe`, then `python3` is the Windows
> Store alias, not a usable Python install. Use the Python Launcher `py -3`, or the
> `python.exe` inside the real install directory.
>
> PowerShell example:
> ```powershell
> py -3 -m venv $env:USERPROFILE\.searchts-venv
> $env:USERPROFILE\.searchts-venv\Scripts\Activate.ps1
> python -m pip install https://github.com/capad-xyz/searchts/archive/main.zip
> searchts install --env=auto
> ```

This installs core infrastructure (gh CLI, Node.js, mcporter, Exa search, yt-dlp config) and activates these zero-config channels:

- Web (Jina Reader), Search (Exa), YouTube, GitHub, RSS

> **macOS / Homebrew Python reporting `externally-managed-environment`?**
> This is PEP 668 protection, not a searchts problem. Prefer `pipx install ...`, or create a `venv` first and then install.

**Safe mode / Dry run:**

```bash
searchts install --env=auto --safe      # Check only, no auto-install
searchts install --env=auto --dry-run   # Preview what would be done
```

### Step 2: Ask the user which optional channels they want

After installing the basics, **ask the user** which additional channels they need. Present this list:

> The core channels are installed! You can now have me search the web, watch YouTube, read GitHub, and more.
>
> These optional channels are also available — which do you need?
>
> - 🐦 **Twitter/X** — search tweets, read timelines (requires a login cookie)
> - 📖 **Reddit** — search and read posts (login required: rdt-cli + cookie)
> - 💼 **LinkedIn** — profiles, job search
>
> Tell me which you want, for example "install Twitter and Reddit". Or say "install all".

Based on the user's choice, run:

```bash
searchts install --env=auto --channels=twitter,reddit   # Example: user chose Twitter + Reddit
searchts install --env=auto --channels=all              # User wants everything
```

Supported channel names: `twitter`, `reddit`, `linkedin`, `all`

### Step 3: Fix what's broken

Run `searchts doctor` and check the output.

Try to get as many channels working as possible. If something failed during install or shows as an error/warning in doctor, diagnose the problem and try to fix it — but stay within the boundaries above. If a fix requires elevated permissions or system changes, ask the user first.

Only ask the user when you genuinely need their input (credentials, permissions, etc.).

### Step 4: Configure things that need user input

Some channels need credentials only the user can provide. Based on the doctor output, ask for what's missing:

> **Security tip:** For platforms that need cookies (Twitter), we recommend using a **dedicated/secondary account** rather than your main account. Cookie-based auth carries two risks:
> 1. **Account ban** — platforms may detect non-browser API calls and restrict or ban the account
> 2. **Credential exposure** — cookies grant full account access; using a secondary account limits the blast radius if credentials are ever compromised

> 🍪 **Cookie import (for any platform that needs login):**
>
> For any platform that needs a cookie (such as Twitter), **prefer importing with Cookie-Editor** — it is the simplest and most reliable method:
> 1. Log into the platform in your own browser
> 2. Install the [Cookie-Editor](https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm) Chrome extension
> 3. Click the extension, then Export, then Header String
> 4. Send the exported string to your Agent
>
> **Local desktop users** can also run `searchts configure --from-browser chrome` to extract cookies automatically.

**Twitter search & posting:**
> "To unlock Twitter search, I need your Twitter cookies. Install the Cookie-Editor Chrome extension, go to x.com/twitter.com, click the extension, then Export, then Header String, and paste it to me."

```bash
searchts configure twitter-cookies "PASTED_STRING"
```

> **Proxy note (for networks that need one to reach blocked sites):**
>
> twitter-cli and rdt-cli use Python and can be pointed at a proxy via environment variables.
>
> **What you (the Agent) need to do:**
> 1. Confirm the user has configured a proxy: `searchts configure proxy http://user:pass@ip:port`
> 2. Set the environment variables: `export HTTP_PROXY="..." HTTPS_PROXY="..."`
> 3. searchts handles the rest automatically; the user does not need to do anything extra
>
> If the user reports "fetch failed", see [troubleshooting.md](troubleshooting.md)

**Reddit (login is mandatory — no zero-config path):**
> Reddit's anonymous endpoints are blocked and the official API needs manual approval. Use rdt-cli:

```bash
# PyPI lags behind, so install from GitHub (same pinned version as the code's _RDT_GIT_SOURCE)
pipx install 'git+https://github.com/public-clis/rdt-cli.git@5e4fb3720d5c174e976cd425ccc3b879d52cac66'
rdt login   # Auto-extracts the browser cookie; on a headless server, follow the doctor prompt to write the cookie manually
```

> A server IP may get rate-limited by Reddit; in that case configure a residential proxy (for example https://webshare.io, around $1/month):
> ```bash
> searchts configure proxy http://user:pass@ip:port
> ```

**LinkedIn (optional — linkedin-scraper-mcp):**
> "Basic LinkedIn content can be read through Jina Reader. Full features (profile details, job search) need linkedin-scraper-mcp."

```bash
pip install linkedin-scraper-mcp
```

> **Login (requires a browser window):**
>
> linkedin-scraper-mcp logs in with a Chromium browser, so you need to be able to see the browser window.
>
> - **Local desktop (has a display):** run directly:
>   ```bash
>   linkedin-scraper-mcp --login --no-headless
>   ```
>   The browser pops up; log into LinkedIn manually.
>
> - **Server (no UI):** operate it over a VNC remote desktop:
>   ```bash
>   # 1. Install and start VNC on the server (skip if you already have it)
>   apt install -y tigervnc-standalone-server
>   vncserver :1 -geometry 1280x720
>
>   # 2. Connect with a VNC client to SERVER_IP:5901
>
>   # 3. In a terminal on the VNC desktop, run:
>   export DISPLAY=:1
>   linkedin-scraper-mcp --login --no-headless
>   ```
>   Once you see the browser in VNC, log in manually. After a successful login the session is saved to `~/.linkedin-mcp/profile/`.
>
> **Start the MCP service after login:**
> ```bash
> linkedin-scraper-mcp --transport streamable-http --port 8001
> mcporter config add linkedin http://localhost:8001/mcp
> ```
>
> See https://github.com/stickerdaniel/linkedin-mcp-server

### Step 5: Final check

Run `searchts doctor` one final time and report the results to your user.

### Step 6: Set up daily monitoring (OpenClaw only)

If you are running inside **OpenClaw**, ask your user:

> "searchts is installed. Want me to set up a daily check task? It will watch whether these channels are healthy and whether there is a new version. It only notifies you when there is a problem, and stays quiet otherwise."

If the user agrees, create a **cron job** (daily, `sessionTarget: "isolated"`, `delivery: "announce"`) with this task:

```
Run the searchts watch command.
If the output says everything is fine, do not notify the user, just exit silently.
If the output reports a problem or a new version, send the full report to the user and suggest a fix.
If a new version is available, ask the user whether they want to upgrade (send this line to the user's Agent to do the full update: Help me update searchts: https://raw.githubusercontent.com/capad-xyz/searchts/main/docs/update.md).
```

If the user wants a different agent to handle it, let them choose.

---

## Quick Reference

| Command | What it does |
|---------|-------------|
| `searchts install --env=auto` | Install core channels (lightweight, zero-config) |
| `searchts install --env=auto --channels=twitter,reddit` | Install core + optional channels |
| `searchts install --env=auto --channels=all` | Install everything |
| `searchts install --env=auto --safe` | Safe setup (no auto system changes) |
| `searchts install --env=auto --dry-run` | Preview what would be done |
| `searchts doctor` | Show channel status |
| `searchts watch` | Quick health + update check (for scheduled tasks) |
| `searchts check-update` | Check for new versions |
| `searchts configure twitter-cookies "..."` | Unlock Twitter search + posting |
| `searchts configure proxy URL` | Save a proxy address (read when the Agent accesses restricted networks like Reddit/Twitter to set HTTP_PROXY/HTTPS_PROXY; it is not an auto-unlock switch) |

After installation, use upstream tools directly. See SKILL.md for the full command reference:

| Platform | Upstream Tool | Example |
|----------|--------------|---------|
| Twitter/X | `twitter` | `twitter search "query" -n 10` |
| YouTube | `yt-dlp` | `yt-dlp --dump-json URL` |
| Reddit | `rdt` | `rdt read POST_ID` |
| GitHub | `gh` | `gh search repos "query"` |
| Web | `curl` + Jina | `curl -s "https://r.jina.ai/URL"` |
| Search (Exa) | `mcporter` | `mcporter call 'exa.web_search_exa(...)'` |
| LinkedIn | `mcporter` | `mcporter call 'linkedin.get_person_profile(...)'` |
| RSS | `feedparser` | `python3 -c "import feedparser; ..."` |

> For multi-backend platforms, the source of truth is the `active_backend` field of `searchts doctor --json`.
