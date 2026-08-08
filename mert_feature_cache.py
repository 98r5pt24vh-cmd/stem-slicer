"""Persistent, head-independent cache for MERT + DSP feature vectors.

This cache deliberately contains no labels, corpus truth or predictions.  A
row is reusable only when both the exact audio SHA-256 and the complete feature
extractor identity match.  The sklearn classification head is intentionally
absent from the key so a newly trained head can reuse existing audio features.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Mapping, Sequence

import numpy as np


FEATURE_CACHE_SCHEMA_VERSION = 1
FEATURE_DTYPE = "<f4"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def default_feature_cache_path() -> Path:
    """Return the external runtime feature-cache location on macOS."""

    configured = os.environ.get("STEM_SLICER_MERT_FEATURE_CACHE", "").strip()
    if configured:
        return Path(configured).expanduser()
    runtime_root = os.environ.get("STEM_SLICER_CACHE_DIR", "").strip()
    if runtime_root:
        return Path(runtime_root).expanduser() / "generate" / "features.sqlite3"
    return Path.home() / "Library" / "Caches" / "Stem Slicer" / "generate" / "features.sqlite3"


def canonical_audio_sha256(value: str) -> str:
    """Validate and normalize one exact audio-content SHA-256."""

    normalized = str(value).strip().casefold()
    if not _SHA256_RE.fullmatch(normalized):
        raise ValueError(f"Invalid audio SHA-256: {value!r}")
    return normalized


def canonical_feature_extractor_spec(
    metadata: Mapping[str, object],
) -> dict[str, object]:
    """Describe only operations that can change the cached 832-vector."""

    raw_mert = metadata.get("mert")
    if not isinstance(raw_mert, Mapping):
        raise ValueError("Classifier metadata has no MERT feature specification")
    raw_names = metadata.get("dsp_feature_names")
    if not isinstance(raw_names, (list, tuple)):
        raise ValueError("Classifier metadata has no DSP feature-name sequence")

    # These algorithm identifiers describe implementation details not present
    # in the historical artifact.  Changing any feature-producing operation
    # requires changing the corresponding identifier below.
    return {
        "identity_schema": "stem-slicer-feature-extractor-v1",
        "audio_decode": {
            "kind": "librosa.load",
            "mono": True,
            "dtype": "float32",
            "res_type": "soxr_hq",
            "sample_rate": int(raw_mert.get("sample_rate", 24_000)),
        },
        "mert": {
            "model_id": str(raw_mert.get("model_id", "")),
            "revision": str(raw_mert.get("revision", "")),
            "state_index": int(raw_mert.get("state_index", -1)),
            "dimension": int(raw_mert.get("dimension", -1)),
            "max_window_seconds": float(
                raw_mert.get("max_window_seconds", 15.0)
            ),
            "hidden_pool": "attention-mask-weighted-mean-v1",
            "window_pool": "ordered-mean-float64-to-float32-v1",
        },
        "dsp": {
            "algorithm": "stem-slicer-audited-dsp64-v1",
            "dimension": int(metadata.get("dsp_dimension", -1)),
            "feature_names": [str(item) for item in raw_names],
        },
        "concatenation": "mert-then-dsp-float32-v1",
    }


def derive_feature_extractor_id(metadata: Mapping[str, object]) -> str:
    """Derive and, when present, verify a stable v0/v1-compatible ID.

    Older artifacts predate ``feature_extractor_id``.  Their identity is
    derived exclusively from the feature-producing MERT/DSP specification,
    never from the training corpus, classifier classes or sklearn head.
    New artifacts may embed that derived ID, but cannot override it: a stale
    declaration must fail closed instead of reusing incompatible vectors.
    """

    specification = canonical_feature_extractor_spec(metadata)
    encoded = json.dumps(
        specification,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    derived = f"mert-dsp:{digest}"
    explicit = metadata.get("feature_extractor_id")
    if explicit is not None and str(explicit).strip():
        declared = str(explicit).strip()
        if declared != derived:
            raise ValueError(
                "Declared feature_extractor_id does not match the canonical "
                f"runtime specification: {declared!r} != {derived!r}"
            )
    return derived


def expected_feature_dimension(metadata: Mapping[str, object]) -> int:
    raw_mert = metadata.get("mert")
    if not isinstance(raw_mert, Mapping):
        raise ValueError("Classifier metadata has no MERT feature specification")
    dimension = int(raw_mert.get("dimension", -1)) + int(
        metadata.get("dsp_dimension", -1)
    )
    if dimension < 1:
        raise ValueError("Classifier metadata has an invalid feature dimension")
    return dimension


class MertFeatureCache:
    """Best-effort SQLite store for validated little-endian float32 vectors.

    Filesystem or SQLite damage must never prevent classification.  Database
    errors disable this instance and turn every access into a normal cache
    miss; the audio pipeline remains fully functional.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path).expanduser().resolve(strict=False)
        self._connection: sqlite3.Connection | None = None
        self.disabled_reason: str | None = None
        connection: sqlite3.Connection | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(self.path), timeout=10.0)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current not in (0, FEATURE_CACHE_SCHEMA_VERSION):
                raise sqlite3.DatabaseError(
                    f"unsupported feature-cache schema {current}"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS feature_vectors (
                    audio_sha256 TEXT NOT NULL,
                    feature_extractor_id TEXT NOT NULL,
                    dimension INTEGER NOT NULL,
                    dtype TEXT NOT NULL,
                    vector_blob BLOB NOT NULL,
                    vector_sha256 TEXT NOT NULL,
                    updated_at_ns INTEGER NOT NULL,
                    PRIMARY KEY (audio_sha256, feature_extractor_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_feature_vectors_extractor "
                "ON feature_vectors(feature_extractor_id)"
            )
            connection.execute(
                f"PRAGMA user_version = {FEATURE_CACHE_SCHEMA_VERSION}"
            )
            connection.commit()
            self._connection = connection
        except (OSError, sqlite3.Error) as error:
            self.disabled_reason = f"{type(error).__name__}: {error}"
            try:
                if connection is not None:
                    connection.close()
            except Exception:
                pass

    @property
    def enabled(self) -> bool:
        return self._connection is not None

    @staticmethod
    def _validated_blob(
        vector: np.ndarray,
        *,
        expected_dimension: int,
    ) -> tuple[np.ndarray, bytes, str]:
        values = np.asarray(vector, dtype=np.dtype(FEATURE_DTYPE))
        if values.ndim != 1 or values.shape != (expected_dimension,):
            raise ValueError(
                "Invalid feature-vector shape: "
                f"expected {(expected_dimension,)}, got {values.shape}"
            )
        if not np.isfinite(values).all():
            raise ValueError("Feature vector contains non-finite values")
        contiguous = np.ascontiguousarray(values, dtype=np.dtype(FEATURE_DTYPE))
        blob = contiguous.tobytes(order="C")
        expected_bytes = expected_dimension * np.dtype(FEATURE_DTYPE).itemsize
        if len(blob) != expected_bytes:
            raise ValueError("Invalid serialized feature-vector byte count")
        return contiguous, blob, hashlib.sha256(blob).hexdigest()

    def get(
        self,
        audio_sha256: str,
        feature_extractor_id: str,
        expected_dimension: int,
    ) -> np.ndarray | None:
        connection = self._connection
        if connection is None:
            return None
        try:
            digest = canonical_audio_sha256(audio_sha256)
            row = connection.execute(
                """
                SELECT dimension, dtype, vector_blob, vector_sha256
                FROM feature_vectors
                WHERE audio_sha256 = ? AND feature_extractor_id = ?
                """,
                (digest, str(feature_extractor_id)),
            ).fetchone()
        except (ValueError, sqlite3.Error):
            return None
        if row is None:
            return None
        try:
            dimension = int(row[0])
            dtype = str(row[1])
            blob = bytes(row[2])
            recorded_checksum = str(row[3]).casefold()
            if dimension != expected_dimension or dtype != FEATURE_DTYPE:
                return None
            if len(blob) != expected_dimension * np.dtype(FEATURE_DTYPE).itemsize:
                return None
            if hashlib.sha256(blob).hexdigest() != recorded_checksum:
                return None
            vector = np.frombuffer(blob, dtype=np.dtype(FEATURE_DTYPE))
            if vector.shape != (expected_dimension,) or not np.isfinite(vector).all():
                return None
            return vector.copy()
        except (TypeError, ValueError):
            return None

    def put_many(
        self,
        rows: Sequence[tuple[str, str, np.ndarray]],
        *,
        expected_dimension: int,
    ) -> bool:
        """Atomically store a fully validated set of vectors."""

        connection = self._connection
        if connection is None or not rows:
            return False
        prepared: list[tuple[str, str, int, str, bytes, str, int]] = []
        now = time.time_ns()
        # Validate every row before the first SQLite write.
        for raw_sha256, extractor_id, raw_vector in rows:
            audio_sha256 = canonical_audio_sha256(raw_sha256)
            _vector, blob, vector_sha256 = self._validated_blob(
                raw_vector,
                expected_dimension=expected_dimension,
            )
            prepared.append(
                (
                    audio_sha256,
                    str(extractor_id),
                    expected_dimension,
                    FEATURE_DTYPE,
                    blob,
                    vector_sha256,
                    now,
                )
            )
        try:
            with connection:
                connection.executemany(
                    """
                    INSERT INTO feature_vectors (
                        audio_sha256, feature_extractor_id, dimension, dtype,
                        vector_blob, vector_sha256, updated_at_ns
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(audio_sha256, feature_extractor_id) DO UPDATE SET
                        dimension=excluded.dimension,
                        dtype=excluded.dtype,
                        vector_blob=excluded.vector_blob,
                        vector_sha256=excluded.vector_sha256,
                        updated_at_ns=excluded.updated_at_ns
                    """,
                    prepared,
                )
            return True
        except sqlite3.Error as error:
            self.disabled_reason = f"{type(error).__name__}: {error}"
            return False

    def close(self) -> None:
        connection = self._connection
        self._connection = None
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                pass
