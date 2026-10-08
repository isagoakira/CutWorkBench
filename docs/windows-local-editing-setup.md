# Windows local Jianying editing setup

This installer packages the verified local path into user-facing scripts: **Jianying Pro + this repository + one-time installation**. Projects, media, and drafts stay local; it does not call cloud VectCut or require `VECTCUT_API_KEY`.

## Installed components

| Component | Purpose | Included in Jianying? |
| --- | --- | --- |
| Cut Workbench | Editable projects, versions, tracks, acceptance | No |
| Local VectCutAPI | Compile Workbench projects into new Jianying drafts | No |
| FFmpeg / ffprobe | Review rendering, duration and audio/video stream checks | No |
| OpenCV / Pillow | Dense keyframe contact sheets and visual acceptance | No; optional |
| Jianying Pro | Open generated drafts and continue manual editing | Yes; user installs it first |

Agents need only stdio MCP support and the generated configuration below, not built-in FFmpeg, visual libraries, or editing tools.

## Before installation

1. Install and open Jianying Pro at least once, create an empty draft, then close it.
2. Download/extract or clone this repository locally. ZIP downloads need no preinstalled Git; the installer uses `winget` when Git is needed.
3. Open PowerShell in the repository root.

The default draft directory is `%LOCALAPPDATA%\JianyingPro\User Data\Projects\com.lveditor.draft`. Supply custom directories explicitly; the script does not guess or scan other disks.

## One-time installation

```powershell
PowerShell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\install-local-editing.ps1 `
  -InstallPrerequisites `
  -StartService
```

`-InstallPrerequisites` uses `winget` to install missing Git, Python 3.11+, and FFmpeg; omit it if they are installed. Default installation: `%LOCALAPPDATA%\CutWorkbench`. Existing Jianying drafts and VectCutAPI configuration are preserved; pass `-ForceConfig` only to rewrite local settings.

For a custom draft directory:

```powershell
PowerShell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\install-local-editing.ps1 `
  -InstallPrerequisites `
  -JianyingDraftFolder 'D:\JianyingPro\User Data\Projects\com.lveditor.draft' `
  -StartService
```

Installation generates:

- `%LOCALAPPDATA%\CutWorkbench\runtime\runtime-config.json`: Local Workbench/VectCut/draft-directory configuration;
- `%LOCALAPPDATA%\CutWorkbench\agent-mcp-config.json`: Service configuration to copy into Codex, Claude Desktop, or another MCP agent;
- `%LOCALAPPDATA%\CutWorkbench\installation.json`: Installation receipt;
- `%LOCALAPPDATA%\CutWorkbench\service\`: Managed local VectCutAPI logs and service state.

## Daily startup, shutdown, and diagnostics

After each reboot, start the local automatic draft service:

```powershell
.\scripts\windows\start-local-editing.ps1
```

Check critical dependencies, draft permissions, local service, and visual acceptance tools:

```powershell
.\scripts\windows\doctor-local-editing.ps1
```

Perform read-only audio/video stream inspection without transcription or draft creation:

```powershell
.\scripts\windows\doctor-local-editing.ps1 -MediaPath 'D:\videos\demo.mp4'
```

The stop script terminates only the local VectCutAPI process recorded by `start-local-editing.ps1`:

```powershell
.\scripts\windows\stop-local-editing.ps1
```

## First real-draft acceptance

Before first Jianying use, run a smoke test on a local video at least 6 seconds long. It creates a new short draft without changing original media or existing drafts:

```powershell
.\scripts\windows\smoke-local-editing.ps1 -Source 'D:\videos\six-seconds-or-longer.mp4'
```

The script verifies two real cuts, timeline continuity, source SHA-256, local VectCutAPI calls, and persisted draft files. Then manually verify visibility/playback in the Jianying Pro draft library; file generation does not establish compatibility with the installed version.

## Agent integration

Import the `cut-workbench` entry from generated `agent-mcp-config.json` into your agent. It starts local stdio MCP. Project edits create Workbench revisions; `vectcut.execute` creates new editable Jianying drafts through `127.0.0.1:9001`.

The installer does not directly modify `draft_content.json`, overwrite original drafts, or switch to cloud VectCut.

## Known compatibility boundaries

- Automatic draft creation uses tested VectCutAPI commit `d14e70749c9331424ab816a402bb45417c50cf68` and the `jianying_pro_10` draft template.
- Jianying versions and draft formats can change; run the real-draft acceptance check after first installation.
- For macOS/Linux, use [macOS / Linux local Jianying editing setup](posix-local-editing-setup.md). WSL verifies Linux services/draft files only, not macOS/Windows Jianying GUI acceptance.
- ASR, TTS, cloud rendering, and AI effects are separate optional capabilities, not prerequisites for local silent screen-recording edits.
