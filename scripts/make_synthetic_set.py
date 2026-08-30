"""Generate the synthetic validation set — the scenario that actually tests the
method, because the ground truth is exact.

The construction is deliberately adversarial to ourselves:

  1. Take a real Sentinel-1 scene and real wind and current forcing.
  2. Pick one real AIS track from the window and call it the offender.
  3. Simulate a discharge along it as a moving line source under forcing
     realisation **A**, and rasterise the result into an observed slick mask.
  4. Run the full AVANTA pipeline blind under forcing realisation **B**.

Attributing under a different forcing realisation than the one that generated
the slick is the whole point. Using the same realisation would be marking our
own homework: it would measure whether the code is self-consistent, not whether
the method recovers a source under forcing we do not know exactly.

Two assertions matter and both are checked by the test suite:
  * the true vessel is rank 1 in at least 80% of cases;
  * with the true vessel removed from the candidate set, p(H0) > 0.5 — the
    system must decline to accuse anyone rather than promoting a runner-up.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.ais.tracks import Track, haversine_km  # noqa: E402
from core.config import settings  # noqa: E402
from core.env.currents import fetch_currents  # noqa: E402
from core.env.wind import fetch_wind  # noqa: E402
from core.pipeline import load_ais_fixture  # noqa: E402
from core.score.attribute import run_attribution  # noqa: E402
from core.score.compare import ComparisonGrid  # noqa: E402
from core.simulate.line_source import ReleaseParams  # noqa: E402
from core.simulate.openoil_runner import run_forward  # noqa: E402
from core.simulate.rasterize import rasterize  # noqa: E402

log = logging.getLogger("synthetic")


@dataclass
class SyntheticCase:
    case_id: int
    true_mmsi: str
    candidates: list[str]
    grid: ComparisonGrid
    truth: ReleaseParams
    acquisition: datetime


def _grid_for(bbox: list[float], shape: tuple[int, int] = (256, 256)) -> tuple[Any, tuple[int, int]]:
    from rasterio.transform import from_bounds

    return from_bounds(bbox[0], bbox[1], bbox[2], bbox[3], shape[1], shape[0]), shape


def distance_to_land_km(lon: float, lat: float, max_km: float = 60.0) -> float:
    """Rough distance from a position to the nearest land, by ring search on the
    GLOBE land mask. Cheap and only needs to be accurate enough to tell inshore
    traffic from offshore traffic."""
    from global_land_mask import globe

    if bool(globe.is_land(lat, lon)):
        return 0.0
    for radius_km in (5.0, 10.0, 15.0, 25.0, 40.0, max_km):
        d_lat = radius_km / 110.574
        d_lon = radius_km / (111.320 * max(math.cos(math.radians(lat)), 1e-3))
        angles = np.linspace(0, 2 * math.pi, 16, endpoint=False)
        lats = lat + d_lat * np.sin(angles)
        lons = lon + d_lon * np.cos(angles)
        if bool(np.any(globe.is_land(np.clip(lats, -89.9, 89.9), np.clip(lons, -179.9, 179.9)))):
            return radius_km
    return max_km


def usable_tracks(
    tracks: list[Track],
    min_span_minutes: float,
    min_km: float,
    min_offshore_km: float = 25.0,
) -> list[Track]:
    """Tracks that can serve as a synthetic line source.

    Three requirements, and the third is not obvious. A track needs time depth
    and real movement, or there is no line to seed along. It also has to be far
    enough offshore: oil released from a vessel a few kilometres off a coast
    beaches within hours, so between 92% and 100% of its particles strand and
    there is no slick left to attribute. Those are physically correct
    simulations and useless test cases, and including them silently throws away
    most of the set.
    """
    out: list[Track] = []
    for track in tracks:
        span = (track.t_end - track.t_start).total_seconds() / 60.0
        if span < min_span_minutes or len(track.fixes) < 6:
            continue
        lon, lat = track.lonlats()
        if haversine_km(float(lon[0]), float(lat[0]), float(lon[-1]), float(lat[-1])) < min_km:
            continue
        mid = len(track.fixes) // 2
        if distance_to_land_km(track.fixes[mid].lon, track.fixes[mid].lat) < min_offshore_km:
            continue
        out.append(track)
    return out


def generate_case(
    case_id: int,
    tracks: list[Track],
    bbox: list[float],
    currents_path: Path,
    wind_path: Path,
    rng: np.random.Generator,
    *,
    n_candidates: int = 5,
    slick_age_hours: float | None = None,
    n_per_point: int = 40,
) -> tuple[SyntheticCase, np.ndarray] | None:
    """Build one case: pick an offender, simulate its discharge, mask it."""
    if len(tracks) < n_candidates:
        log.info("case %d rejected: only %d tracks available", case_id, len(tracks))
        return None

    offender = tracks[int(rng.integers(0, len(tracks)))]
    age = slick_age_hours if slick_age_hours is not None else float(rng.choice([4.0, 8.0, 14.0]))
    duration = float(rng.choice([1.0, 2.0]))
    rate = float(rng.choice([2.0, 4.0, 8.0]))

    t_start = offender.t_start.replace(tzinfo=None) + timedelta(minutes=10)
    acquisition = t_start + timedelta(hours=age)
    truth = ReleaseParams(t_start, duration, rate)

    # Forcing realisation A generates the observed slick.
    try:
        sim = run_forward(
            offender, truth, acquisition.replace(tzinfo=timezone.utc),
            currents_path, wind_path,
            n_per_point=n_per_point,
            wind_drift_factor=0.032,
            horizontal_diffusivity=12.0,
            current_scale=1.08, wind_scale=0.94, wind_rotate_deg=6.0,
            seed_rng=1000 + case_id,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("case %d: truth simulation failed: %s", case_id, exc)
        return None

    lon, lat, mass = sim.surface_at(len(sim.times) - 1)
    if lon.size < 50:
        log.info("case %d rejected: only %d particles survived (stranding %.0f%%)",
                 case_id, lon.size, 100 * sim.stranded_fraction)
        return None

    transform, shape = _grid_for(bbox)
    density = rasterize(lon, lat, transform, shape, weights=mass, sigma_px=2.0)
    if density.max() <= 0:
        log.info("case %d rejected: empty density field", case_id)
        return None
    # The observed mask is where simulated oil is dense enough to have damped
    # the sea surface detectably, plus speckle-scale noise on the boundary.
    mask = density > density.max() * 0.18
    if mask.sum() < 40:
        log.info("case %d rejected: slick mask is only %d cells", case_id, int(mask.sum()))
        return None
    noise = rng.random(mask.shape) < 0.015
    mask = mask ^ (noise & mask)

    others = [t for t in tracks if t.mmsi != offender.mmsi]
    rng.shuffle(others)  # type: ignore[arg-type]
    candidates = [offender.mmsi] + [t.mmsi for t in others[: n_candidates - 1]]

    grid = ComparisonGrid(
        mask=mask, transform=transform, shape=shape, factor=1,
        sigma_px=2.0, fine_shape=shape,
    )
    return SyntheticCase(case_id, offender.mmsi, candidates, grid, truth, acquisition), density


def run_case(
    case: SyntheticCase,
    tracks_by_mmsi: dict[str, Track],
    currents_path: Path,
    wind_path: Path,
    *,
    drop_true: bool = False,
    n_ensemble: int = 3,
    n_per_point: int = 25,
) -> dict[str, Any] | None:
    """Attribute blind under forcing realisation B (the readers as delivered)."""
    wanted = [m for m in case.candidates if not (drop_true and m == case.true_mmsi)]
    selected = [tracks_by_mmsi[m] for m in wanted if m in tracks_by_mmsi]
    if not selected:
        return None
    try:
        result = run_attribution(
            selected, case.grid, case.acquisition.replace(tzinfo=timezone.utc),
            currents_path, wind_path,
            n_ensemble=n_ensemble, n_per_point=n_per_point,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("case %d: attribution failed: %s", case.case_id, exc)
        return None

    entries = result.posterior.entries
    top = next((e for e in entries if not e.is_null), None)
    true_entry = next((e for e in entries if e.hypothesis_id == case.true_mmsi), None)
    return {
        "case_id": case.case_id,
        "true_mmsi": case.true_mmsi,
        "drop_true": drop_true,
        "n_candidates": len(selected),
        "p_null": result.posterior.p_null,
        "no_attribution": result.posterior.no_attribution,
        "top_mmsi": top.hypothesis_id if top else None,
        "top_probability": top.probability if top else 0.0,
        "true_probability": true_entry.probability if true_entry else 0.0,
        "true_rank": true_entry.rank if true_entry else None,
        "correct": bool(top and top.hypothesis_id == case.true_mmsi),
        "slick_cells": case.grid.n_slick_cells,
        "ensemble_spread": result.ensemble_spread,
        "runtime_s": result.runtime_s,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ais", type=Path, default=Path("fixtures/ais/north_sea_live.json"))
    ap.add_argument("--cases", type=int, default=30)
    ap.add_argument("--negative-controls", type=int, default=8)
    ap.add_argument("--candidates", type=int, default=5)
    ap.add_argument("--ensemble", type=int, default=3)
    ap.add_argument("--per-point", type=int, default=25)
    ap.add_argument("--out", type=Path, default=Path("fixtures/scenarios/synthetic_set.json"))
    ap.add_argument("--lead-hours", type=float, nargs="*", default=None,
                    help="override the release-lead grid; fewer values trade profile "
                         "resolution for the case count a calibration set needs")
    ap.add_argument("--duration-hours", type=float, nargs="*", default=None,
                    help="override the release-duration grid")
    ap.add_argument("--offshore-km", type=float, default=25.0,
                    help="minimum distance from land; inshore releases beach before they can be attributed")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    # Narrowing the theta grid is a deliberate, recorded trade. A full grid
    # costs 75 forward simulations per case, which is the right resolution for
    # one investigation and the wrong one for building a calibration set: a
    # reliability diagram needs tens of cases far more than it needs a finely
    # profiled release window in each.
    grid = settings()["simulate"]["theta_grid"]
    if args.lead_hours:
        grid["lead_hours"] = list(args.lead_hours)
    if args.duration_hours:
        grid["duration_hours"] = list(args.duration_hours)

    if not args.ais.exists():
        raise SystemExit(f"AIS fixture not found: {args.ais}. Run scripts/capture_ais.py first.")

    tracks, record = load_ais_fixture(args.ais)
    log.info("loaded %d tracks from %s", len(tracks), args.ais)
    usable = usable_tracks(
        tracks, min_span_minutes=25.0, min_km=1.5, min_offshore_km=args.offshore_km
    )
    log.info("%d tracks have enough time depth and movement to be a line source", len(usable))
    if len(usable) < args.candidates:
        raise SystemExit(
            f"Only {len(usable)} usable tracks; need at least {args.candidates}. "
            "Capture AIS for longer."
        )

    lons = np.concatenate([t.lonlats()[0] for t in usable])
    lats = np.concatenate([t.lonlats()[1] for t in usable])
    bbox = [
        float(np.percentile(lons, 2)) - 0.2, float(np.percentile(lats, 2)) - 0.2,
        float(np.percentile(lons, 98)) + 0.2, float(np.percentile(lats, 98)) + 0.2,
    ]
    log.info("bbox %s", [round(b, 3) for b in bbox])

    t_from = min(t.t_start for t in usable).isoformat()
    t_to = (max(t.t_end for t in usable) + timedelta(hours=30)).isoformat()
    currents = fetch_currents(bbox, t_from, t_to)
    wind = fetch_wind(bbox, t_from, t_to)
    log.info("forcing: currents %s, wind %s", currents.mode, wind.mode)

    by_mmsi = {t.mmsi: t for t in usable}
    rng = np.random.default_rng(args.seed)
    results: list[dict[str, Any]] = []

    for i in range(args.cases):
        built = generate_case(
            i, usable, bbox, currents.path, wind.path, rng,
            n_candidates=args.candidates, n_per_point=args.per_point,
        )
        if built is None:
            continue
        case, _ = built
        outcome = run_case(
            case, by_mmsi, currents.path, wind.path,
            n_ensemble=args.ensemble, n_per_point=args.per_point,
        )
        if outcome is None:
            continue
        results.append(outcome)
        log.info(
            "case %d/%d: true=%s top=%s correct=%s p_true=%.3f p_H0=%.3f",
            i + 1, args.cases, case.true_mmsi, outcome["top_mmsi"],
            outcome["correct"], outcome["true_probability"], outcome["p_null"],
        )

    negatives: list[dict[str, Any]] = []
    for j in range(args.negative_controls):
        built = generate_case(
            10_000 + j, usable, bbox, currents.path, wind.path, rng,
            n_candidates=args.candidates, n_per_point=args.per_point,
        )
        if built is None:
            continue
        case, _ = built
        outcome = run_case(
            case, by_mmsi, currents.path, wind.path, drop_true=True,
            n_ensemble=args.ensemble, n_per_point=args.per_point,
        )
        if outcome is None:
            continue
        negatives.append(outcome)
        log.info(
            "negative control %d/%d: p_H0=%.3f no_attribution=%s",
            j + 1, args.negative_controls, outcome["p_null"], outcome["no_attribution"],
        )

    top1 = sum(1 for r in results if r["correct"]) / max(len(results), 1)
    h0_ok = sum(1 for r in negatives if r["p_null"] > 0.5) / max(len(negatives), 1)

    payload = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "ais_source": record.to_dict(),
        "bbox": bbox,
        "forcing": {"currents": currents.provenance().to_dict(), "wind": wind.provenance().to_dict()},
        "settings_version": settings()["version"],
        "theta_grid": grid,
        "n_cases": len(results),
        "n_negative_controls": len(negatives),
        "top1_accuracy": round(top1, 4),
        "negative_control_pass_rate": round(h0_ok, 4),
        "cases": results,
        "negative_controls": negatives,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 62)
    print(f"cases                     {len(results)}")
    print(f"top-1 accuracy            {top1:.1%}   (target >= 80%)")
    print(f"negative controls         {len(negatives)}")
    print(f"  p(H0) > 0.5 rate        {h0_ok:.1%}   (target 100%)")
    print(f"written to                {args.out}")
    print("=" * 62)


if __name__ == "__main__":
    main()
