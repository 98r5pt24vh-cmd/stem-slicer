import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from functional_core import MidiEngineService


class MidiEngineServiceTests(unittest.TestCase):
    def test_one_converter_handles_pending_and_sequential_jobs_on_its_owner_thread(self):
        initialized = threading.Event()
        two_conversions = threading.Event()
        thread_ids = {"convert": []}
        instances = []

        class FakeConverter:
            def __init__(self):
                instances.append(self)
                thread_ids["init"] = threading.get_ident()
                initialized.set()

            def convert(self, audio_path, midi_path, bpm=None):
                thread_ids["convert"].append(threading.get_ident())
                os.makedirs(os.path.dirname(midi_path), exist_ok=True)
                with open(midi_path, "wb") as output:
                    output.write(b"MThd" + b"\0" * 16)
                if len(thread_ids["convert"]) == 2:
                    two_conversions.set()

        service = MidiEngineService()
        service.latest_job_id = 1
        layer = {"path": "/private/tmp/layer.mp3", "bpm": 140}
        try:
            with tempfile.TemporaryDirectory() as cache_path, patch(
                "midi_conversion.MidiConverter",
                FakeConverter,
            ):
                # A job may already be waiting when the engine finishes its
                # first load.  It must be handled by that same converter.
                service.submit([layer], cache_path, 1)
                service.start()
                self.assertTrue(initialized.wait(2), "MIDI converter did not initialize")
                while len(thread_ids["convert"]) < 1:
                    self.assertTrue(service.is_alive())
                    threading.Event().wait(0.01)
                service.latest_job_id = 2
                service.submit([layer], cache_path, 2)
                self.assertTrue(two_conversions.wait(2), "Sequential MIDI conversion did not finish")
        finally:
            service.request_stop()
            service.join(2)

        self.assertFalse(service.is_alive())
        self.assertEqual(len(instances), 1)
        self.assertEqual(thread_ids["convert"], [thread_ids["init"], thread_ids["init"]])
        self.assertNotEqual(thread_ids["init"], threading.get_ident())
        event_kinds = []
        while not service.events.empty():
            event_kinds.append(service.events.get_nowait()[0])
        self.assertEqual(event_kinds[0], "ready")
        self.assertEqual(event_kinds.count("completed"), 2)
        # The first result may be suppressed when job 2 supersedes it between
        # converter return and publication; the current job must still report.
        self.assertGreaterEqual(event_kinds.count("progress"), 1)
        self.assertEqual(event_kinds[-1], "completed")

    def test_stale_job_is_skipped(self):
        converted = threading.Event()
        converted_paths = []

        class FakeConverter:
            def convert(self, audio_path, midi_path, bpm=None):
                converted_paths.append(audio_path)
                converted.set()

        service = MidiEngineService()
        service.latest_job_id = 2
        try:
            with patch("midi_conversion.MidiConverter", FakeConverter):
                service.submit([{"path": "stale.mp3", "bpm": 140}], "/tmp", 1)
                service.submit([{"path": "current.mp3", "bpm": 140}], "/tmp", 2)
                service.start()
                self.assertTrue(converted.wait(2))
        finally:
            service.request_stop()
            service.join(2)

        self.assertEqual(converted_paths, ["current.mp3"])

    def test_constructor_failure_reports_failed_event_and_stops(self):
        class BrokenConverter:
            def __init__(self):
                raise RuntimeError("broken converter")

        service = MidiEngineService()
        with patch("midi_conversion.MidiConverter", BrokenConverter):
            service.start()
            service.join(2)

        self.assertFalse(service.is_alive())
        self.assertEqual(service.events.get_nowait(), ("failed", "broken converter"))


if __name__ == "__main__":
    unittest.main()
