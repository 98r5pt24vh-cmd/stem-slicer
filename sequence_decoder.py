"""Experimental regularized sequence decoder for Stem Slicer.

The decoder deliberately has no knowledge of loop names or positions of special
cases.  It models the post-mix section as a sequence of musical slots.  Each file
has a dominant layer duration and gap, but an individual transition may use a
longer layer or a different gap when the audio evidence justifies the change.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
from typing import Iterable, Sequence


MIN_LAYER_REMAINING_RATIO = 0.74
BASE_LAYER_BARS = (4, 8, 16)
BASE_SPACE_BARS = tuple(range(1, 9))
TRANSITION_SPACE_BARS = tuple(range(1, 17))
MAX_LAYER_BARS = 32


@dataclass(frozen=True)
class Slot:
    start: int
    duration: int
    space_after: int
    active: bool
    support: float


@dataclass(frozen=True)
class SequenceResult:
    score: float
    confidence_margin: float
    base_layer_bars: int
    base_space_bars: int
    first_start: int
    slots: tuple[Slot, ...]

    @property
    def active_starts(self) -> list[int]:
        return [slot.start for slot in self.slots if slot.active]

    @property
    def active_durations(self) -> list[int]:
        return [slot.duration for slot in self.slots if slot.active]


@dataclass(frozen=True)
class _TransitionFeatures:
    """Base transition score shared by every candidate base-space model."""

    score: float
    layer_mean: float


def _percentile(values: Sequence[float], fraction: float, default: float) -> float:
    if not values:
        return default
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return ordered[max(0, min(len(ordered) - 1, index))]


def _mean(values: Sequence[float], default: float = -120.0) -> float:
    return sum(values) / len(values) if values else default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def classify_activity(energies: Sequence[float]) -> tuple[float, list[bool]]:
    if not energies:
        return -48.0, []
    floor = _percentile(energies, 0.20, -80.0)
    high = _percentile(energies, 0.90, -24.0)
    threshold = max(-54.0, min(-30.0, floor + 10.0, high - 28.0))
    return threshold, [energy >= threshold for energy in energies]


def active_ranges(active_by_bar: Sequence[bool]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    index = 0
    while index < len(active_by_bar):
        if not active_by_bar[index]:
            index += 1
            continue
        end = index + 1
        while end < len(active_by_bar) and active_by_bar[end]:
            end += 1
        ranges.append((index, end))
        index = end
    return ranges


def _nearest_distance(value: int, candidates: frozenset[int]) -> int:
    return min((abs(value - candidate) for candidate in candidates), default=999)


@lru_cache(maxsize=8192)
def _support_strength(value: int, candidates: frozenset[int]) -> float:
    distance = _nearest_distance(value, candidates)
    return {0: 1.0, 1: 0.62, 2: 0.22}.get(distance, 0.0)


def _slot_activity(
    energies: Sequence[float], start: int, duration: int, threshold: float
) -> tuple[bool, float, float]:
    segment = energies[start : start + duration]
    if len(segment) < max(1, math.ceil(duration * MIN_LAYER_REMAINING_RATIO)):
        return False, 0.0, -120.0
    active_count = sum(energy >= threshold for energy in segment)
    peak = max(segment, default=-120.0)
    active = active_count > 0 or (peak >= threshold - 8.0 and peak >= -52.0)
    return active, active_count / len(segment), peak


def _candidate_bars(
    all_starts: Iterable[float],
    true_zero: float,
    seconds_per_bar: float,
) -> set[int]:
    if seconds_per_bar <= 0:
        return set()
    return {
        round((timestamp - true_zero) / seconds_per_bar)
        for timestamp in all_starts
        if timestamp >= true_zero
    }


def _model_support_candidates(
    energies: Sequence[float],
    all_starts: Iterable[float],
    true_zero: float,
    seconds_per_bar: float,
) -> tuple[float, list[bool], list[tuple[int, int]], frozenset[int]]:
    threshold, active_by_bar = classify_activity(energies)
    ranges = active_ranges(active_by_bar)
    silence_ends = _candidate_bars(all_starts, true_zero, seconds_per_bar)
    range_starts = {start for start, _ in ranges}
    return threshold, active_by_bar, ranges, frozenset(silence_ends | range_starts)


def _initial_full_end(ranges: Sequence[tuple[int, int]]) -> int:
    if ranges and ranges[0][0] == 0:
        return ranges[0][1]
    return 16


def _duration_options(base_layer: int) -> tuple[int, ...]:
    options = []
    duration = base_layer
    while duration <= MAX_LAYER_BARS:
        options.append(duration)
        duration *= 2
    return tuple(options)


def _slot_score(
    energies: Sequence[float],
    threshold: float,
    candidates: frozenset[int],
    start: int,
    duration: int,
) -> tuple[float, bool, float]:
    active, active_fraction, peak = _slot_activity(energies, start, duration, threshold)
    support = _support_strength(start, candidates)
    support_score = (support * 10.0) - (4.0 if support == 0.0 else 0.0)
    leading_inactive = 0
    for energy in energies[start : start + min(4, duration)]:
        if energy >= threshold:
            break
        leading_inactive += 1
    trailing_inactive = 0
    for energy in reversed(energies[start + max(0, duration - 4) : start + duration]):
        if energy >= threshold:
            break
        trailing_inactive += 1
    if active:
        activity_score = 2.0 + min(2.5, active_fraction * 4.0)
        if peak < threshold:
            activity_score -= 1.0
    else:
        # Muted layers are valid structural slots, but should remain exceptional.
        activity_score = -3.0
    edge_penalty = leading_inactive * 1.5
    if support == 0.0:
        edge_penalty += trailing_inactive * 1.25
    return support_score + activity_score - edge_penalty, active, support


def _transition_features(
    energies: Sequence[float],
    threshold: float,
    candidates: frozenset[int],
    start: int,
    duration: int,
    space: int,
    base_layer: int,
) -> _TransitionFeatures:
    layer = energies[start : start + duration]
    gap = energies[start + duration : start + duration + space]
    contrast = _clamp(_mean(layer) - _mean(gap, -80.0), -14.0, 24.0)
    contrast_score = contrast * 0.22
    quiet_fraction = (
        sum(energy < threshold for energy in gap) / len(gap)
        if gap
        else 0.0
    )
    gap_purity_score = (quiet_fraction - 0.5) * 4.0

    duration_multiple = max(1, duration // base_layer)
    duration_penalty = math.log2(duration_multiple) * 3.5
    if duration != base_layer:
        duration_penalty += 1.0
        active_fraction = (
            sum(energy >= threshold for energy in layer) / len(layer)
            if layer
            else 0.0
        )
        duration_penalty += max(0.0, 0.75 - active_fraction) * 16.0
        leading_base = layer[:base_layer]
        leading_base_fraction = (
            sum(energy >= threshold for energy in leading_base) / len(leading_base)
            if leading_base
            else 0.0
        )
        duration_penalty += max(0.0, 0.75 - leading_base_fraction) * 20.0
        second_base = layer[base_layer : base_layer * 2]
        if second_base:
            second_base_fraction = sum(
                energy >= threshold for energy in second_base
            ) / len(second_base)
            duration_penalty += max(0.0, 0.75 - second_base_fraction) * 20.0
            internal_rise = _mean(second_base) - _mean(leading_base)
            duration_penalty += max(0.0, internal_rise - 8.0) * 1.2
        internal_center = start + base_layer
        for internal_start in range(internal_center - 1, internal_center + 3):
            if not (1 <= internal_start < len(energies)):
                continue
            if _support_strength(internal_start, candidates) < 0.62:
                continue
            if energies[internal_start - 1] < threshold <= energies[internal_start]:
                duration_penalty += 12.0
                break
        if _support_strength(start, candidates) == 0.0:
            duration_penalty += 12.0

    next_start = start + duration + space
    next_support = _support_strength(next_start, candidates)
    boundary_penalty = 0.0
    if next_support == 0.0 and contrast < 4.0:
        # Continuous energy and no onset evidence means this is probably the
        # middle of one long layer, not a new slot boundary.
        boundary_penalty = 5.0
    layer_mean = _mean(layer)
    return _TransitionFeatures(
        score=(
        contrast_score
        + gap_purity_score
        + (next_support * 1.5)
        - duration_penalty
        - boundary_penalty
        ),
        layer_mean=layer_mean,
    )


def _transition_score(
    features: _TransitionFeatures,
    threshold: float,
    space: int,
    base_space: int,
) -> float:
    gap_delta = abs(space - base_space)
    gap_penalty = gap_delta * 1.5
    if gap_delta:
        # A one-bar raw onset error is common with tails and reverse swells.  A
        # structural deviation must improve the remainder of the sequence, not
        # just chase one locally stronger silence marker.
        gap_penalty += 9.0
        if gap_delta >= 8 and space % base_space == 0:
            multiple = space // base_space
            repeated_space_penalty = 12.0 + max(0, multiple - 2) * 1.5
            gap_penalty = min(gap_penalty, repeated_space_penalty)

    compressed_weak_slot_penalty = 0.0
    if space < base_space and features.layer_mean < threshold + 8.0:
        # A faint tail followed by an abnormally short gap must not be promoted
        # to a layer just because silencedetect found an event inside it.
        compressed_weak_slot_penalty = 6.0 + (
            threshold + 8.0 - features.layer_mean
        )
    return features.score - gap_penalty - compressed_weak_slot_penalty


def _terminal_score(max_bar: int, start: int, duration: int, base_space: int) -> float:
    layer_end = start + duration
    trailing = max_bar - layer_end
    if trailing < -1:
        return -30.0 - abs(trailing) * 3.0
    if trailing > 8:
        return -18.0 - (trailing - 8) * 2.5
    end_error = min(abs(trailing), abs(trailing - base_space))
    return 9.0 - (end_error * 1.4)


def _refine_terminal_slot(
    slots: tuple[Slot, ...],
    energies: Sequence[float],
    threshold: float,
    candidates: frozenset[int],
    max_bar: int,
    base_space: int,
) -> tuple[Slot, ...]:
    if len(slots) < 2 or not slots[-1].active:
        return slots
    last = slots[-1]
    leading_inactive = 0
    for energy in energies[last.start : last.start + min(4, last.duration)]:
        if energy >= threshold:
            break
        leading_inactive += 1
    current_terminal = _terminal_score(max_bar, last.start, last.duration, base_space)
    current_slot_score = _slot_score(
        energies, threshold, candidates, last.start, last.duration
    )[0]
    best = (current_slot_score + current_terminal, 0, last)
    for shift in range(1, leading_inactive + 1):
        shifted_start = last.start + shift
        if _support_strength(shifted_start, candidates) < 0.62:
            continue
        active, _, _ = _slot_activity(energies, shifted_start, last.duration, threshold)
        if not active:
            continue
        shifted_terminal = _terminal_score(
            max_bar, shifted_start, last.duration, base_space
        )
        if shifted_terminal <= current_terminal:
            continue
        shifted_slot_score, _, shifted_support = _slot_score(
            energies, threshold, candidates, shifted_start, last.duration
        )
        candidate = (
            shifted_slot_score + shifted_terminal,
            shift,
            Slot(shifted_start, last.duration, 0, True, shifted_support),
        )
        if candidate[0] > best[0]:
            best = candidate
    previous = slots[-2]
    current_space = previous.space_after
    for shift_back in range(1, min(3, current_space - 1) + 1):
        shifted_start = last.start - shift_back
        shifted_space = current_space - shift_back
        if _support_strength(shifted_start, candidates) < 0.62:
            continue
        if abs(shifted_space - base_space) >= abs(current_space - base_space):
            continue
        active, _, _ = _slot_activity(energies, shifted_start, last.duration, threshold)
        if not active:
            continue
        shifted_terminal = _terminal_score(
            max_bar, shifted_start, last.duration, base_space
        )
        if shifted_terminal <= current_terminal:
            continue
        shifted_slot_score, _, shifted_support = _slot_score(
            energies, threshold, candidates, shifted_start, last.duration
        )
        regularity_gain = (
            abs(current_space - base_space) - abs(shifted_space - base_space)
        ) * 6.0
        candidate = (
            shifted_slot_score + shifted_terminal + regularity_gain,
            -shift_back,
            Slot(shifted_start, last.duration, 0, True, shifted_support),
        )
        if candidate[0] > best[0]:
            best = candidate
    if best[1] == 0:
        return slots

    extended_space = previous.space_after + best[1]
    if extended_space not in TRANSITION_SPACE_BARS:
        return slots
    adjusted = list(slots)
    adjusted[-2] = Slot(
        previous.start,
        previous.duration,
        extended_space,
        previous.active,
        previous.support,
    )
    adjusted[-1] = best[2]
    return tuple(adjusted)


def _refine_continuous_layers(
    slots: tuple[Slot, ...],
    energies: Sequence[float],
    threshold: float,
    base_layer: int,
    base_space: int,
) -> tuple[Slot, ...]:
    """Extend or merge slots only when the alleged gap stays musically active."""
    refined = list(slots)
    index = 0
    while index + 1 < len(refined):
        current = refined[index]
        following = refined[index + 1]
        if not current.active or not following.active:
            index += 1
            continue

        gap_start = current.start + current.duration
        gap_end = following.start
        if gap_end <= gap_start:
            index += 1
            continue
        gap = energies[gap_start:gap_end]
        leading_active = 0
        for energy in gap:
            if energy < threshold:
                break
            leading_active += 1

        if (
            leading_active == len(gap)
            and current.duration > base_layer
            and current.space_after > 1
        ):
            merged_duration = following.start + following.duration - current.start
            if merged_duration <= MAX_LAYER_BARS:
                refined[index] = Slot(
                    current.start,
                    merged_duration,
                    following.space_after,
                    True,
                    max(current.support, following.support),
                )
                del refined[index + 1]
                continue
        else:
            # Preserve the model's normal gap and only absorb a complete extra
            # base-layer block before it. This avoids extending exports by a
            # single reverb bar at the edge of the real silence.
            extension = len(gap) - base_space
            if extension < base_layer:
                index += 1
                continue
            prefix = gap[:extension]
            if sum(energy >= threshold for energy in prefix) < math.ceil(
                len(prefix) * 0.75
            ):
                index += 1
                continue
            refined[index] = Slot(
                current.start,
                current.duration + extension,
                gap_end - (gap_start + extension),
                current.active,
                current.support,
            )
        index += 1

    for index, slot in enumerate(refined[:-1]):
        following = refined[index + 1]
        refined[index] = Slot(
            slot.start,
            slot.duration,
            max(0, following.start - (slot.start + slot.duration)),
            slot.active,
            slot.support,
        )
    return tuple(refined)


def _snap_delayed_phase_after_tail(
    slots: tuple[Slot, ...],
    energies: Sequence[float],
    threshold: float,
    candidates: frozenset[int],
    base_space: int,
) -> tuple[Slot, ...]:
    """Keep the structural phase when a preceding tail delays the next attack."""
    adjusted = list(slots)
    for index in range(1, len(adjusted)):
        previous = adjusted[index - 1]
        current = adjusted[index]
        expected_start = previous.start + previous.duration + base_space
        delay = current.start - expected_start
        if delay != 1:
            continue
        nominal_end = previous.start + previous.duration
        if not (0 <= nominal_end < len(energies)):
            continue
        # A still-active nominal end indicates a release/reverb tail that has
        # shortened the measurable silence. In that case the later onset must
        # not shift the established musical grid.
        if energies[nominal_end] < threshold:
            continue

        for suffix_index in range(index, len(adjusted)):
            slot = adjusted[suffix_index]
            shifted_start = slot.start - delay
            adjusted[suffix_index] = Slot(
                shifted_start,
                slot.duration,
                slot.space_after,
                slot.active,
                _support_strength(shifted_start, candidates),
            )
        break

    for index, slot in enumerate(adjusted[:-1]):
        following = adjusted[index + 1]
        adjusted[index] = Slot(
            slot.start,
            slot.duration,
            max(0, following.start - (slot.start + slot.duration)),
            slot.active,
            slot.support,
        )
    return tuple(adjusted)


def _decode_from(
    energies: Sequence[float],
    threshold: float,
    candidates: frozenset[int],
    max_bar: int,
    first_start: int,
    base_layer: int,
    base_space: int,
    cache: dict[int, tuple[float, tuple[Slot, ...]] | None] | None = None,
    transition_cache: dict[tuple[int, int, int, int], _TransitionFeatures]
    | None = None,
) -> tuple[float, tuple[Slot, ...]] | None:
    durations = _duration_options(base_layer)
    if cache is None:
        cache = {}
    if transition_cache is None:
        transition_cache = {}

    def solve(start: int) -> tuple[float, tuple[Slot, ...]] | None:
        if start in cache:
            return cache[start]
        best: tuple[float, tuple[Slot, ...]] | None = None
        for duration in durations:
            remaining = max_bar - start
            if remaining + 1 < duration * MIN_LAYER_REMAINING_RATIO:
                continue
            slot_score, active, support = _slot_score(
                energies, threshold, candidates, start, duration
            )

            terminal = slot_score + _terminal_score(max_bar, start, duration, base_space)
            terminal_slot = Slot(start, duration, 0, active, support)
            best = max(best or (float("-inf"), ()), (terminal, (terminal_slot,)), key=lambda x: x[0])

            for space in TRANSITION_SPACE_BARS:
                next_start = start + duration + space
                if next_start <= start or next_start >= max_bar:
                    continue
                tail = solve(next_start)
                if tail is None:
                    continue
                transition_key = (base_layer, start, duration, space)
                features = transition_cache.get(transition_key)
                if features is None:
                    features = _transition_features(
                        energies,
                        threshold,
                        candidates,
                        start,
                        duration,
                        space,
                        base_layer,
                    )
                    transition_cache[transition_key] = features
                transition = _transition_score(
                    features,
                    threshold,
                    space,
                    base_space,
                )
                score = slot_score + transition + tail[0]
                slot = Slot(start, duration, space, active, support)
                candidate = (score, (slot,) + tail[1])
                best = max(best or (float("-inf"), ()), candidate, key=lambda x: x[0])
        cache[start] = best
        return best

    return solve(first_start)


def _sequence_quality(
    raw_score: float,
    slots: Sequence[Slot],
    max_bar: int,
    base_layer: int,
    base_space: int,
    initial_full_end: int | None = None,
    energies: Sequence[float] | None = None,
    activity_threshold: float | None = None,
) -> float:
    if len(slots) < 3:
        return float("-inf")
    active_slots = [slot for slot in slots if slot.active]
    if len(active_slots) < 3:
        return float("-inf")
    coverage = min(1.0, (slots[-1].start + slots[-1].duration - slots[0].start) / max(1, max_bar - slots[0].start))
    active_ratio = len(active_slots) / len(slots)
    mean_support = sum(slot.support for slot in active_slots) / len(active_slots)
    deviations = sum(
        slot.duration != base_layer
        or (slot.space_after not in (0, base_space))
        for slot in slots
    )
    primary_main_end = slots[0].start - base_space
    if primary_main_end % 8 == 0:
        initial_phase_score = 3.0
    elif primary_main_end % 4 == 0:
        initial_phase_score = 1.0
    else:
        initial_phase_score = 0.0
    for initial_space in BASE_SPACE_BARS:
        if (slots[0].start - initial_space) % 8 == 0:
            alternate_score = 2.0 - (abs(initial_space - base_space) * 0.5)
            initial_phase_score = max(initial_phase_score, alternate_score)
    pre_full_mix_penalty = 0.0
    if initial_full_end is not None and slots[0].start < initial_full_end:
        # Usually a start inside the opening active range is still part of the
        # full mix. A sharp upward boundary is the important exception: the
        # activity detector can absorb the first real layer when no full
        # silence separates it from the mix.
        start = slots[0].start
        onset_rise = (
            energies[start] - energies[start - 1]
            if energies is not None and 0 < start < len(energies)
            else 0.0
        )
        penalty_per_bar = 0.10 if onset_rise >= 8.0 else 1.00
        pre_full_mix_penalty = (
            initial_full_end - slots[0].start
        ) * penalty_per_bar
    full_mix_outlier_penalty = 0.0
    ambiguous_first_penalty = 0.0
    if energies is not None and initial_full_end is not None and slots[0].start < initial_full_end:
        active_slots = [slot for slot in slots if slot.active]
        if len(active_slots) >= 4:
            first = active_slots[0]
            first_mean = _mean(energies[first.start : first.start + first.duration])
            later_means = [
                _mean(energies[slot.start : slot.start + slot.duration])
                for slot in active_slots[1:]
            ]
            later_median = _percentile(later_means, 0.50, first_mean)
            full_mix_outlier_penalty = max(0.0, first_mean - later_median - 4.0) * 0.5
        if activity_threshold is not None and slots[0].support == 0.0:
            first_segment = energies[
                slots[0].start : slots[0].start + slots[0].duration
            ]
            ambiguous_first_penalty = sum(
                energy < activity_threshold for energy in first_segment
            )
    # Normalize the additive decoder score so shorter base layers do not win by
    # merely creating more slots.
    normalized = raw_score / math.sqrt(len(slots))
    model_prior = 2.5 if base_layer == 8 else 0.0
    space_prior = 2.0 if base_space in (1, 2, 4, 8) else 0.0
    return (
        normalized
        + mean_support * 7.0
        + active_ratio * 8.0
        + coverage * 5.0
        + model_prior
        + space_prior
        + initial_phase_score
        - deviations * 1.90
        - pre_full_mix_penalty
        - full_mix_outlier_penalty
        - ambiguous_first_penalty
    )


def infer_sequence_grid(
    energies: Sequence[float],
    all_starts: Iterable[float],
    true_zero: float,
    seconds_per_bar: float,
    source_duration: float,
) -> SequenceResult | None:
    """Infer a regularized but locally variable layer sequence."""
    if not energies or seconds_per_bar <= 0:
        return None

    threshold, _, ranges, support_candidates = _model_support_candidates(
        energies, all_starts, true_zero, seconds_per_bar
    )
    max_bar = int(source_duration / seconds_per_bar) if source_duration else len(energies)
    full_end = _initial_full_end(ranges)
    first_min = max(16, full_end - 16)
    first_max = min(max_bar - 1, full_end + 12)

    results: list[tuple[float, int, int, int, tuple[Slot, ...]]] = []
    transition_cache: dict[
        tuple[int, int, int, int], _TransitionFeatures
    ] = {}
    for base_layer in BASE_LAYER_BARS:
        for base_space in BASE_SPACE_BARS:
            model_cache: dict[int, tuple[float, tuple[Slot, ...]] | None] = {}
            for first_start in range(first_min, first_max + 1):
                decoded = _decode_from(
                    energies,
                    threshold,
                    support_candidates,
                    max_bar,
                    first_start,
                    base_layer,
                    base_space,
                    model_cache,
                    transition_cache,
                )
                if decoded is None:
                    continue
                raw_score, slots = decoded
                quality = _sequence_quality(
                    raw_score,
                    slots,
                    max_bar,
                    base_layer,
                    base_space,
                    full_end,
                    energies,
                    threshold,
                )
                if math.isfinite(quality):
                    results.append((quality, first_start, base_layer, base_space, slots))

    if not results:
        return None
    results.sort(key=lambda item: item[0], reverse=True)
    quality, first_start, base_layer, base_space, slots = results[0]
    runner_up = results[1][0] if len(results) > 1 else quality
    slots = _refine_terminal_slot(
        slots,
        energies,
        threshold,
        support_candidates,
        max_bar,
        base_space,
    )
    slots = _snap_delayed_phase_after_tail(
        slots, energies, threshold, support_candidates, base_space
    )
    slots = _refine_continuous_layers(
        slots, energies, threshold, base_layer, base_space
    )
    return SequenceResult(
        score=quality,
        confidence_margin=quality - runner_up,
        base_layer_bars=base_layer,
        base_space_bars=base_space,
        first_start=first_start,
        slots=slots,
    )
