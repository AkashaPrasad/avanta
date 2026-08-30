"""The INCOIS OOSA handoff: the integration thesis, as an endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    import os

    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path_factory.mktemp('db')}/test.db"
    os.environ["AISSTREAM_API_KEY"] = ""      # no live socket during tests
    from api.app.db import SessionLocal, create_all
    from api.app.main import app
    from api.app.models.records import AttributionRunRow
    from api.app.models.records import Scene as SceneRow

    create_all()
    with SessionLocal() as session:
        session.add(SceneRow(
            id="scene1", bbox=[70.2, 18.4, 71.6, 19.6], t_from="2026-08-25T00:00:00Z",
            t_to="2026-08-25T23:59:59Z", acquired_utc="2026-08-25T01:02:37+00:00",
            raster_path="/dev/null", raster_sha256="a" * 64, mode="LIVE",
        ))
        session.add(AttributionRunRow(
            id="run1", scene_id="scene1", result=_RUN, simulations={}, provenance={}, runtime_s=42.0,
        ))
        session.commit()

    with TestClient(app) as test_client:
        yield test_client


_RUN = {
    "acquisition_utc": "2026-08-25T01:02:37+00:00",
    "posterior": {"entries": [
        {"hypothesis_id": "431000123", "label": "MV EXAMPLE", "probability": 0.68,
         "log_likelihood": -90.0, "log_prior": 1.1, "score": -88.9, "is_null": False, "rank": 1}],
        "p_null": 0.12, "no_attribution": False},
    "candidates": [{
        "mmsi": "431000123", "name": "MV EXAMPLE",
        "release": {"t_start": "2026-08-24T21:00:00+00:00", "t_end": "2026-08-24T23:00:00+00:00",
                    "duration_hours": 2.0, "rate_m3_per_h": 4.0, "volume_m3": 8.0,
                    "oil_type": "GENERIC INTERMEDIATE FUEL OIL 180"},
        "seed": {"n_elements": 760, "distinct_seed_positions": 19, "distinct_seed_times": 19,
                 "degenerate": False},
    }],
    "tracks": {"431000123": {"features": [{
        "properties": {"segment": "transmitted"},
        "geometry": {"type": "LineString", "coordinates": [[70.9, 19.0], [71.0, 19.1], [71.1, 19.2]]},
    }]}},
}


def test_handoff_oosa(client):
    """Emits the release specification GNOME needs: a point, a time, a duration,
    a rate and the oil's own properties."""
    response = client.post("/api/v1/handoff/oosa", json={"run_id": "run1", "mmsi": "431000123"})
    assert response.status_code == 200
    payload = response.json()

    assert "GNOME" in payload["format"]
    assert "handoff format" in payload["note"], "it must not imply a live INCOIS connection"

    release = payload["release"]
    assert release["geometry_type"] == "moving_line_source"
    assert release["start_position"] == {"lon": 70.9, "lat": 19.0}
    assert release["start_time_utc"] == "2026-08-24T21:00:00+00:00"
    assert release["duration_hours"] == 2.0
    assert release["discharge_rate_m3_per_h"] == 4.0
    assert release["total_volume_m3"] == 8.0
    assert len(release["line_vertices"]) == 3

    assert "ADIOS" in payload["substance"]["database"]
    assert payload["attribution"]["posterior_probability"] == 0.68
    assert payload["attribution"]["probability_unknown_source"] == 0.12


def test_oosa_domain_check_is_honest(client):
    """OOSA covers 60-100E, 0-25N. A release outside it must be reported as
    outside, not silently forwarded."""
    payload = client.post("/api/v1/handoff/oosa",
                          json={"run_id": "run1", "mmsi": "431000123"}).json()
    check = payload["domain_check"]
    assert check["oosa_domain"] == {"lon_min": 60.0, "lon_max": 100.0, "lat_min": 0.0, "lat_max": 25.0}
    assert check["release_inside_domain"] is True
    assert "inside the INCOIS OOSA operational domain" in check["message"]


def test_unknown_run_is_a_404_not_an_empty_spec(client):
    assert client.post("/api/v1/handoff/oosa",
                       json={"run_id": "nope", "mmsi": "431000123"}).status_code == 404
    assert client.post("/api/v1/handoff/oosa",
                       json={"run_id": "run1", "mmsi": "999"}).status_code == 404


def test_health_reports_every_dependency(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body["dependencies"]) >= {"db", "cdse", "forcing", "ais", "model"}
    assert body["dependencies"]["db"]["status"] == "UP"
    # The segmenter must never claim a checkpoint it does not have.
    assert "classical detector" in body["dependencies"]["model"]["segmenter"]


def test_scenarios_are_listed_with_their_honesty_labels(client):
    scenarios = client.get("/api/v1/scenarios").json()["scenarios"]
    assert {s["id"] for s in scenarios} == {"elsa3", "synthetic-discharge", "live"}
    for scenario in scenarios:
        assert scenario["label"], "every scenario must carry a data-provenance label"
        assert scenario["honesty_note"]
        if scenario["kind"] != "live":
            assert scenario["t_from"] and scenario["t_to"], (
                f"{scenario['id']} must include the time window required by one-click ingest"
            )
