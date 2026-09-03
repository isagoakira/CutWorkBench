from __future__ import annotations

import copy
import re
from typing import Any, Mapping

from .errors import ValidationError
from .stable_ids import stable_id_exists


PROTOCOL_ID = "video-production-v1"
PRODUCTION_OPERATION_NAMES = {
    "configure_production_workflow",
    "register_workflow_artifact",
    "submit_workflow_stage",
    "approve_workflow_stage",
}


def _deliverable(kind: str, formats: list[str], *, minimum: int = 1, optional: bool = False) -> dict[str, Any]:
    return {"kind": kind, "formats": formats, "minimum": 0 if optional else minimum, "optional": optional}


_STAGES: list[dict[str, Any]] = [
    {
        "stage_id": "01-script", "number": 1, "name": "脚本", "directory": "01_脚本",
        "depends_on": [], "required_inputs": {},
        "deliverables": [
            _deliverable("video-script", ["md", "docx"]),
            _deliverable("script-change-log", ["xlsx"], optional=True),
        ],
        "acceptance": [
            "全片逻辑完整，开头、主体、结尾明确",
            "每一段均能判断拍什么、说什么、给观众什么信息",
            "总时长预估合理",
            "未确定内容明确标注为待确认",
        ],
        "content_requirements": ["标题、主题、受众和目标时长", "章节目的、核心信息和预计时长", "画面大意与音画角色标记", "后期配音、动画、屏录和资料画面预留"],
    },
    {
        "stage_id": "02-storyboard", "number": 2, "name": "分镜稿", "directory": "02_分镜",
        "depends_on": ["01-script"], "required_inputs": {"01-script": ["video-script"]},
        "deliverables": [
            _deliverable("storyboard", ["xlsx", "pdf"]),
            _deliverable("camera-diagram", ["png"], optional=True),
            _deliverable("shoot-schedule", ["xlsx"], optional=True),
        ],
        "acceptance": [
            "每个脚本段落均有对应镜头方案",
            "明确主体、角度、机位数和补充镜头需求",
            "关键表述有主镜头和足够的 B-roll 支撑",
            "后期配音所需节奏窗口已明确",
        ],
        "content_requirements": ["唯一镜号与脚本段落", "预计时长、画面内容、景别角度和机位", "音频与后期要求", "素材状态"],
    },
    {
        "stage_id": "03-material-list", "number": 3, "name": "素材清单", "directory": "03_素材清单",
        "depends_on": ["02-storyboard"], "required_inputs": {"02-storyboard": ["storyboard"]},
        "deliverables": [
            _deliverable("material-list", ["xlsx"]),
            _deliverable("naming-convention", ["md"]),
            _deliverable("missing-material-tracker", ["xlsx"], optional=True),
        ],
        "acceptance": [
            "所有必须镜头均有可获得的素材来源",
            "每个场景有主画面与补充画面",
            "录制范围明确且可剪辑",
            "版权、授权或素材来源可追溯",
        ],
        "content_requirements": ["素材编号与场景章节", "内容、拍摄范围和重点", "机位角度与音频需求", "来源、优先级和状态"],
    },
    {
        "stage_id": "04-recording", "number": 4, "name": "素材录制与整理", "directory": "04_原始素材",
        "depends_on": ["03-material-list"], "required_inputs": {"03-material-list": ["material-list", "naming-convention"]},
        "deliverables": [
            _deliverable("raw-media", ["directory", "mp4", "mov", "mxf", "wav", "png", "jpg"]),
            _deliverable("asset-index", ["xlsx"]),
            _deliverable("shoot-log", ["md"]),
            _deliverable("reshoot-list", ["xlsx"]),
        ],
        "acceptance": [
            "素材命名与分镜编号对应",
            "关键内容没有缺主镜头、特写或过渡镜头",
            "原始文件未被覆盖且具备备份",
            "补拍问题已形成可执行清单",
        ],
        "content_requirements": ["关键动作前后保留 3–5 秒", "主镜头与补充角度", "统一屏录分辨率和帧率", "可用性分级与拍摄日志"],
    },
    {
        "stage_id": "05-rough-cut", "number": 5, "name": "视频粗剪", "directory": "05_视频粗剪",
        "depends_on": ["01-script", "02-storyboard", "04-recording"],
        "required_inputs": {"01-script": ["video-script"], "02-storyboard": ["storyboard"], "04-recording": ["raw-media", "asset-index"]},
        "deliverables": [
            _deliverable("rough-cut-review", ["mp4"]),
            _deliverable("editor-project", ["directory", "prproj", "aep", "jianying"]),
            _deliverable("rough-cut-issues", ["md"]),
            _deliverable("missing-material-tracker", ["xlsx"]),
        ],
        "acceptance": [
            "不看脚本也能理解视频基本内容",
            "所有关键场景已有对应画面",
            "补拍、补屏录、补动画或补配音项目可逐项执行",
            "时间线与分镜基本一致且变更有记录",
        ],
        "content_requirements": ["按脚本和分镜排列", "短块和清晰标签", "配音窗口标记", "节奏、断裂、缺失和补拍问题"],
    },
    {
        "stage_id": "06-voice", "number": 6, "name": "口播稿与声音录制", "directory": "06_口播与音频",
        "depends_on": ["01-script", "05-rough-cut"],
        "required_inputs": {"01-script": ["video-script"], "05-rough-cut": ["rough-cut-review", "rough-cut-issues"]},
        "deliverables": [
            _deliverable("speech-script", ["md", "docx"]),
            _deliverable("raw-voice", ["directory", "wav", "flac"]),
            _deliverable("edited-voice", ["directory", "wav", "flac"]),
            _deliverable("speech-index", ["xlsx"]),
        ],
        "acceptance": [
            "所有需要表达的信息都有对应音轨",
            "单句可独立替换且不破坏整段音频",
            "人声清晰、响度基本一致且无明显噪声",
            "口播时长与视频预留窗口基本匹配",
        ],
        "content_requirements": ["说话人和对应章节镜号", "一句或一意群一行", "语气、停顿、重音和情绪", "旁白、同期声、AI 配音和补录类型"],
    },
    {
        "stage_id": "07-fine-cut", "number": 7, "name": "视频精剪", "directory": "07_视频精剪",
        "depends_on": ["02-storyboard", "04-recording", "05-rough-cut", "06-voice"],
        "required_inputs": {"02-storyboard": ["storyboard"], "04-recording": ["raw-media"], "05-rough-cut": ["editor-project"], "06-voice": ["edited-voice"]},
        "deliverables": [
            _deliverable("fine-cut-review", ["mp4"]),
            _deliverable("editor-project", ["directory", "prproj", "aep", "jianying"]),
            _deliverable("effects-list", ["xlsx"]),
            _deliverable("pending-voiceover", ["md"]),
        ],
        "acceptance": [
            "观看体验流畅且信息重点清晰",
            "画面变化与口播节奏匹配",
            "配音窗口自然且音画互不挤压",
            "所有后期待办集中在清单中",
        ],
        "content_requirements": ["叙事顺序和信息密度", "调速、转场、标注、动画和基础调色", "自然配音窗口", "带时间码审片版和集中待办"],
    },
    {
        "stage_id": "08-subtitles", "number": 8, "name": "SRT 字幕", "directory": "08_字幕",
        "depends_on": ["06-voice", "07-fine-cut"],
        "required_inputs": {"06-voice": ["speech-script", "edited-voice"], "07-fine-cut": ["fine-cut-review"]},
        "deliverables": [
            _deliverable("master-subtitle", ["srt"]),
            _deliverable("styled-subtitle", ["ass"], optional=True),
            _deliverable("subtitle-proof", ["docx"], optional=True),
        ],
        "acceptance": [
            "字幕出现与消失时机准确",
            "全片无漏错字、重叠、倒序或超长停留",
            "字幕文本与最终人声一致",
            "文件编码与目标平台兼容（默认 UTF-8）",
        ],
        "content_requirements": ["以最终听到音轨为准", "覆盖口播、旁白和关键配音", "一条字幕一个完整语义", "术语、产品名、数字和英文格式统一"],
    },
    {
        "stage_id": "09-final", "number": 9, "name": "配音补充与最终微调", "directory": "09_终剪与发布",
        "depends_on": ["07-fine-cut", "08-subtitles"],
        "required_inputs": {"07-fine-cut": ["fine-cut-review", "editor-project", "pending-voiceover"], "08-subtitles": ["master-subtitle"]},
        "deliverables": [
            _deliverable("supplemental-voice", ["directory", "wav", "flac"], optional=True),
            _deliverable("final-master", ["mp4"]),
            _deliverable("release-landscape", ["mp4"]),
            _deliverable("release-vertical", ["mp4"]),
            _deliverable("final-subtitle", ["srt"]),
            _deliverable("delivery-notes", ["md"]),
        ],
        "acceptance": [
            "画面、口播、配音、音乐、字幕完全同步",
            "所有交付版本来自同一已锁定终剪工程",
            "工程、原始素材、音频、字幕和成片可回溯",
            "平台所需比例、码率、封面、标题和字幕版本齐全",
        ],
        "content_requirements": ["配音优先的画面窗口调整", "不破坏动作、屏录和音乐的调速", "音频替换后的字幕复核", "片尾、封面、版权、音乐授权和导出规格"],
    },
]

_CONTRACTS = {stage["stage_id"]: stage for stage in _STAGES}
_RAW_NAMING_KINDS = {"raw-media", "supplemental-voice"}


def production_contract() -> dict[str, Any]:
    return {
        "protocol_id": PROTOCOL_ID,
        "principle": "每一阶段交付可直接供下一阶段使用的文件，并通过明确验收后再放行。",
        "artifact_naming": "阶段_内容_v版本号_日期",
        "stages": copy.deepcopy(_STAGES),
    }


def apply_production_operation(project: dict[str, Any], operation: Mapping[str, Any]) -> None:
    op = operation.get("op")
    if op == "configure_production_workflow":
        _configure(project, operation)
    elif op == "register_workflow_artifact":
        _register_artifact(project, operation)
    elif op == "submit_workflow_stage":
        _submit_stage(project, operation)
    elif op == "approve_workflow_stage":
        _approve_stage(project, operation)
    else:
        raise ValidationError(f"unsupported production workflow operation: {op}")


def production_status(project: Mapping[str, Any]) -> dict[str, Any]:
    workflow = project.get("production_workflow")
    if not workflow:
        return {"configured": False, "protocol_id": PROTOCOL_ID, "stages": []}
    stages = []
    for contract in _STAGES:
        state = workflow["stages"][contract["stage_id"]]
        blockers = [dep for dep in contract["depends_on"] if workflow["stages"][dep]["status"] != "approved"]
        stages.append({
            "stage_id": contract["stage_id"], "name": contract["name"], "status": state["status"],
            "ready": not blockers and state["status"] in {"not_started", "in_progress", "stale"},
            "blockers": blockers, "artifact_count": len(state["artifact_ids"]),
            "stale_due_to": list(state["stale_due_to"]),
        })
    next_stage = next((item["stage_id"] for item in stages if item["ready"]), None)
    return {"configured": True, "protocol_id": workflow["protocol_id"], "next_stage": next_stage, "stages": stages}


def validate_production_workflow(project: Mapping[str, Any]) -> None:
    workflow = project.get("production_workflow")
    if workflow is None:
        return
    if not isinstance(workflow, Mapping) or workflow.get("protocol_id") != PROTOCOL_ID:
        raise ValidationError("unsupported production workflow protocol")
    if set(workflow.get("stages", {})) != set(_CONTRACTS):
        raise ValidationError("production workflow must contain the canonical nine stages")
    artifacts = workflow.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise ValidationError("production workflow artifacts must be an object")
    for artifact_id, artifact in artifacts.items():
        if artifact.get("artifact_id") != artifact_id or artifact.get("stage_id") not in _CONTRACTS:
            raise ValidationError(f"invalid workflow artifact: {artifact_id}")
        if re.fullmatch(r"[0-9a-fA-F]{64}", str(artifact.get("sha256", ""))) is None:
            raise ValidationError(f"workflow artifact requires SHA-256: {artifact_id}")


def _configure(project: dict[str, Any], operation: Mapping[str, Any]) -> None:
    if project.get("production_workflow") is not None:
        raise ValidationError("production workflow is already configured")
    if operation.get("protocol_id", PROTOCOL_ID) != PROTOCOL_ID:
        raise ValidationError(f"unsupported production workflow protocol: {operation.get('protocol_id')}")
    project["production_workflow"] = {
        "protocol_id": PROTOCOL_ID,
        "stages": {
            stage_id: {
                "status": "not_started", "artifact_ids": [], "submission": None,
                "review": None, "stale_due_to": [],
            }
            for stage_id in _CONTRACTS
        },
        "artifacts": {},
    }


def _register_artifact(project: dict[str, Any], operation: Mapping[str, Any]) -> None:
    workflow = _workflow(project)
    artifact_id = _required_text(operation, "artifact_id")
    if stable_id_exists(project, artifact_id):
        raise ValidationError(f"stable id already exists: {artifact_id}")
    stage_id = _stage_id(operation)
    kind = _required_text(operation, "kind")
    file_format = _required_text(operation, "format").lower().lstrip(".")
    rule = next((item for item in _CONTRACTS[stage_id]["deliverables"] if item["kind"] == kind), None)
    if rule is None or file_format not in rule["formats"]:
        raise ValidationError(f"artifact {kind}.{file_format} is not allowed for {stage_id}")
    digest = _required_text(operation, "sha256")
    if re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None:
        raise ValidationError("workflow artifact sha256 must contain 64 hexadecimal characters")
    derived_from = operation.get("derived_from", [])
    if not isinstance(derived_from, list) or any(item not in workflow["artifacts"] for item in derived_from):
        raise ValidationError("derived_from must reference existing workflow artifacts")
    version = _required_text(operation, "version")
    locator = _required_text(operation, "locator")
    if file_format != "directory" and kind not in _RAW_NAMING_KINDS:
        basename = locator.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        stage_number = f"{_CONTRACTS[stage_id]['number']:02d}"
        marker = rf"^{stage_number}_.+_v{re.escape(version)}_\d{{8}}\.[^.]+$"
        if re.fullmatch(marker, basename) is None:
            raise ValidationError("workflow filename must use 阶段_内容_v版本号_YYYYMMDD")
    artifact_verification = _artifact_verification(operation)
    workflow["artifacts"][artifact_id] = {
        "artifact_id": artifact_id, "stage_id": stage_id, "kind": kind, "format": file_format,
        "version": version, "locator": locator,
        "sha256": digest.lower(), "derived_from": list(derived_from),
        "metadata": _metadata(operation), "verification": artifact_verification,
    }
    state = workflow["stages"][stage_id]
    state["artifact_ids"].append(artifact_id)
    state.update(status="in_progress", submission=None, review=None, stale_due_to=[])
    _invalidate_downstream(workflow, stage_id)


def _submit_stage(project: dict[str, Any], operation: Mapping[str, Any]) -> None:
    workflow = _workflow(project)
    stage_id = _stage_id(operation)
    contract = _CONTRACTS[stage_id]
    state = workflow["stages"][stage_id]
    blockers = [dep for dep in contract["depends_on"] if workflow["stages"][dep]["status"] != "approved"]
    if blockers:
        raise ValidationError(f"stage dependencies are not approved: {', '.join(blockers)}")
    artifact_ids = operation.get("artifact_ids")
    if not isinstance(artifact_ids, list) or not artifact_ids:
        raise ValidationError("stage submission requires artifact_ids")
    if any(item not in state["artifact_ids"] for item in artifact_ids):
        raise ValidationError("stage submission may only contain artifacts registered to that stage")
    inputs = operation.get("input_artifact_ids", [])
    if not isinstance(inputs, list) or any(item not in workflow["artifacts"] for item in inputs):
        raise ValidationError("input_artifact_ids must reference existing workflow artifacts")
    allowed_inputs: set[str] = set()
    for dependency in contract["depends_on"]:
        approved_outputs = set(workflow["stages"][dependency]["submission"]["artifact_ids"])
        allowed_inputs.update(approved_outputs)
        selected_dependency_artifacts = [
            workflow["artifacts"][artifact_id]
            for artifact_id in approved_outputs.intersection(inputs)
        ]
        selected_kinds = {artifact["kind"] for artifact in selected_dependency_artifacts}
        missing_kinds = set(contract["required_inputs"][dependency]).difference(selected_kinds)
        if missing_kinds:
            raise ValidationError(
                f"submission is missing required input kinds from {dependency}: "
                + ", ".join(sorted(missing_kinds))
            )
    unapproved_inputs = set(inputs).difference(allowed_inputs)
    if unapproved_inputs:
        raise ValidationError(
            "submission inputs must come from current approved dependency outputs: "
            + ", ".join(sorted(unapproved_inputs))
        )
    selected = [workflow["artifacts"][item] for item in artifact_ids]
    for artifact in selected:
        missing_lineage = set(inputs).difference(artifact["derived_from"])
        if missing_lineage:
            raise ValidationError(
                f"artifact {artifact['artifact_id']} does not derive from submitted inputs: "
                f"{', '.join(sorted(missing_lineage))}"
            )
    for rule in contract["deliverables"]:
        count = sum(1 for item in selected if item["kind"] == rule["kind"] and item["format"] in rule["formats"])
        if count < rule["minimum"]:
            raise ValidationError(f"missing required deliverable for {stage_id}: {rule['kind']}")
    acceptance = operation.get("acceptance")
    if not isinstance(acceptance, list) or len(acceptance) != len(contract["acceptance"]):
        raise ValidationError("acceptance must contain one result for every canonical criterion")
    normalized = []
    for index, criterion in enumerate(contract["acceptance"], start=1):
        result = acceptance[index - 1]
        if not isinstance(result, Mapping) or result.get("criterion") != criterion or result.get("passed") is not True:
            raise ValidationError(f"acceptance criterion {index} must match and pass")
        evidence = result.get("evidence")
        if not isinstance(evidence, list) or not evidence or not all(isinstance(item, str) and item for item in evidence):
            raise ValidationError(f"acceptance criterion {index} requires evidence")
        normalized.append({"criterion": criterion, "passed": True, "evidence": list(evidence)})
    content_checks = _passed_checks(
        operation.get("content_checks"), contract["content_requirements"], "content requirement"
    )
    state.update(
        status="submitted", review=None, stale_due_to=[],
        submission={
            "version": _required_text(operation, "version"), "artifact_ids": list(artifact_ids),
            "input_artifact_ids": list(inputs), "acceptance": normalized,
            "content_checks": content_checks,
        },
    )


def _approve_stage(project: dict[str, Any], operation: Mapping[str, Any]) -> None:
    workflow = _workflow(project)
    stage_id = _stage_id(operation)
    state = workflow["stages"][stage_id]
    if state["status"] != "submitted" or not state["submission"]:
        raise ValidationError("only a submitted stage can be approved")
    evidence = operation.get("evidence")
    if not isinstance(evidence, list) or not evidence or not all(isinstance(item, str) and item for item in evidence):
        raise ValidationError("stage approval requires evidence")
    state["status"] = "approved"
    state["review"] = {
        "reviewer": _required_text(operation, "reviewer"), "evidence": list(evidence),
        "notes": str(operation.get("notes", "")),
    }


def _invalidate_downstream(workflow: dict[str, Any], changed_stage: str) -> None:
    frontier = [changed_stage]
    affected: set[str] = set()
    while frontier:
        parent = frontier.pop()
        for stage_id, contract in _CONTRACTS.items():
            if parent in contract["depends_on"] and stage_id not in affected:
                affected.add(stage_id)
                frontier.append(stage_id)
    for stage_id in affected:
        state = workflow["stages"][stage_id]
        if state["status"] != "not_started":
            state["status"] = "stale"
            state["stale_due_to"] = sorted(set(state["stale_due_to"] + [changed_stage]))


def _workflow(project: Mapping[str, Any]) -> dict[str, Any]:
    workflow = project.get("production_workflow")
    if not isinstance(workflow, dict):
        raise ValidationError("configure the production workflow before using it")
    return workflow


def _stage_id(operation: Mapping[str, Any]) -> str:
    stage_id = _required_text(operation, "stage_id")
    if stage_id not in _CONTRACTS:
        raise ValidationError(f"unknown production workflow stage: {stage_id}")
    return stage_id


def _required_text(operation: Mapping[str, Any], key: str) -> str:
    value = operation.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{key} is required")
    return value.strip()


def _metadata(operation: Mapping[str, Any]) -> dict[str, Any]:
    value = operation.get("metadata", {})
    if not isinstance(value, Mapping):
        raise ValidationError("metadata must be an object")
    return dict(value)


def _artifact_verification(operation: Mapping[str, Any]) -> dict[str, Any]:
    value = operation.get("verification")
    if not isinstance(value, Mapping):
        raise ValidationError("workflow artifact requires verification")
    evidence = value.get("evidence")
    if not isinstance(evidence, list) or not evidence or not all(isinstance(item, str) and item for item in evidence):
        raise ValidationError("workflow artifact verification requires evidence")
    if value.get("readable") is not True or value.get("hash_matched") is not True:
        raise ValidationError("workflow artifact must be readable and match its declared hash")
    content_profile = value.get("content_profile", {})
    if not isinstance(content_profile, Mapping):
        raise ValidationError("workflow artifact content_profile must be an object")
    return {
        "verifier": _required_text(value, "verifier"), "readable": True, "hash_matched": True,
        "evidence": list(evidence), "content_profile": dict(content_profile),
    }


def _passed_checks(value: Any, requirements: list[str], label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != len(requirements):
        raise ValidationError(f"{label} checks must cover every canonical requirement")
    normalized = []
    for index, requirement in enumerate(requirements, start=1):
        result = value[index - 1]
        evidence = result.get("evidence") if isinstance(result, Mapping) else None
        if (
            not isinstance(result, Mapping) or result.get("requirement") != requirement
            or result.get("passed") is not True or not isinstance(evidence, list) or not evidence
            or not all(isinstance(item, str) and item for item in evidence)
        ):
            raise ValidationError(f"{label} {index} must match, pass and include evidence")
        normalized.append({"requirement": requirement, "passed": True, "evidence": list(evidence)})
    return normalized
