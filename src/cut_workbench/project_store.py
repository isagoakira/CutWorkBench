from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .errors import ProjectNotFound, RevisionConflict, ValidationError


Project = dict[str, Any]
Operation = Mapping[str, Any]


class ProjectStore:
    """Immutable project snapshots behind one transactional editing interface."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.projects_dir = self.root / "projects"

    def create_project(
        self,
        *,
        project_id: str,
        title: str,
        canvas: Mapping[str, Any],
        editor_adapter: str = "unassigned",
    ) -> Project:
        if not project_id or any(part in project_id for part in ("/", "\\", "..")):
            raise ValidationError("project_id must be a non-empty path-safe identifier")
        project_dir = self._project_dir(project_id)
        if project_dir.exists():
            raise ValidationError(f"project already exists: {project_id}")
        project: Project = {
            "schema_version": 1,
            "project_id": project_id,
            "title": title,
            "revision": 1,
            "parent_revision": None,
            "status": "audit",
            "canvas": dict(canvas),
            "editor_adapter": editor_adapter,
            "sources": {},
            "tracks": {},
            "segments": {},
            "controls": {},
            "captions": {},
            "decisions": {},
            "capability_downgrades": {},
            "verification": [],
        }
        self._validate_project(project)
        self._commit(project, actor="system", reason="create project", operations=[])
        return copy.deepcopy(project)

    def read_project(self, project_id: str, revision: int | None = None) -> Project:
        project_dir = self._project_dir(project_id)
        if revision is None:
            current_path = project_dir / "CURRENT"
            if not current_path.exists():
                raise ProjectNotFound(f"project not found: {project_id}")
            revision = int(current_path.read_text(encoding="utf-8").strip())
        revision_path = self._revision_path(project_id, revision)
        if not revision_path.exists():
            raise ProjectNotFound(f"project revision not found: {project_id}@{revision}")
        return json.loads(revision_path.read_text(encoding="utf-8"))

    def apply_plan(
        self,
        *,
        project_id: str,
        expected_revision: int,
        actor: str,
        reason: str,
        operations: Iterable[Operation],
    ) -> Project:
        current = self.read_project(project_id)
        if current["revision"] != expected_revision:
            raise RevisionConflict(
                f"expected revision {expected_revision}, current revision is {current['revision']}"
            )
        if current["status"] == "handed_off":
            raise ValidationError("handed-off projects are immutable; create a branch before editing")

        planned = [dict(operation) for operation in operations]
        updated = copy.deepcopy(current)
        for operation in planned:
            self._apply_operation(updated, operation)
        updated["parent_revision"] = current["revision"]
        updated["revision"] = current["revision"] + 1
        self._validate_project(updated)
        self._commit(updated, actor=actor, reason=reason, operations=planned)
        return copy.deepcopy(updated)

    def branch_project(
        self,
        *,
        source_project_id: str,
        new_project_id: str,
        revision: int | None = None,
        title: str | None = None,
    ) -> Project:
        source = self.read_project(source_project_id, revision=revision)
        branched = copy.deepcopy(source)
        branched.update(
            project_id=new_project_id,
            title=title or f"{source['title']} (branch)",
            revision=1,
            parent_revision=None,
            status="assembly",
            branched_from={"project_id": source_project_id, "revision": source["revision"]},
        )
        if self._project_dir(new_project_id).exists():
            raise ValidationError(f"project already exists: {new_project_id}")
        self._validate_project(branched)
        self._commit(branched, actor="system", reason="branch project", operations=[])
        return copy.deepcopy(branched)

    def _apply_operation(self, project: Project, operation: Operation) -> None:
        op = operation.get("op")
        handler = getattr(self, f"_op_{op}", None)
        if handler is None:
            raise ValidationError(f"unsupported operation: {op}")
        handler(project, operation)

    @staticmethod
    def _op_register_source(project: Project, operation: Operation) -> None:
        source_id = _required_id(operation, "source_id")
        _ensure_unique(project, source_id)
        locator = operation.get("locator")
        if not locator:
            raise ValidationError("source locator is required")
        project["sources"][source_id] = {
            "source_id": source_id,
            "locator": locator,
            "sha256": operation.get("sha256"),
            "media_profile": operation.get("media_profile", {}),
            "original": True,
        }

    @staticmethod
    def _op_add_track(project: Project, operation: Operation) -> None:
        track_id = _required_id(operation, "track_id")
        _ensure_unique(project, track_id)
        kind = operation.get("kind")
        if kind not in {"video", "audio", "caption", "effect", "sticker"}:
            raise ValidationError(f"unsupported track kind: {kind}")
        project["tracks"][track_id] = {
            "track_id": track_id,
            "kind": kind,
            "purpose": operation.get("purpose") or "unspecified",
            "enabled": True,
        }

    @staticmethod
    def _op_add_segment(project: Project, operation: Operation) -> None:
        segment_id = _required_id(operation, "segment_id")
        _ensure_unique(project, segment_id)
        source_id = operation.get("source_id")
        track_id = operation.get("track_id")
        if source_id not in project["sources"]:
            raise ValidationError(f"unknown source: {source_id}")
        if track_id not in project["tracks"]:
            raise ValidationError(f"unknown track: {track_id}")
        source_in = _number(operation, "source_in")
        source_out = _number(operation, "source_out")
        if source_in < 0 or source_out <= source_in:
            raise ValidationError("segment source range must be positive and non-empty")
        project["segments"][segment_id] = {
            "segment_id": segment_id,
            "source_id": source_id,
            "track_id": track_id,
            "source_in": source_in,
            "source_out": source_out,
            "timeline_start": _number(operation, "timeline_start"),
            "transform": dict(operation.get("transform", {})),
            "speed": float(operation.get("speed", 1.0)),
            "role": operation.get("role", "source-derived"),
        }

    @staticmethod
    def _op_add_control(project: Project, operation: Operation) -> None:
        control_id = _required_id(operation, "control_id")
        _ensure_unique(project, control_id)
        target_segment_id = operation.get("target_segment_id")
        track_id = operation.get("track_id")
        if target_segment_id not in project["segments"]:
            raise ValidationError(f"unknown target segment: {target_segment_id}")
        if track_id not in project["tracks"]:
            raise ValidationError(f"unknown control track: {track_id}")
        kind = operation.get("kind")
        target_track_id = project["segments"][target_segment_id]["track_id"]
        if kind in {"mask", "mask_blur", "transform", "keyframes"} and target_track_id != track_id:
            raise ValidationError(f"{kind} control must live on its target segment track")
        if kind == "effect" and project["tracks"][track_id]["kind"] != "effect":
            raise ValidationError("effect control must live on an effect track")
        editable = bool(operation.get("editable", True))
        baked = bool(operation.get("baked", False))
        if baked or not editable:
            exception_id = operation.get("approved_exception_id")
            exception = project["capability_downgrades"].get(exception_id)
            if not exception or not exception.get("approved"):
                raise ValidationError("baked control requires an approved exception")
        active_range = dict(operation.get("active_range", {}))
        if active_range:
            start = active_range.get("start")
            end = active_range.get("end")
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end <= start:
                raise ValidationError("control active range must be numeric and non-empty")
        properties = operation.get("properties")
        if not isinstance(properties, Mapping):
            raise ValidationError("control properties must be an object")
        project["controls"][control_id] = {
            "control_id": control_id,
            "target_segment_id": target_segment_id,
            "track_id": track_id,
            "kind": kind,
            "active_range": active_range,
            "properties": dict(properties),
            "keyframes": list(operation.get("keyframes", [])),
            "editable": editable,
            "baked": baked,
            "approved_exception_id": operation.get("approved_exception_id"),
            "enabled": True,
        }

    @staticmethod
    def _op_add_caption(project: Project, operation: Operation) -> None:
        caption_id = _required_id(operation, "caption_id")
        _ensure_unique(project, caption_id)
        track_id = operation.get("track_id")
        if track_id not in project["tracks"] or project["tracks"][track_id]["kind"] != "caption":
            raise ValidationError("caption must target a caption track")
        start = _number(operation, "start")
        end = _number(operation, "end")
        if start < 0 or end <= start:
            raise ValidationError("caption range must be positive and non-empty")
        text = operation.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValidationError("caption text is required")
        for caption in project["captions"].values():
            if caption["track_id"] == track_id and start < caption["end"] and end > caption["start"]:
                raise ValidationError(f"caption overlaps {caption['caption_id']}")
        project["captions"][caption_id] = {
            "caption_id": caption_id,
            "track_id": track_id,
            "start": start,
            "end": end,
            "text": text,
            "style": dict(operation.get("style", {})),
            "speech_evidence": operation.get("speech_evidence"),
            "visual_scene": operation.get("visual_scene"),
            "intended_gap_after": operation.get("intended_gap_after"),
        }

    @staticmethod
    def _op_record_decision(project: Project, operation: Operation) -> None:
        decision_id = _required_id(operation, "decision_id")
        _ensure_unique(project, decision_id)
        kind = operation.get("kind")
        summary = operation.get("summary")
        evidence = operation.get("evidence", [])
        if not isinstance(kind, str) or not kind:
            raise ValidationError("decision kind is required")
        if not isinstance(summary, str) or not summary:
            raise ValidationError("decision summary is required")
        if not isinstance(evidence, list):
            raise ValidationError("decision evidence must be a list")
        source_id = operation.get("source_id")
        if source_id is not None and source_id not in project["sources"]:
            raise ValidationError(f"unknown decision source: {source_id}")
        project["decisions"][decision_id] = {
            "decision_id": decision_id,
            "kind": kind,
            "summary": summary,
            "source_id": source_id,
            "evidence": list(evidence),
            "data": dict(operation.get("data", {})),
        }

    @staticmethod
    def _op_record_downgrade(project: Project, operation: Operation) -> None:
        exception_id = _required_id(operation, "exception_id")
        _ensure_unique(project, exception_id)
        approved = bool(operation.get("approved", False))
        if approved and not operation.get("approved_by"):
            raise ValidationError("approved downgrade requires approved_by")
        project["capability_downgrades"][exception_id] = {
            "exception_id": exception_id,
            "capability": operation.get("capability"),
            "reason": operation.get("reason"),
            "fallback": operation.get("fallback"),
            "approved": approved,
            "approved_by": operation.get("approved_by"),
        }

    @staticmethod
    def _op_record_verification(project: Project, operation: Operation) -> None:
        verification_id = _required_id(operation, "verification_id")
        if any(item["verification_id"] == verification_id for item in project["verification"]):
            raise ValidationError(f"stable id already exists: {verification_id}")
        kind = operation.get("kind")
        if kind not in {"structural", "visual", "semantic", "render"}:
            raise ValidationError(f"unsupported verification kind: {kind}")
        evidence = operation.get("evidence", [])
        if not isinstance(evidence, list):
            raise ValidationError("verification evidence must be a list")
        project["verification"].append({
            "verification_id": verification_id,
            "kind": kind,
            "verifier": operation.get("verifier"),
            "passed": bool(operation.get("passed", False)),
            "evidence": list(evidence),
            "notes": operation.get("notes", ""),
        })

    @staticmethod
    def _op_set_status(project: Project, operation: Operation) -> None:
        status = operation.get("status")
        if status not in {"audit", "rough-cut", "assembly", "review", "delivered", "handed_off"}:
            raise ValidationError(f"unsupported project status: {status}")
        if status in {"delivered", "handed_off"}:
            from .verification import verify_project

            report = verify_project(project)
            if not report["passed"]:
                codes = ", ".join(issue["code"] for issue in report["issues"])
                raise ValidationError(f"protocol gate failed before {status}: {codes}")
        project["status"] = status

    @staticmethod
    def _validate_project(project: Project) -> None:
        canvas = project.get("canvas", {})
        for key in ("width", "height", "fps"):
            if not isinstance(canvas.get(key), (int, float)) or canvas[key] <= 0:
                raise ValidationError(f"canvas.{key} must be positive")

    def _commit(
        self,
        project: Project,
        *,
        actor: str,
        reason: str,
        operations: list[dict[str, Any]],
    ) -> None:
        project_dir = self._project_dir(project["project_id"])
        revisions_dir = project_dir / "revisions"
        revisions_dir.mkdir(parents=True, exist_ok=True)
        revision_path = self._revision_path(project["project_id"], project["revision"])
        if revision_path.exists():
            raise RevisionConflict(f"revision already exists: {revision_path.name}")
        _atomic_write(revision_path, json.dumps(project, indent=2, ensure_ascii=False) + "\n")
        _atomic_write(project_dir / "CURRENT", f"{project['revision']}\n")
        event = {
            "revision": project["revision"],
            "parent_revision": project.get("parent_revision"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "reason": reason,
            "operations": operations,
        }
        with (project_dir / "journal.jsonl").open("a", encoding="utf-8", newline="\n") as journal:
            journal.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _project_dir(self, project_id: str) -> Path:
        return self.projects_dir / project_id

    def _revision_path(self, project_id: str, revision: int) -> Path:
        return self._project_dir(project_id) / "revisions" / f"rev-{revision:06d}.json"


def _required_id(operation: Operation, key: str) -> str:
    value = operation.get(key)
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{key} is required")
    return value


def _ensure_unique(project: Project, stable_id: str) -> None:
    collections = (
        "sources", "tracks", "segments", "controls", "captions", "decisions",
        "capability_downgrades",
    )
    if any(stable_id in project[name] for name in collections):
        raise ValidationError(f"stable id already exists: {stable_id}")


def _number(operation: Operation, key: str) -> float:
    value = operation.get(key)
    if not isinstance(value, (int, float)):
        raise ValidationError(f"{key} must be numeric")
    return float(value)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temporary, path)
