# Cut Workbench engineering guide

## Invariants

- Original media is immutable; edits reference source ranges.
- Every track, segment, control, caption, decision, and exception has a stable ID.
- Mutations go through `ProjectStore.apply_plan` with an expected revision.
- Treatments remain editable and separable. Flattening requires a recorded, human-approved downgrade.
- Agent hosts and analysis providers are adapters; domain code must not import an Agent SDK.
- A handed-off project is immutable. Further work starts from a branch.

## Commands

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -v
python -m compileall -q src
python -m cut_workbench.cli --root runtime list-tools
```
