"""Ensemble simulation.

A single deterministic run would give a single sharp answer, and that answer
would be a lie: neither the wind field, the current field, nor the wind drift
factor is known exactly, and the further back the release, the more those
uncertainties compound.

Running an ensemble over perturbed forcing is what makes the posterior widen as
a slick ages instead of staying falsely sharp -- which is the difference between
a tool that says "0.71, and here is how sure I am" and one that says "0.71" and
cannot be challenged.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from core.ais.tracks import Track
from core.config import settings
from core.simulate.line_source import ReleaseParams
from core.simulate.openoil_runner import SimulationResult, run_forward


@dataclass
class EnsembleMember:
    index: int
    result: SimulationResult
    perturbation: dict[str, float]


def perturbations(n: int, rng: np.random.Generator) -> list[dict[str, float]]:
    """Draw n forcing perturbations. Member 0 is always unperturbed so the
    ensemble contains the control run."""
    cfg = settings()["simulate"]["ensemble_perturbation"]
    base = float(settings()["simulate"]["wind_drift_factor"])
    diffusivity = float(settings()["simulate"]["horizontal_diffusivity"])
    out: list[dict[str, float]] = [
        {
            "wind_scale": 1.0,
            "wind_rotate_deg": 0.0,
            "current_scale": 1.0,
            "wind_drift_factor": base,
            "horizontal_diffusivity": diffusivity,
        }
    ]
    lo_wdf, hi_wdf = cfg["wind_drift_factor_range"]
    lo_d, hi_d = cfg["diffusivity_range"]
    for _ in range(max(0, n - 1)):
        out.append(
            {
                "wind_scale": float(1.0 + rng.normal(0.0, cfg["wind_speed_frac"])),
                "wind_rotate_deg": float(rng.normal(0.0, cfg["wind_direction_deg"])),
                "current_scale": float(1.0 + rng.normal(0.0, cfg["current_frac"])),
                "wind_drift_factor": float(rng.uniform(lo_wdf, hi_wdf)),
                "horizontal_diffusivity": float(rng.uniform(lo_d, hi_d)),
            }
        )
    return out


def run_ensemble(
    track: Track,
    params: ReleaseParams,
    acquisition: datetime,
    currents_path: Path,
    wind_path: Path,
    *,
    n_members: int | None = None,
    n_per_point: int | None = None,
    seed: int = 0,
    progress: Callable[[int, int], None] | None = None,
) -> list[EnsembleMember]:
    n = n_members if n_members is not None else int(settings()["simulate"]["n_ensemble"])
    rng = np.random.default_rng(seed)
    members: list[EnsembleMember] = []
    for index, perturbation in enumerate(perturbations(n, rng)):
        result = run_forward(
            track,
            params,
            acquisition,
            currents_path,
            wind_path,
            n_per_point=n_per_point,
            wind_drift_factor=perturbation["wind_drift_factor"],
            horizontal_diffusivity=perturbation["horizontal_diffusivity"],
            current_scale=perturbation["current_scale"],
            wind_scale=perturbation["wind_scale"],
            wind_rotate_deg=perturbation["wind_rotate_deg"],
            seed_rng=seed * 1000 + index,
        )
        members.append(EnsembleMember(index, result, perturbation))
        if progress is not None:
            progress(index + 1, n)
    return members


def summarise(values: list[float]) -> dict[str, Any]:
    """Median and a 90% credible interval across ensemble members."""
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    if array.size == 0:
        return {"median": 0.0, "lo": 0.0, "hi": 0.0, "n": 0, "width": 0.0}
    lo, hi = np.percentile(array, [5, 95])
    return {
        "median": float(np.median(array)),
        "lo": float(lo),
        "hi": float(hi),
        "n": int(array.size),
        "width": float(hi - lo),
    }
