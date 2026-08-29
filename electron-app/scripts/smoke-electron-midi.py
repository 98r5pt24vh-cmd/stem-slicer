#!/usr/bin/env python3
"""Exercise the real Electron bridge MIDI result path under a strict timeout."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import wave


def make_short_fixture(source: Path, destination: Path) -> None:
    with wave.open(str(source), "rb") as reader:
        parameters = reader.getparams()
        frame_count = min(reader.getnframes(), reader.getframerate() * 2)
        frames = reader.readframes(frame_count)
    with wave.open(str(destination), "wb") as writer:
        writer.setparams(parameters)
        writer.writeframes(frames)


def worker(source_root: Path, bridge_root: Path) -> int:
    os.environ["STEM_SLICER_SOURCE_ROOT"] = str(source_root)
    sys.path.insert(0, str(bridge_root))
    sys.path.insert(0, str(source_root))
    import engine_bridge as bridge

    warmup = source_root / "assets" / "key-and-bpm-engine-warmup.wav"
    if not warmup.is_file():
        raise RuntimeError(f"MIDI smoke input is missing: {warmup}")
    with tempfile.TemporaryDirectory(prefix="slicer-electron-midi-") as temporary:
        audio = Path(temporary) / "Electron MIDI Smoke 140 C minor.wav"
        make_short_fixture(warmup, audio)
        artifact = {"path": str(audio), "bpm": 140}
        started = time.perf_counter()
        bridge.add_midi("electron-midi-smoke", [artifact], "midi")
        elapsed = time.perf_counter() - started
        midi_path = Path(str(artifact.get("midiPath") or ""))
        if artifact.get("midiError"):
            raise RuntimeError(f"Electron bridge MIDI failed: {artifact['midiError']}")
        if not midi_path.is_file() or midi_path.stat().st_size <= 4:
            raise RuntimeError(f"Electron bridge did not return a usable MIDI file: {midi_path}")
        if midi_path.read_bytes()[:4] != b"MThd":
            raise RuntimeError(f"Electron bridge returned an invalid MIDI header: {midi_path}")
        print(json.dumps({
            "status": "ok",
            "elapsedSeconds": round(elapsed, 3),
            "midiBytes": midi_path.stat().st_size,
            "midiHeader": "MThd",
        }, sort_keys=True), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--bridge-root", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    bridge_root = args.bridge_root.resolve()
    if args.worker:
        return worker(source_root, bridge_root)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--source-root",
        str(source_root),
        "--bridge-root",
        str(bridge_root),
    ]
    started = time.perf_counter()
    completed = subprocess.run(command, timeout=args.timeout, check=False)
    elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        raise RuntimeError(f"Electron MIDI lifecycle failed with exit code {completed.returncode}.")
    print(f"Electron MIDI lifecycle ready in {elapsed:.3f}s (limit {args.timeout}s).", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
