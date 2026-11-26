"""Dimension 4 - objective quality of the five built-in grading presets.

Each preset is baked to a 33^3 LUT and applied through the CPU reference path
(``apply_effect_to_rgba``), which is bit-exact with the GLSL shader. Grading the
whole image rather than a patch means SSIM can answer "did the look destroy
structure?" while the histogram statistics answer "what happened to the tonal
range?".

Metrics (original -> graded):
    SSIM                structure preservation, 0..1
    mean luma           exposure shift, 0..255
    contrast std        tonal spread, 0..255
    entropy             information content, bits
    clip_high/clip_low  highlight/shadow clipping %, reused from app.histogram
    colorfulness        Hasler & Suesstrunk, 0..~110
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from . import common, dataset, metrics

LUT_SIZE = 33
PRESETS = ("warm", "cool", "soft", "cinematic", "mono")


def _array(path: Path) -> np.ndarray:
    with Image.open(path) as opened:
        return np.asarray(opened.convert("RGB"), dtype=np.uint8)


def _clip_rates(rgb: np.ndarray) -> tuple[float, float]:
    from app.histogram import compute_histogram

    hist = compute_histogram(Image.fromarray(rgb, mode="RGB"))
    return hist.clip_low * 100.0, hist.clip_high * 100.0


def _measure(original: np.ndarray, graded: np.ndarray) -> dict[str, float]:
    clip_low, clip_high = _clip_rates(graded)
    return {
        "ssim": round(metrics.ssim(common.to_float01(original), common.to_float01(graded)), 5),
        "mean_luma": round(metrics.mean_luma(graded), 3),
        "contrast_std": round(metrics.contrast_std(graded), 3),
        "entropy": round(metrics.entropy_bits(graded), 4),
        "colorfulness": round(metrics.colorfulness(graded), 4),
        "clip_low": round(clip_low, 4),
        "clip_high": round(clip_high, 4),
    }


def _baseline(rgb: np.ndarray) -> dict[str, float]:
    clip_low, clip_high = _clip_rates(rgb)
    return {
        "mean_luma": round(metrics.mean_luma(rgb), 3),
        "contrast_std": round(metrics.contrast_std(rgb), 3),
        "entropy": round(metrics.entropy_bits(rgb), 4),
        "colorfulness": round(metrics.colorfulness(rgb), 4),
        "clip_low": round(clip_low, 4),
        "clip_high": round(clip_high, 4),
    }


def run(results_dir: Path) -> dict[str, Any]:
    from baker.color_transform import apply_effect_to_rgba, bake_lut
    from baker.params import list_presets, load_preset

    fixtures = common.ROOT / "runtime" / "test-fixtures"
    assets = results_dir / "assets" / "images"
    images = dataset.build_dataset(fixtures, assets, minimum=5)
    print(
        f"  [dim4] {len(images)} benchmark images "
        f"({sum(1 for i in images if i.origin == 'fixture')} fixture, "
        f"{sum(1 for i in images if i.origin == 'synthetic')} synthetic)",
        flush=True,
    )

    labels = {key: label for key, label, _ in list_presets()}
    presets: list[tuple[str, Any, np.ndarray]] = []
    for key in PRESETS:
        params, _ = load_preset(key)
        presets.append((key, params, bake_lut(params, LUT_SIZE)))

    image_rows: list[dict[str, Any]] = []
    originals: dict[str, np.ndarray] = {}
    for image in images:
        rgb = _array(image.path)
        originals[image.key] = rgb
        image_rows.append(
            {
                "key": image.key,
                "label": image.label,
                "origin": image.origin,
                "file": str(image.path.relative_to(common.ROOT)),
                "width": int(rgb.shape[1]),
                "height": int(rgb.shape[0]),
                "original": _baseline(rgb),
            }
        )
        print(f"        loaded {image.label} ({rgb.shape[1]}x{rgb.shape[0]})", flush=True)

    preset_rows: list[dict[str, Any]] = []
    for key, params, lut in presets:
        print(f"  [dim4] grading with preset '{key}' ...", flush=True)
        per_image: list[dict[str, Any]] = []
        for image in images:
            rgb = originals[image.key]
            rgba = np.dstack(
                [rgb, np.full(rgb.shape[:2], 255, dtype=np.uint8)]
            )
            graded = apply_effect_to_rgba(rgba, lut, LUT_SIZE, 1.0)[..., :3]
            measured = _measure(rgb, graded)
            measured["key"] = image.key
            measured["label"] = image.label
            per_image.append(measured)

        keys = ("ssim", "mean_luma", "contrast_std", "entropy", "colorfulness", "clip_low", "clip_high")
        mean = {
            name: round(float(np.mean([row[name] for row in per_image])), 4) for name in keys
        }
        preset_rows.append(
            {
                "preset": key,
                "label": labels.get(key, key),
                "params": params.as_dict(),
                "per_image": per_image,
                "mean": mean,
            }
        )
        print(
            f"        SSIM {mean['ssim']:.4f} | luma {mean['mean_luma']:.1f}"
            f" | std {mean['contrast_std']:.1f} | entropy {mean['entropy']:.3f} bit"
            f" | colorful {mean['colorfulness']:.1f} | clip {mean['clip_low']:.2f}/{mean['clip_high']:.2f}%",
            flush=True,
        )

    baseline = {
        "ssim": 1.0,
        "mean_luma": round(float(np.mean([row["original"]["mean_luma"] for row in image_rows])), 3),
        "contrast_std": round(
            float(np.mean([row["original"]["contrast_std"] for row in image_rows])), 3
        ),
        "entropy": round(float(np.mean([row["original"]["entropy"] for row in image_rows])), 4),
        "colorfulness": round(
            float(np.mean([row["original"]["colorfulness"] for row in image_rows])), 4
        ),
        "clip_low": round(float(np.mean([row["original"]["clip_low"] for row in image_rows])), 4),
        "clip_high": round(float(np.mean([row["original"]["clip_high"] for row in image_rows])), 4),
    }

    return {
        "lut_size": LUT_SIZE,
        "presets": list(PRESETS),
        "images": image_rows,
        "baseline": baseline,
        "rows": preset_rows,
    }


__all__ = ["LUT_SIZE", "PRESETS", "run"]
