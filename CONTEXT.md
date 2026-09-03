# Domain Context

## Purpose

Cut Workbench turns a video-production plan into versioned, editable and auditable work. The production protocol governs whether each phase has produced files that the next phase can use without reconstructing intent from chat history.

## Glossary

### Production Workflow

The nine-stage path from script through final delivery. It records coordination state; it does not replace the media timeline or editor project.

### Stage Contract

The fixed agreement for one workflow stage: required upstream approvals, allowed deliverable kinds and formats, and acceptance criteria. A stage is not complete merely because files exist.

### Artifact

An immutable, versioned file or directory reference produced by a stage. It has a stable ID, locator, SHA-256 hash, format, version and explicit upstream lineage. Revisions create new artifacts rather than overwriting prior evidence.

### Submission

A proposed stage output that pins the exact input and output artifact IDs and supplies evidence for every acceptance criterion.

### Approval

The review decision that releases a submitted stage for downstream use. Only approved artifacts satisfy dependencies.

### Stale Stage

A previously started, submitted or approved stage whose upstream contract output changed. Its files remain preserved, but they no longer authorize delivery until resubmitted and approved against the new inputs.

### Trace Link

An explicit `derived_from` relation between artifacts. Trace links answer which script, storyboard, recordings and voice assets produced a particular cut, subtitle or release file.

### Cue Sheet

Structured, sentence- or intent-level speech timing and semantics used during editing. SRT is a delivery artifact derived from the final heard audio, not the sole source of timing truth.

### Delivery Package

The approved stage 09 outputs: locked master, platform variants, final subtitle and delivery notes, plus optional supplemental voice assets.

### Generation Context Pack

An immutable projection of approved script, storyboard, material-list artifacts and declared source assets into a globally constrained, shot-ordered Canvas plan. It is the handoff to an interactive generative workspace; it never replaces the upstream master or material plan.

### Canvas Node Plan

The dependency-ordered instructions for building a Canvas: global context first, then explicitly approved sources, then one brief and optional generation node per shot. A node may reference only its declared sources and prior generative outputs.

### Canvas Import Pack

A hash-verified, de-duplicated local staging directory derived from one Generation Context Pack. It records the only files approved for upload and requires a complete mapping from each local artifact to one Canvas node after an external upload.

## Invariants

- Original source media is never overwritten.
- Every stage consumes exact approved artifact versions, not ambiguous filenames.
- Every acceptance criterion has explicit evidence.
- An upstream artifact revision invalidates all affected downstream approvals.
- Delivery cannot pass while stage 09 is unapproved.
- Timeline tracks and controls remain separable for manual editing and round-trip synchronization.
