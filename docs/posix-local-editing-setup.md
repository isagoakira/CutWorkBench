# macOS / Linux local Jianying editing setup

These scripts install the local path in one operation: **Cut Workbench + local VectCutAPI + FFmpeg/ffprobe + Jianying draft directory**. The service binds only `127.0.0.1:9001`, uses no cloud VectCut key, and does not enable ASR.

## Platform boundaries

| Platform | Installer | Verifiable scope | Final Jianying acceptance |
| --- | --- | --- | --- |
| macOS | Supported | Local service, persisted drafts, media streams, visual acceptance dependencies | Verify visibility and playback in the Jianying Pro draft library |
| Linux | Supported | Local service, persisted drafts, media streams, visual acceptance dependencies | No native Jianying Pro client; no GUI acceptance claim |
| WSL | Supported for testing | Same as Linux; scripts, services, and file format can be checked | Does not replace Windows/macOS Jianying GUI acceptance |

Generated draft files do not establish compatibility with the installed Jianying version. Before real use, run a real-draft smoke test on macOS or Windows with Jianying Pro installed.

## Before installation

1. macOS: install and open Jianying Pro at least once, create an empty draft, then close it. Default draft directory:  `~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft`.
2. Linux/WSL: prepare an existing writable draft directory and supply it with `--jianying-draft-folder`. Do not point WSL at or modify a Windows Jianying draft library currently in use.
3. Provide Python 3.11+, Git, curl, and FFmpeg including `ffprobe`. The script can attempt dependency installation using Homebrew, apt, dnf, or pacman.

Default installation state paths:

- macOS: `~/Library/Application Support/CutWorkbench`
- Linux/WSL: `${XDG_STATE_HOME:-$HOME/.local/state}/cut-workbench`

Invoke scripts with `bash`; executable file permissions are not required.

## One-time installation

macOS, using the default Jianying draft directory:

```bash
bash ./scripts/posix/install-local-editing.sh \
  --install-prerequisites \
  --start-service
```

Linux/WSL, requiring an existing draft directory:

```bash
bash ./scripts/posix/install-local-editing.sh \
  --jianying-draft-folder /path/to/existing/jianying-drafts \
  --start-service
```

If Python 3.11+ is not in `PATH`, specify the interpreter explicitly:

```bash
bash ./scripts/posix/install-local-editing.sh \
  --python /path/to/python3.11 \
  --jianying-draft-folder /path/to/existing/jianying-drafts \
  --start-service
```

Installation creates:

- `runtime/runtime-config.json`: Points only to local loopback VectCutAPI and the specified draft directory;
- `agent-mcp-config.json`: Entry to import into Codex, Claude Desktop, or another stdio MCP agent;
- `installation.json`: Installation receipt and pinned upstream version;
- `service/`: Local VectCutAPI state and logs.

Existing VectCutAPI/runtime configuration is preserved unless `--force-config` explicitly requests replacement. The installer does not directly edit existing drafts' `draft_content.json`.

### Python restrictions on Ubuntu 22.04 / WSL

Ubuntu 22.04 typically provides Python 3.10 as system `python3`. Even with `--install-prerequisites`, the installer rejects interpreters below 3.11 before creating any virtual environment. Install Python 3.11+ separately and select it with `--python`.

## Daily operation and diagnostics

Start the local service after reboot:

```bash
bash ./scripts/posix/start-local-editing.sh
```

Check Python, FFmpeg, draft directory, pinned VectCut profile, service health, and optional visual acceptance tools:

```bash
bash ./scripts/posix/doctor-local-editing.sh
```

Perform read-only media-stream inspection:

```bash
bash ./scripts/posix/doctor-local-editing.sh --media-path /path/to/demo.mp4
```

The stop script terminates only the VectCutAPI process recorded by `start-local-editing.sh`:

```bash
bash ./scripts/posix/stop-local-editing.sh
```

## First real-draft acceptance

Select a local video at least 6 seconds long and run:

```bash
bash ./scripts/posix/smoke-local-editing.sh --source /path/to/six-seconds-or-longer.mp4
```

This creates a new short draft and verifies two real cuts, timeline continuity, source SHA-256, VectCutAPI responses, and persisted draft files, without modifying sources or existing drafts.

On macOS, open Jianying Pro and verify visibility and playback in its draft library. On Linux/WSL, this proves only the local service/draft-file path. Do not label it “Jianying accepted” before moving the generated directory to a machine with Jianying Pro.

## Agent integration

Import the `cut-workbench` entry from installation-state `agent-mcp-config.json` into the agent. It starts local stdio MCP; only `vectcut.execute` creates new editable drafts through `127.0.0.1:9001`.

The package excludes ASR, TTS, cloud rendering, and AI effects. FFmpeg/ffprobe and OpenCV/Pillow are independent local dependencies: the former for stream inspection/rendering, the latter for keyframe contact sheets and visual acceptance. `--skip-visual-qa` skips the latter, which `doctor` reports as a noncritical missing item.

## Verified pins and troubleshooting

- Automatic draft creation pins VectCutAPI commit `d14e70749c9331424ab816a402bb45417c50cf68`.
- Generated profile:  `jianying_pro_10`、`is_capcut_env=false`、local port `9001`.
- If `doctor` reports `local-vectcut-service` failure, run `start-local-editing.sh`, then inspect `service/vectcut.stderr.log` under installation state.
- If the draft-directory check fails, supply an existing directory writable by the current user. Do not bypass it by creating an empty guessed path.
