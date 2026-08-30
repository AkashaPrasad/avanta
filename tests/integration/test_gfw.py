"""Global Fishing Watch: identity resolution and AIS-off events."""
from __future__ import annotations

import pytest

from core.ais.gfw import GfwClient

pytestmark = pytest.mark.network


def _client() -> GfwClient:
    client = GfwClient()
    if not client.configured:
        pytest.skip("GFW_API_TOKEN is not set")
    return client


def test_gfw_identity():
    """An MMSI resolves to the registry fields a flag-State referral needs.

    MSC ELSA 3 is the validation case: its identity is public, so it is a
    genuine check that the lookup returns the right vessel rather than any
    vessel.
    """
    identity = _client().identity_for_mmsi("636016814")
    assert identity is not None, "MSC ELSA 3 was not found in the GFW registry"
    assert identity.mmsi == "636016814"
    assert identity.imo == "9123221"
    assert identity.name and "ELSA" in identity.name.upper()
    assert identity.callsign
    payload = identity.to_dict()
    assert "Global Fishing Watch" in payload["source"]


def test_gfw_gap_events():
    """AIS-off events are the maintained source behind the ais_gap_overlap prior
    feature. Coverage runs 2020 to roughly 72 hours ago.

    A gap query is a heavy spatial scan and GFW intermittently times out on it.
    An upstream stall is not a defect in this code, so it skips loudly rather
    than failing -- but when the API does answer, the shape of what it returns
    is asserted properly.
    """
    from core.ais.gfw import GfwUnavailable

    try:
        events = _client().gap_events([60.0, 5.0, 78.0, 25.0], "2025-01-01", "2025-06-30", limit=50)
    except GfwUnavailable as exc:
        pytest.skip(f"GFW gap endpoint is not answering right now: {exc}")
    assert events, "GFW answered but returned no AIS-off events for the Arabian Sea in 2025"

    gaps = _client().gaps_by_mmsi([60.0, 5.0, 78.0, 25.0], "2025-01-01", "2025-06-30")
    assert gaps, "events were returned but none survived parsing into gaps"
    for mmsi, events in list(gaps.items())[:5]:
        assert mmsi.isdigit()
        for gap in events:
            assert gap.end > gap.start
            assert gap.minutes > 0


def test_infrastructure_refusal_is_reported_not_swallowed():
    """This dataset is not in every token's permissions. A refusal must surface
    as 'unavailable', never as 'there are no platforms here'."""
    points, status = _client().infrastructure([70.0, 18.0, 72.0, 20.0])
    assert status == "ok" or status.startswith("unavailable")
    if status != "ok":
        assert points == []
