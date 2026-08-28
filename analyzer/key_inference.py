"""Calibrated OpenKeyScan inference for Stem Slicer loop audio.

The production checkpoint predicts 24 Camelot classes. Stem Slicer's pitch
compatibility works on the 12 relative major/minor families, so this module
combines each minor class with its relative-major class after averaging two
temporal halves of the same loop.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch


ANALYZER_ID = "openkeyscan-split2-relative-family-v2"
MARGIN_THRESHOLD = 0.13234874606132507
NORMALIZED_MINOR_KEYS = (
    "G#m", "D#m", "A#m", "Fm", "Cm", "Gm",
    "Dm", "Am", "Em", "Bm", "F#m", "C#m",
)


@dataclass(frozen=True)
class RelativeFamilyDecision:
    class_id: int
    top1_key: str
    top1_probability: float
    top2_key: str
    top2_probability: float
    margin: float


def split2_probabilities(model, spec_tensor: torch.Tensor) -> torch.Tensor:
    """Return mean softmax probabilities from two temporal loop halves."""

    if spec_tensor.ndim != 4 or spec_tensor.shape[0] != 1:
        raise ValueError(
            "Expected one spectrogram with shape (1, channels, bins, frames)"
        )
    frame_count = int(spec_tensor.shape[-1])
    if frame_count // 2 < 8:
        return torch.softmax(model(spec_tensor)[0], dim=0)
    halves = torch.tensor_split(spec_tensor, 2, dim=-1)
    return torch.stack(
        [torch.softmax(model(half)[0], dim=0) for half in halves]
    ).mean(dim=0)


def relative_family_decision(
    probabilities: torch.Tensor,
) -> RelativeFamilyDecision:
    """Select Top-1/Top-2 relative families and the Top-1 raw Camelot class."""

    if probabilities.ndim != 1 or int(probabilities.shape[0]) != 24:
        raise ValueError("Expected exactly 24 OpenKeyScan probabilities")
    family_scores = probabilities[:12] + probabilities[12:]
    order = torch.argsort(family_scores, descending=True)
    first, second = int(order[0]), int(order[1])
    raw_candidates = (first, first + 12)
    class_id = max(
        raw_candidates,
        key=lambda index: float(probabilities[index]),
    )
    top1_probability = float(family_scores[first])
    top2_probability = float(family_scores[second])
    return RelativeFamilyDecision(
        class_id=class_id,
        top1_key=NORMALIZED_MINOR_KEYS[first],
        top1_probability=top1_probability,
        top2_key=NORMALIZED_MINOR_KEYS[second],
        top2_probability=top2_probability,
        margin=top1_probability - top2_probability,
    )


def infer_relative_family(model, spec_tensor: torch.Tensor) -> RelativeFamilyDecision:
    return relative_family_decision(split2_probabilities(model, spec_tensor))


__all__ = [
    "ANALYZER_ID",
    "MARGIN_THRESHOLD",
    "NORMALIZED_MINOR_KEYS",
    "RelativeFamilyDecision",
    "infer_relative_family",
    "relative_family_decision",
    "split2_probabilities",
]
