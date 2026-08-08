import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STEM_SLICER_DISABLE_ENGINE_AUTOSTART", "1")

import generator_controller
from layer_library import LayerLibrary, LayerPrediction


CORPUS_FILENAME = "A#m NOSL33P 144 +NRGY_L1.mp3"
LEGACY_TRUTH_ENV = "STEM_SLICER_GENERATE_TRUTH_CSV"


def _write_wave(path: Path) -> None:
    """Write a tiny valid test signal while retaining the corpus filename."""

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8_000)
        handle.writeframes(b"\x00\x00" * 800)


class _Classifier:
    classifier_id = "runtime-isolation-test-v1"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def predict(self, _path, metadata):
        self.calls.append(metadata.filename)
        return LayerPrediction(
            "Lead",
            confidence=0.8,
            scores={"Lead": 0.8, "Bass": 0.2},
        )


def _run_worker(
    library_root: Path,
    cache_path: Path,
    classifier: _Classifier,
    development_truth_path: Path | None,
):
    completed = []
    failures = []
    worker = generator_controller.ScanWorker(
        library_root,
        cache_path,
        classifier=classifier,
        development_truth_path=development_truth_path,
        key_confidence_inventory_path=None,
        key_confidence_results_path=None,
    )
    worker.completed.connect(completed.append)
    worker.failed.connect(failures.append)
    worker.run()
    if failures:
        raise AssertionError(failures)
    if len(completed) != 1:
        raise AssertionError(f"Expected one scan result, got {len(completed)}")
    return completed[0]


class RuntimeTruthIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.library = self.root / "user-library"
        self.library.mkdir()
        self.audio = self.library / CORPUS_FILENAME
        _write_wave(self.audio)
        self.truth = self.root / "training-manifest.csv"
        self.truth.write_text(
            f"file,label\n{CORPUS_FILENAME},Bass\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def _resolved_development_truth(self):
        return generator_controller.GeneratorController._development_truth_path(
            object()
        )

    def test_corpus_named_file_is_classified_normally_without_dev_overlay(self):
        classifier = _Classifier()
        production_cache = self.root / "production.sqlite3"
        environment = {
            generator_controller.DEVELOPMENT_TRUTH_ENV: "",
            # The old generic variable must not revive the training manifest.
            LEGACY_TRUTH_ENV: str(self.truth),
        }
        with patch.dict(os.environ, environment, clear=False):
            truth_path = self._resolved_development_truth()
            result = _run_worker(
                self.library,
                production_cache,
                classifier,
                truth_path,
            )

        self.assertIsNone(truth_path)
        self.assertEqual(classifier.calls, [CORPUS_FILENAME])
        self.assertEqual(result.classified_count, 1)
        self.assertEqual(result.records[0].effective_label, "Lead")
        self.assertEqual(result.records[0].label_source, "prediction")
        with sqlite3.connect(production_cache) as connection:
            cached = connection.execute(
                "SELECT manual_label, predicted_label, classifier_id "
                "FROM layer_cache"
            ).fetchone()
        self.assertEqual(
            cached,
            (None, "Lead", "runtime-isolation-test-v1"),
        )

    def test_explicit_dev_overlay_bypasses_classifier_only_in_isolated_cache(self):
        classifier = _Classifier()
        development_cache = self.root / "development.sqlite3"
        with patch.dict(
            os.environ,
            {generator_controller.DEVELOPMENT_TRUTH_ENV: str(self.truth)},
            clear=False,
        ):
            truth_path = self._resolved_development_truth()
            result = _run_worker(
                self.library,
                development_cache,
                classifier,
                truth_path,
            )

        self.assertEqual(truth_path, self.truth.resolve())
        self.assertEqual(classifier.calls, [])
        self.assertEqual(result.classified_count, 0)
        self.assertEqual(result.records[0].effective_label, "Bass")
        self.assertEqual(result.records[0].label_source, "manual")
        with sqlite3.connect(development_cache) as connection:
            cached = connection.execute(
                "SELECT manual_label, predicted_label, manual_origin "
                "FROM layer_cache"
            ).fetchone()
        self.assertEqual(cached[0:2], ("Bass", None))
        self.assertEqual(cached[2], f"csv:{self.truth.resolve()}")

        self.assertNotEqual(
            generator_controller.default_cache_path(),
            generator_controller.development_truth_cache_path(),
        )

    def test_missing_dev_overlay_path_is_disabled(self):
        missing = self.root / "missing.csv"
        with patch.dict(
            os.environ,
            {generator_controller.DEVELOPMENT_TRUTH_ENV: str(missing)},
            clear=False,
        ):
            self.assertIsNone(self._resolved_development_truth())

    def test_normal_scan_replaces_legacy_csv_label_with_model_prediction(self):
        cache = self.root / "legacy-contaminated.sqlite3"
        development_classifier = _Classifier()
        seeded = _run_worker(
            self.library,
            cache,
            development_classifier,
            self.truth.resolve(),
        )
        self.assertEqual(seeded.records[0].effective_label, "Bass")
        self.assertEqual(development_classifier.calls, [])

        production_classifier = _Classifier()
        result = _run_worker(
            self.library,
            cache,
            production_classifier,
            None,
        )

        self.assertEqual(production_classifier.calls, [CORPUS_FILENAME])
        self.assertEqual(result.records[0].effective_label, "Lead")
        self.assertEqual(result.records[0].label_source, "prediction")
        with sqlite3.connect(cache) as connection:
            cached = connection.execute(
                "SELECT manual_label, manual_origin, predicted_label "
                "FROM layer_cache"
            ).fetchone()
        self.assertEqual(cached, (None, None, "Lead"))

    def test_production_cache_restore_hides_legacy_csv_label(self):
        cache = self.root / "legacy-restore.sqlite3"
        _run_worker(
            self.library,
            cache,
            _Classifier(),
            self.truth.resolve(),
        )

        restored = LayerLibrary(
            self.library,
            cache,
            classifier=_Classifier(),
        ).load_cached()

        self.assertIsNone(restored.records[0].effective_label)
        self.assertEqual(restored.records[0].label_source, "unreviewed")
        self.assertIn(
            "stale_truth_cache",
            {issue.code for issue in restored.issues},
        )


if __name__ == "__main__":
    unittest.main()
