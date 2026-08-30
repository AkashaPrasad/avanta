"""Put a simulation and an observation on the same grid and score them.

This module exists so that the downsampling factor, the smoothing kernel and
the likelihood temperature can never drift apart. They are three views of one
decision -- how finely the comparison is resolved -- and getting them out of
step silently changes every probability the system reports.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from rasterio.transform import Affine

from core.config import settings
from core.score.likelihood import LikelihoodTerms, log_likelihood, null_log_likelihood
from core.simulate.rasterize import downsample, observed_mask, rasterize


@dataclass
class ComparisonGrid:
    """The coarse grid both the observation and every simulation are scored on."""

    mask: np.ndarray
    transform: Affine
    shape: tuple[int, int]
    factor: int
    sigma_px: float
    fine_shape: tuple[int, int]

    @property
    def n_slick_cells(self) -> int:
        return int(self.mask.sum())


def build_grid(polygons: list[list[list[float]]], transform: Affine, shape: tuple[int, int]) -> ComparisonGrid:
    cfg = settings()["score"]
    factor = max(1, int(cfg.get("likelihood_grid_downsample", 1)))
    fine = observed_mask(polygons, transform, shape)
    # Downsampling a boolean mask by block mean then thresholding at a half cell
    # keeps a coarse cell whenever the slick covers most of it, which avoids
    # inflating a thin slick's footprint.
    coarse = downsample(fine.astype(np.float32), factor) >= 0.5
    coarse_transform = transform * Affine.scale(float(factor), float(factor))
    return ComparisonGrid(
        mask=coarse,
        transform=coarse_transform,
        shape=coarse.shape,  # type: ignore[arg-type]
        factor=factor,
        sigma_px=float(cfg["kernel_sigma_px"]) / factor,
        fine_shape=shape,
    )


def simulated_density(
    grid: ComparisonGrid, lons: np.ndarray, lats: np.ndarray, weights: np.ndarray | None = None
) -> np.ndarray:
    return rasterize(
        lons, lats, grid.transform, grid.shape, weights=weights, sigma_px=grid.sigma_px
    )


def score_simulation(
    grid: ComparisonGrid, lons: np.ndarray, lats: np.ndarray, weights: np.ndarray | None = None
) -> tuple[LikelihoodTerms, np.ndarray]:
    density = simulated_density(grid, lons, lats, weights)
    return log_likelihood(density, grid.mask, sigma_px=grid.sigma_px), density


def feasibility_region(grid: ComparisonGrid, dilate_cells: int | None = None) -> np.ndarray:
    """Where an unobserved source's oil could plausibly be.

    Built by dilating the observed slick by its own extent: a source we never
    saw would have had to put oil in roughly this neighbourhood to produce what
    was observed. This is a support region for the null hypothesis, not a
    trajectory, and nothing about it runs time backwards.
    """
    from scipy.ndimage import binary_dilation

    if not grid.mask.any():
        return np.ones(grid.shape, dtype=bool)
    rows, cols = np.nonzero(grid.mask)
    extent = max(int(np.ptp(rows)), int(np.ptp(cols)), 4)
    radius = dilate_cells if dilate_cells is not None else max(3, extent // 2)
    size = 2 * radius + 1
    return binary_dilation(grid.mask, np.ones((size, size), dtype=bool))


def score_null(grid: ComparisonGrid) -> LikelihoodTerms:
    return null_log_likelihood(
        grid.mask, sigma_px=grid.sigma_px, feasibility=feasibility_region(grid)
    )


def difference_map(grid: ComparisonGrid, density: np.ndarray) -> dict[str, Any]:
    """Summary of where the simulation and the observation disagree, for the
    Observed / Simulated / Difference toggle in the UI."""
    inside = grid.mask
    total = float(density.sum()) or 1.0
    return {
        "explained_fraction": round(float(density[inside].sum()) / total, 4),
        "spilled_outside_fraction": round(float(density[~inside].sum()) / total, 4),
        "slick_cells": int(inside.sum()),
        "simulated_cells_above_noise": int((density > density.max() * 0.05).sum()) if density.max() > 0 else 0,
    }
