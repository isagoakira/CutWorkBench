from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cut_workbench.project_store import ProjectStore
from cut_workbench.errors import ValidationError


class ProjectStoreTests(unittest.TestCase):
    def test_project_ids_are_path_safe_on_every_entry_point(self) -> None:
        with TemporaryDirectory() as directory:
            store = ProjectStore(Path(directory))
            with self.assertRaisesRegex(ValidationError, "path-safe"):
                store.read_project("../outside")
            project = store.create_project(
                project_id="safe", title="Safe", canvas={"width": 1, "height": 1, "fps": 1}
            )
            with self.assertRaisesRegex(ValidationError, "path-safe"):
                store.branch_project(source_project_id=project["project_id"], new_project_id="../outside")

    def test_segment_timing_rejects_negative_timeline_and_nonpositive_speed(self) -> None:
        with TemporaryDirectory() as directory:
            store = ProjectStore(Path(directory))
            project = store.create_project(
                project_id="timing", title="Timing", canvas={"width": 1, "height": 1, "fps": 1}
            )
            project = store.apply_plan(
                project_id="timing", expected_revision=1, actor="test", reason="setup",
                operations=[
                    {"op": "register_source", "source_id": "SRC", "locator": "source.mp4"},
                    {"op": "add_track", "track_id": "V1", "kind": "video"},
                ],
            )
            for values in ({"timeline_start": -1, "speed": 1}, {"timeline_start": 0, "speed": 0}):
                with self.assertRaises(ValidationError):
                    store.apply_plan(
                        project_id="timing", expected_revision=project["revision"], actor="test", reason="bad",
                        operations=[{
                            "op": "add_segment", "segment_id": f"SEG-{values['speed']}", "source_id": "SRC",
                            "track_id": "V1", "source_in": 0, "source_out": 1, **values,
                        }],
                    )

    def test_plan_application_creates_immutable_revision_and_preserves_source_provenance(self) -> None:
        with TemporaryDirectory() as directory:
            store = ProjectStore(Path(directory))
            created = store.create_project(
                project_id="demo",
                title="Demo",
                canvas={"width": 1080, "height": 1920, "fps": 30},
            )

            updated = store.apply_plan(
                project_id="demo",
                expected_revision=created["revision"],
                actor="agent:codex",
                reason="register and assemble source",
                operations=[
                    {
                        "op": "register_source",
                        "source_id": "SRC-001",
                        "locator": "D:/media/original.mp4",
                        "sha256": "abc123",
                    },
                    {"op": "add_track", "track_id": "V1-BASE", "kind": "video", "purpose": "base"},
                    {
                        "op": "add_segment",
                        "segment_id": "SEG-SRC001-001",
                        "source_id": "SRC-001",
                        "track_id": "V1-BASE",
                        "source_in": 2.0,
                        "source_out": 8.0,
                        "timeline_start": 0.0,
                    },
                ],
            )

            self.assertEqual(1, created["revision"])
            self.assertEqual(2, updated["revision"])
            self.assertEqual("SRC-001", updated["segments"]["SEG-SRC001-001"]["source_id"])
            self.assertEqual({}, created["sources"])
            self.assertEqual({}, store.read_project("demo", revision=1)["sources"])
            self.assertEqual(updated, store.read_project("demo"))

            revision_files = sorted((Path(directory) / "projects" / "demo" / "revisions").glob("*.json"))
            self.assertEqual(["rev-000001.json", "rev-000002.json"], [item.name for item in revision_files])
            journal = (Path(directory) / "projects" / "demo" / "journal.jsonl").read_text(encoding="utf-8")
            self.assertEqual([1, 2], [json.loads(line)["revision"] for line in journal.splitlines()])

    def test_controls_are_separable_and_baked_controls_require_an_approved_exception(self) -> None:
        with TemporaryDirectory() as directory:
            store = ProjectStore(Path(directory))
            project = store.create_project(
                project_id="controls",
                title="Controls",
                canvas={"width": 1920, "height": 1080, "fps": 25},
            )
            project = store.apply_plan(
                project_id="controls",
                expected_revision=project["revision"],
                actor="agent:test",
                reason="prepare treatment layer",
                operations=[
                    {"op": "register_source", "source_id": "SRC-001", "locator": "source.mp4"},
                    {"op": "add_track", "track_id": "V1-BASE", "kind": "video", "purpose": "base"},
                    {"op": "add_track", "track_id": "V2-PRIVACY", "kind": "video", "purpose": "privacy"},
                    {
                        "op": "add_segment",
                        "segment_id": "SEG-BASE-001",
                        "source_id": "SRC-001",
                        "track_id": "V1-BASE",
                        "source_in": 0,
                        "source_out": 10,
                        "timeline_start": 0,
                    },
                    {
                        "op": "add_segment",
                        "segment_id": "SEG-PRIVACY-001",
                        "source_id": "SRC-001",
                        "track_id": "V2-PRIVACY",
                        "source_in": 0,
                        "source_out": 10,
                        "timeline_start": 0,
                        "role": "treatment-copy",
                    },
                ],
            )

            updated = store.apply_plan(
                project_id="controls",
                expected_revision=project["revision"],
                actor="agent:test",
                reason="add explicit privacy control",
                operations=[
                    {
                        "op": "add_control",
                        "control_id": "CTL-SEG-PRIVACY-001-MSK-01",
                        "target_segment_id": "SEG-PRIVACY-001",
                        "track_id": "V2-PRIVACY",
                        "kind": "mask_blur",
                        "active_range": {"start": 2.0, "end": 4.0},
                        "properties": {"shape": "circle", "feather": 0.2, "strength": 0.8},
                        "editable": True,
                    }
                ],
            )
            control = updated["controls"]["CTL-SEG-PRIVACY-001-MSK-01"]
            self.assertTrue(control["editable"])
            self.assertEqual("SEG-PRIVACY-001", control["target_segment_id"])

            with self.assertRaisesRegex(ValidationError, "baked control"):
                store.apply_plan(
                    project_id="controls",
                    expected_revision=updated["revision"],
                    actor="agent:test",
                    reason="illegal flatten",
                    operations=[
                        {
                            "op": "add_control",
                            "control_id": "CTL-BAKED-01",
                            "target_segment_id": "SEG-BASE-001",
                            "track_id": "V1-BASE",
                            "kind": "blur",
                            "properties": {},
                            "editable": False,
                            "baked": True,
                        }
                    ],
                )

    def test_handoff_freezes_project_and_branch_remains_editable(self) -> None:
        with TemporaryDirectory() as directory:
            store = ProjectStore(Path(directory))
            project = store.create_project(
                project_id="handoff",
                title="Handoff",
                canvas={"width": 1080, "height": 1920, "fps": 30},
            )
            handed_off = store.apply_plan(
                project_id="handoff",
                expected_revision=1,
                actor="human",
                reason="open in Jianying",
                operations=[
                    {
                        "op": "record_verification", "verification_id": "VER-VISUAL-001",
                        "kind": "visual", "verifier": "human", "passed": True,
                        "evidence": ["preview://final"],
                    },
                    {"op": "set_status", "status": "handed_off"},
                ],
            )
            with self.assertRaisesRegex(ValidationError, "create a branch"):
                store.apply_plan(
                    project_id="handoff",
                    expected_revision=handed_off["revision"],
                    actor="agent:test",
                    reason="must not overwrite",
                    operations=[{"op": "set_status", "status": "assembly"}],
                )

            branch = store.branch_project(source_project_id="handoff", new_project_id="handoff-v2")
            self.assertEqual("assembly", branch["status"])
            self.assertEqual({"project_id": "handoff", "revision": 2}, branch["branched_from"])

    def test_direct_handoff_cannot_bypass_visual_gate(self) -> None:
        with TemporaryDirectory() as directory:
            store = ProjectStore(Path(directory))
            store.create_project(
                project_id="no-visual", title="No visual", canvas={"width": 1, "height": 1, "fps": 1}
            )
            with self.assertRaisesRegex(ValidationError, "visual-verification-missing"):
                store.apply_plan(
                    project_id="no-visual", expected_revision=1, actor="test", reason="bypass",
                    operations=[{"op": "set_status", "status": "handed_off"}],
                )


if __name__ == "__main__":
    unittest.main()
