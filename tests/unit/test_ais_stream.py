"""The live AIS collector reports its own state honestly."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.ais.stream import AisCollector, ship_type_name


def _recent(minutes_ago: float) -> str:
    """The collector holds a rolling 24 h window, so a fixture timestamp from
    last year is correctly pruned. Tests exercise the live path with live-shaped
    times, in aisstream's own Go format."""
    when = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return when.strftime("%Y-%m-%d %H:%M:%S.%f000 +0000 UTC")


def test_go_format_timestamps_are_parsed():
    """aisstream emits Go's time format, with a nanosecond fraction and a space
    before the offset. Failing to parse it silently drops every position."""
    from core.ais.tracks import utc

    parsed = utc("2026-08-30 19:24:41.123456789 +0000 UTC")
    assert parsed.tzinfo is not None
    assert parsed.year == 2026 and parsed.hour == 19 and parsed.minute == 24


def test_ais_collector_status():
    """An unconfigured collector says so rather than pretending to be connected."""
    collector = AisCollector(api_key="")
    assert not collector.configured
    status = collector.status()
    assert status["configured"] is False
    assert status["connected"] is False
    assert status["vessels"] == 0


def test_position_reports_accumulate_into_tracks():
    collector = AisCollector(api_key="test-key")
    for i in range(5):
        collector._ingest({
            "MessageType": "PositionReport",
            "MetaData": {
                "MMSI": 431000123,
                "latitude": 9.30 + 0.001 * i,
                "longitude": 76.00 + 0.001 * i,
                "time_utc": _recent(60 - 5 * i),
            },
            "Message": {"PositionReport": {"Sog": 11.2, "Cog": 45.0}},
        })
    tracks = collector.tracks(min_fixes=3)
    assert len(tracks) == 1
    assert tracks[0].mmsi == "431000123"
    assert len(tracks[0].fixes) == 5
    assert collector.messages_seen == 5


def test_static_data_populates_identity():
    collector = AisCollector(api_key="test-key")
    collector._ingest({
        "MessageType": "ShipStaticData",
        "MetaData": {"MMSI": 431000123},
        "Message": {"ShipStaticData": {
            "Name": "MV EXAMPLE ", "ImoNumber": 9123456, "Type": 80,
            "Dimension": {"A": 120, "B": 60},
        }},
    })
    static = collector.static["431000123"]
    assert static["name"] == "MV EXAMPLE"
    assert static["imo"] == "9123456"
    assert static["ship_type"] == "tanker"
    assert static["length_m"] == 180


def test_ais_not_available_sentinels_are_not_treated_as_measurements():
    """102.3 kn and 360 degrees are AIS 'not available' codes, not readings."""
    collector = AisCollector(api_key="test-key")
    collector._ingest({
        "MessageType": "PositionReport",
        "MetaData": {"MMSI": 1, "latitude": 9.3, "longitude": 76.0,
                     "time_utc": _recent(10)},
        "Message": {"PositionReport": {"Sog": 102.3, "Cog": 360.0}},
    })
    fix = collector.fixes["1"][0]
    assert fix.sog_kn is None and fix.cog_deg is None


def test_ship_type_bands():
    assert ship_type_name(80) == "tanker"
    assert ship_type_name(70) == "cargo"
    assert ship_type_name(30) == "fishing"
    assert ship_type_name(None) == "unknown"
    assert ship_type_name(999) == "unknown"
