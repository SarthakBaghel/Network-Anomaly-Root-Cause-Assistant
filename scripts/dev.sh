#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

cleanup() {
  kill "${BACKEND_PID:-}" "${FRONTEND_PID:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

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
wait "$BACKEND_PID" "$FRONTEND_PID"

