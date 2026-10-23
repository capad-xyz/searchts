# -*- coding: utf-8 -*-
"""
searchts CLI — installer, doctor, and configuration tool.

Usage:
    searchts install --env=auto
    searchts install --browser
    searchts update
    searchts doctor
    searchts configure twitter-cookies "auth_token=xxx; ct0=yyy"
    searchts setup
"""

import argparse
import difflib
import json
import os
import sys
import textwrap
import time
from typing import Dict, List, Optional, Tuple

from searchts import __version__

# Pinned to the 0.4.2 state — PyPI still only has 0.4.1 (upstream issue #10).
_RDT_GIT_SOURCE = "git+https://github.com/public-clis/rdt-cli.git@5e4fb3720d5c174e976cd425ccc3b879d52cac66"

# Keys `searchts configure` accepts, in the order a bare `configure` lists them.
# github-token and youtube-cookies stay in the list so the refusal is
# discoverable. Neither is written to the YAML file.
_CONFIGURE_KEYS = (
    "proxy",
    "github-token",
    "groq-key",
    "openai-key",
    "twitter-cookies",
    "youtube-cookies",
)


def _ensure_utf8_console():
    """Best-effort console encoding setup for CLI runtime only.

    Windows writes UTF-8 through the console buffer, which the console decodes
    to UTF-16, so braille and box drawing survive a cp437 code page. Everywhere
    else the locale's encoding stays, but an unencodable glyph is replaced
    instead of raising: ``LC_ALL=C`` in a container is the case that matters,
    and a doctor tick carrying an ellipsis should not become a traceback.
    """
    # Avoid interfering with pytest/captured streams.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    if sys.platform == "win32":
        try:
            import io
            if hasattr(sys.stdout, "buffer"):
                sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
            if hasattr(sys.stderr, "buffer"):
                sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
        except Exception:
            # Do not crash CLI just because encoding patch failed.
            pass
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):
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


#: The first-run screen is now drawn by ``searchts.helptext`` rather than by
#: argparse: the zero-arg invocation and ``--help`` are the same document, and
#: it opens with the belief rather than with ``positional arguments:``.


def _run():
    """Parse argv and dispatch to a command handler.

    Kept separate from main() so the entry point can translate the two
    interpreter-level failures every piped/interactive CLI hits into clean
    exits instead of tracebacks.
    """
    _ensure_utf8_console()
    from searchts.config import load_dotenv_if_available
    load_dotenv_if_available()
    try:
        from searchts.integrations.memory_rule import refresh_known_rules
        refresh_known_rules()
    except OSError:
        pass

    parser = argparse.ArgumentParser(
        prog="searchts",
        description="Give your AI Agent eyes to see the entire internet",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Show debug logs")
    parser.add_argument("--version", action="version", version=f"searchts v{__version__}")
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # `-v` is accepted both before and after the subcommand. SUPPRESS on the
    # subparser copy keeps the top-level value from being clobbered when the
    # sub-level flag is absent.
    _verbose = argparse.ArgumentParser(add_help=False)
    _verbose.add_argument("-v", "--verbose", action="store_true",
                          default=argparse.SUPPRESS, help="Show debug logs")

    # One registry, so a browser supported by the reader is never rejected by a
    # stale list in the parser. `configure --from-browser` used to accept only
    # five browsers and refused `zen`, which the reader handles fine.
    from searchts.session_cookies import ALL_BROWSERS as _BROWSER_CHOICES

    # ── setup ──
    sub.add_parser("setup", parents=[_verbose], help="Interactive configuration wizard")

    # ── install ──
    p_install = sub.add_parser("install", parents=[_verbose],
                               help="One-shot installer with flags")
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
                                "(twitter,reddit,opencli,linkedin,all)")
    p_install.add_argument(
        "--browser",
        action="store_true",
        help="Install searchts[browser] + Chromium into this CLI's environment "
             "(same interpreter as the running searchts). Refuses ephemeral uvx.",
    )

    # ── configure ──
    p_conf = sub.add_parser("configure", parents=[_verbose],
                            help="List keys, set a value, or copy cookies from a browser")
    p_conf.add_argument("key", nargs="?", default=None,
                        choices=list(_CONFIGURE_KEYS),
                        help="What to configure. Omit the key to list every key, "
                             "its default, and set or unset. "
                             "github-token and youtube-cookies are accepted so the "
                             "refusal is discoverable, but are not stored: "
                             "github-token -> export GITHUB_TOKEN/GH_TOKEN (or .env); "
                             "youtube-cookies -> transcribe <url> "
                             "--cookies-from-browser <browser>")
    p_conf.add_argument("value", nargs="*", help="The value(s) to set")
    p_conf.add_argument("--from-browser", metavar="BROWSER",
                        choices=_BROWSER_CHOICES,
                        help="Auto-extract ALL platform cookies from browser "
                             "(any supported browser: Zen, Firefox, Chrome, Vivaldi, Edge, Brave, Opera, Arc, ...)")

    # ── read ──
    p_read = sub.add_parser("read", parents=[_verbose],
                            help="Fetch a URL through the escalating unlocker and print clean markdown")
    p_read.add_argument("url", help="The URL to read")
    p_read.add_argument("--backend", default=None,
                        help="Force a single backend (e.g. curl_cffi, 'Jina Reader', stealth-browser)")
    p_read.add_argument("--json", action="store_true",
                        help="Print the result as JSON instead of raw text: "
                             "url, final_url, fetched_at, backend, status, chars, "
                             "text, next_url and more")
    p_read.add_argument("--human", action="store_true",
                        help="If no tier gets clean content, open a headful browser to clear it by hand")
    p_read.add_argument("--pages", type=int, default=1,
                        help="Follow the next page on the same site, curl only, up to this many (max 5)")
    p_read.add_argument("--items", type=int, default=0,
                        help="Keep following next pages, then scroll if the list only grows that way, "
                             "until this many list rows (ceiling SEARCHTS_MAX_ITEMS, max 300)")
    p_read.add_argument(
        "--media", type=int, default=0,
        help="How many image and video addresses the media note lists "
             "(default 4, ceiling 40). Does not download them; "
             "searchts grab saves the files. SEARCHTS_MAX_MEDIA or more.media "
             "in the config changes the default.",
    )
    p_read.add_argument(
        "--expand",
        action="store_true",
        help="Open the text the page is holding back: closed <details> and buttons "
             "labelled read/show/see more, and a known host's own controls (a Reddit "
             "thread's 'more replies'). Off by default. Never follows a link, a form "
             "or a sign-in; a 'continue reading' paywall is named, not opened "
             "(ceiling SEARCHTS_MAX_EXPAND_CLICKS)",
    )
    p_read.add_argument("--scrub", action="store_true",
                        help="Redact prompt-injection spans from the content (invisible-char "
"stripping + indicator scanning always run regardless)")
    p_read.add_argument(
        "--cookies-from-browser",
        metavar="BROWSER",
        choices=_BROWSER_CHOICES,
        help="Read YOUR browser's cookies for this site only (opt-in)",
    )
    p_read.add_argument(
        "--yes",
        action="store_true",
        help="Approve copying cookies out of YOUR browser, this session only. "
             "Without it --cookies-from-browser is refused, because the copy "
             "is never silent.",
    )
    p_read.add_argument(
        "--cookies",
        metavar="PATH",
        help="Read a searchts-owned cookie file for this site only (opt-in)",
    )
    p_read.add_argument(
        "--cdp-port",
        metavar="PORT",
        help="Read this site's cookies from your localhost debugger port (opt-in)",
    )
    p_read.add_argument(
        "--proxy",
        metavar="URL",
        help="Route the read through a proxy (http/https/socks), e.g. "
             "socks5://127.0.0.1:7890. For blocks decided on your address, "
             "which no fingerprint can move. Falls back to the `proxy` config "
             "value. Omitted means your own IP, as before.",
    )
    p_read.add_argument(
        "--proxy-trusted",
        action="store_true",
        help="Accept that a remote proxy operator can see the Cookie header",
    )

    # ── search ──
    p_search = sub.add_parser("search", parents=[_verbose],
                              help="Find URLs to read (fusion-merged across providers). A snippet is not the page")
    p_search.add_argument("query", help="The search query")
    p_search.add_argument("-n", dest="max_results", type=int, default=10,
                          metavar="N",
                          help="Maximum number of fused results to return (default: 10)")
    p_search.add_argument("--json", action="store_true",
                          help="Print the list of result dicts as JSON instead of a numbered list")
    p_search.add_argument("--provider", action="append", default=None, metavar="NAME",
                          help="Restrict to a provider (repeatable, or a comma-separated list); "
                               "e.g. --provider duckduckgo --provider brave")

    # ── doctor ──
    p_doctor = sub.add_parser("doctor", parents=[_verbose], help="Check platform availability")
    p_doctor.add_argument("--json", action="store_true",
                          help="Output machine-readable JSON instead of the text report")

    # ── uninstall ──
    p_uninstall = sub.add_parser("uninstall", parents=[_verbose],
                                 help="Remove all searchts config, tokens, and skill files")
    p_uninstall.add_argument("--dry-run", action="store_true",
                             help="Show what would be removed without making any changes")
    p_uninstall.add_argument("--browser", action="store_true",
                             help="Remove only what install --browser added. Chromium stays unless --chromium")
    p_uninstall.add_argument("--chromium", action="store_true",
                             help="With --browser, also remove the shared Chromium cache")
    p_uninstall.add_argument("--keep-config", action="store_true",
                             help="Remove skill files only, keep ~/.searchts/ config and tokens")

    # ── mcp ──
    p_mcp = sub.add_parser("mcp", parents=[_verbose], help="Run or wire up the searchts MCP server")
    mcp_sub = p_mcp.add_subparsers(dest="mcp_command", help="MCP subcommands")
    p_serve = mcp_sub.add_parser(
        "serve",
        parents=[_verbose],
        help="Run the MCP server (stdio default; --http / --sse = loopback only)",
    )
    p_serve.add_argument(
        "--http",
        action="store_true",
        help="Streamable HTTP on loopback (http://127.0.0.1:PORT/mcp). Not a public URL.",
    )
    p_serve.add_argument(
        "--sse",
        action="store_true",
        help="Legacy SSE on loopback (http://127.0.0.1:PORT/sse). Prefer --http.",
    )
    p_serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address for --http/--sse (loopback only; default 127.0.0.1)",
    )
    p_serve.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port for --http/--sse (default 8765)",
    )
    p_mcp_install = mcp_sub.add_parser(
        "install", parents=[_verbose],
        help="Wire the MCP server into agent configs already on this machine")
    p_mcp_install.add_argument(
        "--client",
        choices=[
            "claude", "cursor", "json", "desktop", "codex", "vscode",
            "copilot", "windsurf", "devin", "gemini", "opencode",
        ],
        default=None,
        help="Write one client (default: every client already on this machine). "
             "json only prints the mcpServers snippet",
    )

    # ── skill ──
    p_skill = sub.add_parser("skill", parents=[_verbose], help="Manage agent skill registration")
    # Legacy flags (kept for backward compatibility): `searchts skill --install`.
    p_skill.add_argument("--install", dest="legacy_install", action="store_true",
                         help="Install the SKILL.md bundle to agent skill directories")
    p_skill.add_argument("--uninstall", dest="legacy_uninstall", action="store_true",
                         help="Remove the SKILL.md bundle from agent skill directories")
    skill_sub = p_skill.add_subparsers(dest="skill_command", help="Skill subcommands")
    p_skill_install = skill_sub.add_parser(
        "install", parents=[_verbose],
        help="Write the slash command and the shared SKILL.md bundle")
    p_skill_install.add_argument("--dir", dest="dir", default=None,
                                 help="Target commands directory (default: ~/.claude/commands)")

    # ── login ──
    p_login = sub.add_parser(
        "login",
        parents=[_verbose],
        help="Manage which site logins searchts keeps, and which it copied this session",
    )
    login_sub = p_login.add_subparsers(dest="login_command")

    login_sub.add_parser(
        "list", parents=[_verbose],
        help="Show kept sites, this session's copies, and any scratch left over",
    )

    p_login_keep = login_sub.add_parser(
        "keep", parents=[_verbose],
        help="Keep one site's login in the searchts store",
    )
    p_login_keep.add_argument("url", help="The site whose login to keep")
    p_login_keep.add_argument(
        "--cookies-from-browser", default="", metavar="BROWSER",
        help="Copy from this Firefox-family browser, then keep the site (opt-in)",
    )

    p_login_kill = login_sub.add_parser(
        "kill", parents=[_verbose],
        help="Delete searchts's copy of one site's login",
    )
    p_login_kill.add_argument("url", help="The site to forget")
    p_login_kill.add_argument(
        "--also-browser", action="store_true",
        help="Also delete that site's cookies in your own Firefox/Chrome. "
             "Off by default: those are yours, and searchts does not delete a "
             "login you did not ask it to.",
    )

    p_login_signin = login_sub.add_parser(
        "signin", parents=[_verbose],
        help="Sign in once for a site in a browser searchts opens",
    )
    p_login_signin.add_argument("url", help="The site to sign in to")
    p_login_signin.add_argument(
        "--browser", default="chrome",
        help="Which browser searchts opens (default: chrome)",
    )
    p_login_signin.add_argument(
        "--yes", action="store_true",
        help="Keep the login after signing in. Without this, signing in only "
             "serves this one read and nothing is kept.",
    )

    login_sub.add_parser(
        "purge-scratch", parents=[_verbose],
        help="Delete every scratch copy. This runs on its own at the end of a "
             "read anyway; this is for cleaning up after a killed process",
    )

    # ── check-update ──
    # ── transcribe ──
    p_tr = sub.add_parser("transcribe", parents=[_verbose],
                          help="Read the audio when a player page has no captions, or transcribe a local file (subtitles first, then Whisper)")
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
    p_tr.add_argument(
        "--cookies-from-browser",
        default=None,
        metavar="BROWSER",
        help="Opt-in: pass this browser's cookies to yt-dlp (chrome, firefox, edge, …). "
             "Transcribe only. Never used by searchts read.",
    )

    # ── get / grab (files a read named) ──
    p_get = sub.add_parser("get", parents=[_verbose],
                           help="Download a single asset (image/PDF/font/file) through the unlocker")
    p_get.add_argument("url", help="The asset URL to download")
    p_get.add_argument("-o", "--output", default=None,
                       help="Output file or directory (default: filename from the URL, in the cwd)")

    p_grab = sub.add_parser("grab", parents=[_verbose],
                            help="Save the files a read named (images, fonts, and the rest of the page's assets)")
    p_grab.add_argument("url", help="The page URL to grab")
    p_grab.add_argument("--out", default=None,
                        help="Output directory (default: ./searchts-grab-<host>)")
    p_grab.add_argument("--kinds", default="images,icons,css,fonts,svg,inline_svg",
                        help="Comma list of asset kinds to download "
                             "(images,icons,css,fonts,svg,inline_svg,scripts)")
    p_grab.add_argument("--scripts", action="store_true", help="Also download <script src> files")
    p_grab.add_argument("--read", action="store_true", help="Also save the page text as page.md")
    p_grab.add_argument("--max", dest="max_assets", type=int, default=120,
                        help="Maximum assets to download (default 120)")
    from searchts import assets as _grab_assets
    p_grab.add_argument(
        "--tokens", dest="max_tokens", type=int, default=_grab_assets._TOKEN_CAP,
        help="Radius, shadow, and spacing values to keep "
             f"(default {_grab_assets._TOKEN_CAP}, "
             f"ceiling {_grab_assets._TOKEN_CAP_MAX}). "
             "The note names how many more a higher number returns.",
    )
    p_grab.add_argument("--json", action="store_true", help="Print the manifest JSON to stdout")

    sub.add_parser("check-update", parents=[_verbose],
                   help="Check for new versions and changes")

    p_update = sub.add_parser(
        "update",
        aliases=["upgrade"],
        parents=[_verbose],
        help="Update this install to the latest release (upgrade is the same command)",
    )
    p_update.add_argument(
        "--force",
        action="store_true",
        help="Reinstall even when this copy is already the latest release",
    )
    p_update.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the upgrade command and do not run it",
    )

    # ── watch ──
    sub.add_parser("watch", parents=[_verbose],
                   help="Quick health check + update check (for scheduled tasks)")

    # ── version ──
    sub.add_parser("version", parents=[_verbose], help="Show version")

    _maybe_print_command_suggestion(sys.argv[1:], sub.choices)

    # Help is a document, not a syntax dump. Rendering it ourselves keeps the
    # flag list generated from the live parsers (so it cannot drift) while the
    # prose, the grouping and the width stay ours.
    from searchts import helptext

    if helptext.wants_help(sys.argv[1:]) or len(sys.argv) == 1:
        helptext.render(parser, sys.argv[1:], __version__)
        sys.exit(0)

    args = parser.parse_args()

    # Suppress loguru noise unless --verbose
    _configure_logging(getattr(args, "verbose", False))

    if not args.command:
        helptext.render_root(__version__)
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
    elif args.command in ("update", "upgrade"):
        from searchts.self_update import cmd_update

        sys.exit(cmd_update(
            force=bool(getattr(args, "force", False)),
            dry_run=bool(getattr(args, "dry_run", False)),
            command=args.command,
        ))
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
    elif args.command == "login":
        _cmd_login(args)
    elif args.command == "skill":
        _cmd_skill(args)
    elif args.command == "transcribe":
        _cmd_transcribe(args)
    elif args.command == "get":
        _cmd_get(args)
    elif args.command == "grab":
        _cmd_grab(args)

    from searchts.update_nudge import maybe_nudge

    maybe_nudge(
        command=args.command,
        mcp_subcommand=getattr(args, "mcp_command", None),
    )


def main():
    """Console entry point.

    `read`, `search`, `transcribe` and `grab` are long-running and stream
    content to stdout, so the two things users actually do to them are Ctrl+C
    and piping into `head`/`less`. Left unhandled, both surface as a raw
    traceback: KeyboardInterrupt, or an "Exception ignored ... BrokenPipeError"
    emitted during interpreter shutdown.
    """
    try:
        _run()
    except KeyboardInterrupt:
        print("! Interrupted", file=sys.stderr)
        # 128 + SIGINT, the shell convention for "cancelled by the user".
        sys.exit(130)
    except BrokenPipeError:
        # A downstream reader (head, less) closed the pipe. Python flushes
        # stdout at shutdown, which would raise a second BrokenPipeError that
        # no handler can catch, so point the fd at devnull first.
        # See https://docs.python.org/3/library/signal.html#note-on-sigpipe
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except (OSError, ValueError):
            # Captured or already-closed stdout (pytest, embedded use).
            pass
        sys.exit(141)  # 128 + SIGPIPE


# ── Command handlers ────────────────────────────────


def _cmd_install(args):
    """One-shot deterministic installer."""
    import os

    # F22: focused keep-path for stealth. Do not invent a second install verb.
    if getattr(args, "browser", False):
        from searchts.browser_install import install_browser

        code = install_browser(dry_run=bool(getattr(args, "dry_run", False)))
        raise SystemExit(code)

    from searchts.config import Config
    from searchts.doctor import check_all, format_report

    dry_run = args.dry_run
    # Non-invasive by default: the keyless core (read/search/transcribe) needs no
    # system mutation. Only --system-deps/--apply opts in to apt/npm/NodeSource/
    # yt-dlp-config changes. --safe is now a no-op kept for backward compatibility.
    apply_system = args.system_deps
    safe_mode = not apply_system

    from searchts import progress, receipts

    config = Config()
    style, unicode_ok = receipts.for_stream(sys.stdout)

    def row(item, label_w=9):
        print("\n".join(receipts.row_lines(
            style, item, unicode_ok=unicode_ok, label_w=label_w,
        )))

    # The old banner and its ==== rule are gone. The header says which command
    # is running; the mode is the first row, not a second title.
    print(receipts.header(
        style,
        "install",
        subject=f"v{__version__}",
        status=progress.ROW_SKIP,
        unicode_ok=unicode_ok,
    ))

    # Ensure tools directory exists (for upstream tool repos)
    tools_dir = os.path.expanduser("~/.searchts/tools")
    os.makedirs(tools_dir, exist_ok=True)

    if dry_run:
        mode = "dry run, no changes"
    elif apply_system:
        mode = "system-deps mode, optional system packages"
    else:
        mode = "non-invasive, no system changes"
    row(receipts.Row(progress.ROW_SKIP, "mode", mode), label_w=6)
    print()
    if apply_system:
        print("SYSTEM-DEPS MODE — will install optional system packages (gh, Node.js, npm globals)")
        print()
    elif not dry_run:
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

    row(receipts.Row(
        progress.ROW_SKIP,
        "env",
        "server/VPS (auto-detected)" if env == "server" else "local computer (auto-detected)",
    ), label_w=6)

    # Apply explicit flags
    if args.proxy:
        if dry_run:
            row(receipts.Row(progress.ROW_SKIP, "proxy", "would save the network proxy"), label_w=6)
        else:
            config.set("proxy", args.proxy)
            row(receipts.Row(progress.ROW_OK, "proxy", "saved (used for a restricted network)"), label_w=6)

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
        row(receipts.Row(
            progress.ROW_SKIP,
            "mcporter",
            "would install mcporter and configure Exa search",
        ))
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
            row(receipts.Row(
                progress.ROW_SKIP,
                "opencli",
                "needs a desktop + Chrome; skipped in a server environment",
            ))
        for ch_name in sorted(requested_channels):
            installer = CHANNEL_INSTALLERS.get(ch_name)
            if installer:
                installer()

    if requested_channels and dry_run:
        print()
        row(receipts.Row(
            progress.ROW_SKIP,
            "channels",
            "would install " + ", ".join(sorted(requested_channels)),
        ))
    elif requested_channels and safe_mode:
        print()
        row(receipts.Row(
            progress.ROW_WARN,
            "channels",
            f"requested {', '.join(sorted(requested_channels))} but not installed: "
            "installing them mutates the system (pipx/npm). Re-run with "
            f"--system-deps --channels={','.join(sorted(requested_channels))}",
        ))

    # ── Auto-import cookies (only if cookie-needing channels are requested) ──
    needs_cookies = bool(requested_channels & COOKIE_CHANNELS)
    if env == "local" and needs_cookies and not safe_mode and not dry_run:
        print()
        print("Importing cookies from browser...")
        print("  (macOS may ask for your login password to access the Keychain — this is normal,")
        print("   it only happens once during install. Enter your password or click 'Allow'.)")
        try:
            from searchts.cookie_extract import configure_from_browser
            cookie_results = configure_from_browser("chrome", config)
            found = False
            for platform, success, message in cookie_results:
                if success:
                    row(receipts.Row(progress.ROW_OK, platform, message))
                    found = True
            if not found:
                cookie_results = configure_from_browser("firefox", config)
                for platform, success, message in cookie_results:
                    if success:
                        row(receipts.Row(progress.ROW_OK, platform, message))
                        found = True
            if not found:
                row(receipts.Row(
                    progress.ROW_SKIP,
                    "cookies",
                    "none found (normal if you have not logged into these sites)",
                ))
        except Exception:
            row(receipts.Row(
                progress.ROW_WARN,
                "cookies",
                "could not read browser cookies (browser open or password denied)",
            ))
    elif env == "local" and needs_cookies and dry_run:
        print()
        row(receipts.Row(
            progress.ROW_SKIP,
            "cookies",
            "would try Chrome and Firefox",
        ))

    # Environment-specific advice
    if env == "server":
        print()
        print("Tip: some platforms apply risk controls to server IPs.")
        print("   Reddit requires a logged-in session (rdt-cli + cookie, see the doctor hints), and mainland China networks also need a proxy.")
        print("   Save a proxy for the agent to use: searchts configure proxy http://user:pass@ip:port")
        print("   Cheap option: https://www.webshare.io ($1/month)")

    # Test channels. install does not open a tracker of its own: check_all's
    # rows are the only live region, and its report is the ending.
    if not dry_run:
        print()
        results = check_all(config, progress=True, command="install")

        # Agent skill + reach rule first, so the doctor report stays last.
        _install_skill()
        from searchts.integrations.memory_rule import install_memory_rules
        print()
        print("Agent reach rule (user-scope)...")
        install_memory_rules()

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

        print()
        print(format_report(results))
    else:
        print()
        print(receipts.block(
            style,
            "install",
            [receipts.Row(progress.ROW_SKIP, "dry run", "no changes were made")],
            subject=f"v{__version__}",
            status=progress.ROW_SKIP,
            unicode_ok=unicode_ok,
        ))


def _install_skill():
    """Install searchts as an agent skill (OpenClaw / Claude Code / .agents)."""
    import importlib.resources
    import os
    import shutil

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
            print("  · Could not install agent skill (optional)")
            print("  · Tip: install OpenClaw, Claude Code, or create ~/.agents/skills/ manually")


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
    from searchts import progress, receipts

    target_dir = _slash_command_target_dir(getattr(args, "dir", None))
    tracker = progress.live("skill install", summary_stream=sys.stderr)
    with tracker:
        if tracker.is_live:
            tracker.stage("writing the slash command")
        path = write_slash_command(target_dir)
        from pathlib import Path as _Path

        from searchts.integrations.skill_bundle import install_shared_skills

        home = _Path.home()
        bundles = install_shared_skills(home)
        if tracker.is_live:
            tracker.settle(progress.ROW_OK, path)
        bundle_rows = [
            receipts.Row(
                progress.ROW_OK if item["ok"] else progress.ROW_WARN,
                "skill",
                _short_path(str(item["path"]))
                if item["ok"]
                else "could not write " + _short_path(str(item["path"])),
            )
            for item in bundles
        ]
        receipts.emit(
            tracker,
            receipts.block(
                tracker.color,
                "skill install",
                [receipts.Row(progress.ROW_OK, "command", _short_path(path)), *bundle_rows],
                unicode_ok=tracker.unicode_ok,
            ),
            stream=sys.stderr,
        )
    # The slash-command path is the deliverable, alone on stdout.
    print(_stdout_path(path))
    from searchts.integrations.memory_rule import install_memory_rules

    # The path above is the whole stdout payload. Reach-rule notes stay on stderr.
    install_memory_rules(home, log=lambda message: print(message, file=sys.stderr))


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
        "Note: `searchts` must be on your PATH (pipx install \"searchts[mcp]\"). "
        "If the host cannot see the pipx bin, use "
        "`uvx --from \"searchts[mcp]\" searchts mcp serve` "
        "or replace `searchts` with the path from `pipx which searchts`."
    )
    http_note = (
        "Loopback HTTP (phone / custom connector that cannot use stdio):\n"
        "  searchts mcp serve --http\n"
        "  URL: http://127.0.0.1:8765/mcp\n"
        "Binds 127.0.0.1 only. No public/hosted MCP URL."
    )

    claude_block = "\n".join([
        "Claude Code - run this one-liner:",
        f"  {claude_cmd}",
    ])
    cursor_block = "\n".join([
        "Cursor / Claude Desktop / Copilot / Gemini / Windsurf / Devin - mcpServers:",
        json_snippet,
    ])
    vscode_snippet = json.dumps(
        {"servers": {"searchts": {"type": "stdio", "command": "searchts", "args": ["mcp", "serve"]}}},
        indent=2,
    )
    vscode_block = "\n".join([
        "VS Code user mcp.json - top-level servers, type stdio:",
        vscode_snippet,
    ])
    codex_block = "\n".join([
        "Codex ~/.codex/config.toml:",
        '[mcp_servers.searchts]',
        'command = "searchts"',
        'args = ["mcp", "serve"]',
    ])
    opencode_snippet = json.dumps(
        {"mcp": {"servers": {"searchts": {"type": "local", "command": ["searchts", "mcp", "serve"]}}}},
        indent=2,
    )
    opencode_block = "\n".join([
        "OpenCode ~/.config/opencode/opencode.json - servers map, command is one array:",
        opencode_snippet,
    ])
    write_note = (
        "With no --client, this command writes the stdio server into each of "
        "these that is already installed. --client NAME writes that one even "
        "when it was not detected. --client json only prints the snippet."
    )

    if client == "claude":
        return f"{claude_block}\n\n{path_note}\n\n{http_note}"
    if client in ("cursor", "json", "desktop", "copilot", "gemini", "windsurf", "devin"):
        return f"{cursor_block}\n\n{path_note}\n\n{http_note}"
    if client == "vscode":
        return f"{vscode_block}\n\n{path_note}\n\n{http_note}"
    if client == "codex":
        return f"{codex_block}\n\n{path_note}\n\n{http_note}"
    if client == "opencode":
        return f"{opencode_block}\n\n{path_note}\n\n{http_note}"

    return "\n\n".join([
        claude_block,
        cursor_block,
        vscode_block,
        codex_block,
        opencode_block,
        path_note,
        http_note,
        write_note,
    ])


def _cmd_mcp(args):
    """Dispatch `searchts mcp serve|install`."""
    mcp_command = getattr(args, "mcp_command", None)
    if mcp_command == "serve":
        _cmd_mcp_serve(args)
    elif mcp_command == "install":
        from searchts import progress, receipts

        client = getattr(args, "client", None)
        tracker = progress.live("mcp install", summary_stream=sys.stderr)
        with tracker:
            if tracker.is_live:
                tracker.stage("writing agent config")
            from pathlib import Path as _Path

            from searchts.integrations.wire import apply_mcp

            written = apply_mcp(_Path.home(), client=client)
            text = mcp_install_text(client)
            from searchts.integrations.agent_wiring import check_agent_wiring

            checks = check_agent_wiring()
            if tracker.is_live:
                tracker.settle(
                    progress.ROW_OK,
                    f"{len(checks)} clients detected" if checks else "no clients detected",
                )
            wiring = (
                "claude mcp add searchts -- searchts mcp serve"
                if client == "claude"
                else "searchts mcp serve"
            )
            write_rows = []
            for item in written:
                path = _short_path(str(item["path"]))
                if item["status"] == "wrote":
                    write_rows.append(receipts.Row(progress.ROW_OK, item["client"], f"wrote {path}"))
                elif item["status"] == "already":
                    write_rows.append(receipts.Row(progress.ROW_OK, item["client"], "already registered"))
                elif item["status"] == "kept":
                    write_rows.append(
                        receipts.Row(progress.ROW_WARN, item["client"], "left the existing entry")
                    )
                else:
                    write_rows.append(
                        receipts.Row(progress.ROW_WARN, item["client"], "could not parse the config; left it")
                    )
            receipts.emit(
                tracker,
                receipts.block(
                    tracker.color,
                    "mcp install",
                    [*write_rows, receipts.Row(progress.ROW_OK, "wiring", wiring)],
                    unicode_ok=tracker.unicode_ok,
                ),
                stream=sys.stderr,
            )

        print(text)
        if checks:
            style, unicode_ok = receipts.for_stream(sys.stdout)
            rows = [
                receipts.Row(
                    progress.ROW_OK if c["wired"] else progress.ROW_WARN,
                    c["client"],
                    "registered" if c["wired"] else f"not registered; run: {c['hint']}",
                )
                for c in checks
            ]
            label_w = min(18, max(len(row.label) for row in rows))
            print()
            print("  " + style.dim("AGENT WIRING"))
            for row in rows:
                print("\n".join(receipts.row_lines(
                    style, row, unicode_ok=unicode_ok, label_w=label_w,
                )))
    else:
        print("Usage: searchts mcp serve [--http|--sse] [--host 127.0.0.1] [--port 8765]")
        print("   or: searchts mcp install [--client claude|cursor|codex|vscode|gemini|opencode|json]")
        sys.exit(2)


def _cmd_mcp_serve(args=None):
    """Run the MCP server (stdio default). HTTP/SSE bind loopback only (F9 / N2)."""
    from searchts.integrations import mcp_server

    # Fail before the "waiting" banner if the optional mcp package is missing.
    if not mcp_server.HAS_MCP:
        print(mcp_server.MCP_MISSING_MESSAGE, file=sys.stderr)
        sys.exit(1)

    want_http = bool(getattr(args, "http", False)) if args is not None else False
    want_sse = bool(getattr(args, "sse", False)) if args is not None else False
    if want_http and want_sse:
        print("Usage: searchts mcp serve --http  OR  --sse  (not both)", file=sys.stderr)
        sys.exit(2)
    transport = "stdio"
    if want_http:
        transport = "http"
    elif want_sse:
        transport = "sse"
    host = getattr(args, "host", "127.0.0.1") if args is not None else "127.0.0.1"
    port = int(getattr(args, "port", 8765) if args is not None else 8765)

    if transport == "stdio":
        # Stdio MCP has no banner on stdout (that would break the protocol).
        print(
            "searchts MCP server on stdio — waiting for host (Ctrl+C to stop)",
            file=sys.stderr,
            flush=True,
        )
    else:
        try:
            host = mcp_server.assert_loopback_bind(host)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            sys.exit(2)
        path = "/mcp" if transport == "http" else "/sse"
        print(
            f"searchts MCP server on http://{host}:{port}{path} — loopback only "
            "(Ctrl+C to stop). Not a public URL.",
            file=sys.stderr,
            flush=True,
        )
    try:
        mcp_server.serve(transport=transport, host=host, port=port)
    except mcp_server.MCPNotInstalledError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)


def _install_system_deps():
    """Install system-level dependencies: gh CLI, Node.js (for mcporter)."""
    import platform
    import shutil
    import subprocess
    import tempfile

    from searchts.utils.paths import get_ytdlp_config_dir, get_ytdlp_config_path

    print("Checking system dependencies...")

    # ── gh CLI ──
    if shutil.which("gh"):
        print("  ✓ gh CLI already installed")
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
                    print("  ✓ gh CLI installed")
                else:
                    print("  !  gh CLI install failed. You can try: snap install gh, or download from https://github.com/cli/cli/releases")
            except Exception:
                print("  !  gh CLI install failed. You can try: snap install gh, or download from https://github.com/cli/cli/releases")
        elif os_type == "darwin":
            if shutil.which("brew"):
                try:
                    subprocess.run(["brew", "install", "gh"], capture_output=True, timeout=120)
                    if shutil.which("gh"):
                        print("  ✓ gh CLI installed")
                    else:
                        print("  !  gh CLI install failed. Try: brew install gh")
                except Exception:
                    print("  !  gh CLI install failed. Try: brew install gh")
            else:
                print("  !  gh CLI not found. Install: https://cli.github.com")
        else:
            print("  !  gh CLI not found. Install: https://cli.github.com")

    # ── Node.js (needed for mcporter) ──
    if shutil.which("node") and shutil.which("npm"):
        print("  ✓ Node.js already installed")
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
                print("  ✓ Node.js installed")
            else:
                print("  !  Node.js install failed. Try: apt install nodejs npm, or nvm install 22, or download from https://nodejs.org")
        except Exception:
            print("  !  Node.js install failed. Try: apt install nodejs npm, or nvm install 22, or download from https://nodejs.org")

    # ── undici (proxy support for Node.js fetch) ──
    npm_cmd = shutil.which("npm")
    if npm_cmd:
        npm_root = subprocess.run([npm_cmd, "root", "-g"], capture_output=True, encoding="utf-8", errors="replace", timeout=5).stdout.strip()
        undici_path = os.path.join(npm_root, "undici", "index.js") if npm_root else ""
        if os.path.exists(undici_path):
            print("  ✓ undici already installed (Node.js proxy support)")
        else:
            try:
                subprocess.run([npm_cmd, "install", "-g", "undici"], capture_output=True, encoding="utf-8", errors="replace", timeout=60)
                print("  ✓ undici installed (Node.js proxy support)")
            except Exception:
                print("  · undici install failed (optional — may not work behind proxies)")

    # ── yt-dlp JS runtime config (YouTube requires external JS runtime) ──
    if shutil.which("node"):
        ytdlp_config_dir = get_ytdlp_config_dir()
        ytdlp_config = get_ytdlp_config_path()
        needs_config = True
        if os.path.exists(ytdlp_config):
            with open(ytdlp_config, "r", encoding="utf-8") as f:
                if "--js-runtimes" in f.read():
                    needs_config = False
                    print("  ✓ yt-dlp JS runtime already configured")
        if needs_config:
            try:
                os.makedirs(ytdlp_config_dir, exist_ok=True)
                with open(ytdlp_config, "a", encoding="utf-8") as f:
                    f.write("--js-runtimes node\n")
                print("  ✓ yt-dlp configured to use Node.js as JS runtime (YouTube)")
            except Exception:
                print("  · Could not configure yt-dlp JS runtime (YouTube may not work)")

    # NOTE: twitter-cli etc. are optional.
    # They are installed via --channels flag, not here.
    # See CHANNEL_INSTALLERS in _cmd_install().


def _install_twitter_deps():
    """Install twitter-cli for Twitter search + timeline."""
    import shutil
    import subprocess

    print("Setting up Twitter (twitter-cli)...")
    if shutil.which("twitter"):
        print("  ✓ twitter-cli already installed")
        return
    for tool, cmd in [("pipx", ["pipx", "install", "twitter-cli"]),
                      ("uv", ["uv", "tool", "install", "twitter-cli"])]:
        if shutil.which(tool):
            try:
                subprocess.run(cmd, capture_output=True, encoding="utf-8",
                               errors="replace", timeout=120)
                if shutil.which("twitter"):
                    print("  ✓ twitter-cli installed")
                    return
            except Exception:
                pass
    print("  !  twitter-cli install failed. Run: pipx install twitter-cli")


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
        print(f"  ✓ {opencli_summary(st)}")
        if not st.ready:
            print(f"  {st.hint}")
        return

    if not shutil.which("npm"):
        print("  !  OpenCLI requires Node.js ≥ 20. Install Node first:")
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
        print("  ✓ OpenCLI installed")
        print("  Final step (must be done manually, due to Chrome security restrictions): install the browser extension")
        print(f"    1. Open {OPENCLI_EXTENSION_URL}")
        print("    2. Click \"Add to Chrome\"")
        print("    3. Run `opencli doctor` to verify the connection")
    else:
        print(f"  !  OpenCLI install failed. Run: npm install -g {OPENCLI_PACKAGE}")


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
            print("  ✓ Detected an existing rdt-cli; it will remain available as a fallback backend")
        return

    _install_rdt_cli()


def _install_rdt_cli():
    """Install rdt-cli (pinned git source — PyPI lags upstream)."""
    import shutil
    import subprocess

    print("Setting up Reddit (rdt-cli)...")
    if shutil.which("rdt"):
        print("  ✓ rdt-cli already installed")
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
                    print("  ✓ rdt-cli installed")
                    return
            except Exception:
                pass
    print(f"  !  rdt-cli install failed. Run: pipx install '{_RDT_GIT_SOURCE}'")


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
            print(f"  ✓ {label} already installed")
        else:
            print(f"  \u00b7 {label} not found")
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

    print("· System dependency check:")

    checks = [
        ("gh CLI", ["gh"], "apt install gh / brew install gh"),
        ("Node.js", ["node"], "curl NodeSource setup | bash + apt install nodejs"),
    ]

    for label, binaries, method in checks:
        found = any(shutil.which(b) for b in binaries)
        if found:
            print(f"  ✓ {label}: already installed, skip")
        else:
            print(f"  {label}: would install via: {method}")



def _install_mcporter():
    """Install mcporter and configure Exa search."""
    import shutil
    import subprocess

    print("Setting up mcporter (optional extra search provider; the recommended "
          "search is the keyless built-in 'searchts search')...")

    if shutil.which("mcporter"):
        print("  ✓ mcporter already installed")
    else:
        # Check for npm/npx
        if not shutil.which("npm") and not shutil.which("npx"):
            print("  !  mcporter requires Node.js. Install Node.js first:")
            print("     https://nodejs.org/ or: curl -fsSL https://fnm.vercel.app/install | bash")
            return
        try:
            subprocess.run(
                ["npm", "install", "-g", "mcporter"],
                capture_output=True, encoding="utf-8", errors="replace", timeout=120,
            )
            if shutil.which("mcporter"):
                print("  ✓ mcporter installed")
            else:
                print("  ✗ mcporter install failed. Retry: npm install -g mcporter (check network/timeout), or try: npx mcporter@latest list")
                return
        except Exception as e:
            print(f"  ✗ mcporter install failed: {e}")
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
            print("  ✓ Exa search configured (free, no API key needed)")
        else:
            print("  ✓ Exa search already configured")
    except Exception:
        print("  !  Could not configure Exa. Run manually: mcporter config add exa https://mcp.exa.ai/mcp")


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
        print("  ✓ mcporter already installed")
        print("  Optional — to add Exa as an extra provider: mcporter config add exa https://mcp.exa.ai/mcp")
    else:
        print("  · mcporter not installed (optional; not required for search)")
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


def _value_set(value) -> bool:
    return value is not None and str(value).strip() != ""


def _field_winner(config, field):
    """Return ``(source, value, file_has_value)``.

    A present environment variable wins over the YAML key, the same rule as
    ``Config.get``. ``file_has_value`` is true when the file also holds a
    non-empty value, so the row can name the winner.
    """
    env_name = field.upper()
    file_value = config.data.get(field)
    file_has_value = _value_set(file_value)
    if env_name in os.environ:
        return env_name, os.environ.get(env_name, ""), file_has_value
    if file_has_value:
        return "config.yaml", file_value, False
    return None, None, False


def _proxy_public(url: str) -> str:
    """A proxy URL with the password replaced. The host stays visible."""
    import re

    text = str(url).strip()
    text = re.sub(r"(//[^/@:\s]+):[^@/\s]+@", r"\1:***@", text)
    return re.sub(r"^([^/@:\s]+):[^@/\s]+@", r"\1:***@", text)


def _secret_now(config, fields) -> str:
    """``set`` or ``unset`` for YAML fields. The value itself is never included."""
    bits = []
    saw_value = False
    for field in fields:
        source, value, file_too = _field_winner(config, field)
        if source is None:
            continue
        if _value_set(value):
            saw_value = True
            if file_too and source != "config.yaml":
                bits.append(f"{source} over the file")
            else:
                bits.append(source)
        elif file_too:
            bits.append(f"unset in {source} over the file")
    if not bits:
        return "unset"
    ordered = list(dict.fromkeys(bits))
    if not saw_value:
        return "; ".join(ordered)
    return "set in " + " and ".join(ordered)


def _proxy_now(config) -> str:
    source, value, file_too = _field_winner(config, "proxy")
    if source is None or not _value_set(value):
        if source and file_too:
            return f"unset in {source} over the file"
        return "unset"
    shown = _proxy_public(value)
    if file_too and source != "config.yaml":
        return f"{shown} in {source} over the file"
    if source != "config.yaml":
        return f"{shown} in {source}"
    return shown


def _github_now() -> str:
    """GITHUB_TOKEN is the name on the row. GH_TOKEN counts when it is the one set."""
    if _value_set(os.environ.get("GITHUB_TOKEN")):
        return "set in GITHUB_TOKEN"
    if _value_set(os.environ.get("GH_TOKEN")):
        return "set in GH_TOKEN"
    return "unset"


def _configure_list_rows(config):
    """One receipt row per key ``configure`` accepts. No saved-state row for the browser copy."""
    from searchts import progress, receipts

    def row(name, now, extra=""):
        detail = f"default unset, now {now}"
        if extra:
            detail = f"{detail}. {extra}"
        unset = now == "unset" or now.startswith("unset ")
        status = progress.ROW_SKIP if unset else progress.ROW_OK
        return receipts.Row(status, name, detail)

    built = {
        "proxy": row(
            "proxy",
            _proxy_now(config),
            "in the file; searchts does not apply it",
        ),
        "github-token": row(
            "github-token",
            _github_now(),
            "lives in GITHUB_TOKEN, not in the file",
        ),
        "groq-key": row("groq-key", _secret_now(config, ("groq_api_key",))),
        "openai-key": row("openai-key", _secret_now(config, ("openai_api_key",))),
        "twitter-cookies": row(
            "twitter-cookies",
            _secret_now(config, ("twitter_auth_token", "twitter_ct0")),
        ),
        "youtube-cookies": row("youtube-cookies", "unset", "not stored"),
    }
    return [built[name] for name in _CONFIGURE_KEYS]


def _cmd_configure(args):
    """List the keys, set a config value, or copy cookies from a browser."""
    import shutil

    from searchts import progress, receipts
    from searchts.config import Config

    config = Config()
    style, unicode_ok = receipts.for_stream(sys.stdout)

    def receipt(rows, *, status=progress.ROW_OK, subject=""):
        print(receipts.block(
            style,
            "configure",
            rows,
            subject=subject,
            status=status,
            unicode_ok=unicode_ok,
        ))

    # ── Auto-extract from browser ──
    if args.from_browser:
        from searchts.cookie_extract import configure_from_browser

        browser = args.from_browser
        results = configure_from_browser(browser, config)

        found_any = False
        rows = []
        for platform, success, message in results:
            rows.append(receipts.Row(
                progress.ROW_OK if success else progress.ROW_SKIP,
                platform,
                message,
            ))
            found_any = found_any or success
        rows.append(receipts.Row(
            progress.ROW_OK if found_any else progress.ROW_WARN,
            "done",
            "cookies configured; run `searchts doctor` to see updated status"
            if found_any
            else f"no cookies found; make sure you are logged into the platforms in {browser}",
        ))
        receipt(rows, status=progress.ROW_OK if found_any else progress.ROW_FAIL, subject=browser)
        return

    # ── Bare configure lists the keys. Writes stay above and below. ──
    if not args.key:
        err_style, err_unicode = receipts.for_stream(sys.stderr)
        print(
            receipts.block(
                err_style,
                "configure",
                _configure_list_rows(config),
                status=progress.ROW_OK,
                unicode_ok=err_unicode,
            ),
            file=sys.stderr,
        )
        return

    if args.key == "youtube-cookies":
        receipt(
            [receipts.Row(
                progress.ROW_WARN,
                "youtube-cookies",
                "not wired and not stored in YAML. yt-dlp does not read a searchts key. "
                "Opt in at transcribe time: searchts transcribe <url> "
                "--cookies-from-browser chrome. Never used by `searchts read`.",
            )],
            status=progress.ROW_WARN,
            subject="not stored",
        )
        return

    if args.key == "github-token":
        receipt(
            [receipts.Row(
                progress.ROW_WARN,
                "github-token",
                "not stored. Export GITHUB_TOKEN or GH_TOKEN in the environment, or put it "
                "in .env (see .env.example). Nothing in searchts reads a YAML token.",
            )],
            status=progress.ROW_WARN,
            subject="not stored",
        )
        return

    value = " ".join(args.value) if args.value else ""
    if not value:
        receipt(
            [receipts.Row(progress.ROW_FAIL, "reason", f"missing value for {args.key}")],
            status=progress.ROW_FAIL,
        )
        return

    if args.key == "proxy":
        # Generic network proxy for restricted environments. Nothing reads
        # this key at runtime — agents read it back and export HTTP(S)_PROXY
        # before invoking upstream tools (see docs/install.md).
        config.set("proxy", value)
        receipt([receipts.Row(
            progress.ROW_OK,
            "proxy",
            "saved for the agent to set HTTP_PROXY/HTTPS_PROXY on a restricted network "
            "(Reddit, Twitter)",
        )], subject="saved")

    elif args.key == "twitter-cookies":
        # Accept two formats:
        # 1. auth_token ct0 (two separate values)
        # 2. Full cookie header string: "auth_token=xxx; ct0=yyy; ..."
        auth_token, ct0 = _parse_twitter_cookie_input(value)

        if auth_token and ct0:
            config.set("twitter_auth_token", auth_token)
            config.set("twitter_ct0", ct0)

            rows = [receipts.Row(
                progress.ROW_OK,
                "cookies",
                "Twitter cookies configured",
            )]
            try:
                import subprocess
                twitter_bin = shutil.which("twitter")
                if not twitter_bin:
                    rows.append(receipts.Row(
                        progress.ROW_WARN,
                        "twitter-cli",
                        "not installed; run: pipx install twitter-cli",
                    ))
                else:
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
                        rows.append(receipts.Row(
                            progress.ROW_OK,
                            "access",
                            "Twitter access works",
                        ))
                    else:
                        rows.append(receipts.Row(
                            progress.ROW_WARN,
                            "access",
                            "auth check failed (cookies might be wrong)",
                        ))
            except Exception as e:
                rows.append(receipts.Row(
                    progress.ROW_WARN,
                    "access",
                    f"check failed: {e}",
                ))
            receipt(rows, subject="saved")
        else:
            receipt(
                [
                    receipts.Row(
                        progress.ROW_FAIL,
                        "reason",
                        "could not find auth_token and ct0 in your input",
                    ),
                    receipts.Row(
                        progress.ROW_SKIP,
                        "format",
                        "searchts configure twitter-cookies AUTH_TOKEN CT0",
                    ),
                    receipts.Row(
                        progress.ROW_SKIP,
                        "format",
                        'searchts configure twitter-cookies "auth_token=xxx; ct0=yyy; ..."',
                    ),
                ],
                status=progress.ROW_FAIL,
            )

    elif args.key == "groq-key":
        config.set("groq_api_key", value)
        receipt([receipts.Row(progress.ROW_OK, "groq", "key configured")], subject="saved")

    elif args.key == "openai-key":
        config.set("openai_api_key", value)
        receipt([receipts.Row(progress.ROW_OK, "openai", "key configured")], subject="saved")


def _cmd_transcribe(args):
    """Transcribe a URL or local audio file.

    Subtitles-first: a captioned URL is returned straight from its existing
    captions (no API key needed). Falls back to Whisper audio transcription
    (Groq -> OpenAI, or keyless local) only when there are no usable subtitles,
    or when --no-subtitles forces the audio path.
    """
    from pathlib import Path

    from searchts import progress
    from searchts.transcribe import TranscribeError, transcribe

    tracker = progress.live("transcribe", _short_subject(args.source))
    with tracker:
        try:
            text = transcribe(
                args.source,
                provider=args.provider,
                prefer_subtitles=args.prefer_subtitles,
                # Progress ticks make long ladder/audio runs visible; stderr only.
                progress=True,
                cookies_from_browser=getattr(args, "cookies_from_browser", None),
            )
        except TranscribeError as e:
            tracker.abort()
            # An error on stdout is invisible to every `2>` redirect and
            # makes a failed run look like a successful empty transcript.
            # The ending is the read ladder's shape: a red header and one
            # reason row, not a bracketed marker from an older theme.
            from searchts import receipts

            text = receipts.block(
                tracker.color,
                "transcribe",
                [receipts.Row(progress.ROW_FAIL, "reason", str(e))],
                subject=tracker.subject,
                elapsed=tracker.elapsed(),
                status=progress.ROW_FAIL,
                unicode_ok=tracker.unicode_ok,
            )
            print(text, file=sys.stderr)
            sys.exit(1)
        if tracker.wants():
            s = tracker.color
            mark = "✓" if tracker.unicode_ok else "+"
            tracker.summary(
                f"  {s.green(mark)} {s.cyan('transcribe')}  "
                f"{s.dim(_human_chars(len(text)))}  "
                f"{s.dim(progress.human_time(tracker.elapsed()))}")

    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        # The path is the deliverable, alone on stdout, exactly as `get` and
        # `grab` end: clickable on a terminal, copyable in a pipe.
        print(_stdout_path(args.output))
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

    from searchts import progress, receipts

    dry_run = args.dry_run
    if getattr(args, "chromium", False) and not getattr(args, "browser", False):
        print("--chromium only applies with --browser. It does not remove config.", file=sys.stderr)
        sys.exit(2)
    if getattr(args, "browser", False):
        from searchts.browser_install import uninstall_browser

        sys.exit(uninstall_browser(dry_run=dry_run, chromium=getattr(args, "chromium", False)))
    keep_config = args.keep_config

    style, unicode_ok = receipts.for_stream(sys.stdout)
    print(receipts.header(
        style,
        "uninstall",
        status=progress.ROW_SKIP,
        unicode_ok=unicode_ok,
    ))

    rows: list[receipts.Item] = []

    # ── 1. Config directory (~/.searchts/) ──
    config_dir = os.path.expanduser("~/.searchts")
    if not keep_config:
        if os.path.isdir(config_dir):
            if dry_run:
                rows.append(receipts.Row(
                    progress.ROW_SKIP,
                    "config",
                    f"would remove {_short_path(config_dir)} (tokens, cookies, API keys)",
                ))
            else:
                try:
                    shutil.rmtree(config_dir)
                    rows.append(receipts.Row(progress.ROW_OK, "config", f"removed {config_dir}"))
                except Exception as e:
                    rows.append(receipts.Row(
                        progress.ROW_FAIL, "config", f"could not remove {config_dir}: {e}",
                    ))
        else:
            rows.append(receipts.Row(
                progress.ROW_SKIP, "config", f"not found (already clean): {config_dir}",
            ))
    else:
        rows.append(receipts.Row(
            progress.ROW_SKIP, "config", f"kept (--keep-config): {config_dir}",
        ))

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
                rows.append(receipts.Row(
                    progress.ROW_SKIP, platform_name,
                    f"would remove {_short_path(str(skill_path))}",
                ))
            else:
                try:
                    if os.path.islink(skill_path):
                        os.unlink(skill_path)
                    else:
                        shutil.rmtree(skill_path)
                    rows.append(receipts.Row(
                        progress.ROW_OK, platform_name, f"removed {skill_path}",
                    ))
                except Exception as e:
                    rows.append(receipts.Row(
                        progress.ROW_FAIL, platform_name, f"could not remove {skill_path}: {e}",
                    ))

    # ── 3. mcporter MCP entries ──
    if shutil.which("mcporter"):
        for mcp_name in ("exa",):
            try:
                r = subprocess.run(
                    ["mcporter", "list"], capture_output=True, encoding="utf-8", errors="replace", timeout=10
                )
                if mcp_name in r.stdout:
                    if dry_run:
                        rows.append(receipts.Row(
                            progress.ROW_SKIP, "mcporter", f"would remove {mcp_name}",
                        ))
                    else:
                        subprocess.run(
                            ["mcporter", "config", "remove", mcp_name],
                            capture_output=True, encoding="utf-8", errors="replace", timeout=10,
                        )
                        rows.append(receipts.Row(
                            progress.ROW_OK, "mcporter", f"removed {mcp_name}",
                        ))
            except Exception:
                pass

    rows.append(receipts.Section("optional"))
    rows.append(receipts.Row(progress.ROW_SKIP, "package", "pip uninstall searchts"))
    rows.append(receipts.Row(
        progress.ROW_SKIP,
        "tools",
        "npm uninstall -g mcporter; pipx uninstall twitter-cli; npm uninstall -g undici",
    ))
    print()
    print(receipts.block(
        style,
        "uninstall",
        rows,
        status=progress.ROW_SKIP if dry_run else progress.ROW_OK,
        subject="dry run" if dry_run else "",
        unicode_ok=unicode_ok,
    ))
    if dry_run:
        print()
        print("No changes were made. Run without --dry-run to remove the above.")


def _short_subject(url: str) -> str:
    """`host/path?query` for a live-region header, short enough not to wrap."""
    from urllib.parse import urlsplit

    raw = url if "://" in url else "https://" + url
    try:
        parts = urlsplit(raw)
    except ValueError:
        return url
    text = (parts.netloc or parts.path).lower()
    path = (parts.path or "").rstrip("/")
    if path and path != "/":
        text += path
    if parts.query:
        text += "?" + parts.query
    if len(text) > 58:
        text = text[:55] + "…"
    return text


def _print_reason(prefix: str, why: str, width: int = 76) -> None:
    """Print one backend's reason, wrapped under itself.

    These reasons are forwarded from libraries and are often a full sentence
    with an install command inside it. Printed raw they run past 160 columns and
    the terminal folds them wherever it likes, which turns a tidy failure block
    into a paragraph.
    """
    chunks = textwrap.wrap(why, max(24, width - len(prefix))) or [""]
    print(prefix + chunks[0], file=sys.stderr)
    for chunk in chunks[1:]:
        print(" " * len(prefix) + chunk, file=sys.stderr)


def _human_chars(n: int) -> str:
    if n < 1024:
        return f"{n} chars"
    return f"{n / 1024:.1f} KB"


def _cmd_read(args):
    """Fetch a URL through the unlocker and print clean markdown.

    Content goes to stdout (so it is pipeable); any status/diagnostics go to
    stderr. On total failure, print the per-backend breakdown to stderr and
    exit nonzero.
    """
    from searchts import progress, unlocker, ux

    # A typo is the most common mistake and used to be the most expensive: a
    # bare word is a valid hostname, so `read not-a-url` walked the whole ladder
    # including a browser launch, 18.6s, to say "could not resolve host". Cost:
    # instant and specific, and nothing that used to work is rejected.
    problem = ux.check_url(args.url)
    if problem:
        print(f"searchts read: {problem}", file=sys.stderr)
        sys.exit(2)

    cookies = _read_command_cookies(args)
    proxy = _read_command_proxy(args)

    backends = [args.backend] if args.backend else None
    # Progress is narration ("trying curl_cffi..."), not diagnosis. On a
    # terminal the ladder draws live and the reasons are part of the picture; in
    # a pipe the same reasons are printed once, together, by the failure block
    # below. `tracker.wants()` is exactly that distinction.
    expand = bool(getattr(args, "expand", False))
    tracker = progress.live(
        "read", _short_subject(args.url), enabled=False if args.json else None
    )
    try:
        with tracker:
            if getattr(args, "items", 0):
                if getattr(args, "pages", 1) > 1:
                    # --items counts rows and --pages counts hops; together the
                    # first silently won. Say it rather than drop one.
                    print("--items and --pages are mutually exclusive; using --items.",
                          file=sys.stderr)
                pages = unlocker.read_items(
                    args.url, args.items, backends=backends, allow_human=args.human,
                    scrub=args.scrub, progress=tracker.wants(), cookies=cookies,
                    expand=expand,
                    proxy=proxy, proxy_trusted=getattr(args, "proxy_trusted", False),
                    **_media_kw(args),
                )
            elif getattr(args, "pages", 1) > 1:
                pages = unlocker.read_pages(
                    args.url, args.pages, backends=backends, allow_human=args.human,
                    scrub=getattr(args, "scrub", False), progress=tracker.wants(),
                    cookies=cookies, expand=expand,
                    proxy=proxy, proxy_trusted=getattr(args, "proxy_trusted", False),
                    **_media_kw(args),
                )
            else:
                pages = [unlocker.fetch(
                    args.url, backends=backends, allow_human=args.human,
                    scrub=getattr(args, "scrub", False), progress=tracker.wants(),
                    cookies=cookies, expand=expand,
                    proxy=proxy, proxy_trusted=getattr(args, "proxy_trusted", False),
                    **_media_kw(args),
                )]
            result = pages[0]
            if tracker.wants():
                tracker.summary(_read_receipt(tracker, result, len(pages)))
    except unlocker.UnlockerError as e:
        # The live block is already down. The ending is the same ladder the
        # user watched, with the failed rungs red and their reasons in the
        # detail column -- not a separate prose block that repeats the header.
        from searchts import receipts

        rows = [
            receipts.Row(progress.ROW_FAIL, backend, ux.tidy_reason(why))
            for backend, why in e.attempts
        ]
        # One extra row, only when fetch had something useful to add. The
        # per-backend reasons above are each true; none of them says what to do
        # next, and a read that carried cookies is exactly the case where that
        # is the whole question.
        if e.hint:
            rows.append(receipts.Row(progress.ROW_WARN, "hint", e.hint))
        # A login wall on an anonymous read is the one failure where the
        # reason is not the whole answer: the page exists, it is just
        # behind a login. Naming the commands here is what turns a wall into
        # something an agent can act on, and it costs one row on a path
        # that has already failed.
        if any("login-wall" in why for _, why in e.attempts):
            rows.append(
                receipts.Row(progress.ROW_WARN, "login", _login_wall_hint_text(args.url))
            )
        text = receipts.block(
            tracker.color,
            "read",
            rows,
            subject=tracker.subject,
            elapsed=tracker.elapsed(),
            status=progress.ROW_FAIL,
            unicode_ok=tracker.unicode_ok,
            width=78,
        )
        print(text, file=sys.stderr)
        sys.exit(1)

    # Surface prompt-injection findings to stderr so stdout stays clean content.
    if result.warnings:
        print(f"! {len(result.warnings)} possible prompt-injection indicator(s) detected",
              file=sys.stderr)

    if args.json:
        payload = {
            "url": args.url,
            "final_url": result.final_url or args.url,
            "fetched_at": result.fetched_at,
            "backend": result.backend,
            "status": result.status,
            "chars": len(result.text),
            # True only when this answer came from a request that carried the
            # session cookies. Without it, a logged-in read and an anonymous one
            # produce byte-identical receipts and the caller cannot say which
            # one it just got.
            "authenticated": result.authenticated,
            "text": result.text,
            "next_url": result.next_url,
            "more": result.more,
            "pages": [
                {"url": p.final_url or args.url, "text": p.text, "next_url": p.next_url}
                for p in pages
            ],
        }
        print(json.dumps(payload, ensure_ascii=False))
    else:
        # Status to stderr so stdout stays a clean, pipeable content stream.
        # A terminal already got that status as a receipt under the content
        # stream, so only the non-terminal path repeats it as a line.
        if not tracker.wants():
            status = f"[{result.backend}] status={result.status} chars={len(result.text)}"
            if result.authenticated:
                status += " (logged in)"
            print(status, file=sys.stderr)
            # A pipe and an agent never see the receipt, so the lever note
            # under it is repeated here as its own stderr line.
            tip = _read_config_tip(result)
            if tip:
                _print_tip(tip)
        print(result.text)
        for extra in pages[1:]:
            print(f"\n# {extra.final_url}\n\n{extra.text}")


def _media_kw(args) -> dict:
    """``media=N`` only when the caller asked. ``0`` is "not asked"."""
    asked = getattr(args, "media", 0) or 0
    return {"media": asked} if asked else {}


_LEVER_FLAGS = ("--media", "--items", "--expand")


def _read_config_tip(result) -> str:
    """The lever sentence a read note already carries, lifted verbatim.

    The note owns the flag and its ceiling; this line repeats that sentence
    under the receipt, so a person scanning the end of the command finds the
    lever without rereading the body note. Notes that name no lever add
    nothing, which is what a read before the levers landed looks like.
    """
    tips = []
    for item in getattr(result, "more", None) or []:
        note = (item.get("note") or "") if isinstance(item, dict) else ""
        for flag in _LEVER_FLAGS:
            if flag in note:
                tail = note.split(flag, 1)[1].rstrip()
                if tail.endswith("]"):
                    tail = tail[:-1].rstrip()
                tip = flag + tail
                if not tip.endswith((".", "!", "?")):
                    tip += "."
                if tip not in tips:
                    tips.append(tip)
                break
    return "  ".join(tips)


def _print_tip(tip: str, width: int = 76) -> None:
    """Print one ``[CONFIG]`` line, wrapped under its own mark."""
    from searchts import progress

    for line in _tip_lines(tip, progress.Style(False), width):
        print(line, file=sys.stderr)


def _read_receipt(tracker, result, page_count: int) -> str:
    """One line under the content: who served it, how big it was, how long."""
    from searchts import progress

    s = tracker.color
    mark = "✓" if tracker.unicode_ok else "+"
    bits = [f"{s.green(mark)} {s.cyan('read')}",
            progress.link_url(result.final_url or "", tracker.links) or ""]
    bits = [b for b in bits if b]
    bits.append(s.dim("via " + (result.backend or "?")))
    if result.status:
        bits.append(s.dim(str(result.status)))
    bits.append(s.dim(_human_chars(len(result.text))))
    if page_count > 1:
        bits.append(s.dim(f"{page_count} pages"))
    if result.authenticated:
        bits.append(s.green("logged in"))
    if result.next_url:
        bits.append(s.dim("next page available"))
    bits.append(s.dim(progress.human_time(tracker.elapsed())))
    bits = [b for b in bits if b]
    line = "  " + "  ".join(bits)
    tip = _read_config_tip(result)
    for tip_line in _tip_lines(tip, s) if tip else []:
        line += "\n" + tip_line
    return line



def _read_command_proxy(args):
    """Resolve the proxy for one read: flag first, then the saved config value.

    Returns None when neither is set, which keeps the ladder on the user's own
    address exactly as it was before this existed.
    """
    raw = getattr(args, "proxy", None)
    if not raw:
        try:
            from searchts.config import Config

            raw = (Config().get("proxy") or "").strip() or None
        except Exception:
            raw = None
    if not raw:
        return None
    from searchts.egress import ProxyError, normalize_proxy, redact

    try:
        normalize_proxy(raw)
    except ProxyError as e:
        print(f"proxy: {e}", file=sys.stderr)
        sys.exit(1)
    # One line, credentials stripped, so a long read can be traced later.
    print(f"proxy: {redact(raw)}", file=sys.stderr)
    return raw


def _read_command_cookies(args):
    """Resolve cookies for one read, reporting only safe provenance.

    The rules live in ``login_store`` so the read path, the ``login`` verbs and
    the MCP tool cannot reach different conclusions about the same site.

    Two routes, and the difference is whether the user asked for a browser:

    * No browser named. The store decides. A kept site is used with no prompt
      at all, which is the entire point of keeping it. A site that is not kept
      is *not* silently escalated: read falls back to anonymous and, if that
      hits a login, the failure names the exact ``login`` command to run.
    * A browser named. That is the user reaching for a login that is not kept,
      so it is the copy route, and the session's one approval is required. It
      is asked for exactly here rather than per URL.
    """
    from searchts.login_store import (
        SessionConsentNeeded,
        grant_session_copy,
        host_of,
        prepare,
    )
    from searchts.session_cookies import CookieReadError

    browser = getattr(args, "cookies_from_browser", None) or ""
    cookie_file = getattr(args, "cookies", None) or ""
    cdp_port = getattr(args, "cdp_port", None)

    # Explicit, non-browser sources stay exactly as they were: a file or a port
    # is already the user pointing at something specific.
    if cookie_file or cdp_port:
        from searchts.session_cookies import resolve_cookies

        try:
            records = resolve_cookies(
                args.url, cookies=cookie_file,
                cookies_from_browser=browser, cdp_port=cdp_port,
            )
        except CookieReadError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"could not read cookies: {e}", file=sys.stderr)
            sys.exit(1)
        if not records:
            return None
        print(f"cookies: {_cookie_provenance(args, len(records))}", file=sys.stderr)
        return records

    # No explicit source: let the state machine decide what this site is.
    host = host_of(args.url)

    # `--yes` is the only way this process grants itself the copy approval.
    # It is deliberately explicit: consent is recorded per PID, so a grant
    # cannot outlive the run that the user approved, and there is no ambient
    # "always allow" that would survive the next terminal. The grant happens
    # here, inside this process, because that is what the PID scoping means.
    if browser and getattr(args, "yes", False):
        grant_session_copy()

    try:
        if browser:
            # Whether this browser *can* be read is settled before the consent
            # question, not after. A Chromium cookie file is locked, so asking
            # the user to approve a copy that cannot happen is a question whose
            # answer does not matter, and it burns the one approval the session
            # was going to get for a site that could have used it.
            source = prepare(args.url, browser=browser)
        else:
            source = prepare(args.url)
    except SessionConsentNeeded as e:
        print(str(e), file=sys.stderr)
        sys.exit(3)
    except CookieReadError as e:
        # A site that is not kept and has nothing to copy is not an error
        # here. An anonymous read is still a valid read; only a login wall
        # will make the user care, and that names the command to run.
        if not browser:
            return None
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"could not read cookies: {e}", file=sys.stderr)
        sys.exit(1)

    if not source or not getattr(source, "count", 0):
        return None
    label = getattr(source, "via", "") or "login"
    print(f"cookies: {label} -> {source.count} cookies for {args.url}", file=sys.stderr)
    if source.via == "owned store":
        print(f"{host} was already kept; no browser opened.", file=sys.stderr)
    else:
        print(
            "copied for this session only, not kept. "
            f"`searchts login kill {host}` removes any saved login.",
            file=sys.stderr,
        )
    return source.cookies


def _cookie_provenance(args, count):
    """One line saying where the cookies came from. Never a value."""
    cdp_port = getattr(args, "cdp_port", None)
    if cdp_port:
        return f"cdp port -> {count} cookies for {args.url}"
    if getattr(args, "cookies", None):
        return f"file {args.cookies} -> {count} cookies for {args.url}"
    return f"browser ({args.cookies_from_browser}) -> {count} cookies for {args.url}"


def _cmd_login(args):
    """Keep, kill, list, and sign in. The verbs a logged-in read moves through.

    Every path here reports provenance and never a cookie value. The ordering is
    ``login_store``'s: this function decides nothing about what is allowed, so
    the CLI and the MCP tool cannot reach different conclusions about the same
    site.
    """
    from searchts.login_store import (
        SessionConsentNeeded,
        audit,
        host_of,
        keep,
        kill,
        purge_scratch,
    )
    from searchts.session_cookies import CookieReadError, for_site

    action = getattr(args, "login_command", None) or "list"

    from searchts import progress, receipts

    style, unicode_ok = receipts.for_stream(sys.stdout)

    def receipt(rows, *, subject="", status=progress.ROW_OK):
        print(receipts.block(
            style,
            "login",
            rows,
            subject=subject,
            status=status,
            unicode_ok=unicode_ok,
        ))

    if action == "list":
        a = audit()
        kept_sites = a.kept
        rows = []
        if not kept_sites:
            rows.append(receipts.Row(
                progress.ROW_SKIP,
                "kept",
                "no site logins are kept; nothing is stored between reads",
            ))
        else:
            for host, info in kept_sites.items():
                extra = f" (from {info['browser']})" if info.get("browser") else ""
                rows.append(receipts.Row(
                    progress.ROW_OK,
                    host,
                    f"{info['cookies']} cookies{extra}",
                ))
        if a.session_copy_granted:
            copied = a.session_copied_sites
            rows.append(receipts.Row(
                progress.ROW_SKIP,
                "session",
                f"may copy logins; copied so far: {', '.join(copied) or 'none'}",
            ))
        if a.scratch:
            rows.append(receipts.Row(
                progress.ROW_SKIP,
                "scratch",
                f"Scratch copies present: {len(a.scratch)} (deleted at the end of a read)",
            ))
        receipt(rows, subject="kept")
        sys.exit(0)

    if action == "purge-scratch":
        gone = purge_scratch()
        receipt(
            [receipts.Row(
                progress.ROW_OK,
                "scratch",
                f"Deleted {len(gone)} scratch copy/copies.",
            )],
            subject="scratch",
        )
        sys.exit(0)

    if action == "kill":
        host = host_of(args.url)
        if not host:
            print(f"{args.url!r} is not a site searchts can file a login under.", file=sys.stderr)
            sys.exit(2)
        killed = kill(args.url, browser_copies=bool(args.also_browser))
        receipt(
            [receipts.Row(progress.ROW_OK, "killed", killed.why)],
            subject=host,
        )
        sys.exit(0)

    if action == "keep":
        host = host_of(args.url)
        if not host:
            print(f"{args.url!r} is not a site searchts can file a login under.", file=sys.stderr)
            sys.exit(2)
        browser = getattr(args, "cookies_from_browser", "") or ""
        if not browser:
            print(
                f"Nothing to keep: pass --cookies-from-browser <browser> to copy "
                f"{host} first, or use `searchts login signin {args.url}`.",
                file=sys.stderr,
            )
            sys.exit(2)
        try:
            # Copying is not keeping, so the session's one approval is still
            # required here. `login keep` does not become a way around it.
            from searchts.login_store import require_copy_consent

            require_copy_consent(args.url)
            source = for_site(args.url, browser)
        except SessionConsentNeeded as e:
            print(str(e), file=sys.stderr)
            sys.exit(3)
        except CookieReadError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)
        out = keep(args.url, source.cookies, browser=browser)
        receipt(
            [receipts.Row(progress.ROW_OK, "kept", out.why)],
            subject=host,
        )
        sys.exit(0)

    if action == "signin":
        from searchts.login_store import host_of as _host
        from searchts.signin_browser import signin

        host = _host(args.url)
        if not host:
            print(f"{args.url!r} is not a site searchts can file a login under.", file=sys.stderr)
            sys.exit(2)
        try:
            source = signin(args.url, browser=args.browser)
        except CookieReadError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)
        # Not "Signed in to X". Nothing here has verified that a sign-in
        # happened: a browser that loads the sign-in page sets guest cookies
        # (bcookie, lidc, __cf_bm) before anyone types anything, and counting
        # host-matching cookies as proof of authentication reported a success
        # for a sign-in that never occurred. This says what was observed. The
        # read is a separate command, so it cannot be pointed at from here --
        # the point is that only a read can settle it, not that one is coming.
        rows = [receipts.Row(
            progress.ROW_SKIP,
            "read",
            f"{source.count} cookie(s) for {host} from the sign-in browser "
            f"({source.via}). If no sign-in happened these are guest cookies, "
            f"and only a later read of {host} can tell the difference.",
        )]
        if args.yes:
            kept_login = keep(args.url, source.cookies, browser=args.browser)
            rows.append(receipts.Row(progress.ROW_OK, "kept", kept_login.why))
        else:
            rows.append(receipts.Row(
                progress.ROW_WARN,
                "kept",
                "Nothing kept. The next logged-in read of "
                f"{host} asks again. Pass --yes to keep it.",
            ))
        receipt(rows, subject=host)
        sys.exit(0)

    print(f"unknown login action {action!r}", file=sys.stderr)
    sys.exit(2)


def _login_wall_hint_text(url: str) -> str:
    """One sentence naming the two commands that can get past a login wall.

    Printed only when a rung actually reported ``login-wall``, so it never
    appears on a page that merely embeds a sign-in link, and never on a read
    that already carried cookies -- in that case ``unlocker`` has its own
    ``hint`` naming the real cause, and two competing explanations would be
    worse than one.

    Both ways past the wall end the same way, and that is said out loud: the
    cookies ride the direct request only. The browser tier is sent none of
    them, which is the fence that stops a live login reaching a third party,
    so nobody should expect a logged-in browser to make ``read`` work.
    """
    from searchts.login_store import host_of, kept

    host = host_of(url)
    if not host:
        return ""
    if kept(url):
        # Already kept and still a wall: the saved login is stale, so keeping
        # is not the fix and suggesting it would waste the user's time.
        return (
            f"{host} is already in the searchts store and still returned a "
            f"login page, so that saved login has expired. Sign in again: "
            f"searchts login kill {host}, then searchts login signin {url}.\n"
            "Either way those cookies ride the direct request only. "
            "That is why the browser tier is sent none of them, "
            "so a logged-in browser is not what makes the next read work."
        )
    return (
        f"{host} is behind a login. Two ways past it, your call:\n"
        f"searchts login signin {url}\n"
        f"searchts read {url} --cookies-from-browser firefox\n"
        "Either way those cookies ride the direct request only. "
        "That is why the browser tier is sent none of them, "
        "so a logged-in browser is not what makes the next read work."
    )


def _print_login_wall_hint(url: str) -> None:
    """Print the login-wall guidance as a plain stderr block.

    Kept separate from the receipt row because the two commands are long, and
    a receipt that hard-wraps a command is harder to copy than a short block
    that never wraps one.
    """
    from searchts.login_store import host_of, kept

    host = host_of(url)
    if not host:
        return
    if kept(url):
        print(
            f"  {host} is already in the searchts store and still returned a "
            f"login page, so that saved login has expired. Sign in again: "
            f"`searchts login kill {host}` then "
            f"`searchts login signin {url}`.",
            file=sys.stderr,
        )
    else:
        print(
            f"  {host} is behind a login. Two ways past it, your call:\n"
            f"    searchts login signin {url}          sign in once in a browser searchts opens\n"
            f"    searchts read {url} --cookies-from-browser firefox   copy from a browser you already signed into",
            file=sys.stderr,
        )
    print(
        "  Either way those cookies ride the direct request only: the browser "
        "tier is sent none of them, so a logged-in browser is not what makes "
        "the next read work.",
        file=sys.stderr,
    )


def _stdout_link(text: str, url: str) -> str:
    """A clickable label on stdout, and byte-identical text when piped."""
    from searchts import progress

    return progress.link(text, url, enabled=progress.use_links(sys.stdout))


def _home_relative(path: str) -> str:
    """``~/.searchts`` instead of a home directory the reader already knows."""
    home = os.path.expanduser("~")
    try:
        rel = os.path.relpath(path, home)
    except ValueError:
        return path
    if rel == ".":
        return "~"
    if rel != ".." and not rel.startswith(".." + os.sep):
        return "~" + os.sep + rel
    return path


def _short_path(path: str, limit: int = 63) -> str:
    """A receipt-sized path: home-relative, or elided to its last components."""
    shown = _home_relative(str(path))
    if len(shown) <= limit:
        return shown
    parts = shown.split(os.sep)
    if len(parts) >= 2:
        tail = os.sep.join(parts[-2:])
        candidate = "…" + os.sep + tail
        if len(candidate) <= limit:
            return candidate
    return "…" + shown[-(limit - 1):]


def _stdout_path(path: str) -> str:
    return _stdout_link(path, _file_uri(path))


def _file_uri(path: str) -> str:
    try:
        import pathlib

        return pathlib.Path(path).resolve().as_uri()
    except (ValueError, OSError):
        return ""


def _cmd_get(args):
    """Download one asset through the unlock ladder; print the saved path."""
    from searchts import assets, progress

    tracker = progress.live("get", _short_subject(args.url))
    with tracker:
        try:
            path = assets.get_asset(args.url, args.output, progress=True)
        except assets.AssetError as e:
            tracker.abort()
            print(f"Failed to get asset: {e}", file=sys.stderr)
            sys.exit(1)
        size = path.stat().st_size if path.exists() else 0
        if tracker.wants():
            s = tracker.color
            mark = "✓" if tracker.unicode_ok else "+"
            label = _short_path(str(path), 58)
            tracker.summary(
                f"  {s.green(mark)} {s.cyan('get')}  "
                f"{progress.link(label, _file_uri(str(path)), tracker.links)}"
                f"  {s.dim(progress.human_bytes(size))}  "
                f"{s.dim(progress.human_time(tracker.elapsed()))}")
        else:
            print(f"saved {path} ({size} bytes)", file=sys.stderr)
    print(_stdout_path(str(path)))



def _grab_omitted_note(manifest: dict) -> Optional[str]:
    entries = manifest.get("omitted") or []
    if not entries:
        return None
    total = manifest.get("omitted_count") or sum(e.get("count", 0) for e in entries)
    parts = ", ".join(f"{e['count']} {e['kind']} ({e['reason']})" for e in entries)
    return f"  omitted: {total} asset(s) not saved: {parts}"


def _grab_token_howto(omitted: dict, more: str) -> str:
    """The cap sentence, without repeating counts the line above already gave.

    ``tokens_more`` is ``kept N per list; 13 more radius, ...; --tokens N ...``.
    When that middle clause is the same counts as what was left out, printing
    both stutters. Drop the middle. When it differs, some of what was left
    out is markup a higher cap cannot bring back, so the middle stays: it is
    the part ``--tokens`` would actually return. Any other shape is printed
    whole.
    """
    pieces = more.split("; ")
    if len(pieces) != 3:
        return more
    kept, counts, howto = pieces
    expected = ", ".join(f"{n} more {kind}" for kind, n in omitted.items())
    if counts == expected:
        return f"{kept}; {howto}"
    return more


def _grab_token_note(manifest: dict) -> Optional[str]:
    left = manifest.get("tokens_omitted") or {}
    if not left:
        return None
    parts = ", ".join(f"{n} {kind}" for kind, n in left.items())
    head = f"  tokens left out: {parts}"
    more = manifest.get("tokens_more")
    if not more:
        return head
    return f"{head}\n    {_grab_token_howto(left, more)}"


def _grab_page_md_note(manifest: dict) -> Optional[str]:
    err = manifest.get("page_md_error")
    return f"  page.md not saved: {err}" if err else None


def _cmd_grab(args):
    """Save the files a read named, through the same unlock ladder."""
    from urllib.parse import urlparse

    from searchts import assets, progress

    out = args.out
    if not out:
        host = urlparse(assets.normalize(args.url)).netloc.replace(":", "_") or "site"
        out = f"searchts-grab-{host}"
    # One absolute folder is the contract: it is what stdout prints, what the
    # receipt links, and what the user can paste into `cd`. A relative --out
    # would make the link depend on the shell's cwd at read time.
    out = os.path.abspath(out)
    kinds = tuple(k.strip() for k in (args.kinds or "").split(",") if k.strip())
    if args.max_assets < 0:
        print("--max cannot be negative", file=sys.stderr)
        sys.exit(2)
    try:
        max_tokens = assets.resolve_token_cap(args.max_tokens)
    except ValueError as e:
        print(f"--tokens: {e}", file=sys.stderr)
        sys.exit(2)
    tracker = progress.live(
        "grab", _short_subject(args.url),
        enabled=False if getattr(args, "json", False) else None,
    )
    with tracker:
        try:
            manifest = assets.grab(
                args.url, out, kinds=kinds, include_scripts=args.scripts,
                read=args.read, max_assets=args.max_assets, max_tokens=max_tokens,
                # Ticks go to stderr only, so --json stdout stays machine-clean.
                progress=not getattr(args, "json", False),
            )
        except assets.AssetError as e:
            tracker.abort()
            print(f"Failed to grab {args.url}: {e}", file=sys.stderr)
            sys.exit(1)
        if tracker.wants() and not getattr(args, "json", False):
            # The receipt is written when the live block is taken down, so it
            # has to be built here, inside the block it replaces.
            tracker.summary(_grab_receipt(tracker, manifest, out))

    if args.json:
        note = _grab_omitted_note(manifest)
        if note:
            print(note, file=sys.stderr)
        for tip in _grab_tips(manifest):
            for tip_line in _tip_lines(tip, progress.Style(False)):
                print(tip_line, file=sys.stderr)
        note = _grab_token_note(manifest)
        if note:
            print(note, file=sys.stderr)
        note = _grab_page_md_note(manifest)
        if note:
            print(note, file=sys.stderr)
        print(json.dumps(manifest, ensure_ascii=False))
        return

    manifest_path = os.path.join(out, "manifest.json")
    if not tracker.wants():
        title = manifest.get("title") or "(no title)"
        palette = " ".join(
            str(c["hex"])
            for c in manifest.get("palette", [])[:8]
            if isinstance(c, dict) and c.get("hex")
        )
        fonts = ", ".join(manifest.get("fonts", [])[:6])
        print(f"[grab] {title}", file=sys.stderr)
        print(f"  page via {manifest.get('page_backend', '?')}; downloaded "
              f"{manifest.get('downloaded', 0)} assets", file=sys.stderr)
        # The folder is the thing to cd into; the manifest is named beside it
        # so a script can find the structured result without guessing.
        print(f"  folder: {out}", file=sys.stderr)
        print(f"  manifest: {manifest_path}", file=sys.stderr)
        if palette:
            print(f"  palette: {palette}", file=sys.stderr)
        if fonts:
            print(f"  fonts:   {fonts}", file=sys.stderr)
        note = _grab_omitted_note(manifest)
        if note:
            print(note, file=sys.stderr)
        note = _grab_token_note(manifest)
        if note:
            print(note, file=sys.stderr)
        for tip in _grab_tips(manifest):
            for tip_line in _tip_lines(tip, tracker.color):
                print(tip_line, file=sys.stderr)
    # The receipt cannot show a page.md failure, so that one always prints.
    note = _grab_page_md_note(manifest)
    if note:
        print(note, file=sys.stderr)
    print(_stdout_path(out))


def _grab_receipt(tracker, manifest, out: str) -> str:
    """The grab's ending: what landed, where, and the design it found.

    Three ideas from the design pass, in one shape: a tree, because the assets
    are grouped by kind and a flat column hides that; a design card, because the
    palette and the tokens are the actual deliverable for someone rebuilding a
    page; and the path last, dimmed and clickable, because that is what gets
    pasted into the next command.

    Everything here is width-fitted: a long Windows path is the fastest way to
    wrap a terminal and turn a receipt into a paragraph.
    """
    from searchts import progress

    s = tracker.color
    mark = "✓" if tracker.unicode_ok else "+"
    width = 76

    by_kind: Dict[str, list] = {}
    for rec in manifest.get("assets", []):
        if not rec.get("ok"):
            continue
        entry = by_kind.setdefault(rec.get("kind", "other"), [0, 0])
        entry[0] += 1
        entry[1] += rec.get("bytes", 0) or 0
    downloaded = manifest.get("downloaded", 0)
    size = sum(v[1] for v in by_kind.values())
    page_backend = manifest.get("page_backend", "?")

    lines: List[str] = []
    head = (f"  {s.green(mark)} {s.cyan('grab')}  {s.dim(tracker.subject)}")
    tail = "  ".join([s.dim(progress.human_time(tracker.elapsed()))])
    pad = " " * max(2, width - _plain_len(head) - _plain_len(tail) - 2)
    lines.append(head + pad + tail)
    lines.append("")

    delivered = (f"  {s.dim('Delivered')}   {downloaded} files   "
                 f"{progress.human_bytes(size)}   {s.dim('via ' + page_backend)}")
    lines.append(delivered)

    kinds = sorted(by_kind.items(), key=lambda kv: (-kv[1][0], kv[0]))
    rows: List[Tuple[str, List[str]]] = []
    for kind, (count, ksize) in kinds:
        rows.append((kind, [f"{count:>3}   {s.dim(progress.human_bytes(ksize))}"]))
    omitted = manifest.get("omitted") or []
    if omitted:
        total = manifest.get("omitted_count") or sum(e["count"] for e in omitted)
        reasons = ", ".join(f"{e['count']} {e['kind']} ({e['reason']})"
                            for e in omitted)
        rows.append(("omitted",
                     _pack(f"{total}: {reasons}".split(), width - 16, sep=" ")))
    for is_last, (label, chunks) in enumerate(rows):
        _tree_row(s, lines, label, chunks, is_last == len(rows) - 1)

    tokens = manifest.get("tokens") or {}
    palette = manifest.get("palette") or []
    fonts = manifest.get("fonts") or []
    if palette or fonts or tokens:
        lines.append("")
        lines.append(f"  {s.dim('Design')}")
        design_rows: List[Tuple[str, List[str], int]] = []
        if palette:
            pieces = [progress.swatch(c["hex"], tracker.color.enabled) + c["hex"]
                      for c in palette[:6]]
            design_rows.append(("palette", _pack(pieces, width - 16), 3))
        if fonts:
            design_rows.append(("fonts", _pack(", ".join(fonts[:4]).split(),
                                               width - 16, sep=" "), 0))
        counts = [(k, len(v)) for k, v in tokens.items() if v]
        if counts:
            order = {"radius": 0, "shadow": 1, "spacing": 2}
            counts.sort(key=lambda kv: order.get(kv[0], 9))
            design_rows.append(("tokens",
                                ["   ".join(f"{n} {k}" for k, n in counts)], 0))
        for is_last, (label, chunks, hang) in enumerate(design_rows):
            _tree_row(s, lines, label, chunks,
                      is_last == len(design_rows) - 1, hang)

    lines.append("")
    lines.append(f"  {s.dim('Saved to')}  {progress.link_path(out, tracker.links)}")
    for tip in _grab_tips(manifest):
        lines.extend(_tip_lines(tip, s))
    return "\n".join(lines)


def _sentence(text: str) -> List[str]:
    return text.split()


def _pack(pieces: List[str], room: int, sep: str = "  ") -> List[str]:
    """Greedy fill into *room*-wide lines, keeping styled pieces whole."""
    lines: List[str] = []
    current = ""
    for piece in pieces:
        candidate = piece if not current else current + sep + piece
        if current and _plain_len(candidate) > room:
            lines.append(current)
            current = piece
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


_TIP_LEAD = "  [CONFIG] Tip: "


def _tip_lines(tip: str, s, width: int = 76) -> List[str]:
    """One shape for every [CONFIG] tip: a lead, then a hanging wrap.

    The tip text is the note's own sentence; this renderer only decides where
    it breaks, so a long flag sentence folds under the mark instead of under
    whatever column the terminal's cursor happened to be at.
    """
    lead = "  " + s.cyan("[CONFIG]") + s.dim(" Tip: ")
    chunks = _pack(_sentence(tip), width - len(_TIP_LEAD), sep=" ")
    if not chunks:
        return []
    out = [lead + chunks[0]]
    out.extend(" " * len(_TIP_LEAD) + chunk for chunk in chunks[1:])
    return out


def _tree_row(s, lines: List[str], label: str, chunks: List[str],
              is_last: bool, hang: int = 0) -> None:
    elbow = ("└─" if is_last else "├─")
    head = f"  {s.dim(elbow)} {label:<10} "
    lines.append(head + chunks[0])
    indent = " " * (_plain_len(head) + hang)
    for chunk in chunks[1:]:
        lines.append(indent + chunk)


def _plain_len(text: str) -> int:
    import re

    return len(re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text))


def _grab_tips(manifest) -> List[str]:
    """The next levers this grab actually has, most relevant first.

    A tip that guesses is worse than no tip: it sends someone to a flag that
    will change nothing. Each branch here is a cap that really did cut this
    result short. The token lever is always printed, because it is the one
    knob this command exposes that raises the *quality* of what came back
    rather than the quantity.
    """
    omitted = manifest.get("omitted") or []
    limits = manifest.get("limits") or {}
    tips: List[str] = []
    if any(e.get("reason") == "max-assets" for e in omitted):
        cap = limits.get("max_assets", 120)
        tips.append(f"raise --max {cap} to save the rest "
                    "(named in manifest.json)")
    elif any(e.get("reason") == "size-cap" for e in omitted):
        tips.append("raise --max-total-mb to save the rest")
    if manifest.get("tokens_more") or manifest.get("tokens_omitted"):
        tips.append("--tokens N (max 200) reads more radius, shadow and spacing")
    else:
        tips.append("--tokens N (max 200) reads past the default 24 values")
    return tips




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
    from searchts import progress
    from searchts import search as search_mod

    providers = _parse_provider_flags(args.provider)
    tracker = progress.live(
        "search", f'"{args.query}"', enabled=False if args.json else None
    )
    with tracker:
        try:
            results = search_mod.search(
                args.query, max_results=args.max_results, providers=providers,
                progress=not args.json,
            )
        except search_mod.SearchError as e:
            tracker.abort()
            print(f"Search failed for {e.query!r}", file=sys.stderr)
            for provider, why in e.attempts:
                print(f"  {provider}: {why}", file=sys.stderr)
            sys.exit(1)

        if args.json:
            print(search_mod.SNIPPET_LINE, file=sys.stderr)
            payload = [
                {"title": r.title, "url": r.url, "snippet": r.snippet, "source": r.source}
                for r in results
            ]
            print(json.dumps(payload, ensure_ascii=False))
            return

        sources = {r.source for r in results if r.source}
        if tracker.wants():
            s = tracker.color
            mark = "✓" if tracker.unicode_ok else "+"
            bits = [f"{s.green(mark)} {s.cyan('search')}",
                    s.dim(f"{len(results)} results")]
            if sources:
                bits.append(s.dim(f"{len(sources)} providers"))
            bits.append(s.dim(progress.human_time(tracker.elapsed())))
            tracker.summary("  " + "  ".join(bits))

    print(search_mod.SNIPPET_LINE)
    for i, r in enumerate(results, start=1):
        snippet = r.snippet.replace("\n", " ").strip()
        if len(snippet) > 200:
            snippet = snippet[:197] + "..."
        print(f"{i}. {r.title or '(no title)'}")
        print(f"   {_stdout_link(r.url, r.url)}")
        if snippet:
            print(f"   {snippet}")
        if r.source:
            print(f"   [{r.source}]")



def _cmd_doctor(args=None):
    from searchts.config import Config
    from searchts.doctor import check_all, format_report

    config = Config()
    # Progress ticks go to stderr only, so --json stdout stays machine-clean.
    results = check_all(config, progress=not getattr(args, "json", False))

    if args is not None and getattr(args, "json", False):
        print(json.dumps(results, ensure_ascii=False, indent=2))
        from searchts.doctor import format_lock_note, windows_searchts_pids
        note = format_lock_note(windows_searchts_pids())
        if note:
            print(note, file=sys.stderr)
        return

    # The report owns its wrapping and colour, so it prints as plain text;
    # Rich would re-fold the 71-column lines at the terminal width.
    print(format_report(results))

    from searchts.integrations.agent_wiring import format_wiring_report
    print(format_wiring_report())
    # doctor is read-only: skill install stays on `searchts install` / `searchts skill`.


def _ask(prompt: str) -> str:
    """One line of input, and an empty answer when there is no input to read.

    The wizard's prompts say "press Enter to skip", so a closed stdin is the
    same answer as an empty line. Without this, ``searchts setup`` in a script,
    a CI job, or any run with stdin closed dies with an EOFError traceback
    instead of finishing the steps that need no answer.
    """
    try:
        return input(prompt).strip()
    except EOFError:
        print()
        return ""


def _cmd_setup():
    from searchts import progress, receipts
    from searchts.config import Config

    config = Config()
    style, unicode_ok = receipts.for_stream(sys.stdout)
    print(receipts.header(
        style,
        "setup",
        status=progress.ROW_SKIP,
        unicode_ok=unicode_ok,
    ))
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
                print("  Current status: ✓ configured")
            else:
                print("  Current status: · not configured")
                setup_now = _ask("  Configure Exa automatically now? [y/N]: ").lower()
                if setup_now in ("y", "yes"):
                    add_r = subprocess.run(
                        ["mcporter", "config", "add", "exa", "https://mcp.exa.ai/mcp"],
                        capture_output=True, encoding="utf-8", errors="replace", timeout=10,
                    )
                    if add_r.returncode == 0:
                        print("  ✓ Exa configured")
                    else:
                        print("  ! Automatic configuration failed, please run manually:")
                        print("     mcporter config add exa https://mcp.exa.ai/mcp")
        except Exception:
            print("  ! Could not check the Exa configuration, please run manually:")
            print("     mcporter config add exa https://mcp.exa.ai/mcp")
        print()

    # Step 2: GitHub token (env only — searchts does not store this in YAML)
    print("[Optional] GitHub Token -- raise gh/API rate limits")
    print("  Export GITHUB_TOKEN or add it to .env. searchts does not store this key.")
    print("  Get one: https://github.com/settings/tokens")
    if os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"):
        print("  Current status: ✓ GITHUB_TOKEN/GH_TOKEN is set in the environment")
    else:
        print("  Current status: · not set. Skipped; the public API works too")
    print()

    # Step 3: Reddit — rdt-cli (a channel; `read` does not need a login, F5f)
    print("[Info] Reddit -- no login needed to `searchts read` a public page (that is the "
          "known-host ring; it needs searchts install --browser and a profile Reddit knows). "
          "These CHANNEL backends do need one:")
    print(f"  Install: pipx install '{_RDT_GIT_SOURCE}'")
    print("  Then run: rdt login (you must log into reddit.com in the browser first)")
    print()

    # Step 4: Groq (Whisper)
    print("[Optional] Groq API -- speech-to-text for videos without subtitles")
    print("  Free tier, sign up: https://console.groq.com")
    current = config.get("groq_api_key")
    if current:
        print("  Current status: ✓ configured")
    else:
        key = _ask("  GROQ_API_KEY (press Enter to skip): ")
        if key:
            config.set("groq_api_key", key)
            print("  ✓ Speech-to-text enabled!")
        else:
            print("  Skipped")
    print()

    # Summary. The wizard's ending is one receipt, not a second banner.
    print()
    print(receipts.block(
        style,
        "setup",
        [
            receipts.Row(
                progress.ROW_OK, "config", f"saved to {_short_path(str(config.config_path))}"
            ),
            receipts.Row(progress.ROW_OK, "next", "run searchts doctor to see the full status"),
        ],
        unicode_ok=unicode_ok,
    ))


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


#: What `searchts update` runs. Kept here so check-update still has a manual
#: fallback on a copy that does not have the command yet. See docs/update.md.
_UPDATE_INSTRUCTIONS = (
    "How to update:\n"
    "  searchts update\n"
    "  searchts upgrade     (same command)\n"
    "By hand, if this copy has no update command yet:\n"
    "  pipx:      pipx upgrade searchts --include-injected\n"
    "  uv tool:   uv tool upgrade searchts\n"
    "  venv:      python -m pip install -U \"searchts[mcp]\"\n"
    "  uvx:       uv cache clean --force searchts\n"
    "Guide: https://raw.githubusercontent.com/capad-xyz/searchts/main/docs/update.md"
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

    remote_version, local_version = parse(remote), parse(local)
    if remote_version is None or local_version is None:
        return remote != local  # unparseable — fall back to old behavior
    return remote_version > local_version


def _release_rows(body: str, limit: int = 5):
    """Release notes as ``(scope, subject)`` rows, without the GitHub markdown.

    GitHub's auto-generated notes are a list of PR titles with links and
    handles; pasting them into a terminal ignores the width and the reader.
    This keeps the conventional-commit scope when there is one, strips the
    link/handle decoration, and stops at *limit* rows.
    """
    import re

    rows = []
    seen = set()
    for line in (body or "").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text.lower().startswith(("what's changed", "new contributors",
                                    "**full changelog**", "full changelog")):
            continue
        text = re.sub(r"^[-*+]\s+", "", text)
        # Release-please writes the scope in bold before the colon, while the
        # auto-generated "What's Changed" list repeats the same PR as
        # `feat(scope): ...`. Remember the bold form so both parse alike; the
        # duplicate is then dropped by the subject key below.
        bold_scope = text.startswith("**")
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"\s+by\s+@[\w-]+\s+in\s+\S+.*$", "", text, flags=re.I)
        text = re.sub(r"\s+in\s+https?://\S+$", "", text)
        text = text.replace("**", "").replace("`", "").strip()
        if not text or "@" in text and "first contribution" in text.lower():
            continue
        match = re.match(
            r"^(?P<type>feat|fix|perf|docs|refactor|test|build|ci|chore|revert)"
            r"(?:\((?P<scope>[^)]+)\))?!?:\s*(?P<subject>.+)$",
            text,
            flags=re.I,
        )
        if match:
            scope = (match.group("scope") or match.group("type")).lower()
            subject = match.group("subject").strip()
        elif bold_scope:
            bold = re.match(
                r"^(?P<scope>[a-z][\w-]*):\s*(?P<subject>.+)$", text, flags=re.I
            )
            if bold:
                scope = bold.group("scope").lower()
                subject = bold.group("subject").strip()
            else:
                scope, subject = "change", text
        else:
            scope, subject = "change", text
        # A release-please "chore(main): release 0.18.0" is bookkeeping, not
        # a change a reader can act on.
        if scope in ("main", "chore") and subject.lower().startswith("release "):
            continue
        # The PR number and commit hash are how the release page navigates;
        # the receipt has no links to attach them to, so they are noise here.
        subject = re.sub(r"\s*\(#[0-9]+\)", "", subject)
        subject = re.sub(r"\s*\([0-9a-f]{7,}\)", "", subject, flags=re.I).strip()
        key = " ".join(subject.lower().split())
        if key in seen:
            continue
        seen.add(key)
        rows.append((scope, subject))
        if len(rows) >= limit:
            break
    return rows


def _check_update_receipt(tracker, status, rows, subject=""):
    from searchts import receipts

    style, unicode_ok = receipts.for_stream(sys.stdout)
    return receipts.block(
        style,
        "check-update",
        rows,
        subject=subject,
        elapsed=tracker.elapsed(),
        status=status,
        unicode_ok=unicode_ok,
    )


def _cmd_check_update():
    """Check for newer versions on GitHub."""
    from searchts import __version__, progress, receipts

    release_url = "https://api.github.com/repos/capad-xyz/searchts/releases/latest"
    commit_url = "https://api.github.com/repos/capad-xyz/searchts/commits/main"

    tracker = progress.live("check-update", summary_stream=sys.stdout)
    with tracker:
        # The live row is the new wording; a pipe keeps the old plain line the
        # tests and the logs already know, byte for byte.
        if tracker.is_live:
            tracker.stage("checking GitHub releases")
        else:
            progress.narrate("checking for updates…")

        resp, err, attempts = _github_get_with_retry(release_url, timeout=10, retries=3)
        if err:
            reason = f"{_update_error_text(err)} (retried {attempts} times)"
            if tracker.is_live:
                tracker.settle(progress.ROW_FAIL, reason)
            text = _check_update_receipt(
                tracker,
                progress.ROW_FAIL,
                [receipts.Row(progress.ROW_SKIP, "reason", reason)],
            )
            receipts.emit(tracker, text, stream=sys.stdout)
            return "error"

        if resp.status_code == 200:
            data = resp.json()
            latest = data.get("tag_name", "").lstrip("v")
            body = data.get("body", "")
            if tracker.is_live:
                tracker.settle(
                    progress.ROW_OK,
                    f"v{latest} available"
                    if latest and _is_newer_version(latest, __version__)
                    else "current",
                )

            if latest and _is_newer_version(latest, __version__):
                rows = [
                    receipts.Row(progress.ROW_SKIP, "current", f"v{__version__}"),
                    receipts.Row(progress.ROW_SKIP, "latest", f"v{latest}  update available"),
                    receipts.Section("What's new"),
                ]
                rows += [
                    receipts.Row(progress.ROW_SKIP, scope, subject)
                    for scope, subject in _release_rows(body)
                ]
                rows.append(
                    receipts.Row(
                        progress.ROW_OK,
                        "searchts update",
                        f"run it to move to v{latest}",
                    )
                )
                receipts.emit(
                    tracker,
                    _check_update_receipt(
                        tracker, progress.ROW_OK, rows, subject=f"v{__version__} -> v{latest}"
                    ),
                    stream=sys.stdout,
                )
                return "update_available"

            receipts.emit(
                tracker,
                _check_update_receipt(
                    tracker,
                    progress.ROW_OK,
                    [receipts.Row(
                        progress.ROW_SKIP,
                        "current",
                        f"v{__version__} is the latest release",
                    )],
                    subject=f"v{__version__}",
                ),
                stream=sys.stdout,
            )
            return "up_to_date"

        release_err = _classify_github_response_error(resp)
        if release_err == "rate_limit":
            if tracker.is_live:
                tracker.settle(progress.ROW_FAIL, "GitHub API rate limit")
            receipts.emit(
                tracker,
                _check_update_receipt(
                    tracker,
                    progress.ROW_FAIL,
                    [receipts.Row(
                        progress.ROW_SKIP,
                        "reason",
                        "GitHub API rate limit; try again later",
                    )],
                ),
                stream=sys.stdout,
            )
            return "error"

        # No releases yet, fall back to latest main commit.
        if tracker.is_live:
            tracker.stage("checking main")
        else:
            progress.narrate("checking for updates…")
        resp2, err2, attempts2 = _github_get_with_retry(commit_url, timeout=10, retries=2)
        if err2:
            reason = f"{_update_error_text(err2)} (retried {attempts + attempts2} times)"
            if tracker.is_live:
                tracker.settle(progress.ROW_FAIL, reason)
            receipts.emit(
                tracker,
                _check_update_receipt(
                    tracker,
                    progress.ROW_FAIL,
                    [receipts.Row(progress.ROW_SKIP, "reason", reason)],
                ),
                stream=sys.stdout,
            )
            return "error"
        if resp2.status_code == 200:
            commit = resp2.json()
            sha = commit.get("sha", "")[:7]
            msg = commit.get("commit", {}).get("message", "").split("\n")[0]
            date = commit.get("commit", {}).get("committer", {}).get("date", "")[:10]
            if tracker.is_live:
                tracker.settle(progress.ROW_OK, f"latest commit {sha}")
            receipts.emit(
                tracker,
                _check_update_receipt(
                    tracker,
                    progress.ROW_OK,
                    [
                        receipts.Row(
                            progress.ROW_SKIP,
                            "latest commit",
                            f"{sha} ({date}) {msg}" if date else f"{sha} {msg}",
                        ),
                        receipts.Row(
                            progress.ROW_OK,
                            "searchts update",
                            "fast-forward to the latest release",
                        ),
                    ],
                    subject=f"v{__version__}",
                ),
                stream=sys.stdout,
            )
            return "unknown"

        commit_err = _classify_github_response_error(resp2)
        if commit_err == "rate_limit":
            reason = "GitHub API rate limit; try again later"
        else:
            reason = f"GitHub returned {resp2.status_code}"
        if tracker.is_live:
            tracker.settle(progress.ROW_FAIL, reason)
        receipts.emit(
            tracker,
            _check_update_receipt(
                tracker,
                progress.ROW_FAIL,
                [receipts.Row(progress.ROW_SKIP, "reason", reason)],
            ),
            stream=sys.stdout,
        )
        return "error"


def _cmd_watch():
    """Quick health check + update check, designed for scheduled tasks.

    A pipe keeps the old single line / monitoring report byte for byte. A
    terminal gets the channel rows from ``check_all`` and one receipt; the
    update check never opens a second live region.
    """
    from searchts import __version__, progress, receipts
    from searchts.config import Config
    from searchts.doctor import check_all
    from searchts.progress import phase as progress_phase

    config = Config()
    live = progress.live_available()
    started = time.monotonic()

    # Check channels. On a terminal check_all owns the one live region; in a
    # pipe the outer line is the log's name for the whole pass.
    if live:
        results = check_all(config, progress=True, command="watch")
    else:
        with progress_phase("checking channels…"):
            results = check_all(config, progress=True, command="watch")
    ok = sum(1 for r in results.values() if r["status"] == "ok")
    total = len(results)

    broken = []
    for key, r in results.items():
        if r["status"] in ("off", "error"):
            broken.append((progress.ROW_FAIL, r))
        elif r["status"] == "warn":
            broken.append((progress.ROW_WARN, r))

    # Check for updates. No phase and no tracker on a terminal: the receipt
    # carries the one fact this round-trip produces.
    update_available = False
    new_version = ""
    if live:
        resp, err, _attempts = _github_get_with_retry(
            "https://api.github.com/repos/capad-xyz/searchts/releases/latest",
            timeout=10,
            retries=2,
        )
    else:
        with progress_phase("checking for updates…"):
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

    if not live:
        # The scheduled-task surface. Its consumers parse this, so it stays.
        if not broken and not update_available:
            print(f"searchts: All systems normal ({ok}/{total} channels available, v{__version__} is up to date)")
            return
        print("searchts monitoring report")
        print("=" * 40)
        print(f"Version: v{__version__}  |  Channels: {ok}/{total}")
        if broken:
            print()
            for status, r in broken:
                issue = f"[X] {r['name']}: {r['message']}" if status == progress.ROW_FAIL \
                    else f"[!] {r['name']}: {r['message']}"
                print(f"  {issue}")
        if update_available:
            print()
            print(f"New version available: v{new_version}")
            print("  Update: searchts update")
            print("    (searchts upgrade is the same command)")
        return

    style, unicode_ok = receipts.for_stream(sys.stdout)
    if not broken and not update_available:
        text = receipts.block(
            style,
            "watch",
            [receipts.Row(
                progress.ROW_SKIP,
                "channels",
                f"{ok}/{total}  v{__version__} current",
            )],
            subject=f"v{__version__}",
            elapsed=time.monotonic() - started,
            unicode_ok=unicode_ok,
        )
        print(text)
        return

    rows = [
        receipts.Row(status, r["name"], receipts.summary(r["message"]))
        for status, r in broken
    ]
    if update_available:
        rows.append(
            receipts.Row(
                progress.ROW_WARN,
                f"v{new_version} available",
                "searchts update",
            )
        )
    header_status = progress.ROW_FAIL if any(
        status == progress.ROW_FAIL for status, _r in broken
    ) else progress.ROW_WARN
    print(receipts.block(
        style,
        "watch",
        rows,
        subject=f"channels {ok}/{total}",
        elapsed=time.monotonic() - started,
        status=header_status,
        unicode_ok=unicode_ok,
    ))


if __name__ == "__main__":
    main()
