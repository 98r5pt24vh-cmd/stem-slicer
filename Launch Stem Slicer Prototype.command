#!/bin/zsh
set -euo pipefail

prototype_root=${0:A:h}
prototype_python=${STEM_SLICER_PROTOTYPE_PYTHON:-"$HOME/Documents/Stem Slicer Development Runtime/venv-prototype/bin/python"}

if [[ ! -x "$prototype_python" ]]; then
  print -u2 "Stem Slicer prototype runtime not found: $prototype_python"
  print -u2 "Set STEM_SLICER_PROTOTYPE_PYTHON to the CPython 3.12.13 environment."
  exit 1
fi

cd "$prototype_root"
exec "$prototype_python" scripts/run_generate_prototype.py
