"""Robust Loop-mode BPM analysis for Stem Slicer's Quick Scan.

This module deliberately lives inside the external OpenKeyScan analyzer: the
main Qt application does not bundle Torch, Librosa or SciPy.  It refines the
coarse DeepRhythm estimate with one shared 24-second onset envelope, and only
reads full-file silence structure when the local and global tempo families
disagree.

The filename BPM is never used to choose an audio candidate.  It is consulted
only after the audio-only decision, so a coherent one-BPM rounding difference
can be displayed exactly while a materially wrong title is ignored.
"""

from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path
from statistics import mean

import librosa
import numpy as np
from scipy import signal


SAMPLE_RATE = 22_050
AUDIO_SECONDS = 24.0
HOP_LENGTH = 128
GRID_STEP = 0.02
LOCAL_RADIUS = 3.0
GLOBAL_MIN = 94.0
GLOBAL_MAX = 186.0
MIN_LONG_SILENCE_SECONDS = 1.0
STRUCTURE_RUN_LENGTH = 3
MIN_DEEPRHYTHM_SECONDS = 8.0

# Structural families already supported by Stem Slicer's extraction engine.
STRUCTURE_TEMPLATES = (
    (8, 4),
    (8, 2),
    (8, 1),
    (16, 4),
    (4, 4),
    (4, 2),
    (4, 1),
    (8, 8),
    (16, 8),
)

EXPLICIT_BPM_RE = re.compile(r"(?i)(?<!\d)(\d{2,3})\s*BPM(?![A-Z])")
LEADING_ID_RE = re.compile(r"^\s*\d{3,4}\s*(?:-\s*)?")
INTEGER_RE = re.compile(r"(?<!\d)(\d{2,3})(?!\d)")


def normalize_loop_bpm(bpm: float) -> float:
    """Apply the validated Loop display convention exactly once."""
    value = float(bpm)
    return value * 2.0 if value < 94.0 else value


def prepare_loop_audio(audio: np.ndarray) -> np.ndarray:
    """Repeat a short loop to the eight seconds required by DeepRhythm.

    Loop mode can legitimately receive a single four-bar render shorter than
    one DeepRhythm frame. Repetition preserves its pulse and is limited to
    this explicit Quick Scan mode; legacy extraction analysis is unchanged.
    """
    values = np.asarray(audio)
    if values.size == 0:
        raise ValueError("Loop BPM analysis requires non-empty audio.")
    minimum_samples = int(SAMPLE_RATE * MIN_DEEPRHYTHM_SECONDS)
    if len(values) >= minimum_samples:
        return values
    repetitions = math.ceil(minimum_samples / len(values))
    return np.tile(values, repetitions)[:minimum_samples]


def integer_bpm(value: float) -> int:
    """Match the benchmark's positive-number integer conversion."""
    return int(round(float(value)))


def family_distance(estimate: float, reference: float) -> float:
    """Distance after accepting exact half/double tempo equivalence."""
    return min(
        abs(float(estimate) * factor - float(reference))
        for factor in (0.5, 1.0, 2.0)
    )


def same_tempo_family(left: float, right: float, tolerance: float = 1.0) -> bool:
    return family_distance(left, right) <= tolerance


def parse_declared_bpm(filename: str) -> int | None:
    """Parse one unambiguous BPM while ignoring a leading producer ID.

    An explicit ``NNN BPM`` token wins.  Otherwise, a leading three/four-digit
    identifier is removed and exactly one plausible 60..260 value is required.
    Ambiguous titles intentionally return ``None`` rather than guessing.
    """
    stem = Path(filename).stem
    explicit = [
        int(value)
        for value in EXPLICIT_BPM_RE.findall(stem)
        if 60 <= int(value) <= 260
    ]
    if len(explicit) == 1:
        return explicit[0]
    if len(explicit) > 1:
        return None

    without_id = LEADING_ID_RE.sub("", stem, count=1)
    candidates = [
        int(value)
        for value in INTEGER_RE.findall(without_id)
        if 60 <= int(value) <= 260
    ]
    return candidates[0] if len(candidates) == 1 else None


def reconcile_quick_scan_bpm(
    declared_bpm: int | None,
    audio_bpm: float,
    tolerance: float = 1.0,
) -> tuple[float, str]:
    """Return the exact Loop-facing BPM without contaminating audio inference.

    The representation nearest to the audio result is preserved when it is an
    integer (for example title 192 / audio 96 remains 96).  An odd half-tempo
    such as title 193 / audio 96.5 cannot be represented exactly as an integer,
    so the declared full-tempo integer is retained instead of rounding early.
    """
    audio_value = float(audio_bpm)
    if not declared_bpm:
        return float(integer_bpm(audio_value)), "audio"

    declared = float(declared_bpm)
    representations = (declared, declared / 2.0, declared * 2.0)
    nearest = min(representations, key=lambda value: abs(value - audio_value))
    nearest_integer = integer_bpm(nearest)
    if abs(nearest - nearest_integer) <= 0.05:
        # The product rule is stated on displayed integer BPMs: an audio result
        # that rounds to 150 confirms a declared 151, even if the retained
        # continuous estimate is 149.98 rather than exactly 150.00.
        if abs(nearest_integer - integer_bpm(audio_value)) > tolerance:
            return float(integer_bpm(audio_value)), "audio_title_mismatch"
        return float(nearest_integer), "declared_confirmed"
    if abs(nearest - audio_value) > tolerance:
        return float(integer_bpm(audio_value)), "audio_title_mismatch"
    return declared, "declared_confirmed_odd_half"


def bpm_grid(start: float, stop: float) -> np.ndarray:
    return np.arange(start, stop + GRID_STEP / 2.0, GRID_STEP)


def onset_features(audio: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build the single onset representation shared by both refiners."""
    onset = librosa.onset.onset_strength(
        y=audio,
        sr=SAMPLE_RATE,
        hop_length=HOP_LENGTH,
        n_fft=1024,
        aggregate=np.median,
        detrend=True,
        center=True,
    ).astype(np.float64)
    onset = np.maximum(onset, 0.0)
    maximum = float(np.max(onset)) if onset.size else 0.0
    if maximum > 0:
        onset /= maximum
    times = librosa.times_like(onset, sr=SAMPLE_RATE, hop_length=HOP_LENGTH)

    positive = onset[onset > 0]
    floor = float(np.quantile(positive, 0.55)) if positive.size else 0.0
    peaks, _ = signal.find_peaks(
        onset,
        height=floor,
        prominence=max(0.015, float(np.std(onset)) * 0.08),
        distance=2,
    )
    return onset, times[peaks], onset[peaks] ** 1.5


def spectral_grid_score(
    bpms: np.ndarray,
    peak_times: np.ndarray,
    weights: np.ndarray,
    subdivisions=(0.25, 0.5, 1.0, 2.0, 4.0),
    subdivision_weights=(0.3, 0.4, 0.7, 1.0, 1.2),
) -> np.ndarray:
    """Circular concentration of salient attacks on candidate metric grids."""
    if len(peak_times) == 0:
        return np.zeros_like(bpms)
    normalized_weights = weights / (np.sum(weights) + 1e-12)
    scores = np.zeros_like(bpms)
    for subdivision, sub_weight in zip(subdivisions, subdivision_weights):
        phase = (
            2j
            * np.pi
            * subdivision
            / 60.0
            * np.outer(bpms, peak_times)
        )
        scores += sub_weight * np.abs(np.exp(phase) @ normalized_weights)
    return scores / sum(subdivision_weights)


def acf_comb_score(
    bpms: np.ndarray,
    onset: np.ndarray,
    max_seconds: float = 20.0,
    subdivisions=(0.25, 0.5, 1.0, 2.0, 4.0),
    subdivision_weights=(0.45, 0.6, 1.0, 0.7, 0.45),
) -> np.ndarray:
    """Score repeated integer lags for every candidate tempo."""
    centered = onset - np.mean(onset)
    if not np.any(centered):
        return np.zeros_like(bpms)
    acf = signal.fftconvolve(centered, centered[::-1], mode="full")[
        len(centered) - 1 :
    ]
    overlap = np.arange(len(centered), 0, -1, dtype=float)
    acf = acf / np.maximum(overlap, 1.0)
    acf /= max(abs(acf[0]), 1e-12)

    lag_axis = np.arange(len(acf), dtype=float)
    frame_rate = SAMPLE_RATE / HOP_LENGTH
    max_lag = min(len(acf) - 2, int(max_seconds * frame_rate))
    result = np.zeros_like(bpms)
    total_weight = 0.0
    for subdivision, sub_weight in zip(subdivisions, subdivision_weights):
        periods = 60.0 * frame_rate / (bpms * subdivision)
        max_k = max(1, int(max_lag / np.min(periods)))
        for multiple in range(1, max_k + 1):
            lags = periods * multiple
            valid = lags <= max_lag
            if not np.any(valid):
                continue
            weight = sub_weight / math.sqrt(multiple)
            sampled = np.zeros_like(bpms)
            sampled[valid] = np.interp(lags[valid], lag_axis, acf)
            result += weight * sampled
            total_weight += weight
    return result / max(total_weight, 1e-12)


def robust_standardize(values: np.ndarray) -> np.ndarray:
    median = np.median(values)
    scale = np.quantile(values, 0.9) - np.quantile(values, 0.1)
    return (values - median) / max(float(scale), 1e-12)


def refine_from_onsets(
    onset: np.ndarray,
    peak_times: np.ndarray,
    peak_weights: np.ndarray,
    deep_bpm: float,
) -> dict:
    """Compute the validated local and global audio-only BPM candidates."""
    local_grid = bpm_grid(deep_bpm - LOCAL_RADIUS, deep_bpm + LOCAL_RADIUS)
    local_spectral = spectral_grid_score(local_grid, peak_times, peak_weights)
    local_float = float(local_grid[int(np.argmax(local_spectral))])

    global_grid = bpm_grid(GLOBAL_MIN, GLOBAL_MAX)
    spectral = spectral_grid_score(global_grid, peak_times, peak_weights)
    acf = acf_comb_score(global_grid, onset)
    combined = robust_standardize(spectral) + robust_standardize(acf)
    global_float = float(global_grid[int(np.argmax(combined))])
    spectral_float = float(global_grid[int(np.argmax(spectral))])
    acf_float = float(global_grid[int(np.argmax(acf))])

    local_integer = integer_bpm(local_float)
    global_integer = integer_bpm(global_float)
    spectral_integer = integer_bpm(spectral_float)
    acf_integer = integer_bpm(acf_float)
    consensus = (
        abs(spectral_integer - global_integer) <= 1
        and abs(acf_integer - global_integer) <= 1
    )
    return {
        "local_float_bpm": local_float,
        "local_bpm": local_integer,
        "global_float_bpm": global_float,
        "global_bpm": global_integer,
        "global_spectral_float_bpm": spectral_float,
        "global_spectral_bpm": spectral_integer,
        "global_acf_float_bpm": acf_float,
        "global_acf_bpm": acf_integer,
        "global_consensus": bool(consensus),
    }


def detect_long_silences(audio_path: Path, ffmpeg_path: Path) -> list[tuple[float, float, float]]:
    """Return full-file silence runs used only by the conflict slow path."""
    completed = subprocess.run(
        [
            str(ffmpeg_path),
            "-nostdin",
            "-hide_banner",
            "-i",
            str(audio_path),
            "-af",
            "silencedetect=noise=-45dB:d=0.1",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()
        reason = detail[-1] if detail else f"exit code {completed.returncode}"
        raise RuntimeError(f"FFmpeg silence detection failed: {reason}")
    starts = [
        float(value)
        for value in re.findall(r"silence_start: (-?[\d.]+)", completed.stderr)
    ]
    ends = [
        float(value)
        for value in re.findall(r"silence_end: (-?[\d.]+)", completed.stderr)
    ]
    # An unpaired trailing event must not fail the entire Quick Scan.
    pair_count = min(len(starts), len(ends))
    return [
        (start, end, end - start)
        for start, end in zip(starts[:pair_count], ends[:pair_count])
        if end >= start and end - start >= MIN_LONG_SILENCE_SECONDS
    ]


def _template_transitions(
    silences: list[tuple[float, float, float]],
    bpm: int,
    layer_bars: int,
    space_bars: int,
) -> list[dict]:
    seconds_per_bar = 240.0 / bpm
    transitions = []
    for current, following in zip(silences, silences[1:]):
        stride = (following[1] - current[1]) / seconds_per_bar
        active = (following[0] - current[1]) / seconds_per_bar
        gap = following[2] / seconds_per_bar
        cost = (
            abs(stride - (layer_bars + space_bars))
            + max(0.0, layer_bars - 0.5 - active)
            + max(0.0, gap - (space_bars + 0.5))
            + max(0.0, active - (layer_bars + space_bars + 0.5))
        )
        transitions.append(
            {
                "stride_bars": stride,
                "active_bars": active,
                "gap_bars": gap,
                "cost": cost,
            }
        )
    return transitions


def best_consecutive_structure_fit(
    silences: list[tuple[float, float, float]], bpm: int
) -> dict | None:
    """Find the best repeated run without cherry-picking isolated transitions."""
    choices = []
    for layer_bars, space_bars in STRUCTURE_TEMPLATES:
        transitions = _template_transitions(
            silences, bpm, layer_bars, space_bars
        )
        if len(transitions) < STRUCTURE_RUN_LENGTH:
            continue
        for start in range(len(transitions) - STRUCTURE_RUN_LENGTH + 1):
            window = transitions[start : start + STRUCTURE_RUN_LENGTH]
            costs = [float(item["cost"]) for item in window]
            choices.append(
                {
                    "bpm": int(bpm),
                    "layer_bars": layer_bars,
                    "space_bars": space_bars,
                    "transition_start": start,
                    "mean_cost_bars": mean(costs),
                    "max_cost_bars": max(costs),
                }
            )
    if not choices:
        return None
    choices.sort(key=lambda item: (item["mean_cost_bars"], item["max_cost_bars"]))
    return choices[0]


def resolve_structure_conflict(
    audio_path: Path,
    ffmpeg_path: Path | None,
    local_bpm: int,
    global_bpm: int,
) -> dict:
    """Resolve a local/global conflict or return an explicit abstention."""
    if not ffmpeg_path or not Path(ffmpeg_path).is_file():
        return {"status": "unavailable", "selected_bpm": None}
    try:
        silences = detect_long_silences(audio_path, Path(ffmpeg_path))
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        return {
            "status": "unavailable",
            "selected_bpm": None,
            "error": str(exc),
        }
    if len(silences) < STRUCTURE_RUN_LENGTH + 1:
        return {
            "status": "insufficient",
            "selected_bpm": None,
            "long_silence_count": len(silences),
        }

    fits = [
        best_consecutive_structure_fit(silences, int(local_bpm)),
        best_consecutive_structure_fit(silences, int(global_bpm)),
    ]
    fits = [fit for fit in fits if fit is not None]
    if len(fits) != 2:
        return {
            "status": "insufficient",
            "selected_bpm": None,
            "long_silence_count": len(silences),
        }
    fits.sort(key=lambda item: (item["mean_cost_bars"], item["max_cost_bars"]))
    winner, loser = fits
    margin = loser["mean_cost_bars"] - winner["mean_cost_bars"]
    high = winner["mean_cost_bars"] <= 0.05 and margin >= 0.05
    medium = winner["mean_cost_bars"] <= 1.0 and margin >= 0.25
    resolved = high or medium
    return {
        "status": "resolved" if resolved else "ambiguous",
        "selected_bpm": int(winner["bpm"]) if resolved else None,
        "confidence": "high" if high else "medium" if medium else "ambiguous",
        "long_silence_count": len(silences),
        "winning_margin_bars": margin,
        "winner_mean_cost_bars": winner["mean_cost_bars"],
        "winner_template": [winner["layer_bars"], winner["space_bars"]],
    }


def analyze_loop_bpm(
    audio_path: Path,
    audio: np.ndarray,
    raw_deep_bpm: float,
    ffmpeg_path: Path | None = None,
) -> dict:
    """Run the complete Quick Scan Loop BPM decision."""
    if audio is None or len(audio) < SAMPLE_RATE * MIN_DEEPRHYTHM_SECONDS:
        raise ValueError("Loop BPM analysis requires at least 8 seconds of audio.")

    deep_bpm = normalize_loop_bpm(raw_deep_bpm)
    onset, peak_times, peak_weights = onset_features(audio)
    refined = refine_from_onsets(
        onset, peak_times, peak_weights, deep_bpm
    )
    local_bpm = int(refined["local_bpm"])
    global_bpm = int(refined["global_bpm"])
    structure = None

    if same_tempo_family(local_bpm, global_bpm):
        # Across all 173 observed agreement cases, the global continuous winner
        # was the most precise final value; the local branch remains its guard.
        selected_float = float(refined["global_float_bpm"])
        decision = "onset_agreement"
    else:
        structure = resolve_structure_conflict(
            Path(audio_path), ffmpeg_path, local_bpm, global_bpm
        )
        selected = structure.get("selected_bpm")
        if selected == local_bpm:
            selected_float = float(refined["local_float_bpm"])
            decision = "structure_local"
        elif selected == global_bpm:
            selected_float = float(refined["global_float_bpm"])
            decision = "structure_global"
        elif refined["global_consensus"]:
            selected_float = float(refined["global_float_bpm"])
            decision = "global_consensus_fallback"
        else:
            selected_float = float(refined["local_float_bpm"])
            decision = "local_fallback"

    declared = parse_declared_bpm(Path(audio_path).name)
    final_bpm, final_source = reconcile_quick_scan_bpm(declared, selected_float)
    return {
        "bpm": final_bpm,
        "bpm_float": selected_float,
        "bpm_source": final_source,
        "bpm_decision": decision,
        "declared_bpm": declared,
        "deep_normalized_bpm": deep_bpm,
        **refined,
        "structure": structure,
    }
