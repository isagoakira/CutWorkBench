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

## Incremental updates to an open Jianying editor

`jianying:live-local` is a local bridge adapter separate from the file-draft adapter. It neither calls `jy-draftc` nor modifies `draft_content.json`; the Jianying-side bridge reads the open timeline, executes commands, and returns snapshots.

Within one editor session, use `sync.open → sync.preview → sync.commit → sync.apply`. `sync.apply` creates no clone. Each command includes a baseline `fingerprint`, strict allowlisted `set` patches, and request ID. Execution requires `live_apply_enabled: true` in local authorization and a receipt containing the exact patch list and updated snapshot. Any fingerprint mismatch is rejected.

CLI bridge configuration requires pinned profile SHA-256 and Jianying version:

```powershell
python -m cut_workbench.cli --root <workbench-directory> `
  --jianying-live-bridge-root <jianying-side-bridge-directory> `
  --jianying-live-profile-sha256 <profile-json-sha256> `
  --jianying-live-version 11.3.0.14362 mcp
```

The Jianying-side host maintains `profile.json`, `snapshot.json`, `authorization.json`, `commands/`, and `responses/`. Cut Workbench only writes commands and validates responses; the file protocol does not authorize writing open drafts. The current installer has not identified a verifiable official Jianying extension entry point. A controlled local Jianying-side bridge must connect before enabling this adapter on a real open timeline.

## Low-friction acceptance switching: current default path

Without a live host bridge, do not switch Jianying after every new request. Keep it open while recording requests as Workbench revisions. At acceptance, complete `sync.open → sync.preview → sync.commit`, save and close Jianying, then call:

```json
{"session_id":"<committed-session>","reopen_editor":true}
```

After Jianying exits, `sync.publish` creates and registers the latest named copy and launches `JianyingPro.exe`. It does not close an actively edited application or guess unpublished “open specific draft” arguments. Select the latest copy in the draft library after relaunch. Publication still refuses explicitly if Jianying remains open.
