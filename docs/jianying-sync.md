# Jianying bidirectional sync

The first adapter targets the locally installed Jianying Pro 11.3 line. It reads the native encrypted `draft_content.json` through an external codec sidecar, normalizes A/V segments, and preserves unknown JSON fields for round-trip output.

## Safety contract

- `sync.open` and `sync.preview` are read-only.
- `sync.commit` writes only a new Workbench revision.
- `sync.publish` refuses a running Jianying process, refuses an existing destination, clones the complete source draft, and writes only the clone.
- The codec executable is not bundled. Pin its SHA-256 with `--jianying-codec-sha256`; the adapter stages it with the selected installed `videoeditor.dll` in a temporary directory.
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

The typed bidirectional writer covers A/V segment timeline position, timeline duration, source in/out, speed, and transform. Source out is translated to Jianying's source duration representation. Other native objects and future fields survive as opaque JSON but are not yet directly editable through Workbench operations.
