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

from searchts import catalog
from searchts.progress import Style, human_time, link_url, use_color, use_links  # noqa: F401

WIDTH = 78
LABEL = 22
COLUMN = 24

#: Root groups come from the same catalog every generated surface reads, so
#: adding a command in `searchts/catalog.py` puts it on this screen too.
ROOT_GROUPS: List[Tuple[str, List[Tuple[str, str]]]] = catalog.root_groups()

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

#: What a command without its own footer falls back to. Per-command exit codes
#: live beside the command in `searchts/catalog.py` (gap #6).
EXIT_CODES = catalog.EXIT_PLAIN
ROOT_EXIT_CODES = catalog.EXIT_ROOT

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


def _global_flag_rows(parser: argparse.ArgumentParser | None) -> List[Tuple[str, str]]:
    """Root flags from the live parser: -v/--verbose and --version (gap #11)."""
    if parser is None:
        return [("-v, --verbose", "Show debug logs"),
                ("--version", "Print the version and exit")]
    rows = []
    for action in parser._actions:
        if isinstance(action, argparse._HelpAction) or not action.option_strings:
            continue
        text = catalog.action_help(action)
        if text:
            rows.append((", ".join(action.option_strings), text))
    return rows


def render_root(version: str, parser: argparse.ArgumentParser | None = None) -> None:
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

    d.heading("GLOBAL FLAGS")
    for flag, meaning in _global_flag_rows(parser):
        d.pair(flag, meaning, left_style=s.cyan)

    d.heading("EXAMPLES")
    for cmd, _ in EXAMPLES:
        d.example(cmd)

    d.heading("EXIT CODES")
    for code, meaning in ROOT_EXIT_CODES:
        d.pair(code, meaning, label=6, left_style=s.dim)
    d.blank()
    d.lines.append("  " + s.dim(
        "Other commands: searchts <command> --help or searchts help --json"))

    d.blank()
    d.rule()
    d.blank()
    d.lines.append("  " + s.dim("Run ") + "searchts <command> --help"
                   + s.dim(" for one command, its flags and examples."))
    d.lines.append("  " + s.dim("Run ") + "searchts help --json"
                   + s.dim(" for the machine-readable catalog."))
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


def _subparser_action(parser: argparse.ArgumentParser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _render_subcommands(d: Doc, parser: argparse.ArgumentParser,
                        path: Sequence[str]) -> None:
    """The parent screen's verb table, one line each (gaps #2, #7, #8, #9)."""
    action = _subparser_action(parser)
    if action is None:
        return
    s = d.s
    rows: List[Tuple[str, str]] = []
    seen = set()
    for name, child in action.choices.items():
        if id(child) in seen:
            continue
        seen.add(id(child))
        meta = catalog.meta_for([*path, name])
        lead = meta.lead if meta else (child.description or "")
        if not lead:
            lead = "Subcommand."
        rows.append((name, lead))
    if not rows:
        return
    d.heading("COMMANDS")
    for name, lead in rows:
        d.pair(name, lead, left_style=s.cyan)


def _render_flags(d: Doc, parser: argparse.ArgumentParser,
                  path: Sequence[str]) -> None:
    key = " ".join(path)
    groups = OPTION_GROUPS.get(key) or OPTION_GROUPS.get(path[0])
    by_flag = {}
    for action in parser._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        for flag in action.option_strings:
            by_flag[flag] = action
    options = [a for a in parser._actions
               if a.option_strings and not isinstance(a, argparse._HelpAction)]
    if not options:
        return
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
        leftover = [a for a in options if id(a) not in named]
        if leftover:
            if rows and rows[-1][0] == "ALSO":
                rows[-1][1].extend(leftover)
            else:
                rows.append(("ALSO", leftover))
        if not any(title != "ALSO" for title, _ in rows):
            # A screen with only --verbose has no groups to label. Printing
            # `FLAGS` then an `ALSO` subheading is an empty heading (gap #8).
            d.heading("FLAGS")
            for action in options:
                _option_rows(d, action, catalog.flag_name(action),
                             command_name=" ".join(path))
            return
        d.heading("FLAGS")
        d.blank()
        for i, (title, actions) in enumerate(rows):
            if i:
                d.blank()
            d.lines.append("  " + d.s.dim(title))
            for action in actions:
                _option_rows(d, action, catalog.flag_name(action),
                             command_name=" ".join(path))
        return
    d.heading("FLAGS")
    for action in options:
        _option_rows(d, action, catalog.flag_name(action),
                     command_name=" ".join(path))


def render_command(parser: argparse.ArgumentParser, path: Sequence[str],
                   version: str) -> None:
    d = Doc()
    s = d.s
    meta = catalog.meta_for(path)

    d.lines.append("")
    d.lines.append("  " + s.bold("searchts") + " " + s.cyan(" ".join(path))
                   + "  " + s.dim(f"v{version}"))
    d.blank()
    lead = (meta.lead if meta else "") or (parser.description or "")
    if lead:
        d.lines.append("  " + lead)
    if meta:
        for line in meta.body:
            d.lines.append("  " + s.dim(line))
        if meta.aliases:
            d.lines.append("  " + s.dim("Alias: ")
                           + ", ".join("searchts " + a for a in meta.aliases))
        for note in meta.notes:
            d.lines.append("  " + s.dim(note))

    d.heading("USAGE")
    usage_lines = _usage_lines(catalog.usage_tokens(parser, path))
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
                   and not isinstance(a, argparse._SubParsersAction)
                   and catalog.action_help(a)]
    if positionals:
        d.heading("ARGUMENTS")
        d.blank()
        for action in positionals:
            shown = catalog.metavar(action, lower=True)
            if len(shown) > 20:
                shown = action.dest
            _option_rows(d, action,
                         shown if shown[:1] in ("[", "(") else f"<{shown}>",
                         with_metavar=False)

    # A parent verb (`login`, `mcp`, `skill`) shows its verbs before its flags:
    # a screen with a FLAGS heading and no way to discover `check` is the bug.
    _render_subcommands(d, parser, path)
    _render_flags(d, parser, path)

    examples = list(meta.examples) if meta else []
    if examples:
        d.heading("EXAMPLES")
        for cmd in examples:
            d.example(cmd)

    see = []
    if path and path[0] in ("read", "transcribe"):
        see = ["grab (the files it names)", "get (one file it named)"]
    if see:
        d.heading("SEE ALSO")
        for item in see:
            d.lines.append("  " + item)

    exit_codes = meta.exit_codes if meta and meta.exit_codes else EXIT_CODES
    d.blank()
    d.rule()
    d.blank()
    sep = " · " if _unicode() else " | "
    footer = "Exit codes: " + sep.join(f"{code} {meaning}" for code, meaning in exit_codes)
    for line in _wrap(footer, WIDTH - 4):
        d.lines.append("  " + s.dim(line))
    d.lines.append("")
    d.out()


def _usage_lines(tokens: Sequence[str]) -> List[str]:
    """Pack the usage into lines that never split a ``[flag VALUE]`` group."""
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
                 with_metavar: bool = True, command_name: str = "") -> None:
    s = d.s
    label = flag
    if with_metavar and action.nargs != 0:
        shown = catalog.metavar(action)
        if len(shown) > 14:
            shown = action.dest.upper()
        label = f"{flag} {shown}"
    help_text = catalog.action_help(action)
    if not help_text:
        return
    marker = catalog.FLAG_MARKERS.get((command_name, flag), "")
    if marker == "deprecated" or (action.help or "").startswith("Deprecated"):
        label = label + " (deprecated)"
    elif marker == "legacy":
        label = label + " (legacy)"
    if len(label) > COLUMN - 2:
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
        subs = _subparser_action(current)
        if subs is None:
            break
        if token in subs.choices:
            path.append(token)
            current = subs.choices[token]
        else:
            break
    return path, current


def render(parser: argparse.ArgumentParser, argv: Sequence[str],
           version: str) -> None:
    path, target = find_subparser(parser, argv)
    if not path:
        render_root(version, parser)
    else:
        render_command(target, path, version)
