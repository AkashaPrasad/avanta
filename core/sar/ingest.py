"""Sentinel-1 ingest via the CDSE Sentinel Hub Process API.

The Process API returns an orthorectified, radiometrically calibrated sigma0
GeoTIFF for an arbitrary bbox and time window in one HTTP call. The alternative
-- downloading a ~1 GB GRD product and running ESA SNAP -- costs tens of minutes
per scene, which this project does not have.

Three paths, and the caller is always told which one it got:
  LIVE     a request actually went to Copernicus
  CACHED   a previous identical request is being replayed from disk
  FIXTURE  a bundled scene, used when the API is unreachable or out of quota
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from core.config import fixtures_dir, settings
from core.provenance.hashing import sha256_file
from core.provenance.record import DataMode, SourceRecord
from core.sar.cache import BlobCache

log = logging.getLogger(__name__)

EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{bands: ["VV", "VH", "dataMask"]}],
    output: {id: "default", bands: 4, sampleType: "FLOAT32"}
  };
}
function evaluatePixel(s) {
  var vv = 10 * Math.log(s.VV) / Math.LN10;
  var vh = 10 * Math.log(s.VH) / Math.LN10;
  return [vv, vh, vv - vh, s.dataMask];
}"""


class CdseUnavailable(RuntimeError):
    """Raised when no live path to Copernicus exists. Callers fall back to a
    fixture and must badge the result accordingly -- never silently."""


@dataclass
class Scene:
    scene_id: str
    path: Path
    bbox: list[float]
    t_from: str
    t_to: str
    mode: DataMode
    acquired_utc: str | None
    product_id: str | None
    sha256: str
    processing_units: float | None = None

    @property
    def acquisition_time_known(self) -> bool:
        """Whether the acquisition instant came from the product, or is a guess.

        A cached raster whose metadata sidecar is missing has bytes but no
        timestamp. Falling back to the end of the requested window can put the
        wind gate a day away from the real overpass and quietly change the
        verdict, so the distinction is carried explicitly rather than collapsed.
        """
        return self.acquired_utc is not None

    def provenance(self) -> SourceRecord:
        return SourceRecord(
            source="CDSE Sentinel Hub Process API (sentinel-1-grd, IW, DV, sigma0)",
            mode=self.mode,
            sha256=self.sha256,
            detail={
                "product_id": self.product_id,
                "acquired_utc": self.acquired_utc,
                "acquisition_time_known": self.acquisition_time_known,
                "bbox": self.bbox,
                "processing_units": self.processing_units,
            },
        )


class CdseClient:
    def __init__(self, client_id: str | None = None, client_secret: str | None = None) -> None:
        # None means "not supplied, read the environment"; an explicit empty
        # string means "no credential", which is how an unconfigured client is
        # constructed deliberately. Treating "" as absent would make that
        # impossible and would hide a blank credential in production.
        self.client_id = os.environ.get("CDSE_CLIENT_ID", "") if client_id is None else client_id
        self.client_secret = (
            os.environ.get("CDSE_CLIENT_SECRET", "") if client_secret is None else client_secret
        )
        self.cfg = settings()["sar"]
        self.cache = BlobCache("sar")
        self._token: str | None = None
        self._token_expiry: float = 0.0
        self._process_url: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def token(self) -> str:
        if not self.configured:
            raise CdseUnavailable("CDSE_CLIENT_ID / CDSE_CLIENT_SECRET are not set")
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        try:
            resp = requests.post(
                self.cfg["token_url"],
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                timeout=30,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise CdseUnavailable(f"CDSE token request failed: {exc}") from exc
        payload = resp.json()
        self._token = str(payload["access_token"])
        self._token_expiry = time.time() + float(payload.get("expires_in", 600))
        return self._token

    def process_url(self) -> str:
        """The published examples have used two different paths. Probe once."""
        if self._process_url:
            return self._process_url
        candidates: list[str] = self.cfg["process_url_candidates"]
        headers = {"Authorization": f"Bearer {self.token()}"}
        for url in candidates:
            try:
                # An empty body is rejected with 400 by a real endpoint and 404
                # by one that does not exist; that is enough to tell them apart.
                probe = requests.post(url, headers=headers, json={}, timeout=20)
                if probe.status_code != 404:
                    self._process_url = url
                    return url
            except requests.RequestException:
                continue
        self._process_url = candidates[0]
        return self._process_url

    def search(self, bbox: list[float], t_from: str, t_to: str, limit: int = 20) -> list[dict[str, Any]]:
        headers = {"Authorization": f"Bearer {self.token()}"}
        body = {
            "collections": [self.cfg["collection"]],
            "bbox": bbox,
            "datetime": f"{t_from}/{t_to}",
            "limit": limit,
        }
        try:
            resp = requests.post(self.cfg["catalog_url"], headers=headers, json=body, timeout=60)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise CdseUnavailable(f"CDSE catalog search failed: {exc}") from exc
        features: list[dict[str, Any]] = resp.json().get("features", [])
        return features

    def _process_body(self, bbox: list[float], t_from: str, t_to: str) -> dict[str, Any]:
        cfg = self.cfg
        return {
            "input": {
                "bounds": {
                    "bbox": bbox,
                    "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
                },
                "data": [
                    {
                        "type": cfg["collection"],
                        "dataFilter": {
                            "timeRange": {"from": t_from, "to": t_to},
                            "acquisitionMode": cfg["acquisition_mode"],
                            "polarization": cfg["polarization"],
                            "resolution": cfg["resolution"],
                        },
                        "processing": {
                            "orthorectify": cfg["orthorectify"],
                            "backCoeff": cfg["back_coeff"],
                            "demInstance": cfg["dem_instance"],
                        },
                    }
                ],
            },
            "output": {
                "width": cfg["width"],
                "height": cfg["height"],
                "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}],
            },
            "evalscript": EVALSCRIPT,
        }

    def fetch(
        self,
        bbox: list[float],
        t_from: str,
        t_to: str,
        *,
        allow_live: bool = True,
        fixture_name: str | None = None,
    ) -> Scene:
        body = self._process_body(bbox, t_from, t_to)
        key = self.cache.key(bbox, t_from, t_to, EVALSCRIPT, self.cfg["width"], self.cfg["height"])

        cached = self.cache.get(key, ".tif")
        if cached is not None:
            meta = self.cache.meta(key)
            return Scene(
                scene_id=key[:16],
                path=cached,
                bbox=bbox,
                t_from=t_from,
                t_to=t_to,
                mode="CACHED",
                acquired_utc=meta.get("acquired_utc"),
                product_id=meta.get("product_id"),
                sha256=meta.get("sha256", sha256_file(cached)),
                processing_units=meta.get("processing_units"),
            )

        if allow_live and self.configured:
            try:
                acquisitions = self.search(bbox, t_from, t_to, limit=5)
                headers = {"Authorization": f"Bearer {self.token()}"}
                resp = requests.post(
                    self.process_url(),
                    headers=headers,
                    json=body,
                    timeout=self.cfg["request_timeout_s"],
                )
                resp.raise_for_status()
                if len(resp.content) < 1024:
                    raise CdseUnavailable("CDSE returned an empty raster for this window")
                product = acquisitions[0] if acquisitions else {}
                meta = {
                    "product_id": product.get("id"),
                    "acquired_utc": (product.get("properties") or {}).get("datetime"),
                    "bbox": bbox,
                    "t_from": t_from,
                    "t_to": t_to,
                    "processing_units": float(resp.headers.get("x-processingunits-spent", 0.0)),
                    "requested_utc": datetime.utcnow().isoformat() + "Z",
                }
                path = self.cache.put(key, ".tif", resp.content, meta)
                full = self.cache.meta(key)
                return Scene(
                    scene_id=key[:16],
                    path=path,
                    bbox=bbox,
                    t_from=t_from,
                    t_to=t_to,
                    mode="LIVE",
                    acquired_utc=meta["acquired_utc"],
                    product_id=meta["product_id"],
                    sha256=full["sha256"],
                    processing_units=meta["processing_units"],
                )
            except (requests.RequestException, CdseUnavailable, KeyError) as exc:
                log.warning("live CDSE ingest failed, falling back to fixture: %s", exc)

        return self._fixture(bbox, t_from, t_to, fixture_name)

    def _fixture(
        self, bbox: list[float], t_from: str, t_to: str, fixture_name: str | None
    ) -> Scene:
        candidates = sorted(fixtures_dir().joinpath("scenes").glob("*.tif"))
        chosen: Path | None = None
        if fixture_name:
            named = fixtures_dir() / "scenes" / f"{fixture_name}.tif"
            if named.exists():
                chosen = named
        if chosen is None and candidates:
            chosen = candidates[0]
        if chosen is None:
            raise CdseUnavailable(
                "No live CDSE access and no bundled fixture scene is available. "
                "Run scripts/seed_fixtures.py with working credentials."
            )
        return Scene(
            scene_id=chosen.stem,
            path=chosen,
            bbox=bbox,
            t_from=t_from,
            t_to=t_to,
            mode="FIXTURE",
            acquired_utc=None,
            product_id=chosen.stem,
            sha256=sha256_file(chosen),
        )
