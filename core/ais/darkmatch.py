"""Dark vessel detection: radar ship contacts with no AIS track.

A bright point target in the SAR image is a ship, whether or not it is
transmitting. Matching those contacts against the AIS picture leaves a residue,
and that residue is the most interesting category in the whole system: a vessel
that is physically present and electronically absent.

A dark contact becomes a candidate hypothesis with no identity attached. It
cannot be named, but it can be simulated from its observed position and it
carries the heaviest weight in the behaviour prior.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.ais.tracks import Fix, Track, build_track, haversine_km


@dataclass
class DarkContact:
    contact_id: str
    lon: float
    lat: float
    acquired_utc: datetime
    nearest_ais_km: float | None
    nearest_mmsi: str | None

    def as_track(self) -> Track:
        """A dark contact has one observed position and no history. It is
        represented as a single-vertex track, which the simulator treats as the
        degenerate line-source case and flags as such -- not as a normal point
        release."""
        return build_track(
            f"DARK-{self.contact_id}",
            [Fix(self.acquired_utc, self.lon, self.lat)],
            name=None,
            ship_type="unknown",
            is_dark=True,
            source="SAR radar contact, unmatched against AIS",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contact_id": self.contact_id,
            "lon": self.lon,
            "lat": self.lat,
            "acquired_utc": self.acquired_utc.isoformat(),
            "nearest_ais_km": None if self.nearest_ais_km is None else round(self.nearest_ais_km, 3),
            "nearest_mmsi": self.nearest_mmsi,
        }


def match_contacts(
    ship_points: list[tuple[float, float]],
    tracks: list[Track],
    acquired_utc: datetime,
    *,
    match_radius_km: float = 1.5,
) -> tuple[list[DarkContact], dict[str, tuple[float, float]]]:
    """Split radar ship contacts into matched and unmatched.

    The match radius allows for AIS timestamp offset against the acquisition and
    for the position error of a point target in a 10 m ground-range image.
    """
    dark: list[DarkContact] = []
    matched: dict[str, tuple[float, float]] = {}
    for index, (lon, lat) in enumerate(ship_points):
        best_km: float | None = None
        best_mmsi: str | None = None
        for track in tracks:
            fix = _nearest_in_time(track, acquired_utc)
            if fix is None:
                continue
            distance = haversine_km(lon, lat, fix.lon, fix.lat)
            if best_km is None or distance < best_km:
                best_km, best_mmsi = distance, track.mmsi
        if best_km is not None and best_km <= match_radius_km and best_mmsi:
            matched[best_mmsi] = (lon, lat)
        else:
            dark.append(
                DarkContact(
                    contact_id=f"{index:03d}",
                    lon=lon,
                    lat=lat,
                    acquired_utc=acquired_utc,
                    nearest_ais_km=best_km,
                    nearest_mmsi=best_mmsi,
                )
            )
    return dark, matched


def _nearest_in_time(track: Track, when: datetime) -> Fix | None:
    if not track.fixes:
        return None
    return min(track.fixes, key=lambda f: abs((f.t - when).total_seconds()))
