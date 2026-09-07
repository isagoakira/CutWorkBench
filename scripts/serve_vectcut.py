"""Run the locally installed VectCutAPI on loopback (Windows/macOS/Linux)."""
import argparse
import os
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--repo", type=Path, required=True)
parser.add_argument("--port", type=int, default=9001)
args = parser.parse_args()
repo = args.repo.resolve(strict=True)
if not (repo / "capcut_server.py").is_file():
    parser.error("--repo must contain capcut_server.py")
os.chdir(repo)
sys.path.insert(0, str(repo))
from capcut_server import app
app.run(host="127.0.0.1", port=args.port, use_reloader=False)
