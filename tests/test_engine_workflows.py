import os
import tempfile
import unittest
from unittest.mock import patch

import engine
from filename_templates import TOKENS
from sequence_decoder import SequenceResult, Slot


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
    def test_sequence_decoder_result_maps_to_existing_grid_contract(self):
        result = SequenceResult(
            score=42.5,
            confidence_margin=3.0,
            base_layer_bars=8,
            base_space_bars=4,
            first_start=36,
            slots=(
                Slot(36, 8, 4, True, 1.0),
                Slot(48, 8, 4, False, 0.0),
                Slot(60, 24, 0, True, 1.0),
            ),
        )
        with patch.object(engine, "infer_sequence_grid", return_value=result):
            grid = engine.infer_structural_grid([], [], 0.0, 1.0, 100.0)

        self.assertEqual(grid["first_start"], 36)
        self.assertEqual(grid["slots"], [36, 48, 60])
        self.assertEqual(grid["active_slots"], [36, 60])
        self.assertEqual(grid["silent_slots"], [48])
        self.assertEqual(grid["duration_by_slot"], {36: 8, 48: 8, 60: 24})
        self.assertEqual(grid["stride_bars"], 12)

    def test_duration_probe_falls_back_to_ffmpeg(self):
        class Result:
            returncode = 0
            stderr = "Duration: 00:01:23.45, start: 0.000000, bitrate: 320 kb/s"

        with patch.object(engine, "run_subprocess", return_value=Result()) as runner:
            duration = engine.get_duration("loop.mp3", "/bundled/ffmpeg", ffprobe=None)

        self.assertAlmostEqual(duration, 83.45)
        self.assertEqual(runner.call_args.args[0][0], "/bundled/ffmpeg")

    def test_windows_subprocesses_are_hidden(self):
        class StartupInfo:
            def __init__(self):
                self.dwFlags = 0
                self.wShowWindow = None

        with (
            patch.object(engine.sys, "platform", "win32"),
            patch.object(engine.subprocess, "STARTUPINFO", StartupInfo, create=True),
            patch.object(engine.subprocess, "STARTF_USESHOWWINDOW", 1, create=True),
            patch.object(engine.subprocess, "SW_HIDE", 0, create=True),
            patch.object(engine.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True),
        ):
            options = engine.hidden_process_options()
        self.assertEqual(options["creationflags"], 0x08000000)
        self.assertEqual(options["startupinfo"].dwFlags, 1)
        self.assertEqual(options["startupinfo"].wShowWindow, 0)

    def test_windows_ffmpeg_uses_exe_suffix(self):
        with tempfile.TemporaryDirectory() as root:
            executable = os.path.join(root, "ffmpeg.exe")
            open(executable, "wb").close()
            with patch.object(engine.sys, "platform", "win32"), patch.object(engine.sys, "_MEIPASS", root, create=True):
                self.assertEqual(engine.find_ffmpeg(), executable)

    def test_frozen_bundle_does_not_fall_back_to_external_ffprobe(self):
        with tempfile.TemporaryDirectory() as root:
            ffmpeg = os.path.join(root, "ffmpeg.exe")
            open(ffmpeg, "wb").close()
            with (
                patch.object(engine.sys, "platform", "win32"),
                patch.object(engine.sys, "_MEIPASS", root, create=True),
                patch.object(engine.shutil, "which") as which,
            ):
                self.assertIsNone(engine.find_ffprobe(ffmpeg))
            which.assert_not_called()

    def test_quick_extract_rejects_non_mp3_input(self):
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "loop.wav")
            open(source, "wb").close()
            with self.assertRaisesRegex(ValueError, "MP3"):
                engine.process_single_file(source, os.path.join(root, "output"))

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

    def test_in_place_rename_does_not_create_csv(self):
        with tempfile.TemporaryDirectory() as source:
            filename = "L CALLMEUR3 137 Am +NRGY.mp3"
            with open(os.path.join(source, filename), "wb") as handle:
                handle.write(b"audio")
            FakeAnalyzer.calls = []
            engine.KeyAnalyzer = FakeAnalyzer
            errors = []
            engine.process_audio(
                source,
                "",
                lambda *args: None,
                lambda *args: None,
                errors.append,
                {
                    "enabled": True,
                    "extract_enabled": False,
                    "mode": "relative_minor",
                    "accidentals": "sharps",
                    "destination_mode": "rename_in_place",
                    "token_order": list(TOKENS),
                },
            )
            self.assertFalse(errors)
            self.assertEqual(os.listdir(source), ["A#m CALLMEUR3 137 +NRGY.mp3"])

    def test_shared_analyzer_prevents_second_engine_instance(self):
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as output:
            filename = "L CALLMEUR3 137 +NRGY.mp3"
            open(os.path.join(source, filename), "wb").close()
            shared = FakeAnalyzer()
            shared.calls = []

            class UnexpectedAnalyzer:
                def __init__(self, *args, **kwargs):
                    raise AssertionError("A second key engine was instantiated")

            engine.KeyAnalyzer = UnexpectedAnalyzer
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
                    "mode": "detected",
                    "accidentals": "sharps",
                    "destination_mode": "copy_to_output",
                    "token_order": list(TOKENS),
                },
                analyzer=shared,
            )
            self.assertFalse(errors)
            self.assertEqual(shared.calls, [filename])


if __name__ == "__main__":
    unittest.main()
