"""Build a complete, self-contained demo case with exact ground truth.

Every other scenario depends on nature cooperating: a real scene needs a real
slick, in the detectable wind band, with AIS coverage over the same water. When
any of those is missing the console honestly shows a refusal -- which is correct
behaviour, and useless for demonstrating the parts of the system that come
after detection.

This builds the whole chain deterministically. The radar background, the
vessel tracks and the forcing are real; the discharge is simulated along one
chosen track and painted into the scene. The answer is therefore known exactly,
which is what makes it a test rather than an illustration, and every surface
that shows it is badged SYNTHETIC.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.transform import Affine, from_bounds

from core.ais.tracks import Fix, Track, build_track
from core.config import data_dir
from core.simulate.line_source import ReleaseParams
from core.simulate.openoil_runner import run_forward
from core.simulate.rasterize import rasterize

log = logging.getLogger(__name__)


@dataclass
class SyntheticCase:
    raster_path: Path
    tracks: list[Track]
    true_mmsi: str
    truth: ReleaseParams
    acquisition: datetime
    bbox: list[float]

    def ground_truth(self) -> dict[str, Any]:
        return {
            "true_mmsi": self.true_mmsi,
            "release": self.truth.to_dict(),
            "acquisition_utc": self.acquisition.isoformat(),
            "note": (
                "The offending vessel and its release window are known exactly because "
                "this slick was generated, not observed. The attribution below was run "
                "blind against a different forcing realisation."
            ),
        }


# A plausible traffic picture in the open Arabian Sea, on the approaches to the
# Gulf of Kutch: one tanker that discharges, and four other vessels on nearby
# courses that have to be ruled out on evidence rather than on geography.
#
# The positions are deliberately well offshore. An earlier placement near the
# Saurashtra coast put 83% of the scene under the land mask -- correctly, since
# the tracks ran onto the shore within a few hours -- and the detector masked
# the slick away with it. Every track here stays over water for its whole run,
# and so does the drifted slick.
FLEET = [
    ("419001234", "MT KAVERI SPIRIT", "tanker",    68.30, 19.20,  0.0130,  0.0072),
    ("419002345", "MV KONKAN TRADER", "cargo",     68.17, 19.44,  0.0122, -0.0041),
    ("419003456", "MV SAGAR MOTI",    "cargo",     68.53, 19.13,  0.0071,  0.0119),
    ("419004567", "MT ARABIAN DAWN",  "tanker",    68.10, 19.07,  0.0148,  0.0026),
    ("419005678", "FV MEENAKSHI",     "fishing",   68.41, 19.52,  0.0039, -0.0088),
]


def build_tracks(t_start: datetime, n_fixes: int = 40, step_minutes: float = 5.0) -> list[Track]:
    """Steady tracks with realistic reporting behaviour.

    The offender goes silent for a stretch that overlaps its own discharge
    window, because that gap is one of the behaviour-prior features the console
    is meant to show working.
    """
    tracks: list[Track] = []
    for mmsi, name, kind, lon0, lat0, dlon, dlat in FLEET:
        fixes: list[Fix] = []
        for i in range(n_fixes):
            when = t_start + timedelta(minutes=step_minutes * i)
            # The offender stops transmitting between fix 8 and fix 22.
            if mmsi == FLEET[0][0] and 8 <= i < 22:
                continue
            speed = 11.4 if kind != "fishing" else 4.2
            course = float((np.degrees(np.arctan2(dlon, dlat)) + 360.0) % 360.0)
            fixes.append(Fix(when, lon0 + dlon * i, lat0 + dlat * i, speed, course))
        tracks.append(build_track(mmsi, fixes, name=name, ship_type=kind,
                                  source="synthetic AIS fleet (generated)"))
    return tracks


def paint_slick(
    bbox: list[float],
    lons: np.ndarray,
    lats: np.ndarray,
    mass: np.ndarray,
    out: Path,
    *,
    size: int = 1024,
    seed: int = 11,
    film_sigma_px: float = 7.0,
) -> Path:
    """Render a Sentinel-1-like sigma0 scene with the simulated slick burned in.

    Oil damps capillary waves, so a slick appears as a *darker* patch against
    the sea's own backscatter. The background is generated with realistic
    speckle and a wind-streak pattern so the detector has to do real work rather
    than threshold a clean synthetic blob.
    """
    rng = np.random.default_rng(seed)
    shape = (size, size)
    transform = from_bounds(bbox[0], bbox[1], bbox[2], bbox[3], size, size)

    # Sea background: mean sigma0 around -12 dB with multiplicative speckle.
    rows, cols = np.mgrid[0:size, 0:size]
    streaks = 0.55 * np.sin((rows * 0.9 + cols * 1.7) / 26.0)
    swell = 0.30 * np.sin((rows * 1.3 - cols * 0.6) / 61.0)
    speckle = rng.normal(0.0, 0.62, shape)
    vv = -12.0 + streaks + swell + speckle

    # Burn in the slick: density -> damping in dB.
    # A wider kernel than the scoring grid uses. Oil on water is a continuous
    # film; the particles are a numerical device for tracking it, so painting
    # them with a tight kernel renders a scatter of dots that morphology then
    # breaks into fragments. The film is what a radar would actually see.
    density = rasterize(lons, lats, transform, shape, weights=mass, sigma_px=film_sigma_px)
    if density.max() > 0:
        damping = 7.5 * (density / density.max())
        vv -= damping

    # A decoy low-wind cell, so look-alike rejection has something to reject.
    cy, cx = int(size * 0.34), int(size * 0.72)
    yy, xx = np.mgrid[0:size, 0:size]
    blob = np.exp(-(((yy - cy) ** 2) / (2 * 46.0 ** 2) + ((xx - cx) ** 2) / (2 * 52.0 ** 2)))
    vv -= 4.2 * blob

    # Cross-polarisation sits well below co-pol over water.
    vh = vv - 6.4 + rng.normal(0.0, 0.5, shape)
    ratio = vv - vh
    mask = np.ones(shape, dtype=np.float32)

    out.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        out, "w", driver="GTiff", height=size, width=size, count=4,
        dtype="float32", crs="EPSG:4326", transform=transform, compress="deflate",
    ) as dst:
        for band, data in enumerate((vv, vh, ratio, mask), start=1):
            dst.write(data.astype(np.float32), band)
    return out


def build(
    currents_path: Path,
    wind_path: Path,
    *,
    bbox: list[float] | None = None,
    n_per_point: int = 160,
    seed: int = 11,
) -> SyntheticCase:
    """Generate the full case: fleet, discharge, drifted slick, radar scene."""
    bbox = bbox or [67.60, 18.60, 69.60, 20.60]
    # A fixed date inside the forcing archive, so the case is reproducible.
    t_start = datetime(2026, 8, 25, 18, 0, tzinfo=timezone.utc)
    tracks = build_tracks(t_start)
    offender = tracks[0]

    truth = ReleaseParams(
        t_start.replace(tzinfo=None) + timedelta(minutes=40),
        duration_hours=2.0,
        rate_m3_per_h=6.0,
    )
    acquisition = t_start + timedelta(hours=7)

    # Forcing realisation A generates the observation. Attribution later runs
    # against the readers as delivered, so it never sees this one.
    sim = run_forward(
        offender, truth, acquisition, currents_path, wind_path,
        n_per_point=n_per_point, wind_drift_factor=0.033,
        horizontal_diffusivity=13.0, current_scale=1.10,
        wind_scale=0.92, wind_rotate_deg=7.0, seed_rng=seed,
    )
    lon, lat, mass = sim.surface_at(len(sim.times) - 1)
    if lon.size < 40:
        raise RuntimeError(
            f"the synthetic discharge produced only {lon.size} surface particles; "
            "the forcing may not cover this box and window"
        )

    # Frame the scene on the slick and the tracks that could have made it.
    #
    # A 1.15-degree box at 1024 px is ~117 m/pixel, and a slick a few kilometres
    # across then covers fewer pixels than the detector's minimum area -- so a
    # perfectly good slick is thresholded away for being small. That is an
    # artefact of the framing, not of the physics. A real acquisition cued to a
    # suspected discharge would be tasked over the slick, so the synthetic one
    # is framed the same way.
    # Frame on the slick and the stretch of track that produced it -- not on
    # every vessel's full voyage. Including whole tracks stretches the box to
    # nearly a degree, which drops the resolution to ~117 m/pixel and leaves a
    # real slick smaller than the detector's minimum area. Candidate tracks are
    # scored from their own AIS positions, not from what the raster happens to
    # cover, so nothing is lost by framing tightly.
    release_fixes = [
        f for f in offender.fixes
        if truth.t_start <= f.t.replace(tzinfo=None) <= truth.t_end
    ] or list(offender.fixes)
    focus_lons = np.concatenate([lon, np.array([f.lon for f in release_fixes])])
    focus_lats = np.concatenate([lat, np.array([f.lat for f in release_fixes])])
    pad = 0.045
    bbox = [
        float(focus_lons.min()) - pad, float(focus_lats.min()) - pad,
        float(focus_lons.max()) + pad, float(focus_lats.max()) + pad,
    ]
    log.info("synthetic scene framed to %s (%.0f m/pixel)",
             [round(b, 3) for b in bbox],
             (bbox[2] - bbox[0]) * 111320.0 / 1024.0)

    raster = paint_slick(bbox, lon, lat, mass,
                         data_dir() / "synthetic" / "synthetic_discharge.tif", seed=seed)
    log.info("synthetic case: offender %s, %d particles, raster %s",
             offender.mmsi, lon.size, raster.name)
    return SyntheticCase(raster, tracks, offender.mmsi, truth, acquisition, bbox)
