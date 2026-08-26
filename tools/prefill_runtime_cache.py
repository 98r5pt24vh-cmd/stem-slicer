#!/usr/bin/env python3
"""Headless, resumable prefill of the Generate runtime caches.

The selected library is an immutable input.  The only mutable outputs are the
explicit library and feature SQLite files, both of which are rejected when
they resolve inside the library tree.  Progress and the final compact summary
are emitted as newline-delimited JSON for safe automation.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time
from typing import Callable, Iterator, Mapping, Sequence, TextIO


PROTOTYPE_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = PROTOTYPE_ROOT.parent
if str(PROTOTYPE_ROOT) not in sys.path:
    sys.path.insert(0, str(PROTOTYPE_ROOT))

from layer_library import CancelToken, LayerLibrary, ScanProgress, ScanResult
from mert_client import MertLayerClassifier
from mert_feature_cache import default_feature_cache_path


DEFAULT_ARTIFACT_PATH = PROTOTYPE_ROOT / "models" / "layer_roles_v2.joblib"
DEFAULT_HF_CACHE_DIR = (
    PROJECT_ROOT
    / "research"
    / "layer_role_benchmark_2026-07-30"
    / "cache"
    / "huggingface"
)
DEFAULT_LIBRARY_CACHE_PATH = (
    Path.home()
    / "Library"
    / "Caches"
    / "Stem Slicer Generate Prototype"
    / "library.sqlite3"
)
V1_ARTIFACT_SCHEMA = "stem-slicer-layer-role-head-v1"


@dataclass(frozen=True)
class PrefillConfig:
    library_root: Path
    library_cache_path: Path = DEFAULT_LIBRARY_CACHE_PATH
    feature_cache_path: Path = default_feature_cache_path()
    artifact_path: Path = DEFAULT_ARTIFACT_PATH
    hf_cache_dir: Path = DEFAULT_HF_CACHE_DIR
    device: str = "cpu"
    batch_size: int = 4
    window_batch_size: int = 4
    progress_interval_seconds: float = 0.5

    def resolved(self) -> "PrefillConfig":
        return PrefillConfig(
            library_root=self.library_root.expanduser().resolve(strict=False),
            library_cache_path=self.library_cache_path.expanduser().resolve(
                strict=False
            ),
            feature_cache_path=self.feature_cache_path.expanduser().resolve(
                strict=False
            ),
            artifact_path=self.artifact_path.expanduser().resolve(strict=False),
            hf_cache_dir=self.hf_cache_dir.expanduser().resolve(strict=False),
            device=self.device,
            batch_size=int(self.batch_size),
            window_batch_size=int(self.window_batch_size),
            progress_interval_seconds=float(self.progress_interval_seconds),
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_inside(path: Path, directory: Path) -> bool:
    return path == directory or directory in path.parents


def validate_config(raw_config: PrefillConfig) -> PrefillConfig:
    """Resolve paths and reject every unsafe mutable-output placement."""

    config = raw_config.resolved()
    if not config.library_root.is_dir():
        raise NotADirectoryError(
            f"Layer library is not a directory: {config.library_root}"
        )
    if not config.artifact_path.is_file():
        raise FileNotFoundError(
            f"Classifier v1 artifact does not exist: {config.artifact_path}"
        )
    sidecar_path = config.artifact_path.with_suffix(".json")
    if not sidecar_path.is_file():
        raise FileNotFoundError(
            f"Classifier v1 sidecar does not exist: {sidecar_path}"
        )
    try:
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid classifier v1 sidecar: {error}") from error
    if not isinstance(sidecar, Mapping) or sidecar.get("schema") != V1_ARTIFACT_SCHEMA:
        raise ValueError(
            "The selected classifier is not a Stem Slicer layer-role v1 artifact"
        )
    expected_artifact_sha256 = str(sidecar.get("artifact_sha256") or "").casefold()
    actual_artifact_sha256 = _sha256_file(config.artifact_path)
    if expected_artifact_sha256 != actual_artifact_sha256:
        raise ValueError(
            "Classifier v1 artifact checksum does not match its sidecar"
        )
    if config.device not in {"auto", "cpu", "mps"}:
        raise ValueError(f"Unsupported MERT device: {config.device!r}")
    if config.batch_size < 1 or config.window_batch_size < 1:
        raise ValueError("Batch sizes must be at least one")
    if config.progress_interval_seconds < 0:
        raise ValueError("Progress interval cannot be negative")
    if config.library_cache_path == config.feature_cache_path:
        raise ValueError("Library and feature caches must be different files")
    immutable_files = {config.artifact_path, sidecar_path.resolve(strict=False)}
    for name, cache_path in (
        ("library cache", config.library_cache_path),
        ("feature cache", config.feature_cache_path),
    ):
        if _is_inside(cache_path, config.library_root):
            raise ValueError(
                f"The {name} must be outside the selected library: {cache_path}"
            )
        if cache_path in immutable_files:
            raise ValueError(f"The {name} cannot replace a classifier artifact")
        if cache_path.exists() and cache_path.is_dir():
            raise IsADirectoryError(f"The {name} path is a directory: {cache_path}")
    return config


def emit_json(payload: Mapping[str, object], *, stream: TextIO | None = None) -> None:
    destination = stream if stream is not None else sys.stdout
    destination.write(
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    destination.flush()


class JsonProgressReporter:
    """Throttle noisy scanner callbacks while always emitting terminal state."""

    def __init__(
        self,
        emit: Callable[[Mapping[str, object]], None],
        *,
        interval_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if interval_seconds < 0:
            raise ValueError("Progress interval cannot be negative")
        self._emit = emit
        self._interval_seconds = float(interval_seconds)
        self._clock = clock
        self._last_emitted_at: float | None = None

    def __call__(self, progress: ScanProgress) -> None:
        now = self._clock()
        terminal = progress.phase in {"complete", "cancelled"}
        first = self._last_emitted_at is None
        due = (
            first
            or terminal
            or self._interval_seconds == 0
            or now - self._last_emitted_at >= self._interval_seconds
        )
        if not due:
            return
        self._emit({"event": "progress", **progress.to_dict()})
        self._last_emitted_at = now


def compact_summary(
    result: ScanResult,
    *,
    elapsed_seconds: float,
    classifier: object,
) -> dict[str, object]:
    """Return aggregate scan information without serializing layer records."""

    issue_counts = Counter(issue.code for issue in result.issues)
    return {
        "event": "summary",
        "status": "cancelled" if result.cancelled else "complete",
        "library_root": result.library_root,
        "inventory_count": result.inventory_count,
        "cached_count": result.cached_count,
        "hashed_count": result.hashed_count,
        "classified_count": result.classified_count,
        "unreviewed_count": result.unreviewed_count,
        "category_counts": result.category_counts,
        "issue_count": len(result.issues),
        "issue_counts": dict(sorted(issue_counts.items())),
        "elapsed_seconds": float(elapsed_seconds),
        "classifier_id": str(getattr(classifier, "classifier_id", "")),
        "feature_extractor_id": str(
            getattr(classifier, "feature_extractor_id", "") or ""
        ),
        "head_id": str(getattr(classifier, "head_id", "") or ""),
    }


def run_prefill(
    raw_config: PrefillConfig,
    *,
    cancel_token: CancelToken | None = None,
    emit: Callable[[Mapping[str, object]], None] | None = None,
    classifier_factory: Callable[..., object] | None = None,
    library_factory: Callable[..., object] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[int, dict[str, object]]:
    """Run one cache prefill and always stop the persistent model worker."""

    config = validate_config(raw_config)
    token = cancel_token or CancelToken()
    output = emit or emit_json
    make_classifier = classifier_factory or MertLayerClassifier
    make_library = library_factory or LayerLibrary
    reporter = JsonProgressReporter(
        output,
        interval_seconds=config.progress_interval_seconds,
        clock=clock,
    )
    output(
        {
            "event": "start",
            "library_root": str(config.library_root),
            "library_cache_path": str(config.library_cache_path),
            "feature_cache_path": str(config.feature_cache_path),
            "artifact_path": str(config.artifact_path),
        }
    )

    classifier = make_classifier(
        python_executable=sys.executable,
        artifact_path=config.artifact_path,
        hf_cache_dir=config.hf_cache_dir,
        feature_cache_path=config.feature_cache_path,
        device=config.device,
        batch_size=config.batch_size,
        window_batch_size=config.window_batch_size,
    )
    started = clock()
    try:
        library = make_library(
            config.library_root,
            config.library_cache_path,
            classifier=classifier,
            truth_csv_path=None,
            classification_batch_size=config.batch_size,
        )
        result = library.scan(progress=reporter, cancel=token)
    finally:
        classifier.stop()

    summary = compact_summary(
        result,
        elapsed_seconds=max(0.0, clock() - started),
        classifier=classifier,
    )
    output(summary)
    return (130 if result.cancelled else 0), summary


@contextmanager
def cancellation_signals(token: CancelToken) -> Iterator[None]:
    """Translate SIGINT/SIGTERM into cooperative scanner cancellation."""

    previous: dict[int, object] = {}

    def request_cancel(signum, _frame) -> None:
        del signum
        token.cancel()

    for candidate in (signal.SIGINT, signal.SIGTERM):
        try:
            previous[candidate] = signal.getsignal(candidate)
            signal.signal(candidate, request_cancel)
        except (OSError, RuntimeError, ValueError):
            continue
    try:
        yield
    finally:
        for candidate, handler in previous.items():
            signal.signal(candidate, handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fill the Generate v1 prediction and feature caches without "
            "writing inside the selected layer library."
        )
    )
    parser.add_argument("library", type=Path, help="Layer-library folder to scan")
    parser.add_argument(
        "--library-cache",
        type=Path,
        default=DEFAULT_LIBRARY_CACHE_PATH,
        help="External library.sqlite3 destination",
    )
    parser.add_argument(
        "--feature-cache",
        type=Path,
        default=default_feature_cache_path(),
        help="External features.sqlite3 destination",
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        default=DEFAULT_ARTIFACT_PATH,
        help="Classifier v1 joblib artifact",
    )
    parser.add_argument(
        "--hf-cache-dir",
        type=Path,
        default=DEFAULT_HF_CACHE_DIR,
        help="Local Hugging Face MERT cache",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cpu", "mps"),
        default=os.environ.get("STEM_SLICER_MERT_DEVICE", "cpu"),
    )
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--window-batch-size", type=int, default=4)
    parser.add_argument(
        "--progress-interval",
        type=float,
        default=0.5,
        help="Minimum seconds between non-terminal progress JSON events",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = PrefillConfig(
        library_root=args.library,
        library_cache_path=args.library_cache,
        feature_cache_path=args.feature_cache,
        artifact_path=args.artifact,
        hf_cache_dir=args.hf_cache_dir,
        device=args.device,
        batch_size=args.batch_size,
        window_batch_size=args.window_batch_size,
        progress_interval_seconds=args.progress_interval,
    )
    token = CancelToken()
    try:
        with cancellation_signals(token):
            exit_code, _summary = run_prefill(config, cancel_token=token)
            return exit_code
    except Exception as error:
        emit_json(
            {
                "event": "error",
                "error_type": type(error).__name__,
                "message": str(error),
            },
            stream=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
