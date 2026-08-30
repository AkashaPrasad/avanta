"""10 m wind: the forcing that drives oil drift and the gate that decides
whether a slick could have been seen at all.

Source chain, in order, with the one actually used always named in provenance:
  1. ERA5 through the CDS API -- the reference reanalysis, but a request queues
     for minutes to hours, so it is used for pre-seeded fixtures, not live.
  2. ERA5 through the Open-Meteo archive API -- the same reanalysis, keyless,
     about a second.
  3. A bundled fixture.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import requests
import xarray as xr

from core.env import openmeteo
from core.env.cache import env_cache_path, fixture_path
from core.provenance.hashing import sha256_file
from core.provenance.record import DataMode, SourceRecord

log = logging.getLogger(__name__)


@dataclass
class WindField:
    path: Path
    source: str
    mode: DataMode
    sha256: str

    def provenance(self) -> SourceRecord:
        return SourceRecord(source=self.source, mode=self.mode, sha256=self.sha256)

    def mean_speed_ms(self, lon: float, lat: float, t_iso: str | None = None) -> tuple[float, float]:
        """Wind speed and direction at a point, averaged over the file's window
        if no time is given. Direction is meteorological (blowing FROM)."""
        with xr.open_dataset(self.path) as ds:
            point = ds.sel(lat=lat, lon=lon, method="nearest")
            if t_iso is not None:
                point = point.sel(time=np.datetime64(t_iso.replace("Z", "")), method="nearest")
            u = float(np.nanmean(point.x_wind.values))
            v = float(np.nanmean(point.y_wind.values))
        speed = float(np.hypot(u, v))
        direction = float((np.degrees(np.arctan2(-u, -v)) + 360.0) % 360.0)
        return speed, direction


def fetch_wind(bbox: list[float], t_from: str, t_to: str, *, allow_live: bool = True) -> WindField:
    target = env_cache_path("wind", bbox, t_from, t_to)
    if target.exists() and target.stat().st_size > 0:
        return WindField(target, "ERA5 (Open-Meteo archive)", "CACHED", sha256_file(target))

    if allow_live:
        try:
            openmeteo.fetch_wind(bbox, t_from, t_to, target)
            return WindField(target, openmeteo.source_label(t_to), "LIVE", sha256_file(target))
        except (requests.RequestException, KeyError, ValueError) as exc:
            log.warning("Open-Meteo ERA5 wind fetch failed (%s); falling back to fixture", exc)

    fixture = fixture_path("wind")
    if fixture is None:
        raise RuntimeError("No live wind source and no bundled wind fixture.")
    return WindField(fixture, "ERA5 (bundled fixture)", "FIXTURE", sha256_file(fixture))
