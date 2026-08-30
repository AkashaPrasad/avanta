"""Reproducibility manifest.

The claim a dossier makes is not just "this vessel probably did it". It is
"here is everything that produced that number, and you can run it again". The
manifest is what makes the second half true: every input identified by content
hash, every config value that shaped the result, and the code revision.

Without this a dossier is an assertion. With it, it is a record.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.config import CONFIG_DIR, config_sha, prior_weights, settings
from core.provenance.hashing import git_sha, sha256_file, sha256_json


def build(
    *,
    scene: dict[str, Any],
    provenance: dict[str, Any],
    run: dict[str, Any],
    mmsi: str,
) -> dict[str, Any]:
    inputs = {
        "sar_raster_sha256": scene.get("raster_sha256"),
        "sar_product_id": scene.get("product_id"),
        "bbox": scene.get("bbox"),
        "acquisition_utc": scene.get("acquired_utc"),
    }
    config_files = {
        name: sha256_file(CONFIG_DIR / name) for name in ("settings.yaml", "prior_weights.yaml")
    }
    manifest: dict[str, Any] = {
        "manifest_version": "1.0",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "subject_mmsi": mmsi,
        "inputs": inputs,
        "provenance": provenance,
        "config": {
            "config_sha256": config_sha(),
            "files": config_files,
            "prior_weights_version": prior_weights()["version"],
            "settings_version": settings()["version"],
            "likelihood": {
                "epsilon": settings()["score"]["epsilon"],
                "beta": settings()["score"]["beta"],
                "kernel_sigma_px": settings()["score"]["kernel_sigma_px"],
                "grid_downsample": settings()["score"]["likelihood_grid_downsample"],
            },
            "simulation": {
                "n_ensemble": settings()["simulate"]["n_ensemble"],
                "n_per_point": settings()["simulate"]["n_per_point"],
                "time_step_s": settings()["simulate"]["time_step_s"],
                "wind_drift_factor": settings()["simulate"]["wind_drift_factor"],
                "horizontal_diffusivity": settings()["simulate"]["horizontal_diffusivity"],
            },
        },
        "code": {"git_sha": git_sha()},
        "result": {
            "posterior": run.get("posterior"),
            "acquisition_utc": run.get("acquisition_utc"),
        },
        "method": {
            "integration": "forward only",
            "seeding": "moving line source along the vessel's own AIS track",
            "null_hypothesis": "explicit; posterior includes p(H0)",
            "backward_drift": "not used anywhere; see core/simulate/openoil_runner.py",
        },
    }
    manifest["manifest_sha256"] = sha256_json(manifest)
    return manifest
