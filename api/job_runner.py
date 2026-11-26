from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class JobRecord:
    job_id: str
    kind: str
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    message: str = ""
    result_path: str | None = None
    error: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


_JOBS: dict[str, JobRecord] = {}
_LOCK = threading.Lock()


def create_job(kind: str) -> str:
    job_id = uuid.uuid4().hex
    with _LOCK:
        _JOBS[job_id] = JobRecord(job_id=job_id, kind=kind)
    return job_id


def get_job(job_id: str) -> JobRecord | None:
    with _LOCK:
        return _JOBS.get(job_id)


def update_job(job_id: str, **kwargs: Any) -> None:
    with _LOCK:
        record = _JOBS.get(job_id)
        if record is None:
            return
        for key, value in kwargs.items():
            setattr(record, key, value)


def run_job(
    job_id: str,
    fn: Callable[[Callable[[float], None]], Any],
) -> None:
    def report(progress: float) -> None:
        update_job(
            job_id,
            progress=max(0.0, min(1.0, float(progress))),
            status=JobStatus.RUNNING,
        )

    def worker() -> None:
        update_job(job_id, status=JobStatus.RUNNING, progress=0.01)
        try:
            result = fn(report)
            if isinstance(result, dict):
                path = result.get("path")
                detail = {k: v for k, v in result.items() if k != "path"}
                update_job(
                    job_id,
                    status=JobStatus.DONE,
                    progress=1.0,
                    result_path=str(path) if path else None,
                    detail=detail,
                )
            else:
                update_job(
                    job_id,
                    status=JobStatus.DONE,
                    progress=1.0,
                    result_path=str(result) if result else None,
                )
        except Exception as exc:
            update_job(
                job_id,
                status=JobStatus.FAILED,
                progress=1.0,
                error=str(exc),
                message=str(exc),
            )

    threading.Thread(target=worker, name=f"api-job-{job_id[:8]}", daemon=True).start()


def clear_jobs_for_tests() -> None:
    with _LOCK:
        _JOBS.clear()