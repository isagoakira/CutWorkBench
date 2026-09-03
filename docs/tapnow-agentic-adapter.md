# TapNow Agentic Generative Adapter

## Why this is an Agentic adapter

TapNow's public Creative OS documentation describes Agent, Apps, Canvas nodes, Ask mode and interactive generation, but does not currently publish a stable developer API or MCP contract. Cut Workbench therefore does not call private web endpoints. It creates a durable operation packet that any authorized GUI/browser Agent can execute in TapNow and later replaces the adapter when an official interface becomes available.

The Workbench remains the production source of truth. TapNow is a replaceable generation target and its Canvas is retained as evidence and creative lineage.

## Tools

- `generation.contract`: supported capabilities and safety rules.
- `generation.request`: validate and persist one operation.
- `generation.pending`: list TapNow packets awaiting an Agent executor.
- `generation.reconciliation`: list expired authorized runs that must be checked against TapNow before any retry.
- `generation.claim`: bind one packet to an executor before it touches TapNow.
- `generation.heartbeat`: renew the executor lease during a long interactive run.
- `generation.approve`: bind a prepared operation and its live estimate to a human-approved budget.
- `generation.authorize`: validate the current TapNow confirmation screen before the executor may click Generate.
- `generation.submit`: validate returned nodes/files and produce workflow artifact operations.

Supported provider-neutral capabilities:

- `image.generate`, `image.edit`
- `video.generate`, `video.edit`
- `video.extend`, `video.retake`, `video.inpaint`

## Execution boundaries

`plan` and `preview` always compile with `stop_before_spend: true`. The Agent may organize references, create/configure nodes and report the confirmation state, but must not begin a charged generation.

Their result is `status: "prepared"`, contains no generated outputs, records zero generated candidates and zero Tapies charged, and may include the live estimate shown by TapNow. To proceed, create a new `generate` request that cites the approval evidence and the prepared Canvas node.

After a preview returns its live estimate, approve that exact prepared job:

```json
{
  "prepared_job_id": "<completed preview job>",
  "approved_by": "human:producer",
  "billing_mode": "tapies",
  "max_tapies": 100,
  "max_candidates": 1,
  "evidence": ["approvals/shot-S01.md"]
}
```

Then create the otherwise identical `generate` request with `constraints.prepared_job_id`. The Workbench injects the stored approval and rejects changes to the capability, prompt, references, model, output settings, preservation rules or acceptance criteria.

Use `billing_mode: "unlimited"` when the selected model is covered by a currently active Unlimited benefit. The Agent must still obey `max_candidates` and confirm the live TapNow screen before execution.

A completed `generate` result reports actual `billing_mode`, `candidates_generated` and, for Tapies billing, `tapies_charged`. Results that exceed the approved candidate or Tapies cap are rejected.

Immediately before clicking Generate, the executor returns from a separate `preflight` phase with billing mode, candidate count, current estimate and evidence. Workbench validates it through `generation.authorize`; only then does the worker launch a second `execute` phase carrying that authorization. If the live estimate is above the stored approval, the second phase never runs. Post-run usage is checked again as an audit defense.

Any `local-file` reference requires a separate `external_upload_approval` with approver and evidence. A Canvas node or already-authorized remote URL does not claim a new local upload.

## Example request

```json
{
  "capability": "video.generate",
  "prompt": "A five-second product turntable shot with soft morning light",
  "references": [
    {
      "reference_id": "ART-PRODUCT-FRONT",
      "kind": "canvas-node",
      "locator": "tapnow://canvas/canvas-1/node/product-front",
      "role": "product-source"
    }
  ],
  "output": {"count": 1, "aspect_ratio": "16:9", "duration_seconds": 5},
  "constraints": {
    "execution_boundary": "preview",
    "preserve": ["label text", "bottle proportions"],
    "avoid": ["extra logos"]
  },
  "acceptance_criteria": ["Packaging text remains legible"]
}
```

For edit operations, `change_scope` and at least one `preserve` item are mandatory. This encodes TapNow's recommended targeted-revision pattern: fix one issue while naming the details that must not drift.

## Workflow artifact handoff

An optional `artifact_targets` array specifies the intended Cut Workbench artifact ID, stage, kind, format, canonical local locator, version and `derived_from` IDs. The executor downloads the TapNow result to that exact locator and returns its SHA-256 hash.

After validation, `generation.submit` returns `artifact_operations`. Apply those operations through `project.apply_plan`; do not mutate the project directly. This keeps human approval and immutable revision rules intact.

## Result evidence

Every result must match the dispatched `operation_id` and include:

- Canvas URL;
- output node ID, model and media type;
- canonical downloaded locator and SHA-256;
- executor identity and evidence locators;
- one result for each declared artifact target.

The adapter rejects extra candidates, mismatched targets, changed locators and missing hashes instead of silently accepting an ambiguous generation.

An executor must claim a pending job before opening or changing TapNow. Claimed jobs leave the pending queue, and only the same `executor_id` may submit the result. Claims use a renewable lease. An expired job that never passed preflight returns to the pending queue. An expired job that was already authorized enters `reconciliation_required` instead: an operator must inspect TapNow before deciding what happened, because blind retry could duplicate a charged generation. The filesystem transition itself is locked to prevent two local processes from claiming the same charged operation concurrently.

## Trust boundary

Without an official signed TapNow developer API, the local Agent executor is the trusted source for Canvas node IDs, the confirmation-screen estimate, billing mode and semantic review evidence. Workbench independently enforces operation identity, state transitions, approval caps, candidate counts, local output paths and file hashes, but it cannot cryptographically prove facts observed only inside the TapNow UI. Run the executor under a dedicated TapNow account or team allowance, keep evidence locators, and reconcile any authorized run whose executor lease expires.

## Local Agent worker

The built-in one-shot worker makes the handoff executable rather than requiring manual polling:

```powershell
cut-workbench --root D:\project-runtime generation-worker-once `
  --executor-id codex-local `
  --agent-command-json '["your-agent-command", "tapnow-executor"]'
```

The command receives a JSON envelope on stdin and returns one JSON object with `payload` and `evidence`. Preview jobs receive `phase: "prepare"`. Generate jobs invoke the command twice: `phase: "preflight"`, then—only after Workbench authorization—`phase: "execute"`. It may be implemented by Codex, another local Agent framework, or a future official TapNow client. The worker atomically claims the job and submits successful results through the same validator. Failures before authorization are recorded as failed; failures after authorization enter the reconciliation queue because the external side effect may already have happened.
