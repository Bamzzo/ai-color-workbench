from __future__ import annotations

import json
import shutil
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app import image_io, paths, video_io

MediaKind = Literal["image", "video"]

API_MEDIA_ROOT = paths.CACHE / "api_media"
INDEX_PATH = API_MEDIA_ROOT / "index.json"
INDEX_VERSION = 1


@dataclass
class MediaRecord:
    media_id: str
    kind: MediaKind
    path: Path
    width: int
    height: int
    duration_s: float | None = None
    fps: float | None = None


_REGISTRY: dict[str, MediaRecord] = {}
_LOCK = threading.Lock()


def _record_to_json(record: MediaRecord) -> dict[str, Any]:
    return {
        "media_id": record.media_id,
        "kind": record.kind,
        "path": str(record.path),
        "width": int(record.width),
        "height": int(record.height),
        "duration_s": record.duration_s,
        "fps": record.fps,
    }


def _optional_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _record_from_json(raw: Any) -> MediaRecord | None:
    """Rebuild a record, dropping entries whose file is gone or malformed."""
    if not isinstance(raw, dict):
        return None
    media_id = raw.get("media_id")
    kind = raw.get("kind")
    raw_path = raw.get("path")
    if not isinstance(media_id, str) or not media_id:
        return None
    if kind not in ("image", "video"):
        return None
    if not isinstance(raw_path, str) or not raw_path:
        return None
    try:
        width = int(raw.get("width") or 0)
        height = int(raw.get("height") or 0)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    path = Path(raw_path)
    if not path.is_file():
        return None
    return MediaRecord(
        media_id=media_id,
        kind="video" if kind == "video" else "image",
        path=path,
        width=width,
        height=height,
        duration_s=_optional_float(raw.get("duration_s")),
        fps=_optional_float(raw.get("fps")),
    )


def _write_index() -> None:
    """Persist the registry so a backend restart does not orphan uploads.

    The index is a convenience cache layered on top of the files themselves: a
    failed write must never fail an upload that already succeeded on disk.
    """
    try:
        API_MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": INDEX_VERSION,
            "records": [_record_to_json(record) for record in _REGISTRY.values()],
        }
        tmp = INDEX_PATH.with_name(INDEX_PATH.name + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(INDEX_PATH)
    except (OSError, TypeError, ValueError):
        pass


def load_index() -> int:
    """Restore records from disk; returns how many survived validation."""
    try:
        raw = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    records = raw.get("records") if isinstance(raw, dict) else None
    if not isinstance(records, list):
        return 0
    restored = 0
    with _LOCK:
        for item in records:
            record = _record_from_json(item)
            if record is not None:
                _REGISTRY[record.media_id] = record
                restored += 1
    return restored


def register(record: MediaRecord) -> None:
    with _LOCK:
        _REGISTRY[record.media_id] = record
        _write_index()


def get(media_id: str) -> MediaRecord | None:
    with _LOCK:
        return _REGISTRY.get(media_id)


def save_upload(
    filename: str,
    data: bytes,
) -> MediaRecord:
    API_MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
    media_id = uuid.uuid4().hex
    directory = API_MEDIA_ROOT / media_id
    directory.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name or "upload.bin"
    target = directory / safe_name
    target.write_bytes(data)

    suffix = target.suffix.lower()
    if suffix in video_io.VIDEO_SUFFIXES:
        info = video_io.probe(target)
        record = MediaRecord(
            media_id=media_id,
            kind="video",
            path=target,
            width=info.display_width,
            height=info.display_height,
            duration_s=info.duration_s,
            fps=info.fps,
        )
    else:
        source = image_io.load_source_image(target)
        record = MediaRecord(
            media_id=media_id,
            kind="image",
            path=target,
            width=source.width,
            height=source.height,
        )
    register(record)
    return record


def content_url(media_id: str, *, base: str = "") -> str:
    prefix = base.rstrip("/")
    path = f"/api/media/{media_id}/content"
    return f"{prefix}{path}" if prefix else path


def clear_registry_for_tests() -> None:
    with _LOCK:
        _REGISTRY.clear()
    # rmtree 同时清掉 index.json，避免上一条用例的索引污染下一条
    if API_MEDIA_ROOT.is_dir():
        shutil.rmtree(API_MEDIA_ROOT, ignore_errors=True)


# 模块加载即恢复上一次运行留下的媒体记录，让 uvicorn 重启后旧 media_id 仍然可用。
load_index()