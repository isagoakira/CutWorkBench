from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cut_workbench.manifest import render_cut_manifest
from cut_workbench.project_store import ProjectStore
from cut_workbench.verification import verify_project


class ProtocolClosureTests(unittest.TestCase):
    def test_audit_decisions_downgrades_and_verification_are_versioned_and_rendered(self) -> None:
        with TemporaryDirectory() as directory:
            store = ProjectStore(Path(directory))
            project = store.create_project(
                project_id="closed-loop",
                title="Closed loop",
                canvas={"width": 1920, "height": 1080, "fps": 30},
            )
            project = store.apply_plan(
                project_id="closed-loop",
                expected_revision=1,
                actor="agent:codex",
                reason="audit and assemble",
                operations=[
                    {"op": "register_source", "source_id": "SRC-001", "locator": "original.mp4"},
                    {"op": "add_track", "track_id": "V1-BASE", "kind": "video", "purpose": "base"},
                    {
                        "op": "add_segment", "segment_id": "SEG-001", "source_id": "SRC-001",
                        "track_id": "V1-BASE", "source_in": 0, "source_out": 5, "timeline_start": 0,
                    },
                    {
                        "op": "record_decision", "decision_id": "DEC-AUDIT-SRC001", "kind": "source_audit",
                        "summary": "2 fps full-source pass; no escalation required", "source_id": "SRC-001",
                        "evidence": ["audit/SRC-001/contact-sheet-2fps.jpg"],
                        "data": {"sample_fps": 2, "coverage": "full", "escalations": []},
                    },
                    {
                        "op": "record_downgrade", "exception_id": "EXC-001", "capability": "face-tracking-mask",
                        "reason": "target editor lacks editable tracking", "fallback": "editable static mask",
                        "approved": True, "approved_by": "human:owner",
                    },
                    {
                        "op": "record_verification", "verification_id": "VER-STRUCT-001",
                        "kind": "structural", "verifier": "cut-workbench", "passed": True,
                        "evidence": ["project://closed-loop/2"], "notes": "No gaps on base track",
                    },
                ],
            )

            report = verify_project(project)
            self.assertTrue(report["passed"], report["issues"])
            manifest = render_cut_manifest(project, report=report)
            self.assertIn("DEC-AUDIT-SRC001", manifest)
            self.assertIn("EXC-001", manifest)
            self.assertIn("VER-STRUCT-001", manifest)
            self.assertIn("SEG-001", manifest)

    def test_review_gate_requires_visual_evidence_and_source_audit(self) -> None:
        with TemporaryDirectory() as directory:
            store = ProjectStore(Path(directory))
            project = store.create_project(
                project_id="gate", title="Gate", canvas={"width": 1080, "height": 1920, "fps": 30}
            )
            project = store.apply_plan(
                project_id="gate", expected_revision=1, actor="test", reason="incomplete review",
                operations=[
                    {"op": "register_source", "source_id": "SRC-001", "locator": "source.mp4"},
                    {"op": "set_status", "status": "review"},
                ],
            )
            report = verify_project(project)
            self.assertFalse(report["passed"])
            self.assertTrue(any(issue["code"] == "source-audit-missing" for issue in report["issues"]))
            self.assertTrue(any(issue["code"] == "visual-verification-missing" for issue in report["issues"]))


if __name__ == "__main__":
    unittest.main()
