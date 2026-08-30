"""MARPOL Annex I, Appendix 3 evidence dossier.

Appendix 3 is an itemised list of evidence on an alleged contravention of the
discharge provisions, and IMO's own text notes that what reaches a flag State is
"often inadequate to enable prosecution". So the dossier is laid out field by
field against that list rather than as a report we found convenient to write.

Any field we cannot fill is printed as NOT AVAILABLE. A blank in an evidence
package reads as an oversight; an explicit NOT AVAILABLE reads as a boundary,
and tells the officer exactly what still has to be collected.
"""
from __future__ import annotations

import textwrap
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from core.config import data_dir
from core.dossier.manifest import build as build_manifest

TEMPLATE_DIR = Path(__file__).parent / "templates"
NOT_AVAILABLE = "NOT AVAILABLE"


@dataclass
class Dossier:
    mmsi: str
    run_id: str
    html: str
    fields: dict[str, Any]
    manifest: dict[str, Any]
    pdf_path: Path | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "mmsi": self.mmsi,
            "marpol_annex_i_appendix_3": self.fields,
            "reproducibility_manifest": self.manifest,
        }


def _or_na(value: Any) -> Any:
    if value is None or value == "" or (isinstance(value, float) and value != value):
        return NOT_AVAILABLE
    return value


class _DossierTextParser(HTMLParser):
    """Extract readable text for the dependency-free PDF fallback."""

    _blocks = {"article", "br", "dd", "div", "dt", "footer", "h1", "h2", "h3", "header", "li", "p", "section", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"style", "script"}:
            self._ignored_depth += 1
        elif not self._ignored_depth and tag in self._blocks:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"style", "script"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif not self._ignored_depth and tag in self._blocks:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def _write_basic_pdf(html: str, path: Path) -> None:
    """Write a readable standards-compliant PDF when WeasyPrint's native
    libraries are unavailable.

    The production container still uses the styled HTML renderer. This path is
    intentionally plain, but it preserves the complete evidence text instead
    of making dossier export fail on a workstation without Pango/Cairo.
    """
    parser = _DossierTextParser()
    parser.feed(html)
    paragraphs = [" ".join(part.split()) for part in "".join(parser.parts).splitlines()]
    lines: list[str] = []
    for paragraph in paragraphs:
        if paragraph:
            lines.extend(textwrap.wrap(paragraph, width=92, break_long_words=True) or [""])
            lines.append("")
    if not lines:
        lines = ["AVANTA evidence dossier", "No printable content was produced."]

    pages = [lines[index:index + 54] for index in range(0, len(lines), 54)]
    page_ids = [4 + index * 2 for index in range(len(pages))]
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{' '.join(f'{page_id} 0 R' for page_id in page_ids)}] /Count {len(pages)} >>".encode(),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }

    for index, page_lines in enumerate(pages):
        page_id = page_ids[index]
        content_id = page_id + 1
        commands = ["BT", "/F1 9 Tf", "46 795 Td", "12 TL"]
        for line in page_lines:
            safe = line.encode("latin-1", "replace").decode("latin-1")
            safe = safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(f"({safe}) Tj")
            commands.append("T*")
        commands.append("ET")
        stream = "\n".join(commands).encode("latin-1")
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode()
        objects[content_id] = f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * (max(objects) + 1)
    for object_id in sorted(objects):
        offsets[object_id] = len(pdf)
        pdf.extend(f"{object_id} 0 obj\n".encode())
        pdf.extend(objects[object_id])
        pdf.extend(b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    )
    path.write_bytes(pdf)


def _slick_description(regions: list[dict[str, Any]]) -> dict[str, Any]:
    """Appendix 3 asks for the physical description of the slick: its direction
    and its form -- continuous, in patches, or in windrows."""
    oil = [r for r in regions if (r.get("properties") or {}).get("class") == "oil"]
    if not oil:
        return {
            "form": NOT_AVAILABLE,
            "direction": NOT_AVAILABLE,
            "extent_km2": NOT_AVAILABLE,
            "appearance_note": NOT_AVAILABLE,
        }
    total = sum((r["properties"]["area_km2"] for r in oil), 0.0)
    largest = max(oil, key=lambda r: r["properties"]["area_km2"])
    props = largest["properties"]
    elongation = float(props["features"].get("elongation", 0.0))
    if len(oil) == 1 and elongation >= 3.0:
        form = "Continuous, in a single elongated band"
    elif len(oil) == 1:
        form = "Continuous, in a single patch"
    elif elongation >= 3.0:
        form = f"In windrows: {len(oil)} elongated bands"
    else:
        form = f"In patches: {len(oil)} discrete areas"
    return {
        "form": form,
        "direction": f"{props['major_axis_deg']:.0f}° (principal axis, degrees true)",
        "extent_km2": round(total, 3),
        "length_km": round(props["major_axis_length_km"], 2),
        "appearance_note": (
            f"Radar-dark region with {props['features'].get('contrast_db', 0):.1f} dB damping "
            "relative to the surrounding sea surface."
        ),
        "n_regions": len(oil),
    }


def build_fields(
    *,
    scene: dict[str, Any],
    run: dict[str, Any],
    mmsi: str,
    observer: str,
) -> dict[str, Any]:
    entries = (run.get("posterior") or {}).get("entries") or []
    entry = next((e for e in entries if e["hypothesis_id"] == mmsi), None)
    candidate = next((c for c in (run.get("candidates") or []) if c["mmsi"] == mmsi), None)
    tracks = (run.get("tracks") or {}).get(mmsi) or {}
    track_props: dict[str, Any] = {}
    for feature in tracks.get("features", []):
        if (feature.get("properties") or {}).get("segment") == "transmitted":
            track_props = feature["properties"]
            break

    wind = run.get("wind_gate") or {}
    regions = ((run.get("slick") or {}).get("features")) or []
    release = (candidate or {}).get("release") or {}

    gaps = [
        f["properties"]
        for f in tracks.get("features", [])
        if (f.get("properties") or {}).get("segment") == "gap"
    ]

    return {
        "section_1_vessel_identity": {
            "name": _or_na(track_props.get("name")),
            "imo_number": _or_na(track_props.get("imo")),
            "mmsi": mmsi,
            "flag_state": _or_na(track_props.get("flag")),
            "vessel_type": _or_na(track_props.get("ship_type")),
            "length_overall_m": _or_na(track_props.get("length_m")),
            "descriptive_data": _or_na(
                f"Median speed over ground {track_props.get('median_sog_kn')} kn over the observed track."
                if track_props.get("median_sog_kn") is not None
                else None
            ),
            "identity_source": _or_na(track_props.get("source")),
        },
        "section_2_observation": {
            "date_time_utc": _or_na(run.get("acquisition_utc")),
            "position_of_observation": _or_na(
                f"{(run.get('slick_centroid') or [None, None])[1]}, "
                f"{(run.get('slick_centroid') or [None, None])[0]}"
                if run.get("slick_centroid")
                else None
            ),
            "bbox": _or_na(scene.get("bbox")),
            "method_of_observation": (
                "Sentinel-1 C-band SAR, IW mode, dual polarisation (VV/VH), "
                "orthorectified sigma0 via the Copernicus Data Space Ecosystem."
            ),
            "identity_of_observer": observer,
            "imagery_reference": _or_na(scene.get("product_id")),
            "imagery_sha256": _or_na(scene.get("raster_sha256")),
        },
        "section_3_slick_description": _slick_description(regions),
        "section_4_sea_and_weather": {
            "wind_speed_ms": _or_na(wind.get("wind_speed_ms")),
            "wind_direction_deg": _or_na(wind.get("wind_direction_deg")),
            "wind_source": _or_na(wind.get("source")),
            "detectability_verdict": _or_na(wind.get("verdict")),
            "sea_state": NOT_AVAILABLE,
            "sky_conditions": NOT_AVAILABLE,
            "visibility": NOT_AVAILABLE,
        },
        "section_5_alleged_discharge": {
            "estimated_start_utc": _or_na(release.get("t_start")),
            "estimated_end_utc": _or_na(release.get("t_end")),
            "estimated_duration_hours": _or_na(release.get("duration_hours")),
            "estimated_rate_m3_per_h": _or_na(release.get("rate_m3_per_h")),
            "estimated_volume_m3": _or_na(release.get("volume_m3")),
            "oil_type_assumed": _or_na(release.get("oil_type")),
            "basis": (
                "Maximum-likelihood release parameters from a forward moving-line-source "
                "simulation seeded along the vessel's own AIS track."
            ),
        },
        "section_6_ais_behaviour": {
            "transmission_gaps": gaps or NOT_AVAILABLE,
            "total_gap_minutes": round(sum(g.get("minutes", 0.0) for g in gaps), 1) if gaps else 0.0,
            "behaviour_features": (candidate or {}).get("prior", {}).get("features", NOT_AVAILABLE),
        },
        "section_7_attribution": {
            "posterior_probability": _or_na(entry["probability"] if entry else None),
            "rank": _or_na(entry["rank"] if entry else None),
            "probability_unknown_source": _or_na((run.get("posterior") or {}).get("p_null")),
            "no_attribution_returned": (run.get("posterior") or {}).get("no_attribution", False),
            "log_likelihood": _or_na(entry["log_likelihood"] if entry else None),
            "log_prior": _or_na(entry["log_prior"] if entry else None),
            "method": (
                "Forward hypothesis test. For each candidate vessel a discharge was simulated "
                "forward along that vessel's own track and compared to the observed slick; the "
                "posterior is a softmax over all candidates and an explicit unknown-source "
                "hypothesis. No backward drift integration was used at any point."
            ),
            "caveat": (
                "This is an automated analysis. It is evidence for an investigation, not a "
                "finding of fact, and the probability is conditional on the candidate set "
                "actually observed."
            ),
        },
    }


def render(
    *,
    scene: dict[str, Any],
    run: dict[str, Any],
    provenance: dict[str, Any],
    mmsi: str,
    run_id: str,
    observer: str,
    write_pdf: bool = True,
) -> Dossier:
    fields = build_fields(scene=scene, run=run, mmsi=mmsi, observer=observer)
    manifest = build_manifest(scene=scene, provenance=provenance, run=run, mmsi=mmsi)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("marpol_appendix3.html")
    html = template.render(
        fields=fields,
        manifest=manifest,
        provenance=provenance,
        mmsi=mmsi,
        run_id=run_id,
        generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M timezone.utc"),
        not_available=NOT_AVAILABLE,
    )

    pdf_path: Path | None = None
    if write_pdf:
        out_dir = data_dir() / "dossiers"
        out_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = out_dir / f"avanta_{run_id}_{mmsi}.pdf"
        try:
            from weasyprint import HTML

            HTML(string=html).write_pdf(str(pdf_path))
        except Exception as exc:  # noqa: BLE001
            warnings.warn(
                f"Styled PDF renderer unavailable ({type(exc).__name__}); using the plain evidence renderer.",
                RuntimeWarning,
                stacklevel=2,
            )
            _write_basic_pdf(html, pdf_path)

    return Dossier(mmsi=mmsi, run_id=run_id, html=html, fields=fields, manifest=manifest, pdf_path=pdf_path)
