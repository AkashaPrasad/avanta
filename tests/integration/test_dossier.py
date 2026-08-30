"""AC-15 and AC-16: the dossier mirrors MARPOL Annex I Appendix 3, and the
manifest makes the result reproducible."""
from __future__ import annotations

import json

from core.dossier.builder import NOT_AVAILABLE, build_fields, render
from core.dossier.manifest import build as build_manifest

SCENE = {
    "bbox": [75.8, 9.0, 76.4, 9.6],
    "acquired_utc": "2025-05-28T00:41:37+00:00",
    "product_id": "S1A_IW_GRDH_1SDV_20250528T004137",
    "raster_sha256": "a" * 64,
}

RUN = {
    "acquisition_utc": "2025-05-28T00:41:37+00:00",
    "slick_centroid": [76.10, 9.32],
    "posterior": {
        "entries": [
            {"hypothesis_id": "431000123", "label": "MV EXAMPLE", "probability": 0.71,
             "log_likelihood": -96.2, "log_prior": 1.4, "score": -94.8, "is_null": False, "rank": 1},
            {"hypothesis_id": "H0", "label": "Unknown source", "probability": 0.19,
             "log_likelihood": -99.0, "log_prior": 0.0, "score": -99.0, "is_null": True, "rank": 2},
        ],
        "p_null": 0.19,
        "no_attribution": False,
    },
    "candidates": [{
        "mmsi": "431000123",
        "release": {"t_start": "2025-05-27T22:10:00+00:00", "t_end": "2025-05-27T23:40:00+00:00",
                    "duration_hours": 1.5, "rate_m3_per_h": 4.0, "volume_m3": 6.0,
                    "oil_type": "GENERIC INTERMEDIATE FUEL OIL 180"},
        "prior": {"features": [
            {"name": "ais_gap_overlap", "value": 0.82, "weight": 1.1, "contribution": 0.902,
             "explanation": "74 of 90 minutes fall inside an AIS transmission gap."}
        ]},
    }],
    "tracks": {"431000123": {"features": [
        {"properties": {"segment": "transmitted", "name": "MV EXAMPLE", "imo": "9123456",
                        "flag": "LBR", "ship_type": "tanker", "length_m": 180,
                        "median_sog_kn": 11.2, "source": "aisstream.io (live)"}},
        {"properties": {"segment": "gap", "start": "2025-05-27T22:20:00+00:00",
                        "end": "2025-05-28T00:34:00+00:00", "minutes": 134.0}},
    ]}},
    "slick": {"features": [{"properties": {
        "class": "oil", "area_km2": 12.4, "major_axis_deg": 47.0, "major_axis_length_km": 21.3,
        "features": {"elongation": 6.2, "contrast_db": 4.1},
    }}]},
    "wind_gate": {"wind_speed_ms": 6.4, "wind_direction_deg": 225.0, "passed": True,
                  "source": "ERA5", "verdict": "6.4 m/s — within the detectable band."},
}

PROVENANCE = {"sar": {"source": "CDSE", "mode": "LIVE", "sha256": "b" * 64}}


def test_every_appendix_3_section_is_present():
    fields = build_fields(scene=SCENE, run=RUN, mmsi="431000123", observer="duty officer")
    assert set(fields) == {
        "section_1_vessel_identity",
        "section_2_observation",
        "section_3_slick_description",
        "section_4_sea_and_weather",
        "section_5_alleged_discharge",
        "section_6_ais_behaviour",
        "section_7_attribution",
    }


def test_identity_and_observation_fields_are_filled_from_the_run():
    fields = build_fields(scene=SCENE, run=RUN, mmsi="431000123", observer="duty officer")
    identity = fields["section_1_vessel_identity"]
    assert identity["name"] == "MV EXAMPLE"
    assert identity["imo_number"] == "9123456"
    assert identity["mmsi"] == "431000123"
    observation = fields["section_2_observation"]
    assert "Sentinel-1" in observation["method_of_observation"]
    assert observation["identity_of_observer"] == "duty officer"
    assert observation["imagery_sha256"] == "a" * 64


def test_unknown_fields_say_not_available_rather_than_being_blank():
    """A blank in an evidence package reads as an oversight. An explicit gap
    tells the officer what still has to be collected."""
    fields = build_fields(scene=SCENE, run=RUN, mmsi="431000123", observer="obs")
    weather = fields["section_4_sea_and_weather"]
    assert weather["sea_state"] == NOT_AVAILABLE
    assert weather["sky_conditions"] == NOT_AVAILABLE
    assert weather["visibility"] == NOT_AVAILABLE
    assert weather["wind_speed_ms"] == 6.4


def test_slick_description_uses_appendix_3_vocabulary():
    """Appendix 3 asks for direction and form: continuous, in patches, or in
    windrows."""
    description = build_fields(scene=SCENE, run=RUN, mmsi="431000123", observer="o")[
        "section_3_slick_description"
    ]
    assert any(word in description["form"] for word in ("Continuous", "patches", "windrows"))
    assert "°" in description["direction"]
    assert description["extent_km2"] == 12.4


def test_ais_gap_is_carried_into_the_dossier():
    section = build_fields(scene=SCENE, run=RUN, mmsi="431000123", observer="o")[
        "section_6_ais_behaviour"
    ]
    assert section["total_gap_minutes"] == 134.0
    assert section["transmission_gaps"][0]["minutes"] == 134.0


def test_attribution_section_carries_the_null_hypothesis():
    section = build_fields(scene=SCENE, run=RUN, mmsi="431000123", observer="o")[
        "section_7_attribution"
    ]
    assert section["posterior_probability"] == 0.71
    assert section["probability_unknown_source"] == 0.19
    assert "no backward drift" in section["method"].lower()
    assert "not a finding of fact" in section["caveat"]


def test_pdf_is_generated_and_contains_the_appendix_3_headings():
    dossier = render(
        scene=SCENE, run=RUN, provenance=PROVENANCE,
        mmsi="431000123", run_id="testrun", observer="duty officer",
    )
    assert dossier.pdf_path is not None and dossier.pdf_path.exists()
    assert dossier.pdf_path.stat().st_size > 5_000

    raw = dossier.pdf_path.read_bytes()
    assert raw[:5] == b"%PDF-", "output is not a PDF"

    html = dossier.html
    for heading in ("Identity of the vessel", "Physical description of the oil slick",
                    "Reproducibility manifest", "MARPOL Annex I"):
        assert heading in html, f"the dossier is missing '{heading}'"
    assert NOT_AVAILABLE in html


def test_manifest_hashes():
    """AC-16: the manifest identifies every input by content hash, so a reviewer
    can verify the numbers were not adjusted after the fact."""
    manifest = build_manifest(scene=SCENE, provenance=PROVENANCE, run=RUN, mmsi="431000123")

    assert manifest["inputs"]["sar_raster_sha256"] == "a" * 64
    assert len(manifest["config"]["config_sha256"]) == 64
    assert set(manifest["config"]["files"]) == {"settings.yaml", "prior_weights.yaml"}
    assert manifest["method"]["integration"] == "forward only"
    assert "line source" in manifest["method"]["seeding"]
    assert len(manifest["manifest_sha256"]) == 64

    # The hash must be stable across runs for identical inputs, and must move
    # when an input moves -- otherwise it certifies nothing.
    again = build_manifest(scene=SCENE, provenance=PROVENANCE, run=RUN, mmsi="431000123")
    assert manifest["config"]["config_sha256"] == again["config"]["config_sha256"]

    altered = build_manifest(
        scene={**SCENE, "raster_sha256": "c" * 64},
        provenance=PROVENANCE, run=RUN, mmsi="431000123",
    )
    assert altered["manifest_sha256"] != manifest["manifest_sha256"]


def test_json_export_round_trips():
    dossier = render(scene=SCENE, run=RUN, provenance=PROVENANCE,
                     mmsi="431000123", run_id="testrun", observer="o")
    payload = json.loads(json.dumps(dossier.to_json()))
    assert payload["mmsi"] == "431000123"
    assert "marpol_annex_i_appendix_3" in payload
    assert "reproducibility_manifest" in payload
