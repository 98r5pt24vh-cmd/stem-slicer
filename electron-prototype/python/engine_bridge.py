#!/usr/bin/env python3
"""Persistent NDJSON adapter between Electron and the validated 1.9B engines."""

from __future__ import annotations

from array import array
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import redirect_stdout
from dataclasses import asdict, replace
import json
import math
import os
from pathlib import Path
import queue
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid


SOURCE_ROOT = Path(
    os.environ.get(
        "STEM_SLICER_SOURCE_ROOT",
        "/Users/nrgy/Documents/Stem Slicer Repository",
    )
).expanduser().resolve()
if not SOURCE_ROOT.is_dir():
    raise SystemExit(f"Stem Slicer source root is unavailable: {SOURCE_ROOT}")
sys.path.insert(0, str(SOURCE_ROOT))

_write_lock = threading.Lock()
_analyzer = None
_classifier = None
_midi_converter = None
_generation_sessions: dict[str, dict] = {}
_PRIMARY_PRODUCER = "+NRGY"
_COMPACT_KEY = re.compile(r"^[A-G](?:#|b|♯|♭)?(?:(?:m|min|minor|maj|major))?$", re.IGNORECASE)
_MODE_TOKEN = re.compile(r"^(?:m|min|minor|maj|major)$", re.IGNORECASE)


def _key_token_count(tokens: list[str], index: int) -> int:
    token = tokens[index] if 0 <= index < len(tokens) else ""
    if not _COMPACT_KEY.fullmatch(token):
        return 0
    tonic_only = re.fullmatch(r"[A-G](?:#|b|♯|♭)?", token, re.IGNORECASE)
    following = tokens[index + 1] if index + 1 < len(tokens) else ""
    return 2 if tonic_only and _MODE_TOKEN.fullmatch(following) else 1


def _unique_producers(values, *, include_primary: bool = False) -> list[str]:
    credits = []
    seen = set()
    if include_primary:
        credits.append(_PRIMARY_PRODUCER)
        seen.add(_PRIMARY_PRODUCER.casefold())
    for raw_value in values:
        value = str(raw_value or "").strip()
        if not value:
            continue
        if value.casefold() == _PRIMARY_PRODUCER.casefold():
            value = _PRIMARY_PRODUCER
        if value.casefold() in seen:
            continue
        seen.add(value.casefold())
        credits.append(value)
    return credits


def _source_provenance(filename: str) -> dict[str, object]:
    stem = Path(str(filename or "")).stem
    source = re.sub(r"(?:[_\s-])(?:layer\s*)?l?\d+$", "", stem, flags=re.IGNORECASE).strip()
    tokens = [token for token in re.split(r"\s+", source) if token]
    if not tokens:
        return {"loop_name": "Source loop", "producers": [_PRIMARY_PRODUCER]}
    leading_index = 0
    if tokens[0].isdigit() and int(tokens[0]) > 300:
        leading_index = 1
    leading_key_tokens = _key_token_count(tokens, leading_index)
    bpm_index = next(
        (
            index
            for index, token in enumerate(tokens)
            if index >= leading_index
            and token.isdigit()
            and 40 <= int(token) <= 300
        ),
        -1,
    )
    if bpm_index < 0:
        fallback = " ".join(tokens[leading_index + leading_key_tokens :]).strip()
        return {"loop_name": fallback or source or "Source loop", "producers": [_PRIMARY_PRODUCER]}
    loop_name = " ".join(tokens[leading_index + leading_key_tokens : bpm_index]).strip() or "Source loop"
    producer_start = bpm_index + 1
    if leading_key_tokens == 0:
        producer_start += _key_token_count(tokens, producer_start)
    return {
        "loop_name": loop_name,
        "producers": _unique_producers(tokens[producer_start:]) or [_PRIMARY_PRODUCER],
    }


def _record_producers(record: dict) -> list[str]:
    filename = str(record.get("filename") or "").strip()
    if not filename:
        filename = Path(str(record.get("path") or "")).name
    return list(_source_provenance(filename)["producers"])


def _filter_records_by_collaborators(
    records: list[dict],
    *,
    allowed_producers,
    max_producer_count: int,
    categories: tuple[str, ...],
    seed: int,
) -> tuple[list[dict], list[str]]:
    allowed_names = _unique_producers(allowed_producers or ())
    if allowed_names:
        allowed_keys = {producer.casefold() for producer in allowed_names}
        allowed_keys.add(_PRIMARY_PRODUCER.casefold())
        records = [
            record
            for record in records
            if all(producer.casefold() in allowed_keys for producer in _record_producers(record))
        ]

    selected_external: list[str] = []
    if max_producer_count > 0:
        records_by_external_group: dict[tuple[str, ...], list[dict]] = {}
        external_names_by_group: dict[tuple[str, ...], list[str]] = {}
        for record in records:
            credits = _unique_producers(_record_producers(record), include_primary=True)
            if len(credits) != max_producer_count:
                continue
            external_names = [
                producer
                for producer in credits
                if producer.casefold() != _PRIMARY_PRODUCER.casefold()
            ]
            group = tuple(sorted(producer.casefold() for producer in external_names))
            records_by_external_group.setdefault(group, []).append(record)
            external_names_by_group.setdefault(group, external_names)

        groups = list(records_by_external_group)
        random.Random(seed).shuffle(groups)
        tie_order = {group: index for index, group in enumerate(groups)}
        requested_categories = {category.casefold() for category in categories}

        def group_score(group: tuple[str, ...]) -> tuple[int, int, int]:
            group_records = records_by_external_group[group]
            covered_categories = {
                str(
                    record.get("manual_label")
                    or record.get("predicted_label")
                    or ""
                ).casefold()
                for record in group_records
            }
            requested_coverage = len(covered_categories & requested_categories)
            return (-requested_coverage, -len(group_records), tie_order[group])

        if groups:
            selected_group = min(groups, key=group_score)
            records = records_by_external_group[selected_group]
            selected_external = external_names_by_group[selected_group]
        else:
            records = []
    return records, selected_external


def _generation_producers(selections) -> list[str]:
    return _unique_producers(
        (
            producer
            for selection in selections
            for producer in _source_provenance(selection.candidate.path.name)["producers"]
        ),
        include_primary=True,
    )


def _compact_generation_key(key_name: str) -> str:
    normalized = str(key_name or "").strip().replace("♯", "#").replace("♭", "b")
    match = re.fullmatch(
        r"([A-G](?:#|b)?)(?:\s*(major|maj|minor|min|m))?",
        normalized,
        flags=re.IGNORECASE,
    )
    if not match:
        return re.sub(r"\s+", "", normalized) or "Key"
    tonic = f"{match.group(1)[0].upper()}{match.group(1)[1:]}"
    mode = (match.group(2) or "major").casefold()
    return f"{tonic}{'m' if mode in {'minor', 'min', 'm'} else ''}"


def _generation_display_name(
    generation_number: int,
    target_bpm: float,
    target_key: str,
    producers,
) -> str:
    return (
        f"L Gen{max(1, int(generation_number)):02d}_"
        f"{int(round(float(target_bpm)))}_"
        f"{_compact_generation_key(target_key)} "
        f"{' '.join(_unique_producers(producers, include_primary=True))}"
    )


def _rename_generation_master(rendered, display_name: str):
    invalid_filename = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
    filename_stem = invalid_filename.sub("_", str(display_name)).strip(" .") or "Generated Loop"
    desired_path = rendered.output_directory / f"{filename_stem}.mp3"
    if rendered.master_path == desired_path:
        return rendered
    if desired_path.exists():
        raise RuntimeError(f"Refusing to overwrite an existing generated master: {desired_path}")

    manifest = json.loads(rendered.manifest_path.read_text(encoding="utf-8"))
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        raise RuntimeError("The generated-loop manifest has no output map.")
    outputs["master"] = desired_path.name
    outputs["presentation"] = desired_path.name
    temporary_manifest = rendered.manifest_path.with_name(
        f".{uuid.uuid4().hex}-{rendered.manifest_path.name}"
    )
    temporary_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(rendered.master_path, desired_path)
    os.replace(temporary_manifest, rendered.manifest_path)
    return replace(rendered, master_path=desired_path, presentation_path=desired_path)


def send(payload: dict) -> None:
    with _write_lock:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        sys.stdout.flush()


def progress(job_id: str, message: str, current: int, total: int, phase: str) -> None:
    percent = 100 if total <= 0 else round(100 * max(0, min(current, total)) / total)
    send(
        {
            "id": job_id,
            "type": "progress",
            "message": message,
            "phase": phase,
            "current": current,
            "total": total,
            "percent": percent,
        }
    )


def progress_percent(job_id: str, message: str, percent: int, phase: str) -> None:
    value = max(0, min(int(percent), 100))
    send(
        {
            "id": job_id,
            "type": "progress",
            "message": message,
            "phase": phase,
            "current": value,
            "total": 100,
            "percent": value,
        }
    )


def require_file(value: object, *, mp3_only: bool = False) -> Path:
    path = Path(str(value or "")).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Audio file does not exist: {path}")
    if mp3_only and path.suffix.casefold() != ".mp3":
        raise ValueError("Layer extraction accepts one MP3 loop.")
    return path


def require_folder(value: object) -> Path:
    path = Path(str(value or "")).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"Folder does not exist: {path}")
    return path


def output_folder(value: object) -> Path:
    path = Path(str(value or "")).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_name(value: str) -> str:
    cleaned = "".join("-" if char in '\\/:*?\"<>|' else char for char in str(value))
    return " ".join(cleaned.strip().strip(".").split()) or "Untitled"


def unique_session_folder(category: str, base_name: str) -> Path:
    root = Path.home() / "Documents" / "Stem Slicer" / category
    root.mkdir(parents=True, exist_ok=True)
    clean = safe_name(base_name)
    candidate = root / clean
    if not candidate.exists():
        candidate.mkdir()
        return candidate
    stamp = time.strftime("%y-%m-%d %H-%M-%S")
    for suffix in (stamp, f"{stamp}-{uuid.uuid4().hex[:6]}"):
        candidate = root / f"{clean} — {suffix}"
        if not candidate.exists():
            candidate.mkdir()
            return candidate
    raise RuntimeError("Could not create a unique output folder.")


def unique_file(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 10_000):
        candidate = path.with_name(f"{path.stem} {index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not create a unique output file for {path.name}")


class AnalyzerClient:
    def __init__(self) -> None:
        analyzer_root = SOURCE_ROOT / "analyzer"
        command = [
            sys.executable,
            "-u",
            str(analyzer_root / "openkeyscan_analyzer_server.py"),
            "--device",
            "cpu",
            "--workers",
            "1",
        ]
        self.process = subprocess.Popen(
            command,
            cwd=analyzer_root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self.messages: queue.Queue[dict | None] = queue.Queue()
        self.stderr_lines: list[str] = []
        self.lock = threading.Lock()
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        ready = self._next_message(300.0)
        if not ready or ready.get("type") != "ready":
            self.close()
            raise RuntimeError("The OpenKeyScan engine did not become ready.")

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                try:
                    self.messages.put(json.loads(line))
                except json.JSONDecodeError:
                    continue
        finally:
            self.messages.put(None)

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        for line in self.process.stderr:
            self.stderr_lines.append(line.rstrip())
            if len(self.stderr_lines) > 200:
                del self.stderr_lines[:100]

    def _next_message(self, timeout: float) -> dict | None:
        try:
            message = self.messages.get(timeout=timeout)
        except queue.Empty as error:
            detail = "\n".join(self.stderr_lines[-12:])
            raise TimeoutError(f"Key analysis timed out. {detail}".strip()) from error
        if message is None:
            detail = "\n".join(self.stderr_lines[-12:])
            raise RuntimeError(f"The key engine stopped unexpectedly. {detail}".strip())
        return message

    def analyze(self, path: Path) -> dict:
        from engine import find_ffmpeg

        with self.lock:
            request_id = uuid.uuid4().hex
            request = {
                "id": request_id,
                "path": str(path),
                "bpm_mode": "quick_scan_loop",
                "structure_ffmpeg_path": find_ffmpeg(),
            }
            if self.process.stdin is None:
                raise RuntimeError("The key engine input is unavailable.")
            self.process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
            while True:
                message = self._next_message(240.0)
                if message.get("id") != request_id:
                    continue
                if message.get("status") == "error":
                    raise RuntimeError(str(message.get("error") or "Key analysis failed."))
                if message.get("status") == "success":
                    return message

    def close(self) -> None:
        process = self.process
        if process.poll() is not None:
            return
        if process.stdin:
            process.stdin.close()
        try:
            process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            process.terminate()


def analyzer() -> AnalyzerClient:
    global _analyzer
    if _analyzer is None:
        _analyzer = AnalyzerClient()
    return _analyzer


def classifier():
    global _classifier
    if _classifier is None:
        from mert_client import MertLayerClassifier

        _classifier = MertLayerClassifier(
            python_executable=sys.executable,
            artifact_path=SOURCE_ROOT / "models" / "layer_roles_v3.joblib",
            hf_cache_dir=SOURCE_ROOT / "models" / "huggingface",
            feature_cache_path=(
                Path.home()
                / "Library"
                / "Caches"
                / "Stem Slicer"
                / "1.9"
                / "generate"
                / "features.sqlite3"
            ),
            device=os.environ.get("STEM_SLICER_MERT_DEVICE", "cpu"),
        )
    return _classifier


def midi_converter():
    global _midi_converter
    if _midi_converter is None:
        from midi_conversion import MidiConverter

        _midi_converter = MidiConverter()
    return _midi_converter


ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII")
MODE_NAMES = ("Ionian", "Dorian", "Phrygian", "Lydian", "Mixolydian", "Aeolian", "Locrian")
MAJOR_INTERVALS = (0, 2, 4, 5, 7, 9, 11)
SHARP_PITCHES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def scan_payload(source: Path, raw: dict) -> dict:
    from audio_convert import expanded_key_name
    from key_detection import format_camelot

    camelot = str(raw["camelot"])
    detected_compact = format_camelot(camelot, "detected", "sharps")
    relative_mode = "relative_minor" if camelot.endswith("B") else "relative_major"
    relative_compact = format_camelot(camelot, relative_mode, "sharps")
    major_compact = format_camelot(camelot, "relative_major", "sharps")
    major_tonic = major_compact.removesuffix("m")
    tonic = SHARP_PITCHES.index(major_tonic)
    modes = []
    for mode_index in range(7):
        note = SHARP_PITCHES[(tonic + MAJOR_INTERVALS[mode_index]) % 12]
        modes.append(
            {
                "degreeMajor": ROMAN[mode_index],
                "degreeMinor": ROMAN[(mode_index - 5) % 7],
                "key": note,
                "mode": MODE_NAMES[mode_index],
            }
        )
    return {
        "source": str(source),
        "bpm": int(round(float(raw.get("bpm") or 0))),
        "detectedKey": expanded_key_name(detected_compact),
        "relativeKey": expanded_key_name(relative_compact),
        "camelot": camelot,
        "openKey": str(raw.get("openkey") or ""),
        "bpmConfidence": (
            float(raw["bpm_confidence"])
            if raw.get("bpm_confidence") is not None
            else None
        ),
        "bpmSource": str(raw.get("bpm_source") or raw.get("bpm_decision") or "audio"),
        "relativeModes": modes,
        "raw": raw,
    }


def waveform_peaks(path: Path, points: int = 72) -> list[float]:
    from engine import find_ffmpeg

    ffmpeg = find_ffmpeg()
    completed = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            "8000",
            "-f",
            "s16le",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    samples = array("h")
    raw = completed.stdout[: len(completed.stdout) // 2 * 2]
    samples.frombytes(raw)
    if not samples:
        return [0.0] * points
    stride = max(1, len(samples) // points)
    values = [
        max(abs(value) for value in samples[index : index + stride])
        for index in range(0, len(samples), stride)
    ][:points]
    maximum = max(values) or 1
    return [value / maximum for value in values] + [0.0] * max(0, points - len(values))


def audio_duration(path: Path) -> float:
    from engine import find_ffmpeg, find_ffprobe, get_duration

    ffmpeg = find_ffmpeg()
    return float(get_duration(str(path), ffmpeg, find_ffprobe(ffmpeg)) or 0.0)


def artifact_payload(
    path: Path,
    *,
    bpm: int,
    key: str,
    duration: float | None = None,
    peaks: list[float] | None = None,
    midi_path: Path | None = None,
    category: str | None = None,
    alternate_key: str | None = None,
    source_path: Path | None = None,
) -> dict:
    return {
        "path": str(path),
        "name": path.name,
        "displayName": path.stem,
        "bpm": int(bpm),
        "key": key or "—",
        "duration": float(duration if duration is not None else audio_duration(path)),
        "bytes": path.stat().st_size,
        "peaks": list(peaks if peaks is not None else waveform_peaks(path)),
        "midiPath": str(midi_path) if midi_path else None,
        "category": category,
        "alternateKey": alternate_key,
        "sourcePath": str(source_path) if source_path else None,
    }


def target_selection(payload: dict, scan: dict) -> tuple[int | None, str | None]:
    target_bpm = int(payload.get("targetBpm") or 0) if payload.get("targetBpmEnabled") else None
    target_key = str(payload.get("targetKey") or "") if payload.get("targetKeyEnabled") else None
    if target_bpm is not None and not 1 <= target_bpm <= 999:
        raise ValueError("Target BPM must be a valid positive value.")
    return target_bpm, target_key


def target_key_for_source(source_key: str, target_pair: str | None) -> str:
    if not target_pair:
        return source_key
    parts = [part.strip() for part in target_pair.split("/")]
    if source_key.casefold().endswith(" minor") and len(parts) > 1:
        return parts[1]
    return parts[0]


def build_output_stem(source: Path, scan: dict, payload: dict) -> str:
    from filename_templates import parse_loop_filename, render_name

    target_bpm, target_key = target_selection(payload, scan)
    parts = parse_loop_filename(str(source))
    parts["extension"] = ".mp3"
    parts["BPM"] = str(target_bpm or scan["bpm"])
    parts["KEY"] = target_key_for_source(scan["detectedKey"], target_key)
    return Path(render_name(parts, ("LOOP NAME", "BPM", "KEY", "PROD NAME"))).stem


def add_midi(
    job_id: str,
    artifacts: list[dict],
    phase: str,
    *,
    start_percent: int = 0,
    end_percent: int = 99,
) -> None:
    if not artifacts:
        return
    converter = midi_converter()
    total = len(artifacts)
    for index, artifact in enumerate(artifacts, 1):
        audio_path = Path(artifact["path"])
        midi_path = unique_file(audio_path.with_suffix(".mid"))
        starting_percent = start_percent + round(((index - 1) / total) * (end_percent - start_percent))
        progress_percent(
            job_id,
            f"Creating MIDI {index}/{total}: {audio_path.name}",
            starting_percent,
            phase,
        )
        try:
            with redirect_stdout(sys.stderr):
                converter.convert(str(audio_path), str(midi_path), bpm=int(artifact["bpm"]))
            artifact["midiPath"] = str(midi_path)
        except Exception as error:
            artifact["midiPath"] = None
            artifact["midiError"] = str(error)
        percent = start_percent + round((index / total) * (end_percent - start_percent))
        send(
            {
                "id": job_id,
                "type": "progress",
                "message": f"MIDI {index}/{total}: {audio_path.name}",
                "phase": phase,
                "current": index,
                "total": total,
                "percent": percent,
            }
        )
        send({"id": job_id, "type": "artifact", "message": audio_path.name, "artifact": artifact})


def quick_scan(job_id: str, payload: dict) -> dict:
    source = require_file(payload.get("source"))
    progress(job_id, "Loading the musical analysis engine", 1, 20, "engine")
    raw = analyzer().analyze(source)
    result = scan_payload(source, raw)
    progress(job_id, f"Detected {result['bpm']} BPM · {result['detectedKey']}", 1, 1, "analysis")
    return result


def quick_extract(job_id: str, payload: dict) -> dict:
    from audio_convert import ConversionRequest, convert_audio
    from engine import process_single_file
    from filename_templates import parse_loop_filename

    source = require_file(payload.get("source"), mp3_only=True)
    destination = unique_session_folder("Quick Extract", source.stem)
    target_active = bool(payload.get("targetBpmEnabled") or payload.get("targetKeyEnabled"))
    scan = None
    output_stem = source.stem
    started = time.perf_counter()
    if target_active:
        progress(job_id, "Analyzing source BPM and key", 0, 4, "analysis")
        scan = scan_payload(source, analyzer().analyze(source))
        output_stem = build_output_stem(source, scan, payload)
    progress(job_id, "Detecting and exporting layers", 1, 4, "extraction")
    diagnostics = process_single_file(str(source), str(destination), output_stem)
    exported = [
        row
        for row in diagnostics
        if row.get("event") == "exported" and row.get("output_exists")
    ]
    if not exported:
        raise RuntimeError("No layer could be extracted from this loop.")

    if scan is not None:
        target_bpm, target_key = target_selection(payload, scan)

        def convert_row(row: dict):
            source_layer = destination / row["output_name"]
            staged = destination / f".{uuid.uuid4().hex}-{source_layer.name}"
            result = convert_audio(
                ConversionRequest(
                    source=source_layer,
                    destination=staged,
                    source_bpm=scan["bpm"],
                    target_bpm=target_bpm,
                    source_key=scan["detectedKey"],
                    target_key=target_key,
                )
            )
            os.replace(staged, source_layer)
            return row, result

        progress(job_id, "Applying target BPM and key", 2, 4, "conversion")
        with ThreadPoolExecutor(max_workers=min(4, len(exported))) as executor:
            converted = list(executor.map(convert_row, exported))
        conversion_by_name = {row["output_name"]: result for row, result in converted}
    else:
        conversion_by_name = {}

    parsed = parse_loop_filename(str(source))
    artifacts = []
    for row in exported:
        path = destination / row["output_name"]
        artifacts.append(
            artifact_payload(
                path,
                bpm=int((target_selection(payload, scan)[0] if scan else None) or row.get("bpm") or parsed.get("BPM") or 140),
                key=(target_key_for_source(scan["detectedKey"], target_selection(payload, scan)[1]) if scan else parsed.get("KEY") or "—"),
                duration=(float(row.get("duration_seconds") or 0) / float(conversion_by_name[row["output_name"]].speed_ratio) if row["output_name"] in conversion_by_name else float(row.get("duration_seconds") or 0)),
                peaks=list(row.get("waveform_peaks") or waveform_peaks(path)),
                source_path=source,
            )
        )
    progress(job_id, f"{len(artifacts)} audio layers ready", 3, 4, "audio")
    add_midi(job_id, artifacts, "midi", start_percent=75, end_percent=99)
    progress(job_id, "Quick Extract complete", 4, 4, "complete")
    return {
        "outputFolder": str(destination),
        "layers": artifacts,
        "elapsedSeconds": time.perf_counter() - started,
    }


def quick_convert(job_id: str, payload: dict) -> dict:
    from audio_convert import ConversionRequest, convert_audio

    source = require_file(payload.get("source"))
    if not payload.get("targetBpmEnabled") and not payload.get("targetKeyEnabled"):
        raise ValueError("Enable Target BPM, Target Key, or both before converting.")
    destination = unique_session_folder("Quick Convert", source.stem)
    started = time.perf_counter()
    progress(job_id, "Analyzing source BPM and key", 0, 3, "analysis")
    scan = scan_payload(source, analyzer().analyze(source))
    target_bpm, target_key = target_selection(payload, scan)
    stem = build_output_stem(source, scan, payload)
    output = unique_file(destination / f"{stem}.mp3")
    progress(job_id, "Converting BPM and key", 1, 3, "conversion")
    convert_audio(
        ConversionRequest(
            source=source,
            destination=output,
            source_bpm=scan["bpm"],
            target_bpm=target_bpm,
            source_key=scan["detectedKey"],
            target_key=target_key,
        ),
        progress=lambda message: send(
            {
                "id": job_id,
                "type": "progress",
                "message": message,
                "phase": "conversion",
                "current": 2,
                "total": 3,
                "percent": 67,
            }
        ),
    )
    artifact = artifact_payload(
        output,
        bpm=target_bpm or scan["bpm"],
        key=target_key_for_source(scan["detectedKey"], target_key),
        source_path=source,
    )
    send({"id": job_id, "type": "artifact", "message": output.name, "artifact": artifact})
    progress(job_id, "Quick Convert complete", 3, 3, "complete")
    return {
        "outputFolder": str(destination),
        "artifact": artifact,
        "sourceBpm": scan["bpm"],
        "sourceKey": scan["detectedKey"],
        "targetBpm": target_bpm or scan["bpm"],
        "targetKey": target_key_for_source(scan["detectedKey"], target_key),
        "elapsedSeconds": time.perf_counter() - started,
    }


def batch(job_id: str, payload: dict) -> dict:
    from audio_convert import ConversionRequest, convert_audio
    from engine import process_audio
    from filename_templates import parse_loop_filename, render_name
    from key_detection import format_camelot

    source = require_folder(payload.get("sourceFolder"))
    destination = output_folder(payload.get("outputFolder"))
    files = sorted(source.glob("*.mp3"))
    if not files:
        raise ValueError("No MP3 files were found in the source folder.")
    extraction = bool(payload.get("extractionEnabled"))
    key_analysis = bool(payload.get("keyAnalysisEnabled"))
    conversion = bool(payload.get("conversionEnabled"))
    if not (extraction or key_analysis or conversion):
        raise ValueError("Enable at least one batch operation.")
    if conversion and not (payload.get("targetBpmEnabled") or payload.get("targetKeyEnabled")):
        raise ValueError("Enable Target BPM, Target Key, or both for conversion.")

    analyses: dict[str, dict | Exception] = {}
    raw_results: dict[str, dict | Exception] = {}
    failures: list[dict] = []
    needs_analysis = key_analysis or conversion
    analysis_steps = len(files) if needs_analysis else 0
    process_steps = len(files)
    total = max(1, analysis_steps + process_steps + (len(files) if conversion else 0))
    current = 0
    if needs_analysis:
        for file in files:
            try:
                raw = analyzer().analyze(file)
                scan = scan_payload(file, raw)
                analyses[file.name] = scan
                raw_results[file.name] = raw
                message = f"Analyzed {scan['bpm']} BPM · {scan['detectedKey']}: {file.name}"
            except Exception as error:
                analyses[file.name] = error
                raw_results[file.name] = error
                failures.append({"source": file.name, "message": str(error)})
                message = f"Analysis unavailable: {file.name}"
            current += 1
            progress(job_id, message, current, total, "analysis")

    output_stems: dict[str, str] = {}
    token_order = tuple(str(item).upper() for item in payload.get("tokenOrder") or ("LOOP NAME", "BPM", "KEY", "PROD NAME"))
    for file in files:
        parts = parse_loop_filename(file.name)
        scan = analyses.get(file.name)
        if isinstance(scan, dict):
            if conversion:
                target_bpm, target_key = target_selection(payload, scan)
                parts["BPM"] = str(target_bpm or scan["bpm"])
                parts["KEY"] = target_key_for_source(scan["detectedKey"], target_key)
            elif key_analysis:
                mode = str(payload.get("keyMode") or "detected")
                accidentals = str(payload.get("accidentals") or "sharps")
                parts["KEY"] = format_camelot(str(scan["camelot"]), mode, accidentals)
            output_stems[file.name] = Path(render_name(parts, token_order)).stem
        else:
            output_stems[file.name] = file.stem
    if len(set(output_stems.values())) != len(output_stems):
        raise RuntimeError("The selected filename structure creates duplicate output names.")

    manifest = None
    engine_failures = []
    if extraction or (key_analysis and not conversion):
        state = {"error": "", "manifest": None, "failures": []}

        def report_engine(done: int, engine_total: int, status: str) -> None:
            fraction = done / engine_total if engine_total else 0
            mapped = current + round(fraction * process_steps)
            progress(job_id, status, mapped, total, "extraction" if extraction else "naming")

        settings = {
            "enabled": key_analysis,
            "extract_enabled": extraction,
            "destination_mode": str(payload.get("destinationMode") or "copy_to_output"),
            "token_order": token_order,
            "mode": str(payload.get("keyMode") or "detected"),
            "accidentals": str(payload.get("accidentals") or "sharps"),
            "analysis_results": raw_results,
            "output_stems_override": output_stems,
        }
        process_audio(
            str(source),
            str(destination),
            report_engine,
            lambda items, item_manifest: state.update(failures=list(items), manifest=item_manifest),
            lambda message: state.update(error=str(message)),
            settings,
            analyzer=None,
        )
        if state["error"]:
            raise RuntimeError(state["error"])
        engine_failures = [
            {"source": str(item[0]), "message": str(item[1])}
            for item in state["failures"]
        ]
        failures.extend(engine_failures)
        manifest = state["manifest"]
        current += process_steps

    outputs_by_source = dict((manifest or {}).get("outputs_by_source") or {})
    if conversion:
        if extraction:
            conversion_items = [
                (file, Path(layer))
                for file in files
                for layer in outputs_by_source.get(file.name, [])
            ]
        else:
            conversion_items = [(file, file) for file in files]
        conversion_total = max(1, len(conversion_items))
        converted_outputs: dict[str, list[str]] = {file.name: [] for file in files}
        for index, (source_file, audio_file) in enumerate(conversion_items, 1):
            scan = analyses.get(source_file.name)
            if not isinstance(scan, dict):
                continue
            try:
                target_bpm, target_key = target_selection(payload, scan)
                final_name = audio_file.name if extraction else f"{output_stems[source_file.name]}.mp3"
                final = destination / final_name
                staged = destination / f".{uuid.uuid4().hex}-{final_name}"
                convert_audio(
                    ConversionRequest(
                        source=audio_file,
                        destination=staged,
                        source_bpm=scan["bpm"],
                        target_bpm=target_bpm,
                        source_key=scan["detectedKey"],
                        target_key=target_key,
                    )
                )
                os.replace(staged, final)
                converted_outputs[source_file.name].append(str(final))
            except Exception as error:
                failures.append({"source": source_file.name, "message": str(error)})
            mapped = current + round(index / conversion_total * max(1, total - current))
            progress(job_id, f"Converted: {audio_file.name}", mapped, total, "conversion")
        outputs_by_source = converted_outputs
    elif not extraction and key_analysis:
        outputs_by_source = {
            file.name: [str(destination / f"{output_stems[file.name]}.mp3")]
            for file in files
        }

    outputs = [path for paths in outputs_by_source.values() for path in paths]
    progress(job_id, "Batch complete", total, total, "complete")
    return {
        "outputFolder": str(destination),
        "files": len(files),
        "outputs": outputs,
        "failures": failures,
    }


def library_scan(job_id: str, payload: dict) -> dict:
    from key_confidence import KeyConfidenceIndex
    from layer_library import LayerLibrary

    root = require_folder(payload.get("root"))
    database = Path(str(payload.get("databasePath") or "")).expanduser().resolve()
    accepted_root = Path.home() / "Library" / "Caches" / "Stem Slicer" / "1.9"
    try:
        database.relative_to(accepted_root)
    except ValueError as error:
        raise ValueError("Generate scans must use the active 1.9 cache.") from error
    database.parent.mkdir(parents=True, exist_ok=True)
    key_metadata = database.parent / "key-confidence-v2"
    inventory_path = key_metadata / "original_loop_inventory.json"
    results_path = key_metadata / "key_confidence_results_v2.json"
    if inventory_path.is_file() and results_path.is_file():
        key_confidence_index = KeyConfidenceIndex.from_files(
            library_root=root,
            inventory_path=inventory_path,
            results_path=results_path,
        )
    else:
        key_confidence_index = KeyConfidenceIndex()
    library = LayerLibrary(
        root,
        database,
        classifier=classifier(),
        key_confidence_index=key_confidence_index,
    )

    def report(item) -> None:
        phase_label = {
            "inventory": "Inventorying library",
            "metadata": "Reading metadata",
            "classify": "Classifying layers",
            "complete": "Library ready",
            "cancelled": "Scan cancelled",
        }.get(item.phase, str(item.phase).title())
        message = f"{phase_label}: {item.relative_path}" if item.relative_path else phase_label
        progress(job_id, message, int(item.completed), int(item.total), str(item.phase))

    result = library.scan(progress=report)
    return {
        "root": result.library_root,
        "totalFiles": result.inventory_count,
        "added": max(0, result.hashed_count - result.cached_count),
        "updated": result.hashed_count,
        "unchanged": result.cached_count,
        "removed": 0,
        "issues": len(result.issues),
    }


def generation_artifacts(
    rendered,
    request,
    midi_by_identity: dict[str, str] | None = None,
    source_metadata_by_path: dict[str, dict] | None = None,
) -> list[dict]:
    duration = rendered.timeline.loop_frames / rendered.timeline.sample_rate
    artifacts = []
    midi_paths = midi_by_identity or {}
    metadata_by_path = source_metadata_by_path or {}
    for stem in rendered.stem_results:
        selection = stem.selection
        source_path = str(selection.candidate.path.resolve())
        source_metadata = metadata_by_path.get(source_path, {})
        provenance = _source_provenance(selection.candidate.path.name)
        alternate = selection.candidate.alternate_scanned_key
        alternate_mode = selection.candidate.alternate_scanned_mode or ""
        detected_key = selection.candidate.scanned_key or selection.candidate.source_key
        detected_mode = (
            selection.candidate.scanned_mode
            if selection.candidate.scanned_key
            else selection.candidate.source_mode
        )
        artifact = artifact_payload(
            stem.output_path,
            bpm=int(round(request.plan.request.target_bpm)),
            key=request.plan.request.target_key,
            duration=duration,
            peaks=list(stem.waveform_peaks),
            category=selection.category,
            alternate_key=(f"{alternate} {alternate_mode}".strip() if alternate else None),
            source_path=selection.candidate.path,
        )
        artifact.update(
            {
                "identity": selection.candidate.identity,
                "sourceFile": selection.candidate.path.name,
                "sourceLoopId": selection.candidate.source_loop_id,
                "sourceLoopName": provenance["loop_name"],
                "producers": provenance["producers"],
                "libraryRoot": source_metadata.get("library_root"),
                "sourceDetectedKey": " ".join(
                    item for item in (detected_key, detected_mode) if item
                ),
                "sourceKeyRank": selection.source_key_rank,
                "octave": int(selection.manual_pitch_semitones // 12),
                "locked": (
                    request.plan.request.locked_identities_by_slot[selection.slot_index]
                    == selection.candidate.identity
                ),
            }
        )
        midi_path = midi_paths.get(selection.candidate.identity)
        if midi_path:
            artifact["midiPath"] = midi_path
        artifacts.append(artifact)
    return artifacts


def generation(job_id: str, payload: dict) -> dict:
    from generation_policy import GenerationRequest, LayerCandidate, select_generation
    from generation_renderer import (
        BungeePCMBackend,
        FFmpegMP3Encoder,
        RenderRequest,
        render_generation,
    )

    generation_started = time.perf_counter()
    database = Path(str(payload.get("databasePath") or "")).expanduser().resolve()
    if not database.is_file():
        raise ValueError("The Generate library cache is unavailable.")
    roots = [str(Path(item).expanduser().resolve()) for item in payload.get("libraryRoots") or []]
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(layer_cache)")
        }
        conditions: list[str] = []
        parameters: list[str] = []
        if "manual_excluded" in columns:
            conditions.append("COALESCE(manual_excluded, 0) = 0")
        if roots:
            conditions.append(f"library_root IN ({','.join('?' for _ in roots)})")
            parameters.extend(roots)
        query = "SELECT * FROM layer_cache"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        records = [dict(row) for row in connection.execute(query, parameters)]
    excluded_source_loops = {
        (
            str(Path(str(item.get("libraryRoot") or "")).expanduser().resolve()),
            str(item.get("sourceLoopId") or "").strip(),
        )
        for item in payload.get("excludedSourceLoops") or ()
        if isinstance(item, dict)
        and str(item.get("libraryRoot") or "").strip()
        and str(item.get("sourceLoopId") or "").strip()
    }
    quarantined_count = 0
    if excluded_source_loops:
        eligible_records = []
        for record in records:
            source_identity = (
                str(Path(str(record.get("library_root") or "")).expanduser().resolve()),
                str(record.get("source_loop_id") or "").strip(),
            )
            if source_identity in excluded_source_loops:
                quarantined_count += 1
            else:
                eligible_records.append(record)
        records = eligible_records
    categories = tuple(str(item) for item in payload.get("categories") or ())
    max_producer_count = max(0, int(payload.get("maxProducerCount") or 0))
    records, selected_external_producers = _filter_records_by_collaborators(
        records,
        allowed_producers=payload.get("allowedProducers"),
        max_producer_count=max_producer_count,
        categories=categories,
        seed=int(payload.get("seed") or 0),
    )
    if not records:
        raise ValueError("No indexed layer matches the current collaborator selection.")
    quarantine_label = f" · {quarantined_count} quarantined" if quarantined_count else ""
    collaborator_label = ""
    if max_producer_count == 1:
        collaborator_label = " · solo"
    elif selected_external_producers:
        collaborator_label = f" · +NRGY + {' + '.join(selected_external_producers)}"
    progress_percent(
        job_id,
        f"Loaded {len(records)} indexed layers{quarantine_label}{collaborator_label}",
        3,
        "selection",
    )
    request = GenerationRequest(
        categories=categories,
        target_bpm=float(payload.get("targetBpm") or 140),
        target_key=str(payload.get("targetKey") or "A minor"),
        bars=int(payload.get("bars") or 8),
        seed=int(payload.get("seed") or 0),
        allow_uncertain_key_reserve=False,
        locked_identities_by_slot=tuple(payload.get("lockedIdentitiesBySlot") or ()),
        excluded_identities=frozenset(str(item) for item in payload.get("excludedIdentities") or ()),
    )
    candidates = []
    skipped = 0
    source_metadata_by_path = {
        str(Path(str(record.get("path") or "")).expanduser().resolve()): record
        for record in records
        if record.get("path")
    }
    for record in records:
        if not Path(str(record.get("path") or "")).is_file():
            skipped += 1
            continue
        try:
            candidates.append(LayerCandidate.from_record(record))
        except Exception:
            skipped += 1
    if not candidates:
        raise ValueError("No scanned layer has enough BPM/key metadata to generate.")
    progress_percent(
        job_id,
        f"Selecting compatible layers ({skipped} metadata rows skipped)",
        8,
        "selection",
    )
    selection_started = time.perf_counter()
    plan = select_generation(candidates, request)
    selection_seconds = time.perf_counter() - selection_started
    progress_percent(
        job_id,
        f"Selected {len(plan.selections)} compatible layers in {selection_seconds:.2f}s",
        12,
        "selection",
    )
    generation_number = max(1, int(payload.get("generationNumber") or 1))
    producers = _generation_producers(plan.selections)
    display_name = _generation_display_name(
        generation_number,
        request.target_bpm,
        request.target_key,
        producers,
    )

    class ReportingBackend:
        def __init__(self) -> None:
            self.backend = BungeePCMBackend()
            self.completed = 0
            self.total = len(plan.selections)

        def transform(self, selection, *, target_bpm: float, sample_rate: int, channels: int):
            start = 15 + round((self.completed / max(1, self.total)) * 48)
            progress_percent(
                job_id,
                f"Rendering layer {self.completed + 1}/{self.total}: {selection.category}",
                start,
                "render",
            )
            audio = self.backend.transform(
                selection,
                target_bpm=target_bpm,
                sample_rate=sample_rate,
                channels=channels,
            )
            self.completed += 1
            completed = 15 + round((self.completed / max(1, self.total)) * 48)
            progress_percent(
                job_id,
                f"Rendered layer {self.completed}/{self.total}: {selection.category}",
                completed,
                "render",
            )
            return audio

    class ReportingEncoder:
        def __init__(self) -> None:
            self.encoder = FFmpegMP3Encoder()
            self.completed = 0
            self.total = len(plan.selections) + 1

        def encode(self, destination, audio, *, sample_rate: int, bitrate_bps: int) -> None:
            start = 64 + round((self.completed / max(1, self.total)) * 15)
            progress_percent(
                job_id,
                f"Encoding audio {self.completed + 1}/{self.total}: {destination.name}",
                start,
                "encode",
            )
            self.encoder.encode(
                destination,
                audio,
                sample_rate=sample_rate,
                bitrate_bps=bitrate_bps,
            )
            self.completed += 1
            completed = 64 + round((self.completed / max(1, self.total)) * 15)
            progress_percent(
                job_id,
                f"Encoded audio {self.completed}/{self.total}: {destination.name}",
                completed,
                "encode",
            )

    render_request = RenderRequest(
        plan=plan,
        output_root=Path.home() / "Documents" / "Stem Slicer" / "Generated Loops",
        generation_name=display_name,
    )
    rendered = render_generation(
        render_request,
        backend=ReportingBackend(),
        encoder=ReportingEncoder(),
    )
    rendered = _rename_generation_master(rendered, display_name)
    artifacts = generation_artifacts(
        rendered,
        render_request,
        source_metadata_by_path=source_metadata_by_path,
    )
    add_midi(job_id, artifacts, "midi", start_percent=80, end_percent=99)
    midi_by_identity = {
        str(artifact.get("identity")): str(artifact["midiPath"])
        for artifact in artifacts
        if artifact.get("identity") and artifact.get("midiPath")
    }
    session_key = str(rendered.output_directory)
    _generation_sessions[session_key] = {
        "request": render_request,
        "result": rendered,
        "midi": midi_by_identity,
        "source_metadata": source_metadata_by_path,
        "generation_number": generation_number,
        "display_name": display_name,
        "producers": producers,
    }
    while len(_generation_sessions) > 4:
        _generation_sessions.pop(next(iter(_generation_sessions)))
    progress(job_id, "Generation complete", 10, 10, "complete")
    elapsed_seconds = time.perf_counter() - generation_started
    return {
        "outputDirectory": str(rendered.output_directory),
        "masterPath": str(rendered.master_path),
        "manifestPath": str(rendered.manifest_path),
        "seed": request.seed,
        "targetBpm": request.target_bpm,
        "targetKey": request.target_key,
        "generationNumber": generation_number,
        "displayName": display_name,
        "producers": producers,
        "elapsedSeconds": elapsed_seconds,
        "selectionSeconds": selection_seconds,
        "layers": artifacts,
    }


def generation_update(job_id: str, payload: dict) -> dict:
    from generation_policy import plan_with_manual_pitch, plan_with_source_key_rank
    from generation_renderer import rerender_selected_layer

    session_key = str(Path(str(payload.get("outputDirectory") or "")).expanduser().resolve())
    session = _generation_sessions.get(session_key)
    if session is None:
        raise ValueError("This generated stack is no longer active. Generate it again before editing a card.")
    identity = str(payload.get("identity") or "").strip()
    if not identity:
        raise ValueError("The generated layer identity is unavailable.")
    slot_index = int(payload.get("slotIndex") or 0)
    render_request = session["request"]
    rendered = session["result"]
    update = str(payload.get("update") or "")
    if update == "octave":
        octave = int(payload.get("octave") or 0)
        if octave not in (-1, 0, 1):
            raise ValueError("Octave must be -1, 0 or +1.")
        updated_plan = plan_with_manual_pitch(
            render_request.plan,
            slot_index=slot_index,
            identity=identity,
            semitones=octave * 12,
        )
    elif update == "source-key":
        source_key_rank = int(payload.get("sourceKeyRank") or 1)
        updated_plan = plan_with_source_key_rank(
            render_request.plan,
            slot_index=slot_index,
            identity=identity,
            source_key_rank=source_key_rank,
        )
    else:
        raise ValueError("Unsupported generated-layer update.")
    updated_request = replace(render_request, plan=updated_plan)

    def report(message: str, completed: int, total: int) -> None:
        progress(job_id, message, completed, max(1, total + 1), "rerender")

    updated_result = rerender_selected_layer(
        updated_request,
        rendered,
        slot_index=slot_index,
        identity=identity,
        progress=report,
    )
    midi_by_identity = dict(session.get("midi") or {})
    target_stem = next(
        item for item in updated_result.stem_results
        if item.selection.candidate.identity == identity
    )
    midi_target = Path(midi_by_identity.get(identity) or target_stem.output_path.with_suffix(".mid"))
    staged_midi = midi_target.with_name(f".{uuid.uuid4().hex}-{midi_target.name}")
    progress(job_id, "Updating MIDI", 2, 3, "midi")
    with redirect_stdout(sys.stderr):
        midi_converter().convert(
            str(target_stem.output_path),
            str(staged_midi),
            bpm=int(round(updated_request.plan.request.target_bpm)),
        )
    os.replace(staged_midi, midi_target)
    midi_by_identity[identity] = str(midi_target)
    artifacts = generation_artifacts(
        updated_result,
        updated_request,
        midi_by_identity,
        session.get("source_metadata") or {},
    )
    session.update({"request": updated_request, "result": updated_result, "midi": midi_by_identity})
    progress(job_id, "Layer update complete", 3, 3, "complete")
    return {
        "outputDirectory": str(updated_result.output_directory),
        "masterPath": str(updated_result.master_path),
        "manifestPath": str(updated_result.manifest_path),
        "seed": updated_request.plan.request.seed,
        "targetBpm": updated_request.plan.request.target_bpm,
        "targetKey": updated_request.plan.request.target_key,
        "generationNumber": session.get("generation_number"),
        "displayName": session.get("display_name"),
        "producers": session.get("producers") or [_PRIMARY_PRODUCER],
        "layers": artifacts,
    }


HANDLERS = {
    "quick-scan": quick_scan,
    "quick-extract": quick_extract,
    "quick-convert": quick_convert,
    "batch": batch,
    "library-scan": library_scan,
    "generate": generation,
    "generate-update": generation_update,
}


def execute(command: dict) -> None:
    job_id = str(command.get("id") or "")
    kind = str(command.get("kind") or "")
    payload = command.get("payload") or {}
    if not job_id or kind not in HANDLERS or not isinstance(payload, dict):
        send({"id": job_id, "type": "error", "error": "Invalid engine request."})
        return
    try:
        result = HANDLERS[kind](job_id, payload)
        send({"id": job_id, "type": "result", "message": "Complete", "result": result})
    except Exception as error:
        traceback.print_exc(file=sys.stderr)
        send(
            {
                "id": job_id,
                "type": "error",
                "message": str(error),
                "error": f"{type(error).__name__}: {error}",
            }
        )


def close_engines() -> None:
    if _analyzer is not None:
        _analyzer.close()
    if _classifier is not None:
        try:
            _classifier.close()
        except Exception:
            pass


def main() -> int:
    # Load the accepted Basic Pitch/ONNX stack before render engines alter the
    # process-wide native-library environment. Generate must also work as the
    # very first action in a fresh Electron session.
    midi_converter()
    send(
        {
            "type": "ready",
            "python": sys.executable,
            "version": sys.version.split()[0],
            "sourceRoot": str(SOURCE_ROOT),
        }
    )
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="StemSlicerEngine")
    futures = []
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                command = json.loads(line)
            except json.JSONDecodeError:
                send({"id": "", "type": "error", "error": "Invalid JSON request."})
                continue
            if command.get("type") == "shutdown":
                break
            futures.append(executor.submit(execute, command))
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        close_engines()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
