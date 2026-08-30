"""The pipeline: the spine the whole product runs along.

Watch -> Detect -> Attribute -> Evidence -> Dossier. Each stage takes the
previous stage's output and adds provenance, so that by the time a dossier is
generated every number in it can be traced back to the request that produced it.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from core.ais.darkmatch import match_contacts
from core.ais.tracks import Fix, Track, build_track, utc
from core.config import settings
from core.env.currents import fetch_currents
from core.env.wind import fetch_wind
from core.hypothesis.prefilter import SlickGeometry, prefilter
from core.provenance.record import Provenance, SourceRecord, worst_mode
from core.sar.ingest import CdseClient, Scene
from core.sar.preprocess import read_scene
from core.sar.coverage import Coverage, evaluate as evaluate_coverage
from core.sar.segment_classical import Detection, segment
from core.sar.windgate import WindGate
from core.sar.windgate import evaluate as evaluate_gate
from core.score.attribute import AttributionRun, run_attribution
from core.score.compare import build_grid

log = logging.getLogger(__name__)


@dataclass
class SceneBundle:
    scene: Scene
    detection: Detection
    wind_gate: WindGate
    coverage: Coverage
    currents_path: Path
    wind_path: Path
    provenance: Provenance
    acquired_utc: datetime
    transform: Any
    shape: tuple[int, int]
    mode: str

    def slick_polygons(self) -> list[list[list[float]]]:
        return [r.polygon for r in self.detection.slicks()]

    def slick_geometry(self) -> SlickGeometry | None:
        slicks = self.detection.slicks()
        if not slicks:
            return None
        largest = max(slicks, key=lambda r: r.area_km2)
        return SlickGeometry(
            centroid_lon=largest.centroid_lonlat[0],
            centroid_lat=largest.centroid_lonlat[1],
            major_axis_deg=largest.major_axis_deg,
            major_axis_km=largest.major_axis_length_km,
            area_km2=largest.area_km2,
            acquired_utc=self.acquired_utc,
        )


def ingest_scene(
    bbox: list[float],
    t_from: str,
    t_to: str,
    *,
    allow_live: bool = True,
    fixture_name: str | None = None,
    infrastructure: list[tuple[float, float]] | None = None,
    progress: Callable[[str, float], None] | None = None,
) -> SceneBundle:
    def step(stage: str, fraction: float) -> None:
        if progress is not None:
            progress(stage, fraction)

    step("requesting Sentinel-1 scene", 0.05)
    client = CdseClient()
    scene = client.fetch(bbox, t_from, t_to, allow_live=allow_live, fixture_name=fixture_name)

    step("reading raster", 0.35)
    raster = read_scene(str(scene.path))
    if scene.acquired_utc:
        acquired = utc(scene.acquired_utc)
    else:
        # No product metadata for this raster. The end of the requested window
        # is the best available stand-in, but it can be a day from the real
        # overpass, which moves the wind gate and can flip its verdict. Say so
        # loudly rather than presenting a guess as an observation.
        acquired = utc(t_to)
        log.warning(
            "scene %s has no acquisition metadata; using the end of the requested "
            "window (%s) as the acquisition time. The wind gate and every release "
            "window are relative to this estimate.",
            scene.scene_id, t_to,
        )

    step("fetching environmental forcing", 0.45)
    window_from = (acquired - timedelta(days=2)).isoformat()
    currents = fetch_currents(bbox, window_from, acquired.isoformat(), allow_live=allow_live)
    wind = fetch_wind(bbox, window_from, acquired.isoformat(), allow_live=allow_live)

    step("evaluating coverage and wind gate", 0.6)
    coverage = evaluate_coverage(raster.coverage_fraction)
    if not coverage.sufficient:
        log.warning("scene %s: %s", scene.scene_id, coverage.verdict)

    centre_lon = 0.5 * (bbox[0] + bbox[2])
    centre_lat = 0.5 * (bbox[1] + bbox[3])
    speed, direction = wind.mean_speed_ms(centre_lon, centre_lat, acquired.isoformat())
    gate = evaluate_gate(speed, direction, wind.source)

    step("segmenting scene", 0.7)
    detection = segment(raster, infrastructure=infrastructure)

    provenance = Provenance(
        sar=scene.provenance(),
        wind=wind.provenance(),
        currents=currents.provenance(),
        model={
            "segmenter": segmenter_name(),
            "acquisition_time_known": scene.acquisition_time_known,
        },
    )
    step("scene ready", 1.0)
    return SceneBundle(
        scene=scene,
        detection=detection,
        wind_gate=gate,
        coverage=coverage,
        currents_path=currents.path,
        wind_path=wind.path,
        provenance=provenance,
        acquired_utc=acquired,
        transform=raster.transform,
        shape=raster.shape,
        mode=worst_mode(scene.mode, wind.mode, currents.mode),
    )


def segmenter_name() -> str:
    """Whether a trained checkpoint is actually loaded.

    If it is not, this says so plainly. A UI that claims an attention U-Net when
    the classical detector is running is the single fastest way to lose a
    reviewer's trust in every other claim.
    """
    checkpoint = Path("models/segmenter.pt")
    if checkpoint.exists():
        return "attention-unet (checkpoint loaded)"
    return "classical detector (no trained checkpoint loaded)"


def load_ais_fixture(path: Path, bbox: list[float] | None = None) -> tuple[list[Track], SourceRecord]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    static = payload.get("static", {})
    tracks: list[Track] = []
    for mmsi, raw_fixes in payload.get("fixes", {}).items():
        fixes = [
            Fix(
                t=utc(f["t"]),
                lon=float(f["lon"]),
                lat=float(f["lat"]),
                sog_kn=_num(f.get("sog_kn")),
                cog_deg=_num(f.get("cog_deg")),
            )
            for f in raw_fixes
        ]
        if bbox is not None:
            fixes = [f for f in fixes if bbox[0] <= f.lon <= bbox[2] and bbox[1] <= f.lat <= bbox[3]]
        if len(fixes) < 3:
            continue
        meta = static.get(mmsi, {})
        tracks.append(
            build_track(
                mmsi,
                fixes,
                name=meta.get("name"),
                imo=meta.get("imo"),
                ship_type=meta.get("ship_type", "unknown"),
                length_m=meta.get("length_m"),
                source=payload.get("source", "AIS fixture"),
            )
        )
    record = SourceRecord(
        source=payload.get("source", "AIS fixture"),
        mode="FIXTURE",
        detail={
            "captured_utc": payload.get("captured_utc"),
            "n_vessels": len(tracks),
            "file": path.name,
        },
    )
    return tracks, record


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if out in (102.3, 360.0) else out


def generate_candidates(
    bundle: SceneBundle,
    tracks: list[Track],
    *,
    keep_top_k: int | None = None,
) -> dict[str, Any]:
    """Stage A: narrow the field geometrically, and show the working."""
    geometry = bundle.slick_geometry()
    if geometry is None:
        return {
            "n_considered": len(tracks),
            "n_kept": 0,
            "results": [],
            "dark_contacts": [],
            "tracks": {},
            "reason": "No slick was segmented in this scene, so there is nothing to attribute.",
        }

    dark, _matched = match_contacts(
        bundle.detection.ship_pixels, tracks, bundle.acquired_utc
    )
    # Only keep dark contacts that are plausibly related to the slick; a radar
    # contact 150 km away is a real vessel but not a candidate.
    from core.ais.tracks import haversine_km

    dark = [
        d
        for d in dark
        if haversine_km(d.lon, d.lat, geometry.centroid_lon, geometry.centroid_lat)
        <= float(settings()["prefilter"]["search_radius_km"])
    ][:6]

    drift_u, drift_v = _mean_drift(bundle)
    all_tracks = [*tracks, *[d.as_track() for d in dark]]
    results = prefilter(all_tracks, geometry, drift_u=drift_u, drift_v=drift_v, keep_top_k=keep_top_k)
    by_mmsi = {t.mmsi: t for t in all_tracks}
    kept = [r for r in results if r.kept]
    return {
        "n_considered": len(all_tracks),
        "n_kept": len(kept),
        "n_dark": len(dark),
        "results": [r.to_dict() for r in results],
        "dark_contacts": [d.to_dict() for d in dark],
        "tracks": {r.mmsi: by_mmsi[r.mmsi].to_geojson() for r in kept if r.mmsi in by_mmsi},
        "slick": {
            "centroid": [geometry.centroid_lon, geometry.centroid_lat],
            "major_axis_deg": geometry.major_axis_deg,
            "major_axis_km": geometry.major_axis_km,
            "area_km2": geometry.area_km2,
        },
        "mean_drift_ms": [round(drift_u, 4), round(drift_v, 4)],
    }


def _mean_drift(bundle: SceneBundle) -> tuple[float, float]:
    """Mean surface drift vector over the scene window: current plus 3% of wind.

    Used only to decide which side of the slick is upstream in the prefilter.
    """
    import xarray as xr

    u = v = 0.0
    try:
        with xr.open_dataset(bundle.currents_path) as ds:
            u += float(np.nanmean(ds.x_sea_water_velocity.values))
            v += float(np.nanmean(ds.y_sea_water_velocity.values))
    except Exception as exc:  # noqa: BLE001
        log.debug("current mean unavailable: %s", exc)
    try:
        with xr.open_dataset(bundle.wind_path) as ds:
            u += 0.03 * float(np.nanmean(ds.x_wind.values))
            v += 0.03 * float(np.nanmean(ds.y_wind.values))
    except Exception as exc:  # noqa: BLE001
        log.debug("wind mean unavailable: %s", exc)
    return u, v


def attribute(
    bundle: SceneBundle,
    tracks: list[Track],
    *,
    n_ensemble: int | None = None,
    n_per_point: int | None = None,
    oil_type: str = "GENERIC INTERMEDIATE FUEL OIL 180",
    progress: Callable[[str, float], None] | None = None,
) -> AttributionRun:
    grid = build_grid(bundle.slick_polygons(), bundle.transform, bundle.shape)
    return run_attribution(
        tracks,
        grid,
        bundle.acquired_utc,
        bundle.currents_path,
        bundle.wind_path,
        n_ensemble=n_ensemble,
        n_per_point=n_per_point,
        oil_type=oil_type,
        progress=progress,
    )
