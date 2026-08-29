"""Headless extraction and batch-processing engine used by Electron."""

import os
import re
import shutil
import subprocess
import sys
import threading
import csv
from datetime import datetime
import math
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from diagnostics_runtime import get_diagnostics
from key_detection import KeyAnalyzer, format_camelot
from filename_templates import TOKENS, parse_loop_filename, render_name
from nospace_engine import (
    Candidate as NoSpaceCandidate,
    MIN_LAYERS as NOSPACE_PRODUCT_MIN_LAYERS,
    accepted_gap_contrast,
    auto_select as auto_select_nospace,
    infer_nospace_candidate,
    nospace_candidate_to_grid,
)
from sequence_decoder import infer_sequence_grid

APP_NAME = "Stem Slicer"
APP_VERSION = "0.1.0"
MIN_LAYER_REMAINING_RATIO = 0.74
PARALLEL_WORKERS = 2
DIAGNOSTICS_ENABLED = False
DIAGNOSTICS_ROOT = os.environ.get(
    "STEM_SLICER_DIAGNOSTICS_DIR",
    os.path.join(os.path.expanduser("~/Library/Logs"), APP_NAME),
)
NOSPACE_ACCEPTED_GAP_SHORT_CIRCUIT_DB = 12.0


def hidden_process_options():
    """Return Windows-only flags that prevent child console windows."""
    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "startupinfo": startupinfo,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }


def run_subprocess(cmd, **kwargs):
    for key, value in hidden_process_options().items():
        kwargs.setdefault(key, value)
    started = time.perf_counter()
    diagnostics = get_diagnostics()
    try:
        completed = subprocess.run(cmd, **kwargs)
    except Exception as exc:
        diagnostics.exception(
            "subprocess",
            exc,
            command=cmd,
            duration_seconds=time.perf_counter() - started,
        )
        raise
    diagnostics.record_subprocess(
        command=cmd,
        duration=time.perf_counter() - started,
        returncode=completed.returncode,
        stdout=getattr(completed, "stdout", None),
        stderr=getattr(completed, "stderr", None),
    )
    return completed


def find_ffmpeg():
    bundled_root = getattr(sys, "_MEIPASS", None)
    script_root = os.path.dirname(os.path.abspath(__file__))
    paths = []
    executable = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    if bundled_root:
        paths.append(os.path.join(bundled_root, executable))
    executable_root = os.path.dirname(sys.executable)
    paths += [
        os.path.join(executable_root, executable),
        os.path.join(executable_root, "_internal", executable),
        os.path.join(script_root, "vendor-windows", "ffmpeg-bin", executable),
        os.path.join(script_root, "vendor", "ffmpeg-bin", executable),
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        executable,
    ]
    for path in paths:
        resolved = shutil.which(path) if path == executable else path
        if resolved and os.path.exists(resolved):
            return resolved
    # The macOS Electron runtime pins imageio-ffmpeg, which ships its own
    # architecture-matched executable. Resolve it only after explicit bundled
    # and system locations so this fallback never downloads or mutates data.
    try:
        import imageio_ffmpeg

        imageio_executable = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        imageio_executable = None
    if imageio_executable and os.path.isfile(imageio_executable):
        return imageio_executable
    return None


def find_ffprobe(ffmpeg):
    bundled_root = getattr(sys, "_MEIPASS", None)
    script_root = os.path.dirname(os.path.abspath(__file__))
    executable = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
    if bundled_root:
        # A frozen build must remain self-contained. Falling through to PATH
        # could make CI use a machine-wide FFprobe that users do not have and
        # would silently bypass the bundled FFmpeg duration fallback.
        paths = [os.path.join(bundled_root, executable)]
        if ffmpeg:
            paths.append(os.path.join(os.path.dirname(ffmpeg), executable))
        for path in paths:
            if os.path.exists(path):
                return path
        return None

    paths = []
    executable_root = os.path.dirname(sys.executable)
    paths += [
        os.path.join(executable_root, executable),
        os.path.join(executable_root, "_internal", executable),
        os.path.join(script_root, "vendor-windows", "ffmpeg-bin", executable),
        os.path.join(script_root, "vendor", "ffmpeg-bin", executable),
        "/opt/homebrew/bin/ffprobe",
        "/usr/local/bin/ffprobe",
        executable,
    ]
    for path in paths:
        resolved = shutil.which(path) if path == executable else path
        if resolved and os.path.exists(resolved):
            return resolved
    if ffmpeg:
        sibling = os.path.join(os.path.dirname(ffmpeg), executable)
        if os.path.exists(sibling):
            return sibling
    return None


def get_vrai_zero(filepath, ffmpeg):
    cmd = [ffmpeg, "-i", filepath, "-af", "silencedetect=noise=-45dB:d=0.001", "-f", "null", "-"]
    out = run_subprocess(cmd, capture_output=True, text=True).stderr
    first_start = re.search(r"silence_start: ([\d.]+)", out)
    first_end = re.search(r"silence_end: ([\d.]+)", out)
    if not first_start or not first_end:
        return 0.0
    # Only silence attached to the beginning is encoder padding.  A later
    # musical silence must never shift the structural grid.
    return float(first_end.group(1)) if float(first_start.group(1)) <= 0.001 else 0.0


def _silence_runs(samples, threshold_db, sample_rate):
    """Return stereo silence runs without launching a second FFmpeg pass."""
    if samples.size == 0:
        return []
    threshold = 10.0 ** (threshold_db / 20.0)
    silent = np.all(np.abs(samples) <= threshold, axis=1)
    edges = np.flatnonzero(
        np.diff(np.concatenate(([False], silent, [False])).astype(np.int8))
    )
    return [
        (int(start), int(end), start / sample_rate, end / sample_rate)
        for start, end in zip(edges[::2], edges[1::2])
    ]


def analyze_audio_once(filepath, ffmpeg, bpm, sample_rate=22050):
    """Decode once, normalize analysis levels and collect structural features."""
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", filepath,
        "-ac", "2", "-ar", str(sample_rate),
        "-acodec", "pcm_f32le", "-f", "f32le", "-",
    ]
    result = run_subprocess(command, capture_output=True, check=True)
    pcm = result.stdout
    stereo = np.frombuffer(pcm, dtype="<f4")
    if stereo.size % 2:
        stereo = stereo[:-1]
    stereo = stereo.reshape(-1, 2)
    mixed = stereo.mean(axis=1)
    raw_mono = np.clip(
        np.rint(mixed * 32768.0), -32768, 32767
    ).astype("<i2")
    raw_mono_pcm = raw_mono.tobytes()

    sec_per_bar = (60 / bpm) * 4
    bytes_per_bar = max(2, int(sample_rate * sec_per_bar) * 2)
    bytes_per_bar -= bytes_per_bar % 2
    raw_energies = [
        rms_dbfs(raw_mono_pcm[pos : pos + bytes_per_bar])
        for pos in range(0, len(raw_mono_pcm), bytes_per_bar)
    ]
    reference_level = percentile_value(raw_energies, 0.90, -14.0)
    analysis_gain_db = -14.0 - reference_level
    normalized_mono = np.clip(
        np.rint(mixed * (10.0 ** (analysis_gain_db / 20.0)) * 32768.0),
        -32768,
        32767,
    ).astype("<i2")
    normalized_pcm = normalized_mono.tobytes()
    energies = [
        rms_dbfs(normalized_pcm[pos : pos + bytes_per_bar])
        for pos in range(0, len(normalized_pcm), bytes_per_bar)
    ]

    # Detecting at -45 dB after a fixed gain is equivalent to moving the
    # threshold by the inverse gain. This keeps normalization analysis-only and
    # avoids decoding the file again.
    runs = _silence_runs(stereo, -45.0 - analysis_gain_db, sample_rate)
    short_frames = math.ceil(sample_rate * 0.001)
    long_frames = math.ceil(sample_rate * 0.1)
    short_runs = [run for run in runs if run[1] - run[0] >= short_frames]
    long_ends = [run[3] for run in runs if run[1] - run[0] >= long_frames]
    vrai_zero = (
        short_runs[0][3]
        if short_runs and short_runs[0][0] <= math.ceil(sample_rate * 0.001)
        else 0.0
    )
    return {
        "vrai_zero": vrai_zero,
        "all_starts": long_ends,
        "duration": len(stereo) / sample_rate,
        "energies": energies,
        "analysis_gain_db": analysis_gain_db,
        # Keep the already-decoded mono signal available to Quick Extract.
        # It lets the UI build every layer waveform without launching one
        # additional FFmpeg process per exported layer.
        "waveform_mono": mixed,
        "waveform_sample_rate": sample_rate,
    }


def waveform_peaks_from_samples(samples, points=72):
    """Return normalized display peaks from an in-memory mono signal."""
    samples = np.asarray(samples)
    if samples.size == 0:
        return [0.0] * points
    boundaries = np.linspace(0, samples.size, points + 1, dtype=np.int64)
    values = []
    for index in range(points):
        segment = samples[boundaries[index]:boundaries[index + 1]]
        values.append(float(np.max(np.abs(segment))) if segment.size else 0.0)
    maximum = max(values) or 1.0
    return [value / maximum for value in values]


def get_all_starts(filepath, ffmpeg):
    cmd = [ffmpeg, "-i", filepath, "-af", "silencedetect=noise=-45dB:d=0.1", "-f", "null", "-"]
    out = run_subprocess(cmd, capture_output=True, text=True).stderr
    return [float(item) for item in re.findall(r"silence_end: ([\d.]+)", out)]


def get_duration_with_ffmpeg(filepath, ffmpeg):
    cmd = [ffmpeg, "-i", filepath, "-f", "null", "-"]
    out = run_subprocess(cmd, capture_output=True, text=True).stderr
    match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", out)
    if not match:
        return 0.0
    hours, minutes, seconds = match.groups()
    return (int(hours) * 3600) + (int(minutes) * 60) + float(seconds)


def get_duration(filepath, ffmpeg, ffprobe=None):
    if ffprobe:
        cmd = [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            filepath,
        ]
        proc = run_subprocess(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            try:
                return float(proc.stdout.strip())
            except ValueError:
                pass
    return get_duration_with_ffmpeg(filepath, ffmpeg)


def decode_mono_pcm(filepath, ffmpeg, sample_rate=22050):
    cmd = [
        ffmpeg,
        "-v", "error",
        "-i", filepath,
        "-vn",
        "-ac", "1",
        "-ar", str(sample_rate),
        "-f", "s16le",
        "-",
    ]
    proc = run_subprocess(cmd, capture_output=True)
    return proc.stdout if proc.returncode == 0 else b""


def rms_dbfs(chunk):
    if not chunk:
        return -120.0
    aligned = memoryview(chunk)[: len(chunk) - (len(chunk) % 2)]
    if not aligned:
        return -120.0
    samples = np.frombuffer(aligned, dtype="<i2").astype(np.float64)
    rms = float(np.sqrt(np.mean(np.square(samples))))
    if rms <= 0:
        return -120.0
    return 20 * math.log10(rms / 32768.0)


def bar_energy(filepath, ffmpeg, bpm):
    sample_rate = 22050
    pcm = decode_mono_pcm(filepath, ffmpeg, sample_rate)
    if not pcm:
        return []
    sec_per_bar = (60 / bpm) * 4
    bytes_per_bar = max(2, int(sample_rate * sec_per_bar) * 2)
    bytes_per_bar -= bytes_per_bar % 2
    return [rms_dbfs(pcm[pos : pos + bytes_per_bar]) for pos in range(0, len(pcm), bytes_per_bar)]


def correct_candidate_bar(snapped_bar, energies):
    if not energies:
        return snapped_bar, "no_energy_data"
    local_peak = max(energies[snapped_bar : snapped_bar + 8] or [-120.0])
    active_threshold = max(-48.0, local_peak - 36.0)
    leading_inactive = 0
    for value in energies[snapped_bar : snapped_bar + 4]:
        if value < active_threshold:
            leading_inactive += 1
        else:
            break

    # If the detected start mostly contains structural space before a strong block,
    # move to that block. This targets tails/delay hits inside spaces.
    if leading_inactive >= 2:
        return snapped_bar + leading_inactive, f"shift_forward_{leading_inactive}_leading_space_bars"

    return snapped_bar, "unchanged"


def has_future_corrected_bar(starts_stems, start_index, vrai_zero, sec_per_bar, energies, target_bar, tolerance=1):
    for future_start in starts_stems[start_index + 1 :]:
        raw_bar = round((future_start - vrai_zero) / sec_per_bar)
        corrected_bar, _ = correct_candidate_bar(raw_bar, energies)
        if abs(corrected_bar - target_bar) <= tolerance:
            return True
    return False


def regularize_structural_grid(nb_bars, last_export_bar, starts_stems, start_index, vrai_zero, sec_per_bar, energies):
    if last_export_bar is None:
        return nb_bars, ""

    sixteen_bar_target = last_export_bar + 16
    if nb_bars - last_export_bar < 16:
        return nb_bars, ""
    if abs(nb_bars - sixteen_bar_target) > 3:
        return nb_bars, ""

    has_next_anchor = has_future_corrected_bar(
        starts_stems, start_index, vrai_zero, sec_per_bar, energies, sixteen_bar_target + 16
    )
    has_second_anchor = has_future_corrected_bar(
        starts_stems, start_index, vrai_zero, sec_per_bar, energies, sixteen_bar_target + 32
    )
    if has_next_anchor and has_second_anchor and nb_bars != sixteen_bar_target:
        return sixteen_bar_target, f"regularize_16_bar_grid_{nb_bars}_to_{sixteen_bar_target}"

    return nb_bars, ""



def median_value(values, default=-80.0):
    values = sorted(values)
    if not values:
        return default
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2


def percentile_value(values, pct, default=-80.0):
    values = sorted(values)
    if not values:
        return default
    index = min(len(values) - 1, max(0, int(round((len(values) - 1) * pct))))
    return values[index]


def average_db(values, default=-120.0):
    if not values:
        return default
    return sum(values) / len(values)


def classify_bar_activity(energies):
    if not energies:
        return -48.0, []
    floor = percentile_value(energies, 0.20, -80.0)
    high = percentile_value(energies, 0.90, -24.0)
    threshold = max(-54.0, min(-30.0, floor + 10.0, high - 28.0))
    return threshold, [value >= threshold for value in energies]


def slot_activity(energies, start_bar, layer_bars, threshold):
    segment = energies[start_bar : start_bar + layer_bars]
    if len(segment) < max(1, layer_bars // 2):
        return False, -120.0, 0
    peak = max(segment or [-120.0])
    active_count = sum(1 for value in segment if value >= threshold)
    if active_count > 0:
        return True, peak, active_count
    # Very sparse one-shots can sit below the adaptive threshold but still be real layers.
    if peak >= threshold - 8.0 and peak >= -52.0:
        return True, peak, active_count
    return False, peak, active_count


def grid_slots(first_start, layer_bars, space_bars, max_bar):
    stride = layer_bars + space_bars
    slots = []
    bar = first_start
    while bar + (layer_bars * MIN_LAYER_REMAINING_RATIO) <= max_bar + 1:
        slots.append(bar)
        bar += stride
    return slots


def score_grid(energies, first_start, layer_bars, space_bars, threshold, source_duration, sec_per_bar):
    max_bar = int(source_duration / sec_per_bar) if source_duration else len(energies)
    slots = grid_slots(first_start, layer_bars, space_bars, max_bar)
    if not slots:
        return None
    active_slots = []
    active_peaks = []
    silent_slots = []
    for slot in slots:
        active, peak, active_count = slot_activity(energies, slot, layer_bars, threshold)
        if active:
            active_slots.append(slot)
            active_peaks.append(peak)
        else:
            silent_slots.append(slot)
    if not active_slots:
        return None

    pre_space_scores = []
    for slot in active_slots:
        pre = energies[max(0, slot - space_bars) : slot]
        pre_space_scores.append(average_db(pre, -80.0))
    slot_means = [average_db(energies[slot : slot + layer_bars], -120.0) for slot in active_slots]
    contrast = average_db(slot_means, -120.0) - average_db(pre_space_scores, -80.0)

    candidate_bonus = 0.0
    if first_start in (22, 24, 34, 36, 42, 44, 48, 50, 52):
        candidate_bonus += 1.5
    count_score = min(len(active_slots), 24) * 5.0
    silence_penalty = len(silent_slots) * 0.4
    short_penalty = 0.0
    if len(active_slots) < 3:
        short_penalty = 12.0
    # Prefer simple common structures when scores are otherwise close.
    structure_bonus = {
        (8, 4): 3.0,
        (8, 2): 2.5,
        (16, 4): 2.0,
        (4, 4): 1.0,
        (4, 2): 1.0,
        (8, 8): 1.0,
    }.get((layer_bars, space_bars), 0.0)
    score = count_score + contrast + candidate_bonus + structure_bonus - silence_penalty - short_penalty
    return {
        "score": score,
        "first_start": first_start,
        "layer_bars": layer_bars,
        "space_bars": space_bars,
        "stride_bars": layer_bars + space_bars,
        "slots": slots,
        "active_slots": active_slots,
        "silent_slots": silent_slots,
        "contrast": contrast,
        "threshold": threshold,
    }


def active_ranges(active_by_bar):
    ranges = []
    index = 0
    while index < len(active_by_bar):
        if active_by_bar[index]:
            end = index
            while end < len(active_by_bar) and active_by_bar[end]:
                end += 1
            ranges.append((index, end))
            index = end
        else:
            index += 1
    return ranges


def nearest_distance(value, candidates):
    if not candidates:
        return 999
    return min(abs(value - candidate) for candidate in candidates)


def score_grid_v2(energies, first_start, layer_bars, space_bars, threshold, source_duration, sec_per_bar, support_candidates):
    max_bar = int(source_duration / sec_per_bar) if source_duration else len(energies)
    slots = grid_slots(first_start, layer_bars, space_bars, max_bar)
    if not slots:
        return None
    active_slots = []
    silent_slots = []
    support_score = 0.0
    unsupported = 0
    for slot in slots:
        active, peak, active_count = slot_activity(energies, slot, layer_bars, threshold)
        if active:
            active_slots.append(slot)
            dist = nearest_distance(slot, support_candidates)
            if dist == 0:
                support_score += 7.0
            elif dist == 1:
                support_score += 4.0
            elif dist == 2:
                support_score += 1.0
            else:
                unsupported += 1
                support_score -= 5.0
        else:
            silent_slots.append(slot)
            # One or two silent structural slots are valid, but many means the grid is wrong.
            support_score -= 0.75
    if not active_slots:
        return None
    if len(active_slots) < 3:
        support_score -= 15.0

    slot_means = [average_db(energies[slot : slot + layer_bars], -120.0) for slot in active_slots]
    pre_means = [average_db(energies[max(0, slot - space_bars) : slot], -80.0) for slot in active_slots]
    contrast = average_db(slot_means, -120.0) - average_db(pre_means, -80.0)
    structure_bonus = {
        (8, 4): 4.0,
        (8, 2): 4.0,
        (16, 4): 3.0,
        (8, 1): 3.0,
        (4, 4): 2.0,
        (4, 2): 2.0,
        (4, 1): 1.5,
        (8, 8): 2.0,
    }.get((layer_bars, space_bars), 0.0)
    count_bonus = min(len(active_slots), 24) * 1.5
    score = support_score + contrast + structure_bonus + count_bonus - unsupported * 2.0
    return {
        "score": score,
        "first_start": first_start,
        "layer_bars": layer_bars,
        "space_bars": space_bars,
        "stride_bars": layer_bars + space_bars,
        "slots": slots,
        "active_slots": active_slots,
        "silent_slots": silent_slots,
        "contrast": contrast,
        "threshold": threshold,
    }


def mixed_grid_slots(first_start, leading_layer_bars, repeat_layer_bars, space_bars, max_bar):
    slots = []
    durations = []
    bar = first_start
    for layer_bars in leading_layer_bars:
        if bar + layer_bars > max_bar + 1:
            return slots, durations
        slots.append(bar)
        durations.append(layer_bars)
        bar += layer_bars + space_bars
    while bar + (repeat_layer_bars * MIN_LAYER_REMAINING_RATIO) <= max_bar + 1:
        slots.append(bar)
        durations.append(repeat_layer_bars)
        bar += repeat_layer_bars + space_bars
    return slots, durations


def score_mixed_grid(energies, first_start, leading_layer_bars, repeat_layer_bars, space_bars, threshold, source_duration, sec_per_bar, support_candidates, family):
    if nearest_distance(first_start, support_candidates) > 1:
        return None
    max_bar = int(source_duration / sec_per_bar) if source_duration else len(energies)
    slots, durations = mixed_grid_slots(first_start, leading_layer_bars, repeat_layer_bars, space_bars, max_bar)
    if len(slots) < 7:
        return None
    active_slots = []
    silent_slots = []
    support_score = 0.0
    unsupported = 0
    for slot, layer_bars in zip(slots, durations):
        active, peak, active_count = slot_activity(energies, slot, layer_bars, threshold)
        if active:
            active_slots.append(slot)
            dist = nearest_distance(slot, support_candidates)
            if dist == 0:
                support_score += 8.0
            elif dist == 1:
                support_score += 5.0
            elif dist == 2:
                support_score += 2.0
            else:
                unsupported += 1
                support_score -= 3.0
        else:
            silent_slots.append(slot)
            support_score -= 1.0
    if len(active_slots) < max(3, len(slots) - 1):
        return None

    slot_means = [
        average_db(energies[slot : slot + layer_bars], -120.0)
        for slot, layer_bars in zip(slots, durations)
        if slot in active_slots
    ]
    pre_means = [
        average_db(energies[max(0, slot - space_bars) : slot], -80.0)
        for slot in active_slots
    ]
    contrast = average_db(slot_means, -120.0) - average_db(pre_means, -80.0)
    score = support_score + contrast + min(len(active_slots), 24) * 1.5 + 12.0 - unsupported * 2.0
    duration_by_slot = {slot: layer_bars for slot, layer_bars in zip(slots, durations)}
    return {
        "score": score,
        "first_start": first_start,
        "layer_bars": "mixed",
        "space_bars": space_bars,
        "stride_bars": "mixed",
        "slots": slots,
        "active_slots": active_slots,
        "silent_slots": silent_slots,
        "contrast": contrast,
        "threshold": threshold,
        "slot_durations": durations,
        "duration_by_slot": duration_by_slot,
        "mixed_layer_family": family,
    }


def variable_space_grid_slots(first_start, layer_bars, base_space_bars, extra_space_bars, extended_gap_after_index, max_bar):
    slots = []
    bar = first_start
    index = 0
    while bar + (layer_bars * MIN_LAYER_REMAINING_RATIO) <= max_bar + 1:
        slots.append(bar)
        space_bars = base_space_bars + extra_space_bars if index == extended_gap_after_index else base_space_bars
        bar += layer_bars + space_bars
        index += 1
    return slots


def score_variable_space_grid(energies, first_start, layer_bars, base_space_bars, extra_space_bars, extended_gap_after_index, threshold, source_duration, sec_per_bar, support_candidates):
    if nearest_distance(first_start, support_candidates) > 1:
        return None
    max_bar = int(source_duration / sec_per_bar) if source_duration else len(energies)
    slots = variable_space_grid_slots(first_start, layer_bars, base_space_bars, extra_space_bars, extended_gap_after_index, max_bar)
    if len(slots) < 7:
        return None
    active_slots = []
    silent_slots = []
    support_score = 0.0
    unsupported = 0
    for slot in slots:
        active, peak, active_count = slot_activity(energies, slot, layer_bars, threshold)
        if active:
            active_slots.append(slot)
            dist = nearest_distance(slot, support_candidates)
            if dist == 0:
                support_score += 8.0
            elif dist == 1:
                support_score += 5.0
            elif dist == 2:
                support_score += 1.0
            else:
                unsupported += 1
                support_score -= 4.0
        else:
            silent_slots.append(slot)
            support_score -= 1.0
    if len(active_slots) < max(3, len(slots) - 1):
        return None

    slot_means = [average_db(energies[slot : slot + layer_bars], -120.0) for slot in active_slots]
    pre_means = [average_db(energies[max(0, slot - base_space_bars) : slot], -80.0) for slot in active_slots]
    contrast = average_db(slot_means, -120.0) - average_db(pre_means, -80.0)
    score = support_score + contrast + min(len(active_slots), 24) * 1.5 + 10.0 - unsupported * 2.0
    return {
        "score": score,
        "first_start": first_start,
        "layer_bars": layer_bars,
        "space_bars": "variable",
        "stride_bars": "variable",
        "slots": slots,
        "active_slots": active_slots,
        "silent_slots": silent_slots,
        "contrast": contrast,
        "threshold": threshold,
        "variable_space_family": f"8_bar_layers_space_{base_space_bars}_one_extra_{extra_space_bars}_after_slot_{extended_gap_after_index + 1}",
    }



def maybe_shift_grid_left_one(grid, energies, threshold):
    if not grid or grid["first_start"] <= 0:
        return grid
    shifted_first = grid["first_start"] - 1
    max_bar = grid["slots"][-1] + grid["layer_bars"] if grid["slots"] else len(energies)
    shifted_slots = grid_slots(shifted_first, grid["layer_bars"], grid["space_bars"], max_bar)
    if len(shifted_slots) < max(2, len(grid["slots"]) - 1):
        return grid

    current_active = []
    shifted_active = []
    current_silent = []
    shifted_silent = []
    for slot in grid["slots"]:
        active, peak, active_count = slot_activity(energies, slot, grid["layer_bars"], threshold)
        (current_active if active else current_silent).append(slot)
    for slot in shifted_slots:
        active, peak, active_count = slot_activity(energies, slot, grid["layer_bars"], threshold)
        (shifted_active if active else shifted_silent).append(slot)

    # If a silent first slot is detected one bar late, the whole grid is one bar late.
    if current_silent and current_silent[0] == grid["first_start"] and shifted_silent and shifted_silent[0] == shifted_first:
        if len(shifted_active) >= len(current_active):
            fixed = dict(grid)
            fixed["first_start"] = shifted_first
            fixed["slots"] = shifted_slots
            fixed["active_slots"] = shifted_active
            fixed["silent_slots"] = shifted_silent
            fixed["score"] = grid["score"] + 0.5
            return fixed
    return grid


def apply_long_slot_expansion(grid, energies, threshold, support_candidates):
    if not grid or grid["layer_bars"] != 8 or grid["space_bars"] != 2:
        return grid
    if len(grid["slots"]) < 5:
        return grid
    max_slot = grid["slots"][-1]
    adjusted = []
    slot = grid["first_start"]
    used_long = False
    while slot <= max_slot:
        adjusted.append(slot)
        active, _, _ = slot_activity(energies, slot, 8, threshold)
        expected_space = energies[slot + 8 : slot + 10]
        active_space_bars = sum(1 for value in expected_space if value >= threshold)
        # If the nominal 2-bar space is still strongly active, this slot is likely a 16-bar layer.
        if (
            active
            and len(expected_space) == 2
            and active_space_bars == 2
            and nearest_distance(slot + 18, support_candidates) <= 1
        ):
            slot += 18
            used_long = True
        else:
            slot += 10
    if not used_long:
        return grid
    active_slots = []
    silent_slots = []
    for slot in adjusted:
        active, _, _ = slot_activity(energies, slot, grid["layer_bars"], threshold)
        (active_slots if active else silent_slots).append(slot)
    fixed = dict(grid)
    fixed["slots"] = adjusted
    fixed["active_slots"] = active_slots
    fixed["silent_slots"] = silent_slots
    fixed["score"] = grid["score"] + 0.25
    fixed["mixed_long_slot"] = True
    return fixed



def apply_final_extended_space(grid, energies, threshold, support_candidates):
    if not grid or grid["space_bars"] not in (2, 4):
        return grid
    slots = list(grid["slots"])
    active_slots = set(grid["active_slots"])
    silent_slots = set(grid["silent_slots"])
    if len(slots) < 4:
        return grid
    last_slot = slots[-1]
    extended_slot = last_slot + grid["space_bars"]
    extended_active, _, extended_count = slot_activity(energies, extended_slot, grid["layer_bars"], threshold)
    if not extended_active:
        return grid
    if nearest_distance(extended_slot, support_candidates) > 2:
        return grid
    if last_slot in active_slots:
        current_active, _, current_count = slot_activity(energies, last_slot, grid["layer_bars"], threshold)
        # Final partial slot: the real last layer starts after a longer final space.
        if current_count >= extended_count:
            return grid
    fixed_slots = slots[:-1] + [extended_slot]
    fixed_active = []
    fixed_silent = []
    for slot in fixed_slots:
        slot_is_active, _, _ = slot_activity(energies, slot, grid["layer_bars"], threshold)
        (fixed_active if slot_is_active else fixed_silent).append(slot)
    fixed = dict(grid)
    fixed["slots"] = fixed_slots
    fixed["active_slots"] = fixed_active
    fixed["silent_slots"] = fixed_silent
    fixed["score"] = grid["score"] + 0.2
    fixed["final_extended_space"] = True
    return fixed


def prepend_active_previous_slot(grid, energies, threshold):
    if not grid or grid.get("layer_bars") != 8 or grid.get("space_bars") != 4:
        return grid
    if not grid.get("slots") or grid["first_start"] < 52:
        return grid
    previous_slot = grid["first_start"] - grid["stride_bars"]
    if previous_slot < 40:
        return grid
    active, _, active_count = slot_activity(energies, previous_slot, grid["layer_bars"], threshold)
    if not active or active_count < max(4, grid["layer_bars"] // 2):
        return grid
    # Long reverb can hide the first real 8+4 layer boundary from silencedetect.
    fixed = dict(grid)
    fixed["first_start"] = previous_slot
    fixed["slots"] = [previous_slot] + list(grid["slots"])
    fixed["active_slots"] = [previous_slot] + list(grid["active_slots"])
    fixed["silent_slots"] = list(grid["silent_slots"])
    fixed["score"] = grid["score"] + 0.3
    fixed["prepended_active_previous_slot"] = True
    return fixed


def infer_structural_grid(energies, all_starts, vrai_zero, sec_per_bar, source_duration):
    result = infer_sequence_grid(
        energies,
        all_starts,
        vrai_zero,
        sec_per_bar,
        source_duration,
    )
    if result is None or not result.slots:
        return None
    slots = list(result.slots)
    return {
        "score": result.score,
        "confidence_margin": result.confidence_margin,
        "first_start": slots[0].start,
        "layer_bars": result.base_layer_bars,
        "space_bars": result.base_space_bars,
        "stride_bars": result.base_layer_bars + result.base_space_bars,
        "slots": [slot.start for slot in slots],
        "active_slots": [slot.start for slot in slots if slot.active],
        "silent_slots": [slot.start for slot in slots if not slot.active],
        "duration_by_slot": {slot.start: slot.duration for slot in slots},
        "sequence_decoder": True,
    }


def select_structural_grid_with_nospace(
    accepted_grid,
    analysis,
    sec_per_bar,
    *,
    infer_nospace=None,
):
    """Select the accepted or contiguous-layer grid without a second decode.

    The accepted 1.8.2B decoder remains authoritative whenever it found
    measurable quiet gaps. The No Space branch is isolated behind a broad
    fallback so its own failure can never turn into a file or batch failure.
    """
    gap_contrast = None
    accepted_selected = "accepted" if accepted_grid is not None else "none"
    try:
        gap_contrast = accepted_gap_contrast(
            accepted_grid,
            analysis["energies"],
        )
        if (
            accepted_grid is not None
            and gap_contrast is not None
            and gap_contrast >= NOSPACE_ACCEPTED_GAP_SHORT_CIRCUIT_DB
        ):
            return accepted_grid, {
                "selected_engine": "accepted",
                "decision_reasons": ["accepted_spaces_have_quiet_contrast"],
                "accepted_gap_contrast_db": gap_contrast,
                "short_circuit": True,
                "nospace_error": None,
                "nospace_diagnostics": None,
            }

        infer_callable = infer_nospace or infer_nospace_candidate
        candidate, margin, diagnostics = infer_callable(
            analysis["waveform_mono"],
            analysis["waveform_sample_rate"],
            sec_per_bar,
            analysis["vrai_zero"],
        )
        raw_candidate = diagnostics.get(
            "model_best_before_recall_adjustment"
        )
        gate_candidate = (
            NoSpaceCandidate(**raw_candidate)
            if candidate is not None and raw_candidate is not None
            else None
        )
        product_count_is_safe = (
            candidate is None
            or (
                gate_candidate is not None
                and gate_candidate.count >= NOSPACE_PRODUCT_MIN_LAYERS
                and candidate.count >= NOSPACE_PRODUCT_MIN_LAYERS
            )
        )
        if product_count_is_safe:
            decision, decision_reasons = auto_select_nospace(
                accepted_grid,
                gap_contrast,
                gate_candidate,
            )
        else:
            decision = "accepted"
            decision_reasons = [
                "nospace_product_minimum_layers_not_met"
            ]
        if decision == "nospace" and candidate is not None:
            selected_grid = nospace_candidate_to_grid(candidate, margin)
            selected_engine = "nospace"
            if gate_candidate is not None and candidate.start < gate_candidate.start:
                decision_reasons.append(
                    "recall_span_extended_before_model_start"
                )
        else:
            selected_grid = accepted_grid
            selected_engine = accepted_selected
        return selected_grid, {
            "selected_engine": selected_engine,
            "decision_reasons": decision_reasons,
            "accepted_gap_contrast_db": gap_contrast,
            "short_circuit": False,
            "nospace_error": None,
            "nospace_diagnostics": diagnostics,
        }
    except Exception as error:
        return accepted_grid, {
            "selected_engine": accepted_selected,
            "decision_reasons": ["nospace_inference_error"],
            "accepted_gap_contrast_db": gap_contrast,
            "short_circuit": False,
            "nospace_error": {
                "type": type(error).__name__,
                "message": str(error),
            },
            "nospace_diagnostics": None,
        }


def can_export_full_layer(start_exact, dur_sec, source_duration):
    if source_duration <= 0:
        return True
    remaining = source_duration - start_exact
    return remaining >= dur_sec * MIN_LAYER_REMAINING_RATIO


def write_diagnostics(rows):
    if not rows:
        return None
    safe_timestamp = rows[0]["run_timestamp"].replace(":", "").replace("-", "").replace("T", "_")
    run_dir = os.path.join(DIAGNOSTICS_ROOT, safe_timestamp)
    os.makedirs(run_dir, exist_ok=True)
    path = os.path.join(run_dir, "diagnostics.csv")
    fieldnames = [
        "run_timestamp",
        "app_version",
        "filename",
        "event",
        "reason",
        "bpm",
        "sec_per_bar",
        "source_duration",
        "vrai_zero",
        "seuil_stems",
        "raw_silence_start",
        "snapped_start",
        "snapped_bar",
        "duration_seconds",
        "remaining_seconds",
        "layer_index",
        "output_name",
        "output_exists",
        "output_bytes",
        "all_starts_count",
        "starts_stems_count",
        "correction_reason",
        "parallel_workers",
        "file_elapsed_seconds",
        "analysis_elapsed_seconds",
        "export_elapsed_seconds",
        "total_run_seconds",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def make_diag_row(run_timestamp, filename, event, reason, bpm, sec_per_bar, source_duration, vrai_zero, seuil_stems, all_starts, starts_stems, **extra):
    row = {
        "run_timestamp": run_timestamp,
        "app_version": APP_VERSION,
        "filename": filename,
        "event": event,
        "reason": reason,
        "bpm": bpm,
        "sec_per_bar": round(sec_per_bar, 6) if sec_per_bar != "" else "",
        "source_duration": round(source_duration, 6) if source_duration != "" else "",
        "vrai_zero": round(vrai_zero, 6) if vrai_zero != "" else "",
        "seuil_stems": round(seuil_stems, 6) if seuil_stems != "" else "",
        "raw_silence_start": "",
        "snapped_start": "",
        "snapped_bar": "",
        "duration_seconds": "",
        "remaining_seconds": "",
        "layer_index": "",
        "output_name": "",
        "output_exists": "",
        "output_bytes": "",
        "all_starts_count": len(all_starts),
        "starts_stems_count": len(starts_stems),
        "correction_reason": "",
        "parallel_workers": PARALLEL_WORKERS,
        "file_elapsed_seconds": "",
        "analysis_elapsed_seconds": "",
        "export_elapsed_seconds": "",
        "total_run_seconds": "",
    }
    row.update(extra)
    return row


def process_one_file(d_in, d_out, filename, ffmpeg, ffprobe, run_timestamp, output_stem=None):
    file_started = time.perf_counter()
    filepath = os.path.join(d_in, filename)
    persistent_diagnostics = get_diagnostics()
    persistent_diagnostics.event(
        "layer_extraction_started",
        file=filepath,
        output_folder=d_out,
        output_stem=output_stem,
    )
    diagnostics = []
    export_elapsed = 0.0

    parsed_bpm = parse_loop_filename(filename).get("BPM")
    bpm = int(parsed_bpm or 140)
    sec_per_bar = (60 / bpm) * 4

    analysis_started = time.perf_counter()
    analysis = analyze_audio_once(filepath, ffmpeg, bpm)
    vrai_zero = analysis["vrai_zero"]
    all_starts = analysis["all_starts"]
    source_duration = analysis["duration"]
    energies = analysis["energies"]
    waveform_mono = analysis["waveform_mono"]
    waveform_sample_rate = analysis["waveform_sample_rate"]

    seuil_stems = vrai_zero + (sec_per_bar * 15)
    starts_stems = [t for t in all_starts if t > seuil_stems]
    accepted_grid = infer_structural_grid(
        energies,
        all_starts,
        vrai_zero,
        sec_per_bar,
        source_duration,
    )
    grid, nospace_selection = select_structural_grid_with_nospace(
        accepted_grid,
        analysis,
        sec_per_bar,
    )
    analysis_elapsed = time.perf_counter() - analysis_started
    persistent_diagnostics.event(
        "structural_grid_selected",
        file=filepath,
        selected_engine=nospace_selection["selected_engine"],
        decision_reasons=nospace_selection["decision_reasons"],
        accepted_gap_contrast_db=nospace_selection[
            "accepted_gap_contrast_db"
        ],
        short_circuit=nospace_selection["short_circuit"],
        nospace_error=nospace_selection["nospace_error"],
    )
    grid_reason = "no_structural_grid"
    if grid:
        grid_reason = (
            f"grid_first_{grid['first_start']}"
            f"_layer_{grid['layer_bars']}"
            f"_space_{grid['space_bars']}"
            f"_stride_{grid['stride_bars']}"
            f"_score_{round(grid['score'], 3)}"
        )
        if nospace_selection["selected_engine"] == "nospace":
            grid_reason += "_nospace_A"
        if grid.get("mixed_long_slot"):
            grid_reason += "_mixed_long_slot"
        if grid.get("final_extended_space"):
            grid_reason += "_final_extended_space"
        if grid.get("prepended_active_previous_slot"):
            grid_reason += "_prepended_active_previous_slot"
        if grid.get("mixed_layer_family"):
            grid_reason += f"_{grid['mixed_layer_family']}"
        if grid.get("variable_space_family"):
            grid_reason += f"_{grid['variable_space_family']}"
    diagnostics.append(
        make_diag_row(
            run_timestamp,
            filename,
            "analysis",
            "",
            bpm,
            sec_per_bar,
            source_duration,
            vrai_zero,
            seuil_stems,
            all_starts,
            starts_stems,
            analysis_elapsed_seconds=round(analysis_elapsed, 6),
            correction_reason=grid_reason,
        )
    )

    layer_idx = 1
    if not grid:
        file_elapsed = time.perf_counter() - file_started
        for row in diagnostics:
            row["file_elapsed_seconds"] = round(file_elapsed, 6)
            row["export_elapsed_seconds"] = round(export_elapsed, 6)
        persistent_diagnostics.event(
            "layer_extraction_complete",
            file=filepath,
            output_folder=d_out,
            layers=0,
            duration_seconds=file_elapsed,
            reason="no_structural_grid",
        )
        return diagnostics

    layer_bars = grid["layer_bars"]
    duration_by_slot = grid.get("duration_by_slot", {})
    active_slots = set(grid["active_slots"])
    max_bar = int(source_duration / sec_per_bar) if source_duration else len(energies)
    pending_exports = []

    for slot_bar in grid["slots"]:
        start_exact = vrai_zero + (slot_bar * sec_per_bar)
        slot_layer_bars = duration_by_slot.get(slot_bar, layer_bars)
        dur_sec = sec_per_bar * slot_layer_bars
        remaining_seconds = source_duration - start_exact if source_duration else 0.0
        slot_active = slot_bar in active_slots
        if not slot_active:
            diagnostics.append(
                make_diag_row(
                    run_timestamp,
                    filename,
                    "candidate_rejected",
                    "silent_structural_slot",
                    bpm,
                    sec_per_bar,
                    source_duration,
                    vrai_zero,
                    seuil_stems,
                    all_starts,
                    starts_stems,
                    raw_silence_start="",
                    snapped_start=round(start_exact, 6),
                    snapped_bar=slot_bar,
                    duration_seconds=round(dur_sec, 6),
                    remaining_seconds=round(remaining_seconds, 6),
                    layer_index=layer_idx,
                    correction_reason=grid_reason,
                )
            )
            continue
        if not can_export_full_layer(start_exact, dur_sec, source_duration):
            diagnostics.append(
                make_diag_row(
                    run_timestamp,
                    filename,
                    "candidate_rejected",
                    "not_enough_audio_for_layer_bars",
                    bpm,
                    sec_per_bar,
                    source_duration,
                    vrai_zero,
                    seuil_stems,
                    all_starts,
                    starts_stems,
                    raw_silence_start="",
                    snapped_start=round(start_exact, 6),
                    snapped_bar=slot_bar,
                    duration_seconds=round(dur_sec, 6),
                    remaining_seconds=round(remaining_seconds, 6),
                    layer_index=layer_idx,
                    correction_reason=grid_reason,
                )
            )
            continue

        output_name = f"{output_stem or os.path.splitext(filename)[0]}_L{layer_idx}.mp3"
        output_path = os.path.join(d_out, output_name)
        pending_exports.append({
            "start": start_exact,
            "duration": dur_sec,
            "slot_bar": slot_bar,
            "remaining_seconds": remaining_seconds,
            "layer_index": layer_idx,
            "output_name": output_name,
            "output_path": output_path,
            "waveform_peaks": waveform_peaks_from_samples(
                waveform_mono[
                    max(0, int(round(start_exact * waveform_sample_rate))):
                    max(0, int(round((start_exact + dur_sec) * waveform_sample_rate)))
                ]
            ),
        })
        layer_idx += 1

    if pending_exports:
        labels = "".join(f"[split{index}]" for index in range(len(pending_exports)))
        filters = [f"[0:a]asplit={len(pending_exports)}{labels}"]
        for index, item in enumerate(pending_exports):
            filters.append(
                f"[split{index}]atrim=start={item['start']:.9f}:duration={item['duration']:.9f},"
                f"asetpts=PTS-STARTPTS,aformat=sample_fmts=s32p[out{index}]"
            )
        command = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-i", filepath, "-filter_complex", ";".join(filters),
        ]
        for index, item in enumerate(pending_exports):
            command.extend([
                "-map", f"[out{index}]", "-c:a", "libmp3lame", "-q:a", "2",
                item["output_path"],
            ])
        export_started = time.perf_counter()
        completed = run_subprocess(command, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            message = (completed.stderr or "FFmpeg returned an unknown error.").strip()
            raise RuntimeError(f"FFmpeg layer export failed: {message[-4000:]}")
        export_elapsed = time.perf_counter() - export_started

    for item in pending_exports:
        output_exists = os.path.exists(item["output_path"])
        output_bytes = os.path.getsize(item["output_path"]) if output_exists else 0
        diagnostics.append(
            make_diag_row(
                run_timestamp,
                filename,
                "exported" if output_exists else "export_failed",
                "",
                bpm,
                sec_per_bar,
                source_duration,
                vrai_zero,
                seuil_stems,
                all_starts,
                starts_stems,
                raw_silence_start="",
                snapped_start=round(item["start"], 6),
                snapped_bar=item["slot_bar"],
                duration_seconds=round(item["duration"], 6),
                remaining_seconds=round(item["remaining_seconds"], 6),
                layer_index=item["layer_index"],
                output_name=item["output_name"],
                output_exists=output_exists,
                output_bytes=output_bytes,
                waveform_peaks=item["waveform_peaks"],
                correction_reason=grid_reason,
            )
        )

    file_elapsed = time.perf_counter() - file_started
    for row in diagnostics:
        row["file_elapsed_seconds"] = round(file_elapsed, 6)
        row["export_elapsed_seconds"] = round(export_elapsed, 6)
    persistent_diagnostics.event(
        "layer_extraction_complete",
        file=filepath,
        output_folder=d_out,
        layers=sum(row.get("event") == "exported" for row in diagnostics),
        duration_seconds=file_elapsed,
        analysis_seconds=analysis_elapsed,
        export_seconds=export_elapsed,
        structural_grid=grid_reason,
    )
    return diagnostics


def process_single_file(source_path, output_folder, output_stem=None):
    """Extract one MP3 with the exact same pipeline used by batch mode."""
    source_path = os.path.abspath(source_path)
    if not os.path.isfile(source_path) or not source_path.lower().endswith(".mp3"):
        raise ValueError("Quick Extract accepts one MP3 file.")
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("FFmpeg was not found.")
    ffprobe = find_ffprobe(ffmpeg)
    os.makedirs(output_folder, exist_ok=True)
    return process_one_file(
        os.path.dirname(source_path),
        output_folder,
        os.path.basename(source_path),
        ffmpeg,
        ffprobe,
        datetime.now().isoformat(timespec="seconds"),
        output_stem or os.path.splitext(os.path.basename(source_path))[0],
    )


def organize_complete_loops(d_in, d_out, files, output_stems, destination_mode, on_progress, offset, total):
    plan = []
    for filename in files:
        source = os.path.join(d_in, filename)
        target_dir = d_in if destination_mode == "rename_in_place" else d_out
        target = os.path.join(target_dir, output_stems[filename] + ".mp3")
        plan.append((filename, source, target))

    targets = [target for _, _, target in plan]
    if len(set(targets)) != len(targets):
        raise RuntimeError("The selected filename structure creates duplicate output names.")
    sources = {source for _, source, _ in plan}
    for _, source, target in plan:
        if os.path.exists(target) and target != source and target not in sources:
            raise RuntimeError(f"A target file already exists: {os.path.basename(target)}")

    if destination_mode == "copy_to_output":
        os.makedirs(d_out, exist_ok=True)
        for index, (filename, source, target) in enumerate(plan, start=1):
            if source != target:
                shutil.copy2(source, target)
            on_progress(offset + index, total, f"Organized: {filename}")
        return None

    staged = []
    for filename, source, target in plan:
        if source == target:
            continue
        temporary = os.path.join(d_in, f".stem-slicer-{uuid.uuid4().hex}.mp3")
        os.rename(source, temporary)
        staged.append((filename, temporary, target))
    for index, (filename, temporary, target) in enumerate(staged, start=1):
        os.rename(temporary, target)
        on_progress(offset + index, total, f"Renamed: {filename}")
    return None


def process_audio(d_in, d_out, on_progress, on_done, on_error, key_settings=None, analyzer=None):
    if not d_in or not os.path.isdir(d_in):
        on_error("Choose a valid source folder.")
        return

    key_settings = key_settings or {}
    key_enabled = bool(key_settings.get("enabled", False))
    extract_enabled = bool(key_settings.get("extract_enabled", True))
    destination_mode = key_settings.get("destination_mode", "copy_to_output")
    token_order = key_settings.get("token_order") or list(TOKENS)
    analysis_results = key_settings.get("analysis_results") or {}
    output_stems_override = key_settings.get("output_stems_override") or {}
    if not key_enabled and not extract_enabled:
        on_error("Enable key analysis, layer extraction, or both.")
        return
    output_required = extract_enabled or destination_mode == "copy_to_output"
    if output_required and not d_out:
        on_error("Choose an output folder.")
        return
    if output_required:
        os.makedirs(d_out, exist_ok=True)

    ffmpeg = None
    ffprobe = None
    if extract_enabled:
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            on_error("FFmpeg was not found. This build must include FFmpeg or find ffmpeg in PATH.")
            return
        ffprobe = find_ffprobe(ffmpeg)

    files = sorted(f for f in os.listdir(d_in) if f.lower().endswith(".mp3"))
    if not files:
        on_error("No MP3 files found in the source folder.")
        return

    run_started = time.perf_counter()
    run_timestamp = datetime.now().isoformat(timespec="seconds")
    diagnostics_by_index = {}
    completed = 0

    key_mode = key_settings.get("mode", "relative_minor")
    accidentals = key_settings.get("accidentals", "sharps")
    parsed = {filename: parse_loop_filename(filename) for filename in files}
    detected_keys = {filename: parsed[filename]["KEY"] for filename in files}
    key_failures = []

    if key_enabled:
        def analyze_files(active_analyzer):
            for index, filename in enumerate(files, start=1):
                try:
                    if filename in analysis_results:
                        result = analysis_results[filename]
                        if isinstance(result, BaseException):
                            raise result
                    else:
                        result = active_analyzer.analyze(os.path.join(d_in, filename))
                    key = format_camelot(result["camelot"], key_mode, accidentals)
                    detected_keys[filename] = key
                    on_progress(index, len(files) * 2, f"Detected {key}: {filename}")
                except Exception as exc:
                    key_failures.append((filename, str(exc)))
                    on_progress(index, len(files) * 2, f"Key unavailable, extracting unchanged: {filename}")

        try:
            if all(filename in analysis_results for filename in files):
                analyze_files(None)
            elif analyzer is not None:
                analyze_files(analyzer)
            else:
                on_progress(0, len(files) * 2, "Loading the musical key engine...")
                with KeyAnalyzer(workers=1) as temporary_analyzer:
                    analyze_files(temporary_analyzer)
        except Exception as exc:
            on_error(f"The embedded key engine could not start: {exc}")
            return

    output_stems = {}
    for filename in files:
        if filename in output_stems_override:
            output_stems[filename] = str(output_stems_override[filename])
        elif key_enabled:
            rendered = render_name(parsed[filename], token_order, detected_keys[filename])
            output_stems[filename] = os.path.splitext(rendered)[0]
        else:
            output_stems[filename] = os.path.splitext(filename)[0]

    if len(set(output_stems.values())) != len(output_stems):
        on_error("The selected filename structure creates duplicate output names.")
        return

    total_steps = len(files) * 2 if key_enabled else len(files)
    processing_offset = len(files) if key_enabled else 0
    if not extract_enabled:
        try:
            manifest = organize_complete_loops(
                d_in,
                d_out,
                files,
                output_stems,
                destination_mode,
                on_progress,
                processing_offset,
                total_steps,
            )
        except Exception as exc:
            on_error(str(exc))
            return
        on_done(key_failures, manifest)
        return

    on_progress(
        processing_offset,
        total_steps,
        f"Extracting {len(files)} loop(s), {PARALLEL_WORKERS} at a time.",
    )
    try:
        with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as executor:
            future_to_file = {
                executor.submit(
                    process_one_file,
                    d_in,
                    d_out,
                    filename,
                    ffmpeg,
                    ffprobe,
                    run_timestamp,
                    output_stems[filename],
                ): (index, filename)
                for index, filename in enumerate(files)
            }
            for future in as_completed(future_to_file):
                index, filename = future_to_file[future]
                diagnostics_by_index[index] = future.result()
                completed += 1
                on_progress(processing_offset + completed, total_steps, f"Finished: {filename}")
    except Exception as exc:
        on_error(str(exc))
        return

    total_run_seconds = time.perf_counter() - run_started
    diagnostics = []
    for index in range(len(files)):
        for row in diagnostics_by_index.get(index, []):
            row["total_run_seconds"] = round(total_run_seconds, 6)
            diagnostics.append(row)

    if DIAGNOSTICS_ENABLED:
        try:
            write_diagnostics(diagnostics)
        except OSError:
            # Diagnostics must never invalidate otherwise successful exports.
            pass
    outputs_by_source = {filename: [] for filename in files}
    for row in diagnostics:
        if row.get("event") != "exported" or not row.get("output_exists"):
            continue
        outputs_by_source.setdefault(row["filename"], []).append(
            os.path.join(d_out, row["output_name"])
        )
    on_done(key_failures, {
        "diagnostics": diagnostics,
        "output_stems": output_stems,
        "outputs_by_source": outputs_by_source,
    })
