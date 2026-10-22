# -*- coding: utf-8 -*-
"""The shared receipt frame: a header, a mark per row, wrapped detail.

``progress.Tracker`` owns the moving block. When the command is over the block
is replaced by a receipt, and that receipt is the same grammar everywhere:
``✓ command  subject  elapsed``, then one row per fact. The glyph and its colour
come from the same place the live rows use, so a warning is ``!`` in both and
never gets painted as a green tick.

Rows are deliberately narrow. A receipt that wraps at the terminal's own width
stops being a receipt and becomes a paragraph; every line here is measured and
folded by us, like the doctor report.
"""

from __future__ import annotations

import sys
import textwrap
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple, Union

from searchts import progress


@dataclass(frozen=True)
class Row:
    status: str
    label: str
    detail: str = ""


@dataclass(frozen=True)
class Section:
    label: str


Item = Union[Row, Section]


def for_stream(stream=None) -> Tuple[progress.Style, bool]:
    """The style and glyph width a receipt on *stream* may use."""
    stream = stream or sys.stdout
    return (
        progress.Style(progress.use_color(stream)),
        progress.supports_unicode(stream),
    )


def colored_mark(style: progress.Style, status: str, unicode_ok: bool) -> str:
    glyph = progress.mark(status, unicode_ok)
    if status == progress.ROW_OK:
        return style.green(glyph)
    if status == progress.ROW_WARN:
        return style.yellow(glyph)
    if status == progress.ROW_FAIL:
        return style.red(glyph)
    return style.dim(glyph)


def header(
    style: progress.Style,
    command: str,
    *,
    subject: str = "",
    elapsed: Optional[float] = None,
    status: str = progress.ROW_OK,
    unicode_ok: bool = True,
    width: int = 76,
) -> str:
    glyph = colored_mark(style, status, unicode_ok)
    left = f"  {glyph} {style.cyan(command)}"
    if subject:
        left += "  " + style.dim(subject)
    right = style.dim(progress.human_time(elapsed)) if elapsed is not None else ""
    gap = max(2, width - progress._visible_len(left) - progress._visible_len(right) - 2)
    return progress.fit(left + " " * gap + right, width)


def _label_width(rows: Sequence[Row]) -> int:
    return min(18, max((len(row.label) for row in rows), default=0))


def row_lines(
    style: progress.Style,
    row: Row,
    *,
    unicode_ok: bool = True,
    width: int = 76,
    label_w: Optional[int] = None,
) -> List[str]:
    """One row, with every continuation under the detail column."""
    glyph = colored_mark(style, row.status, unicode_ok)
    if label_w is None:
        label_w = min(18, max(4, len(row.label)))
    label = row.label
    if len(label) > label_w:
        label = label[: max(1, label_w - 1)] + ("…" if unicode_ok else ".")
    prefix = f"  {glyph} {label.ljust(label_w)}  "
    room = max(20, width - progress._visible_len(prefix))
    detail = str(row.detail or "")
    chunks: List[str] = []
    for line in detail.splitlines() or [""]:
        if not line.strip():
            chunks.append("")
            continue
        chunks.extend(
            textwrap.wrap(
                line,
                width=room,
                break_long_words=True,
                break_on_hyphens=False,
            ) or [""]
        )
    if not chunks:
        return [prefix.rstrip()]
    out = [prefix + chunks[0]]
    pad = " " * progress._visible_len(prefix)
    out.extend((pad + chunk) if chunk else "" for chunk in chunks[1:])
    return out


def block(
    style: progress.Style,
    command: str,
    rows: Iterable[Item] = (),
    *,
    subject: str = "",
    elapsed: Optional[float] = None,
    status: str = progress.ROW_OK,
    unicode_ok: bool = True,
    width: int = 76,
    rule: bool = False,
) -> str:
    """A complete receipt: header, optional rule, rows, optional sections."""
    items = list(rows)
    plain_rows = [item for item in items if isinstance(item, Row)]
    label_w = _label_width(plain_rows)
    lines = [
        header(
            style,
            command,
            subject=subject,
            elapsed=elapsed,
            status=status,
            unicode_ok=unicode_ok,
            width=width,
        )
    ]
    if rule:
        lines.append("  " + style.dim(("─" if unicode_ok else "-") * min(width - 4, 64)))
    for item in items:
        if isinstance(item, Section):
            lines.append("")
            lines.append("  " + style.dim(item.label.upper()))
            continue
        lines.extend(
            row_lines(
                style,
                item,
                unicode_ok=unicode_ok,
                width=width,
                label_w=label_w,
            )
        )
    return "\n".join(lines)


def emit(tracker, text: str, *, stream=None) -> None:
    """Print a receipt now, or hand it to the tracker that is about to close.

    A live tracker's close clears the block and then writes the summary, which
    is what makes the ending appear exactly where the moving rows were. A pipe
    has no block to replace, so the same words are printed as plain lines.
    """
    stream = stream or sys.stdout
    if tracker is not None and tracker.is_live:
        tracker.summary(text)
        return
    print(text, file=stream)


def one_line(text: str) -> str:
    """Collapse a channel sentence to the one line a live row can hold."""
    return " ".join(str(text or "").split())


def summary(text: str, limit: int = 72) -> str:
    """The first sentence of a long channel message, fitted to one receipt row.

    The doctor report is where the full fix belongs. A watch receipt that
    repeats a multi-line install command stops being a summary and becomes a
    second, worse copy of the report.
    """
    line = one_line(text)
    cut = len(line)
    for mark in (". ", "! ", "? "):
        at = line.find(mark)
        if 0 <= at < cut:
            cut = at + 1
    line = line[:cut].strip()
    if len(line) <= limit:
        return line
    return line[: max(1, limit - 1)].rstrip(" ,;:") + "…"
