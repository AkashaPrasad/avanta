"""AC-6: the wind gate rejects scenes where a slick could not be seen."""
from __future__ import annotations

import pytest

from core.sar.windgate import evaluate


def test_low_wind_is_gated():
    gate = evaluate(1.8, 270.0, "ERA5")
    assert not gate.passed
    assert "1.8" in gate.verdict and "below" in gate.verdict


def test_high_wind_is_gated():
    gate = evaluate(12.1, 270.0, "ERA5")
    assert not gate.passed
    assert "above" in gate.verdict


def test_normal_wind_passes():
    gate = evaluate(6.4, 225.0, "ERA5")
    assert gate.passed
    assert "within the detectable band" in gate.verdict


@pytest.mark.parametrize("speed", [3.0, 5.0, 10.0])
def test_band_edges_are_inclusive(speed):
    assert evaluate(speed, 180.0, "ERA5").passed


def test_the_measured_number_is_always_reported():
    """A gate that says 'gated' without the number is not auditable."""
    gate = evaluate(2.4, 100.0, "ERA5 via Open-Meteo")
    payload = gate.to_dict()
    assert payload["wind_speed_ms"] == 2.4
    assert payload["min_ms"] == 3.0 and payload["max_ms"] == 10.0
    assert payload["source"] == "ERA5 via Open-Meteo"
