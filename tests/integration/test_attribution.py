"""End-to-end attribution: the evidence adds up, and the system can decline."""
from __future__ import annotations

import json
from datetime import timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from core.score.attribute import run_attribution
from core.score.compare import ComparisonGrid
from core.simulate.line_source import ReleaseParams
from core.simulate.openoil_runner import run_forward
from core.simulate.rasterize import rasterize

# tests/integration/test_attribution.py -> parents[2] is the repository root.
SYNTHETIC_SET = Path(__file__).resolve().parents[2] / "fixtures" / "scenarios" / "synthetic_set.json"


@pytest.fixture(scope="module")
def attribution_run(forcing_files, steady_track):
    """Build a small ground-truth case and attribute it.

    One vessel is the true source; two decoys run parallel tracks offset from
    it. The observed slick is generated under one forcing realisation and
    attributed under another, which is the only arrangement that tests the
    method rather than the code's self-consistency.
    """
    from rasterio.transform import from_bounds

    from core.ais.tracks import Fix, build_track

    currents, wind = forcing_files
    t0 = steady_track.t_start
    truth = ReleaseParams(t0.replace(tzinfo=None) + timedelta(minutes=10), 1.5, 4.0)
    acquisition = t0 + timedelta(hours=6)

    # Forcing realisation A generates the observation.
    sim = run_forward(
        steady_track, truth, acquisition, currents, wind,
        n_per_point=25, wind_drift_factor=0.032, horizontal_diffusivity=12.0,
        current_scale=1.08, wind_scale=0.94, wind_rotate_deg=6.0, seed_rng=99,
    )
    lon, lat, mass = sim.surface_at(len(sim.times) - 1)
    if lon.size < 40:
        pytest.skip("the truth simulation retained too few particles to form a slick")

    shape = (256, 256)
    transform = from_bounds(75.6, 8.9, 76.5, 9.8, shape[1], shape[0])
    density = rasterize(lon, lat, transform, shape, weights=mass, sigma_px=2.0)
    mask = density > density.max() * 0.18
    if mask.sum() < 30:
        pytest.skip("the generated slick mask is too small to score against")

    grid = ComparisonGrid(mask=mask, transform=transform, shape=shape,
                          factor=1, sigma_px=2.0, fine_shape=shape)

    decoys = []
    for index, (dlon, dlat) in enumerate(((0.06, -0.05), (-0.07, 0.06))):
        decoys.append(build_track(
            f"decoy{index}",
            [Fix(f.t, f.lon + dlon, f.lat + dlat, f.sog_kn, f.cog_deg) for f in steady_track.fixes],
            name=f"DECOY {index}", ship_type="cargo",
        ))

    # Forcing realisation B attributes it (the readers as delivered).
    result = run_attribution(
        [steady_track, *decoys], grid, acquisition, currents, wind,
        n_ensemble=2, n_per_point=15,
    )
    return result, steady_track.mmsi, grid, acquisition, currents, wind, decoys


def test_evidence_terms_sum_to_score(attribution_run):
    """AC-14. If the panel's numbers do not add up to the reported log-score,
    it is decoration rather than an audit trail."""
    result, _, _, _, _, _, _ = attribution_run
    assert result.candidates, "no candidate produced evidence"

    for candidate in result.candidates:
        breakdown = candidate.evidence_breakdown()
        assert breakdown["terms"], "a candidate with no terms is a black box"
        total = sum(term["value"] for term in breakdown["terms"])
        assert abs(total - breakdown["score"]) < 1e-5, (
            f"{candidate.mmsi}: terms sum to {total} but the score is {breakdown['score']}"
        )
        assert abs(breakdown["log_likelihood"] + breakdown["log_prior"] - breakdown["score"]) < 1e-5
        for term in breakdown["terms"]:
            assert term["group"] in {"likelihood", "prior"}
            assert term["explanation"], f"term {term['name']} does not explain itself"


def test_posterior_is_a_proper_distribution(attribution_run):
    result, _, _, _, _, _, _ = attribution_run
    payload = result.to_dict()
    assert abs(payload["posterior"]["sums_to"] - 1.0) < 1e-6
    assert any(e["is_null"] for e in payload["posterior"]["entries"]), "H0 must be a row"


def test_true_vessel_outranks_decoys(attribution_run):
    """The offender's own track must explain its own slick better than a track
    running parallel to it."""
    result, true_mmsi, _, _, _, _, _ = attribution_run
    named = [e for e in result.posterior.entries if not e.is_null]
    assert named, "no named hypothesis survived"
    assert named[0].hypothesis_id == true_mmsi, (
        f"ranked {named[0].hypothesis_id} above the true source {true_mmsi}"
    )


def test_negative_control(attribution_run):
    """AC-11, and the most important assertion in the suite.

    Remove the true vessel and re-attribute. A system that still confidently
    accuses a runner-up is worse than useless — it means the probability was
    never conditional on the evidence, only on the shape of the candidate list.
    """
    _, _, grid, acquisition, currents, wind, decoys = attribution_run

    without_truth = run_attribution(
        decoys, grid, acquisition, currents, wind, n_ensemble=2, n_per_point=15,
    )
    assert without_truth.posterior.p_null > 0.5, (
        f"with the true vessel removed, p(H0) was only {without_truth.posterior.p_null:.3f} — "
        "the system accused a vessel it had no evidence against"
    )
    assert without_truth.posterior.no_attribution
    assert without_truth.posterior.entries[0].is_null, "H0 must top the ranking here"


@pytest.mark.skipif(not SYNTHETIC_SET.exists(), reason="no generated synthetic set on disk")
def test_synthetic_set_meets_its_targets():
    """The generated validation set, if one has been built, must hit the
    published targets: rank-1 in at least 80% of cases, and p(H0) > 0.5 in every
    negative control."""
    payload = json.loads(SYNTHETIC_SET.read_text(encoding="utf-8"))
    if payload["n_cases"] < 3:
        pytest.skip(f"only {payload['n_cases']} cases generated; not enough to assert on")

    assert payload["top1_accuracy"] >= 0.8, (
        f"top-1 accuracy is {payload['top1_accuracy']:.1%}, below the 80% target"
    )
    if payload["n_negative_controls"] >= 2:
        assert payload["negative_control_pass_rate"] == 1.0, (
            "a negative control accused a vessel with the true source removed"
        )
    for case in payload["cases"]:
        assert 0.0 <= case["p_null"] <= 1.0
        assert case["true_rank"] is None or case["true_rank"] >= 1


def test_posterior_widens_with_age(forcing_files, steady_track):
    """AC-13 / §5.7: an older slick must produce a less certain answer.

    This is the assertion behind the claim that the posterior widens as a slick
    ages instead of staying falsely sharp. The mechanism is the ensemble: with
    the forcing perturbed, members diverge further the longer they integrate, so
    the likelihood marginalised over them flattens and the spread across members
    grows. If that does not happen, the ensemble is decorative and every stated
    credible interval is meaningless -- so the test asserts on the spread the
    system actually reports, not on a proxy.
    """
    from rasterio.transform import from_bounds

    from core.simulate.ensemble import summarise

    currents, wind = forcing_files
    t0 = steady_track.t_start
    truth = ReleaseParams(t0.replace(tzinfo=None) + timedelta(minutes=10), 1.0, 4.0)

    shape = (256, 256)
    transform = from_bounds(75.6, 8.9, 76.5, 9.8, shape[1], shape[0])

    widths: list[float] = []
    ages = (4, 12)
    for age_hours in ages:
        acquisition = t0 + timedelta(hours=age_hours)

        # The observed slick for this age, from one forcing realisation.
        sim = run_forward(
            steady_track, truth, acquisition, currents, wind,
            n_per_point=20, current_scale=1.08, wind_scale=0.94,
            wind_rotate_deg=6.0, seed_rng=7,
        )
        lon, lat, mass = sim.surface_at(len(sim.times) - 1)
        if lon.size < 30:
            pytest.skip(f"too few particles survived at {age_hours} h to form a slick")

        density = rasterize(lon, lat, transform, shape, weights=mass, sigma_px=2.0)
        mask = density > density.max() * 0.18
        if mask.sum() < 25:
            pytest.skip(f"the slick mask at {age_hours} h is too small to score")

        grid = ComparisonGrid(mask=mask, transform=transform, shape=shape,
                              factor=1, sigma_px=2.0, fine_shape=shape)

        result = run_attribution(
            [steady_track], grid, acquisition, currents, wind,
            n_ensemble=6, n_per_point=15,
        )
        assert result.candidates, f"no candidate scored at {age_hours} h"
        spread = summarise(result.candidates[0].per_member_log_likelihood)
        assert spread["n"] >= 3, "too few ensemble members survived to measure a spread"
        widths.append(spread["width"])

    assert widths[1] > widths[0], (
        f"the ensemble spread did not widen with slick age: "
        f"{ages[0]} h -> {widths[0]:.3f}, {ages[1]} h -> {widths[1]:.3f}. "
        "Either the forcing perturbation is not reaching the physics or the "
        "reported credible interval is not measuring uncertainty."
    )
