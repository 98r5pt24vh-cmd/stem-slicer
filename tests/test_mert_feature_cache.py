import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock

import numpy as np

import mert_worker
from mert_feature_cache import (
    FEATURE_DTYPE,
    MertFeatureCache,
    derive_feature_extractor_id,
)


class _Head:
    classes_ = np.asarray(["Lead", "Pluck"])

    def __init__(self, *, invert: bool = False) -> None:
        self.invert = invert

    def predict_proba(self, values):
        choose_lead = float(values[0, 0]) < 5.0
        if self.invert:
            choose_lead = not choose_lead
        if choose_lead:
            return np.asarray([[0.9, 0.1]], dtype=np.float64)
        return np.asarray([[0.1, 0.9]], dtype=np.float64)


def _runtime(
    cache_path: Path,
    *,
    extractor_id: str = "extractor-v1",
    head_id: str = "head-v1",
    invert: bool = False,
):
    runtime = object.__new__(mert_worker.Runtime)
    runtime.metadata = {
        "version": head_id,
        "mert": {"state_index": 0, "dimension": 2},
        "dsp_dimension": 1,
    }
    runtime.feature_extractor_id = extractor_id
    runtime.feature_dimension = 3
    runtime.head_id = head_id
    runtime.feature_cache = MertFeatureCache(cache_path)
    runtime.classifier = _Head(invert=invert)
    runtime._extract_feature_vectors = MagicMock()
    return runtime


class MertFeatureCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.cache_path = self.root / "features.sqlite3"

    def tearDown(self):
        self.temporary.cleanup()

    def test_cache_hit_skips_audio_feature_extraction(self):
        runtime = _runtime(self.cache_path)
        vector = np.asarray([1.0, 2.0, 3.0], dtype=np.float32)
        runtime.feature_cache.put_many(
            [("a" * 64, runtime.feature_extractor_id, vector)],
            expected_dimension=3,
        )

        results = runtime.classify_many(
            [self.root / "missing-audio-is-not-opened.wav"],
            ["a" * 64],
            window_batch_size=4,
        )

        runtime._extract_feature_vectors.assert_not_called()
        self.assertEqual(results[0]["prediction"], "Lead")
        self.assertTrue(results[0]["feature_cache_hit"])
        runtime.feature_cache.close()

    def test_new_head_reuses_features_and_only_reruns_sklearn(self):
        first = _runtime(self.cache_path, head_id="head-one")
        first._extract_feature_vectors.return_value = np.asarray(
            [[1.0, 2.0, 3.0]], dtype=np.float32
        )
        first_result = first.classify_many(
            [self.root / "audio.wav"],
            ["b" * 64],
            window_batch_size=4,
        )
        first.feature_cache.close()

        second = _runtime(
            self.cache_path,
            head_id="head-two",
            invert=True,
        )
        second_result = second.classify_many(
            [self.root / "audio.wav"],
            ["b" * 64],
            window_batch_size=4,
        )

        self.assertEqual(first_result[0]["prediction"], "Lead")
        self.assertEqual(second_result[0]["prediction"], "Pluck")
        second._extract_feature_vectors.assert_not_called()
        self.assertTrue(second_result[0]["feature_cache_hit"])
        second.feature_cache.close()

    def test_sha_and_extractor_identity_both_invalidate(self):
        cache = MertFeatureCache(self.cache_path)
        vector = np.asarray([1.0, 2.0, 3.0], dtype=np.float32)
        cache.put_many(
            [("c" * 64, "extractor-one", vector)],
            expected_dimension=3,
        )

        self.assertIsNotNone(cache.get("c" * 64, "extractor-one", 3))
        self.assertIsNone(cache.get("d" * 64, "extractor-one", 3))
        self.assertIsNone(cache.get("c" * 64, "extractor-two", 3))
        cache.close()

    def test_corrupt_blob_is_rejected_then_safely_recomputed(self):
        runtime = _runtime(self.cache_path)
        original = np.asarray([1.0, 2.0, 3.0], dtype=np.float32)
        runtime.feature_cache.put_many(
            [("e" * 64, runtime.feature_extractor_id, original)],
            expected_dimension=3,
        )
        with closing(sqlite3.connect(self.cache_path)) as connection, connection:
            connection.execute(
                "UPDATE feature_vectors SET vector_sha256 = ?",
                ("0" * 64,),
            )
            connection.commit()
        self.assertIsNone(
            runtime.feature_cache.get(
                "e" * 64,
                runtime.feature_extractor_id,
                3,
            )
        )

        replacement = np.asarray([[6.0, 7.0, 8.0]], dtype=np.float32)
        runtime._extract_feature_vectors.return_value = replacement
        result = runtime.classify_many(
            [self.root / "audio.wav"],
            ["e" * 64],
            window_batch_size=4,
        )

        self.assertEqual(result[0]["prediction"], "Pluck")
        runtime._extract_feature_vectors.assert_called_once()
        np.testing.assert_array_equal(
            runtime.feature_cache.get(
                "e" * 64,
                runtime.feature_extractor_id,
                3,
            ),
            replacement[0],
        )
        runtime.feature_cache.close()

    def test_only_misses_are_batched_and_caller_order_is_restored(self):
        runtime = _runtime(self.cache_path)
        runtime.feature_cache.put_many(
            [
                (
                    "f" * 64,
                    runtime.feature_extractor_id,
                    np.asarray([1.0, 10.0, 11.0], dtype=np.float32),
                )
            ],
            expected_dimension=3,
        )
        paths = [
            self.root / "miss-high.wav",
            self.root / "hit-low.wav",
            self.root / "miss-low.wav",
        ]
        runtime._extract_feature_vectors.return_value = np.asarray(
            [[8.0, 20.0, 21.0], [2.0, 30.0, 31.0]],
            dtype=np.float32,
        )

        results = runtime.classify_many(
            paths,
            ["1" * 64, "f" * 64, "2" * 64],
            window_batch_size=4,
        )

        self.assertEqual(
            runtime._extract_feature_vectors.call_args.args[0],
            [paths[0], paths[2]],
        )
        self.assertEqual(
            [item["path"] for item in results],
            [str(path) for path in paths],
        )
        self.assertEqual(
            [item["prediction"] for item in results],
            ["Pluck", "Lead", "Lead"],
        )
        runtime.feature_cache.close()

    def test_blob_is_raw_little_endian_float32_with_checksum(self):
        cache = MertFeatureCache(self.cache_path)
        vector = np.asarray([1.25, -2.5, 3.75], dtype=np.float64)
        cache.put_many(
            [("3" * 64, "extractor", vector)],
            expected_dimension=3,
        )
        with closing(sqlite3.connect(self.cache_path)) as connection, connection:
            dtype, blob, checksum = connection.execute(
                "SELECT dtype, vector_blob, vector_sha256 FROM feature_vectors"
            ).fetchone()
        expected_blob = np.asarray(vector, dtype=np.dtype("<f4")).tobytes()
        self.assertEqual(dtype, FEATURE_DTYPE)
        self.assertEqual(blob, expected_blob)
        self.assertEqual(checksum, hashlib.sha256(expected_blob).hexdigest())
        cache.close()

    def test_v0_derived_id_ignores_head_and_corpus_metadata(self):
        base = {
            "version": "head-one",
            "mert": {
                "model_id": "m-a-p/MERT-v1-95M",
                "revision": "revision",
                "sample_rate": 24000,
                "max_window_seconds": 15.0,
                "state_index": 6,
                "dimension": 768,
            },
            "dsp_dimension": 64,
            "dsp_feature_names": [f"feature-{index}" for index in range(64)],
            "head": {"C": 0.03},
            "corpus": {"rows": 100},
        }
        changed_head = json.loads(json.dumps(base))
        changed_head["version"] = "head-two"
        changed_head["head"]["C"] = 1.0
        changed_head["corpus"]["rows"] = 999

        self.assertEqual(
            derive_feature_extractor_id(base),
            derive_feature_extractor_id(changed_head),
        )

    def test_v1_explicit_extractor_id_must_match_canonical_spec(self):
        metadata = {
            "mert": {
                "model_id": "m-a-p/MERT-v1-95M",
                "revision": "revision",
                "sample_rate": 24000,
                "max_window_seconds": 15.0,
                "state_index": 6,
                "dimension": 768,
            },
            "dsp_dimension": 64,
            "dsp_feature_names": [f"feature-{index}" for index in range(64)],
        }
        derived = derive_feature_extractor_id(metadata)
        self.assertEqual(
            derive_feature_extractor_id(
                {**metadata, "feature_extractor_id": derived}
            ),
            derived,
        )
        with self.assertRaisesRegex(ValueError, "does not match"):
            derive_feature_extractor_id(
                {**metadata, "feature_extractor_id": "mert-dsp:stale"}
            )


if __name__ == "__main__":
    unittest.main()
