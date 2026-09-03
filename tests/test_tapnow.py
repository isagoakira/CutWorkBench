from __future__ import annotations

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

from cut_workbench.errors import ValidationError
from cut_workbench.jobs import CapabilityJobStore
from cut_workbench.project_store import ProjectStore
from cut_workbench.tapnow import GenerativeOrchestrator, TapNowAgenticAdapter


class TapNowAgenticAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.jobs = CapabilityJobStore(Path(self.temporary.name))
        self.orchestrator = GenerativeOrchestrator(
            jobs=self.jobs, adapter=TapNowAgenticAdapter(Path(self.temporary.name))
        )

    def test_preview_request_compiles_a_durable_agentic_operation(self) -> None:
        job = self.orchestrator.request({
            "capability": "video.generate",
            "prompt": "产品从雨后的营地桌面缓慢升起",
            "references": [{
                "reference_id": "ART-PRODUCT", "kind": "canvas-node",
                "locator": "tapnow://canvas/c1/node/product", "role": "product-source",
            }],
            "output": {"count": 1, "aspect_ratio": "9:16", "duration_seconds": 5},
            "constraints": {"execution_boundary": "preview", "preserve": ["包装文字", "瓶身比例"]},
        })

        self.assertEqual("pending_provider", job["status"])
        self.assertEqual("agentic:tapnow", job["provider_id"])
        operation = job["request"]["operation"]
        self.assertEqual("generate-video", operation["action"])
        self.assertEqual("ask", operation["execution"]["mode"])
        self.assertTrue(operation["execution"]["stop_before_spend"])
        self.assertEqual(["ART-PRODUCT"], operation["lineage"]["reference_ids"])
        self.assertEqual([job["job_id"]], [item["job_id"] for item in self.jobs.pending_provider()])

        self.orchestrator.claim(job_id=job["job_id"], executor_id="codex")
        prepared = self.orchestrator.submit(
            job_id=job["job_id"], executor_id="codex", evidence=["tapnow://canvas/c1"],
            payload={
                "operation_id": operation["operation_id"], "status": "prepared",
                "canvas_url": "https://app.tapnow.ai/canvas/c1", "outputs": [],
                "usage": {"candidates_generated": 0, "tapies_charged": 0},
                "estimate": {
                    "billing_mode": "tapies", "estimated_tapies": 80,
                    "estimated_candidates": 1,
                },
            },
        )
        self.assertEqual("prepared", prepared["result"]["payload"]["status"])

    def test_only_the_claiming_executor_can_submit(self) -> None:
        job = self.orchestrator.request({
            "capability": "image.generate", "prompt": "产品图", "references": [],
            "output": {"count": 1}, "constraints": {"execution_boundary": "preview"},
        })
        self.orchestrator.claim(job_id=job["job_id"], executor_id="agent-a")
        with self.assertRaisesRegex(ValidationError, "not claimed by this"):
            self.orchestrator.submit(
                job_id=job["job_id"], executor_id="agent-b", evidence=["canvas"],
                payload={
                    "operation_id": job["request"]["operation"]["operation_id"],
                    "status": "prepared", "canvas_url": "canvas", "outputs": [],
                    "usage": {"candidates_generated": 0, "tapies_charged": 0},
                },
            )

    def test_generate_boundary_requires_an_approved_prepared_job(self) -> None:
        request = {
            "capability": "image.generate", "prompt": "明亮产品主视觉",
            "references": [], "output": {"count": 1, "aspect_ratio": "1:1"},
            "constraints": {"execution_boundary": "generate"},
        }
        with self.assertRaisesRegex(ValidationError, "prepared_job_id"):
            self.orchestrator.request(request)

        request["constraints"]["spend_approval"] = {
            "approved_by": "human:owner", "billing_mode": "tapies", "max_tapies": 100,
            "evidence": ["approvals/image-001.md"],
        }
        with self.assertRaisesRegex(ValidationError, "prepared_job_id"):
            self.orchestrator.request(request)

    def test_local_reference_requires_external_upload_approval(self) -> None:
        with self.assertRaisesRegex(ValidationError, "external_upload_approval"):
            self.orchestrator.request({
                "capability": "image.edit", "prompt": "只替换背景",
                "references": [{
                    "reference_id": "ART-LOCAL", "kind": "local-file",
                    "locator": "D:/assets/product.png", "role": "product-source",
                }],
                "output": {"count": 1, "aspect_ratio": "1:1"},
                "constraints": {
                    "execution_boundary": "preview", "change_scope": "background only",
                    "preserve": ["产品", "Logo"],
                },
            })

    def test_edit_requires_one_change_scope_and_preservation_constraints(self) -> None:
        with self.assertRaisesRegex(ValidationError, "change_scope"):
            self.orchestrator.request({
                "capability": "video.edit", "prompt": "修正瓶盖",
                "references": [{
                    "reference_id": "NODE-RESULT", "kind": "canvas-node",
                    "locator": "tapnow://canvas/c1/node/result", "role": "edit-source",
                }],
                "output": {"count": 1}, "constraints": {"execution_boundary": "preview"},
            })

    def test_submit_validates_outputs_and_returns_workflow_artifact_operations(self) -> None:
        request = {
            "capability": "video.generate", "prompt": "五秒产品转台镜头",
            "references": [], "output": {"count": 1, "aspect_ratio": "16:9", "duration_seconds": 5},
            "constraints": {"execution_boundary": "preview"},
            "acceptance_criteria": ["产品主体完整且时长为五秒"],
            "artifact_targets": [{
                "target_id": "SHOT-01", "artifact_id": "ART-GEN-SHOT-01",
                "stage_id": "04-recording", "kind": "raw-media", "format": "mp4",
                "version": "1", "locator": "04_原始素材/S01_生成镜头_001.mp4",
                "derived_from": [],
            }],
        }
        job = self._prepare_approve_generate(request, max_tapies=100)
        self.orchestrator.claim(job_id=job["job_id"], executor_id="codex")
        self._authorize(job, estimated_tapies=80)
        operation_id = job["request"]["operation"]["operation_id"]
        artifact_path = Path(self.temporary.name) / "04_原始素材" / "S01_生成镜头_001.mp4"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_bytes(b"tapnow-video-fixture")
        digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        completed = self.orchestrator.submit(
            job_id=job["job_id"], executor_id="codex", evidence=["tapnow://canvas/c1"],
            payload={
                "operation_id": operation_id, "status": "completed",
                "canvas_url": "https://app.tapnow.ai/canvas/c1",
                "preflight": {
                    "checked_before_generation": True, "billing_mode": "tapies",
                    "candidate_count": 1, "estimated_tapies": 80,
                    "evidence": ["tapnow://canvas/c1/confirmation"],
                },
                "usage": {"billing_mode": "tapies", "tapies_charged": 80, "candidates_generated": 1},
                "acceptance": [{
                    "criterion": "产品主体完整且时长为五秒", "passed": True,
                    "evidence": ["reviews/shot-01.md"],
                }],
                "outputs": [{
                    "target_id": "SHOT-01", "node_id": "node-video-1",
                    "locator": "04_原始素材/S01_生成镜头_001.mp4", "media_type": "video",
                    "model": "auto", "sha256": digest,
                }],
            },
        )

        self.assertEqual("completed", completed["status"])
        result = completed["result"]["payload"]
        self.assertEqual("node-video-1", result["outputs"][0]["node_id"])
        artifact_op = result["artifact_operations"][0]
        self.assertEqual("register_workflow_artifact", artifact_op["op"])
        self.assertEqual("ART-GEN-SHOT-01", artifact_op["artifact_id"])
        self.assertEqual("agentic:tapnow/codex", artifact_op["verification"]["verifier"])
        self.assertEqual(80.0, result["usage"]["tapies_charged"])

        store = ProjectStore(Path(self.temporary.name) / "project-store")
        project = store.create_project(
            project_id="tapnow-handoff", title="TapNow handoff",
            canvas={"width": 1920, "height": 1080, "fps": 25},
        )
        project = store.apply_plan(
            project_id="tapnow-handoff", expected_revision=project["revision"],
            actor="agent:codex", reason="configure workflow and register TapNow output",
            operations=[{"op": "configure_production_workflow"}, artifact_op],
        )
        self.assertIn("ART-GEN-SHOT-01", project["production_workflow"]["artifacts"])

    def test_result_cannot_exceed_approved_tapies_budget(self) -> None:
        job = self._prepare_approve_generate({
            "capability": "image.generate", "prompt": "产品图", "references": [],
            "output": {"count": 1},
            "constraints": {"execution_boundary": "preview"},
        }, max_tapies=10)
        self.orchestrator.claim(job_id=job["job_id"], executor_id="codex")
        self._authorize(job, estimated_tapies=10)
        operation_id = job["request"]["operation"]["operation_id"]
        with self.assertRaisesRegex(ValidationError, "approved Tapies budget"):
            self.orchestrator.submit(
                job_id=job["job_id"], executor_id="codex", evidence=["canvas"],
                payload={
                    "operation_id": operation_id, "status": "completed", "canvas_url": "canvas",
                    "preflight": {
                        "checked_before_generation": True, "billing_mode": "tapies",
                        "candidate_count": 1, "estimated_tapies": 10,
                        "evidence": ["confirmation"],
                    },
                    "usage": {"billing_mode": "tapies", "tapies_charged": 11, "candidates_generated": 1},
                    "outputs": [{
                        "node_id": "node-1", "locator": "image.png", "media_type": "image",
                        "model": "auto", "sha256": "b" * 64,
                    }],
                },
            )

    def test_generate_must_match_the_approved_preview(self) -> None:
        prepared = self._prepare({
            "capability": "image.generate", "prompt": "白色背景产品图", "references": [],
            "output": {"count": 1}, "constraints": {"execution_boundary": "preview"},
        })
        self.orchestrator.approve(
            prepared_job_id=prepared["job_id"], approved_by="human:producer",
            billing_mode="tapies", max_tapies=10, max_candidates=1, evidence=["approval.md"],
        )
        with self.assertRaisesRegex(ValidationError, "differs from the approved"):
            self.orchestrator.request({
                "capability": "image.generate", "prompt": "黑色背景产品图", "references": [],
                "output": {"count": 1},
                "constraints": {"execution_boundary": "generate", "prepared_job_id": prepared["job_id"]},
            })

    def test_generate_cannot_change_the_approved_artifact_target(self) -> None:
        request = {
            "capability": "image.generate", "prompt": "白色背景产品图", "references": [],
            "output": {"count": 1}, "constraints": {"execution_boundary": "preview"},
            "artifact_targets": [{
                "target_id": "IMAGE-01", "artifact_id": "ART-IMAGE-01",
                "stage_id": "04-recording", "kind": "raw-media", "format": "png",
                "version": "1", "locator": "04_原始素材/产品图.png", "derived_from": [],
            }],
        }
        prepared = self._prepare(request)
        self.orchestrator.approve(
            prepared_job_id=prepared["job_id"], approved_by="human:producer",
            billing_mode="tapies", max_tapies=10, max_candidates=1,
            evidence=["approval.md"],
        )
        changed = copy.deepcopy(request)
        changed["constraints"] = {
            "execution_boundary": "generate", "prepared_job_id": prepared["job_id"],
        }
        changed["artifact_targets"][0]["locator"] = "04_原始素材/另一个位置.png"
        with self.assertRaisesRegex(ValidationError, "differs from the approved"):
            self.orchestrator.request(changed)

    def test_artifact_target_cannot_escape_the_workbench_root(self) -> None:
        outside = Path(self.temporary.name).parent / "outside-tapnow.png"
        outside.write_bytes(b"outside")
        self.addCleanup(outside.unlink, missing_ok=True)
        request = {
            "capability": "image.generate", "prompt": "产品图", "references": [],
            "output": {"count": 1}, "constraints": {"execution_boundary": "preview"},
            "artifact_targets": [{
                "target_id": "IMAGE-01", "artifact_id": "ART-IMAGE-01",
                "stage_id": "04-recording", "kind": "raw-media", "format": "png",
                "version": "1", "locator": str(outside), "derived_from": [],
            }],
        }
        job = self._prepare_approve_generate(request, max_tapies=10)
        self.orchestrator.claim(job_id=job["job_id"], executor_id="codex")
        self._authorize(job, estimated_tapies=10)
        with self.assertRaisesRegex(ValidationError, "inside the Workbench root"):
            self.orchestrator.submit(
                job_id=job["job_id"], executor_id="codex", evidence=["canvas"],
                payload={
                    "operation_id": job["request"]["operation"]["operation_id"],
                    "status": "completed", "canvas_url": "canvas",
                    "usage": {
                        "billing_mode": "tapies", "tapies_charged": 10,
                        "candidates_generated": 1,
                    },
                    "outputs": [{
                        "target_id": "IMAGE-01", "node_id": "node-1",
                        "locator": str(outside), "media_type": "image", "model": "auto",
                        "sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
                    }],
                },
            )

    def test_one_approval_can_create_only_one_generate_job(self) -> None:
        request = {
            "capability": "image.generate", "prompt": "白色背景产品图", "references": [],
            "output": {"count": 1}, "constraints": {"execution_boundary": "preview"},
        }
        prepared = self._prepare(request)
        self.orchestrator.approve(
            prepared_job_id=prepared["job_id"], approved_by="human:producer",
            billing_mode="tapies", max_tapies=10, max_candidates=1, evidence=["approval.md"],
        )
        generate = copy.deepcopy(request)
        generate["constraints"] = {
            "execution_boundary": "generate", "prepared_job_id": prepared["job_id"],
        }
        self.orchestrator.request(generate)
        with self.assertRaisesRegex(ValidationError, "already consumed"):
            self.orchestrator.request(generate)

    def test_result_must_match_the_operation_and_all_declared_targets(self) -> None:
        job = self.orchestrator.request({
            "capability": "image.generate", "prompt": "产品图", "references": [],
            "output": {"count": 1}, "constraints": {"execution_boundary": "preview"},
            "artifact_targets": [{
                "target_id": "IMAGE-01", "artifact_id": "ART-IMAGE-01",
                "stage_id": "04-recording", "kind": "raw-media", "format": "png",
                "version": "1", "locator": "04_原始素材/S01_产品图_001.png", "derived_from": [],
            }],
        })
        self.orchestrator.claim(job_id=job["job_id"], executor_id="codex")
        with self.assertRaisesRegex(ValidationError, "operation_id"):
            self.orchestrator.submit(
                job_id=job["job_id"], executor_id="codex", evidence=["canvas"],
                payload={
                    "operation_id": "wrong", "status": "prepared", "canvas_url": "canvas",
                    "outputs": [], "usage": {"candidates_generated": 0, "tapies_charged": 0},
                },
            )

    def _prepare(self, request: dict, *, estimated_tapies: float = 10) -> dict:
        preview_request = copy.deepcopy(request)
        preview_request.setdefault("constraints", {})["execution_boundary"] = "preview"
        preview_request["constraints"].pop("prepared_job_id", None)
        preview_request["constraints"].pop("spend_approval", None)
        job = self.orchestrator.request(preview_request)
        self.orchestrator.claim(job_id=job["job_id"], executor_id="codex")
        self.orchestrator.submit(
            job_id=job["job_id"], executor_id="codex", evidence=["tapnow://canvas/prepared"],
            payload={
                "operation_id": job["request"]["operation"]["operation_id"],
                "status": "prepared", "canvas_url": "https://app.tapnow.ai/canvas/prepared",
                "outputs": [], "usage": {"candidates_generated": 0, "tapies_charged": 0},
                "estimate": {
                    "billing_mode": "tapies", "estimated_tapies": estimated_tapies,
                    "estimated_candidates": preview_request["output"].get("count", 1),
                },
            },
        )
        return job

    def _prepare_approve_generate(self, request: dict, *, max_tapies: float) -> dict:
        prepared = self._prepare(request, estimated_tapies=max_tapies)
        self.orchestrator.approve(
            prepared_job_id=prepared["job_id"], approved_by="human:producer",
            billing_mode="tapies", max_tapies=max_tapies, max_candidates=1,
            evidence=["approvals/generation.md"],
        )
        generate_request = copy.deepcopy(request)
        generate_request.setdefault("constraints", {}).update(
            execution_boundary="generate", prepared_job_id=prepared["job_id"]
        )
        generate_request["constraints"].pop("spend_approval", None)
        return self.orchestrator.request(generate_request)

    def _authorize(self, job: dict, *, estimated_tapies: float) -> dict:
        return self.orchestrator.authorize(
            job_id=job["job_id"], executor_id="codex",
            preflight={
                "checked_before_generation": True, "billing_mode": "tapies",
                "candidate_count": 1, "estimated_tapies": estimated_tapies,
            },
            evidence=["tapnow://confirmation"],
        )


if __name__ == "__main__":
    unittest.main()
