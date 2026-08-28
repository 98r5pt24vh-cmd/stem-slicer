from pathlib import Path
import sys
import unittest

import torch


ANALYZER_ROOT = Path(__file__).resolve().parents[1] / "analyzer"
sys.path.insert(0, str(ANALYZER_ROOT))

from key_inference import relative_family_decision, split2_probabilities  # noqa: E402
from key_confidence import (  # noqa: E402
    TEMPORAL_RELATIVE_ANALYZER_ID,
    TEMPORAL_RELATIVE_KEY_MARGIN_THRESHOLD,
)
from key_inference import ANALYZER_ID, MARGIN_THRESHOLD  # noqa: E402


class RecordingModel(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.frame_counts = []

    def forward(self, value):
        self.frame_counts.append(int(value.shape[-1]))
        logits = torch.zeros((1, 24), dtype=value.dtype, device=value.device)
        target = 0 if float(value.mean()) < 0.5 else 1
        logits[0, target] = 4.0
        return logits


class RelativeFamilyInferenceTests(unittest.TestCase):
    def test_core_and_analyzer_share_the_same_calibration_identity(self):
        self.assertEqual(ANALYZER_ID, TEMPORAL_RELATIVE_ANALYZER_ID)
        self.assertEqual(MARGIN_THRESHOLD, TEMPORAL_RELATIVE_KEY_MARGIN_THRESHOLD)

    def test_family_sum_selects_best_raw_mode_inside_winning_family(self):
        probabilities = torch.zeros(24)
        probabilities[0] = 0.20
        probabilities[12] = 0.35
        probabilities[1] = 0.20
        probabilities[13] = 0.10
        decision = relative_family_decision(probabilities)
        self.assertEqual(decision.top1_key, "G#m")
        self.assertEqual(decision.top2_key, "D#m")
        self.assertEqual(decision.class_id, 12)
        self.assertAlmostEqual(decision.top1_probability, 0.55)
        self.assertAlmostEqual(decision.top2_probability, 0.30)
        self.assertAlmostEqual(decision.margin, 0.25)

    def test_two_temporal_halves_are_inferred_separately(self):
        model = RecordingModel()
        spec = torch.cat(
            (torch.zeros((1, 1, 105, 10)), torch.ones((1, 1, 105, 10))),
            dim=-1,
        )
        probabilities = split2_probabilities(model, spec)
        self.assertEqual(model.frame_counts, [10, 10])
        self.assertAlmostEqual(float(probabilities.sum()), 1.0, places=6)
        self.assertAlmostEqual(float(probabilities[0]), float(probabilities[1]), places=6)

    def test_very_short_spectrogram_falls_back_to_one_full_inference(self):
        model = RecordingModel()
        probabilities = split2_probabilities(model, torch.zeros((1, 1, 105, 14)))
        self.assertEqual(model.frame_counts, [14])
        self.assertAlmostEqual(float(probabilities.sum()), 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
