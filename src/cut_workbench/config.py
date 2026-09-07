from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .capabilities import ProviderRegistry, RoutingPolicy
from .errors import ValidationError
from .local_providers import FfprobeProvider, JsonCommandProvider


def _load_config_document(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValidationError("runtime config must be a JSON object")
    return data


def _is_loopback_host(host: str | None) -> bool:
    if host == "localhost":
        return True
    if host is None:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def load_vectcut_config(path: Path | None) -> dict[str, Any]:
    """Load the local VectCutAPI endpoint; localhost is the mandatory default."""
    data = _load_config_document(path)
    vectcut = data.get("vectcut", {})
    if not isinstance(vectcut, dict):
        raise ValidationError("vectcut config must be an object")
    base_url = vectcut.get("base_url", os.environ.get("CUT_WORKBENCH_VECTCUT_URL", "http://127.0.0.1:9001"))
    parsed_url = urlparse(base_url) if isinstance(base_url, str) else None
    try:
        port = parsed_url.port if parsed_url is not None else None
    except ValueError as error:
        raise ValidationError("vectcut.base_url must include a valid port") from error
    if (
        parsed_url is None
        or parsed_url.scheme not in {"http", "https"}
        or not _is_loopback_host(parsed_url.hostname)
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ValidationError("vectcut.base_url must be an http(s) URL on a local loopback host")
    timeout = vectcut.get("timeout", 120)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValidationError("vectcut.timeout must be a positive number")
    draft_folder = vectcut.get("draft_folder")
    if draft_folder is not None and not isinstance(draft_folder, str):
        raise ValidationError("vectcut.draft_folder must be a string")
    return {"base_url": base_url, "timeout": float(timeout), "draft_folder": draft_folder}


def load_runtime_config(path: Path | None) -> tuple[ProviderRegistry, RoutingPolicy]:
    data = _load_config_document(path)
    provider_items = data.get("providers", [])
    if not isinstance(provider_items, list):
        raise ValidationError("providers config must be a list")

    providers = []
    has_ffprobe = False
    for item in provider_items:
        if not isinstance(item, dict):
            raise ValidationError("each provider config must be an object")
        kind = item.get("kind")
        if kind == "ffprobe":
            providers.append(FfprobeProvider(item.get("executable", "ffprobe")))
            has_ffprobe = True
        elif kind == "json-command":
            providers.append(JsonCommandProvider(
                provider_id=item["provider_id"], capabilities=item["capabilities"],
                command=item["command"], timeout=float(item.get("timeout", 3600)),
            ))
        else:
            raise ValidationError(f"unknown provider kind: {kind}")

    # A VectCut-only runtime config must not silently remove the documented
    # default media probe provider.  An explicit ffprobe entry still controls
    # the executable path when a machine needs an override.
    if not has_ffprobe:
        providers.insert(0, FfprobeProvider())

    routing = data.get("routing")
    if routing is not None and not isinstance(routing, dict):
        raise ValidationError("routing config must be an object")
    policy = RoutingPolicy(
        rules=routing.get("rules", {}), default_route=routing.get("default_route", "agent")
    ) if routing else RoutingPolicy.default()
    return ProviderRegistry(providers), policy
