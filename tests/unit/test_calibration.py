"""Calibration numbers are computed from the data, never hardcoded."""
from __future__ import annotations

import numpy as np
import pytest

from core.score.calibrate import (
    brier_score,
    expected_calibration_error,
    fit,
    reliability_bins,
    uncalibrated_report,
)


def _overconfident(n=400, seed=0):
    rng = np.random.default_rng(seed)
    truth = (rng.random(n) < 0.65).astype(float)
    raw = np.where(truth == 1, rng.beta(9, 1.2, n), rng.beta(6, 2.0, n))
    return raw, truth


def test_isotonic_calibration_reduces_ece_on_held_out_data():
    raw, truth = _overconfident()
    before = uncalibrated_report(raw, truth)
    report, _ = fit(raw, truth, notes="unit test")
    assert report.ece < before["expected_calibration_error"], (
        f"ECE did not improve: {before['expected_calibration_error']} -> {report.ece}"
    )


def test_metrics_change_when_the_input_set_changes():
    """AC-17: if these were constants, two different sets would give one answer."""
    a, ta = _overconfident(seed=1)
    b, tb = _overconfident(seed=2)
    ra, _ = fit(a, ta)
    rb, _ = fit(b, tb)
    assert (ra.brier, ra.ece) != (rb.brier, rb.ece)


def test_a_perfect_predictor_scores_zero_brier():
    truth = np.array([1.0, 0.0] * 20)
    assert brier_score(truth.copy(), truth) == 0.0


def test_bins_report_their_own_counts():
    probabilities = np.linspace(0.0, 1.0, 100)
    outcomes = (probabilities > 0.5).astype(float)
    bins = reliability_bins(probabilities, outcomes, n_bins=10)
    assert len(bins) == 10
    assert sum(b["count"] for b in bins) == 100
    for entry in bins:
        if entry["count"] == 0:
            assert entry["mean_predicted"] is None
        else:
            assert 0.0 <= entry["observed_frequency"] <= 1.0


def test_ece_is_zero_for_a_perfectly_calibrated_predictor():
    rng = np.random.default_rng(3)
    probabilities = rng.uniform(0.05, 0.95, 20000)
    outcomes = (rng.random(20000) < probabilities).astype(float)
    assert expected_calibration_error(probabilities, outcomes, 10) < 0.02


def test_too_few_cases_is_refused_rather_than_guessed():
    with pytest.raises(ValueError, match="at least 10"):
        fit(np.array([0.5, 0.6]), np.array([1.0, 0.0]))
