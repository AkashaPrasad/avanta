from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BBoxWindow(BaseModel):
    bbox: list[float] = Field(min_length=4, max_length=4)
    t_from: str
    t_to: str


class IngestRequest(BaseModel):
    scenario: str | None = None
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)
    t_from: str | None = None
    t_to: str | None = None
    allow_live: bool = True


class CandidatesRequest(BaseModel):
    scene_id: str
    source: Literal["auto", "live", "fixture"] = "auto"
    keep_top_k: int | None = Field(default=None, ge=1, le=32)


class AttributionRequest(BaseModel):
    scene_id: str
    candidate_ids: list[str] | None = None
    n_per_point: int | None = Field(default=None, ge=5, le=500)
    n_ensemble: int | None = Field(default=None, ge=1, le=32)
    oil_type: str = "GENERIC INTERMEDIATE FUEL OIL 180"


class DossierRequest(BaseModel):
    run_id: str
    mmsi: str
    observer: str = "AVANTA automated analysis, reviewed by duty officer"


class HandoffRequest(BaseModel):
    run_id: str
    mmsi: str
