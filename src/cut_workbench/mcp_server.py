from __future__ import annotations

import json
import sys
from typing import Any, Mapping

from .app import WorkbenchApp


class McpServer:
    """Dependency-free MCP stdio adapter over the agent-neutral application facade."""

    def __init__(self, app: WorkbenchApp) -> None:
        self.app = app

    def handle(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        request_id = message.get("id")
        method = message.get("method")
        if request_id is None:
            return None
        try:
            if method == "initialize":
                result: Any = {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "cut-workbench", "version": "0.1.0"},
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": self.app.list_tools()}
            elif method == "tools/call":
                params = message.get("params", {})
                value = self.app.call_tool(params["name"], params.get("arguments", {}))
                result = {
                    "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
                    "structuredContent": value,
                    "isError": False,
                }
            else:
                return _error(request_id, -32601, f"Method not found: {method}")
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except Exception as error:
            if method == "tools/call":
                value = {"error": type(error).__name__, "message": str(error)}
                return {
                    "jsonrpc": "2.0", "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
                        "structuredContent": value, "isError": True,
                    },
                }
            return _error(request_id, -32603, str(error))

    def run_stdio(self) -> None:
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                response = self.handle(json.loads(line))
            except json.JSONDecodeError as error:
                response = _error(None, -32700, f"Parse error: {error}")
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
                sys.stdout.flush()


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
