"""Reading and conditioning a Sentinel-1 sigma0 raster.

Band layout is fixed by the evalscript in core/sar/ingest.py:
  0 VV dB   1 VH dB   2 VV-VH dB (the ratio, since a ratio in dB is a difference)
  3 dataMask
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import rasterio
from rasterio.transform import Affine
from scipy.ndimage import gaussian_filter, uniform_filter


@dataclass
class SarRaster:
    vv_db: np.ndarray
    vh_db: np.ndarray
    ratio_db: np.ndarray
    valid: np.ndarray
    transform: Affine
    crs: str
    bounds: tuple[float, float, float, float]

    @property
    def shape(self) -> tuple[int, int]:
        return self.vv_db.shape  # type: ignore[return-value]

    @property
    def coverage_fraction(self) -> float:
        """Fraction of the requested raster that actually carries data.

        Sentinel-1 returns the intersection of the request with the satellite's
        swath. A bbox placed off the pass comes back mostly empty, and a
        detector run over it will honestly find nothing -- which is easily
        misread as the sea being clean.
        """
        return float(self.valid.mean())

    def pixel_area_km2(self) -> float:
        """Approximate ground area of one pixel. The raster is in EPSG:4326, so
        a degree of longitude shrinks with latitude and we correct for it."""
        lat = 0.5 * (self.bounds[1] + self.bounds[3])
        deg_lat_km = 110.574
        deg_lon_km = 111.320 * float(np.cos(np.deg2rad(lat)))
        return abs(self.transform.a) * deg_lon_km * abs(self.transform.e) * deg_lat_km


def read_scene(path: str) -> SarRaster:
    with rasterio.open(path) as src:
        data = src.read().astype(np.float32)
        transform = src.transform
        crs = str(src.crs) if src.crs else "EPSG:4326"
        bounds = tuple(src.bounds)  # type: ignore[assignment]
    vv, vh, ratio = data[0], data[1], data[2]
    mask = data[3] > 0.5 if data.shape[0] > 3 else np.ones_like(vv, dtype=bool)
    # log(0) in the evalscript yields -inf; treat those as no-data rather than
    # letting them poison every downstream statistic.
    finite = np.isfinite(vv) & np.isfinite(vh)
    valid = mask & finite
    vv = np.where(finite, vv, np.nan)
    vh = np.where(finite, vh, np.nan)
    ratio = np.where(finite, ratio, np.nan)
    return SarRaster(vv, vh, ratio, valid, transform, crs, bounds)  # type: ignore[arg-type]


def despeckle(image: np.ndarray, valid: np.ndarray, sigma_px: float) -> np.ndarray:
    """Gaussian smoothing in dB space, ignoring no-data.

    Speckle in a SAR intensity image is multiplicative, which becomes additive in
    dB -- so smoothing the dB image is the right domain to do it in, and it is
    far cheaper than a refined-Lee filter at no meaningful cost in this pipeline
    because the downstream threshold is adaptive anyway.
    """
    filled = np.where(valid, np.nan_to_num(image, nan=0.0), 0.0)
    weight = valid.astype(np.float32)
    num = gaussian_filter(filled, sigma_px)
    den = gaussian_filter(weight, sigma_px)
    out = np.divide(num, den, out=np.zeros_like(num), where=den > 1e-6)
    return np.where(valid, out, np.nan)


def local_background(image: np.ndarray, valid: np.ndarray, window_px: int) -> np.ndarray:
    """Mean dB over a large window, ignoring no-data. This is the reference the
    adaptive threshold measures darkness against, so that a slick is found by
    contrast to its own surroundings rather than an absolute dB value that
    changes with incidence angle across the swath."""
    filled = np.where(valid, np.nan_to_num(image, nan=0.0), 0.0)
    weight = valid.astype(np.float32)
    num = uniform_filter(filled, size=window_px, mode="nearest")
    den = uniform_filter(weight, size=window_px, mode="nearest")
    return np.divide(num, den, out=np.zeros_like(num), where=den > 1e-6)


def pixel_to_lonlat(transform: Affine, rows: np.ndarray, cols: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lon, lat = transform * (cols + 0.5, rows + 0.5)
    return np.asarray(lon), np.asarray(lat)


def lonlat_to_pixel(transform: Affine, lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    inv = ~transform
    cols, rows = inv * (np.asarray(lon), np.asarray(lat))
    return np.asarray(rows), np.asarray(cols)
