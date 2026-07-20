#!/usr/bin/env bash
# upload-batch.sh — Robust batch upload of .zevtc files to the API.
#
# Usage:
#   scripts/upload-batch.sh [directory]
#
# If no directory is given, defaults to ~/Projects/WvW/WvW (1)/
# Files are uploaded in round-robin order across immediate subdirectories
# to ensure a diverse mix of fights.
#
# Idempotent: re-uploading the same bytes returns the same upload id
# with no side effects (server-side deduplication).
#
# Features:
#   - Controlled concurrency via a FIFO semaphore (default 8 workers)
#   - Per-file retry with exponential back-off (default 3 attempts)
#   - Optional resume from a progress file
#   - Structured stdout/stderr logging and a summary report
#   - Dry-run mode to preview the file list without uploading
#
# Requires: bash >= 4, curl, and jq or python3 for JSON parsing.
#
# Examples:
#   scripts/upload-batch.sh
#   UPLOAD_CONCURRENCY=12 UPLOAD_MAX_RETRIES=5 scripts/upload-batch.sh /path/to/logs
#   UPLOAD_PROGRESS_FILE=/tmp/upload-progress.txt scripts/upload-batch.sh /path/to/logs
#   scripts/upload-batch.sh --dry-run /path/to/logs

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_BASE="${API_BASE:-http://127.0.0.1:8000}"
UPLOAD_URL="$API_BASE/api/v1/uploads"

# Tunables via environment
CONCURRENCY="${UPLOAD_CONCURRENCY:-8}"
MAX_RETRIES="${UPLOAD_MAX_RETRIES:-3}"
PROGRESS_FILE="${UPLOAD_PROGRESS_FILE:-}"
TIMEOUT_SEC="${UPLOAD_TIMEOUT_SEC:-180}"

show_help() {
  cat <<EOF
Usage: $0 [options] [directory]

Upload all .zevtc files from a directory tree to the API server.
Files are uploaded in round-robin order across subdirectories
for diverse fight mix.

Options:
  -n, --dry-run   List files that would be uploaded without sending them.
  -h, --help      Show this help message and exit.

Arguments:
  directory   Path to directory tree with .zevtc files
              (default: ~/Projects/WvW/WvW (1)/)

Environment:
  API_BASE              API server base URL (default: http://127.0.0.1:8000)
  UPLOAD_CONCURRENCY    Number of parallel uploads (default: 8)
  UPLOAD_MAX_RETRIES    Max attempts per file (default: 3)
  UPLOAD_PROGRESS_FILE  Path to a progress file for resume (default: none)
  UPLOAD_TIMEOUT_SEC    Per-request curl timeout (default: 180)
  UPLOAD_DISABLE_JQ     Force the python3 JSON parser even if jq is installed
                        (test/development toggle).

Examples:
  $0
  UPLOAD_CONCURRENCY=12 UPLOAD_MAX_RETRIES=5 $0 /path/to/logs
  UPLOAD_PROGRESS_FILE=/tmp/upload-progress.txt $0 /path/to/logs
EOF
}

DRY_RUN=0
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  show_help
  exit 0
fi
if [[ "${1:-}" == "--dry-run" || "${1:-}" == "-n" ]]; then
  DRY_RUN=1
  shift
fi

SRC_DIR="${1:-$HOME/Projects/WvW/WvW (1)}"
if [[ ! -d "$SRC_DIR" ]]; then
  echo "ERROR: source directory not found: $SRC_DIR" >&2
  echo "  Use --help for usage." >&2
  exit 1
fi

# Ensure we have the tools we need.  JSON status parsing prefers jq,
# but falls back to python3 if jq is unavailable.
for cmd in curl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  fi
done
# UPLOAD_DISABLE_JQ=1 is provided as a developer/test toggle to force the
# python3 fallback even when jq is installed.
if [[ -z "${UPLOAD_DISABLE_JQ:-}" ]] && command -v jq >/dev/null 2>&1; then
  JSON_PARSER="jq"
elif command -v python3 >/dev/null 2>&1; then
  JSON_PARSER="python3"
else
  echo "ERROR: required command not found: jq or python3 (one is needed for JSON parsing)" >&2
  exit 1
fi

# Build ordered file list in round-robin fashion across subdirectories.
# If no subdirectories exist, fall back to a flat sorted list.
build_file_list() {
  local dirs=()
  while IFS= read -r d; do
    dirs+=("$d")
  done < <(find "$SRC_DIR" -mindepth 1 -maxdepth 1 -type d | sort)

  if [[ ${#dirs[@]} -eq 0 ]]; then
    find "$SRC_DIR" -name '*.zevtc' -type f | sort
    return
  fi

  local -a file_lists
  local max_len=0
  for d in "${dirs[@]}"; do
    local list_file
    list_file=$(mktemp)
    find "$d" -name '*.zevtc' -type f | sort > "$list_file"
    file_lists+=("$list_file")
    local len
    len=$(wc -l < "$list_file")
    if ((len > max_len)); then
      max_len=$len
    fi
  done

  for ((i = 0; i < max_len; i++)); do
    for list_file in "${file_lists[@]}"; do
      local line
      line=$(sed -n "$((i + 1))p" "$list_file")
      [[ -n "$line" ]] && echo "$line"
    done
  done

  for list_file in "${file_lists[@]}"; do
    rm -f "$list_file"
  done
}

# Load already-completed paths from progress file.
declare -A DONE_MAP
if [[ -n "$PROGRESS_FILE" && -f "$PROGRESS_FILE" ]]; then
  while IFS= read -r line; do
    [[ -n "$line" && -f "$line" ]] && DONE_MAP["$line"]=1
  done < "$PROGRESS_FILE"
fi

# Build and filter the file list.
mapfile -t ALL_FILES < <(build_file_list)
TOTAL=${#ALL_FILES[@]}

declare -a FILES_TO_UPLOAD=()
for f in "${ALL_FILES[@]}"; do
  if [[ -n "${DONE_MAP[$f]:-}" ]]; then
    continue
  fi
  FILES_TO_UPLOAD+=("$f")
done

TO_UPLOAD=${#FILES_TO_UPLOAD[@]}

echo "=== Batch .zevtc upload ==="
echo "Source directory: $SRC_DIR"
echo "API endpoint:     $UPLOAD_URL"
echo "Concurrency:      $CONCURRENCY"
echo "Max attempts:     $MAX_RETRIES"
[[ -n "$PROGRESS_FILE" ]] && echo "Progress file:    $PROGRESS_FILE"
echo "Total files:      $TOTAL"
echo "Already done:     $((TOTAL - TO_UPLOAD))"
echo "Files to upload:  $TO_UPLOAD"
echo

if ((TO_UPLOAD == 0)); then
  echo "Nothing to upload."
  exit 0
fi

if ((DRY_RUN)); then
  for f in "${FILES_TO_UPLOAD[@]}"; do
    echo "[DRY-RUN] $f"
  done
  echo
  echo "=== Dry-run complete ==="
  echo "Total files found: $TOTAL"
  echo "Would upload:        $TO_UPLOAD"
  echo "Already done:        $((TOTAL - TO_UPLOAD))"
  exit 0
fi

PROGRESS_TMP=""
if [[ -n "$PROGRESS_FILE" ]]; then
  PROGRESS_TMP=$(mktemp)
  # Seed progress file with already-completed paths.
  for f in "${!DONE_MAP[@]}"; do
    [[ -f "$f" ]] && echo "$f" >> "$PROGRESS_TMP"
  done
fi
RESULTS_FILE=$(mktemp)

commit_progress() {
  if [[ -n "$PROGRESS_FILE" && -n "${PROGRESS_TMP:-}" && -f "$PROGRESS_TMP" ]]; then
    mkdir -p "$(dirname "$PROGRESS_FILE")"
    mv "$PROGRESS_TMP" "$PROGRESS_FILE"
  fi
}

# Make sure progress is committed on interrupt/exit.
cleanup() {
  trap - INT TERM EXIT
  # Reap any remaining workers; the subshells will close the semaphore
  # descriptor automatically when they exit.
  wait 2>/dev/null || true
  commit_progress
}
trap cleanup INT TERM EXIT

# Extract the "status" field from an API JSON response.  Falls back to
# "parse_error" if the response is not valid JSON or lacks the field.
parse_status() {
  local resp="$1"
  if [[ "$JSON_PARSER" == "jq" ]]; then
    echo "$resp" | jq -r '.status // "parse_error"' 2>/dev/null || echo "parse_error"
  else
    echo "$resp" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status') or 'parse_error')" 2>/dev/null || echo "parse_error"
  fi
}

# Upload a single file. Prints a status line and appends the result to
# the results file.
# Arguments: <file_path> <result_file> <progress_file>
upload_one() {
  local file_path="$1"
  local result_file="$2"
  local progress_file="$3"
  local attempt=0
  local status=""
  local resp=""

  while ((attempt <= MAX_RETRIES)); do
    resp=$(curl -s --max-time "$TIMEOUT_SEC" -X POST "$UPLOAD_URL" \
      -F "file=@$file_path" 2>/dev/null || echo '{"status":"curl_error"}')
    status=$(parse_status "$resp")

    case "$status" in
      completed|processing|pending|cached|duplicate)
        echo "OK $(basename "$file_path") ($status)"
        echo "OK" >> "$result_file"
        if [[ -n "$progress_file" ]]; then
          echo "$file_path" >> "$progress_file"
        fi
        return 0
        ;;
      curl_error|parse_error|rate_limited|queued)
        # Retry on transient or back-pressure errors.
        ;;
      *)
        echo "FAILED $(basename "$file_path"): $status" >&2
        echo "FAIL" >> "$result_file"
        return 1
        ;;
    esac

    if ((attempt < MAX_RETRIES)); then
      echo "RETRY $(basename "$file_path"): $status (attempt $attempt)" >&2
    fi
    attempt=$((attempt + 1))
    sleep "$((2 ** (attempt - 1)))"
  done

  echo "FAILED $(basename "$file_path"): exhausted retries ($status)" >&2
  echo "FAIL" >> "$result_file"
  return 1
}

# Worker that uploads a file and then returns a token to the semaphore.
# Arguments: <file_path> <result_file> <progress_file> <fd>
worker() {
  local fd="$4"
  local rc=0

  # Always release the semaphore slot, even if a `set -e` abort is
  # triggered inside upload_one. Without this the main loop can hang
  # forever waiting for a token that will never arrive.
  # This helper is invoked both by the EXIT trap and manually below.
  __release_token() {
    echo "token" >&"$fd" || true
  }
  trap '__release_token' EXIT

  upload_one "$1" "$2" "$3"
  rc=$?

  trap - EXIT
  __release_token
  return $rc
}

# Semaphore-based worker pool.
# Open a FIFO for read/write so we can pre-fill it with CONCURRENCY tokens.
FIFO=$(mktemp -u)
mkfifo "$FIFO"
exec {SEMAPHORE_FD}<>"$FIFO"
rm -f "$FIFO"

# Pre-fill the semaphore with CONCURRENCY slots.
for ((i = 0; i < CONCURRENCY; i++)); do
  echo "token" >&"$SEMAPHORE_FD"
done

for f in "${FILES_TO_UPLOAD[@]}"; do
  # Wait for a free slot.
  read -u "$SEMAPHORE_FD" _
  worker "$f" "$RESULTS_FILE" "$PROGRESS_TMP" "$SEMAPHORE_FD" &
done

# Wait for all workers to finish and drain the semaphore tokens so that
# `read` on the FIFO does not block forever.
wait
for ((i = 0; i < CONCURRENCY; i++)); do
  read -u "$SEMAPHORE_FD" _ || true
done
exec {SEMAPHORE_FD}<&-

# Count results.
uploaded=$(grep -c '^OK$' "$RESULTS_FILE" 2>/dev/null || true)
failed=$(grep -c '^FAIL$' "$RESULTS_FILE" 2>/dev/null || true)
uploaded=${uploaded:-0}
failed=${failed:-0}

rm -f "$RESULTS_FILE"

# Print summary and commit progress.
echo
echo "=== Upload complete ==="
echo "Total files found: $TOTAL"
echo "Uploaded:            $uploaded"
echo "Failed:              $failed"
echo "Already done:        $((TOTAL - TO_UPLOAD))"

cleanup

if ((failed > 0)); then
  exit 1
fi
