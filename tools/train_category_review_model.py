#!/usr/bin/env python3
"""Train a research-only v3 layer-role artifact from reviewed truth."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import warnings
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from category_taxonomy import TRAINABLE_CATEGORIES
from evaluate_category_review_model import balanced_training_weights


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from layer_role_classifier import LayerRoleScoreEnsemble  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--runtime-metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def model_digest(models: tuple[object, ...], temporal_classes: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for model in models:
        scaler = model.named_steps["standardscaler"]
        head = model.named_steps["logisticregression"]
        for value in (
            scaler.mean_,
            scaler.scale_,
            head.classes_.astype("U"),
            head.coef_,
            head.intercept_,
        ):
            array = np.ascontiguousarray(value)
            digest.update(str(array.dtype).encode("ascii"))
            digest.update(str(array.shape).encode("ascii"))
            digest.update(array.tobytes())
    digest.update("\0".join(temporal_classes).encode("utf-8"))
    return digest.hexdigest()


def fit(
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


def main() -> int:
    args = parse_args()
    dataset = args.dataset.expanduser().resolve(strict=True)
    evaluation_path = args.evaluation.expanduser().resolve(strict=True)
    runtime_metadata_path = args.runtime_metadata.expanduser().resolve(strict=True)
    output = args.output.expanduser().resolve(strict=False)
    sidecar_output = output.with_suffix(".json")
    if output.exists() or sidecar_output.exists():
        raise FileExistsError("Refusing to replace an existing v3 research artifact")

    with (dataset / "manifest.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    mean = np.load(dataset / "mean.npy")
    std = np.load(dataset / "std.npy")
    dsp = np.load(dataset / "dsp_features.npz")["features"]
    if not (len(rows) == len(mean) == len(std) == len(dsp)):
        raise RuntimeError("Manifest and feature matrices are not aligned")

    labels_all = np.asarray([row["label"] for row in rows], dtype=str)
    roles_all = np.asarray([row["split_role"] for row in rows], dtype=str)
    producers_all = np.asarray([row["producer"] for row in rows], dtype=str)
    groups_all = np.asarray([row["source_group"] for row in rows], dtype=str)
    scope = np.asarray(TRAINABLE_CATEGORIES, dtype=str)
    selected = np.isin(labels_all, scope) & (
        (roles_all == "gold_layer")
        | ((roles_all == "auxiliary_training_only") & (labels_all == "Vocal Chop"))
    )
    indices = np.flatnonzero(selected)
    labels = labels_all[indices]
    roles = roles_all[indices]
    producers = producers_all[indices]
    groups = groups_all[indices]
    weights = balanced_training_weights(labels, roles, producers, groups, 0.05)

    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    base_c = float(evaluation["selection"]["selected_base_c"])
    temporal_c = float(evaluation["selection"]["selected_temporal_c"])
    temporal_classes = tuple(
        str(value) for value in evaluation["selection"]["selected_temporal_classes"]
    )
    base_matrix = np.concatenate([mean[indices], dsp[indices]], axis=1)
    temporal_matrix = np.concatenate([mean[indices], std[indices], dsp[indices]], axis=1)
    base_model = fit(base_matrix, labels, weights, base_c)
    temporal_model = fit(temporal_matrix, labels, weights, temporal_c)
    ensemble = LayerRoleScoreEnsemble(
        base_model,
        temporal_model,
        temporal_classes,
        mert_dimension=mean.shape[1],
        dsp_dimension=dsp.shape[1],
    )
    if tuple(str(value) for value in ensemble.classes_) != tuple(sorted(TRAINABLE_CATEGORIES)):
        raise RuntimeError("Trained class order does not match the v3 taxonomy")

    digest = model_digest((base_model, temporal_model), temporal_classes)
    runtime_metadata = json.loads(runtime_metadata_path.read_text(encoding="utf-8"))
    metadata = {
        "schema": "stem-slicer-layer-role-head-v3-research",
        "version": f"layer-roles-v3-{digest[:16]}",
        "status": "research_candidate_not_deployed",
        "classes": [str(value) for value in ensemble.classes_],
        "feature_extractor_id": runtime_metadata["feature_extractor_id"],
        "feature_extractor": runtime_metadata["feature_extractor"],
        "mert": runtime_metadata["mert"],
        "dsp_dimension": runtime_metadata["dsp_dimension"],
        "dsp_feature_names": runtime_metadata["dsp_feature_names"],
        "head_id": f"classwise-ensemble:{digest}",
        "head": {
            "kind": "classwise ensemble of two StandardScaler + multinomial LogisticRegression heads",
            "base_C": base_c,
            "temporal_C": temporal_c,
            "solver": "newton-cg",
            "base_features": "MERT mean + DSP64",
            "temporal_features": "MERT mean + population std + DSP64",
            "temporal_score_classes": list(temporal_classes),
            "score_combination": "replace selected class columns then renormalize",
            "probabilities_calibrated": False,
        },
        "taxonomy": {
            "categories": list(TRAINABLE_CATEGORIES),
            "changes_from_v2": [
                "added Piano",
                "merged Rhythmic Pluck into Pluck",
                "kept Perc Drums outside the melodic model",
            ],
        },
        "training": {
            "manifest_sha256": sha256_file(dataset / "manifest.csv"),
            "rows": int(len(indices)),
            "gold_rows": int(np.sum(roles == "gold_layer")),
            "auxiliary_rows": int(np.sum(roles == "auxiliary_training_only")),
            "gold_source_groups": int(len(set(groups[roles == "gold_layer"]))),
            "auxiliary_class_fraction": 0.05,
        },
        "validation": {
            "protocol": evaluation["protocol"],
            "selection": evaluation["selection"]["classwise"],
            "confirmation": evaluation["confirmation"]["classwise"],
            "final": evaluation["final"]["classwise"],
            "current_v2_candidate_challenge": evaluation[
                "current_v2_candidate_challenge"
            ],
            "v3_final_candidate_challenge": evaluation[
                "final_candidate_challenge"
            ]["classwise"],
            "evidence": str(evaluation_path),
        },
        "compatibility": {
            "python": (
                f"{sys.version_info.major}.{sys.version_info.minor}."
                f"{sys.version_info.micro}"
            ),
            "sklearn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": ensemble, "metadata": metadata}, output, compress=3)
    sidecar = dict(metadata)
    sidecar["artifact_sha256"] = sha256_file(output)
    sidecar_output.write_text(
        json.dumps(sidecar, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    loaded = joblib.load(output)
    probe = np.zeros((1, ensemble.n_features_in_), dtype=np.float32)
    scores = loaded["model"].predict_proba(probe)
    if scores.shape != (1, len(TRAINABLE_CATEGORIES)) or not np.isclose(scores.sum(), 1.0):
        raise RuntimeError("Serialized v3 artifact failed its probability smoke test")
    print(
        json.dumps(
            {
                "artifact": str(output),
                "artifact_sha256": sidecar["artifact_sha256"],
                "version": metadata["version"],
                "status": metadata["status"],
                "gold_rows": metadata["training"]["gold_rows"],
                "gold_source_groups": metadata["training"]["gold_source_groups"],
                "temporal_score_classes": list(temporal_classes),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
