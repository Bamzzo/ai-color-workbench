"""300 DPI publication figures for the benchmark report.

Every figure is a standalone PNG on a white background, sized for a two-column
paper (roughly 10-15 in wide at 300 DPI). A CJK font is registered explicitly
because matplotlib's default DejaVu Sans has no Chinese glyphs and would render
boxes instead of labels.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager

DPI = 300

# Muted, print-safe palette.
C_CPU = "#2E5EAA"
C_GPU = "#C9705A"
C_SHADER = "#8FA9C9"
C_SPEED = "#4E8C6A"
C_TRI = "#2E5EAA"
C_TET = "#C9705A"
C_BASE = "#9AA3AD"
C_ACCENT = "#E0A458"

_CJK_CANDIDATES = (
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simsun.ttc",
)


def configure_style() -> str:
    """Register the first available CJK font and set a paper-friendly rc."""
    chosen = ""
    for candidate in _CJK_CANDIDATES:
        path = Path(candidate)
        if not path.is_file():
            continue
        try:
            font_manager.fontManager.addfont(str(path))
            chosen = font_manager.FontProperties(fname=str(path)).get_name()
        except Exception:
            continue
        if chosen:
            break

    families = [chosen] if chosen else []
    families += ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": families,
            "axes.unicode_minus": False,
            "font.size": 10.5,
            "axes.titlesize": 12,
            "axes.labelsize": 11,
            "axes.linewidth": 0.9,
            "axes.edgecolor": "#4A4F57",
            "axes.grid": True,
            "grid.color": "#DCE1E7",
            "grid.linewidth": 0.7,
            "grid.alpha": 0.9,
            "legend.frameon": False,
            "legend.fontsize": 9.5,
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
            "savefig.bbox": "tight",
            "savefig.dpi": DPI,
        }
    )
    return chosen or "DejaVu Sans"


def _save(fig: Any, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    print(f"        figure -> {path.relative_to(path.parents[2])}", flush=True)
    return path


def _annotate(ax: Any, bars: Any, fmt: str = "{:.0f}", dy: float = 1.12) -> None:
    for bar in bars:
        height = bar.get_height()
        ax.annotate(
            fmt.format(height),
            xy=(bar.get_x() + bar.get_width() / 2.0, height),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8.2,
            color="#3C424A",
        )


def _legend_above(ax: Any, handles: list[Any], ncol: int, pad: float = 38.0) -> None:
    """Place a legend above the axes so it can never cover bars or ticks."""
    ax.set_title(ax.get_title(), pad=pad)
    ax.legend(
        handles,
        [handle.get_label() for handle in handles],
        loc="lower center",
        bbox_to_anchor=(0.5, 1.02),
        ncol=ncol,
        fontsize=8.4,
        handlelength=1.5,
        columnspacing=1.2,
        borderaxespad=0.0,
    )


def figure_speedup(data: dict[str, Any], path: Path) -> Path:
    rows = data["rows"]
    labels = [row["label"] for row in rows]
    cpu = [row["cpu"]["mean_ms"] for row in rows]
    gpu_total = [row["gpu_total"]["mean_ms"] for row in rows]
    gpu_shader = [row["gpu_shader_ms"] for row in rows]
    speedup = [row["speedup_total"] for row in rows]

    x = np.arange(len(rows), dtype=float)
    width = 0.26
    fig, ax = plt.subplots(figsize=(10.6, 5.4))
    bars_cpu = ax.bar(x - width, cpu, width, color=C_CPU, label="CPU 逐像素变换 (float64)")
    bars_total = ax.bar(x, gpu_total, width, color=C_GPU, label="OpenGL 端到端 (进程+IO+渲染)")
    bars_shader = ax.bar(
        x + width,
        gpu_shader,
        width,
        color=C_SHADER,
        hatch="///",
        edgecolor="white",
        linewidth=0.6,
        label="OpenGL 着色 + 回读",
    )
    ax.set_yscale("log")
    ax.set_ylabel("单帧耗时 (ms，对数刻度)")
    ax.set_xlabel("测试分辨率")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(min(gpu_shader) * 0.55, max(cpu) * 2.4)
    _annotate(ax, bars_cpu, "{:.0f}")
    _annotate(ax, bars_total, "{:.0f}")
    _annotate(ax, bars_shader, "{:.0f}")

    ax2 = ax.twinx()
    ax2.grid(False)
    ax2.plot(
        x,
        speedup,
        color=C_SPEED,
        marker="o",
        markersize=6,
        linewidth=1.8,
        label="端到端加速比 (CPU / GPU)",
        zorder=5,
    )
    for xi, value in zip(x, speedup):
        ax2.annotate(
            f"{value:.2f}x",
            xy=(xi, value),
            xytext=(0, 10),
            textcoords="offset points",
            ha="center",
            fontsize=9,
            color=C_SPEED,
        )
    ax2.set_ylabel("加速比 (×)")
    ax2.set_ylim(0.0, max(speedup) * 1.35)

    handles = [bars_cpu, bars_total, bars_shader, ax2.lines[0]]
    ax.legend(handles, [h.get_label() for h in handles], loc="upper left", ncol=1)
    ax.set_title("CPU 逐像素运算 vs OpenGL 3.3 Core 3D LUT 渲染")
    fig.tight_layout()
    return _save(fig, path)


def figure_lut(data: dict[str, Any], path: Path) -> Path:
    rows = data["rows"]
    sizes = [row["size"] for row in rows]
    psnr = [row["psnr_db"] for row in rows]
    de00 = [row["de00_mean"] for row in rows]
    de00_max = [row["de00_max"] for row in rows]
    bake = [row["bake_ms"] for row in rows]
    payload = [row["payload_kb"] for row in rows]
    positions = np.arange(len(rows), dtype=float)
    tick_labels = [f"${s}^3$\n({s**3:,} 顶点)" for s in sizes]

    fig, (ax_left, ax_right) = plt.subplots(1, 2, figsize=(12.6, 4.9))

    ax_left.plot(
        positions, psnr, color=C_CPU, marker="o", linewidth=1.9, label="PSNR (dB)"
    )
    for xi, value in zip(positions, psnr):
        ax_left.annotate(
            f"{value:.1f} dB",
            xy=(xi, value),
            xytext=(0, 9),
            textcoords="offset points",
            ha="center",
            fontsize=8.6,
            color=C_CPU,
        )
    ax_left.set_ylabel("PSNR (dB)", color=C_CPU)
    ax_left.tick_params(axis="y", labelcolor=C_CPU)
    ax_left.set_ylim(min(psnr) - 6.0, max(psnr) + 6.0)
    ax_left.set_xticks(positions)
    ax_left.set_xticklabels(tick_labels)
    ax_left.set_xlabel("3D LUT 网格尺寸")

    twin = ax_left.twinx()
    twin.grid(False)
    twin.plot(
        positions, de00, color=C_TET, marker="s", linewidth=1.9, label="平均 $\\Delta E_{00}$"
    )
    twin.plot(
        positions,
        de00_max,
        color=C_TET,
        marker="^",
        linewidth=1.1,
        linestyle="--",
        alpha=0.75,
        label="最大 $\\Delta E_{00}$",
    )
    for xi, value in zip(positions, de00):
        twin.annotate(
            f"{value:.3f}",
            xy=(xi, value),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            fontsize=8.4,
            color=C_TET,
        )
    twin.set_ylabel("CIEDE2000 色差", color=C_TET)
    twin.tick_params(axis="y", labelcolor=C_TET)
    twin.set_ylim(0.0, max(de00_max) * 1.5)
    ax_left.set_title("网格密度 vs 近似精度 (真值 = float64 逐像素)")
    _legend_above(ax_left, ax_left.lines + twin.lines, ncol=3)

    ax_right.plot(
        positions, bake, color=C_ACCENT, marker="o", linewidth=1.9, label="烘焙耗时 (ms)"
    )
    for xi, value in zip(positions, bake):
        ax_right.annotate(
            f"{value:.0f} ms",
            xy=(xi, value),
            xytext=(0, 9),
            textcoords="offset points",
            ha="center",
            fontsize=8.6,
            color="#A9762F",
        )
    ax_right.set_ylabel("烘焙耗时 (ms)", color="#A9762F")
    ax_right.tick_params(axis="y", labelcolor="#A9762F")
    ax_right.set_yscale("log")
    ax_right.set_ylim(bake[0] / 1.8, bake[-1] * 1.8)
    ax_right.set_xticks(positions)
    ax_right.set_xticklabels(tick_labels)
    ax_right.set_xlabel("3D LUT 网格尺寸")

    twin2 = ax_right.twinx()
    twin2.grid(False)
    twin2.plot(
        positions,
        payload,
        color=C_SPEED,
        marker="s",
        linewidth=1.9,
        label="Base64 传输体积 (KB)",
    )
    for xi, value in zip(positions, payload):
        twin2.annotate(
            f"{value:,.0f} KB",
            xy=(xi, value),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            fontsize=8.4,
            color=C_SPEED,
        )
    twin2.set_ylabel("Base64 体积 (KB)", color=C_SPEED)
    twin2.tick_params(axis="y", labelcolor=C_SPEED)
    twin2.set_ylim(0.0, max(payload) * 1.55)
    ax_right.set_title("工程成本：烘焙时间与前端传输体积")
    _legend_above(ax_right, ax_right.lines + twin2.lines, ncol=2)

    fig.tight_layout()
    return _save(fig, path)


def figure_interp(data: dict[str, Any], path: Path) -> Path:
    cases = data["cases"]
    primary = data["primary_preset"]
    stress = data["stress_preset"]
    selected = [row for row in cases if row["preset"] == primary]
    sizes = [row["size"] for row in selected]

    fig, (ax_curve, ax_grey, ax_sweep) = plt.subplots(1, 3, figsize=(15.4, 4.6))

    # (a) chroma drift along the neutral ramp, 33^3.
    curve_row = max(selected, key=lambda row: row["size"]) if selected else None
    if curve_row is not None:
        levels = np.arange(256)
        ax_curve.plot(
            levels,
            curve_row["trilinear"]["curves"]["chroma"],
            color=C_TRI,
            linewidth=1.7,
            label=f"三线性 {curve_row['size']}$^3$",
        )
        ax_curve.plot(
            levels,
            curve_row["tetrahedral"]["curves"]["chroma"],
            color=C_TET,
            linewidth=1.7,
            label=f"四面体 {curve_row['size']}$^3$",
        )
    ax_curve.set_xlabel("中性灰阶输入 (0-255)")
    ax_curve.set_ylabel("输出色偏 $\\sqrt{a^{*2}+b^{*2}}$")
    ax_curve.set_title("(a) 灰轴色偏随输入变化")
    ax_curve.legend(loc="upper left")

    # (b) mean / max chroma per size, two filters.
    positions = np.arange(len(sizes), dtype=float)
    width = 0.34
    tri_mean = [row["trilinear"]["grey_chroma_mean"] for row in selected]
    tet_mean = [row["tetrahedral"]["grey_chroma_mean"] for row in selected]
    tri_max = [row["trilinear"]["grey_chroma_max"] for row in selected]
    tet_max = [row["tetrahedral"]["grey_chroma_max"] for row in selected]
    ax_grey.bar(
        positions - width / 2, tri_mean, width, color=C_TRI, label="三线性 平均"
    )
    ax_grey.bar(
        positions + width / 2, tet_mean, width, color=C_TET, label="四面体 平均"
    )
    ax_grey.plot(
        positions - width / 2,
        tri_max,
        color=C_TRI,
        marker="^",
        linestyle="none",
        label="三线性 最大",
    )
    ax_grey.plot(
        positions + width / 2,
        tet_max,
        color=C_TET,
        marker="v",
        linestyle="none",
        label="四面体 最大",
    )
    top = max(max(tri_max), max(tet_max))
    for xi, value in zip(positions - width / 2, tri_max):
        ax_grey.annotate(
            f"{value:.2f}",
            xy=(xi, value),
            xytext=(0, 5),
            textcoords="offset points",
            ha="center",
            fontsize=7.8,
            color=C_TRI,
        )
    for xi, value in zip(positions + width / 2, tet_max):
        ax_grey.annotate(
            f"{value:.2f}",
            xy=(xi, value),
            xytext=(0, 5),
            textcoords="offset points",
            ha="center",
            fontsize=7.8,
            color=C_TET,
        )
    ax_grey.set_ylim(0.0, top * 1.45)
    ax_grey.set_xticks(positions)
    ax_grey.set_xticklabels([f"{s}$^3$" for s in sizes])
    ax_grey.set_xlabel("3D LUT 网格尺寸")
    ax_grey.set_ylabel("灰轴色偏 $C^{*}_{ab}$")
    ax_grey.set_title(f"(b) 灰轴色偏统计 ({primary})")
    ax_grey.legend(loc="upper right", ncol=2, fontsize=8.4)

    # (c) colour-sweep accuracy: PSNR gain and dE00 reduction.
    tri_psnr = [row["trilinear"]["sweep_psnr_db"] for row in selected]
    tet_psnr = [row["tetrahedral"]["sweep_psnr_db"] for row in selected]
    tri_de = [row["trilinear"]["sweep_de00_mean"] for row in selected]
    tet_de = [row["tetrahedral"]["sweep_de00_mean"] for row in selected]
    ax_sweep.bar(positions - width / 2, tri_psnr, width, color=C_TRI, label="三线性 PSNR")
    ax_sweep.bar(positions + width / 2, tet_psnr, width, color=C_TET, label="四面体 PSNR")
    low = min(min(tri_psnr), min(tet_psnr))
    high = max(max(tri_psnr), max(tet_psnr))
    ax_sweep.set_ylim(max(0.0, low - 2.0), high + 1.6)
    ax_sweep.set_ylabel("PSNR (dB)")
    ax_sweep.set_xticks(positions)
    ax_sweep.set_xticklabels([f"{s}$^3$" for s in sizes])
    ax_sweep.set_xlabel("3D LUT 网格尺寸")
    ax_sweep.set_title("(c) 全色域测试卡精度")

    twin = ax_sweep.twinx()
    twin.grid(False)
    twin.plot(
        positions, tri_de, color=C_TRI, marker="o", linestyle="--", linewidth=1.2, label="三线性 $\\Delta E_{00}$"
    )
    twin.plot(
        positions, tet_de, color=C_TET, marker="s", linestyle="-.", linewidth=1.2, label="四面体 $\\Delta E_{00}$"
    )
    twin.set_ylabel("平均 $\\Delta E_{00}$")
    twin.set_ylim(0.0, max(max(tri_de), max(tet_de)) * 1.5)
    ax_sweep.set_title("(c) 全色域测试卡精度")
    _legend_above(ax_sweep, ax_sweep.containers + twin.lines, ncol=2, pad=46)

    fig.suptitle(
        f"三线性 vs 四面体(6-simplex) 插值：主用预设 {primary}，压力预设 {stress} 见报告",
        fontsize=11.5,
        y=1.02,
    )
    fig.tight_layout()
    return _save(fig, path)


def figure_quality(data: dict[str, Any], path: Path) -> Path:
    rows = data["rows"]
    baseline = data["baseline"]
    labels = [row["label"] for row in rows]
    positions = np.arange(len(rows), dtype=float)
    width = 0.36

    fig, axes = plt.subplots(1, 3, figsize=(15.4, 4.6))
    specs = (
        ("ssim", "SSIM（结构相似性）", 1.0, "{:.4f}"),
        ("entropy", "信息熵 (bit)", baseline["entropy"], "{:.2f}"),
        ("colorfulness", "色彩丰富度 (H&S)", baseline["colorfulness"], "{:.1f}"),
    )
    for ax, (key, title, before_value, fmt) in zip(axes, specs):
        before = [before_value] * len(rows)
        after = [row["mean"][key] for row in rows]
        bars_before = ax.bar(
            positions - width / 2, before, width, color=C_BASE, label="调色前 (Original)"
        )
        bars_after = ax.bar(
            positions + width / 2, after, width, color=C_GPU, label="调色后 (Graded)"
        )
        top = max(max(before), max(after))
        ax.set_ylim(0.0, top * 1.28)
        for bars in (bars_before, bars_after):
            for bar in bars:
                ax.annotate(
                    fmt.format(bar.get_height()),
                    xy=(bar.get_x() + bar.get_width() / 2.0, bar.get_height()),
                    xytext=(0, 3),
                    textcoords="offset points",
                    ha="center",
                    fontsize=7.8,
                    color="#3C424A",
                )
        ax.set_xticks(positions)
        ax.set_xticklabels(labels, rotation=18, ha="right")
        ax.set_title(title)
        ax.legend(loc="upper right", fontsize=8.4)

    axes[0].set_ylabel("SSIM")
    axes[1].set_ylabel("bits")
    axes[2].set_ylabel("colorfulness")
    fig.suptitle(
        f"五种调色预设的客观画质对比（{len(data['images'])} 张基准图均值）",
        fontsize=11.5,
        y=1.02,
    )
    fig.tight_layout()
    return _save(fig, path)


def build_all(raw: dict[str, Any], results_dir: Path) -> list[Path]:
    font = configure_style()
    print(f"  [figures] CJK font: {font}", flush=True)
    return [
        figure_speedup(raw["dim1_speedup"], results_dir / "fig1_gpu_vs_cpu_speedup.png"),
        figure_lut(raw["dim2_lut"], results_dir / "fig2_lut_size_accuracy.png"),
        figure_interp(raw["dim3_interp"], results_dir / "fig3_trilinear_vs_tetrahedral.png"),
        figure_quality(raw["dim4_quality"], results_dir / "fig4_image_quality_radar_or_bar.png"),
    ]


__all__ = [
    "DPI",
    "build_all",
    "configure_style",
    "figure_interp",
    "figure_lut",
    "figure_quality",
    "figure_speedup",
]
