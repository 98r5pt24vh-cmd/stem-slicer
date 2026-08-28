#!/usr/bin/env python3
"""Resumable split-temporal Top-1/Top-2 key scan for original loops."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path

import librosa
import numpy as np
import torch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ANALYZER_ROOT = REPOSITORY_ROOT / "analyzer"
sys.path.insert(0, str(ANALYZER_ROOT))

from key_inference import (  # noqa: E402
    ANALYZER_ID,
    MARGIN_THRESHOLD,
    relative_family_decision,
    split2_probabilities,
)
from model import KeyNet  # noqa: E402


SCHEMA_VERSION = 2


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def preprocess(audio_path: Path) -> torch.Tensor:
    waveform, _ = librosa.load(audio_path, sr=44100, mono=True)
    cqt = librosa.cqt(
        waveform.astype(np.float32),
        sr=44100,
        hop_length=8820,
        n_bins=105,
        bins_per_octave=24,
        fmin=65,
    )
    spec = np.log1p(np.abs(cqt))[:, 0:-2]
    return torch.tensor(spec, dtype=torch.float32).unsqueeze(0).unsqueeze(0)


def load_successes(path: Path) -> dict[str, dict[str, object]]:
    successes = {}
    if not path.is_file():
        return successes
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("status") == "success" and record.get("source_loop_id"):
                successes[str(record["source_loop_id"])] = record
    return successes


def resume_matches(
    record: dict[str, object],
    *,
    entry: dict[str, object],
    scan_stat: os.stat_result,
    checkpoint_sha256: str,
) -> bool:
    return bool(
        record.get("schema_version") == SCHEMA_VERSION
        and record.get("scanner_id") == ANALYZER_ID
        and record.get("checkpoint_sha256") == checkpoint_sha256
        and record.get("scan_path") == entry.get("scan_path")
        and record.get("audio_byte_size") == scan_stat.st_size
        and record.get("audio_mtime_ns") == scan_stat.st_mtime_ns
    )


def append_record(path: Path, record: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def scan_one(model, audio_path: Path, device: torch.device) -> dict[str, object]:
    spec = preprocess(audio_path).to(device)
    with torch.no_grad():
        probabilities = split2_probabilities(model, spec)
        decision = relative_family_decision(probabilities)
    probabilities_cpu = probabilities.detach().cpu().numpy()
    positive = probabilities_cpu[probabilities_cpu > 0]
    entropy = -float(np.sum(positive * np.log(positive))) / float(np.log(24))
    return {
        "top1_key": decision.top1_key,
        "top1_probability": decision.top1_probability,
        "top2_key": decision.top2_key,
        "top2_probability": decision.top2_probability,
        "top1_top2_margin": decision.margin,
        "normalized_entropy": entropy,
    }


def export_results(
    *,
    ledger_path: Path,
    output_json: Path,
    output_csv: Path,
    total_manifest_entries: int,
) -> None:
    latest = {}
    with ledger_path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("source_loop_id"):
                latest[str(record["source_loop_id"])] = record
    records = sorted(latest.values(), key=lambda item: str(item["source_loop_id"]))
    successful = [record for record in records if record.get("status") == "success"]
    for record in successful:
        expected = str(record["expected_key_from_layers"])
        record["margin_threshold"] = MARGIN_THRESHOLD
        record["key_matches_filename"] = record["top1_key"] == expected
        record["eligible_normal_pool"] = bool(
            record["key_matches_filename"]
            and float(record["top1_top2_margin"]) >= MARGIN_THRESHOLD
        )
    summary = {
        "manifest_entries": total_manifest_entries,
        "successful": len(successful),
        "errors": len(records) - len(successful),
        "key_matches_filename": sum(record["key_matches_filename"] for record in successful),
        "margin_at_least_threshold": sum(
            float(record["top1_top2_margin"]) >= MARGIN_THRESHOLD
            for record in successful
        ),
        "eligible_normal_pool": sum(record["eligible_normal_pool"] for record in successful),
        "margin_threshold": MARGIN_THRESHOLD,
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "scanner_id": ANALYZER_ID,
        "summary": summary,
        "results": records,
    }
    output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    fields = [
        "source_loop_id", "layer_count", "expected_key_from_layers",
        "top1_key", "top1_probability", "top2_key", "top2_probability",
        "top1_top2_margin", "normalized_entropy", "key_matches_filename",
        "margin_threshold", "eligible_normal_pool", "mapping_method",
        "scan_path", "duration_seconds", "status", "error",
    ]
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            {field: record.get(field, "") for field in fields}
            for record in records
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    torch.set_num_threads(max(1, args.threads))
    torch.set_num_interop_threads(1)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    all_entries = list(manifest["entries"])
    entries = all_entries[: max(0, args.limit)] if args.limit is not None else all_entries
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_sha256 = sha256_file(args.checkpoint)
    state_dict = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    checkpoint_nf = int(state_dict["conv1.conv.weight"].shape[0])
    device = torch.device(args.device)
    model = KeyNet(Nf=checkpoint_nf)
    model.load_state_dict(state_dict)
    model.eval().to(device)

    successes = load_successes(args.ledger)
    for index, entry in enumerate(entries, start=1):
        source_loop_id = str(entry["source_loop_id"])
        scan_path = Path(str(entry["scan_path"]))
        try:
            scan_stat = scan_path.stat()
            previous = successes.get(source_loop_id)
            if previous and resume_matches(
                previous,
                entry=entry,
                scan_stat=scan_stat,
                checkpoint_sha256=checkpoint_sha256,
            ):
                print(f"[{index}/{len(entries)}] cached {scan_path.name}", flush=True)
                continue
            started = time.perf_counter()
            result = scan_one(model, scan_path, device)
            record = {
                "schema_version": SCHEMA_VERSION,
                "scanner_id": ANALYZER_ID,
                "checkpoint_sha256": checkpoint_sha256,
                "runtime": {
                    "python": platform.python_version(),
                    "machine": platform.machine(),
                    "torch": torch.__version__,
                    "device": str(device),
                    "threads": torch.get_num_threads(),
                },
                "source_loop_id": source_loop_id,
                "layer_count": int(entry["layer_count"]),
                "expected_key_from_layers": entry["expected_key_from_layers"],
                "mapping_method": entry["mapping_method"],
                "original_path": entry["original_path"],
                "scan_path": str(scan_path),
                "audio_byte_size": scan_stat.st_size,
                "audio_mtime_ns": scan_stat.st_mtime_ns,
                "duration_seconds": time.perf_counter() - started,
                "status": "success",
                "error": None,
                "recorded_at_ns": time.time_ns(),
                **result,
            }
        except Exception as exc:
            record = {
                "schema_version": SCHEMA_VERSION,
                "scanner_id": ANALYZER_ID,
                "source_loop_id": source_loop_id,
                "scan_path": str(scan_path),
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "recorded_at_ns": time.time_ns(),
            }
        append_record(args.ledger, record)
        if record["status"] == "success":
            print(
                f"[{index}/{len(entries)}] {scan_path.name}: "
                f"{record['top1_key']} / {record['top2_key']} "
                f"margin={float(record['top1_top2_margin']):.6f} "
                f"({float(record['duration_seconds']):.2f}s)",
                flush=True,
            )
        else:
            print(f"[{index}/{len(entries)}] ERROR {scan_path.name}: {record['error']}", flush=True)

    export_results(
        ledger_path=args.ledger,
        output_json=args.json,
        output_csv=args.csv,
        total_manifest_entries=len(entries),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
