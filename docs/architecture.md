# Architecture

The workbench is a control plane, not an editor and not an Agent runtime.

```text
Codex / Claude / future Agent
             |
        MCP JSON tools
             v
        WorkbenchApp
      /       |        \
ProjectStore  Capability  Target compiler
(revisions)   router      (VectCut first)
                  |              |
        local JSON process   HTTP/MCP/in-process
        or pending Agent job editor adapter
```

## Stable seams

### Capability seam

`CapabilityRequest` contains a namespaced capability, inputs, quality, sensitivity, and constraints. The routing policy chooses `local` or `agent`. Local providers synchronously return `CapabilityResult`; Agent work becomes a durable `pending_agent` JSON job and is completed through `capability.submit`. An Agent platform migration changes only how pending jobs are consumed.

`JsonCommandProvider` sends one request object to stdin and reads one result object from stdout. Whisper, PySceneDetect, librosa, OpenCV, or custom tools can therefore run in separate environments without becoming workbench dependencies.

### Edit seam

An edit is an atomic list of operations applied against `expected_revision`. Each successful plan writes a new immutable snapshot and journal event. Controls are explicit records attached to stable segment and track IDs. Baked/non-editable controls are rejected unless the same project contains a human-approved capability downgrade.

### Target seam

`VectCutCompiler` translates one frozen revision to an auditable call plan. It does not perform network I/O. `VectCutExecutor` resolves plan references and delegates calls to a transport; `VectCutHttpTransport` targets the local VectCutAPI service. Other editors implement their own compiler/transport without changing project state.

## Cut Protocol closure

- Source audit: one `source_audit` decision per source, full coverage, sample rate >=2 fps, evidence path, and escalation data.
- Build: immutable source ranges plus named tracks and separable controls.
- Verify: deterministic checks run locally; semantic/frame review uses capability jobs; visual review is recorded with evidence.
- Optimize: every iteration is a new revision with reason, actor, operations, and evidence.
- Handoff: `delivered` and `handed_off` are gated; handed-off revisions reject mutations and require a branch.

The manifest renderer materializes the source ledger, rough-cut mapping, controls, captions, decisions, downgrades, and verification state from the same revision. It cannot silently drift from the project.
