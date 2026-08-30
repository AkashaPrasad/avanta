"""Stage A narrows the field geometrically, and shows every term it used."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.ais.tracks import Fix, build_track
from core.hypothesis.prefilter import SlickGeometry, prefilter

ACQ = datetime(2025, 5, 26, 12, 0, tzinfo=timezone.utc)


def _track(mmsi, lon0, lat0, dlon, dlat, start_hours_before=8.0, n=24):
    start = ACQ - timedelta(hours=start_hours_before)
    return build_track(
        mmsi,
        [Fix(start + timedelta(minutes=10 * i), lon0 + dlon * i, lat0 + dlat * i, 11.0, 45.0)
         for i in range(n)],
    )


@pytest.fixture
def slick():
    # Elongated roughly north-east from 76.10, 9.32
    return SlickGeometry(76.10, 9.32, 45.0, 20.0, 12.0, ACQ)


def test_every_term_is_returned_with_its_value(slick):
    results = prefilter([_track("1", 76.00, 9.25, 0.004, 0.004)], slick)
    assert results
    names = {t.name for t in results[0].terms}
    assert names == {"d_perp_km", "align", "t_feasible", "upstream"}
    for term in results[0].terms:
        assert term.explanation, "a term without an explanation is a black box"


def test_an_aligned_nearby_track_outscores_a_perpendicular_one(slick):
    aligned = _track("aligned", 76.02, 9.26, 0.004, 0.004)      # along the slick axis
    across = _track("across", 76.05, 9.45, 0.004, -0.004)       # perpendicular
    results = {r.mmsi: r for r in prefilter([aligned, across], slick)}
    assert results["aligned"].total_score > results["across"].total_score


def test_a_vessel_that_could_not_reach_the_slick_is_vetoed(slick):
    """Beyond the feasibility cone no amount of alignment rescues a hypothesis."""
    far = _track("far", 70.0, 5.0, 0.004, 0.004, start_hours_before=1.0)
    results = prefilter([far], slick)
    assert results == [] or results[0].total_score == 0.0


def test_a_track_entirely_after_the_acquisition_is_not_feasible(slick):
    later = build_track(
        "later",
        [Fix(ACQ + timedelta(minutes=10 * i), 76.05 + 0.003 * i, 9.28 + 0.003 * i, 11.0, 45.0)
         for i in range(10)],
    )
    results = prefilter([later], slick)
    assert not results or results[0].total_score == 0.0


def test_keep_top_k_is_honoured(slick):
    tracks = [_track(str(i), 76.00 + 0.002 * i, 9.25 + 0.002 * i, 0.004, 0.004) for i in range(15)]
    results = prefilter(tracks, slick, keep_top_k=4)
    assert sum(1 for r in results if r.kept) <= 4


def test_results_are_ordered_by_score(slick):
    tracks = [_track(str(i), 76.00 + 0.01 * i, 9.25 + 0.01 * i, 0.004, 0.004) for i in range(8)]
    scores = [r.total_score for r in prefilter(tracks, slick)]
    assert scores == sorted(scores, reverse=True)
