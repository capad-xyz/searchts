"""Tests for the live progress region.

Two contracts matter here, and they point in opposite directions. A terminal
gets motion: a repainted block, a clock that moves, rows that settle. A pipe,
a log, or CI gets exactly the lines the tool printed before this module
existed, because that is what the other test files assert on and what a
redirected stderr is for. Neither half is optional.
"""

import io
import re

import pytest

from searchts import progress

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\]8;;.*?\x1b\\")
ENV_VARS = (
    "NO_COLOR", "FORCE_COLOR", "CI", "TERM",
    "SEARCHTS_NO_PROGRESS", "SEARCHTS_PROGRESS_TTY", "SEARCHTS_PROGRESS_WIDTH",
    "SEARCHTS_FORCE_COLOR", "SEARCHTS_NO_COLOR", "SEARCHTS_NO_LINKS",
    "SEARCHTS_LINKS", "SEARCHTS_ASCII", "SEARCHTS_PROGRESS",
)


def plain(text: str) -> str:
    return ANSI.sub("", text)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    progress._set_current(None)
    yield
    progress._set_current(None)


def live(width: int = 60, subject: str = "stripe.com", ascii_only: bool = False):
    """A tracker that draws into a string, wired as the process-wide one."""
    stream = io.StringIO()
    tracker = progress.Tracker("grab", subject, stream=stream,
                               enabled=True, ascii_only=ascii_only)
    progress._set_current(tracker)
    return tracker, stream


# ── the plain half: a log, not a film ───────────────────────────────────────


def test_narration_without_a_tracker_is_the_old_log(capsys):
    progress.narrate("trying curl_cffi…")
    progress.narrate("  curl_cffi: 403 forbidden")
    progress.narrate("trying jina…")

    assert capsys.readouterr().err == (
        "trying curl_cffi…\n"
        "  curl_cffi: 403 forbidden\n"
        "trying jina…\n"
    )


def test_a_pipe_never_receives_escape_sequences(capsys):
    progress.narrate("trying curl_cffi…")
    progress.narrate("  curl_cffi: 403")
    progress.counting("downloading assets", 4)
    progress.advance(1, 100)

    assert "\x1b" not in capsys.readouterr().err


def test_counting_prints_one_line_and_advances_print_nothing(capsys):
    progress.counting("downloading assets", 22)
    progress.advance(1, 1000)
    progress.advance(1, 1000)

    assert capsys.readouterr().err == "downloading assets…\n"


def test_disabled_narration_is_silent(capsys):
    progress.narrate("trying curl_cffi…", enabled=False)
    progress.counting("downloading assets", 4, enabled=False)

    assert capsys.readouterr().err == ""


def test_a_log_gets_no_receipt():
    stream = io.StringIO()
    tracker = progress.Tracker("read", "example.com", stream=stream, enabled=False)
    tracker.summary("0.3s")
    tracker.close()

    assert stream.getvalue() == ""
    assert tracker.wants() is False


def test_wants_is_true_only_while_drawing():
    tracker, _ = live()
    assert tracker.wants() is True
    tracker.close()
    assert tracker.wants() is True  # still a terminal, just closed
    assert tracker.is_live is False


# ── the live half: motion that cannot wrap ──────────────────────────────────


def test_redraw_replaces_the_block_instead_of_appending():
    tracker, stream = live()
    tracker.stage("trying curl_cffi…")
    first = stream.getvalue()
    drawn = tracker._drawn
    assert drawn >= 3
    assert "\x1b[" in first  # erase-line, at least

    tracker.stage("trying jina…")
    second = stream.getvalue()[len(first):]
    assert second.startswith(f"\x1b[{drawn}A")
    assert second.count("\x1b[2K") >= drawn


def test_every_frame_fits_the_width(monkeypatch):
    monkeypatch.setenv("SEARCHTS_PROGRESS_WIDTH", "60")
    tracker, stream = live(subject="https://a-very-long-host.example.com/with/a/path")
    tracker.stage("trying a-rather-long-backend-name")
    tracker.detail("a detail long enough that it has to be trimmed somewhere")
    tracker.counter("downloading assets", 22)
    tracker.advance(3, 4096)
    tracker.note("a note that is also too long for sixty columns, honestly")
    tracker.close()

    lines = [line for line in plain(stream.getvalue()).splitlines() if line]
    over = [line for line in lines if len(line) > 60]
    assert over == []


def test_a_long_subject_is_trimmed_not_wrapped(monkeypatch):
    monkeypatch.setenv("SEARCHTS_PROGRESS_WIDTH", "50")
    tracker, stream = live(subject="x" * 200)
    tracker.stage("trying curl_cffi…")
    tracker.close()

    lines = [line for line in plain(stream.getvalue()).splitlines() if line]
    assert lines
    assert max(len(line) for line in lines) <= 50


def test_a_running_row_carries_a_clock():
    tracker, _ = live()
    tracker.stage("trying curl_cffi…")
    blocks = plain("\n".join(tracker._blocks()))
    assert re.search(r"\d+ms|\d\.\ds", blocks)


def test_the_bar_fills_as_items_finish():
    tracker, _ = live(width=80)
    tracker.counter("downloading assets", 4)
    empty = plain(tracker._blocks()[-1])
    tracker.advance(2, 2048)
    half = plain(tracker._blocks()[-1])

    assert "0/4" in empty
    assert "2/4" in half
    assert half.count("█") > empty.count("█")
    assert "2.0 KB" in half


def test_ascii_mode_has_no_box_drawing(monkeypatch):
    tracker, _ = live(width=80, ascii_only=True)
    tracker.stage("trying curl_cffi…")
    tracker.settle(progress.ROW_OK, "ok (200)")
    text = "\n".join(tracker._blocks())

    assert "⠋" not in text and "─" not in text and "✓" not in text
    assert "+" in plain(text)


# ── narration grammar ───────────────────────────────────────────────────────


def test_a_trying_line_opens_a_row_and_a_detail_settles_it():
    tracker, _ = live()
    progress.narrate("trying curl_cffi…")
    assert [row.label for row in tracker.rows] == ["curl_cffi"]
    assert tracker.rows[0].status == progress.ROW_RUNNING

    progress.narrate("  curl_cffi: 403 forbidden")
    assert tracker.rows[0].status == progress.ROW_FAIL
    assert tracker.rows[0].detail == "403 forbidden"


def test_a_skipped_rung_is_a_skip_not_a_failure():
    tracker, _ = live()
    progress.narrate("trying jina…")
    progress.narrate("  jina: skipped (SEARCHTS_NO_JINA)")

    assert tracker.rows[0].status == progress.ROW_SKIP


def test_an_unrecognised_reason_is_a_failure():
    """A new backend's reason must show up loudly, not match nothing quietly."""
    assert progress.classify("socket hang up") == progress.ROW_FAIL
    assert progress.classify("ok (200, 40 KB)") == progress.ROW_OK


def test_the_row_label_is_not_repeated_in_its_verdict():
    assert progress._strip_owner("known-host:reddit: miss",
                                 "known-host:reddit") == "miss"
    assert progress._strip_owner("net::ERR_FAILED", "stealth") == "net::ERR_FAILED"


def test_a_substep_attaches_to_the_running_row():
    tracker, _ = live()
    progress.narrate("trying stealth-browser…")
    progress.narrate("waiting for page to settle…")

    assert [row.label for row in tracker.rows] == ["stealth-browser"]
    assert tracker.rows[0].detail == "waiting for page to settle"


def test_a_saved_counter_advances_the_bar():
    tracker, _ = live()
    progress.counting("downloading assets", 5)
    progress.narrate("downloading assets… 4 saved")

    assert tracker.rows[-1].done == 4


def test_live_narration_does_not_also_print(capsys):
    tracker, _ = live()
    progress.narrate("trying curl_cffi…")

    assert capsys.readouterr().err == ""
    assert tracker.rows[0].label == "curl_cffi"


# ── links, colour, and small formatters ─────────────────────────────────────


def test_links_are_plain_when_disabled():
    assert progress.link_url("https://example.com", False) == "https://example.com"
    assert progress.link("label", "https://example.com", False) == "label"


def test_an_enabled_link_is_osc8_and_labelled():
    got = progress.link_url("https://example.com", True)
    assert got == (
        "\x1b]8;;https://example.com\x1b\\https://example.com\x1b]8;;\x1b\\"
    )
    assert plain(got) == "https://example.com"


def test_a_path_links_to_a_file_uri():
    got = progress.link_path(r"C:\tmp\shot.png", True)
    assert got.startswith("\x1b]8;;file:///")
    assert plain(got) == r"C:\tmp\shot.png"


def test_swatches_are_truecolor_or_nothing():
    assert progress.swatch("#635bff") == "\x1b[48;2;99;91;255m  \x1b[0m "
    assert progress.swatch("#635bff", False) == ""
    assert progress.swatch("not-a-colour") == ""


def test_fit_never_exceeds_its_width():
    assert plain(progress.fit("x" * 50, 20)) == "x" * 19 + "…"
    assert progress.fit("short", 20) == "short"
    dimmed = progress.fit("\x1b[2m" + "x" * 50 + "\x1b[0m", 20)
    assert len(plain(dimmed)) == 20


def test_sizes_and_clocks_read_like_a_person_wrote_them():
    assert progress.human_bytes(999) == "999 B"
    assert progress.human_bytes(1536) == "1.5 KB"
    assert progress.human_bytes(5 * 1024 * 1024) == "5.0 MB"
    assert progress.human_time(0.25) == "250ms"
    assert progress.human_time(2.34) == "2.3s"
    assert progress.human_time(75) == "1m15s"


def test_style_returns_its_input_when_colour_is_off():
    style = progress.Style(False)
    assert style.dim("plain") == "plain"
    assert progress.Style(True).dim("x") == "\x1b[2mx\x1b[0m"
