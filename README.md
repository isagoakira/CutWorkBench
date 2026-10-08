# Cut Workbench

A local-first, agent-neutral video editing control layer built around editable projects.

Cut Workbench manages project versions, stable IDs, evidence, conflicts, verification, and handoff. Through MCP, it connects Codex, Claude, or other agents to local analysis tools, Jianying, Premiere Pro, After Effects, and local VectCutAPI, without trying to rebuild a nonlinear editor.

Its core goal: **after automation, people can still edit tracks, segments, captions, effects, and native projects.**

## Quick start: Windows + Jianying Pro

For users who already have Jianying Pro and want any stdio MCP agent to create local editable drafts, render review versions, and inspect audio/video streams. The entire path uses local `127.0.0.1`, requires no cloud VectCut key, and excludes ASR.

1. Download or clone this repository; install and open Jianying Pro at least once.
2. Open PowerShell in the repository root and run the installer once:

   ```powershell
   PowerShell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\install-local-editing.ps1 `
     -InstallPrerequisites `
     -StartService
   ```

3. Check the local service, Jianying draft directory, FFmpeg/ffprobe, and visual acceptance package:

   ```powershell
   .\scripts\windows\doctor-local-editing.ps1
   ```

4. Import the `cut-workbench` entry from the generated `%LOCALAPPDATA%\CutWorkbench\agent-mcp-config.json` into your agent configuration. Before first use, run a real draft acceptance check with a local video at least 6 seconds long:

   ```powershell
   .\scripts\windows\smoke-local-editing.ps1 -Source 'D:\videos\demo.mp4'
   ```

The installer creates an isolated Python environment and configures local VectCutAPI, FFmpeg/ffprobe, and the default visual acceptance package. It does not overwrite existing Jianying drafts or directly modify `draft_content.json`. For a custom draft directory, add `-JianyingDraftFolder 'D:\your-draft-directory'`. See [Windows local Jianying editing setup](docs/windows-local-editing-setup.md) for troubleshooting, daily startup/shutdown, and compatibility boundaries.

## macOS / Linux installation (including WSL)

The cloud-free installer creates an isolated Python environment, local VectCutAPI, FFmpeg/ffprobe, optional visual acceptance tools, and agent stdio MCP configuration. On macOS, final acceptance must verify opening and playback in actual Jianying Pro. Linux and WSL verify local services, generated draft files, and media processing only; they do not establish native Jianying GUI acceptance.

```bash
bash ./scripts/posix/install-local-editing.sh --install-prerequisites --start-service
bash ./scripts/posix/doctor-local-editing.sh
```

Linux/WSL require an explicitly supplied, existing, writable Jianying draft directory. The default installation state directory is `${XDG_STATE_HOME:-$HOME/.local/state}/cut-workbench` on Linux/WSL and `~/Library/Application Support/CutWorkbench` on macOS. See [macOS / Linux local Jianying editing setup](docs/posix-local-editing-setup.md) for installation, Ubuntu 22.04 Python version restrictions, daily service management, and smoke acceptance.

## Why it exists

Many AI editing tools depend on subscriptions, output only flattened videos, or couple the agent, model, and editor. Cut Workbench separates their responsibilities:

- Agents handle understanding, judgment, planning, and high-precision visual tasks.
- Local programs such as Whisper, FFmpeg, ffprobe, and PySceneDetect handle reproducible lightweight tasks.
- Workbench stores immutable revisions, stable entities, audit evidence, and conflict decisions.
- Jianying, Premiere, AE, or VectCut retain project structures that people can edit further.
- Project data and MCP tools remain stable when the agent platform or local model changes.

## Current capabilities

| Capability | Status |
| --- | --- |
| Versioned projects, atomic edit plans, branching, immutable handoff | Available |
| Named video/audio/caption/effect/sticker tracks | Available |
| Separable segments, Transform, Mask, Keyframe, Effect controls | Available |
| Local/agent capability routing and persistent job queues | Available |
| Cut Protocol structural verification, visual evidence gates, manifests | Available |
| Local VectCut editable multitrack draft generation | Enabled by default; `vectcut.execute` connects to local `127.0.0.1:9001` and fails explicitly if the service is unavailable |
| Jianying Pro 11.3 bidirectional three-way synchronization | Available; requires an external codec sidecar |
| Incremental application to an open Jianying editor | Bridge protocol and `sync.apply` available; requires a controlled local bridge on the Jianying side |
| Premiere Pro 2023 CEP bridge | Available; typed writes currently cover source in/out points |
| After Effects 2023 CEP bridge | Snapshots and opaque preservation available; typed layer merging unfinished |
| Structured bidirectional Dynamic Link editing | Unfinished; native relationships are currently preserved as opaque data |

The project bundles no model weights, Adobe software, Jianying codec, or cloud services, and requires no local LLM.

## Architecture overview

```text
Codex / Claude / other agents
             │
          MCP tools
             │
       Cut Workbench
      ┌──────┼──────────┐
      │      │          │
 revisions  capability  editor adapters
 + audit    router      ├─ Jianying
      │      │          ├─ Premiere CEP
      │      ├─ local   └─ After Effects CEP
      │      └─ agent
      └─ VectCut compile + local execution
```

Workbench revisions are the source of truth. External editors are collaborators. VectCut is the default local editable-draft target; rendered files do not replace editable projects.

## Requirements

- Python 3.11 or later.
- Windows PowerShell examples can be used directly; core Python code has no third-party runtime dependencies.
- `ffprobe` is the default local media probing provider. Install FFmpeg separately and add it to `PATH`.
- Other local models and analyzers connect through JSON stdin/stdout sidecars.
- External editor synchronization requires the corresponding local editor and adapter components.

## Developer installation

```powershell
git clone git@github.com:isagoakira/CutWorkBench.git
Set-Location CutWorkBench
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Verify installation:

```powershell
cut-workbench --root D:/cut-runtime list-tools
```

Alternatively, run directly from source:

```powershell
$env:PYTHONPATH = 'src'
python -m cut_workbench.cli --root D:/cut-runtime list-tools
```

## Configuration resolution and call chain

`runtime-config.json` is a combined configuration: a single file can declare local capability providers, routing policy, and local VectCutAPI settings. These are not three files that overwrite one another. The minimum VectCut configuration is below; Workbench retains its default `ffprobe` provider even if the file contains only `vectcut`.

```json
{
  "vectcut": {
    "base_url": "http://127.0.0.1:9001",
    "timeout": 120,
    "draft_folder": "E:/JianYing/JianyingPro Drafts"
  }
}
```

File selection order: explicit `--config <path>` → `<root>/runtime-config.json` (autoloaded only when `--config` is absent) → built-in defaults. Within the selected configuration, VectCut endpoint precedence is `--vectcut-url` → `vectcut.base_url` → `CUT_WORKBENCH_VECTCUT_URL` → `http://127.0.0.1:9001`. Draft directory precedence is `--vectcut-draft-folder` → `vectcut.draft_folder` → the platform's default Jianying draft root. `--config` does not merge a second file.

VectCut endpoints must be local loopback HTTP(S) services such as `localhost`, `127.0.0.1`, or `::1`, so `vectcut.execute` cannot silently switch to the cloud. See [Runtime configuration](docs/runtime-configuration.md) for fields, examples, and troubleshooting.

```text
--config / <root>/runtime-config.json
              │
              ├─ providers + routing ──→ capability.request
Agent / CLI ──┼─ vectcut endpoint ─────→ vectcut.health → compile → execute → new Jianying draft
  stdio MCP   │
              └─ editor settings ──────→ sync.open → preview → commit → publish / apply
                       │
                 project.inspect → project.apply_plan → verify → manifest
```

## Local deployment

The Workbench core needs no Docker, database, web service, or local LLM. It runs as a local Python process communicating with the agent through stdio MCP. Project revisions, journals, capability jobs, and editor sync sessions are stored in the runtime directory specified by `--root`.

Keep the runtime directory outside the source checkout. Separate code, runtime state, project materials, and local tools:

```text
D:/projects/CutWorkBench/     # Repository and Python virtual environment
D:/cut-runtime/              # Revisions, journal, capability jobs, sync sessions
D:/video-projects/           # Original media, editing projects, subtitles, deliverables
D:/cut-config/               # Local configuration such as runtime-config.json
D:/tools/                    # Whisper, TTS, codec, and other sidecars
```

Create the runtime directory and run a health check:

```powershell
$workbenchRoot = 'D:/cut-runtime'
New-Item -ItemType Directory -Force $workbenchRoot | Out-Null
cut-workbench --root $workbenchRoot list-tools
```

Workbench does not listen on a network port. Agents usually start stdio MCP on demand:

```powershell
cut-workbench --root D:/cut-runtime mcp
```

### Add local components as needed

| Component | Required? | Integration |
| --- | --- | --- |
| FFmpeg / `ffprobe` | Recommended | Install FFmpeg and add it to `PATH` for local media probing. |
| Whisper, shot/silence/beat detection | Optional | Configure as `json-command` sidecars. |
| GPT-SoVITS, CosyVoice, other TTS | Optional | Use an `audio.synthesize.tts` sidecar; see below. |
| Jianying Pro | Optional | Supply a local codec sidecar and pin its version and SHA-256. |
| Premiere Pro / After Effects | Optional | Install the supplied CEP panels and local file bridge; snapshot/preview before authorizing clone publication. |
| TapNow | Optional | Compile locked scripts, storyboards, and material plans into Canvas nodes, Ask-mode execution briefs, and web handoff packages. The TapNow agent executes in the web UI without calling unpublished APIs. |
| VectCutAPI | Required for automatic draft creation | Run locally at `127.0.0.1:9001`; Workbench compiles and writes editable drafts by default. |

Recommended order: **core MCP → local VectCutAPI → Jianying → FFmpeg → Whisper/TTS → Premiere/AE → TapNow**. Project auditing remains available without VectCutAPI, but `vectcut.execute` explicitly blocks automatic editable Jianying draft creation.

### Local VectCutAPI: default automatic draft path

Cut Workbench defaults to `http://127.0.0.1:9001`, accepts only loopback endpoints, does not call `open.vectcut.com`, and requires no `VECTCUT_API_KEY`. Deploy open-source VectCutAPI on the same machine as Jianying:

Windows users should prefer `scripts/windows/install-local-editing.ps1`; macOS/Linux users should prefer `bash scripts/posix/install-local-editing.sh` to the developer commands below. Both installers pin a tested upstream commit and Jianying draft profile, start the service, and provide `doctor` checks.

```powershell
git clone https://github.com/sun-guannan/VectCutAPI.git D:/tools/VectCutAPI
Set-Location D:/tools/VectCutAPI
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python D:/projects/CutWorkBench/scripts/serve_vectcut.py --repo D:/tools/VectCutAPI
```

macOS uses the same repository and Python environment. Install Jianying Pro first, then start the service:

```bash
git clone https://github.com/sun-guannan/VectCutAPI.git ~/tools/VectCutAPI
cd ~/tools/VectCutAPI
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt
python /path/to/CutWorkBench/scripts/serve_vectcut.py --repo ~/tools/VectCutAPI
```

Before startup, create `config.json` in the VectCutAPI repository root. Upstream defaults to the international editor and port 9000, so do not use those defaults unchanged:

```json
{"draft_profile":"jianying_pro_10","is_capcut_env":false,"port":9001,"is_upload_draft":false,"draft_domain":"http://127.0.0.1:9001"}
```

`serve_vectcut.py` binds loopback on Windows/macOS/Linux, defaulting to port 9001. FFmpeg's `ffprobe` must be in the service process's PATH. The upstream template targets Jianying 10.x. Successful generation and opening in the installed editor are separate acceptance checks. macOS editor acceptance requires a real machine; WSL establishes only Linux service execution.

Configure the draft root to avoid writing to the wrong disk or custom installation path. Default candidates are `%LOCALAPPDATA%/JianyingPro/User Data/Projects/com.lveditor.draft` on Windows and `~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft` on macOS. Override them if your actual directory differs:

```json
{
  "vectcut": {
    "base_url": "http://127.0.0.1:9001",
    "timeout": 120,
    "draft_folder": "E:/JianYing/JianyingPro Drafts"
  }
}
```

Saving this as `runtime-config.json` under `--root` enables automatic loading; `--config` selects another file explicitly. The same file can contain `providers` and `routing`; see [Runtime configuration](docs/runtime-configuration.md):

```powershell
cut-workbench --root D:/cut-runtime --config D:/cut-config/runtime-config.json call vectcut.health '{}'
```

After the health check, call `vectcut.execute`. It compiles the specified revision, creates a draft, writes materials/tracks/subtitles/effects, and saves a new draft, refusing to overwrite an existing one. After saving, it checks job status, actual files, entity counts, timeline positions, and media files. Plans and receipts are written to `vectcut-executions/` in the runtime directory.

```powershell
cut-workbench --root D:/cut-runtime --config D:/cut-config/runtime-config.json call vectcut.execute '{"project_id":"demo","revision":2}'
```

Real-media smoke test: source media must be at least 6 seconds; the test generates two clips with source in-points and verifies source SHA-256:

```bash
PYTHONPATH=src python scripts/smoke_vectcut.py --source /path/to/video.mov --root /path/to/smoke-runtime --draft-folder /path/to/jianying-drafts
```

## Connect an agent

Any stdio MCP agent can use the same launch configuration:

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

Add `--config D:/cut-config/runtime-config.json` for local Whisper, shot detection, or custom TTS sidecars. See [Runtime configuration](docs/runtime-configuration.md) and [examples/runtime-config.json](examples/runtime-config.json). Any program that reads one JSON request from stdin and writes one JSON result to stdout can be a `json-command` provider without changes to the core.

## Core workflow

```text
project.create
      ↓
capability.request ──→ local result / pending_agent ──→ capability.submit
      ↓
project.inspect → project.apply_plan → new revision
      ↓
project.verify → project.manifest
      ↓
├─ vectcut.health → vectcut.compile → vectcut.execute (new editable draft)
└─ sync.open → sync.preview → sync.commit → sync.publish clone / sync.apply live
```

Key rules:

- Call `project.inspect` before every mutation and use the current revision as `expected_revision`.
- Original media remains unchanged; segments store source ranges and timeline positions.
- Keep effects, captions, treatment copies, and audio in separate tracks or controls where possible.
- `pending_agent` is normal: the agent completes the task and submits evidence through `capability.submit`.
- Preview before external editor synchronization; explicitly resolve conflicts as `human` or `agent`.
- `sync.publish` creates a new copy and never overwrites the original Jianying, `.prproj`, or `.aep` project. Without `destination_path`, names default to `project-name-vN-specific-change`; use `release_version` and `change_summary` to specify them.
- While Jianying is open, submit new requirements as Workbench revisions. At an acceptance point, close Jianying once and publish the latest committed session. `reopen_editor: true` in `sync.publish` relaunches Jianying after registering the safe copy. Jianying exposes no public “open specific draft” launch argument, so select the latest named copy in its draft library.
- For an open Jianying editor, use the separate `jianying:live-local` adapter with `sync.open → sync.preview → sync.commit → sync.apply`. A Jianying-side bridge applies fingerprinted allowlist patches to the current timeline without generating draft copies or writing to the open `draft_content.json`. Missing bridges or mismatched receipts cause explicit refusal rather than forced file writes.
- Bound A/V segments can replace media, change tracks, or reorder while retaining stable IDs. Media replacement adds a material record to the cloned Jianying draft and redirects only the target segment, preserving the original media record. Arbitrary timeline additions, removals, and restructuring compile through local VectCut into a new editable draft.
- `handed_off` revisions are immutable; branch first to continue editing.

## MCP tools

| Group | Tools |
| --- | --- |
| Project | `project.create`, `project.inspect`, `project.apply_plan`, `project.branch` |
| Verification | `project.verify`, `project.manifest` |
| Production workflow | `workflow.contract`, `workflow.status` |
| Capabilities | `capability.request`, `capability.pending`, `capability.submit` |
| Generation orchestration | `generation.contract`, `generation.request`, `generation.pending`, `generation.reconciliation`, `generation.claim`, `generation.heartbeat`, `generation.approve`, `generation.authorize`, `generation.submit` |
| Local VectCut | `vectcut.health`, `vectcut.compile`, `vectcut.execute` |
| External editors | `sync.open`, `sync.preview`, `sync.commit`, `sync.publish`, `sync.apply` |
| TapNow context engineering | `tapnow.context.compile`, `tapnow.assets.stage`, `tapnow.web.handoff`, `tapnow.canvas.reconcile` |

Run `cut-workbench --root D:/cut-runtime list-tools` for complete JSON Schemas.

## Local analysis and voiceover

Configure lightweight tasks as local providers and reserve high-precision work for the agent. Default policies include media probing, word-level transcription, silence/beat/shot detection, frame understanding, edit planning, and semantic verification.

### Configure local TTS

Local TTS connects through the same capability seam. Wrap GPT-SoVITS, CosyVoice, or another engine in a JSON stdin/stdout sidecar and create a configuration such as `D:/cut-config/runtime-config.json`:

```json
{
  "providers": [
    {
      "kind": "ffprobe",
      "executable": "ffprobe"
    },
    {
      "kind": "json-command",
      "provider_id": "local:gpt-sovits",
      "capabilities": ["audio.synthesize.tts"],
      "command": ["python", "D:/tools/tts_sidecar.py"],
      "timeout": 3600
    }
  ],
  "routing": {
    "default_route": "agent",
    "rules": {
      "media.probe": {"standard": "local", "high": "local"},
      "audio.synthesize.tts": {"standard": "local", "high": "local"}
    }
  }
}
```

Load it at startup:

```powershell
cut-workbench --root D:/cut-runtime `
  --config D:/cut-config/runtime-config.json `
  mcp
```

`json-command` launches processes directly from the `command` array without a shell. Workbench writes one JSON object to sidecar stdin. Suggested TTS fields:

```json
{
  "capability": "audio.synthesize.tts",
  "inputs": {
    "text": "Welcome to TiMEM Space.",
    "output_path": "D:/video-project/06_voiceover-and-audio/VO_S01_001.wav",
    "voice_id": "speaker-01",
    "reference_audio": "D:/voices/speaker-01.wav"
  },
  "quality": "standard",
  "sensitivity": "local-only",
  "constraints": {
    "sample_rate": 48000,
    "format": "wav"
  }
}
```

Sidecar stdout must contain only one result object; write logs to stderr:

```json
{
  "payload": {
    "audio_path": "D:/video-project/06_voiceover-and-audio/VO_S01_001.wav",
    "duration_seconds": 2.84,
    "sample_rate": 48000,
    "voice_id": "speaker-01"
  },
  "evidence": [
    "D:/video-project/06_voiceover-and-audio/VO_S01_001.wav"
  ]
}
```

Verify routing and the sidecar directly:

```powershell
cut-workbench --root D:/cut-runtime `
  --config D:/cut-config/runtime-config.json `
  call capability.request '{"capability":"audio.synthesize.tts","inputs":{"text":"Voiceover test","output_path":"D:/cut-runtime/tts-test.wav"},"quality":"standard","sensitivity":"local-only","constraints":{"format":"wav"}}'
```

`audio.synthesize.tts` prefers an available local provider. If none declares that capability, the job falls back to `pending_agent` instead of claiming successful local generation. Generate separate audio files and segments per subtitle cue, retaining reference audio, natural-duration versions, fitted versions, and measurements; do not keep only one indivisible full-track WAV.

The repository contains no TTS models, voice weights, or machine-specific absolute paths.

## External editors

### Jianying

The adapter performs a three-way merge between baseline A, current Workbench B, and current human draft C. Unknown captions, stickers, effects, and compound clips are preserved as opaque external entities. The file adapter publishes safe copies only after Jianying closes; incremental updates to an open editor use `jianying:live-local` and `sync.apply`. See [docs/jianying-sync.md](docs/jianying-sync.md).

### Premiere Pro / After Effects

The repository supplies local CEP panel source and a restricted file bridge. Panels do not authorize publication by default. Only after a person reviews the preview and enables authorization can Workbench write an allowlist patch to a new project copy. Panel packages, host versions, and profiles are SHA-256 pinned. See [docs/adobe-local-bridge.md](docs/adobe-local-bridge.md).

## Safety and recoverability

- Every project mutation creates a new revision and journal record.
- Revision conflicts do not automatically retry or overwrite concurrent changes.
- Unmodeled editor objects remain as opaque data.
- Unsupported compilation capabilities fail explicitly or require a recorded, human-approved downgrade.
- Publication verifies source hashes, copy existence, panel identity, actual patches, and result snapshots before and after writing.
- Subjective visual quality requires actual visual evidence; structural tests cannot establish it.

## Documentation

- [Complete usage guide](docs/usage-guide.md)
- [Windows local Jianying editing setup](docs/windows-local-editing-setup.md)
- [macOS / Linux local Jianying editing setup](docs/posix-local-editing-setup.md)
- [Architecture and stable boundaries](docs/architecture.md)
- [Implementation specification and non-goals](docs/spec.md)
- [Bidirectional Jianying synchronization](docs/jianying-sync.md)
- [TapNow context engineering](docs/tapnow-context-engineering.md)
- [Local Premiere / After Effects bridge](docs/adobe-local-bridge.md)
- [Runtime configuration and call chain](docs/runtime-configuration.md)
- [Premiere / AE open-source research](docs/premiere-after-effects-open-source-research.md)
- [Runtime configuration example](examples/runtime-config.json)
- [Edit plan example](examples/edit-plan.json)

## Development and testing

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
python -m compileall -q src
```

## Current limitations

- This control plane provides no timeline GUI, player, or renderer.
- Local VectCutAPI is required for automatic draft creation. Without it, `vectcut.execute` fails without falling back to the cloud or manual import.
- The Jianying codec is not bundled; the operator must supply it and pin its SHA-256.
- The Premiere CEP typed writer currently covers only explicitly exposed source in/out points.
- Full typed bidirectional mapping for AE layers, Dynamic Link, and Premiere speed/position/Transform remains on the roadmap.
- This project does not cover fees charged by cloud agents, models, or third-party generation services. Entirely local paths can avoid them.

## License

Apache-2.0; see project metadata in [pyproject.toml](pyproject.toml).
