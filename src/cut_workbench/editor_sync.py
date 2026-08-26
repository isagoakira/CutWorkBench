from __future__ import annotations

import copy
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Mapping, Protocol

from .errors import ProjectNotFound, ValidationError
from .project_store import ProjectStore


class EditorAdapter(Protocol):
    adapter_id: str
    def profile(self) -> Mapping[str, Any]: ...
    def snapshot(self, draft_path: str | Path) -> Mapping[str, Any]: ...
    def publish(
        self, draft_path: str | Path, destination_path: str | Path, patches: list[Mapping[str, Any]]
    ) -> Mapping[str, Any]: ...


class SyncSessionStore:
    def __init__(self, root: Path) -> None:
        self.sessions_dir = Path(root) / "sync-sessions"

    def create(self, value: Mapping[str, Any]) -> dict[str, Any]:
        session = copy.deepcopy(dict(value))
        session["session_id"] = uuid.uuid4().hex
        self.write(session)
        return session

    def read(self, session_id: str) -> dict[str, Any]:
        _validate_session_id(session_id)
        path = self.sessions_dir / f"{session_id}.json"
        if not path.is_file():
            raise ProjectNotFound(f"sync session not found: {session_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def write(self, session: Mapping[str, Any]) -> None:
        session_id = str(session.get("session_id"))
        _validate_session_id(session_id)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        path = self.sessions_dir / f"{session_id}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(session, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)


class EditorSync:
    """Three-way reconciliation behind four stable user-facing operations."""

    def __init__(self, *, store: ProjectStore, sessions: SyncSessionStore, adapter: EditorAdapter) -> None:
        self.store = store
        self.sessions = sessions
        self.adapter = adapter

    def open(
        self,
        *,
        project_id: str,
        draft_path: str,
        revision: int | None = None,
        bindings: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        project = self.store.read_project(project_id, revision)
        external = dict(self.adapter.snapshot(draft_path))
        resolved = dict(bindings or _auto_bind(project, external))
        _validate_bindings(project, external, resolved)
        return self.sessions.create({
            "schema_version": 1,
            "status": "open",
            "project_id": project_id,
            "base_project_revision": project["revision"],
            "draft_path": draft_path,
            "adapter_profile": dict(self.adapter.profile()),
            "base_external": external,
            "bindings": resolved,
            "latest_plan": None,
            "resolutions": {},
        })

    def preview(self, session_id: str) -> dict[str, Any]:
        session = self.sessions.read(session_id)
        base_project = self.store.read_project(session["project_id"], session["base_project_revision"])
        current_project = self.store.read_project(session["project_id"])
        current_external = dict(self.adapter.snapshot(session["draft_path"]))
        plan = _reconcile(
            base_project=base_project,
            current_project=current_project,
            base_external=session["base_external"],
            current_external=current_external,
            bindings=session["bindings"],
        )
        plan.update(
            session_id=session_id,
            project_id=session["project_id"],
            base_project_revision=session["base_project_revision"],
            current_project_revision=current_project["revision"],
            base_external_fingerprint=session["base_external"]["fingerprint"],
            current_external_fingerprint=current_external["fingerprint"],
        )
        session["latest_plan"] = {**plan, "current_external": current_external}
        session["status"] = "previewed"
        self.sessions.write(session)
        return copy.deepcopy(plan)

    def commit(self, session_id: str, *, resolutions: Mapping[str, str]) -> dict[str, Any]:
        session = self.sessions.read(session_id)
        plan = session.get("latest_plan")
        if not plan:
            raise ValidationError("sync.preview must run before sync.commit")
        resolved = _validate_resolutions(plan["conflicts"], resolutions)
        operations = _human_operations(plan, resolved, adapter_id=self.adapter.adapter_id)
        current = self.store.read_project(session["project_id"])
        if operations:
            current = self.store.apply_plan(
                project_id=session["project_id"],
                expected_revision=current["revision"],
                actor="human:jianying",
                reason=f"import manual edits from sync session {session_id}",
                operations=operations,
                evidence=[
                    f"sync-session:{session_id}",
                    f"external-fingerprint:{plan['current_external_fingerprint']}",
                ],
            )
        session["status"] = "committed"
        session["resolutions"] = resolved
        session["committed_project_revision"] = current["revision"]
        self.sessions.write(session)
        return {
            "status": "committed",
            "session_id": session_id,
            "project_id": session["project_id"],
            "project_revision": current["revision"],
            "operations": operations,
            "resolutions": resolved,
        }

    def publish(self, session_id: str, *, destination_path: str) -> dict[str, Any]:
        session = self.sessions.read(session_id)
        plan = session.get("latest_plan")
        if not plan:
            raise ValidationError("sync.preview must run before sync.publish")
        conflicts = plan["conflicts"]
        resolved = _validate_resolutions(conflicts, session.get("resolutions", {})) if conflicts else {}
        patches = _agent_patches(plan, resolved)
        receipt = dict(self.adapter.publish(session["draft_path"], destination_path, patches))
        session["status"] = "published"
        session["publish_receipt"] = receipt
        self.sessions.write(session)
        return receipt


def _auto_bind(project: Mapping[str, Any], external: Mapping[str, Any]) -> dict[str, str]:
    bindings: dict[str, str] = {}
    sources = project.get("sources", {})
    tracks = project.get("tracks", {})
    for external_id, entity in external.get("entities", {}).items():
        if entity.get("kind") != "segment":
            continue
        material = external.get("materials", {}).get(entity.get("material_external_id"), {})
        locator = _path_key(material.get("path"))
        props = entity.get("properties", {})
        candidates = []
        for stable_id, segment in project.get("segments", {}).items():
            source = sources.get(segment["source_id"], {})
            track = tracks.get(segment["track_id"], {})
            external_track = external.get("tracks", {}).get(entity.get("track_external_id"), {})
            if locator and _path_key(source.get("locator")) != locator:
                continue
            if track.get("kind") != external_track.get("kind"):
                continue
            expected = _segment_properties(segment)
            if all(_same(expected.get(key), props.get(key)) for key in ("timeline_start", "source_in", "source_out", "speed")):
                candidates.append(stable_id)
        if len(candidates) == 1:
            bindings[external_id] = candidates[0]
    return bindings


def _validate_bindings(
    project: Mapping[str, Any], external: Mapping[str, Any], bindings: Mapping[str, str]
) -> None:
    # The first Jianying adapter normalizes editable A/V segments only. Keep the
    # binding contract narrow until caption/control importers have typed writers.
    stable_ids = set(project.get("segments", {}))
    for external_id, stable_id in bindings.items():
        if external_id not in external.get("entities", {}):
            raise ValidationError(f"binding references unknown external entity: {external_id}")
        if stable_id not in stable_ids:
            raise ValidationError(f"binding references unknown stable entity: {stable_id}")
    if len(set(bindings.values())) != len(bindings):
        raise ValidationError("multiple external entities cannot bind to the same stable ID")


def _reconcile(
    *,
    base_project: Mapping[str, Any],
    current_project: Mapping[str, Any],
    base_external: Mapping[str, Any],
    current_external: Mapping[str, Any],
    bindings: Mapping[str, str],
) -> dict[str, Any]:
    changes: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for external_id, stable_id in bindings.items():
        base_ext = base_external.get("entities", {}).get(external_id)
        current_ext = current_external.get("entities", {}).get(external_id)
        base_project_props = _project_entity_properties(base_project, stable_id)
        current_project_props = _project_entity_properties(current_project, stable_id)
        if base_ext is None:
            continue
        if current_ext is None:
            changes.append({
                "kind": "delete", "side": "human", "external_id": external_id,
                "stable_id": stable_id, "field": "__deleted__", "base": base_ext, "value": None,
            })
            continue
        fields = set(base_project_props) | set(current_project_props) | set(base_ext.get("properties", {})) | set(current_ext.get("properties", {}))
        for field in sorted(fields):
            base_agent = base_project_props.get(field)
            agent_value = current_project_props.get(field)
            base_human = base_ext.get("properties", {}).get(field)
            human_value = current_ext.get("properties", {}).get(field)
            agent_changed = not _same(base_agent, agent_value)
            human_changed = not _same(base_human, human_value)
            if agent_changed:
                changes.append({
                    "kind": "field", "side": "agent", "external_id": external_id,
                    "stable_id": stable_id, "field": field, "base": base_agent, "value": agent_value,
                })
            if human_changed:
                changes.append({
                    "kind": "field", "side": "human", "external_id": external_id,
                    "stable_id": stable_id, "field": field, "base": base_human, "value": human_value,
                })
            if agent_changed and human_changed and not _same(agent_value, human_value):
                conflict_id = _conflict_id(stable_id, field)
                conflicts.append({
                    "conflict_id": conflict_id, "stable_id": stable_id, "external_id": external_id,
                    "field": field, "base": base_agent, "agent": agent_value, "human": human_value,
                })

    for external_id in sorted(set(current_external.get("entities", {})) - set(base_external.get("entities", {}))):
        changes.append({
            "kind": "external-add", "side": "human", "external_id": external_id,
            "stable_id": None, "field": "__entity__", "base": None,
            "value": copy.deepcopy(current_external["entities"][external_id]),
        })
    return {"schema_version": 1, "changes": changes, "conflicts": conflicts}


def _human_operations(plan: Mapping[str, Any], resolutions: Mapping[str, str], *, adapter_id: str) -> list[dict[str, Any]]:
    conflicts = {(item["stable_id"], item["field"]): item for item in plan["conflicts"]}
    segment_changes: dict[str, dict[str, Any]] = {}
    operations: list[dict[str, Any]] = []
    current_external = plan["current_external"]
    for change in plan["changes"]:
        if change["side"] != "human":
            continue
        if change["kind"] == "external-add":
            entity = change["value"]
            stable_id = "EXT-JY-" + hashlib.sha256(change["external_id"].encode()).hexdigest()[:12].upper()
            operations.append({
                "op": "import_external_entity", "external_entity_id": stable_id,
                "adapter_id": adapter_id, "external_id": change["external_id"],
                "kind": entity.get("kind", "unknown"), "properties": entity.get("properties", {}),
                "native": entity.get("native", {}),
                "external_fingerprint": current_external["fingerprint"],
            })
            continue
        key = (change["stable_id"], change["field"])
        conflict = conflicts.get(key)
        if conflict and resolutions.get(conflict["conflict_id"]) != "human":
            continue
        if change["field"] == "__deleted__":
            operations.append({"op": "remove_entity", "stable_id": change["stable_id"]})
            continue
        segment_changes.setdefault(change["stable_id"], {})[change["field"]] = change["value"]
    for stable_id, changes in segment_changes.items():
        operations.append({"op": "update_segment", "segment_id": stable_id, "changes": changes})
    return operations


def _agent_patches(plan: Mapping[str, Any], resolutions: Mapping[str, str]) -> list[dict[str, Any]]:
    conflicts = {(item["stable_id"], item["field"]): item for item in plan["conflicts"]}
    external = plan["current_external"]
    patches: list[dict[str, Any]] = []
    accepted: dict[tuple[str, str], dict[str, Any]] = {}
    for change in plan["changes"]:
        if change["side"] != "agent" or change["kind"] != "field":
            continue
        conflict = conflicts.get((change["stable_id"], change["field"]))
        if conflict and resolutions.get(conflict["conflict_id"]) != "agent":
            continue
        accepted[(change["external_id"], change["field"])] = change

    source_ranges: set[str] = set()
    for (external_id, field), change in accepted.items():
        entity = external["entities"].get(change["external_id"], {})
        if field in {"source_in", "source_out"}:
            source_ranges.add(external_id)
        if field == "source_out":
            continue
        path = entity.get("property_paths", {}).get(change["field"])
        if not path:
            raise ValidationError(
                f"Jianying adapter cannot publish field {change['field']} for {change['stable_id']}"
            )
        patches.append({"op": "set", "path": path, "value": change["value"], "stable_id": change["stable_id"]})

    # Jianying stores source start + duration, while the workbench exposes the
    # safer source_in/source_out pair. Recalculate duration whenever either end
    # changes so the other end is not shifted accidentally.
    for external_id in sorted(source_ranges):
        entity = external["entities"].get(external_id, {})
        paths = entity.get("property_paths", {})
        duration_path = paths.get("source_duration")
        if not duration_path:
            stable_id = next(
                change["stable_id"] for (item_id, _), change in accepted.items() if item_id == external_id
            )
            raise ValidationError(f"Jianying adapter cannot publish source range for {stable_id}")
        properties = entity.get("properties", {})
        source_in_change = accepted.get((external_id, "source_in"))
        source_out_change = accepted.get((external_id, "source_out"))
        source_in = source_in_change["value"] if source_in_change else properties.get("source_in")
        source_out = source_out_change["value"] if source_out_change else properties.get("source_out")
        if not isinstance(source_in, (int, float)) or not isinstance(source_out, (int, float)) or source_out <= source_in:
            raise ValidationError(f"invalid source range for external entity {external_id}")
        stable_id = (source_out_change or source_in_change)["stable_id"]
        patches.append({
            "op": "set", "path": duration_path, "value": float(source_out) - float(source_in),
            "stable_id": stable_id,
        })
    return patches


def _validate_resolutions(conflicts: list[Mapping[str, Any]], resolutions: Mapping[str, str]) -> dict[str, str]:
    result = dict(resolutions)
    for conflict in conflicts:
        value = result.get(conflict["conflict_id"])
        if value not in {"human", "agent"}:
            raise ValidationError(f"conflict requires human/agent resolution: {conflict['conflict_id']}")
    return result


def _project_entity_properties(project: Mapping[str, Any], stable_id: str) -> dict[str, Any]:
    if stable_id in project.get("segments", {}):
        return _segment_properties(project["segments"][stable_id])
    if stable_id in project.get("captions", {}):
        item = project["captions"][stable_id]
        return {key: copy.deepcopy(item.get(key)) for key in ("start", "end", "text", "style")}
    if stable_id in project.get("controls", {}):
        item = project["controls"][stable_id]
        return {key: copy.deepcopy(item.get(key)) for key in ("active_range", "properties", "keyframes", "enabled")}
    return {}


def _segment_properties(segment: Mapping[str, Any]) -> dict[str, Any]:
    duration = (float(segment["source_out"]) - float(segment["source_in"])) / float(segment.get("speed", 1))
    return {
        "timeline_start": float(segment["timeline_start"]),
        "timeline_duration": duration,
        "source_in": float(segment["source_in"]),
        "source_out": float(segment["source_out"]),
        "speed": float(segment.get("speed", 1)),
        "transform": copy.deepcopy(segment.get("transform", {})),
    }


def _same(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) < 1e-6
    return left == right


def _path_key(value: Any) -> str:
    return str(value or "").replace("\\", "/").lower()


def _conflict_id(stable_id: str, field: str) -> str:
    return "CONFLICT-" + hashlib.sha256(f"{stable_id}:{field}".encode()).hexdigest()[:12].upper()


def _validate_session_id(value: str) -> None:
    if len(value) != 32 or any(character not in "0123456789abcdef" for character in value):
        raise ValidationError("session_id must be a 32-character hexadecimal identifier")
