"""Configuration loading. Every tunable that changes a result is read from
config/*.yaml so the dossier can cite the exact value that produced a number."""
from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"


def data_dir() -> Path:
    path = Path(os.environ.get("DATA_DIR", REPO_ROOT / "data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def fixtures_dir() -> Path:
    return REPO_ROOT / "fixtures"


def _load(name: str) -> dict[str, Any]:
    with (CONFIG_DIR / name).open("rb") as handle:
        raw = handle.read()
    parsed: dict[str, Any] = yaml.safe_load(raw)
    parsed["_sha256"] = hashlib.sha256(raw).hexdigest()
    return parsed


@lru_cache(maxsize=1)
def settings() -> dict[str, Any]:
    return _load("settings.yaml")


@lru_cache(maxsize=1)
def prior_weights() -> dict[str, Any]:
    return _load("prior_weights.yaml")


def config_sha() -> str:
    """One hash covering every config file, for the reproducibility manifest."""
    digest = hashlib.sha256()
    for name in sorted(("settings.yaml", "prior_weights.yaml")):
        digest.update((CONFIG_DIR / name).read_bytes())
    return digest.hexdigest()
