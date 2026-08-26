import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from layer_library import LayerRecord, ScanIssue, ScanProgress, ScanResult
from tools.prefill_runtime_cache import (
    JsonProgressReporter,
    PrefillConfig,
    run_prefill,
    validate_config,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _FakeClassifier:
    classifier_id = "fake-classifier-v1"
    feature_extractor_id = "fake-extractor-v1"
    head_id = "fake-head-v1"

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.stop_called = False

    def stop(self) -> None:
        self.stop_called = True


def _record(*, label: str | None = "Lead") -> LayerRecord:
    return LayerRecord(
        path="/immutable-library/loop_L1.mp3",
        relative_path="loop_L1.mp3",
        filename="loop_L1.mp3",
        source_loop_id="loop",
        layer_index=1,
        bpm=140,
        key="A",
        mode="minor",
        duration_seconds=1.0,
        byte_size=123,
        sha256="a" * 64,
        mtime_ns=1,
        predicted_label=label,
        prediction_confidence=0.9 if label else None,
    )


class PrefillRuntimeCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.library_root = self.root / "library"
        self.library_root.mkdir()
        self.artifact_path = self.root / "layer_roles_v2.joblib"
        artifact_bytes = b"unit-test-v1-artifact"
        self.artifact_path.write_bytes(artifact_bytes)
        self.artifact_path.with_suffix(".json").write_text(
            json.dumps(
                {
                    "schema": "stem-slicer-layer-role-head-v1",
                    "artifact_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def config(self, **overrides) -> PrefillConfig:
        values = {
            "library_root": self.library_root,
            "library_cache_path": self.root / "cache" / "library.sqlite3",
            "feature_cache_path": self.root / "cache" / "features.sqlite3",
            "artifact_path": self.artifact_path,
            "hf_cache_dir": self.root / "hf-cache",
            "device": "cpu",
            "batch_size": 8,
            "window_batch_size": 4,
            "progress_interval_seconds": 1.0,
        }
        values.update(overrides)
        return PrefillConfig(**values)

    def test_run_uses_no_truth_csv_emits_compact_summary_and_stops_worker(self):
        clock = _Clock()
        emitted: list[dict[str, object]] = []
        classifiers: list[_FakeClassifier] = []
        library_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def classifier_factory(**kwargs):
            classifier = _FakeClassifier(**kwargs)
            classifiers.append(classifier)
            return classifier

        class FakeLibrary:
            def __init__(self, *args, **kwargs) -> None:
                library_calls.append((args, kwargs))

            def scan(self, *, progress, cancel):
                self.cancel = cancel
                clock.now = 0.0
                progress(ScanProgress("inventory", 0, 2))
                clock.now = 0.2
                progress(ScanProgress("metadata", 1, 2, "loop_L1.mp3"))
                clock.now = 1.0
                progress(ScanProgress("classify", 2, 2, "loop_L2.mp3"))
                clock.now = 1.1
                progress(ScanProgress("complete", 2, 2))
                return ScanResult(
                    library_root=str(self_outer.library_root),
                    records=(_record(), _record(label=None)),
                    issues=(
                        ScanIssue("broken.mp3", "metadata", "test issue"),
                        ScanIssue("other.mp3", "metadata", "test issue"),
                    ),
                    inventory_count=2,
                    cached_count=0,
                    hashed_count=2,
                    classified_count=1,
                    cancelled=False,
                )

        self_outer = self
        exit_code, summary = run_prefill(
            self.config(),
            emit=lambda payload: emitted.append(dict(payload)),
            classifier_factory=classifier_factory,
            library_factory=FakeLibrary,
            clock=clock,
        )

        self.assertEqual(exit_code, 0)
        self.assertTrue(classifiers[0].stop_called)
        self.assertEqual(classifiers[0].kwargs["batch_size"], 8)
        self.assertEqual(classifiers[0].kwargs["window_batch_size"], 4)
        self.assertIsNone(library_calls[0][1]["truth_csv_path"])
        self.assertEqual(library_calls[0][1]["classification_batch_size"], 8)
        self.assertEqual(
            [event["event"] for event in emitted],
            ["start", "progress", "progress", "progress", "summary"],
        )
        self.assertEqual(summary["status"], "complete")
        self.assertEqual(summary["classified_count"], 1)
        self.assertEqual(summary["unreviewed_count"], 1)
        self.assertEqual(summary["category_counts"]["Lead"], 1)
        self.assertEqual(summary["issue_counts"], {"metadata": 2})
        self.assertNotIn("records", summary)
        self.assertNotIn("issues", summary)

    def test_classifier_is_stopped_when_scan_raises(self):
        classifier = _FakeClassifier()

        class BrokenLibrary:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def scan(self, **_kwargs):
                raise RuntimeError("scan failed")

        with self.assertRaisesRegex(RuntimeError, "scan failed"):
            run_prefill(
                self.config(),
                emit=lambda _payload: None,
                classifier_factory=lambda **_kwargs: classifier,
                library_factory=BrokenLibrary,
            )
        self.assertTrue(classifier.stop_called)

    def test_cancelled_scan_returns_shell_interrupt_status(self):
        classifier = _FakeClassifier()

        class CancelledLibrary:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def scan(self, **_kwargs):
                return ScanResult(
                    library_root=str(self_outer.library_root),
                    records=(),
                    issues=(),
                    inventory_count=10,
                    cached_count=3,
                    hashed_count=4,
                    classified_count=2,
                    cancelled=True,
                )

        self_outer = self
        exit_code, summary = run_prefill(
            self.config(),
            emit=lambda _payload: None,
            classifier_factory=lambda **_kwargs: classifier,
            library_factory=CancelledLibrary,
        )

        self.assertEqual(exit_code, 130)
        self.assertEqual(summary["status"], "cancelled")
        self.assertTrue(classifier.stop_called)

    def test_rejects_cache_inside_library_before_constructing_classifier(self):
        constructed = False

        def classifier_factory(**_kwargs):
            nonlocal constructed
            constructed = True
            return _FakeClassifier()

        with self.assertRaisesRegex(ValueError, "outside the selected library"):
            run_prefill(
                self.config(
                    library_cache_path=self.library_root / "library.sqlite3"
                ),
                emit=lambda _payload: None,
                classifier_factory=classifier_factory,
            )
        self.assertFalse(constructed)

    def test_rejects_artifact_with_incorrect_sidecar_checksum(self):
        sidecar_path = self.artifact_path.with_suffix(".json")
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        sidecar["artifact_sha256"] = "0" * 64
        sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "checksum"):
            validate_config(self.config())

    def test_progress_reporter_throttles_updates_but_keeps_terminal_event(self):
        clock = _Clock()
        emitted: list[dict[str, object]] = []
        reporter = JsonProgressReporter(
            lambda payload: emitted.append(dict(payload)),
            interval_seconds=1.0,
            clock=clock,
        )

        reporter(ScanProgress("inventory", 0, 4))
        clock.now = 0.2
        reporter(ScanProgress("metadata", 1, 4))
        clock.now = 0.9
        reporter(ScanProgress("classify", 2, 4))
        clock.now = 1.0
        reporter(ScanProgress("classify", 3, 4))
        clock.now = 1.1
        reporter(ScanProgress("complete", 4, 4))

        self.assertEqual(
            [event["phase"] for event in emitted],
            ["inventory", "classify", "complete"],
        )


if __name__ == "__main__":
    unittest.main()
