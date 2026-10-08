# Cut Workbench complete usage guide

Starting from an empty directory, this tutorial covers installation, agent integration, project creation, local/agent capability routing, edit plans, verification, manifests, and safe bidirectional synchronization with Jianying or Adobe projects.

Examples use Windows PowerShell and Python 3.11+. Replace all paths with your actual locations.

## 1. Installation and health checks

```powershell
git clone git@github.com:isagoakira/CutWorkBench.git
Set-Location CutWorkBench
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Choose a separate runtime directory for revisions, journals, capability jobs, and sync sessions; do not use the source directory itself:

```powershell
$workbenchRoot = 'D:/cut-runtime'
cut-workbench --root $workbenchRoot list-tools
```

Output should include tools such as `project.create`, `project.apply_plan`, `capability.request`, `project.verify`, and `sync.open`.

To run without installing the package:

```powershell
$env:PYTHONPATH = 'src'
python -m cut_workbench.cli --root $workbenchRoot list-tools
```

## 2. Make the first call through CLI

The CLI `call` subcommand uses the same interface as MCP, useful for installation checks and troubleshooting.

```powershell
$createRequest = @'
{
  "project_id": "tutorial-01",
  "title": "Tutorial project",
  "canvas": {"width": 1920, "height": 1080, "fps": 30},
  "editor_adapter": "unassigned"
}
'@

cut-workbench --root $workbenchRoot call project.create $createRequest
cut-workbench --root $workbenchRoot call project.inspect '{"project_id":"tutorial-01"}'
```

New projects start at revision 1. Each successful `project.apply_plan` creates a new immutable revision.

## 3. Connect Codex or another MCP agent

Add to the agent MCP configuration:

```json
{
  "mcpServers": {
    "cut-workbench": {
      "command": "python",
      "args": ["-m", "cut_workbench.cli", "--root", "D:/cut-runtime", "mcp"],
      "cwd": "D:/projects/CutWorkBench",
      "env": {"PYTHONPATH": "src"}
    }
  }
}
```

Refresh the agent MCP connection. Require `project.inspect` before every mutation. Agent platforms call MCP only; project schemas, revisions, and domain rules remain in Workbench.

## 4. Configure local analysis providers

Without `--config`, Workbench still registers default `ffprobe`. After installing FFmpeg, call:

```powershell
$probeRequest = @'
{
  "capability": "media.probe",
  "inputs": {"media_path": "D:/media/source.mp4"},
  "quality": "standard",
  "sensitivity": "local-only",
  "constraints": {}
}
'@

cut-workbench --root $workbenchRoot call capability.request $probeRequest
```

For Whisper or other sidecars, copy and modify [runtime-config.json](../examples/runtime-config.json):

```json
{
  "providers": [
    {"kind": "ffprobe", "executable": "ffprobe"},
    {
      "kind": "json-command",
      "provider_id": "local:whisper-sidecar",
      "capabilities": ["audio.transcribe.words"],
      "command": ["python", "D:/tools/whisper_sidecar.py"],
      "timeout": 3600
    }
  ],
  "routing": {
    "default_route": "agent",
    "rules": {
      "media.probe": {"standard": "local", "high": "local"},
      "audio.transcribe.words": {"standard": "local", "high": "agent"},
      "video.interpret.frames": {"standard": "agent", "high": "agent"}
    }
  }
}
```

Load the configuration at startup:

```powershell
cut-workbench --root $workbenchRoot --config D:/cut-config/runtime-config.json mcp
```

`--config` selects a combined configuration; declaring only `vectcut`, `routing`, or one sidecar does not remove default `ffprobe`. The same file can configure VectCutAPI. See [Runtime configuration](runtime-configuration.md) for file selection, field precedence, and loopback restrictions.

### Sidecar protocol

A `json-command` provider writes one request JSON to program stdin. The sidecar writes only one result object to stdout:

```json
{
  "payload": {"words": []},
  "evidence": ["D:/evidence/transcript.words.json"]
}
```

Write logs to stderr. Nonzero exit codes, timeouts, or invalid JSON create failed jobs rather than false successes.

### Agent-native tasks

When policy selects `agent`, `capability.request` returns a `pending_agent` job. After completion, call `capability.submit`:

```json
{
  "job_id": "returned job_id",
  "agent_id": "codex",
  "payload": {"result": "Structured result"},
  "evidence": ["evidence/frame-review.json"]
}
```

`pending_agent` is normal. Do not submit without actual results and evidence.

## 5. Create your first editable editing project

Calculate source SHA-256 first:

```powershell
$sourcePath = 'D:/media/source.mp4'
$sourceHash = (Get-FileHash $sourcePath -Algorithm SHA256).Hash.ToLower()
```

First get the current revision with `project.inspect`, then submit sources, tracks, segments, captions, and audit decisions together. This example assumes 12-second media; use the actual duration:

```powershell
$plan = @"
{
  "project_id": "tutorial-01",
  "expected_revision": 1,
  "actor": "agent:codex",
  "reason": "Register source and create editable base and caption tracks",
  "operations": [
    {
      "op": "register_source",
      "source_id": "SRC-001",
      "locator": "$sourcePath",
      "sha256": "$sourceHash",
      "media_profile": {"duration": 12.0}
    },
    {"op": "add_track", "track_id": "V1-BASE", "kind": "video", "purpose": "base"},
    {"op": "add_track", "track_id": "S1-CAPTIONS", "kind": "caption", "purpose": "captions"},
    {
      "op": "add_segment",
      "segment_id": "SEG-001",
      "source_id": "SRC-001",
      "track_id": "V1-BASE",
      "source_in": 1.0,
      "source_out": 8.0,
      "timeline_start": 0.0,
      "speed": 1.0,
      "role": "primary"
    },
    {
      "op": "add_caption",
      "caption_id": "CAP-001",
      "track_id": "S1-CAPTIONS",
      "start": 0.2,
      "end": 2.8,
      "text": "This is the first editable caption",
      "speech_evidence": "evidence/transcript.words.json"
    },
    {
      "op": "record_decision",
      "decision_id": "DEC-AUDIT-SRC001",
      "kind": "source_audit",
      "summary": "Full source audit at 2 fps",
      "source_id": "SRC-001",
      "evidence": ["evidence/SRC-001/contact-sheet-2fps.jpg"],
      "data": {
        "sample_fps": 2,
        "sample_count": 24,
        "coverage_range": {"start": 0, "end": 12.0},
        "escalations": []
      }
    }
  ],
  "evidence": ["evidence/editorial-selection.json"]
}
"@

cut-workbench --root $workbenchRoot call project.apply_plan $plan
```

If another caller has created a revision, the old `expected_revision` is rejected. Inspect again, understand the changes, and build a new plan; do not retry blindly.

### Track budget

Tracks represent simultaneous editorial roles that need independent adjustment, not containers per clip. Screen recordings default to one base video track; silent deliveries have no audio track. Add one track each for captions, narration, music, or annotations only when independent timelines are needed. Sequential clips reuse tracks. See [Conservative track policy](track-usage-policy.md).

## 6. Add effects while preserving separability

Use `add_control` for same-track Transform, Mask, Mask Blur, and Keyframe controls; independent effects use an `effect` track:

```json
{
  "op": "add_control",
  "control_id": "CTRL-ZOOM-001",
  "target_segment_id": "SEG-001",
  "track_id": "V1-BASE",
  "kind": "transform",
  "active_range": {"start": 1.0, "end": 3.0},
  "properties": {"scale": 1.08, "anchor": [0.5, 0.5]},
  "keyframes": [],
  "editable": true,
  "baked": false
}
```

Do not silently bake unsupported target capabilities. First record reason, fallback, and approver with `record_downgrade`; the baked control then references `approved_exception_id`.

For tighter edits, use `update_segment` and `update_caption` to retain stable IDs. Remove empty tracks with `remove_track` only after confirming no segments, controls, or captions remain. Do not delete/recreate the same logical object or add tracks per overlay or segment.

## 7. Verification and manifest

```powershell
cut-workbench --root $workbenchRoot call project.verify '{"project_id":"tutorial-01"}'
cut-workbench --root $workbenchRoot call project.manifest '{"project_id":"tutorial-01"}'
```

Common failures:

- `source-audit-missing`: Missing full-source audit evidence sampled at least at 2 fps.
- `source-hash-missing`: Source lacks a 64-character SHA-256.
- `track-overlap`: Segments overlap on one video/audio track.
- `track-gap`: Base-track gap lacks an `intentional_gap` decision.
- `visual-verification-missing`: Review/delivery/handoff lacks visual evidence matching the current content fingerprint.

The manifest comes directly from the same revision and includes sources, rough-cut mapping, controls, captions, decisions, downgrades, and verification status.

## 8. Compile a VectCut plan

Confirm `vectcut` points to a loopback service and set `draft_folder` or `--vectcut-draft-folder` to the actual draft directory. Runtime `runtime-config.json` loads automatically; use `--config` for another location. See [Runtime configuration](runtime-configuration.md).

```powershell
cut-workbench --root $workbenchRoot call vectcut.compile '{"project_id":"tutorial-01","draft_folder":"D:/drafts/tutorial-01"}'
```

The tool returns an auditable call plan without network access or rendering. Unsupported controls or opaque external entities cause explicit rejection to prevent silent loss of native objects.

The default local path provides `vectcut.health` and `vectcut.execute`. After starting local VectCutAPI, use `call vectcut.execute '{"project_id":"tutorial-01","revision":2,"draft_folder":"D:/drafts"}'` to generate a new draft. The receipt contains its actual path; execution verifies persisted files/media and saves call receipts. See Windows/macOS deployment in the README.

## 9. Bidirectional Jianying synchronization

The Jianying adapter requires an external codec matching the installed version, with mandatory SHA-256 pinning:

```powershell
cut-workbench `
  --root $workbenchRoot `
  --jianying-codec C:/tools/jy-draftc.exe `
  --jianying-install E:/JianYing/JianyingPro/11.3.0.14362 `
  --jianying-version 11.3.0.14362 `
  --jianying-codec-sha256 <VERIFIED_SHA256> `
  mcp
```

Transaction order:

1. `sync.open` pins the Workbench revision, codec profile, and baseline Jianying snapshot.
2. Edit in Workbench and Jianying.
3. `sync.preview` compares baseline A, current agent state B, and human draft C.
4. `sync.commit` explicitly selects `human` or `agent` for every conflict.
5. Close Jianying and run `sync.publish` with a new, nonexistent destination directory.
6. Open the clone for actual visual inspection; preserve the source as rollback baseline.

### Incremental changes while Jianying stays open

With `jianying:live-local`, do not use the codec file publisher. A Jianying-side bridge connects to the current draft and writes snapshots. After initial connection, each request in the same editor session can use:

1. `sync.open` connects to the current draft.
2. Edit in Workbench, then run `sync.preview` and `sync.commit`.
3. Run `sync.apply`; the Jianying-side bridge updates the open timeline.

`sync.apply` has no `destination_path` and is not clone publication. It requires `live_apply_enabled`, matching baseline fingerprints, and complete receipts. Failure of any condition prevents draft-file writes. See [Bridge startup and protocol](jianying-sync.md#incremental-updates-to-an-open-jianying-editor).

Complete constraints:  [jianying-sync.md](jianying-sync.md).

## 10. Premiere Pro / After Effects bridge

Current Adobe 2023 CEP panel capabilities:

- `premiere:cep-local`: Active Sequence snapshots and source in/out writes to clones.
- `after-effects:cep-local`: Active Composition/Layer snapshots and opaque audits; typed layer binding is unfinished.

Install panel source:

```powershell
$cepExtensions = "$env:APPDATA/Adobe/CEP/extensions"
New-Item -ItemType Directory -Force $cepExtensions | Out-Null
Copy-Item adapters/cep-local/premiere "$cepExtensions/com.cutworkbench.premiere" -Recurse
Copy-Item adapters/cep-local/after-effects "$cepExtensions/com.cutworkbench.aftereffects" -Recurse
```

Unsigned development panels require CEP `PlayerDebugMode` in Adobe 2023 and an application restart. Open **Window → Extensions → Cut Workbench Bridge**, enter a private bridge directory, leave **Permit clone publish** unchecked, and click **Write snapshot**.

Calculate the profile and installed-panel-directory hashes:

```powershell
$premiereProfile = (Get-FileHash D:/cut-bridges/premiere/profile.json -Algorithm SHA256).Hash
$premierePanel = cut-workbench bridge-hash "$cepExtensions/com.cutworkbench.premiere"
```

Start the Premiere bridge:

```powershell
cut-workbench `
  --root $workbenchRoot `
  --premiere-bridge-root D:/cut-bridges/premiere `
  --premiere-bridge-kind cep `
  --premiere-profile-sha256 $premiereProfile `
  --premiere-version 23.0 `
  --premiere-panel-root "$cepExtensions/com.cutworkbench.premiere" `
  --premiere-panel-sha256 $premierePanel `
  mcp
```

Synchronization still uses `sync.open → sync.preview → sync.commit → sync.publish`. Authorize publication in the panel only after preview review. The destination must be a new, nonexistent `.prproj` or `.aep`. See [adobe-local-bridge.md](adobe-local-bridge.md).

## 11. Local SRT voiceover

Workbench is TTS-engine-neutral. Wrap GPT-SoVITS, CosyVoice, or another engine as a `json-command` provider:

```json
{
  "kind": "json-command",
  "provider_id": "local:gpt-sovits",
  "capabilities": ["audio.synthesize.tts"],
  "command": ["python", "D:/tools/tts_sidecar.py"],
  "timeout": 3600
}
```

Add explicitly to routing:

```json
"audio.synthesize.tts": {"standard": "local", "high": "local"}
```

Use one WAV and audio segment per SRT cue. Keep subtitles on a caption track and voiceover on a named dialogue track. Retain original SRT, reference audio, natural-duration WAVs, fitted WAVs, and evidence such as RTF/VRAM/duration error. Full-track WAVs are only listening/export conveniences.

## 12. Handoff, branching, and recovery

`handed_off` revisions permanently reject mutation. Call `project.branch` to continue:

```json
{
  "source_project_id": "tutorial-01",
  "new_project_id": "tutorial-01-revision-b",
  "revision": 5,
  "title": "Tutorial project revision B"
}
```

Preserve historical revisions, journals, original media, and external editor baselines.

## 13. Troubleshooting

### `RevisionConflict`

Another caller submitted a revision. Rerun `project.inspect`, understand changes, and rebuild the plan.

### Capability remains `pending_agent`

Routing selected the agent or a local provider is unavailable. Have the agent complete and `capability.submit`, or check capability names and commands in configuration.

### Local provider returns invalid JSON

Ensure stdout contains only one result JSON and all progress logs go to stderr.

### Jianying publication rejected

Confirm Jianying is closed, codec hash/version match, and destination does not exist. Preview again to refresh the fingerprint.

### Adobe profile/hash mismatch

Write a new panel snapshot, confirm the host version, calculate new installed-panel and `profile.json` hashes, then open a new session. Do not bypass pins.

### VectCut compilation rejects opaque entities

The compiler cannot prove lossless reconstruction of the native object. Continue external-editor round trips or implement typed importers/writers; do not delete the opaque ledger to force acceptance.

## 14. Final checklist

- Every source has real SHA-256, duration, and full 2 fps audit evidence.
- Current revision matches the agent's `expected_revision`.
- Base tracks, treatments, captions, effects, and dialogue remain separately selectable.
- Capability jobs are complete or explicitly pending in the handoff.
- Downgrades have reasons, fallbacks, and human approval.
- Visual evidence matches the current content fingerprint.
- External publication targets a new clone; the source remains unchanged.
- `project.verify` passes and `project.manifest` is saved.
- Further work after handoff starts from a branch.
