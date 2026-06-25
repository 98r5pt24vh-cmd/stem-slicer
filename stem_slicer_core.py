import os
import re
import shutil
import subprocess
import sys
import threading
import csv
from datetime import datetime
import audioop
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

APP_NAME = "Stem Slicer 1.0"
APP_VERSION = "1.0"
MIN_LAYER_REMAINING_RATIO = 0.98
PARALLEL_WORKERS = 2
DIAGNOSTICS_ENABLED = False
WORKSPACE_ROOT = os.path.dirname(os.path.abspath(__file__))


def run_subprocess(cmd, **kwargs):
    if os.name == "nt":
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
    return subprocess.run(cmd, **kwargs)


def find_ffmpeg():
    bundled_root = getattr(sys, "_MEIPASS", None)
    script_root = os.path.dirname(os.path.abspath(__file__))
    paths = []
    if bundled_root:
        paths.append(os.path.join(bundled_root, "ffmpeg"))
        paths.append(os.path.join(bundled_root, "ffmpeg.exe"))
    paths += [
        os.path.join(script_root, "vendor", "ffmpeg-bin", "ffmpeg"),
        os.path.join(script_root, "vendor", "ffmpeg-bin", "ffmpeg.exe"),
        os.path.join(os.path.dirname(sys.executable), "ffmpeg"),
        os.path.join(os.path.dirname(sys.executable), "ffmpeg.exe"),
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "ffmpeg",
    ]
    for path in paths:
        resolved = shutil.which(path) if path == "ffmpeg" else path
        if resolved and os.path.exists(resolved):
            return resolved
    return None


def find_ffprobe(ffmpeg):
    bundled_root = getattr(sys, "_MEIPASS", None)
    script_root = os.path.dirname(os.path.abspath(__file__))
    paths = []
    if bundled_root:
        paths.append(os.path.join(bundled_root, "ffprobe"))
        paths.append(os.path.join(bundled_root, "ffprobe.exe"))
    paths += [
        os.path.join(script_root, "vendor", "ffmpeg-bin", "ffprobe"),
        os.path.join(script_root, "vendor", "ffmpeg-bin", "ffprobe.exe"),
        os.path.join(os.path.dirname(sys.executable), "ffprobe"),
        os.path.join(os.path.dirname(sys.executable), "ffprobe.exe"),
        "/opt/homebrew/bin/ffprobe",
        "/usr/local/bin/ffprobe",
        "ffprobe",
    ]
    for path in paths:
        resolved = shutil.which(path) if path == "ffprobe" else path
        if resolved and os.path.exists(resolved):
            return resolved
    if ffmpeg:
        sibling = os.path.join(os.path.dirname(ffmpeg), "ffprobe")
        if os.path.exists(sibling):
            return sibling
        sibling_exe = os.path.join(os.path.dirname(ffmpeg), "ffprobe.exe")
        if os.path.exists(sibling_exe):
            return sibling_exe
    return None


def get_vrai_zero(filepath, ffmpeg):
    cmd = [ffmpeg, "-i", filepath, "-af", "silencedetect=noise=-45dB:d=0.001", "-f", "null", "-"]
    out = run_subprocess(cmd, capture_output=True, text=True).stderr
    impact = re.search(r"silence_end: ([\d.]+)", out)
    return float(impact.group(1)) if impact else 0.0


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
    rms = audioop.rms(chunk, 2)
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
    while bar + layer_bars <= max_bar + 1:
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


def infer_structural_grid(energies, all_starts, vrai_zero, sec_per_bar, source_duration):
    threshold, active_by_bar = classify_bar_activity(energies)
    ranges = active_ranges(active_by_bar)
    if ranges and ranges[0][0] == 0:
        initial_full_end = ranges[0][1]
    else:
        initial_full_end = 16
    max_bar = int(source_duration / sec_per_bar) if source_duration else len(energies)
    silence_bars = {round((t - vrai_zero) / sec_per_bar) for t in all_starts}
    range_starts = {start for start, end in ranges if start >= initial_full_end}
    support_candidates = set(silence_bars) | set(range_starts)

    candidate_first_starts = set()
    min_start = max(0, initial_full_end + 1)
    max_start = min(max_bar, initial_full_end + 12)
    for candidate in support_candidates:
        if min_start <= candidate <= max_start:
            candidate_first_starts.add(candidate)
        # Some sparse first slots have support a few bars late.
        for delta in (-8, -4, -2, -1):
            shifted = candidate + delta
            if min_start <= shifted <= max_start:
                candidate_first_starts.add(shifted)
    for candidate in range(min_start, max_start + 1):
        if candidate in (initial_full_end + 2, initial_full_end + 4, initial_full_end + 8):
            candidate_first_starts.add(candidate)
    structures = [(8, 4), (8, 2), (8, 1), (16, 4), (4, 4), (4, 2), (4, 1), (8, 8), (16, 8)]
    scored = []
    for first_start in sorted(candidate_first_starts):
        for layer_bars, space_bars in structures:
            item = score_grid_v2(
                energies,
                first_start,
                layer_bars,
                space_bars,
                threshold,
                source_duration,
                sec_per_bar,
                support_candidates,
            )
            if item:
                scored.append(item)
    if not scored:
        return None
    scored.sort(key=lambda item: item["score"], reverse=True)
    chosen = scored[0]
    chosen = maybe_shift_grid_left_one(chosen, energies, threshold)
    chosen = apply_long_slot_expansion(chosen, energies, threshold, support_candidates)
    chosen = apply_final_extended_space(chosen, energies, threshold, support_candidates)
    return chosen


def can_export_full_layer(start_exact, dur_sec, source_duration):
    if source_duration <= 0:
        return True
    remaining = source_duration - start_exact
    return remaining >= dur_sec * MIN_LAYER_REMAINING_RATIO


def write_diagnostics(rows):
    if not rows:
        return None
    safe_timestamp = rows[0]["run_timestamp"].replace(":", "").replace("-", "").replace("T", "_")
    run_dir = os.path.join(WORKSPACE_ROOT, "diagnostics", "stem-slicer-1.0", safe_timestamp)
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


def process_one_file(d_in, d_out, filename, ffmpeg, ffprobe, run_timestamp):
    file_started = time.perf_counter()
    filepath = os.path.join(d_in, filename)
    diagnostics = []
    export_elapsed = 0.0

    res = re.search(r"\b(\d{2,3})\b", filename)
    bpm = int(res.group(1)) if res else 140
    sec_per_bar = (60 / bpm) * 4

    analysis_started = time.perf_counter()
    vrai_zero = get_vrai_zero(filepath, ffmpeg)
    all_starts = get_all_starts(filepath, ffmpeg)
    source_duration = get_duration(filepath, ffmpeg, ffprobe)
    energies = bar_energy(filepath, ffmpeg, bpm)
    analysis_elapsed = time.perf_counter() - analysis_started

    seuil_stems = vrai_zero + (sec_per_bar * 15)
    starts_stems = [t for t in all_starts if t > seuil_stems]
    grid = infer_structural_grid(energies, all_starts, vrai_zero, sec_per_bar, source_duration)
    grid_reason = "no_structural_grid"
    if grid:
        grid_reason = (
            f"grid_first_{grid['first_start']}"
            f"_layer_{grid['layer_bars']}"
            f"_space_{grid['space_bars']}"
            f"_stride_{grid['stride_bars']}"
            f"_score_{round(grid['score'], 3)}"
        )
        if grid.get("mixed_long_slot"):
            grid_reason += "_mixed_long_slot"
        if grid.get("final_extended_space"):
            grid_reason += "_final_extended_space"
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
        return diagnostics

    layer_bars = grid["layer_bars"]
    active_slots = set(grid["active_slots"])
    max_bar = int(source_duration / sec_per_bar) if source_duration else len(energies)

    for slot_bar in grid["slots"]:
        start_exact = vrai_zero + (slot_bar * sec_per_bar)
        dur_sec = sec_per_bar * layer_bars
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

        output_name = f"{os.path.splitext(filename)[0]}_L{layer_idx}.mp3"
        output_path = os.path.join(d_out, output_name)
        cmd_cut = [
            ffmpeg,
            "-y",
            "-ss",
            str(round(start_exact, 3)),
            "-t",
            str(round(dur_sec, 3)),
            "-i",
            filepath,
            "-af",
            "volume=0dB",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "2",
            output_path,
            "-loglevel",
            "error",
        ]
        export_started = time.perf_counter()
        run_subprocess(cmd_cut, check=False)
        export_elapsed += time.perf_counter() - export_started

        output_exists = os.path.exists(output_path)
        output_bytes = os.path.getsize(output_path) if output_exists else 0
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
                snapped_start=round(start_exact, 6),
                snapped_bar=slot_bar,
                duration_seconds=round(dur_sec, 6),
                remaining_seconds=round(remaining_seconds, 6),
                layer_index=layer_idx,
                output_name=output_name,
                output_exists=output_exists,
                output_bytes=output_bytes,
                correction_reason=grid_reason,
            )
        )

        if output_exists:
            layer_idx += 1

    file_elapsed = time.perf_counter() - file_started
    for row in diagnostics:
        row["file_elapsed_seconds"] = round(file_elapsed, 6)
        row["export_elapsed_seconds"] = round(export_elapsed, 6)
    return diagnostics


def process_audio(d_in, d_out, on_progress, on_done, on_error):
    if not d_in or not os.path.isdir(d_in):
        on_error("Choose a valid source folder.")
        return
    if not d_out:
        on_error("Choose an output folder.")
        return
    os.makedirs(d_out, exist_ok=True)

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

    on_progress(0, len(files), f"{len(files)} MP3 file(s) found. Processing {PARALLEL_WORKERS} at a time.")
    try:
        with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as executor:
            future_to_file = {
                executor.submit(process_one_file, d_in, d_out, filename, ffmpeg, ffprobe, run_timestamp): (index, filename)
                for index, filename in enumerate(files)
            }
            for future in as_completed(future_to_file):
                index, filename = future_to_file[future]
                diagnostics_by_index[index] = future.result()
                completed += 1
                on_progress(completed, len(files), f"Finished: {filename}")
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
        write_diagnostics(diagnostics)
    on_done()
