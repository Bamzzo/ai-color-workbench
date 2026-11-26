"""Preview/export pipeline shared by the Tk UI and the test harness."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from PIL import Image

from baker.color_transform import bake_lut, resample_effect
from baker.cube_reader import CubeLut
from baker.cube_writer import (
    CubeWriteError,
    export_params_lut,
    verify_exported_effect,
    write_cube,
)
from baker.params import ColorParams, lut_cache_key

from . import image_io, paths
from .engine_client import EngineClient, EngineError, RenderOutcome
from .image_io import SourceImage
from .state import AppState

PREVIEW_LONG_SIDE = 1280
FULL_CACHE = paths.CACHE / "full"
EXTERNAL_CACHE = paths.CACHE / "external"


@dataclass(frozen=True)
class RenderSnapshot:
    document_id: str
    revision: int
    source: SourceImage
    preview: Image.Image
    params: ColorParams
    strength: float
    mode: str
    external_lut: CubeLut | None

    @classmethod
    def from_state(cls, state: AppState) -> "RenderSnapshot":
        if state.source is None or state.preview_image is None:
            raise ValueError("没有已载入的图像")
        return cls(
            document_id=state.document_id,
            revision=state.revision,
            source=state.source,
            preview=state.preview_image,
            params=state.params,
            strength=state.strength,
            mode=state.mode,
            external_lut=state.external_lut,
        )


@dataclass
class PreviewResult:
    image: Image.Image
    metrics: dict[str, Any]
    document_id: str
    revision: int
    elapsed_ms: float


@dataclass
class ExportResult:
    path: Path
    width: int
    height: int
    revision: int
    detail: str = ""
    warning: str = ""


class RenderPipeline:
    def __init__(self, engine: EngineClient | None = None) -> None:
        self.engine = engine or EngineClient()
        FULL_CACHE.mkdir(parents=True, exist_ok=True)
        EXTERNAL_CACHE.mkdir(parents=True, exist_ok=True)

    # ----- document preparation -------------------------------------
    def prepare_preview(self, source: SourceImage) -> tuple[Image.Image, bool, Path]:
        preview, scaled = image_io.make_preview(source.image, PREVIEW_LONG_SIDE)
        target = paths.preview_cache_path(source.fingerprint, PREVIEW_LONG_SIDE)
        expected = 24 + preview.width * preview.height * 4
        if not target.is_file() or target.stat().st_size != expected:
            image_io.write_rgba_bridge(target, preview)
        return preview, scaled, target

    def preview_rgba_path(self, source: SourceImage) -> Path:
        target = paths.preview_cache_path(source.fingerprint, PREVIEW_LONG_SIDE)
        if not target.is_file():
            self.prepare_preview(source)
        return target

    # ----- LUT helpers ----------------------------------------------
    def _params_preview_lut(self, params: ColorParams) -> Path:
        key = lut_cache_key(params, 33, (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), 1.0)
        target = paths.lut_cache_path(key)
        if target.is_file():
            return target
        samples = bake_lut(params, 33)
        write_cube(target, 33, samples, title="ai_color_app preview", verify=False)
        # Every new slider position bakes a ~1 MB text LUT, so the cache grows
        # faster than the preview images do; evict old entries as we go.
        paths.prune_cache()
        return target

    def _preview_lut(self, snapshot: RenderSnapshot) -> tuple[Path, int]:
        if snapshot.mode == "external_lut":
            if snapshot.external_lut is None:
                raise EngineError("LUT_PARSE_ERROR", "外部 LUT 已丢失", "lut")
            return Path(snapshot.external_lut.path), snapshot.external_lut.size
        return self._params_preview_lut(snapshot.params), 33

    def _full_rgba_path(self, source: SourceImage) -> Path:
        target = FULL_CACHE / (
            f"{source.fingerprint[:40]}-{source.width}x{source.height}.rgba"
        )
        if not target.is_file():
            image_io.write_rgba_bridge(target, source.image)
            # A single 40 MP image costs ~160 MB here, so opening a handful of
            # large files would otherwise pin gigabytes until the next startup.
            paths.prune_cache()
        return target

    # ----- render operations ----------------------------------------
    def render_preview(
        self, snapshot: RenderSnapshot, cancel_event: threading.Event | None = None
    ) -> PreviewResult:
        import time

        started = time.monotonic()
        input_path = self.preview_rgba_path(snapshot.source)
        lut_path, _ = self._preview_lut(snapshot)
        outcome: RenderOutcome = self.engine.render(
            input_path,
            lut_path,
            snapshot.strength,
            document_id=snapshot.document_id,
            revision=snapshot.revision,
            cancel_event=cancel_event,
        )
        return PreviewResult(
            image=outcome.image,
            metrics=outcome.metrics,
            document_id=snapshot.document_id,
            revision=snapshot.revision,
            elapsed_ms=(time.monotonic() - started) * 1000.0,
        )

    def export_image(
        self,
        snapshot: RenderSnapshot,
        target: Path,
        fmt: str,
        quality: int = 95,
        cancel_event: threading.Event | None = None,
    ) -> ExportResult:
        import time

        started = time.monotonic()
        fmt = fmt.upper()
        if fmt not in ("PNG", "JPEG", "JPG"):
            raise image_io.ImageError("EXPORT_IO", "仅支持 PNG/JPEG 导出")
        if image_io.is_same_file(target, snapshot.source.path):
            raise image_io.ImageError("EXPORT_IO", "拒绝覆盖源文件")
        input_path = self._full_rgba_path(snapshot.source)
        lut_path, _ = self._preview_lut(snapshot)
        outcome = self.engine.render(
            input_path,
            lut_path,
            snapshot.strength,
            document_id=snapshot.document_id,
            revision=snapshot.revision,
            cancel_event=cancel_event,
            timeout=120.0,
        )
        if outcome.image.size != (snapshot.source.width, snapshot.source.height):
            raise image_io.ImageError(
                "EXPORT_IO", "导出渲染尺寸与规范化图像不一致"
            )
        if fmt == "PNG":
            image_io.save_png_atomic(outcome.image, target)
        else:
            image_io.save_jpeg_atomic(outcome.image, Path(target), quality=quality)
        elapsed = (time.monotonic() - started) * 1000.0
        return ExportResult(
            path=Path(target),
            width=outcome.image.width,
            height=outcome.image.height,
            revision=snapshot.revision,
            detail=f"{fmt} · {elapsed:.0f} ms",
        )

    def export_lut(
        self,
        snapshot: RenderSnapshot,
        target: Path,
        cancel_event: threading.Event | None = None,
    ) -> ExportResult:
        if target.suffix.lower() != ".cube":
            raise CubeWriteError("EXPORT_IO", "导出 LUT 需要 .cube 扩展名")
        if cancel_event is not None and cancel_event.is_set():
            raise EngineError("CANCELLED", "导出已取消", "export")

        best = None
        for size in (33, 65):
            if cancel_event is not None and cancel_event.is_set():
                raise EngineError("CANCELLED", "导出已取消", "export")
            if snapshot.mode == "external_lut":
                lut = snapshot.external_lut
                if lut is None:
                    raise CubeWriteError("LUT_PARSE_ERROR", "外部 LUT 已丢失")
                samples = resample_effect(
                    lut.samples,
                    lut.size,
                    size,
                    snapshot.strength,
                    lut.domain_min,
                    lut.domain_max,
                )
                exported = write_cube(
                    target,
                    size,
                    samples,
                    title="ai_color_app external effect",
                )
                diff = verify_exported_effect(
                    exported,
                    source_samples=lut.samples,
                    source_size=lut.size,
                    source_domain_min=lut.domain_min,
                    source_domain_max=lut.domain_max,
                    strength=snapshot.strength,
                )
            else:
                exported = export_params_lut(
                    snapshot.params,
                    snapshot.strength,
                    target,
                    size=size,
                )
                diff = verify_exported_effect(
                    exported,
                    params=snapshot.params,
                    strength=snapshot.strength,
                )
            best = (size, diff, exported)
            if diff <= 2.0:
                break

        assert best is not None
        size, diff, _exported = best
        warning = ""
        if diff > 2.0:
            sidecar = Path(str(target) + ".strength.json")
            try:
                sidecar.write_text(
                    json.dumps(
                        {
                            "strength": snapshot.strength,
                            "max_8bit_diff": round(diff, 4),
                            "lut_size": size,
                            "note": "导出 LUT 与当前效果的最大差异超过 2/255，无法声明逐点等价",
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            except OSError:
                pass
            warning = (
                f"导出 LUT 的 8-bit 最大差异为 {diff:.2f}，超过 2；"
                "已附 strength sidecar，不能声称与当前效果逐点等价"
            )
        return ExportResult(
            path=Path(target),
            width=size,
            height=size,
            revision=snapshot.revision,
            detail=f"{size}³ · max diff {diff:.2f}/255",
            warning=warning,
        )

    def bake_video_cube(
        self,
        params: ColorParams,
        strength: float,
        target: Path,
        *,
        external_lut: CubeLut | None = None,
        cancel_event: threading.Event | None = None,
        size: int = 33,
    ) -> Path:
        """Write a strength-baked .cube for video encoding.

        Video encoding applies the LUT one-to-one, so the strength slider has to
        be baked in. This is the preview-grade bake, not the user-facing LUT
        export (which additionally verifies equivalence and may escalate size).
        """
        if cancel_event is not None and cancel_event.is_set():
            raise EngineError("CANCELLED", "导出已取消", "export")
        if external_lut is not None:
            samples = resample_effect(
                external_lut.samples,
                external_lut.size,
                size,
                strength,
                external_lut.domain_min,
                external_lut.domain_max,
            )
            write_cube(target, size, samples, title="ai_color_app batch video")
        else:
            export_params_lut(params, strength, Path(target), size=size)
        return Path(target)

    def copy_external_lut(self, lut: CubeLut) -> CubeLut:
        target = EXTERNAL_CACHE / f"{lut.sha256}.cube"
        if not target.is_file():
            import os
            import shutil

            tmp = target.with_name(target.name + ".tmp")
            try:
                shutil.copyfile(lut.path, tmp)
                os.replace(tmp, target)
            except OSError as exc:
                tmp.unlink(missing_ok=True)
                raise CubeWriteError(
                    "EXPORT_IO", f"无法复制外部 LUT: {exc}"
                ) from exc
        return replace(lut, path=target)
