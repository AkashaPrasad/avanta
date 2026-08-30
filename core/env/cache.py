"""Disk cache for environmental forcing subsets.

CMEMS has no volume quota but a subset request still takes tens of seconds, and
the demo has to work with the network off. Keyed by bbox + window + variables so
an identical request is answered from disk.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.config import data_dir, fixtures_dir
from core.provenance.hashing import cache_key


def env_cache_path(kind: str, bbox: list[float], t_from: str, t_to: str, extra: Any = None) -> Path:
    key = cache_key(kind, [round(float(b), 3) for b in bbox], t_from, t_to, extra)
    root = data_dir() / "env"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{kind}_{key[:20]}.nc"


def fixture_path(kind: str) -> Path | None:
    candidates = sorted(fixtures_dir().joinpath("env").glob(f"{kind}_*.nc"))
    return candidates[0] if candidates else None
