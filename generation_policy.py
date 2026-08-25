"""Seeded uniform layer selection policy for the Generate prototype.

The policy deliberately knows nothing about Qt, MERT, SQLite, or audio I/O.  It
accepts small immutable records and returns a reproducible plan that a renderer
can execute.  Manual labels always override model predictions; transformation
distance never changes a safe candidate's chance of being selected.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from key_confidence import (
    DEFAULT_KEY_MARGIN_THRESHOLD,
    KEY_STATUS_CONFLICT,
    KEY_STATUS_SAFE,
    KEY_STATUS_UNAVAILABLE,
    KEY_STATUS_UNCERTAIN,
)


PITCH_CLASSES = {
    "C": 0,
    "B#": 0,
    "C#": 1,
    "DB": 1,
    "D": 2,
    "D#": 3,
    "EB": 3,
    "E": 4,
    "FB": 4,
    "E#": 5,
    "F": 5,
    "F#": 6,
    "GB": 6,
    "G": 7,
    "G#": 8,
    "AB": 8,
    "A": 9,
    "A#": 10,
    "BB": 10,
    "B": 11,
    "CB": 11,
}

_CANONICAL_TONICS = (
    "C",
    "C#",
    "D",
    "D#",
    "E",
    "F",
    "F#",
    "G",
    "G#",
    "A",
    "A#",
    "B",
)

DEFAULT_KEYLESS_LABELS = frozenset({"percussion"})


class GenerationPolicyError(ValueError):
    """Base class for invalid requests and impossible selections."""


class SelectionError(GenerationPolicyError):
    """Raised when at least one requested recipe slot cannot be filled."""

    def __init__(self, message: str, *, slot_index: int | None = None, category: str | None = None):
        super().__init__(message)
        self.slot_index = slot_index
        self.category = category


@dataclass(frozen=True)
class KeySignature:
    """An exact tonic/mode label with a shared relative-key family."""

    tonic: str
    mode: str
    pitch_class: int

    @property
    def canonical(self) -> str:
        return f"{self.tonic} {self.mode}"

    @property
    def family_pitch_class(self) -> int:
        """Return the relative-minor tonic representing this key family."""

        if self.mode == "minor":
            return self.pitch_class
        return (self.pitch_class - 3) % 12


def parse_exact_key(value: str, mode: str | None = None) -> KeySignature:
    """Parse an exact key such as ``A minor`` or ``F#m``.

    Relative-pair UI values such as ``C major / A minor`` are intentionally
    rejected: Generate must send every pitched layer to one exact tonic+mode.
    A bare tonic is accepted only when ``mode`` is supplied separately.
    """

    text = str(value or "").strip().replace("♯", "#").replace("♭", "b")
    if not text:
        raise GenerationPolicyError("An exact target key and mode are required")
    if "/" in text:
        raise GenerationPolicyError(
            "Relative key pairs are not exact targets; choose one major or minor key"
        )

    explicit_mode = str(mode or "").strip().lower() or None
    match = re.fullmatch(
        r"([A-Ga-g](?:#|b)?)(?:(m)|\s+(major|minor))?",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        raise GenerationPolicyError(f"Unsupported musical key: {value!r}")

    tonic_token = match.group(1)
    compact_minor = bool(match.group(2))
    written_mode = match.group(3).lower() if match.group(3) else None
    parsed_mode = "minor" if compact_minor else written_mode
    if explicit_mode not in (None, "major", "minor"):
        raise GenerationPolicyError(f"Unsupported musical mode: {mode!r}")
    if parsed_mode and explicit_mode and parsed_mode != explicit_mode:
        raise GenerationPolicyError(
            f"Conflicting musical modes in {value!r} and {mode!r}"
        )
    final_mode = parsed_mode or explicit_mode
    if final_mode not in ("major", "minor"):
        raise GenerationPolicyError(f"A major/minor mode is required for {value!r}")

    token = tonic_token.upper()
    if token not in PITCH_CLASSES:
        raise GenerationPolicyError(f"Unsupported musical tonic: {tonic_token!r}")
    pitch_class = PITCH_CLASSES[token]
    return KeySignature(_CANONICAL_TONICS[pitch_class], final_mode, pitch_class)


def shortest_semitone_shift(source: KeySignature, target: KeySignature) -> int:
    """Return the shortest shift between relative-key families.

    Major keys and their relative minors share the same pitch classes, so
    ``C major`` and ``A minor`` deliberately require no transposition.
    """

    delta = (target.family_pitch_class - source.family_pitch_class) % 12
    return delta - 12 if delta > 6 else delta


def _normalise_label(value: str | None) -> str | None:
    if value is None:
        return None
    result = " ".join(str(value).strip().split()).casefold()
    return result or None


def _record_value(record: object, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(record, Mapping) and name in record:
            return record[name]
        if hasattr(record, name):
            return getattr(record, name)
    return default


@dataclass(frozen=True)
class LayerCandidate:
    """Minimum metadata needed by the generation policy."""

    identity: str
    path: Path
    source_loop_id: str
    source_bpm: float
    source_key: str | None
    source_mode: str | None = None
    bars: float | None = 8.0
    manual_label: str | None = None
    predicted_label: str | None = None
    prediction_confidence: float | None = None
    key_sensitive: bool = True
    scanned_key: str | None = None
    scanned_mode: str | None = None
    alternate_scanned_key: str | None = None
    alternate_scanned_mode: str | None = None
    key_top1_probability: float | None = None
    key_top2_probability: float | None = None
    key_confidence_margin: float | None = None
    key_confidence_status: str = KEY_STATUS_UNAVAILABLE

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))
        if not str(self.identity).strip():
            raise GenerationPolicyError("A layer identity is required")
        if not str(self.source_loop_id).strip():
            raise GenerationPolicyError(f"A source loop id is required for {self.identity!r}")
        if not math.isfinite(float(self.source_bpm)) or float(self.source_bpm) <= 0:
            raise GenerationPolicyError(f"A positive source BPM is required for {self.identity!r}")
        confidence = self.prediction_confidence
        if confidence is not None and not 0.0 <= float(confidence) <= 1.0:
            raise GenerationPolicyError(
                f"Prediction confidence must be between 0 and 1 for {self.identity!r}"
            )
        if self.bars is not None and (
            not math.isfinite(float(self.bars)) or float(self.bars) <= 0
        ):
            raise GenerationPolicyError(f"Layer bars must be positive for {self.identity!r}")
        status = str(self.key_confidence_status or KEY_STATUS_UNAVAILABLE).casefold()
        if status not in {
            KEY_STATUS_SAFE,
            KEY_STATUS_UNCERTAIN,
            KEY_STATUS_CONFLICT,
            KEY_STATUS_UNAVAILABLE,
        }:
            raise GenerationPolicyError(
                f"Unknown key confidence status for {self.identity!r}: {status!r}"
            )
        object.__setattr__(self, "key_confidence_status", status)
        if self.key_confidence_margin is not None:
            margin = float(self.key_confidence_margin)
            if not math.isfinite(margin) or not 0.0 <= margin <= 1.0:
                raise GenerationPolicyError(
                    f"Key confidence margin must be between 0 and 1 for {self.identity!r}"
                )
            object.__setattr__(self, "key_confidence_margin", margin)

    @classmethod
    def from_record(
        cls,
        record: object,
        *,
        keyless_labels: Iterable[str] = DEFAULT_KEYLESS_LABELS,
    ) -> "LayerCandidate":
        """Adapt a ``layer_library.LayerRecord`` or a mapping without coupling.

        ``LayerRecord`` stores tonic and mode separately.  Bar count is derived
        from duration and BPM when it is not explicitly present.
        """

        raw_path = _record_value(record, "path")
        if not raw_path:
            raise GenerationPolicyError("Layer record has no path")
        path = Path(raw_path)
        identity = str(
            _record_value(
                record,
                "identity",
                "sha256",
                "relative_path",
                default=str(path),
            )
        )
        source_loop_id = str(
            _record_value(record, "source_loop_id", default=path.parent.name or identity)
        )
        bpm = _record_value(record, "source_bpm", "bpm")
        if bpm is None:
            raise GenerationPolicyError(f"Layer record has no BPM: {path}")

        manual_label = _record_value(record, "manual_label")
        predicted_label = _record_value(record, "predicted_label")
        confidence = _record_value(
            record,
            "prediction_confidence",
            "confidence",
        )
        label = manual_label or predicted_label
        explicit_key_sensitive = _record_value(record, "key_sensitive")
        if explicit_key_sensitive is None:
            keyless = {_normalise_label(item) for item in keyless_labels}
            key_sensitive = _normalise_label(label) not in keyless
        else:
            key_sensitive = bool(explicit_key_sensitive)

        bars = _record_value(record, "bars")
        if bars is None:
            duration = _record_value(record, "duration_seconds", "duration")
            if duration is not None:
                bars = float(duration) * float(bpm) / 240.0

        return cls(
            identity=identity,
            path=path,
            source_loop_id=source_loop_id,
            source_bpm=float(bpm),
            source_key=_record_value(record, "source_key", "key"),
            source_mode=_record_value(record, "source_mode", "mode"),
            bars=float(bars) if bars is not None else None,
            manual_label=manual_label,
            predicted_label=predicted_label,
            prediction_confidence=float(confidence) if confidence is not None else None,
            key_sensitive=key_sensitive,
            scanned_key=_record_value(record, "scanned_key"),
            scanned_mode=_record_value(record, "scanned_mode"),
            alternate_scanned_key=_record_value(
                record, "alternate_scanned_key"
            ),
            alternate_scanned_mode=_record_value(
                record, "alternate_scanned_mode"
            ),
            key_top1_probability=_record_value(
                record, "key_top1_probability"
            ),
            key_top2_probability=_record_value(
                record, "key_top2_probability"
            ),
            key_confidence_margin=_record_value(record, "key_confidence_margin"),
            key_confidence_status=str(
                _record_value(
                    record,
                    "key_confidence_status",
                    default=KEY_STATUS_UNAVAILABLE,
                )
                or KEY_STATUS_UNAVAILABLE
            ),
        )

    def resolved_label(self) -> tuple[str | None, str | None, float | None]:
        """Return ``(label, source, confidence)`` with manual truth first."""

        manual = _normalise_label(self.manual_label)
        if manual:
            return manual, "manual", 1.0
        predicted = _normalise_label(self.predicted_label)
        if predicted:
            return predicted, "prediction", self.prediction_confidence
        return None, None, None

    def source_signature(self) -> KeySignature:
        source_key = self.scanned_key or self.source_key
        source_mode = self.scanned_mode or self.source_mode
        if not source_key:
            raise GenerationPolicyError(f"No source key for pitched layer {self.identity!r}")
        return parse_exact_key(source_key, source_mode)

    def alternate_source_signature(self) -> KeySignature:
        if not self.alternate_scanned_key:
            raise GenerationPolicyError(
                f"No alternate source key for pitched layer {self.identity!r}"
            )
        return parse_exact_key(
            self.alternate_scanned_key,
            self.alternate_scanned_mode,
        )


@dataclass(frozen=True)
class GenerationRequest:
    """A complete generation recipe.

    Repeated strings in ``categories`` are separate recipe slots, so
    ``("Lead", "Lead", "Counter")`` requests two distinct lead layers.
    """

    categories: tuple[str, ...]
    target_bpm: float
    target_key: str
    bars: int = 8
    seed: int = 0
    key_confidence_threshold: float = DEFAULT_KEY_MARGIN_THRESHOLD
    bars_tolerance: float = 0.20
    max_layers_per_source_loop: int = 2
    excluded_identities: frozenset[str] = frozenset()
    locked_identities_by_slot: tuple[str | None, ...] = ()

    def __post_init__(self) -> None:
        categories = tuple(" ".join(str(item).strip().split()) for item in self.categories)
        if not categories or any(not item for item in categories):
            raise GenerationPolicyError("At least one non-empty recipe category is required")
        object.__setattr__(self, "categories", categories)
        if not math.isfinite(float(self.target_bpm)) or float(self.target_bpm) <= 0:
            raise GenerationPolicyError("A positive target BPM is required")
        parse_exact_key(self.target_key)
        if int(self.bars) <= 0:
            raise GenerationPolicyError("Generation bars must be positive")
        if not 0.0 <= float(self.key_confidence_threshold) <= 1.0:
            raise GenerationPolicyError(
                "Key confidence threshold must be between 0 and 1"
            )
        if float(self.bars_tolerance) < 0:
            raise GenerationPolicyError("Bar tolerance cannot be negative")
        if int(self.max_layers_per_source_loop) <= 0:
            raise GenerationPolicyError(
                "Maximum layers per source loop must be positive"
            )
        excluded_identities = frozenset(
            str(identity).strip() for identity in self.excluded_identities
        )
        if any(not identity for identity in excluded_identities):
            raise GenerationPolicyError("Excluded layer identities cannot be empty")
        object.__setattr__(self, "excluded_identities", excluded_identities)
        raw_locked = tuple(self.locked_identities_by_slot)
        if not raw_locked:
            raw_locked = (None,) * len(categories)
        if len(raw_locked) != len(categories):
            raise GenerationPolicyError(
                "Locked layer slots must have the same length as the recipe"
            )
        locked = tuple(
            str(identity).strip() if identity is not None else None
            for identity in raw_locked
        )
        if any(identity == "" for identity in locked):
            raise GenerationPolicyError("Locked layer identities cannot be empty")
        locked_values = [identity for identity in locked if identity is not None]
        if len(locked_values) != len(set(locked_values)):
            raise GenerationPolicyError(
                "The same layer identity cannot be locked into multiple slots"
            )
        object.__setattr__(self, "locked_identities_by_slot", locked)

    @property
    def target_signature(self) -> KeySignature:
        return parse_exact_key(self.target_key)


@dataclass(frozen=True)
class SelectedLayer:
    slot_index: int
    category: str
    candidate: LayerCandidate
    label_source: str
    confidence: float
    semitones: int
    speed_ratio: float
    transform_cost: float
    selection_score: float
    reused_source_loop: bool
    source_key_rank: int = 1
    manual_pitch_semitones: int = 0
    normalization_enabled: bool = False


@dataclass(frozen=True)
class GenerationPlan:
    request: GenerationRequest
    selections: tuple[SelectedLayer, ...]

    @property
    def target_key(self) -> str:
        return self.request.target_signature.canonical


def selected_source_signature(selection: SelectedLayer) -> KeySignature:
    """Return the immutable Top 1 or Top 2 signature selected for a layer."""

    if selection.source_key_rank == 1:
        return selection.candidate.source_signature()
    if selection.source_key_rank == 2:
        return selection.candidate.alternate_source_signature()
    raise GenerationPolicyError(
        f"Unsupported source-key rank: {selection.source_key_rank}"
    )


def _updated_transform_cost(selection: SelectedLayer, semitones: int) -> float:
    tempo_distance = abs(12.0 * math.log2(selection.speed_ratio))
    return tempo_distance + 0.35 * abs(int(semitones))


def plan_with_source_key_rank(
    plan: GenerationPlan,
    *,
    slot_index: int,
    identity: str,
    source_key_rank: int,
) -> GenerationPlan:
    """Use Top 1 or Top 2 for one layer without mutating either analysis.

    Selection, tempo, recipe, seed, manual octave and normalization state stay
    untouched.  ``LayerCandidate`` remains the immutable source of both key
    hypotheses so Top 1 can always be restored exactly.
    """

    requested_rank = int(source_key_rank)
    if requested_rank not in (1, 2):
        raise GenerationPolicyError("Source-key rank must be 1 or 2")

    updated: list[SelectedLayer] = []
    matched = False
    for selection in plan.selections:
        if selection.candidate.identity != str(identity):
            updated.append(selection)
            continue
        if not selection.candidate.key_sensitive:
            raise GenerationPolicyError(
                "This layer category does not use key transposition"
            )
        if selection.source_key_rank == requested_rank:
            raise GenerationPolicyError(
                f"This layer is already using source-key rank {requested_rank}"
            )
        source_signature = (
            selection.candidate.source_signature()
            if requested_rank == 1
            else selection.candidate.alternate_source_signature()
        )
        semitones = shortest_semitone_shift(
            source_signature,
            plan.request.target_signature,
        ) + int(selection.manual_pitch_semitones)
        updated.append(
            replace(
                selection,
                semitones=semitones,
                transform_cost=_updated_transform_cost(selection, semitones),
                source_key_rank=requested_rank,
            )
        )
        matched = True
    if not matched:
        raise GenerationPolicyError(
            f"No selected layer exists at slot {int(slot_index) + 1}"
        )
    return GenerationPlan(request=plan.request, selections=tuple(updated))


def plan_with_alternate_key(
    plan: GenerationPlan,
    *,
    slot_index: int,
    identity: str,
) -> GenerationPlan:
    """Compatibility wrapper selecting the second key hypothesis."""

    return plan_with_source_key_rank(
        plan,
        slot_index=slot_index,
        identity=identity,
        source_key_rank=2,
    )


def plan_with_manual_pitch(
    plan: GenerationPlan,
    *,
    slot_index: int,
    identity: str,
    semitones: int,
) -> GenerationPlan:
    """Set one layer's optional octave shift to -12, 0 or +12."""

    requested_pitch = int(semitones)
    if requested_pitch not in (-12, 0, 12):
        raise GenerationPolicyError("Manual pitch must be -12, 0 or +12 semitones")

    updated: list[SelectedLayer] = []
    matched = False
    for selection in plan.selections:
        if selection.candidate.identity != str(identity):
            updated.append(selection)
            continue
        if selection.manual_pitch_semitones == requested_pitch:
            raise GenerationPolicyError(
                f"This layer is already using a {requested_pitch:+d}-semitone shift"
            )
        base_semitones = 0
        if selection.candidate.key_sensitive:
            base_semitones = shortest_semitone_shift(
                selected_source_signature(selection),
                plan.request.target_signature,
            )
        total_semitones = base_semitones + requested_pitch
        updated.append(
            replace(
                selection,
                semitones=total_semitones,
                transform_cost=_updated_transform_cost(
                    selection,
                    total_semitones,
                ),
                manual_pitch_semitones=requested_pitch,
            )
        )
        matched = True
    if not matched:
        raise GenerationPolicyError(
            f"No selected layer exists at slot {int(slot_index) + 1}"
        )
    return GenerationPlan(request=plan.request, selections=tuple(updated))


def plan_with_normalization(
    plan: GenerationPlan,
    *,
    slot_index: int,
    identity: str,
    enabled: bool,
) -> GenerationPlan:
    """Enable or disable optional peak normalization for exactly one layer."""

    requested_state = bool(enabled)
    updated: list[SelectedLayer] = []
    matched = False
    for selection in plan.selections:
        if selection.candidate.identity != str(identity):
            updated.append(selection)
            continue
        if selection.normalization_enabled == requested_state:
            raise GenerationPolicyError(
                "This layer already uses the requested normalization state"
            )
        updated.append(
            replace(selection, normalization_enabled=requested_state)
        )
        matched = True
    if not matched:
        raise GenerationPolicyError(
            f"No selected layer exists at slot {int(slot_index) + 1}"
        )
    return GenerationPlan(request=plan.request, selections=tuple(updated))


@dataclass(frozen=True)
class _Option:
    candidate: LayerCandidate
    label_source: str
    confidence: float
    semitones: int
    speed_ratio: float
    transform_cost: float
    score: float
    key_pool_priority: int


def _stable_noise(seed: int, slot_index: int, identity: str) -> float:
    digest = hashlib.sha256(f"{seed}\0{slot_index}\0{identity}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(2**64 - 1)


def _option_for_slot(
    candidate: LayerCandidate,
    *,
    slot_index: int,
    category: str,
    request: GenerationRequest,
) -> _Option | None:
    resolved_label, label_source, confidence = candidate.resolved_label()
    if resolved_label != _normalise_label(category):
        return None

    key_status = candidate.key_confidence_status
    if key_status == KEY_STATUS_CONFLICT:
        return None
    key_pool_priority = 0
    if candidate.key_sensitive:
        margin = candidate.key_confidence_margin
        if (
            key_status in {KEY_STATUS_UNCERTAIN, KEY_STATUS_UNAVAILABLE}
            or margin is None
            or margin < request.key_confidence_threshold
        ):
            # This is a reserve pool, not a lower weighted chance.  Reserve
            # candidates are considered only when a recipe cannot be completed
            # from safe candidates after previous-generation exclusions.
            key_pool_priority = 1

    if candidate.bars is None or abs(float(candidate.bars) - request.bars) > request.bars_tolerance:
        return None

    speed_ratio = float(request.target_bpm) / float(candidate.source_bpm)

    semitones = 0
    if candidate.key_sensitive:
        try:
            source_signature = candidate.source_signature()
        except GenerationPolicyError:
            return None
        target_signature = request.target_signature
        semitones = shortest_semitone_shift(source_signature, target_signature)

    # Tempo distance is expressed in equivalent semitones: doubling/halving
    # tempo costs 12.  Pitch is already in semitones.
    tempo_distance = abs(12.0 * math.log2(speed_ratio))
    # Diagnostic only: this value is written to the manifest but never takes
    # part in eligibility or ranking.
    transform_cost = tempo_distance + 0.35 * abs(semitones)
    # BPM distance, pitch distance and label confidence deliberately have zero
    # ranking influence.  Once a candidate is eligible, its random rank is
    # symmetric with every other candidate in the same key-confidence pool.
    score = _stable_noise(request.seed, slot_index, candidate.identity)
    return _Option(
        candidate=candidate,
        label_source=str(label_source),
        confidence=float(confidence) if confidence is not None else 0.0,
        semitones=semitones,
        speed_ratio=speed_ratio,
        transform_cost=transform_cost,
        score=score,
        key_pool_priority=key_pool_priority,
    )


def select_generation(
    candidates: Iterable[LayerCandidate | object],
    request: GenerationRequest,
) -> GenerationPlan:
    """Select one distinct layer per recipe slot with uniform random ranks.

    Safe-key candidates are exhausted before the uncertain reserve pool is
    opened.  Inside either pool, BPM distance, pitch distance and classifier
    confidence do not rank candidates.  Every candidate receives only a
    deterministic pseudo-random rank from the request seed.
    """

    adapted = tuple(
        item if isinstance(item, LayerCandidate) else LayerCandidate.from_record(item)
        for item in candidates
    )
    # Stable ordering makes results independent of filesystem/database order.
    adapted = tuple(sorted(adapted, key=lambda item: (item.identity, str(item.path))))
    candidate_identities = {candidate.identity for candidate in adapted}
    locked_identities = {
        identity
        for identity in request.locked_identities_by_slot
        if identity is not None
    }

    options_by_slot: list[list[_Option]] = []
    for slot_index, category in enumerate(request.categories):
        eligible_options = [
            option
            for candidate in adapted
            if (
                option := _option_for_slot(
                    candidate,
                    slot_index=slot_index,
                    category=category,
                    request=request,
                )
            )
            is not None
        ]
        locked_identity = request.locked_identities_by_slot[slot_index]
        if locked_identity is not None:
            if locked_identity not in candidate_identities:
                raise SelectionError(
                    (
                        f"Locked layer for slot {slot_index + 1}: {category} "
                        "is no longer present in the active library"
                    ),
                    slot_index=slot_index,
                    category=category,
                )
            options = [
                option
                for option in eligible_options
                if option.candidate.identity == locked_identity
            ]
            if not options:
                raise SelectionError(
                    (
                        f"Locked layer for slot {slot_index + 1}: {category} "
                        "is incompatible with the current category, key or duration"
                    ),
                    slot_index=slot_index,
                    category=category,
                )
        else:
            options = [
                option
                for option in eligible_options
                if (
                    option.candidate.identity not in request.excluded_identities
                    and option.candidate.identity not in locked_identities
                )
            ]
        options.sort(
            key=lambda option: (
                option.key_pool_priority,
                option.score,
                option.candidate.identity,
            )
        )
        if not options:
            if eligible_options:
                raise SelectionError(
                    (
                        f"No alternative layer for slot {slot_index + 1}: {category}; "
                        "all eligible layers were used in the previous generation"
                    ),
                    slot_index=slot_index,
                    category=category,
                )
            raise SelectionError(
                f"No eligible layer for slot {slot_index + 1}: {category}",
                slot_index=slot_index,
                category=category,
            )
        options_by_slot.append(options)

    selected_options: dict[int, _Option] = {}
    used_identities: set[str] = set()
    loop_use_counts: dict[str, int] = {}

    # Constrained slots are solved first for efficient backtracking.  The
    # original slot indexes are preserved in the returned plan.
    slot_order = sorted(
        range(len(options_by_slot)),
        key=lambda index: (
            request.locked_identities_by_slot[index] is None,
            sum(option.key_pool_priority == 0 for option in options_by_slot[index]),
            len(options_by_slot[index]),
            index,
        ),
    )

    def assign(
        offset: int,
        *,
        reserve_used: int,
        reserve_limit: int,
    ) -> bool:
        if offset >= len(slot_order):
            return True
        slot_index = slot_order[offset]
        for option in options_by_slot[slot_index]:
            proposed_reserve = reserve_used + option.key_pool_priority
            if proposed_reserve > reserve_limit:
                continue
            identity = option.candidate.identity
            loop_id = option.candidate.source_loop_id
            if identity in used_identities:
                continue
            if (
                loop_use_counts.get(loop_id, 0)
                >= request.max_layers_per_source_loop
            ):
                continue
            selected_options[slot_index] = option
            used_identities.add(identity)
            loop_use_counts[loop_id] = loop_use_counts.get(loop_id, 0) + 1
            if assign(
                offset + 1,
                reserve_used=proposed_reserve,
                reserve_limit=reserve_limit,
            ):
                return True
            del selected_options[slot_index]
            used_identities.remove(identity)
            remaining = loop_use_counts[loop_id] - 1
            if remaining:
                loop_use_counts[loop_id] = remaining
            else:
                del loop_use_counts[loop_id]
        return False

    # Every slot without a safe-key option necessarily consumes one reserve.
    # Starting below that lower bound can never succeed and causes explosive
    # backtracking on legacy catalogues whose key confidence is unavailable.
    minimum_reserve_limit = sum(
        not any(option.key_pool_priority == 0 for option in options)
        for options in options_by_slot
    )
    assigned = False
    for reserve_limit in range(minimum_reserve_limit, len(request.categories) + 1):
        selected_options.clear()
        used_identities.clear()
        loop_use_counts.clear()
        if assign(0, reserve_used=0, reserve_limit=reserve_limit):
            assigned = True
            break
    if not assigned:
        raise SelectionError(
            "Not enough distinct layers to fill the recipe without using "
            f"more than {request.max_layers_per_source_loop} from one source loop"
        )

    selections = tuple(
        SelectedLayer(
            slot_index=slot_index,
            category=request.categories[slot_index],
            candidate=selected_options[slot_index].candidate,
            label_source=selected_options[slot_index].label_source,
            confidence=selected_options[slot_index].confidence,
            semitones=selected_options[slot_index].semitones,
            speed_ratio=selected_options[slot_index].speed_ratio,
            transform_cost=selected_options[slot_index].transform_cost,
            selection_score=selected_options[slot_index].score,
            reused_source_loop=loop_use_counts[
                selected_options[slot_index].candidate.source_loop_id
            ]
            > 1,
        )
        for slot_index in range(len(request.categories))
    )
    return GenerationPlan(request=request, selections=selections)
