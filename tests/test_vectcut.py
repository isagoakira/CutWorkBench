from __future__ import annotations

import unittest
from unittest.mock import patch
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from cut_workbench.project_store import ProjectStore
from cut_workbench.vectcut import VectCutCompiler, VectCutExecutor, VectCutHttpTransport
from cut_workbench.errors import ValidationError


class VectCutCompilerTests(unittest.TestCase):
    def test_http_transport_unwraps_vectcut_output_envelope(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"success": True, "output": {"draft_id": "dfd-real"}}).encode()

        with patch("cut_workbench.vectcut.request.urlopen", return_value=Response()):
            result = VectCutHttpTransport().call("create_draft", {"width": 1, "height": 1})
        self.assertEqual({"draft_id": "dfd-real"}, result)
    def test_compiler_rejects_controls_it_cannot_preserve_instead_of_silently_dropping_them(self) -> None:
        project = {
            "project_id": "unsupported", "revision": 1,
            "canvas": {"width": 1, "height": 1}, "sources": {}, "tracks": {}, "segments": {},
            "captions": {}, "controls": {
                "CTL": {"control_id": "CTL", "kind": "unknown-plugin-control", "enabled": True,
                         "target_segment_id": "SEG", "track_id": "V1", "properties": {}}
            },
        }
        with self.assertRaisesRegex(ValidationError, "cannot preserve"):
            VectCutCompiler().compile(project)

    def test_compiler_keeps_base_treatment_caption_and_effects_as_separate_named_tracks(self) -> None:
        with TemporaryDirectory() as directory:
            store = ProjectStore(Path(directory))
            project = store.create_project(
                project_id="vect",
                title="Vect",
                canvas={"width": 1080, "height": 1920, "fps": 30},
                editor_adapter="vectcut",
            )
            project = store.apply_plan(
                project_id="vect",
                expected_revision=1,
                actor="agent:test",
                reason="assemble editable tracks",
                operations=[
                    {"op": "register_source", "source_id": "SRC-001", "locator": "http://127.0.0.1/media/main.mp4"},
                    {"op": "add_track", "track_id": "V1-BASE", "kind": "video", "purpose": "base"},
                    {"op": "add_track", "track_id": "V2-PRIVACY", "kind": "video", "purpose": "privacy"},
                    {"op": "add_track", "track_id": "S1-CAPTIONS", "kind": "caption", "purpose": "captions"},
                    {"op": "add_track", "track_id": "FX1-MOOD", "kind": "effect", "purpose": "mood"},
                    {
                        "op": "add_segment",
                        "segment_id": "SEG-BASE-001",
                        "source_id": "SRC-001",
                        "track_id": "V1-BASE",
                        "source_in": 0,
                        "source_out": 6,
                        "timeline_start": 0,
                    },
                    {
                        "op": "add_segment",
                        "segment_id": "SEG-PRIVACY-001",
                        "source_id": "SRC-001",
                        "track_id": "V2-PRIVACY",
                        "source_in": 0,
                        "source_out": 6,
                        "timeline_start": 0,
                        "role": "treatment-copy",
                    },
                    {
                        "op": "add_control",
                        "control_id": "CTL-PRIVACY-MSK-01",
                        "target_segment_id": "SEG-PRIVACY-001",
                        "track_id": "V2-PRIVACY",
                        "kind": "mask_blur",
                        "active_range": {"start": 0, "end": 6},
                        "properties": {
                            "mask_type": "circle",
                            "mask_center_x": 0.4,
                            "mask_center_y": 0.3,
                            "mask_size": 0.2,
                            "mask_feather": 0.1,
                            "background_blur": 3,
                        },
                    },
                    {
                        "op": "add_control",
                        "control_id": "CTL-MOOD-FX-01",
                        "target_segment_id": "SEG-BASE-001",
                        "track_id": "FX1-MOOD",
                        "kind": "effect",
                        "active_range": {"start": 1, "end": 5},
                        "properties": {"effect_type": "Glitch", "effect_category": "scene"},
                    },
                    {
                        "op": "add_caption",
                        "caption_id": "CAP-001",
                        "track_id": "S1-CAPTIONS",
                        "start": 0.2,
                        "end": 1.1,
                        "text": "你好",
                        "style": {"font_size": 8, "font_color": "#FFFFFF"},
                    },
                ],
            )

            plan = VectCutCompiler().compile(project, draft_folder="D:/drafts")
            video_calls = [call for call in plan["calls"] if call["tool"] == "add_video"]
            self.assertEqual(["V1-BASE", "V2-PRIVACY"], [call["arguments"]["track_name"] for call in video_calls])
            self.assertNotIn("mask_type", video_calls[0]["arguments"])
            self.assertEqual("circle", video_calls[1]["arguments"]["mask_type"])

            effect = next(call for call in plan["calls"] if call["tool"] == "add_effect")
            self.assertEqual("FX1-MOOD", effect["arguments"]["track_name"])
            caption = next(call for call in plan["calls"] if call["tool"] == "add_text")
            self.assertEqual("S1-CAPTIONS", caption["arguments"]["track_name"])
            self.assertEqual("CAP-001", caption["stable_id"])
            self.assertEqual("vect-r000002", plan["draft_id"])
            self.assertEqual("save_draft", plan["calls"][-1]["tool"])

    def test_executor_resolves_draft_reference_without_coupling_compiler_to_transport(self) -> None:
        class FakeTransport:
            def __init__(self) -> None:
                self.calls = []

            def call(self, tool, arguments):
                self.calls.append((tool, arguments))
                if tool == "create_draft":
                    return {"draft_id": "real-draft-123"}
                return {"ok": True}

        plan = {"calls": [
            {"call_id": "create_draft", "tool": "create_draft", "arguments": {"width": 1, "height": 1}},
            {"call_id": "save_draft", "tool": "save_draft", "arguments": {
                "draft_id": {"$ref": "create_draft.result.draft_id"}
            }},
        ]}
        transport = FakeTransport()
        receipt = VectCutExecutor(transport).execute(plan)
        self.assertEqual("real-draft-123", transport.calls[1][1]["draft_id"])
        self.assertEqual("completed", receipt["status"])


if __name__ == "__main__":
    unittest.main()
