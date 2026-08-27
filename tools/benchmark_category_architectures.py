#!/usr/bin/env python3
"""Leakage-safe architecture benchmark for the reviewed category corpus."""

from __future__ import annotations

import argparse
import json
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from sklearn.decomposition import PCA
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.ensemble import (
    ExtraTreesClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from category_taxonomy import TRAINABLE_CATEGORIES
from evaluate_category_review_model import (
    CONFIRMATION_SEEDS,
    FINAL_SEEDS,
    SELECTION_SEEDS,
    balanced_training_weights,
    load_dataset,
)


@dataclass(frozen=True)
class Candidate:
    name: str
    feature: str
    factory: Callable[[int], object]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--baseline-evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirmation-count", type=int, default=6)
    return parser.parse_args()


def candidates() -> list[Candidate]:
    result: list[Candidate] = []
    for feature in ("base", "temporal"):
        for c_value in (0.003, 0.01, 0.03, 0.1):
            result.append(
                Candidate(
                    f"logreg_{feature}_c{c_value:g}",
                    feature,
                    lambda seed, c=c_value: make_pipeline(
                        StandardScaler(),
                        LogisticRegression(
                            C=c,
                            max_iter=2500,
                            solver="newton-cg",
                            tol=1e-5,
                        ),
                    ),
                )
            )
        for c_value in (0.3, 1.0, 3.0, 10.0):
            result.append(
                Candidate(
                    f"rbf_svc_{feature}_c{c_value:g}",
                    feature,
                    lambda seed, c=c_value: make_pipeline(
                        StandardScaler(),
                        SVC(
                            C=c,
                            kernel="rbf",
                            gamma="scale",
                            cache_size=2048,
                            random_state=seed,
                        ),
                    ),
                )
            )
    for feature in ("base", "temporal"):
        for shrinkage in ("auto", 0.1):
            result.append(
                Candidate(
                    f"lda_{feature}_shrink_{shrinkage}",
                    feature,
                    lambda seed, value=shrinkage: make_pipeline(
                        StandardScaler(),
                        LinearDiscriminantAnalysis(
                            solver="lsqr",
                            shrinkage=value,
                            priors=np.full(
                                len(TRAINABLE_CATEGORIES),
                                1.0 / len(TRAINABLE_CATEGORIES),
                            ),
                        ),
                    ),
                )
            )
    for feature in ("base", "temporal"):
        for leaf, max_features in ((1, "sqrt"), (2, "sqrt"), (2, 0.2)):
            result.append(
                Candidate(
                    f"extra_trees_{feature}_leaf{leaf}_mf{max_features}",
                    feature,
                    lambda seed, local_leaf=leaf, local_features=max_features: ExtraTreesClassifier(
                        n_estimators=450,
                        min_samples_leaf=local_leaf,
                        max_features=local_features,
                        n_jobs=-1,
                        random_state=seed,
                    ),
                )
            )
    for leaf in (1, 2):
        result.append(
            Candidate(
                f"random_forest_temporal_leaf{leaf}",
                "temporal",
                lambda seed, local_leaf=leaf: RandomForestClassifier(
                    n_estimators=450,
                    min_samples_leaf=local_leaf,
                    max_features="sqrt",
                    n_jobs=-1,
                    random_state=seed,
                ),
            )
        )
    for width, alpha in ((64, 0.001), (64, 0.01), (128, 0.001), (128, 0.01)):
        result.append(
            Candidate(
                f"mlp_temporal_h{width}_a{alpha:g}",
                "temporal",
                lambda seed, local_width=width, local_alpha=alpha: make_pipeline(
                    StandardScaler(),
                    MLPClassifier(
                        hidden_layer_sizes=(local_width,),
                        activation="relu",
                        alpha=local_alpha,
                        batch_size=64,
                        learning_rate_init=0.001,
                        max_iter=350,
                        early_stopping=True,
                        validation_fraction=0.15,
                        n_iter_no_change=25,
                        random_state=seed,
                    ),
                ),
            )
        )
    for leaf_nodes, l2 in ((15, 0.1), (31, 0.1)):
        result.append(
            Candidate(
                f"pca_hgb_temporal_leaf{leaf_nodes}_l2{l2:g}",
                "temporal",
                lambda seed, nodes=leaf_nodes, local_l2=l2: make_pipeline(
                    StandardScaler(),
                    PCA(n_components=96, whiten=False, random_state=seed),
                    HistGradientBoostingClassifier(
                        learning_rate=0.06,
                        max_iter=250,
                        max_leaf_nodes=nodes,
                        l2_regularization=local_l2,
                        early_stopping=True,
                        random_state=seed,
                    ),
                ),
            )
        )
    return result


def fit_with_weights(
    model: object,
    matrix: np.ndarray,
    labels: np.ndarray,
    weights: np.ndarray,
) -> None:
    if hasattr(model, "steps"):
        final_name = model.steps[-1][0]
        fit_kwargs = {f"{final_name}__sample_weight": weights}
    else:
        fit_kwargs = {"sample_weight": weights}
    try:
        model.fit(matrix, labels, **fit_kwargs)
    except TypeError as exc:
        if "sample_weight" not in str(exc):
            raise
        model.fit(matrix, labels)


def prediction_metrics(
    data: dict[str, object], predictions: np.ndarray
) -> dict[str, object]:
    labels = data["labels"]
    roles = data["roles"]
    origin_sets = data["origin_sets"]
    scope = np.asarray(TRAINABLE_CATEGORIES, dtype=str)
    gold = np.flatnonzero((roles == "gold_layer") & np.isin(labels, scope))
    truth = labels[gold]
    macro = [
        float(f1_score(truth, current, labels=scope, average="macro", zero_division=0))
        for current in predictions
    ]
    accuracy = [float(accuracy_score(truth, current)) for current in predictions]
    flat_truth = np.tile(truth, len(predictions))
    flat_predictions = predictions.reshape(-1)
    report = classification_report(
        flat_truth,
        flat_predictions,
        labels=scope,
        output_dict=True,
        zero_division=0,
    )
    local_candidate = np.flatnonzero(origin_sets[gold] == "candidate")
    candidate_truth = truth[local_candidate]
    candidate_predictions = predictions[:, local_candidate]
    candidate_macro = [
        float(
            f1_score(
                candidate_truth,
                current,
                labels=scope,
                average="macro",
                zero_division=0,
            )
        )
        for current in candidate_predictions
    ]
    candidate_accuracy = [
        float(accuracy_score(candidate_truth, current))
        for current in candidate_predictions
    ]
    return {
        "macro_f1_mean": float(np.mean(macro)),
        "macro_f1_std": float(np.std(macro)),
        "accuracy_mean": float(np.mean(accuracy)),
        "per_seed_macro_f1": macro,
        "per_seed_accuracy": accuracy,
        "per_class_f1": {
            label: float(report[label]["f1-score"]) for label in scope
        },
        "confusion_matrix": confusion_matrix(
            flat_truth, flat_predictions, labels=scope
        ).tolist(),
        "candidate_challenge": {
            "rows": int(len(local_candidate)),
            "macro_f1_mean": float(np.mean(candidate_macro)),
            "accuracy_mean": float(np.mean(candidate_accuracy)),
            "per_seed_macro_f1": candidate_macro,
            "per_seed_accuracy": candidate_accuracy,
        },
    }


def evaluate_candidate(
    data: dict[str, object], candidate: Candidate, seeds: tuple[int, ...]
) -> dict[str, object]:
    matrix = data[candidate.feature]
    labels = data["labels"]
    groups = data["groups"]
    roles = data["roles"]
    producers = data["producers"]
    scope = np.asarray(TRAINABLE_CATEGORIES, dtype=str)
    gold = np.flatnonzero((roles == "gold_layer") & np.isin(labels, scope))
    auxiliary = np.flatnonzero(
        (roles == "auxiliary_training_only") & np.isin(labels, scope)
    )
    predictions = np.full((len(seeds), len(gold)), "", dtype=object)
    started = time.perf_counter()
    for seed_index, seed in enumerate(seeds):
        splitter = StratifiedGroupKFold(n_splits=4, shuffle=True, random_state=seed)
        for local_train, local_test in splitter.split(
            matrix[gold], labels[gold], groups[gold]
        ):
            train = np.concatenate([gold[local_train], auxiliary])
            weights = balanced_training_weights(
                labels[train], roles[train], producers[train], groups[train]
            )
            model = candidate.factory(seed)
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=ConvergenceWarning)
                fit_with_weights(model, matrix[train], labels[train], weights)
            predictions[seed_index, local_test] = model.predict(
                matrix[gold[local_test]]
            )
    result = prediction_metrics(data, predictions)
    result["elapsed_seconds"] = float(time.perf_counter() - started)
    result["feature"] = candidate.feature
    return result


def ranking_key(item: tuple[str, dict[str, object]]) -> tuple[float, float]:
    metrics = item[1]
    return float(metrics["macro_f1_mean"]), float(metrics["accuracy_mean"])


def main() -> int:
    args = parse_args()
    if args.confirmation_count < 1:
        raise ValueError("--confirmation-count must be positive")
    output = args.output.expanduser().resolve(strict=False)
    if output.exists():
        raise FileExistsError(f"Refusing to replace existing result: {output}")
    data = load_dataset(args.dataset.expanduser().resolve(strict=True))
    baseline = json.loads(
        args.baseline_evaluation.expanduser().resolve(strict=True).read_text(
            encoding="utf-8"
        )
    )
    candidate_list = candidates()
    selection: dict[str, dict[str, object]] = {}
    print(f"selection candidates={len(candidate_list)}", flush=True)
    for index, candidate in enumerate(candidate_list, start=1):
        metrics = evaluate_candidate(data, candidate, SELECTION_SEEDS)
        selection[candidate.name] = metrics
        print(
            f"[{index:02d}/{len(candidate_list):02d}] {candidate.name:42s} "
            f"macro={metrics['macro_f1_mean']:.4f} "
            f"accuracy={metrics['accuracy_mean']:.4f} "
            f"elapsed={metrics['elapsed_seconds']:.1f}s",
            flush=True,
        )
    ranked_selection = sorted(selection.items(), key=ranking_key, reverse=True)
    confirmation_names = [
        name for name, _ in ranked_selection[: args.confirmation_count]
    ]
    by_name = {candidate.name: candidate for candidate in candidate_list}
    confirmation: dict[str, dict[str, object]] = {}
    print(f"confirmation candidates={confirmation_names}", flush=True)
    for name in confirmation_names:
        confirmation[name] = evaluate_candidate(
            data, by_name[name], CONFIRMATION_SEEDS
        )
        value = confirmation[name]
        print(
            f"confirmation {name:42s} macro={value['macro_f1_mean']:.4f} "
            f"accuracy={value['accuracy_mean']:.4f}",
            flush=True,
        )
    selected_name = max(confirmation.items(), key=ranking_key)[0]
    final = evaluate_candidate(data, by_name[selected_name], FINAL_SEEDS)
    baseline_final = baseline["final"]["classwise"]
    macro_gain = float(final["macro_f1_mean"] - baseline_final["macro_f1_mean"])
    accuracy_gain = float(final["accuracy_mean"] - baseline_final["accuracy_mean"])
    robust_gain = macro_gain >= 0.01 and accuracy_gain >= -0.005
    result = {
        "schema": "stem-slicer-category-architecture-benchmark-v1",
        "protocol": {
            "selection_seeds": list(SELECTION_SEEDS),
            "confirmation_seeds": list(CONFIRMATION_SEEDS),
            "final_seeds": list(FINAL_SEEDS),
            "folds": 4,
            "grouped_by_source_loop": True,
            "auxiliary_never_scored": True,
            "candidate_count": len(candidate_list),
            "confirmation_count": len(confirmation_names),
            "selection_rule": "macro-F1 then accuracy",
            "robust_gain_rule": "final macro-F1 gain >= 0.01 and accuracy loss <= 0.005",
        },
        "baseline": {
            "selection": baseline["selection"]["classwise"],
            "confirmation": baseline["confirmation"]["classwise"],
            "final": baseline_final,
        },
        "selection": selection,
        "selection_ranking": [name for name, _ in ranked_selection],
        "confirmation": confirmation,
        "selected_for_final": selected_name,
        "final": final,
        "final_gain": {
            "macro_f1": macro_gain,
            "accuracy": accuracy_gain,
            "robust": robust_gain,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"selected_for_final={selected_name} macro={final['macro_f1_mean']:.4f} "
        f"accuracy={final['accuracy_mean']:.4f}",
        flush=True,
    )
    print(
        f"baseline_final macro={baseline_final['macro_f1_mean']:.4f} "
        f"accuracy={baseline_final['accuracy_mean']:.4f}",
        flush=True,
    )
    print(
        f"gain macro={macro_gain:+.4f} accuracy={accuracy_gain:+.4f} "
        f"robust={robust_gain}",
        flush=True,
    )
    print(f"Wrote {output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
