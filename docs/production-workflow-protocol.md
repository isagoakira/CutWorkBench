# Video Production Workflow Protocol v1

This protocol turns the nine production phases into executable gates. Its governing rule is simple: a phase releases files that the next phase can consume directly, and no release occurs without recorded acceptance evidence.

## State model

Each stage moves through:

```text
not_started -> in_progress -> submitted -> approved
                      ^                       |
                      +------ stale <---------+
```

`stale` means an upstream artifact changed. Existing files and history are preserved, but the stage must select the new inputs, resubmit and regain approval.

## Canonical stages

| ID | Stage | Required approved inputs | Output directory |
|---|---|---|---|
| `01-script` | 脚本 | — | `01_脚本/` |
| `02-storyboard` | 分镜稿 | 01 | `02_分镜/` |
| `03-material-list` | 素材清单 | 02 | `03_素材清单/` |
| `04-recording` | 素材录制与整理 | 03 | `04_原始素材/` |
| `05-rough-cut` | 视频粗剪 | 01, 02, 04 | `05_视频粗剪/` |
| `06-voice` | 口播稿与声音录制 | 01, 05 | `06_口播与音频/` |
| `07-fine-cut` | 视频精剪 | 02, 04, 05, 06 | `07_视频精剪/` |
| `08-subtitles` | SRT 字幕 | 06, 07 | `08_字幕/` |
| `09-final` | 配音补充与最终微调 | 07, 08 | `09_终剪与发布/` |

The full deliverable formats and acceptance wording are machine-readable through `workflow.contract`. `10_归档与交付说明/` is the storage location for frozen manifests and backups; it is not a tenth production gate in v1.

## Agent-facing operations

Read operations:

- `workflow.contract`: get exact requirements without relying on prompt memory.
- `workflow.status`: get stage readiness, blockers, artifact counts and stale reasons.

Mutations are atomic operations inside `project.apply_plan`:

- `configure_production_workflow`
- `register_workflow_artifact`
- `submit_workflow_stage`
- `approve_workflow_stage`

Example artifact registration:

```json
{
  "op": "register_workflow_artifact",
  "artifact_id": "ART-SCRIPT-20260827-V1",
  "stage_id": "01-script",
  "kind": "video-script",
  "format": "md",
  "version": "1",
  "locator": "01_脚本/01_视频脚本_v1_20260827.md",
  "sha256": "<64 hexadecimal characters>",
  "derived_from": [],
  "verification": {
    "verifier": "local-artifact-inspector",
    "readable": true,
    "hash_matched": true,
    "evidence": ["10_归档与交付说明/ART-SCRIPT-20260827-V1.json"],
    "content_profile": {"sections": 8}
  }
}
```

A submission must include every required deliverable, exact approved input artifact IDs, the canonical criterion text, `passed: true`, and one or more evidence locators per criterion. Approval requires reviewer identity and review evidence.

Every generated deliverable file must use `阶段_内容_v版本号_YYYYMMDD.扩展名`; raw footage/voice clips keep their shot- or sentence-level naming rules, and registered directories keep their canonical directory names. Artifact registration also requires a verifier attestation that the locator is readable and its computed hash matches `sha256`. Each submission must pass and evidence every item in the contract's `content_requirements`, so either a local inspector or an Agent-native capability can validate the required document fields and production properties without changing the core protocol.

Approving stage 01 is the script-mainline lock; approving stage 06 is the voice-text lock. Any replacement artifact reopens that stage and makes dependent fine-cut, subtitle and final approvals stale, forcing the synchronized recheck required by the protocol.

## Manual editing and dual mapping

Premiere Pro, After Effects, Jianying and future NLE project files are registered as `editor-project` artifacts. Their internal editable tracks remain represented by Cut Workbench stable IDs and adapter bindings. A human can modify the external project; the sync layer previews a three-way diff and commits accepted changes as a new project revision. Workflow approval therefore governs deliverable readiness without flattening or taking ownership away from the editor.

## Delivery gate

Projects without an enabled workflow preserve legacy behavior. Once configured, `delivered` and `handed_off` additionally require stage `09-final` to be approved. Existing Cut Protocol source audit, provenance and visual verification gates still apply.
