"""Live stderr status for work that would otherwise look stuck.

P4.6: a step that can sit longer than a second narrates on stderr, never on
stdout, in plain text. The line names the step that is actually running.
If that step is still running a second later, the same words are printed
again with the real elapsed seconds. The words change only when the work
changes. There is no spinner, and no fraction unless the caller has both a
count and a total.

A terminal rewrites the current line. A pipe or a captured stream gets a
new line, so a log stays readable. A closed stderr never raises. When
progress is off, nothing is written.
"""

from __future__ import annotations

import contextvars
import sys
import threading
import time
from typing import Callable, Optional, TextIO

_current: contextvars.ContextVar[Optional["Phase"]] = contextvars.ContextVar(
    "searchts_progress_phase", default=None
)

#: How often a still-running step proves it is still running.
_INTERVAL_S = 1.0

#: Elapsed time under this is omitted. "0s" would look like a frozen counter.
_SHOW_AFTER_S = 1.0


def wanted(progress: Optional[bool]) -> bool:
    """Resolve the tri-state flag. None follows ``SEARCHTS_PROGRESS=1``."""
    import os

    if progress is None:
        return os.environ.get("SEARCHTS_PROGRESS", "") in (
            "1", "true", "True", "yes",
        )
    return bool(progress)


def render(
    label: str,
    *,
    elapsed: Optional[float] = None,
    done: Optional[int] = None,
    total: Optional[int] = None,
    show_after: float = _SHOW_AFTER_S,
) -> str:
    """The status text for one step.

    ``done`` / ``total`` are a fraction only when both are known. ``done`` is
    the item being worked on (1-based), not a guess at percent. Elapsed time
    is whole seconds of monotonic time on this step, and it is left off until
    the step has actually been running for ``show_after`` seconds.
    """
    text = (label or "").rstrip()
    if (
        done is not None
        and total is not None
        and done >= 0
        and total > 0
    ):
        text = f"{text} {done}/{total}"
    if elapsed is not None and elapsed >= show_after:
        text = f"{text} {int(elapsed)}s"
    return text


def current() -> Optional["Phase"]:
    """The phase this task is narrating, or None."""
    return _current.get()


def update(
    label: str,
    *,
    done: Optional[int] = None,
    total: Optional[int] = None,
) -> None:
    """Point the active phase at the step that is actually running.

    No active phase: nothing. A one-shot line with no phase uses :func:`note`.
    """
    phase = _current.get()
    if phase is not None:
        phase.update(label, done=done, total=total)


def note(msg: str) -> None:
    """A permanent line. A live phase is committed first so the two do not glue."""
    text = (msg or "").rstrip("\n")
    if not text:
        return
    phase = _current.get()
    if phase is not None and phase.enabled:
        phase.note(text)
        return
    _write(sys.stderr, text + "\n")


def announce(msg: str) -> None:
    """Update the live step, or print one line when nothing is live."""
    text = (msg or "").strip()
    if not text:
        return
    phase = _current.get()
    if phase is not None and phase.can_update():
        phase.update(text)
        return
    note(text)


class Phase:
    """One stderr status for one stretch of work.

    Enter prints the label at once. A daemon thread reprints it with the
    real elapsed seconds while this phase is still the one running, so a
    quiet terminal means the step finished. :meth:`update` changes the label
    to the step that is actually in progress and starts that step's clock
    over: the seconds are how long *this* step has taken, not the whole
    command. :meth:`note` prints a permanent line and stops the reprints
    until the next update, so a result is not overwritten by a stale
    "still working".

    An inner phase suspends the outer one. The outer does not resume
    heartbeats on its old label, which would claim the outer step was still
    the thing running after the inner step had replaced it.
    """

    def __init__(
        self,
        label: str,
        *,
        enabled: bool = True,
        stream: Optional[TextIO] = None,
        interval: float = _INTERVAL_S,
        show_after: float = _SHOW_AFTER_S,
        heartbeat: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.label = label
        self.enabled = enabled
        self.stream: TextIO = stream if stream is not None else sys.stderr
        self.interval = interval
        self.show_after = show_after
        self._heartbeat = heartbeat
        self._clock = clock
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._paused = False
        self._suspended = False
        self._closed = False
        self._step_started = 0.0
        self._done: Optional[int] = None
        self._total: Optional[int] = None
        self._live = False
        self._last = ""
        self._token: Optional[contextvars.Token[Optional[Phase]]] = None
        self._outer: Optional[Phase] = None

    def __enter__(self) -> "Phase":
        if not self.enabled:
            return self
        self._outer = _current.get()
        if self._outer is not None and self._outer is not self:
            self._outer.suspend()
        self._token = _current.set(self)
        self._step_started = self._clock()
        self._paint(None)
        if self._heartbeat and self.interval > 0:
            self._thread = threading.Thread(
                target=self._beat,
                name="searchts-progress",
                daemon=True,
            )
            self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: object,
    ) -> None:
        if not self.enabled or self._closed:
            return None
        self._closed = True
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=1.0)
        with self._lock:
            self._commit_locked()
        if self._token is not None:
            _current.reset(self._token)
            self._token = None
        outer = self._outer
        self._outer = None
        if outer is not None:
            outer.resume()
        return None

    def can_update(self) -> bool:
        """True when this phase is the one a sub-step should rename."""
        with self._lock:
            return self.enabled and not self._suspended and not self._closed

    def suspend(self) -> None:
        """An inner phase owns the line. Commit ours and stop reprinting it."""
        with self._lock:
            self._suspended = True
            self._commit_locked()

    def resume(self) -> None:
        """The inner phase ended. Do not reprint this phase's old label."""
        with self._lock:
            self._suspended = False
            # The label we had is no longer what is running. Stay quiet until
            # a new update names the next step, or until this phase ends.
            self._paused = True

    def update(
        self,
        label: str,
        *,
        done: Optional[int] = None,
        total: Optional[int] = None,
    ) -> None:
        """Rename the live step. The elapsed clock starts over."""
        if not self.enabled:
            return
        with self._lock:
            if self._suspended or self._closed:
                return
            same = (
                label == self.label
                and done == self._done
                and total == self._total
            )
            self._paused = False
            if same:
                return
            self._commit_locked()
            self.label = label
            self._done = done
            self._total = total
            self._step_started = self._clock()
            self._last = ""
            self._paint_locked(None)

    def note(self, msg: str) -> None:
        """Print ``msg`` as its own line and stop reprinting the live step."""
        if not self.enabled:
            return
        text = (msg or "").rstrip("\n")
        if not text:
            return
        with self._lock:
            self._paused = True
            self._commit_locked()
            _write(self.stream, text + "\n")

    def _beat(self) -> None:
        while not self._stop.wait(self.interval):
            self._beat_once()

    def _beat_once(self) -> None:
        """Reprint the current step once, if it is still the one running."""
        with self._lock:
            if (
                self._stop.is_set()
                or self._paused
                or self._suspended
                or self._closed
            ):
                return
            self._paint_locked(self._clock() - self._step_started)

    def _paint(self, elapsed: Optional[float]) -> None:
        with self._lock:
            self._paint_locked(elapsed)

    def _paint_locked(self, elapsed: Optional[float]) -> None:
        text = render(
            self.label,
            elapsed=elapsed,
            done=self._done,
            total=self._total,
            show_after=self.show_after,
        )
        if not text or text == self._last:
            return
        self._last = text
        if self._is_tty():
            _write(self.stream, "\r" + text + "\033[K")
            self._live = True
        else:
            _write(self.stream, text + "\n")
            self._live = False

    def _commit_locked(self) -> None:
        if self._live:
            _write(self.stream, "\n")
            self._live = False

    def _is_tty(self) -> bool:
        try:
            return bool(self.stream.isatty())
        except Exception:  # noqa: BLE001 - a stream with no isatty is not a tty
            return False


def phase(
    label: str,
    *,
    enabled: bool = True,
    stream: Optional[TextIO] = None,
    interval: float = _INTERVAL_S,
    show_after: float = _SHOW_AFTER_S,
    heartbeat: bool = True,
    clock: Callable[[], float] = time.monotonic,
) -> Phase:
    """A :class:`Phase` for ``with phase(label):``."""
    return Phase(
        label,
        enabled=enabled,
        stream=stream,
        interval=interval,
        show_after=show_after,
        heartbeat=heartbeat,
        clock=clock,
    )


def _write(stream: Optional[TextIO], text: str) -> None:
    if stream is None:
        return
    try:
        stream.write(text)
        stream.flush()
    except (OSError, ValueError, AttributeError):
        pass
