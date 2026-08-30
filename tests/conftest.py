from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATA_DIR", str(Path(__file__).resolve().parent.parent / "data"))

from core.ais.tracks import Fix, build_track  # noqa: E402


@pytest.fixture(scope="session")
def steady_track():
    """A vessel steaming steadily north-east for two and a half hours."""
    t0 = datetime(2025, 5, 26, 0, 0, tzinfo=timezone.utc)
    fixes = [
        Fix(t0 + timedelta(minutes=5 * i), 75.80 + 0.010 * i, 9.18 + 0.007 * i, 11.0, 55.0)
        for i in range(30)
    ]
    return build_track("419999999", fixes, name="TEST VESSEL", ship_type="tanker")


@pytest.fixture
def track_with_gap():
    """The same vessel, silent for a known two hours in the middle."""
    t0 = datetime(2025, 5, 26, 0, 0, tzinfo=timezone.utc)
    fixes = [Fix(t0 + timedelta(minutes=5 * i), 75.80 + 0.010 * i, 9.18 + 0.007 * i, 11.0, 55.0)
             for i in range(8)]
    resume = t0 + timedelta(minutes=35) + timedelta(hours=2)
    fixes += [Fix(resume + timedelta(minutes=5 * i), 76.00 + 0.010 * i, 9.30 + 0.007 * i, 11.0, 55.0)
              for i in range(10)]
    return build_track("419888888", fixes, name="GAP VESSEL", ship_type="cargo")


@pytest.fixture(scope="session")
def forcing_files(steady_track_bbox):
    """Real forcing that actually covers the test track.

    Picking whichever netCDF happened to sort first is not good enough: forcing
    for the wrong ocean leaves every particle outside the domain, and OpenDrift
    responds by simply not moving them. The run then "succeeds" with zero drift
    and zero weathering, which looks like a physics result and is not one. So
    the fixture fetches (or reuses the cache for) the track's own box.
    """
    from core.env.currents import fetch_currents
    from core.env.wind import fetch_wind

    bbox, t_from, t_to = steady_track_bbox
    try:
        currents = fetch_currents(bbox, t_from, t_to)
        wind = fetch_wind(bbox, t_from, t_to)
    except RuntimeError as exc:
        pytest.skip(f"no forcing available for the test track: {exc}")
    return currents.path, wind.path


@pytest.fixture(scope="session")
def steady_track_bbox():
    """The box and window the `steady_track` fixture lives in."""
    return (
        [75.6, 8.9, 76.5, 9.8],
        "2025-05-25T00:00:00Z",
        "2025-05-27T00:00:00Z",
    )


@pytest.fixture
def slick_mask():
    """An elongated slick on a 256x256 grid, with its transform."""
    from rasterio.transform import from_bounds

    shape = (256, 256)
    transform = from_bounds(75.8, 9.0, 76.4, 9.6, shape[1], shape[0])
    mask = np.zeros(shape, dtype=bool)
    rows, cols = np.mgrid[0:256, 0:256]
    band = np.abs((rows - 120) - 0.25 * (cols - 128)) < 7
    mask[band & (cols > 60) & (cols < 200)] = True
    return mask, transform, shape
