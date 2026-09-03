from __future__ import annotations

import copy
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

from .errors import ValidationError


class LocalFileBridge:
    """A narrow, auditable file protocol for a local editor panel.

    The editor-owned panel writes `profile.json` and `snapshot.json`; Workbench
    writes a publish command and accepts only a matching clone receipt.  This
    keeps UXP/CEP host code out of the versioned Workbench core.
    """

    protocol_version = 1

    def __init__(
        self,
        root: Path,
        *,
        adapter_id: str,
        timeout: float = 30.0,
        poll_interval: float = 0.1,
        request_id_factory: Callable[[], str] | None = None,
        expected_profile_sha256: str | None = None,
        expected_editor_version: str | None = None,
        panel_root: Path | None = None,
        expected_panel_sha256: str | None = None,
    ) -> None:
        self.root = Path(root)
        self.adapter_id = adapter_id
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.request_id_factory = request_id_factory or (lambda: uuid.uuid4().hex)
        if expected_profile_sha256 is not None and not _is_sha256(expected_profile_sha256):
            raise ValidationError("editor bridge profile hash pin must be a SHA-256 value")
        if expected_panel_sha256 is not None and not _is_sha256(expected_panel_sha256):
            raise ValidationError("editor panel hash pin must be a SHA-256 value")
        if (panel_root is None) != (expected_panel_sha256 is None):
            raise ValidationError("editor panel root and hash pin must be configured together")
        self.expected_profile_sha256 = expected_profile_sha256.lower() if expected_profile_sha256 else None
        self.expected_editor_version = expected_editor_version
        self.panel_root = Path(panel_root) if panel_root else None
        self.expected_panel_sha256 = expected_panel_sha256.lower() if expected_panel_sha256 else None
        self._snapshots: dict[str, dict[str, Any]] = {}

    def profile(self) -> dict[str, Any]:
        profile_path = self.root / "profile.json"
        if self.expected_profile_sha256 is not None:
            actual = _file_hash(profile_path)
            if actual != self.expected_profile_sha256:
                raise ValidationError("editor bridge profile hash does not match the configured pin")
        value = _read_object(profile_path, "editor bridge profile")
        if value.get("protocol_version") != self.protocol_version:
            raise ValidationError("editor bridge profile has an unsupported protocol version")
        if value.get("adapter_id") != self.adapter_id:
            raise ValidationError("editor bridge profile belongs to another adapter")
        if not isinstance(value.get("editor_version"), str) or not value["editor_version"]:
            raise ValidationError("editor bridge profile has no editor version")
        if self.expected_editor_version is not None and value["editor_version"] != self.expected_editor_version:
            raise ValidationError("editor bridge profile editor version does not match the configured version")
        if not isinstance(value.get("writable"), bool):
            raise ValidationError("editor bridge profile has no writable state")
        panel_sha256 = panel_tree_hash(self.panel_root) if self.panel_root else None
        if panel_sha256 is not None and panel_sha256 != self.expected_panel_sha256:
            raise ValidationError("editor panel hash does not match the configured pin")
        return {
            "adapter_id": self.adapter_id,
            "editor_version": value["editor_version"],
            "writable": value["writable"],
            "transport": "local-file-bridge",
            "protocol_version": self.protocol_version,
            "profile_sha256": _file_hash(profile_path),
            "panel_sha256": panel_sha256,
        }

    def snapshot(self, draft_path: str | Path) -> dict[str, Any]:
        self.profile()
        envelope = _read_object(self.root / "snapshot.json", "editor bridge snapshot")
        if envelope.get("protocol_version") != self.protocol_version:
            raise ValidationError("editor bridge snapshot has an unsupported protocol version")
        if envelope.get("adapter_id") != self.adapter_id:
            raise ValidationError("editor bridge snapshot belongs to another adapter")
        if _path_key(envelope.get("draft_path")) != _path_key(draft_path):
            raise ValidationError("editor bridge snapshot belongs to a different project")
        external = envelope.get("snapshot")
        if not isinstance(external, Mapping):
            raise ValidationError("editor bridge snapshot has no normalized editor snapshot")
        normalized = copy.deepcopy(dict(external))
        _validate_normalized_snapshot(normalized, self.adapter_id)
        self._snapshots[_path_key(draft_path)] = normalized
        return normalized

    def publish(
        self,
        draft_path: str | Path,
        destination_path: str | Path,
        patches: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        if not self.profile()["writable"]:
            raise ValidationError("editor bridge is not writable")
        if not self._publish_is_authorized():
            raise ValidationError("editor bridge clone publish is not authorized in the local editor panel")
        source_key = _path_key(draft_path)
        destination_key = _path_key(destination_path)
        if source_key == destination_key:
            raise ValidationError("publish destination must differ from the source project")
        if Path(destination_path).exists():
            raise ValidationError("publish destination already exists")
        current = self._snapshots.get(source_key)
        if current is None:
            raise ValidationError("publish requires a fresh editor snapshot")
        _validate_patches(patches, _writable_paths(current))
        request_id = self.request_id_factory()
        if not isinstance(request_id, str) or not request_id:
            raise ValidationError("editor bridge generated an invalid request ID")
        command = {
            "protocol_version": self.protocol_version,
            "request_id": request_id,
            "kind": "publish-clone",
            "adapter_id": self.adapter_id,
            "source_path": str(draft_path),
            "destination_path": str(destination_path),
            "expected_fingerprint": current["fingerprint"],
            "patches": [copy.deepcopy(dict(patch)) for patch in patches],
        }
        _atomic_write(self.root / "commands" / f"{request_id}.json", command)
        receipt = self._await_receipt(request_id)
        _validate_receipt(
            receipt, request_id=request_id, source_path=draft_path,
            destination_path=destination_path, expected_fingerprint=current["fingerprint"],
            expected_adapter_id=self.adapter_id, expected_patches=patches,
        )
        self._snapshots[destination_key] = copy.deepcopy(dict(receipt["result_snapshot"]))
        return {**receipt, "adapter_id": self.adapter_id}

    def _publish_is_authorized(self) -> bool:
        value = _read_object(self.root / "authorization.json", "editor bridge authorization")
        if value.get("protocol_version") != self.protocol_version or value.get("adapter_id") != self.adapter_id:
            raise ValidationError("editor bridge authorization belongs to another adapter or protocol")
        if not isinstance(value.get("publish_enabled"), bool):
            raise ValidationError("editor bridge authorization has no publish state")
        return value["publish_enabled"]

    def _await_receipt(self, request_id: str) -> dict[str, Any]:
        response_path = self.root / "responses" / f"{request_id}.json"
        deadline = time.monotonic() + self.timeout
        while True:
            if response_path.is_file():
                try:
                    return _read_object(response_path, "editor bridge publish receipt")
                except ValidationError:
                    if time.monotonic() >= deadline:
                        raise
            if time.monotonic() >= deadline:
                raise ValidationError("editor bridge did not return a publish receipt before timeout")
            time.sleep(self.poll_interval)


class _LocalEditorAdapter:
    project_extension: str
    writable_fields: frozenset[str]
    writable_kinds: frozenset[str]

    def __init__(self, bridge: LocalFileBridge) -> None:
        self.bridge = bridge
        self._writable_paths_by_project: dict[str, set[str]] = {}

    @property
    def adapter_id(self) -> str:
        return self.bridge.adapter_id

    def profile(self) -> dict[str, Any]:
        return {**self.bridge.profile(), "project_extension": self.project_extension}

    def snapshot(self, draft_path: str | Path) -> dict[str, Any]:
        self._validate_project_path(draft_path)
        snapshot = self.bridge.snapshot(draft_path)
        self._writable_paths_by_project[_path_key(draft_path)] = self._adapter_writable_paths(snapshot)
        return snapshot

    def publish(
        self,
        draft_path: str | Path,
        destination_path: str | Path,
        patches: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        self._validate_project_path(draft_path)
        self._validate_project_path(destination_path)
        source = Path(draft_path)
        if not source.is_file():
            raise ValidationError(f"source editor project not found: {source}")
        source_sha256 = _file_hash(source)
        allowed_paths = self._writable_paths_by_project.get(_path_key(draft_path))
        if allowed_paths is None:
            raise ValidationError("publish requires a fresh adapter snapshot")
        _validate_patches(patches, allowed_paths)
        receipt = self.bridge.publish(draft_path, destination_path, patches)
        destination = Path(destination_path)
        if not destination.is_file():
            raise ValidationError("editor bridge receipt did not create the requested project clone")
        if _file_hash(source) != source_sha256:
            raise ValidationError("editor bridge modified the source project during clone publish")
        return receipt

    def _validate_project_path(self, path: str | Path) -> None:
        if not _path_key(path).endswith(self.project_extension):
            raise ValidationError(f"{self.adapter_id} requires a {self.project_extension} project path")

    def _adapter_writable_paths(self, snapshot: Mapping[str, Any]) -> set[str]:
        paths: set[str] = set()
        for entity in snapshot.get("entities", {}).values():
            if not isinstance(entity, Mapping) or entity.get("kind") not in self.writable_kinds:
                continue
            property_paths = entity.get("property_paths", {})
            if isinstance(property_paths, Mapping):
                paths.update(
                    str(path) for field, path in property_paths.items()
                    if field in self.writable_fields
                )
        return paths


class PremiereAdapter(_LocalEditorAdapter):
    """Premiere CEP or UXP adapter over an explicitly configured local bridge."""

    project_extension = ".prproj"
    writable_fields = frozenset({"timeline_start", "source_in", "source_out", "speed", "transform"})
    writable_kinds = frozenset({"segment"})

    def __init__(self, bridge: LocalFileBridge) -> None:
        if bridge.adapter_id not in {"premiere:cep-local", "premiere:uxp-local"}:
            raise ValidationError(
                "PremiereAdapter requires adapter_id premiere:cep-local or premiere:uxp-local"
            )
        super().__init__(bridge)


class AfterEffectsAdapter(_LocalEditorAdapter):
    """After Effects CEP adapter over the same constrained bridge contract."""

    project_extension = ".aep"
    writable_fields = frozenset({"transform"})
    writable_kinds = frozenset({"composition", "layer"})

    def __init__(self, bridge: LocalFileBridge) -> None:
        if bridge.adapter_id != "after-effects:cep-local":
            raise ValidationError("AfterEffectsAdapter requires adapter_id after-effects:cep-local")
        super().__init__(bridge)


def _validate_normalized_snapshot(snapshot: Mapping[str, Any], adapter_id: str) -> None:
    if snapshot.get("adapter_id") != adapter_id:
        raise ValidationError("normalized editor snapshot belongs to another adapter")
    if not isinstance(snapshot.get("fingerprint"), str) or not snapshot["fingerprint"]:
        raise ValidationError("normalized editor snapshot has no fingerprint")
    entities = snapshot.get("entities")
    if not isinstance(entities, Mapping):
        raise ValidationError("normalized editor snapshot has no entities")
    for entity in entities.values():
        if not isinstance(entity, Mapping):
            raise ValidationError("normalized editor snapshot has an invalid entity")
        paths = entity.get("property_paths", {})
        if not isinstance(paths, Mapping) or any(not isinstance(path, str) or not path.startswith("/") for path in paths.values()):
            raise ValidationError("normalized editor snapshot has invalid property paths")


def _writable_paths(snapshot: Mapping[str, Any]) -> set[str]:
    paths: set[str] = set()
    for entity in snapshot.get("entities", {}).values():
        if isinstance(entity, Mapping) and isinstance(entity.get("property_paths"), Mapping):
            paths.update(str(path) for path in entity["property_paths"].values())
    return paths


def _validate_patches(patches: list[Mapping[str, Any]], allowed_paths: set[str]) -> None:
    for patch in patches:
        if patch.get("op") != "set":
            raise ValidationError("local editor publish accepts only set patches")
        path = patch.get("path")
        if not isinstance(path, str) or path not in allowed_paths:
            raise ValidationError(f"editor patch path is not allowlisted: {path}")


def _validate_receipt(
    receipt: Mapping[str, Any], *, request_id: str, source_path: str | Path,
    destination_path: str | Path, expected_fingerprint: str, expected_adapter_id: str,
    expected_patches: list[Mapping[str, Any]],
) -> None:
    if receipt.get("protocol_version") != LocalFileBridge.protocol_version:
        raise ValidationError("editor bridge receipt has an unsupported protocol version")
    if receipt.get("request_id") != request_id or receipt.get("status") != "published":
        raise ValidationError("editor bridge receipt does not confirm publication")
    if receipt.get("adapter_id") != expected_adapter_id:
        raise ValidationError("editor bridge receipt belongs to another adapter")
    if _path_key(receipt.get("source_path")) != _path_key(source_path):
        raise ValidationError("editor bridge receipt source does not match the publish request")
    if _path_key(receipt.get("destination_path")) != _path_key(destination_path):
        raise ValidationError("editor bridge receipt destination does not match the publish request")
    if receipt.get("source_fingerprint") != expected_fingerprint:
        raise ValidationError("editor bridge receipt was produced from a stale project snapshot")
    if receipt.get("applied_patches") != [dict(patch) for patch in expected_patches]:
        raise ValidationError("editor bridge receipt does not confirm the requested patches")
    if not isinstance(receipt.get("result_fingerprint"), str) or not receipt["result_fingerprint"]:
        raise ValidationError("editor bridge receipt has no resulting project fingerprint")
    result_snapshot = receipt.get("result_snapshot")
    if not isinstance(result_snapshot, Mapping):
        raise ValidationError("editor bridge receipt has no normalized clone snapshot")
    _validate_normalized_snapshot(result_snapshot, expected_adapter_id)
    if result_snapshot.get("fingerprint") != receipt["result_fingerprint"]:
        raise ValidationError("editor bridge receipt clone fingerprint does not match its snapshot")
    result_values = _snapshot_property_values(result_snapshot)
    for patch in expected_patches:
        if not _patch_value_applied(result_values.get(patch["path"]), patch.get("value")):
            raise ValidationError("editor bridge receipt clone snapshot does not contain an applied patch")


def _snapshot_property_values(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for entity in snapshot.get("entities", {}).values():
        if not isinstance(entity, Mapping):
            continue
        paths = entity.get("property_paths", {})
        properties = entity.get("properties", {})
        if not isinstance(paths, Mapping) or not isinstance(properties, Mapping):
            continue
        for field, path in paths.items():
            if isinstance(path, str) and field in properties:
                values[path] = properties[field]
    return values


def _patch_value_applied(actual: Any, expected: Any) -> bool:
    if isinstance(actual, Mapping) and isinstance(expected, Mapping):
        return all(_patch_value_applied(actual.get(key), value) for key, value in expected.items())
    return actual == expected


def _read_object(path: Path, description: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValidationError(f"{description} not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValidationError(f"cannot read {description}: {error}") from error
    if not isinstance(value, dict):
        raise ValidationError(f"{description} must be a JSON object")
    return value


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path)


def _path_key(path: Any) -> str:
    return str(path or "").replace("\\", "/").rstrip("/").lower()


def _file_hash(path: Path) -> str:
    if not path.is_file():
        raise ValidationError(f"editor bridge profile not found: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def panel_tree_hash(root: Path) -> str:
    if not root.is_dir():
        raise ValidationError(f"editor panel root not found: {root}")
    digest = hashlib.sha256()
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix().lower()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdefABCDEF" for character in value)
