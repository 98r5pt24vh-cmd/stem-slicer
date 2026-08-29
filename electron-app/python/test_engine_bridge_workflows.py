from pathlib import Path
import os
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine_bridge as bridge


class EngineBridgeWorkflowTests(unittest.TestCase):
    def test_processing_runtime_warmup_resolves_shared_audio_tools(self) -> None:
        import engine

        with (
            patch.object(engine, "find_ffmpeg", return_value="/runtime/ffmpeg") as find_ffmpeg,
            patch.object(engine, "find_ffprobe", return_value="/runtime/ffprobe") as find_ffprobe,
        ):
            bridge.warm_processing_runtime()

        find_ffmpeg.assert_called_once_with()
        find_ffprobe.assert_called_once_with("/runtime/ffmpeg")

    def test_processing_runtime_warmup_fails_when_ffmpeg_is_unavailable(self) -> None:
        import engine

        with patch.object(engine, "find_ffmpeg", return_value=None):
            with self.assertRaisesRegex(FileNotFoundError, "FFmpeg is unavailable"):
                bridge.warm_processing_runtime()

    def test_categorization_runtime_warmup_starts_the_persistent_worker(self) -> None:
        fake_classifier = SimpleNamespace(start=lambda: None)
        with patch.object(bridge, "classifier", return_value=fake_classifier) as classifier_factory:
            with patch.object(fake_classifier, "start") as start:
                bridge.warm_categorization_runtime()

        classifier_factory.assert_called_once_with()
        start.assert_called_once_with()

    def test_engine_shutdown_stops_the_persistent_classifier(self) -> None:
        fake_classifier = SimpleNamespace(stop=lambda: None)
        with (
            patch.object(bridge, "_analyzer", None),
            patch.object(bridge, "_classifier", fake_classifier),
            patch.object(fake_classifier, "stop") as stop,
        ):
            bridge.close_engines()

        stop.assert_called_once_with()

    def test_target_pair_follows_the_detected_source_mode(self) -> None:
        self.assertEqual(
            bridge.target_key_for_source("C minor", "D major / B minor"),
            "B minor",
        )
        self.assertEqual(
            bridge.target_key_for_source("E major", "D major / B minor"),
            "D major",
        )

    def test_quick_convert_rejects_an_empty_target_selection(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "Loop 140 C minor.mp3"
            source.write_bytes(b"audio")
            with self.assertRaisesRegex(ValueError, "Enable Target BPM, Target Key, or both"):
                bridge.quick_convert(
                    "job",
                    {
                        "source": str(source),
                        "targetBpmEnabled": False,
                        "targetKeyEnabled": False,
                    },
                )

    def test_batch_rejects_when_every_operation_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as source_root, tempfile.TemporaryDirectory() as output_root:
            (Path(source_root) / "Loop 140 C minor.mp3").write_bytes(b"audio")
            with self.assertRaisesRegex(ValueError, "Enable at least one batch operation"):
                bridge.batch(
                    "job",
                    {
                        "sourceFolder": source_root,
                        "outputFolder": output_root,
                        "extractionEnabled": False,
                        "keyAnalysisEnabled": False,
                        "conversionEnabled": False,
                    },
                )

    def test_batch_conversion_analyzes_each_source_once(self) -> None:
        with tempfile.TemporaryDirectory() as source_root, tempfile.TemporaryDirectory() as output_root:
            sources = [
                Path(source_root) / "One 140 C minor.mp3",
                Path(source_root) / "Two 148 C minor.mp3",
            ]
            for source in sources:
                source.write_bytes(b"audio")

            analyzed = []

            class FakeAnalyzer:
                def analyze(self, source):
                    analyzed.append(Path(source).name)
                    return {"bpm": 140, "camelot": "5A"}

            def fake_scan(source, _raw):
                return {
                    "bpm": 140 if Path(source).name.startswith("One") else 148,
                    "detectedKey": "C minor",
                    "camelot": "5A",
                }

            def fake_convert(request):
                request.destination.write_bytes(b"converted")
                return SimpleNamespace(destination=request.destination)

            with (
                patch.object(bridge, "analyzer", return_value=FakeAnalyzer()),
                patch.object(bridge, "scan_payload", side_effect=fake_scan),
                patch.object(bridge, "progress"),
                patch("audio_convert.convert_audio", side_effect=fake_convert),
            ):
                result = bridge.batch(
                    "job",
                    {
                        "sourceFolder": source_root,
                        "outputFolder": output_root,
                        "extractionEnabled": False,
                        "keyAnalysisEnabled": False,
                        "conversionEnabled": True,
                        "targetBpmEnabled": True,
                        "targetBpm": 120,
                        "targetKeyEnabled": False,
                    },
                )

            self.assertCountEqual(analyzed, [source.name for source in sources])
            self.assertEqual(len(analyzed), len(set(analyzed)))
            self.assertEqual(result["failures"], [])
            self.assertEqual(len(result["outputs"]), 2)
            self.assertTrue(all(Path(output).is_file() for output in result["outputs"]))

    def test_quick_extract_finishes_audio_conversion_before_midi(self) -> None:
        events = []
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source = root_path / "Loop 140 C minor.mp3"
            source.write_bytes(b"audio")
            destination = root_path / "Quick Extract"
            destination.mkdir()

            def fake_extract(_source, output, _stem):
                events.append("extract")
                rows = []
                for index in (1, 2):
                    name = f"Loop_L{index}.mp3"
                    Path(output, name).write_bytes(b"layer")
                    rows.append({
                        "event": "exported",
                        "output_exists": True,
                        "output_name": name,
                        "duration_seconds": 8.0,
                        "waveform_peaks": [0.0] * 72,
                    })
                return rows

            def fake_convert(request):
                events.append("convert")
                request.destination.write_bytes(b"converted")
                return SimpleNamespace(speed_ratio=1.0)

            class FakeMidiConverter:
                def convert(self, _audio_path, midi_path, bpm=None):
                    events.append(f"midi:{bpm}")
                    Path(midi_path).write_bytes(b"MThd")

            scan = {"bpm": 140, "detectedKey": "C minor", "camelot": "5A"}
            with (
                patch.object(bridge, "unique_session_folder", return_value=destination),
                patch.object(bridge, "analyzer", return_value=SimpleNamespace(analyze=lambda _source: {})),
                patch.object(bridge, "scan_payload", return_value=scan),
                patch.object(bridge, "midi_converter", return_value=FakeMidiConverter()),
                patch.object(bridge, "progress"),
                patch.object(bridge, "progress_percent"),
                patch.object(bridge, "send"),
                patch("engine.process_single_file", side_effect=fake_extract),
                patch("audio_convert.convert_audio", side_effect=fake_convert),
            ):
                result = bridge.quick_extract(
                    "job",
                    {
                        "source": str(source),
                        "targetBpmEnabled": True,
                        "targetBpm": 120,
                        "targetKeyEnabled": True,
                        "targetKey": "D major / B minor",
                    },
                )

            self.assertEqual(events[:3], ["extract", "convert", "convert"])
            self.assertEqual(events[3:], ["midi:120", "midi:120"])
            self.assertEqual(len(result["layers"]), 2)
            self.assertTrue(all(layer["midiPath"] for layer in result["layers"]))

    def test_midi_failure_is_isolated_to_its_layer(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            first = Path(root) / "first.mp3"
            second = Path(root) / "second.mp3"
            first.write_bytes(b"audio")
            second.write_bytes(b"audio")
            artifacts = [
                {"path": str(first), "bpm": 140},
                {"path": str(second), "bpm": 150},
            ]

            class FakeMidiConverter:
                def convert(self, audio_path, midi_path, bpm=None):
                    if Path(audio_path).name == "first.mp3":
                        raise RuntimeError("synthetic failure")
                    Path(midi_path).write_bytes(b"MThd")

            with (
                patch.object(bridge, "midi_converter", return_value=FakeMidiConverter()) as converter_factory,
                patch.object(bridge, "progress_percent"),
                patch.object(bridge, "send"),
            ):
                bridge.add_midi("job", artifacts, "midi")

            converter_factory.assert_called_once_with()
            self.assertIsNone(artifacts[0]["midiPath"])
            self.assertEqual(artifacts[0]["midiError"], "synthetic failure")
            self.assertTrue(Path(artifacts[1]["midiPath"]).is_file())

    def test_output_names_and_collision_handling_are_portable(self) -> None:
        self.assertEqual(bridge.safe_name('Bad/Pack:*?'), "Bad-Pack---")
        with tempfile.TemporaryDirectory() as root:
            existing = Path(root) / "Loop.mp3"
            existing.write_bytes(b"audio")
            self.assertEqual(bridge.unique_file(existing).name, "Loop 2.mp3")

    def test_library_scan_never_activates_training_truth_from_environment(self) -> None:
        import layer_library

        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            library_root = root_path / "library"
            library_root.mkdir()
            accepted_root = (root_path / "accepted").resolve()
            database = accepted_root / "generate" / "library.sqlite3"
            captured = {}

            class FakeLayerLibrary:
                def __init__(self, *args, **kwargs):
                    captured["args"] = args
                    captured["kwargs"] = kwargs

                def scan(self, **_kwargs):
                    return SimpleNamespace(
                        library_root=str(library_root),
                        hashed_count=1,
                        cached_count=0,
                        issues=[],
                    )

            with (
                patch.dict(os.environ, {
                    "STEM_SLICER_GENERATE_TRUTH_CSV": str(root_path / "legacy.csv"),
                    "STEM_SLICER_GENERATE_DEV_TRUTH_CSV": str(root_path / "development.csv"),
                }),
                patch.object(bridge, "ACCEPTED_CACHE_ROOT", accepted_root),
                patch.object(bridge, "classifier", return_value=object()),
                patch.object(bridge, "progress_percent"),
                patch.object(bridge, "progress"),
                patch.object(layer_library, "LayerLibrary", FakeLayerLibrary),
                patch.object(
                    layer_library,
                    "require_extracted_layer_folder",
                    return_value=SimpleNamespace(audio_file_count=1),
                ),
            ):
                bridge.library_scan(
                    "job",
                    {"root": str(library_root), "databasePath": str(database)},
                )

            self.assertNotIn("truth_csv_path", captured["kwargs"])


if __name__ == "__main__":
    unittest.main()
