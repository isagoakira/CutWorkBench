from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from cut_workbench.errors import ValidationError
from cut_workbench.project_store import ProjectStore
from cut_workbench.tapnow_context import TapNowContextCompiler
from cut_workbench.tapnow_assets import TapNowAssetStager
from cut_workbench.tapnow_web import TapNowWebHandoffRenderer


class TapNowContextCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ProjectStore(self.root)
        self.project = self.store.create_project(
            project_id="context", title="Context", canvas={"width": 1920, "height": 1080, "fps": 25}
        )
        self.project = self._register_context_artifacts(self.project)
        self.compiler = TapNowContextCompiler()
        self.stager = TapNowAssetStager(self.root)
        self.web_handoff = TapNowWebHandoffRenderer(self.root)

    def test_compiles_locked_deliveries_into_ordered_canvas_plan(self) -> None:
        plan = self.compiler.compile(project=self.project, upstream=self._upstream())

        self.assertEqual("agentic:tapnow", plan["provider_id"])
        self.assertEqual(["CTX-GLOBAL", "SRC-ART-PRODUCT", "SHOT-S01-BRIEF", "SHOT-S01-GENERATE", "SHOT-S02-BRIEF"], [item["node_id"] for item in plan["canvas_nodes"]])
        self.assertEqual(["S01"], [item["shot_id"] for item in plan["generation_requests"]])
        self.assertEqual("preview", plan["generation_requests"][0]["constraints"]["execution_boundary"])
        self.assertEqual("human", plan["excluded_shots"][0]["route"])
        self.assertIn("# TapNow Canvas 执行简报", plan["tapnow_agent_brief"])
        self.assertEqual(64, len(plan["context_fingerprint"]))
        self.assertEqual(["product-source"], plan["canvas_nodes"][1]["roles"])

    def test_stages_sources_then_reconciles_complete_canvas_mapping(self) -> None:
        source = self.root / "04_原始素材" / "产品图.png"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"product")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        self.project["production_workflow"]["artifacts"]["ART-PRODUCT"]["sha256"] = digest
        plan = self.compiler.compile(project=self.project, upstream=self._upstream())

        staged = self.stager.stage(project=self.project, context_plan=plan)
        self.assertEqual("prepared_not_uploaded", staged["status"])
        staged_file = self.root / staged["assets"][0]["staged_locator"]
        self.assertTrue(staged_file.is_file())
        reconciled = self.stager.reconcile(
            project=self.project, context_plan=plan, import_id=staged["import_id"],
            canvas_url="https://app.tapnow.ai/canvas/demo", node_mappings=[{"artifact_id": "ART-PRODUCT", "node_id": "product-node"}],
            external_upload_approval={"approved_by": "human:producer", "evidence": ["approvals/upload.md"]},
        )
        self.assertEqual("tapnow://canvas/demo/node/product-node", reconciled["canvas_bindings"][0]["reference"]["locator"])

    def test_reconcile_requires_explicit_upload_approval(self) -> None:
        source = self.root / "04_原始素材" / "产品图.png"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"product")
        self.project["production_workflow"]["artifacts"]["ART-PRODUCT"]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
        plan = self.compiler.compile(project=self.project, upstream=self._upstream())
        staged = self.stager.stage(project=self.project, context_plan=plan)
        with self.assertRaisesRegex(ValidationError, "external_upload_approval"):
            self.stager.reconcile(
                project=self.project, context_plan=plan, import_id=staged["import_id"], canvas_url="https://app.tapnow.ai/canvas/demo",
                node_mappings=[{"artifact_id": "ART-PRODUCT", "node_id": "product-node"}], external_upload_approval={},
            )

    def test_renders_a_web_handoff_without_claiming_browser_automation(self) -> None:
        source = self.root / "04_原始素材" / "产品图.png"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"product")
        self.project["production_workflow"]["artifacts"]["ART-PRODUCT"]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
        plan = self.compiler.compile(project=self.project, upstream=self._upstream())
        staged = self.stager.stage(project=self.project, context_plan=plan)

        handoff = self.web_handoff.render(project=self.project, context_plan=plan, import_pack=staged)

        self.assertEqual("ready_for_web_handoff", handoff["status"])
        brief = (self.root / handoff["agent_brief_locator"]).read_text(encoding="utf-8")
        task_card = (self.root / handoff["handoff_locator"]).read_text(encoding="utf-8")
        mapping = (self.root / handoff["mapping_template_locator"]).read_text(encoding="utf-8")
        self.assertIn("# TapNow Canvas 执行简报", brief)
        self.assertIn("不得创建生成节点", task_card)
        self.assertIn("由 Agent 建立", task_card)
        self.assertIn("先按上列顺序建立", brief)
        self.assertIn('"node_id": ""', mapping)
        self.assertIn("never opens a browser", handoff["automation_boundary"])

    def test_rejects_an_unapproved_storyboard(self) -> None:
        broken = self.project.copy()
        broken["production_workflow"] = {**self.project["production_workflow"]}
        broken["production_workflow"]["stages"] = {**self.project["production_workflow"]["stages"]}
        broken["production_workflow"]["stages"]["02-storyboard"] = {
            **self.project["production_workflow"]["stages"]["02-storyboard"], "status": "submitted"
        }
        with self.assertRaisesRegex(ValidationError, "not an approved"):
            self.compiler.compile(project=broken, upstream=self._upstream())

    def test_rejects_future_or_non_generative_dependencies(self) -> None:
        upstream = self._upstream()
        upstream["shots"][0]["depends_on_shot_ids"] = ["S02"]
        with self.assertRaisesRegex(ValidationError, "only depend on generative"):
            self.compiler.compile(project=self.project, upstream=upstream)

    def _register_context_artifacts(self, project):
        project = self.store.apply_plan(
            project_id=project["project_id"], expected_revision=project["revision"], actor="agent", reason="configure",
            operations=[{"op": "configure_production_workflow"}],
        )
        ids = []
        for stage_id, artifact_id, kind, filename, inputs in [
            ("01-script", "ART-SCRIPT", "video-script", "01_脚本_v1_20260903.md", []),
            ("02-storyboard", "ART-STORY", "storyboard", "02_分镜_v1_20260903.pdf", ["ART-SCRIPT"]),
            ("03-material-list", "ART-MATERIAL", "material-list", "03_素材_v1_20260903.xlsx", ["ART-STORY"]),
            ("04-recording", "ART-PRODUCT", "raw-media", "04_原始素材/产品图.png", ["ART-MATERIAL"]),
        ]:
            project = self.store.apply_plan(
                project_id=project["project_id"], expected_revision=project["revision"], actor="agent", reason="register",
                operations=[{
                    "op": "register_workflow_artifact", "artifact_id": artifact_id, "stage_id": stage_id,
                    "kind": kind, "format": "directory" if kind == "raw-media" else filename.rsplit(".", 1)[1],
                    "version": "1", "locator": filename, "sha256": hashlib.sha256(artifact_id.encode()).hexdigest(),
                    "derived_from": inputs, "verification": {"verifier": "test", "readable": True, "hash_matched": True, "evidence": ["test"], "content_profile": {}},
                }],
            )
            ids.append(artifact_id)
            if stage_id == "03-material-list":
                project = self.store.apply_plan(
                    project_id=project["project_id"], expected_revision=project["revision"], actor="agent", reason="register naming",
                    operations=[{
                        "op": "register_workflow_artifact", "artifact_id": "ART-NAMING", "stage_id": stage_id,
                        "kind": "naming-convention", "format": "md", "version": "1",
                        "locator": "03_命名规则_v1_20260903.md", "sha256": hashlib.sha256(b"ART-NAMING").hexdigest(),
                        "derived_from": inputs, "verification": {"verifier": "test", "readable": True, "hash_matched": True, "evidence": ["test"], "content_profile": {}},
                    }],
                )
            if stage_id != "04-recording":
                workflow = project["production_workflow"]
                contract = {"01-script": ["ART-SCRIPT"], "02-storyboard": ["ART-STORY"], "03-material-list": ["ART-MATERIAL", "ART-NAMING"]}[stage_id]
                project = self.store.apply_plan(
                    project_id=project["project_id"], expected_revision=project["revision"], actor="agent", reason="submit",
                    operations=[{
                        "op": "submit_workflow_stage", "stage_id": stage_id, "version": "1", "artifact_ids": contract,
                        "input_artifact_ids": inputs,
                        "acceptance": [{"criterion": item, "passed": True, "evidence": ["test"]} for item in _acceptance(stage_id)],
                        "content_checks": [{"requirement": item, "passed": True, "evidence": ["test"]} for item in _content(stage_id)],
                    }],
                )
                project = self.store.apply_plan(
                    project_id=project["project_id"], expected_revision=project["revision"], actor="human", reason="approve",
                    operations=[{"op": "approve_workflow_stage", "stage_id": stage_id, "reviewer": "human", "evidence": ["test"]}],
                )
        return project

    def _upstream(self):
        return {
            "artifact_ids": ["ART-SCRIPT", "ART-STORY", "ART-MATERIAL"],
            "campaign": {"audience": "创作者", "platform": "抖音", "core_message": "产品好用", "creative_direction": "轻快实测", "prohibitions": ["不可修改包装文字"]},
            "shots": [
                {"shot_id": "S01", "sequence": 1, "duration_seconds": 5, "purpose": "建立产品印象", "visual_direction": "产品置于桌面", "route": "generative", "source_artifact_ids": ["ART-PRODUCT"], "reference_roles": {"ART-PRODUCT": "product-source"}, "depends_on_shot_ids": [], "generation": {"capability": "video.generate", "prompt": "产品缓慢转动", "output": {"count": 1, "duration_seconds": 5}, "preserve": ["包装文字"], "avoid": ["额外 logo"], "acceptance_criteria": ["产品完整"]}},
                {"shot_id": "S02", "sequence": 2, "duration_seconds": 3, "purpose": "真人解释", "visual_direction": "对镜口播", "route": "human", "source_artifact_ids": ["ART-PRODUCT"], "reference_roles": {"ART-PRODUCT": "product-source"}, "depends_on_shot_ids": []},
            ],
        }


def _acceptance(stage_id):
    return {
        "01-script": ["全片逻辑完整，开头、主体、结尾明确", "每一段均能判断拍什么、说什么、给观众什么信息", "总时长预估合理", "未确定内容明确标注为待确认"],
        "02-storyboard": ["每个脚本段落均有对应镜头方案", "明确主体、角度、机位数和补充镜头需求", "关键表述有主镜头和足够的 B-roll 支撑", "后期配音所需节奏窗口已明确"],
        "03-material-list": ["所有必须镜头均有可获得的素材来源", "每个场景有主画面与补充画面", "录制范围明确且可剪辑", "版权、授权或素材来源可追溯"],
    }[stage_id]


def _content(stage_id):
    return {
        "01-script": ["标题、主题、受众和目标时长", "章节目的、核心信息和预计时长", "画面大意与音画角色标记", "后期配音、动画、屏录和资料画面预留"],
        "02-storyboard": ["唯一镜号与脚本段落", "预计时长、画面内容、景别角度和机位", "音频与后期要求", "素材状态"],
        "03-material-list": ["素材编号与场景章节", "内容、拍摄范围和重点", "机位角度与音频需求", "来源、优先级和状态"],
    }[stage_id]
