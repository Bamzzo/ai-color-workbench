from __future__ import annotations

import unittest

import numpy as np

from baker import color_transform as C
from baker.params import ColorParams, load_preset


class ColorTransformTests(unittest.TestCase):
    def test_identity_lut_is_exact_grid(self) -> None:
        n = 33
        _values, grid = C.lut_grid(n)
        baked = C.bake_lut(ColorParams.identity(), n)
        self.assertEqual(baked.shape, (n**3, 3))
        self.assertLessEqual(
            float(np.max(np.abs(baked.astype(np.float64) - grid))), 1e-6
        )

    def test_identity_is_exact_on_random_colours(self) -> None:
        rng = np.random.default_rng(7)
        rgb = rng.random((10000, 3))
        out = C.transform_rgb(rgb, ColorParams.identity())
        self.assertLessEqual(float(np.max(np.abs(out - rgb))), 1e-12)

    def test_exposure_direction(self) -> None:
        rgb = np.array([[0.5, 0.5, 0.5]])
        up = C.transform_rgb(rgb, ColorParams(exposure_ev=0.5))
        down = C.transform_rgb(rgb, ColorParams(exposure_ev=-0.5))
        self.assertTrue(np.all(up > rgb))
        self.assertTrue(np.all(down < rgb))

    def test_temperature_direction(self) -> None:
        rgb = np.array([[0.5, 0.5, 0.5]])
        warm = C.transform_rgb(rgb, ColorParams(temperature=50))[0]
        cool = C.transform_rgb(rgb, ColorParams(temperature=-50))[0]
        self.assertGreater(warm[0], warm[2])
        self.assertLess(cool[0], cool[2])

    def test_tint_direction_is_magenta(self) -> None:
        rgb = np.array([[0.5, 0.5, 0.5]])
        tinted = C.transform_rgb(rgb, ColorParams(tint=50))[0]
        self.assertGreater(tinted[0], tinted[1])
        self.assertGreater(tinted[2], tinted[1])

    def test_contrast_keeps_endpoints(self) -> None:
        rgb = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]])
        out = C.transform_rgb(rgb, ColorParams(contrast=60))
        np.testing.assert_allclose(out, rgb, atol=1e-12)

    def test_contrast_direction(self) -> None:
        rgb = np.array([[0.25, 0.25, 0.25], [0.75, 0.75, 0.75]])
        out = C.transform_rgb(rgb, ColorParams(contrast=50))
        self.assertLess(out[0, 0], 0.25)
        self.assertGreater(out[1, 0], 0.75)

    def test_shadows_and_highlights_direction(self) -> None:
        dark = np.array([[0.08, 0.08, 0.08]])
        bright = np.array([[0.92, 0.92, 0.92]])
        shadow_up = C.transform_rgb(dark, ColorParams(shadows=60))
        shadow_down = C.transform_rgb(dark, ColorParams(shadows=-60))
        self.assertTrue(np.all(shadow_up > dark))
        self.assertTrue(np.all(shadow_down < dark))
        highlight_up = C.transform_rgb(bright, ColorParams(highlights=60))
        highlight_down = C.transform_rgb(bright, ColorParams(highlights=-60))
        self.assertTrue(np.all(highlight_up >= bright))
        self.assertTrue(np.all(highlight_down <= bright))

    def test_saturation_minus_100_is_gray(self) -> None:
        rgb = np.array([[0.8, 0.2, 0.1], [0.3, 0.6, 0.9]])
        out = C.transform_rgb(rgb, ColorParams(saturation=-100))
        np.testing.assert_allclose(out[:, 0], out[:, 1], atol=1e-12)
        np.testing.assert_allclose(out[:, 1], out[:, 2], atol=1e-12)

    def test_bake_is_byte_repeatable(self) -> None:
        params, _ = load_preset("warm")
        first = C.bake_lut(params, 33).tobytes()
        second = C.bake_lut(params, 33).tobytes()
        self.assertEqual(first, second)

    def test_strength_mix_is_linear(self) -> None:
        params, _ = load_preset("warm")
        base = C.bake_lut(params, 17)
        _values, grid = C.lut_grid(17)
        mixed = C.apply_strength(base, 17, 0.25)
        expected = 0.75 * grid + 0.25 * base
        self.assertLessEqual(
            float(np.max(np.abs(mixed - expected))), 2e-7
        )

    def test_lut_approximation_33(self) -> None:
        params, _ = load_preset("warm")
        rng = np.random.default_rng(20261020)
        points = rng.random((50000, 3))
        direct = C.transform_rgb(points, params)
        baked = C.bake_lut(params, 33)
        sampled = C.sample_lut(baked, 33, points)
        diff = np.abs(sampled - direct) * 255.0
        self.assertLessEqual(float(np.max(diff)), 8.0)
        self.assertLessEqual(float(np.percentile(diff, 99)), 3.0)

    def test_lut_approximation_33_with_split_toning(self) -> None:
        params, _ = load_preset("cinematic")
        rng = np.random.default_rng(11)
        points = rng.random((40000, 3))
        direct = C.transform_rgb(points, params)
        sampled = C.sample_lut(C.bake_lut(params, 33), 33, points)
        diff = np.abs(sampled - direct) * 255.0
        self.assertLessEqual(float(np.max(diff)), 8.0)
        self.assertLessEqual(float(np.percentile(diff, 99)), 3.0)

    def test_whites_and_blacks_only_move_the_extremes(self) -> None:
        rgb = np.array([[0.05, 0.05, 0.05], [0.5, 0.5, 0.5], [0.95, 0.95, 0.95]])
        whites = C.transform_rgb(rgb, ColorParams(whites=80))
        blacks = C.transform_rgb(rgb, ColorParams(blacks=80))
        # Whites lift the top tone and barely touch the midtone.
        self.assertGreater(whites[2, 0], 0.95)
        self.assertAlmostEqual(float(whites[1, 0]), 0.5, places=3)
        # Blacks raise the bottom tone (matte look) without changing the top.
        self.assertGreater(blacks[0, 0], 0.05)
        self.assertAlmostEqual(float(blacks[2, 0]), 0.95, places=6)

    def test_vibrance_protects_saturated_colours(self) -> None:
        rgb = np.array([[0.95, 0.05, 0.05], [0.55, 0.52, 0.50]])
        out = C.transform_rgb(rgb, ColorParams(vibrance=60))
        # Compare *relative* chroma growth: the muted colour should gain a much
        # larger fraction of its chroma than the already saturated red.
        chroma_in = rgb.max(axis=1) - rgb.min(axis=1)
        chroma_out = out.max(axis=1) - out.min(axis=1)
        growth = chroma_out / chroma_in
        self.assertGreater(float(growth[1]), float(growth[0]) * 1.4)

    def test_shadows_highlight_tint_hues(self) -> None:
        low = np.array([[0.10, 0.10, 0.10]])
        high = np.array([[0.90, 0.90, 0.90]])
        shadow_tint = C.transform_rgb(
            low, ColorParams(split_shadow_hue=240, split_shadow_amount=60)
        )[0]
        highlight_tint = C.transform_rgb(
            high, ColorParams(split_highlight_hue=60, split_highlight_amount=60)
        )[0]
        self.assertGreater(shadow_tint[2], shadow_tint[0])  # blue shadows
        self.assertGreater(highlight_tint[0], highlight_tint[2])  # warm highlights

    def test_hue_rotation_moves_red_towards_green(self) -> None:
        rgb = np.array([[0.9, 0.05, 0.05]])
        out = C.transform_rgb(rgb, ColorParams(hue=120))[0]
        self.assertGreater(out[1], out[0])

    def test_hue_rotation_preserves_gray(self) -> None:
        rgb = np.array([[0.42, 0.42, 0.42]])
        out = C.transform_rgb(rgb, ColorParams(hue=-137))
        np.testing.assert_allclose(out, rgb, atol=1e-9)

    def test_strength_zero_is_identity_on_gpu_formula(self) -> None:
        params, _ = load_preset("cool")
        baked = C.bake_lut(params, 33)
        rgb = np.array([[0.7, 0.2, 0.4]])
        out = C.apply_effect_to_rgb(rgb, baked, 33, strength=0.0)
        np.testing.assert_allclose(out, rgb, atol=1e-12)


if __name__ == "__main__":
    unittest.main()
