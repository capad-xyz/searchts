# -*- coding: utf-8 -*-
"""The help screen, drawn as a document rather than a dump.

argparse's generated help is a complete and accurate list of flags, and it is
the wrong first thing to see. It opens with ``positional arguments:`` and
sixteen equal-weight commands, which says nothing about which two of them are
the product. A tool whose whole pitch is "point your agent at this" cannot
open with a wall of syntax.

So the root screen is written by hand: the belief, then the commands a person
actually needs, then examples, then the exit codes. Everything below the root
is generated from the *live* argparse parsers, so it cannot drift, with the
prose around it hand-written per command.

Nothing here is read by an agent. Agents get ``SKILL.md`` and the MCP tool
schemas, which is why this file is allowed to be pretty.

Design rules, kept deliberately small:

  - 78 columns. Wider wraps on a default Windows terminal, and a help screen
    that wraps is a help screen that is harder to skim than the one argprited.
  - Two columns: the command and a single sentence. No second paragraph.
  - Colour only on a terminal, OSC 8 links only on a terminal, ``NO_COLOR``
    honoured. Piped output is plain text that still reads.
  - Every rule is drawn at the same width so the eye can find sections.
"""

from __future__ import annotations

import argparse
from typing import Dict, List, Sequence, Tuple

from searchts.progress import Style, human_time, link_url, use_color, use_links  # noqa: F401

WIDTH = 78
LABEL = 22
COLUMN = 24

#: Root groups: (heading, [(command, one line)]).
#: Order is the order of the job, not the alphabet: read and search first,
#: because the other twelve exist to support them.
ROOT_GROUPS: List[Tuple[str, List[Tuple[str, str]]]] = [
    ("READ THE WEB", [
        ("read <url>", "Fetch a page as markdown, or fail and say why"),
        ("search \"<query>\"", "Find URLs to read. A snippet is not the page"),
        ("transcribe <url>", "A player page's words: captions, then Whisper"),
        ("grab <url>", "Save the files a page uses: images, css, fonts"),
        ("get <url>", "One file through the same unlocker"),
    ]),
    ("WIRE UP AN AGENT", [
        ("mcp serve", "Run the MCP server (stdio; --http for loopback)"),
        ("mcp install", "Wire the MCP server into the agents on this machine"),
        ("skill install", "Slash command plus the shared SKILL.md"),
        ("doctor", "Which channels are installed, configured, working"),
    ]),
    ("SET UP ONCE", [
        ("install", "One-shot installer; --system-deps to change things"),
        ("setup", "Interactive wizard"),
        ("configure", "List the keys, set one, or copy cookies from a browser"),
        ("login <verb>", "Site logins searchts keeps, and what it copied"),
        ("uninstall", "Remove config, tokens and skill files"),
    ]),
    ("HOUSEKEEPING", [
        ("upgrade", "Update to the latest release"),
        ("check-update", "Is there a newer version?"),
        ("watch", "Quick health check for a scheduled task"),
        ("version", "Version"),
    ]),
]

BELIEF = [
    "The missing layer between AI and the web.",
    "",
    "It reads the page, or it says it can't.",
]

BELIEF_BODY = [
    "No API key. No hosted URL. No proxy pool. One command over three escalating",
    "rungs: a browser-fingerprinted fetch, then a JS-render relay, then a real",
    "stealth browser. When all three fail you get every reason, named, and a",
    "non-zero exit. A thin page is a failure, not a result.",
]

EXAMPLES = [
    ("searchts read stripe.com", ""),
    ("searchts read https://x.com/jack/status/20 --json", ""),
    ("searchts search \"rust async runtime\" -n 5", ""),
    ("searchts grab https://stripe.com --out stripe", ""),
]

EXIT_CODES = [
    ("0", "content returned"),
    ("1", "every rung failed; the reasons are on stderr"),
    ("2", "bad usage, or a URL that cannot be read"),
]

#: Per-command prose. The flags themselves come from argparse; only the words
#: around them live here, and a command without an entry still renders.
COMMANDS: Dict[str, dict] = {
    "read": {
        "lead": "Fetch a page and print clean markdown.",
        "body": [
            "Climbs the same three rungs the MCP server uses: curl_cffi with a",
            "browser TLS fingerprint, then the Jina reader relay, then a stealth",
            "browser. It stops at the first rung that returns real text. A wall,",
            "a login page, or a client-rendered shell is a failure, not a page.",
        ],
        "examples": [
            "searchts read example.com",
            "searchts read https://x.com/jack/status/20 --json",
            "searchts read example.com --pages 3 --expand",
        ],
        "see": ["transcribe (a video with no captions)", "grab (the files it names)"],
        "tip": "--pages 3 follows the next page on the same site; "
               "--expand opens closed <details>.",
    },
    "search": {
        "lead": "Find URLs to read, across several providers at once.",
        "body": [
            "Results are fused by rank across every provider that answers, so one",
            "provider having a bad day does not empty the list. A snippet is a",
            "pointer, not a page: read the URL before quoting it.",
        ],
        "examples": [
            "searchts search \"python asyncio timeout\"",
            "searchts search \"stripe pricing\" --provider duckduckgo -n 5",
            "searchts search \"rust 2026\" --json",
        ],
        "tip": "-n 5 is usually enough; read the URL before quoting a snippet.",
    },
    "transcribe": {
        "lead": "Read the audio when a player page has no captions.",
        "body": [
            "Captions come first and cost nothing. Audio goes to Groq, then OpenAI",
            "if a key is set, else the keyless local Whisper. A local file works",
            "the same way.",
        ],
        "examples": [
            "searchts transcribe https://www.youtube.com/watch?v=...",
            "searchts transcribe talk.mp4 --provider local",
        ],
    },
    "grab": {
        "lead": "Save the files a read named.",
        "body": [
            "Downloads images, icons, css, fonts and inline svg through the same",
            "unlocker, then extracts the palette, the fonts and the radius/shadow/",
            "spacing values the page actually uses. Every URL is either saved,",
            "named as a failure, or listed as omitted with the reason, so a cap",
            "never truncates silently.",
        ],
        "examples": [
            "searchts grab https://stripe.com --out stripe",
            "searchts grab https://linear.app --kinds images,fonts",
        ],
        "tip": "--tokens N (max 200) reads more radius, shadow and spacing "
               "values; the manifest names what each cap left out.",
    },
    "get": {
        "lead": "Download one file through the unlocker.",
        "body": ["Prints the saved path on stdout, so it pipes into anything."],
        "examples": ["searchts get https://example.com/logo.svg -o assets/"],
    },
    "mcp": {
        "lead": "Run the MCP server, or print the wiring for an agent client.",
        "body": [
            "stdio by default. --http and --sse bind loopback only: there is no",
            "public URL, and that is on purpose.",
        ],
        "examples": ["searchts mcp serve", "searchts mcp install --client claude"],
        "tip": "--http and --sse bind loopback only; there is no public URL, "
               "and that is on purpose.",
    },
    "doctor": {
        "lead": "Which channels are installed, configured, and working.",
        "body": [
            "Probes each optional channel. A tier-0 probe is a capability the",
            "reader can use; the CLIs are PATH checks, not a routing table.",
        ],
        "examples": ["searchts doctor", "searchts doctor --json"],
    },
    "login": {
        "lead": "Site logins searchts keeps, and what it copied this session.",
        "body": [
            "Nothing is copied out of your browser without --yes. A kept login",
            "rides the direct request only; the browser rung is sent none of it.",
        ],
        "examples": [
            "searchts login list",
            "searchts login signin https://example.com",
            "searchts login kill example.com",
        ],
    },
    "install": {
        "lead": "One-shot installer.",
        "body": ["Non-mutating by default: without --system-deps it prints commands."],
        "examples": ["searchts install", "searchts install --browser"],
    },
    "uninstall": {
        "lead": "Remove searchts config, tokens and skill files.",
        "examples": ["searchts uninstall --dry-run", "searchts uninstall"],
    },
    "configure": {
        "lead": "List every key, set one value, or copy cookies from a browser.",
        "examples": [
            "searchts configure",
            "searchts configure --from-browser firefox",
        ],
    },
    "watch": {
        "lead": "Quick health check plus update check, for a scheduled task.",
        "examples": ["searchts watch"],
    },
    "setup": {
        "lead": "Walk through search, GitHub, Reddit, and Groq in one pass.",
        "body": [
            "Every prompt can be skipped with Enter. The summary says what was",
            "saved and what is still optional; it never installs a system package.",
        ],
        "examples": ["searchts setup"],
    },
    "skill": {
        "lead": "Write the Claude Code slash-command, or register the full skill bundle.",
        "examples": [
            "searchts skill install",
            "searchts skill install --dir ~/.claude/commands",
            "searchts skill --install",
        ],
    },
    "version": {
        "lead": "Print the installed version, one line on stdout.",
        "examples": ["searchts version"],
    },
    "update": {
        "lead": "Update this install to the latest release.",
        "examples": ["searchts update", "searchts update --dry-run"],
    },
    "upgrade": {
        "lead": "Update this install to the latest release.",
        "examples": ["searchts upgrade"],
    },
    "check-update": {
        "lead": "Check for a newer version and what changed.",
        "examples": ["searchts check-update"],
    },
}

#: Which options belong under which heading, in reading order, per command.
#: Anything not listed lands in OPTIONS automatically, so a new flag can never
#: be silently missing from `--help`.
OPTION_GROUPS: Dict[str, List[Tuple[str, List[str]]]] = {
    "read": [
        ("WHAT TO FETCH", ["--backend", "--pages", "--items", "--media",
                           "--expand", "--scrub"]),
        ("OUTPUT", ["--json", "--human"]),
        ("SITE ACCESS", ["--cookies-from-browser", "--yes", "--cookies",
                          "--cdp-port"]),
        ("NETWORK", ["--proxy", "--proxy-trusted"]),
        ("ALSO", ["--verbose"]),
    ],
    "search": [
        ("RESULTS", ["-n", "--provider"]),
        ("OUTPUT", ["--json"]),
        ("ALSO", ["--verbose"]),
    ],
    "grab": [
        ("WHAT TO SAVE", ["--kinds", "--max", "--tokens", "--scripts", "--read"]),
        ("WHERE", ["--out"]),
        ("OUTPUT", ["--json"]),
        ("ALSO", ["--verbose"]),
    ],
    "get": [("WHERE", ["-o", "--output"]), ("ALSO", ["--verbose"])],
    "transcribe": [
        ("HOW", ["--provider", "--no-subtitles"]),
        ("OUTPUT", ["-o", "--output"]),
        ("SITE ACCESS", ["--cookies-from-browser"]),
        ("ALSO", ["--verbose"]),
    ],
    "doctor": [("OUTPUT", ["--json"]), ("ALSO", ["--verbose"])],
    "mcp": [("SERVE", ["--http", "--sse", "--host", "--port"]),
            ("INSTALL", ["--client"]), ("ALSO", ["--verbose"])],
}

FOOTER_LINKS = [
    ("Docs", "https://github.com/capad-xyz/searchts#readme"),
    ("Cases", "https://capad.fyi/work/searchts"),
    ("Issues", "https://github.com/capad-xyz/searchts/issues"),
]


class Doc:
    """A tiny line writer: fixed width, styled, truncating rather than wrapping."""

    def __init__(self, width: int = WIDTH):
        self.width = width
        self.s = Style(use_color())
        self.links = use_links()
        self.lines: List[str] = []

    def blank(self) -> None:
        self.lines.append("")

    def rule(self, indent: int = 2) -> None:
        glyph = "─" if _unicode() else "-"
        self.lines.append(" " * indent + self.s.dim(glyph * (self.width - indent * 2)))

    def heading(self, text: str) -> None:
        self.blank()
        self.lines.append("  " + self.s.dim(text.upper()))

    def pair(self, left: str, right: str, *, label: int = LABEL,
             left_style=None, right_style=None) -> None:
        """One row of a two-column table.

        The right side wraps onto the same indent rather than truncating. A
        command described as "fetch a page as clean markdown, or fail..." tells
        nobody how the sentence ends, and the ends of these sentences are the
        whole point of them.
        """
        left_style = left_style or (lambda x: x)
        right_style = right_style or (lambda x: x)
        if len(left) > label - 1:
            ell = "…" if _unicode() else ""
            left = left[: label - 1 - len(ell)] + ell
        room = max(16, self.width - 4 - label - 2)
        chunks = _wrap(right, room) or [""]
        pad = " " * max(0, label - len(left))
        self.lines.append("  " + left_style(left) + pad + "  "
                          + right_style(chunks[0]))
        for chunk in chunks[1:]:
            self.lines.append(" " * (2 + label + 2) + right_style(chunk))

    def para(self, text: str, indent: int = 2, style=None, width: int = 74) -> None:
        style = style or (lambda x: x)
        for line in _wrap(text, width):
            self.lines.append(" " * indent + style(line))

    def example(self, cmd: str) -> None:
        self.lines.append("    " + self.s.dim("$ ") + cmd)

    def text(self) -> str:
        return "\n".join(self.lines).rstrip() + "\n"

    def out(self) -> None:
        import sys

        sys.stdout.write(self.text())
        sys.stdout.flush()


def _unicode() -> bool:
    from searchts.progress import supports_unicode

    return supports_unicode()


def _wrap(text: str, width: int) -> List[str]:
    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        # A URL or a single long token cannot wrap at a space, so cut it. The
        # alternative is a line the terminal folds wherever it likes, which
        # breaks the column it was drawn in.
        while len(word) > max(8, width):
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:width])
            word = word[width:]
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


# ── root ───────────────────────────────────────────────────────────────────


def render_root(version: str) -> None:
    d = Doc()
    s = d.s
    d.lines.append("")
    d.lines.append("  " + s.bold("searchts") + "  " + s.dim(f"v{version}"))
    d.blank()
    for i, line in enumerate(BELIEF):
        if not line:
            d.blank()
        elif i == 0:
            d.lines.append("  " + s.cyan(line))
        else:
            d.lines.append("  " + s.bold(line))
    d.blank()
    for line in BELIEF_BODY:
        d.lines.append("  " + s.dim(line))

    for title, rows in ROOT_GROUPS:
        d.heading(title)
        for cmd, desc in rows:
            d.pair(cmd, desc, left_style=s.cyan)

    d.heading("EXAMPLES")
    for cmd, _ in EXAMPLES:
        d.example(cmd)

    d.heading("EXIT CODES")
    for code, meaning in EXIT_CODES:
        d.pair(code, meaning, label=6, left_style=s.dim)

    d.blank()
    d.rule()
    d.blank()
    d.lines.append("  " + s.dim("Run ") + "searchts <command> --help"
                   + s.dim(" for one command, its flags and examples."))
    d.blank()
    for name, url in FOOTER_LINKS:
        label = (name + " " * 8)[:8]
        d.lines.append("  " + s.dim(label) + link_url(_short_url(url), d.links))
    d.lines.append("")
    d.out()


def _short_url(url: str) -> str:
    """The URL without its scheme, which is the part a reader never needs."""
    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            return url[len(prefix):]
    return url


# ── one command ────────────────────────────────────────────────────────────


def _action_help(action: argparse.Action) -> str:
    text = (action.help or "").strip()
    if not text or text == argparse.SUPPRESS:
        return ""
    return " ".join(text.split())


def _metavar(action: argparse.Action) -> str:
    if action.metavar:
        return str(action.metavar)
    if action.choices:
        return "{" + ",".join(str(c) for c in action.choices) + "}"
    if action.nargs in ("?", "*", "+"):
        return f"[{action.dest}]" if action.nargs == "?" else f"[{action.dest}...]"
    return action.dest.upper()


def _flag_name(action: argparse.Action) -> str:
    """The name to show for a flag: the long form when there is one.

    ``-v`` is shorter to type and worse to read in a table; ``--verbose`` says
    what it does. A flag with only a short form (``-n``) keeps it.
    """
    for option in action.option_strings:
        if option.startswith("--"):
            return option
    return action.option_strings[0] if action.option_strings else ""


def _usage_tokens(parser: argparse.ArgumentParser, path: Sequence[str]) -> List[str]:
    parts = ["searchts", *path]
    seen = set()
    for action in parser._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        if isinstance(action, argparse._SubParsersAction):
            names = "|".join(list(action.choices)[:4])
            parts.append(f"{{{names}}}")
            seen.add("sub")
            continue
        if not action.option_strings:
            shown = _metavar(action).lower()
            if len(shown) > 20:
                # A seven-way choice list is a table, not a usage line.
                shown = action.dest
            # nargs="*" and "?" already come back bracketed.
            parts.append(shown if shown[:1] in ("[", "(") else f"<{shown}>")
            continue
        if action.dest in seen:
            continue
        seen.add(action.dest)
        flag = _flag_name(action)
        if action.nargs == 0:
            parts.append(f"[{flag}]")
        else:
            shown = _metavar(action)
            if len(shown) > 18:
                shown = action.dest.upper()
            parts.append(f"[{flag} {shown}]")
    return parts


def render_command(parser: argparse.ArgumentParser, path: Sequence[str],
                   version: str) -> None:
    d = Doc()
    s = d.s
    key = path[0] if path else ""
    meta = COMMANDS.get(key, {})

    d.lines.append("")
    d.lines.append("  " + s.bold("searchts") + " " + s.cyan(" ".join(path))
                   + "  " + s.dim(f"v{version}"))
    d.blank()
    lead = meta.get("lead") or (parser.description or "")
    if lead:
        d.lines.append("  " + lead)
    for line in meta.get("body", []):
        d.lines.append("  " + s.dim(line))

    d.heading("USAGE")
    usage_lines = _usage_lines(_usage_tokens(parser, path))
    head = "searchts " + " ".join(path)
    for i, line in enumerate(usage_lines):
        if i == 0 and line.startswith(head):
            d.lines.append("    " + s.cyan(head) + s.dim(line[len(head):]))
        else:
            d.lines.append("    " + line)

    # Positionals first: a flag table that never explains <url> leaves the
    # reader guessing what the command actually takes.
    positionals = [a for a in parser._actions
                   if not a.option_strings and not isinstance(a, argparse._HelpAction)
                   and _action_help(a)]
    if positionals:
        d.heading("ARGUMENTS")
        d.blank()
        for action in positionals:
            shown = _metavar(action).lower()
            if len(shown) > 20:
                shown = action.dest
            _option_rows(d, action, shown if shown[:1] in ("[", "(") else f"<{shown}>",
                         with_metavar=False)

    # Options, grouped. Anything the group table does not name is appended to
    # `ALSO`, so adding a flag can never make it invisible in --help.
    by_flag = {}
    for action in parser._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        for flag in action.option_strings:
            by_flag[flag] = action
    groups = OPTION_GROUPS.get(key)
    if groups:
        rows: List[Tuple[str, List[argparse.Action]]] = []
        named = set()
        for title, flags in groups:
            present = []
            for flag in flags:
                found = by_flag.get(flag)
                if found is not None and id(found) not in named:
                    named.add(id(found))
                    present.append(found)
            if present:
                rows.append((title, present))
        leftover = [a for a in parser._actions
                    if a.option_strings and not isinstance(a, argparse._HelpAction)
                    and id(a) not in named]
        if leftover:
            # Fold into a trailing ALSO rather than printing a second heading
            # with the same name.
            if rows and rows[-1][0] == "ALSO":
                rows[-1][1].extend(leftover)
            else:
                rows.append(("ALSO", leftover))
        d.heading("FLAGS")
        d.blank()
        for i, (title, actions) in enumerate(rows):
            if i:
                d.blank()
            d.lines.append("  " + s.dim(title))
            for action in actions:
                _option_rows(d, action, _flag_name(action))
    else:
        d.heading("FLAGS")
        for action in parser._actions:
            if isinstance(action, argparse._HelpAction) or not action.option_strings:
                continue
            _option_rows(d, action, _flag_name(action))

    examples = meta.get("examples") or []
    if examples:
        d.heading("EXAMPLES")
        for cmd in examples:
            d.example(cmd)

    see = meta.get("see") or []
    if see:
        d.heading("SEE ALSO")
        for item in see:
            d.lines.append("  " + item)

    tip = meta.get("tip")
    if tip:
        d.blank()
        lead_tip = "[CONFIG] Tip: "
        chunks = _wrap(tip, WIDTH - 4 - len(lead_tip))
        d.lines.append("  " + s.cyan("[CONFIG]") + s.dim(" Tip: ") + chunks[0])
        for chunk in chunks[1:]:
            d.lines.append(" " * (2 + len(lead_tip)) + chunk)

    d.blank()
    d.rule()
    d.blank()
    sep = " · " if _unicode() else " | "
    d.lines.append(
        "  " + s.dim(f"Exit codes: 0 content{sep}1 every rung failed{sep}2 bad usage")
    )
    d.lines.append("")
    d.out()


def _usage_lines(tokens: Sequence[str]) -> List[str]:
    """Pack the usage into lines that never split a ``[flag VALUE]`` group.

    A usage line broken as ``[--pages`` / ``PAGES]`` reads as two flags. Each
    bracketed group is one token here, so the break always lands between them.
    """
    lines: List[str] = []
    current = ""
    for token in tokens:
        if not current:
            current = token
        elif len(current) + 1 + len(token) <= WIDTH - 4:
            current += " " + token
        else:
            lines.append(current)
            current = "    " + token
    if current:
        lines.append(current)
    return lines


def _option_rows(d: Doc, action: argparse.Action, flag: str,
                 with_metavar: bool = True) -> None:
    s = d.s
    label = flag
    if with_metavar and action.nargs != 0:
        shown = _metavar(action)
        if len(shown) > 14:
            shown = action.dest.upper()
        label = f"{flag} {shown}"
    help_text = _action_help(action)
    if not help_text:
        return
    if len(label) > COLUMN - 2:
        # A long flag (--cookies-from-browser BROWSER) does not fit the column.
        # Never cut it: the flag name is the thing someone came here to copy.
        d.lines.append("  " + s.cyan(label))
        d.para(help_text, indent=COLUMN + 4, style=s.dim,
               width=d.width - COLUMN - 6)
        return
    d.pair(label, help_text, label=COLUMN, left_style=s.cyan, right_style=s.dim)


# ── dispatch ───────────────────────────────────────────────────────────────


def wants_help(argv: Sequence[str]) -> bool:
    return any(token in ("-h", "--help") for token in argv)


def find_subparser(parser: argparse.ArgumentParser,
                   argv: Sequence[str]) -> Tuple[List[str], argparse.ArgumentParser]:
    """Walk to the deepest subparser the argv names."""
    path: List[str] = []
    current = parser
    for token in argv:
        if token.startswith("-"):
            continue
        subs = [a for a in current._actions
                if isinstance(a, argparse._SubParsersAction)]
        if not subs:
            break
        choices = subs[0].choices
        if token in choices:
            path.append(token)
            current = choices[token]
        else:
            break
    return path, current


def render(parser: argparse.ArgumentParser, argv: Sequence[str],
           version: str) -> None:
    path, target = find_subparser(parser, argv)
    if not path:
        render_root(version)
    else:
        render_command(target, path, version)
