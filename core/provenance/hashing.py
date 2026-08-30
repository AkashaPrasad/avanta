"""Content hashing. Every artefact AVANTA consumes or emits is identified by the
sha256 of its bytes, which is what makes the dossier reproducible."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(obj: Any) -> str:
    """Stable hash of a JSON-serialisable object; key order must not matter."""
    return sha256_bytes(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode())


def cache_key(*parts: Any) -> str:
    return sha256_json(list(parts))


def git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=Path(__file__).resolve().parent.parent.parent,
        )
        return out.stdout.strip() or "unavailable"
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
