# Cut Workbench engineering guide

## Invariants

- Original media is immutable; edits reference source ranges.
- Every track, segment, control, caption, decision, and exception has a stable ID.
- Mutations go through `ProjectStore.apply_plan` with an expected revision.
- Treatments remain editable and separable. Flattening requires a recorded, human-approved downgrade.
- Track usage is deliberately conservative: start with one base video lane and add a video or audio lane only when simultaneous material, independently adjustable audio, or a semantic role requires it. Do not create a track per clip, caption, effect, or privacy rectangle.
- For VectCut/Jianying compilation, reuse a named native lane whenever time ranges do not overlap. Overlapping overlays may use the smallest interval-colored child-lane pool required by the editor; one child track per overlay is prohibited.
- Agent hosts and analysis providers are adapters; domain code must not import an Agent SDK.
- A handed-off project is immutable. Further work starts from a branch.

## Commands

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -v
python -m compileall -q src
python -m cut_workbench.cli --root runtime list-tools
```
