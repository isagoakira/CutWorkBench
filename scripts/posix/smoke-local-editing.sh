#!/usr/bin/env bash
# Create one real short draft from a local source video; opt-in because it writes a new draft.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd -P)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

SOURCE=""
INSTALL_ROOT=""
while (($#)); do
  case "$1" in
    --source) SOURCE="$2"; shift 2 ;;
    --install-root) INSTALL_ROOT="$2"; shift 2 ;;
    -h|--help) echo "Usage: scripts/posix/smoke-local-editing.sh --source PATH [--install-root PATH]"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$SOURCE" && -f "$SOURCE" ]] || { echo "Pass an existing source video with --source." >&2; exit 2; }

SOURCE_ROOT="$(cut_workbench_source_root)"
INSTALL_ROOT="$(cut_workbench_install_root "$INSTALL_ROOT")"
RUNTIME_CONFIG="${INSTALL_ROOT}/runtime/runtime-config.json"
WORKBENCH_PYTHON="${INSTALL_ROOT}/workbench-venv/bin/python"
[[ -f "$RUNTIME_CONFIG" && -x "$WORKBENCH_PYTHON" ]] || { echo "Missing installation files. Run install-local-editing.sh first." >&2; exit 1; }

VECTCUT_URL="$(cut_workbench_read_runtime_value "$WORKBENCH_PYTHON" "$RUNTIME_CONFIG" "vectcut.base_url")"
DRAFT_FOLDER="$(cut_workbench_read_runtime_value "$WORKBENCH_PYTHON" "$RUNTIME_CONFIG" "vectcut.draft_folder")"
cut_workbench_vectcut_health "$VECTCUT_URL" || { echo "Local VectCutAPI is not healthy at $VECTCUT_URL. Run start-local-editing.sh first." >&2; exit 1; }
[[ -d "$DRAFT_FOLDER" ]] && cut_workbench_directory_writable "$DRAFT_FOLDER" || { echo "Configured draft folder is not writable: $DRAFT_FOLDER" >&2; exit 1; }

"$WORKBENCH_PYTHON" "${SOURCE_ROOT}/scripts/smoke_vectcut.py" \
  --source "$SOURCE" \
  --root "${INSTALL_ROOT}/smoke-runtime" \
  --url "$VECTCUT_URL" \
  --draft-folder "$DRAFT_FOLDER"

echo "Smoke draft created. On macOS, open Jianying Pro and confirm that it is visible and playable. WSL/Linux validates the local service and draft files only."
