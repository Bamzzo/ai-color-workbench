"""Atomic .cube writer with readback verification."""

from __future__ import annotations

import math
import os
from pathlib import Path

import numpy as np

from .color_transform import apply_effect_to_rgb, bake_lut, lut_grid
from .cube_reader import CubeError, CubeLut, load_cube
from .params import ColorParams


class CubeWriteError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _format_sample(value: float) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise CubeWriteError("LUT_PARSE_ERROR", "拒绝写入 NaN/Infinity")
    # 9 significant digits are enough for float32 round-trip.
    return format(float(np.float32(number)), ".9g")


def write_cube(
    path: str | Path,
    size: int,
    samples: np.ndarray,
    *,
    title: str = "ai_color_app",
    domain_min: tuple[float, float, float] = (0.0, 0.0, 0.0),
    domain_max: tuple[float, float, float] = (1.0, 1.0, 1.0),
    verify: bool = True,
) -> CubeLut:
    if not 2 <= int(size) <= 65:
        raise CubeWriteError("LUT_UNSUPPORTED", "LUT 尺寸必须在 [2, 65]")
    array = np.asarray(samples, dtype=np.float32)
    expected = int(size) ** 3
    if array.shape != (expected, 3):
        raise CubeWriteError(
            "LUT_PARSE_ERROR",
            f"样本形状 {array.shape} 与 {size}³ 不匹配",
        )
    if not np.all(np.isfinite(array)):
        raise CubeWriteError("LUT_PARSE_ERROR", "拒绝写入非有限样本")
    if np.max(np.abs(array)) > 65504.0:
        raise CubeWriteError("LUT_UNSUPPORTED", "样本超出安全上限 65504")
    for low, high in zip(domain_min, domain_max):
        if not (math.isfinite(low) and math.isfinite(high) and high > low):
            raise CubeWriteError("LUT_PARSE_ERROR", "无效 domain")

    clean_title = "".join(ch for ch in title if ch >= " ")[:256].replace('"', "'")
    lines = [
        f'TITLE "{clean_title}"',
        f"LUT_3D_SIZE {int(size)}",
        "DOMAIN_MIN "
        + " ".join(format(float(v), ".9g") for v in domain_min),
        "DOMAIN_MAX "
        + " ".join(format(float(v), ".9g") for v in domain_max),
    ]
    lines.extend(
        " ".join(_format_sample(v) for v in row) for row in array.tolist()
    )
    payload = "\n".join(lines) + "\n"

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise CubeWriteError("EXPORT_IO", f"写入 LUT 失败: {exc}") from exc

    if not verify:
        loaded = load_cube(target)
        return loaded

    loaded = load_cube(target)
    if loaded.size != int(size):
        raise CubeWriteError("LUT_PARSE_ERROR", "LUT 回读尺寸不一致")
    max_diff = float(np.max(np.abs(loaded.samples.astype(np.float64) - array)))
    if max_diff > 1e-6:
        raise CubeWriteError(
            "LUT_PARSE_ERROR", f"LUT 回读不一致，max diff={max_diff:g}"
        )
    return loaded


def export_params_lut(
    params: ColorParams,
    strength: float,
    path: str | Path,
    size: int = 33,
    title: str = "ai_color_app params",
) -> CubeLut:
    """Export a parameter LUT that already includes the strength slider."""
    base = bake_lut(params, size)
    if strength != 1.0:
        _, grid = lut_grid(size)
        base = np.clip(
            (1.0 - float(strength)) * grid
            + float(strength) * base.astype(np.float64),
            0.0,
            1.0,
        ).astype(np.float32)
    return write_cube(path, size, base, title=title)


def _verification_points() -> np.ndarray:
    # Composite colour card plus deterministic pseudo-random samples.
    card = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 1.0, 1.0],
            [0.5, 0.5, 0.5],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
            [1.0, 1.0, 0.0],
            [0.0, 1.0, 1.0],
            [1.0, 0.0, 1.0],
            [0.8, 0.55, 0.4],
            [0.35, 0.5, 0.75],
            [0.15, 0.15, 0.15],
            [0.9, 0.9, 0.9],
        ],
        dtype=np.float64,
    )
    rng = np.random.default_rng(20261020)
    random_points = rng.random((4096, 3))
    return np.vstack([card, random_points])


def verify_exported_effect(
    exported: CubeLut,
    *,
    params: ColorParams | None = None,
    source_samples: np.ndarray | None = None,
    source_size: int | None = None,
    source_domain_min: tuple[float, float, float] = (0.0, 0.0, 0.0),
    source_domain_max: tuple[float, float, float] = (1.0, 1.0, 1.0),
    strength: float = 1.0,
) -> float:
    """Return the max 8-bit-equivalent difference for the exported LUT.

    Either `params` (parameters mode) or external source LUT data must be
    provided. The reference is evaluated directly, not through a LUT.
    """
    points = _verification_points()
    if params is not None:
        from .color_transform import transform_rgb

        base = transform_rgb(points, params)
        reference = np.clip(
            (1.0 - float(strength)) * points + float(strength) * base, 0.0, 1.0
        )
    elif source_samples is not None and source_size is not None:
        from .color_transform import apply_effect_to_rgb

        reference = apply_effect_to_rgb(
            points,
            source_samples,
            source_size,
            strength,
            source_domain_min,
            source_domain_max,
        )
    else:
        raise CubeWriteError("LUT_PARSE_ERROR", "缺少效果参考数据")

    from .color_transform import sample_lut

    actual = sample_lut(
        exported.samples,
        exported.size,
        points,
        exported.domain_min,
        exported.domain_max,
    )
    return float(np.max(np.abs(actual - reference)) * 255.0)
