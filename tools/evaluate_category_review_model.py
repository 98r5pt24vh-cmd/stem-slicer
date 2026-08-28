#!/usr/bin/env python3
"""Evaluate the reviewed layer-role dataset without source-loop leakage.

Model choices are made only on the selection seeds. The chosen regularization
and classwise temporal representation are then evaluated unchanged on separate
confirmation seeds. Auxiliary Vocal Chop examples are training-only.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import warnings
from pathlib import Path

import joblib
import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from category_taxonomy import TRAINABLE_CATEGORIES


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


SELECTION_SEEDS = (17, 29, 43)
CONFIRMATION_SEEDS = (59, 71, 83)
FINAL_SEEDS = (137, 149, 163)
C_VALUES = (0.01, 0.03, 0.1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--current-model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def balanced_training_weights(
    labels: np.ndarray,
    roles: np.ndarray,
    producers: np.ndarray,
    groups: np.ndarray,
    auxiliary_class_fraction: float = 0.05,
) -> np.ndarray:
    """Give equal mass to classes and to source loops within each class."""

    result = np.zeros(len(labels), dtype=np.float64)

    def assign_equal_group_mass(indices: np.ndarray, total_mass: float) -> None:
        local_groups = sorted(set(groups[indices]))
        group_mass = total_mass / len(local_groups)
        for group in local_groups:
            members = indices[groups[indices] == group]
            result[members] = group_mass / len(members)

    for label in sorted(set(labels)):
        class_indices = np.flatnonzero(labels == label)
        gold = class_indices[roles[class_indices] == "gold_layer"]
        auxiliary = class_indices[roles[class_indices] == "auxiliary_training_only"]
        if gold.size and auxiliary.size:
            assign_equal_group_mass(gold, 1.0 - auxiliary_class_fraction)
            producer_names = sorted(set(producers[auxiliary]))
            producer_mass = auxiliary_class_fraction / len(producer_names)
            for producer in producer_names:
                producer_rows = auxiliary[producers[auxiliary] == producer]
                assign_equal_group_mass(producer_rows, producer_mass)
        else:
            assign_equal_group_mass(class_indices, 1.0)
    result *= len(result) / result.sum()
    return result


def load_dataset(dataset: Path) -> dict[str, object]:
    with (dataset / "manifest.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    mean = np.load(dataset / "mean.npy").astype(np.float64)
    std = np.load(dataset / "std.npy").astype(np.float64)
    dsp = np.load(dataset / "dsp_features.npz")["features"].astype(np.float64)
    if not (len(rows) == len(mean) == len(std) == len(dsp)):
        raise RuntimeError("Manifest and feature arrays are not aligned")
    if not (np.isfinite(mean).all() and np.isfinite(std).all() and np.isfinite(dsp).all()):
        raise RuntimeError("Feature arrays contain non-finite values")
    return {
        "rows": rows,
        "base": np.concatenate([mean, dsp], axis=1),
        "temporal": np.concatenate([mean, std, dsp], axis=1),
        "labels": np.asarray([row["label"] for row in rows], dtype=str),
        "groups": np.asarray([row["source_group"] for row in rows], dtype=str),
        "roles": np.asarray([row["split_role"] for row in rows], dtype=str),
        "producers": np.asarray([row["producer"] for row in rows], dtype=str),
        "origin_sets": np.asarray([row["origin_set"] for row in rows], dtype=str),
    }


def fit_model(
    matrix: np.ndarray,
    labels: np.ndarray,
    weights: np.ndarray,
    c_value: float,
) -> object:
    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(C=c_value, max_iter=2000, solver="newton-cg", tol=1e-5),
    )
    with warnings.catch_warnings():
        warnings.filterwarnings("error", category=ConvergenceWarning)
        model.fit(matrix, labels, logisticregression__sample_weight=weights)
    return model


def ordered_probabilities(model: object, matrix: np.ndarray, scope: np.ndarray) -> np.ndarray:
    raw = model.predict_proba(matrix)
    model_classes = model.classes_.astype(str)
    order = [int(np.flatnonzero(model_classes == label)[0]) for label in scope]
    return raw[:, order]


def remap_legacy_probabilities(
    model: object, matrix: np.ndarray, scope: np.ndarray
) -> np.ndarray:
    """Map the deployed v2 scores onto the reviewed v3 taxonomy."""

    raw = model.predict_proba(matrix)
    model_classes = model.classes_.astype(str)
    remapped = np.zeros((len(matrix), len(scope)), dtype=np.float64)
    scope_positions = {label: index for index, label in enumerate(scope)}
    for source_index, source_label in enumerate(model_classes):
        destination_label = "Pluck" if source_label == "Rhythmic Pluck" else source_label
        destination_index = scope_positions.get(destination_label)
        if destination_index is not None:
            remapped[:, destination_index] += raw[:, source_index]
    totals = remapped.sum(axis=1, keepdims=True)
    if np.any(totals <= 0.0):
        raise RuntimeError("Legacy model scores could not be mapped to the v3 taxonomy")
    remapped /= totals
    return remapped


def oof_probabilities(
    data: dict[str, object],
    feature: str,
    c_value: float,
    seeds: tuple[int, ...],
) -> np.ndarray:
    labels = data["labels"]
    groups = data["groups"]
    roles = data["roles"]
    producers = data["producers"]
    matrix = data[feature]
    scope = np.asarray(TRAINABLE_CATEGORIES, dtype=str)
    gold = np.flatnonzero((roles == "gold_layer") & np.isin(labels, scope))
    auxiliary = np.flatnonzero(
        (roles == "auxiliary_training_only") & np.isin(labels, scope)
    )
    probabilities = np.zeros((len(seeds), len(gold), len(scope)), dtype=np.float64)
    for seed_index, seed in enumerate(seeds):
        splitter = StratifiedGroupKFold(n_splits=4, shuffle=True, random_state=seed)
        for local_train, local_test in splitter.split(matrix[gold], labels[gold], groups[gold]):
            train = np.concatenate([gold[local_train], auxiliary])
            weights = balanced_training_weights(
                labels[train], roles[train], producers[train], groups[train]
            )
            model = fit_model(matrix[train], labels[train], weights, c_value)
            probabilities[seed_index, local_test] = ordered_probabilities(
                model, matrix[gold[local_test]], scope
            )
    return probabilities


def metrics(data: dict[str, object], probabilities: np.ndarray) -> dict[str, object]:
    labels = data["labels"]
    roles = data["roles"]
    scope = np.asarray(TRAINABLE_CATEGORIES, dtype=str)
    gold = np.flatnonzero((roles == "gold_layer") & np.isin(labels, scope))
    predicted = scope[np.argmax(probabilities, axis=2)]
    macro = [
        float(f1_score(labels[gold], current, labels=scope, average="macro", zero_division=0))
        for current in predicted
    ]
    accuracy = [float(accuracy_score(labels[gold], current)) for current in predicted]
    flat_truth = np.tile(labels[gold], len(probabilities))
    flat_predicted = predicted.reshape(-1)
    report = classification_report(
        flat_truth, flat_predicted, labels=scope, output_dict=True, zero_division=0
    )
    return {
        "macro_f1_mean": float(np.mean(macro)),
        "macro_f1_std": float(np.std(macro)),
        "accuracy_mean": float(np.mean(accuracy)),
        "per_seed_macro_f1": macro,
        "per_seed_accuracy": accuracy,
        "per_class_f1": {label: float(report[label]["f1-score"]) for label in scope},
        "confusion_matrix": confusion_matrix(
            flat_truth, flat_predicted, labels=scope
        ).tolist(),
    }


def candidate_metrics(
    data: dict[str, object], probabilities: np.ndarray
) -> dict[str, object]:
    labels = data["labels"]
    roles = data["roles"]
    origin_sets = data["origin_sets"]
    scope = np.asarray(TRAINABLE_CATEGORIES, dtype=str)
    gold = np.flatnonzero((roles == "gold_layer") & np.isin(labels, scope))
    local_candidate = np.flatnonzero(origin_sets[gold] == "candidate")
    truth = labels[gold[local_candidate]]
    predicted = scope[np.argmax(probabilities[:, local_candidate], axis=2)]
    macro = [
        float(f1_score(truth, current, labels=scope, average="macro", zero_division=0))
        for current in predicted
    ]
    accuracy = [float(accuracy_score(truth, current)) for current in predicted]
    flat_truth = np.tile(truth, len(probabilities))
    flat_predicted = predicted.reshape(-1)
    report = classification_report(
        flat_truth, flat_predicted, labels=scope, output_dict=True, zero_division=0
    )
    return {
        "rows": int(len(local_candidate)),
        "macro_f1_all_14_classes_mean": float(np.mean(macro)),
        "accuracy_mean": float(np.mean(accuracy)),
        "per_seed_macro_f1": macro,
        "per_seed_accuracy": accuracy,
        "per_class_support": {label: int(report[label]["support"] / len(probabilities)) for label in scope},
        "per_class_f1": {label: float(report[label]["f1-score"]) for label in scope},
        "confusion_matrix": confusion_matrix(
            flat_truth, flat_predicted, labels=scope
        ).tolist(),
    }


def select_c(
    data: dict[str, object], feature: str
) -> tuple[float, dict[str, np.ndarray], dict[str, dict[str, object]]]:
    probabilities = {
        str(value): oof_probabilities(data, feature, value, SELECTION_SEEDS)
        for value in C_VALUES
    }
    scored = {key: metrics(data, value) for key, value in probabilities.items()}
    selected = max(
        probabilities,
        key=lambda key: (scored[key]["macro_f1_mean"], -abs(float(key) - 0.03)),
    )
    return float(selected), probabilities, scored


def combine_classwise(
    base: np.ndarray, temporal: np.ndarray, temporal_classes: list[str]
) -> np.ndarray:
    combined = base.copy()
    for index, label in enumerate(TRAINABLE_CATEGORIES):
        if label in temporal_classes:
            combined[:, :, index] = temporal[:, :, index]
    combined /= combined.sum(axis=2, keepdims=True)
    return combined


def current_model_challenge(
    data: dict[str, object], current_model_path: Path
) -> dict[str, object]:
    candidate = np.flatnonzero(
        (data["roles"] == "gold_layer") & (data["origin_sets"] == "candidate")
    )
    payload = joblib.load(current_model_path)
    model = payload["model"] if isinstance(payload, dict) else payload
    scope = np.asarray(TRAINABLE_CATEGORIES, dtype=str)
    probabilities = remap_legacy_probabilities(
        model, data["temporal"][candidate], scope
    )
    predicted = scope[np.argmax(probabilities, axis=1)]
    truth = data["labels"][candidate]
    report = classification_report(
        truth, predicted, labels=scope, output_dict=True, zero_division=0
    )
    return {
        "rows": int(len(candidate)),
        "note": (
            "Manually reviewed, previously unseen candidates actively sampled from "
            "the deployed v2; targeted rather than random."
        ),
        "accuracy": float(accuracy_score(truth, predicted)),
        "macro_f1_all_14_classes": float(
            f1_score(truth, predicted, labels=scope, average="macro", zero_division=0)
        ),
        "per_class_support": {label: int(report[label]["support"]) for label in scope},
        "per_class_f1": {label: float(report[label]["f1-score"]) for label in scope},
        "confusion_matrix": confusion_matrix(truth, predicted, labels=scope).tolist(),
    }


def main() -> int:
    args = parse_args()
    dataset = args.dataset.expanduser().resolve(strict=True)
    output = args.output.expanduser().resolve(strict=False)
    if output.exists():
        raise FileExistsError(f"Refusing to replace existing result: {output}")
    data = load_dataset(dataset)

    base_c, base_selection_probabilities, base_selection_metrics = select_c(data, "base")
    temporal_c, temporal_selection_probabilities, temporal_selection_metrics = select_c(
        data, "temporal"
    )
    selected_base = base_selection_probabilities[str(base_c)]
    selected_temporal = temporal_selection_probabilities[str(temporal_c)]
    base_selected_metrics = metrics(data, selected_base)
    temporal_selected_metrics = metrics(data, selected_temporal)
    temporal_classes = [
        label
        for label in TRAINABLE_CATEGORIES
        if temporal_selected_metrics["per_class_f1"][label]
        > base_selected_metrics["per_class_f1"][label] + 0.01
    ]
    selection_classwise = combine_classwise(
        selected_base, selected_temporal, temporal_classes
    )

    confirmation_base = oof_probabilities(data, "base", base_c, CONFIRMATION_SEEDS)
    confirmation_temporal = oof_probabilities(
        data, "temporal", temporal_c, CONFIRMATION_SEEDS
    )
    confirmation_classwise = combine_classwise(
        confirmation_base, confirmation_temporal, temporal_classes
    )
    final_base = oof_probabilities(data, "base", base_c, FINAL_SEEDS)
    final_temporal = oof_probabilities(data, "temporal", temporal_c, FINAL_SEEDS)
    final_classwise = combine_classwise(
        final_base, final_temporal, temporal_classes
    )

    gold_count = int(np.sum(data["roles"] == "gold_layer"))
    gold_groups = len(
        set(data["groups"][np.flatnonzero(data["roles"] == "gold_layer")])
    )
    result = {
        "protocol": {
            "classes": list(TRAINABLE_CATEGORIES),
            "gold_rows": gold_count,
            "gold_source_groups": gold_groups,
            "auxiliary_training_only": int(
                np.sum(data["roles"] == "auxiliary_training_only")
            ),
            "selection_seeds": list(SELECTION_SEEDS),
            "confirmation_seeds": list(CONFIRMATION_SEEDS),
            "final_seeds": list(FINAL_SEEDS),
            "folds": 4,
            "grouped_by_source_loop": True,
            "auxiliary_never_scored": True,
            "c_values": list(C_VALUES),
            "selection_bias_note": (
                "The added review rows were actively sampled, so these metrics measure the "
                "review-enriched corpus and are not a production prevalence estimate."
            ),
        },
        "current_v2_candidate_challenge": current_model_challenge(
            data, args.current_model.expanduser().resolve(strict=True)
        ),
        "selection": {
            "base_by_c": base_selection_metrics,
            "temporal_by_c": temporal_selection_metrics,
            "selected_base_c": base_c,
            "selected_temporal_c": temporal_c,
            "selected_temporal_classes": temporal_classes,
            "base": base_selected_metrics,
            "temporal": temporal_selected_metrics,
            "classwise": metrics(data, selection_classwise),
        },
        "confirmation": {
            "base": metrics(data, confirmation_base),
            "temporal": metrics(data, confirmation_temporal),
            "classwise": metrics(data, confirmation_classwise),
        },
        "final": {
            "base": metrics(data, final_base),
            "temporal": metrics(data, final_temporal),
            "classwise": metrics(data, final_classwise),
        },
        "confirmation_candidate_challenge": {
            "note": (
                "Only newly reviewed candidate rows are scored; every row and "
                "all siblings from its source loop are excluded from that fold's training."
            ),
            "base": candidate_metrics(data, confirmation_base),
            "temporal": candidate_metrics(data, confirmation_temporal),
            "classwise": candidate_metrics(data, confirmation_classwise),
        },
        "final_candidate_challenge": {
            "note": (
                "Final untouched seeds; only newly reviewed candidate rows are scored "
                "and complete source-loop groups remain isolated."
            ),
            "base": candidate_metrics(data, final_base),
            "temporal": candidate_metrics(data, final_temporal),
            "classwise": candidate_metrics(data, final_classwise),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"selected_base_c={base_c} selected_temporal_c={temporal_c} "
        f"temporal_classes={temporal_classes}"
    )
    print(
        "current_v2_candidate_challenge "
        f"accuracy={result['current_v2_candidate_challenge']['accuracy']:.4f}"
    )
    for phase in ("selection", "confirmation", "final"):
        print(phase)
        for name in ("base", "temporal", "classwise"):
            value = result[phase][name]
            print(
                f"  {name:10s} macro_f1={value['macro_f1_mean']:.4f} "
                f"accuracy={value['accuracy_mean']:.4f}"
            )
    print("confirmation_candidate_challenge")
    for name in ("base", "temporal", "classwise"):
        value = result["confirmation_candidate_challenge"][name]
        print(
            f"  {name:10s} macro_f1={value['macro_f1_all_14_classes_mean']:.4f} "
            f"accuracy={value['accuracy_mean']:.4f}"
        )
    print("final_candidate_challenge")
    for name in ("base", "temporal", "classwise"):
        value = result["final_candidate_challenge"][name]
        print(
            f"  {name:10s} macro_f1={value['macro_f1_all_14_classes_mean']:.4f} "
            f"accuracy={value['accuracy_mean']:.4f}"
        )
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
