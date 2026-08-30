"""AVANTA API.

Turns a radar image of an oil slick into a ranked, calibrated, evidence-backed
attribution -- with an explicit "unknown source" hypothesis so it can decline to
accuse anyone when the evidence does not support it.
"""
from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.app import state
from api.app.db import create_all
from api.app.routers import (
    attribution,
    calibration,
    candidates,
    dossier,
    handoff,
    health,
    jobs_router,
    scenes,
    tiles,
)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("avanta")

# The Indian EEZ, which is the area the live AIS collector subscribes to.
DEFAULT_AIS_BBOX = [68.0, 6.0, 90.0, 24.0]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    create_all()
    if state.collector.configured:
        await state.collector.start(DEFAULT_AIS_BBOX)
        log.info("live AIS collector started on %s", DEFAULT_AIS_BBOX)
    else:
        log.warning("AISSTREAM_API_KEY not set: live AIS is unavailable, fixtures will be used")
    yield
    await state.collector.stop()


app = FastAPI(
    title="AVANTA",
    version="1.0.0",
    description=(
        "Attribution of marine oil discharges from Sentinel-1 SAR, AIS and forward "
        "oil-drift simulation. Forward integration only: reverse drift of a "
        "diffusing, weathering substance is ill-posed."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

PREFIX = "/api/v1"
for module in (health, scenes, tiles, candidates, attribution, dossier, calibration, handoff, jobs_router):
    app.include_router(module.router, prefix=PREFIX, tags=[module.__name__.rsplit(".", 1)[-1]])


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "AVANTA",
        "docs": "/docs",
        "health": f"{PREFIX}/health",
    }
