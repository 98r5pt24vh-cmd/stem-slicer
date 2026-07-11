import os
import subprocess
import sys
import tempfile


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
    os.environ["STEM_SLICER_ANALYZER"] = analyzer
    sys._MEIPASS = internal

    from engine import run_subprocess
    from key_detection import KeyAnalyzer

    with tempfile.TemporaryDirectory() as temporary:
        sample = os.path.join(temporary, "A-minor-smoke.wav")
        command = [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:duration=24",
            "-ar",
            "44100",
            sample,
            "-loglevel",
            "error",
        ]
        completed = run_subprocess(command, capture_output=True, text=True, timeout=60)
        if completed.returncode != 0 or not os.path.isfile(sample):
            raise RuntimeError(f"Bundled FFmpeg smoke test failed: {completed.stderr}")
        with KeyAnalyzer(workers=1, startup_timeout=90, request_timeout=180) as key_analyzer:
            result = key_analyzer.analyze(sample)
        if not result.get("camelot"):
            raise RuntimeError(f"Bundled key analyzer returned no key: {result}")
        print(f"Bundled Windows key analyzer ready: {result['camelot']}")


if __name__ == "__main__":
    main()
