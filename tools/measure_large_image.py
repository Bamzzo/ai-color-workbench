"""Measure load/preview/export cost and peak memory on a large image (T15).

The gap this closes: the 40 MP limit was never exercised end to end, so nobody
knew whether a legal maximum-size file fits comfortably or pushes the process
into swap. The report separates the decoded-image peak from the steady state so
the numbers can go straight into a test record.

Usage:
    .venv/Scripts/python.exe tools/measure_large_image.py
    .venv/Scripts/python.exe tools/measure_large_image.py --side 6324 --export
"""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from ctypes import wintypes
from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import image_io, paths  # noqa: E402
from app.pipeline import RenderPipeline, RenderSnapshot  # noqa: E402
from app.state import AppState  # noqa: E402
from baker.params import load_preset  # noqa: E402

# Large synthetic inputs live apart from the small shared fixtures so the
# fixture directory stays small and reproducible.
LARGE_DIR = ROOT / "runtime" / "large-fixtures"


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _memory() -> tuple[float, float] | None:
    """Return (working set MB, peak working set MB) for this process."""
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    except Exception:
        return None
    try:
        get_current = kernel32.GetCurrentProcess
        get_current.argtypes = []
        get_current.restype = wintypes.HANDLE
        query = kernel32.K32GetProcessMemoryInfo
        query.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        query.restype = wintypes.BOOL
        # Without an explicit HANDLE restype the pseudo-handle -1 is passed as a
        # 32-bit int and the call fails on x64.
        if not query(get_current(), ctypes.byref(counters), counters.cb):
            return None
    except Exception:
        return None
    return (
        counters.WorkingSetSize / 1e6,
        counters.PeakWorkingSetSize / 1e6,
    )


def _build_fixture(side: int) -> Path:
    """Write a photolike PNG at roughly the requested square side."""
    target = LARGE_DIR / f"large-{side}.png"
    if target.is_file():
        return target
    LARGE_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20261021)
    # A smooth gradient plus a little noise: compresses poorly enough to keep
    # the decode path honest, small enough to generate in a few seconds.
    row = np.linspace(0, 255, side, dtype=np.float32)
    plane = np.tile(row, (side, 1))
    arr = np.stack([plane, plane.T, (plane + plane.T) / 2.0], axis=2)
    arr += rng.normal(0, 4, size=(side, side, 1)).astype(np.float32)
    arr = np.clip(np.rint(arr), 0, 255).astype(np.uint8)
    Image.fromarray(arr, "RGB").save(target, optimize=False, compress_level=1)
    del arr
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--side", type=int, default=6324)
    parser.add_argument("--export", action="store_true")
    parser.add_argument(
        "--repeats",
        type=int,
        default=0,
        help="edit-and-preview cycles, to show job/cache growth over a session",
    )
    args = parser.parse_args()

    side = args.side
    pixels = side * side
    print(f"fixture side={side} pixels={pixels:,} "
          f"({pixels / 1e6:.2f} MP), limit={image_io.MAX_PIXELS:,}")
    started = time.monotonic()
    path = _build_fixture(side)
    print(f"fixture ready in {time.monotonic() - started:.1f}s "
          f"({path.stat().st_size / 1e6:.1f} MB on disk)")

    memory = _memory()
    print("baseline RSS: " + (f"{memory[0]:.0f} MB" if memory else "unavailable"))

    started = time.monotonic()
    source = image_io.load_source_image(path)
    load_ms = (time.monotonic() - started) * 1000.0
    peak_after_load = _memory()
    print(f"load: {load_ms:.0f} ms, {source.width}x{source.height}, "
          f"rss={peak_after_load[0]:.0f} MB peak={peak_after_load[1]:.0f} MB"
          if peak_after_load else f"load: {load_ms:.0f} ms")

    pipeline = RenderPipeline()
    state = AppState()
    state.document_id = "doc-measure-large"
    state.revision = 1
    state.source = source
    state.preview_image, _scaled, _p = pipeline.prepare_preview(source)
    state.params = load_preset("cinematic")[0]
    state.strength = 1.0
    snapshot = RenderSnapshot.from_state(state)

    started = time.monotonic()
    preview = pipeline.render_preview(snapshot)
    preview_ms = (time.monotonic() - started) * 1000.0
    print(f"preview: {preview_ms:.0f} ms, {preview.image.width}x{preview.image.height}")

    jobs_before = sum(1 for _ in paths.JOBS.iterdir()) if paths.JOBS.is_dir() else 0
    repeat_times: list[float] = []
    for index in range(max(0, args.repeats)):
        state.params = replace(state.params, exposure_ev=0.02 * (index + 1))
        state.revision += 1
        started = time.monotonic()
        pipeline.render_preview(RenderSnapshot.from_state(state))
        repeat_times.append((time.monotonic() - started) * 1000.0)
    if repeat_times:
        jobs_after = sum(1 for _ in paths.JOBS.iterdir()) if paths.JOBS.is_dir() else 0
        print(
            f"repeats: {len(repeat_times)} previews, "
            f"mean {sum(repeat_times) / len(repeat_times):.0f} ms, "
            f"max {max(repeat_times):.0f} ms, "
            f"job dirs {jobs_before} -> {jobs_after}"
        )

    if args.export:
        target = LARGE_DIR / "large-export.png"
        started = time.monotonic()
        result = pipeline.export_image(snapshot, target, "PNG")
        export_ms = (time.monotonic() - started) * 1000.0
        print(f"export: {export_ms:.0f} ms -> {result.path.name} "
              f"({result.width}x{result.height})")
        target.unlink(missing_ok=True)

    final = _memory()
    cache_bytes, cache_files = paths.cache_usage()
    job_files = sum(1 for _ in paths.JOBS.rglob("*")) if paths.JOBS.is_dir() else 0
    report = {
        "side": side,
        "pixels": pixels,
        "load_ms": round(load_ms, 1),
        "preview_ms": round(preview_ms, 1),
        "rss_after_load_mb": round(peak_after_load[0], 1) if peak_after_load else None,
        "peak_rss_mb": round(final[1], 1) if final else None,
        "steady_rss_mb": round(final[0], 1) if final else None,
        "cache_mb": round(cache_bytes / 1e6, 1),
        "cache_files": cache_files,
        "job_files": job_files,
        "repeats": len(repeat_times),
        "repeat_mean_ms": round(sum(repeat_times) / len(repeat_times), 1)
        if repeat_times
        else None,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
