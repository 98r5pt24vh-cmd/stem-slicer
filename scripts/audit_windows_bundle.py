import os
import sys
from pathlib import Path


MODEL_SUFFIXES = {".pt", ".pth", ".ckpt", ".onnx", ".bin"}


def audit_bundle(bundle):
    bundle = Path(bundle).resolve()
    if not bundle.is_dir():
        raise RuntimeError(f"Windows bundle was not found: {bundle}")

    files = [path for path in bundle.rglob("*") if path.is_file()]
    models = [path for path in files if path.suffix.lower() in MODEL_SUFFIXES]
    internal = bundle / "_internal"
    expected_application = bundle / "Stem Slicer 1.9B.exe"
    expected_analyzer = (
        internal / "openkeyscan-analyzer" / "openkeyscan-analyzer.exe"
    )
    analyzer_internal = internal / "openkeyscan-analyzer" / "_internal"
    expected_openkey_model = analyzer_internal / "checkpoints" / "openkeyscan3.pt"
    expected_deeprhythm_model = (
        analyzer_internal / "checkpoints" / "deeprhythm-0.7.pth"
    )
    expected_basic_pitch_model = (
        internal
        / "basic_pitch"
        / "saved_models"
        / "icassp_2022"
        / "nmp.onnx"
    )
    expected_mert_model = (
        internal
        / "models"
        / "huggingface"
        / "models--m-a-p--MERT-v1-95M"
        / "snapshots"
        / "12af15fef9d0ac838c3f475bfbbf26d2060dd4f5"
        / "pytorch_model.bin"
    )
    expected_models = {
        expected_openkey_model,
        expected_deeprhythm_model,
        expected_basic_pitch_model,
        expected_mert_model,
    }
    model_groups = {
        "openkey_models": [path for path in models if path == expected_openkey_model],
        "deeprhythm_models": [
            path for path in models if path == expected_deeprhythm_model
        ],
        "basic_pitch_models": [
            path for path in models if path == expected_basic_pitch_model
        ],
        "mert_models": [path for path in models if path == expected_mert_model],
    }
    unexpected_models = [path for path in models if path not in expected_models]
    torch_cpu = [path for path in files if path.name.lower() == "torch_cpu.dll"]
    parent_torch_cpu = internal / "torch" / "lib" / "torch_cpu.dll"
    analyzer_torch_cpu = analyzer_internal / "torch" / "lib" / "torch_cpu.dll"
    expected_torch = {parent_torch_cpu, analyzer_torch_cpu}
    analyzers = [
        path for path in files if path.name.lower() == "openkeyscan-analyzer.exe"
    ]
    foreign_openkey_ffmpeg = analyzer_internal / "ffmpeg"
    foreign_binaries = [
        path for path in files if path.suffix.lower() in {".dylib", ".so"}
    ]
    logical_bytes = sum(path.stat().st_size for path in files)
    relative_models = [path.relative_to(bundle) for path in models]
    relative_torch = [path.relative_to(bundle) for path in torch_cpu]

    print(
        f"Windows bundle: {len(files)} files, "
        f"{logical_bytes / 1_000_000_000:.3f} GB (decimal)"
    )
    print(f"Model files: {len(models)}")
    for path in relative_models:
        print(f"  {path}")
    print(f"torch_cpu binaries: {len(torch_cpu)}")
    for path in relative_torch:
        print(f"  {path}")

    errors = []
    if not expected_application.is_file():
        errors.append("The Stem Slicer 1.9B executable is missing.")
    if analyzers != [expected_analyzer]:
        errors.append(
            f"Expected exactly one OpenKeyScan executable, found {len(analyzers)}."
        )
    for name, paths in model_groups.items():
        if len(paths) != 1:
            errors.append(f"Expected exactly one {name}, found {len(paths)}.")
    if unexpected_models:
        errors.append(
            "Found unexpected model files: "
            + ", ".join(
                str(path.relative_to(bundle)) for path in unexpected_models
            )
        )
    if set(torch_cpu) != expected_torch:
        errors.append(
            "Expected one parent MERT Torch runtime and one isolated analyzer "
            f"Torch runtime, found: {relative_torch}."
        )
    if foreign_openkey_ffmpeg.is_file():
        errors.append(
            "Found a non-Windows extensionless FFmpeg inside the OpenKeyScan payload."
        )
    if foreign_binaries:
        errors.append(
            "Found non-Windows binaries: "
            + ", ".join(str(path.relative_to(bundle)) for path in foreign_binaries)
        )
    if errors:
        raise RuntimeError("\n".join(errors))

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("### Windows bundle audit\n")
            summary.write(f"- Files: {len(files)}\n")
            summary.write(
                f"- Logical size: {logical_bytes / 1_000_000_000:.3f} GB "
                "(decimal)\n"
            )
            summary.write("- Model payloads: OpenKeyScan, DeepRhythm, Basic Pitch, MERT\n")
            summary.write("- Torch runtimes: 2 (parent MERT + isolated analyzer)\n")

    return {
        "file_count": len(files),
        "logical_bytes": logical_bytes,
        "models": relative_models,
        **{
            name: [path.relative_to(bundle) for path in paths]
            for name, paths in model_groups.items()
        },
        "torch_cpu": relative_torch,
    }


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: audit_windows_bundle.py <PyInstaller output folder>")
    audit_bundle(sys.argv[1])


if __name__ == "__main__":
    main()
