# -*- coding: utf-8 -*-
"""
searchts CLI — installer, doctor, and configuration tool.

Usage:
    searchts install --env=auto
    searchts doctor
    searchts configure twitter-cookies "auth_token=xxx; ct0=yyy"
    searchts setup
"""

import argparse
import difflib
import json
import os
import sys
import time

from searchts import __version__

# Pinned to the 0.4.2 state — PyPI still only has 0.4.1 (upstream issue #10).
_RDT_GIT_SOURCE = "git+https://github.com/public-clis/rdt-cli.git@5e4fb3720d5c174e976cd425ccc3b879d52cac66"


def _ensure_utf8_console():
    """Best-effort Windows console UTF-8 setup for CLI runtime only."""
    if sys.platform != "win32":
        return
    # Avoid interfering with pytest/captured streams.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    try:
        import io
        if hasattr(sys.stdout, "buffer"):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "buffer"):
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        # Do not crash CLI just because encoding patch failed.
        pass


def _configure_logging(verbose: bool = False):
    """Suppress loguru output unless --verbose is set."""
    from loguru import logger
    logger.remove()  # Remove default stderr handler
    if verbose:
        logger.add(sys.stderr, level="INFO")


def _first_command_token(argv):
    """Return the first positional CLI token that could be a subcommand."""
    skip_options = {"-v", "--verbose"}
    terminal_options = {"-h", "--help", "--version"}
    for token in argv:
        if token in skip_options:
            continue
        if token in terminal_options:
            return None
        if token.startswith("-"):
            return None
        return token
    return None


def _maybe_print_command_suggestion(argv, commands):
    """Suggest the nearest known command before argparse prints its error."""
    command = _first_command_token(argv)
    if not command or command in commands:
        return
    matches = difflib.get_close_matches(command, commands, n=1, cutoff=0.6)
    if matches:
        print(f"did you mean '{matches[0]}'?", file=sys.stderr)


def main():
    _ensure_utf8_console()

    parser = argparse.ArgumentParser(
        prog="searchts",
        description="Give your AI Agent eyes to see the entire internet",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Show debug logs")
    parser.add_argument("--version", action="version", version=f"searchts v{__version__}")
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # ── setup ──
    sub.add_parser("setup", help="Interactive configuration wizard")

    # ── install ──
    p_install = sub.add_parser("install", help="One-shot installer with flags")
    p_install.add_argument("--env", choices=["local", "server", "auto"], default="auto",
                           help="Environment: local, server, or auto-detect")
    p_install.add_argument("--proxy", default="",
                           help="Network proxy saved for agents to export as HTTP(S)_PROXY "
                                "in restricted networks (http://user:pass@ip:port)")
    p_install.add_argument("--system-deps", "--apply", dest="system_deps", action="store_true",
                           help="Opt in to mutating the system: install gh/Node.js, npm -g packages, "
                                "apt sources, and yt-dlp config. Off by default (the keyless core "
                                "needs none of this) — without it, install only prints the manual commands.")
    p_install.add_argument("--safe", action="store_true",
                           help="Deprecated no-op: safe (non-mutating) is now the default. "
                                "Use --system-deps to opt in to system changes.")
    p_install.add_argument("--dry-run", action="store_true",
                           help="Show what would be done without making any changes")
    p_install.add_argument("--channels", default="",
                           help="Comma-separated optional channels to install "
                                "(twitter,reddit,linkedin,all)")

    # ── configure ──
    p_conf = sub.add_parser("configure", help="Set a config value or auto-extract from browser")
    p_conf.add_argument("key", nargs="?", default=None,
                        choices=["proxy", "github-token", "groq-key", "openai-key",
                                 "twitter-cookies", "youtube-cookies"],
                        help="What to configure (omit if using --from-browser)")
    p_conf.add_argument("value", nargs="*", help="The value(s) to set")
    p_conf.add_argument("--from-browser", metavar="BROWSER",
                        choices=["chrome", "firefox", "edge", "brave", "opera"],
                        help="Auto-extract ALL platform cookies from browser (chrome/firefox/edge/brave/opera)")

    # ── read ──
    p_read = sub.add_parser("read", help="Fetch a URL through the escalating unlocker and print clean markdown")
    p_read.add_argument("url", help="The URL to read")
    p_read.add_argument("--backend", default=None,
                        help="Force a single backend (e.g. curl_cffi, 'Jina Reader', stealth-browser)")
    p_read.add_argument("--json", action="store_true",
                        help="Print {url,backend,status,chars,text} as JSON instead of raw text")
    p_read.add_argument("--human", action="store_true",
                        help="On a CAPTCHA/challenge, open a headful browser to solve by hand")
    p_read.add_argument("--scrub", action="store_true",
                        help="Redact prompt-injection spans from the content (invisible-char "
                             "stripping + indicator scanning always run regardless)")

    # ── search ──
    p_search = sub.add_parser("search", help="Multi-source web search (fusion-merged across providers)")
    p_search.add_argument("query", help="The search query")
    p_search.add_argument("-n", dest="max_results", type=int, default=10,
                          help="Maximum number of fused results to return (default: 10)")
    p_search.add_argument("--json", action="store_true",
                          help="Print the list of result dicts as JSON instead of a numbered list")
    p_search.add_argument("--provider", action="append", default=None, metavar="NAME",
                          help="Restrict to a provider (repeatable, or a comma-separated list); "
                               "e.g. --provider duckduckgo --provider brave")

    # ── doctor ──
    p_doctor = sub.add_parser("doctor", help="Check platform availability")
    p_doctor.add_argument("--json", action="store_true",
                          help="Output machine-readable JSON instead of the text report")

    # ── uninstall ──
    p_uninstall = sub.add_parser("uninstall", help="Remove all searchts config, tokens, and skill files")
    p_uninstall.add_argument("--dry-run", action="store_true",
                             help="Show what would be removed without making any changes")
    p_uninstall.add_argument("--keep-config", action="store_true",
                             help="Remove skill files only, keep ~/.searchts/ config and tokens")

    # ── mcp ──
    p_mcp = sub.add_parser("mcp", help="Run or wire up the searchts MCP server")
    mcp_sub = p_mcp.add_subparsers(dest="mcp_command", help="MCP subcommands")
    mcp_sub.add_parser("serve", help="Run the stdio MCP server (read_url + web_search tools)")
    p_mcp_install = mcp_sub.add_parser(
        "install", help="Print the exact wiring for an AI agent client (no network)")
    p_mcp_install.add_argument("--client", choices=["claude", "cursor", "json"], default=None,
                               help="Which client to print wiring for (default: all)")

    # ── skill ──
    p_skill = sub.add_parser("skill", help="Manage agent skill registration")
    # Legacy flags (kept for backward compatibility): `searchts skill --install`.
    p_skill.add_argument("--install", dest="legacy_install", action="store_true",
                         help="Install the SKILL.md bundle to agent skill directories")
    p_skill.add_argument("--uninstall", dest="legacy_uninstall", action="store_true",
                         help="Remove the SKILL.md bundle from agent skill directories")
    skill_sub = p_skill.add_subparsers(dest="skill_command", help="Skill subcommands")
    p_skill_install = skill_sub.add_parser(
        "install", help="Write a Claude Code slash-command (searchts.md) into the commands dir")
    p_skill_install.add_argument("--dir", dest="dir", default=None,
                                 help="Target commands directory (default: ~/.claude/commands)")

    # ── check-update ──
    # ── transcribe ──
    p_tr = sub.add_parser("transcribe", help="Transcribe a URL or local audio file (existing subtitles first, then Whisper via Groq/OpenAI or keyless local faster-whisper)")
    p_tr.add_argument("source", help="Audio/video URL or local file path")
    p_tr.add_argument("--provider", choices=["auto", "groq", "openai", "local"], default="auto",
                      help="Audio transcription provider used when there are no subtitles "
                           "(default: auto = hosted key if set, else keyless local "
                           "faster-whisper; `local` forces local, no API key)")
    p_tr.add_argument("--no-subtitles", dest="prefer_subtitles", action="store_false",
                      default=True,
                      help="Skip the video's existing captions and force audio transcription "
                           "(captions otherwise come first and need no API key)")
    p_tr.add_argument("-o", "--output", default=None,
                      help="Write transcript to a file instead of stdout")

    # ── get / grab (assets + design inspiration) ──
    p_get = sub.add_parser("get", help="Download a single asset (image/PDF/font/file) through the unlocker")
    p_get.add_argument("url", help="The asset URL to download")
    p_get.add_argument("-o", "--output", default=None,
                       help="Output file or directory (default: filename from the URL, in the cwd)")

    p_grab = sub.add_parser("grab", help="Grab a page's assets + color palette + fonts (design inspiration)")
    p_grab.add_argument("url", help="The page URL to grab")
    p_grab.add_argument("--out", default=None,
                        help="Output directory (default: ./searchts-grab-<host>)")
    p_grab.add_argument("--kinds", default="images,icons,css,fonts,svg",
                        help="Comma list of asset kinds to download (images,icons,css,fonts,svg,scripts)")
    p_grab.add_argument("--scripts", action="store_true", help="Also download <script src> files")
    p_grab.add_argument("--read", action="store_true", help="Also save the page text as page.md")
    p_grab.add_argument("--max", dest="max_assets", type=int, default=60,
                        help="Maximum assets to download (default 60)")
    p_grab.add_argument("--json", action="store_true", help="Print the manifest JSON to stdout")

    sub.add_parser("check-update", help="Check for new versions and changes")

    # ── watch ──
    sub.add_parser("watch", help="Quick health check + update check (for scheduled tasks)")

    # ── version ──
    sub.add_parser("version", help="Show version")

    _maybe_print_command_suggestion(sys.argv[1:], sub.choices)
    args = parser.parse_args()

    # Suppress loguru noise unless --verbose
    _configure_logging(getattr(args, "verbose", False))

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "version":
        print(f"searchts v{__version__}")
        sys.exit(0)

    if args.command == "read":
        _cmd_read(args)
    elif args.command == "search":
        _cmd_search(args)
    elif args.command == "doctor":
        _cmd_doctor(args)
    elif args.command == "check-update":
        _cmd_check_update()
    elif args.command == "watch":
        _cmd_watch()
    elif args.command == "setup":
        _cmd_setup()
    elif args.command == "install":
        _cmd_install(args)
    elif args.command == "configure":
        _cmd_configure(args)
    elif args.command == "uninstall":
        _cmd_uninstall(args)
    elif args.command == "mcp":
        _cmd_mcp(args)
    elif args.command == "skill":
        _cmd_skill(args)
    elif args.command == "transcribe":
        _cmd_transcribe(args)
    elif args.command == "get":
        _cmd_get(args)
    elif args.command == "grab":
        _cmd_grab(args)


# ── Command handlers ────────────────────────────────


def _cmd_install(args):
    """One-shot deterministic installer."""
    import os
    from searchts.config import Config
    from searchts.doctor import check_all, format_report

    dry_run = args.dry_run
    # Non-invasive by default: the keyless core (read/search/transcribe) needs no
    # system mutation. Only --system-deps/--apply opts in to apt/npm/NodeSource/
    # yt-dlp-config changes. --safe is now a no-op kept for backward compatibility.
    apply_system = args.system_deps
    safe_mode = not apply_system

    config = Config()
    print()
    print("searchts Installer")
    print("=" * 40)

    # Ensure tools directory exists (for upstream tool repos)
    tools_dir = os.path.expanduser("~/.searchts/tools")
    os.makedirs(tools_dir, exist_ok=True)

    if dry_run:
        print("DRY RUN — showing what would be done (no changes)")
        print()
    elif apply_system:
        print("SYSTEM-DEPS MODE — will install optional system packages (gh, Node.js, npm globals)")
        print()
    else:
        print("Non-invasive install (default) — no system changes will be made.")
        print("The keyless core (searchts read/search/transcribe) needs none of these.")
        print("Re-run with --system-deps to actually install the optional system packages below.")
        print()

    # ── Parse --channels ──
    CHANNEL_INSTALLERS = {
        "twitter":     _install_twitter_deps,
        "reddit":      _install_reddit_deps,
        "opencli":     _install_opencli_deps,  # cross-channel backend, desktop only
        # linkedin: manual setup, no auto-install
    }
    COOKIE_CHANNELS = {"twitter"}

    requested_channels = set()
    if args.channels:
        raw = [c.strip().lower() for c in args.channels.split(",") if c.strip()]
        if "all" in raw:
            requested_channels = set(CHANNEL_INSTALLERS.keys()) | {"linkedin"}
        else:
            requested_channels = set(raw)

    # Auto-detect environment
    env = args.env
    if env == "auto":
        env = _detect_environment()

    if env == "server":
        print(f"Environment: Server/VPS (auto-detected)")
    else:
        print(f"Environment: Local computer (auto-detected)")

    # Apply explicit flags
    if args.proxy:
        if dry_run:
            print(f"[dry-run] Would save network proxy")
        else:
            config.set("proxy", args.proxy)
            print(f"[ok] Proxy saved (used when the agent accesses a restricted network)")

    # ── Install core system dependencies (lightweight, always) ──
    print()
    if dry_run:
        _install_system_deps_dryrun()
    elif safe_mode:
        _install_system_deps_safe()
    else:
        _install_system_deps()

    # ── mcporter (for Exa search) ──
    print()
    if dry_run:
        print("[dry-run] Would install mcporter and configure Exa search")
    elif safe_mode:
        _install_mcporter_safe()
    else:
        _install_mcporter()

    # ── Install optional channels (only if --channels specified) ──
    if requested_channels and not dry_run and not safe_mode:
        print()
        print("Installing optional channels...")
        if env == "server" and "opencli" in requested_channels:
            # OpenCLI rides a real desktop Chrome session — useless headless
            requested_channels.discard("opencli")
            print("  -- OpenCLI requires a desktop environment + Chrome; skipping in a server environment")
        for ch_name in sorted(requested_channels):
            installer = CHANNEL_INSTALLERS.get(ch_name)
            if installer:
                installer()

    if requested_channels and dry_run:
        print()
        print(f"[dry-run] Would install optional channels: {', '.join(sorted(requested_channels))}")
    elif requested_channels and safe_mode:
        print()
        print(f"Optional channels requested ({', '.join(sorted(requested_channels))}) but not installed: "
              "installing them mutates the system (pipx/npm).")
        print("   Re-run with --system-deps to install them: "
              f"searchts install --system-deps --channels={','.join(sorted(requested_channels))}")

    # ── Auto-import cookies (only if cookie-needing channels are requested) ──
    needs_cookies = bool(requested_channels & COOKIE_CHANNELS)
    if env == "local" and needs_cookies and not safe_mode and not dry_run:
        print()
        print("Importing cookies from browser...")
        print("  (macOS may ask for your login password to access the Keychain — this is normal,")
        print("   it only happens once during install. Enter your password or click 'Allow'.)")
        try:
            from searchts.cookie_extract import configure_from_browser
            results = configure_from_browser("chrome", config)
            found = False
            for platform, success, message in results:
                if success:
                    print(f"  [ok] {platform}: {message}")
                    found = True
            if not found:
                results = configure_from_browser("firefox", config)
                for platform, success, message in results:
                    if success:
                        print(f"  [ok] {platform}: {message}")
                        found = True
            if not found:
                print("  -- No cookies found (normal if you haven't logged into these sites)")
        except Exception:
            print("  -- Could not read browser cookies (browser might be open or password was denied)")
    elif env == "local" and needs_cookies and dry_run:
        print()
        print("[dry-run] Would try to import cookies from Chrome/Firefox")

    # Environment-specific advice
    if env == "server":
        print()
        print("Tip: some platforms apply risk controls to server IPs.")
        print("   Reddit requires a logged-in session (rdt-cli + cookie, see the doctor hints), and mainland China networks also need a proxy.")
        print("   Save a proxy for the agent to use: searchts configure proxy http://user:pass@ip:port")
        print("   Cheap option: https://www.webshare.io ($1/month)")

    # Test channels
    if not dry_run:
        print()
        print("Testing channels...")
        results = check_all(config)
        ok = sum(1 for r in results.values() if r["status"] == "ok")
        total = len(results)

        # Final status
        print()
        print(format_report(results))
        print()

        # ── Install agent skill ──
        _install_skill()

        print(f"[ok] Installation complete! {ok}/{total} channels active.")

        if not requested_channels:
            # First install — hint about optional channels
            print()
            print("More channels available! Use --channels to install:")
            print("   searchts install --channels=twitter,reddit,...")
            print("   searchts install --channels=all  (install everything)")

        # Star reminder
        print()
        print("If searchts helped you, give it a Star so more people can find it:")
        print("   https://github.com/capad-xyz/searchts")
        print("   It takes just a second and means a lot to an independent developer. Thank you!")
    else:
        print()
        print("Dry run complete. No changes were made.")


def _install_skill():
    """Install searchts as an agent skill (OpenClaw / Claude Code / .agents)."""
    import os
    import shutil
    import importlib.resources

    def _is_english_locale(value: str) -> bool:
        normalized = value.strip().lower()
        return normalized.startswith("en") or normalized.startswith("english")

    def _skill_resource_name() -> str:
        locale_candidates = (
            os.environ.get("SEARCHTS_LANG", ""),
            os.environ.get("LC_ALL", ""),
            os.environ.get("LC_MESSAGES", ""),
            os.environ.get("LANG", ""),
        )
        if any(_is_english_locale(candidate) for candidate in locale_candidates):
            return "SKILL_en.md"
        return "SKILL.md"

    def _read_skill_markdown(skill_pkg):
        resource_name = _skill_resource_name()
        try:
            return skill_pkg.joinpath(resource_name).read_text(encoding="utf-8")
        except FileNotFoundError:
            return skill_pkg.joinpath("SKILL.md").read_text(encoding="utf-8")

    def _copy_skill_dir(target: str) -> bool:
        """Copy entire skill directory (locale-specific SKILL.md + references/)."""
        try:
            # Clear existing installation. A symlinked skill dir (dotfiles
            # setups) breaks shutil.rmtree — unlink the link itself instead.
            if os.path.islink(target):
                os.unlink(target)
            elif os.path.exists(target):
                shutil.rmtree(target)
            os.makedirs(target, exist_ok=True)

            # Get skill directory from package (with fallback for editable installs)
            try:
                skill_pkg = importlib.resources.files("searchts").joinpath("skill")
                skill_md = _read_skill_markdown(skill_pkg)
            except Exception:
                from pathlib import Path
                skill_pkg = Path(__file__).resolve().parent / "skill"
                skill_md = _read_skill_markdown(skill_pkg)

            # Copy SKILL.md using the selected locale file
            with open(os.path.join(target, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write(skill_md)

            # Copy references/ directory
            refs_pkg = skill_pkg.joinpath("references")
            refs_target = os.path.join(target, "references")
            os.makedirs(refs_target, exist_ok=True)

            for ref_file in refs_pkg.iterdir():
                name = ref_file.name if hasattr(ref_file, 'name') else str(ref_file).split('/')[-1]
                if name.endswith(".md"):
                    content = ref_file.read_text(encoding="utf-8") if hasattr(ref_file, 'read_text') else ref_file.read_text()
                    with open(os.path.join(refs_target, name), "w", encoding="utf-8") as f:
                        f.write(content)

            return True
        except Exception as e:
            print(f"  Warning: Could not install skill: {e}")
            return False

    # Determine skill install path (priority: .agents > openclaw > claude)
    skill_dirs = [
        os.path.expanduser("~/.agents/skills"),      # Generic agents (priority)
        os.path.expanduser("~/.openclaw/skills"),    # OpenClaw
        os.path.expanduser("~/.claude/skills"),      # Claude Code (if exists)
    ]

    # Insert OPENCLAW_HOME path at the beginning if environment variable is set
    openclaw_home = os.environ.get("OPENCLAW_HOME")
    if openclaw_home:
        skill_dirs.insert(0, os.path.join(openclaw_home, ".openclaw", "skills"))

    installed = False
    for skill_dir in skill_dirs:
        if os.path.isdir(skill_dir):
            target = os.path.join(skill_dir, "searchts")
            if _copy_skill_dir(target):
                platform_name = "Agent" if ".agents" in skill_dir else "OpenClaw" if "openclaw" in skill_dir else "Claude Code"
                print(f"Skill installed for {platform_name}: {target}")
                installed = True

    if not installed:
        # No known skill directory found — create for .agents by default
        target = os.path.expanduser("~/.agents/skills/searchts")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if _copy_skill_dir(target):
            print(f"Skill installed: {target}")
        else:
            print("  -- Could not install agent skill (optional)")
            print("  -- Tip: install OpenClaw, Claude Code, or create ~/.agents/skills/ manually")


def _uninstall_skill():
    """Remove SKILL.md from all known agent skill directories."""
    import shutil

    skill_dirs = [
        ("~/.openclaw/skills/searchts", "OpenClaw"),
        ("~/.claude/skills/searchts", "Claude Code"),
        ("~/.agents/skills/searchts", "Agent"),
    ]

    # Also check OPENCLAW_HOME
    openclaw_home = os.environ.get("OPENCLAW_HOME")
    if openclaw_home:
        skill_dirs.insert(
            0,
            (os.path.join(openclaw_home, ".openclaw", "skills", "searchts"), "OpenClaw"),
        )

    removed = False
    for skill_path_template, platform_name in skill_dirs:
        skill_path = os.path.expanduser(skill_path_template)
        if os.path.isdir(skill_path):
            try:
                if os.path.islink(skill_path):
                    os.unlink(skill_path)
                else:
                    shutil.rmtree(skill_path)
                print(f"  Removed {platform_name} skill: {skill_path}")
                removed = True
            except Exception as e:
                print(f"  Could not remove {skill_path}: {e}")

    if not removed:
        print("  No skill installations found.")


def _cmd_skill(args):
    """Manage agent skill registration.

    Two shapes:
      * `searchts skill install [--dir DIR]` — write the Claude Code slash-command
        file (searchts.md) into a commands directory.
      * `searchts skill --install / --uninstall` — legacy: (de)register the full
        SKILL.md bundle in agent skill directories.
    """
    if getattr(args, "skill_command", None) == "install":
        _cmd_skill_install(args)
        return

    if getattr(args, "legacy_install", False):
        _install_skill()
    elif getattr(args, "legacy_uninstall", False):
        _uninstall_skill()
    else:
        print("Usage: searchts skill install [--dir DIR]")
        print("   or: searchts skill --install | --uninstall")
        sys.exit(2)


#: Body of the Claude Code custom slash-command (searchts.md). Instructs the
#: agent to route the slash-command argument to `searchts read|search|transcribe`.
_SLASH_COMMAND_BODY = """\
---
description: Read a URL, search the web, or transcribe a video with searchts (open-source escalating unlocker)
argument-hint: <url | video url | search query>
---

Use the `searchts` CLI to satisfy this request. The argument is: $ARGUMENTS

Decide which subcommand to run based on what `$ARGUMENTS` looks like:

- **A web page / article URL** (http(s):// link that is not a video):
  run `searchts read "$ARGUMENTS"`. This fetches the page through an escalating
  open-source unlocker (browser-fingerprinted fetch -> JS-render relay ->
  stealth browser) and prints clean markdown.
- **A video / audio URL** (YouTube, podcast, or any media link) when a
  transcript is wanted: run `searchts transcribe "$ARGUMENTS"` to get a
  Whisper transcript. (`searchts read` is fine for the page text itself.)
- **Anything else (a search query, a question, a topic)**:
  run `searchts search "$ARGUMENTS"` for fusion-merged multi-source web results.

Rules:

- Prefer `searchts read` over the built-in fetch/WebFetch tool for pages that
  are blocked, return a bot-wall/CAPTCHA, or come back empty - the searchts
  unlocker is built to get past those.
- Pass `--json` when you need structured output to parse.
- If a command fails, read its stderr (it prints the per-backend breakdown) and
  report what was tried rather than silently giving up.
"""


def _slash_command_target_dir(dir_arg):
    """Resolve the commands directory for `skill install` (default ~/.claude/commands)."""
    if dir_arg:
        return os.path.abspath(os.path.expanduser(dir_arg))
    return os.path.expanduser(os.path.join("~", ".claude", "commands"))


def write_slash_command(target_dir):
    """Write searchts.md into `target_dir` (created if missing); return the path."""
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, "searchts.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_SLASH_COMMAND_BODY)
    return path


def _cmd_skill_install(args):
    """Write the Claude Code custom slash-command file (searchts.md)."""
    target_dir = _slash_command_target_dir(getattr(args, "dir", None))
    path = write_slash_command(target_dir)
    print(f"Wrote Claude Code slash-command: {path}")
    print("Use it in Claude Code with: /searchts <url | video url | query>")


# ── mcp command ─────────────────────────────────────


def mcp_install_text(client=None):
    """Return the wiring instructions for one client, or all when client is None.

    Pure string builder (no network, no side effects) so it is directly testable.
    """
    claude_cmd = "claude mcp add searchts -- searchts mcp serve"
    json_snippet = json.dumps(
        {"mcpServers": {"searchts": {"command": "searchts", "args": ["mcp", "serve"]}}},
        indent=2,
    )
    path_note = (
        "Note: `searchts` must be on your PATH (e.g. installed with pipx). "
        "If it isn't, replace `searchts` with the full path to the executable."
    )

    claude_block = "\n".join([
        "Claude Code - run this one-liner:",
        f"  {claude_cmd}",
    ])
    cursor_block = "\n".join([
        "Cursor / JSON config - add this to your mcp.json:",
        json_snippet,
    ])

    if client == "claude":
        return f"{claude_block}\n\n{path_note}"
    if client in ("cursor", "json"):
        return f"{cursor_block}\n\n{path_note}"

    return f"{claude_block}\n\n{cursor_block}\n\n{path_note}"


def _cmd_mcp(args):
    """Dispatch `searchts mcp serve|install`."""
    mcp_command = getattr(args, "mcp_command", None)
    if mcp_command == "serve":
        _cmd_mcp_serve()
    elif mcp_command == "install":
        print(mcp_install_text(getattr(args, "client", None)))
        from searchts.integrations.agent_wiring import check_agent_wiring
        checks = check_agent_wiring()
        if checks:
            print("\nDetected wiring on this machine:")
            for c in checks:
                mark = "[ok]" if c["wired"] else "[!] "
                extra = "" if c["wired"] else f"  (not registered — run: {c['hint']})"
                print(f"  {mark} {c['client']}{extra}")
    else:
        print("Usage: searchts mcp serve")
        print("   or: searchts mcp install [--client claude|cursor|json]")
        sys.exit(2)


def _cmd_mcp_serve():
    """Run the stdio MCP server, exiting cleanly if the optional `mcp` pkg is absent."""
    from searchts.integrations import mcp_server

    try:
        mcp_server.serve()
    except mcp_server.MCPNotInstalledError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


def _install_system_deps():
    """Install system-level dependencies: gh CLI, Node.js (for mcporter)."""
    import shutil
    import subprocess
    import platform
    import tempfile

    from searchts.utils.paths import get_ytdlp_config_dir, get_ytdlp_config_path

    print("Checking system dependencies...")

    # ── gh CLI ──
    if shutil.which("gh"):
        print("  [ok] gh CLI already installed")
    else:
        print("  Installing gh CLI...")
        os_type = platform.system().lower()
        if os_type == "linux":
            try:
                # Official GitHub apt source setup without invoking a shell.
                keyring_path = "/usr/share/keyrings/githubcli-archive-keyring.gpg"
                list_path = "/etc/apt/sources.list.d/github-cli.list"
                arch = subprocess.run(
                    ["dpkg", "--print-architecture"],
                    capture_output=True, encoding="utf-8", errors="replace", timeout=10,
                ).stdout.strip() or "amd64"
                subprocess.run(
                    ["curl", "-fsSL", "https://cli.github.com/packages/githubcli-archive-keyring.gpg", "-o", keyring_path],
                    capture_output=True, timeout=60,
                )
                repo_line = (
                    f"deb [arch={arch} signed-by={keyring_path}] "
                    "https://cli.github.com/packages stable main\n"
                )
                with open(list_path, "w", encoding="utf-8") as f:
                    f.write(repo_line)
                subprocess.run(["apt-get", "update", "-qq"], capture_output=True, timeout=60)
                subprocess.run(["apt-get", "install", "-y", "-qq", "gh"], capture_output=True, timeout=60)
                if shutil.which("gh"):
                    print("  [ok] gh CLI installed")
                else:
                    print("  [!]  gh CLI install failed. You can try: snap install gh, or download from https://github.com/cli/cli/releases")
            except Exception:
                print("  [!]  gh CLI install failed. You can try: snap install gh, or download from https://github.com/cli/cli/releases")
        elif os_type == "darwin":
            if shutil.which("brew"):
                try:
                    subprocess.run(["brew", "install", "gh"], capture_output=True, timeout=120)
                    if shutil.which("gh"):
                        print("  [ok] gh CLI installed")
                    else:
                        print("  [!]  gh CLI install failed. Try: brew install gh")
                except Exception:
                    print("  [!]  gh CLI install failed. Try: brew install gh")
            else:
                print("  [!]  gh CLI not found. Install: https://cli.github.com")
        else:
            print("  [!]  gh CLI not found. Install: https://cli.github.com")

    # ── Node.js (needed for mcporter) ──
    if shutil.which("node") and shutil.which("npm"):
        print("  [ok] Node.js already installed")
    else:
        print("  Installing Node.js...")
        try:
            # Use NodeSource setup script without invoking a shell pipeline.
            with tempfile.NamedTemporaryFile(delete=False, suffix=".sh") as tf:
                script_path = tf.name
            subprocess.run(
                ["curl", "-fsSL", "https://deb.nodesource.com/setup_22.x", "-o", script_path],
                capture_output=True, timeout=60,
            )
            subprocess.run(
                ["bash", script_path],
                capture_output=True, timeout=120,
            )
            try:
                os.unlink(script_path)
            except Exception:
                pass
            subprocess.run(
                ["apt-get", "install", "-y", "-qq", "nodejs"],
                capture_output=True, timeout=120,
            )
            if shutil.which("node"):
                print("  [ok] Node.js installed")
            else:
                print("  [!]  Node.js install failed. Try: apt install nodejs npm, or nvm install 22, or download from https://nodejs.org")
        except Exception:
            print("  [!]  Node.js install failed. Try: apt install nodejs npm, or nvm install 22, or download from https://nodejs.org")

    # ── undici (proxy support for Node.js fetch) ──
    npm_cmd = shutil.which("npm")
    if npm_cmd:
        npm_root = subprocess.run([npm_cmd, "root", "-g"], capture_output=True, encoding="utf-8", errors="replace", timeout=5).stdout.strip()
        undici_path = os.path.join(npm_root, "undici", "index.js") if npm_root else ""
        if os.path.exists(undici_path):
            print("  [ok] undici already installed (Node.js proxy support)")
        else:
            try:
                subprocess.run([npm_cmd, "install", "-g", "undici"], capture_output=True, encoding="utf-8", errors="replace", timeout=60)
                print("  [ok] undici installed (Node.js proxy support)")
            except Exception:
                print("  -- undici install failed (optional — may not work behind proxies)")

    # ── yt-dlp JS runtime config (YouTube requires external JS runtime) ──
    if shutil.which("node"):
        ytdlp_config_dir = get_ytdlp_config_dir()
        ytdlp_config = get_ytdlp_config_path()
        needs_config = True
        if os.path.exists(ytdlp_config):
            with open(ytdlp_config, "r", encoding="utf-8") as f:
                if "--js-runtimes" in f.read():
                    needs_config = False
                    print("  [ok] yt-dlp JS runtime already configured")
        if needs_config:
            try:
                os.makedirs(ytdlp_config_dir, exist_ok=True)
                with open(ytdlp_config, "a", encoding="utf-8") as f:
                    f.write("--js-runtimes node\n")
                print("  [ok] yt-dlp configured to use Node.js as JS runtime (YouTube)")
            except Exception:
                print("  -- Could not configure yt-dlp JS runtime (YouTube may not work)")

    # NOTE: twitter-cli etc. are optional.
    # They are installed via --channels flag, not here.
    # See CHANNEL_INSTALLERS in _cmd_install().


def _install_twitter_deps():
    """Install twitter-cli for Twitter search + timeline."""
    import shutil
    import subprocess

    print("Setting up Twitter (twitter-cli)...")
    if shutil.which("twitter"):
        print("  [ok] twitter-cli already installed")
        return
    for tool, cmd in [("pipx", ["pipx", "install", "twitter-cli"]),
                      ("uv", ["uv", "tool", "install", "twitter-cli"])]:
        if shutil.which(tool):
            try:
                subprocess.run(cmd, capture_output=True, encoding="utf-8",
                               errors="replace", timeout=120)
                if shutil.which("twitter"):
                    print("  [ok] twitter-cli installed")
                    return
            except Exception:
                pass
    print("  [!]  twitter-cli install failed. Run: pipx install twitter-cli")


def _install_opencli_deps():
    """Install OpenCLI — cross-platform backend riding the user's Chrome session.

    Desktop-only. The npm package installs automatically; the Chrome
    extension CANNOT be installed programmatically (Chrome security model),
    so we print a one-click guide instead.
    """
    import shutil
    import subprocess

    from searchts.backends import (
        OPENCLI_EXTENSION_URL,
        OPENCLI_PACKAGE,
        opencli_status,
        opencli_summary,
    )

    print("Setting up OpenCLI (browser-session backend, desktop only)...")
    st = opencli_status()
    if st.installed and not st.broken:
        print(f"  [ok] {opencli_summary(st)}")
        if not st.ready:
            print(f"  {st.hint}")
        return

    if not shutil.which("npm"):
        print("  [!]  OpenCLI requires Node.js ≥ 20. Install Node first:")
        print("       https://nodejs.org  (or brew install node)")
        return

    try:
        subprocess.run(
            ["npm", "install", "-g", OPENCLI_PACKAGE],
            capture_output=True, encoding="utf-8", errors="replace", timeout=300,
        )
    except Exception:
        pass

    st = opencli_status()
    if st.installed and not st.broken:
        print("  [ok] OpenCLI installed")
        print("  Final step (must be done manually, due to Chrome security restrictions): install the browser extension")
        print(f"    1. Open {OPENCLI_EXTENSION_URL}")
        print("    2. Click \"Add to Chrome\"")
        print("    3. Run `opencli doctor` to verify the connection")
    else:
        print(f"  [!]  OpenCLI install failed. Run: npm install -g {OPENCLI_PACKAGE}")


def _install_reddit_deps():
    """Set up Reddit — desktop prefers OpenCLI, rdt-cli for servers/legacy.

    No zero-config path exists (anonymous .json blocked, official API
    approval-gated since 2025-11) — every backend needs a logged-in session.
    """
    if _detect_environment() != "server":
        _install_opencli_deps()
        print("  Reddit uses OpenCLI (works once you have logged into reddit.com in the browser)")
        import shutil
        if shutil.which("rdt"):
            print("  [ok] Detected an existing rdt-cli; it will remain available as a fallback backend")
        return

    _install_rdt_cli()


def _install_rdt_cli():
    """Install rdt-cli (pinned git source — PyPI lags upstream)."""
    import shutil
    import subprocess

    print("Setting up Reddit (rdt-cli)...")
    if shutil.which("rdt"):
        print("  [ok] rdt-cli already installed")
        return
    for tool, cmd in [
        ("pipx", ["pipx", "install", _RDT_GIT_SOURCE]),
        ("uv", ["uv", "tool", "install", "--from", _RDT_GIT_SOURCE, "rdt-cli"]),
    ]:
        if shutil.which(tool):
            try:
                subprocess.run(cmd, capture_output=True, encoding="utf-8",
                               errors="replace", timeout=120)
                if shutil.which("rdt"):
                    print("  [ok] rdt-cli installed")
                    return
            except Exception:
                pass
    print(f"  [!]  rdt-cli install failed. Run: pipx install '{_RDT_GIT_SOURCE}'")


def _install_system_deps_safe():
    """Safe mode: check what's installed, print instructions for what's missing."""
    import shutil

    print("Checking system dependencies (safe mode — no auto-install)...")

    deps = [
        ("gh", ["gh"], "GitHub CLI", "https://cli.github.com — or: apt install gh / brew install gh"),
        ("node", ["node", "npm"], "Node.js", "https://nodejs.org — or: apt install nodejs npm"),
    ]

    missing = []
    for name, binaries, label, install_hint in deps:
        found = any(shutil.which(b) for b in binaries)
        if found:
            print(f"  [ok] {label} already installed")
        else:
            print(f"  -- {label} not found")
            missing.append((label, install_hint))

    if missing:
        print()
        print("  To install missing dependencies manually:")
        for label, hint in missing:
            print(f"    {label}: {hint}")
    else:
        print("  All system dependencies are installed!")


def _install_system_deps_dryrun():
    """Dry-run: just show what would be checked/installed."""
    import shutil

    print("[dry-run] System dependency check:")

    checks = [
        ("gh CLI", ["gh"], "apt install gh / brew install gh"),
        ("Node.js", ["node"], "curl NodeSource setup | bash + apt install nodejs"),
    ]

    for label, binaries, method in checks:
        found = any(shutil.which(b) for b in binaries)
        if found:
            print(f"  [ok] {label}: already installed, skip")
        else:
            print(f"  {label}: would install via: {method}")



def _install_mcporter():
    """Install mcporter and configure Exa search."""
    import shutil
    import subprocess

    print("Setting up mcporter (optional extra search provider; the recommended "
          "search is the keyless built-in 'searchts search')...")

    if shutil.which("mcporter"):
        print("  [ok] mcporter already installed")
    else:
        # Check for npm/npx
        if not shutil.which("npm") and not shutil.which("npx"):
            print("  [!]  mcporter requires Node.js. Install Node.js first:")
            print("     https://nodejs.org/ or: curl -fsSL https://fnm.vercel.app/install | bash")
            return
        try:
            subprocess.run(
                ["npm", "install", "-g", "mcporter"],
                capture_output=True, encoding="utf-8", errors="replace", timeout=120,
            )
            if shutil.which("mcporter"):
                print("  [ok] mcporter installed")
            else:
                print("  [X] mcporter install failed. Retry: npm install -g mcporter (check network/timeout), or try: npx mcporter@latest list")
                return
        except Exception as e:
            print(f"  [X] mcporter install failed: {e}")
            return

    # Configure Exa MCP (free, no key needed)
    try:
        r = subprocess.run(
            ["mcporter", "config", "list"], capture_output=True, encoding="utf-8", errors="replace", timeout=5
        )
        if "exa" not in r.stdout:
            subprocess.run(
                ["mcporter", "config", "add", "exa", "https://mcp.exa.ai/mcp"],
                capture_output=True, encoding="utf-8", errors="replace", timeout=10,
            )
            print("  [ok] Exa search configured (free, no API key needed)")
        else:
            print("  [ok] Exa search already configured")
    except Exception:
        print("  [!]  Could not configure Exa. Run manually: mcporter config add exa https://mcp.exa.ai/mcp")


def _install_mcporter_safe():
    """Safe mode: check mcporter status, print instructions.

    mcporter/Exa is an OPTIONAL extra search provider, not the recommended path.
    The recommended search is the keyless built-in `searchts search`.
    """
    import shutil

    print("Search: the recommended path is the keyless built-in 'searchts search'")
    print("  (DuckDuckGo + RRF fusion, no Node/npm needed). Just run: searchts search \"query\"")
    print("Checking mcporter (optional extra Exa provider)...")

    if shutil.which("mcporter"):
        print("  [ok] mcporter already installed")
        print("  Optional — to add Exa as an extra provider: mcporter config add exa https://mcp.exa.ai/mcp")
    else:
        print("  -- mcporter not installed (optional; not required for search)")
        print("  Optional — to install: npm install -g mcporter")
        print("  Then add Exa: mcporter config add exa https://mcp.exa.ai/mcp")


def _detect_environment():
    """Auto-detect if running on local computer or server."""
    import os

    # Check common server indicators
    indicators = 0

    # SSH session
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_CLIENT"):
        indicators += 2

    # Docker / container
    if os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv"):
        indicators += 2

    # No display (headless)
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        indicators += 1

    # Cloud VM identifiers
    for cloud_file in ["/sys/hypervisor/uuid", "/sys/class/dmi/id/product_name"]:
        if os.path.exists(cloud_file):
            try:
                with open(cloud_file) as f:
                    content = f.read().lower()
                if any(x in content for x in ["amazon", "google", "microsoft", "digitalocean", "linode", "vultr", "hetzner"]):
                    indicators += 2
            except Exception:
                pass

    # systemd-detect-virt
    try:
        import subprocess
        result = subprocess.run(["systemd-detect-virt"], capture_output=True, encoding="utf-8", errors="replace", timeout=3)
        if result.returncode == 0 and result.stdout.strip() != "none":
            indicators += 1
    except Exception:
        pass

    return "server" if indicators >= 2 else "local"


def _cmd_configure(args):
    """Set a config value and test it, or auto-extract from browser."""
    import shutil
    from searchts.config import Config

    config = Config()

    # ── Auto-extract from browser ──
    if args.from_browser:
        from searchts.cookie_extract import configure_from_browser

        browser = args.from_browser
        print(f"Extracting cookies from {browser}...")
        print()

        results = configure_from_browser(browser, config)

        found_any = False
        for platform, success, message in results:
            if success:
                print(f"  [ok] {platform}: {message}")
                found_any = True
            else:
                print(f"  -- {platform}: {message}")

        print()
        if found_any:
            print("[ok] Cookies configured! Run `searchts doctor` to see updated status.")
        else:
            print(f"No cookies found. Make sure you're logged into the platforms in {browser}.")
        return

    # ── Manual configure ──
    if not args.key:
        print("Usage: searchts configure <key> <value>")
        print("   or: searchts configure --from-browser chrome")
        return

    value = " ".join(args.value) if args.value else ""
    if not value:
        print(f"Missing value for {args.key}")
        return

    if args.key == "proxy":
        # Generic network proxy for restricted environments. Nothing reads
        # this key at runtime — agents read it back and export HTTP(S)_PROXY
        # before invoking upstream tools (see docs/install.md).
        config.set("proxy", value)
        print("[ok] Proxy saved (for the agent to set HTTP_PROXY/HTTPS_PROXY when accessing networks that need a proxy, such as Reddit/Twitter)")

    elif args.key == "twitter-cookies":
        # Accept two formats:
        # 1. auth_token ct0 (two separate values)
        # 2. Full cookie header string: "auth_token=xxx; ct0=yyy; ..."
        auth_token, ct0 = _parse_twitter_cookie_input(value)

        if auth_token and ct0:
            config.set("twitter_auth_token", auth_token)
            config.set("twitter_ct0", ct0)

            # Sync credentials to twitter-cli env
            print("[ok] Twitter cookies configured!")

            print("Testing Twitter access...", end=" ")
            try:
                import subprocess
                twitter_bin = shutil.which("twitter")
                if not twitter_bin:
                    print("[!] twitter-cli not installed. Run: pipx install twitter-cli")
                else:
                    import os
                    env = os.environ.copy()
                    env["TWITTER_AUTH_TOKEN"] = auth_token
                    env["TWITTER_CT0"] = ct0
                    result = subprocess.run(
                        [twitter_bin, "status"],
                        capture_output=True, encoding="utf-8", errors="replace", timeout=15,
                        env=env,
                    )
                    output = (result.stdout or "") + (result.stderr or "")
                    if "ok: true" in output:
                        print("[ok] Twitter access works!")
                    else:
                        print("[!] Auth check failed (cookies might be wrong)")
            except Exception as e:
                print(f"[X] Failed: {e}")
        else:
            print("[X] Could not find auth_token and ct0 in your input.")
            print("   Accepted formats:")
            print("   1. searchts configure twitter-cookies AUTH_TOKEN CT0")
            print('   2. searchts configure twitter-cookies "auth_token=xxx; ct0=yyy; ..."')

    elif args.key == "youtube-cookies":
        config.set("youtube_cookies_from", value)
        print(f"[ok] YouTube cookie source configured: {value}")
        print("   yt-dlp will use cookies from this browser for age-restricted/member videos.")

    elif args.key == "github-token":
        config.set("github_token", value)
        print(f"[ok] GitHub token configured!")

    elif args.key == "groq-key":
        config.set("groq_api_key", value)
        print(f"[ok] Groq key configured!")

    elif args.key == "openai-key":
        config.set("openai_api_key", value)
        print(f"[ok] OpenAI key configured!")


def _cmd_transcribe(args):
    """Transcribe a URL or local audio file.

    Subtitles-first: a captioned URL is returned straight from its existing
    captions (no API key needed). Falls back to Whisper audio transcription
    (Groq -> OpenAI, or keyless local) only when there are no usable subtitles,
    or when --no-subtitles forces the audio path.
    """
    from pathlib import Path

    from searchts.transcribe import TranscribeError, transcribe

    try:
        text = transcribe(
            args.source,
            provider=args.provider,
            prefer_subtitles=args.prefer_subtitles,
        )
    except TranscribeError as e:
        print(f"[x] {e}")
        sys.exit(1)

    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(f"[ok] Transcript written to {args.output}")
    else:
        print(text)


def _parse_twitter_cookie_input(value: str):
    """Parse Twitter cookie input from either separate values or a cookie header."""
    auth_token = None
    ct0 = None

    if "auth_token=" in value and "ct0=" in value:
        # Full cookie string — parse it.
        for part in value.replace(";", " ").split():
            if part.startswith("auth_token="):
                auth_token = part.split("=", 1)[1]
            elif part.startswith("ct0="):
                ct0 = part.split("=", 1)[1]
    elif len(value.split()) == 2 and "=" not in value:
        # Two separate values: AUTH_TOKEN CT0.
        parts = value.split()
        auth_token = parts[0]
        ct0 = parts[1]

    return auth_token, ct0


def _cmd_uninstall(args):
    """Remove all searchts config, tokens, and skill files."""
    import shutil
    import subprocess

    dry_run = args.dry_run
    keep_config = args.keep_config

    print()
    print("searchts Uninstaller")
    print("=" * 40)

    if dry_run:
        print("DRY RUN — showing what would be removed (no changes)")
        print()

    removed_any = False

    # ── 1. Config directory (~/.searchts/) ──
    config_dir = os.path.expanduser("~/.searchts")
    if not keep_config:
        if os.path.isdir(config_dir):
            if dry_run:
                print(f"[dry-run] Would remove config directory: {config_dir}")
                print("          (contains config.yaml with all tokens/cookies/API keys)")
            else:
                try:
                    shutil.rmtree(config_dir)
                    print(f"  Removed config directory: {config_dir}")
                    removed_any = True
                except Exception as e:
                    print(f"  Could not remove {config_dir}: {e}")
        else:
            print(f"  Config directory not found (already clean): {config_dir}")
    else:
        print(f"  Skipping config directory (--keep-config): {config_dir}")

    # ── 2. Skill files ──
    skill_dirs = [
        ("~/.openclaw/skills/searchts", "OpenClaw"),
        ("~/.claude/skills/searchts", "Claude Code"),
        ("~/.agents/skills/searchts", "Agent"),
    ]

    for skill_path_template, platform_name in skill_dirs:
        skill_path = os.path.expanduser(skill_path_template)
        if os.path.isdir(skill_path):
            if dry_run:
                print(f"[dry-run] Would remove {platform_name} skill: {skill_path}")
            else:
                try:
                    if os.path.islink(skill_path):
                        os.unlink(skill_path)
                    else:
                        shutil.rmtree(skill_path)
                    print(f"  Removed {platform_name} skill: {skill_path}")
                    removed_any = True
                except Exception as e:
                    print(f"  Could not remove {skill_path}: {e}")

    # ── 3. mcporter MCP entries ──
    if shutil.which("mcporter"):
        for mcp_name in ("exa",):
            try:
                r = subprocess.run(
                    ["mcporter", "list"], capture_output=True, encoding="utf-8", errors="replace", timeout=10
                )
                if mcp_name in r.stdout:
                    if dry_run:
                        print(f"[dry-run] Would remove mcporter entry: {mcp_name}")
                    else:
                        subprocess.run(
                            ["mcporter", "config", "remove", mcp_name],
                            capture_output=True, encoding="utf-8", errors="replace", timeout=10,
                        )
                        print(f"  Removed mcporter entry: {mcp_name}")
                        removed_any = True
            except Exception:
                pass

    # ── 4. Summary and optional steps ──
    print()
    if dry_run:
        print("Dry run complete. No changes were made.")
        print("Run without --dry-run to actually remove the above.")
    else:
        if removed_any:
            print("searchts data removed.")
        else:
            print("Nothing to remove — already clean.")

    print()
    print("Optional: remove the searchts Python package itself:")
    print("  pip uninstall searchts")
    print()
    print("Optional: remove tools installed by searchts:")
    print("  npm uninstall -g mcporter")
    print("  pipx uninstall twitter-cli")
    print("  npm uninstall -g undici")


def _cmd_read(args):
    """Fetch a URL through the unlocker and print clean markdown.

    Content goes to stdout (so it is pipeable); any status/diagnostics go to
    stderr. On total failure, print the per-backend breakdown to stderr and
    exit nonzero.
    """
    from searchts import unlocker

    backends = [args.backend] if args.backend else None
    try:
        result = unlocker.fetch(
            args.url, backends=backends, allow_human=args.human,
            scrub=getattr(args, "scrub", False),
        )
    except unlocker.UnlockerError as e:
        print(f"Failed to read {e.url}", file=sys.stderr)
        for backend, why in e.attempts:
            print(f"  {backend}: {why}", file=sys.stderr)
        sys.exit(1)

    # Surface prompt-injection findings to stderr so stdout stays clean content.
    if result.warnings:
        print(f"[!] {len(result.warnings)} possible prompt-injection indicator(s) detected",
              file=sys.stderr)

    if args.json:
        payload = {
            "url": args.url,
            "backend": result.backend,
            "status": result.status,
            "chars": len(result.text),
            "text": result.text,
        }
        print(json.dumps(payload, ensure_ascii=False))
    else:
        # Status to stderr so stdout stays a clean, pipeable content stream.
        print(f"[{result.backend}] status={result.status} chars={len(result.text)}",
              file=sys.stderr)
        print(result.text)


def _cmd_get(args):
    """Download one asset through the unlock ladder; print the saved path."""
    from searchts import assets

    try:
        path = assets.get_asset(args.url, args.output)
    except assets.AssetError as e:
        print(f"Failed to get asset: {e}", file=sys.stderr)
        sys.exit(1)
    size = path.stat().st_size if path.exists() else 0
    print(f"saved {path} ({size} bytes)", file=sys.stderr)
    print(str(path))


def _cmd_grab(args):
    """Grab a page's assets + color palette + fonts (design inspiration)."""
    from urllib.parse import urlparse

    from searchts import assets

    out = args.out
    if not out:
        host = urlparse(assets.normalize(args.url)).netloc.replace(":", "_") or "site"
        out = f"searchts-grab-{host}"
    kinds = tuple(k.strip() for k in (args.kinds or "").split(",") if k.strip())
    try:
        manifest = assets.grab(
            args.url, out, kinds=kinds, include_scripts=args.scripts,
            read=args.read, max_assets=args.max_assets,
        )
    except assets.AssetError as e:
        print(f"Failed to grab {args.url}: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(manifest, ensure_ascii=False))
        return
    title = manifest.get("title") or "(no title)"
    palette = " ".join(c["hex"] for c in manifest.get("palette", [])[:8])
    fonts = ", ".join(manifest.get("fonts", [])[:6])
    print(f"[grab] {title}", file=sys.stderr)
    print(f"  page via {manifest.get('page_backend', '?')}; downloaded "
          f"{manifest.get('downloaded', 0)} assets -> {out}/", file=sys.stderr)
    if palette:
        print(f"  palette: {palette}", file=sys.stderr)
    if fonts:
        print(f"  fonts:   {fonts}", file=sys.stderr)
    print(os.path.join(out, "manifest.json"))


def _parse_provider_flags(provider_args):
    """Flatten repeatable/comma-list --provider flags into an ordered name list.

    Returns None when no flag was given (so search() uses its default selection),
    else a de-duplicated, lower-cased list preserving first-seen order.
    """
    if not provider_args:
        return None
    names = []
    for chunk in provider_args:
        for name in chunk.split(","):
            name = name.strip().lower()
            if name and name not in names:
                names.append(name)
    return names or None


def _cmd_search(args):
    """Multi-source web search; print a numbered list or JSON.

    On total failure, print the per-provider breakdown to stderr and exit
    nonzero (mirrors `read`).
    """
    from searchts import search as search_mod

    providers = _parse_provider_flags(args.provider)
    try:
        results = search_mod.search(
            args.query, max_results=args.max_results, providers=providers,
        )
    except search_mod.SearchError as e:
        print(f"Search failed for {e.query!r}", file=sys.stderr)
        for provider, why in e.attempts:
            print(f"  {provider}: {why}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        payload = [
            {"title": r.title, "url": r.url, "snippet": r.snippet, "source": r.source}
            for r in results
        ]
        print(json.dumps(payload, ensure_ascii=False))
        return

    for i, r in enumerate(results, start=1):
        snippet = r.snippet.replace("\n", " ").strip()
        if len(snippet) > 200:
            snippet = snippet[:197] + "..."
        print(f"{i}. {r.title or '(no title)'}")
        print(f"   {r.url}")
        if snippet:
            print(f"   {snippet}")
        if r.source:
            print(f"   [{r.source}]")


def _cmd_doctor(args=None):
    from searchts.config import Config
    from searchts.doctor import check_all, format_report
    try:
        from rich import print as rprint
    except ImportError:
        rprint = print
    config = Config()
    results = check_all(config)

    if args is not None and getattr(args, "json", False):
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    rprint(format_report(results))

    from searchts.integrations.agent_wiring import format_wiring_report
    rprint(format_wiring_report())

    # Auto-install skill if not already present (fixes #154)
    _install_skill()


def _cmd_setup():
    from searchts.config import Config

    config = Config()
    print()
    print("searchts Setup")
    print("=" * 40)
    print()

    # Step 1: Web search — first-party keyless `searchts search` is recommended.
    import shutil
    import subprocess

    print("[Recommended] Web-wide search -- searchts search")
    print("  Built in, keyless (DuckDuckGo + RRF fusion). No Node/npm or extra setup.")
    print("  Try it: searchts search \"your query\"")
    print()

    # Optional: Exa via mcporter is still supported as an extra provider, but no
    # longer the recommended path (it needs Node/npm). Only surfaced if present.
    if shutil.which("mcporter"):
        print("[Optional] Exa (via mcporter) -- extra search provider")
        try:
            r = subprocess.run(
                ["mcporter", "config", "list"], capture_output=True, encoding="utf-8", errors="replace", timeout=10
            )
            if "exa" in r.stdout.lower():
                print("  Current status: [ok] configured")
            else:
                print("  Current status: -- not configured")
                setup_now = input("  Configure Exa automatically now? [y/N]: ").strip().lower()
                if setup_now in ("y", "yes"):
                    add_r = subprocess.run(
                        ["mcporter", "config", "add", "exa", "https://mcp.exa.ai/mcp"],
                        capture_output=True, encoding="utf-8", errors="replace", timeout=10,
                    )
                    if add_r.returncode == 0:
                        print("  [ok] Exa configured")
                    else:
                        print("  [!] Automatic configuration failed, please run manually:")
                        print("     mcporter config add exa https://mcp.exa.ai/mcp")
        except Exception:
            print("  [!] Could not check the Exa configuration, please run manually:")
            print("     mcporter config add exa https://mcp.exa.ai/mcp")
        print()

    # Step 2: GitHub token
    print("[Optional] GitHub Token -- raise the API rate limit")
    print("  Without token: 60/hour | With token: 5000/hour")
    print("  Get one: https://github.com/settings/tokens (no permissions required)")
    current = config.get("github_token")
    if current:
        print(f"  Current status: [ok] configured")
    else:
        key = input("  GITHUB_TOKEN (press Enter to skip): ").strip()
        if key:
            config.set("github_token", key)
            print("  [ok] GitHub API raised to 5000/hour!")
        else:
            print("  Skipped. The public API works too")
    print()

    # Step 3: Reddit — rdt-cli
    print("[Info] Reddit -- a logged-in session is mandatory (no zero-config path). OpenCLI is recommended on desktop; or rdt-cli:")
    print(f"  Install: pipx install '{_RDT_GIT_SOURCE}'")
    print("  Then run: rdt login (you must log into reddit.com in the browser first)")
    print()

    # Step 4: Groq (Whisper)
    print("[Optional] Groq API -- speech-to-text for videos without subtitles")
    print("  Free tier, sign up: https://console.groq.com")
    current = config.get("groq_api_key")
    if current:
        print(f"  Current status: [ok] configured")
    else:
        key = input("  GROQ_API_KEY (press Enter to skip): ").strip()
        if key:
            config.set("groq_api_key", key)
            print("  [ok] Speech-to-text enabled!")
        else:
            print("  Skipped")
    print()

    # Summary
    print("=" * 40)
    print(f"[ok] Configuration saved to {config.config_path}")
    print("Run searchts doctor to see the full status")
    print()


def _classify_update_error(exc):
    """Classify update-check errors for user-friendly diagnostics."""
    import requests

    if isinstance(exc, requests.exceptions.Timeout):
        return "timeout"
    if isinstance(exc, requests.exceptions.ConnectionError):
        msg = str(exc).lower()
        dns_markers = [
            "name or service not known",
            "temporary failure in name resolution",
            "nodename nor servname",
            "getaddrinfo failed",
            "name resolution",
            "dns",
        ]
        if any(marker in msg for marker in dns_markers):
            return "dns"
        return "connection"
    if isinstance(exc, requests.exceptions.HTTPError):
        return "http"
    return "unknown"


def _update_error_text(kind):
    """Map internal error kinds to user-facing text."""
    mapping = {
        "timeout": "Network timeout",
        "dns": "DNS resolution failed",
        "rate_limit": "GitHub API rate limit",
        "connection": "Network connection failed",
        "server_error": "GitHub service temporarily unavailable",
        "http": "HTTP request failed",
        "unknown": "Unknown network error",
    }
    return mapping.get(kind, "Request failed")


def _classify_github_response_error(resp):
    """Classify non-200 GitHub responses that merit special handling."""
    if resp is None:
        return "unknown"
    if resp.status_code == 429:
        return "rate_limit"
    if resp.status_code == 403:
        remaining = resp.headers.get("X-RateLimit-Remaining", "")
        if remaining == "0":
            return "rate_limit"
        try:
            message = resp.json().get("message", "").lower()
            if "rate limit" in message:
                return "rate_limit"
        except Exception:
            pass
    if 500 <= resp.status_code < 600:
        return "server_error"
    return None


def _github_get_with_retry(url, timeout=10, retries=3, sleeper=time.sleep):
    """GET GitHub API with retry/backoff and basic error classification."""
    import requests

    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=timeout)
        except requests.exceptions.RequestException as exc:
            if attempt >= retries:
                return None, _classify_update_error(exc), attempt
            sleeper(2 ** (attempt - 1))
            continue

        err_kind = _classify_github_response_error(resp)
        if err_kind in ("rate_limit", "server_error"):
            if attempt >= retries:
                return None, err_kind, attempt
            delay = 2 ** (attempt - 1)
            retry_after = resp.headers.get("Retry-After")
            if err_kind == "rate_limit" and retry_after:
                try:
                    delay = max(delay, float(retry_after))
                except Exception:
                    pass
            sleeper(delay)
            continue

        return resp, None, attempt

    return None, "unknown", retries


#: Full update = package + upstream tools + skill. The one-liner walks an
#: agent through all three (docs/update.md); bare pip only updates the package.
_UPDATE_INSTRUCTIONS = (
    "How to update (recommended -- copy this line to your AI agent to fully update the package + upstream tools + skill):\n"
    "  Update searchts for me: https://raw.githubusercontent.com/capad-xyz/searchts/main/docs/update.md\n"
    "Update the package only (without upstream tools and skill):\n"
    "  pip install --upgrade https://github.com/capad-xyz/searchts/archive/main.zip"
)


def _is_newer_version(remote: str, local: str) -> bool:
    """True if remote is strictly newer than local (semantic compare).

    A plain != would tell users "update available" when their local build is
    AHEAD of the latest release (e.g. installed from main during a release
    window) — and walk them into a downgrade.
    """
    def parse(v):
        try:
            return tuple(int(x) for x in v.strip().split("."))
        except ValueError:
            return None

    r, l = parse(remote), parse(local)
    if r is None or l is None:
        return remote != local  # unparseable — fall back to old behavior
    return r > l


def _cmd_check_update():
    """Check for newer versions on GitHub."""
    from searchts import __version__

    print(f"Current version: v{__version__}")
    release_url = "https://api.github.com/repos/capad-xyz/searchts/releases/latest"
    commit_url = "https://api.github.com/repos/capad-xyz/searchts/commits/main"

    # Fetch latest release with retry/backoff.
    resp, err, attempts = _github_get_with_retry(release_url, timeout=10, retries=3)
    if err:
        print(f"[!] Could not check for updates ({_update_error_text(err)}, retried {attempts} times)")
        return "error"

    if resp.status_code == 200:
        data = resp.json()
        latest = data.get("tag_name", "").lstrip("v")
        body = data.get("body", "")

        if latest and _is_newer_version(latest, __version__):
            print(f"Latest version: v{latest} <- update available!")
            if body:
                print()
                print("What's new:")
                # Show first 20 lines of release notes
                for line in body.strip().split("\n")[:20]:
                    print(f"  {line}")
            print()
            print(_UPDATE_INSTRUCTIONS)
            return "update_available"
        print(f"[ok] Already up to date")
        return "up_to_date"

    release_err = _classify_github_response_error(resp)
    if release_err == "rate_limit":
        print("[!] Could not check for updates (GitHub API rate limit, please try again later)")
        return "error"

    # No releases yet, fall back to latest main commit.
    resp2, err2, attempts2 = _github_get_with_retry(commit_url, timeout=10, retries=2)
    if err2:
        print(f"[!] Could not check for updates ({_update_error_text(err2)}, retried {attempts + attempts2} times)")
        return "error"
    if resp2.status_code == 200:
        commit = resp2.json()
        sha = commit.get("sha", "")[:7]
        msg = commit.get("commit", {}).get("message", "").split("\n")[0]
        date = commit.get("commit", {}).get("committer", {}).get("date", "")[:10]
        print(f"Latest commit: {sha} ({date}) {msg}")
        print()
        print(_UPDATE_INSTRUCTIONS)
        return "unknown"

    commit_err = _classify_github_response_error(resp2)
    if commit_err == "rate_limit":
        print("[!] Could not check for updates (GitHub API rate limit, please try again later)")
        return "error"

    print(f"[!] Could not check for updates (GitHub returned {resp2.status_code})")
    return "error"


def _cmd_watch():
    """Quick health check + update check, designed for scheduled tasks.

    Only outputs problems. If everything is fine, outputs a single line.
    """
    from searchts.config import Config
    from searchts.doctor import check_all
    from searchts import __version__

    config = Config()
    issues = []

    # Check channels
    results = check_all(config)
    ok = sum(1 for r in results.values() if r["status"] == "ok")
    total = len(results)

    # Find broken channels (were working, now broken)
    for key, r in results.items():
        if r["status"] in ("off", "error"):
            issues.append(f"[X] {r['name']}: {r['message']}")
        elif r["status"] == "warn":
            issues.append(f"[!] {r['name']}: {r['message']}")

    # Check for updates
    update_available = False
    new_version = ""
    release_body = ""
    resp, err, _attempts = _github_get_with_retry(
        "https://api.github.com/repos/capad-xyz/searchts/releases/latest",
        timeout=10,
        retries=2,
    )
    if not err and resp and resp.status_code == 200:
        data = resp.json()
        latest = data.get("tag_name", "").lstrip("v")
        if latest and _is_newer_version(latest, __version__):
            update_available = True
            new_version = latest
            release_body = data.get("body", "")

    # Output
    if not issues and not update_available:
        print(f"searchts: All systems normal ({ok}/{total} channels available, v{__version__} is up to date)")
        return

    print(f"searchts monitoring report")
    print(f"=" * 40)
    print(f"Version: v{__version__}  |  Channels: {ok}/{total}")

    if issues:
        print()
        for issue in issues:
            print(f"  {issue}")

    if update_available:
        print()
        print(f"New version available: v{new_version}")
        if release_body:
            for line in release_body.strip().split("\n")[:10]:
                print(f"    {line}")
        print("  Update (send this one line to your agent for a full update):")
        print("    Update searchts for me: https://raw.githubusercontent.com/capad-xyz/searchts/main/docs/update.md")


if __name__ == "__main__":
    main()
