# Runtime configuration and call chain

Cut Workbench selects one JSON runtime configuration at startup, containing local capability providers, routing policy, and local VectCutAPI connection settings. Configuration is separate from project data; revisions, journals, jobs, and sync sessions always reside under `--root`.

## Configuration file selection and override order

CLI/MCP selects configuration in this order:

1. With `--config <path>`, read only that file.
2. Without `--config`, automatically read `<root>/runtime-config.json` if it exists.
3. Otherwise, use built-in defaults.

Multiple JSON files are not automatically merged. Environment variables and scalar CLI arguments override only specified VectCut fields:

| Field | Highest → lowest priority |
| --- | --- |
| VectCut endpoint | `--vectcut-url` → `vectcut.base_url` → `CUT_WORKBENCH_VECTCUT_URL` → `http://127.0.0.1:9001` |
| VectCut draft root | `--vectcut-draft-folder` → `vectcut.draft_folder` → Platform default Jianying draft directory |
| VectCut timeout | `vectcut.timeout` → `120` seconds |
| capability provider / routing | Selected configuration → built-in routing; `ffprobe` is always registered by default |

`vectcut.base_url` and `CUT_WORKBENCH_VECTCUT_URL` must use `http://` or `https://` with local loopback (`localhost`, `127.0.0.1`, or `::1`). Remote/cloud endpoints are rejected at startup.

## Minimum configuration

For automatic draft creation alone, declare only VectCut; default `ffprobe` remains:

```json
{
  "vectcut": {
    "base_url": "http://127.0.0.1:9001",
    "timeout": 120,
    "draft_folder": "E:/JianYing/JianyingPro Drafts"
  }
}
```

`draft_folder` must point to the actual writable draft root used by local Jianying. `vectcut.execute` always creates a new draft and refuses to overwrite an existing draft ID.

## Add local sidecars

For local transcription, shot detection, or TTS, put providers and VectCut in the same file:

```json
{
  "vectcut": {
    "base_url": "http://127.0.0.1:9001",
    "draft_folder": "E:/JianYing/JianyingPro Drafts"
  },
  "providers": [
    {
      "kind": "ffprobe",
      "executable": "D:/tools/ffmpeg/bin/ffprobe.exe"
    },
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
      "audio.transcribe.words": {"standard": "local", "high": "agent"}
    }
  }
}
```

`providers` is an array. Supported `kind` values:

- `ffprobe`: optional `executable`; if omitted, `ffprobe` from system PATH is still registered.
- `json-command`: requires `provider_id`, `capabilities`, and a `command` array. Read one JSON request from stdin, write one JSON result to stdout, and send logs to stderr.

`routing` is an object with optional `default_route` (`local` or `agent`) and `rules` mapping capability/quality to routes. Omission uses built-in policy.

## Startup and call chain

```powershell
# Automatically load D:/cut-runtime/runtime-config.json
cut-workbench --root D:/cut-runtime mcp

# Use an explicit machine configuration
cut-workbench --root D:/cut-runtime --config D:/cut-config/runtime-config.json mcp

# Override the VectCut service and draft root for this launch
cut-workbench --root D:/cut-runtime `
  --config D:/cut-config/runtime-config.json `
  --vectcut-url http://127.0.0.1:9100 `
  --vectcut-draft-folder 'E:/JianYing/JianyingPro Drafts' `
  call vectcut.health '{}'
```

MCP and CLI `call` share `WorkbenchApp`. Inspect and apply project changes through `project.inspect` and `project.apply_plan` to create revisions, then select a target path:

```text
capability.request ─────────────→ local provider or pending_agent → capability.submit
project revision ──────────────→ vectcut.health → compile → execute → new Jianying draft
project revision + editor base ─→ sync.open → preview → commit → publish clone / apply live
```

`vectcut.compile` produces an audit plan only; `vectcut.execute` calls local VectCutAPI. `sync.publish` creates external project copies, while `sync.apply` is only for connected, authorized local editor bridges. They are not interchangeable.

## Pre-start checks

1. Run `ffprobe -version` in the terminal used to launch Workbench.
2. Verify local VectCutAPI on the configured port: `cut-workbench --root D:/cut-runtime call vectcut.health '{}'`.
3. Confirm `draft_folder` is the actual writable Jianying draft root.
4. Use `cut-workbench --root D:/cut-runtime list-tools` for current MCP schemas rather than guessing arguments.

A complete runnable configuration is available in [examples/runtime-config.json](../examples/runtime-config.json).
