import math
import os
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


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: smoke_windows_bundle.py <PyInstaller output folder>")
    bundle = os.path.abspath(sys.argv[1])
    internal = os.path.join(bundle, "_internal")
    if not os.path.isdir(internal):
        raise RuntimeError(f"PyInstaller internal folder was not found: {internal}")

    application = os.path.join(bundle, "Stem Slicer 1.6B.exe")
    if not os.path.isfile(application):
        raise RuntimeError(f"Application executable was not found: {application}")
    # IMAGE_SUBSYSTEM_WINDOWS_GUI == 2. A console build would be 3 and could
    # create the Windows Terminal window reported by users.
    subsystem = pe_subsystem(application)
    if subsystem != 2:
        raise RuntimeError(f"Application is not a Windows GUI executable (subsystem={subsystem}).")
    print(f"Windows GUI subsystem verified: {application}", flush=True)

    ffmpeg = os.path.join(internal, "ffmpeg.exe")
    analyzer = os.path.join(internal, "openkeyscan-analyzer", "openkeyscan-analyzer.exe")
    bungee = os.path.join(internal, "bin", "bungee.exe")
    key_warmup = os.path.join(internal, "assets", "key-engine-warmup.wav")
    key_bpm_warmup = os.path.join(internal, "assets", "key-and-bpm-engine-warmup.wav")
    basic_pitch_model = os.path.join(internal, "basic_pitch", "saved_models", "icassp_2022", "nmp.onnx")
    qt_multimedia = find_named(internal, "Qt6Multimedia.dll")
    qt_multimedia_plugin = find_multimedia_plugin(internal)
    for required in (
        ffmpeg,
        bungee,
        analyzer,
        key_warmup,
        key_bpm_warmup,
        basic_pitch_model,
        qt_multimedia,
        qt_multimedia_plugin,
    ):
        if not os.path.isfile(required):
            raise RuntimeError(f"Required bundled file was not found at its application path: {required}")
    print(f"Bundled FFmpeg: {ffmpeg} ({os.path.getsize(ffmpeg)} bytes)", flush=True)
    print(f"Bundled Bungee: {bungee} ({os.path.getsize(bungee)} bytes)", flush=True)
    print(f"Bundled analyzer: {analyzer} ({os.path.getsize(analyzer)} bytes)", flush=True)
    print(f"Bundled key warm-up audio: {key_warmup}", flush=True)
    print(f"Bundled key/BPM warm-up audio: {key_bpm_warmup}", flush=True)
    print(f"Bundled Basic Pitch model: {basic_pitch_model}", flush=True)
    print(f"Bundled Qt Multimedia: {qt_multimedia}", flush=True)
    print(f"Bundled Qt Multimedia backend: {qt_multimedia_plugin}", flush=True)
    sys._MEIPASS = internal

    from audio_convert import _find_bungee
    from engine import find_ffmpeg, find_ffprobe, get_duration, run_subprocess
    from key_detection import KeyAnalyzer, analyzer_executable

    resolved_ffmpeg = os.path.normcase(os.path.abspath(find_ffmpeg() or ""))
    if resolved_ffmpeg != os.path.normcase(os.path.abspath(ffmpeg)):
        raise RuntimeError(f"Application FFmpeg lookup resolved {resolved_ffmpeg!r}, expected {ffmpeg!r}.")
    if find_ffprobe(ffmpeg) is not None:
        raise RuntimeError("The frozen bundle unexpectedly resolved FFprobe instead of using FFmpeg fallback.")
    resolved_analyzer = os.path.normcase(os.path.abspath(analyzer_executable() or ""))
    if resolved_analyzer != os.path.normcase(os.path.abspath(analyzer)):
        raise RuntimeError(f"Application analyzer lookup resolved {resolved_analyzer!r}, expected {analyzer!r}.")
    resolved_bungee = os.path.normcase(os.path.abspath(_find_bungee() or ""))
    if resolved_bungee != os.path.normcase(os.path.abspath(bungee)):
        raise RuntimeError(f"Application Bungee lookup resolved {resolved_bungee!r}, expected {bungee!r}.")

    with tempfile.TemporaryDirectory() as temporary:
        sample = os.path.join(temporary, "A-minor-smoke.wav")
        completed = run_subprocess([ffmpeg, "-version"], capture_output=True, text=True, timeout=30)
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
                value = sum(math.sin(2 * math.pi * frequency * index / sample_rate) for frequency in frequencies)
                frames.extend(struct.pack("<h", int(8500 * value / len(frequencies))))
            output.writeframes(frames)
        measured_duration = get_duration(sample, ffmpeg, None)
        if not math.isclose(measured_duration, duration, abs_tol=0.1):
            raise RuntimeError(f"Bundled FFmpeg duration fallback returned {measured_duration}, expected {duration}.")
        print(f"Bundled FFmpeg duration fallback ready: {measured_duration:.2f}s", flush=True)

        bungee_output = os.path.join(temporary, "bungee-identity.wav")
        completed = run_subprocess(
            [bungee, "--speed", "1", "--pitch", "0", sample, bungee_output],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if completed.returncode != 0 or not os.path.isfile(bungee_output) or os.path.getsize(bungee_output) == 0:
            raise RuntimeError(
                "Bundled Bungee failed its identity conversion: "
                f"returncode={completed.returncode}, stderr={completed.stderr}"
            )
        print("Bundled Windows Bungee engine ready.", flush=True)

        with KeyAnalyzer(workers=1, startup_timeout=90, request_timeout=180) as key_analyzer:
            result = key_analyzer.analyze(
                sample,
                bpm_mode="quick_scan_loop",
                structure_ffmpeg_path=ffmpeg,
            )
        if not result.get("camelot"):
            raise RuntimeError(f"Bundled key analyzer returned no key: {result}")
        if result.get("bpm_mode") != "quick_scan_loop" or not isinstance(result.get("bpm"), (int, float)):
            raise RuntimeError(f"Bundled analyzer does not contain the validated Loop BPM engine: {result}")
        print(
            f"Bundled Windows key/BPM analyzer ready: {result['camelot']}, {result['bpm']} BPM",
            flush=True,
        )

        midi_smoke_result = os.path.join(temporary, "midi-smoke-result.txt")
        smoke_environment = os.environ.copy()
        smoke_environment["STEM_SLICER_SMOKE_RESULT"] = midi_smoke_result
        smoke_environment["STEM_SLICER_SMOKE_AUDIO"] = sample
        midi_output = os.path.join(temporary, "basic-pitch-smoke.mid")
        smoke_environment["STEM_SLICER_SMOKE_MIDI"] = midi_output
        completed = run_subprocess(
            [application, "--smoke-midi-engine"],
            env=smoke_environment,
            timeout=180,
            check=False,
        )
        message = "No result file was produced."
        if os.path.isfile(midi_smoke_result):
            with open(midi_smoke_result, "r", encoding="utf-8") as result_file:
                message = result_file.read().strip()
        if completed.returncode != 0 or message != "ok" or not os.path.isfile(midi_output) or os.path.getsize(midi_output) == 0:
            raise RuntimeError(f"Bundled Basic Pitch engine failed its packaged smoke test: {message}")
        print("Bundled Windows Basic Pitch engine ready.", flush=True)

        ui_smoke_result = os.path.join(temporary, "ui-smoke-result.txt")
        ui_environment = os.environ.copy()
        ui_environment["STEM_SLICER_SMOKE_RESULT"] = ui_smoke_result
        ui_environment["STEM_SLICER_DISABLE_ENGINE_AUTOSTART"] = "1"
        completed = run_subprocess(
            [application, "--smoke-ui"],
            env=ui_environment,
            timeout=60,
            check=False,
        )
        ui_message = "No result file was produced."
        if os.path.isfile(ui_smoke_result):
            with open(ui_smoke_result, "r", encoding="utf-8") as result_file:
                ui_message = result_file.read().strip()
        if completed.returncode != 0 or ui_message != "ok":
            raise RuntimeError(f"Bundled Qt interface failed its packaged smoke test: {ui_message}")
        print("Bundled Windows Qt interface ready.", flush=True)


if __name__ == "__main__":
    main()
