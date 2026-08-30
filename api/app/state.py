"""Process-wide singletons: the live AIS collector and the scene cache."""
from __future__ import annotations

from core.ais.stream import AisCollector
from core.pipeline import SceneBundle

collector = AisCollector()

# Ingested scenes are held in memory keyed by scene id. The raster and forcing
# files themselves live on disk and are re-read on a cache miss, so a restart
# costs a re-read rather than a re-download.
_bundles: dict[str, SceneBundle] = {}


def put_bundle(scene_id: str, bundle: SceneBundle) -> None:
    _bundles[scene_id] = bundle
    while len(_bundles) > 12:
        _bundles.pop(next(iter(_bundles)))


def get_bundle(scene_id: str) -> SceneBundle | None:
    return _bundles.get(scene_id)


def bundle_ids() -> list[str]:
    return list(_bundles)
