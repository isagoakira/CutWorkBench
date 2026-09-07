# Jianying bidirectional sync

The first adapter targets the locally installed Jianying Pro 11.3 line. It reads the native encrypted `draft_content.json` through an external codec sidecar, normalizes A/V segments, and preserves unknown JSON fields for round-trip output.

## Safety contract

- `sync.open` and `sync.preview` are read-only.
- `sync.commit` writes only a new Workbench revision.
- `sync.publish` refuses a running Jianying process, refuses an existing destination, clones the complete source draft, and writes only the clone.
- A published clone receives a new Jianying library UUID. When the local draft index is discoverable, registration is atomic and the previous index is retained as a uniquely named backup.
- The codec executable is not bundled. Its SHA-256 is mandatory; the adapter stages the pinned helper in a temporary directory and points it at the selected installed `videoeditor.dll`.
- Unknown Jianying objects are retained as opaque external entities. A full VectCut rebuild is rejected while such objects exist because it cannot prove lossless preservation.

## Start the MCP server

```powershell
$env:PYTHONPATH='src'
python -m cut_workbench.cli `
  --root runtime `
  --jianying-codec C:/path/to/jy-draftc.exe `
  --jianying-install E:/JianYing/JianyingPro/11.3.0.14362 `
  --jianying-version 11.3.0.14362 `
  --jianying-codec-sha256 <verified-sha256> `
  mcp
```

## Transaction

1. Call `sync.open` with `project_id` and the source `draft_path`. Automatic binding uses media path, track kind, source range, timeline start, and speed; callers may provide explicit segment bindings.
2. Make Agent edits in the Workbench and/or manual edits in Jianying.
3. Call `sync.preview`. Each collision has a stable conflict ID.
4. Call `sync.commit` with a `resolutions` object mapping every conflict ID to `human` or `agent`. Manual changes are journaled as a new project revision.
5. Call `sync.publish` with a new, non-existing `destination_path`. Open that clone in Jianying for visual review; keep the source as rollback baseline.

## Current typed surface

The typed bidirectional writer covers A/V segment timeline position, source in/out, speed, transform, and the timeline duration derived from those fields. Source out is translated to Jianying's source duration representation; an independently stretched duration that cannot be represented by source range and speed is rejected explicitly. Manual segment deletion is supported; Agent-originated deletion is currently rejected rather than flattened. Other native objects and future fields survive as opaque JSON but are not yet directly editable through Workbench operations.

## 已打开剪映的增量应用

`jianying:live-local` 是与文件草稿适配器分离的本地桥接适配器。它不调用 `jy-draftc`，也不修改 `draft_content.json`；剪映侧桥接负责读取当前打开时间线、执行命令并返回快照。

一次剪映会话内的操作顺序是 `sync.open → sync.preview → sync.commit → sync.apply`。`sync.apply` 不创建克隆草稿，且每次命令包含基线 `fingerprint`、严格白名单的 `set` 补丁和请求 ID。桥接只有在本地授权文件的 `live_apply_enabled: true` 时才能执行，并必须回传精确的补丁列表和更新后的快照；任意指纹不一致都会拒绝。

通过 CLI 配置桥接时，必须固定其 profile SHA-256 和剪映版本：

```powershell
python -m cut_workbench.cli --root <工作台目录> `
  --jianying-live-bridge-root <剪映侧桥接目录> `
  --jianying-live-profile-sha256 <profile.json的SHA-256> `
  --jianying-live-version 11.3.0.14362 mcp
```

桥接目录由剪映侧宿主维护：`profile.json`、`snapshot.json`、`authorization.json`、`commands/` 与 `responses/`。Cut Workbench 仅写入 `commands/` 并校验 `responses/`；它不把文件协议当成对打开草稿的写入许可。当前安装包未发现可验证的官方剪映扩展入口，因此必须先由受控的剪映侧本地桥接接入后，才可对真实打开时间线启用该适配器。
