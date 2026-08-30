"""The likelihood must prefer a simulation that lands on the observed slick,
penalise one that floods the box, and stay finite when they do not overlap."""
from __future__ import annotations

import numpy as np

from core.score.compare import build_grid, score_null, score_simulation
from core.score.likelihood import independent_observations, log_likelihood, temperature
from core.simulate.rasterize import rasterize


def _cloud(rng, lon0, lon1, lat0, lat1, n=5000):
    return rng.uniform(lon0, lon1, n), rng.uniform(lat0, lat1, n)


def test_overlapping_simulation_scores_higher_than_a_distant_one(slick_mask):
    mask, transform, shape = slick_mask
    rng = np.random.default_rng(3)
    inside = rasterize(*_cloud(rng, 76.0, 76.2, 9.28, 9.33), transform, shape)
    outside = rasterize(*_cloud(rng, 75.82, 75.95, 9.05, 9.12), transform, shape)
    assert log_likelihood(inside, mask).log_likelihood > log_likelihood(outside, mask).log_likelihood


def test_flooding_the_whole_box_is_penalised(slick_mask):
    """Without the false-area term, a simulation that covers everything would
    score perfectly while explaining nothing."""
    mask, transform, shape = slick_mask
    rng = np.random.default_rng(4)
    focused = rasterize(*_cloud(rng, 76.0, 76.2, 9.28, 9.33), transform, shape)
    flood = rasterize(*_cloud(rng, 75.8, 76.4, 9.0, 9.6, n=40000), transform, shape)
    assert log_likelihood(focused, mask).log_likelihood > log_likelihood(flood, mask).log_likelihood


def test_no_overlap_stays_finite(slick_mask):
    """The epsilon floor exists so one unexplained pixel cannot send the score
    to minus infinity and exonerate a vessel outright."""
    mask, transform, shape = slick_mask
    density = np.zeros(shape, dtype=np.float32)
    density[0, 0] = 1.0
    terms = log_likelihood(density, mask)
    assert np.isfinite(terms.log_likelihood)


def test_empty_mask_returns_no_evidence(slick_mask):
    _, transform, shape = slick_mask
    empty = np.zeros(shape, dtype=bool)
    rng = np.random.default_rng(5)
    density = rasterize(*_cloud(rng, 76.0, 76.2, 9.28, 9.33), transform, shape)
    assert log_likelihood(density, empty).log_likelihood == 0.0


def test_independent_observations_tracks_slick_shape(slick_mask):
    """An elongated slick constrains more than a compact blob, and neither
    constrains as much as its raw pixel count suggests."""
    mask, _, shape = slick_mask
    elongated = independent_observations(mask)

    blob = np.zeros(shape, dtype=bool)
    rows, cols = np.mgrid[0:shape[0], 0:shape[1]]
    blob[(rows - 128) ** 2 + (cols - 128) ** 2 < 30 ** 2] = True

    assert elongated > independent_observations(blob)
    assert independent_observations(mask) < mask.sum()


def test_temperature_reduces_the_effective_sample_size(slick_mask):
    mask, _, _ = slick_mask
    assert temperature(mask) > 1.0
    assert mask.sum() / temperature(mask) < mask.sum()


def test_null_is_beaten_by_a_good_fit_and_beats_a_bad_one(slick_mask):
    mask, transform, shape = slick_mask
    polygons = []
    grid = build_grid(polygons, transform, shape)
    grid.mask = mask  # use the fixture mask directly on the fine grid
    grid.transform = transform
    grid.shape = shape
    grid.sigma_px = 1.5

    rng = np.random.default_rng(6)
    good, _ = score_simulation(grid, *_cloud(rng, 76.0, 76.2, 9.28, 9.33))
    bad, _ = score_simulation(grid, *_cloud(rng, 75.82, 75.9, 9.03, 9.10))
    null = score_null(grid)

    assert good.log_likelihood > null.log_likelihood > bad.log_likelihood
