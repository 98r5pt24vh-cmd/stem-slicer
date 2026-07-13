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

    application = os.path.join(bundle, "Stem Slicer 1.4.1 M.exe")
    if not os.path.isfile(application):
        raise RuntimeError(f"Application executable was not found: {application}")
    # IMAGE_SUBSYSTEM_WINDOWS_GUI == 2. A console build would be 3 and could
    # create the Windows Terminal window reported by users.
    subsystem = pe_subsystem(application)
    if subsystem != 2:
        raise RuntimeError(f"Application is not a Windows GUI executable (subsystem={subsystem}).")
    print(f"Windows GUI subsystem verified: {application}", flush=True)

    ffmpeg = os.path.join(internal, "ffmpeg.exe")
    ffprobe = os.path.join(internal, "ffprobe.exe")
    analyzer = os.path.join(internal, "openkeyscan-analyzer", "openkeyscan-analyzer.exe")
    warmup = os.path.join(internal, "assets", "key-engine-warmup.wav")
    qt_multimedia = find_named(internal, "Qt6Multimedia.dll")
    qt_multimedia_plugin = find_multimedia_plugin(internal)
    for required in (ffmpeg, ffprobe, analyzer, warmup, qt_multimedia, qt_multimedia_plugin):
        if not os.path.isfile(required):
            raise RuntimeError(f"Required bundled file was not found at its application path: {required}")
    print(f"Bundled FFmpeg: {ffmpeg} ({os.path.getsize(ffmpeg)} bytes)", flush=True)
    print(f"Bundled FFprobe: {ffprobe} ({os.path.getsize(ffprobe)} bytes)", flush=True)
    print(f"Bundled analyzer: {analyzer} ({os.path.getsize(analyzer)} bytes)", flush=True)
    print(f"Bundled warm-up audio: {warmup}", flush=True)
    print(f"Bundled Qt Multimedia: {qt_multimedia}", flush=True)
    print(f"Bundled Qt Multimedia backend: {qt_multimedia_plugin}", flush=True)
    sys._MEIPASS = internal

    from engine import find_ffmpeg, find_ffprobe, run_subprocess
    from key_detection import KeyAnalyzer, analyzer_executable

    resolved_ffmpeg = os.path.normcase(os.path.abspath(find_ffmpeg() or ""))
    resolved_ffprobe = os.path.normcase(os.path.abspath(find_ffprobe(resolved_ffmpeg) or ""))
    if resolved_ffmpeg != os.path.normcase(os.path.abspath(ffmpeg)):
        raise RuntimeError(f"Application FFmpeg lookup resolved {resolved_ffmpeg!r}, expected {ffmpeg!r}.")
    if resolved_ffprobe != os.path.normcase(os.path.abspath(ffprobe)):
        raise RuntimeError(f"Application FFprobe lookup resolved {resolved_ffprobe!r}, expected {ffprobe!r}.")
    resolved_analyzer = os.path.normcase(os.path.abspath(analyzer_executable() or ""))
    if resolved_analyzer != os.path.normcase(os.path.abspath(analyzer)):
        raise RuntimeError(f"Application analyzer lookup resolved {resolved_analyzer!r}, expected {analyzer!r}.")

    with tempfile.TemporaryDirectory() as temporary:
        sample = os.path.join(temporary, "A-minor-smoke.wav")
        completed = run_subprocess([ffmpeg, "-version"], capture_output=True, text=True, timeout=30)
        if completed.returncode != 0:
            raise RuntimeError(f"Bundled FFmpeg failed to start: {completed.stderr}")
        completed = run_subprocess([ffprobe, "-version"], capture_output=True, text=True, timeout=30)
        if completed.returncode != 0:
            raise RuntimeError(f"Bundled FFprobe failed to start: {completed.stderr}")

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
