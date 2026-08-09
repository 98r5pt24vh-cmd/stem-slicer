"""Exercise the real Quick Extract MIDI loader, worker, signal and card path."""

import os
from pathlib import Path
import sys
import time


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

os.environ.setdefault("STEM_SLICER_DISABLE_ENGINE_AUTOSTART", "1")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app import MainWindow


def wait_until(predicate, timeout_seconds, description):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return
        QTest.qWait(25)
    raise RuntimeError(f"Timed out waiting for {description}.")


def main():
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    warmup_audio = REPOSITORY_ROOT / "assets" / "key-and-bpm-engine-warmup.wav"
    if not warmup_audio.is_file():
        raise RuntimeError(f"MIDI lifecycle input is missing: {warmup_audio}")

    try:
        window._start_midi_engine()
        wait_until(
            lambda: window.midi_engine_state in {"ready", "failed"},
            360,
            "the MIDI engine loader",
        )
        if window.midi_engine_state != "ready":
            raise RuntimeError("The MIDI engine loader reported failure.")

        layer = {
            "path": str(warmup_audio),
            "name": "Lifecycle Smoke 140 C minor.wav",
            "display_name": "Lifecycle Smoke 140 C minor.wav",
            "key": "5A",
            "bpm": 140,
            "duration": 1.0,
            "bytes": warmup_audio.stat().st_size,
            "peaks": [0.0] * 72,
        }
        window._populate_layer_cards([layer])
        window._queue_midi_conversion([layer])
        wait_until(lambda: len(window.layer_cards) == 1, 10, "the Quick Extract layer card")
        card = window.layer_cards[0]
        wait_until(
            lambda: card.midi_handle.state != "processing",
            240,
            "the Quick Extract MIDI card result",
        )
        midi_path = Path(card.midi_handle.path)
        if card.midi_handle.state != "ready" or not midi_path.is_file() or midi_path.stat().st_size <= 0:
            raise RuntimeError(
                f"Quick Extract MIDI card did not become draggable: "
                f"state={card.midi_handle.state!r}, path={str(midi_path)!r}."
            )
        print(f"Quick Extract MIDI lifecycle ready: {midi_path.name} ({midi_path.stat().st_size} bytes)")
    finally:
        if window.midi_loader_thread is not None and window.midi_loader_thread.is_alive():
            window.midi_loader_thread.join(360)
            application.processEvents()
        window.close()
        application.processEvents()


if __name__ == "__main__":
    main()
