from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .capabilities import ProviderRegistry, RoutingPolicy
from .errors import ValidationError
from .local_providers import FfprobeProvider, JsonCommandProvider


def load_vectcut_config(path: Path | None) -> dict[str, Any]:
    """Load the local VectCutAPI endpoint; localhost is the mandatory default."""
    data: dict[str, Any] = {}
    if path is not None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    vectcut = data.get("vectcut", {})
    if not isinstance(vectcut, dict):
        raise ValidationError("vectcut config must be an object")
    base_url = vectcut.get("base_url", os.environ.get("CUT_WORKBENCH_VECTCUT_URL", "http://127.0.0.1:9001"))
    if not isinstance(base_url, str) or not base_url.startswith(("http://", "https://")):
        raise ValidationError("vectcut.base_url must be an http(s) URL")
    timeout = vectcut.get("timeout", 120)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValidationError("vectcut.timeout must be a positive number")
    draft_folder = vectcut.get("draft_folder")
    if draft_folder is not None and not isinstance(draft_folder, str):
        raise ValidationError("vectcut.draft_folder must be a string")
    return {"base_url": base_url, "timeout": float(timeout), "draft_folder": draft_folder}


def load_runtime_config(path: Path | None) -> tuple[ProviderRegistry, RoutingPolicy]:
    if path is None:
        return ProviderRegistry([FfprobeProvider()]), RoutingPolicy.default()
    data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    providers = []
    for item in data.get("providers", []):
        kind = item.get("kind")
        if kind == "ffprobe":
            providers.append(FfprobeProvider(item.get("executable", "ffprobe")))
        elif kind == "json-command":
            providers.append(JsonCommandProvider(
                provider_id=item["provider_id"], capabilities=item["capabilities"],
                command=item["command"], timeout=float(item.get("timeout", 3600)),
            ))
        else:
            raise ValidationError(f"unknown provider kind: {kind}")
    routing = data.get("routing")
    policy = RoutingPolicy(
        rules=routing.get("rules", {}), default_route=routing.get("default_route", "agent")
    ) if routing else RoutingPolicy.default()
    return ProviderRegistry(providers), policy
