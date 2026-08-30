"""The provenance block that rides on every API response.

Its purpose is honesty: a reader must be able to tell, without asking, whether a
number came from a live satellite request, a disk cache, a bundled fixture, or a
synthetic generator.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from core.config import config_sha, prior_weights
from core.provenance.hashing import git_sha

DataMode = Literal["LIVE", "CACHED", "FIXTURE", "SYNTHETIC", "DOWN"]


@dataclass
class SourceRecord:
    source: str
    mode: DataMode
    sha256: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in (None, {})}


@dataclass
class Provenance:
    sar: SourceRecord | None = None
    wind: SourceRecord | None = None
    currents: SourceRecord | None = None
    ais: SourceRecord | None = None
    model: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        block: dict[str, Any] = {}
        for name in ("sar", "wind", "currents", "ais"):
            record = getattr(self, name)
            if record is not None:
                block[name] = record.to_dict()
        block["model"] = {
            "prior_weights": f"prior_weights.yaml@sha256:{prior_weights()['_sha256']}",
            **self.model,
        }
        block["code"] = {"git_sha": git_sha(), "config_sha": config_sha()}
        block["run_utc"] = datetime.now(timezone.utc).isoformat()
        return block


def worst_mode(*modes: DataMode) -> DataMode:
    """The mode a combined result should advertise: the least-live input wins,
    because a result is only as live as its stalest ingredient."""
    order: list[DataMode] = ["DOWN", "SYNTHETIC", "FIXTURE", "CACHED", "LIVE"]
    present = [m for m in modes if m in order]
    if not present:
        return "DOWN"
    return min(present, key=order.index)
