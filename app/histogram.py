"""256-bin RGB and luminance histograms for the preview canvas.

The histogram is a monitor of the *output* image, so it is computed from the
rendered preview buffer (the same pixels the user sees), not from the source
file. Everything here is pure numpy + Pillow and runs on the Tk main thread in
a few milliseconds for a 1280 px preview.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw

BINS = 256
_LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
_MAX_SAMPLES = 1_200_000

_BG = (23, 24, 28)
_GRID = (42, 44, 50)
_FRAME = (60, 63, 70)
_RGB_COLORS = ((255, 92, 92), (92, 230, 128), (98, 152, 255))
_LUMA_COLOR = (232, 234, 237)
_ORIGINAL_COLOR = (154, 160, 166)
_CLIP_SHADOW = (86, 182, 255)
_CLIP_HIGHLIGHT = (255, 176, 64)
_CLIP_THRESHOLD = 0.001


@dataclass(frozen=True)
class Histogram:
    rgb: np.ndarray  # (3, 256), shared-normalised 0..1
    luma: np.ndarray  # (256,), shared-normalised 0..1
    clip_low: float  # fraction of pixels at or below 2/255
    clip_high: float  # fraction of pixels at or above 253/255

    @property
    def empty(self) -> bool:
        return float(self.luma.max()) <= 0.0


def _sample_rgb(image: Image.Image) -> np.ndarray:
    if image.mode == "RGBA":
        # Preview buffers keep alpha; composite on white so transparent pixels
        # do not masquerade as black bins (matches JPEG export behaviour).
        canvas = Image.new("RGBA", image.size, (255, 255, 255, 255))
        image = Image.alpha_composite(canvas, image)
    if image.mode != "RGB":
        image = image.convert("RGB")
    array = np.asarray(image, dtype=np.uint8)
    flat = array.reshape(-1, 3)
    if flat.shape[0] > _MAX_SAMPLES:
        step = int(np.ceil(flat.shape[0] / _MAX_SAMPLES))
        flat = flat[::step]
    return flat


def compute_histogram(image: Image.Image) -> Histogram:
    """Compute RGB + luminance histograms from a preview image."""
    flat = _sample_rgb(image)
    if flat.size == 0:
        zeros = np.zeros(BINS, dtype=np.float32)
        return Histogram(np.stack([zeros, zeros, zeros]), zeros, 0.0, 0.0)

    values = flat.astype(np.float32) / 255.0
    luma = values @ _LUMA
    luma_u8 = np.clip(np.rint(luma * 255.0), 0, 255).astype(np.uint8)
    luma_hist = np.bincount(luma_u8, minlength=BINS).astype(np.float32)

    channels = []
    for index in range(3):
        hist = np.bincount(flat[:, index], minlength=BINS).astype(np.float32)
        channels.append(hist)
    rgb = np.stack(channels)

    peak = float(max(rgb.max(), luma_hist.max()))
    if peak <= 0.0:
        peak = 1.0
    total = float(flat.shape[0])
    return Histogram(
        rgb=rgb / peak,
        luma=luma_hist / peak,
        clip_low=float(np.count_nonzero(luma_u8 <= 2) / total),
        clip_high=float(np.count_nonzero(luma_u8 >= 253) / total),
    )


def _curve_points(values: np.ndarray, width: int, height: int) -> list[tuple[int, int]]:
    xs = np.linspace(0, width - 1, BINS)
    ys = (height - 1) - np.clip(values, 0.0, 1.0) * (height - 1)
    return [(int(round(x)), int(round(y))) for x, y in zip(xs, ys)]


def _draw_fill(
    draw: ImageDraw.ImageDraw,
    values: np.ndarray,
    width: int,
    height: int,
    color: tuple[int, int, int],
    alpha: int,
) -> None:
    points = _curve_points(values, width, height)
    polygon = [(0, height)] + points + [(width - 1, height)]
    draw.polygon(polygon, fill=(*color, alpha))


def _draw_dashed(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[int, int]],
    color: tuple[int, int, int, int],
    width: int = 2,
    dash: int = 6,
    gap: int = 5,
) -> None:
    """Dash by column parity; histogram curves are single-valued in x."""
    period = max(2, dash + gap)
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if (x0 % period) < dash:
            draw.line([(x0, y0), (x1, y1)], fill=color, width=width)


def render_histogram(
    current: Histogram | None,
    original: Histogram | None,
    width: int,
    height: int,
    *,
    supersample: int = 2,
) -> Image.Image:
    """Render the histogram strip: RGB fills + luma curve, original dashed."""
    width = max(64, int(width))
    height = max(40, int(height))
    scale = max(1, int(supersample))
    w, h = width * scale, height * scale

    canvas = Image.new("RGB", (w, h), _BG)
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for fraction in (0.25, 0.5, 0.75):
        x = int(round((w - 1) * fraction))
        draw.line([(x, 0), (x, h - 1)], fill=(*_GRID, 255), width=max(1, scale))

    if original is not None and not original.empty:
        _draw_dashed(
            draw,
            _curve_points(original.luma, w, h),
            (*_ORIGINAL_COLOR, 150),
            width=max(1, scale),
            dash=5 * scale,
            gap=4 * scale,
        )

    if current is not None and not current.empty:
        for channel in range(3):
            _draw_fill(
                draw, current.rgb[channel], w, h, _RGB_COLORS[channel], 62
            )
        for channel in range(3):
            draw.line(
                _curve_points(current.rgb[channel], w, h),
                fill=(*_RGB_COLORS[channel], 210),
                width=max(1, scale),
            )
        draw.line(
            _curve_points(current.luma, w, h),
            fill=(*_LUMA_COLOR, 235),
            width=max(1, scale + 1),
        )

        # Clip indicators replace a text legend: a slim edge marker is enough
        # to say "the shadows/highlights are being crushed".
        bar = max(2, 3 * scale)
        if current.clip_low >= _CLIP_THRESHOLD:
            draw.rectangle(
                [0, 0, bar - 1, h - 1], fill=(*_CLIP_SHADOW, 210)
            )
        if current.clip_high >= _CLIP_THRESHOLD:
            draw.rectangle(
                [w - bar, 0, w - 1, h - 1], fill=(*_CLIP_HIGHLIGHT, 210)
            )

    draw.rectangle([0, 0, w - 1, h - 1], outline=(*_FRAME, 255), width=1)
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    if scale > 1:
        canvas = canvas.resize((width, height), Image.LANCZOS)
    return canvas


__all__ = ["BINS", "Histogram", "compute_histogram", "render_histogram"]
