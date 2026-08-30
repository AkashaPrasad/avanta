"""Stage A: geometric candidate prefilter.

Running a Monte Carlo oil drift simulation for every vessel in a 200 km box is
far too slow for an interactive console. This stage costs microseconds per
vessel and exists to decide which handful deserve the physics.

It is emphatically NOT a backward drift model. Nothing here integrates
backwards. `t_feasible` asks a strictly weaker question -- could oil released
anywhere on this track have reached the slick within the elapsed time, given a
generous upper bound on surface drift speed -- which is a cone, not a
trajectory, and is stable precisely because it makes no claim about the path.

Every term is returned with its value so the UI can show why 47 vessels became
6, rather than presenting a shortlist as an oracle.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np

from core.ais.tracks import Track, haversine_km
from core.config import settings


@dataclass
class PrefilterTerm:
    name: str
    value: float
    score: float
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": round(self.value, 4),
            "score": round(self.score, 4),
            "explanation": self.explanation,
        }


@dataclass
class PrefilterResult:
    mmsi: str
    name: str | None
    ship_type: str
    is_dark: bool
    total_score: float
    kept: bool
    terms: list[PrefilterTerm]
    closest_approach_km: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "mmsi": self.mmsi,
            "name": self.name,
            "ship_type": self.ship_type,
            "is_dark": self.is_dark,
            "total_score": round(self.total_score, 4),
            "kept": self.kept,
            "closest_approach_km": round(self.closest_approach_km, 3),
            "terms": [t.to_dict() for t in self.terms],
        }


@dataclass
class SlickGeometry:
    """The observed slick reduced to what the prefilter needs: a centroid, a
    principal axis, and an extent."""

    centroid_lon: float
    centroid_lat: float
    major_axis_deg: float
    major_axis_km: float
    area_km2: float
    acquired_utc: datetime


def _perp_distance_km(track: Track, slick: SlickGeometry) -> float:
    """Shortest distance from any point on the track to the slick's major axis
    line, which is where a line-source discharge would have been laid down."""
    lon, lat = track.lonlats()
    lat0 = slick.centroid_lat
    kx = 111.320 * math.cos(math.radians(lat0))
    x = (lon - slick.centroid_lon) * kx
    y = (lat - slick.centroid_lat) * 110.574
    theta = math.radians(slick.major_axis_deg)
    # Unit vector along the slick axis (compass bearing -> east/north).
    ax, ay = math.sin(theta), math.cos(theta)
    perp = np.abs(x * ay - y * ax)
    along = np.abs(x * ax + y * ay)
    # Only count points that lie within the slick's own length; a vessel 300 km
    # up the same bearing is not "near the axis" in any useful sense.
    within = along <= max(slick.major_axis_km, 5.0)
    return float(perp[within].min()) if within.any() else float(perp.min())


def _closest_approach_km(track: Track, slick: SlickGeometry) -> float:
    return min(
        haversine_km(f.lon, f.lat, slick.centroid_lon, slick.centroid_lat) for f in track.fixes
    )


def _alignment(track: Track, slick: SlickGeometry) -> float:
    """|cos(course - slick axis)|.

    Highly discriminative: oil laid down by a moving vessel is stretched along
    that vessel's own course, so a slick whose principal axis is perpendicular
    to a candidate's heading is very unlikely to have come from it.
    """
    from core.ais.tracks import course_over_ground

    course = course_over_ground(track.fixes)
    return abs(math.cos(math.radians(course - slick.major_axis_deg)))


def _feasibility(track: Track, slick: SlickGeometry, max_drift_ms: float) -> tuple[float, float]:
    """Is there a release time on this track from which oil could physically
    have reached the slick by the acquisition?

    Returns (score in [0,1], the best implied drift speed in m/s). This is a
    feasibility cone bounded by an upper drift speed, not a reverse trajectory.
    """
    best_ratio = math.inf
    best_speed = math.inf
    for fix in track.fixes:
        elapsed_s = (slick.acquired_utc - fix.t).total_seconds()
        if elapsed_s <= 0:
            continue  # the vessel was there after the image was taken
        distance_m = haversine_km(fix.lon, fix.lat, slick.centroid_lon, slick.centroid_lat) * 1000.0
        required = distance_m / elapsed_s
        if required < best_speed:
            best_speed = required
            best_ratio = required / max_drift_ms
    if not math.isfinite(best_ratio):
        return 0.0, math.inf
    return float(max(0.0, 1.0 - min(1.0, best_ratio))), float(best_speed)


def _upstream(track: Track, slick: SlickGeometry, drift_u: float, drift_v: float) -> float:
    """Is the track on the upwind/upcurrent side of the slick?

    Oil moves with the combined wind and current vector, so a source should lie
    opposite to that vector from the slick. Returns a signed alignment in
    [-1, 1] mapped to [0, 1].
    """
    magnitude = math.hypot(drift_u, drift_v)
    if magnitude < 1e-6:
        return 0.5
    lat0 = slick.centroid_lat
    kx = 111.320 * math.cos(math.radians(lat0))
    best = -1.0
    for fix in track.fixes:
        dx = (fix.lon - slick.centroid_lon) * kx
        dy = (fix.lat - slick.centroid_lat) * 110.574
        norm = math.hypot(dx, dy)
        if norm < 1e-6:
            best = max(best, 1.0)
            continue
        # Positive when the vessel sits opposite the drift direction.
        best = max(best, -(dx * drift_u + dy * drift_v) / (norm * magnitude))
    return float((best + 1.0) / 2.0)


def prefilter(
    tracks: list[Track],
    slick: SlickGeometry,
    *,
    drift_u: float = 0.0,
    drift_v: float = 0.0,
    keep_top_k: int | None = None,
) -> list[PrefilterResult]:
    cfg = settings()["prefilter"]
    k = keep_top_k if keep_top_k is not None else int(cfg["keep_top_k"])
    max_drift = float(cfg["max_drift_speed_ms"])
    radius = float(cfg["search_radius_km"])

    results: list[PrefilterResult] = []
    for track in tracks:
        if not track.fixes:
            continue
        closest = _closest_approach_km(track, slick)
        if closest > radius:
            continue

        d_perp = _perp_distance_km(track, slick)
        perp_score = float(math.exp(-d_perp / 25.0))
        align = _alignment(track, slick)
        feasible, implied = _feasibility(track, slick, max_drift)
        upstream = _upstream(track, slick, drift_u, drift_v)

        terms = [
            PrefilterTerm(
                "d_perp_km",
                d_perp,
                perp_score,
                f"{d_perp:.1f} km from the slick's principal axis. A line-source "
                "discharge is laid down along that axis.",
            ),
            PrefilterTerm(
                "align",
                align,
                align,
                f"|cos(course − slick axis)| = {align:.2f}. Oil released by a moving "
                "vessel is elongated along that vessel's own course.",
            ),
            PrefilterTerm(
                "t_feasible",
                feasible,
                feasible,
                (
                    f"Reaching the slick would require a mean surface drift of "
                    f"{implied:.2f} m/s against an upper bound of {max_drift:.2f} m/s."
                    if math.isfinite(implied)
                    else "No position on this track precedes the acquisition."
                ),
            ),
            PrefilterTerm(
                "upstream",
                upstream,
                upstream,
                f"Track lies {'upstream' if upstream > 0.5 else 'downstream'} of the slick "
                f"given the mean wind and current vector (score {upstream:.2f}).",
            ),
        ]
        # A hard veto: if oil could not physically have got there, no amount of
        # alignment rescues the hypothesis.
        total = 0.0 if feasible <= 0.0 else float(np.mean([t.score for t in terms]))
        results.append(
            PrefilterResult(
                mmsi=track.mmsi,
                name=track.name,
                ship_type=track.ship_type,
                is_dark=track.is_dark,
                total_score=total,
                kept=False,
                terms=terms,
                closest_approach_km=closest,
            )
        )

    results.sort(key=lambda r: r.total_score, reverse=True)
    kept = 0
    for result in results:
        # Every dark contact survives regardless of rank. A vessel that is not
        # transmitting must not be filtered out by a score computed from the
        # data it is withholding.
        if result.is_dark or (kept < k and result.total_score > 0.0):
            result.kept = True
            if not result.is_dark:
                kept += 1
    return results
