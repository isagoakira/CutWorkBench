from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cut_workbench.app import WorkbenchApp
from cut_workbench.mcp_server import McpServer
from cut_workbench.editor_sync import EditorSync, SyncSessionStore
from cut_workbench.project_store import ProjectStore


class McpSurfaceTests(unittest.TestCase):
    def test_sync_tools_are_exposed_through_the_same_agent_neutral_surface(self) -> None:
        class Adapter:
            adapter_id = "fake"

            def profile(self):
                return {"adapter_id": "fake", "writable": True}

            def snapshot(self, path):
                return {
                    "fingerprint": "fp", "draft_id": "d", "tracks": {}, "materials": {},
                    "entities": {}, "native_summary": {}, "adapter_id": "fake", "schema_version": 1,
                }

            def publish(self, draft_path, destination_path, patches):
                return {"status": "published"}

        with TemporaryDirectory() as directory:
            root = Path(directory)
            sync = EditorSync(store=ProjectStore(root), sessions=SyncSessionStore(root), adapter=Adapter())
            app = WorkbenchApp(root, editor_sync=sync)
            names = {tool["name"] for tool in app.list_tools()}
            self.assertTrue({"sync.open", "sync.preview", "sync.commit", "sync.publish"} <= names)
    def test_agent_neutral_tool_surface_creates_and_mutates_projects(self) -> None:
        with TemporaryDirectory() as directory:
            app = WorkbenchApp(Path(directory))
            tools = app.list_tools()
            names = {tool["name"] for tool in tools}
            self.assertIn("project.create", names)
            self.assertIn("capability.request", names)
            self.assertIn("vectcut.compile", names)
            self.assertTrue({
                "generation.contract", "generation.request", "generation.pending",
                "generation.reconciliation",
                "generation.claim", "generation.heartbeat", "generation.approve",
                "generation.authorize", "generation.submit"
            } <= names)

            generation = app.call_tool("generation.request", {
                "capability": "image.generate", "prompt": "产品主视觉", "references": [],
                "output": {"count": 1, "aspect_ratio": "1:1"},
                "constraints": {"execution_boundary": "preview"},
            })
            self.assertEqual("pending_provider", generation["status"])
            self.assertEqual(generation["job_id"], app.call_tool("generation.pending", {})[0]["job_id"])
            claimed = app.call_tool("generation.claim", {
                "job_id": generation["job_id"], "executor_id": "agent:test",
            })
            self.assertEqual("running_provider", claimed["status"])

            created = app.call_tool("project.create", {
                "project_id": "portable", "title": "Portable",
                "canvas": {"width": 1920, "height": 1080, "fps": 30},
            })
            updated = app.call_tool("project.apply_plan", {
                "project_id": "portable", "expected_revision": 1, "actor": "agent:any",
                "reason": "portable mutation", "operations": [
                    {"op": "add_track", "track_id": "V1-BASE", "kind": "video", "purpose": "base"}
                ],
            })
            self.assertEqual(2, updated["revision"])
            self.assertIn("V1-BASE", app.call_tool("project.inspect", {"project_id": "portable"})["tracks"])

    def test_json_rpc_surface_is_mcp_compatible(self) -> None:
        with TemporaryDirectory() as directory:
            server = McpServer(WorkbenchApp(Path(directory)))
            initialized = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
            self.assertEqual("2025-06-18", initialized["result"]["protocolVersion"])
            listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            self.assertTrue(any(tool["name"] == "project.create" for tool in listed["result"]["tools"]))
            called = server.handle({
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "project.create", "arguments": {
                    "project_id": "mcp", "title": "MCP",
                    "canvas": {"width": 1280, "height": 720, "fps": 25},
                }},
            })
            self.assertFalse(called["result"]["isError"])
            self.assertEqual("mcp", called["result"]["structuredContent"]["project_id"])


if __name__ == "__main__":
    unittest.main()
