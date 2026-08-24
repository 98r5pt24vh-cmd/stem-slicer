#!/usr/bin/env python3
"""Launch the evolving Generate prototype with isolated writable state."""

from __future__ import annotations

import os
from pathlib import Path
import sys


PROTOTYPE_RUNTIME_VERSION = "prototype-generate"


def main() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["STEM_SLICER_RUNTIME_DATA_VERSION"] = PROTOTYPE_RUNTIME_VERSION
    os.execve(
        sys.executable,
        [sys.executable, str(repository_root / "app.py"), *sys.argv[1:]],
        environment,
    )


if __name__ == "__main__":
    main()
