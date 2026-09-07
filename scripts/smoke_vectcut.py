"""Real local REST smoke test; retains draft and receipt for manual editor acceptance."""
import argparse
import hashlib
import json
from pathlib import Path
import uuid

from cut_workbench.app import WorkbenchApp
from cut_workbench.vectcut import VectCutHttpTransport

parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--url", default="http://127.0.0.1:9001")
parser.add_argument(
    "--draft-folder",
    type=Path,
    help="Optional real Jianying draft root. Defaults to <root>/drafts for isolated transport validation.",
)
args = parser.parse_args()
source = args.source.resolve(strict=True)
root = args.root.resolve()
draft_folder = args.draft_folder.resolve() if args.draft_folder else root / "drafts"
digest = hashlib.sha256(source.read_bytes()).hexdigest()
app = WorkbenchApp(root, vectcut_transport=VectCutHttpTransport(args.url), vectcut_draft_folder=str(draft_folder))
project_id = "smoke-" + uuid.uuid4().hex[:12]
app.call_tool("project.create", {"project_id": project_id, "title": "Local VectCut smoke", "canvas": {"width": 1280, "height": 720, "fps": 30}})
app.call_tool("project.apply_plan", {"project_id": project_id, "expected_revision": 1, "actor": "smoke", "reason": "Real local media trim and placement", "operations": [
    {"op": "register_source", "source_id": "SRC", "locator": str(source), "sha256": digest},
    {"op": "add_track", "track_id": "V1", "kind": "video", "purpose": "main"},
    {"op": "add_segment", "segment_id": "S1", "source_id": "SRC", "track_id": "V1", "source_in": 1, "source_out": 3, "timeline_start": 0},
    {"op": "add_segment", "segment_id": "S2", "source_id": "SRC", "track_id": "V1", "source_in": 4, "source_out": 6, "timeline_start": 2},
]})
result = app.call_tool("vectcut.execute", {"project_id": project_id, "revision": 2})
assert digest == hashlib.sha256(source.read_bytes()).hexdigest(), "source changed"
receipt = result["receipt"]
content = json.loads((Path(receipt["draft_path"]) / "draft_content.json").read_text(encoding="utf-8"))
for material in content["materials"]["videos"]:
    assert hashlib.sha256(Path(material["path"]).read_bytes()).hexdigest() == digest, "copied media differs"
print(json.dumps(receipt, ensure_ascii=False, indent=2))
