"""Pipeline, state and job-runner integration tests (T07, T10, T12, T13)."""

from __future__ import annotations

import queue
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from app import image_io, paths
from app.engine_client import EngineClient
from app.image_io import ImageError
from app.jobs import JobOutcome, LatestJobRunner
from app.pipeline import RenderPipeline, RenderSnapshot
from app.state import AppState
from baker.color_transform import apply_effect_to_rgb, lut_grid
from baker.cube_reader import load_cube
from baker.cube_writer import write_cube
from baker.params import ColorParams, load_preset, lut_cache_key

from tests import helpers

FIXTURES = helpers.ensure_fixtures()


def setUpModule() -> None:
    paths.ensure_runtime()
    helpers.ensure_fixtures()


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pipeline = RenderPipeline(EngineClient(timeout=90.0))
        cls._tmp = tempfile.TemporaryDirectory(prefix="pipeline-test-")
        cls.dir = Path(cls._tmp.name)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _prepare(self, path: Path, params: ColorParams, strength: float = 1.0):
        source = image_io.load_source_image(path)
        state = AppState()
        state.new_document(source)
        preview, scaled, _target = self.pipeline.prepare_preview(source)
        state.preview_image = preview
        state.preview_is_scaled = scaled
        state.set_params(params)
        state.set_strength(strength)
        snapshot = RenderSnapshot.from_state(state)
        return source, state, snapshot

    def _cpu_reference(self, source, params, strength=1.0):
        lut_path = self.pipeline._params_preview_lut(params)
        lut = load_cube(lut_path)
        rgb = np.asarray(source.image.convert("RGBA"), dtype=np.uint8)[..., :3]
        return apply_effect_to_rgb(
            rgb.astype(np.float64) / 255.0,
            lut.samples,
            lut.size,
            strength,
        )

    def test_t12_preview_png_and_jpeg_export(self) -> None:
        source, state, snapshot = self._prepare(
            FIXTURES["pattern"], load_preset("warm")[0], strength=0.8
        )
        preview_result = self.pipeline.render_preview(snapshot)
        preview_arr = np.asarray(preview_result.image.convert("RGBA"), dtype=np.uint8)
        # Compare the GPU output against a CPU render of the *input* preview
        # pixels, not of the already-graded output.
        source_arr = np.asarray(state.preview_image.convert("RGBA"), dtype=np.uint8)
        lut = load_cube(self.pipeline._params_preview_lut(snapshot.params))
        expected = apply_effect_to_rgb(
            source_arr[..., :3].astype(np.float64) / 255.0,
            lut.samples,
            lut.size,
            snapshot.strength,
        )
        self.assertLessEqual(
            float(np.max(np.abs(preview_arr[..., :3].astype(np.float64) - expected * 255.0))),
            1.5,
        )

        png_path = self.dir / "导出 图像.png"
        png_result = self.pipeline.export_image(snapshot, png_path, "PNG")
        self.assertEqual((png_result.width, png_result.height), (source.width, source.height))
        with Image.open(png_path) as check:
            check.load()
            png_arr = np.asarray(check.convert("RGBA"), dtype=np.uint8)
        self.assertTrue(np.all(png_arr[..., 3] == np.asarray(source.image)[..., 3]))
        full_expected = self._cpu_reference(source, snapshot.params, snapshot.strength)
        diff = np.abs(png_arr[..., :3].astype(np.float64) - full_expected * 255.0)
        self.assertLessEqual(float(np.max(diff)), 1.5)

        jpeg_path = self.dir / "export.jpg"
        self.pipeline.export_image(snapshot, jpeg_path, "JPEG", quality=95)
        with Image.open(jpeg_path) as check:
            check.load()
            jpeg_arr = np.asarray(check.convert("RGB"), dtype=np.float64)
        expected_rgb = full_expected * 255.0
        alpha = np.asarray(source.image)[..., 3:4].astype(np.float64) / 255.0
        expected_rgb = expected_rgb * alpha + 255.0 * (1.0 - alpha)
        mean = float(np.mean(np.abs(jpeg_arr - expected_rgb)))
        self.assertLess(mean, 4.0, f"JPEG mean abs diff {mean:.3f}/255")

    def test_t12_lut_export_and_verification(self) -> None:
        source, state, snapshot = self._prepare(
            FIXTURES["opaque"], load_preset("cool")[0], strength=0.65
        )
        target = self.dir / "look.cube"
        result = self.pipeline.export_lut(snapshot, target)
        self.assertTrue(target.is_file())
        self.assertIn("max diff", result.detail)
        self.assertEqual(result.warning, "")
        exported = load_cube(target)
        self.assertIn(exported.size, (33, 65))

        lut = load_cube(self.pipeline._params_preview_lut(snapshot.params))
        cpu = np.asarray(source.image.convert("RGBA"), dtype=np.uint8)[..., :3]
        expected = apply_effect_to_rgb(
            cpu.astype(np.float64) / 255.0,
            lut.samples,
            lut.size,
            snapshot.strength,
        )
        from baker.color_transform import sample_lut

        actual = sample_lut(
            exported.samples,
            exported.size,
            cpu.astype(np.float64) / 255.0,
        )
        self.assertLessEqual(
            float(np.max(np.abs(actual - expected)) * 255.0), 2.0
        )

    def test_t12_external_lut_mode(self) -> None:
        size = 17
        _values, grid = lut_grid(size)
        swap_path = self.dir / "swap17.cube"
        write_cube(swap_path, size, np.ascontiguousarray(grid[:, [2, 1, 0]]))
        lut = load_cube(swap_path)
        cached = self.pipeline.copy_external_lut(lut)
        self.assertTrue(cached.path.is_file())

        source = image_io.load_source_image(FIXTURES["pattern"])
        state = AppState()
        state.new_document(source)
        preview, scaled, _target = self.pipeline.prepare_preview(source)
        state.preview_image = preview
        state.preview_is_scaled = scaled
        state.set_params(load_preset("warm")[0])
        state.import_external_lut(cached)
        snapshot = RenderSnapshot.from_state(state)

        outcome = self.pipeline.render_preview(snapshot)
        got = np.asarray(outcome.image.convert("RGBA"), dtype=np.uint8)
        want = np.asarray(preview.convert("RGBA"), dtype=np.uint8)[..., [2, 1, 0, 3]]
        self.assertLessEqual(
            int(np.max(np.abs(got[..., :3].astype(np.int16) - want[..., :3].astype(np.int16)))),
            1,
        )

        target = self.dir / "external.cube"
        result = self.pipeline.export_lut(snapshot, target)
        self.assertTrue(target.is_file())
        self.assertIn("max diff", result.detail)
        self.assertEqual(state.saved_params, load_preset("warm")[0])
        state.return_to_params()
        self.assertEqual(state.params, load_preset("warm")[0])

    def test_t13_unicode_path_and_source_protection(self) -> None:
        unicode_dir = self.dir / "中文 空格 目录"
        unicode_dir.mkdir(parents=True, exist_ok=True)
        source_path = unicode_dir / "图 像.png"
        shutil.copyfile(FIXTURES["pattern"], source_path)
        source, state, snapshot = self._prepare(
            source_path, load_preset("soft")[0]
        )
        self.assertEqual(source.path.name, "图 像.png")
        with self.assertRaises(ImageError) as ctx:
            self.pipeline.export_image(snapshot, source_path, "PNG")
        self.assertEqual(ctx.exception.code, "EXPORT_IO")
        self.assertEqual(
            image_io.file_fingerprint(source_path), source.fingerprint
        )

    def test_t13_failed_target_keeps_no_partial_file(self) -> None:
        source, state, snapshot = self._prepare(
            FIXTURES["opaque"], load_preset("warm")[0]
        )
        blocker = self.dir / "not-a-directory"
        blocker.write_text("x", encoding="utf-8")
        target = blocker / "out.png"
        with self.assertRaises(ImageError) as ctx:
            self.pipeline.export_image(snapshot, target, "PNG")
        self.assertEqual(ctx.exception.code, "EXPORT_IO")
        self.assertFalse(target.exists())
        self.assertFalse(any(p.name.startswith("out.png") for p in self.dir.iterdir()))

    def test_t07_lut_cache_key_is_stable(self) -> None:
        warm, _ = load_preset("warm")
        first = lut_cache_key(warm, 33, (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), 1.0)
        second = lut_cache_key(warm, 33, (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), 1.0)
        other = lut_cache_key(warm, 33, (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), 0.9)
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)

        source, state, snapshot = self._prepare(FIXTURES["opaque"], warm)
        first_path = self.pipeline._params_preview_lut(snapshot.params)
        second_path = self.pipeline._params_preview_lut(snapshot.params)
        self.assertEqual(first_path, second_path)


class JobRunnerTests(unittest.TestCase):
    def test_t10_latest_job_wins(self) -> None:
        runner = LatestJobRunner("test")
        started = threading.Event()
        release = threading.Event()

        def slow(cancel: threading.Event) -> str:
            started.set()
            release.wait(5.0)
            return "A"

        def quick(label: str):
            def run(cancel: threading.Event) -> str:
                return label

            return run

        try:
            runner.submit("preview", slow, coalesce_key="preview", revision=1)
            self.assertTrue(started.wait(2.0))
            runner.submit("preview", quick("B"), coalesce_key="preview", revision=2)
            time.sleep(0.05)
            runner.submit("preview", quick("C"), coalesce_key="preview", revision=3)
            release.set()

            deadline = time.monotonic() + 5.0
            outcomes = []
            while time.monotonic() < deadline and len(outcomes) < 2:
                outcomes.extend(runner.poll())
                time.sleep(0.01)
            self.assertEqual([o.value for o in outcomes], ["A", "C"])
            self.assertEqual([o.revision for o in outcomes], [1, 3])
        finally:
            runner.shutdown()

    def test_t10_export_is_not_dropped_by_a_preview(self) -> None:
        # Regression: the old runner kept a single pending slot regardless of
        # key, so a slider drag (preview) silently discarded a queued export.
        runner = LatestJobRunner("export")
        started = threading.Event()
        release = threading.Event()

        def slow(cancel: threading.Event) -> str:
            started.set()
            release.wait(5.0)
            return "A"

        try:
            runner.submit("preview", slow, coalesce_key="preview", revision=1)
            self.assertTrue(started.wait(2.0))
            runner.submit(
                "export-image",
                lambda cancel: "EXPORT",
                coalesce_key="export-image",
                revision=1,
                coalesce=False,
            )
            runner.submit("preview", lambda c: "P2", coalesce_key="preview", revision=2)
            runner.submit("preview", lambda c: "P3", coalesce_key="preview", revision=3)
            release.set()

            deadline = time.monotonic() + 5.0
            outcomes = []
            while time.monotonic() < deadline and len(outcomes) < 3:
                outcomes.extend(runner.poll())
                time.sleep(0.01)
            values = [o.value for o in outcomes]
            self.assertIn("EXPORT", values)
            self.assertIn("P3", values)
            self.assertNotIn("P2", values)
            # Exports are user-initiated, so they run before the queued preview.
            self.assertEqual(values, ["A", "EXPORT", "P3"])
        finally:
            runner.shutdown()

    def test_queued_exports_keep_fifo_order(self) -> None:
        runner = LatestJobRunner("fifo")
        started = threading.Event()
        release = threading.Event()
        order: list[str] = []

        def slow(cancel: threading.Event) -> str:
            started.set()
            release.wait(5.0)
            return "A"

        def record(label: str):
            def run(cancel: threading.Event) -> str:
                order.append(label)
                return label

            return run

        try:
            runner.submit("preview", slow, coalesce_key="preview", revision=1)
            self.assertTrue(started.wait(2.0))
            runner.submit("export-image", record("img"), coalesce_key="export-image",
                          revision=1, coalesce=False)
            runner.submit("export-lut", record("lut"), coalesce_key="export-lut",
                          revision=2, coalesce=False)
            self.assertEqual(runner.queued_count(), 2)
            release.set()

            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and len(order) < 2:
                runner.poll()
                time.sleep(0.01)
            self.assertEqual(order, ["img", "lut"])
        finally:
            runner.shutdown()

    def test_shutdown_cancels_queued_exports(self) -> None:
        runner = LatestJobRunner("drain")
        started = threading.Event()
        ran: list[str] = []

        def slow(cancel: threading.Event) -> str:
            started.set()
            while not cancel.is_set():
                time.sleep(0.01)
            return "cancelled"

        runner.submit("preview", slow, coalesce_key="preview", revision=1)
        self.assertTrue(started.wait(2.0))
        runner.submit("export-image", lambda c: ran.append("img"),
                      coalesce_key="export-image", revision=1, coalesce=False)
        runner.shutdown()
        self.assertEqual(ran, [])
        self.assertFalse(runner.is_busy())

    def test_t10_shutdown_cancels_work(self) -> None:
        runner = LatestJobRunner("shutdown")
        started = threading.Event()

        def slow(cancel: threading.Event) -> str:
            started.set()
            while not cancel.is_set():
                time.sleep(0.01)
            return "cancelled"

        runner.submit("slow", slow, coalesce_key="slow", revision=1)
        self.assertTrue(started.wait(2.0))
        runner.shutdown()
        self.assertFalse(runner.is_busy())


class BusyStatusTests(unittest.TestCase):
    """The busy line composes every concurrent activity.

    Regression: a preview finishing used to clear the text even when an export
    was still queued, so the UI went quiet while a file was being written.
    """

    class _Var:
        def __init__(self) -> None:
            self.value = ""

        def set(self, value: str) -> None:
            self.value = value

    class _Label:
        def __init__(self) -> None:
            self.style = ""

        def configure(self, **kwargs) -> None:
            self.style = kwargs.get("style", self.style)

    class _Runner:
        """Stub exposing only what _refresh_busy consults."""

        def __init__(self, queued: int = 0) -> None:
            self.queued = queued

        def queued_count(self) -> int:
            return self.queued

        def is_busy(self) -> bool:
            return self.queued > 0

    def setUp(self) -> None:
        from app.ui import ColorApp

        app = ColorApp.__new__(ColorApp)
        app.busy_var = self._Var()
        app.message_var = self._Var()
        app.message_label = self._Label()
        app.state = AppState()
        app._export_tickets = []
        app._export_seq = 0
        app._ai_busy = False
        app._export_notice_until = 0.0
        app.runner = self._Runner()
        self.app = app

    def _finish(self, token: int, kind: str = "图片") -> None:
        self.app._export_take(token, kind)
        self.app._refresh_busy()

    def test_export_status_survives_a_finished_preview(self) -> None:
        app = self.app
        app.state.busy_revision = 5
        app._refresh_busy()
        self.assertEqual(app.busy_var.value, "正在渲染 rev 5…")
        app.runner.queued = 1  # queued behind the running preview
        token = app._export_started("图片", 5)
        self.assertIn("正在导出图片 rev 5", app.busy_var.value)
        self.assertIn("等待当前渲染完成", app.busy_var.value)

        app.state.busy_revision = None  # preview completed
        app.runner.queued = 0  # export is now the one running
        app._refresh_busy()
        self.assertEqual(app.busy_var.value, "正在导出图片 rev 5…")

        self._finish(token)
        self.assertEqual(app.busy_var.value, "")

    def test_queued_exports_are_counted_while_one_runs(self) -> None:
        app = self.app
        image_token = app._export_started("图片", 2)
        app._export_started("LUT", 2)
        app.runner.queued = 1  # the LUT export is waiting behind the image one
        app._refresh_busy()
        self.assertEqual(
            app.busy_var.value, "正在导出图片 rev 2…（另有 1 个导出排队）"
        )
        self._finish(image_token, "图片")
        app.runner.queued = 1
        app._refresh_busy()
        self.assertEqual(app.busy_var.value, "正在导出LUT rev 2…（等待当前渲染完成）")
        self._finish(app._export_tickets[0].token, "LUT")
        self.assertEqual(app.busy_var.value, "")

    def test_two_exports_waiting_report_the_total(self) -> None:
        app = self.app
        app._export_started("图片", 3)
        app._export_started("LUT", 3)
        app.runner.queued = 2  # neither has started yet
        app._refresh_busy()
        self.assertIn("共 2 个导出排队", app.busy_var.value)

    def test_ai_and_export_share_the_line(self) -> None:
        app = self.app
        app._export_started("图片", 4)
        app._ai_busy = True
        app.runner.queued = 0
        app._refresh_busy()
        self.assertEqual(app.busy_var.value, "正在导出图片 rev 4… · AI 请求中…")
        app._ai_busy = False
        app._refresh_busy()
        self.assertEqual(app.busy_var.value, "正在导出图片 rev 4…")

    def test_finishing_an_unknown_export_keeps_the_other_ticket(self) -> None:
        app = self.app
        app._export_started("图片", 7)
        second = app._export_started("图片", 8)
        self._finish(second, "图片")
        self.assertEqual(
            [(t.kind, t.revision) for t in app._export_tickets], [("图片", 7)]
        )

    def test_tokens_keep_same_kind_same_revision_apart(self) -> None:
        # Two identical exports (same kind, same revision) used to collapse
        # into one label, so finishing either one cleared the other's status.
        app = self.app
        first = app._export_started("图片", 11, "a.jpg")
        second = app._export_started("图片", 11, "a.jpg")
        self.assertNotEqual(first, second)
        self._finish(second, "图片")
        self.assertEqual([t.token for t in app._export_tickets], [first])
        self._finish(first, "图片")
        self.assertEqual(app._export_tickets, [])

    def test_notice_names_the_material_it_belongs_to(self) -> None:
        from app.pipeline import ExportResult

        app = self.app
        token = app._export_started("图片", 6, "portrait.jpg")
        app._handle_export(
            JobOutcome(
                tag="export-image",
                coalesce_key="export-image",
                revision=6,
                token=token,
                value=ExportResult(
                    path=Path("C:/out/portrait_graded.png"),
                    width=10,
                    height=10,
                    revision=6,
                    detail="PNG",
                ),
            ),
            "图片",
        )
        self.assertIn("portrait.jpg", app.message_var.value)
        self.assertIn("rev 6", app.message_var.value)
        self.assertIn("portrait_graded.png", app.message_var.value)
        self.assertEqual(app._export_tickets, [])

    def test_failed_export_is_attributed_and_releases_the_gate(self) -> None:
        from app import ui as ui_module

        app = self.app
        token = app._export_started("视频", 3, "clip.mp4")
        with mock.patch.object(ui_module.messagebox, "showerror"):
            app._handle_export(
                JobOutcome(
                    tag="export-video",
                    coalesce_key="export-video",
                    revision=3,
                    token=token,
                    error=RuntimeError("boom"),
                ),
                "视频",
            )
        self.assertIn("clip.mp4", app.message_var.value)
        self.assertIn("boom", app.message_var.value)
        self.assertEqual(app._export_tickets, [])
        self.assertIsNone(app._export_block_reason())

    def test_export_notice_is_not_overwritten_by_a_preview(self) -> None:
        app = self.app
        app._export_notice_until = time.monotonic() + 30.0
        app._preview_message("预览已更新 rev 9 · 120 ms")
        self.assertEqual(app.message_var.value, "")

        app._export_notice_until = 0.0
        app._preview_message("预览已更新 rev 10 · 130 ms")
        self.assertIn("rev 10", app.message_var.value)


class PollIsolationTests(unittest.TestCase):
    """A handler that raises must not swallow the other outcomes in a drain.

    The runner hands over everything it has at once, so an exception in the
    first handler used to drop the rest. With export tickets that would lose the
    ticket for good and block material switching permanently.
    """

    class _Runner:
        def __init__(self, outcomes: list[JobOutcome]) -> None:
            self._outcomes = list(outcomes)

        def poll(self) -> list[JobOutcome]:
            outcomes, self._outcomes = self._outcomes, []
            return outcomes

        def queued_count(self) -> int:
            return 0

    class _Root:
        def after(self, *_args, **_kwargs) -> None:
            return None

    def _app(self):
        from app.ui import ColorApp

        app = ColorApp.__new__(ColorApp)
        app._closing = False
        app._video_results = queue.Queue()
        app._video_progress = None
        app._ai_busy = False
        app._export_tickets = []
        app._export_seq = 0
        app.state = AppState()
        app.busy_var = BusyStatusTests._Var()
        app.message_var = BusyStatusTests._Var()
        app.message_label = BusyStatusTests._Label()
        app.root = self._Root()
        app.runner = self._Runner([])
        app.ai_runner = self._Runner([])
        return app

    def test_one_failing_handler_does_not_drop_the_next_outcome(self) -> None:
        seen: list[str] = []
        app = self._app()

        def dispatch(outcome: JobOutcome) -> None:
            seen.append(outcome.tag)
            if outcome.tag == "preview":
                raise RuntimeError("boom")

        app._dispatch_outcome = dispatch
        app.runner = self._Runner(
            [
                JobOutcome("preview", "preview", 1),
                JobOutcome("export-image", "export-image", 2),
            ]
        )
        app._poll()
        self.assertEqual(seen, ["preview", "export-image"])

    def test_failed_export_handler_still_releases_its_ticket(self) -> None:
        app = self._app()
        token = app._export_started("图片", 4, "scene.jpg")
        app._video_progress = None
        # A result object without the expected attributes makes the notice
        # formatting fail after the ticket was consumed.
        with self.assertRaises(AttributeError):
            app._handle_export(
                JobOutcome(
                    "export-image", "export-image", 4, token=token, value=object()
                ),
                "图片",
            )
        self.assertEqual(app._export_tickets, [])
        self.assertIsNone(app._export_block_reason())


class MaterialSwitchGateTests(unittest.TestCase):
    """An accepted export pins the current material until it reports back.

    The gate is checked before decoding and before the document is replaced, so
    a refused switch leaves the visible material and its state untouched.
    """

    class _Runner:
        def __init__(self, queued: int = 0) -> None:
            self.queued = queued

        def queued_count(self) -> int:
            return self.queued

    class _Root:
        def update_idletasks(self) -> None:
            return None

    def setUp(self) -> None:
        from app import ui as ui_module

        self.ui = ui_module
        self.source = image_io.SourceImage(
            path=Path("original.jpg"),
            fingerprint="fp-original",
            width=4,
            height=4,
            image=Image.new("RGBA", (4, 4), (128, 128, 128, 255)),
        )
        app = ui_module.ColorApp.__new__(ui_module.ColorApp)
        app._closing = False
        app.pipeline = object()  # truthy: the pipeline check must pass
        app._worker_detail = ""
        app._worker_ok = True
        app.state = AppState()
        app.state.source = self.source
        app.busy_var = BusyStatusTests._Var()
        app.message_var = BusyStatusTests._Var()
        app.message_label = BusyStatusTests._Label()
        app._ai_busy = False
        app._export_tickets = []
        app._export_seq = 0
        app._export_notice_until = 0.0
        app._video_progress = None
        app.root = self._Root()
        app.runner = self._Runner()
        self.app = app

    def test_switch_is_refused_while_an_export_is_pending(self) -> None:
        app = self.app
        document_before = app.state.document_id
        app._export_started("图片", 3, "original.jpg")

        with mock.patch.object(
            self.ui.image_io, "load_source_image"
        ) as load, mock.patch.object(self.ui.messagebox, "showwarning") as warn:
            app.load_path(Path("other.jpg"))

        load.assert_not_called()
        warn.assert_called_once()
        self.assertIn("暂时无法切换", warn.call_args[0][1])
        self.assertEqual(app.state.document_id, document_before)
        self.assertIs(app.state.source, self.source)
        self.assertIn("暂时无法切换", app.message_var.value)

    def test_block_message_counts_the_remaining_exports(self) -> None:
        app = self.app
        app._export_started("图片", 3, "original.jpg")
        app._export_started("LUT", 3, "original.jpg")
        app.runner.queued = 1
        self.assertIn("剩余 2 项", app._export_block_reason() or "")

    def test_switch_proceeds_once_the_ticket_is_released(self) -> None:
        app = self.app
        token = app._export_started("图片", 3, "original.jpg")
        app._export_take(token, "图片")

        with mock.patch.object(
            self.ui.image_io,
            "load_source_image",
            side_effect=ImageError("IMAGE_INVALID", "probe"),
        ) as load, mock.patch.object(self.ui.messagebox, "showerror"):
            app.load_path(Path("other.jpg"))

        load.assert_called_once()
        self.assertIn("probe", app.message_var.value)

    def test_previews_alone_never_block_a_switch(self) -> None:
        # A coalescible preview is cancelled constantly while dragging; treating
        # it as an outstanding export would lock the UI on every slider move.
        app = self.app
        app.state.busy_revision = 9
        app.runner.queued = 0
        self.assertIsNone(app._export_block_reason())

    def test_initial_load_is_allowed_even_with_a_queued_fifo(self) -> None:
        app = self.app
        app.state.source = None
        app.runner.queued = 1
        app.state.document_id = ""
        with mock.patch.object(
            self.ui.image_io,
            "load_source_image",
            side_effect=ImageError("IMAGE_INVALID", "probe"),
        ) as load, mock.patch.object(self.ui.messagebox, "showerror"):
            app.load_path(Path("first.jpg"))
        load.assert_called_once()


class AiGenerationTests(unittest.TestCase):
    """A superseded AI request must not clear the newer request's status."""

    def setUp(self) -> None:
        from app.ui import ColorApp

        class _Var:
            def __init__(self) -> None:
                self.value = ""

            def set(self, value: str) -> None:
                self.value = value

        class _Label:
            def __init__(self) -> None:
                self.style = ""

            def configure(self, **kwargs) -> None:
                self.style = kwargs.get("style", self.style)

        app = ColorApp.__new__(ColorApp)
        app.busy_var = _Var()
        app.message_var = _Var()
        app.message_label = _Label()
        app.state = AppState()
        app._export_tickets = []
        app._export_seq = 0
        app._ai_busy = True
        app._ai_request_seq = 2
        app.runner = BusyStatusTests._Runner()
        app.ai_runner = None
        app._refresh_busy()
        self.app = app

    def test_stale_ai_outcome_is_ignored(self) -> None:
        from app.jobs import JobOutcome

        app = self.app
        stale = JobOutcome("ai", "ai", revision=1, cancelled=True, token=1)
        app._handle_ai(stale)
        self.assertTrue(app._ai_busy, "newer request still owns the busy line")
        self.assertEqual(app.message_var.value, "")
        self.assertIn("AI 请求中", app.busy_var.value)

    def test_current_ai_cancellation_is_reported(self) -> None:
        from app.jobs import JobOutcome

        app = self.app
        current = JobOutcome("ai", "ai", revision=1, cancelled=True, token=2)
        app._handle_ai(current)
        self.assertFalse(app._ai_busy)
        self.assertEqual(app.message_var.value, "AI 请求已取消")
        self.assertEqual(app.busy_var.value, "")


class StateTests(unittest.TestCase):
    def test_t11_split_composite_boundaries(self) -> None:
        from app.ui import ColorApp

        view = ColorApp.__new__(ColorApp)
        view.state = AppState()
        original = Image.new("RGBA", (10, 4), (255, 0, 0, 255))
        processed = Image.new("RGBA", (10, 4), (0, 0, 255, 255))
        view._original_preview = original
        view._processed_preview = processed

        self.assertIs(ColorApp._composite_preview(view), processed)

        view.state.show_split = True
        for split in (0.0, 0.5, 1.0):
            with self.subTest(split=split):
                view.state.split_t = split
                result = ColorApp._composite_preview(view)
                arr = np.asarray(result)
                if split == 0.0:
                    self.assertTrue(np.all(arr == (255, 0, 0, 255)))
                elif split == 1.0:
                    self.assertIs(result, processed)
                else:
                    self.assertTrue(np.all(arr[:, :5] == (0, 0, 255, 255)))
                    self.assertTrue(np.all(arr[:, 5:] == (255, 0, 0, 255)))

        view.state.hold_original = True
        view.state.split_t = 1.0
        self.assertIs(ColorApp._composite_preview(view), original)

    def test_new_document_resets_edits(self) -> None:
        state = AppState()
        source = image_io.load_source_image(FIXTURES["pattern"])
        state.new_document(source)
        document_id = state.document_id
        revision = state.revision
        self.assertTrue(document_id)
        self.assertTrue(state.params.is_identity())
        self.assertEqual(state.strength, 1.0)

        state.set_params(load_preset("warm")[0])
        state.set_strength(0.4)
        self.assertGreater(state.revision, revision)
        self.assertTrue(state.dirty)

        state.new_document(source)
        self.assertNotEqual(state.document_id, document_id)
        self.assertTrue(state.params.is_identity())
        self.assertEqual(state.strength, 1.0)
        self.assertFalse(state.dirty)


if __name__ == "__main__":
    unittest.main()
