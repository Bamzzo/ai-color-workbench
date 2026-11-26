"""Video support: probe, frame extraction and LUT-graded re-encode via ffmpeg.

The app grades in the encoded sRGB domain and produces a .cube; ffmpeg's
``lut3d`` filter applies exactly that cube to every frame, so the video export
and the still preview share one colour definition rather than two.

Video is a P1 addition next to the still-image path: ffmpeg is an external
dependency, and its absence only disables the video features.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

LOGGER = logging.getLogger("ai_color.video")

VIDEO_SUFFIXES = (
    ".mp4",
    ".mov",
    ".m4v",
    ".mkv",
    ".webm",
    ".avi",
    ".wmv",
    ".mts",
    ".m2ts",
)

# Frames are decoded to stills for grading; cap the long side so an 8K clip
# cannot blow past the still-image pixel budget.
MAX_FRAME_SIDE = 8192

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class VideoError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    duration_s: float
    fps: float
    width: int
    height: int
    codec: str
    color_space: str
    has_audio: bool
    rotation: int = 0

    @property
    def display_width(self) -> int:
        return self.height if self.rotation % 180 == 90 else self.width

    @property
    def display_height(self) -> int:
        return self.width if self.rotation % 180 == 90 else self.height

    def timecode(self, seconds: float) -> str:
        seconds = max(0.0, float(seconds))
        minutes, rest = divmod(seconds, 60.0)
        return f"{int(minutes):02d}:{rest:05.2f}"


def ffmpeg_bin() -> str | None:
    override = os.environ.get("AI_COLOR_FFMPEG") or os.environ.get("FFMPEG_PATH")
    if override:
        candidate = Path(override)
        return str(candidate) if candidate.is_file() else None
    found = shutil.which("ffmpeg")
    return found


def ffprobe_bin() -> str | None:
    override = os.environ.get("AI_COLOR_FFPROBE") or os.environ.get("FFPROBE_PATH")
    if override:
        candidate = Path(override)
        return str(candidate) if candidate.is_file() else None
    found = shutil.which("ffprobe")
    return found


def availability() -> tuple[bool, str]:
    ffmpeg, ffprobe = ffmpeg_bin(), ffprobe_bin()
    if not ffmpeg:
        return False, "未找到 ffmpeg；视频功能需要 ffmpeg（可设 AI_COLOR_FFMPEG）"
    if not ffprobe:
        return False, "未找到 ffprobe；请安装完整 ffmpeg 发行版"
    return True, ffmpeg


def _run(cmd: list[str], timeout: float = 60.0) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
    except FileNotFoundError as exc:
        raise VideoError("VIDEO_UNAVAILABLE", f"无法启动 {cmd[0]}：{exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise VideoError("VIDEO_TIMEOUT", f"{cmd[0]} 超时") from exc


def _parse_fraction(text: str | None) -> float:
    if not text:
        return 0.0
    if "/" in text:
        num, _, den = text.partition("/")
        try:
            numerator = float(num)
            denominator = float(den) or 1.0
        except ValueError:
            return 0.0
        return numerator / denominator
    try:
        return float(text)
    except ValueError:
        return 0.0


def probe(path: str | Path) -> VideoInfo:
    file_path = Path(path)
    ffprobe = ffprobe_bin()
    if not ffprobe:
        raise VideoError("VIDEO_UNAVAILABLE", availability()[1])
    result = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(file_path),
        ]
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise VideoError(
            "VIDEO_INVALID",
            "无法读取视频信息：" + (detail[-1] if detail else f"exit={result.returncode}"),
        )
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise VideoError("VIDEO_INVALID", f"ffprobe 输出无法解析: {exc}") from exc

    streams = payload.get("streams") or []
    video = next(
        (s for s in streams if s.get("codec_type") == "video"), None
    )
    if video is None:
        raise VideoError("VIDEO_INVALID", "该文件不含视频轨道")
    audio = any(s.get("codec_type") == "audio" for s in streams)

    duration = 0.0
    for source in (payload.get("format") or {}, video):
        try:
            duration = float(source.get("duration") or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        if duration > 0:
            break
    if duration <= 0:
        raise VideoError("VIDEO_INVALID", "无法确定视频时长")

    rotation = 0
    for side_data in video.get("side_data_list") or []:
        if "rotation" in side_data:
            try:
                rotation = int(float(side_data["rotation"])) % 360
            except (TypeError, ValueError):
                rotation = 0
            break
    else:
        try:
            rotation = int(video.get("tags", {}).get("rotate", 0)) % 360
        except (TypeError, ValueError):
            rotation = 0

    fps = _parse_fraction(video.get("avg_frame_rate")) or _parse_fraction(
        video.get("r_frame_rate")
    )
    return VideoInfo(
        path=file_path,
        duration_s=duration,
        fps=fps,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        codec=str(video.get("codec_name") or "?"),
        color_space=str(video.get("color_space") or "unknown"),
        has_audio=audio,
        rotation=rotation,
    )


def frame_cache_path(fingerprint: str, time_s: float, long_side: int) -> str:
    """Stable cache name for one video frame."""
    stamp = f"{time_s:.3f}".replace(".", "_")
    return f"{fingerprint[:32]}-{stamp}-{long_side}.png"


def extract_frame(
    path: str | Path,
    time_s: float,
    target: str | Path,
    *,
    info: VideoInfo | None = None,
    long_side: int = MAX_FRAME_SIDE,
) -> Path:
    """Decode one frame to PNG (display orientation, sRGB-ish RGB)."""
    ffmpeg = ffmpeg_bin()
    if not ffmpeg:
        raise VideoError("VIDEO_UNAVAILABLE", availability()[1])
    source = Path(path)
    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    meta = info or probe(source)
    # Seeking exactly to the end yields nothing: back off by one frame (or
    # 50 ms for very low frame rates) so the last frame is still reachable.
    tail = max(1.0 / max(meta.fps, 1.0), 0.05)
    clamped = max(0.0, min(float(time_s), max(0.0, meta.duration_s - tail)))

    matrix = "bt709" if meta.color_space in ("bt709", "unknown", "") else meta.color_space
    scale = (
        f"scale=w='min(iw,{long_side})':h='min(ih,{long_side})'"
        ":force_original_aspect_ratio=decrease:flags=lanczos"
    )
    filters = f"{scale},scale=in_color_matrix={matrix}:out_color_matrix=bt709,format=rgb24"

    def attempt(at: float) -> subprocess.CompletedProcess:
        cmd = [
            ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-ss",
            f"{at:.3f}",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-vf",
            filters,
            "-pix_fmt",
            "rgb24",
            str(target_path),
        ]
        return _run(cmd)

    result = attempt(clamped)
    if (result.returncode != 0 or not target_path.is_file()) and clamped > 0.0:
        # Some containers report a longer duration than they can seek to.
        result = attempt(0.0)
    if result.returncode != 0 or not target_path.is_file():
        detail = (result.stderr or "").strip().splitlines()
        raise VideoError(
            "VIDEO_FRAME_FAILED",
            "无法解码视频帧：" + (detail[-1] if detail else f"exit={result.returncode}"),
        )
    return target_path


def _filter_path(path: Path) -> str:
    """Escape a Windows path for use inside an ffmpeg filtergraph value."""
    text = Path(path).resolve().as_posix()
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def export_graded(
    path: str | Path,
    cube_path: str | Path,
    target: str | Path,
    *,
    info: VideoInfo | None = None,
    quality: int = 18,
    preset: str = "medium",
    on_progress: Callable[[float], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> Path:
    """Re-encode the whole clip through the exported 3D LUT.

    Progress is reported as 0..1 from ffmpeg's ``-progress`` stream; cancelling
    kills the encoder and leaves no partial file behind.
    """
    ffmpeg = ffmpeg_bin()
    if not ffmpeg:
        raise VideoError("VIDEO_UNAVAILABLE", availability()[1])
    source = Path(path)
    target_path = Path(target)
    meta = info or probe(source)
    if target_path.suffix.lower() not in (".mp4", ".mov", ".mkv", ".webm"):
        target_path = target_path.with_suffix(".mp4")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    # The suffix must stay last: ffmpeg picks the muxer from the extension.
    partial = target_path.with_name(
        f"{target_path.stem}.partial{target_path.suffix}"
    )
    partial.unlink(missing_ok=True)

    matrix = "bt709" if meta.color_space in ("bt709", "unknown", "") else meta.color_space
    filters = (
        f"scale=in_color_matrix={matrix}:out_color_matrix=bt709,"
        f"format=rgb24,lut3d='{_filter_path(Path(cube_path))}',"
        "format=yuv420p"
    )
    cmd = [
        ffmpeg,
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        filters,
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(int(quality)),
        "-pix_fmt",
        "yuv420p",
        "-colorspace",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
        "-nostats",
        str(partial),
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
    except OSError as exc:
        raise VideoError("VIDEO_UNAVAILABLE", f"无法启动 ffmpeg：{exc}") from exc

    cancelled = False
    assert proc.stdout is not None
    time_re = re.compile(r"out_time_(?:ms|us)=(\d+)")
    timed_out = False
    stderr = ""
    try:
        for line in proc.stdout:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                proc.kill()
                break
            match = time_re.search(line)
            if match and on_progress is not None and meta.duration_s > 0:
                done = int(match.group(1))
                # ffmpeg emits out_time_ms but the value is microseconds.
                seconds = done / 1_000_000.0
                on_progress(max(0.0, min(1.0, seconds / meta.duration_s)))
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
    finally:
        if proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - stuck child
                LOGGER.warning("ffmpeg did not exit after kill")
        # Drain and close both pipes; leaving them to GC leaks file handles and
        # trips ResourceWarning in the test suite.
        if proc.stderr is not None:
            try:
                stderr = proc.stderr.read() or ""
            except (OSError, ValueError):
                stderr = ""
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        proc.stdout = None
        proc.stderr = None

    if timed_out:
        partial.unlink(missing_ok=True)
        raise VideoError("VIDEO_TIMEOUT", "ffmpeg 未在预期时间内退出")

    if cancelled:
        partial.unlink(missing_ok=True)
        raise VideoError("CANCELLED", "视频导出已取消")

    if proc.returncode != 0 or not partial.is_file():
        partial.unlink(missing_ok=True)
        detail = stderr.strip().splitlines()
        raise VideoError(
            "VIDEO_ENCODE_FAILED",
            "视频编码失败：" + (detail[-1] if detail else f"exit={proc.returncode}"),
        )

    os.replace(partial, target_path)
    if on_progress is not None:
        on_progress(1.0)
    return target_path


def content_fingerprint(path: Path) -> str:
    """Same content hash used for still images, so caches stay consistent."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def quick_fingerprint(path: Path) -> str:
    """Cheap identity for cache names: size, mtime and the leading megabyte.

    Hashing a multi-gigabyte clip on the UI thread would stall the window, and
    frame caches only need to avoid collisions between different files.
    """
    file_path = Path(path)
    stat = file_path.stat()
    digest = hashlib.sha256()
    digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode("ascii"))
    with file_path.open("rb") as handle:
        digest.update(handle.read(1024 * 1024))
    return digest.hexdigest()
