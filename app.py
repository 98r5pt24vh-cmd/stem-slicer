"""Stem Slicer 1.6B native application entry point.

The validated HTML prototype is faithfully ported by ``ValidatedMainWindow``;
the old widget layout is deliberately not instantiated.
"""

import os
import sys

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


APP_NAME = "Stem Slicer"
APP_VERSION = "1.6B"
MainWindow = ValidatedMainWindow


def main():
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
            result, exit_code = f"{type(exc).__name__}: {exc}", 1
        if result_path:
            with open(result_path, "w", encoding="utf-8") as output:
                output.write(result)
        raise SystemExit(exit_code)

    application = QApplication(sys.argv)
    application.setApplicationName(APP_NAME)
    application.setApplicationDisplayName(f"{APP_NAME} {APP_VERSION}")
    application.setStyleSheet(validated_stylesheet())
    window = MainWindow()
    window.show()
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
