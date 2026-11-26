"""Five-dimension performance and image-quality benchmark for ai_color_app.

The package is intentionally self-contained: it imports the production modules
read-only and never mutates them. Everything it produces is written under
``runtime/benchmark_results``.

Sub-modules
-----------
metrics       Colour-science and image metrics (sRGB->XYZ->CIELAB, dE76, dE00,
              PSNR, MAE, SSIM, Shannon entropy, Hasler-Suesstrunk colorfulness).
interpolation Trilinear vs tetrahedral 3D LUT sampling.
dataset       Deterministic synthetic benchmark images + fixture discovery.
dim1_speedup  CPU per-pixel maths vs OpenGL 3.3 Core offscreen rendering.
dim2_lut      3D LUT grid-size accuracy and transfer cost.
dim3_interp   Trilinear vs tetrahedral interpolation quality.
dim4_quality  Objective quality of the five built-in grading presets.
dim5_ai       Offline/online intent parsing accuracy and robustness.
visualization 300 DPI publication figures.
report        Markdown report assembly.
"""

__all__ = [
    "dataset",
    "dim1_speedup",
    "dim2_lut",
    "dim3_interp",
    "dim4_quality",
    "dim5_ai",
    "interpolation",
    "metrics",
    "report",
    "visualization",
]
