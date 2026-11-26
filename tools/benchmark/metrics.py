"""Colour-science and image-quality metrics, implemented with numpy only.

Everything here is deterministic and dependency-light on purpose: the benchmark
must run inside the project venv without pulling in OpenCV or scikit-image.

Reference formulas
------------------
* sRGB -> linear -> XYZ (IEC 61966-2-1, D65)
* XYZ -> CIELAB (CIE 1976 L*a*b*)
* CIEDE2000 (CIE 2000 colour-difference formula, kL = kC = kH = 1)
* PSNR / MAE on 8-bit encoded sRGB
* SSIM (Wang et al. 2004), uniform 8x8 window, luma channel
* Shannon entropy over the 256-bin luma histogram
* Hasler & Suesstrunk (2003) colourfulness
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# sRGB (linear) -> XYZ, D65.
_M_RGB_TO_XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ],
    dtype=np.float64,
)
_WHITE_D65 = np.array([0.95047, 1.00000, 1.08883], dtype=np.float64)
_EPSILON = 216.0 / 24389.0
_KAPPA = 24389.0 / 27.0
_LUMA_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)


def srgb_to_linear(encoded: np.ndarray) -> np.ndarray:
    """Decode encoded sRGB in [0, 1] to linear light."""
    c = np.asarray(encoded, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_xyz(linear_rgb: np.ndarray) -> np.ndarray:
    return np.asarray(linear_rgb, dtype=np.float64) @ _M_RGB_TO_XYZ.T


def _f(t: np.ndarray) -> np.ndarray:
    return np.where(t > _EPSILON, np.cbrt(t), (_KAPPA * t + 16.0) / 116.0)


def xyz_to_lab(xyz: np.ndarray) -> np.ndarray:
    scaled = np.asarray(xyz, dtype=np.float64) / _WHITE_D65
    fx, fy, fz = _f(scaled[..., 0]), _f(scaled[..., 1]), _f(scaled[..., 2])
    return np.stack(
        [116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)], axis=-1
    )


def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """Convert encoded sRGB in [0, 1] (..., 3) to CIELAB (D65)."""
    c = np.clip(np.asarray(rgb, dtype=np.float64), 0.0, 1.0)
    return xyz_to_lab(linear_to_xyz(srgb_to_linear(c)))


def srgb8_to_lab(rgb: np.ndarray) -> np.ndarray:
    return srgb_to_lab(np.asarray(rgb, dtype=np.float64) / 255.0)


def luma(rgb: np.ndarray) -> np.ndarray:
    """Encoded-domain luma proxy, identical to the engine's weighting."""
    return np.asarray(rgb, dtype=np.float64) @ _LUMA_WEIGHTS


def chroma(lab: np.ndarray) -> np.ndarray:
    """CIELAB chroma C*ab = sqrt(a*^2 + b*^2)."""
    arr = np.asarray(lab, dtype=np.float64)
    return np.hypot(arr[..., 1], arr[..., 2])


def delta_e76(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """CIE76 colour difference (Euclidean distance in CIELAB)."""
    diff = np.asarray(lab1, dtype=np.float64) - np.asarray(lab2, dtype=np.float64)
    return np.sqrt(np.sum(diff * diff, axis=-1))


def delta_e00(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """CIEDE2000 colour difference, vectorised over (..., 3) CIELAB arrays."""
    lab1 = np.asarray(lab1, dtype=np.float64)
    lab2 = np.asarray(lab2, dtype=np.float64)
    l1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    l2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]

    c1 = np.hypot(a1, b1)
    c2 = np.hypot(a2, b2)
    c_bar = 0.5 * (c1 + c2)
    c_bar7 = c_bar**7
    g = 0.5 * (1.0 - np.sqrt(c_bar7 / (c_bar7 + 25.0**7)))

    a1p = (1.0 + g) * a1
    a2p = (1.0 + g) * a2
    c1p = np.hypot(a1p, b1)
    c2p = np.hypot(a2p, b2)

    h1p = np.where(c1p > 0.0, np.degrees(np.arctan2(b1, a1p)) % 360.0, 0.0)
    h2p = np.where(c2p > 0.0, np.degrees(np.arctan2(b2, a2p)) % 360.0, 0.0)

    dlp = l2 - l1
    dcp = c2p - c1p
    zero_chroma = (c1p * c2p) == 0.0
    dh = h2p - h1p
    dh = np.where(dh > 180.0, dh - 360.0, np.where(dh < -180.0, dh + 360.0, dh))
    dhp = np.where(zero_chroma, 0.0, dh)
    dhp_big = 2.0 * np.sqrt(c1p * c2p) * np.sin(np.radians(dhp) / 2.0)

    l_bar_p = 0.5 * (l1 + l2)
    c_bar_p = 0.5 * (c1p + c2p)
    h_sum = h1p + h2p
    h_bar_p = np.where(
        zero_chroma,
        h_sum,
        np.where(
            np.abs(h1p - h2p) <= 180.0,
            0.5 * h_sum,
            np.where(h_sum < 360.0, 0.5 * (h_sum + 360.0), 0.5 * (h_sum - 360.0)),
        ),
    )

    t = (
        1.0
        - 0.17 * np.cos(np.radians(h_bar_p - 30.0))
        + 0.24 * np.cos(np.radians(2.0 * h_bar_p))
        + 0.32 * np.cos(np.radians(3.0 * h_bar_p + 6.0))
        - 0.20 * np.cos(np.radians(4.0 * h_bar_p - 63.0))
    )
    d_theta = 30.0 * np.exp(-(((h_bar_p - 275.0) / 25.0) ** 2))
    c_bar_p7 = c_bar_p**7
    r_c = 2.0 * np.sqrt(c_bar_p7 / (c_bar_p7 + 25.0**7))
    s_l = 1.0 + (0.015 * (l_bar_p - 50.0) ** 2) / np.sqrt(
        20.0 + (l_bar_p - 50.0) ** 2
    )
    s_c = 1.0 + 0.045 * c_bar_p
    s_h = 1.0 + 0.015 * c_bar_p * t
    r_t = -np.sin(np.radians(2.0 * d_theta)) * r_c

    term_l = dlp / s_l
    term_c = dcp / s_c
    term_h = dhp_big / s_h
    squared = term_l**2 + term_c**2 + term_h**2 + r_t * term_c * term_h
    return np.sqrt(np.maximum(squared, 0.0))


@dataclass(frozen=True)
class DeltaEStats:
    mean: float
    max: float
    p95: float


def delta_e_stats(lab1: np.ndarray, lab2: np.ndarray, *, ciede2000: bool) -> DeltaEStats:
    diff = delta_e00(lab1, lab2) if ciede2000 else delta_e76(lab1, lab2)
    flat = np.asarray(diff, dtype=np.float64).ravel()
    if flat.size == 0:
        return DeltaEStats(0.0, 0.0, 0.0)
    return DeltaEStats(
        mean=float(flat.mean()),
        max=float(flat.max()),
        p95=float(np.percentile(flat, 95.0)),
    )


def psnr_uint8(reference: np.ndarray, test: np.ndarray) -> float:
    """PSNR in dB for 8-bit images (identical inputs -> 100.0 sentinel)."""
    ref = np.asarray(reference, dtype=np.float64)
    cmp = np.asarray(test, dtype=np.float64)
    mse = float(np.mean((ref - cmp) ** 2))
    if mse <= 1e-12:
        return 100.0
    return float(10.0 * math.log10((255.0**2) / mse))


def psnr_unit(reference: np.ndarray, test: np.ndarray) -> float:
    """PSNR in dB for float images whose nominal peak is 1.0."""
    ref = np.asarray(reference, dtype=np.float64)
    cmp = np.asarray(test, dtype=np.float64)
    mse = float(np.mean((ref - cmp) ** 2))
    if mse <= 1e-15:
        return 100.0
    return float(10.0 * math.log10(1.0 / mse))


def mae_uint8(reference: np.ndarray, test: np.ndarray) -> float:
    ref = np.asarray(reference, dtype=np.float64)
    cmp = np.asarray(test, dtype=np.float64)
    return float(np.mean(np.abs(ref - cmp)))


def _box_mean(image: np.ndarray, window: int) -> np.ndarray:
    """Mean over a sliding window, 'valid' mode, via summed-area tables."""
    ii = np.pad(image, ((1, 0), (1, 0))).cumsum(axis=0).cumsum(axis=1)
    total = (
        ii[window:, window:]
        - ii[:-window, window:]
        - ii[window:, :-window]
        + ii[:-window, :-window]
    )
    return total / float(window * window)


def ssim(reference: np.ndarray, test: np.ndarray, window: int = 8) -> float:
    """Structural similarity on the luma channel, images in [0, 1] RGB."""
    x = np.clip(luma(np.asarray(reference, dtype=np.float64)), 0.0, 1.0)
    y = np.clip(luma(np.asarray(test, dtype=np.float64)), 0.0, 1.0)
    if x.ndim != 2:
        raise ValueError("ssim expects (H, W, 3) images")
    if min(x.shape) < window + 1:
        window = max(2, min(x.shape) - 1)

    mu_x = _box_mean(x, window)
    mu_y = _box_mean(y, window)
    mu_xx = mu_x * mu_x
    mu_yy = mu_y * mu_y
    mu_xy = mu_x * mu_y

    sigma_xx = _box_mean(x * x, window) - mu_xx
    sigma_yy = _box_mean(y * y, window) - mu_yy
    sigma_xy = _box_mean(x * y, window) - mu_xy

    c1 = 0.01**2
    c2 = 0.03**2
    numerator = (2.0 * mu_xy + c1) * (2.0 * sigma_xy + c2)
    denominator = (mu_xx + mu_yy + c1) * (sigma_xx + sigma_yy + c2)
    return float(np.mean(numerator / denominator))


def entropy_bits(rgb_uint8: np.ndarray) -> float:
    """Shannon entropy of the 256-bin luma histogram, in bits."""
    arr = np.asarray(rgb_uint8, dtype=np.float64) / 255.0
    luma_u8 = np.clip(np.rint(luma(arr) * 255.0), 0, 255).astype(np.uint8)
    counts = np.bincount(luma_u8.ravel(), minlength=256).astype(np.float64)
    total = counts.sum()
    if total <= 0.0:
        return 0.0
    p = counts[counts > 0.0] / total
    return float(-np.sum(p * np.log2(p)))


def mean_luma(rgb_uint8: np.ndarray) -> float:
    arr = np.asarray(rgb_uint8, dtype=np.float64) / 255.0
    return float(luma(arr).mean() * 255.0)


def contrast_std(rgb_uint8: np.ndarray) -> float:
    arr = np.asarray(rgb_uint8, dtype=np.float64) / 255.0
    return float(luma(arr).std(ddof=0) * 255.0)


def colorfulness(rgb_uint8: np.ndarray) -> float:
    """Hasler & Suesstrunk colourfulness metric (RGB in 0..255)."""
    arr = np.asarray(rgb_uint8, dtype=np.float64)
    red, green, blue = arr[..., 0], arr[..., 1], arr[..., 2]
    rg = red - green
    yb = 0.5 * (red + green) - blue
    std = math.sqrt(float(rg.var()) + float(yb.var()))
    mean = math.sqrt(float(rg.mean()) ** 2 + float(yb.mean()) ** 2)
    return float(std + 0.3 * mean)


def identity_psnr() -> float:
    return 100.0


__all__ = [
    "DeltaEStats",
    "chroma",
    "colorfulness",
    "contrast_std",
    "delta_e00",
    "delta_e76",
    "delta_e_stats",
    "entropy_bits",
    "identity_psnr",
    "linear_to_xyz",
    "luma",
    "mae_uint8",
    "mean_luma",
    "psnr_uint8",
    "psnr_unit",
    "srgb8_to_lab",
    "srgb_to_lab",
    "srgb_to_linear",
    "ssim",
    "xyz_to_lab",
]
