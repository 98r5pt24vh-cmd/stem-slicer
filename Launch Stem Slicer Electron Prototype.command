#!/bin/zsh
set -euo pipefail

prototype_dir="${0:A:h}/electron-prototype"
runtime_root="/Users/nrgy/.cache/codex-runtimes/codex-primary-runtime/dependencies"
node_bin="$runtime_root/node/bin/node"
pnpm_bin="$runtime_root/bin/fallback/pnpm"

if [[ ! -x "$node_bin" || ! -x "$pnpm_bin" ]]; then
  print -u2 "Codex Node runtime unavailable. Open this prototype from the Codex workspace first."
  exit 1
fi

export PATH="$runtime_root/node/bin:$runtime_root/bin/fallback:$PATH"
cd "$prototype_dir"

if [[ ! -d node_modules ]]; then
  "$pnpm_bin" install --frozen-lockfile
fi

electron_bin="node_modules/electron/dist/Electron.app/Contents/MacOS/Electron"
if [[ ! -x "$electron_bin" ]]; then
  "$node_bin" node_modules/electron/install.js
fi

exec "$pnpm_bin" dev
