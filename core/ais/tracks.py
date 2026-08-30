"""AIS track assembly and gap detection.

A track is a vessel's own position history. Two things about it matter here and
neither is incidental:

  * The track is the *seed geometry* for the forward simulation. A discharge
    from a moving vessel is a line source along this polyline, not a point.
  * The holes in it are evidence. A vessel that stops transmitting does not
    leave the suspect list; the gap is recorded, measured, and counted against
    it. Dropping a vessel because its data is missing is how a transponder
    becomes a way to disappear.
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from core.config import settings

EARTH_R_KM = 6371.0088


@dataclass
class Fix:
    t: datetime
    lon: float
    lat: float
    sog_kn: float | None = None
    cog_deg: float | None = None


@dataclass
class Gap:
    start: datetime
    end: datetime

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60.0

    def overlap_minutes(self, w_start: datetime, w_end: datetime) -> float:
        lo = max(self.start, w_start)
        hi = min(self.end, w_end)
        return max(0.0, (hi - lo).total_seconds() / 60.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "minutes": round(self.minutes, 1),
        }


@dataclass
class Track:
    mmsi: str
    fixes: list[Fix]
    name: str | None = None
    imo: str | None = None
    flag: str | None = None
    ship_type: str = "unknown"
    length_m: float | None = None
    is_dark: bool = False
    gaps: list[Gap] = field(default_factory=list)
    source: str = "unknown"

    @property
    def t_start(self) -> datetime:
        return self.fixes[0].t

    @property
    def t_end(self) -> datetime:
        return self.fixes[-1].t

    def lonlats(self) -> tuple[np.ndarray, np.ndarray]:
        return (
            np.array([f.lon for f in self.fixes]),
            np.array([f.lat for f in self.fixes]),
        )

    def median_sog(self) -> float:
        values = [f.sog_kn for f in self.fixes if f.sog_kn is not None]
        return float(np.median(values)) if values else 0.0

    def to_geojson(self) -> dict[str, Any]:
        """LineString for the transmitted track, plus the gaps as their own
        features so the UI can render them dashed rather than pretending the
        vessel travelled a straight line through a hole in the data."""
        coords = [[f.lon, f.lat] for f in self.fixes]
        features: list[dict[str, Any]] = [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "mmsi": self.mmsi,
                    "name": self.name,
                    "imo": self.imo,
                    "flag": self.flag,
                    "ship_type": self.ship_type,
                    "is_dark": self.is_dark,
                    "segment": "transmitted",
                    "source": self.source,
                    "t_start": self.t_start.isoformat(),
                    "t_end": self.t_end.isoformat(),
                    "median_sog_kn": round(self.median_sog(), 2),
                },
            }
        ]
        for gap in self.gaps:
            before = max((f for f in self.fixes if f.t <= gap.start), key=lambda f: f.t, default=None)
            after = min((f for f in self.fixes if f.t >= gap.end), key=lambda f: f.t, default=None)
            if before is None or after is None:
                continue
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[before.lon, before.lat], [after.lon, after.lat]],
                    },
                    "properties": {
                        "mmsi": self.mmsi,
                        "segment": "gap",
                        "minutes": round(gap.minutes, 1),
                        "start": gap.start.isoformat(),
                        "end": gap.end.isoformat(),
                    },
                }
            )
        return {"type": "FeatureCollection", "features": features}


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(math.sqrt(a))


def build_track(mmsi: str, fixes: Iterable[Fix], **meta: Any) -> Track:
    ordered = sorted(fixes, key=lambda f: f.t)
    deduped: list[Fix] = []
    for fix in ordered:
        if deduped and (fix.t - deduped[-1].t).total_seconds() < 1.0:
            continue
        deduped.append(fix)
    track = Track(mmsi=mmsi, fixes=deduped, **meta)
    track.gaps = detect_gaps(deduped)
    return track


def detect_gaps(fixes: list[Fix], min_minutes: float | None = None) -> list[Gap]:
    """A gap is a silence longer than a vessel's normal reporting interval.

    Class A AIS reports every 2-10 seconds under way; even allowing for
    terrestrial and satellite receiver coverage holes, a silence beyond the
    configured threshold is a fact worth recording.
    """
    threshold = min_minutes if min_minutes is not None else float(settings()["ais"]["gap_min_minutes"])
    gaps: list[Gap] = []
    # Deliberately unequal lengths: this pairs each fix with its successor.
    for prev, nxt in zip(fixes, fixes[1:], strict=False):
        minutes = (nxt.t - prev.t).total_seconds() / 60.0
        if minutes >= threshold:
            gaps.append(Gap(prev.t, nxt.t))
    return gaps


def resample(track: Track, minutes: float | None = None) -> list[Fix]:
    """Resample to a fixed interval by linear interpolation.

    The simulator seeds one cluster of particles per vertex, so vertices must be
    evenly spaced in time or the line source would be denser where the vessel
    happened to report more often.

    Interpolation deliberately does NOT bridge a gap: a position the vessel
    never transmitted is not evidence, and inventing one would put simulated oil
    somewhere no observation supports.
    """
    step = minutes if minutes is not None else float(settings()["ais"]["resample_minutes"])
    if len(track.fixes) < 2:
        return list(track.fixes)
    delta = timedelta(minutes=step)
    out: list[Fix] = []
    t = track.t_start
    idx = 0
    while t <= track.t_end:
        while idx + 1 < len(track.fixes) and track.fixes[idx + 1].t < t:
            idx += 1
        a, b = track.fixes[idx], track.fixes[min(idx + 1, len(track.fixes) - 1)]
        span = (b.t - a.t).total_seconds()
        if span <= 0:
            out.append(Fix(t, a.lon, a.lat, a.sog_kn, a.cog_deg))
        elif span / 60.0 >= float(settings()["ais"]["gap_min_minutes"]):
            pass  # inside a transmission gap: emit nothing
        else:
            f = (t - a.t).total_seconds() / span
            out.append(
                Fix(
                    t,
                    a.lon + f * (b.lon - a.lon),
                    a.lat + f * (b.lat - a.lat),
                    _lerp(a.sog_kn, b.sog_kn, f),
                    _lerp(a.cog_deg, b.cog_deg, f),
                )
            )
        t += delta
    return out


def _lerp(a: float | None, b: float | None, f: float) -> float | None:
    if a is None or b is None:
        return a if b is None else b
    return a + f * (b - a)


def subtrack(track: Track, t_start: datetime, t_end: datetime, step_minutes: float | None = None) -> list[Fix]:
    """The vertices of the line source: the piece of the vessel's own track that
    falls inside a candidate release window.

    Release windows arrive from several places -- a theta grid, a scenario file,
    an API request -- and are not consistently timezone-aware, while track fixes
    always are. Normalising both sides here rather than trusting callers keeps
    a naive datetime from silently excluding every vertex.
    """
    start, end = utc(t_start), utc(t_end)
    return [f for f in resample(track, step_minutes) if start <= utc(f.t) <= end]


def course_over_ground(fixes: list[Fix]) -> float:
    """Mean heading of a run of fixes, in compass degrees."""
    if len(fixes) < 2:
        return float(fixes[0].cog_deg or 0.0) if fixes else 0.0
    lon = np.array([f.lon for f in fixes])
    lat = np.array([f.lat for f in fixes])
    dlon = np.diff(lon) * np.cos(np.deg2rad(lat[:-1]))
    dlat = np.diff(lat)
    return float((math.degrees(math.atan2(float(dlon.sum()), float(dlat.sum()))) + 360.0) % 360.0)


def utc(value: Any) -> datetime:
    """Parse the several timestamp shapes this system has to accept.

    aisstream emits `2025-05-26 06:00:00.123456789 +0000 UTC` -- Go's time
    format, with a nanosecond fraction and a space before the offset. Neither
    Python's fromisoformat nor a naive ISO assumption handles it, and getting
    this wrong silently drops every live position report.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    text = str(value).strip()
    if text.endswith(" UTC"):
        text = text[:-4].strip()
    text = text.replace("Z", "+00:00")

    # Collapse a bare +0000 / -0530 offset into the +00:00 form isoformat wants.
    match = re.search(r"([+-]\d{2})(\d{2})$", text)
    if match:
        text = f"{text[: match.start()].strip()}{match.group(1)}:{match.group(2)}"

    # Python 3.10's fromisoformat accepts at most 6 fractional digits.
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text.split("+")[0].split(".")[0].strip(), fmt)
                break
            except ValueError:
                continue
        else:
            raise
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
