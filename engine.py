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
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from key_detection import KeyAnalyzer, format_camelot
from filename_templates import TOKENS, parse_loop_filename, render_name

try:
    import objc
    from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyRegular,
    NSAlert,
    NSAppearance,
    NSAppearanceNameDarkAqua,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSBezelStyleRounded,
    NSBitmapImageRep,
    NSButton,
    NSColor,
    NSDragOperationCopy,
    NSFilenamesPboardType,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSImage,
    NSImageScaleProportionallyUpOrDown,
    NSImageView,
    NSMakeRect,
    NSOpenPanel,
    NSPNGFileType,
    NSProgressIndicator,
    NSRunningApplication,
    NSScreen,
    NSSegmentedControl,
    NSSegmentSwitchTrackingSelectOne,
    NSTextField,
    NSTextAlignmentCenter,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskTitled,
    NSWindowTitleHidden,
    )
    from Foundation import NSObject, NSOperationQueue, NSString
except ImportError:
    class _ObjCShim:
        @staticmethod
        def ivar():
            return None

        @staticmethod
        def python_method(function):
            return function

    class _UnusedNativeType:
        @classmethod
        def colorWithCalibratedRed_green_blue_alpha_(cls, *args):
            return cls()

        @classmethod
        def colorWithCalibratedWhite_alpha_(cls, *args):
            return cls()

    objc = _ObjCShim()
    NSView = NSObject = _UnusedNativeType
    NSColor = _UnusedNativeType

APP_NAME = "Stem Slicer"
APP_VERSION = "1.4.1 M"
MIN_LAYER_REMAINING_RATIO = 0.74
PARALLEL_WORKERS = 2
DIAGNOSTICS_ENABLED = False
DIAGNOSTICS_ROOT = os.environ.get(
    "STEM_SLICER_DIAGNOSTICS_DIR",
    os.path.join(os.path.expanduser("~/Library/Logs"), APP_NAME),
)


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
    return subprocess.run(cmd, **kwargs)


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
    return None


def find_ffprobe(ffmpeg):
    bundled_root = getattr(sys, "_MEIPASS", None)
    script_root = os.path.dirname(os.path.abspath(__file__))
    paths = []
    executable = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
    if bundled_root:
        paths.append(os.path.join(bundled_root, executable))
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
        for leading_layer_bars, repeat_layer_bars, space_bars, family in (
            ((16,), 8, 4, "mixed_first_16_then_8_space_4"),
            ((32, 16), 8, 4, "mixed_first_32_second_16_then_8_space_4"),
        ):
            item = score_mixed_grid(
                energies,
                first_start,
                leading_layer_bars,
                repeat_layer_bars,
                space_bars,
                threshold,
                source_duration,
                sec_per_bar,
                support_candidates,
                family,
            )
            if item:
                scored.append(item)
        for extended_gap_after_index in range(0, 4):
            item = score_variable_space_grid(
                energies,
                first_start,
                8,
                2,
                2,
                extended_gap_after_index,
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
    if chosen.get("layer_bars") != "mixed" and not chosen.get("variable_space_family"):
        chosen = maybe_shift_grid_left_one(chosen, energies, threshold)
        chosen = apply_long_slot_expansion(chosen, energies, threshold, support_candidates)
        chosen = apply_final_extended_space(chosen, energies, threshold, support_candidates)
        chosen = prepend_active_previous_slot(chosen, energies, threshold)
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
        return diagnostics

    layer_bars = grid["layer_bars"]
    duration_by_slot = grid.get("duration_by_slot", {})
    active_slots = set(grid["active_slots"])
    max_bar = int(source_duration / sec_per_bar) if source_duration else len(energies)

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
                    result = active_analyzer.analyze(os.path.join(d_in, filename))
                    key = format_camelot(result["camelot"], key_mode, accidentals)
                    detected_keys[filename] = key
                    on_progress(index, len(files) * 2, f"Detected {key}: {filename}")
                except Exception as exc:
                    key_failures.append((filename, str(exc)))
                    on_progress(index, len(files) * 2, f"Key unavailable, extracting unchanged: {filename}")

        try:
            if analyzer is not None:
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
        if key_enabled:
            rendered = render_name(parsed[filename], token_order, detected_keys[filename])
            output_stems[filename] = os.path.splitext(rendered)[0]
        else:
            output_stems[filename] = os.path.splitext(filename)[0]

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
    on_done(key_failures, None)


RED = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.98, 0.16, 0.08, 1.0)
TEXT = NSColor.colorWithCalibratedWhite_alpha_(0.94, 1.0)
MUTED = NSColor.colorWithCalibratedWhite_alpha_(0.58, 1.0)
PANEL = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.105, 0.11, 0.12, 1.0)
PANEL_BORDER = NSColor.colorWithCalibratedWhite_alpha_(0.23, 1.0)


def resource_path(*parts):
    root = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, *parts)


class StudioBackgroundView(NSView):
    def drawRect_(self, dirty_rect):
        NSColor.colorWithCalibratedRed_green_blue_alpha_(0.055, 0.06, 0.065, 1.0).setFill()
        NSBezierPath.fillRect_(self.bounds())
        NSColor.colorWithCalibratedWhite_alpha_(0.035, 1.0).setStroke()
        for x in range(0, int(self.bounds().size.width), 40):
            line = NSBezierPath.bezierPath()
            line.moveToPoint_((x, 0))
            line.lineToPoint_((x, self.bounds().size.height))
            line.setLineWidth_(1)
            line.stroke()
        for y in range(0, int(self.bounds().size.height), 40):
            line = NSBezierPath.bezierPath()
            line.moveToPoint_((0, y))
            line.lineToPoint_((self.bounds().size.width, y))
            line.setLineWidth_(1)
            line.stroke()


class PanelView(NSView):
    accent = objc.ivar()

    @objc.python_method
    def configure(self, accent=False):
        self.accent = accent
        return self

    def drawRect_(self, dirty_rect):
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(self.bounds(), 7, 7)
        PANEL.setFill()
        path.fill()
        (RED if self.accent else PANEL_BORDER).setStroke()
        path.setLineWidth_(1.0 if not self.accent else 1.4)
        path.stroke()


class FolderDropView(NSView):
    role = objc.ivar()
    owner = objc.ivar()
    highlighted = objc.ivar()

    @objc.python_method
    def configure(self, role, owner):
        self.role = role
        self.owner = owner
        self.highlighted = False
        self.registerForDraggedTypes_([NSFilenamesPboardType])
        return self

    @objc.python_method
    def draggedFolder(self, sender):
        paths = sender.draggingPasteboard().propertyListForType_(NSFilenamesPboardType) or []
        for path in paths:
            candidate = str(path)
            if os.path.isdir(candidate):
                return candidate
        return None

    def draggingEntered_(self, sender):
        self.highlighted = bool(self.draggedFolder(sender))
        self.setNeedsDisplay_(True)
        return NSDragOperationCopy if self.highlighted else 0

    def draggingExited_(self, sender):
        self.highlighted = False
        self.setNeedsDisplay_(True)

    def performDragOperation_(self, sender):
        path = self.draggedFolder(sender)
        self.highlighted = False
        self.setNeedsDisplay_(True)
        if not path:
            return False
        self.owner.folderDropped_role_(path, self.role)
        return True

    def drawRect_(self, dirty_rect):
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(self.bounds(), 7, 7)
        fill = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.12, 0.125, 0.135, 1.0)
        if self.highlighted:
            fill = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.22, 0.075, 0.055, 1.0)
        fill.setFill()
        path.fill()
        (RED if self.highlighted else PANEL_BORDER).setStroke()
        path.setLineWidth_(2.0 if self.highlighted else 1.0)
        path.stroke()


class TokenStripView(NSView):
    tokens = objc.ivar()
    owner = objc.ivar()
    drag_index = objc.ivar()
    drag_start_x = objc.ivar()
    drag_offset_x = objc.ivar()
    drag_current_x = objc.ivar()
    drag_active = objc.ivar()

    @objc.python_method
    def configure(self, owner, tokens=None):
        self.owner = owner
        self.tokens = list(tokens or TOKENS)
        self.drag_index = -1
        self.drag_start_x = 0.0
        self.drag_offset_x = 0.0
        self.drag_current_x = 0.0
        self.drag_active = False
        return self

    def mouseDownCanMoveWindow(self):
        return False

    def acceptsFirstMouse_(self, event):
        return True

    def acceptsFirstResponder(self):
        return True

    @objc.python_method
    def chipFrames(self):
        widths = {"KEY": 104, "BPM": 104, "LOOP NAME": 168, "ARTIST": 136}
        frames = []
        x = 14
        for token in self.tokens:
            width = widths[token]
            frames.append(NSMakeRect(x, 11, width, 40))
            x += width + 12
        return frames

    def drawRect_(self, dirty_rect):
        background = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(self.bounds(), 7, 7)
        NSColor.colorWithCalibratedWhite_alpha_(0.055, 1.0).setFill()
        background.fill()
        PANEL_BORDER.setStroke()
        background.stroke()
        attributes = {
            NSFontAttributeName: NSFont.boldSystemFontOfSize_(11),
            NSForegroundColorAttributeName: TEXT,
        }
        frames = self.chipFrames()

        def draw_chip(token, frame, active=False):
            chip = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(frame, 6, 6)
            color = RED if active else NSColor.colorWithCalibratedWhite_alpha_(0.16, 1.0)
            color.setFill()
            chip.fill()
            PANEL_BORDER.setStroke()
            chip.stroke()
            text = NSString.stringWithString_(token)
            size = text.sizeWithAttributes_(attributes)
            point = (
                frame.origin.x + (frame.size.width - size.width) / 2,
                frame.origin.y + (frame.size.height - size.height) / 2,
            )
            text.drawAtPoint_withAttributes_(point, attributes)

        # Paint the dragged chip last so it always stays above its siblings.
        for index, (token, frame) in enumerate(zip(self.tokens, frames)):
            if index != self.drag_index or not self.drag_active:
                draw_chip(token, frame)
        if self.drag_index >= 0 and self.drag_active:
            slot_frame = frames[self.drag_index]
            drag_frame = NSMakeRect(
                self.drag_current_x,
                slot_frame.origin.y,
                slot_frame.size.width,
                slot_frame.size.height,
            )
            draw_chip(self.tokens[self.drag_index], drag_frame, True)

    @objc.python_method
    def indexAtPoint(self, point):
        for index, frame in enumerate(self.chipFrames()):
            if (
                frame.origin.x <= point.x <= frame.origin.x + frame.size.width
                and frame.origin.y <= point.y <= frame.origin.y + frame.size.height
            ):
                return index
        return -1

    def mouseDown_(self, event):
        point = self.convertPoint_fromView_(event.locationInWindow(), None)
        self.drag_index = self.indexAtPoint(point)
        if self.drag_index >= 0:
            frame = self.chipFrames()[self.drag_index]
            self.drag_start_x = point.x
            self.drag_offset_x = point.x - frame.origin.x
            self.drag_current_x = frame.origin.x
            self.drag_active = False
        self.setNeedsDisplay_(True)

    def mouseDragged_(self, event):
        if self.drag_index < 0:
            return
        point = self.convertPoint_fromView_(event.locationInWindow(), None)
        if not self.drag_active and abs(point.x - self.drag_start_x) < 6:
            return
        self.drag_active = True
        frames = self.chipFrames()
        dragged_width = frames[self.drag_index].size.width
        max_x = self.bounds().size.width - dragged_width - 10
        self.drag_current_x = max(10, min(max_x, point.x - self.drag_offset_x))
        changed = False

        while self.drag_index > 0:
            left = frames[self.drag_index - 1]
            if point.x >= left.origin.x + left.size.width / 2:
                break
            token = self.tokens.pop(self.drag_index)
            self.drag_index -= 1
            self.tokens.insert(self.drag_index, token)
            frames = self.chipFrames()
            changed = True

        while self.drag_index < len(self.tokens) - 1:
            right = frames[self.drag_index + 1]
            if point.x <= right.origin.x + right.size.width / 2:
                break
            token = self.tokens.pop(self.drag_index)
            self.drag_index += 1
            self.tokens.insert(self.drag_index, token)
            frames = self.chipFrames()
            changed = True

        if changed:
            self.owner.tokenOrderChanged_(self.tokens)
        self.setNeedsDisplay_(True)

    def mouseUp_(self, event):
        if self.drag_index >= 0 and self.drag_active:
            self.owner.tokenOrderChanged_(self.tokens)
        self.drag_index = -1
        self.drag_active = False
        self.setNeedsDisplay_(True)


class AppDelegate(NSObject):
    source_path = objc.ivar()
    output_path = objc.ivar()
    source_value = objc.ivar()
    output_value = objc.ivar()
    output_button = objc.ivar()
    status = objc.ivar()
    progress = objc.ivar()
    start_button = objc.ivar()
    detection_control = objc.ivar()
    extraction_control = objc.ivar()
    mode_control = objc.ivar()
    accidental_control = objc.ivar()
    destination_control = objc.ivar()
    token_strip = objc.ivar()
    preview_value = objc.ivar()
    window = objc.ivar()

    def applicationDidFinishLaunching_(self, notification):
        self.source_path = ""
        self.output_path = ""
        self.buildWindow()
        self.window.makeKeyAndOrderFront_(None)
        snapshot_path = os.environ.get("STEM_SLICER_UI_SNAPSHOT")
        if snapshot_path:
            self.performSelector_withObject_afterDelay_("captureSnapshot:", snapshot_path, 1.0)
        autorun_input = os.environ.get("STEM_SLICER_AUTORUN_INPUT")
        autorun_output = os.environ.get("STEM_SLICER_AUTORUN_OUTPUT")
        if autorun_input and autorun_output:
            self.setFolder("source", autorun_input)
            self.setFolder("output", autorun_output)
            self.performSelector_withObject_afterDelay_("startProcessing:", None, 0.2)
        NSRunningApplication.currentApplication().activateWithOptions_(1)

    def applicationShouldTerminateAfterLastWindowClosed_(self, sender):
        return True

    @objc.python_method
    def makeLabel(self, text, frame, size=13, weight="regular", color=None, alignment=None, mono=False):
        field = NSTextField.labelWithString_(text)
        field.setFrame_(frame)
        if mono and hasattr(NSFont, "monospacedSystemFontOfSize_weight_"):
            font = NSFont.monospacedSystemFontOfSize_weight_(size, 0.3 if weight == "bold" else 0.0)
        else:
            font = NSFont.boldSystemFontOfSize_(size) if weight == "bold" else NSFont.systemFontOfSize_(size)
        field.setFont_(font)
        field.setTextColor_(color or TEXT)
        field.setLineBreakMode_(5)
        if alignment is not None:
            field.setAlignment_(alignment)
        return field

    @objc.python_method
    def makeSegments(self, labels, frame, selected, action=None):
        control = NSSegmentedControl.alloc().initWithFrame_(frame)
        control.setSegmentCount_(len(labels))
        control.setTrackingMode_(NSSegmentSwitchTrackingSelectOne)
        width = frame.size.width / len(labels)
        for index, label in enumerate(labels):
            control.setLabel_forSegment_(label, index)
            control.setWidth_forSegment_(width, index)
        control.setSelected_forSegment_(True, selected)
        control.setFont_(NSFont.boldSystemFontOfSize_(11))
        if action:
            control.setTarget_(self)
            control.setAction_(action)
        return control

    @objc.python_method
    def addImage(self, content, filename, frame):
        path = resource_path("assets", filename)
        if not os.path.exists(path):
            return None
        image = NSImage.alloc().initWithContentsOfFile_(path)
        view = NSImageView.alloc().initWithFrame_(frame)
        view.setImage_(image)
        view.setImageScaling_(NSImageScaleProportionallyUpOrDown)
        content.addSubview_(view)
        return view

    @objc.python_method
    def captureInterface(self, path):
        content = self.window.contentView()
        def invalidate(view):
            view.setNeedsDisplay_(True)
            for child in view.subviews():
                invalidate(child)

        invalidate(content)
        self.window.display()
        content.displayIfNeeded()
        bounds = content.bounds()
        bitmap = content.bitmapImageRepForCachingDisplayInRect_(bounds)
        content.cacheDisplayInRect_toBitmapImageRep_(bounds, bitmap)
        data = bitmap.representationUsingType_properties_(NSPNGFileType, {})
        data.writeToFile_atomically_(path, True)

    def captureSnapshot_(self, path):
        self.captureInterface(str(path))

    @objc.python_method
    def addDropZone(self, content, role, frame):
        zone = FolderDropView.alloc().initWithFrame_(frame).configure(role, self)
        title = "INPUT FOLDER" if role == "source" else "OUTPUT FOLDER"
        hint = "Drop a folder of MP3 loops" if role == "source" else "Drop the export destination"
        zone.addSubview_(self.makeLabel(title, NSMakeRect(18, 81, 220, 20), 11, "bold", RED, mono=True))
        zone.addSubview_(self.makeLabel(hint, NSMakeRect(18, 59, 390, 20), 12, color=MUTED))
        value = self.makeLabel("No folder selected", NSMakeRect(18, 18, 310, 25), 11, color=TEXT, mono=True)
        zone.addSubview_(value)
        action = "chooseSource:" if role == "source" else "chooseOutput:"
        button = NSButton.buttonWithTitle_target_action_("BROWSE", self, action)
        button.setFrame_(NSMakeRect(frame.size.width - 118, 14, 100, 30))
        button.setBezelStyle_(NSBezelStyleRounded)
        button.setFont_(NSFont.boldSystemFontOfSize_(11))
        zone.addSubview_(button)
        content.addSubview_(zone)
        if role == "source":
            self.source_value = value
        else:
            self.output_value = value
            self.output_button = button

    @objc.python_method
    def buildWindow(self):
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable
        screen = NSScreen.mainScreen().visibleFrame()
        width, height = 1040, 780
        x = screen.origin.x + (screen.size.width - width) / 2
        y = screen.origin.y + (screen.size.height - height) / 2
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, width, height), style, NSBackingStoreBuffered, False
        )
        self.window.setTitle_(APP_NAME)
        self.window.setTitleVisibility_(NSWindowTitleHidden)
        self.window.setTitlebarAppearsTransparent_(True)
        self.window.setMovableByWindowBackground_(False)
        self.window.setAppearance_(NSAppearance.appearanceNamed_(NSAppearanceNameDarkAqua))
        self.window.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.05, 1.0))

        content = StudioBackgroundView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        self.window.setContentView_(content)

        header = PanelView.alloc().initWithFrame_(NSMakeRect(20, 640, 1000, 120)).configure(False)
        content.addSubview_(header)
        self.addImage(header, "antiworld-logo.png", NSMakeRect(12, 20, 78, 78))
        self.addImage(header, "stem-slicer-wordmark.png", NSMakeRect(275, 5, 450, 108))
        header.addSubview_(self.makeLabel("MADE WITH <3 BY ANTIWORLD", NSMakeRect(760, 69, 220, 20), 10, "bold", RED, mono=True))
        header.addSubview_(self.makeLabel("VERSION 1.3 PROTOTYPE", NSMakeRect(760, 42, 220, 20), 10, "bold", TEXT, mono=True))
        header.addSubview_(self.makeLabel("KEY + LAYER WORKSTATION", NSMakeRect(760, 20, 220, 18), 9, color=MUTED, mono=True))

        self.addDropZone(content, "source", NSMakeRect(20, 500, 490, 120))
        self.addDropZone(content, "output", NSMakeRect(530, 500, 490, 120))

        process_panel = PanelView.alloc().initWithFrame_(NSMakeRect(20, 350, 1000, 130)).configure(True)
        content.addSubview_(process_panel)
        process_panel.addSubview_(self.makeLabel("KEY ANALYSIS", NSMakeRect(20, 96, 180, 20), 11, "bold", RED, mono=True))
        process_panel.addSubview_(self.makeLabel("Detect a key before writing files.", NSMakeRect(20, 74, 330, 18), 11, color=MUTED))
        self.detection_control = self.makeSegments(["OFF", "ON"], NSMakeRect(340, 84, 150, 28), 1, "processControlsChanged:")
        process_panel.addSubview_(self.detection_control)
        process_panel.addSubview_(self.makeLabel("MODE", NSMakeRect(20, 46, 80, 16), 9, "bold", MUTED, mono=True))
        self.mode_control = self.makeSegments(
            ["DETECTED", "RELATIVE MINOR", "RELATIVE MAJOR"], NSMakeRect(20, 12, 300, 28), 1
        )
        self.mode_control.setFont_(NSFont.boldSystemFontOfSize_(9))
        process_panel.addSubview_(self.mode_control)
        process_panel.addSubview_(self.makeLabel("ACCIDENTALS", NSMakeRect(336, 46, 150, 16), 9, "bold", MUTED, mono=True))
        self.accidental_control = self.makeSegments(["SHARPS #", "FLATS b"], NSMakeRect(336, 12, 154, 28), 0)
        process_panel.addSubview_(self.accidental_control)

        process_panel.addSubview_(self.makeLabel("LAYER EXTRACTION", NSMakeRect(540, 96, 210, 20), 11, "bold", RED, mono=True))
        process_panel.addSubview_(self.makeLabel("Run the validated 1.0b slicer.", NSMakeRect(540, 74, 300, 18), 11, color=MUTED))
        self.extraction_control = self.makeSegments(["OFF", "ON"], NSMakeRect(824, 84, 150, 28), 1, "processControlsChanged:")
        process_panel.addSubview_(self.extraction_control)
        process_panel.addSubview_(self.makeLabel("Turn extraction off to analyze and organize complete loops only.", NSMakeRect(540, 24, 430, 30), 11, color=TEXT))

        naming_panel = PanelView.alloc().initWithFrame_(NSMakeRect(20, 190, 1000, 140)).configure(False)
        content.addSubview_(naming_panel)
        naming_panel.addSubview_(self.makeLabel("OUTPUT NAME STRUCTURE", NSMakeRect(20, 109, 250, 18), 10, "bold", RED, mono=True))
        naming_panel.addSubview_(self.makeLabel("Drag tokens to reorder the final filename.", NSMakeRect(275, 108, 350, 18), 11, color=MUTED))
        self.token_strip = TokenStripView.alloc().initWithFrame_(NSMakeRect(14, 42, 610, 62)).configure(self, TOKENS)
        naming_panel.addSubview_(self.token_strip)
        naming_panel.addSubview_(self.makeLabel("DESTINATION", NSMakeRect(650, 109, 170, 18), 9, "bold", MUTED, mono=True))
        self.destination_control = self.makeSegments(
            ["COPY TO OUTPUT", "RENAME ORIGINALS"], NSMakeRect(650, 69, 328, 30), 0, "destinationChanged:"
        )
        naming_panel.addSubview_(self.destination_control)
        naming_panel.addSubview_(self.makeLabel("PREVIEW", NSMakeRect(20, 16, 70, 16), 9, "bold", MUTED, mono=True))
        self.preview_value = self.makeLabel("", NSMakeRect(96, 12, 882, 22), 11, color=TEXT, mono=True)
        naming_panel.addSubview_(self.preview_value)

        status_panel = PanelView.alloc().initWithFrame_(NSMakeRect(20, 85, 1000, 85)).configure(False)
        content.addSubview_(status_panel)
        status_panel.addSubview_(self.makeLabel("PROCESS", NSMakeRect(18, 52, 90, 18), 9, "bold", MUTED, mono=True))
        self.status = self.makeLabel("Ready. Configure either process or both.", NSMakeRect(104, 49, 860, 22), 11, color=TEXT)
        status_panel.addSubview_(self.status)
        self.progress = NSProgressIndicator.alloc().initWithFrame_(NSMakeRect(18, 19, 964, 12))
        self.progress.setIndeterminate_(False)
        self.progress.setMinValue_(0)
        self.progress.setMaxValue_(1)
        self.progress.setDoubleValue_(0)
        self.progress.setControlTint_(0)
        status_panel.addSubview_(self.progress)

        self.start_button = NSButton.buttonWithTitle_target_action_("ANALYZE KEYS + EXTRACT LAYERS", self, "startProcessing:")
        self.start_button.setFrame_(NSMakeRect(20, 24, 1000, 42))
        self.start_button.setBordered_(False)
        self.start_button.setFont_(NSFont.boldSystemFontOfSize_(13))
        self.start_button.setContentTintColor_(NSColor.whiteColor())
        self.start_button.setWantsLayer_(True)
        self.start_button.layer().setBackgroundColor_(RED.CGColor())
        self.start_button.layer().setCornerRadius_(7.0)
        content.addSubview_(self.start_button)
        self.processControlsChanged_(None)

    @objc.python_method
    def clipped(self, value, limit=45):
        if len(value) <= limit:
            return value
        return "..." + value[-(limit - 3):]

    @objc.python_method
    def setFolder(self, role, selected):
        if role == "source":
            self.source_path = selected
            label = self.source_value
        else:
            self.output_path = selected
            label = self.output_value
        label.setStringValue_(self.clipped(selected))
        label.setToolTip_(selected)
        self.status.setStringValue_(f"{role.title()} folder selected.")
        self.updatePreview()

    @objc.python_method
    def chooseFolder(self):
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(False)
        panel.setCanChooseDirectories_(True)
        panel.setAllowsMultipleSelection_(False)
        if panel.runModal() == 1:
            return str(panel.URL().path())
        return None

    def folderDropped_role_(self, selected, role):
        self.setFolder(str(role), str(selected))

    def chooseSource_(self, sender):
        selected = self.chooseFolder()
        if selected:
            self.setFolder("source", selected)

    def chooseOutput_(self, sender):
        selected = self.chooseFolder()
        if selected:
            self.setFolder("output", selected)

    def tokenOrderChanged_(self, tokens):
        self.updatePreview()

    @objc.python_method
    def updatePreview(self):
        filename = "L CALLMEUR3 137 +NRGY.mp3"
        if self.source_path and os.path.isdir(self.source_path):
            candidates = sorted(name for name in os.listdir(self.source_path) if name.lower().endswith(".mp3"))
            if candidates:
                filename = candidates[0]
        parts = parse_loop_filename(filename)
        example_key = parts["KEY"] or ("A#m" if self.detection_control.selectedSegment() == 1 else "")
        layer_index = 1 if self.extraction_control.selectedSegment() == 1 else None
        preview = render_name(parts, list(self.token_strip.tokens), example_key, layer_index)
        self.preview_value.setStringValue_(preview)

    def destinationChanged_(self, sender):
        self.processControlsChanged_(sender)

    def processControlsChanged_(self, sender):
        key_enabled = self.detection_control.selectedSegment() == 1
        extract_enabled = self.extraction_control.selectedSegment() == 1
        self.mode_control.setEnabled_(key_enabled)
        self.accidental_control.setEnabled_(key_enabled)
        scan_only = key_enabled and not extract_enabled
        self.destination_control.setEnabled_(scan_only)
        rename_in_place = scan_only and self.destination_control.selectedSegment() == 1
        self.output_button.setEnabled_(not rename_in_place)
        if key_enabled and extract_enabled:
            title = "ANALYZE KEYS + EXTRACT LAYERS"
        elif extract_enabled:
            title = "EXTRACT LAYERS"
        elif key_enabled and rename_in_place:
            title = "ANALYZE + RENAME ORIGINAL LOOPS"
        elif key_enabled:
            title = "ANALYZE + ORGANIZE LOOPS"
        else:
            title = "ENABLE KEY ANALYSIS OR LAYER EXTRACTION"
        self.start_button.setTitle_(title)
        self.start_button.setEnabled_(key_enabled or extract_enabled)
        self.updatePreview()

    def setProgress_(self, args):
        current, total, status = args
        self.progress.setMaxValue_(max(total, 1))
        self.progress.setDoubleValue_(current)
        self.status.setStringValue_(status)

    @objc.python_method
    def finishProcessing(self, failures, manifest):
        self.start_button.setEnabled_(True)
        if failures:
            self.status.setStringValue_(f"Done. {len(failures)} loop(s) completed without a detected key.")
        else:
            self.status.setStringValue_("Done. Processing completed successfully.")
        if os.environ.get("STEM_SLICER_AUTO_QUIT") == "1":
            NSApplication.sharedApplication().terminate_(None)

    def showError_(self, message):
        self.start_button.setEnabled_(True)
        self.status.setStringValue_(message)
        if os.environ.get("STEM_SLICER_AUTO_QUIT") == "1":
            NSApplication.sharedApplication().terminate_(None)

    def startProcessing_(self, sender):
        key_enabled = self.detection_control.selectedSegment() == 1
        extract_enabled = self.extraction_control.selectedSegment() == 1
        rename_in_place = key_enabled and not extract_enabled and self.destination_control.selectedSegment() == 1
        if not key_enabled and not extract_enabled:
            self.showError_("Enable key analysis, layer extraction, or both.")
            return
        if rename_in_place and os.environ.get("STEM_SLICER_SKIP_CONFIRMATION") != "1":
            alert = NSAlert.alloc().init()
            alert.setMessageText_("Rename original loops in place?")
            alert.setInformativeText_("Stem Slicer checks filename collisions first, but the source filenames will change.")
            alert.addButtonWithTitle_("Rename originals")
            alert.addButtonWithTitle_("Cancel")
            if alert.runModal() != 1000:
                return
        self.start_button.setEnabled_(False)
        self.progress.setDoubleValue_(0)
        self.status.setStringValue_("Preparing the batch...")
        modes = ["detected", "relative_minor", "relative_major"]
        settings = {
            "enabled": key_enabled,
            "extract_enabled": extract_enabled,
            "mode": modes[self.mode_control.selectedSegment()],
            "accidentals": "sharps" if self.accidental_control.selectedSegment() == 0 else "flats",
            "destination_mode": "rename_in_place" if rename_in_place else "copy_to_output",
            "token_order": list(self.token_strip.tokens),
        }

        def ui_progress(current, total, status):
            NSOperationQueue.mainQueue().addOperationWithBlock_(lambda: self.setProgress_((current, total, status)))

        def ui_done(failures, manifest):
            NSOperationQueue.mainQueue().addOperationWithBlock_(lambda: self.finishProcessing(failures, manifest))

        def ui_error(message):
            NSOperationQueue.mainQueue().addOperationWithBlock_(lambda: self.showError_(message))

        thread = threading.Thread(
            target=process_audio,
            args=(self.source_path, self.output_path, ui_progress, ui_done, ui_error, settings),
            daemon=True,
        )
        thread.start()


def launch_app():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.run()


if __name__ == "__main__":
    launch_app()
