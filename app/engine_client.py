"""File-protocol client for the isolated ARM64 render worker."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from . import image_io, paths


class EngineError(RuntimeError):
    def __init__(self, code: str, message: str, stage: str = "engine") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.stage = stage


@dataclass
class RenderOutcome:
    image: Image.Image
    output_path: Path
    metrics: dict[str, Any]
    job_dir: Path
    stdout: str
    stderr: str


class EngineClient:
    def __init__(self, worker: Path | None = None, timeout: float = 30.0) -> None:
        self.worker = Path(worker) if worker else paths.worker_path()
        self.timeout = float(timeout)

    def render(
        self,
        input_rgba: Path,
        lut_path: Path,
        strength: float,
        *,
        document_id: str,
        revision: int,
        job_id: str | None = None,
        cancel_event: threading.Event | None = None,
        timeout: float | None = None,
        keep_job_dir: bool = False,
    ) -> RenderOutcome:
        job_dir = paths.new_job_dir()
        job_id = job_id or job_dir.name
        request_path = job_dir / "request.json"
        response_path = job_dir / "response.json"
        output_path = job_dir / "output.rgba"

        request = {
            "protocol_version": "1.0",
            "job_id": job_id,
            "document_id": document_id,
            "revision": int(revision),
            "operation": "render",
            "input_rgba": str(Path(input_rgba).resolve()),
            "lut_path": str(Path(lut_path).resolve()),
            "strength": round(float(strength), 6),
            "output_rgba": str(output_path.resolve()),
        }
        try:
            request_path.write_text(
                json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            raise EngineError(
                "EXPORT_IO", f"无法写入渲染请求: {exc}", "request"
            ) from exc

        cmd = [
            str(self.worker),
            "--request",
            str(request_path),
            "--response",
            str(response_path),
            "--shaders",
            str(paths.SHADER_DIR),
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proc = subprocess.Popen(
                cmd,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
            )
        except OSError as exc:
            raise EngineError(
                "PROCESS_CRASHED", f"无法启动渲染进程: {exc}", "process"
            ) from exc

        deadline = time.monotonic() + float(timeout or self.timeout)
        stdout = b""
        stderr = b""
        cancelled = False
        timed_out = False
        while True:
            try:
                stdout, stderr = proc.communicate(timeout=0.08)
                break
            except subprocess.TimeoutExpired:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    proc.kill()
                    try:
                        stdout, stderr = proc.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                    break
                if time.monotonic() > deadline:
                    timed_out = True
                    proc.kill()
                    try:
                        stdout, stderr = proc.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                    break

        stdout_text = (stdout or b"").decode("utf-8", errors="replace")
        stderr_text = (stderr or b"").decode("utf-8", errors="replace")

        if cancelled:
            # Cancelling is routine (a newer preview superseded this one), so the
            # directory holds nothing worth keeping. Crashes and GPU failures do
            # keep theirs for diagnosis.
            shutil.rmtree(job_dir, ignore_errors=True)
            raise EngineError("CANCELLED", "渲染已取消", "process")
        if timed_out:
            raise EngineError("TIMEOUT", "渲染超时", "process")

        response = self._read_response(response_path, job_id, document_id, revision)
        if response is None:
            detail = stderr_text.strip() or stdout_text.strip() or "无响应文件"
            raise EngineError(
                "PROCESS_CRASHED",
                f"渲染进程未提交结果 (exit={proc.returncode}): {detail}",
                "process",
            )
        if response.get("status") != "ok":
            error = response.get("error") or {}
            raise EngineError(
                str(error.get("code") or "GPU_RENDER_FAILED"),
                str(error.get("message") or "渲染失败"),
                str(error.get("stage") or "gpu"),
            )

        resolved = Path(str(response.get("output_rgba") or "")).resolve()
        try:
            resolved.relative_to(job_dir.resolve())
        except ValueError as exc:
            raise EngineError(
                "INVALID_REQUEST", "响应输出路径不在任务目录内", "protocol"
            ) from exc
        if not resolved.is_file():
            raise EngineError("EXPORT_IO", "响应声明的输出文件不存在", "io")
        try:
            image = image_io.read_rgba_bridge(resolved)
        except image_io.ImageError as exc:
            raise EngineError(exc.code, exc.message, "io") from exc

        metrics = response.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}
        outcome = RenderOutcome(
            image=image,
            output_path=resolved,
            metrics=metrics,
            job_dir=job_dir,
            stdout=stdout_text,
            stderr=stderr_text,
        )
        if not keep_job_dir:
            # The pixels are in memory and the text streams are captured, so the
            # job directory has no further use. Editing a slider for a few
            # minutes otherwise leaves hundreds of megabytes of output.rgba
            # behind until the next startup sweep. Failures keep the directory
            # for diagnosis; keep_job_dir=True does the same on demand.
            shutil.rmtree(job_dir, ignore_errors=True)
        return outcome

    def _read_response(
        self, path: Path, job_id: str, document_id: str, revision: int
    ) -> dict[str, Any] | None:
        for _ in range(5):
            if path.is_file():
                break
            time.sleep(0.02)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EngineError(
                "INVALID_REQUEST", f"响应文件无法解析: {exc}", "protocol"
            ) from exc
        if not isinstance(data, dict):
            raise EngineError("INVALID_REQUEST", "响应根节点不是对象", "protocol")
        if data.get("protocol_version") != "1.0":
            raise EngineError("UNSUPPORTED_VERSION", "响应协议版本不支持", "protocol")
        if data.get("job_id") != job_id:
            raise EngineError("INVALID_REQUEST", "响应 job_id 不匹配", "protocol")
        if data.get("document_id") != document_id:
            raise EngineError("INVALID_REQUEST", "响应 document_id 不匹配", "protocol")
        if data.get("revision") != int(revision):
            raise EngineError("INVALID_REQUEST", "响应 revision 不匹配", "protocol")
        return data
