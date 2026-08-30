"""INCOIS OOSA / NOAA GNOME handoff.

The integration thesis in one endpoint. INCOIS already runs an operational oil
spill trajectory system (OOSA v4.0, built on GNOME, domain 60-100°E / 0-25°N)
that the Coast Guard is trained on. It answers "where will this oil go" and it
cannot start without a release point and time -- which, in a routine discharge,
nobody has. AVANTA produces exactly that.

This emits the release specification in the shape GNOME needs. It is a handoff
format, not a live integration, and the README says so.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from api.app.db import SessionLocal
from api.app.models.records import AttributionRunRow
from api.app.schemas.requests import HandoffRequest

router = APIRouter()

# INCOIS OOSA operational domain.
OOSA_DOMAIN = {"lon_min": 60.0, "lon_max": 100.0, "lat_min": 0.0, "lat_max": 25.0}


@router.post("/handoff/oosa")
def oosa(request: HandoffRequest) -> dict[str, Any]:
    with SessionLocal() as session:
        row = session.get(AttributionRunRow, request.run_id)
        if row is None:
            raise HTTPException(404, f"No attribution run '{request.run_id}'.")
        result = row.result

    candidate = next((c for c in result.get("candidates", []) if c["mmsi"] == request.mmsi), None)
    if candidate is None:
        raise HTTPException(404, f"No candidate '{request.mmsi}' in run '{request.run_id}'.")

    release = candidate["release"]
    seed = candidate.get("seed", {})
    track = (result.get("tracks") or {}).get(request.mmsi, {})
    coords: list[list[float]] = []
    for feature in track.get("features", []):
        if (feature.get("properties") or {}).get("segment") == "transmitted":
            coords = feature["geometry"]["coordinates"]
            break
    start_point = coords[0] if coords else None
    end_point = coords[-1] if coords else None

    in_domain = bool(
        start_point
        and OOSA_DOMAIN["lon_min"] <= start_point[0] <= OOSA_DOMAIN["lon_max"]
        and OOSA_DOMAIN["lat_min"] <= start_point[1] <= OOSA_DOMAIN["lat_max"]
    )

    entry = next(
        (e for e in (result.get("posterior") or {}).get("entries", []) if e["hypothesis_id"] == request.mmsi),
        None,
    )

    return {
        "format": "INCOIS OOSA / NOAA GNOME release specification",
        "format_version": "1.0",
        "note": (
            "This is a handoff format, not a live connection to INCOIS. It supplies the "
            "release point, time, duration, rate and oil properties that OOSA currently has "
            "to be given by hand."
        ),
        "release": {
            "geometry_type": "moving_line_source",
            "start_position": {"lon": start_point[0], "lat": start_point[1]} if start_point else None,
            "end_position": {"lon": end_point[0], "lat": end_point[1]} if end_point else None,
            "line_vertices": coords,
            "start_time_utc": release["t_start"],
            "end_time_utc": release["t_end"],
            "duration_hours": release["duration_hours"],
            "discharge_rate_m3_per_h": release["rate_m3_per_h"],
            "total_volume_m3": release["volume_m3"],
        },
        "substance": {
            "oil_type": release["oil_type"],
            "database": "NOAA ADIOS, via OpenDrift OpenOil",
            "note": "Density and viscosity are taken from the ADIOS record for this oil type.",
        },
        "attribution": {
            "mmsi": request.mmsi,
            "vessel_name": candidate.get("name"),
            "posterior_probability": entry["probability"] if entry else None,
            "probability_unknown_source": (result.get("posterior") or {}).get("p_null"),
        },
        "domain_check": {
            "oosa_domain": OOSA_DOMAIN,
            "release_inside_domain": in_domain,
            "message": (
                "Release point is inside the INCOIS OOSA operational domain."
                if in_domain
                else "Release point is outside the INCOIS OOSA domain (60–100°E, 0–25°N); "
                "OOSA would not forecast this release."
            ),
        },
        "seed_summary": seed,
    }
