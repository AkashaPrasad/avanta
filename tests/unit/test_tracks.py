"""AC-7: tracks build correctly and a known gap is detected."""
from __future__ import annotations

from datetime import timedelta

from core.ais.tracks import course_over_ground, detect_gaps, resample, subtrack


def test_track_builds_in_time_order(steady_track):
    assert len(steady_track.fixes) == 30
    times = [f.t for f in steady_track.fixes]
    assert times == sorted(times)
    assert steady_track.t_end > steady_track.t_start


def test_no_gap_on_a_continuous_track(steady_track):
    assert steady_track.gaps == []


def test_known_two_hour_gap_is_detected(track_with_gap):
    assert len(track_with_gap.gaps) == 1
    gap = track_with_gap.gaps[0]
    assert 115 <= gap.minutes <= 125, f"expected ~120 minutes, got {gap.minutes}"


def test_gap_overlap_with_a_window(track_with_gap):
    gap = track_with_gap.gaps[0]
    window_start = gap.start + timedelta(minutes=30)
    window_end = gap.start + timedelta(minutes=90)
    assert gap.overlap_minutes(window_start, window_end) == 60.0


def test_resampling_does_not_bridge_a_gap(track_with_gap):
    """A position the vessel never transmitted is not evidence, so interpolation
    must not invent one across a transmission gap."""
    gap = track_with_gap.gaps[0]
    points = resample(track_with_gap, 5.0)
    inside = [f for f in points if gap.start < f.t < gap.end]
    assert inside == [], f"{len(inside)} interpolated fixes were invented inside a gap"


def test_subtrack_returns_the_release_window_only(steady_track):
    start = steady_track.t_start + timedelta(minutes=20)
    end = start + timedelta(minutes=40)
    vertices = subtrack(steady_track, start, end, 5.0)
    assert len(vertices) >= 5
    assert all(start <= v.t <= end for v in vertices)


def test_course_over_ground_is_north_east(steady_track):
    course = course_over_ground(steady_track.fixes)
    assert 30 < course < 70, f"expected a north-easterly course, got {course}"


def test_gap_threshold_is_configurable(steady_track):
    assert detect_gaps(steady_track.fixes, min_minutes=1.0), "5-minute steps exceed a 1-minute threshold"
    assert detect_gaps(steady_track.fixes, min_minutes=60.0) == []


def test_geojson_marks_gaps_as_their_own_segments(track_with_gap):
    collection = track_with_gap.to_geojson()
    segments = [f["properties"]["segment"] for f in collection["features"]]
    assert "transmitted" in segments
    assert "gap" in segments, "a gap must render as its own feature, not as a straight line"
