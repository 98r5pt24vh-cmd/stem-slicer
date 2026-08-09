#!/usr/bin/env python3
"""Verify the large local payload trees excluded from ordinary Git history."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys


EXPECTED = {
    "vendor": {
        "files": 2287,
        "bytes": 880_449_181,
        "sha256": "38da39d2c17ad80ea068ac06820c8c21e462a2cb00f11380c2b68795799a6e00",
    },
    "models/huggingface": {
        "files": 15,
        "bytes": 377_625_134,
        "sha256": "1fa9897e43c5e57241bc5a3687d621516b69c503a515d663a1d4deef061a764b",
    },
}


def tree_digest(root: Path) -> tuple[int, int, str]:
    digest = hashlib.sha256()
    count = 0
    total = 0
    files = [item for item in root.rglob("*") if item.is_file()]
    for path in sorted(
        files, key=lambda item: item.relative_to(root).as_posix()
    ):
        relative = path.relative_to(root).as_posix().encode()
        file_digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                file_digest.update(chunk)
        size = path.stat().st_size
        digest.update(
            relative
            + b"\0"
            + str(size).encode()
            + b"\0"
            + file_digest.hexdigest().encode()
            + b"\n"
        )
        count += 1
        total += size
    return count, total, digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    failed = False
    for relative, expected in EXPECTED.items():
        root = args.root / relative
        if not root.is_dir():
            print(f"MISSING {relative}")
            failed = True
            continue
        count, total, checksum = tree_digest(root)
        actual = {"files": count, "bytes": total, "sha256": checksum}
        if actual != expected:
            print(f"MISMATCH {relative}: {actual}")
            failed = True
        else:
            print(f"OK {relative}: {count} files, {total} bytes, {checksum}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
