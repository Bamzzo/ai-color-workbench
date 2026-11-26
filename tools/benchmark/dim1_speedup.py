"""Dimension 1 - CPU per-pixel maths vs the C++ OpenGL 3.3 Core render worker.

Two different costs are compared:

* ``cpu`` - ``baker.color_transform.transform_rgb`` on a float64 image. This is
  the reference implementation: the whole 16-parameter pipeline, evaluated per
  pixel, per channel, in Python/numpy.
* ``gpu_total`` - one full ``EngineClient.render`` call. The worker is a fresh
  process each time, so this includes process start-up, GL context creation,
  RGBA bridge I/O and the frame readback.
* ``gpu_shader`` - the worker-reported ``metrics.render_readback_ms``, i.e. only
  texture upload + fragment shading + ``glReadPixels``. Dividing the CPU time by
  this isolates the acceleration of the rasterisation stage itself from the
  one-shot process overhead.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from . import common

LUT_SIZE = 33
PRESET = "cinematic"
TRIALS = 5
WARMUP = 1


@dataclass(frozen=True)
class Resolution:
    key: str
    label: str
    width: int
    height: int

    @property
    def megapixels(self) -> float:
        return self.width * self.height / 1e6


RESOLUTIONS = (
    Resolution("1080p", "1080p (1920x1080)", 1920, 1080),
    Resolution("2k", "2K (2560x1440)", 2560, 1440),
    Resolution("4k", "4K (3840x2160)", 3840, 2160),
)


def make_test_image(width: int, height: int) -> np.ndarray:
    """Deterministic full-range sRGB card used for both pipelines."""
    xs = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :]
    ys = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    ramp = 0.12 + 0.82 * xs
    red = ramp
    green = ramp * (0.55 + 0.45 * ys)
    blue = (0.12 + 0.82 * (1.0 - xs)) * (0.40 + 0.60 * ys)
    accent = ((xs * 18.0) % 1.0 < 0.25) & ((ys * 11.0) % 1.0 < 0.5)
    red = np.where(accent, np.clip(red * 1.10 + 0.05, 0.0, 1.0), red)
    stack = np.stack(
        [
            np.broadcast_to(red, (height, width)),
            np.broadcast_to(green, (height, width)),
            np.broadcast_to(blue, (height, width)),
        ],
        axis=-1,
    )
    return np.clip(np.rint(stack * 255.0), 0, 255).astype(np.uint8)


def _run_cpu(params: Any, image: np.ndarray) -> common.Timing:
    from baker.color_transform import transform_rgb

    # The conversion to working precision is app-level I/O, not colour maths, so
    # it stays outside the timed region.
    float_image = common.to_float01(image)

    def once() -> None:
        transform_rgb(float_image, params)

    return common.time_call(once, warmup=WARMUP, trials=TRIALS)


def _run_gpu(params: Any, image: np.ndarray, work: Path) -> tuple[common.Timing, float]:
    from app import image_io
    from app.engine_client import EngineClient

    work.mkdir(parents=True, exist_ok=True)
    height, width = image.shape[:2]
    bridge = work / f"input_{width}x{height}.rgba"
    image_io.write_rgba_bridge(bridge, Image.fromarray(image, mode="RGB").convert("RGBA"))
    cube = common.ensure_cube(params, LUT_SIZE, f"dim1_{PRESET}")
    client = EngineClient(timeout=180.0)

    readbacks: list[float] = []

    def once() -> None:
        outcome = client.render(
            bridge, cube, 1.0, document_id="benchmark-dim1", revision=1
        )
        value = outcome.metrics.get("render_readback_ms")
        if isinstance(value, (int, float)):
            readbacks.append(float(value))

    timing = common.time_call(once, warmup=WARMUP, trials=TRIALS)
    shader_ms = float(np.median(readbacks)) if readbacks else float("nan")
    return timing, shader_ms


def run(results_dir: Path) -> dict[str, Any]:
    from baker.params import load_preset

    params, _ = load_preset(PRESET)
    work = results_dir / ".work" / "dim1"
    rows: list[dict[str, Any]] = []
    try:
        for resolution in RESOLUTIONS:
            print(
                f"  [dim1] {resolution.label}: CPU per-pixel vs OpenGL worker ...",
                flush=True,
            )
            image = make_test_image(resolution.width, resolution.height)
            cpu = _run_cpu(params, image)
            gpu_total, gpu_shader = _run_gpu(params, image, work)
            del image
            rows.append(
                {
                    "resolution": resolution.key,
                    "label": resolution.label,
                    "width": resolution.width,
                    "height": resolution.height,
                    "megapixels": round(resolution.megapixels, 3),
                    "cpu": cpu.as_dict(),
                    "gpu_total": gpu_total.as_dict(),
                    "gpu_shader_ms": round(gpu_shader, 4),
                    "gpu_overhead_ms": round(gpu_total.mean_ms - gpu_shader, 4),
                    "speedup_total": round(cpu.mean_ms / gpu_total.mean_ms, 3),
                    "speedup_shader": round(cpu.mean_ms / gpu_shader, 3),
                }
            )
            print(
                f"        CPU {cpu.mean_ms:9.1f} ms | GPU total {gpu_total.mean_ms:8.1f} ms"
                f" | shader {gpu_shader:6.1f} ms | speedup {rows[-1]['speedup_total']:.2f}x"
                f" (shader-only {rows[-1]['speedup_shader']:.1f}x)",
                flush=True,
            )
    finally:
        shutil.rmtree(work, ignore_errors=True)

    return {
        "preset": PRESET,
        "lut_size": LUT_SIZE,
        "trials": TRIALS,
        "warmup": WARMUP,
        "rows": rows,
        "cpu_reference": "baker.color_transform.transform_rgb (float64, 16 params)",
        "gpu_reference": "EngineClient.render -> render_worker.exe (OpenGL 3.3 Core FBO)",
    }


__all__ = ["RESOLUTIONS", "Resolution", "make_test_image", "run"]
