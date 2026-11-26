"""Integration tests against the real render_worker.exe (T01-T05, T14).

These tests need the ARM64 worker and its Mesa runtime to be present. They do
not need a window: the worker renders offscreen into an FBO.
"""

from __future__ import annotations

import struct
import tempfile
import threading
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from app import image_io, paths
from app.engine_client import EngineClient, EngineError
from baker.color_transform import bake_lut, lut_grid, sample_lut
from baker.cube_writer import write_cube
from baker.params import ColorParams


def setUpModule() -> None:
    paths.ensure_runtime()


def _rgba(colors: list[tuple[int, int, int, int]], width: int = 16) -> np.ndarray:
    rows = (len(colors) + width - 1) // width
    padded = colors + [(0, 0, 0, 255)] * (rows * width - len(colors))
    return np.array(padded, dtype=np.uint8).reshape(rows, width, 4)


class WorkerTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = EngineClient(timeout=60.0)
        cls._tmp = tempfile.TemporaryDirectory(prefix="engine-test-")
        cls.dir = Path(cls._tmp.name)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _write_lut(
        self,
        name: str,
        size: int,
        samples: np.ndarray,
        *,
        domain_min: tuple[float, float, float] = (0.0, 0.0, 0.0),
        domain_max: tuple[float, float, float] = (1.0, 1.0, 1.0),
    ) -> Path:
        target = self.dir / name
        write_cube(
            target,
            size,
            samples,
            domain_min=domain_min,
            domain_max=domain_max,
        )
        return target

    def _render(
        self,
        array: np.ndarray,
        lut_path: Path,
        strength: float = 1.0,
        *,
        name: str = "input",
    ):
        input_path = self.dir / f"{name}.rgba"
        image_io.write_rgba_bridge(input_path, Image.fromarray(array, "RGBA"))
        return self.client.render(
            input_path,
            lut_path,
            strength,
            document_id="doc-engine-test",
            revision=7,
        )

    def _rgb_diff(self, actual: Image.Image, expected: np.ndarray) -> int:
        got = np.asarray(actual.convert("RGBA"), dtype=np.int16)
        want = expected.astype(np.int16)
        return int(np.max(np.abs(got[..., :3] - want[..., :3])))


class SamplingTests(WorkerTestCase):
    def test_t01_identity_lut_sizes(self) -> None:
        rng = np.random.default_rng(20261020)
        colors: list[tuple[int, int, int, int]] = []
        for value in range(256):  # full 8-bit grey ramp
            colors.append((value, value, value, value))
        colors.extend(
            [
                (255, 0, 0, 255),
                (0, 255, 0, 128),
                (0, 0, 255, 0),
                (255, 255, 255, 255),
            ]
        )
        random_rgb = rng.integers(0, 256, size=(400, 3), dtype=np.uint8)
        random_alpha = rng.integers(0, 256, size=(400, 1), dtype=np.uint8)
        colors.extend(
            tuple(int(v) for v in row)  # type: ignore[misc]
            for row in np.hstack([random_rgb, random_alpha])
        )
        image = _rgba(colors, width=33)

        for size in (17, 33, 65):
            with self.subTest(size=size):
                lut = self._write_lut(
                    f"identity{size}.cube",
                    size,
                    bake_lut(ColorParams.identity(), size),
                )
                outcome = self._render(image, lut, name=f"t01-{size}")
                self.assertLessEqual(self._rgb_diff(outcome.image, image), 1)
                alpha_out = np.asarray(outcome.image.convert("RGBA"))[..., 3]
                self.assertTrue(np.array_equal(alpha_out, image[..., 3]))
                self.assertIn("render_readback_ms", outcome.metrics)

    def test_t02_known_mappings(self) -> None:
        size = 33
        _values, grid = lut_grid(size)
        swapped = np.ascontiguousarray(grid[:, [2, 1, 0]])
        red = np.zeros((size**3, 3), dtype=np.float64)
        red[:, 0] = 1.0
        black = np.zeros((size**3, 3), dtype=np.float64)

        image = _rgba(
            [
                (255, 0, 0, 255),
                (0, 255, 0, 200),
                (0, 0, 255, 100),
                (0, 0, 0, 255),
                (17, 200, 99, 255),
                (128, 128, 128, 255),
            ],
            width=6,
        )
        zeros = np.zeros_like(image[..., :3])
        cases = {
            "swap": (swapped, np.stack([image[..., 2], image[..., 1], image[..., 0]], axis=-1)),
            "red": (red, np.dstack([np.full(image.shape[:2], 255, dtype=np.uint8), zeros[..., 1], zeros[..., 2]])),
            "black": (black, zeros),
        }
        for name, (samples, expected) in cases.items():
            with self.subTest(case=name):
                lut = self._write_lut(f"t02-{name}.cube", size, samples)
                outcome = self._render(image, lut, name=f"t02-{name}")
                self.assertLessEqual(self._rgb_diff(outcome.image, expected), 1)

    def test_t03_domain_and_out_of_range(self) -> None:
        size = 33
        _values, grid = lut_grid(size)
        samples = np.stack(
            [
                np.sqrt(grid[:, 0]),
                grid[:, 1] ** 2,
                0.5 * (grid[:, 0] + grid[:, 2]),
            ],
            axis=1,
        )
        domain_min = (0.1, 0.2, 0.3)
        domain_max = (0.9, 0.8, 0.7)
        rng = np.random.default_rng(11)
        rgb = rng.random((2000, 3))
        rgb[:20] = 0.0  # below DOMAIN_MIN
        rgb[20:40] = 1.0  # above DOMAIN_MAX
        rgb = np.clip(rgb, 0.0, 1.0)
        image = np.round(
            np.hstack([rgb * 255.0, np.full((len(rgb), 1), 255.0)])
        ).astype(np.uint8).reshape(40, 50, 4)

        lut = self._write_lut(
            "t03-domain.cube",
            size,
            samples,
            domain_min=domain_min,
            domain_max=domain_max,
        )
        outcome = self._render(image, lut, name="t03")
        expected = sample_lut(
            samples,
            size,
            image[..., :3].astype(np.float64) / 255.0,
            domain_min,
            domain_max,
        )
        expected_u8 = np.round(expected * 255.0)
        self.assertLessEqual(self._rgb_diff(outcome.image, expected_u8), 1)

    def test_t03_strength_mixes_identity(self) -> None:
        size = 17
        _values, grid = lut_grid(size)
        samples = grid[:, [2, 1, 0]]
        image = _rgba([(200, 100, 50, 255)], width=1)
        lut = self._write_lut("t03-swap17.cube", size, samples)
        outcome = self._render(image, lut, strength=0.25, name="t03-strength")
        expected = np.clip(0.75 * image[..., :3] + 0.25 * image[..., [2, 1, 0]], 0, 255)
        self.assertLessEqual(self._rgb_diff(outcome.image, expected), 1)


class ProtocolErrorTests(WorkerTestCase):
    def test_t04_lut_errors_are_typed(self) -> None:
        image = _rgba([(10, 20, 30, 255)], width=1)
        bad = self.dir / "bad.cube"
        bad.write_text("LUT_3D_SIZE 33\n0 0 0\n", encoding="utf-8")
        with self.assertRaises(EngineError) as ctx:
            self._render(image, bad)
        self.assertEqual(ctx.exception.code, "LUT_PARSE_ERROR")

        one_d = self.dir / "one-d.cube"
        one_d.write_text("LUT_1D_SIZE 2\n0 0 0\n1 1 1\n", encoding="utf-8")
        with self.assertRaises(EngineError) as ctx:
            self._render(image, one_d)
        self.assertEqual(ctx.exception.code, "LUT_UNSUPPORTED")

        missing = self.dir / "missing.cube"
        with self.assertRaises(EngineError) as ctx:
            self._render(image, missing)
        self.assertEqual(ctx.exception.code, "EXPORT_IO")

        duplicate = self.dir / "duplicate.cube"
        duplicate.write_text(
            "LUT_3D_SIZE 2\nLUT_3D_SIZE 2\n" + "0 0 0\n" * 8, encoding="utf-8"
        )
        with self.assertRaises(EngineError) as ctx:
            self._render(image, duplicate)
        self.assertEqual(ctx.exception.code, "LUT_PARSE_ERROR")

    def test_t04_strength_out_of_range_rejected(self) -> None:
        image = _rgba([(1, 2, 3, 255)], width=1)
        lut = self._write_lut(
            "identity2.cube", 2, bake_lut(ColorParams.identity(), 2)
        )
        with self.assertRaises(EngineError) as ctx:
            self._render(image, lut, strength=1.5)
        self.assertEqual(ctx.exception.code, "INVALID_REQUEST")
        self.assertEqual(ctx.exception.stage, "request")

    def test_t05_bad_rgba_bridge_rejected_before_gl(self) -> None:
        lut = self._write_lut(
            "identity2b.cube", 2, bake_lut(ColorParams.identity(), 2)
        )
        width, height = 4, 2
        header = struct.pack("<8sIIII", image_io.RGBA_MAGIC, width, height, width * 4, 1)
        cases = {
            "truncated": header + b"\x00" * 8,
            "bad-magic": struct.pack("<8sIIII", b"BADMAGIC", width, height, width * 4, 1)
            + b"\x00" * (width * height * 4),
            "stride": struct.pack("<8sIIII", image_io.RGBA_MAGIC, width, height, width * 3, 1)
            + b"\x00" * (width * height * 4),
        }
        for name, payload in cases.items():
            with self.subTest(case=name):
                broken = self.dir / f"t05-{name}.rgba"
                broken.write_bytes(payload)
                with self.assertRaises(EngineError) as ctx:
                    self.client.render(
                        broken,
                        lut,
                        1.0,
                        document_id="doc-engine-test",
                        revision=7,
                    )
                self.assertEqual(ctx.exception.code, "IMAGE_INVALID")
                self.assertEqual(ctx.exception.stage, "image")

    def test_t14_missing_worker_is_reported(self) -> None:
        client = EngineClient(worker=self.dir / "does-not-exist.exe")
        image = _rgba([(0, 0, 0, 255)], width=1)
        input_path = self.dir / "t14.rgba"
        image_io.write_rgba_bridge(input_path, Image.fromarray(image, "RGBA"))
        lut = self._write_lut(
            "identity2c.cube", 2, bake_lut(ColorParams.identity(), 2)
        )
        with self.assertRaises(EngineError) as ctx:
            client.render(input_path, lut, 1.0, document_id="doc", revision=1)
        self.assertEqual(ctx.exception.code, "PROCESS_CRASHED")

    def test_t14_cancel_before_start(self) -> None:
        image = _rgba([(0, 0, 0, 255)], width=1)
        input_path = self.dir / "t14-cancel.rgba"
        image_io.write_rgba_bridge(input_path, Image.fromarray(image, "RGBA"))
        lut = self._write_lut(
            "identity2d.cube", 2, bake_lut(ColorParams.identity(), 2)
        )
        event = threading.Event()
        event.set()
        with self.assertRaises(EngineError) as ctx:
            self.client.render(
                input_path,
                lut,
                1.0,
                document_id="doc",
                revision=1,
                cancel_event=event,
            )
        self.assertEqual(ctx.exception.code, "CANCELLED")

    def test_successful_render_cleans_its_job_directory(self) -> None:
        before = {p.name for p in paths.JOBS.iterdir()} if paths.JOBS.is_dir() else set()
        image = _rgba([(12, 34, 56, 255)], width=1)
        lut = self._write_lut(
            "identity2e.cube", 2, bake_lut(ColorParams.identity(), 2)
        )
        outcome = self._render(image, lut, name="jobdir")
        self.assertFalse(outcome.job_dir.exists())
        after = {p.name for p in paths.JOBS.iterdir()} if paths.JOBS.is_dir() else set()
        self.assertEqual(before, after)

    def test_keep_job_dir_flag_leaves_diagnostics_on_disk(self) -> None:
        image = _rgba([(12, 34, 56, 255)], width=1)
        input_path = self.dir / "keep.rgba"
        image_io.write_rgba_bridge(input_path, Image.fromarray(image, "RGBA"))
        lut = self._write_lut(
            "identity2f.cube", 2, bake_lut(ColorParams.identity(), 2)
        )
        outcome = self.client.render(
            input_path,
            lut,
            1.0,
            document_id="doc",
            revision=2,
            keep_job_dir=True,
        )
        try:
            self.assertTrue(outcome.job_dir.is_dir())
            self.assertTrue((outcome.job_dir / "response.json").is_file())
        finally:
            import shutil

            shutil.rmtree(outcome.job_dir, ignore_errors=True)

    def test_cancelled_render_leaves_no_job_directory(self) -> None:
        # A rapid slider drag cancels renders constantly; each one used to leave
        # a job directory behind until the next startup sweep.
        image = _rgba([(0, 0, 0, 255)], width=1)
        input_path = self.dir / "cancel-clean.rgba"
        image_io.write_rgba_bridge(input_path, Image.fromarray(image, "RGBA"))
        lut = self._write_lut(
            "identity2h.cube", 2, bake_lut(ColorParams.identity(), 2)
        )
        before = {p.name for p in paths.JOBS.iterdir()}
        event = threading.Event()
        event.set()
        with self.assertRaises(EngineError) as ctx:
            self.client.render(
                input_path,
                lut,
                1.0,
                document_id="doc",
                revision=1,
                cancel_event=event,
            )
        self.assertEqual(ctx.exception.code, "CANCELLED")
        after = {p.name for p in paths.JOBS.iterdir()}
        self.assertEqual(before, after)

    def test_t14_foreign_binary_as_worker_is_reported(self) -> None:
        # Simulates a corrupt/mismatched worker: the process starts, exits
        # without writing a response, and must surface as PROCESS_CRASHED with
        # the job directory kept for diagnosis.
        import os

        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        impostor = Path(system_root) / "System32" / "where.exe"
        if not impostor.is_file():
            self.skipTest("no suitable foreign executable available")
        client = EngineClient(worker=impostor, timeout=10.0)
        image = _rgba([(0, 0, 0, 255)], width=1)
        input_path = self.dir / "t14-impostor.rgba"
        image_io.write_rgba_bridge(input_path, Image.fromarray(image, "RGBA"))
        lut = self._write_lut(
            "identity2g.cube", 2, bake_lut(ColorParams.identity(), 2)
        )
        before = {p.name for p in paths.JOBS.iterdir()}
        with self.assertRaises(EngineError) as ctx:
            client.render(input_path, lut, 1.0, document_id="doc", revision=1)
        self.assertEqual(ctx.exception.code, "PROCESS_CRASHED")
        leftovers = {
            p.name for p in paths.JOBS.iterdir()
        } - before
        self.assertTrue(leftovers, "failed job directory should be kept")
        import shutil

        for name in leftovers:
            shutil.rmtree(paths.JOBS / name, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
