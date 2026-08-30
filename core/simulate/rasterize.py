"""Rasterise a simulated particle cloud onto the observed slick's own grid.

The comparison between simulation and observation only means anything if both
live on the same grid, in the same projection, at the same resolution. The
particle cloud is binned, kernel-smoothed to represent each particle as a small
patch of oil rather than a delta spike, and normalised to a probability density.
"""
from __future__ import annotations

import numpy as np
from rasterio.transform import Affine
from scipy.ndimage import gaussian_filter

from core.config import settings


def rasterize(
    lons: np.ndarray,
    lats: np.ndarray,
    transform: Affine,
    shape: tuple[int, int],
    *,
    weights: np.ndarray | None = None,
    sigma_px: float | None = None,
) -> np.ndarray:
    """Particle positions -> normalised density on the scene grid.

    Weighted by remaining oil mass when supplied, so a particle that has largely
    evaporated contributes less than one that has not.
    """
    sigma = sigma_px if sigma_px is not None else float(settings()["score"]["kernel_sigma_px"])
    inv = ~transform
    cols, rows = inv * (np.asarray(lons), np.asarray(lats))
    grid = np.zeros(shape, dtype=np.float32)
    r = np.round(np.asarray(rows)).astype(int)
    c = np.round(np.asarray(cols)).astype(int)
    ok = (r >= 0) & (r < shape[0]) & (c >= 0) & (c < shape[1])
    if weights is None:
        np.add.at(grid, (r[ok], c[ok]), 1.0)
    else:
        np.add.at(grid, (r[ok], c[ok]), np.asarray(weights, dtype=np.float32)[ok])
    grid = gaussian_filter(grid, sigma)
    total = float(grid.sum())
    return grid / total if total > 0 else grid


def observed_mask(polygons: list[list[list[float]]], transform: Affine, shape: tuple[int, int]) -> np.ndarray:
    """Burn slick polygons into a binary mask on the scene grid."""
    from rasterio.features import rasterize as rio_rasterize

    if not polygons:
        return np.zeros(shape, dtype=bool)
    shapes = [({"type": "Polygon", "coordinates": [poly]}, 1) for poly in polygons if len(poly) >= 4]
    if not shapes:
        return np.zeros(shape, dtype=bool)
    burned = rio_rasterize(shapes, out_shape=shape, transform=transform, fill=0, dtype="uint8")
    return burned.astype(bool)


def downsample(grid: np.ndarray, factor: int) -> np.ndarray:
    """Block-mean downsampling.

    The likelihood is evaluated on a coarser grid than the raster: at 10 m
    ground resolution neighbouring pixels are not independent observations, and
    summing a log-likelihood over a million correlated pixels manufactures
    confidence that is not there.
    """
    if factor <= 1:
        return grid
    h = (grid.shape[0] // factor) * factor
    w = (grid.shape[1] // factor) * factor
    trimmed = grid[:h, :w]
    return trimmed.reshape(h // factor, factor, w // factor, factor).mean(axis=(1, 3))
