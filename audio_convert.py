"""BPM and key conversion built around FFmpeg and open-source Bungee.

The module deliberately owns no UI state.  It decodes once to a floating-point
WAV, asks Bungee to change speed and pitch together, measures the generated
peak, then performs one final MP3 encode with only the gain required to avoid
clipping.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from typing import Callable

from diagnostics_runtime import get_diagnostics
from engine import find_ffmpeg


PITCH_CLASSES = {
    "C": 0, "B#": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3,
    "E": 4, "FB": 4, "E#": 5, "F": 5, "F#": 6, "GB": 6, "G": 7,
    "G#": 8, "AB": 8, "A": 9, "A#": 10, "BB": 10, "B": 11, "CB": 11,
}


@dataclass(frozen=True)
class ConversionRequest:
    source: Path
    destination: Path
    source_bpm: float
    target_bpm: float | None
    source_key: str
    target_key: str | None


@dataclass(frozen=True)
class ConversionResult:
    output: Path
    semitones: int
    speed_ratio: float
    peak_db: float | None
    gain_db: float


def _hidden_process_kwargs() -> dict:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "startupinfo": startupinfo,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }


def _run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess:
    started = time.perf_counter()
    diagnostics = get_diagnostics()
    try:
        completed = subprocess.run(
            command,
            check=True,
            text=True,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            # Always retain stderr: FFmpeg/Bungee failures in a GUI build have
            # no console and otherwise leave beta testers with no evidence.
            stderr=subprocess.PIPE,
            **_hidden_process_kwargs(),
        )
    except subprocess.CalledProcessError as exc:
        diagnostics.record_subprocess(
            command=command,
            duration=time.perf_counter() - started,
            returncode=exc.returncode,
            stdout=exc.stdout,
            stderr=exc.stderr,
            failed=True,
        )
        diagnostics.exception("audio_conversion_subprocess", exc, command=command)
        raise
    except Exception as exc:
        diagnostics.exception(
            "audio_conversion_subprocess",
            exc,
            command=command,
            duration_seconds=time.perf_counter() - started,
        )
        raise
    diagnostics.record_subprocess(
        command=command,
        duration=time.perf_counter() - started,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    return completed


def _key_parts(key: str) -> tuple[str, bool]:
    """Return ``(tonic, is_minor)`` for long and compact key spellings.

    OpenKeyScan deliberately returns compact minor names such as ``G#m``.
    Conversion also accepts the human-facing ``G# minor`` form used by the
    1.7B interface.
    """
    normalized = key.strip().replace("♯", "#").replace("♭", "b")
    compact = re.fullmatch(r"([A-Ga-g](?:#|b)?)(m)?", normalized)
    if compact:
        return compact.group(1), bool(compact.group(2))
    words = normalized.split()
    if not words:
        raise ValueError(f"Unsupported musical key: {key!r}")
    return words[0], any(word.lower() == "minor" for word in words[1:])


def expanded_key_name(key: str) -> str:
    """Normalize a key to the display/engine form ``C# major`` or ``C# minor``."""
    tonic, is_minor = _key_parts(key)
    return f"{tonic} {'minor' if is_minor else 'major'}"


def _tonic(key: str) -> int:
    tonic, _ = _key_parts(key)
    token = tonic.upper()
    if token not in PITCH_CLASSES:
        raise ValueError(f"Unsupported musical key: {key!r}")
    return PITCH_CLASSES[token]


def target_minor_tonic(target_pair: str) -> int:
    """Return the pitch class used for a major/relative-minor target pair.

    Conversion is interval-only.  A target such as ``C major / A minor`` uses
    A as its minor tonic when the source is minor, matching the product rule
    validated during the prototype phase.
    """
    parts = [part.strip() for part in target_pair.split("/")]
    if len(parts) == 2 and "minor" in parts[1].lower():
        return _tonic(parts[1])
    return _tonic(parts[0])


def shortest_semitone_shift(source_key: str, target_pair: str) -> int:
    source = _tonic(source_key)
    _, source_is_minor = _key_parts(source_key)
    if source_is_minor:
        target = target_minor_tonic(target_pair)
    else:
        target = _tonic(target_pair.split("/")[0])
    delta = (target - source) % 12
    return delta - 12 if delta > 6 else delta


def _find_bungee(explicit: str | os.PathLike[str] | None = None) -> str:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    root = Path(getattr(__import__("sys"), "_MEIPASS", Path(__file__).parent))
    executable = "bungee.exe" if os.name == "nt" else "bungee"
    candidates.extend((root / "bin" / executable, Path(__file__).parent / "bin" / executable))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise FileNotFoundError("Bungee executable is not bundled")


def _peak_db(ffmpeg: str, audio: Path) -> float | None:
    completed = _run([
        ffmpeg, "-hide_banner", "-nostdin", "-i", str(audio),
        "-af", "astats=metadata=0:reset=0", "-f", "null", "-",
    ], capture=True)
    matches = re.findall(r"Peak level dB:\s*(-?inf|[-+0-9.]+)", completed.stderr)
    if not matches or matches[-1] == "-inf":
        return None
    return float(matches[-1])


def convert_audio(
    request: ConversionRequest,
    *,
    bungee: str | os.PathLike[str] | None = None,
    progress: Callable[[str], None] | None = None,
) -> ConversionResult:
    diagnostics = get_diagnostics()
    operation_started = time.perf_counter()
    diagnostics.event(
        "audio_conversion_started",
        file=str(request.source),
        destination=str(request.destination),
        source_bpm=request.source_bpm,
        target_bpm=request.target_bpm,
        source_key=request.source_key,
        target_key=request.target_key,
    )
    effective_bpm = request.target_bpm if request.target_bpm is not None else request.source_bpm
    if request.source_bpm <= 0 or effective_bpm <= 0:
        raise ValueError("BPM values must be positive")
    ffmpeg = find_ffmpeg()
    bungee_executable = _find_bungee(bungee)
    request.destination.parent.mkdir(parents=True, exist_ok=True)
    semitones = shortest_semitone_shift(request.source_key, request.target_key) if request.target_key else 0
    speed = effective_bpm / request.source_bpm

    with tempfile.TemporaryDirectory(prefix="stem-slicer-convert-") as work:
        work_path = Path(work)
        decoded = work_path / "decoded.wav"
        converted = work_path / "converted.wav"
        if progress:
            progress("Decoding audio")
        _run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-i", str(request.source), "-vn", "-c:a", "pcm_f32le", str(decoded),
        ])
        if progress:
            progress("Converting BPM and key")
        _run([
            bungee_executable, "--speed", f"{speed:.12g}", "--pitch", str(semitones),
            str(decoded), str(converted),
        ])
        peak = _peak_db(ffmpeg, converted)
        gain = -max(0.0, peak or 0.0)
        filters = [f"volume={gain:.6f}dB"] if gain < 0 else []
        command = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-i", str(converted), "-vn",
        ]
        if filters:
            command.extend(("-af", ",".join(filters)))
        command.extend(("-c:a", "libmp3lame", "-q:a", "0", str(request.destination)))
        if progress:
            progress("Encoding MP3")
        _run(command)

    result = ConversionResult(request.destination, semitones, speed, peak, gain)
    diagnostics.event(
        "audio_conversion_complete",
        file=str(request.source),
        destination=str(request.destination),
        duration_seconds=time.perf_counter() - operation_started,
        semitones=semitones,
        speed_ratio=speed,
        peak_db=peak,
        gain_db=gain,
    )
    return result
