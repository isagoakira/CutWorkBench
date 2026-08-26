# Architecture

The workbench is a control plane, not an editor and not an Agent runtime.

```text
Codex / Claude / future Agent
             |
        MCP JSON tools
             v
        WorkbenchApp
      /       |        \
ProjectStore  Capability  Editor adapters
(revisions)   router      /            \
                  |    VectCut compiler  Jianying sync
        local JSON process   HTTP         snapshot/clone
        or pending Agent job
```

## Stable seams

### Capability seam

`CapabilityRequest` contains a namespaced capability, inputs, quality, sensitivity, and constraints. The routing policy chooses `local` or `agent`. Local providers synchronously return `CapabilityResult`; Agent work becomes a durable `pending_agent` JSON job and is completed through `capability.submit`. An Agent platform migration changes only how pending jobs are consumed.

`JsonCommandProvider` sends one request object to stdin and reads one result object from stdout. Whisper, PySceneDetect, librosa, OpenCV, or custom tools can therefore run in separate environments without becoming workbench dependencies.

### Edit seam

An edit is an atomic list of operations applied against `expected_revision`. Each successful plan writes a new immutable snapshot and journal event. Controls are explicit records attached to stable segment and track IDs. Baked/non-editable controls are rejected unless the same project contains a human-approved capability downgrade.

### Target seam

`VectCutCompiler` translates one frozen revision to an auditable call plan. It does not perform network I/O. `VectCutExecutor` resolves plan references and delegates calls to a transport; `VectCutHttpTransport` targets the local VectCutAPI service. Other editors implement their own compiler/transport without changing project state.

### Bidirectional editor seam

`EditorAdapter` exposes only `profile`, `snapshot`, and `publish`. `EditorSync` owns the platform-neutral transaction: `sync.open` pins project revision A and editor snapshot A; `sync.preview` compares current project B and current editor C; `sync.commit` records accepted manual changes as revision D; `sync.publish` applies accepted Agent-side fields to a new editor-draft clone.

Bindings map editor-native IDs to stable Workbench IDs. Unbound native objects are stored as opaque `external_entities`; unsupported objects block full VectCut compilation instead of disappearing. Conflicts are deterministic and require an explicit `human` or `agent` resolution. This keeps Jianying-specific encryption and JSON paths outside the domain model, so another Agent host or editor adapter does not change the four public sync tools.

## Cut Protocol closure

- Source audit: one `source_audit` decision per source with probed duration, valid SHA-256, full `coverage_range`, sample rate >=2 fps, sufficient `sample_count`, evidence locators, and an explicit escalation list.
- Build: immutable source ranges plus named tracks and separable controls.
- Verify: deterministic checks run locally; unexplained base-track gaps/overlaps fail; semantic/frame review uses capability jobs; visual review is bound to a content fingerprint so later edits make it stale.
- Optimize: every iteration is a new revision with reason, actor, operations, and evidence.
- Handoff: `delivered` and `handed_off` are gated; handed-off revisions reject mutations and require a branch.

The manifest renderer materializes the source ledger, rough-cut mapping, controls, captions, decisions, downgrades, and verification state from the same revision. It cannot silently drift from the project.
