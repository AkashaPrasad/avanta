"""Moving line source seeding.

A vessel discharging while under way does not release oil at a point. It lays it
down along its own track, at its own speed, over the duration of the discharge.
That is why these events leave the long narrow slicks they do, and reproducing
that geometry is the whole reason the forward hypothesis test can distinguish
one vessel from another: a point release would produce a roughly circular cloud
that fits almost any candidate equally well.

So a point source here is a bug, not a simplification. The one legitimate
degenerate case is a dark radar contact, which has exactly one observed position
and no history -- and that case is flagged, never silently treated as normal.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from core.ais.tracks import Track, subtrack, utc


@dataclass(frozen=True)
class ReleaseParams:
    """One hypothesis about how a discharge happened: when it started, how long
    it lasted, at what rate, and of what."""

    t_start: datetime
    duration_hours: float
    rate_m3_per_h: float
    oil_type: str = "GENERIC INTERMEDIATE FUEL OIL 180"

    @property
    def t_end(self) -> datetime:
        return self.t_start + timedelta(hours=self.duration_hours)

    @property
    def volume_m3(self) -> float:
        return self.duration_hours * self.rate_m3_per_h

    def to_dict(self) -> dict[str, Any]:
        return {
            "t_start": self.t_start.isoformat(),
            "t_end": self.t_end.isoformat(),
            "duration_hours": self.duration_hours,
            "rate_m3_per_h": self.rate_m3_per_h,
            "volume_m3": round(self.volume_m3, 3),
            "oil_type": self.oil_type,
        }


@dataclass
class SeedArrays:
    """Per-element seed arrays, expanded so every particle carries its own
    origin position and its own origin time.

    OpenDrift requires the time array to be one entry per element, so the
    expansion is explicit rather than delegated to `number_per_point` -- which
    also makes the line-source property directly assertable in a test.
    """

    lon: np.ndarray
    lat: np.ndarray
    time: list[datetime]
    n_vertices: int
    n_per_point: int
    degenerate: bool
    degenerate_reason: str | None = None

    @property
    def n_elements(self) -> int:
        return int(self.lon.size)

    def distinct_positions(self) -> int:
        return len({(round(a, 5), round(b, 5)) for a, b in zip(self.lon, self.lat, strict=True)})

    def distinct_times(self) -> int:
        return len(set(self.time))

    def to_summary(self) -> dict[str, Any]:
        return {
            "n_elements": self.n_elements,
            "n_vertices": self.n_vertices,
            "n_per_point": self.n_per_point,
            "distinct_seed_positions": self.distinct_positions(),
            "distinct_seed_times": self.distinct_times(),
            "degenerate": self.degenerate,
            "degenerate_reason": self.degenerate_reason,
        }


def build_seed(
    track: Track,
    params: ReleaseParams,
    *,
    n_per_point: int,
    step_minutes: float = 5.0,
) -> SeedArrays:
    """Expand a track segment into per-particle seed arrays.

    Each vertex of the vessel's own resampled track inside the release window
    contributes `n_per_point` particles, seeded at *that vertex's* timestamp.
    """
    vertices = subtrack(track, params.t_start, params.t_end, step_minutes)

    degenerate = False
    reason: str | None = None
    if len(vertices) < 2:
        degenerate = True
        if track.is_dark:
            reason = (
                "Dark radar contact: one observed position and no track history, so a "
                "line source cannot be constructed. Seeded as a single point and "
                "reported as such."
            )
        else:
            reason = (
                "The vessel's track has fewer than two positions inside this release "
                "window — the window may fall entirely inside a transmission gap."
            )
        if not vertices:
            vertices = [track.fixes[-1]]

    lon = np.repeat(np.array([v.lon for v in vertices], dtype=float), n_per_point)
    lat = np.repeat(np.array([v.lat for v in vertices], dtype=float), n_per_point)
    # OpenDrift works in naive UTC internally, so seed times are converted once,
    # here, after all comparisons have been done in aware UTC.
    times = [utc(v.t).replace(tzinfo=None) for v in vertices for _ in range(n_per_point)]
    return SeedArrays(
        lon=lon,
        lat=lat,
        time=times,
        n_vertices=len(vertices),
        n_per_point=n_per_point,
        degenerate=degenerate,
        degenerate_reason=reason,
    )


def theta_grid(track: Track, acquisition: datetime, grid: dict[str, list[float]], oil_type: str) -> list[ReleaseParams]:
    """The hypothesis grid over release parameters.

    The likelihood is profiled over this grid, and the argmax is what turns a
    probability into a statement an officer can act on: not "this vessel", but
    "this vessel, discharging between these times, at about this rate".
    """
    out: list[ReleaseParams] = []
    acquisition = utc(acquisition).replace(tzinfo=None)
    for lead in grid["lead_hours"]:
        for duration in grid["duration_hours"]:
            t_start = acquisition - timedelta(hours=float(lead))
            if t_start + timedelta(hours=float(duration)) > acquisition:
                continue  # a release cannot still be running after the image was taken
            if utc(t_start) < utc(track.t_start) - timedelta(hours=1):
                continue  # no track coverage this far back
            for rate in grid["rate_m3_per_h"]:
                out.append(ReleaseParams(t_start, float(duration), float(rate), oil_type))
    return out
