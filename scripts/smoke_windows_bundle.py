import os
import math
import struct
import subprocess
import sys
import tempfile
import wave


def find_file(root, filename):
    for current, _, files in os.walk(root):
        if filename in files:
            return os.path.join(current, filename)
    raise FileNotFoundError(f"{filename} was not found under {root}")


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: smoke_windows_bundle.py <PyInstaller output folder>")
    bundle = os.path.abspath(sys.argv[1])
    internal = os.path.join(bundle, "_internal")
    if not os.path.isdir(internal):
        raise RuntimeError(f"PyInstaller internal folder was not found: {internal}")

    ffmpeg = find_file(internal, "ffmpeg.exe")
    analyzer = find_file(internal, "openkeyscan-analyzer.exe")
    print(f"Bundled FFmpeg: {ffmpeg} ({os.path.getsize(ffmpeg)} bytes)", flush=True)
    print(f"Bundled analyzer: {analyzer} ({os.path.getsize(analyzer)} bytes)", flush=True)
    os.environ["STEM_SLICER_ANALYZER"] = analyzer
    sys._MEIPASS = internal

    from engine import run_subprocess
    from key_detection import KeyAnalyzer

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
        with KeyAnalyzer(workers=1, startup_timeout=90, request_timeout=180) as key_analyzer:
            result = key_analyzer.analyze(sample)
        if not result.get("camelot"):
            raise RuntimeError(f"Bundled key analyzer returned no key: {result}")
        print(f"Bundled Windows key analyzer ready: {result['camelot']}")


if __name__ == "__main__":
    main()
