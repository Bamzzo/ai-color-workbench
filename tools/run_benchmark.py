#!/usr/bin/env python
"""Five-dimension performance & image-quality benchmark for ai_color_app.

Usage
-----
    .\\.venv\\Scripts\\python.exe tools\\run_benchmark.py
    .\\.venv\\Scripts\\python.exe tools\\run_benchmark.py --online
    .\\.venv\\Scripts\\python.exe tools\\run_benchmark.py --only dim1 dim3

Outputs (all under ``runtime/benchmark_results/``):
    benchmark_report.md   Markdown report with tables and conclusions
    benchmark_raw.json    Every raw sample, for before/after diffs
    fig1..fig4 *.png      300 DPI publication figures

Only reads the production packages (baker/, engine/, ai/, app/); nothing in the
application is modified.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
import traceback
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:  # Windows consoles default to cp936, which mangles some CJK output.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - non-reconfigurable streams
    pass

from tools.benchmark import (  # noqa: E402
    common,
    dim1_speedup,
    dim2_lut,
    dim3_interp,
    dim4_quality,
    dim5_ai,
    report,
    visualization,
)

ALL_DIMS = ("dim1", "dim2", "dim3", "dim4", "dim5")
DIM_KEYS = {
    "dim1": "dim1_speedup",
    "dim2": "dim2_lut",
    "dim3": "dim3_interp",
    "dim4": "dim4_quality",
    "dim5": "dim5_ai",
}
DIM_TITLES = {
    "dim1": "维度 1/5  OpenGL GPU 渲染管线加速比",
    "dim2": "维度 2/5  3D LUT 尺寸近似精度与色差",
    "dim3": "维度 3/5  三线性 vs 四面体插值",
    "dim4": "维度 4/5  图像调色增强客观质量",
    "dim5": "维度 5/5  AI 意图解析准确率与鲁棒性",
}


def _banner(text: str) -> None:
    print("", flush=True)
    print("=" * 78, flush=True)
    print(text, flush=True)
    print("=" * 78, flush=True)


def _run_dimension(name: str, online: bool, results_dir: Path) -> dict:
    _banner(DIM_TITLES[name])
    started = time.perf_counter()
    if name == "dim1":
        payload = dim1_speedup.run(results_dir)
    elif name == "dim2":
        payload = dim2_lut.run(results_dir)
    elif name == "dim3":
        payload = dim3_interp.run(results_dir)
    elif name == "dim4":
        payload = dim4_quality.run(results_dir)
    elif name == "dim5":
        payload = dim5_ai.run(online=online, results_dir=results_dir)
    else:  # pragma: no cover - guarded by argparse choices
        raise ValueError(name)
    elapsed = time.perf_counter() - started
    payload["elapsed_s"] = round(elapsed, 2)
    print(f"  [{name}] done in {elapsed:.1f} s", flush=True)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--online",
        action="store_true",
        help="also evaluate DeepSeekProvider (requires AI_API_KEY)",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        choices=ALL_DIMS,
        default=list(ALL_DIMS),
        help="restrict the run to a subset of dimensions",
    )
    parser.add_argument(
        "--no-figures",
        action="store_true",
        help="skip matplotlib rendering (tables still produced)",
    )
    parser.add_argument(
        "--from-json",
        type=Path,
        default=None,
        help="rebuild figures and report from an existing benchmark_raw.json",
    )
    args = parser.parse_args(argv)

    results_dir = common.RESULTS_DIR
    results_dir.mkdir(parents=True, exist_ok=True)

    if args.from_json is not None:
        return _rebuild_from_json(args.from_json, results_dir, args.no_figures)

    common.reset_work_dir()

    started = time.perf_counter()
    meta = common.environment_info()
    print(f"ai_color_app benchmark | {meta['platform']}", flush=True)
    print(f"CPU: {meta['cpu_model']}", flush=True)
    print(f"GPU: {meta['gpu_model']}", flush=True)
    print(f"worker: {meta['worker_path']} ({meta['worker_bytes']:,} B)", flush=True)
    print(f"results: {meta['results_dir']}", flush=True)

    raw: dict = {"meta": meta}
    failures: list[str] = []
    for name in args.only:
        try:
            raw[DIM_KEYS[name]] = _run_dimension(name, args.online, results_dir)
        except Exception as exc:
            failures.append(name)
            print(f"  [!!] {name} failed: {type(exc).__name__}: {exc}", flush=True)
            traceback.print_exc()

    if failures:
        print(f"\nFAILED dimensions: {', '.join(failures)}", flush=True)
        return 1

    partial = set(args.only) != set(ALL_DIMS)
    if partial:
        _banner("部分维度运行：写入 benchmark_raw_partial.json（不覆盖完整结果）")
        common.dump_json(results_dir / "benchmark_raw_partial.json", raw)
        return 0

    return _emit_outputs(raw, results_dir, args.no_figures, time.perf_counter() - started)


def _emit_outputs(
    raw: dict, results_dir: Path, no_figures: bool, elapsed_s: float
) -> int:
    _banner("输出报告与图表")
    figures: list[str] = []
    if not no_figures:
        try:
            paths = visualization.build_all(raw, results_dir)
            figures = [path.name for path in paths]
        except Exception as exc:
            print(f"  [!!] figure generation failed: {exc}", flush=True)
            traceback.print_exc()
            return 1

    report_path = report.build(raw, results_dir)
    raw["figures"] = figures
    raw["total_elapsed_s"] = round(elapsed_s, 2)
    common.dump_json(results_dir / "benchmark_raw.json", raw)
    shutil.rmtree(common.WORK_DIR, ignore_errors=True)

    _banner("完成")
    print(f"  报告   : {report_path}", flush=True)
    print(f"  原始数据: {results_dir / 'benchmark_raw.json'}", flush=True)
    for name in figures:
        print(f"  图表   : {results_dir / name}", flush=True)
    print(f"  总耗时 : {raw['total_elapsed_s']:.1f} s", flush=True)
    return 0


def _rebuild_from_json(source: Path, results_dir: Path, no_figures: bool) -> int:
    import json

    if not source.is_file():
        print(f"  [!!] raw json not found: {source}", flush=True)
        return 1
    raw = json.loads(source.read_text(encoding="utf-8"))
    missing = [key for key in DIM_KEYS.values() if key not in raw]
    if missing:
        print(f"  [!!] raw json is missing dimensions: {', '.join(missing)}", flush=True)
        return 1
    print(f"  rebuilding from {source} (no benchmark executed)", flush=True)
    return _emit_outputs(raw, results_dir, no_figures, float(raw.get("total_elapsed_s", 0.0)))


if __name__ == "__main__":
    raise SystemExit(main())
