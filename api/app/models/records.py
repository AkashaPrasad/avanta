"""Persisted records.

Only what has to survive a restart is stored: scenes, detections, candidate
sets, attribution runs, jobs and dossiers. Rasters and netCDF subsets stay on
disk under DATA_DIR and are referenced by path and hash -- putting a 12 MB
GeoTIFF in a row would make the database the bottleneck for no benefit.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.app.models.base import Base, TimestampMixin


class Scene(Base, TimestampMixin):
    __tablename__ = "scenes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scenario: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bbox: Mapped[list[float]] = mapped_column(JSON)
    t_from: Mapped[str] = mapped_column(String(40))
    t_to: Mapped[str] = mapped_column(String(40))
    acquired_utc: Mapped[str | None] = mapped_column(String(40), nullable=True)
    product_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    raster_path: Mapped[str] = mapped_column(Text)
    raster_sha256: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="NEW")
    wind_gate: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    detections: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    provenance: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    currents_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    wind_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    runs: Mapped[list[AttributionRunRow]] = relationship(back_populates="scene")


class CandidateSet(Base, TimestampMixin):
    __tablename__ = "candidate_sets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id"))
    n_considered: Mapped[int] = mapped_column(Integer, default=0)
    n_kept: Mapped[int] = mapped_column(Integer, default=0)
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    tracks: Mapped[dict[str, Any]] = mapped_column(JSON)
    provenance: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class AttributionRunRow(Base, TimestampMixin):
    __tablename__ = "attribution_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id"))
    candidate_set_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    simulations: Mapped[dict[str, Any]] = mapped_column(JSON)
    provenance: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    runtime_s: Mapped[float] = mapped_column(Float, default=0.0)

    scene: Mapped[Scene] = relationship(back_populates="runs")


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    stage: Mapped[str] = mapped_column(String(200), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    log: Mapped[list[str]] = mapped_column(JSON, default=list)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CalibrationRecord(Base, TimestampMixin):
    __tablename__ = "calibration"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    n_cases: Mapped[int] = mapped_column(Integer)
    brier: Mapped[float] = mapped_column(Float)
    ece: Mapped[float] = mapped_column(Float)
    bins: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    isotonic: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
