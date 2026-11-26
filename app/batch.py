"""Batch workspace model and scheduler (phase B, logic layer).

This module deliberately contains no Tk import and no rendering code. It owns
three things:

* the immutable batch description (:class:`BatchItem`, :class:`OutputPlan`),
* the frozen per-task snapshot the worker receives (:class:`BatchTaskSnapshot`),
* a single-consumer FIFO scheduler with per-item cancellation.

The UI thread owns :class:`BatchState`. Worker threads only ever see frozen
snapshots and only produce :class:`BatchUpdate` values; they never touch Tk
state or the mutable records. That split is what keeps cancellation and
progress reporting safe without a lock around the UI.

Cancellation has three distinct operations, matching the product rules:

``cancel_item``      cancel one item, whether queued or currently running.
``cancel_pending``   cancel everything not yet started, keep the current item.
``cancel_all``       both of the above.

All three are idempotent: a second call never produces a second terminal
update, and an item that already finished is never rewritten as cancelled.
"""

from __future__ import annotations

import itertools
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from queue import Empty, Queue
from typing import Callable, Iterable

from baker.params import ColorParams

TOKEN_COUNTER = itertools.count(1)


class MediaKind(str, Enum):
    IMAGE = "image"
    VIDEO = "video"


class ItemStatus(str, Enum):
    """Batch item states, in the user-facing order of the list."""

    PENDING = "pending"        # 待处理
    PREPARING = "preparing"    # 准备中
    RUNNING = "running"        # 处理中
    DONE = "done"              # 已完成
    FAILED = "failed"          # 失败
    CANCELLED = "cancelled"    # 已取消
    SKIPPED = "skipped"        # 已跳过


TERMINAL_STATUSES = frozenset(
    {ItemStatus.DONE, ItemStatus.FAILED, ItemStatus.CANCELLED, ItemStatus.SKIPPED}
)

# Retry sends a terminal-but-unsuccessful item back to the queue; a finished
# item is never re-run implicitly.
_TRANSITIONS: dict[ItemStatus, frozenset[ItemStatus]] = {
    ItemStatus.PENDING: frozenset(
        {ItemStatus.PREPARING, ItemStatus.RUNNING, ItemStatus.CANCELLED,
         ItemStatus.SKIPPED, ItemStatus.FAILED}
    ),
    ItemStatus.PREPARING: frozenset(
        {ItemStatus.RUNNING, ItemStatus.CANCELLED, ItemStatus.FAILED,
         ItemStatus.SKIPPED}
    ),
    ItemStatus.RUNNING: frozenset(
        {ItemStatus.DONE, ItemStatus.FAILED, ItemStatus.CANCELLED}
    ),
    ItemStatus.FAILED: frozenset({ItemStatus.PENDING}),
    ItemStatus.CANCELLED: frozenset({ItemStatus.PENDING}),
    ItemStatus.SKIPPED: frozenset({ItemStatus.PENDING}),
    ItemStatus.DONE: frozenset(),
}


def can_transition(current: ItemStatus, target: ItemStatus) -> bool:
    if current is target:
        return True
    return target in _TRANSITIONS.get(current, frozenset())


class Strategy(str, Enum):
    """How a batch starts out. Not a lock-in: items can always be overridden."""

    UNIFORM = "uniform"        # 统一参数
    PER_ITEM = "per_item"      # 逐项微调
    REFERENCE = "reference"    # 参考素材协调（阶段 C，占位）


class ConflictPolicy(str, Enum):
    SKIP = "skip"
    RENAME = "rename"
    OVERWRITE = "overwrite"


class BatchPlanError(Exception):
    """Batch-level problem that prevents planning any item."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class OutputPlan:
    """Where results go and how they are named."""

    directory: Path
    image_suffix: str = ".png"
    image_quality: int = 95
    video_suffix: str = ".mp4"
    video_quality: int = 18
    video_preset: str = "medium"
    suffix_label: str = "_graded"
    conflict: ConflictPolicy = ConflictPolicy.SKIP

    def __post_init__(self) -> None:
        for suffix in (self.image_suffix, self.video_suffix):
            if not suffix.startswith("."):
                raise BatchPlanError("OUTPUT_INVALID", f"扩展名必须以 . 开头：{suffix}")
        if not 1 <= self.image_quality <= 100:
            raise BatchPlanError("OUTPUT_INVALID", "图片质量需在 1-100 之间")
        if not 0 <= self.video_quality <= 51:
            raise BatchPlanError("OUTPUT_INVALID", "视频 CRF 需在 0-51 之间")


def _fingerprint(path: Path) -> tuple[int, int]:
    """``(size, mtime_ns)`` for change detection; ``(0, 0)`` when unknown."""
    try:
        info = path.stat()
    except OSError:
        return 0, 0
    return int(info.st_size), int(info.st_mtime_ns)


@dataclass(frozen=True)
class BatchItem:
    """The immutable description of one source in a batch."""

    item_id: str
    source: Path
    kind: MediaKind
    override: ColorParams | None = None
    lut_path: Path | None = None
    strength: float = 1.0
    added_at: float = field(default_factory=time.time)
    # Fingerprint taken at import time. ``0`` means "unknown" (the file was
    # already missing), which disables change detection for that item instead
    # of inventing a failure.
    source_size: int = 0
    source_mtime_ns: int = 0

    @classmethod
    def create(
        cls,
        source: Path | str,
        kind: MediaKind,
        *,
        override: ColorParams | None = None,
        lut_path: Path | None = None,
        strength: float = 1.0,
    ) -> "BatchItem":
        path = Path(source)
        size, mtime_ns = _fingerprint(path)
        return cls(
            item_id=uuid.uuid4().hex[:12],
            source=path,
            kind=kind,
            override=override,
            lut_path=lut_path,
            strength=strength,
            source_size=size,
            source_mtime_ns=mtime_ns,
        )

    def with_override(self, params: ColorParams | None) -> "BatchItem":
        return replace(self, override=params)


@dataclass(frozen=True)
class BatchTaskSnapshot:
    """What one worker task is allowed to read. Frozen when the item starts."""

    batch_id: str
    item_id: str
    source: Path
    kind: MediaKind
    params: ColorParams
    strength: float
    lut_path: Path | None
    target: Path
    strategy: Strategy
    token: int
    policy_version: int = 1
    image_quality: int = 95
    video_quality: int = 18
    video_preset: str = "medium"


@dataclass
class BatchRecord:
    """Mutable per-item runtime state. Only the owner (UI) thread touches it."""

    item_id: str
    status: ItemStatus = ItemStatus.PENDING
    progress: float = 0.0
    output: Path | None = None
    error_code: str = ""
    error_message: str = ""
    skip_reason: str = ""
    attempts: int = 0
    started_at: float | None = None
    finished_at: float | None = None


@dataclass(frozen=True)
class BatchPlan:
    """Result of planning: what will run, what is skipped, what already failed."""

    batch_id: str
    snapshots: tuple[BatchTaskSnapshot, ...]
    skipped: dict[str, str] = field(default_factory=dict)
    errors: dict[str, tuple[str, str]] = field(default_factory=dict)


def _norm(path: Path) -> str:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()
    return os.path.normcase(str(resolved))


def same_path(left: Path, right: Path) -> bool:
    return _norm(left) == _norm(right)


@dataclass
class BatchState:
    """The batch the user is editing. Not a document: it never owns pixels."""

    batch_id: str
    strategy: Strategy
    baseline: ColorParams | None
    output: OutputPlan
    items: list[BatchItem] = field(default_factory=list)
    records: dict[str, BatchRecord] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        strategy: Strategy,
        baseline: ColorParams | None,
        output: OutputPlan,
    ) -> "BatchState":
        return cls(
            batch_id=uuid.uuid4().hex[:12],
            strategy=strategy,
            baseline=baseline,
            output=output,
        )

    # -- structure -----------------------------------------------------

    def add_item(self, item: BatchItem) -> BatchRecord:
        if item.item_id in self.records:
            raise ValueError(f"重复的 item_id：{item.item_id}")
        for existing in self.items:
            if same_path(existing.source, item.source) and existing.kind is item.kind:
                raise ValueError(f"素材已在批次中：{item.source.name}")
        self.items.append(item)
        record = BatchRecord(item_id=item.item_id)
        self.records[item.item_id] = record
        return record

    def item(self, item_id: str) -> BatchItem:
        for candidate in self.items:
            if candidate.item_id == item_id:
                return candidate
        raise KeyError(item_id)

    def record(self, item_id: str) -> BatchRecord:
        return self.records[item_id]

    def remove_item(self, item_id: str) -> bool:
        """Remove an item that has not started. Started items are never dropped."""
        record = self.records.get(item_id)
        if record is None or record.status is not ItemStatus.PENDING:
            return False
        self.items = [i for i in self.items if i.item_id != item_id]
        del self.records[item_id]
        return True

    def set_override(self, item_id: str, params: ColorParams | None) -> None:
        for index, item in enumerate(self.items):
            if item.item_id == item_id:
                self.items[index] = item.with_override(params)
                return
        raise KeyError(item_id)

    def apply_baseline(self, params: ColorParams, *, only_uncovered: bool = True) -> int:
        """Update the shared baseline; returns how many items changed.

        With ``only_uncovered`` (the default) items that already carry their own
        parameters keep them. Overriding a per-item choice silently is exactly
        the "quietly modified another item" behaviour the rules forbid. Passing
        ``False`` is the explicit "apply to every item" action: it clears the
        per-item overrides so the new baseline actually reaches them.
        """
        self.baseline = params
        if only_uncovered:
            return 0
        changed = 0
        for index, item in enumerate(self.items):
            if item.override is not None:
                self.items[index] = item.with_override(None)
                changed += 1
        return changed

    def apply_plan(self, plan: "BatchPlan") -> None:
        """Record the planner's per-item outcomes without running anything."""
        now = time.time()
        for item_id, reason in plan.skipped.items():
            record = self.records.get(item_id)
            if record is None or not can_transition(record.status, ItemStatus.SKIPPED):
                continue
            record.status = ItemStatus.SKIPPED
            record.skip_reason = reason
            record.finished_at = now
        for item_id, (code, message) in plan.errors.items():
            record = self.records.get(item_id)
            if record is None or not can_transition(record.status, ItemStatus.FAILED):
                continue
            record.status = ItemStatus.FAILED
            record.error_code = code
            record.error_message = message
            record.finished_at = now

    def effective_params(self, item_id: str) -> ColorParams | None:
        item = self.item(item_id)
        return item.override if item.override is not None else self.baseline

    def retry(self, item_id: str) -> bool:
        """Send a failed/cancelled/skipped item back to pending."""
        record = self.records[item_id]
        if record.status not in (
            ItemStatus.FAILED,
            ItemStatus.CANCELLED,
            ItemStatus.SKIPPED,
        ):
            return False
        record.status = ItemStatus.PENDING
        record.progress = 0.0
        record.error_code = ""
        record.error_message = ""
        record.skip_reason = ""
        record.output = None
        record.finished_at = None
        return True

    def apply_update(self, update: "BatchUpdate") -> bool:
        """Apply a runner update on the owner thread. Idempotent by design."""
        record = self.records.get(update.item_id)
        if record is None:
            return False
        if update.status is record.status:
            if update.kind is UpdateKind.PROGRESS:
                # Progress never moves backwards, even if an update arrives late.
                record.progress = max(record.progress, update.progress)
                return True
            return False
        if not can_transition(record.status, update.status):
            return False
        record.status = update.status
        if update.kind is UpdateKind.PROGRESS:
            record.progress = max(record.progress, update.progress)
            return True
        if update.status is ItemStatus.RUNNING:
            record.started_at = update.at
            record.attempts += 1
        if update.status in TERMINAL_STATUSES:
            record.finished_at = update.at
            record.progress = 1.0 if update.status is ItemStatus.DONE else record.progress
            record.output = update.output
            record.error_code = update.error_code
            record.error_message = update.error_message
            record.skip_reason = update.skip_reason
        return True


# ----------------------------------------------------------------------
# planning
# ----------------------------------------------------------------------


def _suffix_for(kind: MediaKind, output: OutputPlan) -> str:
    return output.image_suffix if kind is MediaKind.IMAGE else output.video_suffix


def _candidate_name(item: BatchItem, output: OutputPlan, ordinal: int) -> str:
    stem = f"{item.source.stem}{output.suffix_label}"
    if ordinal > 1:
        stem += f"-{ordinal}"
    return stem + _suffix_for(item.kind, output)


def plan_target(
    item: BatchItem,
    output: OutputPlan,
    *,
    taken: Iterable[str] = (),
) -> tuple[Path | None, str]:
    """Resolve one item's output path.

    Returns ``(path, "")`` for a usable target, or ``(None, reason)`` when the
    item must be skipped. Never returns a path equal to the source, and never
    silently overwrites: overwriting requires ``ConflictPolicy.OVERWRITE``.
    """
    directory = output.directory
    reserved = {_norm(Path(t)) for t in taken}
    source_key = _norm(item.source)
    ordinal = 1
    while True:
        target = directory / _candidate_name(item, output, ordinal)
        if _norm(target) == source_key:
            return None, "目标与源文件相同，拒绝覆盖源素材"
        if _norm(target) in reserved or target.exists():
            if output.conflict is ConflictPolicy.SKIP:
                return None, f"目标已存在：{target.name}"
            if output.conflict is ConflictPolicy.OVERWRITE:
                return target, ""
            ordinal += 1
            if ordinal > 9999:
                return None, "无法生成不冲突的文件名"
            continue
        return target, ""


def plan_batch(batch: BatchState) -> BatchPlan:
    """Freeze every runnable item into a snapshot.

    Missing sources, missing parameters and unusable targets are reported per
    item so the rest of the queue can continue; only a broken output directory
    or a duplicate source aborts the whole plan.
    """
    output = batch.output
    if not output.directory.is_dir():
        raise BatchPlanError(
            "OUTPUT_MISSING", f"输出目录不存在：{output.directory}"
        )

    snapshots: list[BatchTaskSnapshot] = []
    skipped: dict[str, str] = {}
    errors: dict[str, tuple[str, str]] = {}
    taken: list[str] = []

    for item in batch.items:
        record = batch.records.get(item.item_id)
        # Only pending items are planned. Failed/cancelled/skipped items come
        # back through an explicit retry, so re-planning never silently reruns
        # something the user already saw finish or explicitly cancelled.
        if record is not None and record.status is not ItemStatus.PENDING:
            continue
        if not item.source.is_file():
            errors[item.item_id] = ("SOURCE_MISSING", f"源文件不存在：{item.source.name}")
            continue
        if item.source_size:
            size, mtime_ns = _fingerprint(item.source)
            if (size, mtime_ns) != (item.source_size, item.source_mtime_ns):
                errors[item.item_id] = (
                    "SOURCE_CHANGED",
                    "源文件在导入后已变化，请移除该项后重新添加",
                )
                continue
        params = item.override if item.override is not None else batch.baseline
        if params is None:
            errors[item.item_id] = ("PARAMS_MISSING", "该项没有参数，也没有统一参数基线")
            continue
        target, reason = plan_target(item, output, taken=taken)
        if target is None:
            skipped[item.item_id] = reason
            continue
        taken.append(str(target))
        snapshots.append(
            BatchTaskSnapshot(
                batch_id=batch.batch_id,
                item_id=item.item_id,
                source=item.source,
                kind=item.kind,
                params=params,
                strength=item.strength,
                lut_path=item.lut_path,
                target=target,
                strategy=batch.strategy,
                token=next(TOKEN_COUNTER),
                image_quality=output.image_quality,
                video_quality=output.video_quality,
                video_preset=output.video_preset,
            )
        )
    return BatchPlan(
        batch_id=batch.batch_id,
        snapshots=tuple(snapshots),
        skipped=skipped,
        errors=errors,
    )


# ----------------------------------------------------------------------
# scheduler
# ----------------------------------------------------------------------


class BatchCancelled(Exception):
    """Raised by a worker that noticed its cancel event and stopped cleanly."""


class UpdateKind(str, Enum):
    QUEUED = "queued"
    STARTED = "started"
    PROGRESS = "progress"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


_STATUS_FOR_KIND = {
    UpdateKind.QUEUED: ItemStatus.PENDING,
    UpdateKind.STARTED: ItemStatus.RUNNING,
    UpdateKind.PROGRESS: ItemStatus.RUNNING,
    UpdateKind.DONE: ItemStatus.DONE,
    UpdateKind.FAILED: ItemStatus.FAILED,
    UpdateKind.CANCELLED: ItemStatus.CANCELLED,
    UpdateKind.SKIPPED: ItemStatus.SKIPPED,
}


@dataclass(frozen=True)
class BatchUpdate:
    item_id: str
    token: int
    kind: UpdateKind
    status: ItemStatus
    progress: float = 0.0
    output: Path | None = None
    error_code: str = ""
    error_message: str = ""
    skip_reason: str = ""
    at: float = field(default_factory=time.time)


ProgressFn = Callable[[float], None]
WorkerFn = Callable[[BatchTaskSnapshot, threading.Event, ProgressFn], Path]


def _update(
    snapshot: BatchTaskSnapshot | None,
    kind: UpdateKind,
    *,
    item_id: str = "",
    token: int = 0,
    **kwargs,
) -> BatchUpdate:
    if snapshot is not None:
        item_id, token = snapshot.item_id, snapshot.token
    return BatchUpdate(
        item_id=item_id,
        token=token,
        kind=kind,
        status=_STATUS_FOR_KIND[kind],
        **kwargs,
    )


class BatchRunner:
    """One worker thread, one task at a time, FIFO in submit order.

    Preview work is not part of this runner. The batch queue is allowed to be
    slow; what it must not do is lose a task or race two heavy renders.
    """

    def __init__(self, worker: WorkerFn) -> None:
        self._worker = worker
        self._lock = threading.Lock()
        self._pending: deque[BatchTaskSnapshot] = deque()
        self._pending_ids: set[str] = set()
        self._current: BatchTaskSnapshot | None = None
        self._current_cancel: threading.Event | None = None
        self._cancel_requested: set[str] = set()
        self._finished_ids: set[str] = set()
        self._updates: Queue[BatchUpdate] = Queue()
        self._thread: threading.Thread | None = None
        self._closing = False

    # -- queue ---------------------------------------------------------

    def submit(self, snapshots: Iterable[BatchTaskSnapshot]) -> int:
        accepted: list[BatchTaskSnapshot] = []
        with self._lock:
            if self._closing:
                raise RuntimeError("批处理已关闭")
            for snapshot in snapshots:
                if snapshot.item_id in self._pending_ids:
                    continue
                if snapshot.item_id in self._finished_ids:
                    continue
                if self._current is not None and snapshot.item_id == self._current.item_id:
                    continue
                self._pending.append(snapshot)
                self._pending_ids.add(snapshot.item_id)
                accepted.append(snapshot)
            for snapshot in accepted:
                self._updates.put(_update(snapshot, UpdateKind.QUEUED))
            if accepted and (self._thread is None or not self._thread.is_alive()):
                self._thread = threading.Thread(
                    target=self._run, name="batch-worker", daemon=True
                )
                self._thread.start()
        return len(accepted)

    def queued_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def is_running(self) -> bool:
        with self._lock:
            return self._current is not None

    def is_idle(self) -> bool:
        """True when nothing is queued and nothing is executing.

        This is the completion signal for the UI. Checking ``is_running`` alone
        races with thread startup: right after ``submit`` the item may still be
        sitting in the pending deque with no current item yet.
        """
        with self._lock:
            return self._current is None and not self._pending

    def current_item_id(self) -> str | None:
        with self._lock:
            return self._current.item_id if self._current is not None else None

    def poll(self) -> list[BatchUpdate]:
        updates: list[BatchUpdate] = []
        while True:
            try:
                updates.append(self._updates.get_nowait())
            except Empty:
                return updates

    # -- cancellation --------------------------------------------------

    def cancel_item(self, item_id: str) -> bool:
        """Cancel one item, queued or running. Second call is a no-op."""
        with self._lock:
            if item_id in self._finished_ids or item_id in self._cancel_requested:
                return False
            if item_id in self._pending_ids:
                self._cancel_requested.add(item_id)
                snapshot = self._remove_pending(item_id)
                self._finished_ids.add(item_id)
                if snapshot is not None:
                    self._updates.put(
                        _update(snapshot, UpdateKind.CANCELLED)
                    )
                return True
            if self._current is not None and self._current.item_id == item_id:
                self._cancel_requested.add(item_id)
                if self._current_cancel is not None:
                    self._current_cancel.set()
                return True
            return False

    def cancel_pending(self) -> int:
        """Cancel everything not started. The running item keeps going."""
        with self._lock:
            cancelled: list[BatchTaskSnapshot] = []
            while self._pending:
                snapshot = self._pending.popleft()
                self._pending_ids.discard(snapshot.item_id)
                self._cancel_requested.add(snapshot.item_id)
                self._finished_ids.add(snapshot.item_id)
                cancelled.append(snapshot)
            for snapshot in cancelled:
                self._updates.put(_update(snapshot, UpdateKind.CANCELLED))
            return len(cancelled)

    def cancel_all(self) -> int:
        """Cancel the running item and every queued item."""
        count = self.cancel_pending()
        current = self.current_item_id()
        if current is not None and self.cancel_item(current):
            count += 1
        return count

    def shutdown(self, timeout: float = 5.0) -> bool:
        """Stop accepting work, cancel everything, and wait for the thread.

        Returns True when the worker thread exited within ``timeout``. False
        means a subprocess is still running; the caller must say so rather than
        claim the batch was cleaned up.
        """
        with self._lock:
            self._closing = True
        self.cancel_all()
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    # -- internals -----------------------------------------------------

    def _remove_pending(self, item_id: str) -> BatchTaskSnapshot | None:
        for snapshot in list(self._pending):
            if snapshot.item_id == item_id:
                self._pending.remove(snapshot)
                self._pending_ids.discard(item_id)
                return snapshot
        return None

    def _next_snapshot(self) -> BatchTaskSnapshot | None:
        with self._lock:
            if self._closing:
                self._current = None
                self._current_cancel = None
                return None
            if not self._pending:
                self._current = None
                self._current_cancel = None
                return None
            snapshot = self._pending.popleft()
            self._pending_ids.discard(snapshot.item_id)
            self._current = snapshot
            self._current_cancel = threading.Event()
            return snapshot

    def _run(self) -> None:
        while True:
            snapshot = self._next_snapshot()
            if snapshot is None:
                return
            cancel = self._current_cancel
            assert cancel is not None
            self._updates.put(_update(snapshot, UpdateKind.STARTED))
            last_tick = [-1]

            def report(value: float, _snapshot=snapshot, _last=last_tick) -> None:
                value = min(1.0, max(0.0, float(value)))
                tick = int(value * 100)
                if tick == _last[0]:
                    return
                _last[0] = tick
                self._updates.put(
                    _update(_snapshot, UpdateKind.PROGRESS, progress=value)
                )

            try:
                output = self._worker(snapshot, cancel, report)
            except BatchCancelled:
                self._finish(snapshot, UpdateKind.CANCELLED)
            except Exception as exc:  # worker failure must not stop the queue
                # The engine/ffmpeg layers signal cancellation with their own
                # error type; a cancelled item is not a failed one.
                if getattr(exc, "code", "") == "CANCELLED":
                    self._finish(snapshot, UpdateKind.CANCELLED)
                else:
                    self._finish(
                        snapshot,
                        UpdateKind.FAILED,
                        error_code=getattr(exc, "code", "BATCH_FAILED")
                        or "BATCH_FAILED",
                        error_message=str(exc) or exc.__class__.__name__,
                    )
            else:
                if cancel.is_set():
                    self._finish(snapshot, UpdateKind.CANCELLED)
                else:
                    self._finish(snapshot, UpdateKind.DONE, output=Path(output))

    def _finish(
        self,
        snapshot: BatchTaskSnapshot,
        kind: UpdateKind,
        *,
        output: Path | None = None,
        error_code: str = "",
        error_message: str = "",
    ) -> None:
        with self._lock:
            self._finished_ids.add(snapshot.item_id)
            self._cancel_requested.discard(snapshot.item_id)
            if self._current is not None and self._current.item_id == snapshot.item_id:
                self._current = None
                self._current_cancel = None
        self._updates.put(
            _update(
                snapshot,
                kind,
                output=output,
                error_code=error_code,
                error_message=error_message,
            )
        )


def detect_kind(path: Path | str) -> MediaKind:
    """Classify a path without importing the heavy media modules."""
    from . import video_io

    return (
        MediaKind.VIDEO
        if Path(path).suffix.lower() in video_io.VIDEO_SUFFIXES
        else MediaKind.IMAGE
    )
