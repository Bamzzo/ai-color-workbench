from __future__ import annotations

import base64
import hashlib
import tempfile
import uuid
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ai.offline import OfflineProvider
from ai.provider import AIError, Proposal, build_provider, load_config
from baker.params import list_presets
from baker.color_transform import bake_lut
from baker.cube_reader import CubeError, load_cube
from baker.params import ColorParams, ParamError, validate_params_document
from app import histogram, image_io, paths, video_io
from app.pipeline import RenderPipeline, RenderSnapshot

from . import envelope
from .job_runner import JobRecord, JobStatus, create_job, get_job, run_job
from .media_store import content_url, get, save_upload

# uvicorn --reload 不会自动读取 .env：必须在构建 AI provider 之前显式加载。
# override=False 保证进程环境变量（CI / 容器）优先于文件。
try:
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=paths.ENV_FILE, override=False)
except Exception:  # pragma: no cover - 缺少 .env 或未安装 dotenv 时静默跳过
    pass

app = FastAPI(title="ai_color_app API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://127.0.0.1",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_pipeline: RenderPipeline | None = None


def get_pipeline() -> RenderPipeline:
    global _pipeline
    if _pipeline is None:
        paths.ensure_runtime()
        _pipeline = RenderPipeline()
    return _pipeline


class ParamsValidateBody(BaseModel):
    params: dict[str, Any]


class AiProposeBody(BaseModel):
    intent: str
    current_params: dict[str, Any] = Field(default_factory=dict)
    allow_offline_fallback: bool = True


class LutBakeBody(BaseModel):
    params: dict[str, Any]
    size: int = 33


class HistogramBody(BaseModel):
    media_id: str | None = None
    image_b64: str | None = None


class ExportImageBody(BaseModel):
    media_id: str
    params: dict[str, Any]
    strength: float = 1.0
    format: str = "PNG"


class ExportVideoBody(BaseModel):
    media_id: str
    params: dict[str, Any]
    strength: float = 1.0


class ExportLutBody(BaseModel):
    params: dict[str, Any]
    strength: float = 1.0


def _lut_payload(
    samples: np.ndarray,
    size: int,
    domain_min: Sequence[float] = (0.0, 0.0, 0.0),
    domain_max: Sequence[float] = (1.0, 1.0, 1.0),
) -> dict[str, Any]:
    raw = np.ascontiguousarray(samples, dtype=np.float32).tobytes()
    digest = hashlib.sha256(raw).hexdigest()
    return {
        "lut_id": digest,
        "size": int(size),
        "domain_min": [float(v) for v in domain_min],
        "domain_max": [float(v) for v in domain_max],
        "data_b64": base64.standard_b64encode(raw).decode("ascii"),
    }


def _proposal_dict(proposal: Proposal) -> dict[str, Any]:
    return {
        "params": proposal.params.as_dict(),
        "summary": proposal.summary,
        "source": proposal.source,
        "provider": proposal.provider,
        "model": proposal.model,
    }


@app.get("/api/presets")
def api_presets() -> dict[str, Any]:
    items = [
        {"key": key, "label": label, "params": params.as_dict()}
        for key, label, params in list_presets()
    ]
    return envelope.ok(items)


@app.post("/api/params/validate")
def api_validate(body: ParamsValidateBody) -> dict[str, Any]:
    try:
        document = {
            "schema_version": "2.0",
            "algorithm_version": "sdr-srgb-v2",
            "params": body.params,
        }
        normalized = validate_params_document(document)
    except ParamError as exc:
        return envelope.err(4001, exc.message)
    return envelope.ok({"params": normalized})


@app.post("/api/ai/propose")
def api_ai_propose(body: AiProposeBody) -> dict[str, Any]:
    intent = (body.intent or "").strip()
    if not intent:
        return envelope.err(4002, "intent 不能为空")
    try:
        current = ColorParams.from_dict(body.current_params)
    except ParamError as exc:
        return envelope.err(4003, exc.message)

    try:
        provider = build_provider(load_config())
        proposal = provider.generate(intent, current)
        return envelope.ok(_proposal_dict(proposal))
    except AIError as exc:
        if not body.allow_offline_fallback:
            return envelope.err(4004, exc.message)
        try:
            proposal = OfflineProvider().generate(intent, current)
            return envelope.ok(_proposal_dict(proposal))
        except Exception as offline_exc:
            return envelope.err(4005, str(offline_exc))


@app.post("/api/lut/bake")
def api_lut_bake(body: LutBakeBody) -> dict[str, Any]:
    size = int(body.size)
    if size not in (33, 65):
        return envelope.err(4010, "size 必须为 33 或 65")
    try:
        params = ColorParams.from_dict(body.params)
    except ParamError as exc:
        return envelope.err(4011, exc.message)
    samples = bake_lut(params, size)
    expected_rows = size**3
    if samples.shape != (expected_rows, 3):
        return envelope.err(4012, f"LUT 形状异常: {samples.shape}")
    return envelope.ok(_lut_payload(samples, size))


@app.post("/api/lut/upload_cube")
async def api_lut_upload_cube(file: UploadFile = File(...)) -> dict[str, Any]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".cube":
        return envelope.err(4020, "需要 .cube 文件")
    try:
        data = await file.read()
    except Exception as exc:
        return envelope.err(4021, f"读取失败: {exc}")
    with tempfile.NamedTemporaryFile(suffix=".cube", delete=False) as tmp:
        tmp.write(data)
        temp_path = Path(tmp.name)
    try:
        lut = load_cube(temp_path)
    except CubeError as exc:
        temp_path.unlink(missing_ok=True)
        return envelope.err(4022, exc.message)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
    samples = np.asarray(lut.samples, dtype=np.float32)
    return envelope.ok(
        {
            **_lut_payload(samples, lut.size, lut.domain_min, lut.domain_max),
            "title": lut.title,
            "sha256": lut.sha256,
        }
    )


@app.post("/api/media/upload")
async def api_media_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    try:
        data = await file.read()
    except Exception as exc:
        return envelope.err(4030, f"读取失败: {exc}")
    if not data:
        return envelope.err(4031, "空文件")
    try:
        record = save_upload(file.filename or "upload", data)
    except Exception as exc:
        return envelope.err(4032, str(exc))
    payload = {
        "media_id": record.media_id,
        "kind": record.kind,
        "width": record.width,
        "height": record.height,
        "content_url": content_url(record.media_id),
    }
    if record.duration_s is not None:
        payload["duration_s"] = record.duration_s
        payload["fps"] = record.fps
    return envelope.ok(payload)


@app.get("/api/media/{media_id}/content")
def api_media_content(media_id: str) -> FileResponse:
    record = get(media_id)
    if record is None or not record.path.is_file():
        return envelope.err(4040, "media 不存在", http_status=404)  # type: ignore[return-value]
    return FileResponse(record.path, filename=record.path.name)


@app.post("/api/histogram")
def api_histogram(body: HistogramBody) -> dict[str, Any]:
    from PIL import Image
    import io

    image = None
    if body.image_b64:
        try:
            raw = base64.standard_b64decode(body.image_b64)
            image = Image.open(io.BytesIO(raw))
        except Exception as exc:
            return envelope.err(4041, f"无法解码 image_b64: {exc}")
    elif body.media_id:
        record = get(body.media_id)
        if record is None:
            return envelope.err(4042, "media_id 不存在")
        if record.kind != "image":
            return envelope.err(4043, "video 请先抽帧或使用 image_b64")
        image = image_io.load_source_image(record.path).image
    else:
        return envelope.err(4044, "需要 media_id 或 image_b64")
    hist = histogram.compute_histogram(image)
    return envelope.ok(
        {
            "r": hist.rgb[0].tolist(),
            "g": hist.rgb[1].tolist(),
            "b": hist.rgb[2].tolist(),
            "luma": hist.luma.tolist(),
            "clip_low": hist.clip_low,
            "clip_high": hist.clip_high,
        }
    )


def _build_snapshot(
    media_id: str,
    params: dict[str, Any],
    strength: float,
) -> tuple[RenderSnapshot | None, str | None]:
    record = get(media_id)
    if record is None:
        return None, "media_id 不存在"
    try:
        cp = ColorParams.from_dict(params)
    except ParamError as exc:
        return None, exc.message
    if record.kind == "image":
        source = image_io.load_source_image(record.path)
        pipeline = get_pipeline()
        preview, scaled, _ = pipeline.prepare_preview(source)
        doc_id = f"api-{media_id[:12]}"
        snapshot = RenderSnapshot(
            document_id=doc_id,
            revision=1,
            source=source,
            preview=preview,
            params=cp,
            strength=float(strength),
            mode="params",
            external_lut=None,
        )
        return snapshot, None
    return None, "视频导出请使用 /api/export/video"


@app.post("/api/export/image")
def api_export_image(body: ExportImageBody) -> dict[str, Any]:
    snapshot, error = _build_snapshot(body.media_id, body.params, body.strength)
    if error:
        return envelope.err(4050, error)
    assert snapshot is not None
    fmt = body.format.upper()
    if fmt not in ("PNG", "JPEG", "JPG"):
        return envelope.err(4051, "format 仅支持 PNG 或 JPEG")
    job_id = create_job("export-image")
    out_dir = paths.CACHE / "api_export" / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".jpg" if fmt in ("JPEG", "JPG") else ".png"
    target = out_dir / f"graded{suffix}"

    def task(report) -> dict[str, Any]:
        report(0.1)
        result = get_pipeline().export_image(snapshot, target, fmt)
        report(1.0)
        return {
            "path": str(result.path),
            "width": result.width,
            "height": result.height,
            "detail": result.detail,
        }

    run_job(job_id, task)
    return envelope.ok({"job_id": job_id})


@app.post("/api/export/video")
def api_export_video(body: ExportVideoBody) -> dict[str, Any]:
    record = get(body.media_id)
    if record is None:
        return envelope.err(4060, "media_id 不存在")
    if record.kind != "video":
        return envelope.err(4061, "需要视频 media_id")
    try:
        cp = ColorParams.from_dict(body.params)
    except ParamError as exc:
        return envelope.err(4062, exc.message)

    info = video_io.probe(record.path)
    frame_path = paths.VIDEO_CACHE / f"api-{body.media_id}-0.png"
    video_io.extract_frame(record.path, 0.0, frame_path, info=info)
    source = image_io.load_source_image(frame_path)
    pipeline = get_pipeline()
    preview, _scaled, _ = pipeline.prepare_preview(source)
    snapshot = RenderSnapshot(
        document_id=f"api-v-{body.media_id[:10]}",
        revision=1,
        source=source,
        preview=preview,
        params=cp,
        strength=float(body.strength),
        mode="params",
        external_lut=None,
    )
    job_id = create_job("export-video")
    out_dir = paths.CACHE / "api_export" / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "graded.mp4"

    def task(report) -> dict[str, Any]:
        report(0.05)
        cube = out_dir / "export.cube"
        pipeline.export_lut(snapshot, cube)
        report(0.2)
        out = video_io.export_graded(
            info.path,
            cube,
            target,
            info=info,
            on_progress=lambda p: report(0.2 + 0.75 * p),
        )
        cube.unlink(missing_ok=True)
        report(1.0)
        return {"path": str(out)}

    run_job(job_id, task)
    return envelope.ok({"job_id": job_id})


_LUT_VERIFY_FIXTURE = paths.ROOT / "runtime" / "test-fixtures" / "pattern.png"
_LUT_VERIFY_SIZE = 16


def _synthetic_verify_source() -> "image_io.SourceImage":
    """Build a 16×16 in-memory source for LUT export verification.

    ``export_lut`` only reads ``params`` / ``strength`` / ``mode``; the source is
    a placeholder that ``prepare_preview`` needs in order to build a snapshot.
    A synthetic ramp keeps the export working when the test fixtures directory
    is absent (e.g. a clean deployment), without shipping binary assets.
    """
    from PIL import Image

    size = _LUT_VERIFY_SIZE
    ramp = np.linspace(0.0, 255.0, size, dtype=np.float32)
    rgba = np.empty((size, size, 4), dtype=np.uint8)
    rgba[..., 0] = np.clip(np.rint(ramp), 0, 255).astype(np.uint8)[None, :]
    rgba[..., 1] = np.clip(np.rint(ramp), 0, 255).astype(np.uint8)[:, None]
    rgba[..., 2] = np.clip(np.rint(ramp)[None, :] * 0.5 + ramp[:, None] * 0.5, 0, 255).astype(
        np.uint8
    )
    rgba[..., 3] = 255
    return image_io.SourceImage(
        path=paths.CACHE / f"lut-verify-{size}.png",
        fingerprint=f"lut-verify-{size}",
        width=size,
        height=size,
        image=Image.fromarray(rgba, mode="RGBA"),
        icc_action="synthetic-srgb",
        notes=["LUT 导出校验用合成图，未读取磁盘素材"],
        container="SYNTHETIC",
    )


def _lut_verify_source() -> "image_io.SourceImage":
    """Prefer the test fixture (bit-identical to previous runs), else synthesize."""
    if _LUT_VERIFY_FIXTURE.is_file():
        try:
            return image_io.load_source_image(_LUT_VERIFY_FIXTURE)
        except image_io.ImageError:
            pass
    return _synthetic_verify_source()


@app.post("/api/export/lut")
def api_export_lut(body: ExportLutBody) -> dict[str, Any]:
    try:
        cp = ColorParams.from_dict(body.params)
    except ParamError as exc:
        return envelope.err(4070, exc.message)

    # LUT 导出只依赖参数数学；夹具缺失时用内存合成图补齐 snapshot 上下文。
    source = _lut_verify_source()
    pipeline = get_pipeline()
    preview, _, _ = pipeline.prepare_preview(source)
    snapshot = RenderSnapshot(
        document_id="api-lut",
        revision=1,
        source=source,
        preview=preview,
        params=cp,
        strength=float(body.strength),
        mode="params",
        external_lut=None,
    )
    job_id = create_job("export-lut")
    out_dir = paths.CACHE / "api_export" / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "export.cube"

    def task(report) -> dict[str, Any]:
        report(0.2)
        result = pipeline.export_lut(snapshot, target)
        report(1.0)
        return {
            "path": str(result.path),
            "detail": result.detail,
            "warning": result.warning,
        }

    run_job(job_id, task)
    return envelope.ok({"job_id": job_id})


@app.get("/api/jobs/{job_id}")
def api_job_status(job_id: str) -> dict[str, Any]:
    record = get_job(job_id)
    if record is None:
        return envelope.err(4080, "job 不存在", http_status=404)
    data = {
        "job_id": record.job_id,
        "kind": record.kind,
        "status": record.status.value,
        "progress": record.progress,
        "message": record.message,
        "result_path": record.result_path,
        "error": record.error,
        "detail": record.detail,
    }
    if record.status == JobStatus.DONE and record.result_path:
        data["download_url"] = f"/api/jobs/{job_id}/download"
    return envelope.ok(data)


@app.get("/api/jobs/{job_id}/download")
def api_job_download(job_id: str) -> FileResponse:
    record = get_job(job_id)
    if record is None or not record.result_path:
        return envelope.err(4081, "无可下载文件", http_status=404)  # type: ignore[return-value]
    path = Path(record.result_path)
    if not path.is_file():
        return envelope.err(4082, "文件已丢失", http_status=404)  # type: ignore[return-value]
    return FileResponse(path, filename=path.name)


@app.websocket("/ws/jobs/{job_id}")
async def ws_job(websocket: WebSocket, job_id: str) -> None:
    await websocket.accept()
    try:
        while True:
            record = get_job(job_id)
            if record is None:
                await websocket.send_json(
                    {"code": 4080, "message": "job 不存在", "data": None}
                )
                break
            await websocket.send_json(
                envelope.ok(
                    {
                        "status": record.status.value,
                        "progress": record.progress,
                        "result_path": record.result_path,
                        "error": record.error,
                    }
                )
            )
            if record.status in (
                JobStatus.DONE,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            ):
                break
            import asyncio

            await asyncio.sleep(0.25)
    except WebSocketDisconnect:
        return