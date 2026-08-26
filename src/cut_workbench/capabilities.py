from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

from .errors import ValidationError
from .jobs import CapabilityJobStore


@dataclass(frozen=True)
class CapabilityRequest:
    capability: str
    inputs: Mapping[str, Any]
    quality: str = "standard"
    sensitivity: str = "local-only"
    constraints: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CapabilityResult:
    capability: str
    provider_id: str
    payload: Mapping[str, Any]
    evidence: list[str] = field(default_factory=list)


class CapabilityProvider(Protocol):
    provider_id: str

    def supports(self, capability: str) -> bool: ...

    def execute(self, request: CapabilityRequest) -> CapabilityResult: ...


class ProviderRegistry:
    def __init__(self, providers: Iterable[CapabilityProvider] = ()) -> None:
        self._providers = list(providers)

    def find(self, capability: str) -> CapabilityProvider | None:
        return next((provider for provider in self._providers if provider.supports(capability)), None)

    def describe(self) -> list[dict[str, str]]:
        return [{"provider_id": provider.provider_id} for provider in self._providers]


@dataclass(frozen=True)
class RoutingPolicy:
    rules: Mapping[str, Mapping[str, str]]
    default_route: str = "agent"

    @classmethod
    def default(cls) -> "RoutingPolicy":
        return cls(
            rules={
                "media.probe": {"standard": "local", "high": "local"},
                "audio.transcribe.words": {"standard": "local", "high": "agent"},
                "audio.detect.silence": {"standard": "local", "high": "local"},
                "audio.detect.beats": {"standard": "local", "high": "agent"},
                "video.detect.scenes": {"standard": "local", "high": "agent"},
                "video.interpret.frames": {"standard": "agent", "high": "agent"},
                "edit.plan": {"standard": "agent", "high": "agent"},
                "edit.verify.semantic": {"standard": "agent", "high": "agent"},
            }
        )

    @classmethod
    def from_file(cls, path: Path) -> "RoutingPolicy":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(rules=data.get("rules", {}), default_route=data.get("default_route", "agent"))

    def route(self, request: CapabilityRequest, *, local_available: bool) -> str:
        route = self.rules.get(request.capability, {}).get(request.quality, self.default_route)
        if route == "local" and not local_available:
            return "agent"
        if route not in {"local", "agent"}:
            raise ValidationError(f"invalid route '{route}' for capability {request.capability}")
        return route


class CapabilityOrchestrator:
    """Routes stable capability requests without exposing provider-specific details."""

    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        jobs: CapabilityJobStore,
        policy: RoutingPolicy,
    ) -> None:
        self.registry = registry
        self.jobs = jobs
        self.policy = policy

    def request(self, request: CapabilityRequest) -> dict[str, Any]:
        provider = self.registry.find(request.capability)
        route = self.policy.route(request, local_available=provider is not None)
        request_data = asdict(request)
        if route == "agent":
            return self.jobs.create(request=request_data, provider_id="agent-native", status="pending_agent")

        if provider is None:
            raise ValidationError(f"no local provider for capability: {request.capability}")
        job = self.jobs.create(request=request_data, provider_id=provider.provider_id, status="running")
        result = provider.execute(request)
        if result.capability != request.capability:
            raise ValidationError("provider returned a result for the wrong capability")
        return self.jobs.complete(
            job_id=job["job_id"],
            provider_id=result.provider_id,
            payload=dict(result.payload),
            evidence=list(result.evidence),
        )

    def submit_agent_result(
        self,
        *,
        job_id: str,
        agent_id: str,
        payload: dict[str, Any],
        evidence: list[str],
    ) -> dict[str, Any]:
        job = self.jobs.read(job_id)
        if job["status"] != "pending_agent":
            raise ValidationError(f"job is not awaiting an agent result: {job_id}")
        if not agent_id:
            raise ValidationError("agent_id is required")
        return self.jobs.complete(
            job_id=job_id,
            provider_id=f"agent:{agent_id}",
            payload=payload,
            evidence=evidence,
        )
