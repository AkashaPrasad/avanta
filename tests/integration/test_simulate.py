"""Forward simulation and ensemble behaviour against real forcing."""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pytest

from core.simulate.ensemble import perturbations, summarise
from core.simulate.line_source import ReleaseParams
from core.simulate.openoil_runner import run_forward

pytestmark = pytest.mark.slow


def test_ensemble_perturbation():
    """Members must differ from each other, and member 0 must be the unperturbed
    control so the ensemble always contains the nominal run."""
    rng = np.random.default_rng(0)
    members = perturbations(12, rng)
    assert len(members) == 12

    control = members[0]
    assert control["wind_scale"] == 1.0
    assert control["current_scale"] == 1.0
    assert control["wind_rotate_deg"] == 0.0

    for key in ("wind_scale", "current_scale", "wind_drift_factor", "horizontal_diffusivity"):
        values = [m[key] for m in members]
        assert len(set(values)) > 1, f"{key} was identical across every member"

    drift = [m["wind_drift_factor"] for m in members[1:]]
    assert all(0.02 <= d <= 0.04 for d in drift), "wind drift factor left its plausible range"


def test_summarise_reports_a_credible_interval():
    summary = summarise([1.0, 2.0, 3.0, 4.0, 5.0])
    assert summary["median"] == 3.0
    assert summary["lo"] < summary["median"] < summary["hi"]
    assert summary["width"] > 0
    assert summarise([])["n"] == 0


def test_forward_run_produces_a_drifting_weathering_slick(steady_track, forcing_files):
    currents, wind = forcing_files
    params = ReleaseParams(steady_track.t_start.replace(tzinfo=None) + timedelta(minutes=10), 1.5, 4.0)
    acquisition = steady_track.t_start + timedelta(hours=8)

    result = run_forward(steady_track, params, acquisition, currents, wind, n_per_point=20)

    assert result.diagnostics["forward_only"] is True
    assert result.seed.distinct_positions() >= 5
    assert result.seed.distinct_times() >= 5

    first_lon, first_lat, _ = result.surface_at(0)
    last_lon, last_lat, last_mass = result.surface_at(len(result.times) - 1)
    assert last_lon.size >= first_lon.size, "particles keep entering as the line source is laid down"

    # The cloud must actually move and actually spread.
    moved_km = np.hypot(
        (float(last_lon.mean()) - float(first_lon.mean())) * 111.0,
        (float(last_lat.mean()) - float(first_lat.mean())) * 111.0,
    )
    assert moved_km > 0.5, f"the slick barely drifted ({moved_km:.2f} km)"
    assert float(last_lon.std()) > float(first_lon.std()), "the cloud did not disperse"

    # NOAA weathering must have removed some mass to the atmosphere.
    evaporated = float(np.nansum(result.mass_evaporated[:, -1]))
    remaining = float(np.nansum(result.mass_oil[:, -1]))
    assert evaporated > 0 and remaining > 0
    assert 0.0 < evaporated / (evaporated + remaining) < 0.8

    # ADIOS oil properties must be real numbers the dossier can quote.
    assert 700 < result.oil_density_kg_m3 < 1100
    assert result.oil_viscosity_cst > 0


def test_a_perturbed_member_actually_runs_and_differs(steady_track, forcing_files):
    """Regression: OpenDrift's add_reader does an isinstance check, so a proxy
    object around a reader is rejected outright. That once made every perturbed
    ensemble member fail silently -- the failures were caught and skipped
    further up, so the ensemble emptied itself while appearing to work.

    A perturbed member must run, and must land somewhere different.
    """
    currents, wind = forcing_files
    params = ReleaseParams(steady_track.t_start.replace(tzinfo=None) + timedelta(minutes=10), 1.0, 4.0)
    acquisition = steady_track.t_start + timedelta(hours=8)

    control = run_forward(steady_track, params, acquisition, currents, wind,
                          n_per_point=15, seed_rng=1)
    member = run_forward(steady_track, params, acquisition, currents, wind,
                         n_per_point=15, seed_rng=1,
                         current_scale=1.15, wind_scale=0.85, wind_rotate_deg=12.0)

    control_lon, control_lat, _ = control.surface_at(len(control.times) - 1)
    member_lon, member_lat, _ = member.surface_at(len(member.times) - 1)

    assert member_lon.size > 0, "the perturbed member produced no particles"
    assert member.diagnostics["current_scale"] == 1.15
    assert member.diagnostics["wind_rotate_deg"] == 12.0

    shift_km = np.hypot(
        (float(member_lon.mean()) - float(control_lon.mean())) * 111.0,
        (float(member_lat.mean()) - float(control_lat.mean())) * 111.0,
    )
    assert shift_km > 0.05, (
        f"perturbing the forcing moved the slick by only {shift_km:.4f} km — "
        "the perturbation is not reaching the physics"
    )


def test_a_later_acquisition_gives_a_wider_cloud(steady_track, forcing_files):
    """Physical sanity, and the mechanism behind 'the posterior widens as the
    slick ages'."""
    currents, wind = forcing_files
    params = ReleaseParams(steady_track.t_start.replace(tzinfo=None) + timedelta(minutes=10), 1.0, 4.0)

    spreads = []
    for hours in (4, 12):
        result = run_forward(
            steady_track, params, steady_track.t_start + timedelta(hours=hours),
            currents, wind, n_per_point=20, seed_rng=1,
        )
        lon, lat, _ = result.surface_at(len(result.times) - 1)
        spreads.append(float(np.hypot(lon.std() * 111.0, lat.std() * 111.0)))

    assert spreads[1] > spreads[0], f"cloud did not widen with age: {spreads}"
