"""Pure NumPy engine for experimental contiguous-layer (No Space) inference.

This module is extracted from the frozen Solution A research detector.  It has
no product-engine import, file/path handling, truth access, CLI, subprocess, or
research serialization.  The production-compatible default remains four
layers.  A caller may explicitly request three layers for a future shadow-only
experiment; this module never enables that mode by itself.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Iterable

import numpy as np


SUBDIVISIONS_PER_BAR = 8
SPECTRAL_BANDS = 30
LAYER_OPTIONS = (4, 8)
MIN_LAYERS = 4
SHADOW_MIN_LAYERS = 3


@dataclass(frozen=True)
class Candidate:
    start: int
    duration: int
    count: int
    end: int
    score: float
    comb_contrast: float
    boundary_median: float
    boundary_floor: float
    peak_fraction: float
    containment_median: float
    containment_floor: float
    closure_similarity: float
    occupancy_median: float
    tail_bars: int


def _validate_minimum_layers(minimum_layers: int) -> int:
    minimum_layers = int(minimum_layers)
    if minimum_layers not in (SHADOW_MIN_LAYERS, MIN_LAYERS):
        raise ValueError("minimum_layers must be 4, or explicitly 3 for shadow evaluation.")
    return minimum_layers


def robust_standardize(matrix: np.ndarray) -> np.ndarray:
    median = np.median(matrix, axis=0, keepdims=True)
    mad = np.median(np.abs(matrix - median), axis=0, keepdims=True)
    scale = np.maximum(1.4826 * mad, 1.0e-5)
    return np.clip((matrix - median) / scale, -8.0, 8.0)


def robust_z(values: np.ndarray) -> np.ndarray:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return np.zeros_like(values)
    center = np.median(finite)
    mad = np.median(np.abs(finite - center))
    scale = max(1.4826 * mad, 1.0e-6)
    return np.clip((values - center) / scale, -12.0, 12.0)


def band_boundaries(sample_rate: int, fft_size: int) -> list[tuple[int, int]]:
    frequencies = np.fft.rfftfreq(fft_size, 1.0 / sample_rate)
    edges = np.geomspace(
        35.0,
        min(10_500.0, sample_rate * 0.48),
        SPECTRAL_BANDS + 1,
    )
    bins = np.searchsorted(frequencies, edges)
    bins = np.clip(bins, 1, len(frequencies) - 1)
    ranges = []
    for index in range(SPECTRAL_BANDS):
        start = int(bins[index])
        end = max(start + 1, int(bins[index + 1]))
        ranges.append((start, min(end, len(frequencies))))
    return ranges


def extract_cell_features(
    samples: np.ndarray,
    sample_rate: int,
    seconds_per_bar: float,
    true_zero: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    zero_sample = max(0, int(round(true_zero * sample_rate)))
    signal = np.asarray(samples[zero_sample:], dtype=np.float32)
    samples_per_cell = max(
        256,
        int(round(sample_rate * seconds_per_bar / SUBDIVISIONS_PER_BAR)),
    )
    cell_count = signal.size // samples_per_cell
    if cell_count < SUBDIVISIONS_PER_BAR * 16:
        raise ValueError("Audio is too short for structural inference.")
    cells = signal[: cell_count * samples_per_cell].reshape(
        cell_count,
        samples_per_cell,
    )

    fft_size = 1 << max(10, (samples_per_cell - 1).bit_length())
    window = np.hanning(samples_per_cell).astype(np.float32)
    ranges = band_boundaries(sample_rate, fft_size)
    spectral_power = np.empty((cell_count, SPECTRAL_BANDS), dtype=np.float32)
    rms = np.empty(cell_count, dtype=np.float32)
    peak = np.empty(cell_count, dtype=np.float32)
    zcr = np.empty(cell_count, dtype=np.float32)
    for batch_start in range(0, cell_count, 128):
        batch = cells[batch_start : batch_start + 128]
        transformed = np.fft.rfft(batch * window, n=fft_size, axis=1)
        power = (
            transformed.real * transformed.real
            + transformed.imag * transformed.imag
        )
        for band, (start, end) in enumerate(ranges):
            spectral_power[
                batch_start : batch_start + len(batch),
                band,
            ] = np.mean(power[:, start:end], axis=1)
        rms[batch_start : batch_start + len(batch)] = np.sqrt(
            np.mean(batch * batch, axis=1) + 1.0e-12
        )
        peak[batch_start : batch_start + len(batch)] = np.max(
            np.abs(batch),
            axis=1,
        )
        zcr[batch_start : batch_start + len(batch)] = np.mean(
            np.signbit(batch[:, 1:]) != np.signbit(batch[:, :-1]),
            axis=1,
        )

    log_spectrum = np.log10(spectral_power + 1.0e-12)
    loudness = 20.0 * np.log10(rms + 1.0e-12)
    crest = 20.0 * np.log10((peak + 1.0e-12) / (rms + 1.0e-12))
    spectral_shape = log_spectrum - np.mean(
        log_spectrum,
        axis=1,
        keepdims=True,
    )
    features = np.column_stack((spectral_shape, loudness, crest, zcr))
    standardized = robust_standardize(features)
    total_bars = cell_count / SUBDIVISIONS_PER_BAR
    return standardized, log_spectrum, loudness, total_bars


def rbf_mmd(left: np.ndarray, right: np.ndarray) -> float:
    joined = np.vstack((left, right))
    squared = np.sum(
        (joined[:, None, :] - joined[None, :, :]) ** 2,
        axis=2,
    )
    nonzero = squared[squared > 1.0e-9]
    bandwidth = float(np.median(nonzero)) if nonzero.size else 1.0
    kernel = np.exp(-squared / max(bandwidth, 1.0e-6))
    length = len(left)
    return float(
        kernel[:length, :length].mean()
        + kernel[length:, length:].mean()
        - 2.0 * kernel[:length, length:].mean()
    )


def boundary_novelty(features: np.ndarray) -> np.ndarray:
    bars = len(features) // SUBDIVISIONS_PER_BAR
    scale_scores = []
    for half_window in (4, 8, 16):
        values = np.full(bars + 1, np.nan, dtype=np.float64)
        for bar in range(1, bars):
            boundary = bar * SUBDIVISIONS_PER_BAR
            if (
                boundary - half_window < 0
                or boundary + half_window > len(features)
            ):
                continue
            left = features[boundary - half_window : boundary]
            right = features[boundary : boundary + half_window]
            mean_jump = float(
                np.sqrt(
                    np.mean(
                        (left.mean(axis=0) - right.mean(axis=0)) ** 2
                    )
                )
            )
            variance_jump = float(
                np.sqrt(
                    np.mean(
                        (left.var(axis=0) - right.var(axis=0)) ** 2
                    )
                )
            )
            values[bar] = (
                mean_jump
                + 0.30 * variance_jump
                + 1.40 * rbf_mmd(left, right)
            )
        scale_scores.append(
            robust_z(np.nan_to_num(values, nan=np.nanmedian(values)))
        )
    local = np.full(bars + 1, np.nan, dtype=np.float64)
    for bar in range(1, bars):
        boundary = bar * SUBDIVISIONS_PER_BAR
        local[bar] = float(
            np.sqrt(
                np.mean(
                    (features[boundary - 1] - features[boundary]) ** 2
                )
            )
        )
    local = robust_z(np.nan_to_num(local, nan=np.nanmedian(local)))
    combined = np.median(np.vstack(scale_scores), axis=0) + 0.20 * local
    combined[0] = -12.0
    return robust_z(combined)


def chunk_signature(
    log_spectrum: np.ndarray,
    start: int,
    duration: int,
) -> np.ndarray | None:
    first = start * SUBDIVISIONS_PER_BAR
    last = (start + duration) * SUBDIVISIONS_PER_BAR
    if first < 0 or last > len(log_spectrum):
        return None
    block = log_spectrum[first:last]
    phase = block.reshape(
        duration,
        SUBDIVISIONS_PER_BAR,
        SPECTRAL_BANDS,
    ).mean(axis=0)
    phase -= phase.mean(axis=1, keepdims=True)
    vector = phase.reshape(-1)
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 1.0e-9 else vector


def signature_similarity(first: np.ndarray, second: np.ndarray) -> float:
    return float(np.clip(np.dot(first, second), -1.0, 1.0))


def chunk_containment(
    log_spectrum: np.ndarray,
    prefix_end: int,
    chunk_start: int,
    duration: int,
) -> float:
    source = chunk_signature(log_spectrum, chunk_start, duration)
    if source is None:
        return -1.0
    references = []
    for reference_start in range(0, max(0, prefix_end - duration) + 1):
        reference = chunk_signature(log_spectrum, reference_start, duration)
        if reference is not None:
            references.append(signature_similarity(source, reference))
    return max(references, default=-1.0)


def closure_similarity(
    log_spectrum: np.ndarray,
    start: int,
    duration: int,
    count: int,
    minimum_layers: int = MIN_LAYERS,
) -> float:
    minimum_layers = _validate_minimum_layers(minimum_layers)
    signatures = [
        chunk_signature(
            log_spectrum,
            start + index * duration,
            duration,
        )
        for index in range(count)
    ]
    signatures = [
        signature for signature in signatures if signature is not None
    ]
    if len(signatures) < minimum_layers:
        return -1.0
    source_stack = np.vstack(signatures)
    positive_envelope = (
        np.max(source_stack, axis=0)
        + np.mean(source_stack, axis=0)
    )
    envelope_norm = float(np.linalg.norm(positive_envelope))
    if envelope_norm <= 1.0e-9:
        return -1.0
    positive_envelope /= envelope_norm
    references = []
    for reference_start in range(0, max(0, start - duration) + 1):
        reference = chunk_signature(log_spectrum, reference_start, duration)
        if reference is not None:
            references.append(
                signature_similarity(positive_envelope, reference)
            )
    return max(references, default=-1.0)


def block_occupancy(
    loudness: np.ndarray,
    start: int,
    duration: int,
    threshold: float,
) -> float:
    first = start * SUBDIVISIONS_PER_BAR
    last = (start + duration) * SUBDIVISIONS_PER_BAR
    block = loudness[first:last]
    return float(np.mean(block >= threshold)) if block.size else 0.0


def chunk_profile(
    log_spectrum: np.ndarray,
    loudness: np.ndarray,
    novelty: np.ndarray,
    start: int,
    duration: int,
    bar_limit: int,
    loudness_threshold: float,
) -> list[dict]:
    rows = []
    previous_signature = None
    for position in range(start, bar_limit - duration + 1, duration):
        first = position * SUBDIVISIONS_PER_BAR
        last = (position + duration) * SUBDIVISIONS_PER_BAR
        spectrum = log_spectrum[first:last]
        power = np.power(
            10.0,
            spectrum - np.max(spectrum, axis=1, keepdims=True),
        )
        distribution = power / np.maximum(
            power.sum(axis=1, keepdims=True),
            1.0e-12,
        )
        entropy = -np.sum(
            distribution * np.log(distribution + 1.0e-12),
            axis=1,
        )
        entropy /= math.log(SPECTRAL_BANDS)
        signature = chunk_signature(log_spectrum, position, duration)
        previous_similarity = (
            signature_similarity(signature, previous_signature)
            if signature is not None and previous_signature is not None
            else None
        )
        block_loudness = loudness[first:last]
        rows.append(
            {
                "start": position,
                "end": position + duration,
                "novelty": float(novelty[position]),
                "mean_loudness": float(np.mean(block_loudness)),
                "q10_loudness": float(
                    np.quantile(block_loudness, 0.10)
                ),
                "occupancy": block_occupancy(
                    loudness,
                    position,
                    duration,
                    loudness_threshold,
                ),
                "spectral_entropy": float(np.mean(entropy)),
                "previous_similarity": previous_similarity,
            }
        )
        previous_signature = signature
    return rows


def candidate_metrics(
    novelty: np.ndarray,
    log_spectrum: np.ndarray,
    loudness: np.ndarray,
    start: int,
    duration: int,
    count: int,
    bar_limit: int,
    loudness_threshold: float,
    minimum_layers: int = MIN_LAYERS,
) -> Candidate:
    minimum_layers = _validate_minimum_layers(minimum_layers)
    end = start + duration * count
    boundary_positions = [
        start + index * duration for index in range(count)
    ]
    boundaries = np.asarray(
        [novelty[position] for position in boundary_positions]
    )
    control_positions = []
    offsets = (
        duration // 4,
        duration // 2,
        (duration * 3) // 4,
    )
    for position in boundary_positions:
        control_positions.extend(
            shifted
            for shifted in (
                position + offset for offset in offsets
            )
            if 0 < shifted < min(end, len(novelty))
        )
    controls = np.asarray(
        [novelty[position] for position in control_positions]
    )
    comb_contrast = float(
        np.median(boundaries) - np.median(controls)
    )
    boundary_median = float(np.median(boundaries))
    boundary_floor = float(np.quantile(boundaries, 0.20))
    peak_threshold = float(
        np.quantile(novelty[1:bar_limit], 0.60)
    )
    peak_fraction = float(np.mean(boundaries >= peak_threshold))
    containments = np.asarray(
        [
            chunk_containment(
                log_spectrum,
                start,
                position,
                duration,
            )
            for position in boundary_positions
        ]
    )
    containment_median = float(np.median(containments))
    containment_floor = float(np.quantile(containments, 0.20))
    closure = closure_similarity(
        log_spectrum,
        start,
        duration,
        count,
        minimum_layers,
    )
    occupancies = np.asarray(
        [
            block_occupancy(
                loudness,
                position,
                duration,
                loudness_threshold,
            )
            for position in boundary_positions
        ]
    )
    occupancy_median = float(np.median(occupancies))
    tail_bars = max(0, bar_limit - end)
    terminal_bonus = 0.0
    if tail_bars <= 1:
        terminal_bonus = 0.8
    elif end < len(novelty):
        terminal_bonus = min(
            1.0,
            max(-0.5, float(novelty[end]) * 0.20),
        )
    length_bonus = min(
        1.5,
        math.log2(max(count, 1)) * 0.45,
    )
    duration_prior = 2.0 if duration == 8 else 0.0
    score = (
        1.35 * comb_contrast
        + 0.65 * boundary_median
        + 0.35 * boundary_floor
        + 1.20 * peak_fraction
        + 1.80 * containment_median
        + 0.65 * containment_floor
        + 1.00 * closure
        + 0.80 * occupancy_median
        + terminal_bonus
        + length_bonus
        + duration_prior
    )
    return Candidate(
        start=start,
        duration=duration,
        count=count,
        end=end,
        score=float(score),
        comb_contrast=comb_contrast,
        boundary_median=boundary_median,
        boundary_floor=boundary_floor,
        peak_fraction=peak_fraction,
        containment_median=containment_median,
        containment_floor=containment_floor,
        closure_similarity=float(closure),
        occupancy_median=occupancy_median,
        tail_bars=tail_bars,
    )


def shortlist_candidates(
    novelty: np.ndarray,
    bar_limit: int,
    minimum_layers: int = MIN_LAYERS,
) -> list[tuple[float, int, int, int]]:
    minimum_layers = _validate_minimum_layers(minimum_layers)
    short = []
    for duration in LAYER_OPTIONS:
        for start in range(
            16,
            bar_limit - minimum_layers * duration + 1,
        ):
            maximum_count = (bar_limit - start) // duration
            for count in range(minimum_layers, maximum_count + 1):
                end = start + count * duration
                boundaries = np.asarray(
                    [
                        novelty[start + index * duration]
                        for index in range(count)
                    ]
                )
                controls = np.asarray(
                    [
                        novelty[
                            start
                            + index * duration
                            + duration // 2
                        ]
                        for index in range(count)
                        if (
                            start
                            + index * duration
                            + duration // 2
                            < end
                        )
                    ]
                )
                rough = (
                    float(
                        np.median(boundaries)
                        - np.median(controls)
                    )
                    + 0.35
                    * float(np.quantile(boundaries, 0.20))
                    + min(1.0, count / 10.0)
                    + (0.4 if bar_limit - end <= 1 else 0.0)
                )
                short.append((rough, start, duration, count))
    short.sort(reverse=True)
    selected = []
    per_phase: dict[tuple[int, int], int] = {}
    for item in short:
        _, start, duration, _ = item
        key = (duration, start % duration)
        if per_phase.get(key, 0) >= 4:
            continue
        selected.append(item)
        per_phase[key] = per_phase.get(key, 0) + 1
        if len(selected) >= 80:
            break
    return selected


def select_sequence_start(
    novelty: np.ndarray,
    conservative_start: int,
    duration: int,
    chosen_end: int,
    minimum_layers: int = MIN_LAYERS,
) -> tuple[int, dict]:
    minimum_layers = _validate_minimum_layers(minimum_layers)
    positions = list(
        range(conservative_start, chosen_end, duration)
    )
    for index, position in enumerate(positions):
        remaining = len(positions) - index
        if remaining < minimum_layers:
            break
        future = np.asarray(
            [
                novelty[value]
                for value in positions[
                    index : index + min(5, remaining)
                ]
            ]
        )
        previous = np.asarray(
            [
                novelty[value]
                for value in positions[max(0, index - 3) : index]
            ]
        )
        previous_median = (
            float(np.median(previous))
            if previous.size
            else 0.0
        )
        jump = float(novelty[position] - previous_median)
        future_median = float(np.median(future))
        future_fraction = float(np.mean(future >= 1.0))
        if (
            novelty[position] >= 1.5
            and jump >= 1.5
            and future_median >= 1.5
            and future_fraction >= 0.75
        ):
            exact_strength = min(
                float(novelty[position]),
                jump,
                future_median,
            )
            recall_blocks = 1 if exact_strength >= 3.0 else 2
            selected = max(
                conservative_start,
                position - recall_blocks * duration,
            )
            return selected, {
                "detected_boundary": position,
                "selected_start": selected,
                "exact_strength": exact_strength,
                "jump": jump,
                "future_median": future_median,
                "future_fraction": future_fraction,
            }
    return conservative_start, {
        "detected_boundary": None,
        "selected_start": conservative_start,
        "reason": "no_sustained_boundary_run",
    }


def infer_nospace_candidate(
    samples: np.ndarray,
    sample_rate: int,
    seconds_per_bar: float,
    true_zero: float,
    minimum_layers: int = MIN_LAYERS,
) -> tuple[Candidate | None, float, dict]:
    minimum_layers = _validate_minimum_layers(minimum_layers)
    features, log_spectrum, loudness, total_bars = (
        extract_cell_features(
            samples,
            sample_rate,
            seconds_per_bar,
            true_zero,
        )
    )
    novelty = boundary_novelty(features)
    rounded_bars = round(total_bars)
    if abs(total_bars - rounded_bars) <= 0.35:
        inferred_bars = int(rounded_bars)
    else:
        inferred_bars = int(math.floor(total_bars))
    bar_limit = inferred_bars
    loudness_floor = float(np.quantile(loudness, 0.15))
    loudness_high = float(np.quantile(loudness, 0.85))
    loudness_threshold = min(
        loudness_high - 20.0,
        loudness_floor + 10.0,
    )
    candidates = [
        candidate_metrics(
            novelty,
            log_spectrum,
            loudness,
            start,
            duration,
            count,
            bar_limit,
            loudness_threshold,
            minimum_layers,
        )
        for _, start, duration, count in shortlist_candidates(
            novelty,
            bar_limit,
            minimum_layers,
        )
    ]
    candidates.sort(
        key=lambda candidate: candidate.score,
        reverse=True,
    )
    if not candidates:
        return None, 0.0, {
            "bar_limit": bar_limit,
            "total_bars": total_bars,
        }
    model_best = candidates[0]
    compatible = [
        candidate
        for candidate in candidates
        if candidate.duration == model_best.duration
        and (
            candidate.start % candidate.duration
            == model_best.start % model_best.duration
        )
    ]
    del compatible
    phase = model_best.start % model_best.duration
    conservative_start = (
        16 + ((phase - 16) % model_best.duration)
    )
    maximum_count = max(
        0,
        (bar_limit - conservative_start) // model_best.duration,
    )
    terminal_activity = []
    chosen_end = conservative_start
    for index in range(maximum_count):
        position = (
            conservative_start + index * model_best.duration
        )
        occupancy = block_occupancy(
            loudness,
            position,
            model_best.duration,
            loudness_threshold,
        )
        terminal_activity.append(
            {
                "start": position,
                "end": position + model_best.duration,
                "occupancy": occupancy,
            }
        )
        if occupancy >= 0.20:
            chosen_end = position + model_best.duration
    selected_start, start_diagnostics = select_sequence_start(
        novelty,
        conservative_start,
        model_best.duration,
        chosen_end,
        minimum_layers,
    )
    conservative_count = (
        (chosen_end - selected_start) // model_best.duration
    )
    if conservative_count < minimum_layers:
        return None, 0.0, {
            "bar_limit": bar_limit,
            "total_bars": total_bars,
            "fallback_reason": (
                "fewer_than_minimum_active_layers_after_terminal_scan"
            ),
            "minimum_layers": minimum_layers,
            "selected_start": selected_start,
            "chosen_end": chosen_end,
            "selected_count": conservative_count,
            "model_best_before_recall_adjustment": asdict(
                model_best
            ),
        }
    best = candidate_metrics(
        novelty,
        log_spectrum,
        loudness,
        selected_start,
        model_best.duration,
        conservative_count,
        bar_limit,
        loudness_threshold,
        minimum_layers,
    )
    rivals = [
        candidate
        for candidate in candidates[1:]
        if (
            candidate.duration != model_best.duration
            or (
                candidate.start % candidate.duration
                != model_best.start % model_best.duration
            )
        )
    ]
    runner_up = (
        rivals[0].score
        if rivals
        else (
            candidates[1].score
            if len(candidates) > 1
            else model_best.score
        )
    )
    return best, float(model_best.score - runner_up), {
        "bar_limit": bar_limit,
        "total_bars": total_bars,
        "novelty_quantiles": {
            "q20": float(
                np.quantile(novelty[1:bar_limit], 0.20)
            ),
            "q50": float(
                np.quantile(novelty[1:bar_limit], 0.50)
            ),
            "q80": float(
                np.quantile(novelty[1:bar_limit], 0.80)
            ),
        },
        "top_candidates": [
            asdict(candidate) for candidate in candidates[:8]
        ],
        "model_best_before_recall_adjustment": asdict(
            model_best
        ),
        "recall_adjustment": {
            "conservative_start": conservative_start,
            "start_selection": start_diagnostics,
            "chosen_end": chosen_end,
            "terminal_activity": terminal_activity,
        },
        "selected_phase_profile": chunk_profile(
            log_spectrum,
            loudness,
            novelty,
            selected_start,
            model_best.duration,
            bar_limit,
            loudness_threshold,
        ),
    }


def accepted_gap_contrast(
    grid: dict | None,
    energies: Iterable[float],
) -> float | None:
    if not grid or not grid.get("slots"):
        return None
    energy = list(energies)
    duration_by_slot = grid.get("duration_by_slot", {})
    contrasts = []
    for slot in grid["slots"][:-1]:
        duration = int(
            duration_by_slot.get(slot, grid["layer_bars"])
        )
        next_slot = next(
            (
                value
                for value in grid["slots"]
                if value > slot
            ),
            None,
        )
        if next_slot is None:
            continue
        gap_start = slot + duration
        if next_slot <= gap_start:
            continue
        layer = energy[slot:gap_start]
        gap = energy[gap_start:next_slot]
        if layer and gap:
            contrasts.append(
                float(np.mean(layer) - np.mean(gap))
            )
    return (
        float(np.median(contrasts))
        if contrasts
        else None
    )


def auto_select(
    accepted: dict | None,
    gap_contrast: float | None,
    nospace: Candidate | None,
) -> tuple[str, list[str]]:
    if nospace is None:
        return "accepted", ["no_nospace_hypothesis"]
    pillars = {
        "comb": nospace.comb_contrast >= 1.75,
        "boundary": (
            nospace.boundary_median >= 1.75
            and nospace.boundary_floor >= 1.25
        ),
        "peaks": nospace.peak_fraction >= 0.80,
        "containment": nospace.containment_median >= 0.25,
        "closure": nospace.closure_similarity >= 0.25,
        "occupancy": nospace.occupancy_median >= 0.70,
    }
    failed = [
        name for name, passed in pillars.items() if not passed
    ]
    if failed:
        return "accepted", [
            "nospace_pillar_failed:" + ",".join(failed)
        ]
    if accepted is not None:
        if gap_contrast is None:
            return "accepted", [
                "accepted_model_without_measurable_gap"
            ]
        if gap_contrast >= 12.0:
            return "accepted", [
                "accepted_spaces_have_quiet_contrast"
            ]
    return "nospace", ["nospace_model_gate_passed"]


def nospace_candidate_to_grid(
    candidate: Candidate,
    margin: float,
) -> dict:
    starts = [
        candidate.start + index * candidate.duration
        for index in range(candidate.count)
    ]
    return {
        "score": float(candidate.score),
        "confidence_margin": float(margin),
        "first_start": int(candidate.start),
        "layer_bars": int(candidate.duration),
        "space_bars": 0,
        "stride_bars": int(candidate.duration),
        "slots": starts,
        "active_slots": list(starts),
        "silent_slots": [],
        "duration_by_slot": {
            start: int(candidate.duration) for start in starts
        },
        "sequence_decoder": False,
    }
