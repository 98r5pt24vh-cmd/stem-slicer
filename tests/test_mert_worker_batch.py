import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import torch

import mert_worker


class _Processor:
    def __call__(
        self,
        chunks,
        *,
        sampling_rate,
        return_tensors,
        padding,
        return_attention_mask,
    ):
        del sampling_rate, return_tensors, padding, return_attention_mask
        maximum = max(len(chunk) for chunk in chunks)
        values = torch.zeros((len(chunks), maximum), dtype=torch.float32)
        mask = torch.zeros((len(chunks), maximum), dtype=torch.long)
        for index, chunk in enumerate(chunks):
            size = len(chunk)
            values[index, :size] = torch.as_tensor(chunk)
            mask[index, :size] = 1
        return {"input_values": values, "attention_mask": mask}


class _Mert:
    def __init__(self):
        self.received_attention_mask = None
        self.received_shapes = []

    def __call__(self, input_values, *, attention_mask, output_hidden_states):
        self.received_attention_mask = attention_mask.clone()
        self.received_shapes.append(tuple(input_values.shape))
        self.assert_output_hidden_states = output_hidden_states
        state = torch.stack((input_values, input_values * 2.0), dim=-1)
        return SimpleNamespace(hidden_states=(state,))

    def _get_feature_vector_attention_mask(self, length, attention_mask):
        return attention_mask[:, :length].bool()


class MertWorkerBatchTests(unittest.TestCase):
    def _runtime(self):
        runtime = object.__new__(mert_worker.Runtime)
        runtime.metadata = {
            "version": "test-v1",
            "mert": {"state_index": 0, "dimension": 2},
        }
        runtime.device = torch.device("cpu")
        runtime.processor = _Processor()
        runtime.mert = _Mert()
        return runtime

    def test_parallel_dsp_preserves_input_order_and_values(self):
        audios = [
            np.asarray([3.0], dtype=np.float32),
            np.asarray([1.0], dtype=np.float32),
            np.asarray([2.0], dtype=np.float32),
        ]

        def fake_features(audio):
            return np.full(64, audio[0], dtype=np.float32)

        with patch.object(mert_worker, "dsp_features", side_effect=fake_features):
            sequential = mert_worker.dsp_features_many(audios, max_workers=1)
            parallel = mert_worker.dsp_features_many(audios, max_workers=3)

        np.testing.assert_array_equal(parallel, sequential)
        self.assertEqual(parallel[:, 0].tolist(), [3.0, 1.0, 2.0])

    def test_different_sample_lengths_are_never_padded_together(self):
        runtime = self._runtime()
        audios = [
            np.asarray([1.0, 3.0], dtype=np.float32),
            np.asarray([2.0, 4.0, 6.0, 8.0], dtype=np.float32),
        ]

        features = runtime.mert_features_many(audios, window_batch_size=2)

        np.testing.assert_allclose(
            features,
            np.asarray([[2.0, 4.0], [5.0, 10.0]], dtype=np.float32),
        )
        self.assertEqual(runtime.mert.received_shapes, [(1, 2), (1, 4)])
        self.assertEqual(runtime.mert.received_attention_mask.tolist(), [[1, 1, 1, 1]])

    def test_single_and_batched_feature_paths_are_equivalent(self):
        audio = np.asarray([1.0, 3.0, 5.0], dtype=np.float32)
        single_runtime = self._runtime()
        batch_runtime = self._runtime()

        single = single_runtime.mert_features(audio)
        batched = batch_runtime.mert_features_many(
            [audio, audio.copy()],
            window_batch_size=2,
        )

        np.testing.assert_allclose(batched[0], single)
        np.testing.assert_allclose(batched[1], single)
        self.assertEqual(batch_runtime.mert.received_shapes, [(2, 3)])

    def test_exact_length_buckets_preserve_original_audio_order(self):
        runtime = self._runtime()
        audios = [
            np.asarray([1.0, 3.0], dtype=np.float32),
            np.asarray([2.0, 4.0, 6.0], dtype=np.float32),
            np.asarray([5.0, 7.0], dtype=np.float32),
            np.asarray([8.0, 10.0, 12.0], dtype=np.float32),
        ]

        features = runtime.mert_features_many(audios, window_batch_size=4)

        np.testing.assert_allclose(
            features,
            np.asarray(
                [[2.0, 4.0], [4.0, 8.0], [6.0, 12.0], [10.0, 20.0]],
                dtype=np.float32,
            ),
        )
        self.assertEqual(runtime.mert.received_shapes, [(2, 2), (2, 3)])

    def test_classify_many_returns_results_in_input_order(self):
        runtime = self._runtime()
        runtime.feature_extractor_id = "test-extractor"
        runtime.feature_dimension = 3
        runtime.head_id = "test-head"
        classifier = MagicMock()
        classifier.classes_ = np.asarray(["Lead", "Pluck"])
        classifier.predict_proba.side_effect = [
            np.asarray([[0.9, 0.1]], dtype=np.float32),
            np.asarray([[0.2, 0.8]], dtype=np.float32),
        ]
        runtime.classifier = classifier
        runtime.feature_vectors_many = MagicMock(
            return_value=(
                np.asarray(
                    [[1.0, 2.0, 5.0], [3.0, 4.0, 6.0]],
                    dtype=np.float32,
                ),
                (False, True),
            )
        )
        paths = [Path("/tmp/first.wav"), Path("/tmp/second.wav")]
        hashes = ["1" * 64, "2" * 64]

        results = runtime.classify_many(
            paths,
            hashes,
            window_batch_size=2,
        )

        self.assertEqual([item["path"] for item in results], [str(path) for path in paths])
        self.assertEqual(
            [item["prediction"] for item in results],
            ["Lead", "Pluck"],
        )
        self.assertEqual(classifier.predict_proba.call_count, 2)
        self.assertEqual(
            [item["feature_cache_hit"] for item in results],
            [False, True],
        )

    def test_encoder_is_truncated_exactly_at_artifact_state(self):
        model = SimpleNamespace(
            encoder=SimpleNamespace(
                layers=torch.nn.ModuleList(
                    [torch.nn.Identity() for _index in range(12)]
                )
            )
        )

        mert_worker._truncate_encoder_for_state(model, 6)

        self.assertEqual(len(model.encoder.layers), 6)

    def test_invalid_encoder_state_is_rejected(self):
        model = SimpleNamespace(
            encoder=SimpleNamespace(
                layers=torch.nn.ModuleList([torch.nn.Identity()])
            )
        )

        with self.assertRaises(RuntimeError):
            mert_worker._truncate_encoder_for_state(model, 2)


if __name__ == "__main__":
    unittest.main()
