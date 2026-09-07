"""A stalled CMEMS subset must not wedge the job executor.

copernicusmarine.subset() carries no timeout of its own. The API runs jobs
through a single-worker pool, so one hung fetch does not merely fail its own
job -- it blocks every job submitted afterwards, for the life of the process.
That is what these tests pin down.
"""
from __future__ import annotations

import sys
import threading
import time
import types

import pytest

from core.env import currents


@pytest.fixture
def credentials(monkeypatch):
    monkeypatch.setenv("COPERNICUSMARINE_SERVICE_USERNAME", "user")
    monkeypatch.setenv("COPERNICUSMARINE_SERVICE_PASSWORD", "secret")


@pytest.fixture
def cache_miss(monkeypatch, tmp_path):
    """Point the cache at an empty directory so the live path is taken."""
    target = tmp_path / "currents.nc"
    monkeypatch.setattr(currents, "env_cache_path", lambda *a, **k: target)
    return target


def _install_fake_cmems(monkeypatch, subset):
    module = types.ModuleType("copernicusmarine")
    module.subset = subset
    monkeypatch.setitem(sys.modules, "copernicusmarine", module)


BBOX = [67.6, 18.6, 69.6, 20.6]
WINDOW = ("2026-08-25T00:00:00Z", "2026-08-27T00:00:00Z")


def test_stalled_subset_falls_back_within_the_budget(
    monkeypatch, credentials, cache_miss
):
    """The call returns on the budget, not on the stalled fetch."""
    released = threading.Event()

    def never_returns(**kwargs):
        released.wait(30)  # far longer than the budget below

    _install_fake_cmems(monkeypatch, never_returns)
    monkeypatch.setattr(currents, "CMEMS_TIMEOUT_S", 0.5)

    def fake_openmeteo_fetch(bbox, t_from, t_to, out):
        out.write_bytes(b"open-meteo")
        return out

    monkeypatch.setattr(
        currents, "sha256_file", lambda path: "sha-" + path.name, raising=True
    )
    fake = types.ModuleType("core.env.openmeteo")
    fake.fetch_currents = fake_openmeteo_fetch
    monkeypatch.setitem(sys.modules, "core.env.openmeteo", fake)

    started = time.monotonic()
    try:
        result = currents.fetch_currents(BBOX, *WINDOW)
        elapsed = time.monotonic() - started

        # Without the budget this blocks for the full 30s wait above.
        assert elapsed < 10, f"fetch_currents blocked for {elapsed:.1f}s"
        assert result.mode == "LIVE"
        assert "open-meteo" in result.dataset_id
    finally:
        released.set()


def test_partial_file_from_an_abandoned_subset_is_not_cached(
    monkeypatch, credentials, cache_miss
):
    """A truncated subset left by the abandoned worker must not be served.

    The worker is not interruptible, so it can still be writing after the
    timeout. If that half-written file survived, the next run would take the
    cache branch at the top of fetch_currents and hand back a truncated field
    as though it were a complete one.
    """
    def writes_then_stalls(**kwargs):
        cache_miss.write_bytes(b"truncated")
        time.sleep(30)

    _install_fake_cmems(monkeypatch, writes_then_stalls)
    monkeypatch.setattr(currents, "CMEMS_TIMEOUT_S", 0.5)

    fake = types.ModuleType("core.env.openmeteo")
    fake.fetch_currents = lambda bbox, t_from, t_to, out: (_ for _ in ()).throw(
        RuntimeError("open-meteo unavailable")
    )
    monkeypatch.setitem(sys.modules, "core.env.openmeteo", fake)
    monkeypatch.setattr(currents, "fixture_path", lambda kind: None)

    # Every live source is now failing, so this surfaces the honest error
    # rather than a fabricated field -- and the partial file is gone.
    with pytest.raises(RuntimeError, match="No live current source"):
        currents.fetch_currents(BBOX, *WINDOW)

    assert not cache_miss.exists(), "a truncated subset was left to be cached"
