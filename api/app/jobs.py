"""Background job execution.

A deliberate simplification of the brief's Redis + Celery design. Every job here
is a single CPU-bound pipeline run owned by one request; there is no fan-out, no
retry semantics worth the name, and no second consumer. A thread pool plus a row
in Postgres does everything a broker would do for this workload, and it removes
an entire service from the deployment -- which matters because the same
docker-compose file is the on-premise deliverable.

Progress is written to the job row as it goes, so the UI can stream a named
stage rather than an indeterminate spinner.
"""
from __future__ import annotations

import logging
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from api.app.db import SessionLocal
from api.app.models.records import Job

log = logging.getLogger(__name__)

# One worker: the science is numpy/OpenDrift bound and running two attribution
# jobs at once on a 2-vCPU box makes both slower than running them in order.
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="avanta-job")


class JobHandle:
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id

    def update(self, *, stage: str | None = None, progress: float | None = None, log_line: str | None = None) -> None:
        with SessionLocal() as session:
            job = session.get(Job, self.job_id)
            if job is None:
                return
            if stage is not None:
                job.stage = stage[:200]
            if progress is not None:
                job.progress = max(0.0, min(1.0, float(progress)))
            if log_line is not None:
                job.log = [*(job.log or []), f"{datetime.now(timezone.utc).isoformat()} {log_line}"][-200:]
            session.commit()


def submit(kind: str, fn: Callable[[JobHandle], dict[str, Any]]) -> str:
    job_id = uuid.uuid4().hex
    with SessionLocal() as session:
        session.add(Job(id=job_id, kind=kind, status="queued", stage="queued", progress=0.0, log=[]))
        session.commit()

    def runner() -> None:
        handle = JobHandle(job_id)
        with SessionLocal() as session:
            job = session.get(Job, job_id)
            if job is not None:
                job.status = "running"
                job.stage = "starting"
                session.commit()
        try:
            result = fn(handle)
            with SessionLocal() as session:
                job = session.get(Job, job_id)
                if job is not None:
                    job.status = "succeeded"
                    job.stage = "done"
                    job.progress = 1.0
                    job.result = result
                    job.finished_at = datetime.now(timezone.utc)
                    session.commit()
        except Exception as exc:  # noqa: BLE001
            log.exception("job %s (%s) failed", job_id, kind)
            with SessionLocal() as session:
                job = session.get(Job, job_id)
                if job is not None:
                    job.status = "failed"
                    job.stage = "failed"
                    # The real reason goes to the client. A demo that hides why
                    # it broke is worse than one that visibly broke.
                    job.error = f"{type(exc).__name__}: {exc}"
                    job.log = [*(job.log or []), traceback.format_exc()[-4000:]]
                    job.finished_at = datetime.now(timezone.utc)
                    session.commit()

    _EXECUTOR.submit(runner)
    return job_id


def get(job_id: str) -> dict[str, Any] | None:
    with SessionLocal() as session:
        job = session.get(Job, job_id)
        if job is None:
            return None
        return {
            "job_id": job.id,
            "kind": job.kind,
            "status": job.status,
            "stage": job.stage,
            "progress": round(job.progress, 4),
            "result": job.result,
            "error": job.error,
            "log": (job.log or [])[-25:],
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        }
