"""3D LUT sampling: GPU-equivalent trilinear vs 6-simplex tetrahedral.

Trilinear interpolation blends the eight corners of the enclosing cube. On the
neutral axis (r = g = b) the sample sits exactly on the cube diagonal, so all
eight corners contribute: any asymmetry between them shows up as chroma drift
on what should stay grey.

Tetrahedral interpolation (Kasson et al., 1995; the default in DaVinci Resolve
and most film-grade LUT engines) sorts the fractional coordinates and keeps
only the four vertices of the simplex that contains the sample. It needs four
lookups instead of eight and cannot invent a colour that is not spanned by the
tetrahedron holding the input.
"""

from __future__ import annotations

import numpy as np

Domain = tuple[float, float, float]


def _grid_position(
    rgb: np.ndarray, n: int, domain_min: Domain, domain_max: Domain
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    dmin = np.asarray(domain_min, dtype=np.float64)
    dmax = np.asarray(domain_max, dtype=np.float64)
    c = np.asarray(rgb, dtype=np.float64)
    q = np.clip((c - dmin) / (dmax - dmin), 0.0, 1.0)
    pos = q * (n - 1)
    i0 = np.minimum(np.floor(pos).astype(np.int64), n - 1)
    i1 = np.minimum(i0 + 1, n - 1)
    return i0, i1, pos - i0


def tetrahedral_sample(
    lut: np.ndarray,
    n: int,
    rgb: np.ndarray,
    domain_min: Domain = (0.0, 0.0, 0.0),
    domain_max: Domain = (1.0, 1.0, 1.0),
) -> np.ndarray:
    """Sample an N^3 LUT with tetrahedral (6-simplex) interpolation."""
    lut3 = np.asarray(lut, dtype=np.float64).reshape(n, n, n, 3)
    i0, i1, f = _grid_position(rgb, n, domain_min, domain_max)

    r0, g0, b0 = i0[..., 0], i0[..., 1], i0[..., 2]
    r1, g1, b1 = i1[..., 0], i1[..., 1], i1[..., 2]

    c000 = lut3[b0, g0, r0]
    c100 = lut3[b0, g0, r1]
    c010 = lut3[b0, g1, r0]
    c110 = lut3[b0, g1, r1]
    c001 = lut3[b1, g0, r0]
    c101 = lut3[b1, g0, r1]
    c011 = lut3[b1, g1, r0]
    c111 = lut3[b1, g1, r1]

    fr, fg, fb = f[..., 0:1], f[..., 1:2], f[..., 2:3]
    sr, sg, sb = f[..., 0], f[..., 1], f[..., 2]

    # The six orderings of (fr, fg, fb) select the simplex; each branch is a
    # chain of four vertices along the sorted axis order.
    branches = (
        (
            (sr > sg) & (sg > sb),
            c000 + fr * (c100 - c000) + fg * (c110 - c100) + fb * (c111 - c110),
        ),
        (
            (sr > sg) & ~(sg > sb) & (sr > sb),
            c000 + fr * (c100 - c000) + fb * (c101 - c100) + fg * (c111 - c101),
        ),
        (
            (sr > sg) & ~(sg > sb) & ~(sr > sb),
            c000 + fb * (c001 - c000) + fr * (c101 - c001) + fg * (c111 - c101),
        ),
        (
            ~(sr > sg) & (sb > sg),
            c000 + fb * (c001 - c000) + fg * (c011 - c001) + fr * (c111 - c011),
        ),
        (
            ~(sr > sg) & ~(sb > sg) & (sb > sr),
            c000 + fg * (c010 - c000) + fb * (c011 - c010) + fr * (c111 - c011),
        ),
        (
            ~(sr > sg) & ~(sb > sg) & ~(sb > sr),
            c000 + fg * (c010 - c000) + fr * (c110 - c010) + fb * (c111 - c110),
        ),
    )

    # A NaN coordinate matches no branch; seeding with the lower corner keeps
    # the output defined instead of uninitialised.
    out = np.array(c000, dtype=np.float64, copy=True)
    assigned = np.zeros(sr.shape, dtype=bool)
    for mask, value in branches:
        take = mask & ~assigned
        assigned |= take
        out[take] = value[take]
    return out


def trilinear_sample(
    lut: np.ndarray,
    n: int,
    rgb: np.ndarray,
    domain_min: Domain = (0.0, 0.0, 0.0),
    domain_max: Domain = (1.0, 1.0, 1.0),
) -> np.ndarray:
    """Trilinear sampling, byte-for-byte the CPU mirror of the GLSL shader."""
    from baker.color_transform import sample_lut

    return sample_lut(lut, n, np.asarray(rgb, dtype=np.float64), domain_min, domain_max)


__all__ = ["Domain", "tetrahedral_sample", "trilinear_sample"]
