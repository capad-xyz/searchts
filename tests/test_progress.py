# -*- coding: utf-8 -*-
"""The live status names the real step, times it for real, and then stops."""

import io
import time

import pytest

from searchts import progress


class _TTY(io.StringIO):
    def isatty(self) -> bool:
        return True


class _Boom:
    def write(self, _text: str) -> None:
        raise OSError("closed")

    def flush(self) -> None:
        raise OSError("closed")

    def isatty(self) -> bool:
        return False


def test_render_uses_real_seconds_and_a_real_fraction():
    assert progress.render("reading…") == "reading…"
    # Under a second is not "0s". A frozen zero reads as stuck.
    assert progress.render("reading…", elapsed=0.4) == "reading…"
    # Whole seconds, floored. 3.9s is three seconds so far, not four.
    assert progress.render("reading…", elapsed=3.9) == "reading… 3s"
    assert (
        progress.render("downloading assets…", done=3, total=12, elapsed=4)
        == "downloading assets… 3/12 4s"
    )
    assert "%" not in progress.render("downloading assets…", done=3, total=12)
    # No fraction unless both numbers are known.
    assert progress.render("downloading assets…", done=3) == "downloading assets…"
    assert progress.render("downloading assets…", total=12) == "downloading assets…"


def test_a_quiet_phase_is_a_finished_phase(capsys):
    """Off, or a stream that cannot be written, never raises and never prints."""
    stream = io.StringIO()
    with progress.phase("reading…", enabled=False, stream=stream):
        progress.update("still reading…")
    assert stream.getvalue() == ""
    assert capsys.readouterr().out == ""

    with progress.phase("reading…", enabled=True, stream=_Boom()):  # type: ignore[arg-type]
        progress.update("still reading…")


def test_elapsed_is_the_clock_not_the_number_of_reprints():
    """Two reprints in the same second say 1s, not 2. A new step starts over."""
    stream = io.StringIO()
    clock = {"t": 10.0}
    phase = progress.Phase(
        "reading…",
        enabled=True,
        stream=stream,
        interval=60,
        clock=lambda: clock["t"],
    )
    with phase:
        clock["t"] = 10.4
        phase._beat_once()
        assert stream.getvalue() == "reading…\n"
        clock["t"] = 13.9
        phase._beat_once()
        assert "reading… 3s\n" in stream.getvalue()
        assert "4s" not in stream.getvalue()
        # The launch took 3s. Settling has not.
        phase.update("waiting for the page to settle…")
        clock["t"] = 15.2
        phase._beat_once()
    text = stream.getvalue()
    assert "waiting for the page to settle…\n" in text
    assert "waiting for the page to settle… 1s\n" in text
    assert "waiting for the page to settle… 5s" not in text


def test_a_result_line_is_not_overwritten_by_the_step():
    stream = io.StringIO()
    clock = {"t": 0.0}
    phase = progress.Phase(
        "trying curl_cffi…",
        enabled=True,
        stream=stream,
        interval=60,
        clock=lambda: clock["t"],
    )
    with phase:
        clock["t"] = 4.0
        phase._beat_once()
        phase.note("  curl_cffi: http-403")
        clock["t"] = 9.0
        phase._beat_once()
    text = stream.getvalue()
    assert "  curl_cffi: http-403\n" in text
    assert "9s" not in text
    assert text.index("http-403") > text.index("4s")


def test_tty_rewrites_one_line_and_commits_it():
    stream = _TTY()
    with progress.phase("reading…", enabled=True, stream=stream, interval=60):
        pass
    assert stream.getvalue() == "\rreading…\033[K\n"


def test_an_inner_step_replaces_the_outer_one():
    """The outer label must not come back and claim it is still the work."""
    stream = io.StringIO()
    clock = {"t": 0.0}

    def now() -> float:
        return clock["t"]

    with progress.Phase("fetching page…", enabled=True, stream=stream, interval=60, clock=now):
        clock["t"] = 2.0
        with progress.Phase(
            "trying curl_cffi…", enabled=True, stream=stream, interval=60, clock=now
        ) as inner:
            clock["t"] = 5.0
            inner._beat_once()
        # The page phase is still open, but curl already finished. Reprinting
        # "fetching page… 5s" would be the outer step pretending it never left.
        outer = progress.current()
        assert outer is not None
        clock["t"] = 8.0
        outer._beat_once()
    text = stream.getvalue()
    assert "fetching page…\n" in text
    assert "trying curl_cffi… 3s\n" in text
    assert "fetching page… 8s" not in text


def test_a_count_changes_the_line_and_the_same_count_does_not():
    stream = io.StringIO()
    with progress.phase("downloading assets…", enabled=True, stream=stream, interval=60) as ph:
        ph.update("downloading assets…", done=1, total=4)
        ph.update("downloading assets…", done=1, total=4)
        once = stream.getvalue()
        ph.update("downloading assets…", done=2, total=4)
    text = stream.getvalue()
    assert once.count("downloading assets… 1/4") == 1
    assert "downloading assets… 2/4\n" in text
    assert "%" not in text


def test_heartbeat_stops_when_the_phase_ends():
    stream = io.StringIO()
    with progress.phase(
        "reading…", enabled=True, stream=stream, interval=0.05, show_after=0.0
    ):
        time.sleep(0.25)
        during = stream.getvalue()
    ended = stream.getvalue()
    time.sleep(0.25)
    assert stream.getvalue() == ended
    assert during.count("reading…") >= 2


def test_stdout_stays_empty(capsys):
    with progress.phase("reading…", enabled=True, interval=60):
        progress.announce("waiting for the page to render…")
        progress.note("  curl_cffi: ok")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "reading…" in captured.err
    assert "waiting for the page to render…" in captured.err
    assert "curl_cffi: ok" in captured.err


def test_browser_worker_sees_the_phase_label():
    """MCP runs the browser off the event-loop thread. The step name goes with it."""
    import asyncio

    from searchts import unlocker

    seen: dict[str, str] = {}

    def look() -> None:
        phase = progress.current()
        seen["label"] = phase.label if phase is not None else ""

    async def main() -> None:
        with progress.phase("trying stealth-browser…", enabled=True, stream=io.StringIO(), interval=60):
            unlocker._call_sync_browser(look)

    asyncio.run(main())
    assert seen["label"] == "trying stealth-browser…"


def test_read_narrates_the_rung_without_repeating_the_reason(monkeypatch, capsys):
    """The live line is the step. The reason is printed once, by the caller."""
    from searchts import unlocker

    page = "<html><body>" + ("hello " * 200) + "</body></html>"
    monkeypatch.setattr(
        unlocker, "_fetch_curl_cffi", lambda url, timeout=30: (200, page, url, {})
    )
    unlocker.fetch(
        "https://example.com/progress",
        backends=["curl_cffi"],
        use_memory=False,
        progress=True,
        echo_attempts=False,
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "trying curl_cffi…" in captured.err
    assert "curl_cffi: ok" not in captured.err

    unlocker.fetch(
        "https://example.com/progress",
        backends=["curl_cffi"],
        use_memory=False,
        progress=True,
    )
    again = capsys.readouterr()
    assert "curl_cffi: ok" in again.err
    assert again.out == ""


@pytest.mark.parametrize("flag", [False, None])
def test_read_stays_quiet_when_progress_is_off(monkeypatch, capsys, flag):
    from searchts import unlocker

    monkeypatch.delenv("SEARCHTS_PROGRESS", raising=False)
    page = "<html><body>" + ("hello " * 200) + "</body></html>"
    monkeypatch.setattr(
        unlocker, "_fetch_curl_cffi", lambda url, timeout=30: (200, page, url, {})
    )
    unlocker.fetch(
        "https://example.com/quiet",
        backends=["curl_cffi"],
        use_memory=False,
        progress=flag,
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
