"""Global Fishing Watch API v3 client.

Three things AVANTA takes from GFW, and one it asks for and may not get:

  * **AIS-off (gap) events.** A maintained, independent record of vessels that
    stopped transmitting, which is exactly the signal the `ais_gap_overlap`
    prior feature claims to use. Deriving gaps only from our own short capture
    window would systematically miss the long ones that matter most.
  * **Vessel identity.** MMSI and IMO resolved across 40-odd public registries,
    which is what fills the Appendix 3 identity fields with something a flag
    State can act on rather than a bare MMSI.
  * **Insights.** Fused indicators including AIS-off and authorisations.
  * **SAR-detected fixed infrastructure**, to mask platforms so an installation's
    routine sheen is never attributed to a passing ship. This dataset is not
    included in every API token's permissions; when it is refused the mask is
    reported as unavailable rather than quietly skipped.

Coverage to state honestly: GFW AIS-off events run from 2020 to roughly 72 hours
ago, so they are an investigative source, not a real-time one.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import requests

from core.ais.tracks import Gap, utc

log = logging.getLogger(__name__)

BASE = "https://gateway.api.globalfishingwatch.org/v3"
IDENTITY_DATASET = "public-global-vessel-identity:latest"
GAPS_DATASET = "public-global-gaps-events:latest"
INFRASTRUCTURE_DATASET = "public-global-fixed-infrastructure:latest"


class GfwUnavailable(RuntimeError):
    pass


@dataclass
class VesselIdentity:
    vessel_id: str
    mmsi: str | None
    imo: str | None
    name: str | None
    flag: str | None
    callsign: str | None
    ship_type: str | None
    tonnage_gt: float | None
    length_m: float | None
    last_transmission_utc: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "vessel_id": self.vessel_id,
            "mmsi": self.mmsi,
            "imo": self.imo,
            "name": self.name,
            "flag": self.flag,
            "callsign": self.callsign,
            "ship_type": self.ship_type,
            "tonnage_gt": self.tonnage_gt,
            "length_m": self.length_m,
            "last_transmission_utc": self.last_transmission_utc,
            "source": "Global Fishing Watch vessel registry (v3, 40+ public registries)",
        }


class GfwClient:
    def __init__(self, token: str | None = None, timeout: float = 90.0) -> None:
        # None reads the environment; an explicit "" means no token.
        self.token = os.environ.get("GFW_API_TOKEN", "") if token is None else token
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def _headers(self) -> dict[str, str]:
        if not self.configured:
            raise GfwUnavailable("GFW_API_TOKEN is not set")
        return {"Authorization": f"Bearer {self.token}"}

    # -- vessel identity ----------------------------------------------------

    def search_vessel(self, query: str, limit: int = 5) -> list[VesselIdentity]:
        try:
            resp = requests.get(
                f"{BASE}/vessels/search",
                headers=self._headers(),
                params={
                    "query": query,
                    "datasets[0]": IDENTITY_DATASET,
                    "limit": limit,
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise GfwUnavailable(f"GFW vessel search failed: {exc}") from exc
        return [_identity(entry) for entry in resp.json().get("entries", [])]

    def identity_for_mmsi(self, mmsi: str) -> VesselIdentity | None:
        """Resolve an MMSI to a registry identity for the dossier."""
        try:
            matches = self.search_vessel(mmsi, limit=3)
        except GfwUnavailable as exc:
            log.info("GFW identity lookup unavailable for %s: %s", mmsi, exc)
            return None
        for match in matches:
            if match.mmsi == str(mmsi):
                return match
        return matches[0] if matches else None

    # -- AIS-off events -----------------------------------------------------

    def gap_events(
        self, bbox: list[float], start: str, end: str, *, limit: int = 200
    ) -> list[dict[str, Any]]:
        polygon = {
            "type": "Polygon",
            "coordinates": [
                [
                    [bbox[0], bbox[1]],
                    [bbox[2], bbox[1]],
                    [bbox[2], bbox[3]],
                    [bbox[0], bbox[3]],
                    [bbox[0], bbox[1]],
                ]
            ],
        }
        body = {
            "datasets": [GAPS_DATASET],
            "startDate": start[:10],
            "endDate": end[:10],
            "geometry": polygon,
        }
        # A gap query is a heavy spatial scan on GFW's side and intermittently
        # exceeds its own read timeout. One retry costs a few seconds and turns
        # a transient upstream stall into a non-event; a persistent failure
        # still surfaces as GfwUnavailable rather than as an empty result.
        last: Exception | None = None
        for attempt in range(2):
            try:
                resp = requests.post(
                    f"{BASE}/events",
                    headers={**self._headers(), "Content-Type": "application/json"},
                    params={"limit": limit, "offset": 0},
                    json=body,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return list(resp.json().get("entries", []))
            except requests.RequestException as exc:
                last = exc
                log.info("GFW gap query attempt %d failed (%s); retrying", attempt + 1, exc)
        raise GfwUnavailable(f"GFW gap events failed after 2 attempts: {last}") from last

    def gaps_by_mmsi(self, bbox: list[float], start: str, end: str) -> dict[str, list[Gap]]:
        """AIS-off events keyed by MMSI, ready to merge with locally observed gaps."""
        try:
            events = self.gap_events(bbox, start, end)
        except GfwUnavailable as exc:
            log.info("GFW gap events unavailable: %s", exc)
            return {}
        out: dict[str, list[Gap]] = {}
        for event in events:
            vessel = event.get("vessel") or {}
            mmsi = str(vessel.get("ssvid") or "").strip()
            if not mmsi or not event.get("start") or not event.get("end"):
                continue
            try:
                out.setdefault(mmsi, []).append(Gap(utc(event["start"]), utc(event["end"])))
            except (ValueError, TypeError):
                continue
        return out

    # -- fixed infrastructure ----------------------------------------------

    def infrastructure(self, bbox: list[float]) -> tuple[list[tuple[float, float]], str]:
        """SAR-detected fixed infrastructure, for masking platforms.

        Returns the points and a status string. This dataset is not granted to
        every token; a refusal is reported, never treated as "no platforms here".
        """
        try:
            resp = requests.get(
                f"{BASE}/4wings/report",
                headers=self._headers(),
                params={
                    "datasets[0]": INFRASTRUCTURE_DATASET,
                    "format": "JSON",
                    "spatial-resolution": "HIGH",
                    "temporal-resolution": "ENTIRE",
                    "spatial-aggregation": "false",
                },
                timeout=self.timeout,
            )
            if resp.status_code == 403:
                return [], (
                    "unavailable: this API token does not include the fixed-infrastructure "
                    "dataset, so platform sheen cannot be masked out"
                )
            resp.raise_for_status()
        except (requests.RequestException, GfwUnavailable) as exc:
            return [], f"unavailable: {exc}"
        points: list[tuple[float, float]] = []
        for entry in resp.json().get("entries", []):
            for row in entry.values() if isinstance(entry, dict) else []:
                if isinstance(row, list):
                    for item in row:
                        if isinstance(item, dict) and "lat" in item and "lon" in item:
                            points.append((float(item["lon"]), float(item["lat"])))
        return points, "ok"


def _identity(entry: dict[str, Any]) -> VesselIdentity:
    registry = (entry.get("registryInfo") or [{}])[0]
    combined = entry.get("combinedSourcesInfo") or []
    ship_type = None
    if combined:
        types = (combined[0] or {}).get("shiptypes") or []
        if types:
            ship_type = (types[0] or {}).get("name")
    geartypes = registry.get("geartypes") or []
    return VesselIdentity(
        vessel_id=str(registry.get("id") or entry.get("id") or ""),
        mmsi=str(registry.get("ssvid")) if registry.get("ssvid") else None,
        imo=str(registry.get("imo")) if registry.get("imo") else None,
        name=registry.get("shipname"),
        flag=registry.get("flag"),
        callsign=registry.get("callsign"),
        ship_type=ship_type or (geartypes[0] if geartypes else None),
        tonnage_gt=_float(registry.get("tonnageGt")),
        length_m=_float(registry.get("lengthM")),
        last_transmission_utc=registry.get("transmissionDateTo"),
    )


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
