"""Histogram widget tests: binning, clipping fractions and rendering."""

from __future__ import annotations

import unittest

import numpy as np
from PIL import Image

from app.histogram import compute_histogram, render_histogram


def _gradient() -> Image.Image:
    x = np.linspace(0, 255, 256, dtype=np.uint8)
    row = np.stack([x, x, x], axis=1)
    return Image.fromarray(np.repeat(row[None, :, :], 8, axis=0), "RGB")


class HistogramTests(unittest.TestCase):
    def test_gradient_spreads_across_all_bins(self) -> None:
        hist = compute_histogram(_gradient())
        occupied = int(np.count_nonzero(hist.luma > 0))
        self.assertEqual(occupied, 256)
        self.assertAlmostEqual(float(hist.luma.sum()), 256.0, delta=1e-3)
        # The ramp touches 0..2 and 253..255, so three bins count as clipped.
        self.assertAlmostEqual(float(hist.clip_low), 3 / 256, places=4)
        self.assertAlmostEqual(float(hist.clip_high), 3 / 256, places=4)

    def test_channel_separation(self) -> None:
        arr = np.zeros((10, 10, 3), dtype=np.uint8)
        arr[..., 0] = 255  # pure red image
        hist = compute_histogram(Image.fromarray(arr, "RGB"))
        self.assertGreater(float(hist.rgb[0, 255]), 0.99)
        self.assertGreater(float(hist.rgb[1, 0]), 0.99)
        self.assertGreater(float(hist.rgb[2, 0]), 0.99)

    def test_clipping_fractions(self) -> None:
        arr = np.zeros((10, 10, 3), dtype=np.uint8)
        arr[:5] = 255
        hist = compute_histogram(Image.fromarray(arr, "RGB"))
        self.assertAlmostEqual(hist.clip_low, 0.5, places=6)
        self.assertAlmostEqual(hist.clip_high, 0.5, places=6)

    def test_render_size_and_content(self) -> None:
        current = compute_histogram(_gradient())
        original = compute_histogram(_gradient().point(lambda v: v // 2))
        image = render_histogram(current, original, 320, 64)
        self.assertEqual(image.size, (320, 64))
        self.assertEqual(image.mode, "RGB")
        array = np.asarray(image).astype(int)
        background = np.abs(array - np.array([23, 24, 28])).sum(axis=2) <= 6
        self.assertLess(float(background.mean()), 0.95)
        self.assertTrue((array.min(axis=2) > 120).any())  # luma curve drawn

    def test_transparent_pixels_composite_on_white(self) -> None:
        arr = np.zeros((4, 4, 4), dtype=np.uint8)
        arr[..., 0] = 255  # red, fully transparent
        hist = compute_histogram(Image.fromarray(arr, "RGBA"))
        self.assertGreater(float(hist.luma[255]), 0.99)
        self.assertAlmostEqual(float(hist.clip_low), 0.0, places=6)

    def test_render_empty_histogram(self) -> None:
        image = render_histogram(None, None, 120, 40)
        self.assertEqual(image.size, (120, 40))
        # Only background, grid and frame: no bright curve pixels.
        array = np.asarray(image)
        self.assertFalse((array.min(axis=2) > 120).any())


if __name__ == "__main__":
    unittest.main()
