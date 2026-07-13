#!/usr/bin/env bash
# dev-web-bg.sh — start the Next.js dev server in a detached tmux session
#
# Why this exists: previously we started `pnpm dev` with `nohup ... & disown`,
# but that process died every time the spawning shell (e.g. an AI-agent basher)
# exited or timed out. tmux runs as a real daemon — the session survives
# independent of any parent process, so pnpm dev stays up across basher
# timeouts, terminal closures, and AI-agent turn boundaries.
#
# Usage:
#   scripts/dev-web-bg.sh           # start (idempotent — refuses if already up)
#   scripts/dev-web-bg.sh --restart # kill + start (e.g. after a .env change)
#   scripts/dev-web-bg.sh --status  # check if the session + :3000 are up
#   scripts/dev-web-bg.sh --stop    # kill the session
#   scripts/dev-web-bg.sh --tail    # tail the pnpm dev log
#   scripts/dev-web-bg.sh --attach  # attach to the session (Ctrl-b d to detach)
#
# The session name is "web-dev" so it doesn't collide with other dev workflows.

set -euo pipefail

SESSION="web-dev"
PORT=3000
LOG="/tmp/pnpm-dev.log"
WEB_DIR="web"

# Repo root = parent of this script's directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WEB_PATH="${REPO_ROOT}/${WEB_DIR}"

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
  # Process info via lsof (informational only — the curl health check below
  # is the source of truth for pass/fail, because lsof can misreport for
  # child processes spawned by tmux on some platforms / lsof versions).
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:${PORT} -sTCP:LISTEN 2>/dev/null | head -3 | sed 's/^/  /' || true
  fi
  echo
  echo "=== health check ==="
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:${PORT}/" 2>/dev/null || echo "000")
  echo "  GET http://127.0.0.1:${PORT}/ -> $code"
  exit 0
fi

if [[ "$cmd" == "--stop" || "$cmd" == "stop" ]]; then
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux kill-session -t "$SESSION"
    echo "killed tmux session '$SESSION'"
  else
    echo "no tmux session '$SESSION' to kill"
  fi
  # Belt-and-suspenders: also kill any orphaned next/pnpm processes
  pkill -9 -f "next dev" 2>/dev/null || true
  pkill -9 -f "next-server" 2>/dev/null || true
  pkill -9 -f "next/dist" 2>/dev/null || true
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

# Kill any orphaned next/pnpm processes (in case tmux was killed ungracefully)
pkill -9 -f "next dev" 2>/dev/null || true
pkill -9 -f "next-server" 2>/dev/null || true
pkill -9 -f "next/dist" 2>/dev/null || true
sleep 1

# Load .env from the repo root + web/ if present (Next.js only reads web/.env,
# but the API + workers read the root .env — we keep the two in sync via
# shared DATABASE_URL/S3_* values).
if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env"
  set +a
fi
if [[ -f "${WEB_PATH}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${WEB_PATH}/.env"
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
export API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8000}"

# Warn loudly if the SECRETS_KEK is the publicly-known docker-compose dev key.
# This is fine for local dev (the value is the same across all dev checkouts
# so web + API + workers agree on the same KEK) but it must NEVER be used in
# production. If a user accidentally runs this in a fresh checkout without
# copying .env.example -> .env, the warning above makes the situation obvious.
_DEV_KEK="YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE="
if [[ "${SECRETS_KEK}" == "${_DEV_KEK}" ]]; then
  echo "NOTE: SECRETS_KEK is using the public docker-compose dev default (fine for local dev)."
  echo "      Set your own in .env (copy from .env.example) before any non-local use."
fi

cd "$WEB_PATH"

# Start pnpm dev in a detached tmux session. The -H 0.0.0.0 flag is required
# so the dev server binds to all interfaces (127.0.0.1 + localhost + LAN).
# Without it, the dev server binds to localhost only and a browser hitting
# 127.0.0.1:3000 gets ERR_CONNECTION_REFUSED.
#
# The command is wrapped in a `while true; do ...; done` loop because
# Next.js 16's auto-restart mechanism (triggered by changes to
# `next.config.ts` or any other file the dev server watches) **intentionally
# exits its process with code 0** so a process supervisor (pm2, nodemon,
# tmux) respawns it. tmux's `new-session` runs exactly one command; if
# that command exits, tmux tears down the session. The `while` loop
# respawns pnpm dev the instant Next.js exits, keeping the session alive
# across any number of auto-restart cycles. Uvicorn doesn't need this
# because it isn't run with --reload (its dev script is a plain `uvicorn`
# invocation, no file-watcher process group to fight).
#
# The `|| sleep 30` provides a backoff on real errors: if pnpm dev exits
# with a non-zero code (missing dep, port conflict, config syntax error),
# we wait 30s before retrying. Without this, a persistent error would
# spin every 2s and fill the log; with it, the user has time to notice
# via `make dev-web-tail` and Ctrl-C in `--attach` won't tear the
# session down permanently.
#
# `> ${LOG}` (not `>>`) truncates the log on each restart so a stale
# failed parse doesn't pollute the next run's log (the previous run's
# errors are already in the git history of the user's mental model).
#
# We export the resolved env vars inside a generated wrapper script so
# the tmux session picks them up reliably (tmux does not inherit the
# current shell's environment). See dev-api-bg.sh for the same pattern.
WRAPPER=$(mktemp /tmp/web-dev-wrapper.XXXXXX.sh)
cat > "$WRAPPER" <<EOF
#!/usr/bin/env bash
# Preserve the parent shell's PATH so pnpm/node resolve inside tmux.
export PATH=$(printf '%q' "$PATH")
export DATABASE_URL=$(printf '%q' "$DATABASE_URL")
export S3_ENDPOINT=$(printf '%q' "$S3_ENDPOINT")
export S3_ACCESS_KEY=$(printf '%q' "$S3_ACCESS_KEY")
export S3_SECRET_KEY=$(printf '%q' "$S3_SECRET_KEY")
export S3_BUCKET=$(printf '%q' "$S3_BUCKET")
export SECRETS_KEK=$(printf '%q' "$SECRETS_KEK")
export API_BASE_URL=$(printf '%q' "$API_BASE_URL")
rm -f "\$0"
while true; do
  pnpm exec next dev -H 0.0.0.0 -p ${PORT} > ${LOG} 2>&1 || sleep 30
  sleep 2
done
EOF
chmod +x "$WRAPPER"

# Run the wrapper through bash explicitly so it works even if /tmp is
# mounted noexec (the file still needs read permission, not execute).
tmux new-session -d -s "$SESSION" "bash \"$WRAPPER\""

# Poll for ready (max 60s)
echo "starting pnpm dev in tmux session '$SESSION' (logs: $LOG) ..."
ready=0
for i in $(seq 1 60); do
  if curl -s -o /dev/null -w '%{http_code}' --max-time 2 "http://127.0.0.1:${PORT}/" 2>/dev/null | grep -q '^200$'; then
    ready=1
    echo "ready after ${i}s"
    break
  fi
  sleep 1
done

if [[ "$ready" -ne 1 ]]; then
  echo "ERROR: pnpm dev did not become ready within 60s. Tail of $LOG:"
  tail -20 "$LOG" || true
  exit 1
fi

echo
echo "pnpm dev is up in tmux session '$SESSION'."
echo "  URLs:"
echo "    http://127.0.0.1:${PORT}/"
echo "    http://localhost:${PORT}/"
echo "  Commands:"
echo "    $0 --status  # check health"
echo "    $0 --tail    # tail the log"
echo "    $0 --attach  # attach (Ctrl-b d to detach)"
echo "    $0 --stop    # kill the session"
echo "    $0 --restart # recycle (e.g. after .env change)"
