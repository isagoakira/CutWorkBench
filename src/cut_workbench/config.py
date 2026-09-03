from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .capabilities import ProviderRegistry, RoutingPolicy
from .errors import ValidationError
from .local_providers import FfprobeProvider, JsonCommandProvider


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
