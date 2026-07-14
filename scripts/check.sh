#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
"$root/scripts/ensure.sh"

pushd "$root/backend" >/dev/null
uv run --locked python -m ruff format --check .
uv run --locked python -m ruff check .
uv run --locked python -m pyright
uv run --locked python -m pytest
popd >/dev/null

pushd "$root/frontend" >/dev/null
npm run test
npm run typecheck
npm run lint
npm run build
popd >/dev/null
