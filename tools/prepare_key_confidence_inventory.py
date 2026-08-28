#!/usr/bin/env python3
"""Build a strict original-loop inventory for Generate key analysis.

Each extracted source group is matched to one full loop by its normalized
name.  The key prefix and layer suffix are parsed by the production filename
parser.  No fuzzy matching, audio mutation or corpus copying is performed.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from layer_library import AUDIO_EXTENSIONS, parse_layer_filename


SCHEMA_VERSION = 2
_PITCH_CLASSES = {
    "C": 0,
    "C#": 1,
    "Db": 1,
    "D": 2,
    "D#": 3,
    "Eb": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "Gb": 6,
    "G": 7,
    "G#": 8,
    "Ab": 8,
    "A": 9,
    "A#": 10,
    "Bb": 10,
    "B": 11,
}
_MINOR_TONICS = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def normalized_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).replace("♯", "#").replace("♭", "b")
    return re.sub(r"[\s_-]+", " ", text).strip().casefold()


def audio_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() in AUDIO_EXTENSIONS
    )


def relative_minor_label(key: str, mode: str) -> str:
    pitch_class = _PITCH_CLASSES[key]
    minor_pitch_class = pitch_class if mode == "minor" else (pitch_class - 3) % 12
    return f"{_MINOR_TONICS[minor_pitch_class]}m"


def layer_group(path: Path) -> tuple[str, str, str]:
    parsed = parse_layer_filename(path.name)
    if parsed.key is None or parsed.mode not in {"major", "minor"}:
        raise ValueError(f"Layer has no unambiguous key: {path}")
    escaped_key = re.escape(parsed.key)
    if parsed.mode == "minor":
        without_key = re.sub(
            rf"(?i)^{escaped_key}(?:m|[\s_-]*(?:minor|min))\s+",
            "",
            parsed.source_stem,
            count=1,
        )
    else:
        without_key = re.sub(
            rf"(?i)^{escaped_key}(?:[\s_-]*(?:major|maj))?\s+",
            "",
            parsed.source_stem,
            count=1,
        )
    if without_key == parsed.source_stem:
        raise ValueError(f"Layer key prefix could not be removed: {path}")
    return (
        normalized_text(without_key),
        parsed.source_stem,
        relative_minor_label(parsed.key, parsed.mode),
    )


def original_loop_key(path: Path) -> str:
    stem = re.sub(r"(?i)^L\s+", "", path.stem.strip(), count=1)
    return normalized_text(stem)


def atomic_json(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_inventory(layers_root: Path, loops_root: Path) -> dict[str, object]:
    grouped: dict[str, dict[str, object]] = {}
    layer_paths = audio_files(layers_root)
    for path in layer_paths:
        group_key, source_stem, expected_key = layer_group(path)
        group = grouped.setdefault(
            group_key,
            {"source_stems": set(), "layer_paths": [], "expected_keys": set()},
        )
        group["source_stems"].add(source_stem)  # type: ignore[union-attr]
        group["layer_paths"].append(path)  # type: ignore[union-attr]
        group["expected_keys"].add(expected_key)  # type: ignore[union-attr]

    loop_paths = audio_files(loops_root)
    original_index: dict[str, list[Path]] = defaultdict(list)
    for path in loop_paths:
        original_index[original_loop_key(path)].append(path)

    entries: list[dict[str, object]] = []
    missing: list[dict[str, object]] = []
    for group_key, group in sorted(grouped.items()):
        expected_keys = set(group["expected_keys"])  # type: ignore[arg-type]
        if len(expected_keys) != 1:
            raise RuntimeError(
                f"Source group has conflicting keys: {group_key!r}: {sorted(expected_keys)!r}"
            )
        matches = original_index.get(group_key, [])
        if len(matches) > 1:
            raise RuntimeError(
                f"Ambiguous original-loop match for {group_key!r}: {matches!r}"
            )
        base = {
            "source_loop_id": group_key,
            "layer_source_stems": sorted(group["source_stems"]),  # type: ignore[arg-type]
            "layer_count": len(group["layer_paths"]),  # type: ignore[arg-type]
            "expected_key_from_layers": next(iter(expected_keys)),
        }
        if not matches:
            missing.append(base)
            continue
        original = matches[0]
        stat = original.stat()
        entries.append(
            {
                **base,
                "mapping_method": "exact_normalized_name",
                "original_path": str(original),
                "scan_path": str(original),
                "original_byte_size": stat.st_size,
                "original_mtime_ns": stat.st_mtime_ns,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "layers_root": str(layers_root),
        "loops_root": str(loops_root),
        "selected_original_loops_root": None,
        "summary": {
            "layer_files": len(layer_paths),
            "source_groups": len(grouped),
            "original_loop_files": len(loop_paths),
            "matched_groups": len(entries),
            "covered_layers": sum(int(item["layer_count"]) for item in entries),
            "missing_groups": len(missing),
            "missing_layers": sum(int(item["layer_count"]) for item in missing),
        },
        "entries": entries,
        "missing": missing,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layers", type=Path, required=True)
    parser.add_argument("--loops", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    layers_root = args.layers.expanduser().resolve()
    loops_root = args.loops.expanduser().resolve()
    output_root = args.output.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    payload = build_inventory(layers_root, loops_root)
    atomic_json(output_root / "original_loop_inventory.json", payload)
    atomic_json(
        output_root / "missing_original_loops.json",
        {"schema_version": SCHEMA_VERSION, "missing": payload["missing"]},
    )
    fields = (
        "source_loop_id",
        "layer_count",
        "expected_key_from_layers",
        "mapping_method",
        "original_path",
        "scan_path",
        "original_byte_size",
        "original_mtime_ns",
        "layer_source_stems",
    )
    with (output_root / "original_loop_inventory.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in payload["entries"]:  # type: ignore[assignment]
            row = dict(item)
            row["layer_source_stems"] = " | ".join(item["layer_source_stems"])
            writer.writerow({field: row.get(field, "") for field in fields})
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
