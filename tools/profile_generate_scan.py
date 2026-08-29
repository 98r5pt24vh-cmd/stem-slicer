#!/usr/bin/env python3
"""Measure cold Generate classification phases without persisting decoded audio."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mert_worker import Runtime, dsp_features_many, load_audio


AUDIO_EXTENSIONS = {".aif", ".aiff", ".flac", ".m4a", ".mp3", ".ogg", ".wav"}


def audio_paths(root: Path, limit: int) -> tuple[Path, ...]:
    candidates = sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.casefold() in AUDIO_EXTENSIONS
        ),
        key=lambda path: (path.relative_to(root).as_posix().casefold(), path.as_posix()),
    )
    return tuple(candidates[:limit])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--artifact", type=Path, default=ROOT / "models/layer_roles_v4_2.joblib")
    parser.add_argument("--hf-cache-dir", type=Path, default=ROOT / "models/huggingface")
    parser.add_argument("--device", choices=("cpu", "mps", "auto"), default="cpu")
    args = parser.parse_args()
    if args.limit < 1 or args.batch_size < 1:
        parser.error("limit and batch size must be at least one")

    paths = audio_paths(args.library.expanduser().resolve(), args.limit)
    if not paths:
        parser.error("no supported audio files found")

    timings = {
        "runtime_setup_seconds": 0.0,
        "model_load_seconds": 0.0,
        "decode_seconds": 0.0,
        "mert_seconds": 0.0,
        "dsp_seconds": 0.0,
        "head_seconds": 0.0,
    }
    decoded_lengths: list[int] = []
    with tempfile.TemporaryDirectory(prefix="stem-slicer-profile-") as temporary:
        started = time.perf_counter()
        runtime = Runtime(
            args.artifact.resolve(),
            args.hf_cache_dir.resolve(),
            Path(temporary) / "features.sqlite3",
            args.device,
        )
        timings["runtime_setup_seconds"] = time.perf_counter() - started

        started = time.perf_counter()
        runtime.ensure_mert()
        timings["model_load_seconds"] = time.perf_counter() - started

        for offset in range(0, len(paths), args.batch_size):
            batch_paths = paths[offset : offset + args.batch_size]
            started = time.perf_counter()
            audios = [load_audio(path) for path in batch_paths]
            timings["decode_seconds"] += time.perf_counter() - started
            decoded_lengths.extend(int(audio.size) for audio in audios)

            started = time.perf_counter()
            mert = runtime.mert_features_many(
                audios,
                window_batch_size=args.batch_size,
            )
            timings["mert_seconds"] += time.perf_counter() - started

            started = time.perf_counter()
            dsp = dsp_features_many(audios)
            timings["dsp_seconds"] += time.perf_counter() - started

            vectors = np.concatenate([mert, dsp], axis=1).astype(np.float32, copy=False)
            started = time.perf_counter()
            for vector in vectors:
                runtime.classifier.predict_proba(vector[None, :])
            timings["head_seconds"] += time.perf_counter() - started

    measured_total = sum(timings.values())
    payload = {
        "schema": "stem-slicer-generate-scan-profile-v1",
        "file_count": len(paths),
        "batch_size": args.batch_size,
        "device": args.device,
        "unique_decoded_lengths": len(set(decoded_lengths)),
        "batchable_files": len(decoded_lengths) - len(set(decoded_lengths)),
        "measured_total_seconds": measured_total,
        "seconds_per_file": measured_total / len(paths),
        "timings": timings,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
