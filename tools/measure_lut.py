"""Measure 3D LUT approximation error against the CPU reference (T08).

Usage:
    .venv/Scripts/python.exe tools/measure_lut.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from baker.color_transform import bake_lut, lut_grid, sample_lut, transform_rgb  # noqa: E402
from baker.params import ColorParams, list_presets  # noqa: E402


def measure(params: ColorParams, size: int, points: np.ndarray) -> dict[str, float]:
    direct = transform_rgb(points, params)
    baked = bake_lut(params, size)
    sampled = sample_lut(baked, size, points)
    diff = np.abs(sampled - direct) * 255.0
    return {
        "size": size,
        "mae": round(float(np.mean(diff)), 4),
        "p99": round(float(np.percentile(diff, 99)), 4),
        "max": round(float(np.max(diff)), 4),
    }


def main() -> int:
    rng = np.random.default_rng(20261020)
    random_points = rng.random((100_000, 3))
    _values, grid = lut_grid(33)
    # Include the LUT grid itself, plus 8-bit quantized colours.
    quantized = np.round(rng.random((10_000, 3)) * 255.0) / 255.0
    points = np.vstack([random_points, quantized, grid])

    report: dict[str, object] = {"points": int(len(points)), "presets": {}}
    for key, label, params in list_presets():
        entries = []
        for size in (33, 65):
            entries.append(measure(params, size, points))
        report["presets"][key] = {
            "label": label,
            "params": params.as_dict(),
            "results": entries,
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
