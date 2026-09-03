# TapNow Context Engineering

## Purpose

`tapnow.context.compile` is the production translation layer between the locked
pre-production deliveries and TapNow Agent. It does not ask an operator to
rewrite the script, does not call browser endpoints, and does not start a paid
generation. It compiles the existing production truth into a Canvas build order
and an Ask-mode brief.

```text
approved script + storyboard + material list + declared source assets
                              ↓
                  Generation Context Pack
                              ↓
          TapNow Canvas nodes and Agent execution brief
                              ↓
          preview → human approval → generation → artifact handoff
```

## Required upstream bridge

The upstream workflow must first register its immutable deliveries in the Cut
Workbench project. The compiler requires the current, approved `video-script`,
`storyboard`, and `material-list` artifacts. It receives a structured projection
of the already locked campaign and shot rows; it is not a second planning form.

Each projected shot carries its existing purpose, duration, visual direction,
source artifact IDs, production route and, only for a `generative` route, the
generation settings agreed during the production decision. `human` and `local`
shots stay visible in the plan but are explicitly excluded from TapNow generation.

## Canvas order

1. One global context node fixes audience, platform, core message, creative
   direction and prohibitions.
2. Source nodes import only registered assets actually referenced by a shot,
   ordered product/character/style/evidence/footage/audio.
3. Each shot gets a brief node with its inherited purpose, duration, visual
   direction and declared sources.
4. Generative shots receive a task node. It is always `preview`/Ask mode;
   paid generation remains a separate approved `generation.request` lifecycle.
5. TapNow results are downloaded to their canonical artifact locators and fed
   back through `generation.submit`, which verifies the hash and returns a
   `register_workflow_artifact` operation.

## Asset staging and Canvas reconciliation

Call `tapnow.assets.stage` with the returned Context Pack. It creates a
`tapnow-imports/<context-fingerprint>/` directory under the Workbench root:

- `assets/` contains one hard-linked source file per unique artifact (or a copy
  only when the filesystem prevents a hard link);
- `asset-manifest.json` retains artifact IDs, hashes, roles and staged paths;
- `canvas-import-order.md` gives the exact human upload order.

Staging is local only. It does not open a browser, upload any file, or assert
that TapNow received an asset. After an explicit external-upload approval and
the actual multi-file upload, call `tapnow.canvas.reconcile` with the Canvas URL
and exactly one node ID per staged artifact. The result supplies `canvas-node`
references for the later TapNow preview jobs. It rejects missing mappings,
unapproved uploads, changed staged files and plans from another project revision.

The compiler rejects a missing or unapproved script/storyboard/material list,
unknown source IDs, non-continuous shot ordering, future dependencies, or an
attempt to make a human/local shot generative without an explicit replan.

## Web handoff

After staging, call `tapnow.web.handoff` with the same Context Pack and returned
Import Pack. It writes three further files beside the manifest:

- `tapnow-web-handoff.md`: the exact human sequence for a new TapNow Web Canvas;
- `tapnow-agent-brief.md`: the locked Ask-mode instruction produced by the
  Context compiler, ready to paste into Agent;
- `canvas-node-mapping.json`: an intentionally blank per-asset node-ID template
  for the post-upload reconciliation step.

This is deliberately a local renderer, not a browser driver. The user uploads
assets, selects explicit `@` references and sends the Agent task; Agent then
creates the global and shot-brief text nodes during its Ask-mode planning pass.
The user reviews the resulting node plan and estimate before any later
generation. The renderer rejects a different project revision, an unstaged
Import Pack, a changed staging root or an invalid manifest.

## MCP example

```json
{
  "project_id": "campaign-01",
  "upstream": {
    "artifact_ids": ["ART-SCRIPT-V1", "ART-STORYBOARD-V1", "ART-MATERIAL-V1"],
    "campaign": {
      "audience": "目标用户",
      "platform": "短视频平台",
      "core_message": "一句已锁定的核心信息",
      "creative_direction": "已确认的视觉基调",
      "prohibitions": ["产品文字不得漂移"]
    },
    "shots": [
      {
        "shot_id": "S01",
        "sequence": 1,
        "duration_seconds": 5,
        "purpose": "建立产品视觉锚点",
        "visual_direction": "来自分镜的画面方向",
        "route": "generative",
        "source_artifact_ids": ["ART-PRODUCT-FRONT"],
        "reference_roles": {"ART-PRODUCT-FRONT": "product-source"},
        "depends_on_shot_ids": [],
        "generation": {
          "capability": "video.generate",
          "prompt": "已由锁定分镜和生成决定导出的镜头提示",
          "output": {"count": 1, "aspect_ratio": "9:16", "duration_seconds": 5},
          "preserve": ["包装文字", "瓶身比例"],
          "avoid": ["额外 Logo"],
          "acceptance_criteria": ["产品主体完整"]
        }
      }
    ]
  }
}
```
