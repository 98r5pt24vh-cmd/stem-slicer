#!/usr/bin/env python3
"""Build an aligned v3 research dataset from a frozen Finder review."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import numpy as np

from export_category_review import CATEGORIES


V2_FEATURE_ID = "mert-dsp:c0af6eae387f84d1a5dbebb2f7162f15f2ff261a11f7a8b43c3867f88dff6b2d"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reviewed-truth", type=Path, required=True)
    parser.add_argument("--original-root", type=Path, required=True)
    parser.add_argument("--feature-db", type=Path, required=True)
    parser.add_argument("--library-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_v2_vectors(database_path: Path) -> dict[str, np.ndarray]:
    connection = sqlite3.connect(f"file:{database_path.resolve(strict=True)}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            """
            SELECT audio_sha256, dtype, dimension, vector_blob, vector_sha256
            FROM feature_vectors
            WHERE feature_extractor_id = ?
            """,
            (V2_FEATURE_ID,),
        ).fetchall()
    finally:
        connection.close()
    result: dict[str, np.ndarray] = {}
    for sha256, dtype, dimension, blob, vector_sha256 in rows:
        if dtype != "<f4" or dimension != 1600 or len(blob) != 6400:
            raise RuntimeError(f"Invalid cached v2 vector for {sha256}")
        if hashlib.sha256(blob).hexdigest() != vector_sha256:
            raise RuntimeError(f"Cached v2 vector hash mismatch for {sha256}")
        result[str(sha256)] = np.frombuffer(blob, dtype="<f4").copy()
    return result


def read_library_groups(database_path: Path) -> dict[str, str]:
    connection = sqlite3.connect(f"file:{database_path.resolve(strict=True)}?mode=ro", uri=True)
    try:
        rows = connection.execute("SELECT sha256, source_loop_id FROM layer_cache").fetchall()
    finally:
        connection.close()
    return {str(sha256): str(group) for sha256, group in rows}


def main() -> int:
    args = parse_args()
    output = args.output.expanduser().resolve(strict=False)
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    output.mkdir(parents=True)

    original_root = args.original_root.expanduser().resolve(strict=True)
    with (original_root / "manifest.csv").open(encoding="utf-8", newline="") as stream:
        original_rows = list(csv.DictReader(stream))
    original_by_hash = {row["sha256"]: (index, row) for index, row in enumerate(original_rows)}
    old_mean = np.load(original_root / "outputs/mert95/mean.npy")[:, 6, :]
    old_std = np.load(original_root / "outputs/mert95/std.npy")[:, 6, :]
    old_dsp = np.load(original_root / "dsp_features.npz")["features"]
    if not (len(original_rows) == len(old_mean) == len(old_std) == len(old_dsp)):
        raise RuntimeError("Original manifest and feature arrays are misaligned")

    reviewed_path = args.reviewed_truth.expanduser().resolve(strict=True)
    with reviewed_path.open(encoding="utf-8-sig", newline="") as stream:
        reviewed_rows = list(csv.DictReader(stream, delimiter=";"))
    if len(reviewed_rows) < 1:
        raise RuntimeError("Reviewed truth is empty")

    v2_vectors = read_v2_vectors(args.feature_db)
    library_groups = read_library_groups(args.library_db)
    old_group_mappings: dict[str, set[str]] = defaultdict(set)
    for row in original_rows:
        if row["split_role"] != "gold_layer":
            continue
        active_group = library_groups.get(row["sha256"])
        if active_group:
            old_group_mappings[row["source_group"]].add(active_group)
    ambiguous = {group: values for group, values in old_group_mappings.items() if len(values) > 1}
    if ambiguous:
        raise RuntimeError(f"Original source groups map to multiple active loops: {ambiguous!r}")

    def canonical_gold_group(reviewed: dict[str, str]) -> str:
        if reviewed["origin_set"] == "candidate":
            return f"loop:{reviewed['source_group']}"
        original = original_by_hash[reviewed["sha256"]][1]
        mapped = old_group_mappings.get(original["source_group"])
        if mapped:
            return f"loop:{next(iter(mapped))}"
        return f"legacy:{original['source_group'].casefold()}"

    manifest_rows: list[dict[str, str]] = []
    mean_rows: list[np.ndarray] = []
    std_rows: list[np.ndarray] = []
    dsp_rows: list[np.ndarray] = []

    for reviewed in reviewed_rows:
        label = reviewed["final_label"]
        if label not in CATEGORIES:
            raise RuntimeError(f"Unknown reviewed label: {label}")
        sha256 = reviewed["sha256"]
        original_entry = original_by_hash.get(sha256)
        if original_entry is not None:
            index, _ = original_entry
            mean, std, dsp = old_mean[index], old_std[index], old_dsp[index]
        else:
            vector = v2_vectors.get(sha256)
            if vector is None:
                raise RuntimeError(f"Missing v2 feature vector for reviewed audio {sha256}")
            mean, std, dsp = vector[:768], vector[768:1536], vector[1536:]
        manifest_rows.append(
            {
                "source_group": canonical_gold_group(reviewed),
                "file": reviewed["filename"],
                "label": label,
                "sha256": sha256,
                "split_role": "gold_layer",
                "origin": f"user_review_2026-08-27:{reviewed['origin_set']}",
                "producer": "reviewed_user",
                "origin_set": reviewed["origin_set"],
                "previous_label": reviewed["previous_label"],
                "model_score": reviewed["model_score"],
                "audio_path": reviewed["reviewed_audio_path"],
                "eligible_for_generation": "false",
            }
        )
        mean_rows.append(np.asarray(mean, dtype=np.float32))
        std_rows.append(np.asarray(std, dtype=np.float32))
        dsp_rows.append(np.asarray(dsp, dtype=np.float32))

    for index, row in enumerate(original_rows):
        if row["split_role"] != "auxiliary_training_only" or row["label"] != "Vocal Chop":
            continue
        if row["sha256"] in {item["sha256"] for item in manifest_rows}:
            raise RuntimeError(f"Auxiliary audio overlaps reviewed truth: {row['sha256']}")
        manifest_rows.append(
            {
                "source_group": f"aux:{row['source_group']}",
                "file": row["file"],
                "label": row["label"],
                "sha256": row["sha256"],
                "split_role": row["split_role"],
                "origin": row["origin"],
                "producer": row["producer"],
                "origin_set": "auxiliary",
                "previous_label": row["label"],
                "model_score": "",
                "audio_path": str((original_root / row["audio_path"]).resolve(strict=True)),
                "eligible_for_generation": "false",
            }
        )
        mean_rows.append(np.asarray(old_mean[index], dtype=np.float32))
        std_rows.append(np.asarray(old_std[index], dtype=np.float32))
        dsp_rows.append(np.asarray(old_dsp[index], dtype=np.float32))

    fieldnames = tuple(manifest_rows[0])
    with (output / "manifest.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(manifest_rows)
    np.save(output / "mean.npy", np.stack(mean_rows))
    np.save(output / "std.npy", np.stack(std_rows))
    np.savez_compressed(output / "dsp_features.npz", features=np.stack(dsp_rows))

    gold = [row for row in manifest_rows if row["split_role"] == "gold_layer"]
    auxiliary = [row for row in manifest_rows if row["split_role"] == "auxiliary_training_only"]
    metadata = {
        "schema": "stem-slicer-layer-role-review-dataset-v1",
        "reviewed_truth_source": str(reviewed_path),
        "reviewed_truth_sha256": sha256_file(reviewed_path),
        "feature_extractor_id": V2_FEATURE_ID,
        "rows": len(manifest_rows),
        "gold_rows": len(gold),
        "gold_groups": len({row["source_group"] for row in gold}),
        "new_candidate_rows": sum(row["origin_set"] == "candidate" for row in gold),
        "auxiliary_rows": len(auxiliary),
        "dimensions": {"mean": 768, "std": 768, "dsp": 64},
    }
    (output / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
