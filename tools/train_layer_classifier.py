#!/usr/bin/env python3
"""Train the small, versioned classification head used by the prototype.

MERT remains frozen.  This script consumes the audited benchmark cache and
trains only the lightweight scaler/logistic head.  Categories without at
least five independent source loops are deliberately excluded from automatic
prediction; manual truth remains available to the library scanner for all
nineteen product categories.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


MODEL_VERSION = "mert95-state6-mean-dsp64-logreg-c003-v0"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dsp", type=Path, required=True)
    parser.add_argument("--mert-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with args.manifest.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    labels_all = np.asarray([row["label"] for row in rows], dtype=str)
    groups_all = np.asarray([row["source"] for row in rows], dtype=str)
    files_all = np.asarray([row["file"] for row in rows], dtype=str)

    counts = Counter(labels_all)
    loop_sets: dict[str, set[str]] = defaultdict(set)
    for label, group in zip(labels_all, groups_all):
        loop_sets[label].add(group)
    classes = sorted(
        label
        for label in counts
        if counts[label] >= 5 and len(loop_sets[label]) >= 5
    )
    mask = np.isin(labels_all, classes)

    dsp_archive = np.load(args.dsp, allow_pickle=False)
    if not np.array_equal(files_all, dsp_archive["files"].astype(str)):
        raise RuntimeError("DSP features and manifest are not aligned.")
    dsp = np.asarray(dsp_archive["features"], dtype=np.float32)
    feature_names = dsp_archive["feature_names"].astype(str).tolist()

    mert_metadata_path = args.mert_dir / "metadata.json"
    mert_metadata = json.loads(mert_metadata_path.read_text(encoding="utf-8"))
    completed = np.load(args.mert_dir / "completed.npy", mmap_mode="r")
    mean = np.load(args.mert_dir / "mean.npy", mmap_mode="r")
    if mean.shape[0] != len(rows) or not completed.all():
        raise RuntimeError("MERT cache is incomplete or misaligned.")
    state = int(mert_metadata["priority_state_index"])
    kept = list(mert_metadata["kept_state_indices"])
    local_index = kept.index(state)
    mert = np.asarray(mean[:, local_index], dtype=np.float32)

    features = np.concatenate([mert, dsp], axis=1)
    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(
            C=0.03,
            class_weight="balanced",
            max_iter=5000,
            solver="lbfgs",
            tol=1e-4,
        ),
    )
    model.fit(features[mask], labels_all[mask])

    unsupported = sorted(set(labels_all) - set(classes))
    payload = {
        "model": model,
        "metadata": {
            "version": MODEL_VERSION,
            "classes": classes,
            "unsupported_automatic_categories": unsupported,
            "training_layers": int(mask.sum()),
            "training_source_loops": int(len(set(groups_all[mask]))),
            "mert": {
                "model_id": mert_metadata["model_id"],
                "revision": mert_metadata["revision"],
                "sample_rate": int(mert_metadata["sample_rate"]),
                "max_window_seconds": float(
                    mert_metadata["max_window_seconds"]
                ),
                "state_index": state,
                "dimension": int(mert_metadata["dimension"]),
            },
            "dsp_feature_names": feature_names,
            "dsp_dimension": int(dsp.shape[1]),
            "head": {
                "kind": "StandardScaler + balanced multinomial LogisticRegression",
                "C": 0.03,
                "probabilities_calibrated": False,
            },
            "corpus": {
                "manifest_sha256": sha256_file(args.manifest),
                "rows": len(rows),
            },
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(payload, args.output, compress=3)
    metadata_path = args.output.with_suffix(".json")
    metadata_path.write_text(
        json.dumps(payload["metadata"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["metadata"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
