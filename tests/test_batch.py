"""Batch model, planner and scheduler tests (phase B logic layer).

No Tk, no engine subprocess, no real media: the workers are stubs, so these
tests are about queue semantics and state transitions. End-to-end runs with
real decoding live in ``runtime/``.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path

from app import batch
from app.batch import (
    BatchCancelled,
    BatchItem,
    BatchPlanError,
    BatchRunner,
    BatchState,
    BatchTaskSnapshot,
    ConflictPolicy,
    ItemStatus,
    MediaKind,
    OutputPlan,
    Strategy,
    UpdateKind,
    can_transition,
    plan_batch,
    plan_target,
)
from baker.params import ColorParams


def _token() -> int:
    return next(batch.TOKEN_COUNTER)


def _snapshot(
    item_id: str,
    *,
    target: Path | None = None,
    token: int | None = None,
) -> BatchTaskSnapshot:
    return BatchTaskSnapshot(
        batch_id="batch-test",
        item_id=item_id,
        source=Path(item_id + ".jpg"),
        kind=MediaKind.IMAGE,
        params=ColorParams(),
        strength=1.0,
        lut_path=None,
        target=target or Path(f"{item_id}_graded.png"),
        strategy=Strategy.UNIFORM,
        token=token if token is not None else _token(),
    )


def _wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


class _StubWorker:
    """Records execution order and concurrency, with optional gates."""

    def __init__(
        self,
        *,
        fail: tuple[str, ...] = (),
        gates: dict[str, threading.Event] | None = None,
        cooperative: bool = True,
        delay: float = 0.0,
    ) -> None:
        self.fail = set(fail)
        self.gates = gates or {}
        self.cooperative = cooperative
        self.delay = delay
        self.order: list[str] = []
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def __call__(self, snapshot, cancel, report) -> Path:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.order.append(snapshot.item_id)
        try:
            report(0.1)
            report(0.1)  # duplicate tick: must not produce a second update
            gate = self.gates.get(snapshot.item_id)
            if gate is not None:
                if self.cooperative:
                    while not gate.is_set():
                        if cancel.wait(0.005):
                            raise BatchCancelled()
                else:
                    gate.wait(5.0)
            if self.delay:
                time.sleep(self.delay)
            if snapshot.item_id in self.fail:
                raise RuntimeError("boom")
            report(0.5)
            if self.cooperative and cancel.is_set():
                raise BatchCancelled()
            report(1.0)
            return snapshot.target
        finally:
            with self._lock:
                self.active -= 1


class _BatchFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = Path(tempfile.mkdtemp(prefix="batch-test-"))
        self.addCleanup(shutil.rmtree, self._dir, ignore_errors=True)

    def _file(self, name: str, payload: bytes = b"x" * 32) -> Path:
        path = self._dir / "in" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def _output(self, **kwargs) -> OutputPlan:
        out = self._dir / "out"
        out.mkdir(exist_ok=True)
        return OutputPlan(directory=out, **kwargs)

    def _batch(self, sources: list[Path], **kwargs) -> BatchState:
        state = BatchState.create(
            strategy=kwargs.pop("strategy", Strategy.UNIFORM),
            baseline=kwargs.pop("baseline", ColorParams()),
            output=kwargs.pop("output", self._output()),
        )
        for index, source in enumerate(sources):
            state.add_item(
                BatchItem.create(
                    source,
                    MediaKind.IMAGE,
                    override=kwargs.get("overrides", (None,) * len(sources))[index],
                )
            )
        return state


class BatchModelTests(_BatchFixture):
    def test_uniform_baseline_is_used_when_item_has_no_override(self) -> None:
        baseline = ColorParams(contrast=12.0)
        state = self._batch([self._file("a.jpg")], baseline=baseline)
        item_id = state.items[0].item_id
        self.assertIs(state.effective_params(item_id), baseline)

    def test_override_wins_without_touching_other_items(self) -> None:
        a = self._file("a.jpg")
        b = self._file("b.jpg")
        baseline = ColorParams(contrast=5.0)
        state = self._batch([a, b], baseline=baseline)
        first, second = (item.item_id for item in state.items)
        override = ColorParams(contrast=40.0)
        state.set_override(first, override)

        self.assertEqual(state.effective_params(first), override)
        self.assertIs(state.effective_params(second), baseline)
        self.assertIs(state.item(second).override, None)

    def test_updating_the_baseline_leaves_covered_items_alone(self) -> None:
        state = self._batch([self._file("a.jpg"), self._file("b.jpg")])
        first = state.items[0].item_id
        override = ColorParams(saturation=20.0)
        state.set_override(first, override)

        state.apply_baseline(ColorParams(contrast=9.0))
        self.assertEqual(state.effective_params(first), override)
        self.assertEqual(state.effective_params(state.items[1].item_id).contrast, 9.0)

    def test_applying_the_baseline_to_all_items_is_explicit(self) -> None:
        state = self._batch([self._file("a.jpg"), self._file("b.jpg")])
        for item in state.items:
            state.set_override(item.item_id, ColorParams(contrast=30.0))

        changed = state.apply_baseline(ColorParams(contrast=3.0), only_uncovered=False)
        self.assertEqual(changed, 2)
        for item in state.items:
            self.assertIsNone(item.override)
            self.assertEqual(state.effective_params(item.item_id).contrast, 3.0)

    def test_duplicate_source_is_rejected(self) -> None:
        source = self._file("a.jpg")
        state = self._batch([source])
        with self.assertRaises(ValueError):
            state.add_item(BatchItem.create(source, MediaKind.IMAGE))

    def test_remove_only_removes_items_that_have_not_started(self) -> None:
        state = self._batch([self._file("a.jpg"), self._file("b.jpg")])
        first, second = (item.item_id for item in state.items)
        self.assertTrue(state.remove_item(first))
        self.assertEqual(len(state.items), 1)
        self.assertFalse(state.remove_item(first))

        state.records[second].status = ItemStatus.RUNNING
        self.assertFalse(state.remove_item(second))

    def test_retry_resets_failed_items_only(self) -> None:
        state = self._batch([self._file("a.jpg"), self._file("b.jpg")])
        failed, done = (item.item_id for item in state.items)
        state.records[failed].status = ItemStatus.FAILED
        state.records[failed].error_code = "BOOM"
        state.records[done].status = ItemStatus.DONE

        self.assertTrue(state.retry(failed))
        self.assertEqual(state.records[failed].status, ItemStatus.PENDING)
        self.assertEqual(state.records[failed].error_code, "")
        self.assertFalse(state.retry(done))
        self.assertEqual(state.records[done].status, ItemStatus.DONE)

    def test_progress_never_moves_backwards(self) -> None:
        state = self._batch([self._file("a.jpg")])
        item_id = state.items[0].item_id
        state.records[item_id].status = ItemStatus.RUNNING
        state.apply_update(
            batch.BatchUpdate(
                item_id, 1, UpdateKind.PROGRESS, ItemStatus.RUNNING, progress=0.7
            )
        )
        state.apply_update(
            batch.BatchUpdate(
                item_id, 1, UpdateKind.PROGRESS, ItemStatus.RUNNING, progress=0.2
            )
        )
        self.assertEqual(state.records[item_id].progress, 0.7)

    def test_a_finished_item_is_never_reported_as_cancelled(self) -> None:
        state = self._batch([self._file("a.jpg")])
        item_id = state.items[0].item_id
        state.records[item_id].status = ItemStatus.DONE
        applied = state.apply_update(
            batch.BatchUpdate(
                item_id, 1, UpdateKind.CANCELLED, ItemStatus.CANCELLED
            )
        )
        self.assertFalse(applied)
        self.assertEqual(state.records[item_id].status, ItemStatus.DONE)
        self.assertFalse(can_transition(ItemStatus.DONE, ItemStatus.CANCELLED))


class BatchPlanTests(_BatchFixture):
    def test_target_keeps_the_stem_and_uses_the_kind_suffix(self) -> None:
        source = self._file("holiday.jpg")
        state = self._batch([source])
        plan = plan_batch(state)
        self.assertEqual(len(plan.snapshots), 1)
        self.assertEqual(plan.snapshots[0].target.name, "holiday_graded.png")

    def test_video_items_use_the_video_suffix(self) -> None:
        source = self._file("clip.mp4")
        state = BatchState.create(Strategy.UNIFORM, ColorParams(), self._output())
        state.add_item(BatchItem.create(source, MediaKind.VIDEO))
        plan = plan_batch(state)
        self.assertEqual(plan.snapshots[0].target.name, "clip_graded.mp4")

    def test_existing_target_is_skipped_by_default(self) -> None:
        source = self._file("a.jpg")
        state = self._batch([source])
        existing = state.output.directory / "a_graded.png"
        existing.write_bytes(b"old")

        plan = plan_batch(state)
        self.assertEqual(plan.snapshots, ())
        self.assertIn("目标已存在", plan.skipped[state.items[0].item_id])

        state.apply_plan(plan)
        self.assertEqual(state.records[state.items[0].item_id].status, ItemStatus.SKIPPED)
        self.assertEqual(existing.read_bytes(), b"old")

    def test_rename_policy_picks_the_next_free_name(self) -> None:
        source = self._file("a.jpg")
        state = self._batch([source], output=self._output(conflict=ConflictPolicy.RENAME))
        (state.output.directory / "a_graded.png").write_bytes(b"old")

        plan = plan_batch(state)
        self.assertEqual(plan.snapshots[0].target.name, "a_graded-2.png")

    def test_rename_avoids_collisions_inside_the_batch(self) -> None:
        first = self._file("a.jpg")
        second = self._dir / "in2" / "a.jpg"
        second.parent.mkdir(parents=True, exist_ok=True)
        second.write_bytes(b"y")
        state = BatchState.create(
            Strategy.UNIFORM, ColorParams(), self._output(conflict=ConflictPolicy.RENAME)
        )
        state.add_item(BatchItem.create(first, MediaKind.IMAGE))
        state.add_item(BatchItem.create(second, MediaKind.IMAGE))

        plan = plan_batch(state)
        names = [snapshot.target.name for snapshot in plan.snapshots]
        self.assertEqual(names, ["a_graded.png", "a_graded-2.png"])

    def test_overwrite_happens_only_when_selected(self) -> None:
        source = self._file("a.jpg")
        state = self._batch(
            [source], output=self._output(conflict=ConflictPolicy.OVERWRITE)
        )
        existing = state.output.directory / "a_graded.png"
        existing.write_bytes(b"old")
        plan = plan_batch(state)
        self.assertEqual(plan.snapshots[0].target, existing)

    def test_target_may_never_be_the_source(self) -> None:
        source = self._file("a.jpg")
        item = BatchItem.create(source, MediaKind.IMAGE)
        output = OutputPlan(directory=source.parent, suffix_label="", image_suffix=".jpg")
        target, reason = plan_target(item, output)
        self.assertIsNone(target)
        self.assertIn("源文件", reason)

    def test_missing_source_is_reported_with_a_stable_code(self) -> None:
        state = BatchState.create(Strategy.UNIFORM, ColorParams(), self._output())
        state.add_item(BatchItem.create(self._dir / "gone.jpg", MediaKind.IMAGE))
        plan = plan_batch(state)
        self.assertEqual(plan.snapshots, ())
        code, _message = plan.errors[state.items[0].item_id]
        self.assertEqual(code, "SOURCE_MISSING")

    def test_missing_parameters_are_reported(self) -> None:
        source = self._file("a.jpg")
        state = self._batch([source], baseline=None)
        plan = plan_batch(state)
        code, _message = plan.errors[state.items[0].item_id]
        self.assertEqual(code, "PARAMS_MISSING")

    def test_source_change_after_import_is_reported(self) -> None:
        source = self._file("a.jpg")
        state = self._batch([source])
        self.assertGreater(state.items[0].source_size, 0)

        source.write_bytes(b"changed content")
        plan = plan_batch(state)

        self.assertEqual(plan.snapshots, ())
        code, message = plan.errors[state.items[0].item_id]
        self.assertEqual(code, "SOURCE_CHANGED")
        self.assertIn("重新添加", message)
        # The explicit retry path is the user's way back in, and it keeps
        # failing until the item is re-imported with a fresh fingerprint.
        state.apply_plan(plan)
        item_id = state.items[0].item_id
        self.assertTrue(state.retry(item_id))
        self.assertIn(item_id, plan_batch(state).errors)

    def test_an_unchanged_source_still_plans(self) -> None:
        source = self._file("a.jpg")
        state = self._batch([source])
        plan = plan_batch(state)
        self.assertEqual([s.item_id for s in plan.snapshots], [state.items[0].item_id])

    def test_planning_aborts_when_the_output_directory_is_gone(self) -> None:
        source = self._file("a.jpg")
        state = self._batch([source], output=OutputPlan(directory=self._dir / "nope"))
        with self.assertRaises(BatchPlanError) as ctx:
            plan_batch(state)
        self.assertEqual(ctx.exception.code, "OUTPUT_MISSING")

    def test_snapshot_is_frozen_against_later_edits(self) -> None:
        source = self._file("a.jpg")
        state = self._batch([source], baseline=ColorParams(contrast=8.0))
        plan = plan_batch(state)
        frozen = plan.snapshots[0]

        state.apply_baseline(ColorParams(contrast=80.0), only_uncovered=False)
        state.items[0] = replace(state.items[0], source=Path("different.jpg"))

        self.assertEqual(frozen.params.contrast, 8.0)
        self.assertEqual(frozen.source, source)

    def test_only_pending_items_are_planned(self) -> None:
        state = self._batch(
            [self._file("a.jpg"), self._file("b.jpg"), self._file("c.jpg")]
        )
        first, second, third = (item.item_id for item in state.items)
        state.records[first].status = ItemStatus.DONE
        state.records[second].status = ItemStatus.FAILED

        plan = plan_batch(state)
        self.assertEqual([s.item_id for s in plan.snapshots], [third])

        # Retry is the explicit path back into the queue.
        self.assertTrue(state.retry(second))
        retried = plan_batch(state)
        self.assertEqual([s.item_id for s in retried.snapshots], [second, third])


class BatchRunnerTests(_BatchFixture):
    def _runner(self, worker) -> BatchRunner:
        runner = BatchRunner(worker)
        self.addCleanup(runner.shutdown, 2.0)
        return runner

    def _drain(self, runner: BatchRunner) -> list[batch.BatchUpdate]:
        return runner.poll()

    def test_items_run_in_submit_order(self) -> None:
        worker = _StubWorker()
        runner = self._runner(worker)
        snapshots = [_snapshot(name) for name in ("a", "b", "c")]
        self.assertEqual(runner.submit(snapshots), 3)
        self.assertTrue(
            _wait_for(lambda: len(worker.order) == 3 and not runner.is_running())
        )
        self.assertEqual(worker.order, ["a", "b", "c"])

        updates = self._drain(runner)
        done = [u.item_id for u in updates if u.kind is UpdateKind.DONE]
        self.assertEqual(done, ["a", "b", "c"])

    def test_only_one_item_runs_at_a_time(self) -> None:
        worker = _StubWorker(delay=0.02)
        runner = self._runner(worker)
        runner.submit([_snapshot(f"j{index}") for index in range(6)])
        self.assertTrue(_wait_for(lambda: len(worker.order) == 6 and not runner.is_running()))
        self.assertEqual(worker.max_active, 1)

    def test_a_failure_does_not_stop_the_queue(self) -> None:
        worker = _StubWorker(fail=("b",))
        runner = self._runner(worker)
        runner.submit([_snapshot(name) for name in ("a", "b", "c")])
        self.assertTrue(_wait_for(lambda: len(worker.order) == 3 and not runner.is_running()))

        updates = self._drain(runner)
        by_item = {u.item_id: u for u in updates if u.kind in (
            UpdateKind.DONE, UpdateKind.FAILED
        )}
        self.assertEqual(by_item["a"].status, ItemStatus.DONE)
        self.assertEqual(by_item["b"].status, ItemStatus.FAILED)
        self.assertEqual(by_item["b"].error_code, "BATCH_FAILED")
        self.assertIn("boom", by_item["b"].error_message)
        self.assertEqual(by_item["c"].status, ItemStatus.DONE)

    def test_cancelling_a_queued_item_is_idempotent(self) -> None:
        gate = threading.Event()
        worker = _StubWorker(gates={"a": gate})
        runner = self._runner(worker)
        runner.submit([_snapshot("a"), _snapshot("b")])
        self.assertTrue(_wait_for(lambda: worker.order == ["a"]))

        self.assertTrue(runner.cancel_item("b"))
        self.assertFalse(runner.cancel_item("b"))  # second click is a no-op
        self.assertEqual(runner.queued_count(), 0)

        gate.set()
        self.assertTrue(_wait_for(lambda: not runner.is_running()))

        updates = self._drain(runner)
        b_updates = [u for u in updates if u.item_id == "b"]
        self.assertEqual(len(b_updates), 2)  # queued + cancelled, nothing else
        self.assertEqual(b_updates[-1].kind, UpdateKind.CANCELLED)
        self.assertNotIn("b", worker.order)

    def test_cancelling_the_current_item_stops_it_cooperatively(self) -> None:
        gate = threading.Event()
        worker = _StubWorker(gates={"a": gate})
        runner = self._runner(worker)
        runner.submit([_snapshot("a")])
        self.assertTrue(_wait_for(lambda: worker.order == ["a"]))

        self.assertTrue(runner.cancel_item("a"))
        self.assertTrue(_wait_for(lambda: not runner.is_running()))

        updates = self._drain(runner)
        kinds = [u.kind for u in updates if u.item_id == "a"]
        self.assertEqual(kinds[-1], UpdateKind.CANCELLED)
        self.assertNotIn(UpdateKind.DONE, kinds)

    def test_cancel_pending_keeps_the_running_item(self) -> None:
        gate = threading.Event()
        worker = _StubWorker(gates={"a": gate})
        runner = self._runner(worker)
        runner.submit([_snapshot("a"), _snapshot("b"), _snapshot("c")])
        self.assertTrue(_wait_for(lambda: worker.order == ["a"]))

        self.assertEqual(runner.cancel_pending(), 2)
        self.assertEqual(runner.cancel_pending(), 0)  # idempotent

        gate.set()
        self.assertTrue(_wait_for(lambda: not runner.is_running()))

        updates = self._drain(runner)
        done = [u.item_id for u in updates if u.kind is UpdateKind.DONE]
        cancelled = [u.item_id for u in updates if u.kind is UpdateKind.CANCELLED]
        self.assertEqual(done, ["a"])
        self.assertEqual(sorted(cancelled), ["b", "c"])

    def test_cancel_all_reports_the_current_item_too(self) -> None:
        gate = threading.Event()
        worker = _StubWorker(gates={"a": gate})
        runner = self._runner(worker)
        runner.submit([_snapshot("a"), _snapshot("b")])
        self.assertTrue(_wait_for(lambda: worker.order == ["a"]))

        self.assertEqual(runner.cancel_all(), 2)
        self.assertTrue(_wait_for(lambda: not runner.is_running()))

        updates = self._drain(runner)
        cancelled = sorted(u.item_id for u in updates if u.kind is UpdateKind.CANCELLED)
        self.assertEqual(cancelled, ["a", "b"])
        self.assertNotIn(
            UpdateKind.DONE, [u.kind for u in updates]
        )

    def test_cancelling_after_completion_is_a_no_op(self) -> None:
        worker = _StubWorker()
        runner = self._runner(worker)
        runner.submit([_snapshot("a")])
        self.assertTrue(_wait_for(runner.is_idle))
        self.assertFalse(runner.cancel_item("a"))

        updates = self._drain(runner)
        self.assertEqual(
            [
                u.kind for u in updates
                if u.item_id == "a" and u.kind is not UpdateKind.PROGRESS
            ],
            [UpdateKind.QUEUED, UpdateKind.STARTED, UpdateKind.DONE],
        )

    def test_a_worker_that_ignores_cancel_is_not_reported_as_done(self) -> None:
        gate = threading.Event()
        worker = _StubWorker(gates={"a": gate}, cooperative=False)
        runner = self._runner(worker)
        runner.submit([_snapshot("a")])
        self.assertTrue(_wait_for(lambda: worker.order == ["a"]))

        self.assertTrue(runner.cancel_item("a"))
        gate.set()  # the worker still returns a path
        self.assertTrue(_wait_for(lambda: not runner.is_running()))

        updates = self._drain(runner)
        kinds = [u.kind for u in updates if u.item_id == "a"]
        self.assertEqual(kinds[-1], UpdateKind.CANCELLED)
        self.assertNotIn(UpdateKind.DONE, kinds)

    def test_progress_updates_are_forwarded_and_deduplicated(self) -> None:
        worker = _StubWorker()
        runner = self._runner(worker)
        runner.submit([_snapshot("a")])
        self.assertTrue(_wait_for(runner.is_idle))

        values = [
            u.progress for u in self._drain(runner)
            if u.item_id == "a" and u.kind is UpdateKind.PROGRESS
        ]
        self.assertEqual(values, [0.1, 0.5, 1.0])

    def test_shutdown_cancels_running_and_pending(self) -> None:
        gate = threading.Event()
        worker = _StubWorker(gates={"a": gate})
        runner = BatchRunner(worker)
        runner.submit([_snapshot("a"), _snapshot("b")])
        self.assertTrue(_wait_for(lambda: worker.order == ["a"]))

        self.assertTrue(runner.shutdown(timeout=2.0))
        self.assertFalse(runner.is_running())
        self.assertEqual(runner.queued_count(), 0)
        with self.assertRaises(RuntimeError):
            runner.submit([_snapshot("c")])

    def test_duplicate_submissions_are_ignored(self) -> None:
        worker = _StubWorker(delay=0.01)
        runner = self._runner(worker)
        snapshot = _snapshot("a")
        self.assertEqual(runner.submit([snapshot]), 1)
        self.assertEqual(runner.submit([snapshot]), 0)
        self.assertTrue(_wait_for(runner.is_idle))
        self.assertEqual(worker.order, ["a"])


if __name__ == "__main__":
    unittest.main()
