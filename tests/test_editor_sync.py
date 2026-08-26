from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cut_workbench.editor_sync import EditorSync, SyncSessionStore
from cut_workbench.errors import ValidationError
from cut_workbench.jianying import JianyingDraftAdapter, PlainJsonCodec
from cut_workbench.project_store import ProjectStore


def external_snapshot(*, timeline_start: float = 0.0, speed: float = 1.0, extra: bool = False):
    entities = {
        "jy-seg-1": {
            "external_id": "jy-seg-1",
            "kind": "segment",
            "track_external_id": "jy-track-1",
            "material_external_id": "jy-mat-1",
            "properties": {
                "timeline_start": timeline_start,
                "source_in": 0.0,
                "source_out": 5.0,
                "speed": speed,
                "transform": {},
            },
            "property_paths": {
                "timeline_start": "/tracks/0/segments/0/target_timerange/start",
                "timeline_duration": "/tracks/0/segments/0/target_timerange/duration",
                "source_in": "/tracks/0/segments/0/source_timerange/start",
                "source_duration": "/tracks/0/segments/0/source_timerange/duration",
                "speed": "/tracks/0/segments/0/speed",
            },
            "native": {"id": "jy-seg-1"},
        }
    }
    if extra:
        entities["jy-human-added"] = {
            "external_id": "jy-human-added", "kind": "sticker",
            "track_external_id": "jy-track-2", "material_external_id": "jy-sticker-1",
            "properties": {"timeline_start": 1.0}, "property_paths": {},
            "native": {"id": "jy-human-added", "future_field": {"keep": True}},
        }
    return {
        "schema_version": 1,
        "adapter_id": "fake:jianying",
        "draft_id": "draft-1",
        "fingerprint": f"fp-{timeline_start}-{speed}-{extra}",
        "tracks": {
            "jy-track-1": {"external_id": "jy-track-1", "kind": "video", "order": 0},
        },
        "materials": {
            "jy-mat-1": {"external_id": "jy-mat-1", "kind": "video", "path": "D:/media/source.mp4"},
        },
        "entities": entities,
        "native_summary": {},
    }


class FakeAdapter:
    adapter_id = "fake:jianying"

    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.published = []

    def profile(self):
        return {"adapter_id": self.adapter_id, "editor_version": "11.3-test", "writable": True}

    def snapshot(self, draft_path):
        return copy.deepcopy(self.snapshots.pop(0) if len(self.snapshots) > 1 else self.snapshots[0])

    def publish(self, draft_path, destination_path, patches):
        receipt = {"status": "published", "destination_path": str(destination_path), "patches": copy.deepcopy(patches)}
        self.published.append(receipt)
        return receipt


class JianyingAdapterTests(unittest.TestCase):
    def test_publish_refuses_while_jianying_is_running_without_creating_destination(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            destination = Path(directory) / "published"
            source.mkdir()
            (source / "draft_content.json").write_text("{}", encoding="utf-8")
            adapter = JianyingDraftAdapter(
                codec=PlainJsonCodec(), editor_version="fixture", process_checker=lambda: True
            )

            with self.assertRaisesRegex(ValidationError, "Jianying is running"):
                adapter.publish(source, destination, [])
            self.assertFalse(destination.exists())

    def test_plain_draft_is_normalized_without_discarding_native_fields(self) -> None:
        draft = {
            "id": "draft-1", "duration": 5000000, "canvas_config": {"width": 1920, "height": 1080},
            "materials": {"videos": [{"id": "mat-1", "path": "D:/media/source.mp4", "future": {"x": 1}}]},
            "tracks": [{
                "id": "track-1", "type": "video", "future_track": 7,
                "segments": [{
                    "id": "seg-1", "material_id": "mat-1", "speed": 1.0,
                    "source_timerange": {"start": 1000000, "duration": 3000000},
                    "target_timerange": {"start": 2000000, "duration": 3000000},
                    "clip": {"transform": {"x": 0.1}}, "future_segment": {"keep": True},
                }],
            }],
            "future_root": {"must_survive": True},
        }
        with TemporaryDirectory() as directory:
            draft_dir = Path(directory) / "draft"
            draft_dir.mkdir()
            (draft_dir / "draft_content.json").write_text(json.dumps(draft), encoding="utf-8")
            adapter = JianyingDraftAdapter(codec=PlainJsonCodec(), editor_version="fixture")
            snapshot = adapter.snapshot(draft_dir)

        entity = snapshot["entities"]["seg-1"]
        self.assertEqual(2.0, entity["properties"]["timeline_start"])
        self.assertEqual(1.0, entity["properties"]["source_in"])
        self.assertEqual("D:/media/source.mp4", snapshot["materials"]["mat-1"]["path"])
        self.assertEqual({"keep": True}, entity["native"]["future_segment"])
        self.assertEqual({"must_survive": True}, snapshot["native_summary"]["opaque_root"]["future_root"])

    def test_publish_only_writes_a_clone_and_preserves_unknown_json(self) -> None:
        draft = {
            "id": "draft-1", "materials": {"videos": []}, "future_root": {"keep": True},
            "tracks": [{"id": "track-1", "type": "video", "segments": [{
                "id": "seg-1", "material_id": "mat-1", "speed": 1,
                "source_timerange": {"start": 0, "duration": 1000000},
                "target_timerange": {"start": 0, "duration": 1000000},
            }]}],
        }
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            destination = Path(directory) / "published"
            source.mkdir()
            original = json.dumps(draft, sort_keys=True)
            (source / "draft_content.json").write_text(original, encoding="utf-8")
            adapter = JianyingDraftAdapter(codec=PlainJsonCodec(), editor_version="fixture", process_checker=lambda: False)
            receipt = adapter.publish(source, destination, [{
                "op": "set", "path": "/tracks/0/segments/0/speed", "value": 1.5,
            }])
            source_after = (source / "draft_content.json").read_text(encoding="utf-8")
            published = json.loads((destination / "draft_content.json").read_text(encoding="utf-8"))

        self.assertEqual(original, source_after)
        self.assertEqual(1.5, published["tracks"][0]["segments"][0]["speed"])
        self.assertEqual({"keep": True}, published["future_root"])
        self.assertEqual("published", receipt["status"])


class EditorSyncTests(unittest.TestCase):
    def _project(self, root: Path):
        store = ProjectStore(root)
        project = store.create_project(
            project_id="sync", title="Sync", canvas={"width": 1920, "height": 1080, "fps": 30}
        )
        project = store.apply_plan(
            project_id="sync", expected_revision=1, actor="agent", reason="base", operations=[
                {"op": "register_source", "source_id": "SRC-001", "locator": "D:/media/source.mp4"},
                {"op": "add_track", "track_id": "V1-BASE", "kind": "video", "purpose": "base"},
                {"op": "add_segment", "segment_id": "SEG-001", "source_id": "SRC-001", "track_id": "V1-BASE",
                 "source_in": 0, "source_out": 5, "timeline_start": 0},
            ],
        )
        return store, project

    def test_conflicting_human_timing_can_be_committed_as_a_new_revision(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store, project = self._project(root)
            adapter = FakeAdapter([external_snapshot(), external_snapshot(timeline_start=2.0)])
            sync = EditorSync(store=store, sessions=SyncSessionStore(root), adapter=adapter)
            opened = sync.open(project_id="sync", draft_path="D:/drafts/demo")
            self.assertEqual({"jy-seg-1": "SEG-001"}, opened["bindings"])

            project = store.apply_plan(
                project_id="sync", expected_revision=project["revision"], actor="agent", reason="agent move",
                operations=[{"op": "update_segment", "segment_id": "SEG-001", "changes": {"timeline_start": 1.0}}],
            )
            preview = sync.preview(opened["session_id"])
            self.assertEqual(1, len(preview["conflicts"]))
            conflict = preview["conflicts"][0]
            self.assertEqual("timeline_start", conflict["field"])

            committed = sync.commit(opened["session_id"], resolutions={conflict["conflict_id"]: "human"})
            current = store.read_project("sync")
            self.assertEqual(2.0, current["segments"]["SEG-001"]["timeline_start"])
            self.assertEqual(current["revision"], committed["project_revision"])

    def test_nonconflicting_agent_and_human_changes_merge_and_publish_incrementally(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store, project = self._project(root)
            adapter = FakeAdapter([external_snapshot(), external_snapshot(timeline_start=2.0)])
            sync = EditorSync(store=store, sessions=SyncSessionStore(root), adapter=adapter)
            opened = sync.open(project_id="sync", draft_path="D:/drafts/demo")
            store.apply_plan(
                project_id="sync", expected_revision=project["revision"], actor="agent", reason="agent speed",
                operations=[{"op": "update_segment", "segment_id": "SEG-001", "changes": {"speed": 1.5}}],
            )
            preview = sync.preview(opened["session_id"])
            self.assertEqual([], preview["conflicts"])
            self.assertTrue(any(change["side"] == "human" for change in preview["changes"]))
            self.assertTrue(any(change["side"] == "agent" for change in preview["changes"]))
            sync.commit(opened["session_id"], resolutions={})
            receipt = sync.publish(opened["session_id"], destination_path="D:/drafts/demo-merged")

            current = store.read_project("sync")
            self.assertEqual(2.0, current["segments"]["SEG-001"]["timeline_start"])
            self.assertEqual(1.5, current["segments"]["SEG-001"]["speed"])
            self.assertTrue(any(patch["path"].endswith("/speed") for patch in receipt["patches"]))

    def test_unbound_human_entity_is_preserved_as_an_external_entity(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store, _ = self._project(root)
            adapter = FakeAdapter([external_snapshot(), external_snapshot(extra=True)])
            sync = EditorSync(store=store, sessions=SyncSessionStore(root), adapter=adapter)
            opened = sync.open(project_id="sync", draft_path="D:/drafts/demo")
            preview = sync.preview(opened["session_id"])
            self.assertTrue(any(item["kind"] == "external-add" for item in preview["changes"]))
            sync.commit(opened["session_id"], resolutions={})
            external = store.read_project("sync")["external_entities"]
            self.assertEqual({"keep": True}, next(iter(external.values()))["native"]["future_field"])

    def test_agent_source_range_is_published_as_jianying_start_and_duration(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store, project = self._project(root)
            adapter = FakeAdapter([external_snapshot(), external_snapshot()])
            sync = EditorSync(store=store, sessions=SyncSessionStore(root), adapter=adapter)
            opened = sync.open(project_id="sync", draft_path="D:/drafts/demo")
            store.apply_plan(
                project_id="sync", expected_revision=project["revision"], actor="agent", reason="trim",
                operations=[{"op": "update_segment", "segment_id": "SEG-001", "changes": {
                    "source_in": 1.0, "source_out": 4.0,
                }}],
            )
            sync.preview(opened["session_id"])
            receipt = sync.publish(opened["session_id"], destination_path="D:/drafts/demo-trimmed")

            by_path = {patch["path"]: patch["value"] for patch in receipt["patches"]}
            self.assertEqual(1.0, by_path["/tracks/0/segments/0/source_timerange/start"])
            self.assertEqual(3.0, by_path["/tracks/0/segments/0/source_timerange/duration"])


if __name__ == "__main__":
    unittest.main()
