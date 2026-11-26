"""End-to-end check for the batch worker: real engine + real ffmpeg.

Drives ``BatchRunner`` with ``BatchExportWorker`` over a mixed queue (two stills
and one clip), then verifies failure continuation and both cancellation modes.
Everything is written under a system temp directory and removed afterwards; no
repository path is touched.

Exits non-zero if any check fails.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from PIL import Image  # noqa: E402

from app import video_io  # noqa: E402
from app.batch import (  # noqa: E402
    BatchItem,
    BatchRunner,
    BatchState,
    ConflictPolicy,
    ItemStatus,
    MediaKind,
    OutputPlan,
    Strategy,
    UpdateKind,
    plan_batch,
)
from app.batch_export import BatchExportWorker  # noqa: E402
from app.pipeline import RenderPipeline  # noqa: E402
from baker.params import ColorParams  # noqa: E402

FIXTURES = ROOT_DIR / "runtime" / "test-fixtures"
FAILURES: list[str] = []


def check(condition: bool, label: str, detail: object = "") -> None:
    if not condition:
        FAILURES.append(label)
        print(f"FAIL: {label} {detail}")


def make_clip(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=1",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def collect(runner: BatchRunner, timeout: float = 240.0) -> list:
    updates = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        updates.extend(runner.poll())
        if runner.is_idle():
            updates.extend(runner.poll())
            return updates
        time.sleep(0.02)
    FAILURES.append("batch did not finish within the timeout")
    return updates


def build(sources, out_dir: Path, *, conflict=ConflictPolicy.SKIP) -> BatchState:
    out_dir.mkdir(parents=True, exist_ok=True)
    state = BatchState.create(
        Strategy.UNIFORM,
        ColorParams(contrast=18.0, saturation=12.0),
        OutputPlan(directory=out_dir, conflict=conflict),
    )
    for path, kind in sources:
        state.add_item(BatchItem.create(path, kind))
    return state


def apply_updates(state: BatchState, updates) -> None:
    for update in updates:
        state.apply_update(update)


def phase_mixed(work: Path, worker: BatchExportWorker) -> None:
    print("\n-- phase 1: mixed queue (2 stills + 1 clip) --")
    sources = [
        (work / "still-a.jpg", MediaKind.IMAGE),
        (work / "clip.mp4", MediaKind.VIDEO),
        (work / "still-b.png", MediaKind.IMAGE),
    ]
    state = build(sources, work / "out-mixed")
    plan = plan_batch(state)
    check(len(plan.snapshots) == 3, "three items planned", len(plan.snapshots))
    state.apply_plan(plan)

    runner = BatchRunner(worker)
    runner.submit(plan.snapshots)
    updates = collect(runner)
    apply_updates(state, updates)

    for item in state.items:
        record = state.record(item.item_id)
        print(f"   {item.source.name:<14} {record.status.value:<10} {record.output}")
        check(record.status is ItemStatus.DONE, f"{item.source.name} finished")
        check(record.output is not None and record.output.is_file(),
              f"{item.source.name} output exists")
        if record.output is not None and record.output.is_file():
            check(record.output.stat().st_size > 1000,
                  f"{item.source.name} output is non-trivial")
        check(record.attempts == 1, f"{item.source.name} ran once", record.attempts)

    still = state.record(state.items[0].item_id).output
    check(still is not None and still.is_file(), "still output path recorded")
    if still is not None and still.is_file():
        with Image.open(still) as rendered:
            with Image.open(work / "still-a.jpg") as original:
                check(
                    rendered.size == original.size,
                    "still keeps source dimensions",
                    (rendered.size, original.size),
                )

    clip = state.record(state.items[1].item_id).output
    check(clip is not None and clip.is_file(), "clip output path recorded")
    if clip is not None and clip.is_file():
        info = video_io.probe(clip)
        check(abs(info.duration_s - 1.0) < 0.2, "clip duration preserved",
              info.duration_s)
        check(info.width == 640 and info.height == 360, "clip size preserved",
              (info.width, info.height))

    check(not list((work / "cubes").glob("*.cube")), "no internal cubes left behind")

    for item in state.items:
        values = [
            u.progress for u in updates
            if u.item_id == item.item_id and u.kind is UpdateKind.PROGRESS
        ]
        check(values == sorted(values), f"{item.source.name} progress monotonic", values)
        check(values and values[-1] >= 0.99, f"{item.source.name} reported completion",
              values[-1] if values else None)


def phase_failure_continues(work: Path, worker: BatchExportWorker) -> None:
    print("\n-- phase 2: a missing source does not stop the queue --")
    out_dir = work / "out-fail"
    sources = [
        (work / "f-a.jpg", MediaKind.IMAGE),
        (work / "f-missing.jpg", MediaKind.IMAGE),
        (work / "f-b.png", MediaKind.IMAGE),
    ]
    shutil.copyfile(FIXTURES / "scene.jpg", sources[0][0])
    shutil.copyfile(FIXTURES / "pattern.png", sources[2][0])
    shutil.copyfile(FIXTURES / "scene.jpg", sources[1][0])

    state = build(sources, out_dir)
    plan = plan_batch(state)
    check(len(plan.snapshots) == 3, "missing source passed planning (deleted later)")

    # Delete after planning: this is the "file changed between plan and run" case.
    sources[1][0].unlink()

    runner = BatchRunner(worker)
    runner.submit(plan.snapshots)
    updates = collect(runner)
    apply_updates(state, updates)

    statuses = [state.record(item.item_id).status for item in state.items]
    print("   statuses:", [s.value for s in statuses])
    check(statuses[0] is ItemStatus.DONE, "item before the failure completed")
    check(statuses[1] is ItemStatus.FAILED, "missing source reported as failed")
    check(statuses[2] is ItemStatus.DONE, "item after the failure still ran")
    code = state.record(state.items[1].item_id).error_code
    check(bool(code), "failure carries a stable code", code)


def phase_cancel_pending(work: Path, worker: BatchExportWorker) -> None:
    print("\n-- phase 3: cancel pending keeps the running item --")
    out_dir = work / "out-cancel-pending"
    names = ["c-a.jpg", "c-b.jpg", "c-c.jpg"]
    for name in names:
        shutil.copyfile(FIXTURES / "scene.jpg", work / name)

    state = build([(work / n, MediaKind.IMAGE) for n in names], out_dir)
    plan = plan_batch(state)
    runner = BatchRunner(worker)
    runner.submit(plan.snapshots)
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline and not runner.is_running():
        time.sleep(0.01)
    check(runner.is_running(), "an item started before cancelling")
    cancelled = runner.cancel_pending()
    check(cancelled == 2, "two queued items cancelled", cancelled)

    updates = collect(runner)
    apply_updates(state, updates)
    statuses = [state.record(item.item_id).status for item in state.items]
    print("   statuses:", [s.value for s in statuses])
    check(statuses[0] is ItemStatus.DONE, "running item was allowed to finish")
    check(statuses[1] is ItemStatus.CANCELLED, "queued item 2 cancelled")
    check(statuses[2] is ItemStatus.CANCELLED, "queued item 3 cancelled")
    check(not (out_dir / "c-b_graded.png").exists(), "cancelled item wrote no file")


def phase_cancel_current(work: Path, worker: BatchExportWorker) -> None:
    print("\n-- phase 4: cancel the current item, keep the queue --")
    out_dir = work / "out-cancel-current"
    names = ["q-a.jpg", "q-b.jpg", "q-c.jpg"]
    for name in names:
        shutil.copyfile(FIXTURES / "scene.jpg", work / name)

    state = build([(work / n, MediaKind.IMAGE) for n in names], out_dir)
    plan = plan_batch(state)
    runner = BatchRunner(worker)
    runner.submit(plan.snapshots)
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline and not runner.is_running():
        time.sleep(0.01)
    current = runner.current_item_id()
    check(runner.cancel_item(current), "cancel accepted for the running item")

    updates = collect(runner)
    apply_updates(state, updates)
    statuses = [state.record(item.item_id).status for item in state.items]
    print("   statuses:", [s.value for s in statuses])
    check(statuses[0] is ItemStatus.CANCELLED, "current item cancelled")
    check(statuses[1] is ItemStatus.DONE, "following item still ran")
    check(statuses[2] is ItemStatus.DONE, "last item still ran")


def main() -> int:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        print("SKIP: ffmpeg/ffprobe not on PATH")
        return 0
    for name in ("scene.jpg", "pattern.png"):
        if not (FIXTURES / name).is_file():
            print(f"SKIP: fixture missing: {name}")
            return 0

    work = Path(tempfile.mkdtemp(prefix="batch-mixed-check-"))
    try:
        shutil.copyfile(FIXTURES / "scene.jpg", work / "still-a.jpg")
        shutil.copyfile(FIXTURES / "pattern.png", work / "still-b.png")
        make_clip(work / "clip.mp4")

        worker = BatchExportWorker(
            RenderPipeline(), video_work_dir=work / "cubes"
        )
        started = time.monotonic()
        phase_mixed(work, worker)
        phase_failure_continues(work, worker)
        phase_cancel_pending(work, worker)
        phase_cancel_current(work, worker)
        print(f"\nelapsed: {time.monotonic() - started:.1f}s")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if FAILURES:
        print(f"\nFAILURES ({len(FAILURES)}):")
        for item in FAILURES:
            print(" -", item)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
