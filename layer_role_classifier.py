"""Portable classifier adapters used by Stem Slicer's layer-role artifacts."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np


class LayerRoleScoreEnsemble:
    """Combine a stable mean-feature head with selected temporal-score columns.

    The input layout is fixed to ``MERT mean, MERT std, DSP``.  The historical
    head receives the mean and DSP slices; the temporal head receives the full
    vector.  Only classes selected before final validation use the temporal
    score.  Re-normalization restores a proper probability distribution.
    """

    def __init__(
        self,
        base_model,
        temporal_model,
        temporal_classes: Iterable[str],
        *,
        mert_dimension: int,
        dsp_dimension: int,
    ) -> None:
        self.base_model = base_model
        self.temporal_model = temporal_model
        self.classes_ = np.asarray(base_model.classes_, dtype=str)
        temporal_order = np.asarray(temporal_model.classes_, dtype=str)
        if not np.array_equal(self.classes_, temporal_order):
            raise ValueError("Base and temporal heads must use the same class order")
        selected = frozenset(str(value) for value in temporal_classes)
        unknown = selected.difference(self.classes_)
        if unknown:
            raise ValueError(f"Unknown temporal classes: {sorted(unknown)!r}")
        self.temporal_classes = tuple(
            label for label in self.classes_ if label in selected
        )
        self.mert_dimension = int(mert_dimension)
        self.dsp_dimension = int(dsp_dimension)
        if self.mert_dimension < 1 or self.dsp_dimension < 1:
            raise ValueError("Feature dimensions must be positive")
        self.n_features_in_ = self.mert_dimension * 2 + self.dsp_dimension

    def _validated_matrix(self, values) -> np.ndarray:
        matrix = np.asarray(values)
        if matrix.ndim != 2 or matrix.shape[1] != self.n_features_in_:
            raise ValueError(
                "Layer-role ensemble expects "
                f"{self.n_features_in_} features, got {matrix.shape}"
            )
        if not np.isfinite(matrix).all():
            raise ValueError("Layer-role features contain non-finite values")
        return matrix

    def predict_proba(self, values) -> np.ndarray:
        matrix = self._validated_matrix(values)
        mean_end = self.mert_dimension
        std_end = mean_end + self.mert_dimension
        base_matrix = np.concatenate(
            [matrix[:, :mean_end], matrix[:, std_end:]],
            axis=1,
        )
        base = np.asarray(self.base_model.predict_proba(base_matrix), dtype=np.float64)
        temporal = np.asarray(
            self.temporal_model.predict_proba(matrix), dtype=np.float64
        )
        expected = (len(matrix), len(self.classes_))
        if base.shape != expected or temporal.shape != expected:
            raise RuntimeError("Layer-role head returned an invalid probability matrix")
        combined = base.copy()
        for index, label in enumerate(self.classes_):
            if label in self.temporal_classes:
                combined[:, index] = temporal[:, index]
        totals = combined.sum(axis=1, keepdims=True)
        if not np.isfinite(combined).all() or np.any(combined < 0.0) or np.any(totals <= 0.0):
            raise RuntimeError("Layer-role ensemble produced invalid scores")
        return combined / totals

    def predict(self, values) -> np.ndarray:
        probabilities = self.predict_proba(values)
        return self.classes_[np.argmax(probabilities, axis=1)]
