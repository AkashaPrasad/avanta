"""Content-addressed disk cache.

Free CDSE accounts have a monthly Processing Unit budget, so a request that has
already been answered must never be sent twice. The key is the hash of
everything that could change the bytes coming back.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.config import data_dir
from core.provenance.hashing import cache_key, sha256_file


class BlobCache:
    def __init__(self, namespace: str) -> None:
        self.root = data_dir() / "cache" / namespace
        self.root.mkdir(parents=True, exist_ok=True)

    def key(self, *parts: Any) -> str:
        return cache_key(*parts)

    def path(self, key: str, suffix: str) -> Path:
        return self.root / f"{key}{suffix}"

    def meta_path(self, key: str) -> Path:
        return self.root / f"{key}.meta.json"

    def get(self, key: str, suffix: str) -> Path | None:
        candidate = self.path(key, suffix)
        return candidate if candidate.exists() and candidate.stat().st_size > 0 else None

    def put(self, key: str, suffix: str, payload: bytes, meta: dict[str, Any]) -> Path:
        target = self.path(key, suffix)
        tmp = target.with_suffix(target.suffix + ".partial")
        tmp.write_bytes(payload)
        tmp.replace(target)
        meta = {**meta, "sha256": sha256_file(target), "bytes": target.stat().st_size}
        self.meta_path(key).write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
        return target

    def meta(self, key: str) -> dict[str, Any]:
        path = self.meta_path(key)
        if not path.exists():
            return {}
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return loaded
