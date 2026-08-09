import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mert_client import MertClientError, MertLayerClassifier


class MertClientIdentityTests(unittest.TestCase):
    def _client(self, root: Path, version: str = "model-v1"):
        artifact = root / "model.joblib"
        artifact.write_bytes(b"stable artifact bytes")
        artifact.with_suffix(".json").write_text(
            json.dumps(
                {
                    "version": version,
                    "mert": {
                        "model_id": "test/mert",
                        "revision": "revision-1",
                        "sample_rate": 24000,
                        "max_window_seconds": 15.0,
                        "state_index": 6,
                        "dimension": 2,
                    },
                    "dsp_dimension": 1,
                    "dsp_feature_names": ["test"],
                }
            ),
            encoding="utf-8",
        )
        client = MertLayerClassifier(
            artifact_path=artifact,
            worker_path=root / "worker.py",
            python_executable="python-test",
        )
        expected = f"{version}:{hashlib.sha256(artifact.read_bytes()).hexdigest()[:16]}"
        return client, expected

    def test_cold_packaged_worker_has_a_realistic_startup_ceiling(self):
        with tempfile.TemporaryDirectory() as temporary:
            client, _ = self._client(Path(temporary))
            self.assertEqual(client.startup_timeout, 300.0)

    def test_packaged_worker_mode_reenters_the_application_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client, _ = self._client(root)
            client.frozen_worker_mode = True
            process = MagicMock()
            process.poll.return_value = None
            ready = {
                "event": "ready",
                "model_version": "model-v1",
                "feature_extractor_id": client.feature_extractor_id,
                "feature_dimension": 3,
                "head_id": client.head_id,
            }
            with (
                patch("mert_client.subprocess.Popen", return_value=process) as popen,
                patch.object(client, "_readline", return_value=json.dumps(ready)),
            ):
                client.start()
                command = popen.call_args.args[0]
                self.assertEqual(command[:2], ["python-test", "--mert-worker"])
                self.assertNotIn("-u", command)
                client.stop(force=True)

    def test_worker_start_does_not_change_cache_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            client, expected = self._client(Path(temporary))
            process = MagicMock()
            process.poll.return_value = None
            with (
                patch("mert_client.subprocess.Popen", return_value=process),
                patch.object(
                    client,
                    "_readline",
                    return_value=json.dumps(
                        {"event": "ready", "model_version": "model-v1"}
                    ),
                ),
            ):
                self.assertEqual(client.classifier_id, expected)
                ready = {
                    "event": "ready",
                    "model_version": "model-v1",
                    "feature_extractor_id": client.feature_extractor_id,
                    "feature_dimension": 3,
                    "head_id": client.head_id,
                }
                client._readline.return_value = json.dumps(ready)
                client.start()
                self.assertEqual(client.classifier_id, expected)
                client.stop(force=True)

    def test_worker_version_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            client, _ = self._client(Path(temporary))
            process = MagicMock()
            process.poll.return_value = None
            with (
                patch("mert_client.subprocess.Popen", return_value=process),
                patch.object(
                    client,
                    "_readline",
                    return_value=json.dumps(
                        {
                            "event": "ready",
                            "model_version": "other-model",
                            "feature_extractor_id": client.feature_extractor_id,
                            "feature_dimension": 3,
                            "head_id": client.head_id,
                        }
                    ),
                ),
            ):
                with self.assertRaises(MertClientError):
                    client.start()

    def test_missing_sidecar_fallback_identity_tracks_artifact_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "model.joblib"
            artifact.write_bytes(b"head one")
            first = MertLayerClassifier(
                artifact_path=artifact,
                worker_path=root / "worker.py",
                python_executable="python-test",
            )
            artifact.write_bytes(b"head two")
            second = MertLayerClassifier(
                artifact_path=artifact,
                worker_path=root / "worker.py",
                python_executable="python-test",
            )
            self.assertNotEqual(first.classifier_id, second.classifier_id)

    def test_predict_many_preserves_request_order_and_scores(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client, _ = self._client(root)
            paths = [root / "one.wav", root / "two.wav"]
            for path in paths:
                path.write_bytes(b"audio")
            results = [
                {
                    "path": str(path.resolve()),
                    "prediction": "Lead",
                    "score": 0.8 - index * 0.1,
                    "alternatives": [{"label": "Pluck", "score": 0.2}],
                }
                for index, path in enumerate(paths)
            ]
            with patch.object(
                client,
                "_request",
                return_value={"results": results},
            ) as request:
                predictions = client.predict_many(
                    [
                        (
                            path,
                            SimpleNamespace(sha256=str(index + 1) * 64),
                        )
                        for index, path in enumerate(paths)
                    ]
                )

            request.assert_called_once_with(
                "classify_many",
                items=[
                    {"path": str(paths[0].resolve()), "sha256": "1" * 64},
                    {"path": str(paths[1].resolve()), "sha256": "2" * 64},
                ],
            )
            self.assertEqual([item.label for item in predictions], ["Lead", "Lead"])
            self.assertAlmostEqual(predictions[0].confidence, 0.8)
            self.assertAlmostEqual(predictions[1].confidence, 0.7)
            self.assertEqual(predictions[0].scores, {"Lead": 0.8, "Pluck": 0.2})

    def test_predict_many_rejects_misaligned_paths_and_resets_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client, _ = self._client(root)
            first = root / "one.wav"
            second = root / "two.wav"
            first.write_bytes(b"audio")
            second.write_bytes(b"audio")
            response = {
                "results": [
                    {
                        "path": str(second.resolve()),
                        "prediction": "Lead",
                        "score": 0.8,
                        "alternatives": [],
                    },
                    {
                        "path": str(first.resolve()),
                        "prediction": "Lead",
                        "score": 0.8,
                        "alternatives": [],
                    },
                ]
            }
            with (
                patch.object(client, "_request", return_value=response),
                patch.object(client, "stop") as stop,
            ):
                with self.assertRaises(MertClientError):
                    client.predict_many(
                        [
                            (first, SimpleNamespace(sha256="1" * 64)),
                            (second, SimpleNamespace(sha256="2" * 64)),
                        ]
                    )
            stop.assert_called_once_with(force=True)

    def test_predict_passes_exact_metadata_sha256(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client, _ = self._client(root)
            path = root / "one.wav"
            path.write_bytes(b"audio")
            result = {
                "prediction": "Lead",
                "score": 0.8,
                "alternatives": [],
            }
            with patch.object(
                client,
                "_request",
                return_value={"result": result},
            ) as request:
                client.predict(path, SimpleNamespace(sha256="a" * 64))
            request.assert_called_once_with(
                "classify",
                path=str(path.resolve()),
                sha256="a" * 64,
            )


if __name__ == "__main__":
    unittest.main()
