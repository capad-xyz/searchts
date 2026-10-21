"""User-facing message shaping for searchts.

The failure path is the product. README: "return the real page, or fail loudly
and say why." So the reasons we print are load-bearing, and three things were
making them worse than they had to be:

1. **A typo cost the full ladder.** ``searchts read not-a-url`` took 18.6s and
   launched a real browser, because a bare word is a syntactically valid
   hostname that happens not to resolve. The most common user mistake was being
   charged the most expensive code path.
2. **Every reason was printed twice.** The progress ticks announced each rung's
   failure, and then the final block repeated all of them verbatim.
3. **Library internals leaked through.** Playwright's "Call log: - navigating
   to..." and curl's "See https://curl.se/... for more details" are debugging
   help aimed at the person who wrote the integration, not at someone who
   mistyped a URL.

Kept here rather than in cli.py because ``transcribe``, ``get`` and ``grab``
take the same kind of argument and deserve the same treatment, and because the
noise-stripping belongs next to the text it shapes.
"""

from __future__ import annotations

import os
import re
from typing import Optional, Sequence
from urllib.parse import urlsplit
from urllib.request import pathname2url

#: Playwright appends a "Call log:" block with the navigation step. Useful in a
#: bug report, noise in an error message.
_PLAYWRIGHT_CALL_LOG = re.compile(r"\s*Call log:.*\Z", re.S | re.I)

#: curl appends a documentation pointer. Same reasoning. The space before
#: "first" has to be matched explicitly: `\S*` alone swallows it and backtracks
#: to the wrong split, which I only found by running the pattern.
_CURL_DOC_HINT = re.compile(
    r"\s*See https?://curl\.se/\S*?\s+first for more details\.?\s*\Z", re.I
)

#: urllib and friends put the message on one line with a "urlopen error" frame.
_OPENER_FRAME = re.compile(r"\s*urlopen error \S+\s*\Z", re.I)

#: A bare word with no dot is a hostname only in a lab. For a tool whose job is
#: reading public pages, it is a typo far more often than it is an intranet
#: host, and the SSRF guard blocks the internal ones anyway.
_BARE_LABEL = re.compile(r"^[A-Za-z0-9_-]+$")

#: Schemes a web reader can actually fetch.
_READABLE_SCHEMES = ("http", "https")


def check_url(url: str) -> Optional[str]:
    """A message if *url* cannot be read, else None.

    Deliberately conservative: this must never reject a URL that would have
    worked. Every branch here fires on something no successful read would have
    contained.
    """
    raw = (url or "").strip()
    if not raw:
        return "no URL given"

    # A URL with a space is a paste accident, and the failure mode otherwise is a
    # confusing DNS or 400 error rather than a note about the space.
    if any(c.isspace() for c in raw):
        return f"{url!r} contains a space. Quote the whole URL, or remove the space."

    try:
        parts = urlsplit(raw)
    except ValueError as e:
        return f"{raw!r} is not a URL: {e}"

    scheme = (parts.scheme or "").lower()
    if scheme and scheme not in _READABLE_SCHEMES:
        # Suggest the same target with a readable scheme rather than a bare
        # "https://", which would be an empty URL and a second failure.
        # With no netloc (file://, mailto:) there is no target to rewrite, so
        # name the problem and stop instead of inventing a URL.
        if not parts.netloc:
            return (
                f"searchts reads {' and '.join(_READABLE_SCHEMES)} URLs, "
                f"not {scheme!r}, and this one names no site to fetch."
            )
        guess = f"https://{parts.netloc}{parts.path}"
        if parts.query:
            guess += f"?{parts.query}"
        return (
            f"searchts reads {' and '.join(_READABLE_SCHEMES)} URLs, "
            f"not {scheme!r}. Did you mean {guess} ?"
        )

    if not scheme:
        host = parts.path.split("/")[0]
        if _BARE_LABEL.match(host):
            # The whole case: `read example`, `read not-a-url`. Costs a browser
            # launch today to report "could not resolve host".
            return f"{raw!r} is not a URL. Did you mean https://{raw}/ ?"

    return None


def tidy_reason(why: str) -> str:
    """Strip debugging help aimed at the integrator out of a user-facing reason."""
    text = (why or "").strip()
    for pattern in (_PLAYWRIGHT_CALL_LOG, _CURL_DOC_HINT, _OPENER_FRAME):
        text = pattern.sub("", text).strip()
    # curl's message keeps a useful prefix; only the pointer goes.
    return text or "failed"


def stream_is_tty(stream: object) -> bool:
    """Whether ``stream`` is a terminal someone is looking at."""
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except Exception:  # noqa: BLE001 - a broken stream is not a terminal
        return False


def links_enabled(stream: object) -> bool:
    """OSC 8 only where the escapes will be interpreted, not printed.

    A pipe, a capture, and ``TERM=dumb`` must see the path itself. Escape
    codes there hide it from the next program.
    """
    if os.environ.get("TERM") == "dumb":
        return False
    return stream_is_tty(stream)


def color_enabled(stream: object) -> bool:
    """Truecolor only when a person will see it.

    ``NO_COLOR`` is the off switch. A captured stream is not a terminal, so
    a test or a pipe keeps the hex and nothing else.
    """
    if os.environ.get("NO_COLOR", "") != "":
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    return stream_is_tty(stream)


def file_uri(path: str) -> str:
    """A ``file://`` URI for ``path``. A directory URI opens the directory.

    The path is made absolute first, then percent-encoded, so a space cannot
    end an OSC 8 sequence early. Windows ``pathname2url`` already returns
    ``///C:/...``, and the scheme there is ``file:`` plus that. Everywhere
    else it returns ``/tmp/...`` and the scheme is ``file://``. Both come
    out as ``file:///...``, which Explorer, Finder, and a terminal's
    Ctrl+click open.
    """
    absolute = os.path.abspath(path)
    if os.name == "nt":
        import nturl2path

        return "file:" + nturl2path.pathname2url(absolute)
    return "file://" + pathname2url(absolute)


def clickable_path(path: str, *, link: bool) -> str:
    """``path`` as text, and when ``link`` an OSC 8 hyperlink to its file URI.

    The visible characters are always the path. A copy pastes as a path, and
    a terminal that detects paths (VS Code, Cursor) can open a directory
    from the text alone. Windows Terminal does not detect bare paths, so on
    a real terminal the same text is also an OSC 8 link: Ctrl+click opens
    the folder.

    ``link`` stays false for a pipe. The escapes would be part of the path
    the next program reads.
    """
    if not link:
        return path
    uri = file_uri(path)
    if any(ch in uri or ch in path for ch in ("\033", "\x07", "\n", "\r")):
        return path
    # ST (ESC \\) closes the sequence. It does not occur in a file URI.
    return f"\033]8;;{uri}\033\\{path}\033]8;;\033\\"


_HEX6 = re.compile(r"^#([0-9a-fA-F]{6})$")


def palette_text(hexes: Sequence[str], *, color: bool) -> str:
    """Hex codes, with a truecolor chip in front of each when ``color``.

    The hex stays either way, so it can be copied and a test can find it.
    The chip is two spaces on a 24-bit background: a space is in every
    font, a block glyph is not. A value that is not ``#rrggbb`` is printed
    as text, so an odd token cannot paint the rest of the line.
    """
    parts = []
    for hx in hexes:
        if not hx:
            continue
        match = _HEX6.match(hx) if color else None
        if match:
            raw = match.group(1)
            r = int(raw[0:2], 16)
            g = int(raw[2:4], 16)
            b = int(raw[4:6], 16)
            parts.append(f"\033[48;2;{r};{g};{b}m  \033[0m {hx}")
        else:
            parts.append(hx)
    return " ".join(parts)
