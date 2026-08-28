#!/usr/bin/env python3
"""Freeze a Finder-sorted category review without mutating its source folder."""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter
from pathlib import Path

from category_taxonomy import (
    OUT_OF_SCOPE_LABELS,
    TRAINABLE_CATEGORIES,
    canonical_folder_label,
)


IGNORED_NAMES = {".DS_Store", "manifest.csv", "À LIRE.txt"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reject-label", default="REJECT_ALMOST_EMPTY")
    parser.add_argument("--reject-reason", default="almost_empty_not_counter")
    return parser.parse_args()


def source_inode(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino


def unique_destination(directory: Path, filename: str, sha256: str) -> Path:
    destination = directory / filename
    if not destination.exists():
        return destination
    suffix = Path(filename).suffix
    stem = filename[: -len(suffix)] if suffix else filename
    return directory / f"{stem}__{sha256[:8]}{suffix}"


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise RuntimeError(f"Refusing to write an empty manifest: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(rows[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    review_root = args.review_root.expanduser().resolve(strict=True)
    output = args.output.expanduser().resolve(strict=False)
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")

    export_manifest = review_root / "manifest.csv"
    with export_manifest.open(encoding="utf-8-sig", newline="") as stream:
        exported = list(csv.DictReader(stream, delimiter=";"))
    if not exported:
        raise RuntimeError("The category export manifest is empty")

    by_inode: dict[tuple[int, int], dict[str, str]] = {}
    for row in exported:
        original = Path(row["original_path"]).expanduser().resolve(strict=True)
        inode = source_inode(original)
        if inode in by_inode:
            raise RuntimeError(f"Duplicate source inode in export manifest: {original}")
        by_inode[inode] = row

    observed: dict[str, tuple[str, Path]] = {}
    for path in review_root.rglob("*"):
        if not path.is_file() or path.name in IGNORED_NAMES:
            continue
        row = by_inode.get(source_inode(path))
        if row is None:
            raise RuntimeError(f"Untracked file in review: {path}")
        sha256 = row["sha256"]
        if sha256 in observed:
            raise RuntimeError(f"Duplicate reviewed audio hash: {path}")
        relative = path.relative_to(review_root)
        if relative.parts[0] == "01 - Corpus vérité":
            final_label = canonical_folder_label(relative.parts[1])
            if (
                final_label not in TRAINABLE_CATEGORIES
                and final_label not in OUT_OF_SCOPE_LABELS
            ):
                raise RuntimeError(f"Unknown final category: {path}")
        else:
            final_label = args.reject_label
        observed[sha256] = (final_label, path)

    if len(observed) != len(exported):
        missing = sorted(row["filename"] for row in exported if row["sha256"] not in observed)
        raise RuntimeError(f"Missing {len(missing)} exported files: {missing[:8]!r}")

    truth_root = output / "reviewed_truth"
    reject_root = output / "quality_rejects" / args.reject_reason
    out_of_scope_root = output / "out_of_scope"
    for category in TRAINABLE_CATEGORIES:
        (truth_root / category).mkdir(parents=True, exist_ok=False)
    reject_root.mkdir(parents=True, exist_ok=False)
    for label in OUT_OF_SCOPE_LABELS:
        (out_of_scope_root / label).mkdir(parents=True, exist_ok=False)

    truth_rows: list[dict[str, object]] = []
    reject_rows: list[dict[str, object]] = []
    out_of_scope_rows: list[dict[str, object]] = []
    transitions: Counter[tuple[str, str, str]] = Counter()
    for row in exported:
        final_label, reviewed_path = observed[row["sha256"]]
        transitions[(row["set"], row["suggested_category"], final_label)] += 1
        common = {
            "origin_set": row["set"],
            "previous_label": row["suggested_category"],
            "final_label": final_label,
            "model_score": row["model_score"],
            "source_group": row["source_group"],
            "filename": reviewed_path.name,
            "sha256": row["sha256"],
            "original_path": row["original_path"],
        }
        if final_label == args.reject_label:
            destination = unique_destination(reject_root, reviewed_path.name, row["sha256"])
            os.link(reviewed_path, destination)
            reject_rows.append(
                {
                    **common,
                    "reviewed_audio_path": str(destination),
                    "quality_reason": args.reject_reason,
                }
            )
        elif final_label in OUT_OF_SCOPE_LABELS:
            destination = unique_destination(
                out_of_scope_root / final_label, reviewed_path.name, row["sha256"]
            )
            os.link(reviewed_path, destination)
            out_of_scope_rows.append(
                {
                    **common,
                    "reviewed_audio_path": str(destination),
                    "quality_reason": "out_of_scope_for_melodic_role_model",
                }
            )
        else:
            destination = unique_destination(
                truth_root / final_label, reviewed_path.name, row["sha256"]
            )
            os.link(reviewed_path, destination)
            truth_rows.append(
                {
                    **common,
                    "reviewed_audio_path": str(destination),
                    "quality_reason": "accepted",
                }
            )

    write_csv(output / "reviewed_truth.csv", truth_rows)
    write_csv(output / "quality_rejects.csv", reject_rows)
    if out_of_scope_rows:
        write_csv(output / "out_of_scope.csv", out_of_scope_rows)

    truth_counts = Counter(str(row["final_label"]) for row in truth_rows)
    candidate_rows = [
        row
        for row in truth_rows + reject_rows + out_of_scope_rows
        if row["origin_set"] == "candidate"
    ]
    confirmed = sum(
        row["final_label"] == row["previous_label"] for row in candidate_rows
    )
    rejected = sum(row["final_label"] == args.reject_label for row in candidate_rows)
    out_of_scope = sum(
        row["final_label"] in OUT_OF_SCOPE_LABELS for row in candidate_rows
    )
    summary = {
        "schema": "stem-slicer-category-review-v1",
        "source_review_root": str(review_root),
        "reviewed_truth_rows": len(truth_rows),
        "quality_reject_rows": len(reject_rows),
        "out_of_scope_rows": len(out_of_scope_rows),
        "truth_counts": {
            category: truth_counts[category] for category in TRAINABLE_CATEGORIES
        },
        "candidate_audit": {
            "rows": len(candidate_rows),
            "confirmed": confirmed,
            "reclassified": len(candidate_rows) - confirmed - rejected - out_of_scope,
            "rejected": rejected,
            "reject_label": args.reject_label,
            "reject_reason": args.reject_reason,
            "out_of_scope": out_of_scope,
            "confirmed_fraction": confirmed / len(candidate_rows),
        },
        "transitions": [
            {
                "origin_set": origin,
                "previous_label": before,
                "final_label": after,
                "rows": count,
            }
            for (origin, before, after), count in sorted(transitions.items())
        ],
        "audio_storage": "hard_links",
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
