"""Deterministic benchmark image set.

The grading benchmark needs coverage of the failure modes that matter to a
colour-grading tool: crushed shadows, low-contrast haze, gamut-stressing
saturation, skin tones and clipped highlight ranges. ``runtime/test-fixtures``
only ships a handful of tiny images, so the set is topped up with synthetic
scenes generated from a fixed seed: the same bytes are produced on every run,
which keeps before/after benchmark diffs meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

MAX_LONG_SIDE = 768
_GRID_W, _GRID_H = 768, 512


@dataclass(frozen=True)
class BenchImage:
    key: str
    label: str
    path: Path
    origin: str  # "fixture" | "synthetic"


def _hsv(hue: np.ndarray, sat: np.ndarray, val: np.ndarray) -> np.ndarray:
    """Vectorised HSV -> RGB for hue in degrees, sat/val in [0, 1]."""
    h = (np.asarray(hue, dtype=np.float64) % 360.0) / 60.0
    s = np.clip(np.asarray(sat, dtype=np.float64), 0.0, 1.0)
    v = np.clip(np.asarray(val, dtype=np.float64), 0.0, 1.0)
    sector = np.floor(h).astype(np.int64) % 6
    f = h - np.floor(h)
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    r = np.select(
        [sector == 0, sector == 1, sector == 2, sector == 3, sector == 4],
        [v, q, p, p, t],
        default=v,
    )
    g = np.select(
        [sector == 0, sector == 1, sector == 2, sector == 3, sector == 4],
        [t, v, v, q, p],
        default=p,
    )
    b = np.select(
        [sector == 0, sector == 1, sector == 2, sector == 3, sector == 4],
        [p, p, t, v, v],
        default=q,
    )
    return np.stack([r, g, b], axis=-1)


def _save(rgb: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.clip(np.rint(np.asarray(rgb, dtype=np.float64) * 255.0), 0, 255).astype(
        np.uint8
    )
    Image.fromarray(arr, mode="RGB").save(path, optimize=True)


def _grid() -> tuple[np.ndarray, np.ndarray]:
    ys = np.linspace(0.0, 1.0, _GRID_H)[:, None]
    xs = np.linspace(0.0, 1.0, _GRID_W)[None, :]
    return np.broadcast_to(xs, (_GRID_H, _GRID_W)), np.broadcast_to(
        ys, (_GRID_H, _GRID_W)
    )


def _underexposed(rng: np.random.Generator) -> np.ndarray:
    """Dark interior: mean luma near 30/255 with one warm practical light."""
    xs, ys = _grid()
    base = 0.055 + 0.075 * (1.0 - ys)
    lamp = 0.42 * np.exp(-(((xs - 0.72) ** 2) / 0.035 + ((ys - 0.38) ** 2) / 0.05))
    window = 0.30 * ((xs > 0.06) & (xs < 0.26) & (ys > 0.12) & (ys < 0.55))
    luma_img = np.clip(base + lamp + window, 0.0, 1.0)
    tint = np.stack(
        [1.0 + 0.55 * lamp, 1.0 + 0.22 * lamp, 1.0 - 0.10 * lamp], axis=-1
    )
    rgb = luma_img[..., None] * tint
    rgb = rgb + rng.normal(0.0, 0.006, rgb.shape)
    return np.clip(rgb, 0.0, 1.0)


def _lowcontrast_haze(rng: np.random.Generator) -> np.ndarray:
    """Foggy morning: everything crammed into a narrow mid-tone band."""
    xs, ys = _grid()
    wave = (
        0.030 * np.sin(xs * 7.5)
        + 0.022 * np.cos(ys * 5.0 + xs * 3.0)
        + 0.018 * np.sin((xs + ys) * 9.0)
    )
    luma_img = 0.56 + wave
    rgb = np.stack(
        [luma_img * 0.99, luma_img * 1.0, luma_img * 1.04], axis=-1
    )
    silhouette = (ys > 0.66) & (np.abs(xs - 0.34) < 0.10)
    rgb[silhouette] *= 0.90
    rgb = rgb + rng.normal(0.0, 0.004, rgb.shape)
    return np.clip(rgb, 0.0, 1.0)


def _saturated_landscape(rng: np.random.Generator) -> np.ndarray:
    """High-chroma outdoor card: deeply saturated sky, field and water."""
    xs, ys = _grid()
    hue = np.where(ys < 0.42, 205.0 + 20.0 * ys, np.where(ys < 0.66, 135.0, 190.0))
    sat = np.where(ys < 0.42, 0.72, np.where(ys < 0.66, 0.88, 0.80))
    val = np.where(ys < 0.42, 0.92 - 0.18 * ys, np.where(ys < 0.66, 0.72, 0.55))
    ridge = 0.40 + 0.06 * np.sin(xs * 9.0) + 0.03 * np.sin(xs * 23.0)
    hue = np.where((ys > ridge) & (ys < 0.66), 110.0 + 30.0 * xs, hue)
    rgb = _hsv(hue, sat, val)
    blossom = ((xs - 0.18) ** 2 + (ys - 0.78) ** 2) < 0.006
    rgb = np.where(blossom[..., None], np.array([0.90, 0.18, 0.42]), rgb)
    rgb = rgb + rng.normal(0.0, 0.004, rgb.shape)
    return np.clip(rgb, 0.0, 1.0)


def _skin_tone_study(rng: np.random.Generator) -> np.ndarray:
    """Portrait proxy: skin-tone gradient plus a neutral reference patch."""
    xs, ys = _grid()
    radial = np.sqrt(((xs - 0.50) * 1.6) ** 2 + ((ys - 0.46) * 1.15) ** 2)
    light = np.clip(1.05 - 1.25 * radial, 0.10, 1.0)
    lit = 0.30 + 0.70 * light
    low = np.array([0.46, 0.28, 0.21])
    high = np.array([0.97, 0.80, 0.69])
    rgb = low + (high - low) * lit[..., None]
    cheek = np.exp(-(((xs - 0.36) ** 2) / 0.004 + ((ys - 0.56) ** 2) / 0.006))
    rgb[..., 0] = np.clip(rgb[..., 0] + 0.07 * cheek, 0.0, 1.0)
    background = (xs > 0.80) | (xs < 0.06)
    rgb = np.where(background[..., None], 0.22 + 0.10 * (1.0 - ys)[..., None], rgb)
    patch = (xs > 0.83) & (xs < 0.93) & (ys > 0.10) & (ys < 0.30)
    rgb = np.where(patch[..., None], 0.18, rgb)
    rgb = rgb + rng.normal(0.0, 0.005, rgb.shape)
    return np.clip(rgb, 0.0, 1.0)


def _hdr_architecture(rng: np.random.Generator) -> np.ndarray:
    """Backlit facade: deep interior plus a blown-out sky (6+ stops)."""
    xs, ys = _grid()
    sky = np.clip(0.95 - 0.25 * ys, 0.0, 1.0)
    rgb = np.stack([sky * 1.02, sky * 0.98, sky * 0.94], axis=-1)
    sun = ((xs - 0.78) ** 2 + (ys - 0.14) ** 2) < 0.0035
    rgb = np.where(sun[..., None], 1.0, rgb)
    body = (ys > 0.30) & (xs > 0.05) & (xs < 0.95)
    facade = 0.045 + 0.10 * (1.0 - np.abs(xs - 0.5) * 2.0)
    rgb = np.where(body[..., None], facade[..., None], rgb)
    columns = body & (((xs * 14.0) % 2.0) < 0.42)
    rgb = np.where(columns[..., None], 0.015, rgb)
    window = (ys > 0.46) & (ys < 0.72) & (xs > 0.18) & (xs < 0.62)
    glow = 0.28 + 0.42 * np.abs(np.sin(xs * 31.0))
    rgb = np.where(window[..., None], glow[..., None], rgb)
    rgb = rgb + rng.normal(0.0, 0.004, rgb.shape)
    return np.clip(rgb, 0.0, 1.0)


_SYNTHETIC = (
    ("underexposed", "欠曝暗调", _underexposed),
    ("lowcontrast", "低对比灰雾", _lowcontrast_haze),
    ("saturated", "高饱和风景", _saturated_landscape),
    ("skintone", "肤色渐变", _skin_tone_study),
    ("hdr", "高动态范围建筑", _hdr_architecture),
)

_FIXTURE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
_SKIP_FIXTURE_HINTS = ("icc", "palette", "opaque", "tmp", "gray", "pattern")


def _prepare_fixture(path: Path, out_dir: Path) -> BenchImage | None:
    try:
        with Image.open(path) as opened:
            image = opened.convert("RGB")
    except Exception:
        return None
    longest = max(image.size)
    if longest > MAX_LONG_SIDE:
        scale = MAX_LONG_SIDE / float(longest)
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.LANCZOS,
        )
    target = out_dir / f"fixture_{path.stem.lower()}.png"
    image.save(target, optimize=True)
    return BenchImage(path.stem.lower(), f"夹具图 {path.name}", target, "fixture")


def build_dataset(
    fixtures_dir: Path, out_dir: Path, minimum: int = 5
) -> list[BenchImage]:
    """Return at least ``minimum`` benchmark images, generating what is missing.

    Real fixtures are preferred; the synthetic scenes are appended until the
    set reaches ``minimum`` plus whatever fixtures were usable. Images are
    always re-serialised into ``out_dir`` so a later run sees identical bytes.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20261118)
    images: list[BenchImage] = []

    if fixtures_dir.is_dir():
        for path in sorted(fixtures_dir.iterdir()):
            if path.suffix.lower() not in _FIXTURE_SUFFIXES:
                continue
            if any(hint in path.stem.lower() for hint in _SKIP_FIXTURE_HINTS):
                continue
            prepared = _prepare_fixture(path, out_dir)
            if prepared is not None and prepared.path.stat().st_size > 2048:
                images.append(prepared)

    synthetic = [
        (key, label, maker)
        for key, label, maker in _SYNTHETIC
    ]
    for key, label, maker in synthetic:
        target = out_dir / f"synth_{key}.png"
        _save(maker(rng), target)
        images.append(BenchImage(key, label, target, "synthetic"))

    return images


__all__ = ["BenchImage", "build_dataset", "MAX_LONG_SIDE"]
