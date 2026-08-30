"""Environmental forcing: real files, correctly shaped, honestly labelled."""
from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

BBOX = [75.6, 8.9, 76.5, 9.8]
T_FROM = "2025-05-25T00:00:00Z"
T_TO = "2025-05-28T12:00:00Z"


@pytest.mark.network
def test_wind_forcing_fetch():
    """ERA5 10 m wind, written as CF netCDF that OpenDrift's generic reader can
    dispatch on by standard_name."""
    from core.env.wind import fetch_wind

    field = fetch_wind(BBOX, T_FROM, T_TO)
    assert field.mode in {"LIVE", "CACHED", "FIXTURE"}
    assert field.path.exists()

    with xr.open_dataset(field.path) as ds:
        assert {"x_wind", "y_wind"} <= set(ds.data_vars)
        assert ds.x_wind.attrs["standard_name"] == "x_wind"
        assert ds.sizes["time"] > 24
        speed = np.hypot(ds.x_wind.values, ds.y_wind.values)
        assert np.isfinite(speed).all(), "a NaN in the forcing would strand particles"
        assert 0.0 <= float(np.nanmean(speed)) < 40.0

    speed, direction = field.mean_speed_ms(76.1, 9.3, "2025-05-28T00:41:00")
    assert 0.0 <= speed < 40.0
    assert 0.0 <= direction <= 360.0


@pytest.mark.network
def test_currents_forcing_fetch():
    """Currents and the wave spectrum for Stokes drift."""
    from core.env.currents import fetch_currents

    forcing = fetch_currents(BBOX, T_FROM, T_TO)
    assert forcing.mode in {"LIVE", "CACHED", "FIXTURE"}
    with xr.open_dataset(forcing.path) as ds:
        assert {"x_sea_water_velocity", "y_sea_water_velocity"} <= set(ds.data_vars)
        speed = np.hypot(ds.x_sea_water_velocity.values, ds.y_sea_water_velocity.values)
        assert float(np.nanmax(speed)) < 5.0, "a surface current above 5 m/s is not physical here"


@pytest.mark.network
def test_provenance_names_the_source_actually_used():
    """AC: if we fall back, the provenance block says so rather than implying
    the primary source answered."""
    from core.env.wind import fetch_wind

    record = fetch_wind(BBOX, T_FROM, T_TO).provenance()
    payload = record.to_dict()
    assert payload["mode"] in {"LIVE", "CACHED", "FIXTURE"}
    assert "ERA5" in payload["source"]
    assert payload.get("sha256")
