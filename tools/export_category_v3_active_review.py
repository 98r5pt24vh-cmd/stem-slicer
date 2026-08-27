#!/usr/bin/env python3
"""Export a difficult V3 review batch without rescanning or copying audio."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np

from category_taxonomy import TRAINABLE_CATEGORIES
from export_category_review import unique_destination


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


@dataclass(frozen=True)
class Candidate:
    target_category: str
    predicted_category: str
    prediction_confidence: float
    target_score: float
    target_rank: int
    top_margin: float
    source_group: str
    filename: str
    audio_path: Path
    sha256: str
    rank: tuple[object, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reviewed-truth", type=Path, required=True)
    parser.add_argument("--quality-rejects", type=Path, required=True)
    parser.add_argument("--out-of-scope", type=Path)
    parser.add_argument("--library-db", type=Path, required=True)
    parser.add_argument("--feature-db", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit-per-category", type=int, default=50)
    parser.add_argument("--maximum-target-rank", type=int, default=4)
    parser.add_argument("--minimum-target-score", type=float, default=0.05)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def read_semicolon_rows(path: Path) -> list[dict[str, str]]:
    with path.expanduser().resolve(strict=True).open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream, delimiter=";"))
    if not rows:
        raise RuntimeError(f"Manifest is empty: {path}")
    return rows


def read_library(path: Path) -> list[tuple[str, str, str, str]]:
    database = path.expanduser().resolve(strict=True)
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        return [
            (str(audio_path), str(filename), str(group), str(sha256).lower())
            for audio_path, filename, group, sha256 in connection.execute(
                """
                SELECT path, filename, source_loop_id, sha256
                FROM layer_cache
                ORDER BY path ASC
                """
            )
        ]
    finally:
        connection.close()


def read_features(
    path: Path, extractor_id: str, expected_dimension: int
) -> dict[str, np.ndarray]:
    database = path.expanduser().resolve(strict=True)
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            """
            SELECT audio_sha256, dimension, dtype, vector_blob
            FROM feature_vectors
            WHERE feature_extractor_id = ?
            """,
            (extractor_id,),
        ).fetchall()
    finally:
        connection.close()
    result: dict[str, np.ndarray] = {}
    for sha256, dimension, dtype, blob in rows:
        if int(dimension) != expected_dimension:
            raise RuntimeError(
                f"Unexpected feature dimension {dimension}; expected {expected_dimension}"
            )
        vector = np.frombuffer(blob, dtype=np.dtype(str(dtype)))
        if len(vector) != expected_dimension or not np.isfinite(vector).all():
            raise RuntimeError(f"Invalid cached feature vector: {sha256}")
        result[str(sha256).lower()] = vector.copy()
    return result


def score_candidates(
    library_rows: list[tuple[str, str, str, str]],
    features: dict[str, np.ndarray],
    model: object,
    excluded_hashes: set[str],
    excluded_groups: set[str],
    maximum_target_rank: int,
    minimum_target_score: float,
) -> dict[str, list[Candidate]]:
    usable_rows: list[tuple[Path, str, str, str]] = []
    vectors: list[np.ndarray] = []
    for raw_path, filename, source_group, sha256 in library_rows:
        audio_path = Path(raw_path).expanduser()
        if (
            sha256 in excluded_hashes
            or source_group in excluded_groups
            or sha256 not in features
            or not audio_path.is_file()
        ):
            continue
        usable_rows.append((audio_path.resolve(strict=True), filename, source_group, sha256))
        vectors.append(features[sha256])
    if not vectors:
        raise RuntimeError("No unreviewed cached feature vectors are available")

    probabilities = model.predict_proba(np.stack(vectors))
    classes = np.asarray([str(value) for value in model.classes_], dtype=str)
    if tuple(classes) != tuple(sorted(TRAINABLE_CATEGORIES)):
        raise RuntimeError("Model taxonomy does not match the current review taxonomy")
    ordered = np.argsort(-probabilities, axis=1)
    pools: dict[str, list[Candidate]] = defaultdict(list)
    for row_index, (audio_path, filename, source_group, sha256) in enumerate(usable_rows):
        scores = probabilities[row_index]
        predicted_index = int(ordered[row_index, 0])
        second_index = int(ordered[row_index, 1])
        prediction_confidence = float(scores[predicted_index])
        top_margin = float(scores[predicted_index] - scores[second_index])
        for target_index, target_category in enumerate(classes):
            target_rank = int(np.flatnonzero(ordered[row_index] == target_index)[0]) + 1
            target_score = float(scores[target_index])
            if (
                target_rank > maximum_target_rank
                or target_score < minimum_target_score
            ):
                continue
            best_other = float(np.max(np.delete(scores, target_index)))
            boundary_gap = abs(target_score - best_other)
            pools[target_category].append(
                Candidate(
                    target_category=target_category,
                    predicted_category=str(classes[predicted_index]),
                    prediction_confidence=prediction_confidence,
                    target_score=target_score,
                    target_rank=target_rank,
                    top_margin=top_margin,
                    source_group=source_group,
                    filename=filename,
                    audio_path=audio_path,
                    sha256=sha256,
                    rank=(
                        target_rank,
                        boundary_gap,
                        -target_score,
                        str(audio_path).casefold(),
                    ),
                )
            )
    for category in TRAINABLE_CATEGORIES:
        pools[category].sort(key=lambda candidate: candidate.rank)
    return pools


def select_round_robin(
    pools: dict[str, list[Candidate]], limit_per_category: int
) -> list[Candidate]:
    selected: list[Candidate] = []
    counts: Counter[str] = Counter()
    cursors: Counter[str] = Counter()
    used_hashes: set[str] = set()
    used_groups: set[str] = set()
    progress = True
    while progress and any(
        counts[category] < limit_per_category for category in TRAINABLE_CATEGORIES
    ):
        progress = False
        for category in TRAINABLE_CATEGORIES:
            if counts[category] >= limit_per_category:
                continue
            pool = pools[category]
            while cursors[category] < len(pool):
                candidate = pool[cursors[category]]
                cursors[category] += 1
                if (
                    candidate.sha256 in used_hashes
                    or candidate.source_group in used_groups
                ):
                    continue
                selected.append(candidate)
                used_hashes.add(candidate.sha256)
                used_groups.add(candidate.source_group)
                counts[category] += 1
                progress = True
                break
    return selected


def hard_link(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.link(source, destination)


def export(
    output: Path,
    truth_rows: list[dict[str, str]],
    candidates: list[Candidate],
    *,
    model_version: str,
    limit_per_category: int,
    maximum_target_rank: int,
    minimum_target_score: float,
) -> None:
    output = output.expanduser().resolve(strict=False)
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    truth_root = output / "01 - Corpus vérité"
    review_root = output / "02 - À valider"
    for root in (truth_root, review_root):
        for category in TRAINABLE_CATEGORIES:
            (root / category).mkdir(parents=True, exist_ok=False)

    manifest_rows: list[dict[str, object]] = []
    for row in truth_rows:
        category = row["final_label"]
        source = Path(row["reviewed_audio_path"]).resolve(strict=True)
        destination = unique_destination(truth_root / category, source.name, row["sha256"])
        hard_link(source, destination)
        manifest_rows.append(
            {
                "set": "gold",
                "suggested_category": category,
                "model_score": row["model_score"],
                "source_group": row["source_group"],
                "filename": destination.name,
                "sha256": row["sha256"],
                "original_path": str(source),
                "predicted_category": "",
                "prediction_confidence": "",
                "target_rank": "",
                "top_margin": "",
            }
        )
    for candidate in candidates:
        destination = unique_destination(
            review_root / candidate.target_category,
            candidate.filename,
            candidate.sha256,
        )
        hard_link(candidate.audio_path, destination)
        manifest_rows.append(
            {
                "set": "candidate",
                "suggested_category": candidate.target_category,
                "model_score": f"{candidate.target_score:.6f}",
                "source_group": candidate.source_group,
                "filename": destination.name,
                "sha256": candidate.sha256,
                "original_path": str(candidate.audio_path),
                "predicted_category": candidate.predicted_category,
                "prediction_confidence": f"{candidate.prediction_confidence:.6f}",
                "target_rank": candidate.target_rank,
                "top_margin": f"{candidate.top_margin:.6f}",
            }
        )
    with (output / "manifest.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(
            stream, fieldnames=tuple(manifest_rows[0]), delimiter=";"
        )
        writer.writeheader()
        writer.writerows(manifest_rows)

    truth_counts = Counter(row["final_label"] for row in truth_rows)
    candidate_counts = Counter(row.target_category for row in candidates)
    guide = [
        "CATÉGORISATION IMPROVEMENT — LOT 3 DIFFICILE",
        "",
        "Ce lot cible les frontières et les erreurs potentielles de la V3 simple.",
        "Le dossier de 02 - À valider est une catégorie à tester : ce n’est pas",
        "forcément la prédiction numéro 1 du modèle.",
        "",
        "Pour chaque fichier de 02 - À valider :",
        "- le glisser dans sa catégorie audible correcte de 01 - Corpus vérité ;",
        "- ne garder qu’un seul rôle dominant ;",
        "- s’il est presque vide, mal extrait ou hors taxonomie, le laisser dans",
        "  02 - À valider afin qu’il soit importé comme rejet.",
        "",
        "Les audios sont des liens physiques : aucune source n’est déplacée ni copiée.",
        f"Modèle de ciblage : {model_version}",
        f"Maximum demandé : {limit_per_category} par catégorie, rang cible <= "
        f"{maximum_target_rank}, score cible >= {minimum_target_score:.2f}.",
        "Une seule loop source est présente dans tout le lot.",
        "",
        "COMPTES",
    ]
    for category in TRAINABLE_CATEGORIES:
        guide.append(
            f"- {category}: {truth_counts[category]} vérités, "
            f"{candidate_counts[category]} candidats"
        )
    guide.extend(
        (
            "",
            f"Total vérité : {len(truth_rows)}",
            f"Total à valider : {len(candidates)}",
            "",
            "Quand le tri est terminé, demander à Codex d’intégrer ce dossier.",
        )
    )
    (output / "À LIRE.txt").write_text("\n".join(guide) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    if args.limit_per_category < 1:
        raise ValueError("--limit-per-category must be positive")
    if args.maximum_target_rank < 1:
        raise ValueError("--maximum-target-rank must be positive")
    if not 0.0 <= args.minimum_target_score <= 1.0:
        raise ValueError("--minimum-target-score must be between 0 and 1")
    output = args.output.expanduser().resolve(strict=False)
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")

    truth_rows = read_semicolon_rows(args.reviewed_truth)
    exclusion_rows = list(truth_rows)
    exclusion_rows.extend(read_semicolon_rows(args.quality_rejects))
    if args.out_of_scope and args.out_of_scope.expanduser().exists():
        exclusion_rows.extend(read_semicolon_rows(args.out_of_scope))
    excluded_hashes = {row["sha256"].lower() for row in exclusion_rows}
    excluded_groups = {row["source_group"] for row in exclusion_rows}

    payload = joblib.load(args.model.expanduser().resolve(strict=True))
    if not isinstance(payload, dict) or "model" not in payload or "metadata" not in payload:
        raise RuntimeError("Expected a model artifact with model and metadata")
    model = payload["model"]
    metadata = payload["metadata"]
    extractor_id = str(metadata["feature_extractor_id"])
    expected_dimension = int(model.n_features_in_)
    features = read_features(args.feature_db, extractor_id, expected_dimension)
    pools = score_candidates(
        read_library(args.library_db),
        features,
        model,
        excluded_hashes,
        excluded_groups,
        args.maximum_target_rank,
        args.minimum_target_score,
    )
    selected = select_round_robin(pools, args.limit_per_category)
    counts = Counter(candidate.target_category for candidate in selected)
    summary = {
        "model": metadata["version"],
        "available_feature_vectors": len(features),
        "selected": len(selected),
        "counts": {
            category: counts[category] for category in TRAINABLE_CATEGORIES
        },
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    if not args.dry_run:
        export(
            output,
            truth_rows,
            selected,
            model_version=str(metadata["version"]),
            limit_per_category=args.limit_per_category,
            maximum_target_rank=args.maximum_target_rank,
            minimum_target_score=args.minimum_target_score,
        )
        print(f"Wrote {output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
