"""Golden scenarios: one click from a cold page to a working result."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import yaml

from core.config import CONFIG_DIR


@dataclass
class Scenario:
    id: str
    title: str
    subtitle: str
    kind: str
    label: str
    honesty_note: str
    bbox: list[float]
    raw: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "subtitle": self.subtitle,
            "kind": self.kind,
            "label": self.label,
            "honesty_note": " ".join(self.honesty_note.split()),
            "bbox": self.bbox,
            "known_source": self.raw.get("known_source"),
            "t_from": self.raw.get("t_from"),
            "t_to": self.raw.get("t_to"),
        }


@lru_cache(maxsize=1)
def load_all() -> dict[str, Scenario]:
    out: dict[str, Scenario] = {}
    for path in sorted((CONFIG_DIR / "scenarios").glob("*.yaml")):
        # Skip OS and editor sidecar files. macOS writes AppleDouble resource
        # forks named `._thing.yaml` beside real files; they match the glob, are
        # not text, and take the whole endpoint down when parsed.
        if path.name.startswith("."):
            continue
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        out[raw["id"]] = Scenario(
            id=raw["id"],
            title=raw["title"],
            subtitle=raw.get("subtitle", ""),
            kind=raw.get("kind", "custom"),
            label=raw.get("label", ""),
            honesty_note=raw.get("honesty_note", ""),
            bbox=[float(v) for v in raw["bbox"]],
            raw=raw,
        )
    return out


def get(scenario_id: str) -> Scenario | None:
    return load_all().get(scenario_id)
