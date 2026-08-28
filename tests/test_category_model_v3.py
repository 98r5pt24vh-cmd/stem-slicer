import hashlib
import json
from pathlib import Path
import unittest

import joblib
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CLASSES = (
    "Arp",
    "Bass",
    "Bells",
    "Chords",
    "Counter",
    "Guitar Chords",
    "Keys",
    "Lead",
    "Pad",
    "Piano",
    "Pluck",
    "Strings",
    "Texture",
    "Vocal Chop",
)


class CategoryModelV3Tests(unittest.TestCase):
    def setUp(self):
        self.artifact_path = ROOT / "models" / "layer_roles_v3.joblib"
        self.sidecar_path = self.artifact_path.with_suffix(".json")

    def test_artifact_identity_taxonomy_and_status_are_pinned(self):
        sidecar = json.loads(self.sidecar_path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(self.artifact_path.read_bytes()).hexdigest()

        self.assertEqual(sidecar["schema"], "stem-slicer-layer-role-head-v3")
        self.assertEqual(sidecar["status"], "accepted_current")
        self.assertEqual(sidecar["artifact_sha256"], digest)
        self.assertEqual(tuple(sidecar["classes"]), EXPECTED_CLASSES)
        self.assertEqual(sidecar["training"]["gold_rows"], 849)
        self.assertEqual(sidecar["training"]["gold_source_groups"], 641)
        self.assertEqual(sidecar["training"]["auxiliary_rows"], 323)

    def test_serialized_head_produces_valid_v3_scores(self):
        payload = joblib.load(self.artifact_path)
        model = payload["model"]
        scores = model.predict_proba(np.zeros((1, 1600), dtype=np.float32))

        self.assertEqual(tuple(model.classes_), EXPECTED_CLASSES)
        self.assertEqual(model.n_features_in_, 1600)
        self.assertEqual(scores.shape, (1, len(EXPECTED_CLASSES)))
        self.assertTrue(np.isfinite(scores).all())
        self.assertAlmostEqual(float(scores.sum()), 1.0)


if __name__ == "__main__":
    unittest.main()
