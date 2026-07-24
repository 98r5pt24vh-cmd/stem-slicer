"""Time the cold Basic Pitch/ONNX startup path without packaging the app."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback


STARTED = time.perf_counter()
PROFILE_TARGETS = {
    "MidiConverter.__init__",
    "Model.__init__",
    "Model.predict",
}


def report(stage: str) -> None:
    elapsed = time.perf_counter() - STARTED
    print(
        f"MIDI_DIAGNOSTIC elapsed={elapsed:07.3f}s "
        f"thread={threading.current_thread().name!r} stage={stage}",
        flush=True,
    )


def profile(frame, event, _argument):
    if event not in {"call", "return"}:
        return profile
    qualified_name = getattr(frame.f_code, "co_qualname", frame.f_code.co_name)
    if qualified_name in PROFILE_TARGETS:
        report(f"{qualified_name}:{event}")
    return profile


def load_converter(source_root: Path) -> None:
    os.chdir(source_root)
    sys.path.insert(0, str(source_root))
    sys.setprofile(profile)
    report("midi_conversion import:start")
    from midi_conversion import MidiConverter

    report("midi_conversion import:complete")
    converter = MidiConverter()
    report(f"MidiConverter ready type={type(converter).__name__}")


def worker(source_root: Path, mode: str) -> int:
    report(f"worker:start mode={mode}")
    failure = []

    def target():
        try:
            load_converter(source_root)
        except BaseException as exc:
            failure.append(exc)
            report(f"worker:error type={type(exc).__name__} message={exc}")
            traceback.print_exc()

    if mode == "main":
        target()
    elif mode == "background":
        thread = threading.Thread(target=target, name="StemSlicerMidiLoader", daemon=True)
        thread.start()
        thread.join()
    elif mode == "qt-background":
        os.environ["STEM_SLICER_DISABLE_ENGINE_AUTOSTART"] = "1"
        os.chdir(source_root)
        sys.path.insert(0, str(source_root))
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        report("QApplication ready")
        thread = threading.Thread(target=target, name="StemSlicerMidiLoader", daemon=True)
        thread.start()
        while thread.is_alive():
            application.processEvents()
            thread.join(0.01)
        application.processEvents()
        report("QApplication + MIDI thread complete")
    else:
        os.environ["STEM_SLICER_DISABLE_ENGINE_AUTOSTART"] = "1"
        os.chdir(source_root)
        sys.path.insert(0, str(source_root))
        threading.setprofile(profile)
        from PySide6.QtWidgets import QApplication
        from app import MainWindow

        application = QApplication.instance() or QApplication([])
        report("QApplication ready")
        window = MainWindow()
        report("MainWindow ready")
        window._start_midi_engine()
        report("MainWindow MIDI start requested")
        while window.midi_engine_state not in {"ready", "failed"}:
            application.processEvents()
            time.sleep(0.01)
        report(f"MainWindow MIDI state={window.midi_engine_state}")
        window.close()
        application.processEvents()
    if failure:
        return 1
    report("worker:complete")
    return 0


def supervise(arguments) -> int:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--source-root",
        str(arguments.source_root),
        "--mode",
        arguments.mode,
    ]
    report(
        f"supervisor:start mode={arguments.mode} "
        f"timeout={arguments.timeout}s source={arguments.source_root}"
    )
    process = subprocess.Popen(command)
    try:
        return_code = process.wait(timeout=arguments.timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        report(f"RESULT timeout after {arguments.timeout}s")
        return 0
    if return_code == 0:
        report("RESULT ready within limit")
    else:
        report(f"RESULT error returncode={return_code}")
    return 0


def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=("main", "background", "qt-background", "window-lifecycle"),
        required=True,
    )
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--worker", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    source_root = arguments.source_root.resolve()
    if arguments.worker:
        return worker(source_root, arguments.mode)
    return supervise(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
