"""Stem Slicer 1.8B native application entry point.

The validated HTML prototype is faithfully ported by ``ValidatedMainWindow``;
the old widget layout is deliberately not instantiated.
"""

import json
import os
import sys

APP_NAME = "Stem Slicer"
APP_VERSION = "1.8B"

# Configure every writable runtime cache before importing Qt, OpenKeyScan,
# Numba or any audio engine.  A packaged application must never modify its own
# signed bundle after first launch.
from diagnostics_runtime import configure_runtime_environment, initialize_diagnostics

configure_runtime_environment(APP_NAME, APP_VERSION)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from functional_core import (
    DropZone,
    KeyEngineLoader,
    LayerCard,
    LineIcon,
    QuickExtractManagerDialog,
    QuickExtractWorker,
    WaveformWidget,
)
from validated_ui import ValidatedMainWindow, validated_stylesheet


MainWindow = ValidatedMainWindow


def main():
    diagnostics = initialize_diagnostics(APP_NAME, APP_VERSION)
    diagnostics.event("application_entry", argv=sys.argv)
    if "--smoke-key-engine" in sys.argv:
        result_path = os.environ.get("STEM_SLICER_SMOKE_RESULT")
        analyzer = None
        try:
            from engine import find_ffmpeg
            from key_detection import KeyAnalyzer

            resource_root = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
            smoke_audio = os.environ.get(
                "STEM_SLICER_SMOKE_AUDIO",
                os.path.join(resource_root, "assets", "key-and-bpm-engine-warmup.wav"),
            )
            analyzer = KeyAnalyzer(workers=1)
            analyzer.start()
            result = analyzer.analyze(
                smoke_audio,
                bpm_mode="quick_scan_loop",
                structure_ffmpeg_path=find_ffmpeg(),
            )
            payload, exit_code = json.dumps(result, ensure_ascii=False, sort_keys=True), 0
        except Exception as exc:
            diagnostics.exception("key_engine_smoke", exc)
            payload, exit_code = f"{type(exc).__name__}: {exc}", 1
        finally:
            if analyzer is not None:
                analyzer.stop()
        if result_path:
            with open(result_path, "w", encoding="utf-8") as output:
                output.write(payload)
        diagnostics.shutdown()
        raise SystemExit(exit_code)

    if "--smoke-midi-engine" in sys.argv:
        result_path = os.environ.get("STEM_SLICER_SMOKE_RESULT")
        try:
            from midi_conversion import MidiConverter
            converter = MidiConverter()
            smoke_audio = os.environ.get("STEM_SLICER_SMOKE_AUDIO")
            smoke_midi = os.environ.get("STEM_SLICER_SMOKE_MIDI")
            if smoke_audio and smoke_midi:
                converter.convert(smoke_audio, smoke_midi, bpm=120)
            result, exit_code = "ok", 0
        except Exception as exc:
            diagnostics.exception("midi_engine_smoke", exc)
            result, exit_code = f"{type(exc).__name__}: {exc}", 1
        if result_path:
            with open(result_path, "w", encoding="utf-8") as output:
                output.write(result)
        diagnostics.shutdown()
        raise SystemExit(exit_code)

    application = QApplication(sys.argv)
    application.setApplicationName(APP_NAME)
    application.setApplicationDisplayName(f"{APP_NAME} {APP_VERSION}")
    application.setStyleSheet(validated_stylesheet())
    window = MainWindow()
    window.show()
    diagnostics.event("main_window_shown")
    diagnostics.start_ui_watchdog(application, timeout_seconds=10.0)
    application.aboutToQuit.connect(diagnostics.shutdown)
    if "--smoke-ui" in sys.argv:
        result_path = os.environ.get("STEM_SLICER_SMOKE_RESULT")

        def complete_smoke():
            if result_path:
                with open(result_path, "w", encoding="utf-8") as output:
                    output.write("ok")
            application.quit()

        QTimer.singleShot(750, complete_smoke)
    raise SystemExit(application.exec())


if __name__ == "__main__":
    main()
