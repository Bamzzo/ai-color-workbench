"""Batch worker adapter tests.

The render pipeline is stubbed: these tests are about the adapter's contract —
which export path it picks, what it freezes, what it cleans up — not about image
math. Real engine/ffmpeg coverage lives in ``runtime/batch_mixed_check.py``.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image

from app import batch, batch_export, video_io
from app.batch import BatchRunner, BatchTaskSnapshot, ItemStatus, MediaKind, UpdateKind
from app.batch_export import BatchExportWorker
from app.engine_client import EngineError
from app.image_io import ImageError
from app.pipeline import ExportResult
from baker.params import ColorParams


class _Recorder:
    """Stands in for the decoded PIL image; records that it was released."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Pipeline:
    def __init__(self) -> None:
        self.preview_calls = 0
        self.export_calls: list[tuple] = []
        self.cube_calls: list[tuple] = []

    def prepare_preview(self, source):
        self.preview_calls += 1
        return Image.new("RGBA", (2, 2), (1, 2, 3, 255)), False, Path("x.rgba")

    def export_image(self, snapshot, target, fmt, quality=95, cancel=None):
        Path(target).write_bytes(b"image-bytes")
        self.export_calls.append((snapshot, Path(target), fmt, quality, cancel))
        return ExportResult(
            path=Path(target), width=2, height=2, revision=snapshot.revision, detail=fmt
        )

    def bake_video_cube(
        self, params, strength, target, *, external_lut=None, cancel_event=None, size=33
    ):
        Path(target).write_text("LUT_3D_SIZE 2\n", encoding="utf-8")
        self.cube_calls.append((params, strength, Path(target), external_lut))


def _snapshot(**kwargs) -> BatchTaskSnapshot:
    values = dict(
        batch_id="b1",
        item_id="i1",
        source=Path("clip.mp4"),
        kind=MediaKind.IMAGE,
        params=ColorParams(contrast=20.0),
        strength=0.8,
        lut_path=None,
        target=Path("out.png"),
        strategy=batch.Strategy.UNIFORM,
        token=7,
        image_quality=88,
        video_quality=21,
        video_preset="fast",
    )
    values.update(kwargs)
    return BatchTaskSnapshot(**values)


class BatchExportWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = Path(tempfile.mkdtemp(prefix="batch-export-test-"))
        self.addCleanup(shutil.rmtree, self._dir, ignore_errors=True)
        self.pipeline = _Pipeline()
        self.worker = BatchExportWorker(
            self.pipeline, video_work_dir=self._dir / "cubes"
        )

    def _reports(self):
        values: list[float] = []
        return values, values.append

    def test_image_item_exports_with_the_snapshot_settings(self) -> None:
        image = _Recorder()
        source = SimpleNamespace(image=image, path=Path("a.png"))
        reports, report = self._reports()
        with mock.patch.object(
            batch_export.image_io, "load_source_image", return_value=source
        ) as load:
            out = self.worker(
                _snapshot(source=Path("a.png"), target=self._dir / "a_graded.png"),
                threading.Event(),
                report,
            )

        load.assert_called_once_with(Path("a.png"))
        _render, target, fmt, quality, cancel = self.pipeline.export_calls[0]
        self.assertEqual(fmt, "PNG")
        self.assertEqual(quality, 88)
        self.assertEqual(target, self._dir / "a_graded.png")
        self.assertIsInstance(cancel, threading.Event)
        self.assertEqual(_render.params.contrast, 20.0)
        self.assertEqual(_render.strength, 0.8)
        self.assertEqual(_render.mode, "params")
        self.assertEqual(out, self._dir / "a_graded.png")
        self.assertTrue(image.closed, "decoded pixels were not released")

    def test_jpeg_suffix_selects_jpeg(self) -> None:
        source = SimpleNamespace(image=_Recorder(), path=Path("a.jpg"))
        _reports_list, report = self._reports()
        with mock.patch.object(
            batch_export.image_io, "load_source_image", return_value=source
        ):
            self.worker(_snapshot(target=self._dir / "a_graded.jpg"), threading.Event(), report)
        self.assertEqual(self.pipeline.export_calls[0][2], "JPEG")

    def test_external_lut_switches_the_render_mode(self) -> None:
        source = SimpleNamespace(image=_Recorder(), path=Path("a.png"))
        lut = SimpleNamespace(path=Path("look.cube"), size=33)
        _reports_list, report = self._reports()
        with mock.patch.object(
            batch_export.image_io, "load_source_image", return_value=source
        ), mock.patch.object(batch_export, "load_cube", return_value=lut) as load_cube:
            self.worker(
                _snapshot(target=self._dir / "a.png", lut_path=Path("look.cube")),
                threading.Event(),
                report,
            )
        load_cube.assert_called_once_with(Path("look.cube"))
        render = self.pipeline.export_calls[0][0]
        self.assertEqual(render.mode, "external_lut")
        self.assertIs(render.external_lut, lut)

    def test_cancel_before_start_never_touches_the_pipeline(self) -> None:
        cancel = threading.Event()
        cancel.set()
        _reports_list, report = self._reports()
        with self.assertRaises(batch.BatchCancelled):
            self.worker(_snapshot(), cancel, report)
        self.assertEqual(self.pipeline.preview_calls, 0)
        self.assertEqual(self.pipeline.export_calls, [])

    def test_decode_failure_propagates_with_its_code(self) -> None:
        _reports_list, report = self._reports()
        with mock.patch.object(
            batch_export.image_io,
            "load_source_image",
            side_effect=ImageError("IMAGE_INVALID", "bad"),
        ):
            with self.assertRaises(ImageError) as ctx:
                self.worker(_snapshot(), threading.Event(), report)
        self.assertEqual(ctx.exception.code, "IMAGE_INVALID")

    def test_video_item_bakes_a_cube_and_removes_it(self) -> None:
        info = SimpleNamespace(path=Path("clip.mp4"))
        reports, report = self._reports()
        target = self._dir / "clip_graded.mp4"
        with mock.patch.object(batch_export.video_io, "probe", return_value=info), \
                mock.patch.object(
                    batch_export.video_io,
                    "export_graded",
                    side_effect=lambda *a, **k: (k["on_progress"](0.5), target)[1],
                ) as encode:
            out = self.worker(
                _snapshot(kind=MediaKind.VIDEO, source=Path("clip.mp4"), target=target),
                threading.Event(),
                report,
            )

        self.assertEqual(out, target)
        params, strength, cube_path, external = self.pipeline.cube_calls[0]
        self.assertEqual(strength, 0.8)
        self.assertIsNone(external)
        self.assertFalse(cube_path.exists(), "internal cube was left in the cache")
        self.assertEqual(list((self._dir / "cubes").glob("*.cube")), [])

        kwargs = encode.call_args.kwargs
        self.assertEqual(kwargs["quality"], 21)
        self.assertEqual(kwargs["preset"], "fast")
        self.assertIs(kwargs["info"], info)
        self.assertEqual(reports, sorted(reports), "progress went backwards")
        self.assertAlmostEqual(reports[-1], 1.0)

    def test_video_failure_still_removes_the_cube(self) -> None:
        info = SimpleNamespace(path=Path("clip.mp4"))
        _reports_list, report = self._reports()
        with mock.patch.object(batch_export.video_io, "probe", return_value=info), \
                mock.patch.object(
                    batch_export.video_io,
                    "export_graded",
                    side_effect=video_io.VideoError("EXPORT_IO", "ffmpeg died"),
                ):
            with self.assertRaises(video_io.VideoError):
                self.worker(
                    _snapshot(kind=MediaKind.VIDEO, target=self._dir / "o.mp4"),
                    threading.Event(),
                    report,
                )
        self.assertEqual(list((self._dir / "cubes").glob("*.cube")), [])


class RunnerCancellationMappingTests(unittest.TestCase):
    """Cancellation is not failure, whichever layer notices it first."""

    def _run(self, worker) -> list[batch.BatchUpdate]:
        runner = BatchRunner(worker)
        self.addCleanup(runner.shutdown, 2.0)
        runner.submit([_snapshot()])
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not runner.is_idle():
            time.sleep(0.005)
        self.assertTrue(runner.is_idle())
        return runner.poll()

    def test_engine_cancelled_error_is_reported_as_cancelled(self) -> None:
        def worker(snapshot, cancel, report):
            raise EngineError("CANCELLED", "渲染已取消", "process")

        updates = self._run(worker)
        finals = [u for u in updates if u.kind in (UpdateKind.DONE, UpdateKind.FAILED,
                                                   UpdateKind.CANCELLED)]
        self.assertEqual(len(finals), 1)
        self.assertEqual(finals[0].status, ItemStatus.CANCELLED)

    def test_other_engine_errors_are_failures(self) -> None:
        def worker(snapshot, cancel, report):
            raise EngineError("ENGINE_ERROR", "worker crashed", "process")

        updates = self._run(worker)
        finals = [u for u in updates if u.kind in (UpdateKind.DONE, UpdateKind.FAILED,
                                                   UpdateKind.CANCELLED)]
        self.assertEqual(finals[0].status, ItemStatus.FAILED)
        self.assertEqual(finals[0].error_code, "ENGINE_ERROR")
