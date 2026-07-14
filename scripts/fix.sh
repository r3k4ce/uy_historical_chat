#!/usr/bin/env bash
set -euo pipefail

pushd backend >/dev/null
uv run ruff check . --fix
uv run ruff format .
uv run ruff check .
uv run pyright
uv run pytest
popd >/dev/null

pushd frontend >/dev/null
npm run test
npm run typecheck
npm run lint
npm run build
popd >/dev/null
