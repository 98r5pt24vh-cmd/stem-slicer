#!/bin/zsh
set -euo pipefail

repository_root=${0:A:h}
electron_root="$repository_root/electron-app"
bundled_dependencies="/Users/nrgy/.cache/codex-runtimes/codex-primary-runtime/dependencies"
node_bin=${SLICER_NODE_BIN:-"$bundled_dependencies/node/bin/node"}
pnpm_bin=${SLICER_PNPM_BIN:-"$bundled_dependencies/bin/fallback/pnpm"}

if [[ ! -x "$node_bin" ]]; then
  node_bin=$(command -v node || true)
fi
if [[ ! -x "$pnpm_bin" ]]; then
  pnpm_bin=$(command -v pnpm || true)
fi
if [[ ! -x "$node_bin" || ! -x "$pnpm_bin" ]]; then
  print -u2 "Node 24 and pnpm 11.19.0 are required to launch Slicer."
  exit 1
fi

export PATH="${node_bin:h}:${pnpm_bin:h}:$PATH"
cd "$electron_root"

if [[ ! -d node_modules ]]; then
  "$pnpm_bin" install --frozen-lockfile
fi
if [[ ! -x .runtime/python/bin/python3.12 ]]; then
  print -u2 "The Slicer Python runtime is missing. Run pnpm run runtime:setup first."
  exit 1
fi

exec "$pnpm_bin" dev
