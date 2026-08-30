"""How well does a simulated slick explain the observed one?

    logL(v, θ) = Σ_{x ∈ M} w(x)·log[(1−ε)·p_{v,θ}(x) + ε·u(x)]
                 − β · Σ_x p_{v,θ}(x)·(1 − M(x))

Two terms, and both are needed.

The first asks how much simulated oil density sits under the pixels where oil
was actually seen. The ε-mixture with a uniform background is a robustness
floor: without it, one observed pixel that the simulation happens to miss sends
the whole log-likelihood to −∞ and a single speckle artefact can exonerate a
vessel outright.

The second is the term most such systems leave out. A simulation that floods the
entire search box with oil would score perfectly on the first term while
explaining nothing, so simulated oil that lands where no oil was observed is
penalised. β sets the exchange rate between the two, and it is a published
config value because it is a genuine modelling choice, not a constant of nature.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from core.config import settings


@dataclass
class LikelihoodTerms:
    log_likelihood: float          # after tempering; this is what the posterior uses
    raw_log_likelihood: float      # before tempering
    coverage_term: float
    false_area_term: float
    overlap_fraction: float
    simulated_mass_in_mask: float
    n_mask_cells: int
    effective_n: float
    temperature: float
    epsilon: float
    beta: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "log_likelihood": round(self.log_likelihood, 4),
            "raw_log_likelihood": round(self.raw_log_likelihood, 4),
            "coverage_term": round(self.coverage_term, 4),
            "false_area_term": round(self.false_area_term, 4),
            "overlap_fraction": round(self.overlap_fraction, 4),
            "simulated_density_in_mask": round(self.simulated_mass_in_mask, 4),
            "n_mask_cells": self.n_mask_cells,
            "effective_n": round(self.effective_n, 2),
            "temperature": round(self.temperature, 3),
            "epsilon": self.epsilon,
            "beta": self.beta,
        }


def independent_observations(mask: np.ndarray) -> float:
    """How many genuinely independent constraints an observed slick supplies.

    Not the pixel count. Neighbouring pixels of one slick are not separate
    pieces of evidence about which vessel produced it -- the errors that matter
    here (the wind field, the current field, the release timing, the
    segmentation boundary) are correlated across the whole feature, so they do
    not average away with more pixels.

    What a slick actually constrains is its position, its orientation and its
    extent. For an elongated feature the number of independent constraints is
    approximately its aspect ratio: a 20 km by 2 km slick pins down roughly ten
    resolution elements along its own axis, and a compact blob pins down very
    few. Treating a million correlated pixels as a million observations is how a
    tool ends up reporting 0.9999 for whichever vessel happened to be nearest.

    Clamped to a sane band because a degenerate mask must not produce either
    infinite confidence or none at all.
    """
    cells = float(mask.sum())
    if cells <= 0:
        return 1.0
    rows, cols = np.nonzero(mask)
    if rows.size < 3:
        return 1.0
    coords = np.stack([rows - rows.mean(), cols - cols.mean()])
    eigenvalues = np.linalg.eigvalsh(np.cov(coords))
    major = float(np.sqrt(max(eigenvalues[-1], 1e-9)))
    minor = float(np.sqrt(max(eigenvalues[0], 1e-9)))
    aspect = major / max(minor, 1e-6)
    return float(np.clip(aspect, 3.0, 40.0))


def temperature(mask: np.ndarray) -> float:
    """Cells per independent observation: what the log-likelihood is divided by."""
    configured = settings()["score"].get("likelihood_temperature", "auto")
    if configured != "auto":
        return max(1.0, float(configured))
    cells = float(mask.sum())
    return max(1.0, cells / independent_observations(mask))


def log_likelihood(
    simulated: np.ndarray,
    mask: np.ndarray,
    *,
    weights: np.ndarray | None = None,
    epsilon: float | None = None,
    beta: float | None = None,
    sigma_px: float | None = None,  # accepted for call-site symmetry; unused
) -> LikelihoodTerms:
    cfg = settings()["score"]
    eps = float(epsilon if epsilon is not None else cfg["epsilon"])
    b = float(beta if beta is not None else cfg["beta"])
    temp = temperature(mask)

    area = float(mask.size)
    uniform = 1.0 / area
    density = simulated.astype(np.float64)
    total = density.sum()
    if total > 0:
        density = density / total

    inside = mask.astype(bool)
    n_cells = int(inside.sum())
    if n_cells == 0:
        # No observed slick: every hypothesis is equally unsupported, and saying
        # so is more useful than returning a number that looks like evidence.
        return LikelihoodTerms(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, temp, eps, b)

    w = np.ones(n_cells) if weights is None else weights[inside].astype(np.float64)
    mixed = (1.0 - eps) * density[inside] + eps * uniform
    coverage = float(np.sum(w * np.log(mixed)))

    outside_mass = float(density[~inside].sum())
    false_area = -b * outside_mass * n_cells

    raw = coverage + false_area
    return LikelihoodTerms(
        log_likelihood=raw / temp,
        raw_log_likelihood=raw,
        coverage_term=coverage / temp,
        false_area_term=false_area / temp,
        overlap_fraction=float(density[inside].sum()),
        simulated_mass_in_mask=float(density[inside].sum()),
        n_mask_cells=n_cells,
        effective_n=n_cells / temp,
        temperature=temp,
        epsilon=eps,
        beta=b,
    )


def null_log_likelihood(
    mask: np.ndarray,
    *,
    epsilon: float | None = None,
    beta: float | None = None,
    sigma_px: float | None = None,
    feasibility: np.ndarray | None = None,
) -> LikelihoodTerms:
    """The H0 likelihood: oil from a source that is somewhere in the search
    window but is none of the observed candidates.

    Spreading that oil uniformly over the *entire* scene makes H0 far too weak.
    A vessel only has to land some oil anywhere near the slick to beat it, so
    the system ends up naming a runner-up in exactly the situation the null
    exists to prevent. The null is therefore uniform over the *feasibility
    region* -- the part of the scene an unobserved source could plausibly have
    reached -- which is both what §5.6 specifies and a much fairer competitor:
    it concentrates the same probability mass where the slick actually is.

    Passing no feasibility mask falls back to the whole scene, and that fallback
    is deliberately conservative in the direction of accusing someone less often
    being *harder*, so callers should supply one.
    """
    if feasibility is None:
        support = np.ones(mask.shape, dtype=bool)
    else:
        support = feasibility.astype(bool)
        if not support.any():
            support = np.ones(mask.shape, dtype=bool)

    density = np.zeros(mask.shape, dtype=np.float64)
    density[support] = 1.0 / float(support.sum())
    return log_likelihood(density, mask, epsilon=epsilon, beta=beta, sigma_px=sigma_px)
