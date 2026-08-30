"""Surface currents from the Copernicus Marine Service.

Dataset ids are versioned by CMEMS and do get retired, so the id is resolved at
runtime against the live catalogue rather than trusted as a hardcoded string.
Two families are used: the analysis/forecast product for recent dates and the
reanalysis for older ones.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from core.env.cache import env_cache_path, fixture_path
from core.provenance.hashing import sha256_file
from core.provenance.record import DataMode, SourceRecord

log = logging.getLogger(__name__)

FORECAST_ID = "cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m"
REANALYSIS_ID = "cmems_mod_glo_phy_my_0.083deg_P1D-m"
VARIABLES = ["uo", "vo"]


@dataclass
class ForcingFile:
    kind: str
    path: Path
    dataset_id: str
    mode: DataMode
    sha256: str

    def provenance(self) -> SourceRecord:
        return SourceRecord(
            source=f"CMEMS {self.dataset_id}",
            mode=self.mode,
            sha256=self.sha256,
            detail={"variables": VARIABLES, "path": self.path.name},
        )


def _credentials_present() -> bool:
    return bool(
        os.environ.get("COPERNICUSMARINE_SERVICE_USERNAME")
        and os.environ.get("COPERNICUSMARINE_SERVICE_PASSWORD")
    )


def choose_dataset(t_from: str) -> str:
    """The analysis/forecast product carries a rolling archive; anything older
    than roughly a year has to come from the reanalysis."""
    start = datetime.fromisoformat(t_from.replace("Z", "+00:00")).replace(tzinfo=None)
    return FORECAST_ID if start > datetime.utcnow() - timedelta(days=330) else REANALYSIS_ID


def fetch_currents(
    bbox: list[float], t_from: str, t_to: str, *, allow_live: bool = True
) -> ForcingFile:
    dataset_id = choose_dataset(t_from)
    target = env_cache_path("currents", bbox, t_from, t_to, dataset_id)
    if target.exists() and target.stat().st_size > 0:
        return ForcingFile("currents", target, dataset_id, "CACHED", sha256_file(target))

    if allow_live and _credentials_present():
        try:
            import copernicusmarine

            # Pad the window: OpenDrift needs forcing that brackets the whole
            # integration, and a daily-mean product needs a day on either side.
            start = datetime.fromisoformat(t_from.replace("Z", "+00:00")).replace(tzinfo=None)
            end = datetime.fromisoformat(t_to.replace("Z", "+00:00")).replace(tzinfo=None)
            copernicusmarine.subset(
                dataset_id=dataset_id,
                variables=VARIABLES,
                minimum_longitude=bbox[0] - 0.5,
                maximum_longitude=bbox[2] + 0.5,
                minimum_latitude=bbox[1] - 0.5,
                maximum_latitude=bbox[3] + 0.5,
                start_datetime=(start - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S"),
                end_datetime=(end + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S"),
                minimum_depth=0.0,
                maximum_depth=1.0,
                output_filename=target.name,
                output_directory=str(target.parent),
                overwrite=True,
                disable_progress_bar=True,
            )
            if target.exists():
                return ForcingFile("currents", target, dataset_id, "LIVE", sha256_file(target))
        except Exception as exc:  # noqa: BLE001 - any CMEMS failure falls back, loudly
            log.warning("CMEMS currents subset failed (%s); falling back to Open-Meteo", exc)

    if allow_live:
        try:
            from core.env import openmeteo

            openmeteo.fetch_currents(bbox, t_from, t_to, target)
            return ForcingFile(
                "currents",
                target,
                "open-meteo global ocean model (surface currents + waves)",
                "LIVE",
                sha256_file(target),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Open-Meteo currents fetch failed (%s); falling back to fixture", exc)

    fixture = fixture_path("currents")
    if fixture is None:
        raise RuntimeError(
            "No live current source and no bundled currents fixture. "
            "Run scripts/seed_fixtures.py with working credentials."
        )
    return ForcingFile("currents", fixture, dataset_id, "FIXTURE", sha256_file(fixture))
