from __future__ import annotations

"""Prepare an auditable local import pack and reconcile its Canvas node mappings."""

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Mapping

from .errors import ValidationError


_SAFE_PART = re.compile(r"[^A-Za-z0-9._-]+")


class TapNowAssetStager:
    """Stage exactly the declared Context Pack assets; it never uploads them."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()

    def stage(self, *, project: Mapping[str, Any], context_plan: Mapping[str, Any]) -> dict[str, Any]:
        _validate_plan_project(project, context_plan)
        context_fingerprint = _text(context_plan, "context_fingerprint")
        nodes = context_plan.get("canvas_nodes")
        if not isinstance(nodes, list):
            raise ValidationError("context_plan canvas_nodes must be a list")
        sources = [item for item in nodes if isinstance(item, Mapping) and item.get("kind") == "source-asset"]
        if not sources:
            raise ValidationError("context_plan has no source assets to stage")

        pack_dir = self.root / "tapnow-imports" / context_fingerprint
        assets_dir = pack_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        staged: list[dict[str, Any]] = []
        for order, node in enumerate(sources, start=1):
            artifact = node.get("artifact")
            if not isinstance(artifact, Mapping):
                raise ValidationError("source asset node lacks its artifact reference")
            artifact_id = _text(artifact, "artifact_id")
            source = self._verified_source(artifact)
            role = _primary_role(node.get("roles"))
            destination = assets_dir / f"{order:02d}_{role}_{_safe_name(artifact_id)}{source.suffix.lower()}"
            transfer = _stage_file(source, destination)
            staged.append({
                "order": order, "artifact_id": artifact_id, "roles": list(node.get("roles", [])),
                "source_locator": artifact["locator"], "sha256": artifact["sha256"],
                "staged_locator": str(destination.relative_to(self.root)), "transfer": transfer,
            })

        manifest = {
            "schema_version": 1, "import_id": context_fingerprint,
            "project_id": project["project_id"], "project_revision": project["revision"],
            "context_fingerprint": context_fingerprint, "assets": staged,
            "upload_contract": {
                "status": "prepared_not_uploaded",
                "requires_external_upload_approval": True,
                "required_mapping": "Every staged artifact must be mapped once to a TapNow Canvas node after upload.",
            },
        }
        manifest_path = pack_dir / "asset-manifest.json"
        order_path = pack_dir / "canvas-import-order.md"
        _write_if_equal_or_new(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        _write_if_equal_or_new(order_path, _render_import_order(staged))
        return {
            "import_id": context_fingerprint,
            "status": "prepared_not_uploaded",
            "import_root": str(pack_dir.relative_to(self.root)),
            "manifest_locator": str(manifest_path.relative_to(self.root)),
            "import_order_locator": str(order_path.relative_to(self.root)),
            "assets": staged,
            "next_action": "Obtain explicit external-upload approval, upload these files to TapNow in order, then call tapnow.canvas.reconcile with every returned Canvas node ID.",
        }

    def reconcile(
        self,
        *, project: Mapping[str, Any], context_plan: Mapping[str, Any], import_id: str,
        canvas_url: str, node_mappings: list[Mapping[str, Any]], external_upload_approval: Mapping[str, Any],
    ) -> dict[str, Any]:
        _validate_plan_project(project, context_plan)
        if import_id != context_plan.get("context_fingerprint"):
            raise ValidationError("import_id does not match the context plan")
        approval = _upload_approval(external_upload_approval)
        manifest_path = self.root / "tapnow-imports" / import_id / "asset-manifest.json"
        if not manifest_path.is_file():
            raise ValidationError("TapNow import pack is missing; stage it before reconciliation")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = {item["artifact_id"]: item for item in manifest.get("assets", [])}
        if not isinstance(node_mappings, list) or len(node_mappings) != len(expected):
            raise ValidationError("node_mappings must contain every staged asset exactly once")
        bindings: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in node_mappings:
            if not isinstance(raw, Mapping):
                raise ValidationError("node_mappings must contain objects")
            artifact_id = _text(raw, "artifact_id")
            node_id = _text(raw, "node_id")
            if artifact_id not in expected or artifact_id in seen:
                raise ValidationError("node_mappings contain an unknown or repeated artifact_id")
            seen.add(artifact_id)
            expected_item = expected[artifact_id]
            staged_path = self.root / expected_item["staged_locator"]
            if not staged_path.is_file() or _sha256(staged_path) != expected_item["sha256"]:
                raise ValidationError(f"staged file is missing or changed: {artifact_id}")
            bindings.append({
                "artifact_id": artifact_id, "node_id": node_id, "canvas_url": canvas_url,
                "roles": expected_item["roles"], "sha256": expected_item["sha256"],
                "reference": {
                    "reference_id": artifact_id, "kind": "canvas-node",
                    "locator": f"tapnow://canvas/{_canvas_id(canvas_url)}/node/{node_id}",
                    "role": _primary_role(expected_item["roles"]),
                },
            })
        if set(expected) != seen:
            raise ValidationError("node_mappings must cover every staged asset")
        return {
            "import_id": import_id, "status": "reconciled", "canvas_url": canvas_url,
            "external_upload_approval": approval, "canvas_bindings": bindings,
            "next_action": "Replace local-file references with these canvas-node references when requesting TapNow preview jobs.",
        }

    def _verified_source(self, artifact: Mapping[str, Any]) -> Path:
        locator = _text(artifact, "locator")
        source = Path(locator)
        if not source.is_absolute():
            source = self.root / source
        source = source.resolve()
        try:
            source.relative_to(self.root)
        except ValueError as error:
            raise ValidationError(f"TapNow source artifact must remain inside the Workbench root: {locator}") from error
        if not source.is_file():
            raise ValidationError(f"TapNow source artifact is not a readable file: {locator}")
        if _sha256(source) != _text(artifact, "sha256"):
            raise ValidationError(f"TapNow source artifact hash does not match registration: {artifact['artifact_id']}")
        return source


def _validate_plan_project(project: Mapping[str, Any], context_plan: Mapping[str, Any]) -> None:
    if context_plan.get("project_id") != project.get("project_id") or context_plan.get("project_revision") != project.get("revision"):
        raise ValidationError("context_plan belongs to a different project revision")
    fingerprint = context_plan.get("context_fingerprint")
    if not isinstance(fingerprint, str) or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
        raise ValidationError("context_plan has an invalid context_fingerprint")


def _stage_file(source: Path, destination: Path) -> str:
    if destination.exists():
        if not destination.is_file() or _sha256(destination) != _sha256(source):
            raise ValidationError(f"existing staged path differs from source: {destination}")
        return "existing"
    try:
        os.link(source, destination)
        return "hardlink"
    except OSError:
        shutil.copy2(source, destination)
        return "copy"


def _write_if_equal_or_new(path: Path, contents: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") != contents:
            raise ValidationError(f"existing import pack differs from current context: {path}")
        return
    path.write_text(contents, encoding="utf-8", newline="\n")


def _render_import_order(assets: list[Mapping[str, Any]]) -> str:
    lines = ["# TapNow Canvas 素材导入顺序", "", "此包仅在本机准备，未上传。获得外传批准后，按以下顺序多选上传：", ""]
    for item in assets:
        lines.append(f"{item['order']}. `{item['staged_locator']}` · {item['artifact_id']} · {' / '.join(item['roles'])}")
    lines.extend(["", "上传完成后，记录每个文件对应的 Canvas 节点 ID；不可将未列出的本地文件一并上传。", ""])
    return "\n".join(lines)


def _upload_approval(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError("external_upload_approval is required")
    evidence = value.get("evidence")
    if not isinstance(evidence, list) or not evidence or any(not isinstance(item, str) or not item for item in evidence):
        raise ValidationError("external_upload_approval requires evidence")
    return {"approved_by": _text(value, "approved_by"), "evidence": list(evidence)}


def _primary_role(value: Any) -> str:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) for item in value):
        raise ValidationError("source roles are required")
    return value[0]


def _canvas_id(url: str) -> str:
    value = _text({"canvas_url": url}, "canvas_url")
    return _SAFE_PART.sub("-", value.rstrip("/").rsplit("/", 1)[-1]).strip("-") or "canvas"


def _safe_name(value: str) -> str:
    return _SAFE_PART.sub("-", value).strip("-")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValidationError(f"{key} is required")
    return item.strip()
