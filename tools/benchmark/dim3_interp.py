"""Dimension 3 - trilinear vs tetrahedral 3D LUT interpolation.

Two probes:

* **Grey ramp** (256 steps, r = g = b). The sample point lies exactly on the
  cube diagonal, where trilinear blending mixes eight corners from different
  tetrahedra. Any asymmetry between those corners is injected into a colour
  that should stay neutral, which is what chroma drift measures.
* **Colour sweep** (64^3 lattice, 512x512 card). Dense gamut coverage including
  clipped, high-chroma corners, scored against the float64 truth with PSNR and
  CIEDE2000.

Both filters run on the *same* baked LUT, so the only difference is the
reconstruction kernel.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from . import common, metrics
from .dim2_lut import build_probe
from .interpolation import tetrahedral_sample, trilinear_sample

SIZES = (17, 33)
PRIMARY_PRESET = "cinematic"
# A deliberately hostile look (hard S-curve, strong split-tone, heavy saturation)
# where the f(LUT) surface is far from linear inside a cell.
STRESS_PRESET = "tetra_stress"
STRESS_PARAMS = {
    "contrast": 100.0,
    "saturation": 55.0,
    "temperature": 45.0,
    "vibrance": 25.0,
    "highlights": -35.0,
    "shadows": 20.0,
    "split_shadow_hue": 195.0,
    "split_shadow_amount": 40.0,
    "split_highlight_hue": 40.0,
    "split_highlight_amount": 40.0,
}


def _grey_ramp() -> np.ndarray:
    ramp = np.linspace(0.0, 1.0, 256, dtype=np.float64)
    return np.stack([ramp, ramp, ramp], axis=1)


def _resolve_preset(name: str) -> Any:
    from baker.params import ColorParams, load_preset

    if name == STRESS_PRESET:
        return ColorParams.from_dict(STRESS_PARAMS)
    params, _ = load_preset(name)
    return params


def _evaluate(params: Any, size: int, grey: np.ndarray, probe01: np.ndarray) -> dict[str, Any]:
    from baker.color_transform import bake_lut, transform_rgb

    lut = bake_lut(params, size)
    grey_truth = transform_rgb(grey, params)
    sweep_truth = transform_rgb(probe01, params)
    sweep_truth_u8 = common.to_uint8(sweep_truth)
    sweep_truth_lab = metrics.srgb8_to_lab(sweep_truth_u8)
    grey_truth_lab = metrics.srgb8_to_lab(common.to_uint8(grey_truth))

    result: dict[str, Any] = {"size": size}
    for tag, sampler in (("trilinear", trilinear_sample), ("tetrahedral", tetrahedral_sample)):
        grey_out = np.clip(sampler(lut, size, grey), 0.0, 1.0)
        grey_u8 = common.to_uint8(grey_out)
        grey_lab = metrics.srgb8_to_lab(grey_u8)

        sweep_out = np.clip(sampler(lut, size, probe01), 0.0, 1.0)
        sweep_u8 = common.to_uint8(sweep_out)
        sweep_lab = metrics.srgb8_to_lab(sweep_u8)

        drift = metrics.chroma(grey_lab)
        truth_drift = metrics.chroma(grey_truth_lab)
        drift_err = np.abs(drift - truth_drift)
        de_grey = metrics.delta_e_stats(grey_truth_lab, grey_lab, ciede2000=True)
        de_sweep = metrics.delta_e_stats(sweep_truth_lab, sweep_lab, ciede2000=True)
        de_grey_curve = metrics.delta_e00(grey_truth_lab, grey_lab)
        result[tag] = {
            "grey_chroma_mean": round(float(drift.mean()), 4),
            "grey_chroma_max": round(float(drift.max()), 4),
            "grey_chroma_err_mean": round(float(drift_err.mean()), 4),
            "grey_chroma_err_max": round(float(drift_err.max()), 4),
            "grey_de00_mean": round(de_grey.mean, 4),
            "grey_de00_max": round(de_grey.max, 4),
            "sweep_psnr_db": round(metrics.psnr_uint8(sweep_truth_u8, sweep_u8), 3),
            "sweep_mae": round(metrics.mae_uint8(sweep_truth_u8, sweep_u8), 4),
            "sweep_de00_mean": round(de_sweep.mean, 4),
            "sweep_de00_max": round(de_sweep.max, 4),
            "curves": {
                "chroma": [round(float(v), 4) for v in drift.tolist()],
                "chroma_err": [round(float(v), 4) for v in drift_err.tolist()],
                "de00": [round(float(v), 4) for v in de_grey_curve.tolist()],
            },
        }

    tri = result["trilinear"]
    tet = result["tetrahedral"]
    result["delta"] = {
        "grey_chroma_reduction_pct": round(
            100.0 * (tri["grey_chroma_mean"] - tet["grey_chroma_mean"])
            / tri["grey_chroma_mean"]
            if tri["grey_chroma_mean"] > 1e-9
            else 0.0,
            2,
        ),
        "grey_de00_reduction_pct": round(
            100.0 * (tri["grey_de00_mean"] - tet["grey_de00_mean"])
            / tri["grey_de00_mean"]
            if tri["grey_de00_mean"] > 1e-9
            else 0.0,
            2,
        ),
        "sweep_psnr_gain_db": round(tet["sweep_psnr_db"] - tri["sweep_psnr_db"], 4),
        "sweep_de00_reduction_pct": round(
            100.0 * (tri["sweep_de00_mean"] - tet["sweep_de00_mean"])
            / tri["sweep_de00_mean"]
            if tri["sweep_de00_mean"] > 1e-9
            else 0.0,
            2,
        ),
    }
    return result


def run(results_dir: Path | None = None) -> dict[str, Any]:
    grey = _grey_ramp()
    probe01, _, _ = build_probe()

    cases: list[dict[str, Any]] = []
    for preset in (PRIMARY_PRESET, STRESS_PRESET):
        params = _resolve_preset(preset)
        for size in SIZES:
            print(f"  [dim3] {preset} @ {size}^3: trilinear vs tetrahedral ...", flush=True)
            row = _evaluate(params, size, grey, probe01)
            row["preset"] = preset
            cases.append(row)
            print(
                f"        grey chroma {row['trilinear']['grey_chroma_mean']:.3f}"
                f" -> {row['tetrahedral']['grey_chroma_mean']:.3f}"
                f" | sweep PSNR {row['trilinear']['sweep_psnr_db']:.2f}"
                f" -> {row['tetrahedral']['sweep_psnr_db']:.2f} dB"
                f" | dE00 {row['trilinear']['sweep_de00_mean']:.3f}"
                f" -> {row['tetrahedral']['sweep_de00_mean']:.3f}",
                flush=True,
            )

    if results_dir is not None:
        _save_ramp_sheet(grey, cases, results_dir)

    return {
        "sizes": list(SIZES),
        "primary_preset": PRIMARY_PRESET,
        "stress_preset": STRESS_PRESET,
        "stress_params": STRESS_PARAMS,
        "ramp_steps": int(grey.shape[0]),
        "sweep_probe": "64^3 RGB lattice",
        "cases": cases,
    }


def _save_ramp_sheet(grey: np.ndarray, cases: list[dict[str, Any]], results_dir: Path) -> None:
    """Store the evaluated grey ramps + sweep cards as a PNG contact sheet."""
    from PIL import Image

    from baker.color_transform import bake_lut

    tiles: list[np.ndarray] = []
    for row in cases:
        params = _resolve_preset(row["preset"])
        lut = bake_lut(params, row["size"])
        strip = []
        for sampler in (trilinear_sample, tetrahedral_sample):
            out = np.clip(sampler(lut, row["size"], grey), 0.0, 1.0)
            line = common.to_uint8(out)
            strip.append(np.repeat(line[None, :, :], 24, axis=0))
        tiles.append(np.concatenate(strip, axis=0))
    sheet = np.concatenate(tiles, axis=1)
    target = results_dir / "assets" / "dim3_grey_ramps.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(sheet, mode="RGB").save(target, optimize=True)


__all__ = ["PRIMARY_PRESET", "SIZES", "STRESS_PARAMS", "STRESS_PRESET", "run"]
