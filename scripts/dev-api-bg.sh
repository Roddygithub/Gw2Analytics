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
PORT=8000
LOG="/tmp/uvicorn-dev.log"
API_DIR="apps/api"

# Repo root = parent of this script's directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
API_PATH="${REPO_ROOT}/${API_DIR}"

cmd="${1:-start}"

# --- subcommand dispatch ------------------------------------------------------

if [[ "$cmd" == "--status" || "$cmd" == "status" ]]; then
  echo "=== tmux session ==="
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux ls | grep -E "^${SESSION}:" || true
    echo "  (running)"
  else
    echo "  (no tmux session named '$SESSION')"
  fi
  echo
  echo "=== port :$PORT ==="
  if command -v lsof >/dev/null 2>&1; then
    if lsof -nP -iTCP:${PORT} -sTCP:LISTEN 2>/dev/null | grep -q .; then
      lsof -nP -iTCP:${PORT} -sTCP:LISTEN 2>/dev/null | head -3
    else
      echo "  (not bound)"
    fi
  else
    echo "  (lsof not installed — check 'health check' below for the source of truth)"
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
  # Belt-and-suspenders: also kill any orphaned uvicorn processes
  pkill -9 -f "uvicorn gw2analytics_api" 2>/dev/null || true
  exit 0
fi

if [[ "$cmd" == "--tail" || "$cmd" == "tail" ]]; then
  exec tail -f "$LOG"
fi

if [[ "$cmd" == "--attach" || "$cmd" == "attach" ]]; then
  exec tmux attach -t "$SESSION"
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

# Kill any orphaned uvicorn processes (in case tmux was killed ungracefully)
pkill -9 -f "uvicorn gw2analytics_api" 2>/dev/null || true
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
tmux new-session -d -s "$SESSION" \
  "exec uv run uvicorn gw2analytics_api.main:app --host 0.0.0.0 --port ${PORT} 2>&1 | tee ${LOG}"

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
  echo "ERROR: uvicorn did not become ready within 90s. Tail of $LOG:"
  tail -30 "$LOG" || true
  exit 1
fi

echo
echo "uvicorn is up in tmux session '$SESSION'."
echo "  URLs:"
echo "    http://127.0.0.1:${PORT}/"
echo "    http://127.0.0.1:${PORT}/docs       (OpenAPI)"
echo "    http://127.0.0.1:${PORT}/api/v1/health/summary"
echo "  Commands:"
echo "    $0 --status  # check health"
echo "    $0 --tail    # tail the log"
echo "    $0 --attach  # attach (Ctrl-b d to detach)"
echo "    $0 --stop    # kill the session"
echo "    $0 --restart # recycle (e.g. after .env change)"
