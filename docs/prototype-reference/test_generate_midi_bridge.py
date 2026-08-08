import os
import sys
from pathlib import Path
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STEM_SLICER_DISABLE_ENGINE_AUTOSTART", "1")

ROOT = Path(__file__).resolve().parent
SOURCE = (
    ROOT.parent
    / "Stem Slicer 1.9 macOS Beta - 2026-08-08"
    / "Source"
    / "Stem_Slicer_1.9_macOS"
)
sys.path.insert(1, str(SOURCE))

from PySide6.QtWidgets import QApplication

from generate_midi_bridge import GenerateMidiBridge


APP = QApplication.instance() or QApplication([])


class _Signal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, *args):
        for callback in tuple(self._callbacks):
            callback(*args)


class _Page:
    def __init__(self):
        self.midiBatchRequested = _Signal()
        self.midiLayerRequested = _Signal()
        self.paths = []
        self.all_unavailable = False

    def set_layer_midi_path(self, audio_path, midi_path):
        self.paths.append((audio_path, midi_path))

    def set_all_midi_unavailable(self):
        self.all_unavailable = True


class _ServiceSignals:
    def __init__(self):
        self.ready = _Signal()
        self.failed = _Signal()
        self.progress = _Signal()
        self.completed = _Signal()


class _Service:
    def __init__(self):
        self.signals = _ServiceSignals()
        self.latest_job_id = 0
        self.jobs = []

    def submit(self, requests, cache_path, job_id):
        self.jobs.append((tuple(requests), cache_path, job_id))


class GenerateMidiBridgeTests(unittest.TestCase):
    def test_batch_reuses_service_and_exposes_ready_midi(self):
        page = _Page()
        service = _Service()
        bridge = GenerateMidiBridge(page, service, engine_ready=True)

        page.midiBatchRequested.emit(
            ({"path": "/tmp/layer.mp3", "bpm": 140, "identity": "one"},)
        )

        self.assertEqual(len(service.jobs), 1)
        job_id = service.jobs[0][2]
        self.assertGreaterEqual(job_id, 1_000_000_001)
        service.signals.progress.emit(
            job_id, "/tmp/layer.mp3", "/tmp/layer.mid", 1, 1
        )
        self.assertEqual(
            page.paths, [("/tmp/layer.mp3", "/tmp/layer.mid")]
        )
        bridge.deleteLater()

    def test_changed_card_waits_then_replaces_stale_batch_result(self):
        page = _Page()
        service = _Service()
        bridge = GenerateMidiBridge(page, service, engine_ready=True)
        request = {
            "path": "/tmp/transformed.mp3",
            "bpm": 140,
            "identity": "one",
        }
        page.midiBatchRequested.emit((request,))
        first_job = service.jobs[0][2]

        page.midiLayerRequested.emit(request)
        service.signals.progress.emit(
            first_job,
            request["path"],
            "/tmp/stale.mid",
            1,
            1,
        )
        self.assertEqual(page.paths, [])

        service.signals.completed.emit(first_job, 1, 0.1)
        self.assertEqual(len(service.jobs), 2)
        second_job = service.jobs[1][2]
        service.signals.progress.emit(
            second_job,
            request["path"],
            "/tmp/current.mid",
            1,
            1,
        )
        self.assertEqual(
            page.paths,
            [(request["path"], "/tmp/current.mid")],
        )
        bridge.deleteLater()


if __name__ == "__main__":
    unittest.main()
