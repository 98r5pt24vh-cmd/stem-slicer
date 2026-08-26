"""Precomputed source-loop key confidence for the Generate prototype.

The experimental library contains extracted layers, while the confidence lab
analysed each original full loop once.  This module joins those results back to
the layer source names without re-analysing every layer during a library scan.

The margin is a model score gap, not a calibrated probability of correctness.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import unicodedata


DEFAULT_KEY_MARGIN_THRESHOLD = 0.22
KEY_STATUS_SAFE = "safe"
KEY_STATUS_UNCERTAIN = "uncertain"
KEY_STATUS_CONFLICT = "conflict"
KEY_STATUS_UNAVAILABLE = "unavailable"
KEY_STATUSES = frozenset(
    {
        KEY_STATUS_SAFE,
        KEY_STATUS_UNCERTAIN,
        KEY_STATUS_CONFLICT,
        KEY_STATUS_UNAVAILABLE,
    }
)

_PITCH_CLASSES = {
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
_KEY_RE = re.compile(
    r"(?ix)^\s*([a-g](?:[#♯b♭])?)(?:(m)|[\s_-]*(major|maj|minor|min))?\s*$"
)


def _normalised_source(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("_", " ").replace("-", " ")
    return " ".join(text.casefold().split())


def _source_aliases(value: str) -> set[str]:
    """Return strict aliases for the one known optional producer suffix.

    Corpus truth rows predate the consolidated library and sometimes store
    ``PRAGMATIC 149`` while the actual layer stem is
    ``A#m PRAGMATIC 149 +NRGY``. This is a deterministic name convention, not
    fuzzy matching.
    """

    normalized = _normalised_source(value)
    aliases = {normalized}
    if normalized.endswith(" +nrgy"):
        aliases.add(normalized[: -len(" +nrgy")].rstrip())
    return {alias for alias in aliases if alias}


def _signature(key: str | None, mode: str | None = None) -> tuple[int, str] | None:
    if not key:
        return None
    text = str(key).replace("♯", "#").replace("♭", "b")
    match = _KEY_RE.fullmatch(text)
    if not match:
        return None
    token = match.group(1).upper()
    pitch_class = _PITCH_CLASSES.get(token)
    if pitch_class is None:
        return None
    compact_minor = bool(match.group(2))
    written_mode = (match.group(3) or "").casefold()
    parsed_mode = (
        "minor"
        if compact_minor or written_mode in {"minor", "min"}
        else "major" if written_mode in {"major", "maj"} else None
    )
    supplied_mode = str(mode or "").strip().casefold() or None
    if supplied_mode not in (None, "major", "minor"):
        return None
    final_mode = parsed_mode or supplied_mode
    if final_mode not in ("major", "minor"):
        return None
    return pitch_class, final_mode


def _display_parts(key: str) -> tuple[str, str]:
    signature = _signature(key)
    if signature is None:
        raise ValueError(f"Unsupported scanned key: {key!r}")
    pitch_class, mode = signature
    return _CANONICAL_TONICS[pitch_class], mode


def _relative_family(signature: tuple[int, str]) -> int:
    """Return the relative-minor tonic shared by one major/minor family."""

    pitch_class, mode = signature
    return pitch_class if mode == "minor" else (pitch_class - 3) % 12


def classify_key_confidence_status(
    *,
    filename_key: str | None,
    filename_mode: str | None,
    scanned_key: str,
    scanned_mode: str,
    margin: float,
    threshold: float = DEFAULT_KEY_MARGIN_THRESHOLD,
) -> str:
    """Classify one precomputed analysis against the current filename key.

    The audio analysis may safely follow an exact-content SHA-256 match after
    a file is copied or relocated.  Its status must still be recalculated,
    because the destination filename may advertise a different key.
    """

    filename_signature = _signature(filename_key, filename_mode)
    scanned_signature = _signature(scanned_key, scanned_mode)
    if (
        filename_signature is None
        or scanned_signature is None
        or _relative_family(filename_signature)
        != _relative_family(scanned_signature)
    ):
        return KEY_STATUS_CONFLICT
    if float(margin) < float(threshold):
        return KEY_STATUS_UNCERTAIN
    return KEY_STATUS_SAFE


@dataclass(frozen=True)
class KeyConfidenceMatch:
    source_loop_id: str
    scanned_key: str
    scanned_mode: str
    alternate_scanned_key: str | None
    alternate_scanned_mode: str | None
    top1_probability: float | None
    top2_probability: float | None
    margin: float
    status: str
    analyzer_id: str


@dataclass(frozen=True)
class _LoopConfidence:
    source_loop_id: str
    scanned_key: str
    scanned_mode: str
    alternate_scanned_key: str | None
    alternate_scanned_mode: str | None
    top1_probability: float | None
    top2_probability: float | None
    margin: float
    analyzer_id: str


class KeyConfidenceIndex:
    """Immutable name index over precomputed original-loop key analyses."""

    def __init__(
        self,
        aliases: dict[str, _LoopConfidence] | None = None,
        *,
        threshold: float = DEFAULT_KEY_MARGIN_THRESHOLD,
        enabled: bool = False,
    ) -> None:
        self._aliases = dict(aliases or {})
        self.threshold = float(threshold)
        self.enabled = bool(enabled)

    @classmethod
    def from_files(
        cls,
        *,
        library_root: Path,
        inventory_path: Path,
        results_path: Path,
        threshold: float = DEFAULT_KEY_MARGIN_THRESHOLD,
    ) -> "KeyConfidenceIndex":
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        results_payload = json.loads(results_path.read_text(encoding="utf-8"))
        declared_root = Path(str(inventory.get("layers_root", ""))).expanduser()
        if declared_root.resolve(strict=False) != Path(library_root).resolve(strict=False):
            return cls(threshold=threshold, enabled=False)

        analyzer_id = str(results_payload.get("scanner_id") or "unknown-key-analyzer")
        by_source: dict[str, _LoopConfidence] = {}
        for item in results_payload.get("results", ()):
            if item.get("status") != "success":
                continue
            source_loop_id = str(item.get("source_loop_id") or "").strip()
            if not source_loop_id:
                continue
            scanned_key, scanned_mode = _display_parts(str(item["top1_key"]))
            raw_alternate_key = item.get("top2_key")
            if raw_alternate_key:
                alternate_scanned_key, alternate_scanned_mode = _display_parts(
                    str(raw_alternate_key)
                )
            else:
                alternate_scanned_key = None
                alternate_scanned_mode = None
            by_source[source_loop_id] = _LoopConfidence(
                source_loop_id=source_loop_id,
                scanned_key=scanned_key,
                scanned_mode=scanned_mode,
                alternate_scanned_key=alternate_scanned_key,
                alternate_scanned_mode=alternate_scanned_mode,
                top1_probability=(
                    float(item["top1_probability"])
                    if item.get("top1_probability") is not None
                    else None
                ),
                top2_probability=(
                    float(item["top2_probability"])
                    if item.get("top2_probability") is not None
                    else None
                ),
                margin=float(item["top1_top2_margin"]),
                analyzer_id=analyzer_id,
            )

        aliases: dict[str, _LoopConfidence] = {}
        for entry in inventory.get("entries", ()):
            source_loop_id = str(entry.get("source_loop_id") or "")
            confidence = by_source.get(source_loop_id)
            if confidence is None:
                continue
            for alias in _source_aliases(source_loop_id):
                aliases[alias] = confidence
            for source_stem in entry.get("layer_source_stems", ()):
                for alias in _source_aliases(str(source_stem)):
                    aliases[alias] = confidence
            # Also accept the current scanned-key prefix.  This deliberately
            # allows a user-confirmed filename correction (for example Em ->
            # Am) without rewriting the immutable audio-analysis ledger.
            compact = (
                f"{confidence.scanned_key}m"
                if confidence.scanned_mode == "minor"
                else f"{confidence.scanned_key} major"
            )
            for alias in _source_aliases(f"{compact} {source_loop_id}"):
                aliases[alias] = confidence

        return cls(aliases, threshold=threshold, enabled=True)

    def match(
        self,
        source_loop_id: str,
        *,
        filename_key: str | None,
        filename_mode: str | None,
    ) -> KeyConfidenceMatch | None:
        if not self.enabled:
            return None
        source_token = str(source_loop_id).rsplit("::", 1)[-1]
        confidence = self._aliases.get(_normalised_source(source_token))
        if confidence is None:
            return None

        status = classify_key_confidence_status(
            filename_key=filename_key,
            filename_mode=filename_mode,
            scanned_key=confidence.scanned_key,
            scanned_mode=confidence.scanned_mode,
            margin=confidence.margin,
            threshold=self.threshold,
        )
        return KeyConfidenceMatch(
            source_loop_id=confidence.source_loop_id,
            scanned_key=confidence.scanned_key,
            scanned_mode=confidence.scanned_mode,
            alternate_scanned_key=confidence.alternate_scanned_key,
            alternate_scanned_mode=confidence.alternate_scanned_mode,
            top1_probability=confidence.top1_probability,
            top2_probability=confidence.top2_probability,
            margin=confidence.margin,
            status=status,
            analyzer_id=confidence.analyzer_id,
        )


__all__ = [
    "DEFAULT_KEY_MARGIN_THRESHOLD",
    "KEY_STATUSES",
    "KEY_STATUS_CONFLICT",
    "KEY_STATUS_SAFE",
    "KEY_STATUS_UNAVAILABLE",
    "KEY_STATUS_UNCERTAIN",
    "KeyConfidenceIndex",
    "KeyConfidenceMatch",
    "classify_key_confidence_status",
]
