from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from api.app import jobs

router = APIRouter()


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, f"No job '{job_id}'.")
    return job


@router.websocket("/jobs/{job_id}/stream")
async def stream_job(websocket: WebSocket, job_id: str) -> None:
    """Named-stage progress, so a long run shows what it is doing rather than an
    indeterminate bar."""
    await websocket.accept()
    try:
        while True:
            job = jobs.get(job_id)
            if job is None:
                await websocket.send_json({"error": f"No job '{job_id}'."})
                break
            await websocket.send_json(job)
            if job["status"] in ("succeeded", "failed"):
                break
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return
    finally:
        try:
            await websocket.close()
        except RuntimeError:
            pass
