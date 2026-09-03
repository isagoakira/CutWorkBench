from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

from cut_workbench.editor_sync import EditorSyncRegistry, SyncSessionStore
from cut_workbench.errors import ValidationError
from cut_workbench.local_editor import AfterEffectsAdapter, LocalFileBridge, PremiereAdapter
from cut_workbench.project_store import ProjectStore


def snapshot(*, adapter_id: str, draft_path: str, fingerprint: str = "fingerprint-1") -> dict:
    return {
        "schema_version": 1,
        "adapter_id": adapter_id,
        "draft_id": "sequence-or-comp-1",
        "fingerprint": fingerprint,
        "tracks": {
            "track-1": {"external_id": "track-1", "kind": "video", "order": 0},
        },
        "materials": {
            "media-1": {"external_id": "media-1", "kind": "video", "path": "D:/media/source.mp4"},
        },
        "entities": {
            "clip-1": {
                "external_id": "clip-1", "kind": "segment", "track_external_id": "track-1",
                "material_external_id": "media-1",
                "properties": {
                    "timeline_start": 0.0, "timeline_duration": 5.0,
                    "source_in": 0.0, "source_out": 5.0, "speed": 1.0, "transform": {},
                },
                "property_paths": {
                    "timeline_start": "/sequences/sequence-1/video/0/clip-1/timeline_start",
                    "source_in": "/sequences/sequence-1/video/0/clip-1/source_in",
                    "source_out": "/sequences/sequence-1/video/0/clip-1/source_out",
                    "speed": "/sequences/sequence-1/video/0/clip-1/speed",
                    "transform": "/sequences/sequence-1/video/0/clip-1/transform",
                },
                "native": {"opaque": {"keep": True}},
            },
        },
        "native_summary": {"active_path": draft_path},
    }


class LocalFileBridgeTests(unittest.TestCase):
    def _bridge(
        self,
        root: Path,
        *,
        adapter_id: str,
        draft_path: str,
        request_id: str = "request-1",
        writable: bool = True,
    ):
        profile = {
            "protocol_version": 1,
            "adapter_id": adapter_id,
            "editor_version": "test",
            "writable": writable,
        }
        (root / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
        (root / "authorization.json").write_text(json.dumps({
            "protocol_version": 1, "adapter_id": adapter_id, "publish_enabled": writable,
        }), encoding="utf-8")
        (root / "snapshot.json").write_text(json.dumps({
            "protocol_version": 1, "adapter_id": adapter_id, "draft_path": draft_path,
            "snapshot": snapshot(adapter_id=adapter_id, draft_path=draft_path),
        }), encoding="utf-8")
        return LocalFileBridge(root, adapter_id=adapter_id, request_id_factory=lambda: request_id, poll_interval=0)

    def test_premiere_adapter_reads_a_matching_local_snapshot_and_declares_profile(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            draft = "D:/Projects/rough-cut.prproj"
            bridge = self._bridge(root, adapter_id="premiere:uxp-local", draft_path=draft)
            adapter = PremiereAdapter(bridge)

            result = adapter.snapshot(draft)
            profile = adapter.profile()

        self.assertEqual("fingerprint-1", result["fingerprint"])
        self.assertEqual("premiere:uxp-local", profile["adapter_id"])
        self.assertEqual(".prproj", profile["project_extension"])

    def test_adapter_rejects_wrong_project_type_and_snapshot_for_another_project(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bridge = self._bridge(root, adapter_id="premiere:uxp-local", draft_path="D:/Projects/one.prproj")
            adapter = PremiereAdapter(bridge)

            with self.assertRaisesRegex(ValidationError, r"\.prproj"):
                adapter.snapshot("D:/Projects/one.aep")
            with self.assertRaisesRegex(ValidationError, "different project"):
                adapter.snapshot("D:/Projects/two.prproj")

    def test_premiere_cep_adapter_is_supported_for_legacy_local_hosts(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            draft = "D:/Projects/rough-cut.prproj"
            bridge = self._bridge(root, adapter_id="premiere:cep-local", draft_path=draft)

            result = PremiereAdapter(bridge).snapshot(draft)

        self.assertEqual("premiere:cep-local", result["adapter_id"])

    def test_bridge_rejects_a_profile_that_does_not_match_the_configured_hash_pin(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            draft = "D:/Projects/rough-cut.prproj"
            self._bridge(root, adapter_id="premiere:uxp-local", draft_path=draft)
            actual = hashlib.sha256((root / "profile.json").read_bytes()).hexdigest()
            pinned = LocalFileBridge(
                root, adapter_id="premiere:uxp-local", expected_profile_sha256=actual,
            )
            rejected = LocalFileBridge(
                root, adapter_id="premiere:uxp-local", expected_profile_sha256="0" * 64,
            )

            self.assertEqual("premiere:uxp-local", pinned.profile()["adapter_id"])
            with self.assertRaisesRegex(ValidationError, "hash does not match"):
                rejected.profile()

    def test_publish_only_queues_allowlisted_patches_and_requires_a_clone_receipt(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "rough-cut.prproj"
            source.write_bytes(b"original project")
            destination_file = root / "rough-cut-agent.prproj"
            draft = str(source)
            destination = str(destination_file)
            bridge = self._bridge(root, adapter_id="premiere:uxp-local", draft_path=draft)
            adapter = PremiereAdapter(bridge)
            adapter.snapshot(draft)
            patch = {"op": "set", "path": "/sequences/sequence-1/video/0/clip-1/speed", "value": 1.25}

            def write_clone_and_receipt() -> str:
                destination_file.write_bytes(b"cloned project")
                clone_snapshot = snapshot(
                    adapter_id="premiere:uxp-local", draft_path=destination,
                    fingerprint="fingerprint-2",
                )
                clone_snapshot["entities"]["clip-1"]["properties"]["speed"] = 1.25
                (root / "responses").mkdir()
                (root / "responses" / "request-1.json").write_text(json.dumps({
                    "protocol_version": 1, "request_id": "request-1", "status": "published",
                    "adapter_id": "premiere:uxp-local",
                    "source_path": draft, "destination_path": destination,
                    "source_fingerprint": "fingerprint-1", "result_fingerprint": "fingerprint-2",
                    "applied_patches": [patch],
                    "result_snapshot": clone_snapshot,
                }), encoding="utf-8")
                return "request-1"

            bridge.request_id_factory = write_clone_and_receipt

            receipt = adapter.publish(draft, destination, [patch])
            command = json.loads((root / "commands" / "request-1.json").read_text(encoding="utf-8"))

        self.assertEqual("published", receipt["status"])
        self.assertEqual(destination, command["destination_path"])
        self.assertEqual("fingerprint-1", command["expected_fingerprint"])

    def test_publish_rejects_unmodeled_paths_before_writing_a_command(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "rough-cut.prproj"
            source.write_bytes(b"original project")
            draft = str(source)
            bridge = self._bridge(root, adapter_id="premiere:uxp-local", draft_path=draft)
            adapter = PremiereAdapter(bridge)
            adapter.snapshot(draft)

            with self.assertRaisesRegex(ValidationError, "not allowlisted"):
                adapter.publish(draft, "D:/Projects/copy.prproj", [{
                    "op": "set", "path": "/project/unknown/native-field", "value": 1,
                }])
            self.assertFalse((root / "commands").exists())

    def test_read_only_panel_can_supply_a_snapshot_but_cannot_publish(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "rough-cut.prproj"
            source.write_bytes(b"original project")
            draft = str(source)
            bridge = self._bridge(
                root, adapter_id="premiere:uxp-local", draft_path=draft, writable=False,
            )
            adapter = PremiereAdapter(bridge)

            self.assertEqual("fingerprint-1", adapter.snapshot(draft)["fingerprint"])
            with self.assertRaisesRegex(ValidationError, "not writable"):
                adapter.publish(draft, root / "rough-cut-agent.prproj", [])

    def test_publish_requires_current_panel_authorization_after_a_fresh_snapshot(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "rough-cut.prproj"
            source.write_bytes(b"original project")
            draft = str(source)
            bridge = self._bridge(root, adapter_id="premiere:cep-local", draft_path=draft)
            adapter = PremiereAdapter(bridge)
            adapter.snapshot(draft)
            (root / "authorization.json").write_text(json.dumps({
                "protocol_version": 1, "adapter_id": "premiere:cep-local", "publish_enabled": False,
            }), encoding="utf-8")

            with self.assertRaisesRegex(ValidationError, "not authorized"):
                adapter.publish(draft, root / "rough-cut-agent.prproj", [])

    def test_publish_rejects_a_receipt_from_another_adapter(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "rough-cut.prproj"
            source.write_bytes(b"original project")
            draft = str(source)
            destination = root / "rough-cut-agent.prproj"
            bridge = self._bridge(root, adapter_id="premiere:cep-local", draft_path=draft)
            adapter = PremiereAdapter(bridge)
            adapter.snapshot(draft)

            def write_wrong_receipt() -> str:
                destination.write_bytes(b"clone")
                (root / "responses").mkdir()
                (root / "responses" / "request-1.json").write_text(json.dumps({
                    "protocol_version": 1, "request_id": "request-1", "status": "published",
                    "adapter_id": "after-effects:cep-local", "source_path": draft,
                    "destination_path": str(destination), "source_fingerprint": "fingerprint-1",
                    "result_fingerprint": "fingerprint-2", "applied_patches": [],
                    "result_snapshot": snapshot(
                        adapter_id="after-effects:cep-local", draft_path=str(destination),
                        fingerprint="fingerprint-2",
                    ),
                }), encoding="utf-8")
                return "request-1"

            bridge.request_id_factory = write_wrong_receipt
            with self.assertRaisesRegex(ValidationError, "another adapter"):
                adapter.publish(draft, destination, [])


class EditorSyncRegistryTests(unittest.TestCase):
    def test_registry_selects_the_project_adapter_and_pins_it_in_the_session(self) -> None:
        class Adapter:
            adapter_id = "premiere:uxp-local"

            def profile(self):
                return {"adapter_id": self.adapter_id, "editor_version": "test", "writable": True}

            def snapshot(self, draft_path):
                return copy.deepcopy(snapshot(adapter_id=self.adapter_id, draft_path=str(draft_path)))

            def publish(self, draft_path, destination_path, patches):
                return {"status": "published", "destination_path": str(destination_path), "patches": list(patches)}

        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = ProjectStore(root)
            store.create_project(
                project_id="premiere-sync", title="Premiere", editor_adapter="premiere:uxp-local",
                canvas={"width": 1920, "height": 1080, "fps": 30},
            )
            registry = EditorSyncRegistry(
                store=store, sessions=SyncSessionStore(root), adapters={"premiere:uxp-local": Adapter()},
            )

            session = registry.open(project_id="premiere-sync", draft_path="D:/Projects/rough-cut.prproj")

        self.assertEqual("premiere:uxp-local", session["adapter_profile"]["adapter_id"])

    def test_registry_rejects_a_session_when_its_pinned_adapter_profile_changes(self) -> None:
        class Adapter:
            adapter_id = "premiere:cep-local"
            version = "23.0"

            def profile(self):
                return {"adapter_id": self.adapter_id, "editor_version": self.version, "writable": True}

            def snapshot(self, draft_path):
                return copy.deepcopy(snapshot(adapter_id=self.adapter_id, draft_path=str(draft_path)))

            def publish(self, draft_path, destination_path, patches):
                raise AssertionError("not reached")

        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = ProjectStore(root)
            store.create_project(
                project_id="premiere-profile-pin", title="Premiere", editor_adapter="premiere:cep-local",
                canvas={"width": 1920, "height": 1080, "fps": 30},
            )
            adapter = Adapter()
            registry = EditorSyncRegistry(
                store=store, sessions=SyncSessionStore(root), adapters={adapter.adapter_id: adapter},
            )
            session = registry.open(project_id="premiere-profile-pin", draft_path="D:/Projects/rough-cut.prproj")
            adapter.version = "23.1"

            with self.assertRaisesRegex(ValidationError, "profile changed"):
                registry.preview(session["session_id"])


class AfterEffectsAdapterTests(unittest.TestCase):
    def test_after_effects_adapter_requires_an_aep_project(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bridge = LocalFileBridge(root, adapter_id="after-effects:cep-local")
            adapter = AfterEffectsAdapter(bridge)

            with self.assertRaisesRegex(ValidationError, r"\.aep"):
                adapter.snapshot("D:/Projects/not-a-project.prproj")


class CepPanelPackageTests(unittest.TestCase):
    def test_panels_target_the_installed_2023_hosts_and_fixed_adapter_ids(self) -> None:
        root = Path(__file__).resolve().parents[1] / "adapters" / "cep-local"
        cases = {
            "premiere": ("PPRO", "premiere:cep-local"),
            "after-effects": ("AEFT", "after-effects:cep-local"),
        }

        for panel, (host, adapter_id) in cases.items():
            manifest = ElementTree.parse(root / panel / "CSXS" / "manifest.xml")
            self.assertEqual(host, manifest.find(".//Host").attrib["Name"])
            host_code = (root / panel / "jsx" / "host.jsx").read_text(encoding="utf-8")
            self.assertIn('ADAPTER_ID = "' + adapter_id + '"', host_code)
            self.assertIn('"publish-clone"', host_code)


if __name__ == "__main__":
    unittest.main()
