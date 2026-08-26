import unittest

import numpy as np

from layer_role_classifier import LayerRoleScoreEnsemble


class _Head:
    classes_ = np.asarray(["Bells", "Lead", "Texture"])

    def __init__(self, probabilities):
        self.probabilities = np.asarray(probabilities, dtype=np.float64)
        self.received = None

    def predict_proba(self, values):
        self.received = np.asarray(values).copy()
        return np.tile(self.probabilities, (len(values), 1))


class LayerRoleScoreEnsembleTests(unittest.TestCase):
    def test_selected_temporal_columns_replace_base_then_renormalize(self):
        base = _Head([0.2, 0.7, 0.1])
        temporal = _Head([0.6, 0.1, 0.3])
        ensemble = LayerRoleScoreEnsemble(
            base,
            temporal,
            ["Bells", "Texture"],
            mert_dimension=2,
            dsp_dimension=1,
        )
        matrix = np.asarray([[1.0, 2.0, 3.0, 4.0, 5.0]])

        probabilities = ensemble.predict_proba(matrix)

        np.testing.assert_allclose(base.received, [[1.0, 2.0, 5.0]])
        np.testing.assert_allclose(temporal.received, matrix)
        np.testing.assert_allclose(probabilities, [[0.375, 0.4375, 0.1875]])
        self.assertEqual(ensemble.predict(matrix).tolist(), ["Lead"])

    def test_feature_dimension_mismatch_fails_closed(self):
        ensemble = LayerRoleScoreEnsemble(
            _Head([0.3, 0.4, 0.3]),
            _Head([0.3, 0.4, 0.3]),
            ["Bells"],
            mert_dimension=2,
            dsp_dimension=1,
        )

        with self.assertRaisesRegex(ValueError, "expects 5 features"):
            ensemble.predict_proba(np.zeros((1, 4)))


if __name__ == "__main__":
    unittest.main()
