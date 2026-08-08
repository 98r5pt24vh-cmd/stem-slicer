#!/usr/bin/env python3
"""Exercise the real source-mode Key -> MIDI -> Quick Extract lifecycle."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time


SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))
os.chdir(SOURCE_ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("STEM_SLICER_DISABLE_ENGINE_AUTOSTART", None)

from diagnostics_runtime import initialize_diagnostics
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from app import APP_NAME, APP_VERSION, MainWindow
from storage import StorageManager
from validated_ui import validated_stylesheet


class DevSettings:
    def __init__(self, root: str):
        self.values = {"storage/root": root}

    def value(self, key, default="", type=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value


def pump_until(application, predicate, stage, seconds):
    started = time.perf_counter()
    print(f"[gate] waiting: {stage}", flush=True)
    while not predicate():
        application.processEvents()
        if time.perf_counter() - started > seconds:
            raise RuntimeError(f"{stage} did not complete")
        time.sleep(0.005)
    print(
        f"[gate] complete: {stage} ({time.perf_counter() - started:.3f}s)",
        flush=True,
    )


def validate_midi(path):
    if not path or not os.path.isfile(path):
        raise RuntimeError(f"MIDI output is missing: {path}")
    size = os.path.getsize(path)
    with open(path, "rb") as midi_file:
        header = midi_file.read(4)
    if size <= 14 or header != b"MThd":
        raise RuntimeError(f"MIDI output is invalid: {path}")
    return size


def run_gate(input_path, expected_layers, output_root, mode):
    diagnostics = initialize_diagnostics(APP_NAME, APP_VERSION)
    application = QApplication.instance() or QApplication([])
    application.setApplicationName(APP_NAME)
    application.setApplicationDisplayName(f"{APP_NAME} {APP_VERSION}")
    application.setStyleSheet(validated_stylesheet())

    started = time.perf_counter()
    window = MainWindow()
    window.storage = StorageManager(DevSettings(output_root))
    service = None
    try:
        pump_until(
            application,
            lambda: window.key_engine_state in {"ready", "failed"},
            "Key engine",
            120,
        )
        if window.key_engine_state != "ready":
            raise RuntimeError("Key engine failed")
        key_ready_at = time.perf_counter()

        if mode == "ready-first":
            pump_until(
                application,
                lambda: window.midi_engine_state in {"ready", "failed"},
                "MIDI engine",
                30,
            )
            if window.midi_engine_state != "ready":
                raise RuntimeError("MIDI engine failed")
            midi_ready_at = time.perf_counter()
            service = window.midi_service
        else:
            # Drop immediately after Key becomes ready, before waiting for the
            # scheduled MIDI ready signal.  This exercises pending-job handoff.
            midi_ready_at = None

        if not window.quick_extract_drop.set_path(input_path):
            raise RuntimeError(f"Quick Extract rejected the input: {input_path}")

        pump_until(
            application,
            lambda: window.quick_extract_worker is not None,
            "Quick Extract worker creation",
            5,
        )

        if service is None:
            pump_until(
                application,
                lambda: window.midi_service is not None,
                "MIDI service creation",
                10,
            )
            service = window.midi_service

        first_midi_at = []
        midi_completed = []
        service.signals.progress.connect(
            lambda *_args: first_midi_at.append(time.perf_counter()) if not first_midi_at else None,
            Qt.ConnectionType.DirectConnection,
        )
        service.signals.completed.connect(
            lambda *args: midi_completed.append((time.perf_counter(), args)),
            Qt.ConnectionType.DirectConnection,
        )

        pump_until(
            application,
            lambda: window.midi_job_total > 0 or bool(midi_completed),
            "Quick Extract completion",
            90,
        )
        extraction_handoff_at = time.perf_counter()
        midi_state_at_handoff = window.midi_engine_state
        if window.midi_job_total != expected_layers:
            raise RuntimeError(
                f"Expected {expected_layers} extracted layers, got {window.midi_job_total}"
            )

        if midi_ready_at is None:
            pump_until(
                application,
                lambda: window.midi_engine_state in {"ready", "failed"},
                "MIDI engine",
                30,
            )
            if window.midi_engine_state != "ready":
                raise RuntimeError("MIDI engine failed")
            midi_ready_at = time.perf_counter()

        pump_until(
            application,
            lambda: bool(midi_completed),
            "MIDI conversion",
            90,
        )
        pump_until(
            application,
            lambda: (
                len(window.layer_cards) == expected_layers
                and not getattr(window, "_layer_cards_rendering", False)
            ),
            "Layer card rendering",
            10,
        )
        pump_until(
            application,
            lambda: all(
                card.midi_handle.state != "processing"
                for card in window.layer_cards
            ),
            "MIDI UI handoff",
            10,
        )

        completed_at, completed_args = midi_completed[-1]
        _job_id, ready_count, midi_elapsed = completed_args
        if len(window.layer_cards) != expected_layers:
            raise RuntimeError(
                f"Expected {expected_layers} layers, got {len(window.layer_cards)}"
            )
        if ready_count != expected_layers:
            raise RuntimeError(
                f"Expected {expected_layers} MIDI files, got {ready_count}"
            )

        midi_sizes = []
        for card in window.layer_cards:
            if card.midi_handle.state != "ready":
                raise RuntimeError(f"MIDI handle is not draggable for {card.layer['path']}")
            midi_sizes.append(validate_midi(card.midi_handle.path))

        return {
            "status": "ok",
            "mode": mode,
            "input": input_path,
            "output_folder": window.quick_extract_session,
            "layers": len(window.layer_cards),
            "midi_files": ready_count,
            "midi_bytes": midi_sizes,
            "key_ready_seconds": round(key_ready_at - started, 6),
            "midi_ready_seconds": round(midi_ready_at - key_ready_at, 6),
            "extraction_seconds": round(float(window.quick_extract_elapsed), 6),
            "midi_state_at_extraction_handoff": midi_state_at_handoff,
            "extraction_to_first_midi_seconds": (
                round(first_midi_at[0] - extraction_handoff_at, 6)
                if first_midi_at
                else None
            ),
            "extraction_to_all_midi_seconds": round(
                completed_at - extraction_handoff_at,
                6,
            ),
            "midi_worker_seconds": round(float(midi_elapsed), 6),
            "midi_service_id": id(service),
        }
    finally:
        if service is None:
            service = window.midi_service
        if service is not None and service.is_alive():
            service.request_stop()
            service.join(30)
        window.midi_service = None
        window.midi_worker = None
        window.close()
        application.processEvents()
        diagnostics.shutdown()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--expected-layers", type=int, required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument(
        "--mode",
        choices=("ready-first", "pending-race"),
        default="ready-first",
    )
    parser.add_argument("--report")
    args = parser.parse_args()

    input_path = os.path.abspath(os.path.expanduser(args.input))
    output_root = os.path.abspath(os.path.expanduser(args.output_root))
    if not os.path.isfile(input_path):
        raise SystemExit(f"Input does not exist: {input_path}")
    os.makedirs(output_root, exist_ok=True)

    result = run_gate(input_path, args.expected_layers, output_root, args.mode)
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    print(payload, flush=True)
    if args.report:
        report_path = os.path.abspath(os.path.expanduser(args.report))
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as report:
            report.write(payload + "\n")


if __name__ == "__main__":
    main()
