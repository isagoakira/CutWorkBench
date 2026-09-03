from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from .capabilities import CapabilityOrchestrator, CapabilityRequest, ProviderRegistry, RoutingPolicy
from .jobs import CapabilityJobStore
from .local_providers import FfprobeProvider
from .manifest import render_cut_manifest
from .project_store import ProjectStore
from .production_workflow import production_contract, production_status
from .vectcut import VectCutCompiler
from .verification import verify_project
from .editor_sync import EditorSync
from .tapnow import GenerativeOrchestrator, TapNowAgenticAdapter


class WorkbenchApp:
    """Portable use-case facade shared by CLI, MCP, Codex and future agent hosts."""

    def __init__(
        self,
        root: Path,
        *,
        registry: ProviderRegistry | None = None,
        policy: RoutingPolicy | None = None,
        editor_sync: EditorSync | None = None,
        generative: GenerativeOrchestrator | None = None,
    ) -> None:
        self.root = Path(root)
        self.projects = ProjectStore(self.root)
        self.jobs = CapabilityJobStore(self.root)
        self.capabilities = CapabilityOrchestrator(
            registry=registry or ProviderRegistry([FfprobeProvider()]),
            jobs=self.jobs,
            policy=policy or RoutingPolicy.default(),
        )
        self.vectcut = VectCutCompiler()
        self.editor_sync = editor_sync
        self.generative = generative or GenerativeOrchestrator(
            jobs=self.jobs, adapter=TapNowAgenticAdapter(artifact_root=self.root)
        )

    def list_tools(self) -> list[dict[str, Any]]:
        string = {"type": "string"}
        integer = {"type": "integer", "minimum": 1}
        obj = {"type": "object"}
        return [
            _tool("project.create", "Create a versioned editable project", {
                "project_id": string, "title": string, "canvas": obj, "editor_adapter": string,
            }, ["project_id", "title", "canvas"]),
            _tool("project.inspect", "Read a project revision", {
                "project_id": string, "revision": integer,
            }, ["project_id"]),
            _tool("project.apply_plan", "Atomically apply stable-ID edit operations", {
                "project_id": string, "expected_revision": integer, "actor": string, "reason": string,
                "operations": {"type": "array", "items": obj},
                "evidence": {"type": "array", "items": string},
            }, ["project_id", "expected_revision", "actor", "reason", "operations"]),
            _tool("project.branch", "Branch a frozen or handed-off project", {
                "source_project_id": string, "new_project_id": string, "revision": integer, "title": string,
            }, ["source_project_id", "new_project_id"]),
            _tool("project.verify", "Run deterministic Cut Protocol gates", {
                "project_id": string, "revision": integer,
            }, ["project_id"]),
            _tool("project.manifest", "Render the auditable cut manifest", {
                "project_id": string, "revision": integer,
            }, ["project_id"]),
            _tool("workflow.contract", "Read the canonical nine-stage production contract", {}, []),
            _tool("workflow.status", "Read production-stage readiness and blockers", {
                "project_id": string, "revision": integer,
            }, ["project_id"]),
            _tool("capability.request", "Route work to a local provider or agent-native queue", {
                "capability": string, "inputs": obj, "quality": {"enum": ["standard", "high"]},
                "sensitivity": string, "constraints": obj,
            }, ["capability", "inputs"]),
            _tool("capability.pending", "List jobs awaiting an agent-native result", {}, []),
            _tool("capability.submit", "Submit an agent-native capability result", {
                "job_id": string, "agent_id": string, "payload": obj,
                "evidence": {"type": "array", "items": string},
            }, ["job_id", "agent_id", "payload", "evidence"]),
            _tool("generation.contract", "Read the agentic generative operation contract", {}, []),
            _tool("generation.request", "Dispatch a provider-neutral generation operation", {
                "capability": string, "prompt": string,
                "references": {"type": "array", "items": obj}, "output": obj,
                "constraints": obj, "artifact_targets": {"type": "array", "items": obj},
                "acceptance_criteria": {"type": "array", "items": string},
            }, ["capability", "prompt", "references", "output", "constraints"]),
            _tool("generation.pending", "List operations awaiting a generative Agent executor", {}, []),
            _tool("generation.reconciliation", "List authorized generation jobs requiring manual reconciliation", {}, []),
            _tool("generation.claim", "Claim one generative operation before external execution", {
                "job_id": string, "executor_id": string,
                "lease_seconds": {"type": "number", "exclusiveMinimum": 0},
            }, ["job_id", "executor_id"]),
            _tool("generation.heartbeat", "Renew a claimed generation operation lease", {
                "job_id": string, "executor_id": string,
                "lease_seconds": {"type": "number", "exclusiveMinimum": 0},
            }, ["job_id", "executor_id"]),
            _tool("generation.approve", "Approve one prepared operation for bounded generation", {
                "prepared_job_id": string, "approved_by": string,
                "billing_mode": {"enum": ["tapies", "unlimited"]},
                "max_candidates": integer, "max_tapies": {"type": "number", "minimum": 0},
                "evidence": {"type": "array", "items": string},
            }, ["prepared_job_id", "approved_by", "billing_mode", "max_candidates", "evidence"]),
            _tool("generation.authorize", "Validate live preflight and authorize external generation", {
                "job_id": string, "executor_id": string, "preflight": obj,
                "evidence": {"type": "array", "items": string},
            }, ["job_id", "executor_id", "preflight", "evidence"]),
            _tool("generation.submit", "Submit a validated generative result and artifact plan", {
                "job_id": string, "executor_id": string, "payload": obj,
                "evidence": {"type": "array", "items": string},
            }, ["job_id", "executor_id", "payload", "evidence"]),
            _tool("vectcut.compile", "Compile a project revision to a separable VectCut call plan", {
                "project_id": string, "revision": integer, "draft_folder": string,
            }, ["project_id"]),
            _tool("sync.open", "Open a version-pinned external editing session", {
                "project_id": string, "draft_path": string, "revision": integer,
                "bindings": {"type": "object", "additionalProperties": string},
            }, ["project_id", "draft_path"]),
            _tool("sync.preview", "Preview Agent/manual three-way changes and conflicts", {
                "session_id": string,
            }, ["session_id"]),
            _tool("sync.commit", "Commit manual changes as a new project revision", {
                "session_id": string,
                "resolutions": {"type": "object", "additionalProperties": {"enum": ["human", "agent"]}},
            }, ["session_id", "resolutions"]),
            _tool("sync.publish", "Publish merged Agent changes to a new editor draft clone", {
                "session_id": string, "destination_path": string,
            }, ["session_id", "destination_path"]),
        ]

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        handlers: dict[str, Callable[[Mapping[str, Any]], Any]] = {
            "project.create": lambda a: self.projects.create_project(**dict(a)),
            "project.inspect": lambda a: self.projects.read_project(a["project_id"], a.get("revision")),
            "project.apply_plan": lambda a: self.projects.apply_plan(**dict(a)),
            "project.branch": lambda a: self.projects.branch_project(**dict(a)),
            "project.verify": self._verify,
            "project.manifest": self._manifest,
            "workflow.contract": lambda a: production_contract(),
            "workflow.status": lambda a: production_status(
                self.projects.read_project(a["project_id"], a.get("revision"))
            ),
            "capability.request": self._request_capability,
            "capability.pending": lambda a: self.jobs.pending(),
            "capability.submit": lambda a: self.capabilities.submit_agent_result(**dict(a)),
            "generation.contract": lambda a: self.generative.contract(),
            "generation.request": lambda a: self.generative.request(a),
            "generation.pending": lambda a: self.generative.pending(),
            "generation.reconciliation": lambda a: self.generative.reconciliation(),
            "generation.claim": lambda a: self.generative.claim(**dict(a)),
            "generation.heartbeat": lambda a: self.generative.heartbeat(**dict(a)),
            "generation.approve": lambda a: self.generative.approve(**dict(a)),
            "generation.authorize": lambda a: self.generative.authorize(**dict(a)),
            "generation.submit": lambda a: self.generative.submit(**dict(a)),
            "vectcut.compile": self._compile_vectcut,
            "sync.open": lambda a: self._sync().open(**dict(a)),
            "sync.preview": lambda a: self._sync().preview(a["session_id"]),
            "sync.commit": lambda a: self._sync().commit(
                a["session_id"], resolutions=a.get("resolutions", {})
            ),
            "sync.publish": lambda a: self._sync().publish(
                a["session_id"], destination_path=a["destination_path"]
            ),
        }
        if name not in handlers:
            raise KeyError(f"unknown tool: {name}")
        return handlers[name](arguments)

    def _request_capability(self, arguments: Mapping[str, Any]) -> Any:
        return self.capabilities.request(CapabilityRequest(**dict(arguments)))

    def _verify(self, arguments: Mapping[str, Any]) -> Any:
        return verify_project(self.projects.read_project(arguments["project_id"], arguments.get("revision")))

    def _manifest(self, arguments: Mapping[str, Any]) -> Any:
        project = self.projects.read_project(arguments["project_id"], arguments.get("revision"))
        return {"markdown": render_cut_manifest(project)}

    def _compile_vectcut(self, arguments: Mapping[str, Any]) -> Any:
        project = self.projects.read_project(arguments["project_id"], arguments.get("revision"))
        return self.vectcut.compile(project, draft_folder=arguments.get("draft_folder"))

    def _sync(self) -> EditorSync:
        if self.editor_sync is None:
            raise RuntimeError(
                "external editor sync is not configured; configure a Jianying codec or a local editor bridge"
            )
        return self.editor_sync


def _tool(
    name: str, description: str, properties: Mapping[str, Any], required: list[str]
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object", "properties": dict(properties), "required": required,
            "additionalProperties": False,
        },
    }
