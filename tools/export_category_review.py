#!/usr/bin/env python3
"""Export the gold role corpus and a strict high-confidence review batch.

The export uses hard links so the Finder workflow consumes no duplicate audio
storage and never changes the source library when links are moved between the
review folders.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


CATEGORIES = (
    "Arp",
    "Bass",
    "Bells",
    "Chords",
    "Counter",
    "Guitar Chords",
    "Keys",
    "Lead",
    "Pad",
    "Pluck",
    "Rhythmic Pluck",
    "Strings",
    "Texture",
    "Vocal Chop",
)

V2_CLASSIFIER_PREFIX = "layer-roles-v2-6e24b7ca1a587bb2"


@dataclass(frozen=True)
class GoldLayer:
    category: str
    source_group: str
    filename: str
    audio_path: Path
    sha256: str


@dataclass(frozen=True)
class Candidate:
    category: str
    confidence: float
    source_loop_id: str
    filename: str
    audio_path: Path
    sha256: str
    classifier_id: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--library-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-score", type=float, default=0.90)
    parser.add_argument("--limit-per-category", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_gold(manifest_path: Path) -> tuple[list[GoldLayer], set[str]]:
    manifest_path = manifest_path.expanduser().resolve(strict=True)
    research_root = manifest_path.parent
    gold: list[GoldLayer] = []
    all_gold_hashes: set[str] = set()
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("split_role") != "gold_layer":
                continue
            sha256 = row["sha256"].lower()
            all_gold_hashes.add(sha256)
            category = row["label"]
            if category not in CATEGORIES:
                continue
            audio_path = (research_root / row["audio_path"]).resolve(strict=True)
            if file_sha256(audio_path) != sha256:
                raise RuntimeError(f"Gold audio hash mismatch: {audio_path}")
            gold.append(
                GoldLayer(
                    category=category,
                    source_group=row["source_group"],
                    filename=row["file"],
                    audio_path=audio_path,
                    sha256=sha256,
                )
            )
    return gold, all_gold_hashes


def read_candidates(
    database_path: Path,
    *,
    excluded_hashes: set[str],
    minimum_score: float,
    limit_per_category: int,
) -> list[Candidate]:
    database_path = database_path.expanduser().resolve(strict=True)
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            """
            SELECT predicted_label, prediction_confidence, source_loop_id,
                   filename, path, sha256, classifier_id
            FROM layer_cache
            WHERE classifier_id LIKE ?
              AND prediction_confidence >= ?
              AND predicted_label IS NOT NULL
            ORDER BY prediction_confidence DESC, path ASC
            """,
            (f"{V2_CLASSIFIER_PREFIX}%", minimum_score),
        ).fetchall()
    finally:
        connection.close()

    selected: list[Candidate] = []
    category_counts: Counter[str] = Counter()
    category_groups: dict[str, set[str]] = defaultdict(set)
    selected_hashes: set[str] = set()
    for category, confidence, source_group, filename, raw_path, sha256, classifier_id in rows:
        if category not in CATEGORIES:
            continue
        sha256 = str(sha256).lower()
        if sha256 in excluded_hashes or sha256 in selected_hashes:
            continue
        source_group = str(source_group)
        if source_group in category_groups[category]:
            continue
        if category_counts[category] >= limit_per_category:
            continue
        audio_path = Path(raw_path).expanduser().resolve(strict=True)
        selected.append(
            Candidate(
                category=category,
                confidence=float(confidence),
                source_loop_id=source_group,
                filename=str(filename),
                audio_path=audio_path,
                sha256=sha256,
                classifier_id=str(classifier_id),
            )
        )
        selected_hashes.add(sha256)
        category_groups[category].add(source_group)
        category_counts[category] += 1
    return selected


def unique_destination(directory: Path, filename: str, sha256: str) -> Path:
    destination = directory / filename
    if not destination.exists():
        return destination
    suffix = Path(filename).suffix
    stem = filename[: -len(suffix)] if suffix else filename
    return directory / f"{stem}__{sha256[:8]}{suffix}"


def hard_link(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.link(source, destination)


def export(
    output: Path,
    gold: list[GoldLayer],
    candidates: list[Candidate],
    *,
    minimum_score: float,
    limit_per_category: int,
) -> None:
    output = output.expanduser().resolve(strict=False)
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")

    truth_root = output / "01 - Corpus vérité"
    review_root = output / "02 - À valider"
    for root in (truth_root, review_root):
        for category in CATEGORIES:
            (root / category).mkdir(parents=True, exist_ok=False)

    manifest_rows: list[dict[str, object]] = []
    for row in gold:
        destination = unique_destination(
            truth_root / row.category, row.filename, row.sha256
        )
        hard_link(row.audio_path, destination)
        manifest_rows.append(
            {
                "set": "gold",
                "suggested_category": row.category,
                "model_score": "",
                "source_group": row.source_group,
                "filename": destination.name,
                "sha256": row.sha256,
                "original_path": str(row.audio_path),
            }
        )

    for row in candidates:
        destination = unique_destination(
            review_root / row.category, row.filename, row.sha256
        )
        hard_link(row.audio_path, destination)
        manifest_rows.append(
            {
                "set": "candidate",
                "suggested_category": row.category,
                "model_score": f"{row.confidence:.6f}",
                "source_group": row.source_loop_id,
                "filename": destination.name,
                "sha256": row.sha256,
                "original_path": str(row.audio_path),
            }
        )

    with (output / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "set",
                "suggested_category",
                "model_score",
                "source_group",
                "filename",
                "sha256",
                "original_path",
            ),
            delimiter=";",
        )
        writer.writeheader()
        writer.writerows(manifest_rows)

    gold_counts = Counter(row.category for row in gold)
    candidate_counts = Counter(row.category for row in candidates)
    lines = [
        "CATÉGORISATION IMPROVEMENT — MODE D’EMPLOI",
        "",
        "01 - Corpus vérité contient les exemples déjà validés.",
        "02 - À valider contient les prédictions v2 les plus affirmées.",
        "",
        "Pour chaque fichier de 02 - À valider :",
        "- si la catégorie proposée est correcte, glisser le fichier vers le dossier",
        "  de même nom dans 01 - Corpus vérité ;",
        "- si elle est incorrecte mais appartient à une autre des 14 catégories,",
        "  le glisser vers cette catégorie correcte dans 01 - Corpus vérité ;",
        "- s’il ne correspond à aucune catégorie, le laisser dans 02 - À valider.",
        "",
        "Les fichiers sont des liens physiques : les déplacer ici ne déplace ni ne",
        "modifie les audios originaux de la bibliothèque.",
        "",
        f"Sélection : score modèle >= {minimum_score:.2f}, maximum {limit_per_category}",
        "par catégorie et un seul candidat par loop source dans une catégorie.",
        "Le score est un score de classement du modèle, pas une probabilité garantie.",
        "",
        "COMPTES",
    ]
    for category in CATEGORIES:
        lines.append(
            f"- {category}: {gold_counts[category]} vérités, "
            f"{candidate_counts[category]} candidats"
        )
    lines.extend(
        (
            "",
            f"Total vérité : {len(gold)}",
            f"Total à valider : {len(candidates)}",
            "",
            "Quand le tri est terminé, demander à Codex d’intégrer le dossier.",
        )
    )
    (output / "À LIRE.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    if not 0.0 <= args.minimum_score <= 1.0:
        raise ValueError("--minimum-score must be between 0 and 1")
    if args.limit_per_category < 1:
        raise ValueError("--limit-per-category must be positive")
    gold, all_gold_hashes = read_gold(args.manifest)
    candidates = read_candidates(
        args.library_db,
        excluded_hashes=all_gold_hashes,
        minimum_score=args.minimum_score,
        limit_per_category=args.limit_per_category,
    )
    gold_counts = Counter(row.category for row in gold)
    candidate_counts = Counter(row.category for row in candidates)
    print(f"gold={len(gold)} candidates={len(candidates)}")
    for category in CATEGORIES:
        print(
            f"{category}: gold={gold_counts[category]} "
            f"candidates={candidate_counts[category]}"
        )
    if not args.dry_run:
        export(
            args.output,
            gold,
            candidates,
            minimum_score=args.minimum_score,
            limit_per_category=args.limit_per_category,
        )
        print(f"output={args.output.expanduser().resolve(strict=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
