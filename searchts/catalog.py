# -*- coding: utf-8 -*-
"""The one source of truth for what a command is and what an agent may run.

The argparse tree in :func:`searchts.cli.build_parser` says which commands,
subcommands and flags exist. This module adds the part argparse has never held:
one lead sentence, at least one example, exit codes, a root-help group, and
the MCP mapping for every command *and every subcommand*.

Everything else is generated from those two: ``searchts help`` / ``--help``,
``searchts help --json``, ``llms.txt``, the command sections of the two
SKILL.md files, and ``docs/cli.md``. ``python -m searchts.helpgen --write``
regenerates the files; ``tests/test_help_catalog.py`` fails when they are stale.

Machine-readable shape (``searchts help --json``)::

    {
      "schema": "searchts.help.v1",
      "prog": "searchts",
      "version": "0.22.0",
      "global_flags": [<flag>],
      "commands": [<command>]
    }

A ``<flag>`` is ``option_strings``, ``dest``, ``metavar``, ``choices``,
``default``, ``help``, ``required``, ``deprecated``, ``legacy``.

A ``<command>`` is ``name`` (space-separated path), ``aliases``, ``group``,
``description``, ``usage``, ``positionals``, ``flags``, ``examples``,
``exit_codes``, ``deprecated``, ``legacy``, ``mcp``, ``subcommands``.

``mcp`` is ``{"tools": [...], "notes": [...], "cli_only": bool, "reason": str}``.
Every tool is either mapped to a command here or listed as MCP-only; every
command is either mapped or carries a CLI-only reason.

Add a command once, in :data:`COMMANDS`; the drift test names the missing
entry and the file to edit.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Dict, Iterator, List, Sequence, Tuple

SCHEMA = "searchts.help.v1"

GROUP_ORDER: Tuple[str, ...] = (
    "READ THE WEB",
    "WIRE UP AN AGENT",
    "SET UP ONCE",
    "HOUSEKEEPING",
)

#: The sentences every screen uses. A command can override any of them.
EXIT_CONTENT = (
    ("0", "content or the requested output was returned"),
    ("1", "the command failed; the reasons are on stderr"),
    ("2", "bad usage, or a URL that cannot be read"),
)
EXIT_PLAIN = (
    ("0", "the command finished"),
    ("1", "the command failed; the reason is on stderr"),
    ("2", "bad usage"),
)
EXIT_ROOT = (
    ("0", "content returned"),
    ("1", "every rung failed; the reasons are on stderr"),
    ("2", "bad usage, or a URL that cannot be read"),
)


@dataclass(frozen=True)
class Command:
    name: str
    group: str
    lead: str
    examples: Tuple[str, ...]
    body: Tuple[str, ...] = ()
    exit_codes: Tuple[Tuple[str, str], ...] = EXIT_PLAIN
    aliases: Tuple[str, ...] = ()
    root: str = ""
    legacy: bool = False
    deprecated: bool = False
    notes: Tuple[str, ...] = ()

    @property
    def path(self) -> Tuple[str, ...]:
        return tuple(self.name.split())


_LOGIN = "SET UP ONCE"
_MCP = "WIRE UP AN AGENT"
_HOUSE = "HOUSEKEEPING"

#: One entry per command *and* subcommand, in the order root help shows them.
COMMANDS: Dict[str, Command] = {}


def _add(command: Command) -> None:
    COMMANDS[command.name] = command


# ── READ THE WEB ──────────────────────────────────────────────────────────
_add(Command(
    name="read", group="READ THE WEB", root="read <url>",
    lead="Fetch a page as markdown, or fail and say why.",
    body=(
        "Climbs the same three rungs the MCP server uses: curl_cffi with a",
        "browser TLS fingerprint, then the Jina reader relay, then a stealth",
        "browser. It stops at the first rung that returns real text. A wall,",
        "a login page, or a client-rendered shell is a failure, not a page.",
    ),
    examples=(
        "searchts read example.com",
        "searchts read https://x.com/jack/status/20 --json",
        "searchts read example.com --pages 3 --expand",
    ),
    exit_codes=(
        ("0", "the page was read"),
        ("1", "every rung failed (a wall, a login page, a network error)"),
        ("2", "bad usage, a malformed URL, or the SSRF guard refused the URL"),
    ),
    notes=(
        "A player page comes back as its captions, or the failure names transcribe.",
        "A share link whose HTML is empty is still a read.",
        "On failure `--json` prints `{\"url\", \"error\": {kind, message, exit_code, "
        "attempts}}` on stdout; kind is bad_url, ssrf_refused, login_wall or read_failed.",
    ),
))
_add(Command(
    name="search", group="READ THE WEB", root='search "<query>"',
    lead="Find URLs to read. A snippet is not the page.",
    body=(
        "Results are fused by rank across every provider that answers, so one",
        "provider having a bad day does not empty the list. A snippet is a",
        "pointer, not a page: read the URL before quoting it.",
    ),
    examples=(
        'searchts search "python asyncio timeout"',
        'searchts search "stripe pricing" --provider duckduckgo -n 5',
        'searchts search "rust 2026" --json',
    ),
    exit_codes=EXIT_CONTENT,
))
_add(Command(
    name="transcribe", group="READ THE WEB", root="transcribe <url>",
    lead="A player page's words: captions, then Whisper.",
    body=(
        "Captions come first and cost nothing. Audio goes to Groq, then OpenAI",
        "if a key is set, else the keyless local Whisper. A local file works",
        "the same way.",
    ),
    examples=(
        "searchts transcribe https://www.youtube.com/watch?v=...",
        "searchts transcribe talk.mp4 --provider local",
        "searchts transcribe https://www.instagram.com/reel/... --cookies-from-browser chrome",
    ),
    exit_codes=EXIT_CONTENT,
))
_add(Command(
    name="grab", group="READ THE WEB", root="grab <url>",
    lead="Save the files a page uses: images, css, fonts.",
    body=(
        "Downloads images, icons, css, fonts and inline svg through the same",
        "unlocker, then extracts the palette, the fonts and the radius/shadow/",
        "spacing values the page actually uses. Every URL is either saved,",
        "named as a failure, or listed as omitted with the reason, so a cap",
        "never truncates silently.",
    ),
    examples=(
        "searchts grab https://stripe.com --out stripe",
        "searchts grab https://linear.app --kinds images,fonts",
        "searchts grab https://example.com --tokens 60 --json",
    ),
    exit_codes=EXIT_CONTENT,
))
_add(Command(
    name="get", group="READ THE WEB", root="get <url>",
    lead="One file through the same unlocker.",
    body=("Prints the saved path on stdout, so it pipes into anything.",),
    examples=("searchts get https://example.com/logo.svg -o assets/",),
    exit_codes=EXIT_CONTENT,
))

# ── WIRE UP AN AGENT ──────────────────────────────────────────────────────
_add(Command(
    name="mcp", group=_MCP,
    lead="Run or wire up the searchts MCP server.",
    body=(
        "stdio by default. --http and --sse bind loopback only: there is no",
        "public URL, and that is on purpose.",
    ),
    examples=("searchts mcp serve", "searchts mcp install --client claude"),
    notes=("A bare `searchts mcp` prints the generated usage and exits 2.",),
))
_add(Command(
    name="mcp serve", group=_MCP, root="mcp serve",
    lead="Run the MCP server (stdio default; --http for loopback).",
    body=(
        "The server exposes the same read/search/download code as the CLI.",
        "stdio is what an agent host spawns; --http and --sse are for a custom",
        "connector on loopback only.",
    ),
    examples=(
        "searchts mcp serve",
        "searchts mcp serve --http --port 8765",
    ),
    exit_codes=(
        ("0", "the server stopped normally"),
        ("1", "the optional `mcp` extra is missing"),
        ("2", "bad usage, or a non-loopback bind was refused"),
    ),
))
_add(Command(
    name="mcp install", group=_MCP, root="mcp install",
    lead="Wire the MCP server into the agents on this machine.",
    body=(
        "Writes `searchts mcp serve` into each detected client's own config",
        "(Claude Code, Claude Desktop, Cursor, Codex, VS Code, Copilot, Gemini,",
        "OpenCode, Windsurf, Devin). It never creates a config for a client",
        "that is not installed and never touches a project file.",
    ),
    examples=(
        "searchts mcp install",
        "searchts mcp install --client cursor",
        "searchts mcp install --client json",
    ),
    notes=(
        "--client json prints the mcpServers snippet and writes nothing.",
        "A config that does not parse, or already names a different command, is left alone.",
    ),
))
_add(Command(
    name="skill", group=_MCP,
    lead="Manage agent skill registration.",
    body=(
        "`skill install` writes the Claude Code slash command and the shared",
        "SKILL.md bundle. The old `skill --install` / `--uninstall` flags still",
        "work for scripts; they are the legacy form of the same job.",
    ),
    examples=(
        "searchts skill install",
        "searchts skill install --dir ~/.claude/commands",
    ),
    notes=("A bare `searchts skill` prints the generated usage and exits 2.",),
))
_add(Command(
    name="skill install", group=_MCP, root="skill install",
    lead="Write the slash command and the shared SKILL.md bundle.",
    body=(
        "Writes `searchts.md` into the commands directory (default",
        "~/.claude/commands) and the SKILL.md bundle into the agent skill homes",
        "that exist. The slash command routes read, search, transcribe, login,",
        "grab and get.",
    ),
    examples=(
        "searchts skill install",
        "searchts skill install --dir ~/.config/opencode/commands",
    ),
))
_add(Command(
    name="doctor", group=_MCP, root="doctor",
    lead="Which channels are installed, configured, working.",
    body=(
        "Probes each optional channel. A tier-0 probe is a capability the",
        "reader can use; the CLIs are PATH checks, not a routing table.",
    ),
    examples=("searchts doctor", "searchts doctor --json"),
    exit_codes=(
        ("0", "the health report was printed"),
        ("2", "bad usage"),
    ),
))

# ── SET UP ONCE ───────────────────────────────────────────────────────────
_add(Command(
    name="install", group=_LOGIN, root="install",
    lead="One-shot installer; --system-deps to change things.",
    body=(
        "Non-mutating by default: without --system-deps it prints the system",
        "commands instead of running them. It does write the agent skill files",
        "(~/.agents/skills/searchts, or each OpenClaw/Claude Code skills dir that",
        "exists) and the user-scope memory rule; both are listed up front, and",
        "--dry-run lists them and writes nothing. --browser installs the",
        "stealth-browser extra into this interpreter.",
    ),
    examples=(
        "searchts install",
        "searchts install --browser",
        "searchts install --system-deps --channels twitter,reddit",
    ),
    notes=("--safe is a deprecated no-op; non-mutating is now the default.",),
))
_add(Command(
    name="setup", group=_LOGIN, root="setup",
    lead="Walk through search, GitHub, Reddit, and Groq in one pass.",
    body=(
        "Every prompt can be skipped with Enter. The summary says what was",
        "saved and what is still optional; it never installs a system package.",
    ),
    examples=("searchts setup",),
))
_add(Command(
    name="configure", group=_LOGIN, root="configure",
    lead="List the keys, set one, or copy cookies from a browser.",
    body=(
        "With no key it lists every key, its current source and whether it is",
        "set. With a key and a value it writes the key. --from-browser copies",
        "the platform cookies that browser holds.",
    ),
    examples=(
        "searchts configure",
        "searchts configure proxy http://user:pass@ip:port",
        "searchts configure --from-browser firefox",
    ),
))
_add(Command(
    name="login", group=_LOGIN, root="login <verb>",
    lead="Site logins: list, keep, kill, signin, purge-scratch, sweep, check.",
    body=(
        "Nothing is copied out of your browser without --yes. A kept login",
        "stays on this machine: direct requests and a temporary local browser",
        "context can use it; the Jina relay never receives it. A bare",
        "`searchts login` is the same as `searchts login list`.",
    ),
    examples=(
        "searchts login list",
        "searchts login signin https://example.com",
        "searchts login keep https://example.com --cookies-from-browser zen --yes",
    ),
    exit_codes=(
        ("0", "the requested login action finished"),
        ("1", "a cookie copy or sign-in failed"),
        ("2", "bad usage"),
        ("3", "consent is needed for a cookie copy"),
    ),
))
_add(Command(
    name="login list", group=_LOGIN,
    lead="Show kept sites, this session's copies, and leftover scratch.",
    body=(
        "Each kept site shows its live cookie count, whether it came from a",
        "browser or `login signin`, and its expiry (an upper bound, never a",
        "promise). No cookie value is printed.",
    ),
    examples=("searchts login list",),
    exit_codes=(("0", "the audit was printed"), ("2", "bad usage")),
))
_add(Command(
    name="login keep", group=_LOGIN,
    lead="Keep one site's login in the searchts store.",
    body=(
        "Copies only that site's cookies from the named browser, then keeps",
        "them. Copying is never silent: without a recorded yes for the site or",
        "--yes in this run, the command exits 3 and explains what it needs.",
    ),
    examples=(
        "searchts login keep https://example.com --cookies-from-browser zen --yes",
        "searchts login keep https://reddit.com --cookies-from-browser firefox",
    ),
    exit_codes=(
        ("0", "the login was kept"),
        ("1", "the browser copy failed"),
        ("2", "bad usage, or no browser was named"),
        ("3", "consent is needed for the cookie copy"),
    ),
))
_add(Command(
    name="login kill", group=_LOGIN,
    lead="Delete searchts's copy of one site's login.",
    body=(
        "Your own Firefox or Chrome cookies stay untouched unless",
        "--also-browser is passed, because those are yours.",
    ),
    examples=(
        "searchts login kill https://example.com",
        "searchts login kill https://example.com --also-browser",
    ),
    exit_codes=(("0", "searchts's copy was removed"), ("2", "bad usage")),
))
_add(Command(
    name="login signin", group=_LOGIN,
    lead="Sign in once for a site in a browser searchts opens.",
    body=(
        "The browser is searchts's own, not a copy of your profile. Signing in",
        "serves this one read and keeps nothing unless --yes is passed. The",
        "command reports what it observed; only a later read proves the login.",
    ),
    examples=(
        "searchts login signin https://example.com",
        "searchts login signin https://example.com --browser firefox --yes",
    ),
    exit_codes=(
        ("0", "the sign-in browser closed"),
        ("1", "the browser or cookie read failed"),
        ("2", "bad usage"),
    ),
))
_add(Command(
    name="login purge-scratch", group=_LOGIN,
    lead="Delete every scratch copy now.",
    body=(
        "A read deletes its own scratch copy at the end, so this is for",
        "cleaning up after a process that was killed.",
    ),
    examples=("searchts login purge-scratch",),
    exit_codes=(("0", "the scratch copies were deleted"), ("2", "bad usage")),
))
_add(Command(
    name="login sweep", group=_LOGIN,
    lead="Delete expired cookies now, offline.",
    body=(
        "Runs offline: no browser, no network, no daemon. searchts also sweeps",
        "on every command start; schedule this yourself if you want the",
        "receipt in a cron or Task Scheduler entry.",
    ),
    examples=("searchts login sweep",),
    exit_codes=(("0", "the sweep finished"), ("2", "bad usage")),
))
_add(Command(
    name="login check", group=_LOGIN,
    lead="Read one signed-in-only page with the saved cookies.",
    body=(
        "Exit 0 means logged in, 1 logged out, 2 unknown. Expiry is only an",
        "upper bound (a server can end a session early), and this proves no",
        "login wall, not which account is signed in. A captcha or block is",
        "unknown, never a guess. Only direct requests carry the cookies; the",
        "Jina relay never receives them.",
    ),
    examples=(
        "searchts login check reddit.com",
        "searchts login check example.com --url https://example.com/account",
    ),
    exit_codes=(
        ("0", "logged in: the signed-in page was read without a login wall"),
        ("1", "logged out: no live saved cookies, or the site showed its login page"),
        ("2", "unknown: a captcha, block, network error, or no page could be chosen"),
    ),
))
_add(Command(
    name="uninstall", group=_LOGIN, root="uninstall",
    lead="Remove config, tokens and skill files.",
    body=(
        "Without flags it removes the config directory and the skill files.",
        "--keep-config removes only the skill files. --browser removes only",
        "what `install --browser` added.",
    ),
    examples=(
        "searchts uninstall --dry-run",
        "searchts uninstall",
        "searchts uninstall --browser --chromium",
    ),
))

# ── HOUSEKEEPING ──────────────────────────────────────────────────────────
_add(Command(
    name="update", group=_HOUSE, root="update", aliases=("upgrade",),
    lead="Update to the latest release (`upgrade` is the same command).",
    body=(
        "Detects the install shape (pipx, uv tool, editable checkout) and runs",
        "that install's own upgrade command. It does not kill a running",
        "searchts.exe; stop it first on Windows.",
    ),
    examples=(
        "searchts update",
        "searchts update --dry-run",
        "searchts update --force",
    ),
    exit_codes=(
        ("0", "up to date, or the update finished"),
        ("1", "the update failed"),
        ("2", "this install shape cannot be updated"),
    ),
))
_add(Command(
    name="check-update", group=_HOUSE, root="check-update",
    lead="Is there a newer version?",
    body=(
        "One GitHub API call. Since 0.22.0 a newer release is also reported in",
        "`--json` output and in every successful MCP result as",
        "`update_available` (an `Error: ...` result does not carry it), so an",
        "agent does not need a separate call after each task. `search --json`",
        "keeps stdout a bare array, so it prints `{\"update_available\": ...}`",
        "as one JSON line on stderr instead.",
    ),
    examples=("searchts check-update",),
    exit_codes=(("0", "the check finished (newer or current)"), ("2", "bad usage")),
))
_add(Command(
    name="watch", group=_HOUSE, root="watch",
    lead="Quick health check for a scheduled task.",
    body=(
        "Prints one line when everything is normal, a monitoring report when a",
        "channel is broken, and a one-line update note when a newer release",
        "exists. Designed to be run by cron or Task Scheduler.",
    ),
    examples=("searchts watch",),
    exit_codes=(("0", "the check finished"), ("2", "bad usage")),
))
_add(Command(
    name="version", group=_HOUSE, root="version",
    lead="Version.",
    examples=("searchts version",),
    exit_codes=(("0", "the version was printed"), ("2", "bad usage")),
))
_add(Command(
    name="help", group=_HOUSE, root="help",
    lead="The command index, one command, or the machine-readable catalog.",
    body=(
        "`searchts help` is the same document as `searchts --help`.",
        "`searchts help <cmd>` renders that command. `--json` prints the",
        "stable catalog agents and tooling read.",
    ),
    examples=(
        "searchts help",
        "searchts help login check",
        "searchts help --json",
    ),
    exit_codes=(("0", "the help was printed"), ("2", "unknown command path")),
))

ALIASES: Dict[str, str] = {
    alias: command.name
    for command in COMMANDS.values()
    for alias in command.aliases
}


def canonical_name(name: Sequence[str] | str) -> str:
    """``"upgrade"`` -> ``"update"``; a real path is returned as typed."""
    text = " ".join(name) if not isinstance(name, str) else " ".join(name.split())
    return ALIASES.get(text, text)


def meta_for(name: Sequence[str] | str) -> Command | None:
    text = " ".join(name) if not isinstance(name, str) else name
    return COMMANDS.get(canonical_name(text.strip()))


def top_level_leads() -> Dict[str, str]:
    """The lead of every top-level command, for the unknown-command screen."""
    return {
        name: command.lead
        for name, command in COMMANDS.items()
        if " " not in name
    }


def root_groups() -> List[Tuple[str, List[Tuple[str, str]]]]:
    """Root help: (heading, [(label, lead)]) in catalog order."""
    groups: List[Tuple[str, List[Tuple[str, str]]]] = []
    for title in GROUP_ORDER:
        rows = [
            (command.root, command.lead)
            for command in COMMANDS.values()
            if command.root and command.group == title
        ]
        if rows:
            groups.append((title, rows))
    return groups


# ── MCP mapping ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class McpTool:
    tool: str
    command: str
    notes: Tuple[str, ...] = ()
    mcp_only_params: Tuple[str, ...] = ()
    cli_only_flags: Tuple[str, ...] = ()
    mcp_only: bool = False
    #: MCP param -> CLI flag (or positional) where the names differ. A param
    #: whose name is a flag's dest or a positional needs no entry. The help
    #: catalog test checks that every param and every flag is accounted for.
    param_flags: Tuple[Tuple[str, str], ...] = ()


#: Every registered MCP tool -> the CLI command an agent would otherwise run.
MCP_TOOLS: Dict[str, McpTool] = {
    "read_url": McpTool(
        "read_url", "read",
        notes=(
            "Same unlocker path as `searchts read`.",
            "The JSON has no `next_url`: a page-authored URL is not a safe next "
            "request. Use the signed `next_cursor`, or `searchts read --json` "
            "when a human wants the URL.",
            "`approve_cookie_copy` is CLI `--yes` for one call: set it only after "
            "the user said yes to a `cookies_from_browser` copy.",
        ),
        mcp_only_params=("cursor", "page_items"),
        cli_only_flags=("--human", "--scrub", "--backend", "--json"),
        param_flags=(("max_pages", "--pages"), ("max_items", "--items"),
                     ("max_media", "--media"), ("approve_cookie_copy", "--yes")),
    ),
    "web_search": McpTool(
        "web_search", "search",
        notes=(
            "MCP default is max_results=5 (CLI `-n` default is 10).",
            "MCP has no `provider` parameter; the CLI does.",
        ),
        cli_only_flags=("--provider", "--json"),
        param_flags=(("max_results", "-n"),),
    ),
    "fetch_asset": McpTool(
        "fetch_asset", "get",
        notes=(
            "MCP saves only inside the server working directory or "
            "$SEARCHTS_MCP_OUT_DIR, never to an absolute path.",
        ),
        param_flags=(("out_dir", "-o"),),
    ),
    "grab_site": McpTool(
        "grab_site", "grab",
        notes=(
            "`max_assets` mirrors CLI `--max`; `max_tokens` mirrors `--tokens`.",
            "MCP saves only inside the server working directory or "
            "$SEARCHTS_MCP_OUT_DIR.",
        ),
        cli_only_flags=("--kinds", "--scripts", "--json"),
        param_flags=(("out_dir", "--out"), ("max_assets", "--max"),
                     ("max_tokens", "--tokens")),
    ),
    "get_status": McpTool(
        "get_status", "doctor",
        notes=("The same health report `searchts doctor` prints.",),
        cli_only_flags=("--json",),
    ),
    "transcribe": McpTool(
        "transcribe", "transcribe",
        notes=(
            "`prefer_subtitles` mirrors CLI `--no-subtitles`.",
            "`cookies_from_browser` is passed to yt-dlp, same as the CLI flag.",
        ),
        cli_only_flags=("-o",),
        param_flags=(("prefer_subtitles", "--no-subtitles"),),
    ),
    "login_status": McpTool(
        "login_status", "login list",
        notes=("Same audit as `searchts login list`; never a cookie value.",),
    ),
    "login_signin": McpTool(
        "login_signin", "login signin",
        notes=(
            "MCP keeps the login; CLI `login signin` keeps only with `--yes`.",
            "MCP has no terminal: the user closes the window to finish, and the "
            "call waits up to `wait_seconds` (default 180, 30 to 900).",
        ),
        mcp_only_params=("wait_seconds",),
        cli_only_flags=("--yes",),
    ),
    "login_check": McpTool(
        "login_check", "login check",
        notes=(
            "`check_url` mirrors CLI `--url`: a page only a signed-in account sees.",
            "Without it, the known account pages for reddit.com, linkedin.com, "
            "github.com and x.com are used.",
        ),
        param_flags=(("url", "site"), ("check_url", "--url")),
    ),
    "login_kill": McpTool(
        "login_kill", "login kill",
        notes=("`also_browser` mirrors CLI `--also-browser`.",),
    ),
}

MCP_ONLY_TOOLS: Dict[str, str] = {}


def mcp_tool_names() -> Tuple[str, ...]:
    return tuple(MCP_TOOLS)


#: Commands with no tool, and why that is on purpose (gap #33).
CLI_ONLY: Dict[str, str] = {
    "install": "installing software is the user's act; the MCP server reports readiness instead",
    "setup": "an interactive wizard needs a person at the terminal",
    "configure": "keys are the user's; MCP reads only what is already configured",
    "uninstall": "removing software is the user's act",
    "skill install": "writes files on this machine for the host's slash command",
    "skill": "parent verb for `skill install`",
    "mcp": "parent verb for `mcp serve` / `mcp install`",
    "mcp serve": "this is the server itself; a tool for it would be the server",
    "mcp install": "writes client configs; the host does this once",
    "login": "parent verb for the login tools and the CLI-only login verbs",
    "login keep": "MCP reaches the same login through `login_signin` or `read_url` + `cookies_from_browser`",
    "login purge-scratch": "scratch copies are deleted at the end of every read",
    "login sweep": "expired cookies are swept on every MCP result; a tool would duplicate it",
    "update": "installing software is the user's act; MCP reports `update_available` instead",
    "check-update": "MCP results already carry `update_available`; the CLI verb is for scripts",
    "watch": "a scheduled shell check, not an agent tool",
    "version": "`get_status` carries the version",
    "help": "the MCP tool list is the machine-readable surface",
}


def mcp_record(name: str) -> dict:
    canonical = canonical_name(name)
    tools = [t for t in MCP_TOOLS.values() if t.command == canonical]
    if tools:
        return {
            "tools": [t.tool for t in tools],
            "notes": [n for t in tools for n in t.notes],
            "mcp_only_params": [p for t in tools for p in t.mcp_only_params],
            "cli_only_flags": [f for t in tools for f in t.cli_only_flags],
            "param_flags": {p: f for t in tools for p, f in t.param_flags},
            "cli_only": False,
            "reason": "",
        }
    reason = CLI_ONLY.get(canonical, "")
    return {
        "tools": [],
        "notes": [],
        "mcp_only_params": [],
        "cli_only_flags": [],
        "param_flags": {},
        "cli_only": bool(reason),
        "reason": reason or "not part of the MCP tool surface",
    }


# ── parser walking + JSON ─────────────────────────────────────────────────


def _subparsers(parser: argparse.ArgumentParser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def walk_parsers(
    parser: argparse.ArgumentParser,
    prefix: Tuple[str, ...] = (),
) -> Iterator[Tuple[Tuple[str, ...], argparse.ArgumentParser]]:
    """Yield every command path and its parser, root included as ``()``."""
    yield prefix, parser
    action = _subparsers(parser)
    if action is None:
        return
    seen = set()
    for name, child in action.choices.items():
        if id(child) in seen:
            continue
        seen.add(id(child))
        yield from walk_parsers(child, (*prefix, name))


def child_aliases(parser: argparse.ArgumentParser) -> Dict[str, Tuple[str, ...]]:
    """Canonical child name -> its aliases, from the live subparser action."""
    action = _subparsers(parser)
    if action is None:
        return {}
    by_id: Dict[int, str] = {}
    aliases: Dict[str, List[str]] = {}
    for name, child in action.choices.items():
        key = id(child)
        if key not in by_id:
            by_id[key] = name
            aliases[name] = []
        elif name != by_id[key]:
            aliases[by_id[key]].append(name)
    return {name: tuple(extra) for name, extra in aliases.items()}


def action_help(action: argparse.Action) -> str:
    text = (action.help or "").strip()
    if not text or text == argparse.SUPPRESS:
        return ""
    return " ".join(text.split())


def metavar(action: argparse.Action, *, lower: bool = False) -> str:
    """The value name argparse would show, with optional positionals bracketed.

    ``nargs="?"`` wins over ``choices`` so `configure [key]` reads as optional
    instead of collapsing into the required-looking `<key>` (gap #12).
    """
    base = action.metavar
    if base is not None:
        base = str(base)
    elif action.choices:
        base = "{" + ",".join(str(c) for c in action.choices) + "}"
    else:
        base = action.dest.upper()
    if lower:
        base = base.lower()
    if action.nargs == "?":
        return f"[{base}]"
    if action.nargs in ("*", "+"):
        return f"[{base}...]"
    return base


def flag_name(action: argparse.Action) -> str:
    for option in action.option_strings:
        if option.startswith("--"):
            return option
    return action.option_strings[0] if action.option_strings else ""


def usage_tokens(
    parser: argparse.ArgumentParser, path: Sequence[str]
) -> List[str]:
    """Positionals and verbs first, flags last, in the order a shell wants."""
    parts = ["searchts", *path]
    flags: List[str] = []
    seen = set()
    for action in parser._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        if isinstance(action, argparse._SubParsersAction):
            # Every verb, not the first four (gap #1). The usage line is
            # allowed to wrap; hiding three verbs is worse than a second line.
            names = "|".join(list(action.choices))
            parts.append(f"{{{names}}}")
            continue
        if not action.option_strings:
            shown = metavar(action, lower=True)
            if len(shown) > 24:
                shown = f"[{action.dest}]" if action.nargs == "?" else action.dest
            parts.append(shown if shown[:1] in ("[", "(") else f"<{shown}>")
            continue
        if action.dest in seen:
            continue
        seen.add(action.dest)
        flag = flag_name(action)
        if action.nargs == 0:
            flags.append(f"[{flag}]")
        else:
            shown = metavar(action)
            if not action.choices and len(shown) > 30:
                shown = action.dest.upper()
            flags.append(f"[{flag} {shown}]")
    return parts + flags


def parser_for(
    parser: argparse.ArgumentParser, path: Sequence[str]
) -> argparse.ArgumentParser | None:
    """The subparser for ``path`` under ``parser``, or None."""
    return dict(walk_parsers(parser)).get(tuple(path))


def usage_text(parser: argparse.ArgumentParser, path: Sequence[str]) -> str:
    """Usage for ``path``; accepts either the root parser or its subparser."""
    target = parser_for(parser, path) or parser
    return " ".join(usage_tokens(target, path))


def synopsis(command: "Command", parser: argparse.ArgumentParser) -> str:
    """``searchts login check <site>``: name plus its positional arguments."""
    bits = ["searchts", *command.path]
    for action in parser._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        if isinstance(action, argparse._SubParsersAction) or action.option_strings:
            continue
        shown = metavar(action, lower=True)
        if len(shown) > 24:
            shown = f"[{action.dest}]" if action.nargs == "?" else action.dest
        bits.append(shown if shown[:1] in ("[", "(") else f"<{shown}>")
    return " ".join(bits)


FLAG_MARKERS: Dict[Tuple[str, str], str] = {
    ("install", "--safe"): "deprecated",
    ("skill", "--install"): "legacy",
    ("skill", "--uninstall"): "legacy",
}


def _flag_record(name: str, action: argparse.Action) -> dict:
    marker = ""
    for flag in action.option_strings:
        marker = FLAG_MARKERS.get((name, flag), marker)
    if not marker and action_help(action).lower().startswith("deprecated"):
        marker = "deprecated"
    default = action.default
    if default is argparse.SUPPRESS:
        default = None
    try:
        import json

        json.dumps(default)
    except (TypeError, ValueError):
        default = str(default)
    return {
        "option_strings": list(action.option_strings),
        "dest": action.dest,
        "metavar": metavar(action) if action.nargs != 0 else "",
        "choices": [str(c) for c in action.choices] if action.choices else [],
        "default": default,
        "help": action_help(action),
        "required": bool(action.required),
        "deprecated": marker == "deprecated",
        "legacy": marker == "legacy",
    }


def _positional_record(action: argparse.Action) -> dict:
    return {
        "name": action.dest,
        "metavar": metavar(action, lower=True),
        "nargs": action.nargs if isinstance(action.nargs, str) else "",
        "choices": [str(c) for c in action.choices] if action.choices else [],
        "help": action_help(action),
    }


def _global_flags(parser: argparse.ArgumentParser) -> List[dict]:
    return [
        _flag_record("", action)
        for action in parser._actions
        if action.option_strings and not isinstance(action, argparse._HelpAction)
    ]


def _command_record(
    parser: argparse.ArgumentParser,
    path: Tuple[str, ...],
    aliases: Tuple[str, ...],
) -> dict:
    name = " ".join(path)
    meta = meta_for(name)
    command = meta or Command(
        name=name,
        group="",
        lead="",
        examples=(),
        exit_codes=(),
    )
    flags = [
        _flag_record(canonical_name(name), action)
        for action in parser._actions
        if action.option_strings and not isinstance(action, argparse._HelpAction)
    ]
    positionals = [
        _positional_record(action)
        for action in parser._actions
        if not action.option_strings
        and not isinstance(action, argparse._HelpAction)
        and not isinstance(action, argparse._SubParsersAction)
    ]
    return {
        "name": name,
        "aliases": list(aliases),
        "group": command.group,
        "description": command.lead,
        "body": list(command.body),
        "notes": list(command.notes),
        "usage": usage_text(parser, path),
        "positionals": positionals,
        "flags": flags,
        "examples": list(command.examples),
        "exit_codes": [
            {"code": code, "meaning": meaning}
            for code, meaning in command.exit_codes
        ],
        "deprecated": command.deprecated,
        "legacy": command.legacy,
        "mcp": mcp_record(name),
        "subcommands": [
            name + " " + child
            for child in child_aliases(parser)
        ] if _subparsers(parser) is not None else [],
    }


def build_catalog(parser: argparse.ArgumentParser, version: str) -> dict:
    """Walk the live parser and merge it with :data:`COMMANDS`."""
    parsers = dict(walk_parsers(parser))
    records = []
    for path, child in parsers.items():
        if not path:
            continue
        parent = parsers[path[:-1]]
        aliases = child_aliases(parent).get(path[-1], ())
        records.append(_command_record(child, path, aliases))
    return {
        "schema": SCHEMA,
        "prog": parser.prog,
        "version": version,
        "global_flags": _global_flags(parser),
        "commands": records,
    }


def find_command(catalog: dict, path: Sequence[str]) -> dict | None:
    name = canonical_name(path)
    for record in catalog["commands"]:
        if record["name"] == name:
            return record
    return None


# ── the guard ─────────────────────────────────────────────────────────────


def validate(parser: argparse.ArgumentParser, version: str) -> List[str]:
    """Every problem the CI guard turns into a failing test, with a fix hint."""
    problems: List[str] = []
    catalog = build_catalog(parser, version)
    known = {record["name"] for record in catalog["commands"]}
    for path, child in walk_parsers(parser):
        name = " ".join(path)
        label = name or "root"
        if not path:
            continue
        record = find_command(catalog, path)
        if record is None or not record["description"]:
            problems.append(
                f"{label}: no description in searchts/catalog.py; add a "
                f"Command(name={label!r}, lead=..., examples=...)."
            )
        if record is not None and not record["examples"]:
            problems.append(
                f"{label}: no example in searchts/catalog.py; add at least one "
                f"to its Command entry."
            )
        if record is not None and not record["exit_codes"]:
            problems.append(
                f"{label}: no exit codes in searchts/catalog.py; add them to "
                f"its Command entry."
            )
        for action in child._actions:
            if isinstance(action, argparse._HelpAction):
                continue
            if isinstance(action, argparse._SubParsersAction):
                continue
            if action.option_strings and not action_help(action):
                problems.append(
                    f"{label}: flag {action.option_strings[0]} has no help text; "
                    f"add help=... in searchts/cli.py."
                )
    for action in parser._actions:
        if (action.option_strings and not isinstance(action, argparse._HelpAction)
                and not action_help(action)):
            problems.append(
                f"root: flag {action.option_strings[0]} has no help text; "
                f"add help=... in searchts/cli.py."
            )
    # Every MCP tool maps to a real command, and every command says either
    # mapped or CLI-only (gaps #30 and #33).
    for tool_name, tool in MCP_TOOLS.items():
        if tool.command not in known:
            problems.append(
                f"MCP tool {tool_name}: maps to unknown command {tool.command!r}; "
                f"fix MCP_TOOLS in searchts/catalog.py."
            )
    for name in known:
        record = find_command(catalog, name)
        assert record is not None
        if not record["mcp"]["tools"] and not record["mcp"]["cli_only"]:
            problems.append(
                f"{name}: not mapped to an MCP tool and not marked CLI-only; "
                f"add it to MCP_TOOLS or CLI_ONLY in searchts/catalog.py."
            )
    return problems


#: Commands a hand-written surface may name even though they do not exist.
NEGATIVE_MENTIONS = frozenset({"search-twitter"})


def surface_problems(root) -> List[str]:
    """`searchts <cmd>` mentions in agent-facing files that name no command.

    Only a backticked command, a fenced/indented shell line, or a line that
    starts with ``searchts`` counts. Prose such as "searchts is keyless" is a
    sentence, not a command, and must not fail the guard.
    """
    import re
    from pathlib import Path

    root = Path(root)
    files = [
        root / "llms.txt",
        root / "README.md",
        root / "docs" / "mcp.md",
        root / "docs" / "cli.md",
        root / "docs" / "troubleshooting.md",
        root / "searchts" / "skill" / "SKILL.md",
        root / "searchts" / "skill" / "SKILL_en.md",
    ]
    files.extend(sorted((root / "searchts" / "skill" / "references").glob("*.md")))
    names = {name.split()[0] for name in COMMANDS} | set(ALIASES) | set(NEGATIVE_MENTIONS)
    problems = []
    command = re.compile(r"searchts ([a-z][a-z0-9-]+)")
    span = re.compile(r"`([^`\n]+)`")
    for path in files:
        if not path.exists():
            continue
        in_fence = False
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            mentions = []
            for code in span.findall(line):
                mentions.extend(command.findall(code))
            stripped = line.strip()
            if stripped.startswith("$ "):
                stripped = stripped[2:]
            if in_fence and stripped.startswith("searchts "):
                mentions.extend(command.findall(stripped)[:1])
            for token in mentions:
                if token not in names:
                    problems.append(
                        f"{path.relative_to(root)}:{line_no}: `searchts {token}` "
                        f"is not a command. Fix the surface, or add the token to "
                        f"catalog.NEGATIVE_MENTIONS when it is a deliberate "
                        f"negative mention."
                    )
    return problems
