"""Read-only layer-library inventory and metadata cache for Generate.

The scanner never writes inside the selected library.  All mutable state lives
in the caller-provided SQLite cache, which must be outside the library root.
Heavy audio classification is deliberately injected behind ``LayerClassifier``;
without one, new files remain unreviewed.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import wave
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence, runtime_checkable

from key_confidence import (
    KEY_STATUS_UNAVAILABLE,
    KeyConfidenceIndex,
    KeyConfidenceMatch,
    classify_key_confidence_status,
    key_margin_threshold_for_analyzer,
)


CACHE_SCHEMA_VERSION = 3

AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".flac", ".aif", ".aiff", ".m4a"})

# This is the single-label Generate taxonomy agreed with the user.  Unreviewed
# is a review state, never a twentieth category.
TAXONOMY = (
    "Bass",
    "Chords",
    "Counter",
    "Keys",
    "Piano",
    "Lead",
    "Pad",
    "Pluck",
    "Vocal Chop",
    "Bells",
    "Strings",
    "Texture",
    "Guitar Lead",
    "Guitar Chords",
    "Vocal",
    "Arp",
    "Brass",
    "Synth",
    "Percussion",
)

_TAXONOMY_BY_CASEFOLD = {label.casefold(): label for label in TAXONOMY}
_LEGACY_LABEL_ALIASES = {
    "rhythmic pluck": "Pluck",
}
_LAYER_SUFFIX_RE = re.compile(
    r"(?ix)"
    r"(?:[\s_-]+(?:layer[\s_-]*|l)(?P<index>\d{1,4}))"
    r"(?=$|[\s_-]+)"
)
_BPM_RE = re.compile(
    r"(?ix)"
    r"(?<!\d)"
    r"(?P<bpm>[5-9]\d|1\d{2}|2[0-4]\d)"
    r"(?:[\s_-]*bpm)?"
    r"(?!\d)"
)
_EXPLICIT_KEY_RE = re.compile(
    r"(?ix)"
    r"(?<![a-z0-9])"
    r"(?P<tonic>[a-g](?:[#♯b♭])?)"
    r"(?:"
    r"(?P<compact_minor>m)(?![a-z])"
    r"|[\s_-]*(?P<mode>major|maj|minor|min)(?![a-z])"
    r")"
)
_NAKED_KEY_RE = re.compile(
    r"(?ix)"
    r"(?<![a-z0-9])"
    r"(?P<tonic>[a-g](?:[#♯b♭])?)"
    r"(?![#♯b♭a-z])"
)


class LayerLibraryError(RuntimeError):
    """Base exception for layer-library failures."""


class CacheInsideLibraryError(LayerLibraryError):
    """Raised when mutable cache state would be placed in the library."""


class CacheSchemaError(LayerLibraryError):
    """Raised when an unsupported cache schema is encountered."""


class TruthCSVError(LayerLibraryError):
    """Raised when the optional truth CSV is structurally invalid."""


class UnknownLayerError(LayerLibraryError):
    """Raised when editing a manual label for a layer absent from the cache."""


class _ScanCancelled(Exception):
    pass


def canonical_label(value: str | None) -> str | None:
    """Return the canonical taxonomy spelling, or raise for an unknown label."""

    if value is None or not str(value).strip():
        return None
    normalized = str(value).strip().casefold()
    result = _TAXONOMY_BY_CASEFOLD.get(normalized)
    if result is None:
        result = _LEGACY_LABEL_ALIASES.get(normalized)
    if result is None:
        allowed = ", ".join(TAXONOMY)
        raise ValueError(f"Unknown layer category {value!r}; expected one of: {allowed}")
    return result


@dataclass(frozen=True)
class ParsedLayerName:
    bpm: int | None
    key: str | None
    mode: str | None
    layer_index: int | None
    source_stem: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LayerMetadata:
    """Metadata supplied to an optional classifier."""

    path: str
    relative_path: str
    filename: str
    source_loop_id: str
    layer_index: int | None
    bpm: int | None
    key: str | None
    mode: str | None
    duration_seconds: float | None
    byte_size: int
    sha256: str
    mtime_ns: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LayerPrediction:
    label: str
    confidence: float | None = None
    scores: Mapping[str, float] = field(default_factory=dict)

    def normalized(self) -> "LayerPrediction":
        label = canonical_label(self.label)
        assert label is not None
        confidence = None if self.confidence is None else float(self.confidence)
        if confidence is not None and not 0.0 <= confidence <= 1.0:
            raise ValueError("Prediction confidence must be between 0 and 1")
        scores: dict[str, float] = {}
        for raw_label, raw_score in self.scores.items():
            score_label = canonical_label(raw_label)
            assert score_label is not None
            score = float(raw_score)
            if not 0.0 <= score <= 1.0:
                raise ValueError("Prediction scores must be between 0 and 1")
            scores[score_label] = scores.get(score_label, 0.0) + score
        return LayerPrediction(label=label, confidence=confidence, scores=scores)

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "confidence": self.confidence,
            "scores": dict(self.scores),
        }


@runtime_checkable
class LayerClassifier(Protocol):
    """Small injectable boundary around a heavy or remote classifier."""

    @property
    def classifier_id(self) -> str:
        """Stable identifier including model and feature-pipeline versions."""

    def predict(self, path: Path, metadata: LayerMetadata) -> LayerPrediction | None:
        """Return a prediction, or ``None`` when the file cannot be classified."""


@runtime_checkable
class BatchLayerClassifier(LayerClassifier, Protocol):
    """Optional extension for aligned multi-layer inference."""

    @property
    def preferred_batch_size(self) -> int:
        """Conservative number of layers to classify in one request."""

    def predict_many(
        self,
        items: Sequence[tuple[Path, LayerMetadata]],
    ) -> Sequence[LayerPrediction | None]:
        """Return exactly one prediction slot for every input item, in order."""


@dataclass(frozen=True)
class LayerRecord:
    path: str
    relative_path: str
    filename: str
    source_loop_id: str
    layer_index: int | None
    bpm: int | None
    key: str | None
    mode: str | None
    duration_seconds: float | None
    byte_size: int
    sha256: str
    mtime_ns: int
    manual_label: str | None = None
    predicted_label: str | None = None
    prediction_confidence: float | None = None
    prediction_scores: Mapping[str, float] = field(default_factory=dict)
    scanned_key: str | None = None
    scanned_mode: str | None = None
    alternate_scanned_key: str | None = None
    alternate_scanned_mode: str | None = None
    key_top1_probability: float | None = None
    key_top2_probability: float | None = None
    key_confidence_margin: float | None = None
    key_confidence_status: str = KEY_STATUS_UNAVAILABLE
    key_confidence_source_loop_id: str | None = None
    key_analyzer_id: str | None = None

    @property
    def effective_label(self) -> str | None:
        return self.manual_label or self.predicted_label

    @property
    def label_source(self) -> str:
        if self.manual_label is not None:
            return "manual"
        if self.predicted_label is not None:
            return "prediction"
        return "unreviewed"

    @property
    def review_status(self) -> str:
        return {
            "manual": "Reviewed",
            "prediction": "Predicted",
            "unreviewed": "Unreviewed",
        }[self.label_source]

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["prediction_scores"] = dict(self.prediction_scores)
        result["effective_label"] = self.effective_label
        result["label_source"] = self.label_source
        result["review_status"] = self.review_status
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "LayerRecord":
        fields = {
            key: data[key]
            for key in cls.__dataclass_fields__
            if key in data
        }
        scores = fields.get("prediction_scores")
        fields["prediction_scores"] = dict(scores) if isinstance(scores, Mapping) else {}
        return cls(**fields)  # type: ignore[arg-type]


@dataclass(frozen=True)
class ScanIssue:
    path: str | None
    code: str
    message: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ScanProgress:
    phase: str
    completed: int
    total: int
    relative_path: str | None = None

    @property
    def fraction(self) -> float:
        if self.total <= 0:
            return 1.0
        return min(1.0, max(0.0, self.completed / self.total))

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["fraction"] = self.fraction
        return result


@dataclass(frozen=True)
class ScanResult:
    library_root: str
    records: tuple[LayerRecord, ...]
    issues: tuple[ScanIssue, ...]
    inventory_count: int
    cached_count: int
    hashed_count: int
    classified_count: int
    cancelled: bool

    @property
    def category_counts(self) -> dict[str, int]:
        counts = Counter(record.effective_label for record in self.records)
        return {label: counts.get(label, 0) for label in TAXONOMY}

    @property
    def unreviewed_count(self) -> int:
        return sum(record.effective_label is None for record in self.records)

    @property
    def key_confidence_counts(self) -> dict[str, int]:
        return dict(Counter(record.key_confidence_status for record in self.records))

    def to_dict(self) -> dict[str, object]:
        return {
            "library_root": self.library_root,
            "records": [record.to_dict() for record in self.records],
            "issues": [issue.to_dict() for issue in self.issues],
            "inventory_count": self.inventory_count,
            "cached_count": self.cached_count,
            "hashed_count": self.hashed_count,
            "classified_count": self.classified_count,
            "cancelled": self.cancelled,
            "category_counts": self.category_counts,
            "unreviewed_count": self.unreviewed_count,
            "key_confidence_counts": self.key_confidence_counts,
        }


class CancelToken:
    """Thread-safe cooperative cancellation token for a scan worker."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()


@dataclass(frozen=True)
class _TruthRow:
    row_number: int
    label: str
    path: str | None
    relative_path: str | None
    sha256: str | None
    filename: str | None
    source_loop_id: str | None


@dataclass(frozen=True)
class _PendingClassification:
    path: Path
    metadata: LayerMetadata
    manual_label: str | None
    manual_origin: str | None
    key_confidence: KeyConfidenceMatch | None
    offset: int
    relative_path: str


class _TruthIndex:
    def __init__(self, csv_path: Path | None, library_root: Path) -> None:
        self.rows: tuple[_TruthRow, ...] = ()
        self.by_path: dict[str, list[_TruthRow]] = defaultdict(list)
        self.by_relative: dict[str, list[_TruthRow]] = defaultdict(list)
        self.by_hash: dict[str, list[_TruthRow]] = defaultdict(list)
        self.by_filename: dict[str, list[_TruthRow]] = defaultdict(list)
        if csv_path is not None:
            self._load(csv_path, library_root)

    @staticmethod
    def _first(row: Mapping[str, str], names: Sequence[str]) -> str | None:
        normalized = {key.strip().casefold(): (value or "").strip() for key, value in row.items()}
        for name in names:
            value = normalized.get(name.casefold())
            if value:
                return value
        return None

    def _load(self, csv_path: Path, library_root: Path) -> None:
        try:
            handle = csv_path.open("r", encoding="utf-8-sig", newline="")
        except OSError as exc:
            raise TruthCSVError(f"Cannot open truth CSV {csv_path}: {exc}") from exc
        parsed_rows: list[_TruthRow] = []
        with handle:
            sample = handle.read(8192)
            handle.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                header = sample.splitlines()[0] if sample else ""
                delimiter = max(
                    (",", ";", "\t"),
                    key=lambda candidate: header.count(candidate),
                )
                reader = csv.DictReader(handle, delimiter=delimiter)
            else:
                reader = csv.DictReader(handle, dialect=dialect)
            if not reader.fieldnames:
                raise TruthCSVError(f"Truth CSV has no header: {csv_path}")
            for row_number, row in enumerate(reader, start=2):
                raw_label = self._first(
                    row,
                    (
                        "label",
                        "category",
                        "manual_label",
                        "truth",
                        "user_truth",
                    ),
                )
                if raw_label is None:
                    raise TruthCSVError(f"Missing label at CSV row {row_number}")
                try:
                    label = canonical_label(raw_label)
                except ValueError as exc:
                    raise TruthCSVError(f"CSV row {row_number}: {exc}") from exc
                assert label is not None

                raw_path = self._first(row, ("audio_path", "file_path", "path"))
                raw_relative = self._first(row, ("relative_path", "relative", "relpath"))
                raw_hash = self._first(row, ("sha256", "hash", "content_hash"))
                filename = self._first(row, ("file", "filename", "name"))
                source = self._first(row, ("source_loop_id", "source", "group", "loop"))

                resolved_path: str | None = None
                if raw_path:
                    path = Path(os.path.expanduser(raw_path))
                    if not path.is_absolute():
                        path = library_root / path
                    resolved_path = str(path.resolve(strict=False))
                relative_path = _normalized_relative(raw_relative) if raw_relative else None
                sha256 = raw_hash.casefold() if raw_hash else None
                if sha256 and not re.fullmatch(r"[0-9a-f]{64}", sha256):
                    raise TruthCSVError(
                        f"CSV row {row_number}: invalid SHA-256 value {raw_hash!r}"
                    )
                if not any((resolved_path, relative_path, sha256, filename)):
                    raise TruthCSVError(
                        f"CSV row {row_number}: expected path, relative path, hash, or filename"
                    )
                truth = _TruthRow(
                    row_number=row_number,
                    label=label,
                    path=resolved_path,
                    relative_path=relative_path,
                    sha256=sha256,
                    filename=filename,
                    source_loop_id=source,
                )
                parsed_rows.append(truth)
                if resolved_path:
                    self.by_path[resolved_path].append(truth)
                if relative_path:
                    self.by_relative[relative_path.casefold()].append(truth)
                if sha256:
                    self.by_hash[sha256].append(truth)
                if filename:
                    self.by_filename[filename.casefold()].append(truth)
        self.rows = tuple(parsed_rows)

    def match(
        self,
        *,
        path: str,
        relative_path: str,
        sha256: str,
        filename: str,
        filename_is_unique: bool,
    ) -> tuple[_TruthRow | None, str | None]:
        def compatible(rows: Sequence[_TruthRow]) -> list[_TruthRow]:
            # A path/name match with a different recorded content hash is stale,
            # not truth for the new file occupying that path.
            return [row for row in rows if row.sha256 in (None, sha256.casefold())]

        strong_tiers: list[tuple[str, Sequence[_TruthRow]]] = [
            ("path", compatible(self.by_path.get(path, ()))),
            (
                "relative path",
                compatible(self.by_relative.get(relative_path.casefold(), ())),
            ),
            ("SHA-256", self.by_hash.get(sha256.casefold(), ())),
        ]
        strong_rows: list[_TruthRow] = []
        seen_row_numbers: set[int] = set()
        evidence: list[str] = []
        for kind, rows in strong_tiers:
            if rows:
                evidence.append(kind)
            for row in rows:
                if row.row_number not in seen_row_numbers:
                    strong_rows.append(row)
                    seen_row_numbers.add(row.row_number)
        if strong_rows:
            labels = {row.label for row in strong_rows}
            sources = {row.source_loop_id for row in strong_rows if row.source_loop_id}
            if len(labels) > 1 or len(sources) > 1:
                numbers = ", ".join(str(row.row_number) for row in strong_rows)
                return (
                    None,
                    f"Conflicting truth rows {numbers} matched by {', '.join(evidence)}",
                )
            # Prefer a content-hash row, then exact path, then relative path.
            hash_rows = [
                row for row in strong_rows if row.sha256 == sha256.casefold()
            ]
            return (hash_rows or strong_rows)[0], None

        if filename_is_unique:
            rows = compatible(self.by_filename.get(filename.casefold(), ()))
            if not rows:
                return None, None
            labels = {row.label for row in rows}
            sources = {row.source_loop_id for row in rows if row.source_loop_id}
            if len(labels) > 1 or len(sources) > 1:
                numbers = ", ".join(str(row.row_number) for row in rows)
                return None, f"Conflicting truth rows {numbers} matched by filename"
            return rows[0], None
        return None, None


def _canonical_tonic(value: str) -> str:
    value = value.replace("♯", "#").replace("♭", "b")
    return value[0].upper() + value[1:]


def _mode_from_key_match(match: re.Match[str]) -> str:
    if match.groupdict().get("compact_minor"):
        return "minor"
    raw_mode = (match.groupdict().get("mode") or "").casefold()
    return "minor" if raw_mode.startswith("min") else "major"


def _candidate_key_near_bpm(stem: str, bpm_match: re.Match[str] | None) -> re.Match[str] | None:
    """Find a conservative naked key token adjacent to the BPM."""

    if bpm_match is None:
        return None
    candidates = list(_NAKED_KEY_RE.finditer(stem))
    ranked: list[tuple[int, re.Match[str]]] = []
    for match in candidates:
        before_gap = stem[match.end() : bpm_match.start()] if match.end() <= bpm_match.start() else None
        after_gap = stem[bpm_match.end() : match.start()] if bpm_match.end() <= match.start() else None
        gaps = [gap for gap in (before_gap, after_gap) if gap is not None]
        if any(re.fullmatch(r"[\s_-]*", gap) for gap in gaps):
            distance = min(len(gap) for gap in gaps if re.fullmatch(r"[\s_-]*", gap))
            ranked.append((distance, match))
    if not ranked:
        # A naked tonic at the absolute beginning is common in exported layers.
        beginning = _NAKED_KEY_RE.match(stem)
        return beginning
    ranked.sort(key=lambda item: (item[0], item[1].start()))
    return ranked[0][1]


def parse_layer_filename(filename: str | os.PathLike[str]) -> ParsedLayerName:
    """Parse BPM, exact key/mode and layer grouping from either token order."""

    stem = Path(filename).stem.strip()
    layer_matches = list(_LAYER_SUFFIX_RE.finditer(stem))
    layer_match = layer_matches[-1] if layer_matches else None
    layer_index = int(layer_match.group("index")) if layer_match else None
    source_stem = (
        (stem[: layer_match.start()] + stem[layer_match.end() :]).strip(" _-")
        if layer_match
        else stem
    )
    source_stem = re.sub(r"[\s_-]+", " ", source_stem).strip()

    bpm_matches = list(_BPM_RE.finditer(stem))
    bpm_match = bpm_matches[0] if bpm_matches else None
    bpm = int(bpm_match.group("bpm")) if bpm_match else None

    explicit_keys = list(_EXPLICIT_KEY_RE.finditer(stem))
    if explicit_keys:
        # Prefer the explicit key nearest the BPM, then the leftmost.
        if bpm_match:
            explicit_keys.sort(
                key=lambda match: (
                    min(
                        abs(match.start() - bpm_match.end()),
                        abs(match.end() - bpm_match.start()),
                    ),
                    match.start(),
                )
            )
        key_match = explicit_keys[0]
        return ParsedLayerName(
            bpm=bpm,
            key=_canonical_tonic(key_match.group("tonic")),
            mode=_mode_from_key_match(key_match),
            layer_index=layer_index,
            source_stem=source_stem,
        )

    naked_key = _candidate_key_near_bpm(stem, bpm_match)
    return ParsedLayerName(
        bpm=bpm,
        key=_canonical_tonic(naked_key.group("tonic")) if naked_key else None,
        mode="major" if naked_key else None,
        layer_index=layer_index,
        source_stem=source_stem,
    )


def _normalized_relative(value: str | None) -> str:
    if not value:
        return ""
    return Path(value.replace("\\", "/")).as_posix().lstrip("./")


def _source_loop_id(relative_path: str, parsed: ParsedLayerName) -> str:
    parent = Path(relative_path).parent.as_posix()
    normalized_stem = re.sub(r"\s+", " ", parsed.source_stem).strip().casefold()
    if parent == ".":
        return normalized_stem
    return f"{parent.casefold()}::{normalized_stem}"


def _cancelled(cancel: CancelToken | Callable[[], bool] | None) -> bool:
    if cancel is None:
        return False
    if isinstance(cancel, CancelToken):
        return cancel.is_cancelled()
    return bool(cancel())


def _sha256_file(
    path: Path,
    cancel: CancelToken | Callable[[], bool] | None,
    chunk_size: int = 1024 * 1024,
) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            if _cancelled(cancel):
                raise _ScanCancelled
            chunk = handle.read(chunk_size)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def _wave_duration(path: Path) -> float | None:
    if path.suffix.casefold() != ".wav":
        return None
    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        return handle.getnframes() / rate if rate else None


def _aiff_duration(path: Path) -> float | None:
    if path.suffix.casefold() not in {".aif", ".aiff"}:
        return None
    try:
        import aifc
    except ImportError:
        return None
    with aifc.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        return handle.getnframes() / rate if rate else None


def _mutagen_duration(path: Path) -> float | None:
    try:
        import mutagen  # type: ignore[import-not-found]
    except ImportError:
        return None
    audio = mutagen.File(str(path))
    if audio is None or getattr(audio, "info", None) is None:
        return None
    duration = getattr(audio.info, "length", None)
    return float(duration) if duration is not None else None


def _soundfile_duration(path: Path) -> float | None:
    try:
        import soundfile  # type: ignore[import-not-found]
    except ImportError:
        return None
    info = soundfile.info(str(path))
    if not info.samplerate:
        return None
    return float(info.frames / info.samplerate)


def _audioread_duration(path: Path) -> float | None:
    try:
        import audioread  # type: ignore[import-not-found]
    except ImportError:
        return None
    with audioread.audio_open(str(path)) as audio:
        return float(audio.duration)


def _ffprobe_duration(path: Path) -> float | None:
    executable = shutil.which("ffprobe")
    if executable is None:
        return None
    process_options = {}
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        process_options = {
            "startupinfo": startupinfo,
            "creationflags": subprocess.CREATE_NO_WINDOW,
        }
    completed = subprocess.run(
        [
            executable,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        **process_options,
    )
    if completed.returncode != 0:
        return None
    try:
        return float(completed.stdout.strip())
    except ValueError:
        return None


def read_audio_duration(path: Path) -> float | None:
    """Read duration without changing the file, using lightweight fallbacks."""

    readers = (
        _wave_duration,
        _aiff_duration,
        _mutagen_duration,
        _soundfile_duration,
        _audioread_duration,
        _ffprobe_duration,
    )
    for reader in readers:
        try:
            duration = reader(path)
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError):
            continue
        if duration is not None and duration >= 0:
            return duration
    return None


def _iter_audio_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for current_root, directories, filenames in os.walk(root, followlinks=False):
        directories[:] = sorted(
            (
                name
                for name in directories
                if not (Path(current_root) / name).is_symlink()
            ),
            key=lambda value: (value.casefold(), value),
        )
        for filename in sorted(filenames, key=lambda value: (value.casefold(), value)):
            path = Path(current_root) / filename
            if path.is_symlink() or path.suffix.casefold() not in AUDIO_EXTENSIONS:
                continue
            paths.append(path)
    paths.sort(
        key=lambda path: (
            path.relative_to(root).as_posix().casefold(),
            path.relative_to(root).as_posix(),
        )
    )
    return paths


class LayerLibrary:
    """Recursive scanner backed by an external, versioned SQLite cache."""

    def __init__(
        self,
        library_root: str | os.PathLike[str],
        cache_path: str | os.PathLike[str],
        *,
        classifier: LayerClassifier | None = None,
        truth_csv_path: str | os.PathLike[str] | None = None,
        key_confidence_index: KeyConfidenceIndex | None = None,
        duration_reader: Callable[[Path], float | None] = read_audio_duration,
        classification_batch_size: int | None = None,
    ) -> None:
        self.library_root = Path(library_root).expanduser().resolve(strict=False)
        self.cache_path = Path(cache_path).expanduser().resolve(strict=False)
        self.classifier = classifier
        self.truth_csv_path = (
            Path(truth_csv_path).expanduser().resolve(strict=False)
            if truth_csv_path is not None
            else None
        )
        self.key_confidence_index = key_confidence_index or KeyConfidenceIndex()
        self.duration_reader = duration_reader
        requested_batch_size = (
            classification_batch_size
            if classification_batch_size is not None
            else getattr(classifier, "preferred_batch_size", 1)
        )
        self.classification_batch_size = int(requested_batch_size)
        if self.classification_batch_size < 1:
            raise ValueError("Classification batch size must be at least one")
        self._validate_paths()

    def _validate_paths(self) -> None:
        if not self.library_root.is_dir():
            raise NotADirectoryError(f"Layer library is not a directory: {self.library_root}")
        if self.cache_path == self.library_root or self.library_root in self.cache_path.parents:
            raise CacheInsideLibraryError(
                "The SQLite cache must be outside the scanned layer library"
            )
        if self.truth_csv_path is not None and not self.truth_csv_path.is_file():
            raise FileNotFoundError(f"Truth CSV does not exist: {self.truth_csv_path}")

    def _manual_origin_is_usable(self, raw_origin: object) -> bool:
        """Accept user edits, plus only this scan's explicit dev overlay.

        Older prototype revisions could write training-CSV labels into the
        production library cache.  Merely disconnecting that CSV at startup is
        insufficient: those persisted rows would otherwise keep masquerading
        as user-library truth forever.  A normal scan/load therefore accepts
        only ``manual_origin='user'``.  The isolated development cache may also
        accept the exact overlay path explicitly supplied to this instance.
        """

        origin = str(raw_origin) if raw_origin else None
        if origin == "user":
            return True
        return bool(
            self.truth_csv_path is not None
            and origin == f"csv:{self.truth_csv_path}"
        )

    def _connect(self) -> sqlite3.Connection:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.cache_path))
        connection.row_factory = sqlite3.Row
        current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if current_version < 0 or current_version > CACHE_SCHEMA_VERSION:
            connection.close()
            raise CacheSchemaError(
                f"Unsupported cache schema {current_version}; expected {CACHE_SCHEMA_VERSION}"
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS layer_cache (
                path TEXT PRIMARY KEY,
                library_root TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                filename TEXT NOT NULL,
                source_loop_id TEXT NOT NULL,
                layer_index INTEGER,
                bpm INTEGER,
                key TEXT,
                mode TEXT,
                duration_seconds REAL,
                byte_size INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                mtime_ns INTEGER NOT NULL,
                predicted_label TEXT,
                prediction_confidence REAL,
                prediction_scores_json TEXT NOT NULL DEFAULT '{}',
                classifier_id TEXT,
                manual_label TEXT,
                manual_origin TEXT,
                scanned_key TEXT,
                scanned_mode TEXT,
                alternate_scanned_key TEXT,
                alternate_scanned_mode TEXT,
                key_top1_probability REAL,
                key_top2_probability REAL,
                key_confidence_margin REAL,
                key_confidence_status TEXT NOT NULL DEFAULT 'unavailable',
                key_confidence_source_loop_id TEXT,
                key_analyzer_id TEXT,
                updated_at_ns INTEGER NOT NULL
            )
            """
        )
        existing_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(layer_cache)")
        }
        migrations = {
            "scanned_key": "TEXT",
            "scanned_mode": "TEXT",
            "alternate_scanned_key": "TEXT",
            "alternate_scanned_mode": "TEXT",
            "key_top1_probability": "REAL",
            "key_top2_probability": "REAL",
            "key_confidence_margin": "REAL",
            "key_confidence_status": "TEXT NOT NULL DEFAULT 'unavailable'",
            "key_confidence_source_loop_id": "TEXT",
            "key_analyzer_id": "TEXT",
        }
        for column, declaration in migrations.items():
            if column not in existing_columns:
                connection.execute(
                    f"ALTER TABLE layer_cache ADD COLUMN {column} {declaration}"
                )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_layer_cache_hash ON layer_cache(sha256)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_layer_cache_root ON layer_cache(library_root)"
        )
        connection.execute(f"PRAGMA user_version = {CACHE_SCHEMA_VERSION}")
        connection.commit()
        return connection

    @staticmethod
    def _cached_row(connection: sqlite3.Connection, path: str) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM layer_cache WHERE path = ?", (path,)
        ).fetchone()

    @staticmethod
    def _cached_rows_by_hash(
        connection: sqlite3.Connection,
        sha256: str,
    ) -> tuple[sqlite3.Row, ...]:
        """Return newest-first cache rows for identical audio content.

        Paths are deliberately not part of this lookup.  It lets a copied or
        relocated library reuse duration and classification work after the new
        path has been content-verified by SHA-256.
        """

        return tuple(
            connection.execute(
                """
                SELECT * FROM layer_cache
                WHERE sha256 = ?
                ORDER BY updated_at_ns DESC
                """,
                (sha256,),
            ).fetchall()
        )

    @staticmethod
    def _record_from_values(
        metadata: LayerMetadata,
        *,
        manual_label: str | None,
        predicted_label: str | None,
        prediction_confidence: float | None,
        prediction_scores: Mapping[str, float],
        key_confidence: KeyConfidenceMatch | None,
    ) -> LayerRecord:
        return LayerRecord(
            **metadata.to_dict(),
            manual_label=manual_label,
            predicted_label=predicted_label,
            prediction_confidence=prediction_confidence,
            prediction_scores=dict(prediction_scores),
            scanned_key=(key_confidence.scanned_key if key_confidence else None),
            scanned_mode=(key_confidence.scanned_mode if key_confidence else None),
            alternate_scanned_key=(
                key_confidence.alternate_scanned_key if key_confidence else None
            ),
            alternate_scanned_mode=(
                key_confidence.alternate_scanned_mode if key_confidence else None
            ),
            key_top1_probability=(
                key_confidence.top1_probability if key_confidence else None
            ),
            key_top2_probability=(
                key_confidence.top2_probability if key_confidence else None
            ),
            key_confidence_margin=(key_confidence.margin if key_confidence else None),
            key_confidence_status=(
                key_confidence.status if key_confidence else KEY_STATUS_UNAVAILABLE
            ),
            key_confidence_source_loop_id=(
                key_confidence.source_loop_id if key_confidence else None
            ),
            key_analyzer_id=(key_confidence.analyzer_id if key_confidence else None),
        )

    @staticmethod
    def _save_record(
        connection: sqlite3.Connection,
        record: LayerRecord,
        *,
        library_root: str,
        classifier_id: str | None,
        manual_origin: str | None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO layer_cache (
                path, library_root, relative_path, filename, source_loop_id,
                layer_index, bpm, key, mode, duration_seconds, byte_size,
                sha256, mtime_ns, predicted_label, prediction_confidence,
                prediction_scores_json, classifier_id, manual_label,
                manual_origin, scanned_key, scanned_mode,
                alternate_scanned_key, alternate_scanned_mode,
                key_top1_probability, key_top2_probability,
                key_confidence_margin, key_confidence_status,
                key_confidence_source_loop_id, key_analyzer_id, updated_at_ns
            ) VALUES (
                :path, :library_root, :relative_path, :filename, :source_loop_id,
                :layer_index, :bpm, :key, :mode, :duration_seconds, :byte_size,
                :sha256, :mtime_ns, :predicted_label, :prediction_confidence,
                :prediction_scores_json, :classifier_id, :manual_label,
                :manual_origin, :scanned_key, :scanned_mode,
                :alternate_scanned_key, :alternate_scanned_mode,
                :key_top1_probability, :key_top2_probability,
                :key_confidence_margin, :key_confidence_status,
                :key_confidence_source_loop_id, :key_analyzer_id, :updated_at_ns
            )
            ON CONFLICT(path) DO UPDATE SET
                library_root=excluded.library_root,
                relative_path=excluded.relative_path,
                filename=excluded.filename,
                source_loop_id=excluded.source_loop_id,
                layer_index=excluded.layer_index,
                bpm=excluded.bpm,
                key=excluded.key,
                mode=excluded.mode,
                duration_seconds=excluded.duration_seconds,
                byte_size=excluded.byte_size,
                sha256=excluded.sha256,
                mtime_ns=excluded.mtime_ns,
                predicted_label=excluded.predicted_label,
                prediction_confidence=excluded.prediction_confidence,
                prediction_scores_json=excluded.prediction_scores_json,
                classifier_id=excluded.classifier_id,
                manual_label=excluded.manual_label,
                manual_origin=excluded.manual_origin,
                scanned_key=excluded.scanned_key,
                scanned_mode=excluded.scanned_mode,
                alternate_scanned_key=excluded.alternate_scanned_key,
                alternate_scanned_mode=excluded.alternate_scanned_mode,
                key_top1_probability=excluded.key_top1_probability,
                key_top2_probability=excluded.key_top2_probability,
                key_confidence_margin=excluded.key_confidence_margin,
                key_confidence_status=excluded.key_confidence_status,
                key_confidence_source_loop_id=excluded.key_confidence_source_loop_id,
                key_analyzer_id=excluded.key_analyzer_id,
                updated_at_ns=excluded.updated_at_ns
            """,
            {
                **record.to_dict(),
                "library_root": library_root,
                "prediction_scores_json": json.dumps(
                    dict(record.prediction_scores), sort_keys=True, separators=(",", ":")
                ),
                "classifier_id": classifier_id,
                "manual_origin": manual_origin,
                "updated_at_ns": time.time_ns(),
            },
        )

    def scan(
        self,
        *,
        progress: Callable[[ScanProgress], None] | None = None,
        cancel: CancelToken | Callable[[], bool] | None = None,
    ) -> ScanResult:
        """Scan recursively and return a deterministic immutable inventory."""

        paths = _iter_audio_files(self.library_root)
        total = len(paths)
        filename_counts = Counter(path.name.casefold() for path in paths)
        truth = _TruthIndex(self.truth_csv_path, self.library_root)
        records: list[LayerRecord] = []
        issues: list[ScanIssue] = []
        cached_count = 0
        hashed_count = 0
        classified_count = 0
        was_cancelled = False

        if progress:
            progress(ScanProgress("inventory", 0, total, None))

        connection = self._connect()
        try:
            classifier_id = (
                str(self.classifier.classifier_id) if self.classifier is not None else None
            )
            batch_predictor = (
                getattr(self.classifier, "predict_many", None)
                if self.classifier is not None
                else None
            )
            batch_enabled = bool(
                callable(batch_predictor)
                and self.classification_batch_size > 1
            )
            pending: list[_PendingClassification] = []

            def persist_prediction(
                item: _PendingClassification,
                prediction: LayerPrediction | None,
                prediction_id: str | None,
            ) -> None:
                record = self._record_from_values(
                    item.metadata,
                    manual_label=item.manual_label,
                    predicted_label=prediction.label if prediction else None,
                    prediction_confidence=(
                        prediction.confidence if prediction else None
                    ),
                    prediction_scores=prediction.scores if prediction else {},
                    key_confidence=item.key_confidence,
                )
                self._save_record(
                    connection,
                    record,
                    library_root=str(self.library_root),
                    classifier_id=(prediction_id if prediction is not None else None),
                    manual_origin=item.manual_origin,
                )
                records.append(record)

            def flush_pending() -> bool:
                """Classify one complete chunk, then persist it atomically."""

                nonlocal classified_count, was_cancelled
                if not pending:
                    return True
                batch = tuple(pending)
                pending.clear()
                if _cancelled(cancel):
                    was_cancelled = True
                    return False
                if progress:
                    detail = batch[0].relative_path
                    if len(batch) > 1:
                        detail = f"{detail} (+{len(batch) - 1})"
                    progress(
                        ScanProgress(
                            "classify",
                            batch[0].offset,
                            total,
                            detail,
                        )
                    )

                normalized: list[LayerPrediction | None]
                completed_classifications = 0
                try:
                    assert callable(batch_predictor)
                    raw_predictions = list(
                        batch_predictor(
                            tuple((item.path, item.metadata) for item in batch)
                        )
                    )
                    if len(raw_predictions) != len(batch):
                        raise ValueError(
                            "Batch classifier returned "
                            f"{len(raw_predictions)} results for {len(batch)} inputs"
                        )
                    normalized = [
                        prediction.normalized()
                        if prediction is not None
                        else None
                        for prediction in raw_predictions
                    ]
                    completed_classifications = len(batch)
                except Exception:
                    # A batch transport/model failure must not poison otherwise
                    # valid layers.  Retry individually through the established
                    # classifier contract, retaining input order.
                    normalized = []
                    for item in batch:
                        if _cancelled(cancel):
                            was_cancelled = True
                            return False
                        try:
                            assert self.classifier is not None
                            raw_prediction = self.classifier.predict(
                                item.path,
                                item.metadata,
                            )
                            normalized.append(
                                raw_prediction.normalized()
                                if raw_prediction is not None
                                else None
                            )
                            completed_classifications += 1
                        except Exception as exc:
                            normalized.append(None)
                            issues.append(
                                ScanIssue(
                                    item.metadata.path,
                                    "classification_failed",
                                    str(exc),
                                )
                            )

                if _cancelled(cancel):
                    was_cancelled = True
                    return False
                classified_count += completed_classifications
                # Normalize every result before the first write.  A malformed
                # batch can therefore never shift predictions between paths or
                # leave half of that batch saved.
                for item, prediction in zip(batch, normalized, strict=True):
                    persist_prediction(item, prediction, classifier_id)
                return True

            for offset, path in enumerate(paths):
                if _cancelled(cancel):
                    was_cancelled = True
                    break
                relative_path = path.relative_to(self.library_root).as_posix()
                if progress:
                    progress(ScanProgress("metadata", offset, total, relative_path))
                try:
                    stat = path.stat()
                except OSError as exc:
                    issues.append(ScanIssue(str(path), "stat_failed", str(exc)))
                    continue

                absolute_path = str(path.resolve(strict=False))
                cached = self._cached_row(connection, absolute_path)
                unchanged = bool(
                    cached
                    and int(cached["byte_size"]) == stat.st_size
                    and int(cached["mtime_ns"]) == stat.st_mtime_ns
                )
                try:
                    if unchanged:
                        sha256 = str(cached["sha256"])
                        cached_count += 1
                    else:
                        sha256 = _sha256_file(path, cancel)
                        hashed_count += 1
                except _ScanCancelled:
                    was_cancelled = True
                    break
                except OSError as exc:
                    issues.append(ScanIssue(absolute_path, "read_failed", str(exc)))
                    continue

                cached_prediction_is_current = bool(
                    cached
                    and cached["predicted_label"]
                    and (
                        self.classifier is None
                        or (
                            str(cached["classifier_id"])
                            if cached["classifier_id"]
                            else None
                        )
                        == classifier_id
                    )
                )
                cached_has_usable_label = bool(
                    cached
                    and (
                        (
                            cached["manual_label"]
                            and self._manual_origin_is_usable(
                                cached["manual_origin"]
                            )
                        )
                        or cached_prediction_is_current
                    )
                )
                if unchanged and cached is not None and cached_has_usable_label:
                    content_cache = (cached,)
                else:
                    content_cache = self._cached_rows_by_hash(connection, sha256)
                duration_source = next(
                    (
                        row
                        for row in content_cache
                        if row["duration_seconds"] is not None
                    ),
                    None,
                )
                duration = (
                    duration_source["duration_seconds"]
                    if duration_source is not None
                    else None
                )
                try:
                    if duration is None:
                        duration = self.duration_reader(path)
                except Exception as exc:
                    issues.append(ScanIssue(absolute_path, "duration_failed", str(exc)))
                    duration = None

                if duration is None:
                    issues.append(
                        ScanIssue(
                            absolute_path,
                            "duration_unavailable",
                            "Audio duration could not be read",
                        )
                    )

                parsed = parse_layer_filename(path.name)
                inferred_source = _source_loop_id(relative_path, parsed)
                truth_row, truth_error = truth.match(
                    path=absolute_path,
                    relative_path=relative_path,
                    sha256=sha256,
                    filename=path.name,
                    filename_is_unique=filename_counts[path.name.casefold()] == 1,
                )
                if truth_error:
                    issues.append(ScanIssue(absolute_path, "truth_conflict", truth_error))

                user_manual_source = next(
                    (
                        row
                        for row in content_cache
                        if row["manual_label"] and row["manual_origin"] == "user"
                    ),
                    None,
                )
                cached_manual = (
                    canonical_label(cached["manual_label"])
                    if (
                        unchanged
                        and cached
                        and self._manual_origin_is_usable(
                            cached["manual_origin"]
                        )
                    )
                    else None
                )
                cached_origin = (
                    str(cached["manual_origin"])
                    if (
                        unchanged
                        and cached
                        and self._manual_origin_is_usable(
                            cached["manual_origin"]
                        )
                    )
                    else None
                )
                if user_manual_source is not None:
                    manual_label = canonical_label(user_manual_source["manual_label"])
                    manual_origin = "user"
                elif truth_row is not None:
                    manual_label = truth_row.label
                    manual_origin = f"csv:{self.truth_csv_path}"
                else:
                    manual_label = cached_manual
                    manual_origin = cached_origin

                source_loop_id = (
                    truth_row.source_loop_id
                    if truth_row is not None and truth_row.source_loop_id
                    else inferred_source
                )
                metadata = LayerMetadata(
                    path=absolute_path,
                    relative_path=relative_path,
                    filename=path.name,
                    source_loop_id=source_loop_id,
                    layer_index=parsed.layer_index,
                    bpm=parsed.bpm,
                    key=parsed.key,
                    mode=parsed.mode,
                    duration_seconds=float(duration) if duration is not None else None,
                    byte_size=stat.st_size,
                    sha256=sha256,
                    mtime_ns=stat.st_mtime_ns,
                )
                key_confidence = self.key_confidence_index.match(
                    source_loop_id,
                    filename_key=parsed.key,
                    filename_mode=parsed.mode,
                )
                cached_key_confidence = next(
                    (
                        row
                        for row in content_cache
                        if row["scanned_key"]
                        and row["scanned_mode"]
                        and row["key_confidence_margin"] is not None
                        and row["key_confidence_source_loop_id"]
                        and row["key_analyzer_id"]
                    ),
                    None,
                )
                if key_confidence is None and cached_key_confidence is None:
                    # ``content_cache`` intentionally collapses to the current
                    # path on a warm scan when its category is already usable.
                    # Key analysis may still exist on another exact-content
                    # row (for example the same layer in an older library).
                    cached_key_confidence = next(
                        (
                            row
                            for row in self._cached_rows_by_hash(connection, sha256)
                            if row["scanned_key"]
                            and row["scanned_mode"]
                            and row["key_confidence_margin"] is not None
                            and row["key_confidence_source_loop_id"]
                            and row["key_analyzer_id"]
                        ),
                        None,
                    )
                if (
                    key_confidence is None
                    and cached_key_confidence is not None
                ):
                    # Exact-content cache reuse applies to precomputed key
                    # metadata too. Recompute the status because a relocated
                    # copy can have a different filename key.
                    confidence_margin = float(
                        cached_key_confidence["key_confidence_margin"]
                    )
                    key_confidence = KeyConfidenceMatch(
                        source_loop_id=str(
                            cached_key_confidence["key_confidence_source_loop_id"]
                        ),
                        scanned_key=str(cached_key_confidence["scanned_key"]),
                        scanned_mode=str(cached_key_confidence["scanned_mode"]),
                        alternate_scanned_key=(
                            str(cached_key_confidence["alternate_scanned_key"])
                            if cached_key_confidence["alternate_scanned_key"]
                            else None
                        ),
                        alternate_scanned_mode=(
                            str(cached_key_confidence["alternate_scanned_mode"])
                            if cached_key_confidence["alternate_scanned_mode"]
                            else None
                        ),
                        top1_probability=(
                            float(cached_key_confidence["key_top1_probability"])
                            if cached_key_confidence["key_top1_probability"] is not None
                            else None
                        ),
                        top2_probability=(
                            float(cached_key_confidence["key_top2_probability"])
                            if cached_key_confidence["key_top2_probability"] is not None
                            else None
                        ),
                        margin=confidence_margin,
                        status=classify_key_confidence_status(
                            filename_key=parsed.key,
                            filename_mode=parsed.mode,
                            scanned_key=str(cached_key_confidence["scanned_key"]),
                            scanned_mode=str(cached_key_confidence["scanned_mode"]),
                            margin=confidence_margin,
                            threshold=key_margin_threshold_for_analyzer(
                                str(cached_key_confidence["key_analyzer_id"]),
                                fallback=self.key_confidence_index.threshold,
                            ),
                        ),
                        analyzer_id=str(cached_key_confidence["key_analyzer_id"]),
                    )

                prediction: LayerPrediction | None = None
                prediction_classifier_id: str | None = None
                prediction_source = next(
                    (
                        row
                        for row in content_cache
                        if row["predicted_label"]
                        and (
                            self.classifier is None
                            or (
                                str(row["classifier_id"])
                                if row["classifier_id"]
                                else None
                            )
                            == classifier_id
                        )
                    ),
                    None,
                )
                if manual_label is None and prediction_source is not None:
                    cached_classifier_id = (
                        str(prediction_source["classifier_id"])
                        if prediction_source["classifier_id"]
                        else None
                    )
                    # A cache-only pass must preserve an existing prediction.
                    # It must never turn classified layers back into Unknown
                    # merely because no classifier was injected.
                    raw_scores = json.loads(
                        prediction_source["prediction_scores_json"] or "{}"
                    )
                    prediction = LayerPrediction(
                        label=str(prediction_source["predicted_label"]),
                        confidence=prediction_source["prediction_confidence"],
                        scores=raw_scores,
                    ).normalized()
                    prediction_classifier_id = cached_classifier_id

                if (
                    self.classifier is not None
                    and manual_label is None
                    and prediction is None
                ):
                    prepared = _PendingClassification(
                        path=path,
                        metadata=metadata,
                        manual_label=manual_label,
                        manual_origin=manual_origin,
                        key_confidence=key_confidence,
                        offset=offset,
                        relative_path=relative_path,
                    )
                    if batch_enabled:
                        pending.append(prepared)
                        if len(pending) >= self.classification_batch_size:
                            if not flush_pending():
                                break
                        if (offset + 1) % 32 == 0:
                            connection.commit()
                        continue
                    if progress:
                        progress(ScanProgress("classify", offset, total, relative_path))
                    try:
                        raw_prediction = self.classifier.predict(path, metadata)
                        if _cancelled(cancel):
                            was_cancelled = True
                            break
                        prediction = (
                            raw_prediction.normalized()
                            if raw_prediction is not None
                            else None
                        )
                        prediction_classifier_id = (
                            classifier_id if prediction is not None else None
                        )
                        classified_count += 1
                    except Exception as exc:
                        issues.append(
                            ScanIssue(absolute_path, "classification_failed", str(exc))
                        )
                persist_prediction(
                    _PendingClassification(
                        path=path,
                        metadata=metadata,
                        manual_label=manual_label,
                        manual_origin=manual_origin,
                        key_confidence=key_confidence,
                        offset=offset,
                        relative_path=relative_path,
                    ),
                    prediction,
                    prediction_classifier_id,
                )
                if (offset + 1) % 32 == 0:
                    connection.commit()
            if not was_cancelled and pending:
                flush_pending()
            connection.commit()
        finally:
            connection.close()

        records.sort(
            key=lambda record: (
                record.relative_path.casefold(),
                record.relative_path,
            )
        )
        if progress:
            progress(
                ScanProgress(
                    "cancelled" if was_cancelled else "complete",
                    len(records),
                    total,
                    None,
                )
            )
        return ScanResult(
            library_root=str(self.library_root),
            records=tuple(records),
            issues=tuple(issues),
            inventory_count=total,
            cached_count=cached_count,
            hashed_count=hashed_count,
            classified_count=classified_count,
            cancelled=was_cancelled,
        )

    def load_cached(self) -> ScanResult:
        """Hydrate one already-scanned library directly from SQLite.

        This deliberately performs no directory walk, stat, hash, duration
        read, key analysis, or classifier call. A normal ``scan()`` remains
        available when the user wants to detect added or modified files.  If a
        classifier is attached, predictions created by another classifier
        version are exposed as unreviewed instead of silently restoring stale
        labels.
        """

        hydrated_key_confidence: dict[str, KeyConfidenceMatch] = {}
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT * FROM layer_cache
                WHERE library_root = ?
                ORDER BY relative_path COLLATE NOCASE, relative_path
                """,
                (str(self.library_root),),
            ).fetchall()
            if self.key_confidence_index.enabled:
                for row in rows:
                    match = self.key_confidence_index.match(
                        str(row["source_loop_id"]),
                        filename_key=row["key"],
                        filename_mode=row["mode"],
                    )
                    if match is None:
                        continue
                    path = str(row["path"])
                    hydrated_key_confidence[path] = match
                    current = (
                        row["scanned_key"],
                        row["scanned_mode"],
                        row["alternate_scanned_key"],
                        row["alternate_scanned_mode"],
                        row["key_top1_probability"],
                        row["key_top2_probability"],
                        row["key_confidence_margin"],
                        row["key_confidence_status"],
                        row["key_confidence_source_loop_id"],
                        row["key_analyzer_id"],
                    )
                    desired = (
                        match.scanned_key,
                        match.scanned_mode,
                        match.alternate_scanned_key,
                        match.alternate_scanned_mode,
                        match.top1_probability,
                        match.top2_probability,
                        match.margin,
                        match.status,
                        match.source_loop_id,
                        match.analyzer_id,
                    )
                    if current == desired:
                        continue
                    connection.execute(
                        """
                        UPDATE layer_cache SET
                            scanned_key = ?,
                            scanned_mode = ?,
                            alternate_scanned_key = ?,
                            alternate_scanned_mode = ?,
                            key_top1_probability = ?,
                            key_top2_probability = ?,
                            key_confidence_margin = ?,
                            key_confidence_status = ?,
                            key_confidence_source_loop_id = ?,
                            key_analyzer_id = ?
                        WHERE path = ?
                        """,
                        (*desired, path),
                    )
                connection.commit()
        finally:
            connection.close()

        expected_classifier_id = (
            str(self.classifier.classifier_id)
            if self.classifier is not None
            else None
        )
        records: list[LayerRecord] = []
        issues: list[ScanIssue] = []
        for row in rows:
            manual_is_compatible = self._manual_origin_is_usable(
                row["manual_origin"]
            )
            if row["manual_label"] and not manual_is_compatible:
                issues.append(
                    ScanIssue(
                        str(row["path"]),
                        "stale_truth_cache",
                        "Cached CSV truth is not a production user label",
                    )
                )
            cached_classifier_id = (
                str(row["classifier_id"])
                if row["classifier_id"]
                else None
            )
            prediction_is_compatible = (
                expected_classifier_id is None
                or not row["predicted_label"]
                or cached_classifier_id == expected_classifier_id
            )
            if not prediction_is_compatible:
                issues.append(
                    ScanIssue(
                        str(row["path"]),
                        "stale_classifier_cache",
                        "Cached prediction belongs to another classifier version",
                    )
                )
            raw_scores = (
                json.loads(row["prediction_scores_json"] or "{}")
                if prediction_is_compatible
                else {}
            )
            key_confidence = hydrated_key_confidence.get(str(row["path"]))
            records.append(
                LayerRecord(
                    path=str(row["path"]),
                    relative_path=str(row["relative_path"]),
                    filename=str(row["filename"]),
                    source_loop_id=str(row["source_loop_id"]),
                    layer_index=row["layer_index"],
                    bpm=row["bpm"],
                    key=row["key"],
                    mode=row["mode"],
                    duration_seconds=row["duration_seconds"],
                    byte_size=int(row["byte_size"]),
                    sha256=str(row["sha256"]),
                    mtime_ns=int(row["mtime_ns"]),
                    manual_label=(
                        canonical_label(row["manual_label"])
                        if manual_is_compatible
                        else None
                    ),
                    predicted_label=(
                        canonical_label(row["predicted_label"])
                        if prediction_is_compatible
                        else None
                    ),
                    prediction_confidence=(
                        row["prediction_confidence"]
                        if prediction_is_compatible
                        else None
                    ),
                    prediction_scores=dict(raw_scores),
                    scanned_key=(
                        key_confidence.scanned_key
                        if key_confidence is not None
                        else row["scanned_key"]
                    ),
                    scanned_mode=(
                        key_confidence.scanned_mode
                        if key_confidence is not None
                        else row["scanned_mode"]
                    ),
                    alternate_scanned_key=(
                        key_confidence.alternate_scanned_key
                        if key_confidence is not None
                        else row["alternate_scanned_key"]
                    ),
                    alternate_scanned_mode=(
                        key_confidence.alternate_scanned_mode
                        if key_confidence is not None
                        else row["alternate_scanned_mode"]
                    ),
                    key_top1_probability=(
                        key_confidence.top1_probability
                        if key_confidence is not None
                        else row["key_top1_probability"]
                    ),
                    key_top2_probability=(
                        key_confidence.top2_probability
                        if key_confidence is not None
                        else row["key_top2_probability"]
                    ),
                    key_confidence_margin=(
                        key_confidence.margin
                        if key_confidence is not None
                        else row["key_confidence_margin"]
                    ),
                    key_confidence_status=(
                        key_confidence.status
                        if key_confidence is not None
                        else str(row["key_confidence_status"])
                        if row["key_confidence_status"]
                        else KEY_STATUS_UNAVAILABLE
                    ),
                    key_confidence_source_loop_id=(
                        key_confidence.source_loop_id
                        if key_confidence is not None
                        else row["key_confidence_source_loop_id"]
                    ),
                    key_analyzer_id=(
                        key_confidence.analyzer_id
                        if key_confidence is not None
                        else row["key_analyzer_id"]
                    ),
                )
            )
        return ScanResult(
            library_root=str(self.library_root),
            records=tuple(records),
            issues=tuple(issues),
            inventory_count=len(records),
            cached_count=len(records),
            hashed_count=0,
            classified_count=0,
            cancelled=False,
        )

    def set_manual_label(
        self,
        path: str | os.PathLike[str],
        label: str | None,
    ) -> None:
        """Persist a user correction; it always outranks CSV and predictions."""

        normalized_label = canonical_label(label)
        absolute_path = str(Path(path).expanduser().resolve(strict=False))
        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                UPDATE layer_cache
                SET manual_label = ?, manual_origin = ?, updated_at_ns = ?
                WHERE path = ? AND library_root = ?
                """,
                (
                    normalized_label,
                    "user" if normalized_label else None,
                    time.time_ns(),
                    absolute_path,
                    str(self.library_root),
                ),
            )
            if cursor.rowcount != 1:
                raise UnknownLayerError(f"Layer is not present in this cache: {absolute_path}")
            connection.commit()
        finally:
            connection.close()


def scan_layer_library(
    library_root: str | os.PathLike[str],
    cache_path: str | os.PathLike[str],
    *,
    classifier: LayerClassifier | None = None,
    truth_csv_path: str | os.PathLike[str] | None = None,
    key_confidence_index: KeyConfidenceIndex | None = None,
    duration_reader: Callable[[Path], float | None] = read_audio_duration,
    classification_batch_size: int | None = None,
    progress: Callable[[ScanProgress], None] | None = None,
    cancel: CancelToken | Callable[[], bool] | None = None,
) -> ScanResult:
    """Convenience wrapper for one-shot scans."""

    return LayerLibrary(
        library_root,
        cache_path,
        classifier=classifier,
        truth_csv_path=truth_csv_path,
        key_confidence_index=key_confidence_index,
        duration_reader=duration_reader,
        classification_batch_size=classification_batch_size,
    ).scan(progress=progress, cancel=cancel)


def most_recent_cached_library_root(
    cache_path: str | os.PathLike[str],
) -> Path | None:
    """Return the newest cached library that still exists on disk."""

    path = Path(cache_path).expanduser().resolve(strict=False)
    if not path.is_file():
        return None
    try:
        connection = sqlite3.connect(str(path))
        rows = connection.execute(
            """
            SELECT library_root, MAX(updated_at_ns) AS newest
            FROM layer_cache
            GROUP BY library_root
            ORDER BY newest DESC
            """
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        if "connection" in locals():
            connection.close()
    for raw_root, _newest in rows:
        candidate = Path(str(raw_root)).expanduser().resolve(strict=False)
        if candidate.is_dir():
            return candidate
    return None


__all__ = [
    "AUDIO_EXTENSIONS",
    "BatchLayerClassifier",
    "CACHE_SCHEMA_VERSION",
    "TAXONOMY",
    "CacheInsideLibraryError",
    "CacheSchemaError",
    "CancelToken",
    "LayerClassifier",
    "LayerLibrary",
    "LayerLibraryError",
    "LayerMetadata",
    "LayerPrediction",
    "LayerRecord",
    "ParsedLayerName",
    "ScanIssue",
    "ScanProgress",
    "ScanResult",
    "TruthCSVError",
    "UnknownLayerError",
    "canonical_label",
    "parse_layer_filename",
    "read_audio_duration",
    "most_recent_cached_library_root",
    "scan_layer_library",
]
