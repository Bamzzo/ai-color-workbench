"""Deterministic sdr-srgb-v2 colour math.

This is the single implementation of the parameter maths. The C++ worker only
applies a LUT and never re-interprets parameters (ADR-003).

All transforms operate on encoded sRGB values in [0, 1] unless a step
explicitly decodes to linear light.
"""

# ============================================================================
# 【文件总体作用】
#   调色参数的数学真值。滑块不直接进 GPU，而是先在这里烘焙成 3D LUT，
#   C++ / WebGL 只负责查表。因此改公式只改这一个文件，预览和导出才不会分叉。
#
# 【输入与输出】
#   输入：编码域 sRGB，形状 (..., 3)，数值在 [0, 1]；以及 ColorParams。
#   输出：同样形状的编码域 sRGB，或 N³×3 的 float32 LUT 采样（R 最快、B 最慢）。
#
# 【核心算法要点】
#   sRGB 与线性光互转、曝光与白平衡的 2 的幂增益、绕 0.5 的对比度幂曲线、
#   高光/阴影/黑白点的二次方权重、保持亮度的色相旋转、饱和度与自然饱和度、分离色调。
# ============================================================================

from __future__ import annotations

import math

import numpy as np

from .params import ALGORITHM_VERSION, ColorParams, PARAM_KEYS

_LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)
# BT.709 编码域亮度权重：绿 0.7152 约占七成，红 0.2126，蓝 0.0722。
# 人眼对绿色最敏感，所以“看起来有多亮”不能把三个通道平均。
# 这里用在编码域 sRGB 上，是调色用的亮度代理，不是线性光的物理亮度。


def _luma(c: np.ndarray) -> np.ndarray:
    """Encoded-domain tone proxy, not linear luminance."""
    return (
        0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]
    )


def hue_to_rgb(hue_degrees: float) -> np.ndarray:
    """Fully saturated hue at value 1, as an encoded-sRGB triple."""
    # 把色相角折进 6 个 60° 扇区。每个扇区里有一个通道为 1、一个为 0，剩下的一个在 0 和 1 之间线性过渡。
    # 这就是 HSV 中 S=1、V=1 的色相环，用来给分离色调提供“纯色染料”。
    h = (float(hue_degrees) % 360.0) / 60.0
    x = 1.0 - abs(h % 2.0 - 1.0)  # 扇区内的斜坡：0→1→0，周期为两个扇区
    sector = int(h) % 6
    table = (
        (1.0, x, 0.0),
        (x, 1.0, 0.0),
        (0.0, 1.0, x),
        (0.0, x, 1.0),
        (x, 0.0, 1.0),
        (1.0, 0.0, x),
    )
    return np.array(table[sector], dtype=np.float64)


def _hue_matrix(degrees: float) -> np.ndarray:
    """Rotation matrix that preserves the encoded-domain luma weights."""
    # 在垂直于亮度轴 (0.213, 0.715, 0.072) 的平面里旋转颜色。
    # 0.213/0.715/0.072 是 BT.709 权重的三位小数近似。
    # 绕亮度轴转，意味着 0.213*R + 0.715*G + 0.072*B 在旋转前后不变，色相变了、明暗感留住。
    # 每一项都是「亮度权重 + cos·(通道自身分量) + sin·(与亮度轴叉乘出来的分量)」。
    angle = math.radians(float(degrees))
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    return np.array(
        [
            [
                # 第 1 行作用在 R 上。0.787 = 1 - 0.213，是红通道里“不属于亮度”的那一份。
                0.213 + cos_a * 0.787 - sin_a * 0.213,
                0.715 - cos_a * 0.715 - sin_a * 0.715,
                0.072 - cos_a * 0.072 + sin_a * 0.928,
            ],
            [
                # 第 2 行作用在 G 上。0.285 = 1 - 0.715。sin 的 0.143 / 0.140 / 0.283 来自亮度轴的叉乘分量。
                0.213 - cos_a * 0.213 + sin_a * 0.143,
                0.715 + cos_a * 0.285 + sin_a * 0.140,
                0.072 - cos_a * 0.072 - sin_a * 0.283,
            ],
            [
                # 第 3 行作用在 B 上。0.928 = 1 - 0.072。角度为 0 时 cos=1、sin=0，矩阵退回单位阵。
                0.213 - cos_a * 0.213 - sin_a * 0.787,
                0.715 - cos_a * 0.715 + sin_a * 0.715,
                0.072 + cos_a * 0.928 + sin_a * 0.072,
            ],
        ],
        dtype=np.float64,
    )


def srgb_decode(encoded: np.ndarray) -> np.ndarray:
    """sRGB electro-optical transfer function (W3C CSS Color 4)."""
    # 编码值 → 线性光。暗部（≤0.04045）是直线 c/12.92，避免纯黑附近的斜率无穷大；
    # 其余用 ((c+0.055)/1.055)^2.4，2.4 是 sRGB 的近似伽马，0.055/1.055 用来和直线段平滑相接。
    c = np.asarray(encoded, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def srgb_encode(linear: np.ndarray) -> np.ndarray:
    """Inverse sRGB transfer function (W3C CSS Color 4)."""
    # 线性光 → 编码值，是上面那个曲线的反函数。
    # 分界点 0.0031308 是 0.04045/12.92。亮部用 1.055 * L^(1/2.4) - 0.055。
    c = np.asarray(linear, dtype=np.float64)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * (c ** (1.0 / 2.4)) - 0.055)


def _clip01(value: np.ndarray) -> np.ndarray:
    return np.clip(value, 0.0, 1.0)


def transform_rgb(rgb: np.ndarray, params: ColorParams) -> np.ndarray:
    """Apply the sdr-srgb-v2 pipeline to encoded-sRGB values.

    Input and output shape is (..., 3), values in [0, 1]. The operation is
    per-pixel and per-channel; no spatial information is used, so it can be
    baked into a 3D LUT exactly as documented in ADR-003.
    """
    c = np.asarray(rgb, dtype=np.float64)
    if c.shape[-1] != 3:
        raise ValueError("rgb must have a trailing dimension of 3")

    # 1-2. 先解到线性光，再乘曝光。+1 EV 表示光量翻倍，所以系数是 2^exposure，而不是直接加一个常数。
    linear = srgb_decode(c) * (2.0 ** params.exposure_ev)

    # 3. 色温 / 色调用每通道增益近似，不是完整的色适应矩阵。
    # t>0 偏暖：红增益上升、蓝增益下降。m>0 偏品红：红和蓝一起略升、绿下降。
    # 增益写成 2 的幂，和曝光用同一套“档”的手感：系数 0.25 表示拉满 ±100 时大约 ±0.25 档。
    t = params.temperature / 100.0
    m = params.tint / 100.0
    gain = np.array(
        [
            2.0 ** (0.25 * t + 0.10 * m),   # R：暖色加红，品红也略加红
            2.0 ** (-0.20 * m),             # G：品红（m>0）压绿，青绿（m<0）抬绿
            2.0 ** (-0.25 * t + 0.10 * m),  # B：暖色压蓝，冷色抬蓝
        ],
        dtype=np.float64,
    )
    linear = linear * gain

    # 4. Clip in linear light, re-encode.
    c = srgb_encode(_clip01(linear))

    # 5. 对比度绕中灰 0.5 做幂曲线，0 和 1 保持不动。
    #
    # 规范字面若写成 p = 2**(contrast/100)，正对比度会把 |2c-1|<1 的中间调往 0.5 挤，
    # 和“正值增加对比”的约定相反。这里用倒数指数 p = 2**(-contrast/100)：
    # contrast>0 时 p<1，|signed|^p 比 |signed| 更大，中间调被推离 0.5。
    # 见 docs/decisions/ADR-006-contrast-direction.md。
    p = 2.0 ** (-params.contrast / 100.0)
    signed = 2.0 * c - 1.0                                      # [0,1] → [-1,1]，枢轴在 0
    c = 0.5 + 0.5 * np.sign(signed) * np.abs(signed) ** p       # 再映回 [0,1]。|±1|^p 仍是 1，所以黑白点不动

    # 6. 阴影 / 高光。y 是编码域亮度代理，不是线性亮度。
    y = _luma(c)
    w_s = (1.0 - y) ** 2   # 二次方权重：暗部接近 1，亮部接近 0，中间衰减比线性更快，避免动到高光
    w_h = y**2             # 对称的高光权重：只在亮部显著
    # 0.20 是满幅 ±100 时的最大抬升/压暗量，三通道一起加，色相大体不动
    delta = 0.20 * (
        (params.shadows / 100.0) * w_s + (params.highlights / 100.0) * w_h
    )
    c = _clip01(c + delta[..., None])

    # 6b. 白点 / 黑点。只作用在亮度的上半段或下半段，中间调权重为 0，因此和阴影/高光分开。
    if params.whites:
        w = np.clip((_luma(c) - 0.5) / 0.5, 0.0, 1.0) ** 2  # y≤0.5 时为 0，y=1 时为 1，再平方使过渡更贴着白点
        c = _clip01(c + (params.whites / 100.0) * 0.25 * w[..., None])
    if params.blacks:
        w = np.clip((0.5 - _luma(c)) / 0.5, 0.0, 1.0) ** 2  # 只压或抬 y<0.5 的那一半，满幅系数同样是 0.25
        c = _clip01(c + (params.blacks / 100.0) * 0.25 * w[..., None])

    # 7. Global hue rotation (luma-weight preserving, encoded sRGB).
    if params.hue:
        c = _clip01(c @ _hue_matrix(params.hue).T)

    # 8. 饱和度：沿“离开亮度轴”的方向缩放。factor=1 不变，>1 更艳，<1 更灰。
    factor = 1.0 + params.saturation / 100.0
    y = _luma(c)
    c = _clip01(y[..., None] + factor * (c - y[..., None]))

    # 9. 自然饱和度：同一个缩放，但权重偏向低彩度像素，已经很艳的颜色（以及肤色）少动。
    if params.vibrance:
        chroma = np.clip(c.max(axis=-1) - c.min(axis=-1), 0.0, 1.0)  # 最大通道减最小通道，灰点为 0，纯色为 1
        weight = np.asarray(1.0 - chroma, dtype=np.float64)           # 越灰权重越大
        v_factor = 1.0 + (params.vibrance / 100.0) * weight
        y = _luma(c)
        c = _clip01(y[..., None] + v_factor[..., None] * (c - y[..., None]))

    # 10. 分离色调：阴影和高光分别混入一种纯色。balance 把分界亮度挪动最多 ±0.25。
    if params.split_shadow_amount or params.split_highlight_amount:
        y = np.clip(
            _luma(c) + (params.split_balance / 100.0) * 0.25, 0.0, 1.0
        )
        if params.split_shadow_amount:
            tint = hue_to_rgb(params.split_shadow_hue)
            # (1-y)^2：只染暗部。0.30 是满幅混合上限，避免阴影被染成整块纯色
            k = np.asarray(
                (params.split_shadow_amount / 100.0) * 0.30 * (1.0 - y) ** 2
            )
            c = c * (1.0 - k[..., None]) + tint * k[..., None]
        if params.split_highlight_amount:
            tint = hue_to_rgb(params.split_highlight_hue)
            k = np.asarray(
                (params.split_highlight_amount / 100.0) * 0.30 * y**2
            )
            c = c * (1.0 - k[..., None]) + tint * k[..., None]

    # 11. Encoded sRGB output.
    return _clip01(c)


def lut_grid(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Return (values, samples) for an N^3 grid.

    values has shape (N, 3); samples is the flattened encoded-RGB grid in
    .cube order (R fastest, B slowest) with shape (N^3, 3).
    """
    if n < 2 or n > 65:
        raise ValueError("LUT size must be in [2, 65]")
    values = np.linspace(0.0, 1.0, n, dtype=np.float64)  # 每条轴上等分的 N 个输入，含 0 和 1
    # indexing="ij"：三个轴分别对应输出的第 0、1、2 维。
    # ravel 是 C 顺序，最后一维变化最快，所以 r（第 3 个返回值）变化最快，b 最慢。
    # 这与 .cube 以及 glTexImage3D 的 RGB 紧密排列一致。
    b, g, r = np.meshgrid(values, values, values, indexing="ij")
    samples = np.stack([r.ravel(), g.ravel(), b.ravel()], axis=1)
    return values, samples


def bake_lut(params: ColorParams, n: int = 33) -> np.ndarray:
    """Bake the base LUT (strength not applied) as float32 samples."""
    _, grid = lut_grid(n)
    baked = transform_rgb(grid, params)
    return np.ascontiguousarray(baked.astype(np.float32))


def apply_strength(samples: np.ndarray, n: int, strength: float) -> np.ndarray:
    """Mix identity and base samples at grid vertices, in encoded sRGB."""
    s = float(strength)
    if not np.isfinite(s) or s < 0.0 or s > 1.0:
        raise ValueError("strength must be in [0, 1]")
    if s == 1.0:
        return np.ascontiguousarray(samples, dtype=np.float32)
    _, grid = lut_grid(n)
    base = np.asarray(samples, dtype=np.float64)
    mixed = (1.0 - s) * grid + s * base
    return np.ascontiguousarray(np.clip(mixed, 0.0, 1.0).astype(np.float32))


def bake_lut_with_strength(
    params: ColorParams, n: int = 33, strength: float = 1.0
) -> np.ndarray:
    return apply_strength(bake_lut(params, n), n, strength)


def _trilinear(
    lut: np.ndarray,
    n: int,
    q: np.ndarray,
) -> np.ndarray:
    """Trilinear interpolation of a [0,1]^3 grid at q (..., 3).

    This matches the GPU's center-corrected, linearly filtered 3D texture.
    """
    # GPU 先把 q 校正到纹素中心：tc = q*(N-1)/N + 0.5/N。
    # 硬件按“纹理坐标 × N - 0.5”还原成连续格子下标，化简后就是 q*(N-1)。
    # 所以这里直接用 pos = q*(N-1)，再取 8 个角点做三线性，与 sampler3D 的 LINEAR 一致。
    lut3 = np.asarray(lut, dtype=np.float64).reshape(n, n, n, 3)
    pos = np.clip(q, 0.0, 1.0) * (n - 1)
    i0 = np.floor(pos).astype(np.int64)
    i0 = np.minimum(i0, n - 1)
    i1 = np.minimum(i0 + 1, n - 1)
    f = pos - i0

    r0, g0, b0 = i0[..., 0], i0[..., 1], i0[..., 2]
    r1, g1, b1 = i1[..., 0], i1[..., 1], i1[..., 2]
    fr, fg, fb = f[..., 0:1], f[..., 1:2], f[..., 2:3]

    c000 = lut3[b0, g0, r0]
    c100 = lut3[b0, g0, r1]
    c010 = lut3[b0, g1, r0]
    c110 = lut3[b0, g1, r1]
    c001 = lut3[b1, g0, r0]
    c101 = lut3[b1, g0, r1]
    c011 = lut3[b1, g1, r0]
    c111 = lut3[b1, g1, r1]

    c00 = c000 * (1.0 - fr) + c100 * fr
    c10 = c010 * (1.0 - fr) + c110 * fr
    c01 = c001 * (1.0 - fr) + c101 * fr
    c11 = c011 * (1.0 - fr) + c111 * fr
    c0 = c00 * (1.0 - fg) + c10 * fg
    c1 = c01 * (1.0 - fg) + c11 * fg
    return c0 * (1.0 - fb) + c1 * fb


def sample_lut(
    samples: np.ndarray,
    n: int,
    rgb: np.ndarray,
    domain_min: tuple[float, float, float] = (0.0, 0.0, 0.0),
    domain_max: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> np.ndarray:
    """GPU-equivalent LUT lookup (clamped domain) without strength."""
    dmin = np.asarray(domain_min, dtype=np.float64)
    dmax = np.asarray(domain_max, dtype=np.float64)
    c = np.asarray(rgb, dtype=np.float64)
    q = np.clip((c - dmin) / (dmax - dmin), 0.0, 1.0)
    return _trilinear(samples, n, q)


def apply_effect_to_rgb(
    rgb: np.ndarray,
    samples: np.ndarray,
    n: int,
    strength: float = 1.0,
    domain_min: tuple[float, float, float] = (0.0, 0.0, 0.0),
    domain_max: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> np.ndarray:
    """CPU reference for the GPU shader: lookup, mix by strength, clamp."""
    c = np.asarray(rgb, dtype=np.float64)
    mapped = sample_lut(samples, n, c, domain_min, domain_max)
    mixed = (1.0 - float(strength)) * c + float(strength) * mapped
    return np.clip(mixed, 0.0, 1.0)


def apply_effect_to_rgba(
    rgba: np.ndarray,
    samples: np.ndarray,
    n: int,
    strength: float = 1.0,
    domain_min: tuple[float, float, float] = (0.0, 0.0, 0.0),
    domain_max: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> np.ndarray:
    """CPU reference for a full straight RGBA8 image. Alpha is untouched."""
    arr = np.asarray(rgba, dtype=np.uint8)
    rgb = arr[..., :3].astype(np.float64) / 255.0
    out_rgb = apply_effect_to_rgb(rgb, samples, n, strength, domain_min, domain_max)
    out = np.empty_like(arr)
    out[..., :3] = np.clip(np.rint(out_rgb * 255.0), 0, 255).astype(np.uint8)
    out[..., 3] = arr[..., 3]
    return out


def resample_effect(
    samples: np.ndarray,
    n_in: int,
    n_out: int,
    strength: float,
    domain_min: tuple[float, float, float] = (0.0, 0.0, 0.0),
    domain_max: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> np.ndarray:
    """Resample the current effect (including strength) onto a [0,1]^3 grid.

    Used for exporting external LUTs and for the LUT readback check. The
    result is an ordinary [0,1] domain LUT.
    """
    _, grid = lut_grid(n_out)
    effect = apply_effect_to_rgb(
        grid, samples, n_in, strength, domain_min, domain_max
    )
    return np.ascontiguousarray(effect.astype(np.float32))


def algorithm_version() -> str:
    return ALGORITHM_VERSION


__all__ = [
    "srgb_decode",
    "srgb_encode",
    "transform_rgb",
    "lut_grid",
    "bake_lut",
    "apply_strength",
    "bake_lut_with_strength",
    "sample_lut",
    "apply_effect_to_rgb",
    "apply_effect_to_rgba",
    "resample_effect",
    "algorithm_version",
    "PARAM_KEYS",
]
