from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cut_workbench.app import WorkbenchApp
from cut_workbench.mcp_server import McpServer


class McpSurfaceTests(unittest.TestCase):
    def test_agent_neutral_tool_surface_creates_and_mutates_projects(self) -> None:
        with TemporaryDirectory() as directory:
            app = WorkbenchApp(Path(directory))
            tools = app.list_tools()
            names = {tool["name"] for tool in tools}
            self.assertIn("project.create", names)
            self.assertIn("capability.request", names)
            self.assertIn("vectcut.compile", names)

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
