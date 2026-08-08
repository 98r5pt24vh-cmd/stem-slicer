import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from audio_convert import ConversionResult
from stem_workflow import (
    BatchWorkflowWorker,
    LoopAnalysis,
    QuickConvertWorkflowWorker,
    QuickExtractWorkflowWorker,
    TargetSelection,
    analyze_loop,
    build_output_stem,
    resolved_target_bpm,
    target_key_for_source,
)


class FakeAnalyzer:
    def __init__(self, result):
        self.result = dict(result)
        self.calls = []

    def analyze(self, path, **kwargs):
        self.calls.append((path, kwargs))
        return dict(self.result)


def fake_conversion(request):
    request.destination.parent.mkdir(parents=True, exist_ok=True)
    request.destination.write_bytes(b"converted")
    speed = (request.target_bpm or request.source_bpm) / request.source_bpm
    return ConversionResult(request.destination, 0, speed, -1.0, 0.0)


class WorkflowTests(unittest.TestCase):
    def test_loop_analysis_uses_exact_loop_mode_and_canonical_tempo(self):
        analyzer = FakeAnalyzer({"bpm": 75.0, "camelot": "3A"})
        with patch("stem_workflow.find_ffmpeg", return_value="ffmpeg"):
            analysis, raw = analyze_loop(analyzer, "/tmp/Loop.mp3")

        self.assertEqual(analysis, LoopAnalysis(150, "3A", "A# minor"))
        self.assertEqual(raw["bpm"], 75.0)
        self.assertEqual(len(analyzer.calls), 1)
        self.assertEqual(analyzer.calls[0][1]["bpm_mode"], "quick_scan_loop")
        self.assertEqual(analyzer.calls[0][1]["structure_ffmpeg_path"], "ffmpeg")

    def test_target_pair_follows_source_mode_and_shortest_display_rule(self):
        minor = LoopAnalysis(140, "3A", "A# minor")
        major = LoopAnalysis(140, "3B", "C# major")
        target = TargetSelection(True, 120, True, "C major / A minor")

        self.assertEqual(target_key_for_source(minor, target.key_pair), "A minor")
        self.assertEqual(target_key_for_source(major, target.key_pair), "C major")
        self.assertEqual(resolved_target_bpm(minor, target), 120)
        self.assertEqual(
            build_output_stem("L Cut The Rope 140 +NRGY.mp3", minor, target),
            "Cut The Rope 120 A minor +NRGY",
        )

    def test_quick_convert_rejects_when_both_targets_are_off(self):
        worker = QuickConvertWorkflowWorker(
            object(),
            "/tmp/Loop.mp3",
            "/tmp",
            bpm_enabled=False,
            bpm=None,
            key_enabled=False,
            key_pair=None,
        )
        failures = []
        worker.failed.connect(failures.append)
        worker.run()
        self.assertEqual(failures, ["Enable BPM, Key, or both before converting."])

    def test_quick_convert_key_only_keeps_detected_bpm_and_writes_mp3(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, "L Loop 148 C minor +NRGY.wav")
            source.write_bytes(b"audio")
            output = Path(root, "converted")
            worker = QuickConvertWorkflowWorker(
                object(),
                str(source),
                str(output),
                bpm_enabled=False,
                bpm=None,
                key_enabled=True,
                key_pair="D major / B minor",
            )
            completed = []
            requests = []
            worker.completed.connect(lambda result, elapsed: completed.append(result))

            def convert(request):
                requests.append(request)
                return fake_conversion(request)

            with patch("stem_workflow.analyze_loop", return_value=(LoopAnalysis(148, "5A", "C minor"), {})), \
                 patch("stem_workflow.convert_audio", side_effect=convert):
                worker.run()

            self.assertEqual(len(completed), 1)
            self.assertEqual(completed[0]["target_bpm"], 148)
            self.assertEqual(completed[0]["target_key"], "B minor")
            self.assertTrue(completed[0]["path"].endswith(".mp3"))
            self.assertIsNone(requests[0].target_bpm)
            self.assertEqual(requests[0].target_key, "D major / B minor")

    def test_quick_extract_extracts_before_converting_every_layer(self):
        events = []
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, "L Loop 140 C minor +NRGY.mp3")
            source.write_bytes(b"audio")
            output = Path(root, "session")
            output.mkdir()
            rows = [
                {"event": "exported", "output_exists": True, "output_name": "Loop_L1.mp3", "duration_seconds": 8.0, "output_bytes": 5},
                {"event": "exported", "output_exists": True, "output_name": "Loop_L2.mp3", "duration_seconds": 8.0, "output_bytes": 5},
            ]

            def extract(*args):
                events.append("extract")
                for row in rows:
                    Path(output, row["output_name"]).write_bytes(b"layer")
                return rows

            def convert(request):
                events.append("convert")
                return fake_conversion(request)

            worker = QuickExtractWorkflowWorker(
                object(), str(source), str(output),
                bpm_enabled=True, bpm=120,
                key_enabled=True, key_pair="D major / B minor",
            )
            completed = []
            worker.completed.connect(lambda layers, elapsed: completed.extend(layers))
            with patch("stem_workflow.analyze_loop", return_value=(LoopAnalysis(140, "5A", "C minor"), {})), \
                 patch("stem_workflow.process_single_file", side_effect=extract), \
                 patch("stem_workflow.convert_audio", side_effect=convert), \
                 patch("stem_workflow.waveform_peaks", return_value=[0.0] * 72):
                worker.run()

            self.assertEqual(events, ["extract", "convert", "convert"])
            self.assertEqual(len(completed), 2)
            self.assertTrue(all(layer["bpm"] == 120 for layer in completed))
            self.assertTrue(all(layer["key"] == "B minor" for layer in completed))

    def test_batch_convert_only_analyzes_each_source_once(self):
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as output:
            for name in ("L One 140 C minor.mp3", "L Two 148 C minor.mp3"):
                Path(source, name).write_bytes(b"audio")
            settings = {
                "extract_enabled": False,
                "enabled": False,
                "convert_enabled": True,
                "target_bpm_enabled": True,
                "target_bpm": 120,
                "target_key_enabled": False,
                "target_key": "C major / A minor",
            }
            worker = BatchWorkflowWorker(source, output, settings, analyzer=object())
            completed = []
            worker.completed.connect(lambda failures, manifest: completed.append((failures, manifest)))
            analyses = []

            def analyze(analyzer, path):
                analyses.append(path)
                bpm = 140 if "One" in path else 148
                return LoopAnalysis(bpm, "5A", "C minor"), {"bpm": bpm, "camelot": "5A"}

            with patch("stem_workflow.analyze_loop", side_effect=analyze), \
                 patch("stem_workflow.convert_audio", side_effect=fake_conversion):
                worker.run()

            self.assertEqual(len(analyses), 2)
            self.assertEqual(len(set(analyses)), 2)
            self.assertEqual(completed[0][0], [])
            outputs = completed[0][1]["outputs_by_source"]
            self.assertEqual(set(outputs), {"L One 140 C minor.mp3", "L Two 148 C minor.mp3"})
            self.assertTrue(all(Path(paths[0]).is_file() for paths in outputs.values()))


if __name__ == "__main__":
    unittest.main()
