#!/usr/bin/env bash
# Shared helpers for the macOS/Linux local Cut Workbench setup.

cut_workbench_source_root() {
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P
}

cut_workbench_install_root() {
  if [[ -n "${1:-}" ]]; then
    printf '%s\n' "$1"
    return
  fi
  if [[ "$(uname -s)" == "Darwin" ]]; then
    printf '%s\n' "${HOME}/Library/Application Support/CutWorkbench"
    return
  fi
  printf '%s\n' "${XDG_STATE_HOME:-${HOME}/.local/state}/cut-workbench"
}

cut_workbench_default_draft_folder() {
  if [[ "$(uname -s)" == "Darwin" ]]; then
    printf '%s\n' "${HOME}/Movies/JianyingPro/User Data/Projects/com.lveditor.draft"
  fi
}

cut_workbench_find_python() {
  local preferred="${1:-}"
  if [[ -n "$preferred" ]]; then
    [[ -x "$preferred" ]] || { echo "Python executable not found: $preferred" >&2; return 1; }
    printf '%s\n' "$preferred"
    return
  fi
  local candidate
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      command -v "$candidate"
      return
    fi
  done
  echo "Python 3.11+ was not found. Pass --python or install Python 3.11+." >&2
  return 1
}

cut_workbench_assert_python_version() {
  local python="$1"
  "$python" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit(f"Cut Workbench requires Python 3.11+; found {sys.version.split()[0]}")
print(".".join(map(str, sys.version_info[:3])))
PY
}

cut_workbench_is_loopback_url() {
  local url="$1"
  [[ "$url" =~ ^https?://(localhost|127\.0\.0\.1|\[::1\])(:[0-9]+)?(/.*)?$ ]]
}

cut_workbench_vectcut_health() {
  local url="${1%/}"
  command -v curl >/dev/null 2>&1 || return 1
  local body
  body="$(curl --fail --silent --show-error --max-time 5 "${url}/get_mask_types" 2>/dev/null)" || return 1
  grep -Eq '"success"[[:space:]]*:[[:space:]]*true' <<<"$body" && \
    grep -Eq '"output"[[:space:]]*:[[:space:]]*\[' <<<"$body"
}

cut_workbench_wait_vectcut_health() {
  local url="$1"
  local timeout_seconds="${2:-30}"
  local deadline=$((SECONDS + timeout_seconds))
  while (( SECONDS < deadline )); do
    if cut_workbench_vectcut_health "$url"; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

cut_workbench_directory_writable() {
  local directory="$1"
  [[ -d "$directory" ]] || return 1
  local probe="${directory}/.cut-workbench-write-${RANDOM}-${RANDOM}"
  : > "$probe" 2>/dev/null || return 1
  rm -f -- "$probe"
}

cut_workbench_write_json() {
  local python="$1"
  local target="$2"
  local json="$3"
  mkdir -p -- "$(dirname -- "$target")"
  "$python" - "$target" "$json" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
value = json.loads(sys.argv[2])
path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

cut_workbench_read_runtime_value() {
  local python="$1"
  local config="$2"
  local key="$3"
  "$python" - "$config" "$key" <<'PY'
import json
import sys

value = json.load(open(sys.argv[1], encoding="utf-8"))
for part in sys.argv[2].split("."):
    value = value[part]
print(value)
PY
}
