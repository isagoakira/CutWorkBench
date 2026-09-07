#!/usr/bin/env bash
# Start the local VectCutAPI sidecar required to create editable Jianying drafts.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd -P)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

INSTALL_ROOT=""
VECTCUT_URL="http://127.0.0.1:9001"
VECTCUT_URL_SET=0
RUN_MCP=0

usage() {
  cat <<'EOF'
Usage: scripts/posix/start-local-editing.sh [options]
  --install-root PATH   Installation state directory
  --vectcut-url URL     Local loopback URL (default: http://127.0.0.1:9001)
  --mcp                 Run Cut Workbench MCP in the foreground after VectCutAPI is healthy
  -h, --help            Show this help
EOF
}

while (($#)); do
  case "$1" in
    --install-root) INSTALL_ROOT="$2"; shift 2 ;;
    --vectcut-url) VECTCUT_URL="$2"; VECTCUT_URL_SET=1; shift 2 ;;
    --mcp) RUN_MCP=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

SOURCE_ROOT="$(cut_workbench_source_root)"
INSTALL_ROOT="$(cut_workbench_install_root "$INSTALL_ROOT")"
RUNTIME_ROOT="${INSTALL_ROOT}/runtime"
RUNTIME_CONFIG="${RUNTIME_ROOT}/runtime-config.json"
VECTCUT_ROOT="${INSTALL_ROOT}/tools/VectCutAPI"
VECTCUT_PYTHON="${VECTCUT_ROOT}/.venv/bin/python"
WORKBENCH_PYTHON="${INSTALL_ROOT}/workbench-venv/bin/python"
SERVICE_ROOT="${INSTALL_ROOT}/service"
SERVICE_STATE="${SERVICE_ROOT}/vectcut-service.json"
STDOUT_LOG="${SERVICE_ROOT}/vectcut.stdout.log"
STDERR_LOG="${SERVICE_ROOT}/vectcut.stderr.log"

[[ -f "$RUNTIME_CONFIG" ]] || { echo "Missing runtime config. Run install-local-editing.sh first." >&2; exit 1; }
[[ -x "$VECTCUT_PYTHON" && -f "${VECTCUT_ROOT}/capcut_server.py" ]] || { echo "Missing local VectCutAPI installation. Run install-local-editing.sh first." >&2; exit 1; }
[[ -x "$WORKBENCH_PYTHON" ]] || { echo "Missing Cut Workbench virtual environment. Run install-local-editing.sh first." >&2; exit 1; }
if (( ! VECTCUT_URL_SET )); then
  VECTCUT_URL="$(cut_workbench_read_runtime_value "$WORKBENCH_PYTHON" "$RUNTIME_CONFIG" "vectcut.base_url" 2>/dev/null || printf '%s' "$VECTCUT_URL")"
fi
cut_workbench_is_loopback_url "$VECTCUT_URL" || { echo "VectCut URL must be a loopback HTTP(S) URL: $VECTCUT_URL" >&2; exit 1; }

if cut_workbench_vectcut_health "$VECTCUT_URL"; then
  echo "Local VectCutAPI is already healthy at $VECTCUT_URL"
else
  port="$("$WORKBENCH_PYTHON" - "$VECTCUT_URL" <<'PY'
from urllib.parse import urlparse
import sys
value = urlparse(sys.argv[1])
print(value.port or (443 if value.scheme == "https" else 80))
PY
)"
  mkdir -p -- "$SERVICE_ROOT"
  nohup "$VECTCUT_PYTHON" "${SOURCE_ROOT}/scripts/serve_vectcut.py" --repo "$VECTCUT_ROOT" --port "$port" \
    >"$STDOUT_LOG" 2>"$STDERR_LOG" < /dev/null &
  pid=$!
  state_json="$($WORKBENCH_PYTHON - "$pid" "$VECTCUT_PYTHON" "$VECTCUT_URL" <<'PY'
import datetime
import json
import sys
print(json.dumps({
    "pid": int(sys.argv[1]),
    "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "executable": sys.argv[2],
    "vectcut_url": sys.argv[3],
}))
PY
)"
  cut_workbench_write_json "$WORKBENCH_PYTHON" "$SERVICE_STATE" "$state_json"
  if ! cut_workbench_wait_vectcut_health "$VECTCUT_URL" 30; then
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" || true
    fi
    echo "Local VectCutAPI did not become healthy. Log tail:" >&2
    tail -n 30 "$STDERR_LOG" >&2 || true
    exit 1
  fi
  echo "Started local VectCutAPI at $VECTCUT_URL (PID $pid)."
fi

if (( RUN_MCP )); then
  echo "Starting Cut Workbench MCP in the foreground. Stop it with Ctrl+C."
  exec "$WORKBENCH_PYTHON" -m cut_workbench.cli --root "$RUNTIME_ROOT" --config "$RUNTIME_CONFIG" mcp
fi

echo "Local editing service is ready. Configure your Agent with agent-mcp-config.json, then run doctor-local-editing.sh."
