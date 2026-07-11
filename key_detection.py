import json
import os
import queue
import re
import subprocess
import sys
import threading
import uuid


SHARP_KEYS = {
    "1A": "G#m", "2A": "D#m", "3A": "A#m", "4A": "Fm",
    "5A": "Cm", "6A": "Gm", "7A": "Dm", "8A": "Am",
    "9A": "Em", "10A": "Bm", "11A": "F#m", "12A": "C#m",
    "1B": "B", "2B": "F#", "3B": "C#", "4B": "G#",
    "5B": "D#", "6B": "A#", "7B": "F", "8B": "C",
    "9B": "G", "10B": "D", "11B": "A", "12B": "E",
}

FLAT_KEYS = {
    "1A": "Abm", "2A": "Ebm", "3A": "Bbm", "4A": "Fm",
    "5A": "Cm", "6A": "Gm", "7A": "Dm", "8A": "Am",
    "9A": "Em", "10A": "Bm", "11A": "Gbm", "12A": "Dbm",
    "1B": "B", "2B": "Gb", "3B": "Db", "4B": "Ab",
    "5B": "Eb", "6B": "Bb", "7B": "F", "8B": "C",
    "9B": "G", "10B": "D", "11B": "A", "12B": "E",
}

KEY_AFTER_BPM_RE = re.compile(
    r"(?i)(?<![A-Za-z])(?:[A-G](?:#|b)?m|[A-G](?:#|b)?\s+(?:major|minor)|[A-G](?:#|b)?)(?![A-Za-z])"
)
BPM_RE = re.compile(r"\b(?:[6-9]\d|1\d{2}|2[0-4]\d)\b")


def hidden_process_options():
    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "startupinfo": startupinfo,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }


def analyzer_executable():
    configured = os.environ.get("STEM_SLICER_ANALYZER")
    if configured and os.path.isfile(configured):
        return configured
    roots = []
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        roots.append(bundled_root)
    executable_root = os.path.dirname(sys.executable)
    roots.extend((executable_root, os.path.join(executable_root, "_internal")))
    roots.append(os.path.dirname(os.path.abspath(__file__)))
    executable = "openkeyscan-analyzer.exe" if sys.platform == "win32" else "openkeyscan-analyzer"
    for root in roots:
        candidates = (
            os.path.join(root, "openkeyscan-analyzer", executable),
            os.path.join(root, "vendor", "openkeyscan-analyzer", executable),
        )
        for candidate in candidates:
            executable_file = sys.platform == "win32" or os.access(candidate, os.X_OK)
            if os.path.isfile(candidate) and executable_file:
                return candidate
    return None


def filename_has_key(filename):
    stem = os.path.splitext(os.path.basename(filename))[0]
    bpm = BPM_RE.search(stem)
    if not bpm:
        return False
    return bool(KEY_AFTER_BPM_RE.search(stem, bpm.end()))


def format_camelot(camelot, mode="detected", accidentals="sharps"):
    match = re.fullmatch(r"(1[0-2]|[1-9])([AB])", camelot or "")
    if not match:
        raise ValueError(f"Invalid Camelot key: {camelot!r}")
    number, detected_mode = match.groups()
    target_mode = detected_mode
    if mode == "relative_minor":
        target_mode = "A"
    elif mode == "relative_major":
        target_mode = "B"
    elif mode != "detected":
        raise ValueError(f"Unknown key mode: {mode}")
    table = FLAT_KEYS if accidentals == "flats" else SHARP_KEYS
    return table[f"{number}{target_mode}"]


def insert_key_after_bpm(filename, key):
    stem, extension = os.path.splitext(filename)
    bpm = BPM_RE.search(stem)
    if bpm:
        stem = f"{stem[:bpm.end()]} {key}{stem[bpm.end():]}"
    else:
        stem = f"{stem} {key}"
    return stem + extension


class KeyAnalyzer:
    def __init__(self, workers=1, startup_timeout=45, request_timeout=120):
        self.workers = workers
        self.startup_timeout = startup_timeout
        self.request_timeout = request_timeout
        self.process = None
        self.messages = queue.Queue()
        self.reader = None

    def start(self):
        path = analyzer_executable()
        if not path:
            raise RuntimeError("The embedded key analyzer was not found.")
        self.process = subprocess.Popen(
            [path, "--workers", str(self.workers)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            **hidden_process_options(),
        )
        self.reader = threading.Thread(target=self._read_stdout, daemon=True)
        self.reader.start()
        message = self._next_message(self.startup_timeout)
        if message.get("type") != "ready":
            self.stop()
            raise RuntimeError("The key analyzer did not become ready.")

    def _read_stdout(self):
        try:
            for line in self.process.stdout:
                try:
                    self.messages.put(json.loads(line))
                except json.JSONDecodeError:
                    continue
        finally:
            self.messages.put({"type": "closed"})

    def _next_message(self, timeout):
        try:
            return self.messages.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError("Key analysis timed out.") from exc

    def analyze(self, audio_path):
        if not self.process or self.process.poll() is not None:
            raise RuntimeError("The key analyzer is not running.")
        request_id = str(uuid.uuid4())
        request = {"id": request_id, "path": os.path.abspath(audio_path)}
        self.process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        while True:
            message = self._next_message(self.request_timeout)
            if message.get("type") in {"heartbeat", "ready"}:
                continue
            if message.get("type") == "closed":
                raise RuntimeError("The key analyzer stopped unexpectedly.")
            if message.get("id") != request_id:
                continue
            if message.get("status") != "success":
                raise RuntimeError(message.get("error", "Key analysis failed."))
            return message

    def stop(self):
        process, self.process = self.process, None
        if not process:
            return
        try:
            if process.stdin:
                process.stdin.close()
        except OSError:
            pass
        try:
            # The analyzer exits cleanly when its NDJSON input reaches EOF.
            # Its PyInstaller bootloader manages a child process, so a normal
            # EOF avoids signal propagation through that process tree.
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            try:
                process.terminate()
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.kill()
            except OSError:
                pass
        except OSError:
            pass

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.stop()
