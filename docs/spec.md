# Implementation specification

## Objective

Build a zero-subscription, local-first video editing workbench where an external Agent supplies high-judgment capabilities, local tools handle cheap deterministic analysis, and the output remains independently editable on named tracks.

## Required behavior

1. Preserve originals and source provenance. Store immutable, versioned project snapshots and reject stale mutations.
2. Represent source media, named tracks, source-derived segments, controls, captions, decisions, capability downgrades, and verification evidence with stable IDs.
3. Keep base video, treatment copies, captions, effects, audio, and stickers independently addressable. Never silently flatten controls.
4. Route stable capability requests by policy. Standard transcription/silence/beat/scene work may use local commands; high-precision frame interpretation, planning, and semantic verification may become durable Agent jobs.
5. Keep the Agent boundary platform-neutral through MCP tools and JSON request/result envelopes. Switching Agent hosts must not change the domain model or edit-plan caller.
6. Compile a frozen revision to a VectCut call plan that creates named tracks and preserves treatment isolation, then execute it through a replaceable transport.
7. Enforce the Cut Protocol loop: full-source audit at no less than 2 fps with evidence, explicit decisions and escalations, deterministic structural verification, visual evidence before delivery/handoff, versioned manifest, approved downgrade declarations, and immutable handoff with branching.
8. Depend only on Python's standard library at runtime. FFmpeg/ffprobe and local model sidecars are optional external processes.

## Non-goals for v0.1

- Building a new nonlinear editor UI.
- Bundling model weights or requiring a local LLM.
- Hiding proprietary editor formats behind an irreversible render.
- Automatically claiming subjective quality without Agent or human evidence.
