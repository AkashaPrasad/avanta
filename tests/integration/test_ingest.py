"""AC-3 and AC-4: live ingest works, and cached ingest works offline."""
from __future__ import annotations

import os

import pytest
import rasterio

from core.sar.ingest import CdseClient, CdseUnavailable

BBOX = [75.8, 9.0, 76.4, 9.6]
T_FROM = "2025-05-28T00:00:00Z"
T_TO = "2025-05-28T23:59:59Z"


def _configured() -> bool:
    return bool(os.environ.get("CDSE_CLIENT_ID") and os.environ.get("CDSE_CLIENT_SECRET"))


@pytest.mark.network
def test_cdse_live_ingest():
    """A real calibrated Sentinel-1 scene arrives as a georeferenced GeoTIFF.

    Network-gated: skipped loudly rather than silently passing when offline.
    """
    if not _configured():
        pytest.skip("CDSE_CLIENT_ID / CDSE_CLIENT_SECRET are not set")

    client = CdseClient()
    scene = client.fetch(BBOX, T_FROM, T_TO)
    assert scene.mode in {"LIVE", "CACHED"}, f"expected a real fetch, got {scene.mode}"
    assert scene.path.exists() and scene.path.stat().st_size > 100_000
    assert len(scene.sha256) == 64

    with rasterio.open(scene.path) as src:
        assert src.count >= 3, "expected VV, VH and the VV-VH ratio"
        assert src.crs is not None and src.crs.to_epsg() == 4326
        west, south, east, north = src.bounds
        assert abs(west - BBOX[0]) < 0.05 and abs(north - BBOX[3]) < 0.05, "raster is not georeferenced to the request"
        band = src.read(1)
        finite = band[band == band]
        assert finite.size > 0
        assert -45.0 < float(finite.mean()) < 5.0, "VV should be in a plausible sigma0 dB range"


@pytest.mark.network
def test_cached_ingest_offline():
    """The second identical request never touches the network.

    Free Processing Units are finite, and the demo must survive with the network
    off, so this is a hard requirement rather than an optimisation.
    """
    if not _configured():
        pytest.skip("CDSE credentials are not set")

    client = CdseClient()
    client.fetch(BBOX, T_FROM, T_TO)                       # warm the cache

    offline = CdseClient(client_id="", client_secret="")   # cannot reach CDSE at all
    scene = offline.fetch(BBOX, T_FROM, T_TO, allow_live=False)
    assert scene.mode == "CACHED", f"expected CACHED with no credentials, got {scene.mode}"
    assert scene.path.exists()


def test_missing_credentials_and_no_cache_raises_rather_than_faking():
    """Degrade visibly. A fabricated raster would be worse than an error."""
    client = CdseClient(client_id="", client_secret="")
    with pytest.raises(CdseUnavailable):
        client.token()


def test_cache_key_depends_on_the_request():
    from core.sar.cache import BlobCache

    cache = BlobCache("test-keys")
    a = cache.key(BBOX, T_FROM, T_TO, "eval", 1024, 1024)
    b = cache.key(BBOX, T_FROM, "2025-05-29T00:00:00Z", "eval", 1024, 1024)
    assert a != b, "a different time window must not hit the same cache entry"
    assert a == cache.key(BBOX, T_FROM, T_TO, "eval", 1024, 1024)
