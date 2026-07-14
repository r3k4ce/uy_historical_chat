#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

(cd "$root/backend" && exec uv run uvicorn artigas_mvp_backend.main:app --reload) &
backend_pid=$!
(cd "$root/frontend" && exec npm run dev) &
frontend_pid=$!

cleanup() {
    kill "$backend_pid" "$frontend_pid" 2>/dev/null || true
    wait "$backend_pid" "$frontend_pid" 2>/dev/null || true
}

trap cleanup INT TERM EXIT
wait "$backend_pid" "$frontend_pid"
