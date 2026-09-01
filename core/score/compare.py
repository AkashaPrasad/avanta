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
    """The envelope an unobserved source's oil could plausibly occupy.

    This is the support for H0, and how wide it is decides whether the system
    can ever decline to accuse anyone. Dilating by about the slick's own size
    concentrates the null exactly where the oil is, so H0 explains the
    observation nearly perfectly and beats genuine candidates on well-defined
    slicks -- a null fitted to the very thing it is an alternative to. Spreading
    it far too wide has the opposite failure: H0 can never win and the system
    always names somebody.

    So the envelope is several times the slick's extent, which is what "oil from
    a source we never saw" actually implies: it could be anywhere in this
    neighbourhood, and the fact that it is precisely here is what a named
    candidate has to explain better.

    Computed with a distance transform rather than a morphological dilation. A
    structuring element three times the slick's extent is larger than the grid
    itself -- a 459x459 kernel over a 256x256 image -- which scipy answers with
    a MemoryError. The distance transform is O(n) in the grid size regardless of
    radius and gives an identical result, a true Euclidean disc rather than the
    square a box kernel would produce.

    This is a support region, not a trajectory. Nothing here runs time backwards.
    """
    from scipy.ndimage import distance_transform_edt

    if not grid.mask.any():
        return np.ones(grid.shape, dtype=bool)

    rows, cols = np.nonzero(grid.mask)
    extent = max(int(np.ptp(rows)), int(np.ptp(cols)), 4)
    factor = float(settings()["score"].get("null_envelope_extents", 3.0))
    radius = float(dilate_cells if dilate_cells is not None else max(3.0, extent * factor / 2.0))
    # Cap the envelope so it cannot swallow the whole grid. Past that point the
    # null is uniform over everything, which is the weak null this replaced --
    # any candidate landing oil anywhere near the slick beats it, and the system
    # loses the ability to decline. The cap is a fraction of the grid diagonal.
    diagonal = float(np.hypot(*grid.shape))
    radius = min(radius, diagonal * float(settings()["score"].get("null_envelope_max_diag", 0.28)))

    # Distance from every cell to the nearest slick cell.
    distance = distance_transform_edt(~grid.mask)
    region = distance <= radius
    # The envelope must never collapse to the slick, nor swallow the whole grid
    # so completely that H0 becomes unbeatable.
    if not region.any():
        return grid.mask.copy()
    return region


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
