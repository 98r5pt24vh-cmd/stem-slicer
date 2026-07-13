import os
import sys
from pathlib import Path


MODEL_SUFFIXES = {".pt", ".pth", ".ckpt", ".onnx"}


def audit_bundle(bundle):
    bundle = Path(bundle).resolve()
    if not bundle.is_dir():
        raise RuntimeError(f"Windows bundle was not found: {bundle}")

    files = [path for path in bundle.rglob("*") if path.is_file()]
    models = [path for path in files if path.suffix.lower() in MODEL_SUFFIXES]
    torch_cpu = [path for path in files if "torch_cpu" in path.name.lower()]
    analyzers = [path for path in files if path.name.lower() == "openkeyscan-analyzer.exe"]
    logical_bytes = sum(path.stat().st_size for path in files)
    relative_models = [path.relative_to(bundle) for path in models]
    relative_torch = [path.relative_to(bundle) for path in torch_cpu]

    print(f"Windows bundle: {len(files)} files, {logical_bytes / 1_000_000_000:.3f} GB (decimal)")
    print(f"Model files: {len(models)}")
    for path in relative_models:
        print(f"  {path}")
    print(f"torch_cpu binaries: {len(torch_cpu)}")
    for path in relative_torch:
        print(f"  {path}")

    errors = []
    if len(analyzers) != 1:
        errors.append(f"Expected exactly one OpenKeyScan executable, found {len(analyzers)}.")
    if len(models) != 1:
        errors.append(f"Expected exactly one OpenKeyScan model, found {len(models)}.")
    if len(torch_cpu) != 1:
        errors.append(f"Expected exactly one torch_cpu binary, found {len(torch_cpu)}.")
    expected_component = "openkeyscan-analyzer"
    for label, paths in (("model", relative_models), ("torch_cpu binary", relative_torch)):
        for path in paths:
            if expected_component not in {part.lower() for part in path.parts}:
                errors.append(f"Unexpected {label} outside the isolated key engine: {path}")
    if errors:
        raise RuntimeError("\n".join(errors))

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("### Windows bundle audit\n")
            summary.write(f"- Files: {len(files)}\n")
            summary.write(f"- Logical size: {logical_bytes / 1_000_000_000:.3f} GB (decimal)\n")
            summary.write(f"- Model files: {len(models)}\n")
            summary.write(f"- torch_cpu binaries: {len(torch_cpu)}\n")

    return {
        "file_count": len(files),
        "logical_bytes": logical_bytes,
        "models": relative_models,
        "torch_cpu": relative_torch,
    }


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: audit_windows_bundle.py <PyInstaller output folder>")
    audit_bundle(sys.argv[1])


if __name__ == "__main__":
    main()
