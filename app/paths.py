"""Application paths and runtime directory management."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
JOBS = RUNTIME / "jobs"
CACHE = RUNTIME / "cache"
LUT_CACHE = CACHE / "lut"
PREVIEW_CACHE = CACHE / "preview"
VIDEO_CACHE = CACHE / "video"
LOGS = RUNTIME / "logs"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
SHADER_DIR = ROOT / "shaders"


class PathError(RuntimeError):
    pass


def ensure_runtime() -> None:
    for directory in (RUNTIME, JOBS, CACHE, LUT_CACHE, PREVIEW_CACHE, VIDEO_CACHE, LOGS):
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PathError(f"无法创建运行目录 {directory}: {exc}") from exc
    probe = RUNTIME / ".write-probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise PathError(f"运行目录不可写: {exc}") from exc


def worker_path() -> Path:
    override = os.environ.get("AI_COLOR_WORKER")
    candidates = []
    if override:
        candidates.append(Path(override))
    candidates.extend(
        [
            ROOT / "build-arm64" / "Debug" / "render_worker.exe",
            ROOT / "build-arm64" / "Release" / "render_worker.exe",
            ROOT / "build" / "Debug" / "render_worker.exe",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise PathError(
        "找不到 render_worker.exe；请先构建 ARM64 目标，或设置 AI_COLOR_WORKER"
    )


def check_worker() -> tuple[bool, str]:
    try:
        path = worker_path()
    except PathError as exc:
        return False, str(exc)
    shaders = path.parent / "shaders"
    if not (shaders / "grade.frag").is_file():
        return False, f"worker 缺少 shader 目录: {shaders}"
    return True, str(path)


def new_job_dir(prefix: str = "job") -> Path:
    import uuid

    directory = JOBS / f"{prefix}-{uuid.uuid4().hex}"
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def cleanup_old_jobs(max_age_hours: float = 24.0) -> int:
    """Remove only our own job directories older than the cutoff."""
    cutoff = time.time() - max_age_hours * 3600.0
    removed = 0
    try:
        entries = list(JOBS.iterdir())
    except OSError:
        return 0
    for entry in entries:
        if not entry.is_dir() or not entry.name.startswith("job-"):
            continue
        try:
            if entry.stat().st_mtime >= cutoff:
                continue
            shutil.rmtree(entry, ignore_errors=False)
            removed += 1
        except OSError:
            continue
    return removed


CACHE_LIMIT_BYTES = 320 * 1024 * 1024
# Never evict something written this recently: a render or export that is
# already running resolves its input paths at process start, and the four
# sub-caches are read from the worker thread.
CACHE_MIN_AGE_SECONDS = 600.0


def _walk_files(base: Path):
    """Yield ``(path, stat)`` for every file under ``base``, tolerating errors."""
    stack = [base]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as scan:
                children = list(scan)
        except OSError:
            continue
        for entry in children:
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                    continue
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            yield Path(entry.path), info


def cache_usage(root: Path | None = None) -> tuple[int, int]:
    """Return (bytes, files) currently stored under the cache directory."""
    base = Path(root) if root is not None else CACHE
    total = 0
    count = 0
    for _path, info in _walk_files(base):
        total += info.st_size
        count += 1
    return total, count


def prune_cache(
    max_bytes: int = CACHE_LIMIT_BYTES,
    min_age_seconds: float = CACHE_MIN_AGE_SECONDS,
    root: Path | None = None,
) -> tuple[int, int]:
    """Drop least-recently-used cache files until the directory fits the cap.

    Deleting a cache entry only costs a rebuild; sources and exported files are
    never touched. Files younger than ``min_age_seconds`` are skipped so an
    in-flight render cannot lose its input, and unreadable entries are ignored.
    """
    base = Path(root) if root is not None else CACHE
    total, _count = cache_usage(base)
    if total <= max_bytes:
        return 0, 0

    cutoff = time.time() - float(min_age_seconds)
    candidates = [
        (info.st_mtime, info.st_size, path)
        for path, info in _walk_files(base)
        if info.st_mtime <= cutoff
    ]

    candidates.sort()  # oldest first
    removed = 0
    freed = 0
    for _mtime, size, path in candidates:
        if total - freed <= max_bytes:
            break
        try:
            path.unlink()
        except OSError:
            continue
        removed += 1
        freed += size
    return removed, freed


def preview_cache_path(fingerprint: str, long_side: int) -> Path:
    return PREVIEW_CACHE / f"{fingerprint[:32]}-{long_side}.rgba"


def lut_cache_path(key: str) -> Path:
    return LUT_CACHE / f"{key}.cube"
