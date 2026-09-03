from __future__ import annotations

import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cut_workbench.errors import ValidationError
from cut_workbench.generation_worker import AgentExecutionResult, GenerationWorker
from cut_workbench.jobs import CapabilityJobStore
from cut_workbench.tapnow import GenerativeOrchestrator, TapNowAgenticAdapter


class GenerationWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.jobs = CapabilityJobStore(root)
        self.orchestrator = GenerativeOrchestrator(
            jobs=self.jobs, adapter=TapNowAgenticAdapter(root)
        )

    def test_worker_claims_and_executes_a_prepared_operation(self) -> None:
        job = self.orchestrator.request({
            "capability": "image.generate", "prompt": "产品图", "references": [],
            "output": {"count": 1}, "constraints": {"execution_boundary": "preview"},
        })

        class Executor:
            def execute(self, envelope):
                operation = envelope["operation"]
                return AgentExecutionResult(
                    payload={
                        "operation_id": operation["operation_id"], "status": "prepared",
                        "canvas_url": "https://app.tapnow.ai/canvas/worker", "outputs": [],
                        "usage": {"candidates_generated": 0, "tapies_charged": 0},
                        "estimate": {
                            "billing_mode": "tapies", "estimated_tapies": 10,
                            "estimated_candidates": 1,
                        },
                    },
                    evidence=["tapnow://canvas/worker"],
                )

        result = GenerationWorker(
            orchestrator=self.orchestrator, jobs=self.jobs,
            executor=Executor(), executor_id="local-agent",
        ).run_once()
        self.assertEqual("completed", result["status"])
        self.assertEqual(job["job_id"], result["job_id"])
        self.assertEqual("prepared", result["result"]["payload"]["status"])

    def test_worker_failure_is_persisted(self) -> None:
        self.orchestrator.request({
            "capability": "image.generate", "prompt": "产品图", "references": [],
            "output": {"count": 1}, "constraints": {"execution_boundary": "preview"},
        })

        class Executor:
            def execute(self, envelope):
                raise RuntimeError("browser agent stopped")

        worker = GenerationWorker(
            orchestrator=self.orchestrator, jobs=self.jobs,
            executor=Executor(), executor_id="local-agent",
        )
        with self.assertRaisesRegex(RuntimeError, "browser agent stopped"):
            worker.run_once()
        self.assertEqual("failed", self.jobs.failed()[0]["status"])

    def test_claim_is_atomic_across_concurrent_workers(self) -> None:
        job = self.orchestrator.request({
            "capability": "image.generate", "prompt": "产品图", "references": [],
            "output": {"count": 1}, "constraints": {"execution_boundary": "preview"},
        })

        def claim(executor_id: str) -> str:
            try:
                return self.orchestrator.claim(job_id=job["job_id"], executor_id=executor_id)["claimed_by"]
            except ValidationError:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(claim, ["agent-a", "agent-b"]))
        self.assertEqual(1, outcomes.count("rejected"))
        self.assertEqual(1, len([item for item in outcomes if item != "rejected"]))

    def test_expired_unapproved_claim_returns_to_pending_queue(self) -> None:
        job = self.orchestrator.request({
            "capability": "image.generate", "prompt": "产品图", "references": [],
            "output": {"count": 1}, "constraints": {"execution_boundary": "preview"},
        })
        self.orchestrator.claim(
            job_id=job["job_id"], executor_id="stopped-agent", lease_seconds=0.001
        )
        time.sleep(0.01)

        pending = self.orchestrator.pending()

        self.assertEqual([job["job_id"]], [item["job_id"] for item in pending])
        self.assertNotIn("claimed_by", pending[0])

    def test_expired_authorized_claim_requires_reconciliation(self) -> None:
        job = self._generate_job()
        self.orchestrator.claim(
            job_id=job["job_id"], executor_id="stopped-agent", lease_seconds=0.001
        )
        self.orchestrator.authorize(
            job_id=job["job_id"], executor_id="stopped-agent",
            preflight={
                "checked_before_generation": True, "billing_mode": "tapies",
                "candidate_count": 1, "estimated_tapies": 10,
            },
            evidence=["tapnow://confirmation"],
        )
        time.sleep(0.01)

        self.assertEqual([], self.orchestrator.pending())
        reconciliation = self.orchestrator.reconciliation()
        self.assertEqual([job["job_id"]], [item["job_id"] for item in reconciliation])
        self.assertIn("verify provider state", reconciliation[0]["reconciliation_reason"])

    def test_generate_worker_authorizes_before_execute_phase(self) -> None:
        job = self._generate_job()
        phases = []

        class Executor:
            def execute(self, envelope):
                phases.append(envelope["phase"])
                operation = envelope["operation"]
                if envelope["phase"] == "preflight":
                    return AgentExecutionResult(
                        payload={
                            "checked_before_generation": True, "billing_mode": "tapies",
                            "candidate_count": 1, "estimated_tapies": 10,
                        },
                        evidence=["tapnow://confirmation"],
                    )
                self.authorization = envelope["authorization"]
                return AgentExecutionResult(
                    payload={
                        "operation_id": operation["operation_id"], "status": "completed",
                        "canvas_url": "https://app.tapnow.ai/canvas/worker",
                        "usage": {
                            "billing_mode": "tapies", "tapies_charged": 10,
                            "candidates_generated": 1,
                        },
                        "outputs": [{
                            "node_id": "generated-1", "locator": "generated-1.png",
                            "media_type": "image", "model": "auto", "sha256": "a" * 64,
                        }],
                    },
                    evidence=["tapnow://canvas/worker/generated-1"],
                )

        result = GenerationWorker(
            orchestrator=self.orchestrator, jobs=self.jobs,
            executor=Executor(), executor_id="local-agent",
        ).run_once()

        self.assertEqual(["preflight", "execute"], phases)
        self.assertEqual("completed", result["status"])
        self.assertEqual(job["job_id"], result["job_id"])

    def test_generate_worker_failure_after_authorization_requires_reconciliation(self) -> None:
        job = self._generate_job()

        class Executor:
            def execute(self, envelope):
                if envelope["phase"] == "preflight":
                    return AgentExecutionResult(
                        payload={
                            "checked_before_generation": True, "billing_mode": "tapies",
                            "candidate_count": 1, "estimated_tapies": 10,
                        },
                        evidence=["tapnow://confirmation"],
                    )
                raise RuntimeError("browser disappeared after click")

        worker = GenerationWorker(
            orchestrator=self.orchestrator, jobs=self.jobs,
            executor=Executor(), executor_id="local-agent",
        )
        with self.assertRaisesRegex(RuntimeError, "browser disappeared"):
            worker.run_once()

        self.assertEqual([], self.jobs.failed())
        reconciliation = self.orchestrator.reconciliation()
        self.assertEqual(job["job_id"], reconciliation[0]["job_id"])
        self.assertIn("after generation authorization", reconciliation[0]["reconciliation_reason"])

    def _generate_job(self) -> dict:
        request = {
            "capability": "image.generate", "prompt": "产品图", "references": [],
            "output": {"count": 1}, "constraints": {"execution_boundary": "preview"},
        }
        preview = self.orchestrator.request(request)
        self.orchestrator.claim(job_id=preview["job_id"], executor_id="setup-agent")
        self.orchestrator.submit(
            job_id=preview["job_id"], executor_id="setup-agent",
            evidence=["tapnow://canvas/prepared"],
            payload={
                "operation_id": preview["request"]["operation"]["operation_id"],
                "status": "prepared", "canvas_url": "https://app.tapnow.ai/canvas/prepared",
                "outputs": [], "usage": {"candidates_generated": 0, "tapies_charged": 0},
                "estimate": {
                    "billing_mode": "tapies", "estimated_tapies": 10,
                    "estimated_candidates": 1,
                },
            },
        )
        self.orchestrator.approve(
            prepared_job_id=preview["job_id"], approved_by="human:producer",
            billing_mode="tapies", max_tapies=10, max_candidates=1,
            evidence=["approvals/generation.md"],
        )
        request["constraints"] = {
            "execution_boundary": "generate", "prepared_job_id": preview["job_id"],
        }
        return self.orchestrator.request(request)


if __name__ == "__main__":
    unittest.main()
