import csv
from contextlib import closing
import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
import wave
from pathlib import Path

from key_confidence import KeyConfidenceIndex

from layer_library import (
    AUDIO_EXTENSIONS,
    TAXONOMY,
    CacheInsideLibraryError,
    CancelToken,
    LayerLibrary,
    LayerPrediction,
    LayerRecord,
    TruthCSVError,
    UnknownLayerError,
    most_recent_cached_library_root,
    parse_layer_filename,
)


def _write_wave(path: Path, *, frames: int = 8000, rate: int = 8000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * frames)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


class _Classifier:
    classifier_id = "fake-v1"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def predict(self, path, metadata):
        self.calls.append(metadata.relative_path)
        return LayerPrediction(
            "Lead",
            confidence=0.8,
            scores={"Lead": 0.8, "Pluck": 0.2},
        )


class _BatchClassifier(_Classifier):
    preferred_batch_size = 3

    def __init__(self) -> None:
        super().__init__()
        self.batch_calls: list[list[str]] = []

    def predict_many(self, items):
        self.batch_calls.append(
            [metadata.relative_path for _path, metadata in items]
        )
        return [
            LayerPrediction(
                "Lead",
                confidence=0.8,
                scores={"Lead": 0.8, "Pluck": 0.2},
            )
            for _item in items
        ]


class LayerFilenameTests(unittest.TestCase):
    def test_parses_key_before_bpm_and_layer_suffix(self):
        parsed = parse_layer_filename("A#m NOSL33P 144 +NRGY_L7.mp3")
        self.assertEqual(parsed.key, "A#")
        self.assertEqual(parsed.mode, "minor")
        self.assertEqual(parsed.bpm, 144)
        self.assertEqual(parsed.layer_index, 7)
        self.assertEqual(parsed.source_stem, "A#m NOSL33P 144 +NRGY")

    def test_parses_key_after_bpm(self):
        parsed = parse_layer_filename("FLEXOR 136 C# minor XT_L12.wav")
        self.assertEqual(parsed.key, "C#")
        self.assertEqual(parsed.mode, "minor")
        self.assertEqual(parsed.bpm, 136)
        self.assertEqual(parsed.layer_index, 12)

    def test_parses_compact_major_and_naked_key_near_bpm(self):
        explicit = parse_layer_filename("Night 92 Fmaj Layer 2.aiff")
        self.assertEqual((explicit.key, explicit.mode), ("F", "major"))
        naked = parse_layer_filename("Night 92 Bb - L3.flac")
        self.assertEqual((naked.key, naked.mode), ("Bb", "major"))

    def test_does_not_treat_words_as_keys(self):
        parsed = parse_layer_filename("FREAK 130 XT_L1.mp3")
        self.assertIsNone(parsed.key)
        self.assertEqual(parsed.bpm, 130)


class LayerLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = self.root / "library"
        self.state = self.root / "state"
        self.library.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_taxonomy_is_exact_and_unreviewed_is_not_a_category(self):
        self.assertEqual(len(TAXONOMY), 19)
        self.assertEqual(len(set(TAXONOMY)), 19)
        self.assertNotIn("Unreviewed", TAXONOMY)
        self.assertEqual(
            AUDIO_EXTENSIONS,
            {".mp3", ".wav", ".flac", ".aif", ".aiff", ".m4a"},
        )

    def test_recursive_scan_is_deterministic_read_only_and_groups_siblings(self):
        first = self.library / "B Folder" / "A#m LOOP 144 XT_L2.wav"
        second = self.library / "B Folder" / "A#m LOOP 144 XT_L1.WAV"
        _write_wave(first)
        _write_wave(second, frames=4000)
        (self.library / "ignore.txt").write_text("not audio", encoding="utf-8")
        before = {
            path.relative_to(self.library).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
            for path in self.library.rglob("*")
            if path.is_file()
        }

        result = LayerLibrary(self.library, self.state / "cache.sqlite").scan()

        self.assertEqual(
            [record.relative_path for record in result.records],
            [
                "B Folder/A#m LOOP 144 XT_L1.WAV",
                "B Folder/A#m LOOP 144 XT_L2.wav",
            ],
        )
        self.assertEqual(result.inventory_count, 2)
        self.assertEqual(result.hashed_count, 2)
        self.assertEqual(result.cached_count, 0)
        self.assertTrue(all(record.effective_label is None for record in result.records))
        self.assertTrue(all(record.review_status == "Unreviewed" for record in result.records))
        self.assertEqual(result.records[0].source_loop_id, result.records[1].source_loop_id)
        self.assertAlmostEqual(result.records[0].duration_seconds, 0.5)
        self.assertAlmostEqual(result.records[1].duration_seconds, 1.0)
        after = {
            path.relative_to(self.library).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
            for path in self.library.rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)
        self.assertFalse((self.library / "cache.sqlite").exists())

    def test_cache_reuses_metadata_and_classifier_by_version(self):
        audio = self.library / "A#m LOOP 144 XT_L1.wav"
        _write_wave(audio)
        classifier = _Classifier()
        scanner = LayerLibrary(
            self.library,
            self.state / "cache.sqlite",
            classifier=classifier,
        )
        first = scanner.scan()
        second = scanner.scan()

        self.assertEqual(classifier.calls, ["A#m LOOP 144 XT_L1.wav"])
        self.assertEqual(first.classified_count, 1)
        self.assertEqual(second.classified_count, 0)
        self.assertEqual(second.cached_count, 1)
        self.assertEqual(second.records[0].effective_label, "Lead")
        self.assertEqual(second.records[0].label_source, "prediction")

    def test_optional_batch_classifier_uses_aligned_conservative_chunks(self):
        for index in range(7):
            _write_wave(
                self.library / f"A#m LOOP {index} 144 XT_L1.wav",
                frames=8000 + index,
            )
        classifier = _BatchClassifier()

        result = LayerLibrary(
            self.library,
            self.state / "cache.sqlite",
            classifier=classifier,
        ).scan()

        self.assertEqual([len(call) for call in classifier.batch_calls], [3, 3, 1])
        self.assertEqual(classifier.calls, [])
        self.assertEqual(result.classified_count, 7)
        self.assertEqual(len(result.records), 7)
        self.assertTrue(all(record.effective_label == "Lead" for record in result.records))

    def test_batch_failure_retries_individually_without_losing_layers(self):
        for index in range(3):
            _write_wave(
                self.library / f"A#m LOOP {index} 144 XT_L1.wav",
                frames=8000 + index,
            )

        class BrokenBatchClassifier(_BatchClassifier):
            def predict_many(self, items):
                self.batch_calls.append(
                    [metadata.relative_path for _path, metadata in items]
                )
                raise RuntimeError("batch transport failed")

        classifier = BrokenBatchClassifier()
        result = LayerLibrary(
            self.library,
            self.state / "cache.sqlite",
            classifier=classifier,
        ).scan()

        self.assertEqual([len(call) for call in classifier.batch_calls], [3])
        self.assertEqual(len(classifier.calls), 3)
        self.assertEqual(result.classified_count, 3)
        self.assertEqual(len(result.records), 3)
        self.assertEqual(result.issues, ())

    def test_cancel_during_batch_discards_the_whole_unsaved_chunk(self):
        for index in range(3):
            _write_wave(
                self.library / f"A#m LOOP {index} 144 XT_L1.wav",
                frames=8000 + index,
            )
        token = CancelToken()

        class CancellingBatchClassifier(_BatchClassifier):
            def predict_many(self, items):
                predictions = super().predict_many(items)
                token.cancel()
                return predictions

        result = LayerLibrary(
            self.library,
            self.state / "cache.sqlite",
            classifier=CancellingBatchClassifier(),
        ).scan(cancel=token)

        self.assertTrue(result.cancelled)
        self.assertEqual(result.records, ())
        self.assertEqual(result.classified_count, 0)
        with closing(sqlite3.connect(self.state / "cache.sqlite")) as connection, connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM layer_cache").fetchone()[0],
                0,
            )

    def test_relocated_identical_audio_reuses_duration_and_prediction_by_hash(self):
        audio = self.library / "A#m LOOP 144 XT_L1.wav"
        _write_wave(audio)
        cache = self.state / "cache.sqlite"
        classifier = _Classifier()
        duration_calls: list[str] = []

        def duration_reader(path):
            duration_calls.append(path.name)
            return 1.0

        first = LayerLibrary(
            self.library,
            cache,
            classifier=classifier,
            duration_reader=duration_reader,
        ).scan()
        relocated = self.root / "relocated-library"
        relocated.mkdir()
        relocated_audio = relocated / "C#m RENAMED 150 XT_L7.wav"
        shutil.copy2(audio, relocated_audio)

        second = LayerLibrary(
            relocated,
            cache,
            classifier=classifier,
            duration_reader=duration_reader,
        ).scan()

        self.assertEqual(first.classified_count, 1)
        self.assertEqual(second.hashed_count, 1)
        self.assertEqual(second.classified_count, 0)
        self.assertEqual(classifier.calls, ["A#m LOOP 144 XT_L1.wav"])
        self.assertEqual(duration_calls, ["A#m LOOP 144 XT_L1.wav"])
        self.assertEqual(second.records[0].effective_label, "Lead")
        self.assertEqual(second.records[0].duration_seconds, 1.0)

    def test_relocated_identical_audio_reuses_key_confidence_by_hash(self):
        audio = self.library / "Am CHANCE 140 +NRGY_L1.wav"
        _write_wave(audio)
        cache = self.state / "cache.sqlite"
        inventory = self.root / "inventory.json"
        results = self.root / "results.json"
        inventory.write_text(
            json.dumps(
                {
                    "layers_root": str(self.library),
                    "entries": [
                        {
                            "source_loop_id": "chance 140 +nrgy",
                            "layer_source_stems": ["Am CHANCE 140 +NRGY"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        results.write_text(
            json.dumps(
                {
                    "scanner_id": "test-key-engine",
                    "results": [
                        {
                            "source_loop_id": "chance 140 +nrgy",
                            "status": "success",
                            "top1_key": "Am",
                            "top1_probability": 0.62,
                            "top2_key": "Dm",
                            "top2_probability": 0.18,
                            "top1_top2_margin": 0.44,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        index = KeyConfidenceIndex.from_files(
            library_root=self.library,
            inventory_path=inventory,
            results_path=results,
        )
        first = LayerLibrary(
            self.library,
            cache,
            key_confidence_index=index,
        ).scan()
        self.assertEqual(first.records[0].key_confidence_status, "safe")

        relocated = self.root / "relocated-library"
        relocated.mkdir()
        shutil.copy2(audio, relocated / audio.name)
        inherited = LayerLibrary(relocated, cache).scan().records[0]

        self.assertEqual(inherited.key_confidence_status, "safe")
        self.assertEqual(inherited.scanned_key, "A")
        self.assertEqual(inherited.alternate_scanned_key, "D")
        self.assertAlmostEqual(inherited.key_top2_probability, 0.18)
        self.assertEqual(inherited.key_analyzer_id, "test-key-engine")

        renamed = self.root / "renamed-library"
        renamed.mkdir()
        shutil.copy2(audio, renamed / "F#m RENAMED 140 +NRGY_L1.wav")
        conflicting = LayerLibrary(renamed, cache).scan().records[0]

        self.assertEqual(conflicting.scanned_key, "A")
        self.assertEqual(conflicting.key_confidence_status, "conflict")

    def test_warm_cached_path_backfills_key_confidence_from_identical_audio(self):
        current_audio = self.library / "Am CHANCE 140 +NRGY_L1.wav"
        _write_wave(current_audio)
        cache = self.state / "cache.sqlite"
        initial = LayerLibrary(self.library, cache).scan()
        self.assertEqual(initial.records[0].key_confidence_status, "unavailable")

        analyzed = self.root / "analyzed-library"
        analyzed.mkdir()
        analyzed_audio = analyzed / current_audio.name
        shutil.copy2(current_audio, analyzed_audio)
        inventory = self.root / "analyzed-inventory.json"
        results = self.root / "analyzed-results.json"
        inventory.write_text(
            json.dumps(
                {
                    "layers_root": str(analyzed),
                    "entries": [
                        {
                            "source_loop_id": "chance 140 +nrgy",
                            "layer_source_stems": ["Am CHANCE 140 +NRGY"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        results.write_text(
            json.dumps(
                {
                    "scanner_id": "test-key-engine",
                    "results": [
                        {
                            "source_loop_id": "chance 140 +nrgy",
                            "status": "success",
                            "top1_key": "Am",
                            "top1_probability": 0.62,
                            "top2_key": "Dm",
                            "top2_probability": 0.18,
                            "top1_top2_margin": 0.44,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        index = KeyConfidenceIndex.from_files(
            library_root=analyzed,
            inventory_path=inventory,
            results_path=results,
        )
        LayerLibrary(analyzed, cache, key_confidence_index=index).scan()

        hydrated = LayerLibrary(self.library, cache).scan()

        self.assertEqual(hydrated.cached_count, 1)
        self.assertEqual(hydrated.records[0].key_confidence_status, "safe")
        self.assertEqual(hydrated.records[0].scanned_key, "A")
        self.assertEqual(hydrated.records[0].alternate_scanned_key, "D")

    def test_identical_content_is_classified_once_during_first_scan(self):
        first_audio = self.library / "A#m FIRST 144 XT_L1.wav"
        second_audio = self.library / "A#m SECOND 144 XT_L1.wav"
        _write_wave(first_audio)
        shutil.copy2(first_audio, second_audio)
        classifier = _Classifier()

        result = LayerLibrary(
            self.library,
            self.state / "cache.sqlite",
            classifier=classifier,
        ).scan()

        self.assertEqual(result.hashed_count, 2)
        self.assertEqual(result.classified_count, 1)
        self.assertEqual(classifier.calls, [first_audio.name])
        self.assertEqual(
            [record.effective_label for record in result.records],
            ["Lead", "Lead"],
        )

    def test_relocated_hash_cache_respects_classifier_version(self):
        audio = self.library / "A#m LOOP 144 XT_L1.wav"
        _write_wave(audio)
        cache = self.state / "cache.sqlite"
        first_classifier = _Classifier()
        LayerLibrary(self.library, cache, classifier=first_classifier).scan()

        relocated = self.root / "relocated-library"
        relocated.mkdir()
        shutil.copy2(audio, relocated / audio.name)
        second_classifier = _Classifier()
        second_classifier.classifier_id = "fake-v2"

        result = LayerLibrary(
            relocated,
            cache,
            classifier=second_classifier,
        ).scan()
        matching_classifier = _Classifier()
        matching_classifier.classifier_id = "fake-v2"
        reused = LayerLibrary(
            self.library,
            cache,
            classifier=matching_classifier,
        ).scan()

        self.assertEqual(result.classified_count, 1)
        self.assertEqual(second_classifier.calls, [audio.name])
        self.assertEqual(reused.classified_count, 0)
        self.assertEqual(matching_classifier.calls, [])

    def test_classifier_version_change_invalidates_once_then_reuses_cache(self):
        audio = self.library / "A#m LOOP 144 XT_L1.wav"
        _write_wave(audio)
        cache = self.state / "cache.sqlite"
        first_classifier = _Classifier()
        first = LayerLibrary(
            self.library,
            cache,
            classifier=first_classifier,
        ).scan()

        second_classifier = _Classifier()
        second_classifier.classifier_id = "fake-v2"
        scanner = LayerLibrary(
            self.library,
            cache,
            classifier=second_classifier,
        )
        second = scanner.scan()
        third = scanner.scan()

        self.assertEqual(first.classified_count, 1)
        self.assertEqual(second.classified_count, 1)
        self.assertEqual(third.classified_count, 0)
        self.assertEqual(first_classifier.calls, ["A#m LOOP 144 XT_L1.wav"])
        self.assertEqual(second_classifier.calls, ["A#m LOOP 144 XT_L1.wav"])

    def test_scan_without_classifier_preserves_cached_prediction(self):
        audio = self.library / "A#m LOOP 144 XT_L1.wav"
        _write_wave(audio)
        cache = self.state / "cache.sqlite"
        classifier = _Classifier()
        LayerLibrary(
            self.library,
            cache,
            classifier=classifier,
        ).scan()

        restored = LayerLibrary(self.library, cache).scan()

        self.assertEqual(restored.classified_count, 0)
        self.assertEqual(restored.records[0].predicted_label, "Lead")
        self.assertEqual(restored.records[0].prediction_confidence, 0.8)
        with closing(sqlite3.connect(cache)) as connection, connection:
            row = connection.execute(
                "SELECT predicted_label, classifier_id FROM layer_cache"
            ).fetchone()
        self.assertEqual(row, ("Lead", "fake-v1"))

    def test_cache_only_scan_preserves_precomputed_key_metadata(self):
        audio = self.library / "A#m LOOP 144 XT_L1.wav"
        _write_wave(audio)
        cache = self.state / "cache.sqlite"
        LayerLibrary(self.library, cache).scan()
        with closing(sqlite3.connect(cache)) as connection, connection:
            connection.execute(
                """UPDATE layer_cache
                   SET scanned_key = 'A#', scanned_mode = 'minor',
                       key_confidence_margin = 0.42,
                       key_confidence_status = 'safe',
                       key_confidence_source_loop_id = 'loop 144 xt',
                       key_analyzer_id = 'key-test-v1'"""
            )

        restored = LayerLibrary(self.library, cache).scan().records[0]

        self.assertEqual(restored.scanned_key, "A#")
        self.assertEqual(restored.scanned_mode, "minor")
        self.assertEqual(restored.key_confidence_margin, 0.42)
        self.assertEqual(restored.key_confidence_status, "safe")
        self.assertEqual(restored.key_analyzer_id, "key-test-v1")

    def test_cached_library_hydrates_without_touching_audio(self):
        audio = self.library / "A#m LOOP 144 XT_L1.wav"
        _write_wave(audio)
        cache = self.state / "cache.sqlite"
        classifier = _Classifier()
        scanned = LayerLibrary(
            self.library,
            cache,
            classifier=classifier,
        ).scan()

        def forbidden_duration_read(_path):
            raise AssertionError("cached hydration must not read audio")

        restored = LayerLibrary(
            self.library,
            cache,
            duration_reader=forbidden_duration_read,
        ).load_cached()

        self.assertEqual(restored.records, scanned.records)
        self.assertEqual(restored.inventory_count, 1)
        self.assertEqual(restored.cached_count, 1)
        self.assertEqual(restored.hashed_count, 0)
        self.assertEqual(restored.classified_count, 0)
        self.assertEqual(
            most_recent_cached_library_root(cache),
            self.library.resolve(),
        )

    def test_cached_hydration_hides_prediction_from_another_classifier(self):
        audio = self.library / "A#m LOOP 144 XT_L1.wav"
        _write_wave(audio)
        cache = self.state / "cache.sqlite"
        LayerLibrary(self.library, cache, classifier=_Classifier()).scan()
        replacement = _Classifier()
        replacement.classifier_id = "fake-v2"

        restored = LayerLibrary(
            self.library,
            cache,
            classifier=replacement,
            duration_reader=lambda _path: (_ for _ in ()).throw(
                AssertionError("cached hydration must not read audio")
            ),
        ).load_cached()

        self.assertIsNone(restored.records[0].predicted_label)
        self.assertIsNone(restored.records[0].prediction_confidence)
        self.assertEqual(restored.records[0].prediction_scores, {})
        self.assertEqual(restored.unreviewed_count, 1)
        self.assertEqual(
            [issue.code for issue in restored.issues],
            ["stale_classifier_cache"],
        )

    def test_file_change_invalidates_hash_duration_and_prediction(self):
        audio = self.library / "A#m LOOP 144 XT_L1.wav"
        _write_wave(audio)
        classifier = _Classifier()
        scanner = LayerLibrary(
            self.library,
            self.state / "cache.sqlite",
            classifier=classifier,
        )
        first = scanner.scan()
        _write_wave(audio, frames=16000)
        second = scanner.scan()

        self.assertEqual(len(classifier.calls), 2)
        self.assertNotEqual(first.records[0].sha256, second.records[0].sha256)
        self.assertAlmostEqual(second.records[0].duration_seconds, 2.0)
        self.assertEqual(second.hashed_count, 1)

    def test_file_content_change_invalidates_path_bound_manual_label(self):
        audio = self.library / "A#m LOOP 144 XT_L1.wav"
        _write_wave(audio)
        scanner = LayerLibrary(self.library, self.state / "cache.sqlite")
        scanner.scan()
        scanner.set_manual_label(audio, "Bass")
        _write_wave(audio, frames=16000)

        changed = scanner.scan()

        self.assertIsNone(changed.records[0].manual_label)

    def test_user_manual_label_follows_identical_relocated_audio(self):
        audio = self.library / "A#m LOOP 144 XT_L1.wav"
        _write_wave(audio)
        cache = self.state / "cache.sqlite"
        scanner = LayerLibrary(self.library, cache)
        scanner.scan()
        scanner.set_manual_label(audio, "Bass")
        relocated = self.root / "relocated-library"
        relocated.mkdir()
        shutil.copy2(audio, relocated / "renamed.wav")

        result = LayerLibrary(relocated, cache).scan()

        self.assertEqual(result.records[0].manual_label, "Bass")
        self.assertEqual(result.records[0].label_source, "manual")

    def test_cache_inside_library_is_rejected(self):
        with self.assertRaises(CacheInsideLibraryError):
            LayerLibrary(self.library, self.library / ".cache.sqlite")

    def test_truth_csv_matches_relocated_audio_by_hash_and_wins_prediction(self):
        audio = self.library / "relocated" / "renamed.wav"
        _write_wave(audio)
        truth_path = self.root / "truth.csv"
        with truth_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["audio_path", "file", "label", "source", "sha256"],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "audio_path": "/old/location/original.wav",
                    "file": "original.wav",
                    "label": "Bass",
                    "source": "TRUTH LOOP 140",
                    "sha256": _sha256(audio),
                }
            )
        classifier = _Classifier()

        result = LayerLibrary(
            self.library,
            self.state / "cache.sqlite",
            classifier=classifier,
            truth_csv_path=truth_path,
        ).scan()

        record = result.records[0]
        self.assertEqual(record.manual_label, "Bass")
        self.assertEqual(record.effective_label, "Bass")
        self.assertEqual(record.label_source, "manual")
        self.assertEqual(record.source_loop_id, "TRUTH LOOP 140")
        self.assertEqual(classifier.calls, [])

    def test_truth_csv_filename_fallback_requires_unique_library_filename(self):
        _write_wave(self.library / "one" / "same.wav")
        _write_wave(self.library / "two" / "same.wav")
        truth_path = self.root / "truth.csv"
        truth_path.write_text("file,label\nsame.wav,Pad\n", encoding="utf-8")

        result = LayerLibrary(
            self.library,
            self.state / "cache.sqlite",
            truth_csv_path=truth_path,
        ).scan()

        self.assertEqual([record.manual_label for record in result.records], [None, None])

    def test_semicolon_user_truth_csv_matches_current_corpus_schema(self):
        audio = self.library / "A#m LOOP 144 XT_L1.wav"
        _write_wave(audio)
        truth_path = self.root / "truth-semicolon.csv"
        truth_path.write_text(
            "source;layer;file;user_truth;user_notes\n"
            "LOOP 144;1;A#m LOOP 144 XT_L1.wav;Bass;verified\n",
            encoding="utf-8-sig",
        )

        result = LayerLibrary(
            self.library,
            self.state / "cache.sqlite",
            truth_csv_path=truth_path,
        ).scan()

        self.assertEqual(result.records[0].manual_label, "Bass")
        self.assertEqual(result.records[0].source_loop_id, "LOOP 144")

    def test_stale_truth_path_with_different_hash_does_not_label_new_content(self):
        audio = self.library / "same-path.wav"
        _write_wave(audio, frames=4000)
        old_hash = _sha256(audio)
        _write_wave(audio, frames=8000)
        truth_path = self.root / "truth.csv"
        with truth_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["audio_path", "label", "sha256"])
            writer.writeheader()
            writer.writerow(
                {"audio_path": audio, "label": "Bass", "sha256": old_hash}
            )

        result = LayerLibrary(
            self.library,
            self.state / "cache.sqlite",
            truth_csv_path=truth_path,
        ).scan()

        self.assertIsNone(result.records[0].manual_label)

    def test_user_manual_truth_outweighs_csv_on_rescan(self):
        audio = self.library / "A#m LOOP 144 XT_L1.wav"
        _write_wave(audio)
        truth_path = self.root / "truth.csv"
        truth_path.write_text(
            "audio_path,label\n" + f"{audio},Bass\n",
            encoding="utf-8",
        )
        scanner = LayerLibrary(
            self.library,
            self.state / "cache.sqlite",
            truth_csv_path=truth_path,
        )
        scanner.scan()
        scanner.set_manual_label(audio, "Pluck")
        result = scanner.scan()

        self.assertEqual(result.records[0].manual_label, "Pluck")
        self.assertEqual(result.records[0].effective_label, "Pluck")

    def test_manual_label_validation_and_unknown_path(self):
        audio = self.library / "loop.wav"
        _write_wave(audio)
        scanner = LayerLibrary(self.library, self.state / "cache.sqlite")
        scanner.scan()
        with self.assertRaises(ValueError):
            scanner.set_manual_label(audio, "Not a category")
        with self.assertRaises(UnknownLayerError):
            scanner.set_manual_label(self.library / "missing.wav", "Lead")

    def test_invalid_truth_category_is_rejected(self):
        _write_wave(self.library / "loop.wav")
        truth_path = self.root / "truth.csv"
        truth_path.write_text("file,label\nloop.wav,Other\n", encoding="utf-8")
        scanner = LayerLibrary(
            self.library,
            self.state / "cache.sqlite",
            truth_csv_path=truth_path,
        )
        with self.assertRaises(TruthCSVError):
            scanner.scan()

    def test_progress_cancel_and_serialization(self):
        for index in range(3):
            _write_wave(self.library / f"Loop 140 C_L{index + 1}.wav")
        events = []
        token = CancelToken()

        def on_progress(event):
            events.append(event)
            if event.phase == "metadata" and event.completed == 1:
                token.cancel()

        result = LayerLibrary(self.library, self.state / "cache.sqlite").scan(
            progress=on_progress,
            cancel=token,
        )

        self.assertTrue(result.cancelled)
        self.assertEqual(len(result.records), 1)
        self.assertEqual(events[-1].phase, "cancelled")
        payload = result.records[0].to_dict()
        restored = LayerRecord.from_dict(json.loads(json.dumps(payload)))
        self.assertEqual(restored, result.records[0])

    def test_cancel_requested_during_classification_does_not_save_partial_record(self):
        audio = self.library / "Loop 140 C_L1.wav"
        _write_wave(audio)
        token = CancelToken()
        events = []

        class CancellingClassifier(_Classifier):
            def predict(self, path, metadata):
                prediction = super().predict(path, metadata)
                token.cancel()
                return prediction

        result = LayerLibrary(
            self.library,
            self.state / "cache.sqlite",
            classifier=CancellingClassifier(),
        ).scan(progress=events.append, cancel=token)

        self.assertTrue(result.cancelled)
        self.assertEqual(result.records, ())
        self.assertEqual(result.classified_count, 0)
        self.assertEqual(events[-1].phase, "cancelled")

    def test_cache_schema_is_versioned(self):
        _write_wave(self.library / "loop.wav")
        cache = self.state / "cache.sqlite"
        LayerLibrary(self.library, cache).scan()
        with closing(sqlite3.connect(cache)) as connection, connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(version, 3)

    def test_cached_library_backfills_top_two_without_reading_audio(self):
        audio = self.library / "Am CHANCE 140 +NRGY_L1.wav"
        _write_wave(audio)
        cache = self.state / "cache.sqlite"
        first = LayerLibrary(self.library, cache).scan()
        self.assertEqual(len(first.records), 1)

        inventory = self.root / "inventory.json"
        results = self.root / "results.json"
        inventory.write_text(
            json.dumps(
                {
                    "layers_root": str(self.library),
                    "entries": [
                        {
                            "source_loop_id": "chance 140 +nrgy",
                            "layer_source_stems": ["Am CHANCE 140 +NRGY"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        results.write_text(
            json.dumps(
                {
                    "scanner_id": "test-key-engine",
                    "results": [
                        {
                            "source_loop_id": "chance 140 +nrgy",
                            "status": "success",
                            "top1_key": "Am",
                            "top1_probability": 0.62,
                            "top2_key": "Dm",
                            "top2_probability": 0.18,
                            "top1_top2_margin": 0.44,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        index = KeyConfidenceIndex.from_files(
            library_root=self.library,
            inventory_path=inventory,
            results_path=results,
        )

        def forbidden_duration(_path):
            raise AssertionError("load_cached must not read audio")

        restored = LayerLibrary(
            self.library,
            cache,
            key_confidence_index=index,
            duration_reader=forbidden_duration,
        ).load_cached()
        record = restored.records[0]
        self.assertEqual(
            (record.alternate_scanned_key, record.alternate_scanned_mode),
            ("D", "minor"),
        )
        self.assertAlmostEqual(record.key_top2_probability, 0.18)
        with closing(sqlite3.connect(cache)) as connection, connection:
            row = connection.execute(
                """
                SELECT alternate_scanned_key, alternate_scanned_mode,
                       key_top2_probability
                FROM layer_cache
                """
            ).fetchone()
        self.assertEqual(row[:2], ("D", "minor"))
        self.assertAlmostEqual(row[2], 0.18)

    def test_schema_one_cache_is_migrated_without_losing_rows(self):
        self.state.mkdir(exist_ok=True)
        cache = self.state / "cache.sqlite"
        with closing(sqlite3.connect(cache)) as connection, connection:
            connection.execute(
                """
                CREATE TABLE layer_cache (
                    path TEXT PRIMARY KEY,
                    library_root TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    source_loop_id TEXT NOT NULL,
                    layer_index INTEGER,
                    bpm INTEGER,
                    key TEXT,
                    mode TEXT,
                    duration_seconds REAL,
                    byte_size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    predicted_label TEXT,
                    prediction_confidence REAL,
                    prediction_scores_json TEXT NOT NULL DEFAULT '{}',
                    classifier_id TEXT,
                    manual_label TEXT,
                    manual_origin TEXT,
                    updated_at_ns INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO layer_cache (
                    path, library_root, relative_path, filename,
                    source_loop_id, byte_size, sha256, mtime_ns,
                    prediction_scores_json, manual_label, updated_at_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
                """,
                (
                    "/old/layer.wav",
                    str(self.library),
                    "layer.wav",
                    "layer.wav",
                    "old loop",
                    10,
                    "hash",
                    1,
                    "Bass",
                    1,
                ),
            )
            connection.execute("PRAGMA user_version = 1")
        scanner = LayerLibrary(self.library, cache)
        connection = scanner._connect()
        try:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0],
                3,
            )
            row = connection.execute(
                "SELECT manual_label, key_confidence_status FROM layer_cache"
            ).fetchone()
            self.assertEqual(tuple(row), ("Bass", "unavailable"))
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
