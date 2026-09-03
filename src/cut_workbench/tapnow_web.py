from __future__ import annotations

"""Render one human-executable TapNow Web handoff from a staged Context Pack."""

import json
from pathlib import Path
from typing import Any, Mapping

from .errors import ValidationError


class TapNowWebHandoffRenderer:
    """Materialize the complete, non-automated Web handoff behind one method."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()

    def render(
        self,
        *,
        project: Mapping[str, Any],
        context_plan: Mapping[str, Any],
        import_pack: Mapping[str, Any],
    ) -> dict[str, Any]:
        fingerprint = _validate_plan(project, context_plan)
        pack_dir = _import_pack_dir(self.root, fingerprint, import_pack)
        manifest = _manifest(pack_dir, project, fingerprint)
        agent_brief = _text(context_plan, "tapnow_agent_brief")

        handoff_path = pack_dir / "tapnow-web-handoff.md"
        brief_path = pack_dir / "tapnow-agent-brief.md"
        mapping_path = pack_dir / "canvas-node-mapping.json"
        _write_if_equal_or_new(brief_path, agent_brief)
        _write_if_equal_or_new(handoff_path, _render_handoff(context_plan, manifest["assets"]))
        mapping_template = {
            "schema_version": 1,
            "import_id": fingerprint,
            "canvas_url": "",
            "node_mappings": [
                {
                    "artifact_id": item["artifact_id"],
                    "staged_locator": item["staged_locator"],
                    "roles": item["roles"],
                    "node_id": "",
                }
                for item in manifest["assets"]
            ],
            "instructions": "After upload, fill canvas_url and every node_id, then pass canvas_url and node_mappings to tapnow.canvas.reconcile. Do not put credentials, costs, or generated results in this file.",
        }
        _write_if_equal_or_new(mapping_path, json.dumps(mapping_template, ensure_ascii=False, indent=2) + "\n")
        return {
            "status": "ready_for_web_handoff",
            "import_id": fingerprint,
            "handoff_locator": _relative(self.root, handoff_path),
            "agent_brief_locator": _relative(self.root, brief_path),
            "mapping_template_locator": _relative(self.root, mapping_path),
            "manual_steps": [
                "Open a new TapNow Web canvas and upload only the staged assets in canvas-import-order.md order.",
                "Verify every uploaded preview, paste tapnow-agent-brief.md, and attach only its declared source nodes with @.",
                "Have Agent create the Context and Shot Brief text nodes, then review its Ask-mode node plan and cost estimate; do not generate.",
                "After approved upload, fill canvas-node-mapping.json and call tapnow.canvas.reconcile before requesting any preview jobs.",
            ],
            "automation_boundary": "This handoff never opens a browser, uploads a file, selects @ references, sends an Agent message, or starts generation.",
        }


def _validate_plan(project: Mapping[str, Any], context_plan: Mapping[str, Any]) -> str:
    if context_plan.get("project_id") != project.get("project_id"):
        raise ValidationError("context_plan belongs to a different project")
    if context_plan.get("project_revision") != project.get("revision"):
        raise ValidationError("context_plan belongs to a different project revision")
    fingerprint = context_plan.get("context_fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise ValidationError("context_plan has an invalid context_fingerprint")
    return fingerprint


def _import_pack_dir(root: Path, fingerprint: str, import_pack: Mapping[str, Any]) -> Path:
    if import_pack.get("import_id") != fingerprint or import_pack.get("status") != "prepared_not_uploaded":
        raise ValidationError("render a Web handoff only from the matching staged import pack")
    import_root = _text(import_pack, "import_root")
    pack_dir = (root / import_root).resolve()
    expected = (root / "tapnow-imports" / fingerprint).resolve()
    if pack_dir != expected:
        raise ValidationError("import_pack root is not the expected TapNow staging directory")
    return pack_dir


def _manifest(pack_dir: Path, project: Mapping[str, Any], fingerprint: str) -> dict[str, Any]:
    path = pack_dir / "asset-manifest.json"
    if not path.is_file():
        raise ValidationError("TapNow import pack is missing asset-manifest.json")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValidationError("TapNow asset manifest is unreadable") from error
    if not isinstance(value, dict) or value.get("import_id") != fingerprint:
        raise ValidationError("TapNow asset manifest does not match the import pack")
    if value.get("project_id") != project.get("project_id") or value.get("project_revision") != project.get("revision"):
        raise ValidationError("TapNow asset manifest belongs to a different project revision")
    assets = value.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValidationError("TapNow asset manifest has no staged assets")
    for item in assets:
        if not isinstance(item, dict) or not isinstance(item.get("artifact_id"), str) or not isinstance(item.get("staged_locator"), str):
            raise ValidationError("TapNow asset manifest has an invalid staged asset")
    return value


def _render_handoff(context_plan: Mapping[str, Any], assets: list[Mapping[str, Any]]) -> str:
    nodes = context_plan.get("canvas_nodes")
    if not isinstance(nodes, list) or not nodes or not isinstance(nodes[0], Mapping):
        raise ValidationError("context_plan has no global Canvas node")
    campaign = nodes[0].get("content", {})
    if not isinstance(campaign, Mapping):
        raise ValidationError("context_plan global Canvas node has no campaign context")
    lines = [
        "# TapNow Web 执行交接卡",
        "",
        "本交接卡只组织网页端人工操作；不允许以浏览器脚本代替上传、节点选择、Agent 发送或付费确认。",
        "",
        "## 已锁定的全局约束",
        f"- 受众：{campaign.get('audience', '')}",
        f"- 平台：{campaign.get('platform', '')}",
        f"- 核心信息：{campaign.get('core_message', '')}",
        f"- 创意基调：{campaign.get('creative_direction', '')}",
        f"- 禁止项：{'；'.join(campaign.get('prohibitions', [])) or '无'}",
        "",
        "## 1. 上传已登记素材",
        "在新 Canvas 中仅上传 `assets/` 内的文件，并逐项核对预览。每一项都是独立节点：",
        "",
    ]
    for item in assets:
        lines.append(f"{item['order']}. `{item['staged_locator']}` · `{item['artifact_id']}` · 角色：{' / '.join(item['roles'])}")
    lines.extend([
        "",
        "## 2. 交给 Agent 建立文字上下文并规划",
        "粘贴 `tapnow-agent-brief.md`，用 `@` 明确引用每一个已登记的源素材节点。由 Agent 建立全局 Context 与镜头 Brief 文字节点；它不得改写锁定时长、目的、禁止项或素材角色。",
        "",
        "只接受 Agent 在 Ask 模式返回的节点建立计划、引用关系、逐镜方案与实时成本预估；不得创建生成节点或开始生成。",
        "",
        "## 3. 回填节点映射",
        "在 `canvas-node-mapping.json` 中填写 Canvas URL 和每项的 node_id。获得外传批准后，调用 `tapnow.canvas.reconcile`。回填完成后才可提出逐镜 preview 请求。",
        "",
    ])
    return "\n".join(lines)


def _write_if_equal_or_new(path: Path, contents: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") != contents:
            raise ValidationError(f"existing Web handoff differs from current context: {path}")
        return
    path.write_text(contents, encoding="utf-8", newline="\n")


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root))


def _text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValidationError(f"{key} is required")
    return item.strip()
