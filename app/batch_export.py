"""Worker adapter: run one batch item through the existing export paths.

The batch runner knows nothing about images, videos, engines or ffmpeg; it only
calls ``worker(snapshot, cancel, report)``. This module is that worker.

Every item is decoded, rendered and released inside one call, so memory does not
accumulate across a long queue. The only shared state is the render pipeline
(engine client and disk caches), which is exactly what the single-item UI uses.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from baker.cube_reader import CubeError, load_cube

from . import image_io, paths, video_io
from .batch import BatchCancelled, BatchTaskSnapshot, MediaKind
from .pipeline import RenderPipeline, RenderSnapshot

LOGGER = logging.getLogger(__name__)

IMAGE_JPEG_SUFFIXES = (".jpg", ".jpeg")


class BatchExportWorker:
    """Serial worker for batch items, image or video."""

    def __init__(
        self,
        pipeline: RenderPipeline,
        *,
        video_work_dir: Path | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.video_work_dir = Path(video_work_dir or paths.VIDEO_CACHE)

    def __call__(
        self,
        snapshot: BatchTaskSnapshot,
        cancel,
        report,
    ) -> Path:
        if cancel.is_set():
            raise BatchCancelled()
        report(0.02)
        if snapshot.kind is MediaKind.VIDEO:
            return self._video(snapshot, cancel, report)
        return self._image(snapshot, cancel, report)

    # -- stills --------------------------------------------------------

    def _image(self, snapshot: BatchTaskSnapshot, cancel, report) -> Path:
        target = snapshot.target
        fmt = "JPEG" if target.suffix.lower() in IMAGE_JPEG_SUFFIXES else "PNG"
        source = image_io.load_source_image(snapshot.source)
        try:
            preview, _scaled, _path = self.pipeline.prepare_preview(source)
            if cancel.is_set():
                raise BatchCancelled()
            report(0.10)

            external = self._load_external(snapshot, cancel)
            render = RenderSnapshot(
                document_id=f"batch-{snapshot.batch_id}-{snapshot.item_id}",
                revision=snapshot.token,
                source=source,
                preview=preview,
                params=snapshot.params,
                strength=snapshot.strength,
                mode="external_lut" if external is not None else "params",
                external_lut=external,
            )
            report(0.25)
            result = self.pipeline.export_image(
                render,
                target,
                fmt,
                snapshot.image_quality,
                cancel,
            )
            report(1.0)
            return result.path
        finally:
            # Release this item's decoded pixels before the next one starts.
            try:
                source.image.close()
            except Exception:  # closing a already-closed image is harmless
                pass

    # -- video ---------------------------------------------------------

    def _video(self, snapshot: BatchTaskSnapshot, cancel, report) -> Path:
        info = video_io.probe(snapshot.source)
        if cancel.is_set():
            raise BatchCancelled()
        report(0.05)

        external = self._load_external(snapshot, cancel)
        self.video_work_dir.mkdir(parents=True, exist_ok=True)
        cube = self.video_work_dir / (
            f"batch-{snapshot.token}-{time.monotonic_ns()}.cube"
        )
        try:
            self.pipeline.bake_video_cube(
                snapshot.params,
                snapshot.strength,
                cube,
                external_lut=external,
                cancel_event=cancel,
            )
            if cancel.is_set():
                raise BatchCancelled()
            report(0.15)
            out = video_io.export_graded(
                snapshot.source,
                cube,
                snapshot.target,
                info=info,
                quality=snapshot.video_quality,
                preset=snapshot.video_preset,
                on_progress=lambda value: report(0.15 + 0.85 * float(value)),
                cancel_event=cancel,
            )
            report(1.0)
            return out
        finally:
            # The cube is an internal artifact; never leave it in the cache.
            cube.unlink(missing_ok=True)

    # -- shared --------------------------------------------------------

    def _load_external(self, snapshot: BatchTaskSnapshot, cancel):
        if snapshot.lut_path is None:
            return None
        if cancel.is_set():
            raise BatchCancelled()
        try:
            return load_cube(snapshot.lut_path)
        except CubeError as exc:
            raise CubeError(
                "LUT_PARSE_ERROR",
                f"无法读取批次 LUT {snapshot.lut_path.name}: {exc}",
            ) from exc
