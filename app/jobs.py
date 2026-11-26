"""Background job runner with two queueing policies.

Two kinds of work share one worker thread:

* **coalescible** (preview renders) — only the newest matters, so at most one
  waits and a newer one cancels the older.
* **must-run** (image/LUT export) — dropping one silently would tell the user a
  file was written when it was not, so these go into a FIFO and are never
  replaced by a newer submission of a different kind.

One thread, not two: the worker is a single GPU process per job and this
machine rasterizes in software, so running a preview and an export in parallel
only makes both slower.

Tk never reads results from the worker thread directly: the UI polls and
applies them on the main thread.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class JobSpec:
    tag: str
    coalesce_key: str
    fn: Callable[[threading.Event], Any]
    revision: int | None
    cancel_event: threading.Event
    coalesce: bool = True
    token: int | None = None


@dataclass
class JobOutcome:
    tag: str
    coalesce_key: str
    revision: int | None
    value: Any = None
    error: BaseException | None = None
    cancelled: bool = False
    elapsed_ms: float = 0.0
    token: int | None = None


class LatestJobRunner:
    def __init__(self, name: str = "job") -> None:
        self._name = name
        self._lock = threading.Condition()
        self._pending: JobSpec | None = None
        self._fifo: deque[JobSpec] = deque()
        self._current: JobSpec | None = None
        self._stopping = False
        self._results: queue.Queue[JobOutcome] = queue.Queue()
        self._thread = threading.Thread(
            target=self._run, name=f"latest-{name}", daemon=True
        )
        self._thread.start()

    def submit(
        self,
        tag: str,
        fn: Callable[[threading.Event], Any],
        *,
        coalesce_key: str = "default",
        revision: int | None = None,
        coalesce: bool = True,
        token: int | None = None,
    ) -> None:
        """Queue a task.

        ``coalesce=True`` (preview) keeps only the newest submission per key and
        cancels an in-flight task with the same key. ``coalesce=False`` (export)
        appends to a FIFO that no other submission can displace.

        ``token`` is an opaque caller-owned stamp echoed back on the outcome, so
        a UI can tell "this result belongs to the request I still care about"
        apart from a superseded one.
        """
        spec = JobSpec(
            tag, coalesce_key, fn, revision, threading.Event(), coalesce, token
        )
        with self._lock:
            if self._stopping:
                spec.cancel_event.set()
                return
            if coalesce:
                if (
                    self._pending is not None
                    and self._pending.coalesce_key == coalesce_key
                ):
                    self._pending.cancel_event.set()
                if (
                    self._current is not None
                    and self._current.coalesce_key == coalesce_key
                ):
                    self._current.cancel_event.set()
                self._pending = spec
            else:
                self._fifo.append(spec)
            self._lock.notify()

    def cancel(self, coalesce_key: str | None = None) -> None:
        with self._lock:
            if self._pending is not None and (
                coalesce_key is None or self._pending.coalesce_key == coalesce_key
            ):
                self._pending.cancel_event.set()
                self._pending = None
            if coalesce_key is None:
                for spec in self._fifo:
                    spec.cancel_event.set()
                self._fifo.clear()
            else:
                kept: deque[JobSpec] = deque()
                for spec in self._fifo:
                    if spec.coalesce_key == coalesce_key:
                        spec.cancel_event.set()
                    else:
                        kept.append(spec)
                self._fifo = kept
            if self._current is not None and (
                coalesce_key is None or self._current.coalesce_key == coalesce_key
            ):
                self._current.cancel_event.set()

    def poll(self) -> list[JobOutcome]:
        outcomes: list[JobOutcome] = []
        while True:
            try:
                outcomes.append(self._results.get_nowait())
            except queue.Empty:
                break
        return outcomes

    def queued_count(self) -> int:
        """Number of must-run tasks waiting (exports queued behind a render)."""
        with self._lock:
            return len(self._fifo)

    def is_busy(self) -> bool:
        with self._lock:
            return (
                self._current is not None
                or self._pending is not None
                or bool(self._fifo)
            )

    def shutdown(self) -> None:
        with self._lock:
            self._stopping = True
            if self._pending is not None:
                self._pending.cancel_event.set()
                self._pending = None
            for spec in self._fifo:
                spec.cancel_event.set()
            self._fifo.clear()
            if self._current is not None:
                self._current.cancel_event.set()
            self._lock.notify_all()
        self._thread.join(timeout=2.0)

    def _next_spec(self) -> JobSpec | None:
        """Exports first, then the newest coalescible task; None when stopping.

        ``_current`` is claimed under the same lock as the pop so a submission
        arriving right after cannot miss the cancellation target.
        """
        with self._lock:
            while not self._stopping:
                if self._fifo:
                    self._current = self._fifo.popleft()
                    return self._current
                if self._pending is not None:
                    self._current = self._pending
                    self._pending = None
                    return self._current
                self._lock.wait()
            return None

    def _run(self) -> None:
        while True:
            spec = self._next_spec()
            if spec is None:
                return
            started = time.monotonic()
            outcome = JobOutcome(
                tag=spec.tag,
                coalesce_key=spec.coalesce_key,
                revision=spec.revision,
                token=spec.token,
            )
            if spec.cancel_event.is_set():
                outcome.cancelled = True
            else:
                try:
                    outcome.value = spec.fn(spec.cancel_event)
                except BaseException as exc:  # reported to the UI thread
                    if spec.cancel_event.is_set():
                        outcome.cancelled = True
                    else:
                        outcome.error = exc
            outcome.elapsed_ms = (time.monotonic() - started) * 1000.0
            self._results.put(outcome)
            with self._lock:
                self._current = None
