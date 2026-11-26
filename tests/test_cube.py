from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from baker.cube_reader import CubeError, load_cube
from baker.cube_writer import CubeWriteError, write_cube


def _valid_text(size: int = 2, *, title: str = "test") -> str:
    lines = [f'TITLE "{title}"', f"LUT_3D_SIZE {size}"]
    for b in range(size):
        for g in range(size):
            for r in range(size):
                lines.append(f"{r/(size-1)} {g/(size-1)} {b/(size-1)}")
    return "\n".join(lines) + "\n"


class CubeReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, text: str, name: str = "x.cube") -> Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_valid_and_title_with_hash(self) -> None:
        text = _valid_text(2, title="hello # not a comment")
        lut = load_cube(self._write(text))
        self.assertEqual(lut.title, "hello # not a comment")
        self.assertEqual(lut.size, 2)
        self.assertEqual(lut.samples.shape, (8, 3))

    def test_bom_and_crlf(self) -> None:
        text = "\ufeff" + _valid_text(2).replace("\n", "\r\n")
        lut = load_cube(self._write(text))
        self.assertEqual(lut.size, 2)

    def test_missing_size(self) -> None:
        path = self._write(_valid_text(2).replace("LUT_3D_SIZE 2\n", ""))
        with self.assertRaises(CubeError) as ctx:
            load_cube(path)
        self.assertEqual(ctx.exception.code, "LUT_PARSE_ERROR")

    def test_duplicate_size(self) -> None:
        text = _valid_text(2).replace("LUT_3D_SIZE 2\n", "LUT_3D_SIZE 2\nLUT_3D_SIZE 2\n")
        with self.assertRaises(CubeError):
            load_cube(self._write(text))

    def test_header_after_data(self) -> None:
        text = _valid_text(2) + "LUT_3D_SIZE 2\n"
        with self.assertRaises(CubeError):
            load_cube(self._write(text))

    def test_extra_and_short_rows(self) -> None:
        text = _valid_text(2) + "0 0 0\n"
        with self.assertRaises(CubeError):
            load_cube(self._write(text))
        short = "\n".join(_valid_text(2).splitlines()[:-1]) + "\n"
        with self.assertRaises(CubeError):
            load_cube(self._write(short))

    def test_extra_token(self) -> None:
        text = _valid_text(2).replace("0.0 0.0 0.0", "0.0 0.0 0.0 1.0", 1)
        with self.assertRaises(CubeError):
            load_cube(self._write(text))

    def test_nan_inf_and_range(self) -> None:
        for token in ("nan", "inf", "70000"):
            with self.subTest(token=token):
                text = _valid_text(2).replace("0.0 0.0 0.0", f"{token} 0.0 0.0", 1)
                with self.assertRaises(CubeError):
                    load_cube(self._write(text))

    def test_1d_and_unknown(self) -> None:
        for feature in ("LUT_1D_SIZE 16", "FOO 1 2 3", "LUT_3D_INPUT_RANGE 0 1"):
            with self.subTest(feature=feature):
                text = feature + "\n" + _valid_text(2)
                with self.assertRaises(CubeError) as ctx:
                    load_cube(self._write(text))
                self.assertEqual(ctx.exception.code, "LUT_UNSUPPORTED")

    def test_invalid_domain(self) -> None:
        text = "DOMAIN_MIN 1 1 1\nDOMAIN_MAX 1 1 1\n" + _valid_text(2)
        with self.assertRaises(CubeError):
            load_cube(self._write(text))

    def test_negative_and_above_one_samples_allowed(self) -> None:
        text = _valid_text(2).replace("0.0 0.0 0.0", "-0.25 1.25 0.5", 1)
        lut = load_cube(self._write(text))
        self.assertAlmostEqual(float(lut.samples[0, 0]), -0.25, places=6)


class CubeWriterTests(unittest.TestCase):
    def test_roundtrip_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rng = np.random.default_rng(3)
            samples = rng.random((17**3, 3)).astype(np.float32)
            path = Path(tmp) / "round.cube"
            lut = write_cube(path, 17, samples)
            self.assertEqual(lut.size, 17)
            self.assertLessEqual(
                float(np.max(np.abs(lut.samples - samples))), 1e-7
            )

    def test_rejects_nonfinite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            samples = np.zeros((8, 3), dtype=np.float32)
            samples[0, 0] = np.nan
            with self.assertRaises(CubeWriteError):
                write_cube(Path(tmp) / "bad.cube", 2, samples)

    def test_rejects_wrong_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(CubeWriteError):
                write_cube(Path(tmp) / "bad.cube", 2, np.zeros((7, 3), dtype=np.float32))


if __name__ == "__main__":
    unittest.main()
