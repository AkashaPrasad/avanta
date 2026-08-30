"""Forward OpenOil integration.

FORWARD ONLY. This is the load-bearing design decision of the whole system and
it is enforced here in code, not left to convention.

Backtracking -- running drift in reverse from an observed slick to guess where
it came from -- is the obvious approach and it does not work. Two independent
reasons, both fatal:

  * Turbulent diffusion is a random walk. A random walk has no inverse. Running
    the stochastic term backwards does not retrace the particles' path, it
    disperses them again, so the "origin" a backward run produces is an
    artefact of the diffusivity, not a location.
  * The slick being reversed is not the slick that was released. Oil evaporates,
    emulsifies and disperses continuously, so its mass, area and drift
    properties at observation time differ from those at release. Reversing the
    observed slick reverses the wrong object.

  (Breivik et al., "Advances in search and rescue at sea", Ocean Dynamics 2013,
   on the ill-posedness of reverse drift with stochastic terms.)

AVANTA therefore never integrates backwards. It runs each candidate vessel
*forward* from its own track and compares the result to the observation. That is
a hypothesis test, not an inverse problem, and forward integration of a
stochastic process is well-posed.

`assert_forward_only` below is called on every run and is checked by AC-9.
"""
from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from core.ais.tracks import Track, utc
from core.config import settings
from core.simulate.line_source import ReleaseParams, SeedArrays, build_seed

log = logging.getLogger(__name__)


class BackwardIntegrationError(RuntimeError):
    """Raised if anything ever asks this runner to integrate backwards."""


def assert_forward_only(seed_times: list[datetime], end_time: datetime, time_step_s: float) -> None:
    """The three ways a backward run could sneak in, all refused explicitly."""
    if time_step_s <= 0:
        raise BackwardIntegrationError(
            f"time_step must be positive; got {time_step_s}. AVANTA never integrates backwards."
        )
    if not seed_times:
        raise BackwardIntegrationError("No seed times: nothing to integrate.")
    latest_seed = max(seed_times)
    if end_time < latest_seed:
        raise BackwardIntegrationError(
            f"end_time {end_time.isoformat()} precedes the last seed time "
            f"{latest_seed.isoformat()}. AVANTA never integrates backwards."
        )


@dataclass
class SimulationResult:
    lon: np.ndarray                 # (n_elements, n_time)
    lat: np.ndarray
    times: list[datetime]
    status: np.ndarray
    mass_oil: np.ndarray
    mass_evaporated: np.ndarray
    water_fraction: np.ndarray
    seed: SeedArrays
    params: ReleaseParams
    oil_density_kg_m3: float
    oil_viscosity_cst: float
    runtime_s: float
    stranded_fraction: float
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def surface_at(self, index: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Positions and remaining oil mass at one output step, active only."""
        lon = self.lon[:, index]
        lat = self.lat[:, index]
        mass = self.mass_oil[:, index]
        ok = np.isfinite(lon) & np.isfinite(lat) & (mass > 0)
        return lon[ok], lat[ok], mass[ok]

    def to_timeseries_geojson(self, stride: int = 1) -> dict[str, Any]:
        """Particle positions per output step, for the timeline scrubber.

        Emitted as flat coordinate arrays rather than one Feature per particle:
        a 5,000-particle, 25-step run is 125,000 points and deck.gl wants them
        as a buffer, not as GeoJSON features.
        """
        frames = []
        for i in range(0, len(self.times), stride):
            lon, lat, mass = self.surface_at(i)
            frames.append(
                {
                    "t": self.times[i].isoformat(),
                    "n": int(lon.size),
                    "lon": [round(float(v), 5) for v in lon],
                    "lat": [round(float(v), 5) for v in lat],
                    "mass_kg": round(float(mass.sum()), 2),
                }
            )
        return {
            "release": self.params.to_dict(),
            "seed": self.seed.to_summary(),
            "frames": frames,
            "oil": {
                "density_kg_m3": round(self.oil_density_kg_m3, 1),
                "viscosity_cst": round(self.oil_viscosity_cst, 1),
            },
        }


def run_forward(
    track: Track,
    params: ReleaseParams,
    acquisition: datetime,
    currents_path: Path,
    wind_path: Path,
    *,
    n_per_point: int | None = None,
    wind_drift_factor: float | None = None,
    horizontal_diffusivity: float | None = None,
    current_scale: float = 1.0,
    wind_scale: float = 1.0,
    wind_rotate_deg: float = 0.0,
    seed_rng: int | None = None,
) -> SimulationResult:
    """Integrate one release hypothesis forward to the SAR acquisition time.

    The `*_scale` and `wind_rotate_deg` arguments perturb the forcing for an
    ensemble member; at their defaults the forcing is used as delivered.
    """
    import time as _time

    from opendrift.models.openoil import OpenOil
    from opendrift.readers import reader_netCDF_CF_generic

    cfg = settings()["simulate"]
    n_per_point = n_per_point if n_per_point is not None else int(cfg["n_per_point"])
    wind_drift_factor = (
        wind_drift_factor if wind_drift_factor is not None else float(cfg["wind_drift_factor"])
    )
    horizontal_diffusivity = (
        horizontal_diffusivity
        if horizontal_diffusivity is not None
        else float(cfg["horizontal_diffusivity"])
    )

    seed = build_seed(track, params, n_per_point=n_per_point, step_minutes=float(settings()["ais"]["resample_minutes"]))
    end_time = utc(acquisition).replace(tzinfo=None)
    assert_forward_only(seed.time, end_time, float(cfg["time_step_s"]))

    started = _time.time()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = OpenOil(loglevel=50, weathering_model="noaa")
        readers = [
            _reader(reader_netCDF_CF_generic, currents_path, current_scale, 0.0),
            _reader(reader_netCDF_CF_generic, wind_path, wind_scale, wind_rotate_deg),
        ]
        model.add_reader(readers)
        model.set_config("environment:constant:horizontal_diffusivity", horizontal_diffusivity)
        model.set_config("drift:vertical_mixing", True)
        model.set_config("processes:evaporation", True)
        model.set_config("processes:emulsification", True)
        model.set_config("drift:stokes_drift", True)
        model.set_config("seed:wind_drift_factor", wind_drift_factor)
        model.set_config("general:coastline_action", "stranding")
        if seed_rng is not None:
            np.random.seed(seed_rng)

        # The released volume has to actually reach OpenDrift, or the rate in
        # the dossier and the OOSA handoff describes a discharge the simulation
        # never modelled. m3_per_hour is spread across the seeded elements.
        model.seed_elements(
            lon=seed.lon,
            lat=seed.lat,
            time=seed.time,
            radius=float(cfg["seed_radius_m"]),
            z=0,
            oil_type=params.oil_type,
            m3_per_hour=params.rate_m3_per_h,
        )
        model.run(
            end_time=end_time,
            time_step=int(cfg["time_step_s"]),
            time_step_output=int(cfg["output_step_s"]),
        )

    result = model.result
    times = [
        datetime.utcfromtimestamp(int(t) / 1e9) if isinstance(t, (int, np.integer)) else _as_dt(t)
        for t in result.time.values
    ]
    status = result.status.values
    stranded = float(np.mean(status[:, -1] != 0)) if status.size else 0.0
    density = float(np.nanmedian(result.density.values[:, -1]))
    viscosity = float(np.nanmedian(result.viscosity.values[:, -1])) * 1e6  # m2/s -> cSt

    return SimulationResult(
        lon=result.lon.values,
        lat=result.lat.values,
        times=times,
        status=status,
        mass_oil=result.mass_oil.values,
        mass_evaporated=result.mass_evaporated.values,
        water_fraction=result.water_fraction.values,
        seed=seed,
        params=params,
        oil_density_kg_m3=density,
        oil_viscosity_cst=viscosity,
        runtime_s=_time.time() - started,
        stranded_fraction=stranded,
        diagnostics={
            "forward_only": True,
            "n_output_steps": len(times),
            "wind_drift_factor": wind_drift_factor,
            "horizontal_diffusivity": horizontal_diffusivity,
            "current_scale": current_scale,
            "wind_scale": wind_scale,
            "wind_rotate_deg": wind_rotate_deg,
        },
    )


def _reader(module: Any, path: Path, scale: float, rotate_deg: float) -> Any:
    """A netCDF reader, optionally with its vector field perturbed.

    The perturbation is applied by patching the reader instance's own
    interpolation method rather than wrapping it in a proxy object. OpenDrift's
    `add_reader` does an isinstance check against its Reader base class, so a
    proxy is rejected outright -- and because a failed member is caught and
    skipped further up, that rejection would silently empty the ensemble while
    everything still appeared to work. Patching in place keeps the object a real
    Reader.

    Rescaling and rotating the reader's output also means an ensemble of twelve
    members reads one copy of the forcing from disk rather than twelve.
    """
    reader = module.Reader(str(path))
    if scale == 1.0 and rotate_deg == 0.0:
        return reader

    vector_pairs = [
        ("x_sea_water_velocity", "y_sea_water_velocity"),
        ("x_wind", "y_wind"),
    ]
    original = reader.get_variables_interpolated
    cos_r = float(np.cos(np.deg2rad(rotate_deg)))
    sin_r = float(np.sin(np.deg2rad(rotate_deg)))

    def perturbed(*args: Any, **kwargs: Any) -> Any:
        env, profiles = original(*args, **kwargs)
        for x_key, y_key in vector_pairs:
            if x_key in env and y_key in env:
                x = np.asarray(env[x_key], dtype=float) * scale
                y = np.asarray(env[y_key], dtype=float) * scale
                env[x_key] = x * cos_r - y * sin_r
                env[y_key] = x * sin_r + y * cos_r
        return env, profiles

    reader.get_variables_interpolated = perturbed
    return reader


def _as_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.utcfromtimestamp(np.datetime64(value, "s").astype("int64"))
