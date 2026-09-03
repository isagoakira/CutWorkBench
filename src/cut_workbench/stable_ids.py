from __future__ import annotations

from typing import Any, Mapping


STABLE_ID_COLLECTIONS = (
    "sources", "tracks", "segments", "controls", "captions", "decisions",
    "capability_downgrades", "external_entities",
)


def stable_id_exists(project: Mapping[str, Any], stable_id: str) -> bool:
    return (
        any(stable_id in project.get(name, {}) for name in STABLE_ID_COLLECTIONS)
        or any(item.get("verification_id") == stable_id for item in project.get("verification", []))
        or stable_id in (project.get("production_workflow") or {}).get("artifacts", {})
    )
