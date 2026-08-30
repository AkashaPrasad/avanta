"""The behaviour prior, log pi(v).

A thin layer over core.ais.features: the features are computed there, this
assembles them into a log prior and keeps the per-feature contributions
attached so the evidence panel can show them adding up to the number.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.ais.features import FeatureValue, compute, log_prior
from core.ais.tracks import Track
from core.config import prior_weights, settings


@dataclass
class PriorResult:
    log_prior: float
    features: list[FeatureValue]
    weights_version: str
    weights_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "log_prior": round(self.log_prior, 4),
            "features": [f.to_dict() for f in self.features],
            "weights_version": self.weights_version,
            "weights_sha256": self.weights_sha256,
            "sums_to": round(sum(f.contribution for f in self.features), 6),
        }


def evaluate(track: Track, window_start: datetime, window_end: datetime, **kwargs: Any) -> PriorResult:
    cfg = prior_weights()
    features = compute(track, window_start, window_end, **kwargs)
    return PriorResult(
        log_prior=log_prior(features),
        features=features,
        weights_version=str(cfg["version"]),
        weights_sha256=str(cfg["_sha256"]),
    )


def null_log_prior() -> float:
    """log pi_0 for the "unknown source" hypothesis.

    Zero by default: H0 is given no behavioural head start and no handicap. It
    competes on likelihood alone, which is the conservative choice -- it means a
    named vessel can only win by explaining the observation better, not by being
    the only option on the list.
    """
    return float(settings()["score"]["null_prior_logit"])
