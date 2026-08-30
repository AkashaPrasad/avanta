"""The posterior over candidate vessels, including an explicit "unknown source".

    score(v)  = logL(v) + log π(v)
    score(H0) = logL_null + log π_0
    p(· | obs) = softmax over all candidates and H0

H0 is not optional and it is not a formality. Without it a softmax over
candidates is normalised over a set that is *assumed* to contain the culprit, so
the top-ranked vessel receives a high probability even when no hypothesis fits
the evidence at all. That is precisely the failure mode that makes an automated
enforcement tool dangerous: it cannot return "I don't know", so it accuses
whoever happens to be closest.

With H0 in the ranking, the system can say the true thing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from core.config import settings

H0_ID = "H0"
H0_LABEL = "Unknown source — none of the observed candidates"


@dataclass
class Hypothesis:
    hypothesis_id: str
    label: str
    log_likelihood: float
    log_prior: float
    is_null: bool = False
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def score(self) -> float:
        return self.log_likelihood + self.log_prior


@dataclass
class PosteriorEntry:
    hypothesis_id: str
    label: str
    probability: float
    log_likelihood: float
    log_prior: float
    score: float
    is_null: bool
    rank: int
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "label": self.label,
            "probability": round(self.probability, 6),
            "log_likelihood": round(self.log_likelihood, 4),
            "log_prior": round(self.log_prior, 4),
            "score": round(self.score, 4),
            "is_null": self.is_null,
            "rank": self.rank,
            **self.detail,
        }


@dataclass
class Posterior:
    entries: list[PosteriorEntry]
    p_null: float
    no_attribution: bool
    threshold: float

    def top(self) -> PosteriorEntry | None:
        real = [e for e in self.entries if not e.is_null]
        return real[0] if real else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "p_null": round(self.p_null, 6),
            "no_attribution": self.no_attribution,
            "h0_threshold": self.threshold,
            "sums_to": round(sum(e.probability for e in self.entries), 9),
        }


def softmax(scores: np.ndarray) -> np.ndarray:
    shifted = scores - np.max(scores)
    exponentiated = np.exp(shifted)
    return exponentiated / exponentiated.sum()


def build(hypotheses: list[Hypothesis]) -> Posterior:
    if not hypotheses:
        raise ValueError("A posterior needs at least the null hypothesis.")
    cfg = settings()["score"]
    scores = np.array([h.score for h in hypotheses], dtype=float)
    probabilities = softmax(scores)

    order = np.argsort(-probabilities)
    entries: list[PosteriorEntry] = []
    for rank, index in enumerate(order, start=1):
        h = hypotheses[int(index)]
        entries.append(
            PosteriorEntry(
                hypothesis_id=h.hypothesis_id,
                label=h.label,
                probability=float(probabilities[int(index)]),
                log_likelihood=h.log_likelihood,
                log_prior=h.log_prior,
                score=h.score,
                is_null=h.is_null,
                rank=rank,
                detail=h.detail,
            )
        )
    p_null = float(sum(e.probability for e in entries if e.is_null))
    threshold = float(cfg["h0_display_threshold"])
    return Posterior(entries, p_null, p_null > threshold, threshold)
