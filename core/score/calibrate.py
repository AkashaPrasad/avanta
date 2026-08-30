"""Calibration: is a stated probability of 0.7 right seven times in ten?

Accuracy and calibration are different properties and only one of them tells an
officer how much to trust a number. A system that ranks the true vessel first
90% of the time but reports 0.99 every time is accurate and badly calibrated,
and acting on it would mean treating a coin flip as a certainty.

Raw softmax posteriors over a likelihood summed across correlated pixels are
systematically overconfident. Isotonic regression -- monotonic, non-parametric,
fitted on held-out synthetic cases -- maps the raw number onto one that means
what it says. The reliability diagram is the evidence that it worked, and it is
computed from real runs, never hardcoded.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class CalibrationReport:
    n_cases: int
    brier: float
    ece: float
    bins: list[dict[str, Any]]
    isotonic_x: list[float]
    isotonic_y: list[float]
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_cases": self.n_cases,
            "brier_score": round(self.brier, 5),
            "expected_calibration_error": round(self.ece, 5),
            "bins": self.bins,
            "isotonic": {"x": self.isotonic_x, "y": self.isotonic_y},
            "notes": self.notes,
        }


def reliability_bins(probabilities: np.ndarray, outcomes: np.ndarray, n_bins: int = 10) -> list[dict[str, Any]]:
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bins: list[dict[str, Any]] = []
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        in_bin = (probabilities >= lo) & (probabilities < hi if hi < 1.0 else probabilities <= hi)
        count = int(in_bin.sum())
        bins.append(
            {
                "lo": round(float(lo), 3),
                "hi": round(float(hi), 3),
                "count": count,
                "mean_predicted": round(float(probabilities[in_bin].mean()), 4) if count else None,
                "observed_frequency": round(float(outcomes[in_bin].mean()), 4) if count else None,
            }
        )
    return bins


def expected_calibration_error(probabilities: np.ndarray, outcomes: np.ndarray, n_bins: int = 10) -> float:
    total = len(probabilities)
    if total == 0:
        return 0.0
    error = 0.0
    for entry in reliability_bins(probabilities, outcomes, n_bins):
        if entry["count"] == 0:
            continue
        error += (entry["count"] / total) * abs(entry["mean_predicted"] - entry["observed_frequency"])
    return float(error)


def brier_score(probabilities: np.ndarray, outcomes: np.ndarray) -> float:
    if len(probabilities) == 0:
        return 0.0
    return float(np.mean((probabilities - outcomes) ** 2))


def fit(
    probabilities: np.ndarray,
    outcomes: np.ndarray,
    *,
    holdout_fraction: float = 0.5,
    n_bins: int = 10,
    notes: str = "",
    seed: int = 0,
) -> tuple[CalibrationReport, Any]:
    """Fit isotonic regression on one split and report metrics on the other.

    Reporting calibration on the same data the mapping was fitted on would
    report the fit, not the calibration.
    """
    from sklearn.isotonic import IsotonicRegression

    probabilities = np.asarray(probabilities, dtype=float)
    outcomes = np.asarray(outcomes, dtype=float)
    n = len(probabilities)
    if n < 10:
        raise ValueError(f"Calibration needs at least 10 cases; got {n}.")

    rng = np.random.default_rng(seed)
    order = rng.permutation(n)
    split = int(n * (1.0 - holdout_fraction))
    train, test = order[:split], order[split:]

    model = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    model.fit(probabilities[train], outcomes[train])
    calibrated = model.predict(probabilities[test])

    report = CalibrationReport(
        n_cases=int(len(test)),
        brier=brier_score(calibrated, outcomes[test]),
        ece=expected_calibration_error(calibrated, outcomes[test], n_bins),
        bins=reliability_bins(calibrated, outcomes[test], n_bins),
        isotonic_x=[round(float(v), 5) for v in model.X_thresholds_],
        isotonic_y=[round(float(v), 5) for v in model.y_thresholds_],
        notes=notes,
    )
    return report, model


def uncalibrated_report(probabilities: np.ndarray, outcomes: np.ndarray, n_bins: int = 10) -> dict[str, Any]:
    """The same metrics before calibration, so the effect of the mapping is visible."""
    probabilities = np.asarray(probabilities, dtype=float)
    outcomes = np.asarray(outcomes, dtype=float)
    return {
        "brier_score": round(brier_score(probabilities, outcomes), 5),
        "expected_calibration_error": round(expected_calibration_error(probabilities, outcomes, n_bins), 5),
        "bins": reliability_bins(probabilities, outcomes, n_bins),
        "n_cases": int(len(probabilities)),
    }
