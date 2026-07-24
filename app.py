"""Stem Slicer 1.8.2B native application entry point.

The validated HTML prototype is faithfully ported by ``ValidatedMainWindow``;
the old widget layout is deliberately not instantiated.
"""

import json
import os
import platform
import sys

APP_NAME = "Stem Slicer"
APP_VERSION = "1.8.2B"

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
    if "--smoke-runtime" in sys.argv:
        result_path = os.environ.get("STEM_SLICER_SMOKE_RESULT")
        try:
            import PySide6

            payload = json.dumps({
                "app_version": APP_VERSION,
                "architecture": platform.machine(),
                "frozen": bool(getattr(sys, "frozen", False)),
                "python": platform.python_version(),
                "pyside6": PySide6.__version__,
            }, sort_keys=True)
            exit_code = 0
        except Exception as exc:
            diagnostics.exception("runtime_smoke", exc)
            payload, exit_code = f"{type(exc).__name__}: {exc}", 1
        if result_path:
            with open(result_path, "w", encoding="utf-8") as output:
                output.write(payload)
        diagnostics.shutdown()
        raise SystemExit(exit_code)

    if "--smoke-convert-engine" in sys.argv:
        result_path = os.environ.get("STEM_SLICER_SMOKE_RESULT")
        try:
            from pathlib import Path

            from audio_convert import ConversionRequest, convert_audio

            smoke_audio = os.environ["STEM_SLICER_SMOKE_AUDIO"]
            smoke_output = os.environ["STEM_SLICER_SMOKE_CONVERTED"]
            result = convert_audio(ConversionRequest(
                source=Path(smoke_audio),
                destination=Path(smoke_output),
                source_bpm=140,
                target_bpm=120,
                source_key="C minor",
                target_key="D# major / C minor",
            ))
            if not result.output.is_file() or result.output.stat().st_size <= 0:
                raise RuntimeError("The converted MP3 was not created.")
            payload, exit_code = "ok", 0
        except Exception as exc:
            diagnostics.exception("convert_engine_smoke", exc)
            payload, exit_code = f"{type(exc).__name__}: {exc}", 1
        if result_path:
            with open(result_path, "w", encoding="utf-8") as output:
                output.write(payload)
        diagnostics.shutdown()
        raise SystemExit(exit_code)

    if "--smoke-quick-extract-optional-target" in sys.argv:
        result_path = os.environ.get("STEM_SLICER_SMOKE_RESULT")
        try:
            from pathlib import Path
            import tempfile

            from audio_convert import ConversionResult
            import stem_workflow

            originals = {
                "analyze_loop": stem_workflow.analyze_loop,
                "convert_audio": stem_workflow.convert_audio,
                "process_single_file": stem_workflow.process_single_file,
                "waveform_peaks": stem_workflow.waveform_peaks,
            }
            try:
                with tempfile.TemporaryDirectory(prefix="stem-slicer-optional-target-smoke-") as temporary:
                    root = Path(temporary)
                    source = root / "L Smoke 140 C minor.mp3"
                    source.write_bytes(b"packaged-smoke-source")
                    output_folder = root / "published"
                    output_folder.mkdir()
                    rows = [
                        {
                            "event": "exported",
                            "output_exists": True,
                            "output_name": "Smoke_L1.mp3",
                            "duration_seconds": 8.0,
                        },
                        {
                            "event": "exported",
                            "output_exists": True,
                            "output_name": "Smoke_L2.mp3",
                            "duration_seconds": 8.0,
                        },
                    ]

                    def smoke_extract(_source, extraction_folder, _stem):
                        for index, row in enumerate(rows, start=1):
                            Path(extraction_folder, row["output_name"]).write_bytes(
                                f"raw-{index}".encode("ascii")
                            )
                        return rows

                    def smoke_convert(request):
                        request.destination.parent.mkdir(parents=True, exist_ok=True)
                        request.destination.write_bytes(b"converted-" + request.source.read_bytes())
                        return ConversionResult(request.destination, 0, 120 / 140, -1.0, 0.0)

                    stem_workflow.analyze_loop = lambda *_args, **_kwargs: (
                        stem_workflow.LoopAnalysis(140, "5A", "C minor"),
                        {},
                    )
                    stem_workflow.process_single_file = smoke_extract
                    stem_workflow.convert_audio = smoke_convert
                    stem_workflow.waveform_peaks = lambda _path: [0.0] * 72

                    completed = []
                    failures = []
                    worker = stem_workflow.QuickExtractWorkflowWorker(
                        object(),
                        str(source),
                        str(output_folder),
                        bpm_enabled=True,
                        bpm=120,
                        key_enabled=True,
                        key_pair="D major / B minor",
                    )
                    worker.completed.connect(lambda layers, _elapsed: completed.extend(layers))
                    worker.failed.connect(failures.append)
                    worker.run()
                    published = sorted(output_folder.glob("*.mp3"))
                    if failures or len(completed) != 2 or len(published) != 2:
                        raise RuntimeError(
                            f"Optional Target workflow failed: failures={failures!r}, "
                            f"completed={len(completed)}, published={len(published)}"
                        )
                    if any(not path.read_bytes().startswith(b"converted-raw-") for path in published):
                        raise RuntimeError("Optional Target published a raw or invalid layer.")
                payload, exit_code = "ok", 0
            finally:
                for name, value in originals.items():
                    setattr(stem_workflow, name, value)
        except Exception as exc:
            diagnostics.exception("quick_extract_optional_target_smoke", exc)
            payload, exit_code = f"{type(exc).__name__}: {exc}", 1
        if result_path:
            with open(result_path, "w", encoding="utf-8") as output:
                output.write(payload)
        diagnostics.shutdown()
        raise SystemExit(exit_code)

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
