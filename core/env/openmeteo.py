"""Open-Meteo forcing: ERA5 reanalysis wind, ocean currents and waves.

Why this exists. The brief's primary sources are ERA5 through the CDS API and
currents through Copernicus Marine. Both are the right sources and both are
wired up -- but CDS queues a reanalysis request for minutes to hours, which an
interactive console cannot wait on, and CMEMS needs an account whose credentials
may not be present. Open-Meteo serves the *same* ERA5 reanalysis and a global
ocean model over a free keyless HTTP API with a multi-year archive, in about a
second.

So this is a genuine forcing source, not a stub, and it is always named as what
it is in the provenance block. It is used as the interactive path and as the
fallback when CDS or CMEMS are unavailable.

Output is CF-compliant netCDF with the standard_name attributes OpenDrift's
generic reader dispatches on, so the same file drives the physics either way.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import requests
import xarray as xr

log = logging.getLogger(__name__)

ERA5_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/era5"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Requesting a coarse grid keeps the call inside Open-Meteo's per-request limits
# while still resolving the mesoscale structure that matters over a 200 km box.
GRID_N = 5


@dataclass
class GridSpec:
    lats: np.ndarray
    lons: np.ndarray

    @property
    def pairs(self) -> tuple[list[float], list[float]]:
        la, lo = np.meshgrid(self.lats, self.lons, indexing="ij")
        return la.ravel().tolist(), lo.ravel().tolist()


def build_grid(bbox: list[float], n: int = GRID_N) -> GridSpec:
    """A grid padded beyond the scene, because particles drift out of the box."""
    pad_lon = max(0.25, 0.15 * (bbox[2] - bbox[0]))
    pad_lat = max(0.25, 0.15 * (bbox[3] - bbox[1]))
    return GridSpec(
        lats=np.linspace(bbox[1] - pad_lat, bbox[3] + pad_lat, n),
        lons=np.linspace(bbox[0] - pad_lon, bbox[2] + pad_lon, n),
    )


def _request(url: str, params: dict[str, object]) -> list[dict]:
    resp = requests.get(url, params=params, timeout=90)
    resp.raise_for_status()
    payload = resp.json()
    return payload if isinstance(payload, list) else [payload]


def _to_uv(speed: np.ndarray, direction_deg: np.ndarray, *, coming_from: bool) -> tuple[np.ndarray, np.ndarray]:
    """Convert a speed/direction pair to eastward and northward components.

    Meteorological wind direction is the direction the wind blows FROM;
    oceanographic current direction is the direction the water flows TO. Getting
    this backwards silently reverses the drift, so it is an explicit argument.
    """
    theta = np.deg2rad(direction_deg)
    u = speed * np.sin(theta)
    v = speed * np.cos(theta)
    if coming_from:
        return -u, -v
    return u, v


def _series(results: list[dict], key: str) -> np.ndarray:
    return np.array([r["hourly"][key] for r in results], dtype=np.float32)


def _times(results: list[dict]) -> np.ndarray:
    return np.array(results[0]["hourly"]["time"], dtype="datetime64[ns]")


def _reshape(flat: np.ndarray, grid: GridSpec) -> np.ndarray:
    """(n_points, n_time) -> (n_time, n_lat, n_lon)."""
    n_lat, n_lon = len(grid.lats), len(grid.lons)
    return flat.reshape(n_lat, n_lon, -1).transpose(2, 0, 1)


# ERA5 is a reanalysis and runs about five days behind real time. Asking the
# archive for yesterday returns a 400, so a recent window has to come from the
# analysis/forecast endpoint instead. Which one answered is reported in
# provenance either way -- they are not the same product and must not be
# presented as if they were.
ERA5_LATENCY_DAYS = 6


def _window(t_from: str, t_to: str) -> tuple[str, str]:
    start = datetime.fromisoformat(t_from.replace("Z", "+00:00")).replace(tzinfo=None)
    end = datetime.fromisoformat(t_to.replace("Z", "+00:00")).replace(tzinfo=None)
    return (start - timedelta(days=1)).strftime("%Y-%m-%d"), (end + timedelta(days=1)).strftime("%Y-%m-%d")


def _needs_forecast(t_to: str) -> bool:
    end = datetime.fromisoformat(t_to.replace("Z", "+00:00")).replace(tzinfo=None)
    return end > datetime.utcnow() - timedelta(days=ERA5_LATENCY_DAYS)


def source_label(t_to: str) -> str:
    """What actually answered, for the provenance block."""
    if _needs_forecast(t_to):
        return (
            "ECMWF IFS analysis/forecast 10 m wind via Open-Meteo "
            "(ERA5 reanalysis lags real time by ~5 days and does not cover this window)"
        )
    return "ERA5 reanalysis 10 m wind via the Open-Meteo archive API"


def fetch_wind(bbox: list[float], t_from: str, t_to: str, out: Path) -> Path:
    """ERA5 10 m wind on a grid, written as CF netCDF."""
    grid = build_grid(bbox)
    lats, lons = grid.pairs
    start, end = _window(t_from, t_to)
    forecast = _needs_forecast(t_to)
    params: dict[str, object] = {
        "latitude": ",".join(f"{v:.4f}" for v in lats),
        "longitude": ",".join(f"{v:.4f}" for v in lons),
        "start_date": start,
        "end_date": end,
        "hourly": "wind_speed_10m,wind_direction_10m",
        "wind_speed_unit": "ms",
        "timezone": "UTC",
    }
    results = _request(FORECAST_URL if forecast else ERA5_ARCHIVE_URL, params)
    speed = _series(results, "wind_speed_10m")
    direction = _series(results, "wind_direction_10m")
    u, v = _to_uv(speed, direction, coming_from=True)
    ds = xr.Dataset(
        {
            "x_wind": (("time", "lat", "lon"), _reshape(u, grid)),
            "y_wind": (("time", "lat", "lon"), _reshape(v, grid)),
        },
        coords={"time": _times(results), "lat": grid.lats, "lon": grid.lons},
    )
    ds.x_wind.attrs = {"standard_name": "x_wind", "units": "m s-1"}
    ds.y_wind.attrs = {"standard_name": "y_wind", "units": "m s-1"}
    return _write(ds, out, source_label(t_to))


def fetch_currents(bbox: list[float], t_from: str, t_to: str, out: Path) -> Path:
    """Surface currents and waves on a grid, written as CF netCDF."""
    grid = build_grid(bbox)
    lats, lons = grid.pairs
    start, end = _window(t_from, t_to)
    results = _request(
        MARINE_URL,
        {
            "latitude": ",".join(f"{v:.4f}" for v in lats),
            "longitude": ",".join(f"{v:.4f}" for v in lons),
            "start_date": start,
            "end_date": end,
            "hourly": "ocean_current_velocity,ocean_current_direction,wave_height,wave_direction,wave_period",
            "timezone": "UTC",
        },
    )
    # Open-Meteo reports current speed in km/h and direction as the heading the
    # water is flowing towards.
    speed = _series(results, "ocean_current_velocity") / 3.6
    direction = _series(results, "ocean_current_direction")
    u, v = _to_uv(speed, direction, coming_from=False)

    wave_dir = _series(results, "wave_direction")
    wave_h = _series(results, "wave_height")
    data = {
        "x_sea_water_velocity": (("time", "lat", "lon"), _reshape(u, grid)),
        "y_sea_water_velocity": (("time", "lat", "lon"), _reshape(v, grid)),
        "sea_surface_wave_significant_height": (("time", "lat", "lon"), _reshape(wave_h, grid)),
        "sea_surface_wave_from_direction": (("time", "lat", "lon"), _reshape(wave_dir, grid)),
        "sea_surface_wave_mean_period": (
            ("time", "lat", "lon"),
            _reshape(_series(results, "wave_period"), grid),
        ),
    }
    ds = xr.Dataset(data, coords={"time": _times(results), "lat": grid.lats, "lon": grid.lons})
    ds.x_sea_water_velocity.attrs = {"standard_name": "x_sea_water_velocity", "units": "m s-1"}
    ds.y_sea_water_velocity.attrs = {"standard_name": "y_sea_water_velocity", "units": "m s-1"}
    ds.sea_surface_wave_significant_height.attrs = {
        "standard_name": "sea_surface_wave_significant_height",
        "units": "m",
    }
    ds.sea_surface_wave_from_direction.attrs = {
        "standard_name": "sea_surface_wave_from_direction",
        "units": "degree",
    }
    ds.sea_surface_wave_mean_period.attrs = {
        "standard_name": "sea_surface_wave_mean_period_from_variance_spectral_density_second_frequency_moment",
        "units": "s",
    }
    return _write(ds, out, "Open-Meteo global ocean model: surface currents and wave spectrum")


def _write(ds: xr.Dataset, out: Path, title: str) -> Path:
    ds.lat.attrs = {"standard_name": "latitude", "units": "degrees_north"}
    ds.lon.attrs = {"standard_name": "longitude", "units": "degrees_east"}
    ds.attrs = {"Conventions": "CF-1.8", "title": title, "source": "open-meteo.com"}
    out.parent.mkdir(parents=True, exist_ok=True)
    # Interpolate across any gaps so OpenDrift never sees a NaN in the interior.
    ds = ds.interpolate_na(dim="time", method="linear", fill_value="extrapolate")
    # Grid points that fall on land come back empty from the ocean model. Fill
    # them from their neighbours so the reader has continuous coverage; whether
    # a particle is actually on land is decided by the landmask, not by a hole
    # in the current field.
    for dim in ("lon", "lat"):
        if ds.sizes.get(dim, 0) > 1:
            ds = ds.interpolate_na(dim=dim, method="nearest", fill_value="extrapolate")
    ds.to_netcdf(out)
    return out
