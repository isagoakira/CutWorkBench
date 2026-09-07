#!/usr/bin/env bash
# Stop only the VectCutAPI process previously launched by start-local-editing.sh.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd -P)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

INSTALL_ROOT=""
while (($#)); do
  case "$1" in
    --install-root) INSTALL_ROOT="$2"; shift 2 ;;
    -h|--help) echo "Usage: scripts/posix/stop-local-editing.sh [--install-root PATH]"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

INSTALL_ROOT="$(cut_workbench_install_root "$INSTALL_ROOT")"
SERVICE_STATE="${INSTALL_ROOT}/service/vectcut-service.json"
[[ -f "$SERVICE_STATE" ]] || { echo "No managed VectCutAPI service state exists; nothing was stopped."; exit 0; }

JSON_PYTHON="${INSTALL_ROOT}/workbench-venv/bin/python"
if [[ ! -x "$JSON_PYTHON" ]]; then
  JSON_PYTHON="$(command -v python3 || true)"
fi
[[ -n "$JSON_PYTHON" ]] || { echo "Python 3 is required to read managed service state." >&2; exit 1; }

readarray -t values < <("$JSON_PYTHON" - "$SERVICE_STATE" <<'PY'
import json
import sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
print(value.get("pid", ""))
print(value.get("executable", ""))
PY
)
pid="${values[0]:-}"
expected_executable="${values[1]:-}"
[[ "$pid" =~ ^[0-9]+$ && -n "$expected_executable" ]] || { echo "Invalid managed VectCutAPI service state: $SERVICE_STATE" >&2; exit 1; }

if ! kill -0 "$pid" 2>/dev/null; then
  rm -f -- "$SERVICE_STATE"
  echo "Managed VectCutAPI is not running; removed stale service state."
  exit 0
fi
if [[ "$(uname -s)" == "Linux" && -r "/proc/${pid}/cmdline" ]]; then
  command_line="$(tr '\0' ' ' < "/proc/${pid}/cmdline")"
else
  command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
fi
if [[ "$command_line" != *"$expected_executable"* || "$command_line" != *"serve_vectcut.py"* ]]; then
  echo "Refusing to stop PID $pid: it does not match the managed VectCutAPI command." >&2
  exit 1
fi
kill "$pid"
rm -f -- "$SERVICE_STATE"
echo "Stopped managed VectCutAPI process $pid."
