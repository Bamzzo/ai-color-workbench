"""Shared plumbing: paths, timing statistics, environment capture, LUT caching."""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = ROOT / "runtime" / "benchmark_results"
WORK_DIR = RESULTS_DIR / ".work"


@dataclass(frozen=True)
class Timing:
    samples_ms: list[float]
    mean_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float
    std_ms: float
    fps: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "samples_ms": [round(v, 4) for v in self.samples_ms],
            "mean_ms": round(self.mean_ms, 4),
            "p95_ms": round(self.p95_ms, 4),
            "min_ms": round(self.min_ms, 4),
            "max_ms": round(self.max_ms, 4),
            "std_ms": round(self.std_ms, 4),
            "fps": round(self.fps, 3),
        }


def summarise(samples_ms: Sequence[float]) -> Timing:
    values = [float(v) for v in samples_ms]
    if not values:
        raise ValueError("no timing samples")
    mean = float(np.mean(values))
    return Timing(
        samples_ms=values,
        mean_ms=mean,
        p95_ms=float(np.percentile(values, 95.0)),
        min_ms=float(np.min(values)),
        max_ms=float(np.max(values)),
        std_ms=float(np.std(values, ddof=0)),
        fps=1000.0 / mean if mean > 0.0 else 0.0,
    )


def time_call(func: Callable[[], Any], *, warmup: int = 1, trials: int = 5) -> Timing:
    """Run ``warmup`` untimed calls, then ``trials`` timed calls."""
    for _ in range(max(0, warmup)):
        func()
    samples: list[float] = []
    for _ in range(trials):
        started = time.perf_counter()
        func()
        samples.append((time.perf_counter() - started) * 1000.0)
    return summarise(samples)


def to_float01(rgb_uint8: np.ndarray) -> np.ndarray:
    return np.asarray(rgb_uint8, dtype=np.float64) / 255.0


def to_uint8(rgb01: np.ndarray) -> np.ndarray:
    return np.clip(np.rint(np.asarray(rgb01, dtype=np.float64) * 255.0), 0, 255).astype(
        np.uint8
    )


def bake_timed(params: Any, size: int, *, repeats: int = 3) -> tuple[np.ndarray, float]:
    """Bake a LUT and return (samples, best-of-N bake time in ms)."""
    from baker.color_transform import bake_lut

    best = float("inf")
    samples: np.ndarray | None = None
    for _ in range(max(1, repeats)):
        started = time.perf_counter()
        samples = bake_lut(params, size)
        best = min(best, (time.perf_counter() - started) * 1000.0)
    assert samples is not None
    return samples, best


def cube_cache_path(tag: str, size: int) -> Path:
    return WORK_DIR / f"{tag}_{size}.cube"


def ensure_cube(params: Any, size: int, tag: str) -> Path:
    """Export (and cache) a .cube file for the C++ worker."""
    from baker.cube_writer import export_params_lut

    path = cube_cache_path(tag, size)
    if path.is_file() and path.stat().st_size > 0:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    export_params_lut(params, 1.0, path, size)
    return path


def _command_first_line(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return ""
    for line in completed.stdout.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def environment_info() -> dict[str, Any]:
    """Capture everything a reader needs to reproduce the numbers."""
    import matplotlib

    import baker.params as params_mod

    gpu = _command_first_line(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "(Get-CimInstance Win32_VideoController | "
            "Select-Object -First 1 -ExpandProperty Name)",
        ]
    )
    cpu = _command_first_line(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "(Get-CimInstance Win32_Processor | "
            "Select-Object -First 1 -ExpandProperty Name)",
        ]
    )
    from app import paths

    worker = paths.worker_path()
    worker_stat = worker.stat() if worker.is_file() else None
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_model": cpu or platform.processor() or "unknown",
        "gpu_model": gpu or "unknown",
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "matplotlib": matplotlib.__version__,
        "pillow": _pillow_version(),
        "algorithm_version": params_mod.ALGORITHM_VERSION,
        "worker_path": str(worker.relative_to(ROOT)) if worker.is_file() else str(worker),
        "worker_bytes": worker_stat.st_size if worker_stat else 0,
        "worker_mtime": (
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(worker_stat.st_mtime))
            if worker_stat
            else ""
        ),
        "results_dir": str(RESULTS_DIR.relative_to(ROOT)),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "gl_context": "OpenGL 3.3 Core (offscreen FBO, Mesa software rasteriser)",
    }


def _pillow_version() -> str:
    try:
        import PIL

        return str(PIL.__version__)
    except Exception:
        return "unknown"


def reset_work_dir() -> None:
    shutil.rmtree(WORK_DIR, ignore_errors=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)
    path.write_text(text, encoding="utf-8")


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serialisable: {type(value)!r}")


__all__ = [
    "RESULTS_DIR",
    "ROOT",
    "Timing",
    "WORK_DIR",
    "bake_timed",
    "cube_cache_path",
    "dump_json",
    "ensure_cube",
    "environment_info",
    "reset_work_dir",
    "summarise",
    "time_call",
    "to_float01",
    "to_uint8",
]
