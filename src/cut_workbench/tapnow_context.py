from __future__ import annotations

"""Compile approved production context into a human-executable TapNow Canvas plan.

This module deliberately has no browser or TapNow network dependency.  Its seam is
the handoff between the versioned production workflow and the interactive Canvas:
callers provide immutable artifact identifiers plus the structured projection that
the upstream promo workflow already derived from its locked deliveries.
"""

import hashlib
import json
from typing import Any, Mapping

from .errors import ValidationError


_CONTEXT_KINDS = {"video-script", "storyboard", "material-list"}
_ROUTES = {"generative", "human", "local"}
_CAPABILITY_ACTIONS = {
    "image.generate": "generate-image",
    "image.edit": "edit-image",
    "video.generate": "generate-video",
    "video.edit": "edit-video",
    "video.extend": "extend-video",
    "video.retake": "retake-video",
    "video.inpaint": "inpaint-video",
}
_REFERENCE_ROLES = {
    "product-source", "character-source", "style-source", "evidence-source",
    "footage-source", "audio-source", "context-source",
}
_ROLE_ORDER = {
    "product-source": 0, "character-source": 1, "style-source": 2,
    "evidence-source": 3, "footage-source": 4, "audio-source": 5,
    "context-source": 6,
}


class TapNowContextCompiler:
    """Hide Canvas ordering, provenance checks and brief rendering behind one interface."""

    def compile(self, *, project: Mapping[str, Any], upstream: Mapping[str, Any]) -> dict[str, Any]:
        workflow = project.get("production_workflow")
        if not isinstance(workflow, Mapping):
            raise ValidationError("configure the production workflow before compiling TapNow context")
        artifacts = workflow.get("artifacts")
        stages = workflow.get("stages")
        if not isinstance(artifacts, Mapping) or not isinstance(stages, Mapping):
            raise ValidationError("project production workflow is incomplete")

        artifact_ids = _unique_text_list(upstream.get("artifact_ids"), "upstream artifact_ids")
        selected = _selected_artifacts(artifacts, artifact_ids)
        _validate_approved_context(selected, stages)
        campaign = _campaign(upstream.get("campaign"))
        shots = _shots(upstream.get("shots"), artifacts, artifact_ids)

        plan_nodes: list[dict[str, Any]] = []
        global_node_id = "CTX-GLOBAL"
        plan_nodes.append({
            "node_id": global_node_id,
            "kind": "text-context",
            "purpose": "锁定整条作品的受众、平台、核心信息、基调与禁止项",
            "depends_on": [],
            "content": campaign,
        })

        source_nodes: dict[str, str] = {}
        source_artifacts = _source_artifacts_for(shots, artifacts)
        for artifact, roles in source_artifacts:
            node_id = f"SRC-{artifact['artifact_id']}"
            source_nodes[artifact["artifact_id"]] = node_id
            plan_nodes.append({
                "node_id": node_id,
                "kind": "source-asset",
                "purpose": "提供已登记的上游证据或可复用素材；不得被未声明的镜头泛化引用",
                "depends_on": [global_node_id],
                "roles": roles,
                "artifact": _artifact_ref(artifact),
            })

        generation_requests: list[dict[str, Any]] = []
        excluded_shots: list[dict[str, Any]] = []
        generated_node_by_shot: dict[str, str] = {}
        for shot in shots:
            brief_id = f"SHOT-{shot['shot_id']}-BRIEF"
            shot_generation = shot.get("generation") or {}
            dependencies = [global_node_id] + [source_nodes[item] for item in shot["source_artifact_ids"]]
            for dependency_id in shot["depends_on_shot_ids"]:
                dependencies.append(generated_node_by_shot[dependency_id])
            plan_nodes.append({
                "node_id": brief_id,
                "kind": "shot-brief",
                "purpose": shot["purpose"],
                "depends_on": dependencies,
                "content": {
                    "shot_id": shot["shot_id"], "sequence": shot["sequence"],
                    "duration_seconds": shot["duration_seconds"],
                    "visual_direction": shot["visual_direction"],
                    "source_artifact_ids": shot["source_artifact_ids"],
                    "preserve": shot_generation.get("preserve", []),
                    "avoid": shot_generation.get("avoid", []),
                },
            })
            if shot["route"] != "generative":
                excluded_shots.append({
                    "shot_id": shot["shot_id"], "route": shot["route"],
                    "reason": "该镜头已有非生成式生产路线，不能被 TapNow 计划替代",
                })
                continue
            generation = shot["generation"]
            generation_node_id = f"SHOT-{shot['shot_id']}-GENERATE"
            plan_nodes.append({
                "node_id": generation_node_id,
                "kind": "generation-task",
                "purpose": "仅在 TapNow Ask 模式中准备本镜头，等待人工确认后再生成",
                "depends_on": [brief_id],
                "operation": {
                    "capability": generation["capability"],
                    "action": _CAPABILITY_ACTIONS[generation["capability"]],
                    "execution_boundary": "preview",
                    "prompt": generation["prompt"],
                    "output": generation["output"],
                    "preserve": generation["preserve"],
                    "avoid": generation["avoid"],
                    "acceptance_criteria": generation["acceptance_criteria"],
                },
            })
            generated_node_by_shot[shot["shot_id"]] = generation_node_id
            generation_requests.append({
                "shot_id": shot["shot_id"],
                "capability": generation["capability"],
                "prompt": generation["prompt"],
                "references": [
                    {
                        "reference_id": artifact_id,
                        "kind": "local-file",
                        "locator": artifacts[artifact_id]["locator"],
                        "role": shot["reference_roles"][artifact_id],
                    }
                    for artifact_id in shot["source_artifact_ids"]
                ],
                "output": generation["output"],
                "constraints": {
                    "execution_boundary": "preview",
                    "preserve": generation["preserve"], "avoid": generation["avoid"],
                },
                "acceptance_criteria": generation["acceptance_criteria"],
                "handoff": {
                    "brief_node_id": brief_id,
                    "generation_node_id": generation_node_id,
                    "instruction": "在 TapNow Canvas 中创建该节点，先读取实时预估，勿在本步骤开始付费生成。",
                },
            })

        plan = {
            "schema_version": 1,
            "provider_id": "agentic:tapnow",
            "project_id": project["project_id"],
            "project_revision": project["revision"],
            "upstream_artifacts": [_artifact_ref(item) for item in selected],
            "canvas_nodes": plan_nodes,
            "generation_requests": generation_requests,
            "excluded_shots": excluded_shots,
            "execution_rule": "在 TapNow Agent 中按 canvas_nodes 顺序建立上下文；generation_requests 一律从 preview 开始，人工批准后才可创建对应 generate job。",
        }
        plan["context_fingerprint"] = _fingerprint(plan)
        plan["tapnow_agent_brief"] = _render_brief(campaign, plan_nodes, generation_requests, excluded_shots)
        return plan


def _selected_artifacts(artifacts: Mapping[str, Any], artifact_ids: list[str]) -> list[dict[str, Any]]:
    missing = [item for item in artifact_ids if item not in artifacts]
    if missing:
        raise ValidationError("upstream artifact_ids are not registered in this project: " + ", ".join(missing))
    return [dict(artifacts[item]) for item in artifact_ids]


def _validate_approved_context(selected: list[dict[str, Any]], stages: Mapping[str, Any]) -> None:
    kinds = {item["kind"] for item in selected}
    missing = _CONTEXT_KINDS.difference(kinds)
    if missing:
        raise ValidationError("TapNow context requires approved video-script, storyboard and material-list artifacts; missing: " + ", ".join(sorted(missing)))
    for artifact in selected:
        if artifact["kind"] not in _CONTEXT_KINDS:
            continue
        stage = stages.get(artifact["stage_id"])
        submission = stage.get("submission") if isinstance(stage, Mapping) else None
        if not isinstance(stage, Mapping) or stage.get("status") != "approved" or artifact["artifact_id"] not in submission.get("artifact_ids", []):
            raise ValidationError(f"context artifact is not an approved stage output: {artifact['artifact_id']}")


def _campaign(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError("upstream campaign is required")
    result = {
        "audience": _text(value, "audience"),
        "platform": _text(value, "platform"),
        "core_message": _text(value, "core_message"),
        "creative_direction": _text(value, "creative_direction"),
        "prohibitions": _string_list(value.get("prohibitions", []), "campaign prohibitions"),
    }
    return result


def _shots(value: Any, artifacts: Mapping[str, Any], allowed_artifact_ids: list[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValidationError("upstream shots must be a non-empty list")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, Mapping):
            raise ValidationError("upstream shots must contain objects")
        shot_id = _text(raw, "shot_id")
        if shot_id in seen:
            raise ValidationError(f"duplicate shot_id: {shot_id}")
        seen.add(shot_id)
        sequence = raw.get("sequence")
        duration = raw.get("duration_seconds")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise ValidationError(f"shot {shot_id} sequence must be a positive integer")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
            raise ValidationError(f"shot {shot_id} duration_seconds must be positive")
        route = raw.get("route")
        if route not in _ROUTES:
            raise ValidationError(f"shot {shot_id} route must be one of: {', '.join(sorted(_ROUTES))}")
        source_ids = _unique_text_list(raw.get("source_artifact_ids"), f"shot {shot_id} source_artifact_ids")
        unknown = [item for item in source_ids if item not in artifacts]
        if unknown:
            raise ValidationError(f"shot {shot_id} references unknown artifacts: {', '.join(unknown)}")
        roles = raw.get("reference_roles", {})
        if not isinstance(roles, Mapping) or set(roles) != set(source_ids):
            raise ValidationError(f"shot {shot_id} reference_roles must name every source artifact exactly once")
        normalized_roles: dict[str, str] = {}
        for artifact_id in source_ids:
            role = roles[artifact_id]
            if role not in _REFERENCE_ROLES:
                raise ValidationError(f"shot {shot_id} has unsupported reference role: {role}")
            normalized_roles[artifact_id] = role
        depends = _unique_text_list(raw.get("depends_on_shot_ids", []), f"shot {shot_id} depends_on_shot_ids")
        generation: dict[str, Any] | None = None
        if route == "generative":
            generation = _generation(raw.get("generation"), shot_id)
        elif raw.get("generation") is not None:
            raise ValidationError(f"non-generative shot {shot_id} must not carry generation settings")
        result.append({
            "shot_id": shot_id, "sequence": sequence, "duration_seconds": float(duration),
            "purpose": _text(raw, "purpose"), "visual_direction": _text(raw, "visual_direction"),
            "route": route, "source_artifact_ids": source_ids, "reference_roles": normalized_roles,
            "depends_on_shot_ids": depends, "generation": generation,
        })
    result.sort(key=lambda item: item["sequence"])
    if [item["sequence"] for item in result] != list(range(1, len(result) + 1)):
        raise ValidationError("shot sequence must be continuous and start at 1")
    ids = {item["shot_id"] for item in result}
    generative_ids = {item["shot_id"] for item in result if item["route"] == "generative"}
    for shot in result:
        unknown = set(shot["depends_on_shot_ids"]).difference(ids)
        if unknown:
            raise ValidationError(f"shot {shot['shot_id']} depends on unknown shots: {', '.join(sorted(unknown))}")
        if shot["shot_id"] in shot["depends_on_shot_ids"]:
            raise ValidationError(f"shot {shot['shot_id']} may not depend on itself")
        if any(item not in generative_ids for item in shot["depends_on_shot_ids"]):
            raise ValidationError(f"shot {shot['shot_id']} may only depend on generative shot outputs")
        prior = {item["shot_id"] for item in result if item["sequence"] < shot["sequence"]}
        if not set(shot["depends_on_shot_ids"]).issubset(prior):
            raise ValidationError(f"shot {shot['shot_id']} dependencies must precede it")
    return result


def _generation(value: Any, shot_id: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"generative shot {shot_id} requires generation settings")
    capability = _text(value, "capability")
    if capability not in _CAPABILITY_ACTIONS:
        raise ValidationError(f"shot {shot_id} uses unsupported generation capability: {capability}")
    output = value.get("output")
    if not isinstance(output, Mapping) or not output:
        raise ValidationError(f"shot {shot_id} generation output is required")
    return {
        "capability": capability, "prompt": _text(value, "prompt"), "output": dict(output),
        "preserve": _string_list(value.get("preserve", []), f"shot {shot_id} preserve"),
        "avoid": _string_list(value.get("avoid", []), f"shot {shot_id} avoid"),
        "acceptance_criteria": _string_list(value.get("acceptance_criteria", []), f"shot {shot_id} acceptance_criteria"),
    }


def _source_artifacts_for(shots: list[dict[str, Any]], artifacts: Mapping[str, Any]) -> list[tuple[dict[str, Any], list[str]]]:
    roles_by_artifact: dict[str, set[str]] = {}
    for shot in shots:
        for artifact_id in shot["source_artifact_ids"]:
            roles_by_artifact.setdefault(artifact_id, set()).add(shot["reference_roles"][artifact_id])
    return sorted(
        ((dict(artifacts[item]), sorted(roles_by_artifact[item], key=_ROLE_ORDER.__getitem__)) for item in roles_by_artifact),
        key=lambda item: (_ROLE_ORDER[item[1][0]], item[0]["artifact_id"]),
    )


def _artifact_ref(artifact: Mapping[str, Any]) -> dict[str, Any]:
    return {key: artifact[key] for key in ("artifact_id", "stage_id", "kind", "format", "version", "locator", "sha256")}


def _render_brief(campaign: Mapping[str, Any], nodes: list[dict[str, Any]], requests: list[dict[str, Any]], excluded: list[dict[str, Any]]) -> str:
    lines = [
        "# TapNow Canvas 执行简报",
        "",
        "## 全局约束",
        f"- 受众：{campaign['audience']}", f"- 平台：{campaign['platform']}",
        f"- 核心信息：{campaign['core_message']}", f"- 创意基调：{campaign['creative_direction']}",
        f"- 禁止项：{'；'.join(campaign['prohibitions']) or '无'}", "",
        "## Canvas 建立顺序",
    ]
    for index, node in enumerate(nodes, start=1):
        lines.append(f"{index}. `{node['node_id']}` · {node['kind']}：{node['purpose']}")
    lines.extend([
        "", "## TapNow Agent 执行规则",
        "- 已上传的 source-asset 节点是唯一可引用的外部素材。先按上列顺序建立 `CTX-GLOBAL` 与各 `SHOT-*-BRIEF` 文字节点；不得改写其中的锁定信息。",
        "- 建立文字节点后，先汇报节点、引用关系、逐镜执行计划与实时成本预估，等待确认；此阶段不得创建生成节点或开始生成。",
    ])
    for request in requests:
        lines.extend([
            f"- `{request['shot_id']}`：先在 Ask 模式中建立 `{request['handoff']['generation_node_id']}`，",
            f"  提示词：{request['prompt']}",
            f"  保持：{'；'.join(request['constraints']['preserve']) or '无'}；避免：{'；'.join(request['constraints']['avoid']) or '无'}。",
            "  只读取实时成本与候选数，不要生成；待 Workbench 的预算批准后再继续。",
        ])
    if excluded:
        lines.extend(["", "## 不交给 TapNow 的镜头"])
        lines.extend(f"- `{item['shot_id']}`：{item['route']} 路线。{item['reason']}" for item in excluded)
    return "\n".join(lines) + "\n"


def _fingerprint(plan: Mapping[str, Any]) -> str:
    canonical = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValidationError(f"{key} is required")
    return item.strip()


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValidationError(f"{label} must be a list of non-empty strings")
    return [item.strip() for item in value]


def _unique_text_list(value: Any, label: str) -> list[str]:
    items = _string_list(value, label)
    if len(items) != len(set(items)):
        raise ValidationError(f"{label} must not repeat values")
    return items
