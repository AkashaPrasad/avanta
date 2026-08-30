"""A vessel that is present on radar and absent from AIS must not disappear."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.ais.darkmatch import match_contacts
from core.ais.tracks import Fix, build_track


def _track(mmsi: str, lon: float, lat: float, when: datetime):
    return build_track(mmsi, [Fix(when + timedelta(minutes=5 * i), lon + 0.001 * i, lat, 10.0, 90.0)
                              for i in range(6)])


def test_contact_near_a_transmitting_vessel_is_matched():
    when = datetime(2025, 5, 26, 6, 0, tzinfo=timezone.utc)
    tracks = [_track("111", 76.00, 9.30, when)]
    dark, matched = match_contacts([(76.002, 9.3005)], tracks, when)
    assert dark == []
    assert "111" in matched


def test_contact_with_no_ais_becomes_a_dark_hypothesis():
    when = datetime(2025, 5, 26, 6, 0, tzinfo=timezone.utc)
    tracks = [_track("111", 76.00, 9.30, when)]
    dark, _ = match_contacts([(76.40, 9.55)], tracks, when)
    assert len(dark) == 1
    assert dark[0].nearest_mmsi == "111"
    assert dark[0].nearest_ais_km and dark[0].nearest_ais_km > 1.5


def test_a_dark_contact_becomes_a_single_vertex_track_flagged_as_dark():
    when = datetime(2025, 5, 26, 6, 0, tzinfo=timezone.utc)
    dark, _ = match_contacts([(76.40, 9.55)], [], when)
    track = dark[0].as_track()
    assert track.is_dark
    assert track.mmsi.startswith("DARK-")
    assert len(track.fixes) == 1


def test_dark_contacts_survive_the_prefilter_unconditionally():
    """A vessel must not be filtered out by a score computed from the data it is
    withholding."""
    from core.hypothesis.prefilter import SlickGeometry, prefilter

    when = datetime(2025, 5, 26, 6, 0, tzinfo=timezone.utc)
    geometry = SlickGeometry(76.10, 9.32, 45.0, 12.0, 8.0, when + timedelta(hours=4))
    dark, _ = match_contacts([(76.42, 9.58)], [], when)
    tracks = [_track(str(200 + i), 76.0 + 0.01 * i, 9.30, when) for i in range(12)]
    tracks.append(dark[0].as_track())

    results = prefilter(tracks, geometry, keep_top_k=3)
    dark_result = next(r for r in results if r.is_dark)
    assert dark_result.kept, "a dark contact must always survive the prefilter"
