from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cut_workbench.editor_sync import EditorSync, SyncSessionStore
from cut_workbench.errors import ValidationError
from cut_workbench.jianying import JianyingCodecCommand, JianyingDraftAdapter, PlainJsonCodec
from cut_workbench.project_store import ProjectStore


def external_snapshot(
    *, timeline_start: float = 0.0, speed: float = 1.0, source_in: float = 0.0,
    source_out: float = 5.0, extra: bool = False, deleted: bool = False,
):
    entities = {
        "jy-seg-1": {
            "external_id": "jy-seg-1",
            "kind": "segment",
            "track_external_id": "jy-track-1",
            "material_external_id": "jy-mat-1",
            "properties": {
                "timeline_start": timeline_start,
                "timeline_duration": (source_out - source_in) / speed,
                "source_in": source_in,
                "source_out": source_out,
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
            "entity_path": "/tracks/0/segments/0",
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
    if deleted:
        del entities["jy-seg-1"]
    return {
        "schema_version": 1,
        "adapter_id": "fake:jianying",
        "draft_id": "draft-1",
        "fingerprint": f"fp-{timeline_start}-{speed}-{source_in}-{source_out}-{extra}-{deleted}",
        "tracks": {
            "jy-track-1": {
                "external_id": "jy-track-1", "kind": "video", "order": 0,
                "segment_collection_path": "/tracks/0/segments",
                "segment_count": 0 if deleted else 1,
            },
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
    def test_codec_rechecks_the_staged_helper_against_the_mandatory_pin(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            helper = root / "helper.exe"
            install = root / "install"
            install.mkdir()
            helper.write_bytes(b"pinned")
            (install / "videoeditor.dll").write_bytes(b"dll")
            expected = hashlib.sha256(b"pinned").hexdigest()
            codec = JianyingCodecCommand(helper, install, expected_sha256=expected)
            helper.write_bytes(b"replaced after initialization")
            encrypted = root / "draft_content.json"
            encrypted.write_bytes(b"payload")

            with self.assertRaisesRegex(ValidationError, "no longer matches"):
                codec.decode(encrypted)

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

    def test_publish_discards_clone_if_jianying_starts_during_encoding(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            destination = Path(directory) / "published"
            source.mkdir()
            (source / "draft_content.json").write_text("{}", encoding="utf-8")
            states = iter((False, True))
            adapter = JianyingDraftAdapter(
                codec=PlainJsonCodec(), editor_version="fixture", process_checker=lambda: next(states)
            )

            with self.assertRaisesRegex(ValidationError, "started during publish"):
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

    def test_publish_can_restore_a_deleted_segment_at_its_native_index(self) -> None:
        draft = {
            "id": "draft-1", "materials": {"videos": []},
            "tracks": [{"id": "track-1", "type": "video", "segments": []}],
        }
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            destination = Path(directory) / "published"
            source.mkdir()
            (source / "draft_content.json").write_text(json.dumps(draft), encoding="utf-8")
            adapter = JianyingDraftAdapter(
                codec=PlainJsonCodec(), editor_version="fixture", process_checker=lambda: False
            )
            adapter.publish(source, destination, [{
                "op": "insert", "path": "/tracks/0/segments/0", "value": {"id": "restored"},
            }])
            restored = json.loads((destination / "draft_content.json").read_text(encoding="utf-8"))

        self.assertEqual("restored", restored["tracks"][0]["segments"][0]["id"])

    def test_publish_registers_a_unique_clone_and_rewrites_its_metadata(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "Original"
            destination = root / "Acceptance"
            source.mkdir()
            (source / "draft_content.json").write_text('{"id":"timeline-1","tracks":[]}', encoding="utf-8")
            original_meta = {
                "draft_id": "draft-original", "draft_name": "Original",
                "draft_fold_path": str(source), "draft_root_path": str(root),
                "draft_cover": str(source / "draft_cover.jpg"),
                "tm_draft_create": 1, "tm_draft_modified": 2,
            }
            (source / "draft_meta_info.json").write_text(json.dumps(original_meta), encoding="utf-8")
            index_path = root / "root_meta_info.json"
            index_path.write_text(json.dumps({
                "all_draft_store": [{
                    **original_meta, "draft_json_file": str(source / "draft_content.json")
                }],
                "draft_ids": 1, "root_path": str(root),
            }), encoding="utf-8")
            adapter = JianyingDraftAdapter(
                codec=PlainJsonCodec(), editor_version="fixture", process_checker=lambda: False,
                draft_index_path=index_path,
            )
            receipt = adapter.publish(source, destination, [])
            source_meta = json.loads((source / "draft_meta_info.json").read_text(encoding="utf-8"))
            clone_meta = json.loads((destination / "draft_meta_info.json").read_text(encoding="utf-8"))
            index = json.loads(index_path.read_text(encoding="utf-8"))

        self.assertEqual("draft-original", source_meta["draft_id"])
        self.assertNotEqual("draft-original", clone_meta["draft_id"])
        self.assertEqual("Acceptance", clone_meta["draft_name"])
        self.assertEqual(2, index["draft_ids"])
        self.assertEqual(clone_meta["draft_id"], index["all_draft_store"][-1]["draft_id"])
        self.assertTrue(receipt["registered"])
        self.assertTrue(receipt["index_backup_path"])


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

    def test_removed_opaque_entity_does_not_remain_as_a_ghost_record(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store, _ = self._project(root)
            first_adapter = FakeAdapter([external_snapshot(extra=True), external_snapshot(extra=True)])
            first = EditorSync(store=store, sessions=SyncSessionStore(root), adapter=first_adapter)
            first_session = first.open(project_id="sync", draft_path="D:/drafts/demo")
            first.preview(first_session["session_id"])
            first.commit(first_session["session_id"], resolutions={})

            second_adapter = FakeAdapter([external_snapshot(extra=True), external_snapshot(extra=False)])
            second = EditorSync(store=store, sessions=SyncSessionStore(root), adapter=second_adapter)
            second_session = second.open(project_id="sync", draft_path="D:/drafts/demo")
            second.preview(second_session["session_id"])
            second.commit(second_session["session_id"], resolutions={})

            external_ids = {
                item["external_id"] for item in store.read_project("sync")["external_entities"].values()
            }
            self.assertNotIn("jy-human-added", external_ids)

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
            sync.commit(opened["session_id"], resolutions={})
            receipt = sync.publish(opened["session_id"], destination_path="D:/drafts/demo-trimmed")

            by_path = {patch["path"]: patch["value"] for patch in receipt["patches"]}
            self.assertEqual(1.0, by_path["/tracks/0/segments/0/source_timerange/start"])
            self.assertEqual(3.0, by_path["/tracks/0/segments/0/source_timerange/duration"])

    def test_manual_trim_commits_without_treating_derived_duration_as_a_project_field(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store, _ = self._project(root)
            adapter = FakeAdapter([
                external_snapshot(), external_snapshot(source_in=1.0, source_out=4.0),
            ])
            sync = EditorSync(store=store, sessions=SyncSessionStore(root), adapter=adapter)
            opened = sync.open(project_id="sync", draft_path="D:/drafts/demo")
            sync.preview(opened["session_id"])
            sync.commit(opened["session_id"], resolutions={})

            segment = store.read_project("sync")["segments"]["SEG-001"]
            self.assertEqual((1.0, 4.0), (segment["source_in"], segment["source_out"]))

    def test_commit_rejects_a_plan_after_project_changes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store, project = self._project(root)
            adapter = FakeAdapter([external_snapshot(), external_snapshot()])
            sync = EditorSync(store=store, sessions=SyncSessionStore(root), adapter=adapter)
            opened = sync.open(project_id="sync", draft_path="D:/drafts/demo")
            sync.preview(opened["session_id"])
            store.apply_plan(
                project_id="sync", expected_revision=project["revision"], actor="agent", reason="late edit",
                operations=[{"op": "update_segment", "segment_id": "SEG-001", "changes": {"speed": 1.2}}],
            )

            with self.assertRaisesRegex(ValidationError, "project changed after sync.preview"):
                sync.commit(opened["session_id"], resolutions={})

    def test_publish_requires_commit_and_opaque_baseline_is_journaled(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store, _ = self._project(root)
            adapter = FakeAdapter([external_snapshot(), external_snapshot()])
            sync = EditorSync(store=store, sessions=SyncSessionStore(root), adapter=adapter)
            opened = sync.open(project_id="sync", draft_path="D:/drafts/demo")
            sync.preview(opened["session_id"])
            with self.assertRaisesRegex(ValidationError, "requires sync.commit"):
                sync.publish(opened["session_id"], destination_path="D:/drafts/invalid")

            sync.commit(opened["session_id"], resolutions={})
            ledgers = [
                item for item in store.read_project("sync")["external_entities"].values()
                if item["kind"] == "opaque-draft-ledger"
            ]
            self.assertEqual(1, len(ledgers))
            self.assertEqual("draft-1", ledgers[0]["properties"]["draft_id"])
            with self.assertRaisesRegex(ValidationError, "cannot reopen"):
                sync.preview(opened["session_id"])

    def test_explicit_binding_rejects_non_segment_native_entity(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store, _ = self._project(root)
            snapshot = external_snapshot(extra=True)
            adapter = FakeAdapter([snapshot])
            sync = EditorSync(store=store, sessions=SyncSessionStore(root), adapter=adapter)

            with self.assertRaisesRegex(ValidationError, "requires an A/V segment"):
                sync.open(
                    project_id="sync", draft_path="D:/drafts/demo",
                    bindings={"jy-human-added": "SEG-001"},
                )

    def test_delete_vs_agent_edit_conflict_can_restore_the_native_segment(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store, project = self._project(root)
            adapter = FakeAdapter([external_snapshot(), external_snapshot(deleted=True)])
            sync = EditorSync(store=store, sessions=SyncSessionStore(root), adapter=adapter)
            opened = sync.open(project_id="sync", draft_path="D:/drafts/demo")
            store.apply_plan(
                project_id="sync", expected_revision=project["revision"], actor="agent", reason="speed",
                operations=[{"op": "update_segment", "segment_id": "SEG-001", "changes": {"speed": 1.5}}],
            )
            preview = sync.preview(opened["session_id"])
            conflict = next(item for item in preview["conflicts"] if item["field"] == "__deleted__")
            sync.commit(opened["session_id"], resolutions={conflict["conflict_id"]: "agent"})
            receipt = sync.publish(opened["session_id"], destination_path="D:/drafts/restored")

            self.assertEqual("insert", receipt["patches"][0]["op"])
            self.assertEqual("/tracks/0/segments/0", receipt["patches"][0]["path"])

    def test_delete_restore_relocates_by_current_track_instead_of_baseline_index(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store, project = self._project(root)
            current = external_snapshot(deleted=True)
            current["tracks"]["jy-track-1"].update(
                order=2, segment_collection_path="/tracks/2/segments", segment_count=3
            )
            current["fingerprint"] += "-reordered"
            adapter = FakeAdapter([external_snapshot(), current])
            sync = EditorSync(store=store, sessions=SyncSessionStore(root), adapter=adapter)
            opened = sync.open(project_id="sync", draft_path="D:/drafts/demo")
            store.apply_plan(
                project_id="sync", expected_revision=project["revision"], actor="agent", reason="move",
                operations=[{"op": "update_segment", "segment_id": "SEG-001", "changes": {"timeline_start": 2.0}}],
            )
            preview = sync.preview(opened["session_id"])
            conflict = next(item for item in preview["conflicts"] if item["field"] == "__deleted__")
            sync.commit(opened["session_id"], resolutions={conflict["conflict_id"]: "agent"})
            receipt = sync.publish(opened["session_id"], destination_path="D:/drafts/relocated")

            self.assertEqual("/tracks/2/segments/3", receipt["patches"][0]["path"])


if __name__ == "__main__":
    unittest.main()
