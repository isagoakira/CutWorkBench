# ADR 0001: Represent production as stage contracts and immutable file artifacts

## Status

Accepted

## Context

The production process must hand real files from one phase to the next, preserve manual editor freedom, support multiple Agent hosts, and prevent script, voice, timeline and subtitle versions from silently diverging. Embedding office documents and media inside the project snapshot would make revisions large and editor-specific. Tracking only checklist state would lose provenance and permit a later phase to consume the wrong version.

## Decision

Cut Workbench stores a nine-stage Production Workflow inside each immutable project revision. Each stage has a canonical contract, explicit dependencies, allowed file deliverables and acceptance criteria.

Files stay outside the JSON snapshot. The snapshot records immutable artifacts by stable ID, locator, format, version, SHA-256 hash and `derived_from` links. A stage submission pins exact input/output artifact IDs and evidence for every criterion. A separate approval releases those artifacts downstream. Registering a new upstream artifact marks affected downstream work stale.

All mutations continue through `project.apply_plan`. Agent hosts receive two read-only conveniences: `workflow.contract` and `workflow.status`. The core therefore depends on no Agent vendor or NLE.

SRT remains a stage deliverable generated from the final heard audio. Editable speech intent and timing may remain structured separately as a cue sheet.

## Consequences

- A release can be traced back to exact script, storyboard, media and audio file versions.
- Manual edits remain possible because editor projects are artifacts and timeline elements remain separable.
- Replacing a file requires a new artifact ID and reapproval of affected work.
- Storage and hashing are handled by filesystem or adapter layers; the core stores references rather than binary content.
- Legacy projects remain valid until the production workflow is explicitly configured.
