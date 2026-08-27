#!/usr/bin/env python3
"""Test weakly supervised internal attributes on the reviewed role corpus.

Attribute targets are derived from user-validated role folders. At inference
time they are predicted from audio features; folder names are never supplied to
the classifier. Attribute compatibility is fused with the role probabilities
and evaluated with source-loop grouped folds.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import StratifiedGroupKFold

from category_taxonomy import TRAINABLE_CATEGORIES
from evaluate_category_review_model import (
    CONFIRMATION_SEEDS,
    FINAL_SEEDS,
    SELECTION_SEEDS,
    balanced_training_weights,
    candidate_metrics,
    combine_classwise,
    fit_model,
    load_dataset,
    metrics,
    oof_probabilities,
    ordered_probabilities,
)


ATTRIBUTE_MAPS = {
    "articulation": {
        "Arp": "mixed_repeated",
        "Bass": "sustained_legato",
        "Bells": "percussive_decay",
        "Chords": "mixed_layered",
        "Counter": "mixed_sparse",
        "Guitar Chords": "mixed_layered",
        "Keys": "sustained_legato",
        "Lead": "sustained_legato",
        "Pad": "sustained_legato",
        "Piano": "percussive_decay",
        "Pluck": "plucky_short",
        "Strings": "sustained_legato",
        "Texture": "chopped_gated",
        "Vocal Chop": "chopped_gated",
    },
    "identity": {
        "Arp": "synth_processed",
        "Bass": "synth_dominant",
        "Bells": "bells_synth",
        "Chords": "synth_dominant",
        "Counter": "synth_dominant",
        "Guitar Chords": "guitar",
        "Keys": "synth_dominant",
        "Lead": "synth_dominant",
        "Pad": "synth_dominant",
        "Piano": "piano",
        "Pluck": "synth_dominant",
        "Strings": "strings",
        "Texture": "processed",
        "Vocal Chop": "vocal_processed",
    },
    "temporal_activity": {
        "Arp": "dense",
        "Bass": "medium",
        "Bells": "sparse",
        "Chords": "dense",
        "Counter": "sparse",
        "Guitar Chords": "dense",
        "Keys": "medium",
        "Lead": "medium",
        "Pad": "dense",
        "Piano": "medium",
        "Pluck": "sparse",
        "Strings": "dense",
        "Texture": "medium",
        "Vocal Chop": "medium",
    },
    "processing": {
        "Arp": "processed",
        "Bass": "standard",
        "Bells": "standard",
        "Chords": "standard",
        "Counter": "standard",
        "Guitar Chords": "standard",
        "Keys": "standard",
        "Lead": "standard",
        "Pad": "standard",
        "Piano": "standard",
        "Pluck": "standard",
        "Strings": "standard",
        "Texture": "processed",
        "Vocal Chop": "processed",
    },
}

CONFIGURATIONS = (
    ("articulation",),
    ("identity",),
    ("temporal_activity",),
    ("processing",),
    ("articulation", "temporal_activity"),
    ("articulation", "identity"),
    ("identity", "processing"),
    ("articulation", "identity", "temporal_activity"),
    tuple(ATTRIBUTE_MAPS),
)
FUSION_WEIGHTS = (0.25, 0.5, 1.0, 2.0)
ATTRIBUTE_C = 0.01


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--role-evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def attribute_oof_probabilities(
    data: dict[str, object], axis: str, seeds: tuple[int, ...]
) -> tuple[np.ndarray, tuple[str, ...]]:
    role_labels = data["labels"]
    roles = data["roles"]
    groups = data["groups"]
    producers = data["producers"]
    matrix = data["temporal"]
    scope = np.asarray(TRAINABLE_CATEGORIES, dtype=str)
    gold = np.flatnonzero((roles == "gold_layer") & np.isin(role_labels, scope))
    auxiliary = np.flatnonzero(
        (roles == "auxiliary_training_only") & np.isin(role_labels, scope)
    )
    mapping = ATTRIBUTE_MAPS[axis]
    attribute_labels = np.asarray([mapping[label] for label in role_labels], dtype=str)
    attribute_classes = tuple(sorted(set(mapping.values())))
    attribute_scope = np.asarray(attribute_classes, dtype=str)
    probabilities = np.zeros(
        (len(seeds), len(gold), len(attribute_classes)), dtype=np.float64
    )
    for seed_index, seed in enumerate(seeds):
        splitter = StratifiedGroupKFold(n_splits=4, shuffle=True, random_state=seed)
        for local_train, local_test in splitter.split(
            matrix[gold], role_labels[gold], groups[gold]
        ):
            train = np.concatenate([gold[local_train], auxiliary])
            weights = balanced_training_weights(
                attribute_labels[train],
                roles[train],
                producers[train],
                groups[train],
            )
            model = fit_model(
                matrix[train], attribute_labels[train], weights, ATTRIBUTE_C
            )
            probabilities[seed_index, local_test] = ordered_probabilities(
                model, matrix[gold[local_test]], attribute_scope
            )
    return probabilities, attribute_classes


def attribute_metrics(
    data: dict[str, object],
    axis: str,
    probabilities: np.ndarray,
    classes: tuple[str, ...],
) -> dict[str, float]:
    role_labels = data["labels"]
    roles = data["roles"]
    scope = np.asarray(TRAINABLE_CATEGORIES, dtype=str)
    gold = np.flatnonzero((roles == "gold_layer") & np.isin(role_labels, scope))
    truth = np.asarray([ATTRIBUTE_MAPS[axis][label] for label in role_labels[gold]])
    predicted = np.asarray(classes)[np.argmax(probabilities, axis=2)]
    return {
        "accuracy_mean": float(
            np.mean([accuracy_score(truth, current) for current in predicted])
        ),
        "macro_f1_mean": float(
            np.mean(
                [
                    f1_score(
                        truth,
                        current,
                        labels=np.asarray(classes),
                        average="macro",
                        zero_division=0,
                    )
                    for current in predicted
                ]
            )
        ),
    }


def role_baseline(
    data: dict[str, object], evaluation: dict[str, object], seeds: tuple[int, ...]
) -> np.ndarray:
    base = oof_probabilities(
        data, "base", float(evaluation["selection"]["selected_base_c"]), seeds
    )
    temporal = oof_probabilities(
        data,
        "temporal",
        float(evaluation["selection"]["selected_temporal_c"]),
        seeds,
    )
    return combine_classwise(
        base,
        temporal,
        list(evaluation["selection"]["selected_temporal_classes"]),
    )


def compatibility_log_scores(
    probabilities: dict[str, np.ndarray],
    classes: dict[str, tuple[str, ...]],
    axes: tuple[str, ...],
) -> np.ndarray:
    sample = probabilities[axes[0]]
    result = np.zeros(
        (sample.shape[0], sample.shape[1], len(TRAINABLE_CATEGORIES)),
        dtype=np.float64,
    )
    for axis in axes:
        positions = {value: index for index, value in enumerate(classes[axis])}
        for role_index, role in enumerate(TRAINABLE_CATEGORIES):
            attribute_index = positions[ATTRIBUTE_MAPS[axis][role]]
            result[:, :, role_index] += np.log(
                np.clip(probabilities[axis][:, :, attribute_index], 1e-8, 1.0)
            )
    result /= len(axes)
    return result


def fuse(
    baseline: np.ndarray, compatibility: np.ndarray, weight: float
) -> np.ndarray:
    log_scores = np.log(np.clip(baseline, 1e-8, 1.0)) + weight * compatibility
    log_scores -= np.max(log_scores, axis=2, keepdims=True)
    scores = np.exp(log_scores)
    scores /= scores.sum(axis=2, keepdims=True)
    return scores


def phase_probabilities(
    data: dict[str, object],
    evaluation: dict[str, object],
    seeds: tuple[int, ...],
) -> tuple[np.ndarray, dict[str, np.ndarray], dict[str, tuple[str, ...]]]:
    baseline = role_baseline(data, evaluation, seeds)
    attributes: dict[str, np.ndarray] = {}
    classes: dict[str, tuple[str, ...]] = {}
    for axis in ATTRIBUTE_MAPS:
        attributes[axis], classes[axis] = attribute_oof_probabilities(
            data, axis, seeds
        )
    return baseline, attributes, classes


def main() -> int:
    args = parse_args()
    output = args.output.expanduser().resolve(strict=False)
    if output.exists():
        raise FileExistsError(f"Refusing to replace existing result: {output}")
    data = load_dataset(args.dataset.expanduser().resolve(strict=True))
    evaluation = json.loads(
        args.role_evaluation.expanduser().resolve(strict=True).read_text(encoding="utf-8")
    )

    selection_base, selection_attributes, selection_classes = phase_probabilities(
        data, evaluation, SELECTION_SEEDS
    )
    selection_candidates: dict[str, dict[str, object]] = {}
    for axes in CONFIGURATIONS:
        compatibility = compatibility_log_scores(
            selection_attributes, selection_classes, axes
        )
        for weight in FUSION_WEIGHTS:
            key = f"{'+'.join(axes)}@{weight:g}"
            selection_candidates[key] = {
                "axes": list(axes),
                "weight": weight,
                "metrics": metrics(data, fuse(selection_base, compatibility, weight)),
            }
    selected_key = max(
        selection_candidates,
        key=lambda key: (
            selection_candidates[key]["metrics"]["macro_f1_mean"],
            selection_candidates[key]["metrics"]["accuracy_mean"],
        ),
    )
    selected_axes = tuple(selection_candidates[selected_key]["axes"])
    selected_weight = float(selection_candidates[selected_key]["weight"])

    phases = {
        "confirmation": CONFIRMATION_SEEDS,
        "final": FINAL_SEEDS,
    }
    phase_results: dict[str, object] = {}
    for phase, seeds in phases.items():
        baseline, attributes, classes = phase_probabilities(data, evaluation, seeds)
        compatibility = compatibility_log_scores(attributes, classes, selected_axes)
        hierarchical = fuse(baseline, compatibility, selected_weight)
        phase_results[phase] = {
            "baseline": metrics(data, baseline),
            "hierarchical": metrics(data, hierarchical),
            "baseline_candidate_challenge": candidate_metrics(data, baseline),
            "hierarchical_candidate_challenge": candidate_metrics(data, hierarchical),
            "attribute_metrics": {
                axis: attribute_metrics(data, axis, attributes[axis], classes[axis])
                for axis in ATTRIBUTE_MAPS
            },
        }

    selection_compatibility = compatibility_log_scores(
        selection_attributes, selection_classes, selected_axes
    )
    selection_hierarchical = fuse(
        selection_base, selection_compatibility, selected_weight
    )
    result = {
        "schema": "stem-slicer-weak-attribute-hierarchy-evaluation-v1",
        "protocol": {
            "selection_seeds": list(SELECTION_SEEDS),
            "confirmation_seeds": list(CONFIRMATION_SEEDS),
            "final_seeds": list(FINAL_SEEDS),
            "folds": 4,
            "grouped_by_source_loop": True,
            "attributes_predicted_from_audio": True,
            "folder_labels_unavailable_at_inference": True,
            "attribute_C": ATTRIBUTE_C,
            "fusion_weights": list(FUSION_WEIGHTS),
        },
        "attribute_maps": ATTRIBUTE_MAPS,
        "selection": {
            "baseline": metrics(data, selection_base),
            "candidates": selection_candidates,
            "selected": selected_key,
            "selected_axes": list(selected_axes),
            "selected_weight": selected_weight,
            "hierarchical": metrics(data, selection_hierarchical),
            "attribute_metrics": {
                axis: attribute_metrics(
                    data, axis, selection_attributes[axis], selection_classes[axis]
                )
                for axis in ATTRIBUTE_MAPS
            },
        },
        **phase_results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"selected={selected_key}")
    for phase in ("selection", "confirmation", "final"):
        baseline = result[phase]["baseline"]
        hierarchical = result[phase]["hierarchical"]
        print(
            f"{phase:12s} baseline macro={baseline['macro_f1_mean']:.4f} "
            f"accuracy={baseline['accuracy_mean']:.4f}"
        )
        print(
            f"{phase:12s} hierarchy macro={hierarchical['macro_f1_mean']:.4f} "
            f"accuracy={hierarchical['accuracy_mean']:.4f}"
        )
        if phase != "selection":
            challenge = result[phase]["hierarchical_candidate_challenge"]
            print(
                f"{phase:12s} hard cases macro="
                f"{challenge['macro_f1_all_14_classes_mean']:.4f} "
                f"accuracy={challenge['accuracy_mean']:.4f}"
            )
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
