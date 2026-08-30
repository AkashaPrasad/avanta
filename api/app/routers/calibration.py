from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from api.app.db import SessionLocal
from api.app.models.records import CalibrationRecord

router = APIRouter()


@router.get("/calibration")
def get_calibration() -> dict[str, Any]:
    with SessionLocal() as session:
        row = session.scalars(
            select(CalibrationRecord).order_by(CalibrationRecord.created_at.desc()).limit(1)
        ).first()
        if row is None:
            raise HTTPException(
                404,
                "No calibration has been computed on this deployment. Run "
                "scripts/make_synthetic_set.py to generate a validation set and fit the "
                "isotonic mapping.",
            )
        return {
            "id": row.id,
            "n_cases": row.n_cases,
            "brier_score": row.brier,
            "expected_calibration_error": row.ece,
            "bins": row.bins,
            "isotonic": row.isotonic,
            "notes": row.notes,
            "computed_at": row.created_at.isoformat() if row.created_at else None,
        }
