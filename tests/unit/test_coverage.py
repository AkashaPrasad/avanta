"""Scene coverage: whether we actually looked, as distinct from what we saw."""
from __future__ import annotations

import numpy as np
import pytest

from core.sar.coverage import evaluate


def test_a_mostly_empty_raster_is_reported_as_insufficient():
    """The failure this guards against: a bbox placed off the satellite's swath
    comes back 82% no-data, the detector honestly finds nothing, and the console
    reads as 'this area is clean'."""
    coverage = evaluate(0.183)
    assert not coverage.sufficient
    assert "18%" in coverage.verdict
    assert "never imaged" in coverage.verdict


def test_a_full_raster_is_sufficient():
    coverage = evaluate(0.97)
    assert coverage.sufficient
    assert "97%" in coverage.verdict
    assert "informative" in coverage.verdict


@pytest.mark.parametrize("fraction", [0.0, 0.25, 0.5999])
def test_below_the_threshold_is_always_refused(fraction):
    assert not evaluate(fraction).sufficient


@pytest.mark.parametrize("fraction", [0.60, 0.8, 1.0])
def test_at_or_above_the_threshold_is_accepted(fraction):
    assert evaluate(fraction).sufficient


def test_the_measured_number_is_always_reported():
    payload = evaluate(0.42).to_dict()
    assert payload["percent"] == 42.0
    assert payload["min_fraction"] == 0.6
    assert payload["sufficient"] is False


def test_coverage_fraction_is_computed_from_the_valid_mask():
    from rasterio.transform import from_bounds

    from core.sar.preprocess import SarRaster

    shape = (100, 100)
    valid = np.zeros(shape, dtype=bool)
    valid[:30, :] = True  # 30% imaged
    raster = SarRaster(
        vv_db=np.zeros(shape), vh_db=np.zeros(shape), ratio_db=np.zeros(shape),
        valid=valid, transform=from_bounds(70, 18, 71, 19, shape[1], shape[0]),
        crs="EPSG:4326", bounds=(70.0, 18.0, 71.0, 19.0),
    )
    assert abs(raster.coverage_fraction - 0.30) < 1e-9
    assert not evaluate(raster.coverage_fraction).sufficient
