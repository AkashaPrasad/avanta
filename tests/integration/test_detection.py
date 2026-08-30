"""AC-5: segmentation on a real Sentinel-1 scene, with reasoning attached."""
from __future__ import annotations

import json

import pytest

from core.config import fixtures_dir
from core.sar.preprocess import read_scene
from core.sar.segment_classical import CLASS_LOOKALIKE, CLASS_OIL, segment


@pytest.fixture(scope="module")
def golden_raster():
    scenes = sorted((fixtures_dir() / "scenes").glob("*.tif"))
    if not scenes:
        pytest.skip("no bundled scene; run scripts/seed_fixtures.py")
    return read_scene(str(scenes[0]))


def test_segmentation_on_golden_scene(golden_raster):
    """Runs on a real calibrated Sentinel-1 raster and produces georeferenced
    regions inside the scene bounds."""
    detection = segment(golden_raster)
    assert detection.regions, "no region was segmented from the golden scene"
    west, south, east, north = golden_raster.bounds
    for region in detection.regions:
        lon, lat = region.centroid_lonlat
        assert west <= lon <= east and south <= lat <= north, "region centroid is outside the scene"
        assert region.area_km2 > 0
        assert len(region.polygon) >= 4, "a polygon needs at least four positions"
        assert region.polygon[0] == region.polygon[-1], "the ring must be closed"
        assert region.label in {CLASS_OIL, CLASS_LOOKALIKE}


def test_polygons_are_valid_rfc7946_geojson(golden_raster):
    detection = segment(golden_raster)
    collection = detection.to_geojson()
    assert collection["type"] == "FeatureCollection"
    for feature in collection["features"]:
        assert feature["geometry"]["type"] == "Polygon"
        ring = feature["geometry"]["coordinates"][0]
        assert all(-180 <= c[0] <= 180 and -90 <= c[1] <= 90 for c in ring)
    # PostgreSQL's JSON type follows RFC 8259 and refuses NaN/Infinity.
    json.dumps(collection, allow_nan=False)
    for feature in collection["features"]:
        assert feature["properties"]["features"]["infrastructure_distance_km"] is None


def test_lookalike_features_reported(golden_raster):
    """Every classification decision names the tests that produced it, with the
    value, the threshold and the weight."""
    detection = segment(golden_raster)
    assert detection.regions
    for region in detection.regions:
        assert region.reasons, "a region with no reasons is a black box"
        for reason in region.reasons:
            assert {"feature", "threshold", "weight", "supports", "note"} <= set(reason)
            assert reason["supports"] in {"oil", "look_alike"}
            assert reason["note"], "every test must explain itself"
        # The reported confidence must be the weighted vote actually taken.
        total = sum(r["weight"] for r in region.reasons)
        passed = sum(r["weight"] for r in region.reasons if r["passed"])
        assert abs(region.confidence - passed / total) < 1e-6


def test_land_and_inland_water_are_excluded(golden_raster):
    """The Kerala backwaters sit beside the validation scene and look exactly
    like calm sea to a radar."""
    from global_land_mask import globe

    from core.sar.segment_classical import _land_mask

    land = _land_mask(golden_raster)
    detection = segment(golden_raster)
    for region in detection.regions:
        lon, lat = region.centroid_lonlat
        assert not bool(globe.is_land(lat, lon)), "a region was detected over land"
    assert land.any(), "the validation scene contains coastline, so the mask must be non-empty"
