# Local Premiere Pro / After Effects bridge

Cut Workbench connects to Premiere Pro and After Effects through one restricted local file-bridge protocol, without connecting to ChatCut, VectCut, or Adobe cloud services. Workbench remains the source of truth for revisions, three-way merges, conflict decisions, and publication audits.

## Currently supported scope

- Premiere Pro 2023 / After Effects 2023 on the tested machine are both 23.0, so the first host implementation uses CEP/ExtendScript: `premiere:cep-local` and `after-effects:cep-local`.
- The future Premiere UXP route `premiere:uxp-local` can reuse the same protocol, but this repository does not yet provide a UXP panel. Do not configure it for Premiere 23.0.
- Installable CEP panel source is in `adapters/cep-local/`. Premiere currently exposes snapshot reads and source in/out writes to clones only. The AE panel exposes unkeyframed Layer Transform paths, but Workbench lacks AE typed-layer binding; currently these preserve and audit human changes only. Other objects, effects, text animation, keyframes, and Dynamic Link remain opaque external entities and are not rewritten by agents.
- One runtime can configure Jianying, Premiere, and AE together. `project.create.editor_adapter` selects the project adapter; `sync.open` routes accordingly and pins it for the session.
- Adapters permit only `set` patches to `property_paths` declared by the external snapshot. Panels are read-only by default; clone publication requires enabling authorization in the local panel.

Startup example:

```powershell
$env:PYTHONPATH = 'src'
python -m cut_workbench.cli `
  --root D:/cut-runtime `
  --premiere-bridge-root D:/cut-bridges/premiere `
  --premiere-bridge-kind cep `
  --premiere-profile-sha256 <PREMIERE_PROFILE_SHA256> `
  --premiere-version 23.0 `
  --premiere-panel-root "$env:APPDATA/Adobe/CEP/extensions/com.cutworkbench.premiere" `
  --premiere-panel-sha256 <PREMIERE_PANEL_SHA256> `
  --after-effects-bridge-root D:/cut-bridges/after-effects `
  --after-effects-profile-sha256 <AE_PROFILE_SHA256> `
  --after-effects-version 23.0 `
  --after-effects-panel-root "$env:APPDATA/Adobe/CEP/extensions/com.cutworkbench.aftereffects" `
  --after-effects-panel-sha256 <AE_PANEL_SHA256> `
  mcp
```

After each panel review/update, pin the profile and panel-directory SHA-256 values at startup. Use **Write snapshot** to create `profile.json`, then calculate both pins:

```powershell
(Get-FileHash D:/cut-bridges/premiere/profile.json -Algorithm SHA256).Hash
python -m cut_workbench.cli bridge-hash "$env:APPDATA/Adobe/CEP/extensions/com.cutworkbench.premiere"
```

Workbench rejects reads/publication if the profile, host version, or panel-directory content changes without updated startup pins. This is the explicit approval point for local connector updates. `profile.writable` indicates clone capability in that pinned panel version, not authorization for each publication.

## Install CEP panels in local development mode

Do not edit `.prproj` / `.aep` directly. Copy both panel directories into the current user's CEP extensions directory:

```powershell
$extensions = "$env:APPDATA/Adobe/CEP/extensions"
Copy-Item adapters/cep-local/premiere "$extensions/com.cutworkbench.premiere" -Recurse
Copy-Item adapters/cep-local/after-effects "$extensions/com.cutworkbench.aftereffects" -Recurse
```

These unsigned development panels require CEP `PlayerDebugMode` in Adobe 2023 and a restart of the corresponding application. Open **Cut Workbench Bridge** through **Window > Extensions** in Premiere or AE. The operator performs the registry change and file-copy installation; panels neither listen on ports nor call cloud services.

Enter the same bridge directory as the CLI in each panel. Keep authorization unchecked for `sync.open` / `sync.preview`. The panel writes this live choice to unpinned `authorization.json`. Check **Permit clone publish** only after preview review, then run `sync.commit` and `sync.publish`. Both Workbench when queuing and the panel when executing check authorization. Panels never overwrite source projects.

Select the corresponding adapter when creating a project, for example:

```json
{
 "project_id": "brand-film-pr",
  "title": "Brand film",
  "canvas": {"width": 1920, "height": 1080, "fps": 30},
  "editor_adapter": "premiere:cep-local"
}
```

## Local file protocol between panels and Workbench

Only the current Windows user should have read/write access to the bridge directory. Keep it off synced disks, shared directories, and network mounts; panels must not listen on non-loopback ports.

### `profile.json` (written by the panel)

```json
{
  "protocol_version": 1,
  "adapter_id": "premiere:cep-local",
  "editor_version": "23.0",
  "writable": true
}
```

### `snapshot.json` (written by the panel)

Overwrite this file after human changes, active project/sequence changes, or read requests. `snapshot` is a standard Workbench external snapshot containing `adapter_id`, stable `draft_id`, content `fingerprint`, tracks, materials, entities, and `native_summary`. Every agent-editable field needs a stable path in `entities.*.property_paths`.

```json
{
  "protocol_version": 1,
  "adapter_id": "premiere:cep-local",
  "draft_path": "D:/Projects/rough-cut.prproj",
  "snapshot": {
    "schema_version": 1,
    "adapter_id": "premiere:cep-local",
    "draft_id": "sequence-guid",
    "fingerprint": "sha256-or-host-state-fingerprint",
    "tracks": {},
    "materials": {},
    "entities": {},
    "native_summary": {}
  }
}
```

### `authorization.json` (written by the panel)

This is one-time local interactive authorization, not a code-integrity signal, so it is excluded from profile hash pinning. With `publish_enabled: false`, Workbench writes no publish command and the panel ignores even an existing command.

```json
{
  "protocol_version": 1,
  "adapter_id": "premiere:cep-local",
  "publish_enabled": false
}
```

### `commands/<request_id>.json` (written by Workbench)

For a `sync.publish` command, the panel first rereads the current project and checks `expected_fingerprint`. On mismatch it must not write, and must return a failure receipt requiring a new `sync.preview`.

```json
{
  "protocol_version": 1,
  "request_id": "...",
  "kind": "publish-clone",
  "adapter_id": "premiere:cep-local",
  "source_path": "D:/Projects/rough-cut.prproj",
  "destination_path": "D:/Projects/rough-cut-agent.prproj",
  "expected_fingerprint": "...",
  "patches": [{"op": "set", "path": "/...", "value": 1.25}]
}
```

### `responses/<request_id>.json` (written by the panel)

In Premiere, first `Save As` to `destination_path`; in AE, save a new `.aep`. Apply patches to the copy and read its new fingerprint. Do not save or rewrite the source.

```json
{
  "protocol_version": 1,
  "request_id": "...",
  "status": "published",
  "source_path": "D:/Projects/rough-cut.prproj",
  "destination_path": "D:/Projects/rough-cut-agent.prproj",
  "source_fingerprint": "...",
  "result_fingerprint": "...",
  "applied_patches": [],
  "adapter_id": "premiere:cep-local",
  "result_snapshot": {
    "schema_version": 1,
    "adapter_id": "premiere:cep-local",
    "draft_id": "sequence-guid",
    "fingerprint": "...",
    "tracks": {},
    "materials": {},
    "entities": {},
    "native_summary": {}
  }
}
```

Before including the copy in the next loop, Workbench verifies its existence, unchanged source bytes, and consistency between `result_snapshot.fingerprint` and the receipt.

## Current hard limits and next steps

- Premiere does not expose timeline position, speed, or Transform writes to agents; CEP generates paths only for explicit source in/out fields.
- The AE panel generates paths only for unkeyframed Layer Transform. Agents will not generate patches for them until Workbench adds typed-layer binding. Keyframes, expressions, text, and effects remain opaque.
- Dynamic Link currently enters the external ledger through both native summaries; it is not a structured cross-project diff and cannot automatically edit PR project items and AE compositions bidirectionally.
- Next: an explicit typed ledger for Dynamic Link relationships and the same restricted protocol for Premiere UXP 25.6+.

The protocol excludes direct `.prproj` / `.aep` rewriting, arbitrary agent-supplied ExtendScript/eval, native patches outside the allowlist, and overwriting originals.
