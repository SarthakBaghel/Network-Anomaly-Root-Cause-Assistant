#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

terminate_tree() {
  local pid="${1:-}"
  local child

  [[ -n "$pid" ]] || return 0
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    terminate_tree "$child"
  done
  kill "$pid" 2>/dev/null || true
}

cleanup() {
  trap - EXIT INT TERM HUP
  terminate_tree "${BACKEND_PID:-}"
  terminate_tree "${FRONTEND_PID:-}"
  wait "${BACKEND_PID:-}" "${FRONTEND_PID:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM HUP

(
  cd backend
  ../.venv/bin/uvicorn app.main:app --reload --port 8000
) &
BACKEND_PID=$!
(
  cd frontend
  npm run dev
) &
FRONTEND_PID=$!

# macOS ships Bash 3.2 without `wait -n`. Poll both direct children so the
# surviving service is stopped immediately when its peer exits (for example,
# when uvicorn cannot bind port 8000). Waiting for both here would leave a
# misleading frontend running without an API.
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 0.25
done

if kill -0 "$BACKEND_PID" 2>/dev/null; then
  wait "$FRONTEND_PID"
else
  wait "$BACKEND_PID"
fi
