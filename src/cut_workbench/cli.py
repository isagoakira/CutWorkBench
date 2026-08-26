from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .app import WorkbenchApp
from .config import load_runtime_config
from .mcp_server import McpServer


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cut-workbench")
    parser.add_argument("--root", type=Path, default=Path(".cut-workbench"))
    parser.add_argument("--config", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("mcp", help="Run the MCP server over stdio")
    subparsers.add_parser("list-tools", help="Print the portable tool catalog")
    call = subparsers.add_parser("call", help="Call a workbench tool with JSON arguments")
    call.add_argument("tool")
    call.add_argument("arguments", help="JSON object")
    args = parser.parse_args(argv)

    registry, policy = load_runtime_config(args.config)
    app = WorkbenchApp(args.root, registry=registry, policy=policy)
    if args.command == "mcp":
        McpServer(app).run_stdio()
        return 0
    if args.command == "list-tools":
        print(json.dumps(app.list_tools(), indent=2, ensure_ascii=False))
        return 0
    value = app.call_tool(args.tool, json.loads(args.arguments))
    print(json.dumps(value, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
