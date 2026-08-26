from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cut_workbench.capabilities import (
    CapabilityOrchestrator,
    CapabilityRequest,
    CapabilityResult,
    ProviderRegistry,
    RoutingPolicy,
)
from cut_workbench.jobs import CapabilityJobStore


class FakeLocalProvider:
    provider_id = "local:test"

    def supports(self, capability: str) -> bool:
        return capability in {"audio.transcribe.words", "audio.detect.silence"}

    def execute(self, request: CapabilityRequest) -> CapabilityResult:
        return CapabilityResult(
            capability=request.capability,
            provider_id=self.provider_id,
            payload={"words": [{"text": "hello", "start": 0.0, "end": 0.4}]},
            evidence=["fixture.wav"],
        )


class CapabilityOrchestratorTests(unittest.TestCase):
    def test_light_analysis_runs_locally_but_high_precision_visual_work_is_left_for_agent(self) -> None:
        with TemporaryDirectory() as directory:
            jobs = CapabilityJobStore(Path(directory))
            registry = ProviderRegistry([FakeLocalProvider()])
            orchestrator = CapabilityOrchestrator(
                registry=registry,
                jobs=jobs,
                policy=RoutingPolicy.default(),
            )

            local = orchestrator.request(
                CapabilityRequest(
                    capability="audio.transcribe.words",
                    inputs={"media_path": "fixture.wav"},
                    quality="standard",
                    sensitivity="local-only",
                )
            )
            self.assertEqual("completed", local["status"])
            self.assertEqual("local:test", local["provider_id"])

            agent_job = orchestrator.request(
                CapabilityRequest(
                    capability="video.interpret.frames",
                    inputs={"evidence_paths": ["contact-sheet-001.jpg"]},
                    quality="high",
                    sensitivity="summaries-only",
                )
            )
            self.assertEqual("pending_agent", agent_job["status"])
            self.assertEqual("agent-native", agent_job["provider_id"])
            self.assertEqual([agent_job["job_id"]], [job["job_id"] for job in jobs.pending()])

            completed = orchestrator.submit_agent_result(
                job_id=agent_job["job_id"],
                agent_id="codex",
                payload={"events": [{"start": 0.0, "end": 1.0, "description": "title card"}]},
                evidence=["contact-sheet-001.jpg"],
            )
            self.assertEqual("completed", completed["status"])
            self.assertEqual("agent:codex", completed["provider_id"])

    def test_policy_can_move_a_capability_between_local_and_agent_without_callers_changing(self) -> None:
        policy = RoutingPolicy(
            rules={"audio.transcribe.words": {"standard": "agent", "high": "agent"}},
            default_route="agent",
        )
        request = CapabilityRequest(
            capability="audio.transcribe.words",
            inputs={"media_path": "fixture.wav"},
            quality="standard",
        )
        self.assertEqual("agent", policy.route(request, local_available=True))


if __name__ == "__main__":
    unittest.main()
