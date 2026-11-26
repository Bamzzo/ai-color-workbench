"""Dimension 2 - how much accuracy a 17^3 / 33^3 / 65^3 LUT costs.

The ground truth is the exact float64 evaluation of the 16-parameter pipeline
(``transform_rgb``). Each LUT size is baked from the same parameters, sampled
with the GPU-equivalent trilinear filter and compared against that truth on a
dense full-gamut probe (a 64^3 RGB lattice laid out as a 512x512 card).

Besides accuracy the dimension records the two engineering costs that decide
which grid the product uses: bake time (CPU, ms) and the base64 payload the API
ships to the browser (``/api/lut`` sends float32 samples, base64-encoded).
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import numpy as np

from . import common, metrics
from .interpolation import trilinear_sample

PRESET = "cinematic"
SIZES = (17, 33, 65)
PROBE_GRID = 64


def build_probe() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (rgb01, rgb_uint8, card_uint8) for a dense 64^3 gamut probe."""
    from baker.color_transform import lut_grid

    _, grid = lut_grid(PROBE_GRID)
    rgb01 = np.asarray(grid, dtype=np.float64)
    rgb_uint8 = common.to_uint8(rgb01)
    card = rgb_uint8.reshape(512, 512, 3)
    return rgb01, rgb_uint8, card


def payload_kb(samples: np.ndarray) -> float:
    """Exact size of the ``data_b64`` field produced by ``api.server._lut_payload``."""
    raw = np.ascontiguousarray(samples, dtype=np.float32).tobytes()
    return len(base64.standard_b64encode(raw)) / 1024.0


def run(results_dir: Path | None = None) -> dict[str, Any]:
    from baker.params import load_preset

    params, _ = load_preset(PRESET)
    rgb01, rgb_uint8, card = build_probe()

    print(f"  [dim2] baking ground truth for {PROBE_GRID}^3 probe ...", flush=True)
    truth01 = metrics_transform(rgb01, params)
    truth_uint8 = common.to_uint8(truth01)
    truth_lab = metrics.srgb8_to_lab(truth_uint8)

    rows: list[dict[str, Any]] = []
    for size in SIZES:
        print(f"  [dim2] LUT {size}^3 ...", flush=True)
        samples, bake_ms = common.bake_timed(params, size)
        sampled01 = trilinear_sample(samples, size, rgb01)
        sampled01 = np.clip(sampled01, 0.0, 1.0)
        sampled_uint8 = common.to_uint8(sampled01)
        sampled_lab = metrics.srgb8_to_lab(sampled_uint8)

        de76 = metrics.delta_e_stats(truth_lab, sampled_lab, ciede2000=False)
        de00 = metrics.delta_e_stats(truth_lab, sampled_lab, ciede2000=True)
        rows.append(
            {
                "size": size,
                "vertices": size**3,
                "psnr_db": round(metrics.psnr_uint8(truth_uint8, sampled_uint8), 3),
                "mae": round(metrics.mae_uint8(truth_uint8, sampled_uint8), 4),
                "max_abs_error": int(
                    np.max(np.abs(truth_uint8.astype(np.int16) - sampled_uint8.astype(np.int16)))
                ),
                "de76_mean": round(de76.mean, 4),
                "de76_max": round(de76.max, 4),
                "de00_mean": round(de00.mean, 4),
                "de00_p95": round(de00.p95, 4),
                "de00_max": round(de00.max, 4),
                "bake_ms": round(bake_ms, 2),
                "payload_kb": round(payload_kb(samples), 1),
                "payload_bytes": int(samples.size * 4),
            }
        )
        print(
            f"        PSNR {rows[-1]['psnr_db']:7.2f} dB | MAE {rows[-1]['mae']:.3f}/255"
            f" | dE00 {rows[-1]['de00_mean']:.3f} (max {rows[-1]['de00_max']:.2f})"
            f" | bake {rows[-1]['bake_ms']:.1f} ms | b64 {rows[-1]['payload_kb']:.0f} KB",
            flush=True,
        )

    if results_dir is not None:
        _save_probe_card(card, results_dir)

    return {
        "preset": PRESET,
        "probe": f"{PROBE_GRID}^3 RGB lattice ({card.shape[0]}x{card.shape[1]})",
        "sampling": "trilinear (GPU-equivalent)",
        "rows": rows,
    }


def metrics_transform(rgb01: np.ndarray, params: Any) -> np.ndarray:
    from baker.color_transform import transform_rgb

    return transform_rgb(rgb01, params)


def _save_probe_card(card: np.ndarray, results_dir: Path) -> None:
    from PIL import Image

    target = results_dir / "assets" / "dim2_gamut_probe.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(card, mode="RGB").save(target, optimize=True)


__all__ = ["SIZES", "build_probe", "payload_kb", "run"]
