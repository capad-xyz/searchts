# -*- coding: utf-8 -*-
"""Live progress for the commands that can sit for seconds.

The problem this module exists for is narrow and real. ``searchts grab`` on a
normal marketing site spends eight seconds reading CSS and forty downloading
images, and until now it printed one line at the start of each of those phases
and nothing in between. ``searchts read`` on a walled page spends twenty of its
twenty-five seconds inside a Chromium launch, printing one line. Both of those
look exactly like a hang, and a user who thinks a CLI has hung kills it.

So: a live region, on stderr, that moves.

Three rules, and they are the whole design:

1. **stderr only.** stdout is content. A read's markdown, a search's list and a
   grab's manifest path have to stay pipeable, and the MCP protocol is not a
   place to draw a spinner. Everything here writes to stderr.

2. **Not a terminal, not a film.** When stderr is a pipe, a file, CI, or the
   MCP server, this module prints exactly the plain lines the tool always
   printed, one per line, no cursor movement, no colour, no animation. A log
   gets a log. That is also why the plain path is the *fallback* rather than a
   mode: the tests assert on it, and they are right to.

3. **It cannot break a read.** Every write is wrapped. A closed pipe, a
   detached stderr, a terminal that rejects UTF-8: all of it degrades to
   silence, never to a traceback in the middle of someone's fetch.

The stage grammar comes from the narration the ladder already emits. A line
``trying curl_cffi…`` opens a rung; a following indented ``curl_cffi: 403``
gives that rung its verdict. That is why this file can turn sixty existing
tick call sites into a ladder without editing sixty call sites.
"""

from __future__ import annotations

import contextvars
import os
import re
import shutil
import sys
import threading
import time
from typing import List, Optional

# ── capability detection ─────────────────────────────────────────────────────

#: Braille spinner. Six frames is enough to read as motion at 10 fps without
#: the shimmer a twenty-frame set has on a slow terminal.
_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_ASCII_FRAMES = ("|", "/", "-", "\\")

#: The bar uses eighth-blocks so a slow download visibly creeps instead of
#: jumping a whole cell at a time.
_BAR_FULL = "█"
_BAR_PARTIAL = ("", "▏", "▎", "▍", "▌", "▋", "▊", "▉")
_BAR_EMPTY = "░"
_ASCII_BAR_FULL = "#"
_ASCII_BAR_EMPTY = "-"


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def supports_unicode(stream=None) -> bool:
    """Can this stream carry box-drawing and braille without mojibake?

    The Windows console is the reason this is a runtime question rather than a
    platform constant: a UTF-8 Windows Terminal renders braille perfectly, and
    the same binary on a cp437 console renders ``?``. Ask the stream.
    """
    if _env_flag("SEARCHTS_ASCII"):
        return False
    stream = stream or sys.stderr
    encoding = (getattr(stream, "encoding", None) or "").lower()
    if not encoding:
        return False
    try:
        "⠋─█".encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def use_color(stream=None) -> bool:
    """Colour only on a terminal, and only when the user has not opted out."""
    if _env_flag("NO_COLOR") or _env_flag("SEARCHTS_NO_COLOR"):
        return False
    if _env_flag("FORCE_COLOR") or _env_flag("SEARCHTS_FORCE_COLOR"):
        return True
    if os.environ.get("TERM", "").lower() == "dumb":
        return False
    stream = stream or sys.stderr
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False



def live_available(stream=None) -> bool:
    """Would a tracker on this stream draw, without constructing one?

    Used by ``watch`` to decide whether the outer "checking channels…" line is
    the plain log or would be a duplicate of the tracker's own header.
    """
    return Tracker._detect_tty(stream or sys.stderr, None)


def mark(status: str, unicode_ok: bool = True) -> str:
    """The one-glyph verdict shared by the live rows and every receipt."""
    if status == ROW_OK:
        return "✓" if unicode_ok else "+"
    if status == ROW_WARN:
        return "!"
    if status == ROW_FAIL:
        return "✗" if unicode_ok else "x"
    return "·" if unicode_ok else "."


def use_links(stream=None) -> bool:
    """OSC 8 hyperlinks.

    Separate from colour on purpose: a terminal with no colour still follows a
    link, and ``NO_COLOR`` is about palette, not about whether a path is
    clickable. Piped output never gets them, which is what keeps a redirect to
    a file byte-clean.
    """
    if _env_flag("SEARCHTS_NO_LINKS"):
        return False
    if _env_flag("SEARCHTS_LINKS"):
        return True
    # A dumb terminal renders the escape bytes instead of following them. The
    # label would still be readable, but the bytes are not part of the path a
    # person or the next program should have to strip.
    if os.environ.get("TERM", "").lower() == "dumb":
        return False
    stream = stream or sys.stderr
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


class Style:
    """ANSI helpers that return their input unchanged when colour is off."""

    def __init__(self, enabled: bool):
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        if not self.enabled or not text:
            return text
        return f"\x1b[{code}m{text}\x1b[0m"

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def green(self, text: str) -> str:
        return self._wrap("32", text)

    def red(self, text: str) -> str:
        return self._wrap("31", text)

    def yellow(self, text: str) -> str:
        return self._wrap("33", text)

    def cyan(self, text: str) -> str:
        return self._wrap("36", text)

    def magenta(self, text: str) -> str:
        return self._wrap("35", text)

    def grey(self, text: str) -> str:
        return self._wrap("90", text)


# ── clickable targets ───────────────────────────────────────────────────────


def link(text: str, url: str, enabled: Optional[bool] = None) -> str:
    """Wrap *text* in an OSC 8 hyperlink to *url*.

    Terminals that do not understand OSC 8 ignore it and print the label, which
    is why the label has to be the whole truth on its own.
    """
    if enabled is None:
        enabled = use_links()
    if not enabled or not url:
        return text
    # ESC and BEL inside the target would end or corrupt the sequence.
    safe = url.replace("\x1b", "").replace("\x07", "").replace("\n", "")
    return f"\x1b]8;;{safe}\x1b\\{text}\x1b]8;;\x1b\\"


def link_url(url: str, enabled: Optional[bool] = None) -> str:
    return link(url, url, enabled)


def link_path(path: str, enabled: Optional[bool] = None) -> str:
    """A local path as a clickable ``file://`` target."""
    try:
        import pathlib

        target = pathlib.Path(path).resolve().as_uri()
    except (ValueError, OSError):
        return path
    return link(path, target, enabled)


# ── sizes and clocks ────────────────────────────────────────────────────────


def human_bytes(n: float) -> str:
    if n < 1024:
        return f"{int(n)} B"
    for unit in ("KB", "MB", "GB"):
        n /= 1024.0
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
    return f"{n:.1f} GB"


def human_rate(bytes_per_second: float) -> str:
    if bytes_per_second <= 0:
        return ""
    return human_bytes(bytes_per_second) + "/s"


def human_time(seconds: float) -> str:
    if seconds < 1:
        return f"{int(seconds * 1000)}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes}m{rest:02d}s"


def swatch(hex_color: str, enabled: bool = True) -> str:
    """A two-cell colour chip for a palette entry, on a truecolor terminal.

    A hex list is a string to read; a chip is a colour to see. Terminals that
    do not advertise truecolor get the hex alone, which loses nothing.
    """
    if not enabled:
        return ""
    raw = (hex_color or "").lstrip("#")
    if len(raw) == 3:
        raw = "".join(c * 2 for c in raw)
    if len(raw) != 6:
        return ""
    try:
        r, g, b = (int(raw[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return ""
    return f"\x1b[48;2;{r};{g};{b}m  \x1b[0m "



def fit(text: str, width: int) -> str:
    """Truncate to *width* printable cells.

    Non-negotiable: the redraw counts lines and moves the cursor up by that
    count, so a line that wraps desynchronises the whole block and leaves
    half-drawn rows behind. Every rendered line goes through here.
    """
    if width <= 0:
        return ""
    # ANSI sequences occupy no cells, so measure the visible text.
    visible = _ANSI_RE.sub("", text)
    if len(visible) <= width:
        return text
    if width <= 1:
        return "…"
    # Truncating inside an escape sequence would leak it, so cut the plain text
    # and re-apply nothing: this only ever trims trailing detail.
    plain = visible[: width - 1] + "…"
    if text != visible:
        # Rebuild by stripping escapes from the tail we keep. Simpler and
        # safer: drop styling entirely on an over-long line.
        return plain
    return plain


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\]8;;.*?\x1b\\")
_OSC8_RE = re.compile(r"\x1b\]8;;.*?\x1b\\")


def _visible_len(text: str) -> int:
    return len(_ANSI_RE.sub("", text))


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _visible_len(text))


# ── the live region ─────────────────────────────────────────────────────────

#: A row is one rung, phase, provider, or counter.
ROW_PENDING = "pending"
ROW_RUNNING = "running"
ROW_OK = "ok"
ROW_WARN = "warn"
ROW_SKIP = "skip"
ROW_FAIL = "fail"


class Row:
    __slots__ = ("label", "detail", "status", "started", "ended", "id", "total", "done",
                 "size", "rate", "note")

    def __init__(self, label: str, row_id: Optional[str] = None):
        self.label = label
        self.detail = ""
        self.status = ROW_RUNNING
        self.started = time.monotonic()
        self.ended: Optional[float] = None
        self.id = row_id
        self.total = 0
        self.done = 0
        self.size = 0
        self.rate = 0.0
        self.note = ""

    def elapsed(self) -> float:
        end = self.ended if self.ended is not None else time.monotonic()
        return max(0.0, end - self.started)


class Tracker:
    """One live region, owning the rows of a single command.

    Not thread-safe by accident: mutations take the lock, because a read's
    browser rung narrates from a Playwright callback while the animator thread
    is redrawing.
    """

    #: Frames are cheap; the clock is what convinces a human the process is
    #: alive, and 10 fps keeps the tenths digit honest.
    FPS = 10.0

    #: More rows than this and the block becomes a wall of noise that scrolls
    #: the answer away. The oldest finished rows collapse into a count.
    MAX_ROWS = 8

    def __init__(self, command: str, subject: str = "", *, stream=None,
                 enabled: Optional[bool] = None, ascii_only: Optional[bool] = None,
                 max_rows: Optional[int] = None, summary_stream=None):
        self.command = command
        self.subject = subject
        self._stream = stream
        #: Doctor probes 11 channels and the 8-row default would hide the first
        #: three behind "… N earlier". A command that knows its whole block can
        #: raise the cap; every other caller keeps the readable default.
        self.max_rows = max(1, int(max_rows)) if max_rows is not None else self.MAX_ROWS
        #: A receipt is stdout content on a status command. The live block is
        #: still stderr; only the line close() writes goes to this stream.
        self._summary_stream = summary_stream
        self.rows: List[Row] = []
        self._active: Optional[Row] = None
        self._lock = threading.RLock()
        self._drawn = 0
        self._frame = 0
        self._start = time.monotonic()
        self._closed = False
        self._summary: Optional[str] = None
        self._note_line = ""
        self._spin: Optional[threading.Thread] = None
        self._stop = threading.Event()

        stream = stream or sys.stderr
        self._tty = self._detect_tty(stream, enabled)
        self._unicode = supports_unicode(stream) if ascii_only is None else not ascii_only
        self.color = Style(use_color(stream) if self._tty else False)
        self.links = use_links(stream) if self._tty else False

    @staticmethod
    def _detect_tty(stream, enabled: Optional[bool]) -> bool:
        if enabled is not None:
            return enabled
        # Forced on or off, for a demo recorder and for anything driving a
        # pty it does not own. Checked before CI so a recorder in CI still
        # records.
        if _env_flag("SEARCHTS_NO_PROGRESS"):
            return False
        if _env_flag("SEARCHTS_PROGRESS_TTY"):
            return True
        if os.environ.get("CI"):
            # CI logs are line-oriented and a live region there is pure noise.
            return False
        try:
            return bool(stream.isatty())
        except (AttributeError, ValueError):
            return False


    # ── lifecycle ──────────────────────────────────────────────────────────

    def __enter__(self) -> "Tracker":
        _set_current(self)
        if self._tty:
            self._start_animator()
            self._redraw()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close(failed=exc_type is not None)

    def close(self, *, failed: bool = False) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for row in self.rows:
                if row.status == ROW_RUNNING:
                    row.status = ROW_FAIL if failed else ROW_SKIP
                    row.ended = time.monotonic()
        self._stop.set()
        thread = self._spin
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=0.5)
        _set_current(None)
        if self._tty:
            self._clear()
        self._finish()

    def wants(self) -> bool:
        """Should the fetcher narrate to this tracker?

        True only when a live region is actually drawing. A piped read keeps
        ``progress=False`` so the reasons are printed once, by the failure
        block, rather than twice.
        """
        return self._tty

    def abort(self) -> None:
        """Take the live block down without printing a receipt.

        The caller already owns the ending: ``read`` prints its per-rung reasons
        through ``ux``, and those are tidier than anything this module could
        reconstruct from the narration.
        """
        self._summary = None
        self.close(failed=True)


    # ── mutation ───────────────────────────────────────────────────────────

    def stage(self, label: str, detail: str = "", row_id: Optional[str] = None) -> Row:
        """Open a new row, retiring the previous one."""
        if row_id is not None:
            for row in self.rows:
                if row.id == row_id:
                    row.status = ROW_RUNNING
                    row.ended = None
                    row.started = time.monotonic()
                    if detail:
                        row.detail = detail
                    self._active = row
                    self._refresh(force=True)
                    return row
        with self._lock:
            if self._active is not None and self._active.status == ROW_RUNNING:
                # A new stage means the last one is over. It has a verdict only
                # if the ladder narrated one; without a detail line, "·" is the
                # honest mark rather than a green tick nothing promised.
                self._active.status = ROW_OK if self._active.detail else ROW_SKIP
                self._active.ended = time.monotonic()
            row = Row(label, row_id)
            row.detail = detail
            self.rows.append(row)
            self._active = row
            self._trim()
        self._refresh(force=True)
        return row

    def settle(self, status: str = ROW_OK, detail: Optional[str] = None) -> None:
        """Give the active row its verdict."""
        with self._lock:
            row = self._active
            if row is None:
                return
            row.status = status
            if detail is not None:
                row.detail = detail
            row.ended = time.monotonic()
        self._refresh(force=True)

    def detail(self, text: str) -> None:
        """Attach progress detail (a reason, a size) to the active row."""
        with self._lock:
            if self._active is not None:
                self._active.detail = text
        self._refresh()

    def note(self, text: str) -> None:
        """A line that is not a rung verdict: a hint, a [dry-run] marker."""
        with self._lock:
            self._note_line = text
        self._refresh(force=True)

    def counter(self, label: str, total: int = 0) -> Row:
        """The determinate row for a phase whose size is known up front.

        Reuses the active row when the ladder already opened one with the same
        label, because ``downloading assets…`` is narrated as a stage and then
        immediately turned into a bar. Two rows saying the same thing is the
        one thing a progress display must not do.
        """
        row = self._active
        if row is None or row.label != label:
            row = self.stage(label)
        row.total = total
        row.done = 0
        row.size = 0
        row.rate = 0.0
        self._refresh(force=True)
        return row


    def advance(self, n: int = 1, size: int = 0) -> None:
        """One more finished item: the determinate half of the display."""
        with self._lock:
            row = self._active
            if row is None:
                return
            row.done += n
            row.size += size
            elapsed = max(row.elapsed(), 1e-9)
            row.rate = row.size / elapsed
        self._refresh()

    def summary(self, text: str) -> None:
        self._summary = text

    def elapsed(self) -> float:
        return max(0.0, time.monotonic() - self._start)

    @property
    def unicode_ok(self) -> bool:
        """Can this terminal take box-drawing and braille?"""
        return self._unicode

    @property
    def is_live(self) -> bool:
        """Is this tracker drawing, as opposed to standing in for a log?"""
        return self._tty and not self._closed



    # ── drawing ────────────────────────────────────────────────────────────

    def _width(self) -> int:
        forced = os.environ.get("SEARCHTS_PROGRESS_WIDTH")
        if forced:
            try:
                return max(40, int(forced))
            except ValueError:
                pass
        try:
            return max(40, shutil.get_terminal_size((80, 24)).columns)
        except (OSError, ValueError):
            return 80


    def _glyph(self, row: Row) -> str:
        if row.status == ROW_OK:
            return "✓" if self._unicode else "+"
        if row.status == ROW_WARN:
            return "!"
        if row.status == ROW_SKIP:
            return "·" if self._unicode else "."
        if row.status == ROW_FAIL:
            return "✗" if self._unicode else "x"
        frames = _FRAMES if self._unicode else _ASCII_FRAMES
        return frames[self._frame % len(frames)]

    def _bar(self, row: Row, width: int) -> str:
        if row.total <= 0:
            return ""
        s = self.color
        frac = min(1.0, row.done / row.total)
        full = frac * width
        whole = int(full)
        part = int((full - whole) * 8)
        filled = (_BAR_FULL if self._unicode else _ASCII_BAR_FULL) * whole
        if part and whole < width and self._unicode:
            filled += _BAR_PARTIAL[part]
        # The fill is the accent, the remainder is a shade. Both in the default
        # foreground reads as one bar that never looks finished.
        left = width - _visible_len(filled)
        return (s.green(filled)
                + s.dim((_BAR_EMPTY if self._unicode else _ASCII_BAR_EMPTY)
                        * max(0, left)))

    def _blocks(self) -> List[str]:
        s = self.color
        width = self._width()
        out: List[str] = []

        elapsed = time.monotonic() - self._start
        right = s.dim(human_time(elapsed))
        subject = self.subject
        head = f"{s.bold('searchts')} {s.cyan(self.command)}"
        if subject:
            head += "  " + s.dim(subject)
        gap = max(1, width - _visible_len(head) - _visible_len(right) - 2)
        # A long subject is the one thing here that can outgrow the terminal.
        # Truncate it before it wraps, or the cursor-up count desyncs.
        while subject and _visible_len(head) + gap + _visible_len(right) + 2 > width:
            subject = subject[: max(3, len(subject) - 4)].rstrip()
            head = f"{s.bold('searchts')} {s.cyan(self.command)}  {s.dim(subject)}"
            gap = max(1, width - _visible_len(head) - _visible_len(right) - 2)
        out.append(fit("  " + head + " " * gap + right, width))
        rule = "─" if self._unicode else "-"
        out.append("  " + s.dim(rule * min(width - 4, 64)))

        rows = self.rows[-self.max_rows:]
        hidden = len(self.rows) - len(rows)
        if hidden > 0:
            out.append("  " + s.dim(f"… {hidden} earlier"))

        # One label column, so the details stack instead of ragging. Capped:
        # a long known-host name must not push every verdict off the screen.
        label_w = min(24, max((len(r.label) for r in rows), default=0))

        for row in rows:
            glyph = self._glyph(row)
            if row.status == ROW_OK:
                glyph = s.green(glyph)
            elif row.status == ROW_WARN:
                glyph = s.yellow(glyph)
            elif row.status == ROW_FAIL:
                glyph = s.red(glyph)
            elif row.status == ROW_SKIP:
                glyph = s.dim(glyph)
            else:
                glyph = s.cyan(glyph)

            label = row.label
            if len(label) > label_w:
                label = label[: label_w - 1] + "…"
            line = f"  {glyph} {_pad(label, label_w)}"

            # The right column is built by importance and trimmed by width:
            # a bar and its count always fit, the byte rate only when there is
            # room. Losing a number beats wrapping a line.
            right_bits: List[str] = []
            if row.total > 0:
                bar_w = 14 if width >= 74 else (8 if width >= 58 else 5)
                done = min(row.done, row.total)
                right_bits.append(self._bar(row, bar_w))
                right_bits.append(f"{done}/{row.total}")
                if row.size and width >= 68:
                    right_bits.append(human_bytes(row.size))
                if row.rate and row.status == ROW_RUNNING and width >= 76:
                    right_bits.append(human_rate(row.rate))
            # Every row carries a clock, running or not. A number that moves
            # every tenth of a second is the whole difference between "working"
            # and "wedged", and it costs six characters.
            right_bits.append(s.dim(human_time(row.elapsed())))
            right = "  ".join(right_bits)

            detail = row.detail
            # -6: the two-space separators on either side of the right column.
            room = width - _visible_len(line) - _visible_len(right) - 6
            if detail and room >= 8:
                line += "  " + s.dim(fit(detail, room))
            pad = max(2, width - _visible_len(line) - _visible_len(right) - 2)
            out.append(fit(line + " " * pad + right, width))



        if self._note_line:
            out.append("  " + s.dim(fit(self._note_line, width - 4)))

        # A hint that only appears once a rung has behaved like a slow rung.
        hint = self._slow_hint()
        if hint:
            out.append("  " + s.dim(fit(hint, width - 4)))
        return out

    def _slow_hint(self) -> str:
        """Say something true once a wait stops looking like a normal wait.

        The measured cost of the stealth rung is 18-20s per launch, so a browser
        row that has been running for six seconds is behaving exactly as
        designed and the user deserves to be told that rather than invent it.
        """
        row = self._active
        if row is None or row.status != ROW_RUNNING:
            return ""
        waited = row.elapsed()
        label = row.label.lower()
        if "browser" in label or "stealth" in label:
            if waited > 6:
                return "chromium launch; a walled page measures 18-20s at this rung"
        elif waited > 8:
            return f"{human_time(waited)} at this rung; still working"
        return ""

    def _redraw(self) -> None:
        if not self._tty or self._closed:
            return
        blocks = self._blocks()
        buf: List[str] = []
        if self._drawn:
            # Move to the top of the block and repaint in place.
            buf.append(f"\x1b[{self._drawn}A")
        for line in blocks:
            buf.append("\x1b[2K" + line + "\n")
        if self._drawn > len(blocks):
            for _ in range(self._drawn - len(blocks)):
                buf.append("\x1b[2K\n")
            buf.append(f"\x1b[{self._drawn - len(blocks)}A")
        try:
            stream = self._stream or sys.stderr
            if stream is None:
                return
            stream.write("".join(buf))
            stream.flush()
            self._drawn = len(blocks)
        except (OSError, ValueError, AttributeError):
            # A closed pipe mid-read is a thing users do (`| head`). Stop
            # drawing rather than raise into the fetch.
            self._tty = False

    def _clear(self) -> None:
        if not self._drawn:
            return
        try:
            stream = self._stream or sys.stderr
            if stream is None:
                return
            stream.write(f"\x1b[{self._drawn}A")
            for _ in range(self._drawn):
                stream.write("\x1b[2K\n")
            stream.write(f"\x1b[{self._drawn}A")
            stream.flush()
        except (OSError, ValueError, AttributeError):
            pass
        finally:
            self._drawn = 0

    def _finish(self) -> None:
        """The receipt: one line, and only when the caller wrote one.

        In plain mode this prints nothing. A piped command's ending is written
        by the command itself (or by ``ux`` on a failure), and adding a receipt
        line there would put the same fact on stderr twice.
        """
        stream = self._summary_stream or self._stream or sys.stderr
        if stream is None or not self._tty or self._summary is None:
            return
        try:
            stream.write(self._summary.rstrip("\n") + "\n")
            stream.flush()
        except (OSError, ValueError, AttributeError):
            pass

    def _receipt(self) -> str:
        s = self.color
        total = time.monotonic() - self._start
        parts = [f"{s.green('✓' if self._unicode else '+')} {s.cyan(self.command)}"]
        if self.subject:
            parts.append(self.subject)
        winner = next((r.label for r in self.rows if r.status == ROW_OK), "")
        if winner:
            parts.append(s.dim("via " + winner))
        parts.append(s.dim(human_time(total)))
        return "  " + "  ".join(parts)


    def _refresh(self, force: bool = False) -> None:
        if not self._tty or self._closed:
            return
        if force:
            self._redraw()

    def _trim(self) -> None:
        if len(self.rows) > 32:
            del self.rows[:-24]

    def _start_animator(self) -> None:
        def spin() -> None:
            period = 1.0 / self.FPS
            while not self._stop.wait(period):
                self._frame += 1
                self._redraw()

        self._spin = threading.Thread(target=spin, name="searchts-progress", daemon=True)
        self._spin.start()


# ── the process-wide current tracker ────────────────────────────────────────

_current: Optional[Tracker] = None
_current_lock = threading.Lock()


def _set_current(tracker: Optional[Tracker]) -> None:
    global _current
    with _current_lock:
        _current = tracker


def current() -> Optional[Tracker]:
    with _current_lock:
        return _current


def live(command: str, subject: str = "", **kwargs) -> Tracker:
    return Tracker(command, subject, **kwargs)


# ── narration routing ───────────────────────────────────────────────────────

_STAGE_START = re.compile(r"^trying (?P<label>.+?)(?:…|\.\.\.)?$")
_DETAIL = re.compile(r"^  (?P<who>[^:]+):\s*(?P<what>.*)$")
_SAVED = re.compile(r"^downloading assets…\s*(?P<n>\d+) saved$")

#: Lines that end in an ellipsis but describe the *active* rung rather than
#: starting a new one. Saying "waiting for page to settle" as a stage of its own
#: would put the browser's own step beside the browser, which is a lie about the
#: ladder's shape.
_SUBSTEP = ("waiting ", "climbing ", "manifest will come", "still ")

_OK_WORDS = ("ok (", "ok:", "captions (", "success")
_SKIP_WORDS = ("skipped", "miss", "thin-", "no captions", "no video", "no audio",
               "not a ", "none", "empty")


def classify(detail: str) -> str:
    """Which verdict does a rung's reason line carry?

    Deliberately word-based rather than regex-per-backend: the ladder grows
    reasons over time, and a new reason should show up as a failure (loud)
    rather than silently match nothing (quiet). That is the same trade as
    ``fail loud``, applied to the display of a failure.
    """
    low = detail.lower()
    if any(word in low for word in _OK_WORDS):
        return ROW_OK
    if any(word in low for word in _SKIP_WORDS):
        return ROW_SKIP
    return ROW_FAIL


def _strip_owner(detail: str, label: str = "") -> str:
    """Drop a label the detail line repeats.

    ``known-host:reddit: miss`` arrives with the row's own name in front of the
    verdict, because the narration was written to carry its context on a flat
    log. In a two-column display that context is already in the left column.
    Only an exact match against the row's own label (or its last namespace
    segment) is stripped, so a real ``net::ERR_FAILED`` keeps its colons.
    """
    if not label or ":" not in detail:
        return detail
    candidates = {label.strip().lower(), label.strip().lower().split(":")[-1]}
    low = detail.lower()
    for cand in sorted(candidates, key=len, reverse=True):
        if cand and low.startswith(cand + ":"):
            rest = detail[len(cand) + 1:].strip()
            return rest or detail
    return detail


def narrate(message: str, *, enabled: bool = True) -> None:
    """Send one narration line to the live region, or print it plain.

    This is the single entry point the existing ``_tick`` helpers call, which
    is what lets the whole tool get a live display without each call site
    learning about terminals.
    """
    if not enabled:
        return
    tracker = current()
    if tracker is None or not tracker.is_live:
        # No terminal, so this is a log: the same line the tool always printed.
        _plain(message)
        return
    text = message.rstrip()
    if not text:
        return

    saved = _SAVED.match(text)
    if saved:
        tracker.advance(int(saved.group("n")))
        return

    detail = _DETAIL.match(text)
    if detail:
        text_out = detail.group("what")
        label = tracker._active.label if tracker._active else ""
        tracker.settle(classify(text_out), _strip_owner(text_out, label))
        return

    start = _STAGE_START.match(text)
    if start:
        tracker.stage(start.group("label").strip())
        return

    if text.lower().startswith(_SUBSTEP):
        tracker.detail(text.rstrip("…. "))
        return

    if text.endswith(("…", "...")) and len(text) <= 64:
        tracker.stage(text.rstrip("…. "))
        return

    tracker.note(text)


def counting(label: str, total: int, enabled: bool = True) -> None:
    """Open (or update) the determinate row for a *total*-item phase.

    Plain mode prints the phase line once, exactly as the tool always did:
    a pipe or a log gets one line, not a hundred carriage returns.
    """
    tracker = current()
    if tracker is not None and tracker.is_live:
        row = tracker.counter(label, total)
        row.total = total
        return
    if enabled:
        _plain(label + "…")


def advance(n: int = 1, size: int = 0) -> None:
    """One more finished item, for the row ``counting`` opened."""
    tracker = current()
    if tracker is not None and tracker.is_live:
        tracker.advance(n, size)


def outcome(detail: str, status: Optional[str] = None) -> None:
    """Give the active row its verdict.

    Only when a live region exists. A piped log already gets the same reasons
    once, together, in the failure block; repeating them per rung there would
    be the duplication ``ux`` was written to stop.
    """
    tracker = current()
    if tracker is None or not tracker.is_live:
        return
    tracker.settle(status or classify(detail), detail)




def _plain(message: str) -> None:
    stream = sys.stderr
    if stream is None:
        return
    try:
        print(message, file=stream, flush=True)
    except (OSError, ValueError):
        pass


def tick(progress: Optional[bool], message: str) -> None:
    """The helper the fetchers call: tri-state flag plus one message.

    ``None`` follows ``SEARCHTS_PROGRESS`` exactly as before; ``False`` is
    silence; ``True`` narrates.
    """
    if progress is None:
        enabled = _env_flag("SEARCHTS_PROGRESS")
    else:
        enabled = bool(progress)
    narrate(message, enabled=enabled)


def log(message: str, *, enabled: bool = True) -> None:
    """A pipe-only line: the live region already says this in its row.

    Use it for an ending fact (``downloading assets. 12 saved``) that a log
    would otherwise never see, while keeping a terminal's block free of a
    second copy under the counter that just finished.
    """
    if not enabled:
        return
    tracker = current()
    if tracker is None or not tracker.is_live:
        _plain(message)


# --- the #407 phase API, routed into the tracker above ----------------------
#
# This module replaced the Phase engine with the live Tracker, but
# browser_install, device_check and parts of unlocker still import phase/note/
# announce/update. Those calls are kept working here and route into the tracker
# that is already open, so there is exactly one live region: a nested phase
# never draws a second spinner, and a pipe still gets one plain line per step.

_INTERVAL_S = 1.0
_SHOW_AFTER_S = 1.0

_phase_var: "contextvars.ContextVar[Optional[_CompatPhase]]" = contextvars.ContextVar(
    "searchts_compat_phase", default=None
)


def wanted(progress: Optional[bool]) -> bool:
    """Resolve the tri-state flag. None follows ``SEARCHTS_PROGRESS=1``."""
    if progress is None:
        return _env_flag("SEARCHTS_PROGRESS")
    return bool(progress)


def render(
    label: str,
    *,
    elapsed: Optional[float] = None,
    done: Optional[int] = None,
    total: Optional[int] = None,
    show_after: float = _SHOW_AFTER_S,
) -> str:
    """Plain status text: a fraction only when both numbers are known."""
    text = (label or "").rstrip()
    if done is not None and total is not None and done >= 0 and total > 0:
        text = f"{text} {done}/{total}"
    if elapsed is not None and elapsed >= show_after:
        text = f"{text} {int(elapsed)}s"
    return text


class _CompatPhase:
    """A #407 ``Phase`` that never opens a second live region.

    An explicit stream (tests, redirects) is written directly. Otherwise the
    label goes through :func:`narrate`, so an open tracker owns the drawing and
    a pipe gets one plain line per change.
    """

    def __init__(self, label: str, *, enabled: bool = True, stream=None) -> None:
        self.label = label
        self.enabled = enabled
        self.stream = stream
        self._token: Optional[contextvars.Token] = None

    def _say(self, text: str) -> None:
        if not self.enabled or not text:
            return
        if self.stream is not None:
            try:
                print(text, file=self.stream, flush=True)
            except (OSError, ValueError):
                pass
            return
        narrate(text)

    def __enter__(self) -> "_CompatPhase":
        if self.enabled:
            self._token = _phase_var.set(self)
            self._say(self.label)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._token is not None:
            _phase_var.reset(self._token)
            self._token = None
        return None

    def can_update(self) -> bool:
        return self.enabled

    def suspend(self) -> None:
        return None

    def resume(self) -> None:
        return None

    def update(self, label: str, *, done=None, total=None) -> None:
        # Updating the step is not the same as narrating it. A live region
        # already has the phase's name; repainting a fraction from every loop
        # would either stack lines in a log or fight the counter row. The
        # caller's real progress is expressed with counting()/advance().
        self.label = label

    def note(self, msg: str) -> None:
        self._say((msg or "").rstrip("\n"))


def phase(
    label: str,
    *,
    enabled: bool = True,
    stream=None,
    interval: float = _INTERVAL_S,
    show_after: float = _SHOW_AFTER_S,
    heartbeat: bool = True,
    clock=time.monotonic,
) -> _CompatPhase:
    """A :class:`_CompatPhase` for ``with phase(label):`` (the #407 API)."""
    return _CompatPhase(label, enabled=enabled, stream=stream)


def _compat_phase() -> Optional[_CompatPhase]:
    return _phase_var.get()


def note(msg: str) -> None:
    """A permanent line, routed into the open tracker when there is one."""
    text = (msg or "").rstrip("\n")
    if not text:
        return
    active = _compat_phase()
    if active is not None and active.enabled:
        active.note(text)
        return
    tracker = current()
    if tracker is not None and tracker.is_live:
        narrate(text)
        return
    _plain(text)


def announce(msg: str) -> None:
    """Update the live step, or print one line when nothing is live."""
    text = (msg or "").strip()
    if not text:
        return
    active = _compat_phase()
    if active is not None and active.enabled:
        active.update(text)
        return
    tracker = current()
    if tracker is not None and tracker.is_live:
        narrate(text)
        return
    _plain(text)


def update(label: str, *, done=None, total=None) -> None:
    """Point the active compat phase at the step that is actually running."""
    active = _compat_phase()
    if active is not None:
        active.update(label, done=done, total=total)
