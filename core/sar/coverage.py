"""Scene coverage: how much of the requested area was actually imaged.

Kept beside the wind gate because it answers the same shape of question. The
wind gate asks whether a slick could have been *seen* if it were there; this
asks whether we *looked*. Both can turn a negative detection from evidence into
nothing at all, and both must say so with the number that decided it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.config import settings


@dataclass
class Coverage:
    fraction: float
    min_fraction: float
    sufficient: bool
    verdict: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "fraction": round(self.fraction, 4),
            "percent": round(self.fraction * 100, 1),
            "min_fraction": self.min_fraction,
            "sufficient": self.sufficient,
            "verdict": self.verdict,
        }


def evaluate(fraction: float) -> Coverage:
    minimum = float(settings()["coverage"]["min_fraction"])
    percent = fraction * 100.0
    if fraction >= minimum:
        verdict = (
            f"{percent:.0f}% of the requested area was imaged by this pass. "
            "A negative detection over it is informative."
        )
        return Coverage(fraction, minimum, True, verdict)
    verdict = (
        f"Only {percent:.0f}% of the requested area falls inside this "
        f"acquisition's swath, below the {minimum * 100:.0f}% threshold. Finding no "
        "slick here says little about the rest of the box, which was never "
        "imaged. Move the search window to a pass that covers it."
    )
    return Coverage(fraction, minimum, False, verdict)
