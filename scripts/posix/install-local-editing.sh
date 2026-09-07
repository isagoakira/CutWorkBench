#!/usr/bin/env bash
# Install the no-cloud local Cut Workbench + VectCutAPI editing kit on macOS/Linux.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd -P)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

INSTALL_ROOT=""
JIANYING_DRAFT_FOLDER=""
PYTHON_EXECUTABLE=""
INSTALL_PREREQUISITES=0
SKIP_VISUAL_QA=0
FORCE_CONFIG=0
START_SERVICE=0
NON_INTERACTIVE=0
VECTCUT_REPOSITORY="https://github.com/sun-guannan/VectCutAPI.git"
VECTCUT_REF="d14e70749c9331424ab816a402bb45417c50cf68"

usage() {
  cat <<'EOF'
Usage: scripts/posix/install-local-editing.sh [options]

  --install-root PATH             State, venvs, service logs and config location
  --jianying-draft-folder PATH   Existing Jianying draft folder (required on Linux/WSL)
  --python PATH                   Python 3.11+ executable
  --install-prerequisites         Install Git/Python/FFmpeg with Homebrew or the system package manager
  --skip-visual-qa                Skip optional OpenCV/Pillow installation
  --force-config                  Replace existing local VectCut/runtime configuration
  --start-service                 Start local VectCutAPI after installation
  --non-interactive               Fail instead of prompting for the Jianying draft folder
  --vectcut-repository URL        Override the VectCutAPI git repository
  --vectcut-ref REF               Override the tested VectCutAPI revision
  -h, --help                      Show this help
EOF
}

while (($#)); do
  case "$1" in
    --install-root) INSTALL_ROOT="$2"; shift 2 ;;
    --jianying-draft-folder) JIANYING_DRAFT_FOLDER="$2"; shift 2 ;;
    --python) PYTHON_EXECUTABLE="$2"; shift 2 ;;
    --install-prerequisites) INSTALL_PREREQUISITES=1; shift ;;
    --skip-visual-qa) SKIP_VISUAL_QA=1; shift ;;
    --force-config) FORCE_CONFIG=1; shift ;;
    --start-service) START_SERVICE=1; shift ;;
    --non-interactive) NON_INTERACTIVE=1; shift ;;
    --vectcut-repository) VECTCUT_REPOSITORY="$2"; shift 2 ;;
    --vectcut-ref) VECTCUT_REF="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

install_prerequisites() {
  local platform
  platform="$(uname -s)"
  if [[ "$platform" == "Darwin" ]]; then
    command -v brew >/dev/null 2>&1 || {
      echo "Homebrew is required for automatic macOS prerequisite installation. Install Homebrew, then rerun." >&2
      return 1
    }
    brew install git python@3.11 ffmpeg curl
    return
  fi
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y git curl ffmpeg python3 python3-venv
    return
  fi
  if command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y git curl ffmpeg python3.11
    return
  fi
  if command -v pacman >/dev/null 2>&1; then
    sudo pacman -Sy --noconfirm git curl ffmpeg python
    return
  fi
  echo "No supported package manager was found. Install Git, curl, FFmpeg and Python 3.11+ manually." >&2
  return 1
}

if (( INSTALL_PREREQUISITES )); then
  install_prerequisites
fi

for command_name in git curl ffmpeg ffprobe; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "Missing ${command_name}. Install it, or rerun with --install-prerequisites." >&2
    exit 1
  }
done

PYTHON="$(cut_workbench_find_python "$PYTHON_EXECUTABLE")"
PYTHON_VERSION="$(cut_workbench_assert_python_version "$PYTHON")"
SOURCE_ROOT="$(cut_workbench_source_root)"
INSTALL_ROOT="$(cut_workbench_install_root "$INSTALL_ROOT")"
RUNTIME_ROOT="${INSTALL_ROOT}/runtime"
TOOLS_ROOT="${INSTALL_ROOT}/tools"
VECTCUT_ROOT="${TOOLS_ROOT}/VectCutAPI"
WORKBENCH_VENV="${INSTALL_ROOT}/workbench-venv"
VECTCUT_VENV="${VECTCUT_ROOT}/.venv"
WORKBENCH_PYTHON="${WORKBENCH_VENV}/bin/python"
VECTCUT_PYTHON="${VECTCUT_VENV}/bin/python"
RUNTIME_CONFIG="${RUNTIME_ROOT}/runtime-config.json"
MCP_CONFIG="${INSTALL_ROOT}/agent-mcp-config.json"

if [[ -z "$JIANYING_DRAFT_FOLDER" ]]; then
  JIANYING_DRAFT_FOLDER="$(cut_workbench_default_draft_folder || true)"
fi
if [[ -z "$JIANYING_DRAFT_FOLDER" || ! -d "$JIANYING_DRAFT_FOLDER" ]]; then
  if (( NON_INTERACTIVE )); then
    echo "Jianying draft folder was not found. Pass --jianying-draft-folder <existing folder>." >&2
    exit 1
  fi
  read -r -p "Existing Jianying draft folder: " JIANYING_DRAFT_FOLDER
fi
[[ -d "$JIANYING_DRAFT_FOLDER" ]] || { echo "Jianying draft folder does not exist: $JIANYING_DRAFT_FOLDER" >&2; exit 1; }
cut_workbench_directory_writable "$JIANYING_DRAFT_FOLDER" || { echo "Jianying draft folder is not writable: $JIANYING_DRAFT_FOLDER" >&2; exit 1; }

mkdir -p -- "$INSTALL_ROOT" "$RUNTIME_ROOT" "$TOOLS_ROOT"

if [[ ! -x "$WORKBENCH_PYTHON" ]]; then
  "$PYTHON" -m venv "$WORKBENCH_VENV"
fi
"$WORKBENCH_PYTHON" -m pip install --disable-pip-version-check --upgrade pip setuptools wheel
"$WORKBENCH_PYTHON" -m pip install --disable-pip-version-check -e "$SOURCE_ROOT"
if (( ! SKIP_VISUAL_QA )); then
  "$WORKBENCH_PYTHON" -m pip install --disable-pip-version-check opencv-python Pillow
fi

if [[ ! -e "$VECTCUT_ROOT" ]]; then
  git clone --no-checkout "$VECTCUT_REPOSITORY" "$VECTCUT_ROOT"
  git -C "$VECTCUT_ROOT" fetch --depth 1 origin "$VECTCUT_REF"
  git -C "$VECTCUT_ROOT" checkout --detach "$VECTCUT_REF"
elif [[ ! -f "${VECTCUT_ROOT}/capcut_server.py" ]]; then
  echo "Existing VectCutAPI directory is invalid: $VECTCUT_ROOT" >&2
  exit 1
else
  existing_ref="$(git -C "$VECTCUT_ROOT" rev-parse HEAD 2>/dev/null || true)"
  [[ "$existing_ref" == "$VECTCUT_REF" ]] || echo "Warning: keeping existing VectCutAPI revision ${existing_ref:-unknown}; tested revision is $VECTCUT_REF" >&2
fi

if [[ ! -x "$VECTCUT_PYTHON" ]]; then
  "$PYTHON" -m venv "$VECTCUT_VENV"
fi
"$VECTCUT_PYTHON" -m pip install --disable-pip-version-check --upgrade pip
"$VECTCUT_PYTHON" -m pip install --disable-pip-version-check -r "${VECTCUT_ROOT}/requirements.txt"

VECTCUT_PROFILE="${VECTCUT_ROOT}/config.json"
profile_json='{"draft_profile":"jianying_pro_10","is_capcut_env":false,"port":9001,"is_upload_draft":false,"draft_domain":"http://127.0.0.1:9001"}'
if (( FORCE_CONFIG )) || [[ ! -f "$VECTCUT_PROFILE" ]]; then
  cut_workbench_write_json "$PYTHON" "$VECTCUT_PROFILE" "$profile_json"
else
  echo "Warning: keeping existing VectCutAPI config: $VECTCUT_PROFILE (use --force-config to replace)." >&2
fi

runtime_json="$($PYTHON - "$JIANYING_DRAFT_FOLDER" "$(command -v ffprobe)" <<'PY'
import json
import sys
print(json.dumps({
    "vectcut": {"base_url": "http://127.0.0.1:9001", "timeout": 120, "draft_folder": sys.argv[1]},
    "providers": [{"kind": "ffprobe", "executable": sys.argv[2]}],
}))
PY
)"
effective_draft_folder="$JIANYING_DRAFT_FOLDER"
if (( FORCE_CONFIG )) || [[ ! -f "$RUNTIME_CONFIG" ]]; then
  cut_workbench_write_json "$PYTHON" "$RUNTIME_CONFIG" "$runtime_json"
else
  effective_draft_folder="$(cut_workbench_read_runtime_value "$PYTHON" "$RUNTIME_CONFIG" "vectcut.draft_folder" 2>/dev/null || printf '%s' "$JIANYING_DRAFT_FOLDER")"
  echo "Warning: keeping existing runtime config: $RUNTIME_CONFIG (use --force-config to replace)." >&2
fi

mcp_json="$($PYTHON - "$WORKBENCH_PYTHON" "$RUNTIME_ROOT" "$RUNTIME_CONFIG" "$SOURCE_ROOT" <<'PY'
import json
import sys
print(json.dumps({"mcpServers": {"cut-workbench": {
    "command": sys.argv[1],
    "args": ["-m", "cut_workbench.cli", "--root", sys.argv[2], "--config", sys.argv[3], "mcp"],
    "cwd": sys.argv[4],
}}}))
PY
)"
cut_workbench_write_json "$PYTHON" "$MCP_CONFIG" "$mcp_json"

receipt_json="$($PYTHON - "$SOURCE_ROOT" "$INSTALL_ROOT" "$RUNTIME_ROOT" "$effective_draft_folder" "$WORKBENCH_PYTHON" "$VECTCUT_PYTHON" "$VECTCUT_REPOSITORY" "$VECTCUT_REF" "$RUNTIME_CONFIG" "$MCP_CONFIG" "$PYTHON_VERSION" "$SKIP_VISUAL_QA" <<'PY'
import datetime
import json
import sys
print(json.dumps({
    "installed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "source_root": sys.argv[1], "install_root": sys.argv[2], "runtime_root": sys.argv[3],
    "jianying_draft_folder": sys.argv[4], "workbench_python": sys.argv[5],
    "vectcut_python": sys.argv[6], "vectcut_repository": sys.argv[7], "vectcut_ref": sys.argv[8],
    "runtime_config": sys.argv[9], "agent_mcp_config": sys.argv[10], "python_version": sys.argv[11],
    "visual_qa_installed": sys.argv[12] == "0",
}))
PY
)"
cut_workbench_write_json "$PYTHON" "${INSTALL_ROOT}/installation.json" "$receipt_json"

echo "Installation complete."
echo "Runtime config: $RUNTIME_CONFIG"
echo "Agent MCP snippet: $MCP_CONFIG"
echo "Next: scripts/posix/start-local-editing.sh then scripts/posix/doctor-local-editing.sh"

if (( START_SERVICE )); then
  bash "${SCRIPT_DIR}/start-local-editing.sh" --install-root "$INSTALL_ROOT"
fi
