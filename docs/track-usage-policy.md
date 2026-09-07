# Conservative track-usage policy

Tracks convey simultaneous, independently adjustable roles—not implementation
convenience. A normal screen-demo cut should begin with one base video track,
no audio track when the delivery is silent, and at most one track for each
genuine simultaneous role such as narration, music, captions, or annotation.

- Reuse a lane for sequential clips and controls.
- Add a video or audio lane only when items must overlap in time or must remain
  independently adjustable for a named editorial role.
- Remove empty lanes before a review handoff.
- Keep privacy overlays logically grouped, but compile them into the smallest
  possible native lane pool: non-overlapping intervals reuse a lane, while
  only concurrent overlays receive separate child lanes.
- Do not create tracks merely to work around a temporary implementation detail.
  If an editor requires a fallback, keep the number of lanes bounded and state
  the reason in the project decision record.
