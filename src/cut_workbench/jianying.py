from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from .errors import ValidationError


class DraftCodec(Protocol):
    def decode(self, path: Path) -> dict[str, Any]: ...
    def encode(self, value: Mapping[str, Any], path: Path) -> None: ...
    def describe(self) -> Mapping[str, Any]: ...


class PlainJsonCodec:
    """Plain adapter for fixtures and legacy/CapCut drafts."""

    def decode(self, path: Path) -> dict[str, Any]:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValidationError("draft content must be a JSON object")
        return value

    def encode(self, value: Mapping[str, Any], path: Path) -> None:
        Path(path).write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    def describe(self) -> Mapping[str, Any]:
        return {"codec": "plain-json", "writable": True}


class JianyingCodecCommand:
    """Version-local sidecar around jy-draftc and Jianying's installed videoeditor.dll."""

    def __init__(self, executable: Path, install_dir: Path, *, expected_sha256: str) -> None:
        self.executable = Path(executable).resolve()
        self.install_dir = Path(install_dir).resolve()
        if not self.executable.is_file():
            raise ValidationError(f"Jianying codec helper not found: {self.executable}")
        if not (self.install_dir / "videoeditor.dll").is_file():
            raise ValidationError(f"videoeditor.dll not found under: {self.install_dir}")
        if len(expected_sha256) != 64 or any(character not in "0123456789abcdefABCDEF" for character in expected_sha256):
            raise ValidationError("Jianying codec helper requires a valid SHA-256 pin")
        actual = _file_hash(self.executable)
        if actual.lower() != expected_sha256.lower():
            raise ValidationError("Jianying codec helper hash does not match the configured pin")
        self.helper_sha256 = actual
        self.dll_sha256 = _file_hash(self.install_dir / "videoeditor.dll")

    def decode(self, path: Path) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="cut-workbench-jy-codec-") as directory:
            output = Path(directory) / "decoded.json"
            self._run("-d", Path(path), output)
            value = json.loads(output.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValidationError("decoded Jianying content is not an object")
            return value

    def encode(self, value: Mapping[str, Any], path: Path) -> None:
        with tempfile.TemporaryDirectory(prefix="cut-workbench-jy-codec-") as directory:
            plain = Path(directory) / "plain.json"
            plain.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            self._run("-e", plain, Path(path))

    def describe(self) -> Mapping[str, Any]:
        return {
            "codec": "jy-draftc", "writable": True,
            "helper_sha256": self.helper_sha256, "videoeditor_sha256": self.dll_sha256,
            "install_dir": str(self.install_dir),
        }

    def _run(self, mode: str, source: Path, output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="cut-workbench-jy-host-") as host_dir:
            host = Path(host_dir)
            helper = host / self.executable.name
            shutil.copy2(self.executable, helper)
            if _file_hash(helper) != self.helper_sha256:
                raise ValidationError("staged Jianying codec helper no longer matches its SHA-256 pin")
            (host / ".env").write_text(f"JY_INSTALL_DIR={self.install_dir}\n", encoding="utf-8")
            completed = subprocess.run(
                [str(helper), mode, str(source.resolve()), str(output.resolve())],
                cwd=host, text=True, capture_output=True, encoding="utf-8", errors="replace",
                check=False, timeout=120,
            )
        if completed.returncode != 0 or not output.is_file():
            detail = (completed.stderr or completed.stdout).strip()[-2000:]
            raise ValidationError(f"Jianying codec {mode} failed ({completed.returncode}): {detail}")


class JianyingDraftAdapter:
    adapter_id = "jianying:11"

    def __init__(
        self,
        *,
        codec: DraftCodec,
        editor_version: str,
        process_checker: Callable[[], bool] | None = None,
        draft_index_path: Path | None = None,
    ) -> None:
        self.codec = codec
        self.editor_version = editor_version
        self.process_checker = process_checker or _jianying_is_running
        self.draft_index_path = Path(draft_index_path).resolve() if draft_index_path else None

    def profile(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "editor_version": self.editor_version,
            "writable": bool(self.codec.describe().get("writable")),
            "codec": dict(self.codec.describe()),
        }

    def snapshot(self, draft_path: str | Path) -> dict[str, Any]:
        draft_dir = Path(draft_path).resolve()
        content_path = draft_dir / "draft_content.json"
        if not content_path.is_file():
            raise ValidationError(f"draft_content.json not found: {draft_dir}")
        native = self.codec.decode(content_path)
        return _normalize_draft(native, adapter_id=self.adapter_id)

    def publish(
        self,
        draft_path: str | Path,
        destination_path: str | Path,
        patches: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        if self.process_checker():
            raise ValidationError("Jianying is running; close it before publishing a draft clone")
        source = Path(draft_path).resolve()
        destination = Path(destination_path).resolve()
        if not source.is_dir():
            raise ValidationError(f"source draft directory not found: {source}")
        if destination.exists():
            raise ValidationError(f"publish destination already exists: {destination}")
        if source == destination or source in destination.parents:
            raise ValidationError("publish destination must not be inside the source draft")
        shutil.copytree(source, destination)
        registered = False
        index_backup_path: Path | None = None
        clone_draft_id: str | None = None
        try:
            content_path = destination / "draft_content.json"
            native = self.codec.decode(content_path)
            for patch in patches:
                _apply_json_patch(native, patch)
            encoded = destination / ".cut-workbench-content.tmp"
            self.codec.encode(native, encoded)
            encoded_bytes = encoded.read_bytes()
            if self.process_checker():
                raise ValidationError("Jianying started during publish; draft clone was discarded")
            mirrors = _content_mirrors(destination, native.get("id"))
            for mirror in mirrors:
                mirror.parent.mkdir(parents=True, exist_ok=True)
                temporary = mirror.with_suffix(mirror.suffix + ".cut-workbench.tmp")
                temporary.write_bytes(encoded_bytes)
                os.replace(temporary, mirror)
            encoded.unlink(missing_ok=True)
            metadata = _rewrite_clone_metadata(
                codec=self.codec, destination=destination, editor_version=self.editor_version
            )
            clone_draft_id = metadata.get("draft_id") if metadata else None
            if self.draft_index_path and metadata:
                if self.process_checker():
                    raise ValidationError("Jianying started before draft registration; clone was discarded")
                index_backup_path = _register_clone(
                    index_path=self.draft_index_path,
                    source_draft_id=metadata["source_draft_id"],
                    clone_meta=metadata,
                    destination=destination,
                )
                registered = True
        except Exception:
            shutil.rmtree(destination)
            raise
        return {
            "status": "published",
            "source_path": str(source),
            "destination_path": str(destination),
            "patches": [dict(item) for item in patches],
            "content_sha256": _file_hash(destination / "draft_content.json"),
            "mirrors_written": [str(path) for path in mirrors],
            "editor_version": self.editor_version,
            "draft_id": clone_draft_id,
            "registered": registered,
            "index_backup_path": str(index_backup_path) if index_backup_path else None,
        }


def _normalize_draft(native: Mapping[str, Any], *, adapter_id: str) -> dict[str, Any]:
    materials: dict[str, Any] = {}
    native_materials = native.get("materials", {})
    if isinstance(native_materials, Mapping):
        for collection, values in native_materials.items():
            if not isinstance(values, list):
                continue
            kind = _material_kind(collection)
            for item in values:
                if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
                    continue
                materials[item["id"]] = {
                    "external_id": item["id"], "kind": kind,
                    "path": item.get("path") or item.get("lumi_hub_path"),
                    "native": copy.deepcopy(dict(item)),
                }

    tracks: dict[str, Any] = {}
    entities: dict[str, Any] = {}
    for track_index, track in enumerate(native.get("tracks", [])):
        if not isinstance(track, Mapping):
            continue
        track_id = str(track.get("id") or f"track-{track_index}")
        track_kind = str(track.get("type") or "unknown")
        tracks[track_id] = {
            "external_id": track_id, "kind": track_kind, "order": track_index,
            "segment_collection_path": f"/tracks/{track_index}/segments",
            "segment_count": len(track.get("segments", [])) if isinstance(track.get("segments", []), list) else 0,
            "native": copy.deepcopy(dict(track)),
        }
        for segment_index, segment in enumerate(track.get("segments", [])):
            if not isinstance(segment, Mapping):
                continue
            segment_id = str(segment.get("id") or f"{track_id}:segment-{segment_index}")
            target = segment.get("target_timerange") or {}
            source = segment.get("source_timerange") or {}
            source_in = _micros(source.get("start", 0))
            source_duration = _micros(source.get("duration", 0))
            clip = segment.get("clip") if isinstance(segment.get("clip"), Mapping) else {}
            properties = {
                "timeline_start": _micros(target.get("start", 0)),
                "timeline_duration": _micros(target.get("duration", 0)),
                "source_in": source_in,
                "source_out": source_in + source_duration,
                "speed": float(segment.get("speed", 1.0)),
                "transform": copy.deepcopy(clip.get("transform", {})),
            }
            prefix = f"/tracks/{track_index}/segments/{segment_index}"
            entities[segment_id] = {
                "external_id": segment_id,
                "kind": "segment" if track_kind in {"video", "audio"} else track_kind,
                "track_external_id": track_id,
                "material_external_id": segment.get("material_id"),
                "properties": properties,
                "property_paths": {
                    "timeline_start": f"{prefix}/target_timerange/start",
                    "timeline_duration": f"{prefix}/target_timerange/duration",
                    "source_in": f"{prefix}/source_timerange/start",
                    "source_duration": f"{prefix}/source_timerange/duration",
                    "speed": f"{prefix}/speed",
                    "transform": f"{prefix}/clip/transform",
                },
                "entity_path": prefix,
                "native": copy.deepcopy(dict(segment)),
            }
    encoded = json.dumps(native, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    opaque_root = {
        key: copy.deepcopy(value)
        for key, value in native.items()
        if key not in {"tracks", "materials"}
    }
    return {
        "schema_version": 1,
        "adapter_id": adapter_id,
        "draft_id": str(native.get("id") or "unknown"),
        "fingerprint": hashlib.sha256(encoded).hexdigest(),
        "tracks": tracks,
        "materials": materials,
        "entities": entities,
        "native_summary": {"opaque_root": opaque_root},
    }


def _material_kind(collection: str) -> str:
    aliases = {"videos": "video", "audios": "audio", "texts": "text", "stickers": "sticker"}
    return aliases.get(collection, collection.rstrip("s"))


def _micros(value: Any) -> float:
    return float(value or 0) / 1_000_000.0


def _apply_json_patch(root: Any, patch: Mapping[str, Any]) -> None:
    path = patch.get("path")
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValidationError(f"invalid JSON patch path: {path}")
    tokens = [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]
    parent = root
    for token in tokens[:-1]:
        parent = parent[int(token)] if isinstance(parent, list) else parent[token]
    final = tokens[-1]
    operation = patch.get("op")
    if operation == "set":
        value = copy.deepcopy(patch.get("value"))
        if final in {"start", "duration"} and any(name in path for name in ("timerange", "time_range")):
            value = round(float(value) * 1_000_000)
        if isinstance(parent, list):
            parent[int(final)] = value
        else:
            parent[final] = value
    elif operation == "remove":
        if isinstance(parent, list):
            parent.pop(int(final))
        else:
            parent.pop(final, None)
    elif operation == "insert":
        if not isinstance(parent, list):
            raise ValidationError("insert patch requires a list parent")
        parent.insert(int(final), copy.deepcopy(patch.get("value")))
    else:
        raise ValidationError(f"unsupported JSON patch operation: {operation}")


def _content_mirrors(draft: Path, timeline_id: Any) -> list[Path]:
    root_content = draft / "draft_content.json"
    paths = [root_content]
    paths.extend(path for path in (draft / "draft_content.json.bak", draft / "template-2.tmp") if path.is_file())
    if isinstance(timeline_id, str) and timeline_id:
        timeline = draft / "Timelines" / timeline_id
        if timeline.is_dir():
            paths.extend(path for path in [
                timeline / "draft_content.json",
                timeline / "draft_content.json.bak",
                timeline / "template-2.tmp",
            ] if path.is_file())
    return paths


def _rewrite_clone_metadata(
    *, codec: DraftCodec, destination: Path, editor_version: str,
) -> dict[str, Any]:
    meta_path = destination / "draft_meta_info.json"
    if not meta_path.is_file():
        return {}
    meta = codec.decode(meta_path)
    source_draft_id = meta.get("draft_id")
    if not isinstance(source_draft_id, str) or not source_draft_id:
        raise ValidationError("Jianying draft metadata has no draft_id")
    clone_draft_id = str(uuid.uuid4()).upper()
    now = int(time.time() * 1_000_000)
    meta.update({
        "draft_id": clone_draft_id,
        "draft_name": destination.name,
        "draft_fold_path": _jianying_path(destination),
        "draft_root_path": str(destination.parent),
        "tm_draft_create": now,
        "tm_draft_modified": now,
    })
    if "draft_cover" in meta:
        meta["draft_cover"] = _jianying_path(destination / "draft_cover.jpg")
    temporary = destination / ".cut-workbench-meta.tmp"
    codec.encode(meta, temporary)
    os.replace(temporary, meta_path)
    return {
        **meta,
        "source_draft_id": source_draft_id,
        "editor_version": editor_version,
    }


def _register_clone(
    *, index_path: Path, source_draft_id: str, clone_meta: Mapping[str, Any], destination: Path,
) -> Path:
    if not index_path.is_file():
        raise ValidationError(f"Jianying draft index not found: {index_path}")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    stores = index.get("all_draft_store")
    if not isinstance(stores, list):
        raise ValidationError("Jianying draft index has no all_draft_store list")
    source_entry = next((item for item in stores if item.get("draft_id") == source_draft_id), None)
    if not isinstance(source_entry, Mapping):
        raise ValidationError(f"source draft is not registered in Jianying index: {source_draft_id}")
    clone_entry = copy.deepcopy(dict(source_entry))
    clone_entry.update({
        key: copy.deepcopy(value)
        for key, value in clone_meta.items()
        if key in clone_entry and key not in {"source_draft_id", "editor_version"}
    })
    clone_entry.update({
        "draft_id": clone_meta["draft_id"],
        "draft_name": clone_meta["draft_name"],
        "draft_fold_path": _jianying_path(destination),
        "draft_json_file": _jianying_path(destination / "draft_content.json"),
        "draft_root_path": str(destination.parent),
        "draft_cover": _jianying_path(destination / "draft_cover.jpg"),
    })
    stores.append(clone_entry)
    index["draft_ids"] = len(stores)
    backup = index_path.with_name(f"{index_path.name}.cut-workbench-{uuid.uuid4().hex}.bak")
    shutil.copy2(index_path, backup)
    temporary = index_path.with_name(f"{index_path.name}.cut-workbench.tmp")
    temporary.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, index_path)
    return backup


def discover_jianying_draft_index() -> Path | None:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    candidate = (
        Path(local_app_data) / "JianyingPro" / "User Data" / "Projects"
        / "com.lveditor.draft" / "root_meta_info.json"
    )
    return candidate if candidate.is_file() else None


def _jianying_path(path: Path) -> str:
    return str(Path(path).resolve()).replace("\\", "/")


def _jianying_is_running() -> bool:
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq JianyingPro.exe", "/FO", "CSV", "/NH"],
            text=True, capture_output=True, check=False,
        )
    except OSError as error:
        raise ValidationError(f"cannot verify Jianying process state: {error}") from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise ValidationError(f"cannot verify Jianying process state: {detail or completed.returncode}")
    return "JianyingPro.exe" in completed.stdout


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
