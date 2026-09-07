#!/usr/bin/env bash
# Check whether this macOS/Linux machine can create local editable Jianying drafts.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd -P)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

INSTALL_ROOT=""
MEDIA_PATH=""
JSON_OUTPUT=0
TESTED_VECTCUT_REF="d14e70749c9331424ab816a402bb45417c50cf68"
declare -a CHECKS=()
CRITICAL_FAILURES=0

usage() {
  cat <<'EOF'
Usage: scripts/posix/doctor-local-editing.sh [options]
  --install-root PATH  Installation state directory
  --media-path PATH    Optional read-only ffprobe stream check
  --json               Print machine-readable results
  -h, --help           Show this help
EOF
}

while (($#)); do
  case "$1" in
    --install-root) INSTALL_ROOT="$2"; shift 2 ;;
    --media-path) MEDIA_PATH="$2"; shift 2 ;;
    --json) JSON_OUTPUT=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

add_check() {
  local name="$1" passed="$2" critical="$3" detail="$4" fix="$5"
  CHECKS+=("${name}"$'\t'"${passed}"$'\t'"${critical}"$'\t'"${detail}"$'\t'"${fix}")
  [[ "$passed" == "true" || "$critical" != "true" ]] || CRITICAL_FAILURES=$((CRITICAL_FAILURES + 1))
}

INSTALL_ROOT="$(cut_workbench_install_root "$INSTALL_ROOT")"
RUNTIME_ROOT="${INSTALL_ROOT}/runtime"
RUNTIME_CONFIG="${RUNTIME_ROOT}/runtime-config.json"
WORKBENCH_PYTHON="${INSTALL_ROOT}/workbench-venv/bin/python"
VECTCUT_ROOT="${INSTALL_ROOT}/tools/VectCutAPI"
VECTCUT_PROFILE="${VECTCUT_ROOT}/config.json"
VECTCUT_URL="http://127.0.0.1:9001"
DRAFT_FOLDER=""

if [[ -f "$RUNTIME_CONFIG" ]]; then
  add_check "runtime-config" true true "$RUNTIME_CONFIG" ""
  if [[ -x "$WORKBENCH_PYTHON" ]]; then
    VECTCUT_URL="$(cut_workbench_read_runtime_value "$WORKBENCH_PYTHON" "$RUNTIME_CONFIG" "vectcut.base_url" 2>/dev/null || printf '%s' "$VECTCUT_URL")"
    DRAFT_FOLDER="$(cut_workbench_read_runtime_value "$WORKBENCH_PYTHON" "$RUNTIME_CONFIG" "vectcut.draft_folder" 2>/dev/null || true)"
  fi
else
  add_check "runtime-config" false true "Missing $RUNTIME_CONFIG" "Run install-local-editing.sh."
fi

if cut_workbench_is_loopback_url "$VECTCUT_URL"; then
  add_check "vectcut-loopback-url" true true "$VECTCUT_URL" ""
else
  add_check "vectcut-loopback-url" false true "$VECTCUT_URL" "Use localhost/127.0.0.1/::1 only."
fi

if [[ -x "$WORKBENCH_PYTHON" ]] && "$WORKBENCH_PYTHON" -c 'import cut_workbench' >/dev/null 2>&1; then
  add_check "cut-workbench-python" true true "$WORKBENCH_PYTHON" ""
else
  add_check "cut-workbench-python" false true "Missing or invalid $WORKBENCH_PYTHON" "Run install-local-editing.sh."
fi

for binary in ffmpeg ffprobe; do
  if command -v "$binary" >/dev/null 2>&1; then
    add_check "${binary}" true true "$(command -v "$binary")" ""
  else
    add_check "${binary}" false true "${binary} is not on PATH" "Install FFmpeg, then rerun doctor."
  fi
done

if [[ -f "$VECTCUT_PROFILE" ]]; then
  profile_ok=false
  if [[ -x "$WORKBENCH_PYTHON" ]]; then
    profile_ok="$($WORKBENCH_PYTHON - "$VECTCUT_PROFILE" <<'PY'
import json
import sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
print("true" if value.get("draft_profile") == "jianying_pro_10" and value.get("port") == 9001 and value.get("is_capcut_env") is False else "false")
PY
)"
  fi
  add_check "vectcut-profile" "$profile_ok" true "$VECTCUT_PROFILE" "Run install-local-editing.sh --force-config."
else
  add_check "vectcut-profile" false true "Missing $VECTCUT_PROFILE" "Run install-local-editing.sh."
fi

if [[ -d "${VECTCUT_ROOT}/.git" ]] && command -v git >/dev/null 2>&1; then
  actual_ref="$(git -C "$VECTCUT_ROOT" rev-parse HEAD 2>/dev/null || true)"
  if [[ "$actual_ref" == "$TESTED_VECTCUT_REF" ]]; then
    add_check "vectcut-tested-revision" true false "$actual_ref" ""
  else
    add_check "vectcut-tested-revision" false false "${actual_ref:-unknown}" "Use a fresh installer-managed VectCutAPI directory or checkout $TESTED_VECTCUT_REF."
  fi
else
  add_check "vectcut-tested-revision" false false "Git revision unavailable" "Install Git or use a fresh installer-managed VectCutAPI directory."
fi

if [[ -n "$DRAFT_FOLDER" && -d "$DRAFT_FOLDER" ]] && cut_workbench_directory_writable "$DRAFT_FOLDER"; then
  add_check "jianying-draft-folder" true true "$DRAFT_FOLDER" ""
else
  add_check "jianying-draft-folder" false true "${DRAFT_FOLDER:-No configured draft folder}" "Pass --jianying-draft-folder to the installer with an existing writable folder."
fi

if cut_workbench_vectcut_health "$VECTCUT_URL"; then
  add_check "local-vectcut-service" true true "$VECTCUT_URL" ""
else
  add_check "local-vectcut-service" false true "$VECTCUT_URL" "Run start-local-editing.sh, then rerun doctor."
fi

if [[ -x "$WORKBENCH_PYTHON" ]] && "$WORKBENCH_PYTHON" -c 'import cv2, PIL' >/dev/null 2>&1; then
  add_check "visual-qa-packages" true false "opencv-python + Pillow" ""
else
  add_check "visual-qa-packages" false false "opencv-python/Pillow unavailable" "Rerun install-local-editing.sh without --skip-visual-qa."
fi

if [[ -n "$MEDIA_PATH" ]]; then
  if [[ ! -f "$MEDIA_PATH" ]]; then
    add_check "media-stream-probe" false true "Media file does not exist: $MEDIA_PATH" "Pass an existing local video/audio file."
  elif ! command -v ffprobe >/dev/null 2>&1; then
    add_check "media-stream-probe" false true "ffprobe is unavailable" "Install FFmpeg."
  else
    stream_types="$(ffprobe -v error -show_entries stream=codec_type -of csv=p=0 "$MEDIA_PATH" 2>/dev/null | paste -sd, - || true)"
    if [[ -n "$stream_types" ]]; then
      add_check "media-stream-probe" true true "Detected streams: $stream_types" ""
    else
      add_check "media-stream-probe" false true "ffprobe could not read $MEDIA_PATH" "Verify the media file is readable by FFmpeg."
    fi
  fi
fi

if (( JSON_OUTPUT )); then
  JSON_PYTHON="$WORKBENCH_PYTHON"
  if [[ ! -x "$JSON_PYTHON" ]]; then
    JSON_PYTHON="$(command -v python3 || true)"
  fi
  [[ -n "$JSON_PYTHON" ]] || { echo "Python 3 is required to print JSON output." >&2; exit 1; }
  printf '%s\n' "${CHECKS[@]}" | "$JSON_PYTHON" -c '
import json
import sys

checks = []
for line in sys.stdin.read().splitlines():
    name, passed, critical, detail, fix = line.split("\t", 4)
    checks.append({"check": name, "passed": passed == "true", "critical": critical == "true", "detail": detail, "fix": fix})
print(json.dumps({"passed": int(sys.argv[1]) == 0, "vectcut_url": sys.argv[2], "checks": checks}, ensure_ascii=False, indent=2))
' "$CRITICAL_FAILURES" "$VECTCUT_URL"
else
  printf '%-28s %-8s %-9s %s\n' "CHECK" "PASSED" "CRITICAL" "DETAIL"
  for record in "${CHECKS[@]}"; do
    IFS=$'\t' read -r name passed critical detail fix <<<"$record"
    printf '%-28s %-8s %-9s %s\n' "$name" "$passed" "$critical" "$detail"
    [[ -z "$fix" ]] || printf '  fix: %s\n' "$fix"
  done
  if (( CRITICAL_FAILURES == 0 )); then
    echo "Doctor passed: this machine can create local editable drafts and run FFmpeg media checks."
  else
    echo "Doctor found ${CRITICAL_FAILURES} critical issue(s). Apply the listed fix and rerun." >&2
  fi
fi

(( CRITICAL_FAILURES == 0 ))
