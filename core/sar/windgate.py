"""The wind gate.

Oil is visible in a SAR image because it damps the short capillary waves that
produce radar backscatter. That mechanism has a working range at both ends:

  below ~3 m/s  the sea is already too smooth -- there is nothing for the oil to
                damp, so a slick and calm water are indistinguishable, and dark
                patches in the image are low-wind cells rather than oil;
  above ~10 m/s wind mixes surface oil down into the water column and rebuilds
                the capillary field, so a real slick stops showing contrast.

Outside that band a negative detection carries almost no information, and
reporting one as if it did is how a remote-sensing tool loses an analyst's
trust. The gate refuses the scene and says the number that made it refuse.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.config import settings


@dataclass
class WindGate:
    wind_speed_ms: float
    wind_direction_deg: float
    min_ms: float
    max_ms: float
    passed: bool
    verdict: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "wind_speed_ms": round(self.wind_speed_ms, 1),
            "wind_direction_deg": round(self.wind_direction_deg, 1),
            "min_ms": self.min_ms,
            "max_ms": self.max_ms,
            "passed": self.passed,
            "verdict": self.verdict,
            "source": self.source,
        }


def evaluate(wind_speed_ms: float, wind_direction_deg: float, source: str) -> WindGate:
    cfg = settings()["windgate"]
    low, high = float(cfg["min_ms"]), float(cfg["max_ms"])
    # Round once, here, and use the same figure in the verdict and in the
    # payload. Formatting the raw value separately in each place makes the card
    # read "11.2 m/s" above a sentence that says "11.1 m/s", which invites the
    # reader to wonder which number the gate actually used.
    shown = round(float(wind_speed_ms), 1)
    if wind_speed_ms < low:
        verdict = (
            f"{shown:.1f} m/s — below the {low:.0f} m/s detection floor. "
            "The sea surface is already too smooth for oil to produce radar contrast, "
            "so a dark patch here cannot be distinguished from a low-wind cell and an "
            "absence of detection means nothing."
        )
        passed = False
    elif wind_speed_ms > high:
        verdict = (
            f"{shown:.1f} m/s — above the {high:.0f} m/s detection ceiling. "
            "Wind at this speed mixes surface oil into the water column and rebuilds the "
            "capillary wave field, so a slick that is present may leave no radar signature."
        )
        passed = False
    else:
        verdict = (
            f"{shown:.1f} m/s — within the detectable band "
            f"({low:.0f}–{high:.0f} m/s). Slick features in this scene are physically plausible."
        )
        passed = True
    return WindGate(shown, wind_direction_deg, low, high, passed, verdict, source)
