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
    expected_analyzer = bundle / "_internal" / "openkeyscan-analyzer" / "openkeyscan-analyzer.exe"
    expected_openkey_model = bundle / "_internal" / "openkeyscan-analyzer" / "_internal" / "checkpoints" / "openkeyscan3.pt"
    expected_deeprhythm_model = bundle / "_internal" / "openkeyscan-analyzer" / "_internal" / "checkpoints" / "deeprhythm-0.7.pth"
    expected_basic_pitch_model = bundle / "_internal" / "basic_pitch" / "saved_models" / "icassp_2022" / "nmp.onnx"
    expected_models = {expected_openkey_model, expected_deeprhythm_model, expected_basic_pitch_model}
    openkey_models = [path for path in models if path == expected_openkey_model]
    deeprhythm_models = [path for path in models if path == expected_deeprhythm_model]
    basic_pitch_models = [path for path in models if path == expected_basic_pitch_model]
    unexpected_models = [path for path in models if path not in expected_models]
    torch_cpu = [path for path in files if "torch_cpu" in path.name.lower()]
    analyzers = [path for path in files if path.name.lower() == "openkeyscan-analyzer.exe"]
    foreign_openkey_ffmpeg = bundle / "_internal" / "openkeyscan-analyzer" / "_internal" / "ffmpeg"
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
    if analyzers != [expected_analyzer]:
        errors.append(f"Expected exactly one OpenKeyScan executable, found {len(analyzers)}.")
    if len(openkey_models) != 1:
        errors.append(f"Expected exactly one OpenKeyScan model, found {len(openkey_models)}.")
    if len(deeprhythm_models) != 1:
        errors.append(f"Expected exactly one DeepRhythm model, found {len(deeprhythm_models)}.")
    if len(basic_pitch_models) != 1:
        errors.append(f"Expected exactly one Basic Pitch model, found {len(basic_pitch_models)}.")
    if unexpected_models:
        errors.append(f"Found unexpected model files: {', '.join(str(path.relative_to(bundle)) for path in unexpected_models)}.")
    if len(torch_cpu) != 1:
        errors.append(f"Expected exactly one torch_cpu binary, found {len(torch_cpu)}.")
    if foreign_openkey_ffmpeg.is_file():
        errors.append("Found a non-Windows extensionless FFmpeg inside the OpenKeyScan payload.")
    expected_component = "openkeyscan-analyzer"
    for path in relative_torch:
        if expected_component not in {part.lower() for part in path.parts}:
            errors.append(f"Unexpected torch_cpu binary outside the isolated key engine: {path}")
    if errors:
        raise RuntimeError("\n".join(errors))

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("### Windows bundle audit\n")
            summary.write(f"- Files: {len(files)}\n")
            summary.write(f"- Logical size: {logical_bytes / 1_000_000_000:.3f} GB (decimal)\n")
            summary.write(f"- Model files: {len(models)}\n")
            summary.write(f"- OpenKeyScan models: {len(openkey_models)}\n")
            summary.write(f"- DeepRhythm models: {len(deeprhythm_models)}\n")
            summary.write(f"- Basic Pitch models: {len(basic_pitch_models)}\n")
            summary.write(f"- torch_cpu binaries: {len(torch_cpu)}\n")

    return {
        "file_count": len(files),
        "logical_bytes": logical_bytes,
        "models": relative_models,
        "openkey_models": [path.relative_to(bundle) for path in openkey_models],
        "deeprhythm_models": [path.relative_to(bundle) for path in deeprhythm_models],
        "basic_pitch_models": [path.relative_to(bundle) for path in basic_pitch_models],
        "torch_cpu": relative_torch,
    }


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: audit_windows_bundle.py <PyInstaller output folder>")
    audit_bundle(sys.argv[1])


if __name__ == "__main__":
    main()
