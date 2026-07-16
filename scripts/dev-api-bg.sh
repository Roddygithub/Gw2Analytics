#!/usr/bin/env bash
# dev-api-bg.sh — start the FastAPI uvicorn dev server in a detached tmux session
#
# Parallel to dev-web-bg.sh. The motivation is the same: previously uvicorn
# was started with `nohup ... & disown` and died every time the spawning shell
# (e.g. an AI-agent basher) exited. tmux runs as a real daemon — the session
# survives independent of any parent process.
#
# Usage:
#   scripts/dev-api-bg.sh           # start (idempotent — refuses if already up)
#   scripts/dev-api-bg.sh --restart # kill + start (e.g. after a .env change)
#   scripts/dev-api-bg.sh --status  # check if the session + :8000 are up
#   scripts/dev-api-bg.sh --stop    # kill the session
#   scripts/dev-api-bg.sh --tail    # tail the uvicorn log
#   scripts/dev-api-bg.sh --attach  # attach to the session (Ctrl-b d to detach)
#
# The session name is "api-dev" so it doesn't collide with web-dev or other
# dev workflows.

set -euo pipefail

SESSION="api-dev"
WORKER_SESSION="arq-worker"
PORT=8000
LOG="/tmp/uvicorn-dev.log"
WORKER_LOG="/tmp/arq-worker-dev.log"
API_DIR="apps/api"

# Repo root = parent of this script's directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
API_PATH="${REPO_ROOT}/${API_DIR}"

cmd="${1:-start}"

# --- helpers ------------------------------------------------------------------

# Build a small wrapper script that exports the shared dev env vars and
# then execs the provided command, tee-ing output to the given log file.
# The wrapper self-deletes via `rm -f "$0"` after exporting env vars,
# so the caller does not need to (and must not) remove it.
build_wrapper() {
  local command="$1"
  local log_file="$2"
  local prefix="$3"

  local wrapper
  wrapper=$(mktemp "/tmp/${prefix}-wrapper.XXXXXX.sh")

  cat > "$wrapper" <<EOF
#!/usr/bin/env bash
# Preserve the parent shell's PATH so uv/uvicorn/arq resolve inside tmux.
export PATH=$(printf '%q' "$PATH")
export DATABASE_URL=$(printf '%q' "$DATABASE_URL")
export S3_ENDPOINT=$(printf '%q' "$S3_ENDPOINT")
export S3_ACCESS_KEY=$(printf '%q' "$S3_ACCESS_KEY")
export S3_SECRET_KEY=$(printf '%q' "$S3_SECRET_KEY")
export S3_BUCKET=$(printf '%q' "$S3_BUCKET")
export SECRETS_KEK=$(printf '%q' "$SECRETS_KEK")
export ALLOW_INREQUEST_PARSE_FALLBACK=$(printf '%q' "$ALLOW_INREQUEST_PARSE_FALLBACK")
rm -f "\$0"
exec ${command} 2>&1 | tee ${log_file}
EOF
  chmod +x "$wrapper"
  echo "$wrapper"
}

# --- subcommand dispatch ------------------------------------------------------

if [[ "$cmd" == "--status" || "$cmd" == "status" ]]; then
  echo "=== tmux session ==="
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux ls | grep -E "^${SESSION}:" || true
    echo "  (running)"
  else
    echo "  (no tmux session named '$SESSION')"
  fi
  if tmux has-session -t "$WORKER_SESSION" 2>/dev/null; then
    tmux ls | grep -E "^${WORKER_SESSION}:" || true
    echo "  (worker running)"
  else
    echo "  (no tmux session named '$WORKER_SESSION')"
  fi
  echo
  echo "=== port :$PORT ==="
  # Process info via lsof (informational only — the curl health check below
  # is the source of truth for pass/fail, because lsof can misreport for
  # child processes spawned by tmux on some platforms / lsof versions).
  # The `|| true` is required: pipefail propagates lsof's no-match exit 1.
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:${PORT} -sTCP:LISTEN 2>/dev/null | head -3 | sed 's/^/  /' || true
  fi
  echo
  echo "=== health check ==="
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:${PORT}/healthz" 2>/dev/null || echo "000")
  echo "  GET http://127.0.0.1:${PORT}/healthz -> $code"
  exit 0
fi

if [[ "$cmd" == "--stop" || "$cmd" == "stop" ]]; then
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux kill-session -t "$SESSION"
    echo "killed tmux session '$SESSION'"
  else
    echo "no tmux session '$SESSION' to kill"
  fi
  if tmux has-session -t "$WORKER_SESSION" 2>/dev/null; then
    tmux kill-session -t "$WORKER_SESSION"
    echo "killed tmux session '$WORKER_SESSION'"
  else
    echo "no tmux session '$WORKER_SESSION' to kill"
  fi
  # Belt-and-suspenders: also kill any orphaned processes
  pkill -9 -f "uvicorn gw2analytics_api" 2>/dev/null || true
  pkill -9 -f "arq gw2analytics_api.workers" 2>/dev/null || true
  exit 0
fi

if [[ "$cmd" == "--tail" || "$cmd" == "tail" ]]; then
  exec tail -f "$LOG" "$WORKER_LOG"
fi

if [[ "$cmd" == "--tail-worker" || "$cmd" == "tail-worker" ]]; then
  exec tail -f "$WORKER_LOG"
fi

if [[ "$cmd" == "--attach" || "$cmd" == "attach" ]]; then
  exec tmux attach -t "$SESSION"
fi

if [[ "$cmd" == "--attach-worker" || "$cmd" == "attach-worker" ]]; then
  exec tmux attach -t "$WORKER_SESSION"
fi

if [[ "$cmd" == "--restart" || "$cmd" == "restart" ]]; then
  "$0" --stop
  sleep 1
  cmd="start"
fi

# --- start (default) ----------------------------------------------------------

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "tmux session '$SESSION' already exists — refusing to start a duplicate."
  echo "  Use '$0 --status' to check, '$0 --restart' to recycle, or '$0 --stop' to kill."
  exit 0
fi

# Kill any orphaned processes (in case tmux was killed ungracefully)
pkill -9 -f "uvicorn gw2analytics_api" 2>/dev/null || true
pkill -9 -f "arq gw2analytics_api.workers" 2>/dev/null || true
sleep 1

# Load .env from the repo root if present (uvicorn reads it via pydantic-settings,
# but we also load it into the env here so the tmux session inherits the right values).
if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env"
  set +a
fi

# Dev-required env vars. These are NOT secrets — they're the same
# docker-compose dev defaults. The user's .env overrides if present.
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://gw2analytics:gw2analytics@localhost:5432/gw2analytics}"
export S3_ENDPOINT="${S3_ENDPOINT:-localhost:9000}"
export S3_ACCESS_KEY="${S3_ACCESS_KEY:-gw2analytics}"
export S3_SECRET_KEY="${S3_SECRET_KEY:-gw2analytics-secret}"
export S3_BUCKET="${S3_BUCKET:-gw2analytics}"
export SECRETS_KEK="${SECRETS_KEK:-YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE=}"
# ALLOW_INREQUEST_PARSE_FALLBACK=1 makes the upload endpoint parse the .zevtc
# inline in the request handler when no arq worker is available (dev mode).
# Without it, POST /api/v1/uploads returns "pending" that never resolves in
# dev. Production keeps the default (0) so the worker queue is the only path.
export ALLOW_INREQUEST_PARSE_FALLBACK="${ALLOW_INREQUEST_PARSE_FALLBACK:-1}"

# Warn loudly if the SECRETS_KEK is the publicly-known docker-compose dev key.
# This is fine for local dev (the value is the same across all dev checkouts
# so web + API + workers agree on the same KEK) but it must NEVER be used in
# production.
_DEV_KEK="YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE="
if [[ "${SECRETS_KEK}" == "${_DEV_KEK}" ]]; then
  echo "NOTE: SECRETS_KEK is using the public docker-compose dev default (fine for local dev)."
  echo "      Set your own in .env (copy from .env.example) before any non-local use."
fi

cd "$API_PATH"

# Start uvicorn in a detached tmux session. The -H 0.0.0.0 flag binds all
# interfaces (127.0.0.1 + localhost + LAN). Without it, a browser hitting
# 127.0.0.1:8000 gets ERR_CONNECTION_REFUSED.
#
# We use a small generated wrapper script instead of ``tmux -e`` flags
# because ``-e`` is brittle: values containing spaces, quotes or shell
# metacharacters break the tmux command string. The wrapper exports the
# resolved env vars directly and then execs uvicorn, so the process
# tree is clean and tmux only sees a single executable argument.
WRAPPER=$(build_wrapper "uv run uvicorn gw2analytics_api.main:app --host 0.0.0.0 --port ${PORT} --timeout-keep-alive 120" "$LOG" "api-dev")

# Run the wrapper through bash explicitly so it works even if /tmp is
# mounted noexec (the file still needs read permission, not execute).
tmux new-session -d -s "$SESSION" "bash \"$WRAPPER\""

# Poll for ready (max 90s — alembic schema-drift check + DB connect can be slow)
echo "starting uvicorn in tmux session '$SESSION' (logs: $LOG) ..."
ready=0
for i in $(seq 1 90); do
  if curl -s -o /dev/null -w '%{http_code}' --max-time 2 "http://127.0.0.1:${PORT}/healthz" 2>/dev/null | grep -q '^200$'; then
    ready=1
    echo "ready after ${i}s"
    break
  fi
  sleep 1
done

if [[ "$ready" -ne 1 ]]; then
  rm -f "$WRAPPER"
  echo "ERROR: uvicorn did not become ready within 90s. Tail of $LOG:"
  tail -30 "$LOG" || true
  exit 1
fi

# Start the Arq parser worker alongside the API. In dev mode the upload
# endpoint can fall back to in-request parsing, but the worker is the
# preferred path and keeps the API responsive under load.
echo "starting arq worker in tmux session '$WORKER_SESSION' (logs: $WORKER_LOG) ..."
WORKER_WRAPPER=$(build_wrapper "uv run arq gw2analytics_api.workers.parser_settings.WorkerSettings" "$WORKER_LOG" "arq-dev")

tmux new-session -d -s "$WORKER_SESSION" "bash \"$WORKER_WRAPPER\""

# Briefly wait for the worker tmux session to materialise and warn if it
# did not. We consider the worker healthy when its tmux session exists
# and the log shows the arq startup line.
sleep 2
if ! tmux has-session -t "$WORKER_SESSION" 2>/dev/null; then
  rm -f "$WORKER_WRAPPER"
  echo
  echo "WARNING: arq worker tmux session '$WORKER_SESSION' did not start."
  echo "         Check $WORKER_LOG for details."
  echo "uvicorn is up in tmux session '$SESSION'."
else
  echo
  echo "uvicorn + arq worker are up in tmux sessions '$SESSION' and '$WORKER_SESSION'."
fi
echo
echo "  URLs:"
echo "    http://127.0.0.1:${PORT}/"
echo "    http://127.0.0.1:${PORT}/docs       (OpenAPI)"
echo "    http://127.0.0.1:${PORT}/api/v1/health/summary"
echo "  Commands:"
echo "    $0 --status  # check health"
echo "    $0 --tail    # tail the log"
echo "    $0 --attach  # attach (Ctrl-b d to detach)"
echo "    $0 --stop    # kill the sessions"
echo "    $0 --restart # recycle (e.g. after .env change)"
