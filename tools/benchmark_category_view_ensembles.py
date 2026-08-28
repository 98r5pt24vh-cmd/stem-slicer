#!/usr/bin/env python3
"""Leakage-safe benchmark of complementary category feature views."""

from __future__ import annotations

import argparse
import json
import time
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from category_taxonomy import TRAINABLE_CATEGORIES
from evaluate_category_review_model import (
    CONFIRMATION_SEEDS,
    FINAL_SEEDS,
    SELECTION_SEEDS,
    balanced_training_weights,
    load_dataset,
)


C_VALUES = (0.003, 0.01, 0.03, 0.1)
BLEND_VALUES = (0.25, 0.5, 0.75)
CLASSWISE_MARGINS = (0.0, 0.005, 0.01, 0.02)


@dataclass(frozen=True)
class Recipe:
    name: str
    kind: str
    payload: dict[str, object]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--baseline-evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirmation-count", type=int, default=6)
    return parser.parse_args()


def load_views(dataset: Path) -> tuple[dict[str, object], dict[str, np.ndarray]]:
    data = load_dataset(dataset)
    mean = np.load(dataset / "mean.npy").astype(np.float64)
    std = np.load(dataset / "std.npy").astype(np.float64)
    dsp = np.load(dataset / "dsp_features.npz")["features"].astype(np.float64)
    views = {
        "mean": mean,
        "std": std,
        "dsp": dsp,
        "mean_std": np.concatenate([mean, std], axis=1),
        "base": np.concatenate([mean, dsp], axis=1),
        "std_dsp": np.concatenate([std, dsp], axis=1),
        "temporal": np.concatenate([mean, std, dsp], axis=1),
    }
    return data, views


def ordered_probabilities(
    model: object, matrix: np.ndarray, scope: np.ndarray
) -> np.ndarray:
    raw = model.predict_proba(matrix)
    classes = model.classes_.astype(str)
    order = [int(np.flatnonzero(classes == label)[0]) for label in scope]
    return raw[:, order]


def oof_probabilities(
    data: dict[str, object],
    matrix: np.ndarray,
    c_value: float,
    seeds: tuple[int, ...],
) -> np.ndarray:
    labels = data["labels"]
    groups = data["groups"]
    roles = data["roles"]
    producers = data["producers"]
    scope = np.asarray(TRAINABLE_CATEGORIES, dtype=str)
    gold = np.flatnonzero((roles == "gold_layer") & np.isin(labels, scope))
    auxiliary = np.flatnonzero(
        (roles == "auxiliary_training_only") & np.isin(labels, scope)
    )
    probabilities = np.zeros((len(seeds), len(gold), len(scope)), dtype=np.float64)
    for seed_index, seed in enumerate(seeds):
        splitter = StratifiedGroupKFold(n_splits=4, shuffle=True, random_state=seed)
        for local_train, local_test in splitter.split(
            matrix[gold], labels[gold], groups[gold]
        ):
            train = np.concatenate([gold[local_train], auxiliary])
            weights = balanced_training_weights(
                labels[train], roles[train], producers[train], groups[train]
            )
            model = make_pipeline(
                StandardScaler(),
                LogisticRegression(
                    C=c_value,
                    max_iter=2500,
                    solver="newton-cg",
                    tol=1e-5,
                ),
            )
            with warnings.catch_warnings():
                warnings.filterwarnings("error", category=ConvergenceWarning)
                model.fit(
                    matrix[train],
                    labels[train],
                    logisticregression__sample_weight=weights,
                )
            probabilities[seed_index, local_test] = ordered_probabilities(
                model, matrix[gold[local_test]], scope
            )
    return probabilities


def metrics(data: dict[str, object], probabilities: np.ndarray) -> dict[str, object]:
    labels = data["labels"]
    roles = data["roles"]
    origin_sets = data["origin_sets"]
    scope = np.asarray(TRAINABLE_CATEGORIES, dtype=str)
    gold = np.flatnonzero((roles == "gold_layer") & np.isin(labels, scope))
    truth = labels[gold]
    predicted = scope[np.argmax(probabilities, axis=2)]
    macro = [
        float(f1_score(truth, row, labels=scope, average="macro", zero_division=0))
        for row in predicted
    ]
    accuracy = [float(accuracy_score(truth, row)) for row in predicted]
    flat_truth = np.tile(truth, len(probabilities))
    flat_predicted = predicted.reshape(-1)
    report = classification_report(
        flat_truth,
        flat_predicted,
        labels=scope,
        output_dict=True,
        zero_division=0,
    )
    challenge = np.flatnonzero(origin_sets[gold] == "candidate")
    challenge_truth = truth[challenge]
    challenge_predicted = predicted[:, challenge]
    return {
        "macro_f1_mean": float(np.mean(macro)),
        "macro_f1_std": float(np.std(macro)),
        "accuracy_mean": float(np.mean(accuracy)),
        "per_seed_macro_f1": macro,
        "per_seed_accuracy": accuracy,
        "per_class_f1": {
            label: float(report[label]["f1-score"]) for label in scope
        },
        "candidate_challenge": {
            "rows": int(len(challenge)),
            "macro_f1_mean": float(
                np.mean(
                    [
                        f1_score(
                            challenge_truth,
                            row,
                            labels=scope,
                            average="macro",
                            zero_division=0,
                        )
                        for row in challenge_predicted
                    ]
                )
            ),
            "accuracy_mean": float(
                np.mean(
                    [accuracy_score(challenge_truth, row) for row in challenge_predicted]
                )
            ),
        },
    }


def normalize(probabilities: np.ndarray) -> np.ndarray:
    totals = probabilities.sum(axis=2, keepdims=True)
    if np.any(totals <= 0.0):
        raise RuntimeError("Cannot normalize zero category scores")
    return probabilities / totals


def apply_recipe(
    recipe: Recipe, probability_sets: dict[str, np.ndarray]
) -> np.ndarray:
    if recipe.kind == "single":
        return probability_sets[str(recipe.payload["view"])]
    if recipe.kind == "blend":
        left = probability_sets[str(recipe.payload["left"])]
        right = probability_sets[str(recipe.payload["right"])]
        alpha = float(recipe.payload["right_weight"])
        return normalize((1.0 - alpha) * left + alpha * right)
    if recipe.kind == "classwise":
        default = str(recipe.payload["default"])
        sources = dict(recipe.payload["sources"])
        combined = probability_sets[default].copy()
        for index, label in enumerate(TRAINABLE_CATEGORIES):
            combined[:, :, index] = probability_sets[str(sources[label])][:, :, index]
        return normalize(combined)
    raise ValueError(f"Unknown recipe kind: {recipe.kind}")


def ranking_key(item: tuple[str, dict[str, object]]) -> tuple[float, float]:
    value = item[1]
    return float(value["macro_f1_mean"]), float(value["accuracy_mean"])


def main() -> int:
    args = parse_args()
    dataset = args.dataset.expanduser().resolve(strict=True)
    output = args.output.expanduser().resolve(strict=False)
    if output.exists():
        raise FileExistsError(f"Refusing to replace existing result: {output}")
    data, views = load_views(dataset)
    baseline = json.loads(
        args.baseline_evaluation.expanduser().resolve(strict=True).read_text(
            encoding="utf-8"
        )
    )

    started = time.perf_counter()
    selection_probabilities: dict[str, np.ndarray] = {}
    view_selection: dict[str, object] = {}
    for view_name, matrix in views.items():
        by_c: dict[str, dict[str, object]] = {}
        by_c_probabilities: dict[str, np.ndarray] = {}
        for c_value in C_VALUES:
            probabilities = oof_probabilities(data, matrix, c_value, SELECTION_SEEDS)
            by_c_probabilities[str(c_value)] = probabilities
            by_c[str(c_value)] = metrics(data, probabilities)
        selected_c = max(by_c, key=lambda key: ranking_key((key, by_c[key])))
        selection_probabilities[view_name] = by_c_probabilities[selected_c]
        view_selection[view_name] = {
            "selected_c": float(selected_c),
            "by_c": by_c,
            "selected": by_c[selected_c],
        }
        print(
            f"view {view_name:10s} C={selected_c:5s} "
            f"macro={by_c[selected_c]['macro_f1_mean']:.4f} "
            f"accuracy={by_c[selected_c]['accuracy_mean']:.4f}",
            flush=True,
        )

    recipes: list[Recipe] = [
        Recipe(f"single_{name}", "single", {"view": name}) for name in views
    ]
    view_names = list(views)
    for left_index, left in enumerate(view_names):
        for right in view_names[left_index + 1 :]:
            for alpha in BLEND_VALUES:
                recipes.append(
                    Recipe(
                        f"blend_{left}_{right}_{alpha:g}",
                        "blend",
                        {"left": left, "right": right, "right_weight": alpha},
                    )
                )

    selected_view_metrics = {
        name: metrics(data, probabilities)
        for name, probabilities in selection_probabilities.items()
    }
    default = max(selected_view_metrics.items(), key=ranking_key)[0]
    for margin in CLASSWISE_MARGINS:
        sources: dict[str, str] = {}
        for label in TRAINABLE_CATEGORIES:
            best = max(
                selected_view_metrics,
                key=lambda name: selected_view_metrics[name]["per_class_f1"][label],
            )
            improvement = (
                selected_view_metrics[best]["per_class_f1"][label]
                - selected_view_metrics[default]["per_class_f1"][label]
            )
            sources[label] = best if improvement > margin else default
        recipes.append(
            Recipe(
                f"classwise_margin_{margin:g}",
                "classwise",
                {"default": default, "margin": margin, "sources": sources},
            )
        )

    legacy_sources = {label: "base" for label in TRAINABLE_CATEGORIES}
    for label in TRAINABLE_CATEGORIES:
        improvement = (
            selected_view_metrics["temporal"]["per_class_f1"][label]
            - selected_view_metrics["base"]["per_class_f1"][label]
        )
        if improvement > 0.01:
            legacy_sources[label] = "temporal"
    recipes.append(
        Recipe(
            "legacy_base_temporal_classwise",
            "classwise",
            {"default": "base", "margin": 0.01, "sources": legacy_sources},
        )
    )

    selection: dict[str, dict[str, object]] = {}
    by_name = {recipe.name: recipe for recipe in recipes}
    for recipe in recipes:
        selection[recipe.name] = metrics(
            data, apply_recipe(recipe, selection_probabilities)
        )
    ranked_selection = sorted(selection.items(), key=ranking_key, reverse=True)
    confirmation_names = [
        name for name, _ in ranked_selection[: args.confirmation_count]
    ]
    required_views = sorted(
        {
            source
            for name in confirmation_names
            for source in (
                [str(by_name[name].payload["view"])]
                if by_name[name].kind == "single"
                else (
                    [
                        str(by_name[name].payload["left"]),
                        str(by_name[name].payload["right"]),
                    ]
                    if by_name[name].kind == "blend"
                    else list(dict(by_name[name].payload["sources"]).values())
                )
            )
        }
    )
    confirmation_probabilities: dict[str, np.ndarray] = {}
    final_probabilities: dict[str, np.ndarray] = {}
    for name in required_views:
        c_value = float(view_selection[name]["selected_c"])
        confirmation_probabilities[name] = oof_probabilities(
            data, views[name], c_value, CONFIRMATION_SEEDS
        )
        final_probabilities[name] = oof_probabilities(
            data, views[name], c_value, FINAL_SEEDS
        )
    confirmation = {
        name: metrics(
            data, apply_recipe(by_name[name], confirmation_probabilities)
        )
        for name in confirmation_names
    }
    selected_name = max(confirmation.items(), key=ranking_key)[0]
    final = metrics(
        data, apply_recipe(by_name[selected_name], final_probabilities)
    )
    baseline_final = baseline["final"]["classwise"]
    macro_gain = float(final["macro_f1_mean"] - baseline_final["macro_f1_mean"])
    accuracy_gain = float(final["accuracy_mean"] - baseline_final["accuracy_mean"])
    robust = macro_gain >= 0.01 and accuracy_gain >= -0.005
    result = {
        "schema": "stem-slicer-category-view-ensemble-benchmark-v1",
        "protocol": {
            "selection_seeds": list(SELECTION_SEEDS),
            "confirmation_seeds": list(CONFIRMATION_SEEDS),
            "final_seeds": list(FINAL_SEEDS),
            "folds": 4,
            "grouped_by_source_loop": True,
            "auxiliary_never_scored": True,
            "views": list(views),
            "c_values": list(C_VALUES),
            "recipe_count": len(recipes),
            "confirmation_count": len(confirmation_names),
            "robust_gain_rule": "final macro-F1 gain >= 0.01 and accuracy loss <= 0.005",
        },
        "baseline_final": baseline_final,
        "view_selection": view_selection,
        "selection": selection,
        "selection_ranking": [name for name, _ in ranked_selection],
        "recipes": {
            name: {"kind": recipe.kind, "payload": recipe.payload}
            for name, recipe in by_name.items()
        },
        "confirmation": confirmation,
        "selected_for_final": selected_name,
        "final": final,
        "final_gain": {
            "macro_f1": macro_gain,
            "accuracy": accuracy_gain,
            "robust": robust,
        },
        "elapsed_seconds": float(time.perf_counter() - started),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"selection_top={confirmation_names}", flush=True)
    for name in confirmation_names:
        value = confirmation[name]
        print(
            f"confirmation {name:45s} macro={value['macro_f1_mean']:.4f} "
            f"accuracy={value['accuracy_mean']:.4f}",
            flush=True,
        )
    print(
        f"selected_for_final={selected_name} macro={final['macro_f1_mean']:.4f} "
        f"accuracy={final['accuracy_mean']:.4f}",
        flush=True,
    )
    print(
        f"gain macro={macro_gain:+.4f} accuracy={accuracy_gain:+.4f} robust={robust}",
        flush=True,
    )
    print(f"Wrote {output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
