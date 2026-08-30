"""Deterministic dark-spot detection and five-class labelling.

This is the production detector. It needs no training data, runs in seconds, and
-- the part that matters for enforcement -- every decision it makes is a named
number a human can disagree with. The discriminating features are the same ones
the oil-spill remote sensing literature uses (Krestenitis et al. 2019 and the
Bonn Agreement guidelines): area, elongation, edge sharpness, local contrast,
and cross-polarisation behaviour.

Classes follow the Krestenitis benchmark: sea / oil / look-alike / ship / land.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from global_land_mask import globe
from scipy.ndimage import (
    binary_closing,
    binary_dilation,
    binary_erosion,
    binary_opening,
    label,
    sobel,
)
from skimage.measure import find_contours, regionprops

from core.config import settings
from core.sar.preprocess import SarRaster, despeckle, local_background, pixel_to_lonlat

CLASS_SEA = "sea"
CLASS_OIL = "oil"
CLASS_LOOKALIKE = "look_alike"
CLASS_SHIP = "ship"
CLASS_LAND = "land"


@dataclass
class Region:
    region_id: int
    label: str
    confidence: float
    area_px: int
    area_km2: float
    centroid_lonlat: tuple[float, float]
    polygon: list[list[float]]
    features: dict[str, float]
    reasons: list[dict[str, Any]] = field(default_factory=list)
    major_axis_deg: float = 0.0
    major_axis_length_km: float = 0.0

    def to_geojson(self) -> dict[str, Any]:
        return {
            "type": "Feature",
            "id": self.region_id,
            "geometry": {"type": "Polygon", "coordinates": [self.polygon]},
            "properties": {
                "class": self.label,
                "confidence": round(self.confidence, 4),
                "area_px": self.area_px,
                "area_km2": round(self.area_km2, 4),
                "centroid": list(self.centroid_lonlat),
                "major_axis_deg": round(self.major_axis_deg, 2),
                "major_axis_length_km": round(self.major_axis_length_km, 3),
                # PostgreSQL JSON and RFC 8259 reject NaN/Infinity. A missing
                # infrastructure catalogue is represented as +inf internally
                # for classification, but crosses the API/storage boundary as
                # JSON null while the reason record still explains the pass.
                "features": {
                    k: round(float(v), 4) if np.isfinite(float(v)) else None
                    for k, v in self.features.items()
                },
                "reasons": self.reasons,
            },
        }


@dataclass
class Detection:
    regions: list[Region]
    dark_mask: np.ndarray
    ship_pixels: list[tuple[float, float]]
    threshold_db: float

    def slicks(self) -> list[Region]:
        return [r for r in self.regions if r.label == CLASS_OIL]

    def to_geojson(self) -> dict[str, Any]:
        return {
            "type": "FeatureCollection",
            "features": [r.to_geojson() for r in self.regions],
        }


def _land_mask(raster: SarRaster, buffer_km: float = 2.0) -> np.ndarray:
    """Land and inland water, from the GLOBE-derived global land mask.

    A radiometric test alone is not enough: an inland lake looks exactly like
    calm sea in a SAR image, and the Kerala backwaters sit directly beside the
    validation scene. The coastline is dilated by a buffer because radar layover
    and shadow near a shoreline produce dark artefacts that are not slicks.
    """
    rows, cols = np.indices(raster.shape)
    lon, lat = pixel_to_lonlat(raster.transform, rows, cols)
    land = np.asarray(globe.is_land(lat, lon))

    lat_mid = 0.5 * (raster.bounds[1] + raster.bounds[3])
    px_km = float(
        np.hypot(
            abs(raster.transform.a) * 111.320 * np.cos(np.deg2rad(lat_mid)),
            abs(raster.transform.e) * 110.574,
        )
    )
    buffer_px = int(round(buffer_km / max(px_km, 1e-6)))
    if buffer_px >= 1:
        size = 2 * buffer_px + 1
        land = binary_dilation(land, np.ones((size, size), dtype=bool))
    return land


def _ship_mask(raster: SarRaster, background: np.ndarray) -> np.ndarray:
    """Ships are small, very bright point targets: strongly above the local
    background in both polarisations."""
    with np.errstate(invalid="ignore"):
        return np.nan_to_num((raster.vv_db - background) > 6.0, nan=False) & raster.valid


def _polygon_from_mask(mask: np.ndarray, raster: SarRaster) -> list[list[float]]:
    contours = find_contours(mask.astype(float), 0.5)
    if not contours:
        return []
    contour = max(contours, key=len)
    step = max(1, len(contour) // 240)
    contour = contour[::step]
    lon, lat = pixel_to_lonlat(raster.transform, contour[:, 0], contour[:, 1])
    ring = [[float(a), float(b)] for a, b in zip(lon, lat, strict=True)]
    if ring and ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def _axis_from_props(props: Any, raster: SarRaster) -> tuple[float, float]:
    """Orientation of the region's PCA major axis, in compass degrees, and its
    length in km. A line-source slick is elongated along the vessel's course, so
    this axis is what the geometric prefilter aligns candidate tracks against."""
    # regionprops orientation is measured from the row axis, counter-clockwise.
    theta = float(props.orientation)
    drow = -np.cos(theta)
    dcol = np.sin(theta)
    lat = 0.5 * (raster.bounds[1] + raster.bounds[3])
    dlat = drow * raster.transform.e
    dlon = dcol * raster.transform.a
    bearing = float((np.degrees(np.arctan2(dlon * np.cos(np.deg2rad(lat)), dlat)) + 360.0) % 180.0)
    px_km = np.hypot(
        abs(raster.transform.a) * 111.320 * np.cos(np.deg2rad(lat)),
        abs(raster.transform.e) * 110.574,
    )
    return bearing, float(props.major_axis_length * px_km)


def segment(raster: SarRaster, *, infrastructure: list[tuple[float, float]] | None = None) -> Detection:
    cfg = settings()["detect"]
    la = cfg["lookalike"]

    smoothed = despeckle(raster.vv_db, raster.valid, cfg["speckle_sigma_px"])
    background = local_background(smoothed, raster.valid, int(cfg["local_window_px"]))

    land = _land_mask(raster)
    ships = _ship_mask(raster, background) & ~land

    with np.errstate(invalid="ignore"):
        dark = np.nan_to_num(
            (background - smoothed) > cfg["dark_offset_db"], nan=False
        )
    dark = dark & raster.valid & ~land & ~ships
    dark = binary_opening(dark, np.ones((3, 3)))
    dark = binary_closing(dark, np.ones((5, 5)))

    labelled, n = label(dark)
    gradient = np.hypot(sobel(np.nan_to_num(smoothed), 0), sobel(np.nan_to_num(smoothed), 1))
    # Reference texture: how sharp the undisturbed sea already is in THIS scene.
    # Normalising by it makes edge sharpness comparable across scenes, incidence
    # angles and sea states instead of depending on an absolute dB number. The
    # 90th percentile is the reference rather than the median because the
    # question is whether the boundary is sharper than the sea's own strong
    # texture -- wind streaks and swell -- not sharper than its calmest patch.
    sea = raster.valid & ~land & ~dark
    sea_gradient = float(np.nanpercentile(gradient[sea], 90)) if sea.any() else 1.0
    sea_gradient = max(sea_gradient, 1e-6)

    regions: list[Region] = []
    pixel_km2 = raster.pixel_area_km2()
    for props in regionprops(labelled):
        if props.area < cfg["min_area_px"]:
            continue
        mask = labelled == props.label
        boundary = mask & ~binary_erosion(mask, np.ones((3, 3)))

        minor = max(float(props.minor_axis_length), 1e-6)
        elongation = float(props.major_axis_length) / minor
        perimeter_area = float(props.perimeter) / max(float(props.area) ** 0.5, 1e-6)
        edge_gradient = float(np.nanmean(gradient[boundary])) if boundary.any() else 0.0
        contrast = float(np.nanmean(background[mask] - smoothed[mask]))
        ratio_inside = float(np.nanmean(raster.ratio_db[mask]))
        ratio_outside = float(np.nanmean(raster.ratio_db[raster.valid & ~dark]))
        vh_contrast = float(
            np.nanmean(local_background(raster.vh_db, raster.valid, int(cfg["local_window_px"]))[mask]
                       - raster.vh_db[mask])
        )

        row, col = props.centroid
        lon, lat = pixel_to_lonlat(raster.transform, np.array([row]), np.array([col]))
        centroid = (float(lon[0]), float(lat[0]))
        infra_km = _nearest_infrastructure_km(centroid, infrastructure)
        bearing, axis_km = _axis_from_props(props, raster)

        features = {
            "area_km2": props.area * pixel_km2,
            "elongation": elongation,
            "perimeter_area_ratio": perimeter_area,
            "edge_gradient_db": edge_gradient,
            "edge_sharpness_ratio": edge_gradient / sea_gradient,
            "sea_texture_gradient": sea_gradient,
            "contrast_db": contrast,
            "ratio_db_inside": ratio_inside,
            "ratio_db_outside": ratio_outside,
            "vh_contrast_db": vh_contrast,
            "infrastructure_distance_km": infra_km,
        }
        label_name, confidence, reasons = _classify(features, la)
        polygon = _polygon_from_mask(mask, raster)
        if not polygon:
            continue
        regions.append(
            Region(
                region_id=int(props.label),
                label=label_name,
                confidence=confidence,
                area_px=int(props.area),
                area_km2=float(props.area * pixel_km2),
                centroid_lonlat=centroid,
                polygon=polygon,
                features=features,
                reasons=reasons,
                major_axis_deg=bearing,
                major_axis_length_km=axis_km,
            )
        )

    regions.sort(key=lambda r: r.area_km2, reverse=True)
    ship_rows, ship_cols = np.nonzero(ships)
    ship_lon, ship_lat = pixel_to_lonlat(raster.transform, ship_rows, ship_cols)
    ship_points = _cluster_points(ship_lon, ship_lat)

    return Detection(
        regions=regions,
        dark_mask=dark,
        ship_pixels=ship_points,
        threshold_db=float(cfg["dark_offset_db"]),
    )


def _nearest_infrastructure_km(
    centroid: tuple[float, float], infrastructure: list[tuple[float, float]] | None
) -> float:
    if not infrastructure:
        return float("inf")
    lon, lat = centroid
    best = float("inf")
    for ilon, ilat in infrastructure:
        dx = (ilon - lon) * 111.320 * float(np.cos(np.deg2rad(lat)))
        dy = (ilat - lat) * 110.574
        best = min(best, float(np.hypot(dx, dy)))
    return best


def _classify(
    features: dict[str, float], la: dict[str, Any]
) -> tuple[str, float, list[dict[str, Any]]]:
    """Score a dark region as oil or look-alike, reporting each test separately.

    A low-wind cell, a biogenic film, a rain cell and a wind shadow all produce
    dark patches in a SAR image. They differ from a vessel discharge in shape and
    in edge behaviour, and those are exactly the terms exposed here -- with the
    value, the threshold and the weight -- so an analyst can see which test
    carried the decision instead of being handed a bare class name.
    """
    # Each entry: (feature key, comparison, human note)
    spec: list[tuple[str, str, str]] = [
        ("elongation", "ge",
         "A discharge from a moving vessel is elongated along its course; "
         "low-wind cells and biogenic films are compact."),
        ("perimeter_area_ratio", "le",
         "Ragged, convoluted boundaries indicate a natural surface film rather "
         "than a discharge."),
        ("edge_sharpness_ratio", "ge",
         "Oil damps capillary waves abruptly, so its boundary gradient stands "
         "out against the scene's own sea texture; a wind shadow fades."),
        ("contrast_db", "ge",
         "Damping weaker than this is within the natural variability of the sea "
         "surface at this incidence angle."),
        ("infrastructure_distance_km", "ge",
         "A dark patch sitting on known fixed infrastructure is that "
         "installation's routine sheen, not a passing vessel's discharge."),
    ]

    tests: list[dict[str, Any]] = []
    score = 0.0
    total_weight = 0.0
    for key, comparison, note in spec:
        cfg = la["tests"][key]
        threshold = float(cfg["threshold"])
        weight = float(cfg["weight"])
        value = float(features[key])
        if not np.isfinite(value):
            # An infinite distance-to-infrastructure means none is known nearby,
            # which supports oil; anything else non-finite is uninformative.
            passed = key == "infrastructure_distance_km"
        else:
            passed = value >= threshold if comparison == "ge" else value <= threshold
        total_weight += weight
        if passed:
            score += weight
        tests.append(
            {
                "feature": key,
                "value": None if not np.isfinite(value) else round(value, 4),
                "threshold": round(threshold, 4),
                "weight": round(weight, 3),
                "comparison": comparison,
                "passed": bool(passed),
                "supports": "oil" if passed else "look_alike",
                "note": note,
            }
        )

    confidence = score / total_weight if total_weight else 0.0
    label_name = CLASS_OIL if confidence >= float(la["decision_threshold"]) else CLASS_LOOKALIKE
    return label_name, confidence, tests


def _cluster_points(lon: np.ndarray, lat: np.ndarray, tol_deg: float = 0.004) -> list[tuple[float, float]]:
    """Collapse bright-pixel blobs into one point per ship."""
    points: list[tuple[float, float]] = []
    for x, y in zip(lon, lat, strict=True):
        for i, (px, py) in enumerate(points):
            if abs(px - x) < tol_deg and abs(py - y) < tol_deg:
                points[i] = ((px + float(x)) / 2, (py + float(y)) / 2)
                break
        else:
            points.append((float(x), float(y)))
        if len(points) > 400:
            break
    return points
