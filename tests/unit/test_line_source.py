"""AC-8: seeding is a genuine moving line source."""
from __future__ import annotations

from datetime import timedelta

from core.simulate.line_source import ReleaseParams, build_seed, theta_grid


def test_seed_has_many_distinct_positions_and_times(steady_track):
    """The load-bearing assertion. A point source would give 1 and 1."""
    params = ReleaseParams(
        t_start=steady_track.t_start + timedelta(minutes=10),
        duration_hours=1.5,
        rate_m3_per_h=4.0,
    )
    seed = build_seed(steady_track, params, n_per_point=20)

    assert seed.distinct_positions() >= 5, "a line source must originate at multiple positions"
    assert seed.distinct_times() >= 5, "a line source must originate at multiple times"
    assert not seed.degenerate
    assert seed.n_elements == seed.n_vertices * 20


def test_each_particle_carries_its_own_origin_time(steady_track):
    params = ReleaseParams(steady_track.t_start + timedelta(minutes=10), 1.0, 4.0)
    seed = build_seed(steady_track, params, n_per_point=10)
    assert len(seed.time) == seed.n_elements
    assert len(seed.lon) == seed.n_elements
    # Times must advance along the track, not all be the release start.
    assert max(seed.time) > min(seed.time)


def test_seed_positions_advance_along_the_track(steady_track):
    params = ReleaseParams(steady_track.t_start + timedelta(minutes=10), 1.5, 4.0)
    seed = build_seed(steady_track, params, n_per_point=1)
    assert seed.lon[-1] > seed.lon[0], "the line source must follow the vessel's motion"
    assert seed.lat[-1] > seed.lat[0]


def test_single_position_track_is_flagged_degenerate_not_silently_a_point(steady_track):
    """A dark contact is the one legitimate degenerate case, and it must be
    reported as such rather than treated as a normal release."""
    from core.ais.tracks import Fix, build_track

    dark = build_track("DARK-001", [Fix(steady_track.t_start, 75.9, 9.2)], is_dark=True)
    params = ReleaseParams(steady_track.t_start, 1.0, 4.0)
    seed = build_seed(dark, params, n_per_point=10)
    assert seed.degenerate
    assert seed.degenerate_reason and "Dark radar contact" in seed.degenerate_reason


def test_theta_grid_never_proposes_a_release_after_the_acquisition(steady_track):
    acquisition = steady_track.t_end.replace(tzinfo=None)
    grid = {"lead_hours": [1.0, 3.0, 6.0], "duration_hours": [1.0, 2.0], "rate_m3_per_h": [4.0]}
    for params in theta_grid(steady_track, acquisition, grid, "GENERIC INTERMEDIATE FUEL OIL 180"):
        assert params.t_end <= acquisition
