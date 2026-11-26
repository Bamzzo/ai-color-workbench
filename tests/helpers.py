"""Shared fixtures and helpers for the test suite."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageCms

from app import image_io, paths

FIXTURES = paths.RUNTIME / "test-fixtures"


def ensure_fixtures() -> dict[str, Path]:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}

    pattern = FIXTURES / "pattern.png"
    if not pattern.is_file():
        height, width = 48, 64
        yy, xx = np.indices((height, width))
        arr = np.empty((height, width, 4), dtype=np.uint8)
        arr[..., 0] = (xx * 255 // (width - 1)).astype(np.uint8)
        arr[..., 1] = (yy * 255 // (height - 1)).astype(np.uint8)
        arr[..., 2] = ((xx + yy) * 255 // (width + height - 2)).astype(np.uint8)
        arr[..., 3] = np.select(
            [xx < width // 4, xx < width // 2, xx < 3 * width // 4],
            [0, 64, 128],
            default=255,
        ).astype(np.uint8)
        arr[0, 0] = (255, 0, 0, 255)
        arr[0, -1] = (0, 255, 0, 255)
        arr[-1, 0] = (0, 0, 255, 255)
        arr[-1, -1] = (255, 255, 255, 255)
        Image.fromarray(arr, "RGBA").save(pattern)
    files["pattern"] = pattern

    opaquepath = FIXTURES / "opaque.png"
    if not opaquepath.is_file():
        height, width = 32, 40
        yy, xx = np.indices((height, width))
        arr = np.empty((height, width, 3), dtype=np.uint8)
        arr[..., 0] = (xx * 6).astype(np.uint8)
        arr[..., 1] = (yy * 7).astype(np.uint8)
        arr[..., 2] = 90
        Image.fromarray(arr, "RGB").save(opaquepath)
    files["opaque"] = opaquepath

    gray = FIXTURES / "gray.png"
    if not gray.is_file():
        Image.fromarray(np.arange(256, dtype=np.uint8).reshape(16, 16), "L").save(gray)
    files["gray"] = gray

    palette = FIXTURES / "palette.png"
    if not palette.is_file():
        image = Image.new("P", (16, 16))
        image.putpalette([255, 0, 0, 0, 255, 0, 0, 0, 255] + [0] * (256 * 3 - 9))
        image.paste(1, (0, 0, 8, 16))
        image.paste(2, (8, 0, 16, 16))
        image.save(palette, transparency=0)
    files["palette"] = palette

    icc_path = FIXTURES / "icc.png"
    if not icc_path.is_file():
        image = Image.fromarray(
            np.full((16, 16, 3), 128, dtype=np.uint8), "RGB"
        )
        image.save(icc_path, icc_profile=image_io.srgb_profile_bytes())
    files["icc"] = icc_path

    return files


def make_snapshot_image(width: int = 32, height: int = 24) -> Image.Image:
    yy, xx = np.indices((height, width))
    arr = np.empty((height, width, 4), dtype=np.uint8)
    arr[..., 0] = (xx * 7).astype(np.uint8)
    arr[..., 1] = (yy * 9).astype(np.uint8)
    arr[..., 2] = ((xx * 3 + yy * 5) % 256).astype(np.uint8)
    arr[..., 3] = 255
    return Image.fromarray(arr, "RGBA")


def write_params_document(path: Path, **overrides: float) -> Path:
    import json

    from baker.params import ColorParams

    params = ColorParams.identity()
    if overrides:
        params = params.with_updates(**overrides)
    path.write_text(
        json.dumps(params.to_document(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load_rgba_array(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGBA"), dtype=np.uint8)
