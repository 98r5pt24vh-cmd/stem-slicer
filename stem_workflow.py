"""Validated 1.8.2B orchestration shared by the native interface.

This module keeps UI code away from the audio pipeline.  A loop is analyzed at
most once per operation, extraction always precedes conversion, and converted
files are staged before becoming visible in their final destination.
"""

from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

from PySide6.QtCore import QObject, Signal, Slot

from audio_convert import ConversionRequest, convert_audio, expanded_key_name
from diagnostics_runtime import get_diagnostics
from engine import find_ffmpeg, process_audio, process_single_file
from filename_templates import parse_loop_filename, render_name
from functional_core import canonical_loop_bpm, waveform_peaks
from key_detection import format_camelot
from storage import StorageManager


DEFAULT_OUTPUT_ORDER = ("LOOP NAME", "BPM", "KEY", "PROD NAME")


@dataclass(frozen=True)
class TargetSelection:
    bpm_enabled: bool
    bpm: int | None
    key_enabled: bool
    key_pair: str | None

    @property
    def active(self) -> bool:
        return self.bpm_enabled or self.key_enabled


@dataclass(frozen=True)
class LoopAnalysis:
    bpm: int
    camelot: str
    source_key: str

    @property
    def is_minor(self) -> bool:
        return self.source_key.lower().endswith(" minor")


def analyze_loop(analyzer, path: str) -> tuple[LoopAnalysis, dict]:
    if analyzer is None:
        raise RuntimeError("The musical key engine is not ready.")
    raw = analyzer.analyze(
        path,
        bpm_mode="quick_scan_loop",
        structure_ffmpeg_path=find_ffmpeg(),
    )
    bpm = canonical_loop_bpm(raw.get("bpm"))
    if not bpm:
        raise ValueError("The source BPM could not be detected.")
    compact_key = format_camelot(raw["camelot"], "detected", "sharps")
    return LoopAnalysis(bpm, raw["camelot"], expanded_key_name(compact_key)), raw


def target_key_for_source(analysis: LoopAnalysis, target_pair: str | None) -> str:
    if not target_pair:
        return analysis.source_key
    parts = [part.strip() for part in target_pair.split("/")]
    if analysis.is_minor and len(parts) > 1:
        return parts[1]
    return parts[0]


def resolved_target_bpm(analysis: LoopAnalysis, target: TargetSelection) -> int:
    return int(target.bpm) if target.bpm_enabled and target.bpm else analysis.bpm


def build_output_stem(
    source: str,
    analysis: LoopAnalysis | None,
    target: TargetSelection | None,
    *,
    key_analysis_enabled: bool = False,
    key_mode: str = "detected",
    accidentals: str = "sharps",
    token_order=DEFAULT_OUTPUT_ORDER,
) -> str:
    parts = parse_loop_filename(source)
    parts["extension"] = ".mp3"
    if analysis is not None and target is not None and target.active:
        parts["BPM"] = str(resolved_target_bpm(analysis, target))
        if target.key_enabled:
            parts["KEY"] = target_key_for_source(analysis, target.key_pair)
        elif key_analysis_enabled:
            parts["KEY"] = format_camelot(analysis.camelot, key_mode, accidentals)
        else:
            parts["KEY"] = analysis.source_key
    elif analysis is not None and key_analysis_enabled:
        parts["KEY"] = format_camelot(analysis.camelot, key_mode, accidentals)
    rendered = render_name(parts, token_order)
    return os.path.splitext(rendered)[0]


def _selection(bpm_enabled, bpm, key_enabled, key_pair) -> TargetSelection:
    parsed_bpm = int(bpm) if bpm_enabled and bpm else None
    if parsed_bpm is not None and not 1 <= parsed_bpm <= 999:
        raise ValueError("Target BPM must contain a valid positive value.")
    return TargetSelection(bool(bpm_enabled), parsed_bpm, bool(key_enabled), key_pair if key_enabled else None)


def _converted_layer_metadata(path, row, analysis, target, speed_ratio=1.0):
    duration = float(row.get("duration_seconds") or 0)
    if speed_ratio > 0:
        duration /= speed_ratio
    return {
        "path": path,
        "name": os.path.basename(path),
        "display_name": os.path.splitext(os.path.basename(path))[0],
        "key": target_key_for_source(analysis, target.key_pair) if target.key_enabled else analysis.source_key,
        "bpm": resolved_target_bpm(analysis, target),
        "duration": duration,
        "bytes": os.path.getsize(path),
        "peaks": waveform_peaks(path),
    }


class QuickExtractWorkflowWorker(QObject):
    completed = Signal(object, float)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, analyzer, source, output, *, bpm_enabled, bpm, key_enabled, key_pair):
        super().__init__()
        self.analyzer = analyzer
        self.source = source
        self.output = output
        self.target = _selection(bpm_enabled, bpm, key_enabled, key_pair)

    @Slot()
    def run(self):
        started = time.perf_counter()
        diagnostics_log = get_diagnostics()
        diagnostics_log.event(
            "quick_extract_started",
            file=self.source,
            output_folder=self.output,
            target_bpm=self.target.bpm if self.target.bpm_enabled else None,
            target_key=self.target.key_pair if self.target.key_enabled else None,
        )
        try:
            analysis = None
            output_stem = os.path.splitext(os.path.basename(self.source))[0]
            if self.target.active:
                analysis, _ = analyze_loop(self.analyzer, self.source)
                output_stem = build_output_stem(self.source, analysis, self.target)
            conversion_results = {}
            if sys.platform == "win32" and analysis is not None:
                # Keep freshly written MP3s away from Explorer/Defender until
                # every conversion is complete.  Windows can otherwise lock a
                # raw layer between extraction and its atomic replacement.
                with tempfile.TemporaryDirectory(prefix="stem-slicer-quick-extract-") as staging:
                    raw_folder = os.path.join(staging, "raw")
                    converted_folder = os.path.join(staging, "converted")
                    os.makedirs(raw_folder, exist_ok=True)
                    os.makedirs(converted_folder, exist_ok=True)
                    diagnostics = process_single_file(self.source, raw_folder, output_stem)
                    exported = [
                        row for row in diagnostics
                        if row.get("event") == "exported" and row.get("output_exists")
                    ]

                    def convert_windows_layer(row):
                        output_name = row["output_name"]
                        try:
                            result = convert_audio(ConversionRequest(
                                source=Path(raw_folder, output_name),
                                destination=Path(converted_folder, output_name),
                                source_bpm=analysis.bpm,
                                target_bpm=self.target.bpm if self.target.bpm_enabled else None,
                                source_key=analysis.source_key,
                                target_key=self.target.key_pair if self.target.key_enabled else None,
                            ))
                        except Exception as exc:
                            raise RuntimeError(f"Optional Target failed for {output_name}: {exc}") from exc
                        return output_name, result

                    worker_count = min(4, len(exported))
                    with ThreadPoolExecutor(max_workers=worker_count) as executor:
                        converted = list(executor.map(convert_windows_layer, exported))
                    conversion_results.update(converted)

                    os.makedirs(self.output, exist_ok=True)
                    for row in exported:
                        output_name = row["output_name"]
                        final_layer = os.path.join(self.output, output_name)
                        if os.path.exists(final_layer):
                            raise FileExistsError(f"The output layer already exists: {output_name}")
                        shutil.copyfile(os.path.join(converted_folder, output_name), final_layer)
            else:
                diagnostics = process_single_file(self.source, self.output, output_stem)
                exported = [
                    row for row in diagnostics
                    if row.get("event") == "exported" and row.get("output_exists")
                ]

            if sys.platform != "win32" and analysis is not None and exported:
                with tempfile.TemporaryDirectory(prefix=".stem-slicer-stage-", dir=self.output) as staging:
                    def convert_layer(row):
                        source_layer = os.path.join(self.output, row["output_name"])
                        staged_layer = os.path.join(staging, row["output_name"])
                        result = convert_audio(ConversionRequest(
                            source=Path(source_layer),
                            destination=Path(staged_layer),
                            source_bpm=analysis.bpm,
                            target_bpm=self.target.bpm if self.target.bpm_enabled else None,
                            source_key=analysis.source_key,
                            target_key=self.target.key_pair if self.target.key_enabled else None,
                        ))
                        return row["output_name"], staged_layer, source_layer, result

                    # Four conversions gave the best stable latency/CPU balance
                    # in the 17-layer reference benchmark.  Each task owns its
                    # temporary files, and final files remain atomic below.
                    worker_count = min(4, len(exported))
                    with ThreadPoolExecutor(max_workers=worker_count) as executor:
                        converted = list(executor.map(convert_layer, exported))

                    staged = []
                    for output_name, staged_layer, source_layer, result in converted:
                        staged.append((staged_layer, source_layer))
                        conversion_results[output_name] = result
                    for staged_layer, source_layer in staged:
                        os.replace(staged_layer, source_layer)

            layers = []
            for row in exported:
                path = os.path.join(self.output, row["output_name"])
                if analysis is not None:
                    result = conversion_results[row["output_name"]]
                    layers.append(_converted_layer_metadata(path, row, analysis, self.target, result.speed_ratio))
                else:
                    parsed = parse_loop_filename(self.source)
                    source_bpm = canonical_loop_bpm(row.get("bpm") or parsed.get("BPM") or 140)
                    layers.append({
                        "path": path,
                        "name": os.path.basename(path),
                        "display_name": os.path.splitext(os.path.basename(path))[0],
                        "key": parsed.get("KEY") or "—",
                        "bpm": source_bpm,
                        "duration": float(row.get("duration_seconds") or 0),
                        "bytes": int(row.get("output_bytes") or os.path.getsize(path)),
                        "peaks": row.get("waveform_peaks") or waveform_peaks(path),
                    })
            elapsed = time.perf_counter() - started
            diagnostics_log.event(
                "quick_extract_complete",
                file=self.source,
                output_folder=self.output,
                layers=len(layers),
                duration_seconds=elapsed,
            )
            self.completed.emit(layers, elapsed)
        except Exception as exc:
            diagnostics_log.exception(
                "quick_extract_worker",
                exc,
                file=self.source,
                output_folder=self.output,
                duration_seconds=time.perf_counter() - started,
            )
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class QuickConvertWorkflowWorker(QObject):
    completed = Signal(object, float)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, analyzer, source, output_folder, *, bpm_enabled, bpm, key_enabled, key_pair):
        super().__init__()
        self.analyzer = analyzer
        self.source = source
        self.output_folder = output_folder
        self.target = _selection(bpm_enabled, bpm, key_enabled, key_pair)

    @Slot()
    def run(self):
        started = time.perf_counter()
        diagnostics_log = get_diagnostics()
        diagnostics_log.event(
            "quick_convert_started",
            file=self.source,
            output_folder=self.output_folder,
            target_bpm=self.target.bpm if self.target.bpm_enabled else None,
            target_key=self.target.key_pair if self.target.key_enabled else None,
        )
        try:
            if not self.target.active:
                raise ValueError("Enable BPM, Key, or both before converting.")
            analysis, _ = analyze_loop(self.analyzer, self.source)
            stem = build_output_stem(self.source, analysis, self.target)
            destination = StorageManager.unique_file(os.path.join(self.output_folder, stem + ".mp3"))
            result = convert_audio(ConversionRequest(
                source=Path(self.source),
                destination=Path(destination),
                source_bpm=analysis.bpm,
                target_bpm=self.target.bpm if self.target.bpm_enabled else None,
                source_key=analysis.source_key,
                target_key=self.target.key_pair if self.target.key_enabled else None,
            ))
            payload = {
                "path": str(result.output),
                "source_bpm": analysis.bpm,
                "target_bpm": resolved_target_bpm(analysis, self.target),
                "source_key": analysis.source_key,
                "target_key": target_key_for_source(analysis, self.target.key_pair) if self.target.key_enabled else analysis.source_key,
                "bytes": os.path.getsize(result.output),
            }
            elapsed = time.perf_counter() - started
            diagnostics_log.event(
                "quick_convert_complete",
                file=self.source,
                output=str(result.output),
                duration_seconds=elapsed,
                target_bpm=payload["target_bpm"],
                target_key=payload["target_key"],
            )
            self.completed.emit(payload, elapsed)
        except Exception as exc:
            diagnostics_log.exception(
                "quick_convert_worker",
                exc,
                file=self.source,
                output_folder=self.output_folder,
                duration_seconds=time.perf_counter() - started,
            )
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class BatchWorkflowWorker(QObject):
    progress = Signal(int, int, str)
    completed = Signal(object, object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, source, output, settings, analyzer=None):
        super().__init__()
        self.source = source
        self.output = output
        self.settings = dict(settings)
        self.analyzer = analyzer

    def _run_engine(self, destination, settings, phase_offset, phase_size, total_steps):
        state = {"failures": [], "manifest": None, "error": ""}

        def progress(current, total, status):
            fraction = (float(current) / total) if total else 0.0
            mapped = phase_offset + min(phase_size, round(fraction * phase_size))
            self.progress.emit(mapped, total_steps, status)

        process_audio(
            self.source,
            destination,
            progress,
            lambda failures, manifest: state.update(failures=list(failures), manifest=manifest),
            lambda message: state.update(error=str(message)),
            settings,
            analyzer=self.analyzer,
        )
        if state["error"]:
            raise RuntimeError(state["error"])
        return state["failures"], state["manifest"]

    @Slot()
    def run(self):
        started = time.perf_counter()
        diagnostics_log = get_diagnostics()
        diagnostics_log.event(
            "batch_started",
            source_folder=self.source,
            output_folder=self.output,
            settings=self.settings,
        )
        try:
            files = sorted(name for name in os.listdir(self.source) if name.lower().endswith(".mp3"))
            if not files:
                raise ValueError("No MP3 files found in the source folder.")
            extract = bool(self.settings.get("extract_enabled"))
            key_enabled = bool(self.settings.get("enabled"))
            convert = bool(self.settings.get("convert_enabled"))
            target = _selection(
                self.settings.get("target_bpm_enabled"),
                self.settings.get("target_bpm"),
                self.settings.get("target_key_enabled"),
                self.settings.get("target_key"),
            )
            if convert and not target.active:
                raise ValueError("Enable Target BPM, Target Key, or both for Convert BPM & Key.")

            needs_analysis = key_enabled or convert
            analysis_by_file = {}
            raw_by_file = {}
            failures = []
            process_steps = len(files)
            conversion_steps = len(files) if convert and not extract else 0
            total_steps = len(files) * (1 if needs_analysis else 0) + process_steps + conversion_steps
            total_steps = max(1, total_steps)

            if needs_analysis:
                for index, filename in enumerate(files, 1):
                    try:
                        analysis, raw = analyze_loop(self.analyzer, os.path.join(self.source, filename))
                        analysis_by_file[filename] = analysis
                        raw_by_file[filename] = raw
                        status = f"Analyzed {analysis.bpm} BPM · {analysis.source_key}: {filename}"
                    except Exception as exc:
                        diagnostics_log.exception(
                            "batch_analysis_file",
                            exc,
                            file=os.path.join(self.source, filename),
                        )
                        analysis_by_file[filename] = exc
                        raw_by_file[filename] = exc
                        failures.append((filename, str(exc)))
                        status = f"Analysis unavailable: {filename}"
                    self.progress.emit(index, total_steps, status)

            output_stems = {}
            for filename in files:
                analysis = analysis_by_file.get(filename)
                if isinstance(analysis, LoopAnalysis):
                    output_stems[filename] = build_output_stem(
                        filename,
                        analysis,
                        target if convert else None,
                        key_analysis_enabled=key_enabled,
                        key_mode=self.settings.get("mode", "detected"),
                        accidentals=self.settings.get("accidentals", "sharps"),
                        token_order=self.settings.get("token_order") or DEFAULT_OUTPUT_ORDER,
                    )
                else:
                    output_stems[filename] = os.path.splitext(filename)[0]
            if len(set(output_stems.values())) != len(output_stems):
                raise RuntimeError("The selected filename structure creates duplicate output names.")

            engine_settings = dict(self.settings)
            engine_settings.update({
                "analysis_results": raw_by_file,
                "output_stems_override": output_stems,
                "convert_enabled": False,
            })
            analysis_offset = len(files) if needs_analysis else 0

            if extract:
                if convert:
                    os.makedirs(self.output, exist_ok=True)
                    with tempfile.TemporaryDirectory(prefix=".stem-slicer-extract-") as extraction_stage:
                        engine_failures, manifest = self._run_engine(
                            extraction_stage, engine_settings, analysis_offset, process_steps, total_steps
                        )
                        failures.extend(engine_failures)
                        outputs = (manifest or {}).get("outputs_by_source", {})
                        exported_count = sum(len(items) for items in outputs.values())
                        total_steps += exported_count
                        current = analysis_offset + process_steps
                        converted_sources = set()
                        with tempfile.TemporaryDirectory(prefix=".stem-slicer-convert-", dir=self.output) as conversion_stage:
                            for filename in files:
                                analysis = analysis_by_file.get(filename)
                                if not isinstance(analysis, LoopAnalysis):
                                    continue
                                staged_pairs = []
                                try:
                                    for source_layer in outputs.get(filename, []):
                                        staged_layer = os.path.join(conversion_stage, os.path.basename(source_layer))
                                        convert_audio(ConversionRequest(
                                            source=Path(source_layer),
                                            destination=Path(staged_layer),
                                            source_bpm=analysis.bpm,
                                            target_bpm=target.bpm if target.bpm_enabled else None,
                                            source_key=analysis.source_key,
                                            target_key=target.key_pair if target.key_enabled else None,
                                        ))
                                        staged_pairs.append((staged_layer, os.path.join(self.output, os.path.basename(source_layer))))
                                        current += 1
                                        self.progress.emit(current, total_steps, f"Converted: {os.path.basename(source_layer)}")
                                    for staged_layer, final_layer in staged_pairs:
                                        os.replace(staged_layer, final_layer)
                                    converted_sources.add(filename)
                                except Exception as exc:
                                    diagnostics_log.exception(
                                        "batch_layer_conversion_file",
                                        exc,
                                        file=os.path.join(self.source, filename),
                                    )
                                    failures.append((filename, str(exc)))
                        final_outputs = {
                            filename: [os.path.join(self.output, os.path.basename(path)) for path in paths]
                            for filename, paths in outputs.items()
                            if filename in converted_sources
                        }
                        manifest = dict(manifest or {})
                        manifest["outputs_by_source"] = final_outputs
                else:
                    engine_failures, manifest = self._run_engine(
                        self.output, engine_settings, analysis_offset, process_steps, total_steps
                    )
                    failures.extend(engine_failures)
            elif convert:
                os.makedirs(self.output, exist_ok=True)
                manifest = {"outputs_by_source": {}}
                current = analysis_offset
                with tempfile.TemporaryDirectory(prefix=".stem-slicer-convert-", dir=self.output) as conversion_stage:
                    for filename in files:
                        analysis = analysis_by_file.get(filename)
                        if not isinstance(analysis, LoopAnalysis):
                            continue
                        try:
                            staged = os.path.join(conversion_stage, output_stems[filename] + ".mp3")
                            final = os.path.join(self.output, output_stems[filename] + ".mp3")
                            convert_audio(ConversionRequest(
                                source=Path(os.path.join(self.source, filename)),
                                destination=Path(staged),
                                source_bpm=analysis.bpm,
                                target_bpm=target.bpm if target.bpm_enabled else None,
                                source_key=analysis.source_key,
                                target_key=target.key_pair if target.key_enabled else None,
                            ))
                            os.replace(staged, final)
                            manifest["outputs_by_source"][filename] = [final]
                        except Exception as exc:
                            diagnostics_log.exception(
                                "batch_loop_conversion_file",
                                exc,
                                file=os.path.join(self.source, filename),
                            )
                            failures.append((filename, str(exc)))
                        current += 1
                        self.progress.emit(current, total_steps, f"Converted: {filename}")
            else:
                engine_failures, manifest = self._run_engine(
                    self.output, engine_settings, analysis_offset, process_steps, total_steps
                )
                failures.extend(engine_failures)

            # Preserve order while suppressing duplicate analysis/conversion warnings.
            unique_failures = []
            seen = set()
            for failure in failures:
                marker = tuple(failure)
                if marker not in seen:
                    seen.add(marker)
                    unique_failures.append(failure)
            diagnostics_log.event(
                "batch_complete",
                source_folder=self.source,
                output_folder=self.output,
                duration_seconds=time.perf_counter() - started,
                files=len(files),
                failures=len(unique_failures),
            )
            self.completed.emit(unique_failures, manifest)
        except Exception as exc:
            diagnostics_log.exception(
                "batch_worker",
                exc,
                source_folder=self.source,
                output_folder=self.output,
                settings=self.settings,
                duration_seconds=time.perf_counter() - started,
            )
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()
