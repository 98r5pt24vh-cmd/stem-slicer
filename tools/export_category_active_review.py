#!/usr/bin/env python3
"""Export a boundary-focused second layer-role review batch.

The accepted truth corpus and candidate audio are exported as hard links. The
source library and frozen research corpus are never moved or modified.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from export_category_review import CATEGORIES, V2_CLASSIFIER_PREFIX, unique_destination


TARGETS = (
    "Bells",
    "Keys",
    "Rhythmic Pluck",
    "Strings",
    "Texture",
    "Pad",
    "Arp",
    "Pluck",
    "Counter",
)

NEIGHBORS = {
    "Arp": ("Pluck", "Rhythmic Pluck"),
    "Bells": ("Keys", "Pluck", "Texture"),
    "Counter": ("Lead", "Pluck", "Guitar Chords", "Rhythmic Pluck"),
    "Keys": ("Chords", "Pad", "Bells"),
    "Pad": ("Texture", "Chords", "Keys", "Strings"),
    "Pluck": ("Arp", "Rhythmic Pluck", "Counter", "Bells"),
    "Rhythmic Pluck": ("Pluck", "Arp", "Counter"),
    "Strings": ("Pad", "Chords", "Lead", "Texture"),
    "Texture": ("Pad", "Vocal Chop", "Strings"),
}


@dataclass(frozen=True)
class Candidate:
    category: str
    confidence: float
    source_group: str
    filename: str
    audio_path: Path
    sha256: str
    classifier_id: str
    nearest_boundary: str
    boundary_score: float
    top_margin: float
    rank: tuple[object, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reviewed-truth", type=Path, required=True)
    parser.add_argument("--quality-rejects", type=Path, required=True)
    parser.add_argument("--library-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit-per-category", type=int, default=50)
    parser.add_argument("--minimum-score", type=float, default=0.20)
    parser.add_argument("--maximum-score", type=float, default=0.85)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.expanduser().resolve(strict=True).open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream, delimiter=";"))
    if not rows:
        raise RuntimeError(f"Manifest is empty: {path}")
    return rows


def read_library_rows(database_path: Path) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(
        f"file:{database_path.expanduser().resolve(strict=True)}?mode=ro", uri=True
    )
    try:
        return connection.execute(
            """
            SELECT predicted_label, prediction_confidence, prediction_scores_json,
                   source_loop_id, filename, path, sha256, classifier_id
            FROM layer_cache
            WHERE classifier_id LIKE ?
              AND predicted_label IS NOT NULL
            ORDER BY path ASC
            """,
            (f"{V2_CLASSIFIER_PREFIX}%",),
        ).fetchall()
    finally:
        connection.close()


def candidate_from_row(
    row: tuple[object, ...], minimum_score: float, maximum_score: float
) -> Candidate | None:
    category, confidence, raw_scores, source_group, filename, raw_path, sha256, classifier_id = row
    category = str(category)
    confidence = float(confidence)
    if category not in TARGETS or not minimum_score <= confidence <= maximum_score:
        return None
    audio_path = Path(str(raw_path)).expanduser()
    if not audio_path.is_file():
        return None
    scores = {str(key): float(value) for key, value in json.loads(str(raw_scores)).items()}
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    second_score = ordered[1][1] if len(ordered) > 1 else 0.0
    top_margin = confidence - second_score
    boundary_options = [
        (neighbor, scores[neighbor])
        for neighbor in NEIGHBORS[category]
        if neighbor in scores
    ]
    if boundary_options:
        nearest_boundary, boundary_score = min(
            boundary_options, key=lambda item: abs(confidence - item[1])
        )
        boundary_gap = abs(confidence - boundary_score)
        lacks_boundary = 0
    else:
        nearest_boundary, boundary_score = "", 0.0
        boundary_gap = 1.0
        lacks_boundary = 1
    rank = (
        lacks_boundary,
        boundary_gap,
        top_margin,
        abs(confidence - 0.50),
        str(audio_path).casefold(),
    )
    return Candidate(
        category=category,
        confidence=confidence,
        source_group=str(source_group),
        filename=str(filename),
        audio_path=audio_path.resolve(strict=True),
        sha256=str(sha256).lower(),
        classifier_id=str(classifier_id),
        nearest_boundary=nearest_boundary,
        boundary_score=boundary_score,
        top_margin=top_margin,
        rank=rank,
    )


def select_candidates(
    rows: list[tuple[object, ...]],
    excluded_hashes: set[str],
    limit_per_category: int,
    minimum_score: float,
    maximum_score: float,
) -> list[Candidate]:
    known_groups = {
        str(row[3]) for row in rows if str(row[6]).lower() in excluded_hashes
    }
    pools: dict[str, list[Candidate]] = defaultdict(list)
    for row in rows:
        candidate = candidate_from_row(row, minimum_score, maximum_score)
        if candidate is None:
            continue
        if candidate.sha256 in excluded_hashes or candidate.source_group in known_groups:
            continue
        pools[candidate.category].append(candidate)
    for category in TARGETS:
        pools[category].sort(key=lambda candidate: candidate.rank)

    selected: list[Candidate] = []
    used_hashes: set[str] = set()
    used_groups: set[str] = set()
    counts: Counter[str] = Counter()
    cursors: Counter[str] = Counter()
    progress = True
    while progress and any(counts[category] < limit_per_category for category in TARGETS):
        progress = False
        for category in TARGETS:
            if counts[category] >= limit_per_category:
                continue
            pool = pools[category]
            while cursors[category] < len(pool):
                candidate = pool[cursors[category]]
                cursors[category] += 1
                if candidate.sha256 in used_hashes or candidate.source_group in used_groups:
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
    minimum_score: float,
    maximum_score: float,
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
                "nearest_boundary": "",
                "boundary_score": "",
                "top_margin": "",
            }
        )

    for candidate in candidates:
        destination = unique_destination(
            review_root / candidate.category, candidate.filename, candidate.sha256
        )
        hard_link(candidate.audio_path, destination)
        manifest_rows.append(
            {
                "set": "candidate",
                "suggested_category": candidate.category,
                "model_score": f"{candidate.confidence:.6f}",
                "source_group": candidate.source_group,
                "filename": destination.name,
                "sha256": candidate.sha256,
                "original_path": str(candidate.audio_path),
                "nearest_boundary": candidate.nearest_boundary,
                "boundary_score": f"{candidate.boundary_score:.6f}",
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
    candidate_counts = Counter(row.category for row in candidates)
    guide = [
        "CATÉGORISATION IMPROVEMENT — LOT 2 ACTIF",
        "",
        "Ce lot contient volontairement des cas moins évidents et des frontières.",
        "Le dossier proposé par le modèle est seulement une hypothèse à vérifier.",
        "",
        "RÈGLE GÉNÉRALE",
        "Classer selon le rôle audible dominant dans une génération, pas selon le",
        "nom du preset ni nécessairement la source sonore d’origine.",
        "Un seul label principal par fichier ; ne pas dupliquer un même fichier.",
        "",
        "FRONTIÈRES IMPORTANTES",
        "- Arp : mouvement de hauteurs cyclique, ordonné et répétitif.",
        "- Pluck : attaque courte/percussive avec une vraie phrase mélodique.",
        "- Rhythmic Pluck : motif ou ostinato régulier présent sur une part importante",
        "  de la loop ; pas seulement une réponse ponctuelle.",
        "- Counter : élément secondaire espacé qui répond au motif principal ; son",
        "  timbre peut être lead, pluck ou guitare. Un fichier presque vide ne compte pas.",
        "- Pad : enveloppe douce, sustain/réverbération et fonction de lit harmonique,",
        "  même s’il joue des accords.",
        "- Chords : les attaques/changements d’accords ou la progression dominent.",
        "- Texture : mouvement timbral/atmosphérique ; mélodie, hauteur et identité de",
        "  la source sont secondaires.",
        "- Vocal Chop : l’identité vocale humaine et le découpage restent centraux ;",
        "  si la voix devient surtout une matière transformée, choisir Texture.",
        "",
        "GESTE FINDER",
        "- correct : glisser vers la même catégorie dans 01 - Corpus vérité ;",
        "- incorrect : glisser vers la catégorie correcte dans 01 - Corpus vérité ;",
        "- presque vide, clic seul ou inutilisable : laisser dans 02 - À valider ou",
        "  le mettre dans un dossier de rejet séparé hors de 01.",
        "",
        "Les audios sont des liens physiques : aucun audio source n’est déplacé.",
        f"Plage de sélection : score {minimum_score:.2f} à {maximum_score:.2f},",
        f"maximum {limit_per_category} par catégorie ciblée, une seule loop source",
        "dans tout le lot. Le score n’est pas une probabilité garantie.",
        "",
        "COMPTES",
    ]
    for category in CATEGORIES:
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
    if not 0.0 <= args.minimum_score < args.maximum_score <= 1.0:
        raise ValueError("Expected 0 <= minimum score < maximum score <= 1")
    truth_rows = read_manifest(args.reviewed_truth)
    reject_rows = read_manifest(args.quality_rejects)
    excluded_hashes = {
        row["sha256"].lower() for row in truth_rows + reject_rows
    }
    library_rows = read_library_rows(args.library_db)
    candidates = select_candidates(
        library_rows,
        excluded_hashes,
        args.limit_per_category,
        args.minimum_score,
        args.maximum_score,
    )
    counts = Counter(candidate.category for candidate in candidates)
    print(f"truth={len(truth_rows)} candidates={len(candidates)}")
    for category in CATEGORIES:
        print(f"{category}: truth={sum(row['final_label'] == category for row in truth_rows)} candidates={counts[category]}")
    missing = [category for category in TARGETS if counts[category] < args.limit_per_category]
    if missing:
        raise RuntimeError(f"Could not fill the requested categories: {missing}")
    if not args.dry_run:
        export(
            args.output,
            truth_rows,
            candidates,
            minimum_score=args.minimum_score,
            maximum_score=args.maximum_score,
            limit_per_category=args.limit_per_category,
        )
        print(f"output={args.output.expanduser().resolve(strict=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
