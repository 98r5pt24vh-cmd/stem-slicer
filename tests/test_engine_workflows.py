import os
import tempfile
import unittest

import engine
from filename_templates import TOKENS


class FakeAnalyzer:
    calls = []

    def __init__(self, workers=1):
        self.workers = workers

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def analyze(self, path):
        self.calls.append(os.path.basename(path))
        return {"camelot": "3A"}


class EngineWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.originals = {
            "KeyAnalyzer": engine.KeyAnalyzer,
            "find_ffmpeg": engine.find_ffmpeg,
            "find_ffprobe": engine.find_ffprobe,
            "process_one_file": engine.process_one_file,
        }

    def tearDown(self):
        for name, value in self.originals.items():
            setattr(engine, name, value)

    def test_simple_extraction_preserves_original_stem(self):
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as output:
            filename = "L ARTIFICIAL 144 +NRGY.mp3"
            open(os.path.join(source, filename), "wb").close()
            captured = []
            engine.find_ffmpeg = lambda: "/fake/ffmpeg"
            engine.find_ffprobe = lambda ffmpeg: "/fake/ffprobe"

            def process(*args, **kwargs):
                captured.append(args[-1])
                return []

            engine.process_one_file = process
            errors = []
            engine.process_audio(
                source,
                output,
                lambda *args: None,
                lambda *args: None,
                errors.append,
                {"enabled": False, "extract_enabled": True, "token_order": list(TOKENS)},
            )
            self.assertFalse(errors)
            self.assertEqual(captured, ["L ARTIFICIAL 144 +NRGY"])

    def test_key_analysis_replaces_existing_key(self):
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as output:
            filename = "L CALLMEUR3 137 Am +NRGY.mp3"
            with open(os.path.join(source, filename), "wb") as handle:
                handle.write(b"audio")
            FakeAnalyzer.calls = []
            engine.KeyAnalyzer = FakeAnalyzer
            errors = []
            engine.process_audio(
                source,
                output,
                lambda *args: None,
                lambda *args: None,
                errors.append,
                {
                    "enabled": True,
                    "extract_enabled": False,
                    "mode": "relative_minor",
                    "accidentals": "sharps",
                    "destination_mode": "copy_to_output",
                    "token_order": list(TOKENS),
                },
            )
            self.assertFalse(errors)
            self.assertEqual(FakeAnalyzer.calls, [filename])
            self.assertEqual(os.listdir(output), ["A#m CALLMEUR3 137 +NRGY.mp3"])


if __name__ == "__main__":
    unittest.main()
