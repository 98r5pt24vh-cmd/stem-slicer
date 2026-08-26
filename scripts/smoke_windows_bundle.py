import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
import wave


REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPOSITORY_ROOT not in sys.path:
    sys.path.insert(0, REPOSITORY_ROOT)


def pe_subsystem(path):
    with open(path, "rb") as stream:
        if stream.read(2) != b"MZ":
            raise RuntimeError(f"Not a PE executable: {path}")
        stream.seek(0x3C)
        pe_offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(pe_offset)
        if stream.read(4) != b"PE\0\0":
            raise RuntimeError(f"Invalid PE header: {path}")
        stream.seek(pe_offset + 24 + 68)
        return struct.unpack("<H", stream.read(2))[0]


def find_named(root, filename):
    for current, _, files in os.walk(root):
        if filename in files:
            return os.path.join(current, filename)
    return None


def find_multimedia_plugin(root):
    for current, _, files in os.walk(root):
        if os.path.basename(current).lower() != "multimedia":
            continue
        for filename in files:
            if filename.lower().endswith(".dll"):
                return os.path.join(current, filename)
    return None


def read_result(path, default="No result file was produced."):
    if not os.path.isfile(path):
        return default
    with open(path, "r", encoding="utf-8") as result_file:
        return result_file.read().strip()


def run_application_smoke(application, flag, result_path, environment, timeout):
    from engine import run_subprocess

    smoke_environment = os.environ.copy()
    smoke_environment.update(environment)
    smoke_environment["STEM_SLICER_SMOKE_RESULT"] = result_path
    completed = run_subprocess(
        [application, flag], env=smoke_environment, timeout=timeout, check=False
    )
    return completed, read_result(result_path)


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: smoke_windows_bundle.py <PyInstaller output folder>")
    bundle = os.path.abspath(sys.argv[1])
    internal = os.path.join(bundle, "_internal")
    if not os.path.isdir(internal):
        raise RuntimeError(f"PyInstaller internal folder was not found: {internal}")

    application = os.path.join(bundle, "Stem Slicer 1.9B.exe")
    if not os.path.isfile(application):
        raise RuntimeError(f"Application executable was not found: {application}")
    subsystem = pe_subsystem(application)
    if subsystem != 2:
        raise RuntimeError(
            f"Application is not a Windows GUI executable (subsystem={subsystem})."
        )
    print(f"Windows GUI subsystem verified: {application}", flush=True)

    ffmpeg = os.path.join(internal, "ffmpeg.exe")
    analyzer = os.path.join(
        internal, "openkeyscan-analyzer", "openkeyscan-analyzer.exe"
    )
    warmup = os.path.join(internal, "assets", "key-and-bpm-engine-warmup.wav")
    basic_pitch_model = os.path.join(
        internal,
        "basic_pitch",
        "saved_models",
        "icassp_2022",
        "nmp.onnx",
    )
    classifier_artifact = os.path.join(
        internal, "models", "layer_roles_v2.joblib"
    )
    classifier_metadata = os.path.join(internal, "models", "layer_roles_v2.json")
    hf_cache = os.path.join(internal, "models", "huggingface")
    mert_model = os.path.join(
        hf_cache,
        "models--m-a-p--MERT-v1-95M",
        "snapshots",
        "12af15fef9d0ac838c3f475bfbbf26d2060dd4f5",
        "pytorch_model.bin",
    )
    qt_multimedia = find_named(internal, "Qt6Multimedia.dll")
    qt_multimedia_plugin = find_multimedia_plugin(internal)
    required_files = (
        ffmpeg,
        analyzer,
        warmup,
        basic_pitch_model,
        classifier_artifact,
        classifier_metadata,
        mert_model,
        qt_multimedia,
        qt_multimedia_plugin,
    )
    for required in required_files:
        if not required or not os.path.isfile(required):
            raise RuntimeError(
                f"Required bundled file was not found at its application path: {required}"
            )
    print(f"Bundled FFmpeg: {ffmpeg} ({os.path.getsize(ffmpeg)} bytes)", flush=True)
    print(f"Bundled analyzer: {analyzer} ({os.path.getsize(analyzer)} bytes)", flush=True)
    print(f"Bundled MERT: {mert_model} ({os.path.getsize(mert_model)} bytes)", flush=True)
    print(f"Bundled Qt Multimedia: {qt_multimedia}", flush=True)
    print(f"Bundled Qt Multimedia backend: {qt_multimedia_plugin}", flush=True)
    sys._MEIPASS = internal

    from engine import find_ffmpeg, find_ffprobe, get_duration, run_subprocess
    from key_detection import KeyAnalyzer, analyzer_executable

    resolved_ffmpeg = os.path.normcase(os.path.abspath(find_ffmpeg() or ""))
    if resolved_ffmpeg != os.path.normcase(os.path.abspath(ffmpeg)):
        raise RuntimeError(
            f"Application FFmpeg lookup resolved {resolved_ffmpeg!r}, expected {ffmpeg!r}."
        )
    if find_ffprobe(ffmpeg) is not None:
        raise RuntimeError(
            "The frozen bundle unexpectedly resolved FFprobe instead of using FFmpeg fallback."
        )
    resolved_analyzer = os.path.normcase(os.path.abspath(analyzer_executable() or ""))
    if resolved_analyzer != os.path.normcase(os.path.abspath(analyzer)):
        raise RuntimeError(
            f"Application analyzer lookup resolved {resolved_analyzer!r}, expected {analyzer!r}."
        )

    with tempfile.TemporaryDirectory() as temporary:
        runtime_result = os.path.join(temporary, "runtime-smoke-result.json")
        completed, message = run_application_smoke(
            application, "--smoke-runtime", runtime_result, {}, 60
        )
        if completed.returncode != 0:
            raise RuntimeError(f"Packaged runtime smoke failed: {message}")
        runtime = json.loads(message)
        expected_runtime = {
            "app_version": "1.9B",
            "python": "3.12.10",
            "pyside6": "6.11.1",
            "frozen": True,
        }
        for field, expected in expected_runtime.items():
            if runtime.get(field) != expected:
                raise RuntimeError(
                    f"Unexpected packaged runtime {field}: "
                    f"{runtime.get(field)!r}, expected {expected!r}."
                )
        if runtime.get("architecture", "").lower() not in {"amd64", "x86_64"}:
            raise RuntimeError(
                f"Unexpected packaged architecture: {runtime.get('architecture')!r}."
            )
        print(
            "Embedded runtime verified: "
            f"Python {runtime['python']} x64, PySide6 {runtime['pyside6']}.",
            flush=True,
        )

        sample = os.path.join(temporary, "A-minor-smoke.wav")
        completed = run_subprocess(
            [ffmpeg, "-version"], capture_output=True, text=True, timeout=30
        )
        if completed.returncode != 0:
            raise RuntimeError(f"Bundled FFmpeg failed to start: {completed.stderr}")
        sample_rate = 22050
        duration = 24
        frequencies = (220.0, 261.6256, 329.6276)
        with wave.open(sample, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            frames = bytearray()
            for index in range(sample_rate * duration):
                value = sum(
                    math.sin(2 * math.pi * frequency * index / sample_rate)
                    for frequency in frequencies
                )
                frames.extend(
                    struct.pack("<h", int(8500 * value / len(frequencies)))
                )
            output.writeframes(frames)
        measured_duration = get_duration(sample, ffmpeg, None)
        if not math.isclose(measured_duration, duration, abs_tol=0.1):
            raise RuntimeError(
                f"Bundled FFmpeg duration fallback returned {measured_duration}, "
                f"expected {duration}."
            )
        sample_mp3 = os.path.join(temporary, "L Smoke 140 C minor.mp3")
        completed = run_subprocess(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                sample,
                "-c:a",
                "libmp3lame",
                "-q:a",
                "2",
                sample_mp3,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if completed.returncode != 0 or not os.path.isfile(sample_mp3):
            raise RuntimeError(
                f"Bundled FFmpeg could not create the MP3 smoke input: {completed.stderr}"
            )
        with KeyAnalyzer(
            workers=1, startup_timeout=90, request_timeout=180
        ) as key_analyzer:
            key_result = key_analyzer.analyze(sample_mp3)
        if not key_result.get("camelot"):
            raise RuntimeError(
                f"Bundled key analyzer returned no key: {key_result}"
            )
        print(
            f"Bundled Windows key analyzer ready: {key_result['camelot']}",
            flush=True,
        )

        midi_result = os.path.join(temporary, "midi-smoke-result.json")
        midi_output = os.path.join(temporary, "basic-pitch-smoke.mid")
        completed, message = run_application_smoke(
            application,
            "--smoke-midi-engine",
            midi_result,
            {
                "STEM_SLICER_SMOKE_AUDIO": sample_mp3,
                "STEM_SLICER_SMOKE_MIDI": midi_output,
            },
            180,
        )
        try:
            midi_payload = json.loads(message)
        except json.JSONDecodeError:
            midi_payload = {}
        if (
            completed.returncode != 0
            or midi_payload.get("status") != "ok"
            or midi_payload.get("header") != "MThd"
            or not os.path.isfile(midi_output)
        ):
            raise RuntimeError(
                f"Bundled Basic Pitch engine failed its packaged smoke test: {message}"
            )
        print("Bundled Windows Basic Pitch engine ready.", flush=True)

        converted_output = os.path.join(temporary, "converted-smoke.mp3")
        convert_result = os.path.join(temporary, "convert-smoke-result.txt")
        completed, message = run_application_smoke(
            application,
            "--smoke-convert-engine",
            convert_result,
            {
                "STEM_SLICER_SMOKE_AUDIO": sample_mp3,
                "STEM_SLICER_SMOKE_CONVERTED": converted_output,
            },
            180,
        )
        if (
            completed.returncode != 0
            or message != "ok"
            or not os.path.isfile(converted_output)
            or os.path.getsize(converted_output) <= 0
        ):
            raise RuntimeError(
                f"Bundled Bungee conversion engine failed its smoke test: {message}"
            )
        print("Bundled Windows Bungee conversion engine ready.", flush=True)

        optional_result = os.path.join(temporary, "optional-target-result.txt")
        completed, message = run_application_smoke(
            application,
            "--smoke-quick-extract-optional-target",
            optional_result,
            {},
            60,
        )
        if completed.returncode != 0 or message != "ok":
            raise RuntimeError(
                "Packaged Quick Extract Optional Target workflow failed: "
                f"{message}"
            )
        print(
            "Packaged Windows Quick Extract Optional Target workflow ready.",
            flush=True,
        )

        # Exercise the exact packaged classifier worker and checkpoint, not the
        # source interpreter.  This also validates the Windows pipe reader and
        # hidden child-process launch used by real Generate scans.
        from layer_library import LayerMetadata, TAXONOMY
        from mert_client import MertLayerClassifier

        audio_hash = hashlib.sha256(Path(sample_mp3).read_bytes()).hexdigest()
        stat = os.stat(sample_mp3)
        metadata = LayerMetadata(
            path=sample_mp3,
            relative_path=os.path.basename(sample_mp3),
            filename=os.path.basename(sample_mp3),
            source_loop_id="packaged-smoke",
            layer_index=1,
            bpm=140,
            key="C minor",
            mode="minor",
            duration_seconds=float(duration),
            byte_size=stat.st_size,
            sha256=audio_hash,
            mtime_ns=stat.st_mtime_ns,
        )
        classifier = MertLayerClassifier(
            python_executable=application,
            worker_path=os.path.join(internal, "mert_worker.py"),
            artifact_path=classifier_artifact,
            hf_cache_dir=hf_cache,
            feature_cache_path=os.path.join(temporary, "mert-features.sqlite3"),
            device="cpu",
            # On a freshly extracted, unsigned beta ZIP, Windows Defender may
            # scan Torch and its large model payload during the worker's first
            # import.  This is a maximum wait, not an artificial delay.
            startup_timeout=300,
            request_timeout=900,
            batch_size=1,
            window_batch_size=1,
            # This smoke script itself runs under the source interpreter, but
            # the worker must re-enter the extracted PyInstaller executable in
            # exactly the same mode used by the packaged application.
            frozen_worker_mode=True,
        )
        try:
            worker_metadata = classifier.metadata()
            if len(worker_metadata.get("classes", [])) != 14:
                raise RuntimeError(
                    f"Unexpected MERT class metadata: {worker_metadata.get('classes')}"
                )
            prediction = classifier.predict(Path(sample_mp3), metadata)
        finally:
            classifier.stop()
        if prediction is None or prediction.label not in TAXONOMY:
            raise RuntimeError(f"Bundled MERT returned an invalid prediction: {prediction}")
        print(
            "Bundled Windows MERT + DSP classifier ready: "
            f"{prediction.label} ({prediction.confidence:.4f}).",
            flush=True,
        )

        ui_result = os.path.join(temporary, "ui-smoke-result.txt")
        completed, message = run_application_smoke(
            application,
            "--smoke-ui",
            ui_result,
            {"STEM_SLICER_DISABLE_ENGINE_AUTOSTART": "1"},
            90,
        )
        if completed.returncode != 0 or message != "ok":
            raise RuntimeError(
                f"Bundled Qt interface failed its packaged smoke test: {message}"
            )
        print("Bundled Windows Qt interface ready.", flush=True)


if __name__ == "__main__":
    main()
