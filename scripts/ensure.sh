#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
skip_hook_install=false

if [[ ${1:-} == "--skip-hook-install" ]]; then
    skip_hook_install=true
    shift
fi
if (($#)); then
    echo "Usage: scripts/ensure.sh [--skip-hook-install]" >&2
    exit 2
fi

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Missing required tool: $1. See README.md for supported versions." >&2
        exit 1
    fi
}

require_command uv
require_command node
require_command npm

uv_version=$(uv --version | awk '{print $2}')
node_version=$(node --version)
npm_version=$(npm --version)
if [[ $uv_version != "0.11.26" ]]; then
    echo "Unsupported uv version $uv_version; install uv 0.11.26." >&2
    exit 1
fi
if [[ ${node_version#v} != 24.* ]]; then
    echo "Unsupported Node.js version $node_version; install Node.js 24." >&2
    exit 1
fi
if [[ $npm_version != 11.* ]]; then
    echo "Unsupported npm version $npm_version; install npm 11." >&2
    exit 1
fi

backend_path="$root/backend"
path_sentinel="$backend_path/.venv/.artigas-project-path"
stored_path=""
if [[ -f $path_sentinel ]]; then
    stored_path=$(<"$path_sentinel")
fi

pushd "$backend_path" >/dev/null
if [[ $stored_path != "$backend_path" ]]; then
    echo "Repairing backend environment for $backend_path"
    uv sync --locked --dev --reinstall
    printf '%s\n' "$backend_path" >"$path_sentinel"
elif ! uv sync --locked --dev --check; then
    echo "Synchronizing backend dependencies"
    uv sync --locked --dev
fi
popd >/dev/null

lock_file="$root/frontend/package-lock.json"
lock_sentinel="$root/frontend/node_modules/.artigas-package-lock.sha256"
if command -v sha256sum >/dev/null 2>&1; then
    lock_hash=$(sha256sum "$lock_file" | awk '{print $1}')
elif command -v shasum >/dev/null 2>&1; then
    lock_hash=$(shasum -a 256 "$lock_file" | awk '{print $1}')
else
    echo "Missing SHA-256 tool: install sha256sum or shasum." >&2
    exit 1
fi
stored_hash=""
if [[ -f $lock_sentinel ]]; then
    stored_hash=$(<"$lock_sentinel")
fi
if [[ $stored_hash != "$lock_hash" ]] || ! (cd "$root/frontend" && npm ls --depth=0 >/dev/null 2>&1); then
    echo "Installing frontend dependencies from package-lock.json"
    (cd "$root/frontend" && npm ci)
    printf '%s\n' "$lock_hash" >"$lock_sentinel"
fi

if [[ $skip_hook_install == false && -z ${ARTIGAS_SKIP_HOOK_INSTALL:-} && -z ${CI:-} ]]; then
    "$backend_path/.venv/bin/python" -m pre_commit install --hook-type pre-commit --overwrite
fi
