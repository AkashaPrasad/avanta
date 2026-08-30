"""Behaviour prior features.

Every feature here is computed from data and every one is shown to the analyst
with its raw value, its weight and its signed contribution. None of them is a
verdict on its own -- a tanker steaming slowly at night is not guilty of
anything. Together, weighted by a published config, they say how much the
vessel's *behaviour* raises or lowers the prior odds relative to the others in
the same scene, before the physics is consulted at all.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np

from core.ais.tracks import Track
from core.config import prior_weights


@dataclass
class FeatureValue:
    name: str
    value: float
    weight: float
    contribution: float
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": round(self.value, 4),
            "weight": round(self.weight, 4),
            "contribution": round(self.contribution, 4),
            "explanation": self.explanation,
        }


def solar_elevation_deg(when: datetime, lon: float, lat: float) -> float:
    """NOAA low-precision solar position. Accurate to a fraction of a degree,
    which is far more than is needed to answer 'was it dark'."""
    day = when.timetuple().tm_yday
    hour = when.hour + when.minute / 60.0 + when.second / 3600.0
    gamma = 2 * math.pi / 365.0 * (day - 1 + (hour - 12) / 24.0)
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )
    decl = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )
    time_offset = eqtime + 4 * lon
    true_solar = (hour * 60 + time_offset) % 1440
    hour_angle = math.radians(true_solar / 4 - 180)
    phi = math.radians(lat)
    cos_zenith = math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(hour_angle)
    return math.degrees(math.asin(max(-1.0, min(1.0, cos_zenith))))


def compute(
    track: Track,
    window_start: datetime,
    window_end: datetime,
    *,
    prior_hit_count: int = 0,
    lane_distance_km: float | None = None,
    hours_since_port_call: float | None = None,
    gfw_gap_minutes: float | None = None,
) -> list[FeatureValue]:
    cfg = prior_weights()
    w = cfg["weights"]
    window_minutes = max((window_end - window_start).total_seconds() / 60.0, 1e-6)
    in_window = [f for f in track.fixes if window_start <= f.t <= window_end]
    features: list[FeatureValue] = []

    # --- AIS gap overlapping the estimated release window -------------------
    gap_minutes = sum(g.overlap_minutes(window_start, window_end) for g in track.gaps)
    if gfw_gap_minutes is not None:
        gap_minutes = max(gap_minutes, gfw_gap_minutes)
    gap_fraction = min(1.0, gap_minutes / window_minutes)
    features.append(
        FeatureValue(
            "ais_gap_overlap",
            gap_fraction,
            w["ais_gap_overlap"],
            gap_fraction * w["ais_gap_overlap"],
            f"{gap_minutes:.0f} of {window_minutes:.0f} minutes of the estimated release "
            f"window fall inside an AIS transmission gap.",
        )
    )

    # --- Speed anomaly relative to this vessel's own voyage -----------------
    median = track.median_sog()
    window_speeds = [f.sog_kn for f in in_window if f.sog_kn is not None]
    if median > 0.5 and window_speeds:
        window_median = float(np.median(window_speeds))
        anomaly = max(0.0, min(1.0, (median - window_median) / median))
        note = (
            f"{window_median:.1f} kn during the window against a voyage median of "
            f"{median:.1f} kn. A controlled discharge is usually made at reduced speed."
        )
    else:
        anomaly, note = 0.0, "Insufficient speed reports in the window to assess."
    features.append(
        FeatureValue("speed_anomaly", anomaly, w["speed_anomaly"], anomaly * w["speed_anomaly"], note)
    )

    # --- Course stability ---------------------------------------------------
    if len(in_window) >= 3:
        headings = np.array([f.cog_deg for f in in_window if f.cog_deg is not None], dtype=float)
        if headings.size >= 3:
            radians = np.deg2rad(headings)
            resultant = float(np.hypot(np.cos(radians).mean(), np.sin(radians).mean()))
            stability = resultant
            note = (
                f"Circular concentration of course over ground is {resultant:.2f} "
                "(1.0 is perfectly straight). Steady steaming is typical of a "
                "deliberate discharge rather than manoeuvring."
            )
        else:
            stability, note = 0.0, "No usable course reports in the window."
    else:
        stability, note = 0.0, "Fewer than three position reports in the window."
    features.append(
        FeatureValue("course_stability", stability, w["course_stability"], stability * w["course_stability"], note)
    )

    # --- Nighttime ----------------------------------------------------------
    if in_window:
        mid = in_window[len(in_window) // 2]
        elevation = solar_elevation_deg(window_start + (window_end - window_start) / 2, mid.lon, mid.lat)
        night = 1.0 if elevation < 0 else 0.0
        note = (
            f"Solar elevation at the window midpoint is {elevation:.1f}°"
            f" — {'night' if night else 'daylight'}. Routine discharges are "
            "disproportionately made after dark."
        )
    else:
        night, note = 0.0, "No position in the window to compute solar elevation."
    features.append(FeatureValue("nighttime", night, w["nighttime"], night * w["nighttime"], note))

    # --- Vessel type risk ---------------------------------------------------
    risk = float(cfg["vessel_type_risk"].get(track.ship_type, cfg["vessel_type_risk"]["unknown"]))
    features.append(
        FeatureValue(
            "vessel_type_risk",
            risk,
            w["vessel_type_risk"],
            risk * w["vessel_type_risk"],
            f"Declared ship type '{track.ship_type}' carries a base risk of {risk:.2f} "
            "in the published weight table.",
        )
    )

    # --- Route deviation ----------------------------------------------------
    if lane_distance_km is None:
        deviation, note = 0.0, "No designated traffic lane reference available for this area."
    else:
        deviation = min(1.0, lane_distance_km / 50.0)
        note = f"{lane_distance_km:.1f} km from the nearest designated traffic lane."
    features.append(
        FeatureValue("route_deviation", deviation, w["route_deviation"], deviation * w["route_deviation"], note)
    )

    # --- Time since port reception facility ---------------------------------
    if hours_since_port_call is None:
        reception, note = 0.0, "No port call history available for this vessel."
    else:
        reception = min(1.0, max(0.0, (hours_since_port_call - 240.0) / 480.0))
        note = (
            f"{hours_since_port_call:.0f} h since the last port call. Bilge holding "
            "capacity on a vessel of this class is typically exceeded beyond ten days."
        )
    features.append(
        FeatureValue(
            "no_recent_port_reception",
            reception,
            w["no_recent_port_reception"],
            reception * w["no_recent_port_reception"],
            note,
        )
    )

    # --- Dark contact -------------------------------------------------------
    dark = 1.0 if track.is_dark else 0.0
    features.append(
        FeatureValue(
            "dark_contact",
            dark,
            w["dark_contact"],
            dark * w["dark_contact"],
            "Radar contact with no matching AIS track at all."
            if dark
            else "Vessel was transmitting AIS and is matched to a radar contact.",
        )
    )

    # --- Prior hits ---------------------------------------------------------
    hits = min(1.0, prior_hit_count / 3.0)
    features.append(
        FeatureValue(
            "prior_hits",
            hits,
            w["prior_hits"],
            hits * w["prior_hits"],
            f"{prior_hit_count} prior AVANTA detection(s) associated with this identity."
            if prior_hit_count
            else "No prior AVANTA detection associated with this identity.",
        )
    )
    return features


def log_prior(features: list[FeatureValue]) -> float:
    return float(sum(f.contribution for f in features))
