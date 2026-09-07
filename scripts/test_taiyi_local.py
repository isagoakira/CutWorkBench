"""Branch an existing full-source project and align joins to its integer frame rate."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import uuid
from cut_workbench.app import WorkbenchApp

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--project", required=True)
parser.add_argument("--revision", type=int, required=True)
parser.add_argument("--draft-folder", required=True)
args = parser.parse_args()
root = args.root.resolve()
app = WorkbenchApp(root, vectcut_draft_folder=args.draft_folder)
original = app.projects.read_project(args.project, args.revision)
if any(s["source_in"] != 0 or s["speed"] != 1 for s in original["segments"].values()):
    raise ValueError("Only full-source, normal-speed sequential projects are supported")
if len({s["track_id"] for s in original["segments"].values()}) != 1:
    raise ValueError("Requires one sequential source track")
fps = original["canvas"]["fps"]
project_id = "aligned-local-" + uuid.uuid4().hex[:8]
project = app.projects.branch_project(source_project_id=args.project, new_project_id=project_id, revision=args.revision)
frames = 0
operations = []
for segment in sorted(project["segments"].values(), key=lambda s: s["timeline_start"]):
    source = project["sources"][segment["source_id"]]
    info = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration:format=duration", "-of", "json", source["locator"]]))
    duration = min(float(info["format"]["duration"]), float(info["streams"][0].get("duration", info["format"]["duration"])))
    count = math.floor(min(duration, segment["source_out"]) * fps)
    operations.append({"op":"update_segment", "segment_id":segment["segment_id"], "changes":{"source_out":count/fps, "timeline_start":frames/fps}})
    frames += count
project = app.projects.apply_plan(project_id=project_id, expected_revision=project["revision"], actor="local-test", reason="Align full-source joins to canvas fps using probed stream durations", operations=operations)
result = app.call_tool("vectcut.execute", {"project_id":project_id,"revision":project["revision"]})
print(json.dumps({"project_id":project_id,"revision":project["revision"],"duration":frames/fps,"receipt":result["receipt"]},ensure_ascii=False,indent=2))
