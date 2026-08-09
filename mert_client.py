"""Small synchronous client for the persistent MERT NDJSON worker."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from typing import Sequence

from layer_library import LayerMetadata, LayerPrediction
from mert_feature_cache import (
    canonical_audio_sha256,
    default_feature_cache_path,
    derive_feature_extractor_id,
    expected_feature_dimension,
)


class MertClientError(RuntimeError):
    pass


class MertLayerClassifier:
    """Injectable ``LayerClassifier`` implementation backed by one process."""

    def __init__(
        self,
        *,
        python_executable: str | os.PathLike[str] | None = None,
        worker_path: str | os.PathLike[str] | None = None,
        artifact_path: str | os.PathLike[str] | None = None,
        hf_cache_dir: str | os.PathLike[str] | None = None,
        feature_cache_path: str | os.PathLike[str] | None = None,
        # Backward-compatible name for the Hugging Face model cache.  It is
        # never used as the feature-vector SQLite location.
        cache_dir: str | os.PathLike[str] | None = None,
        device: str = "cpu",
        startup_timeout: float = 300.0,
        request_timeout: float = 180.0,
        batch_size: int | None = None,
        window_batch_size: int | None = None,
    ) -> None:
        source_root = Path(__file__).resolve().parent
        root = Path(getattr(sys, "_MEIPASS", source_root))
        self.python_executable = str(python_executable or sys.executable)
        self.worker_path = Path(worker_path or root / "mert_worker.py")
        self.artifact_path = Path(
            artifact_path or root / "models" / "layer_roles_v1.joblib"
        )
        if hf_cache_dir is not None and cache_dir is not None:
            raise ValueError("Pass hf_cache_dir or cache_dir, not both")
        bundled_hf_cache = root / "models" / "huggingface"
        development_hf_cache = (
            source_root.parent
            / "research"
            / "layer_role_benchmark_2026-07-30"
            / "cache"
            / "huggingface"
        )
        configured_hf_cache = os.environ.get(
            "STEM_SLICER_MERT_MODEL_CACHE", ""
        ).strip()
        self.hf_cache_dir = Path(
            hf_cache_dir
            or cache_dir
            or configured_hf_cache
            or (
                bundled_hf_cache
                if bundled_hf_cache.exists()
                else development_hf_cache
            )
        )
        self.feature_cache_path = Path(
            feature_cache_path or default_feature_cache_path()
        ).expanduser()
        self.device = device
        self.startup_timeout = float(startup_timeout)
        self.request_timeout = float(request_timeout)
        self.batch_size = int(
            batch_size
            if batch_size is not None
            else os.environ.get("STEM_SLICER_MERT_BATCH_SIZE", "4")
        )
        self.window_batch_size = int(
            window_batch_size
            if window_batch_size is not None
            else os.environ.get(
                "STEM_SLICER_MERT_WINDOW_BATCH_SIZE",
                str(self.batch_size),
            )
        )
        if self.batch_size < 1 or self.window_batch_size < 1:
            raise ValueError("MERT batch sizes must be at least one")
        self._process: subprocess.Popen[str] | None = None
        self._stdout_queue: queue.Queue[str | None] = queue.Queue()
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr_lines: list[str] = []
        self._lock = threading.Lock()
        self._request_id = 0
        self._model_version: str | None = None
        self._feature_extractor_id: str | None = None
        self._feature_dimension: int | None = None
        self._head_id: str | None = None
        metadata_path = self.artifact_path.with_suffix(".json")
        artifact_digest: str | None = None
        try:
            artifact_digest = hashlib.sha256(
                self.artifact_path.read_bytes()
            ).hexdigest()
        except OSError:
            pass
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if artifact_digest is None:
                raise OSError(f"Unreadable classifier artifact: {self.artifact_path}")
            self._model_version = str(metadata["version"])
            self._feature_extractor_id = derive_feature_extractor_id(metadata)
            self._feature_dimension = expected_feature_dimension(metadata)
            self._head_id = f"sklearn-artifact:{artifact_digest}"
            self._classifier_id = (
                f"{self._model_version}:{artifact_digest[:16]}"
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            self._classifier_id = (
                "mert-worker:"
                f"{self.artifact_path.resolve(strict=False)}:"
                f"{artifact_digest or 'unreadable'}"
            )

    @property
    def classifier_id(self) -> str:
        return self._classifier_id

    @property
    def preferred_batch_size(self) -> int:
        return self.batch_size

    @property
    def feature_extractor_id(self) -> str | None:
        return self._feature_extractor_id

    @property
    def head_id(self) -> str | None:
        return self._head_id

    def _readline(self, timeout: float) -> str:
        process = self._process
        if process is None or process.stdout is None:
            raise MertClientError("MERT worker is not running.")
        try:
            line = self._stdout_queue.get(timeout=timeout)
        except queue.Empty:
            status = (
                f"exit code {process.poll()}"
                if process.poll() is not None
                else "process still running"
            )
            detail = "\n".join(self._stderr_lines[-20:]).strip()
            raise TimeoutError(
                "Timed out waiting for the MERT worker "
                f"after {timeout:.1f}s ({status})."
                + (f" {detail}" if detail else "")
            )
        if line is not None:
            return line
        detail = "\n".join(self._stderr_lines[-20:]).strip()
        raise MertClientError(
            "MERT worker stopped unexpectedly."
            + (f" {detail}" if detail else "")
        )

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            self._stdout_queue.put(None)
            return
        try:
            for line in process.stdout:
                self._stdout_queue.put(line)
        finally:
            self._stdout_queue.put(None)

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            self._stderr_lines.append(line.rstrip())
            if len(self._stderr_lines) > 200:
                del self._stderr_lines[:100]

    @staticmethod
    def _hidden_windows_process_options() -> dict[str, object]:
        if os.name != "nt":
            return {}
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        return {
            "startupinfo": startupinfo,
            "creationflags": subprocess.CREATE_NO_WINDOW,
        }

    def start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        if getattr(sys, "frozen", False):
            command = [self.python_executable, "--mert-worker"]
        else:
            command = [
                self.python_executable,
                "-u",
                str(self.worker_path),
            ]
        command.extend([
            "--artifact",
            str(self.artifact_path),
            "--hf-cache-dir",
            str(self.hf_cache_dir),
            "--feature-cache",
            str(self.feature_cache_path),
            "--device",
            self.device,
            "--window-batch-size",
            str(self.window_batch_size),
        ])
        environment = os.environ.copy()
        environment["PYTHONUNBUFFERED"] = "1"
        self._stdout_queue = queue.Queue()
        self._stderr_lines = []
        self._process = subprocess.Popen(
            command,
            cwd=str(self.worker_path.parent),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=environment,
            **self._hidden_windows_process_options(),
        )
        self._stdout_thread = threading.Thread(
            target=self._read_stdout,
            name="StemSlicerMertStdout",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._read_stderr,
            name="StemSlicerMertStderr",
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()
        try:
            payload = json.loads(self._readline(self.startup_timeout))
        except Exception:
            self.stop(force=True)
            raise
        if payload.get("event") != "ready":
            self.stop(force=True)
            raise MertClientError(
                f"Unexpected MERT worker handshake: {payload!r}"
            )
        worker_version = str(payload.get("model_version") or "")
        if self._model_version is not None and worker_version != self._model_version:
            self.stop(force=True)
            raise MertClientError(
                "MERT worker/model artifact version mismatch: "
                f"expected {self._model_version!r}, got {worker_version!r}."
            )
        worker_extractor_id = str(payload.get("feature_extractor_id") or "")
        if (
            self._feature_extractor_id is not None
            and worker_extractor_id != self._feature_extractor_id
        ):
            self.stop(force=True)
            raise MertClientError(
                "MERT worker feature-extractor mismatch: "
                f"expected {self._feature_extractor_id!r}, "
                f"got {worker_extractor_id!r}."
            )
        worker_dimension = payload.get("feature_dimension")
        if (
            self._feature_dimension is not None
            and int(worker_dimension or -1) != self._feature_dimension
        ):
            self.stop(force=True)
            raise MertClientError(
                "MERT worker feature dimension mismatch: "
                f"expected {self._feature_dimension!r}, "
                f"got {worker_dimension!r}."
            )
        worker_head_id = str(payload.get("head_id") or "")
        if self._head_id is not None and worker_head_id != self._head_id:
            self.stop(force=True)
            raise MertClientError(
                "MERT worker classifier-head mismatch: "
                f"expected {self._head_id!r}, got {worker_head_id!r}."
            )

    def _request(self, command: str, **payload) -> dict:
        with self._lock:
            self.start()
            process = self._process
            if process is None or process.stdin is None:
                raise MertClientError("MERT worker has no stdin.")
            self._request_id += 1
            request_id = self._request_id
            message = {"id": request_id, "command": command, **payload}
            process.stdin.write(
                json.dumps(message, ensure_ascii=False) + "\n"
            )
            process.stdin.flush()
            response = json.loads(self._readline(self.request_timeout))
            if response.get("id") != request_id:
                raise MertClientError(
                    f"MERT protocol id mismatch: {response!r}"
                )
            if not response.get("ok"):
                raise MertClientError(
                    str(response.get("error") or "Unknown MERT worker error")
                )
            return response

    @staticmethod
    def _prediction_from_result(result: dict) -> LayerPrediction:
        scores = {
            str(item["label"]): float(item["score"])
            for item in [
                {
                    "label": result["prediction"],
                    "score": result["score"],
                },
                *result.get("alternatives", []),
            ]
        }
        return LayerPrediction(
            label=str(result["prediction"]),
            confidence=float(result["score"]),
            scores=scores,
        )

    def predict(
        self, path: Path, metadata: LayerMetadata
    ) -> LayerPrediction | None:
        result = self._request(
            "classify",
            path=str(path.resolve()),
            sha256=canonical_audio_sha256(metadata.sha256),
        )["result"]
        return self._prediction_from_result(result)

    def predict_many(
        self,
        items: Sequence[tuple[Path, LayerMetadata]],
    ) -> list[LayerPrediction | None]:
        """Classify paths together and strictly preserve caller ordering."""

        if not items:
            return []
        paths = tuple(path.resolve() for path, _metadata in items)
        hashes = tuple(
            canonical_audio_sha256(metadata.sha256)
            for _path, metadata in items
        )
        try:
            payload = self._request(
                "classify_many",
                items=[
                    {"path": str(path), "sha256": audio_sha256}
                    for path, audio_sha256 in zip(paths, hashes, strict=True)
                ],
            )
            raw_results = payload.get("results")
            if not isinstance(raw_results, list) or len(raw_results) != len(paths):
                raise MertClientError(
                    "MERT batch response count does not match the request"
                )
            predictions: list[LayerPrediction | None] = []
            for expected_path, result in zip(paths, raw_results, strict=True):
                if not isinstance(result, dict):
                    raise MertClientError("Invalid MERT batch result payload")
                returned_path = Path(str(result.get("path") or "")).resolve()
                if returned_path != expected_path:
                    raise MertClientError(
                        "MERT batch response order/path does not match the request"
                    )
                predictions.append(self._prediction_from_result(result))
            return predictions
        except Exception:
            # A timed-out or malformed batch can leave the NDJSON stream out of
            # sync.  Stop it before LayerLibrary retries through ``predict``.
            self.stop(force=True)
            raise

    def metadata(self) -> dict:
        return dict(self._request("metadata")["metadata"])

    def stop(self, *, force: bool = False) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.poll() is not None:
            return
        if not force and process.stdin is not None:
            try:
                self._request_id += 1
                process.stdin.write(
                    json.dumps(
                        {
                            "id": self._request_id,
                            "command": "shutdown",
                        }
                    )
                    + "\n"
                )
                process.stdin.flush()
                deadline = time.monotonic() + 3.0
                while process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
            except Exception:
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)

    def __enter__(self) -> "MertLayerClassifier":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.stop()
