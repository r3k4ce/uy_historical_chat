#!/usr/bin/env bash
set -uo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
"$root/scripts/ensure.sh" || exit $?

(cd "$root/backend" && exec uv run --locked python -m uvicorn artigas_mvp_backend.main:app --reload) &
backend_pid=$!
(cd "$root/frontend" && exec npm run dev) &
frontend_pid=$!

cleanup() {
    trap - INT TERM EXIT
    kill "$backend_pid" "$frontend_pid" 2>/dev/null || true
    wait "$backend_pid" "$frontend_pid" 2>/dev/null || true
}

trap 'status=$?; cleanup; exit "$status"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

wait -n "$backend_pid" "$frontend_pid"
exit $?
