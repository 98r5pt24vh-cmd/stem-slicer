#!/usr/bin/env python3
"""Persistent NDJSON MERT + DSP classifier for the Generate prototype.

The worker writes protocol messages to stdout and diagnostics to stderr.  It
loads the 95M MERT checkpoint lazily on the first unknown layer so a library
fully covered by manual truth can be scanned without paying the model startup
cost.
"""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
from typing import Sequence


PROTOTYPE_ROOT = Path(__file__).resolve().parent
DEFAULT_RESEARCH_ROOT = (
    PROTOTYPE_ROOT.parent / "research" / "layer_role_benchmark_2026-07-30"
)
DEFAULT_HF_HOME = Path(
    os.environ.get("STEM_SLICER_MERT_MODEL_CACHE")
    or os.environ.get("HF_HOME")
    or DEFAULT_RESEARCH_ROOT / "cache" / "huggingface"
)
os.environ.setdefault("HF_HOME", str(DEFAULT_HF_HOME))
os.environ.setdefault("HF_HUB_CACHE", str(DEFAULT_HF_HOME / "hub"))
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import joblib
import librosa
import numpy as np
import torch

from layer_role_classifier import LayerRoleScoreEnsemble  # noqa: F401
from mert_feature_cache import (
    MertFeatureCache,
    canonical_audio_sha256,
    default_feature_cache_path,
    derive_feature_extractor_id,
    expected_feature_dimension,
)


SR = 24_000
MAX_WINDOW_SECONDS = 15.0
N_BINS = 32


def _truncate_encoder_for_state(model, state_index: int) -> None:
    """Keep only the encoder blocks required for ``hidden_states[state_index]``.

    Transformers exposes the projected feature sequence as hidden state zero;
    hidden state N is therefore produced by encoder block N.  Later blocks
    cannot influence that state in evaluation mode and only waste inference
    time for an artifact trained from an intermediate MERT layer.
    """

    encoder = getattr(model, "encoder", None)
    layers = getattr(encoder, "layers", None)
    if not isinstance(layers, torch.nn.ModuleList):
        raise RuntimeError("MERT encoder does not expose a ModuleList of layers.")
    if state_index < 0 or state_index > len(layers):
        raise RuntimeError(
            f"Invalid MERT hidden-state index {state_index} for {len(layers)} layers."
        )
    if state_index < len(layers):
        encoder.layers = torch.nn.ModuleList(list(layers[:state_index]))


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _safe_stat(
    values: np.ndarray, function, default: float = 0.0
) -> float:
    finite = values[np.isfinite(values)]
    return float(function(finite)) if finite.size else default


def _active_runs(mask: np.ndarray) -> tuple[int, int]:
    padded = np.pad(mask.astype(np.int8), (1, 1))
    delta = np.diff(padded)
    starts = np.flatnonzero(delta == 1)
    ends = np.flatnonzero(delta == -1)
    lengths = ends - starts
    return int(len(starts)), int(lengths.max()) if lengths.size else 0


def load_audio(path: Path) -> np.ndarray:
    audio, sample_rate = librosa.load(
        path,
        sr=SR,
        mono=True,
        dtype=np.float32,
        res_type="soxr_hq",
    )
    if sample_rate != SR or audio.ndim != 1 or audio.size == 0:
        raise ValueError(f"Invalid audio: {path}")
    if not np.isfinite(audio).all():
        raise ValueError(f"Non-finite audio: {path}")
    return np.ascontiguousarray(audio)


def audio_windows(audio: np.ndarray) -> list[np.ndarray]:
    maximum = int(MAX_WINDOW_SECONDS * SR)
    if audio.size <= maximum:
        return [audio]
    count = int(np.ceil(audio.size / maximum))
    starts = np.linspace(0, audio.size - maximum, count, dtype=int)
    return [audio[start : start + maximum] for start in starts]


def dsp_features(audio: np.ndarray) -> np.ndarray:
    """Return the audited 64-feature DSP vector without decoding twice."""
    raw_rms = float(
        np.sqrt(np.mean(np.square(audio), dtype=np.float64))
    )
    peak = float(np.max(np.abs(audio)))
    normalized = audio / max(peak, 1e-8)

    n_fft = 2048
    hop = 256
    stft = np.abs(librosa.stft(normalized, n_fft=n_fft, hop_length=hop))
    power = np.square(stft)
    frequencies = librosa.fft_frequencies(sr=SR, n_fft=n_fft)
    total_power = float(power.sum()) + 1e-12

    rms = librosa.feature.rms(
        y=normalized, frame_length=n_fft, hop_length=hop
    )[0]
    centroid = librosa.feature.spectral_centroid(
        S=stft, sr=SR
    )[0]
    bandwidth = librosa.feature.spectral_bandwidth(
        S=stft, sr=SR
    )[0]
    rolloff = librosa.feature.spectral_rolloff(
        S=stft, sr=SR, roll_percent=0.85
    )[0]
    flatness = librosa.feature.spectral_flatness(S=stft)[0]
    zcr = librosa.feature.zero_crossing_rate(
        normalized, frame_length=n_fft, hop_length=hop
    )[0]
    onset = librosa.onset.onset_strength(
        y=normalized, sr=SR, hop_length=hop
    )
    onset_frames = librosa.onset.onset_detect(
        onset_envelope=onset,
        sr=SR,
        hop_length=hop,
        units="frames",
        backtrack=False,
    )

    harmonic, percussive = librosa.effects.hpss(normalized)
    harmonic_rms = float(
        np.sqrt(np.mean(np.square(harmonic), dtype=np.float64))
    )
    percussive_rms = float(
        np.sqrt(np.mean(np.square(percussive), dtype=np.float64))
    )

    duration = audio.size / SR
    frame_db = librosa.amplitude_to_db(
        np.maximum(rms, 1e-12), ref=np.max
    )
    active = frame_db > -45.0

    edges = np.linspace(0, audio.size, N_BINS + 1, dtype=int)
    bin_rms = np.asarray(
        [
            np.sqrt(
                np.mean(np.square(normalized[edges[index] : edges[index + 1]]))
                + 1e-12
            )
            for index in range(N_BINS)
        ],
        dtype=np.float32,
    )
    bin_db = librosa.amplitude_to_db(
        np.maximum(bin_rms, 1e-12), ref=np.max
    )
    bin_active = bin_db > -35.0
    run_count, longest_run = _active_runs(bin_active)
    active_indices = np.flatnonzero(bin_active)
    first_active = (
        float(active_indices[0] / (N_BINS - 1))
        if active_indices.size
        else 1.0
    )
    last_active = (
        float(active_indices[-1] / (N_BINS - 1))
        if active_indices.size
        else 0.0
    )
    probability = np.square(bin_rms)
    probability /= probability.sum() + 1e-12
    temporal_entropy = float(
        -(probability * np.log(probability + 1e-12)).sum()
        / np.log(N_BINS)
    )

    values = [
        duration,
        raw_rms,
        peak,
        _safe_stat(rms, np.mean),
        _safe_stat(rms, np.std),
        _safe_stat(rms, lambda item: np.percentile(item, 10)),
        _safe_stat(rms, lambda item: np.percentile(item, 90)),
        float(active.mean()),
        peak / (raw_rms + 1e-12),
        _safe_stat(centroid, np.mean),
        _safe_stat(centroid, np.std),
        _safe_stat(bandwidth, np.mean),
        _safe_stat(rolloff, np.mean),
        _safe_stat(flatness, np.mean),
        _safe_stat(zcr, np.mean),
        float(power[frequencies < 120].sum() / total_power),
        float(power[frequencies < 250].sum() / total_power),
        float(
            power[
                (frequencies >= 250) & (frequencies < 1200)
            ].sum()
            / total_power
        ),
        float(power[frequencies >= 2000].sum() / total_power),
        float(len(onset_frames) / max(duration, 1e-8)),
        _safe_stat(onset, np.mean),
        _safe_stat(onset, np.std),
        _safe_stat(onset, lambda item: np.percentile(item, 90)),
        harmonic_rms,
        percussive_rms,
        percussive_rms
        / (harmonic_rms + percussive_rms + 1e-12),
        float(bin_active.mean()),
        float(run_count),
        float(longest_run / N_BINS),
        first_active,
        last_active,
        temporal_entropy,
    ]
    values.extend(float(value) for value in bin_db)
    vector = np.asarray(values, dtype=np.float32)
    if vector.shape != (64,) or not np.isfinite(vector).all():
        raise RuntimeError("Invalid DSP feature vector.")
    return vector


class Runtime:
    def __init__(
        self,
        artifact_path: Path,
        hf_cache_dir: Path,
        feature_cache_path: Path,
        device_name: str,
    ) -> None:
        artifact = joblib.load(artifact_path)
        self.classifier = artifact["model"]
        self.metadata = artifact["metadata"]
        self.hf_cache_dir = hf_cache_dir
        self.feature_extractor_id = derive_feature_extractor_id(self.metadata)
        self.feature_dimension = expected_feature_dimension(self.metadata)
        self.reusable_base_feature_extractor_id: str | None = None
        self.reusable_base_feature_dimension: int | None = None
        mert_spec = self.metadata.get("mert", {})
        statistics = tuple(str(value) for value in mert_spec.get("statistics", ("mean",)))
        if statistics == ("mean", "std"):
            base_metadata = dict(self.metadata)
            base_mert = dict(mert_spec)
            base_mert.pop("statistics", None)
            base_mert.pop("output_dimension", None)
            base_metadata["mert"] = base_mert
            base_metadata.pop("feature_extractor_id", None)
            self.reusable_base_feature_extractor_id = derive_feature_extractor_id(
                base_metadata
            )
            self.reusable_base_feature_dimension = expected_feature_dimension(
                base_metadata
            )
        artifact_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        self.head_id = f"sklearn-artifact:{artifact_sha256}"
        head_dimension = getattr(self.classifier, "n_features_in_", None)
        if head_dimension is not None and int(head_dimension) != self.feature_dimension:
            raise RuntimeError(
                "Classifier/extractor feature dimension mismatch: "
                f"head expects {head_dimension}, extractor produces "
                f"{self.feature_dimension}."
            )
        self.feature_cache = MertFeatureCache(feature_cache_path)
        self.device = self._choose_device(device_name)
        self.processor = None
        self.mert = None

    @staticmethod
    def _choose_device(requested: str) -> torch.device:
        if requested == "mps":
            if not torch.backends.mps.is_available():
                raise RuntimeError("MPS was requested but is unavailable.")
            return torch.device("mps")
        if requested == "auto" and torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")

    def ensure_mert(self) -> None:
        if self.mert is not None:
            return
        # The checkpoint's custom module prints one optional-dependency notice
        # to stdout.  Stdout belongs exclusively to the NDJSON protocol, so
        # redirect all third-party load chatter to stderr.
        with redirect_stdout(sys.stderr):
            from transformers import AutoModel, Wav2Vec2FeatureExtractor

            spec = self.metadata["mert"]
            snapshot = (
                self.hf_cache_dir
                / f"models--{str(spec['model_id']).replace('/', '--')}"
                / "snapshots"
                / str(spec["revision"])
            )
            model_source = snapshot if snapshot.is_dir() else spec["model_id"]
            arguments = {
                "local_files_only": True,
                "trust_remote_code": True,
            }
            if model_source == spec["model_id"]:
                arguments.update(
                    {
                        "revision": spec["revision"],
                        "cache_dir": str(self.hf_cache_dir),
                    }
                )
            self.processor = Wav2Vec2FeatureExtractor.from_pretrained(
                model_source, **arguments
            )
            self.mert = AutoModel.from_pretrained(
                model_source, **arguments
            ).to(self.device).eval()
            _truncate_encoder_for_state(
                self.mert,
                int(spec["state_index"]),
            )

    def mert_features_many(
        self,
        audios: Sequence[np.ndarray],
        *,
        window_batch_size: int,
    ) -> np.ndarray:
        """Extract correctly masked MERT mean or mean+std per input audio."""

        mert_spec = self.metadata["mert"]
        statistics = tuple(str(value) for value in mert_spec.get("statistics", ("mean",)))
        if statistics not in (("mean",), ("mean", "std")):
            raise RuntimeError(f"Unsupported MERT statistics: {statistics!r}")
        state_dimension = int(mert_spec["dimension"])
        output_dimension = int(
            mert_spec.get("output_dimension", state_dimension * len(statistics))
        )
        if not audios:
            return np.empty((0, output_dimension), dtype=np.float32)
        if window_batch_size < 1:
            raise ValueError("MERT window batch size must be at least one")
        self.ensure_mert()
        state_index = int(mert_spec["state_index"])
        windows: list[tuple[int, int, np.ndarray]] = []
        for audio_index, audio in enumerate(audios):
            for chunk in audio_windows(audio):
                windows.append((len(windows), audio_index, chunk))
        # MERT's convolutional frontend uses group normalization.  Padding a
        # shorter waveform can therefore alter its *valid* activations before
        # an attention mask is applied.  Bucket by exact decoded sample count
        # so batching remains bit-equivalent to the established single-item
        # artifact protocol.
        buckets: dict[int, list[tuple[int, int, np.ndarray]]] = {}
        for window in windows:
            buckets.setdefault(int(window[2].size), []).append(window)

        pooled_by_audio: list[list[tuple[int, np.ndarray, np.ndarray | None]]] = [
            [] for _audio in audios
        ]
        for bucket in buckets.values():
            for start in range(0, len(bucket), window_batch_size):
                current = bucket[start : start + window_batch_size]
                inputs = self.processor(
                    [chunk for _index, _owner, chunk in current],
                    sampling_rate=SR,
                    return_tensors="pt",
                    padding=True,
                    return_attention_mask=True,
                )
                input_values = inputs["input_values"].to(
                    self.device, dtype=torch.float32
                )
                attention_mask = inputs.get("attention_mask")
                if attention_mask is None:
                    raise RuntimeError(
                        "MERT processor did not return an attention mask."
                    )
                attention_mask = attention_mask.to(self.device)
                with torch.inference_mode():
                    output = self.mert(
                        input_values,
                        attention_mask=attention_mask,
                        output_hidden_states=True,
                    )
                state = output.hidden_states[state_index]
                if state.ndim != 3 or state.shape[0] != len(current):
                    raise RuntimeError("Invalid batched MERT hidden-state shape.")
                mask_converter = getattr(
                    self.mert,
                    "_get_feature_vector_attention_mask",
                    None,
                )
                if not callable(mask_converter):
                    raise RuntimeError(
                        "MERT model cannot map the sample attention mask to hidden frames."
                    )
                feature_mask = mask_converter(state.shape[1], attention_mask)
                if feature_mask.shape != state.shape[:2]:
                    raise RuntimeError("Invalid MERT feature attention-mask shape.")
                weights = feature_mask.to(
                    device=state.device,
                    dtype=state.dtype,
                ).unsqueeze(-1)
                denominator = weights.sum(dim=1).clamp_min(1.0)
                mean_tensor = (state * weights).sum(dim=1) / denominator
                pooled_batch = mean_tensor.detach().cpu().numpy().astype(np.float32)
                if pooled_batch.shape != (len(current), state_dimension):
                    raise RuntimeError("Invalid batched MERT feature matrix.")
                std_batch: np.ndarray | None = None
                if statistics == ("mean", "std"):
                    variance = (
                        (torch.square(state - mean_tensor.unsqueeze(1)) * weights).sum(dim=1)
                        / denominator
                    )
                    std_batch = (
                        torch.sqrt(variance.clamp_min(0.0))
                        .detach()
                        .cpu()
                        .numpy()
                        .astype(np.float32)
                    )
                    if std_batch.shape != (len(current), state_dimension):
                        raise RuntimeError("Invalid batched MERT std matrix.")
                for batch_index, ((window_index, owner, _chunk), vector) in enumerate(zip(
                    current,
                    pooled_batch,
                    strict=True,
                )):
                    window_std = None if std_batch is None else std_batch[batch_index]
                    pooled_by_audio[owner].append((window_index, vector, window_std))

        pooled_rows: list[np.ndarray] = []
        for chunks in pooled_by_audio:
            ordered = sorted(chunks, key=lambda item: item[0])
            means = [mean for _index, mean, _std in ordered]
            pooled_mean = np.mean(means, axis=0, dtype=np.float64).astype(np.float32)
            if statistics == ("mean",):
                pooled_rows.append(pooled_mean)
                continue
            variances = []
            for _index, current_mean, current_std in ordered:
                if current_std is None:
                    raise RuntimeError("Missing MERT window standard deviation")
                variances.append(
                    np.square(current_std, dtype=np.float64)
                    + np.square(
                        current_mean.astype(np.float64)
                        - pooled_mean.astype(np.float64)
                    )
                )
            pooled_std = np.sqrt(np.mean(variances, axis=0)).astype(np.float32)
            pooled_rows.append(np.concatenate([pooled_mean, pooled_std]))
        pooled = np.stack(pooled_rows, axis=0)
        if pooled.shape != (len(audios), output_dimension) or not np.isfinite(pooled).all():
            raise RuntimeError("Invalid MERT feature matrix.")
        return pooled

    def mert_features(self, audio: np.ndarray) -> np.ndarray:
        return self.mert_features_many(
            [audio],
            window_batch_size=1,
        )[0]

    def _classification_result(
        self,
        path: Path,
        probabilities: np.ndarray,
        *,
        elapsed_seconds: float,
    ) -> dict:
        classes = self.classifier.classes_.astype(str)
        order = np.argsort(probabilities)[::-1]
        top = [
            {
                "label": str(classes[index]),
                "score": float(probabilities[index]),
            }
            for index in order[:3]
        ]
        return {
            "path": str(path),
            "prediction": top[0]["label"],
            "score": top[0]["score"],
            "alternatives": top[1:],
            "probabilities_calibrated": False,
            "model_version": self.metadata["version"],
            "feature_extractor_id": self.feature_extractor_id,
            "head_id": self.head_id,
            "elapsed_seconds": elapsed_seconds,
        }

    def _extract_feature_vectors(
        self,
        paths: Sequence[Path],
        *,
        window_batch_size: int,
        reusable_base_vectors: Sequence[np.ndarray | None] | None = None,
    ) -> np.ndarray:
        """Decode and extract complete MERT+DSP vectors for cache misses."""

        if not paths:
            return np.empty((0, self.feature_dimension), dtype=np.float32)
        if reusable_base_vectors is not None and len(reusable_base_vectors) != len(paths):
            raise ValueError("Reusable feature-vector count does not match paths")
        audios = [load_audio(path) for path in paths]
        mert = self.mert_features_many(
            audios,
            window_batch_size=window_batch_size,
        )
        dsp_dimension = int(self.metadata["dsp_dimension"])
        dsp_rows: list[np.ndarray] = []
        for index, audio in enumerate(audios):
            reusable = (
                None if reusable_base_vectors is None else reusable_base_vectors[index]
            )
            if reusable is None:
                dsp_rows.append(dsp_features(audio))
                continue
            vector = np.asarray(reusable, dtype=np.float32)
            if vector.ndim != 1 or vector.size < dsp_dimension:
                raise RuntimeError("Invalid reusable base feature vector")
            dsp_rows.append(vector[-dsp_dimension:])
        dsp = np.stack(dsp_rows, axis=0)
        vectors = np.concatenate([mert, dsp], axis=1).astype(
            np.float32,
            copy=False,
        )
        if vectors.shape != (len(paths), self.feature_dimension):
            raise RuntimeError(
                "Invalid combined feature matrix: "
                f"expected {(len(paths), self.feature_dimension)}, "
                f"got {vectors.shape}."
            )
        if not np.isfinite(vectors).all():
            raise RuntimeError("Combined feature matrix contains non-finite values.")
        return vectors

    def feature_vectors_many(
        self,
        paths: Sequence[Path],
        audio_sha256s: Sequence[str],
        *,
        window_batch_size: int,
    ) -> tuple[np.ndarray, tuple[bool, ...]]:
        """Load cached vectors and batch only unique cache misses.

        The returned matrix is always restored to exact caller order.  Exact
        duplicate audio within one request is extracted at most once.
        """

        if len(paths) != len(audio_sha256s):
            raise ValueError("Path/SHA-256 counts do not match")
        normalized_hashes = tuple(
            canonical_audio_sha256(value) for value in audio_sha256s
        )
        ordered: list[np.ndarray | None] = [None] * len(paths)
        cache_hits = [False] * len(paths)
        vectors_by_hash: dict[str, np.ndarray] = {}
        miss_paths: list[Path] = []
        miss_hashes: list[str] = []

        for index, (path, audio_sha256) in enumerate(
            zip(paths, normalized_hashes, strict=True)
        ):
            existing = vectors_by_hash.get(audio_sha256)
            if existing is not None:
                ordered[index] = existing
                continue
            cached = self.feature_cache.get(
                audio_sha256,
                self.feature_extractor_id,
                self.feature_dimension,
            )
            if cached is not None:
                vectors_by_hash[audio_sha256] = cached
                ordered[index] = cached
                cache_hits[index] = True
                continue
            # A later duplicate SHA will reuse this newly extracted vector.
            if audio_sha256 not in miss_hashes:
                miss_paths.append(path)
                miss_hashes.append(audio_sha256)

        if miss_paths:
            reusable_base_vectors: list[np.ndarray | None] | None = None
            if (
                self.reusable_base_feature_extractor_id is not None
                and self.reusable_base_feature_dimension is not None
            ):
                reusable_base_vectors = [
                    self.feature_cache.get(
                        audio_sha256,
                        self.reusable_base_feature_extractor_id,
                        self.reusable_base_feature_dimension,
                    )
                    for audio_sha256 in miss_hashes
                ]
            extracted = self._extract_feature_vectors(
                miss_paths,
                window_batch_size=window_batch_size,
                reusable_base_vectors=reusable_base_vectors,
            )
            # All extraction and validation finished successfully before this
            # single atomic cache write.  A failed batch stores no partial row.
            self.feature_cache.put_many(
                tuple(
                    (audio_sha256, self.feature_extractor_id, vector)
                    for audio_sha256, vector in zip(
                        miss_hashes,
                        extracted,
                        strict=True,
                    )
                ),
                expected_dimension=self.feature_dimension,
            )
            for audio_sha256, vector in zip(
                miss_hashes,
                extracted,
                strict=True,
            ):
                vectors_by_hash[audio_sha256] = vector

        for index, audio_sha256 in enumerate(normalized_hashes):
            if ordered[index] is None:
                ordered[index] = vectors_by_hash[audio_sha256]
        matrix = np.stack(ordered, axis=0).astype(np.float32, copy=False)
        if matrix.shape != (len(paths), self.feature_dimension):
            raise RuntimeError("Feature-cache result order/dimension is invalid")
        return matrix, tuple(cache_hits)

    def classify_many(
        self,
        paths: Sequence[Path],
        audio_sha256s: Sequence[str],
        *,
        window_batch_size: int,
    ) -> list[dict]:
        if not paths:
            return []
        started = time.perf_counter()
        vectors, cache_hits = self.feature_vectors_many(
            paths,
            audio_sha256s,
            window_batch_size=window_batch_size,
        )
        # Preserve the exact historical one-row sklearn inference path.  MERT
        # dominates runtime, while doing the tiny linear head per row avoids
        # BLAS batch-shape rounding becoming another source of score drift.
        probabilities = np.concatenate(
            [self.classifier.predict_proba(vector[None, :]) for vector in vectors],
            axis=0,
        )
        if probabilities.shape[0] != len(paths):
            raise RuntimeError("Classifier batch output is not aligned with its inputs.")
        elapsed = time.perf_counter() - started
        per_item_elapsed = elapsed / len(paths)
        results = [
            {
                **self._classification_result(
                path,
                probability,
                elapsed_seconds=per_item_elapsed,
                ),
                "feature_cache_hit": cache_hit,
            }
            for path, probability, cache_hit in zip(
                paths,
                probabilities,
                cache_hits,
                strict=True,
            )
        ]
        return results

    def classify(self, path: Path, audio_sha256: str) -> dict:
        return self.classify_many(
            [path],
            [audio_sha256],
            window_batch_size=1,
        )[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--artifact",
        type=Path,
        default=PROTOTYPE_ROOT / "models" / "layer_roles_v2.joblib",
    )
    parser.add_argument(
        "--hf-cache-dir", type=Path, default=DEFAULT_HF_HOME
    )
    parser.add_argument(
        "--feature-cache",
        type=Path,
        default=default_feature_cache_path(),
    )
    parser.add_argument(
        "--device", choices=("auto", "cpu", "mps"), default="cpu"
    )
    parser.add_argument("--window-batch-size", type=int, default=4)
    args = parser.parse_args()
    if args.window_batch_size < 1:
        parser.error("--window-batch-size must be at least one")

    runtime = Runtime(
        args.artifact,
        args.hf_cache_dir,
        args.feature_cache,
        args.device,
    )
    _emit(
        {
            "event": "ready",
            "model_version": runtime.metadata["version"],
            "classes": runtime.metadata["classes"],
            "lazy_mert": True,
            "feature_extractor_id": runtime.feature_extractor_id,
            "feature_dimension": runtime.feature_dimension,
            "head_id": runtime.head_id,
            "feature_cache_enabled": runtime.feature_cache.enabled,
        }
    )
    try:
        for raw_line in sys.stdin:
            try:
                request = json.loads(raw_line)
                request_id = request.get("id")
                command = request.get("command")
                if command == "shutdown":
                    _emit({"id": request_id, "ok": True})
                    return
                if command == "metadata":
                    _emit(
                        {
                            "id": request_id,
                            "ok": True,
                            "metadata": runtime.metadata,
                        }
                    )
                    continue
                if command == "classify_many":
                    raw_items = request.get("items")
                    if not isinstance(raw_items, list) or not raw_items:
                        raise ValueError(
                            "classify_many requires a non-empty items list"
                        )
                    if any(not isinstance(item, dict) for item in raw_items):
                        raise ValueError("classify_many items must be objects")
                    paths = [
                        Path(item["path"]).expanduser().resolve()
                        for item in raw_items
                    ]
                    audio_sha256s = [
                        canonical_audio_sha256(item["sha256"])
                        for item in raw_items
                    ]
                    if any(not path.is_file() for path in paths):
                        missing = next(
                            path for path in paths if not path.is_file()
                        )
                        raise FileNotFoundError(missing)
                    _emit(
                        {
                            "id": request_id,
                            "ok": True,
                            "results": runtime.classify_many(
                                paths,
                                audio_sha256s,
                                window_batch_size=args.window_batch_size,
                            ),
                        }
                    )
                    continue
                if command != "classify":
                    raise ValueError(f"Unsupported command: {command!r}")
                path = Path(request["path"]).expanduser().resolve()
                audio_sha256 = canonical_audio_sha256(request["sha256"])
                if not path.is_file():
                    raise FileNotFoundError(path)
                _emit(
                    {
                        "id": request_id,
                        "ok": True,
                        "result": runtime.classify(path, audio_sha256),
                    }
                )
            except Exception as error:
                traceback.print_exc(file=sys.stderr)
                _emit(
                    {
                        "id": (
                            request.get("id")
                            if "request" in locals()
                            else None
                        ),
                        "ok": False,
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
    finally:
        runtime.feature_cache.close()


if __name__ == "__main__":
    main()
