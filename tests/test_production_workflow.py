from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cut_workbench.app import WorkbenchApp
from cut_workbench.errors import ValidationError
from cut_workbench.manifest import render_cut_manifest
from cut_workbench.production_workflow import production_contract, production_status
from cut_workbench.project_store import ProjectStore
from cut_workbench.verification import verify_project


class ProductionWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = ProjectStore(Path(self.temporary.name))
        self.project = self.store.create_project(
            project_id="production", title="Production", canvas={"width": 1920, "height": 1080, "fps": 25}
        )

    def apply(self, *operations: dict) -> dict:
        self.project = self.store.apply_plan(
            project_id="production", expected_revision=self.project["revision"], actor="test",
            reason="exercise production workflow", operations=operations,
        )
        return self.project

    def test_contract_and_status_expose_the_canonical_nine_stage_protocol(self) -> None:
        contract = production_contract()
        self.assertEqual(9, len(contract["stages"]))
        self.assertEqual("01-script", contract["stages"][0]["stage_id"])
        self.assertEqual("09-final", contract["stages"][-1]["stage_id"])

        self.apply({"op": "configure_production_workflow"})
        status = production_status(self.project)
        self.assertEqual("01-script", status["next_stage"])
        self.assertTrue(status["stages"][0]["ready"])
        self.assertEqual(["01-script"], status["stages"][1]["blockers"])

    def test_stage_submission_requires_deliverables_and_evidenced_acceptance(self) -> None:
        self.apply({"op": "configure_production_workflow"})
        with self.assertRaisesRegex(ValidationError, "missing required deliverable"):
            self.apply(
                self._artifact("ART-CHANGE", "01-script", "script-change-log", "xlsx"),
                self._submission("01-script", ["ART-CHANGE"], []),
            )

    def test_submission_requires_canonical_content_checks(self) -> None:
        self.apply({"op": "configure_production_workflow"})
        artifact = self._artifact("ART-SCRIPT", "01-script", "video-script", "md")
        submission = self._submission("01-script", ["ART-SCRIPT"], [])
        submission["content_checks"] = []
        with self.assertRaisesRegex(ValidationError, "content requirement checks"):
            self.apply(artifact, submission)

    def test_dependency_requires_the_actual_primary_input_kinds(self) -> None:
        self.apply({"op": "configure_production_workflow"})
        script = self._artifact("ART-SCRIPT", "01-script", "video-script", "md")
        change_log = self._artifact("ART-CHANGE", "01-script", "script-change-log", "xlsx")
        self.apply(
            script, change_log,
            self._submission("01-script", ["ART-SCRIPT", "ART-CHANGE"], []),
            {"op": "approve_workflow_stage", "stage_id": "01-script", "reviewer": "producer", "evidence": ["review.md"]},
        )
        storyboard = self._artifact(
            "ART-STORYBOARD", "02-storyboard", "storyboard", "xlsx", derived_from=["ART-CHANGE"]
        )
        with self.assertRaisesRegex(ValidationError, "video-script"):
            self.apply(storyboard, self._submission("02-storyboard", ["ART-STORYBOARD"], ["ART-CHANGE"]))

    def test_upstream_change_marks_approved_downstream_work_stale(self) -> None:
        self.apply({"op": "configure_production_workflow"})
        self._complete_stage("01-script")
        self._complete_stage("02-storyboard")

        self.apply(self._artifact("ART-SCRIPT-V2", "01-script", "video-script", "md", version="2"))
        workflow = self.project["production_workflow"]
        self.assertEqual("in_progress", workflow["stages"]["01-script"]["status"])
        self.assertEqual("stale", workflow["stages"]["02-storyboard"]["status"])
        self.assertEqual(["01-script"], workflow["stages"]["02-storyboard"]["stale_due_to"])

    def test_submission_cannot_claim_inputs_missing_from_artifact_lineage(self) -> None:
        self.apply({"op": "configure_production_workflow"})
        self._complete_stage("01-script")
        script_artifacts = self.project["production_workflow"]["stages"]["01-script"]["submission"]["artifact_ids"]
        artifact = self._artifact("ART-STORYBOARD", "02-storyboard", "storyboard", "xlsx")
        with self.assertRaisesRegex(ValidationError, "does not derive from submitted inputs"):
            self.apply(artifact, self._submission("02-storyboard", ["ART-STORYBOARD"], script_artifacts))

    def test_submission_rejects_unapproved_extra_inputs(self) -> None:
        self.apply({"op": "configure_production_workflow"})
        self._complete_stage("01-script")
        script_artifacts = self.project["production_workflow"]["stages"]["01-script"]["submission"]["artifact_ids"]
        self.apply(self._artifact("ART-UNAPPROVED", "02-storyboard", "camera-diagram", "png"))
        artifact = self._artifact(
            "ART-STORYBOARD", "02-storyboard", "storyboard", "xlsx",
            derived_from=script_artifacts + ["ART-UNAPPROVED"],
        )
        with self.assertRaisesRegex(ValidationError, "current approved dependency outputs"):
            self.apply(
                artifact,
                self._submission("02-storyboard", ["ART-STORYBOARD"], script_artifacts + ["ART-UNAPPROVED"]),
            )

    def test_all_stages_can_close_with_exact_file_lineage(self) -> None:
        self.apply({"op": "configure_production_workflow"})
        for stage in production_contract()["stages"]:
            self._complete_stage(stage["stage_id"])

        status = production_status(self.project)
        self.assertIsNone(status["next_stage"])
        self.assertTrue(all(item["status"] == "approved" for item in status["stages"]))
        manifest = render_cut_manifest(self.project)
        self.assertIn("## Production workflow", manifest)
        self.assertIn("`09-final`: **approved**", manifest)

        candidate = dict(self.project)
        candidate["status"] = "delivered"
        report = verify_project(candidate)
        self.assertNotIn("production-final-stage-unapproved", {item["code"] for item in report["issues"]})

    def test_delivery_gate_rejects_an_unapproved_final_package(self) -> None:
        self.apply({"op": "configure_production_workflow"})
        candidate = dict(self.project)
        candidate["status"] = "delivered"
        report = verify_project(candidate)
        self.assertIn("production-final-stage-unapproved", {item["code"] for item in report["issues"]})

    def test_workflow_tools_are_agent_host_neutral(self) -> None:
        app = WorkbenchApp(Path(self.temporary.name) / "app")
        names = {tool["name"] for tool in app.list_tools()}
        self.assertIn("workflow.contract", names)
        self.assertIn("workflow.status", names)
        self.assertEqual(9, len(app.call_tool("workflow.contract", {})["stages"]))

    def test_artifact_ids_share_the_project_wide_stable_id_namespace(self) -> None:
        self.apply({"op": "configure_production_workflow"})
        self.apply(self._artifact("ART-SHARED", "01-script", "video-script", "md"))
        with self.assertRaisesRegex(ValidationError, "stable id already exists"):
            self.apply({"op": "add_track", "track_id": "ART-SHARED", "kind": "video"})

    def test_version_critical_files_require_dated_names_and_file_verification(self) -> None:
        self.apply({"op": "configure_production_workflow"})
        invalid_name = self._artifact("ART-BAD-NAME", "01-script", "video-script", "md")
        invalid_name["locator"] = "01_脚本/01_视频脚本_v1.md"
        with self.assertRaisesRegex(ValidationError, "_v版本号_YYYYMMDD"):
            self.apply(invalid_name)

        unverified = self._artifact("ART-UNVERIFIED", "01-script", "video-script", "md")
        unverified["verification"]["hash_matched"] = False
        with self.assertRaisesRegex(ValidationError, "match its declared hash"):
            self.apply(unverified)

    def _complete_stage(self, stage_id: str) -> None:
        contract = next(item for item in production_contract()["stages"] if item["stage_id"] == stage_id)
        workflow = self.project["production_workflow"]
        inputs = []
        for dependency in contract["depends_on"]:
            inputs.extend(workflow["stages"][dependency]["submission"]["artifact_ids"])
        artifacts = []
        artifact_ids = []
        for index, deliverable in enumerate(contract["deliverables"], start=1):
            if deliverable["minimum"] == 0:
                continue
            artifact_id = f"ART-{stage_id.upper()}-{index}"
            artifact_ids.append(artifact_id)
            artifacts.append(self._artifact(
                artifact_id, stage_id, deliverable["kind"], deliverable["formats"][0],
                derived_from=inputs,
            ))
        self.apply(*artifacts, self._submission(stage_id, artifact_ids, inputs), {
            "op": "approve_workflow_stage", "stage_id": stage_id, "reviewer": "producer",
            "evidence": [f"reviews/{stage_id}.md"],
        })

    @staticmethod
    def _artifact(
        artifact_id: str, stage_id: str, kind: str, file_format: str, *, version: str = "1",
        derived_from: list[str] | None = None,
    ) -> dict:
        number = stage_id.split("-", 1)[0]
        filename = (
            f"{number}_{kind}_v{version}_20260827"
            if file_format == "directory"
            else f"{number}_{kind}_v{version}_20260827.{file_format}"
        )
        return {
            "op": "register_workflow_artifact", "artifact_id": artifact_id, "stage_id": stage_id,
            "kind": kind, "format": file_format, "version": version,
            "locator": f"deliverables/{filename}", "sha256": "a" * 64,
            "derived_from": derived_from or [],
            "verification": {
                "verifier": "test-fixture", "readable": True, "hash_matched": True,
                "evidence": [f"checks/{artifact_id}-file.json"], "content_profile": {},
            },
        }

    @staticmethod
    def _submission(stage_id: str, artifact_ids: list[str], inputs: list[str]) -> dict:
        contract = next(item for item in production_contract()["stages"] if item["stage_id"] == stage_id)
        return {
            "op": "submit_workflow_stage", "stage_id": stage_id, "version": "1",
            "artifact_ids": artifact_ids, "input_artifact_ids": inputs,
            "acceptance": [
                {"criterion": criterion, "passed": True, "evidence": [f"checks/{stage_id}-{index}.md"]}
                for index, criterion in enumerate(contract["acceptance"], start=1)
            ],
            "content_checks": [
                {"requirement": requirement, "passed": True, "evidence": [f"checks/{stage_id}-content-{index}.json"]}
                for index, requirement in enumerate(contract["content_requirements"], start=1)
            ],
        }


if __name__ == "__main__":
    unittest.main()
