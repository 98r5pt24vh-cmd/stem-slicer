#!/usr/bin/env python3
"""Fetch the pinned MERT 95M payload into the deterministic bundle layout."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import tempfile
from urllib.request import Request, urlopen


MODEL_ID = "m-a-p/MERT-v1-95M"
REVISION = "12af15fef9d0ac838c3f475bfbbf26d2060dd4f5"
FILES = {
    "config.json": "ea2627c4c7825cd66f3c944b6b966331604c35928174e0100cd4a82829424e32",
    "configuration_MERT.py": "ae0ec2bab8f59c724ba9878a7c20b67210189536ea62d34a56775968e9decb03",
    "modeling_MERT.py": "6c3ee73cef6f0c30ef494f88d96f891fa6925ffe663fa391b512f4b57abecc6c",
    "preprocessor_config.json": "cc5a5e4a5d3b1a758a5ed984b2eaa15bb0522d811d44a9eed82bfca4baa0dc8f",
    "pytorch_model.bin": "a2b8b747f72c06e0595aeae41ae5473f4364938c6b39b2c58be38c48e6bd3fcd",
}
EXPECTED_TREE = {
    "files": 15,
    "bytes": 377_625_134,
    "sha256": "1fa9897e43c5e57241bc5a3687d621516b69c503a515d663a1d4deef061a764b",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path, expected_sha256: str) -> None:
    if destination.is_file():
        actual = sha256(destination)
        if actual != expected_sha256:
            raise RuntimeError(
                f"Existing MERT payload hash mismatch for {destination}: {actual}"
            )
        print(f"Already verified: {destination.name}", flush=True)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "Slicer-Electron-Build/0.1.0"})
    with tempfile.NamedTemporaryFile(
        prefix=f"{destination.name}.", suffix=".download", dir=destination.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
        with urlopen(request, timeout=120) as response:
            shutil.copyfileobj(response, temporary, length=8 * 1024 * 1024)
    actual = sha256(temporary_path)
    if actual != expected_sha256:
        raise RuntimeError(
            f"Downloaded MERT payload hash mismatch for {destination.name}: {actual}"
        )
    temporary_path.replace(destination)
    print(f"Downloaded and verified: {destination.name}", flush=True)


def create_module_cache(root: Path, snapshot: Path) -> None:
    modules = root / "modules" / "transformers_modules"
    destinations = (
        modules / REVISION,
        modules / "m-a-p" / "MERT-v1-95M" / REVISION,
    )
    init_directories = {
        root / "modules",
        modules,
        modules / REVISION,
        modules / "m-a-p",
        modules / "m-a-p" / "MERT-v1-95M",
        modules / "m-a-p" / "MERT-v1-95M" / REVISION,
    }
    for directory in sorted(init_directories):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "__init__.py").touch(exist_ok=True)
    for destination in destinations:
        for filename in ("configuration_MERT.py", "modeling_MERT.py"):
            shutil.copyfile(snapshot / filename, destination / filename)


def tree_digest(root: Path) -> dict[str, int | str]:
    digest = hashlib.sha256()
    count = 0
    total = 0
    files = [item for item in root.rglob("*") if item.is_file()]
    for path in sorted(
        files, key=lambda item: item.relative_to(root).as_posix()
    ):
        relative = path.relative_to(root).as_posix().encode()
        size = path.stat().st_size
        file_digest = sha256(path)
        digest.update(
            relative
            + b"\0"
            + str(size).encode()
            + b"\0"
            + file_digest.encode()
            + b"\n"
        )
        count += 1
        total += size
    return {"files": count, "bytes": total, "sha256": digest.hexdigest()}


def main() -> int:
    repository_root = Path(__file__).resolve().parents[1]
    root = repository_root / "models" / "huggingface"
    snapshot = (
        root
        / "models--m-a-p--MERT-v1-95M"
        / "snapshots"
        / REVISION
    )
    for filename, expected_sha256 in FILES.items():
        url = (
            f"https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/"
            f"{filename}?download=true"
        )
        download(url, snapshot / filename, expected_sha256)
    create_module_cache(root, snapshot)
    actual = tree_digest(root)
    if actual != EXPECTED_TREE:
        raise RuntimeError(f"Unexpected deterministic MERT tree: {actual}")
    print(
        "MERT payload ready: "
        f"{actual['files']} files, {actual['bytes']} bytes, {actual['sha256']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
