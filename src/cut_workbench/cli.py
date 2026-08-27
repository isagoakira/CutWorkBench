from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .app import WorkbenchApp
from .config import load_runtime_config
from .mcp_server import McpServer
from .editor_sync import EditorSyncRegistry, SyncSessionStore
from .jianying import JianyingCodecCommand, JianyingDraftAdapter, discover_jianying_draft_index
from .local_editor import AfterEffectsAdapter, LocalFileBridge, PremiereAdapter, panel_tree_hash
from .project_store import ProjectStore


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cut-workbench")
    parser.add_argument("--root", type=Path, default=Path(".cut-workbench"))
    parser.add_argument("--config", type=Path)
    parser.add_argument("--jianying-codec", type=Path)
    parser.add_argument("--jianying-install", type=Path)
    parser.add_argument("--jianying-version", default="local")
    parser.add_argument("--jianying-codec-sha256")
    parser.add_argument("--premiere-bridge-root", type=Path)
    parser.add_argument("--premiere-bridge-kind", choices=("cep", "uxp"), default="cep")
    parser.add_argument("--premiere-profile-sha256")
    parser.add_argument("--premiere-version")
    parser.add_argument("--premiere-panel-root", type=Path)
    parser.add_argument("--premiere-panel-sha256")
    parser.add_argument("--after-effects-bridge-root", type=Path)
    parser.add_argument("--after-effects-profile-sha256")
    parser.add_argument("--after-effects-version")
    parser.add_argument("--after-effects-panel-root", type=Path)
    parser.add_argument("--after-effects-panel-sha256")
    parser.add_argument("--editor-bridge-timeout", type=float, default=30.0)
    parser.add_argument("--editor-bridge-poll-interval", type=float, default=0.1)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("mcp", help="Run the MCP server over stdio")
    subparsers.add_parser("list-tools", help="Print the portable tool catalog")
    bridge_hash = subparsers.add_parser("bridge-hash", help="Print a deterministic local panel directory hash")
    bridge_hash.add_argument("panel_root", type=Path)
    call = subparsers.add_parser("call", help="Call a workbench tool with JSON arguments")
    call.add_argument("tool")
    call.add_argument("arguments", help="JSON object")
    args = parser.parse_args(argv)

    if args.command == "bridge-hash":
        print(panel_tree_hash(args.panel_root))
        return 0

    registry, policy = load_runtime_config(args.config)
    adapters = {}
    if args.jianying_codec or args.jianying_install:
        if not args.jianying_codec or not args.jianying_install:
            parser.error("--jianying-codec and --jianying-install must be provided together")
        if not args.jianying_codec_sha256:
            parser.error("--jianying-codec-sha256 is required for an external Jianying codec")
        codec = JianyingCodecCommand(
            args.jianying_codec, args.jianying_install,
            expected_sha256=args.jianying_codec_sha256,
        )
        adapter = JianyingDraftAdapter(
            codec=codec, editor_version=args.jianying_version,
            draft_index_path=discover_jianying_draft_index(),
        )
        adapters[adapter.adapter_id] = adapter
    if args.premiere_bridge_root:
        if not all((args.premiere_profile_sha256, args.premiere_version, args.premiere_panel_root, args.premiere_panel_sha256)):
            parser.error("Premiere bridge requires profile hash, editor version, panel root, and panel hash pins")
        bridge = LocalFileBridge(
            args.premiere_bridge_root, adapter_id=f"premiere:{args.premiere_bridge_kind}-local",
            timeout=args.editor_bridge_timeout, poll_interval=args.editor_bridge_poll_interval,
            expected_profile_sha256=args.premiere_profile_sha256,
            expected_editor_version=args.premiere_version,
            panel_root=args.premiere_panel_root, expected_panel_sha256=args.premiere_panel_sha256,
        )
        adapter = PremiereAdapter(bridge)
        adapters[adapter.adapter_id] = adapter
    if args.after_effects_bridge_root:
        if not all((args.after_effects_profile_sha256, args.after_effects_version, args.after_effects_panel_root, args.after_effects_panel_sha256)):
            parser.error("After Effects bridge requires profile hash, editor version, panel root, and panel hash pins")
        bridge = LocalFileBridge(
            args.after_effects_bridge_root, adapter_id="after-effects:cep-local",
            timeout=args.editor_bridge_timeout, poll_interval=args.editor_bridge_poll_interval,
            expected_profile_sha256=args.after_effects_profile_sha256,
            expected_editor_version=args.after_effects_version,
            panel_root=args.after_effects_panel_root, expected_panel_sha256=args.after_effects_panel_sha256,
        )
        adapter = AfterEffectsAdapter(bridge)
        adapters[adapter.adapter_id] = adapter
    editor_sync = EditorSyncRegistry(
        store=ProjectStore(args.root), sessions=SyncSessionStore(args.root), adapters=adapters
    ) if adapters else None
    app = WorkbenchApp(args.root, registry=registry, policy=policy, editor_sync=editor_sync)
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
