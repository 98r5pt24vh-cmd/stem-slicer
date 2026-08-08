"""Sample-accurate PCM renderer with one final MP3 encode per output.

The renderer keeps transformed audio as floating-point PCM through fitting,
peak protection, mixing, and sequence assembly.  The single primary master
contains the mixed loop followed by ``gap + stem`` for every selected layer.
That master and every individual stem are each encoded exactly once as MP3 CBR
320 kb/s.  It never calls ``audio_convert.convert_audio`` because that function
would transform and encode individual intermediates before the mix,
introducing avoidable lossy round trips.

The transform backend is injectable.  ``BungeePCMBackend`` is the functional
default and reuses Stem Slicer's bundled FFmpeg/Bungee executables while
returning PCM in memory.  Tests and future cached engines can provide the same
small ``transform`` interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Callable, Protocol, Sequence
import wave

import numpy as np
import numpy.typing as npt

from generation_policy import (
    GenerationPlan,
    SelectedLayer,
    selected_source_signature,
)


RENDERER_VERSION = "generate-mp3-320-sequence-v3"
OUTPUT_CODEC = "libmp3lame"
OUTPUT_BITRATE_BPS = 320_000
WAVEFORM_BINS = 110
LAYER_NORMALIZATION_TARGET_DBFS = -1.0
LAYER_NORMALIZATION_MAX_BOOST_DB = 18.0
LAYER_NORMALIZATION_SILENCE_FLOOR_DBFS = -60.0


class GenerationRenderError(RuntimeError):
    """Raised when a generation cannot be rendered safely."""


class PCMTransformBackend(Protocol):
    """Transform one source layer and return float PCM.

    Returned arrays may be ``(frames,)`` mono or ``(frames, channels)``.  The
    renderer normalizes channel layout and fits only the *tail* to the exact
    timeline length, preserving any leading silence.
    """

    def transform(
        self,
        selection: SelectedLayer,
        *,
        target_bpm: float,
        sample_rate: int,
        channels: int,
    ) -> npt.NDArray[np.floating]:
        ...


class FinalAudioEncoder(Protocol):
    """Encode one already-rendered PCM output without transforming it again."""

    def encode(
        self,
        destination: Path,
        audio: npt.NDArray[np.float32],
        *,
        sample_rate: int,
        bitrate_bps: int,
    ) -> None:
        ...


@dataclass(frozen=True)
class TimelinePlan:
    sample_rate: int
    target_bpm: float
    loop_bars: int
    gap_bars: int
    loop_frames: int
    gap_frames: int

    @classmethod
    def create(
        cls,
        *,
        sample_rate: int,
        target_bpm: float,
        loop_bars: int,
        gap_bars: int = 2,
    ) -> "TimelinePlan":
        if int(sample_rate) <= 0:
            raise GenerationRenderError("Sample rate must be positive")
        if not math.isfinite(float(target_bpm)) or float(target_bpm) <= 0:
            raise GenerationRenderError("Target BPM must be positive")
        if int(loop_bars) <= 0:
            raise GenerationRenderError("Loop bars must be positive")
        if int(gap_bars) < 0:
            raise GenerationRenderError("Gap bars cannot be negative")
        return cls(
            sample_rate=int(sample_rate),
            target_bpm=float(target_bpm),
            loop_bars=int(loop_bars),
            gap_bars=int(gap_bars),
            loop_frames=_frames_for_bars(sample_rate, target_bpm, loop_bars),
            gap_frames=_frames_for_bars(sample_rate, target_bpm, gap_bars),
        )

    def presentation_frames(self, stem_count: int) -> int:
        """Frames for ``master + [gap + stem] * N`` (no trailing gap)."""

        if stem_count < 0:
            raise GenerationRenderError("Stem count cannot be negative")
        return self.loop_frames * (stem_count + 1) + self.gap_frames * stem_count


@dataclass(frozen=True)
class RenderRequest:
    plan: GenerationPlan
    output_root: Path
    generation_name: str = "Generated Loop"
    sample_rate: int = 48_000
    channels: int = 2
    gap_bars: int = 2
    headroom_db: float = -1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_root", Path(self.output_root))
        if not self.plan.selections:
            raise GenerationRenderError("A generation plan must contain at least one stem")
        if int(self.channels) not in (1, 2):
            raise GenerationRenderError("The prototype renderer supports mono or stereo output")
        if not math.isfinite(float(self.headroom_db)) or float(self.headroom_db) > 0:
            raise GenerationRenderError("Headroom must be a finite value at or below 0 dBFS")
        if not str(self.generation_name).strip():
            raise GenerationRenderError("Generation name cannot be empty")


@dataclass(frozen=True)
class StemRenderResult:
    selection: SelectedLayer
    output_path: Path
    source_peak: float
    rendered_peak: float
    protection_gain_db: float
    waveform_peaks: tuple[float, ...]


@dataclass(frozen=True)
class RenderResult:
    output_directory: Path
    master_path: Path
    stem_results: tuple[StemRenderResult, ...]
    presentation_path: Path
    manifest_path: Path
    timeline: TimelinePlan
    master_source_peak: float
    master_peak: float
    master_gain_db: float
    master_waveform_peaks: tuple[float, ...]
    presentation_waveform_peaks: tuple[float, ...]
    stem_audio_pcm: tuple[npt.NDArray[np.float32], ...] = field(
        repr=False,
        compare=False,
    )

    @property
    def stem_paths(self) -> tuple[Path, ...]:
        return tuple(item.output_path for item in self.stem_results)


def _frames_for_bars(sample_rate: int, bpm: float, bars: int) -> int:
    """Round one exact 4/4 duration to the nearest sample.

    ``Fraction(str(bpm))`` avoids accumulating binary floating-point error
    across the master, gaps, and stem segments.
    """

    if bars == 0:
        return 0
    exact = Fraction(int(sample_rate) * 60 * 4 * int(bars), 1) / Fraction(str(float(bpm)))
    return int(exact + Fraction(1, 2))


def _hidden_process_kwargs() -> dict[str, int]:
    if os.name != "nt":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


class BungeePCMBackend:
    """Decode -> Bungee -> PCM backend with no intermediate lossy encoding."""

    def __init__(
        self,
        *,
        ffmpeg: str | os.PathLike[str] | None = None,
        bungee: str | os.PathLike[str] | None = None,
    ) -> None:
        self._ffmpeg = str(ffmpeg) if ffmpeg else None
        self._bungee = str(bungee) if bungee else None

    def _executables(self) -> tuple[str, str]:
        from audio_convert import _find_bungee
        from engine import find_ffmpeg

        return self._ffmpeg or find_ffmpeg(), _find_bungee(self._bungee)

    @staticmethod
    def _run(command: Sequence[str], *, capture_stdout: bool = False) -> bytes:
        try:
            completed = subprocess.run(
                list(command),
                check=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                **_hidden_process_kwargs(),
            )
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.decode("utf-8", errors="replace").strip()
            raise GenerationRenderError(
                f"Audio transform command failed ({exc.returncode}): {detail}"
            ) from exc
        return completed.stdout or b""

    @classmethod
    def _decode_float(
        cls,
        ffmpeg: str,
        source: Path,
        *,
        sample_rate: int,
        channels: int,
    ) -> npt.NDArray[np.float32]:
        raw = cls._run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-i",
                str(source),
                "-vn",
                "-ar",
                str(sample_rate),
                "-ac",
                str(channels),
                "-c:a",
                "pcm_f32le",
                "-f",
                "f32le",
                "-",
            ],
            capture_stdout=True,
        )
        values = np.frombuffer(raw, dtype="<f4")
        if values.size == 0:
            raise GenerationRenderError(f"Decoded audio is empty: {source}")
        if values.size % channels:
            raise GenerationRenderError(f"Decoded PCM has an invalid channel layout: {source}")
        return values.reshape((-1, channels)).copy()

    def transform(
        self,
        selection: SelectedLayer,
        *,
        target_bpm: float,
        sample_rate: int,
        channels: int,
    ) -> npt.NDArray[np.float32]:
        ffmpeg, bungee = self._executables()
        source = selection.candidate.path
        if (
            math.isclose(selection.speed_ratio, 1.0, rel_tol=0.0, abs_tol=1e-12)
            and selection.semitones == 0
        ):
            return self._decode_float(
                ffmpeg,
                source,
                sample_rate=sample_rate,
                channels=channels,
            )

        with tempfile.TemporaryDirectory(prefix="stem-slicer-generate-") as work:
            work_path = Path(work)
            decoded = work_path / "decoded.wav"
            converted = work_path / "converted.wav"
            self._run(
                [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-i",
                    str(source),
                    "-vn",
                    "-ar",
                    str(sample_rate),
                    "-ac",
                    str(channels),
                    "-c:a",
                    "pcm_f32le",
                    str(decoded),
                ]
            )
            # A keyless selection is guaranteed to carry semitones == 0 by the
            # policy; the backend never infers or changes that decision.
            self._run(
                [
                    bungee,
                    "--speed",
                    f"{float(target_bpm) / selection.candidate.source_bpm:.12g}",
                    "--pitch",
                    str(selection.semitones),
                    str(decoded),
                    str(converted),
                ]
            )
            return self._decode_float(
                ffmpeg,
                converted,
                sample_rate=sample_rate,
                channels=channels,
            )


def _normalise_channels(
    audio: npt.ArrayLike,
    channels: int,
) -> npt.NDArray[np.float32]:
    result = np.asarray(audio, dtype=np.float32)
    if result.ndim == 1:
        result = result[:, np.newaxis]
    if result.ndim != 2:
        raise GenerationRenderError("Transform backend must return frames or frames x channels")
    if result.shape[0] == 0:
        raise GenerationRenderError("Transform backend returned empty audio")
    if not np.isfinite(result).all():
        raise GenerationRenderError("Transform backend returned NaN or infinite samples")
    if result.shape[1] == channels:
        return np.ascontiguousarray(result)
    if result.shape[1] == 1 and channels == 2:
        return np.repeat(result, 2, axis=1)
    if channels == 1:
        return np.mean(result, axis=1, keepdims=True, dtype=np.float32)
    raise GenerationRenderError(
        f"Cannot map {result.shape[1]} input channels to {channels} output channels"
    )


def _fit_tail(
    audio: npt.NDArray[np.float32],
    frames: int,
) -> npt.NDArray[np.float32]:
    """Crop or pad only at the end, preserving source time zero."""

    if audio.shape[0] >= frames:
        return np.ascontiguousarray(audio[:frames])
    padding = np.zeros((frames - audio.shape[0], audio.shape[1]), dtype=np.float32)
    return np.concatenate((audio, padding), axis=0)


def _linear_to_db(gain: float) -> float:
    return -math.inf if gain <= 0 else 20.0 * math.log10(gain)


def _peak_protect(
    audio: npt.NDArray[np.float32],
    *,
    ceiling: float,
) -> tuple[npt.NDArray[np.float32], float, float, float]:
    source_peak = float(np.max(np.abs(audio), initial=0.0))
    gain = min(1.0, ceiling / source_peak) if source_peak > 0 else 1.0
    protected = np.asarray(audio * gain, dtype=np.float32)
    rendered_peak = float(np.max(np.abs(protected), initial=0.0))
    return protected, source_peak, rendered_peak, _linear_to_db(gain)


def _peak_normalize(
    audio: npt.NDArray[np.float32],
    *,
    target_dbfs: float = LAYER_NORMALIZATION_TARGET_DBFS,
) -> tuple[npt.NDArray[np.float32], float, float, float]:
    """Peak-normalize one explicitly opted-in layer to a safe target."""

    source_peak = float(np.max(np.abs(audio), initial=0.0))
    target_peak = 10.0 ** (float(target_dbfs) / 20.0)
    silence_floor = 10.0 ** (LAYER_NORMALIZATION_SILENCE_FLOOR_DBFS / 20.0)
    if source_peak < silence_floor:
        return np.asarray(audio, dtype=np.float32), source_peak, source_peak, 0.0
    desired_gain = target_peak / source_peak
    maximum_boost = 10.0 ** (LAYER_NORMALIZATION_MAX_BOOST_DB / 20.0)
    requested_gain = min(desired_gain, maximum_boost)
    boosted = np.asarray(audio * requested_gain, dtype=np.float32)
    protected, _boosted_peak, rendered_peak, protection_db = _peak_protect(
        boosted,
        ceiling=target_peak,
    )
    total_gain = requested_gain * (10.0 ** (protection_db / 20.0))
    return protected, source_peak, rendered_peak, _linear_to_db(total_gain)


def _render_selected_audio(
    selection: SelectedLayer,
    *,
    backend: PCMTransformBackend,
    target_bpm: float,
    sample_rate: int,
    channels: int,
    frames: int,
) -> tuple[npt.NDArray[np.float32], float, float, float]:
    """Render one selection from its source with all current card controls."""

    transformed = backend.transform(
        selection,
        target_bpm=target_bpm,
        sample_rate=sample_rate,
        channels=channels,
    )
    channel_normalized = _normalise_channels(transformed, channels)
    fitted = _fit_tail(channel_normalized, frames)
    if selection.normalization_enabled:
        return _peak_normalize(fitted)
    return _peak_protect(fitted, ceiling=1.0)


def _selected_source_key_parts(
    selection: SelectedLayer,
) -> tuple[str | None, str | None]:
    if not selection.candidate.key_sensitive:
        return (
            selection.candidate.scanned_key or selection.candidate.source_key,
            selection.candidate.scanned_mode or selection.candidate.source_mode,
        )
    signature = selected_source_signature(selection)
    return signature.tonic, signature.mode


def _safe_stem(value: str, fallback: str) -> str:
    text = re.sub(r"[^\w.-]+", "_", str(value).strip(), flags=re.UNICODE).strip("._")
    return text or fallback


def _create_unique_run_directory(root: Path, name: str, seed: int) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    base = _safe_stem(name, "Generated_Loop")
    candidate = root / f"{base}_seed-{seed}"
    suffix = 2
    while True:
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            candidate = root / f"{base}_seed-{seed}_{suffix:02d}"
            suffix += 1


def _write_pcm16_wav(
    destination: Path,
    audio: npt.NDArray[np.float32],
    *,
    sample_rate: int,
) -> None:
    """Write one internal PCM16 staging file for the final encoder."""

    if destination.exists():
        raise GenerationRenderError(f"Refusing to overwrite an existing output: {destination}")
    clipped = np.clip(audio, -1.0, 1.0)
    pcm = np.rint(clipped * 32767.0).astype("<i2", copy=False)
    with wave.open(str(destination), "wb") as output:
        output.setnchannels(int(audio.shape[1]))
        output.setsampwidth(2)
        output.setframerate(int(sample_rate))
        output.writeframes(pcm.tobytes(order="C"))


class FFmpegMP3Encoder:
    """Encode final PCM through the bundled FFmpeg/libmp3lame exactly once."""

    def __init__(self, ffmpeg: str | os.PathLike[str] | None = None) -> None:
        self._ffmpeg = str(ffmpeg) if ffmpeg else None

    def _executable(self) -> str:
        if self._ffmpeg:
            return self._ffmpeg
        from engine import find_ffmpeg

        executable = find_ffmpeg()
        if not executable:
            raise GenerationRenderError("FFmpeg was not found for final MP3 encoding")
        return executable

    def encode(
        self,
        destination: Path,
        audio: npt.NDArray[np.float32],
        *,
        sample_rate: int,
        bitrate_bps: int,
    ) -> None:
        if destination.suffix.casefold() != ".mp3":
            raise GenerationRenderError(
                f"Final audio destination must be MP3: {destination}"
            )
        if destination.exists():
            raise GenerationRenderError(
                f"Refusing to overwrite an existing output: {destination}"
            )
        if int(bitrate_bps) != OUTPUT_BITRATE_BPS:
            raise GenerationRenderError(
                f"Generate outputs require exactly {OUTPUT_BITRATE_BPS} bit/s"
            )

        # Keep the staging WAV beside the destination so the final atomic move
        # cannot cross filesystems.  The WAV is internal and never enters the
        # returned output contract.
        with tempfile.TemporaryDirectory(
            prefix=".stem-slicer-mp3-", dir=str(destination.parent)
        ) as temporary:
            temporary_root = Path(temporary)
            pcm_path = temporary_root / "source.wav"
            encoded_path = temporary_root / "encoded.mp3"
            _write_pcm16_wav(pcm_path, audio, sample_rate=sample_rate)
            command = [
                self._executable(),
                "-n",
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-i",
                str(pcm_path),
                "-vn",
                "-map_metadata",
                "-1",
                "-c:a",
                OUTPUT_CODEC,
                "-b:a",
                f"{OUTPUT_BITRATE_BPS // 1000}k",
                "-write_xing",
                "1",
                str(encoded_path),
            ]
            try:
                completed = subprocess.run(
                    command,
                    check=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    **_hidden_process_kwargs(),
                )
            except (OSError, subprocess.CalledProcessError) as exc:
                stderr = getattr(exc, "stderr", b"") or b""
                detail = stderr.decode("utf-8", errors="replace").strip()
                suffix = f": {detail}" if detail else ""
                raise GenerationRenderError(
                    f"Final MP3 encoding failed{suffix}"
                ) from exc
            if completed.returncode != 0 or not encoded_path.is_file():
                raise GenerationRenderError("Final MP3 encoder produced no output")
            if encoded_path.stat().st_size <= 0:
                raise GenerationRenderError("Final MP3 encoder produced an empty output")
            encoded_path.replace(destination)


def _waveform_peaks(
    audio: npt.NDArray[np.float32],
    bins: int = WAVEFORM_BINS,
) -> tuple[float, ...]:
    """Derive UI peaks from pre-encode PCM, avoiding a synchronous MP3 decode."""

    frame_count = int(audio.shape[0])
    if frame_count <= 0 or bins <= 0:
        return (0.0,)
    step = max(1, math.ceil(frame_count / int(bins)))
    return tuple(
        min(1.0, float(np.max(np.abs(audio[start : start + step]), initial=0.0)))
        for start in range(0, frame_count, step)
    ) or (0.0,)


def _write_manifest(destination: Path, payload: dict) -> None:
    if destination.exists():
        raise GenerationRenderError(f"Refusing to overwrite an existing output: {destination}")
    with destination.open("x", encoding="utf-8") as output:
        json.dump(payload, output, indent=2, sort_keys=True, ensure_ascii=False)
        output.write("\n")


def render_generation(
    request: RenderRequest,
    *,
    backend: PCMTransformBackend | None = None,
    encoder: FinalAudioEncoder | None = None,
    progress: Callable[[str, int, int], None] | None = None,
) -> RenderResult:
    """Transform, mix, and encode a complete generated-loop package."""

    transform_backend = backend or BungeePCMBackend()
    final_encoder = encoder or FFmpegMP3Encoder()
    timeline = TimelinePlan.create(
        sample_rate=request.sample_rate,
        target_bpm=request.plan.request.target_bpm,
        loop_bars=request.plan.request.bars,
        gap_bars=request.gap_bars,
    )
    run_directory = _create_unique_run_directory(
        request.output_root,
        request.generation_name,
        request.plan.request.seed,
    )
    total = len(request.plan.selections)
    stem_audio: list[npt.NDArray[np.float32]] = []
    stem_metrics: list[tuple[float, float, float]] = []

    for index, selection in enumerate(request.plan.selections, start=1):
        if progress:
            progress(f"Transforming {selection.category}", index, total)
        protected, source_peak, rendered_peak, gain_db = _render_selected_audio(
            selection,
            backend=transform_backend,
            target_bpm=request.plan.request.target_bpm,
            sample_rate=request.sample_rate,
            channels=request.channels,
            frames=timeline.loop_frames,
        )
        stem_audio.append(protected)
        stem_metrics.append((source_peak, rendered_peak, gain_db))

    stacked = np.stack(stem_audio, axis=0).astype(np.float64, copy=False)
    raw_master = np.sum(stacked, axis=0, dtype=np.float64)
    ceiling = 10.0 ** (float(request.headroom_db) / 20.0)
    master, master_source_peak, master_peak, master_gain_db = _peak_protect(
        np.asarray(raw_master, dtype=np.float32),
        ceiling=ceiling,
    )

    base = _safe_stem(request.generation_name, "Generated_Loop")
    master_path = run_directory / f"00_{base}_Master.mp3"

    stem_results: list[StemRenderResult] = []
    for index, (selection, audio, metrics) in enumerate(
        zip(request.plan.selections, stem_audio, stem_metrics),
        start=1,
    ):
        category = _safe_stem(selection.category, "Layer")
        destination = run_directory / f"{index:02d}_{category}.mp3"
        final_encoder.encode(
            destination,
            audio,
            sample_rate=request.sample_rate,
            bitrate_bps=OUTPUT_BITRATE_BPS,
        )
        stem_results.append(
            StemRenderResult(
                selection=selection,
                output_path=destination,
                source_peak=metrics[0],
                rendered_peak=metrics[1],
                protection_gain_db=metrics[2],
                waveform_peaks=_waveform_peaks(audio),
            )
        )

    silence = np.zeros((timeline.gap_frames, request.channels), dtype=np.float32)
    presentation_parts: list[npt.NDArray[np.float32]] = [master]
    for audio in stem_audio:
        presentation_parts.extend((silence, audio))
    presentation = np.concatenate(presentation_parts, axis=0)
    expected_presentation_frames = timeline.presentation_frames(len(stem_audio))
    if presentation.shape[0] != expected_presentation_frames:
        raise GenerationRenderError(
            "Internal presentation timeline does not match its sample-accurate plan"
        )
    master_peaks = _waveform_peaks(presentation)
    final_encoder.encode(
        master_path,
        presentation,
        sample_rate=request.sample_rate,
        bitrate_bps=OUTPUT_BITRATE_BPS,
    )
    # Compatibility alias only: there is deliberately no second presentation
    # file because the primary master already contains the complete sequence.
    presentation_path = master_path

    manifest_path = run_directory / "generation.json"
    manifest = {
        "schema_version": 3,
        "renderer_version": RENDERER_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "seed": request.plan.request.seed,
        "recipe": list(request.plan.request.categories),
        "target": {
            "bpm": request.plan.request.target_bpm,
            "key": request.plan.target_key,
            "bars": request.plan.request.bars,
        },
        "render": {
            "format": "MP3",
            "codec": OUTPUT_CODEC,
            "bitrate_bps": OUTPUT_BITRATE_BPS,
            "bitrate_mode": "CBR",
            "intermediate_audio": "float PCM",
            "no_intermediate_lossy_encode": True,
            "lossy_encodes_per_output": 1,
            "timeline_frame_domain": "pre-encode PCM",
            "primary_master_content": "loop_mix_then_gap_and_each_stem",
            "loop_only_output": False,
            "presentation_is_master": True,
            "sample_rate": request.sample_rate,
            "channels": request.channels,
            "loop_frames": timeline.loop_frames,
            "gap_bars": timeline.gap_bars,
            "gap_frames": timeline.gap_frames,
            "presentation_frames": presentation.shape[0],
            "presentation_order": [
                "master",
                *[
                    item
                    for index in range(len(stem_audio))
                    for item in (f"silence_{timeline.gap_bars}_bars", f"stem_{index + 1}")
                ],
            ],
            "headroom_db": request.headroom_db,
            "master_source_peak": master_source_peak,
            "master_peak": master_peak,
            "master_gain_db": master_gain_db,
        },
        "outputs": {
            "master": master_path.name,
            "presentation": presentation_path.name,
            "stems": [item.output_path.name for item in stem_results],
        },
        "layers": [
            {
                "slot_index": item.selection.slot_index,
                "category": item.selection.category,
                "identity": item.selection.candidate.identity,
                "locked": (
                    request.plan.request.locked_identities_by_slot[
                        item.selection.slot_index
                    ]
                    == item.selection.candidate.identity
                ),
                "source_path": str(item.selection.candidate.path),
                "source_loop_id": item.selection.candidate.source_loop_id,
                "label_source": item.selection.label_source,
                "confidence": item.selection.confidence,
                "source_bpm": item.selection.candidate.source_bpm,
                "source_key": _selected_source_key_parts(item.selection)[0],
                "source_mode": _selected_source_key_parts(item.selection)[1],
                "alternate_source_key": (
                    item.selection.candidate.alternate_scanned_key
                ),
                "alternate_source_mode": (
                    item.selection.candidate.alternate_scanned_mode
                ),
                "source_key_rank": item.selection.source_key_rank,
                "alternate_key_used": item.selection.source_key_rank == 2,
                "manual_pitch_semitones": (
                    item.selection.manual_pitch_semitones
                ),
                "normalization_enabled": (
                    item.selection.normalization_enabled
                ),
                "normalization_target_dbfs": (
                    LAYER_NORMALIZATION_TARGET_DBFS
                    if item.selection.normalization_enabled
                    else None
                ),
                "key_top1_probability": (
                    item.selection.candidate.key_top1_probability
                ),
                "key_top2_probability": (
                    item.selection.candidate.key_top2_probability
                ),
                "filename_key": item.selection.candidate.source_key,
                "filename_mode": item.selection.candidate.source_mode,
                "key_confidence_margin": (
                    item.selection.candidate.key_confidence_margin
                ),
                "key_confidence_status": (
                    item.selection.candidate.key_confidence_status
                ),
                "target_bpm": request.plan.request.target_bpm,
                "target_key": request.plan.target_key,
                "speed_ratio": item.selection.speed_ratio,
                "semitones": item.selection.semitones,
                "key_sensitive": item.selection.candidate.key_sensitive,
                "reused_source_loop": item.selection.reused_source_loop,
                "transform_cost": item.selection.transform_cost,
                "selection_score": item.selection.selection_score,
                "output": item.output_path.name,
                "source_peak": item.source_peak,
                "rendered_peak": item.rendered_peak,
                "protection_gain_db": item.protection_gain_db,
            }
            for item in stem_results
        ],
    }
    _write_manifest(manifest_path, manifest)
    if progress:
        progress("Generation complete", total, total)

    return RenderResult(
        output_directory=run_directory,
        master_path=master_path,
        stem_results=tuple(stem_results),
        presentation_path=presentation_path,
        manifest_path=manifest_path,
        timeline=timeline,
        master_source_peak=master_source_peak,
        master_peak=master_peak,
        master_gain_db=master_gain_db,
        master_waveform_peaks=master_peaks,
        presentation_waveform_peaks=master_peaks,
        stem_audio_pcm=tuple(stem_audio),
    )


def rerender_selected_layer(
    request: RenderRequest,
    existing: RenderResult,
    *,
    slot_index: int,
    identity: str | None = None,
    backend: PCMTransformBackend | None = None,
    encoder: FinalAudioEncoder | None = None,
    progress: Callable[[str, int, int], None] | None = None,
) -> RenderResult:
    """Rerender one card from source using its current key/pitch/gain state.

    The unchanged stems are reused as lossless in-memory PCM from the initial
    render.  Only the targeted stem and the primary Full Loop are encoded
    again; the other individual MP3 files are left byte-for-byte untouched.
    """

    if existing.output_directory != existing.master_path.parent:
        raise GenerationRenderError("The existing render package is inconsistent")
    if len(existing.stem_audio_pcm) != len(existing.stem_results):
        raise GenerationRenderError("Lossless stem state is unavailable")
    if len(request.plan.selections) != len(existing.stem_results):
        raise GenerationRenderError("The updated plan no longer matches the render")

    normalized_identity = str(identity or "").strip()
    target_offset = next(
        (
            offset
            for offset, selection in enumerate(request.plan.selections)
            if (
                selection.candidate.identity == normalized_identity
                if normalized_identity
                else selection.slot_index == int(slot_index)
            )
        ),
        None,
    )
    if target_offset is None:
        raise GenerationRenderError(
            f"No rendered layer exists at slot {int(slot_index) + 1}"
        )
    selection = request.plan.selections[target_offset]
    transform_backend = backend or BungeePCMBackend()
    final_encoder = encoder or FFmpegMP3Encoder()
    timeline = existing.timeline
    if progress:
        progress(f"Updating {selection.category}", 0, 2)
    updated_audio, source_peak, rendered_peak, protection_gain_db = (
        _render_selected_audio(
        selection,
        backend=transform_backend,
        target_bpm=request.plan.request.target_bpm,
        sample_rate=timeline.sample_rate,
        channels=request.channels,
        frames=timeline.loop_frames,
        )
    )

    stem_audio = list(existing.stem_audio_pcm)
    stem_audio[target_offset] = updated_audio
    stacked = np.stack(stem_audio, axis=0).astype(np.float64, copy=False)
    raw_master = np.sum(stacked, axis=0, dtype=np.float64)
    ceiling = 10.0 ** (float(request.headroom_db) / 20.0)
    master, master_source_peak, master_peak, master_gain_db = _peak_protect(
        np.asarray(raw_master, dtype=np.float32),
        ceiling=ceiling,
    )
    silence = np.zeros((timeline.gap_frames, request.channels), dtype=np.float32)
    presentation_parts: list[npt.NDArray[np.float32]] = [master]
    for audio in stem_audio:
        presentation_parts.extend((silence, audio))
    presentation = np.concatenate(presentation_parts, axis=0)
    if presentation.shape[0] != timeline.presentation_frames(len(stem_audio)):
        raise GenerationRenderError("Updated Full Loop timeline is inconsistent")

    old_stem = existing.stem_results[target_offset]
    new_stem = StemRenderResult(
        selection=selection,
        output_path=old_stem.output_path,
        source_peak=source_peak,
        rendered_peak=rendered_peak,
        protection_gain_db=protection_gain_db,
        waveform_peaks=_waveform_peaks(updated_audio),
    )
    updated_stems = list(existing.stem_results)
    updated_stems[target_offset] = new_stem
    master_peaks = _waveform_peaks(presentation)

    try:
        manifest = json.loads(existing.manifest_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as error:
        raise GenerationRenderError("The existing generation manifest is unreadable") from error
    layers = manifest.get("layers")
    if not isinstance(layers, list) or target_offset >= len(layers):
        raise GenerationRenderError("The existing generation manifest has no matching layer")
    layer_payload = layers[target_offset]
    if not isinstance(layer_payload, dict):
        raise GenerationRenderError("The existing generation layer metadata is invalid")
    source_key, source_mode = _selected_source_key_parts(selection)
    layer_payload.update(
        {
            "source_key": source_key,
            "source_mode": source_mode,
            "source_key_rank": selection.source_key_rank,
            "alternate_key_used": selection.source_key_rank == 2,
            "manual_pitch_semitones": selection.manual_pitch_semitones,
            "normalization_enabled": selection.normalization_enabled,
            "normalization_target_dbfs": (
                LAYER_NORMALIZATION_TARGET_DBFS
                if selection.normalization_enabled
                else None
            ),
            "semitones": selection.semitones,
            "transform_cost": selection.transform_cost,
            "source_peak": source_peak,
            "rendered_peak": rendered_peak,
            "protection_gain_db": protection_gain_db,
        }
    )
    render_payload = manifest.get("render")
    if isinstance(render_payload, dict):
        render_payload.update(
            {
                "master_source_peak": master_source_peak,
                "master_peak": master_peak,
                "master_gain_db": master_gain_db,
            }
        )
    manifest["updated_utc"] = datetime.now(timezone.utc).isoformat()

    with tempfile.TemporaryDirectory(
        prefix=".stem-slicer-layer-update-",
        dir=str(existing.output_directory),
    ) as temporary:
        temporary_root = Path(temporary)
        encoded_stem = temporary_root / old_stem.output_path.name
        encoded_master = temporary_root / existing.master_path.name
        temporary_manifest = temporary_root / existing.manifest_path.name
        final_encoder.encode(
            encoded_stem,
            updated_audio,
            sample_rate=timeline.sample_rate,
            bitrate_bps=OUTPUT_BITRATE_BPS,
        )
        if progress:
            progress("Updating Full Loop", 1, 2)
        final_encoder.encode(
            encoded_master,
            presentation,
            sample_rate=timeline.sample_rate,
            bitrate_bps=OUTPUT_BITRATE_BPS,
        )
        with temporary_manifest.open("x", encoding="utf-8") as output:
            json.dump(manifest, output, indent=2, sort_keys=True, ensure_ascii=False)
            output.write("\n")
        encoded_stem.replace(old_stem.output_path)
        encoded_master.replace(existing.master_path)
        temporary_manifest.replace(existing.manifest_path)

    if progress:
        progress("Layer updated", 2, 2)
    return RenderResult(
        output_directory=existing.output_directory,
        master_path=existing.master_path,
        stem_results=tuple(updated_stems),
        presentation_path=existing.presentation_path,
        manifest_path=existing.manifest_path,
        timeline=timeline,
        master_source_peak=master_source_peak,
        master_peak=master_peak,
        master_gain_db=master_gain_db,
        master_waveform_peaks=master_peaks,
        presentation_waveform_peaks=master_peaks,
        stem_audio_pcm=tuple(stem_audio),
    )


def rerender_alternate_key(
    request: RenderRequest,
    existing: RenderResult,
    *,
    slot_index: int,
    identity: str | None = None,
    backend: PCMTransformBackend | None = None,
    encoder: FinalAudioEncoder | None = None,
    progress: Callable[[str, int, int], None] | None = None,
) -> RenderResult:
    """Backward-compatible alias for the generic targeted card rerender."""

    return rerender_selected_layer(
        request,
        existing,
        slot_index=slot_index,
        identity=identity,
        backend=backend,
        encoder=encoder,
        progress=progress,
    )
