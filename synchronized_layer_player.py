"""Sample-synchronised preview mixer for generated layer cards."""

from __future__ import annotations

from pathlib import Path
import threading

import numpy as np
import soundfile as sf

from PySide6.QtCore import QIODevice, QObject, QTimer, Signal
from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices


_CHANNELS = 2
_SAMPLE_RATE = 48_000
_CEILING = 10.0 ** (-1.0 / 20.0)


def _decode_layer(path: str) -> tuple[np.ndarray, int]:
    audio, sample_rate = sf.read(
        str(Path(path)),
        dtype="float32",
        always_2d=True,
    )
    if audio.shape[1] == 1:
        audio = np.repeat(audio, _CHANNELS, axis=1)
    elif audio.shape[1] > _CHANNELS:
        audio = audio[:, :_CHANNELS]
    return np.ascontiguousarray(audio, dtype=np.float32), int(sample_rate)


class LayerMixDevice(QIODevice):
    """Infinite looping QIODevice which mixes a mutable set of PCM layers."""

    def __init__(self, layers: dict[str, np.ndarray], parent=None) -> None:
        super().__init__(parent)
        self._layers = dict(layers)
        self._volumes = {path: 1.0 for path in self._layers}
        self._frame_count = max(
            (audio.shape[0] for audio in self._layers.values()),
            default=0,
        )
        self._active: set[str] = set()
        self._crossfades: dict[str, list[object]] = {}
        self._gain_crossfade: list[float | int] | None = None
        self._frame = 0
        self._lock = threading.RLock()
        self._gain = self._full_mix_gain()
        self.open(QIODevice.OpenModeFlag.ReadOnly)

    def _full_mix_gain(self) -> float:
        if self._frame_count <= 0 or not self._layers:
            return 1.0
        mixed = np.zeros((self._frame_count, _CHANNELS), dtype=np.float32)
        for audio in self._layers.values():
            mixed[: audio.shape[0]] += audio
        peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
        return min(1.0, _CEILING / peak) if peak > 0.0 else 1.0

    def activePaths(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(path for path in self._layers if path in self._active)

    def allPaths(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._layers)

    def setActive(self, path: str, active: bool) -> bool:
        with self._lock:
            if path not in self._layers:
                return False
            if active:
                self._active.add(path)
            else:
                self._active.discard(path)
            return True

    def setActivePaths(self, paths) -> None:
        with self._lock:
            self._active = {str(path) for path in paths if str(path) in self._layers}

    def setVolume(self, path: str, gain: float) -> bool:
        """Set one layer's preview gain without replacing or restarting audio."""

        with self._lock:
            path = str(path)
            if path not in self._layers:
                return False
            self._volumes[path] = max(0.0, min(1.0, float(gain)))
            return True

    def replaceLayer(
        self,
        path: str,
        audio: np.ndarray,
        *,
        crossfade_frames: int = 480,
    ) -> bool:
        path = str(path)
        replacement = np.ascontiguousarray(audio, dtype=np.float32)
        if replacement.ndim != 2 or replacement.shape[1] != _CHANNELS:
            return False
        with self._lock:
            previous = self._layers.get(path)
            if previous is None or replacement.shape[0] != self._frame_count:
                return False
            previous_gain = self._gain
            self._layers[path] = replacement
            fade_frames = max(0, int(crossfade_frames))
            if path in self._active and fade_frames:
                self._crossfades[path] = [previous, fade_frames, 0]
            else:
                self._crossfades.pop(path, None)
            self._gain = self._full_mix_gain()
            if fade_frames and previous_gain != self._gain:
                self._gain_crossfade = [
                    previous_gain,
                    self._gain,
                    fade_frames,
                    0,
                ]
            else:
                self._gain_crossfade = None
            return True

    def setPositionRatio(self, ratio: float) -> None:
        with self._lock:
            if self._frame_count <= 0:
                self._frame = 0
            else:
                bounded = max(0.0, min(1.0, float(ratio)))
                self._frame = min(
                    self._frame_count - 1,
                    round(bounded * self._frame_count),
                )

    def positionRatio(self) -> float:
        with self._lock:
            return self._frame / self._frame_count if self._frame_count else 0.0

    def readData(self, maxlen: int) -> bytes:
        frame_bytes = _CHANNELS * np.dtype("<f4").itemsize
        requested_frames = max(0, int(maxlen) // frame_bytes)
        trailing_bytes = max(0, int(maxlen) - requested_frames * frame_bytes)
        if requested_frames <= 0:
            return b"\0" * max(0, int(maxlen))

        with self._lock:
            active = tuple(self._active)
            start = self._frame
            frame_count = self._frame_count
            gain = self._gain
            gain_curve = None

            output = np.zeros((requested_frames, _CHANNELS), dtype=np.float32)
            if frame_count > 0:
                written = 0
                cursor = start
                while written < requested_frames:
                    span = min(requested_frames - written, frame_count - cursor)
                    for path in active:
                        audio = self._layers[path]
                        volume = self._volumes.get(path, 1.0)
                        available = max(0, min(span, audio.shape[0] - cursor))
                        if available:
                            target = output[written : written + available]
                            fade = self._crossfades.get(path)
                            if fade is None:
                                target += (
                                    audio[cursor : cursor + available] * volume
                                )
                            else:
                                previous, total, completed = fade
                                crossfade = min(available, int(total) - int(completed))
                                if crossfade > 0:
                                    alpha = (
                                        np.arange(
                                            int(completed) + 1,
                                            int(completed) + crossfade + 1,
                                            dtype=np.float32,
                                        )
                                        / float(total)
                                    )[:, None]
                                    target[:crossfade] += volume * (
                                        previous[cursor : cursor + crossfade]
                                        * (1.0 - alpha)
                                        + audio[cursor : cursor + crossfade] * alpha
                                    )
                                    fade[2] = int(completed) + crossfade
                                if crossfade < available:
                                    target[crossfade:] += volume * audio[
                                        cursor + crossfade : cursor + available
                                    ]
                                if int(fade[2]) >= int(total):
                                    self._crossfades.pop(path, None)
                    written += span
                    cursor = (cursor + span) % frame_count
                self._frame = cursor

            gain_fade = self._gain_crossfade
            if gain_fade is not None:
                old_gain, new_gain, total, completed = gain_fade
                crossfade = min(
                    requested_frames,
                    int(total) - int(completed),
                )
                gain_curve = np.full(
                    (requested_frames, 1),
                    float(new_gain),
                    dtype=np.float32,
                )
                if crossfade > 0:
                    alpha = (
                        np.arange(
                            int(completed) + 1,
                            int(completed) + crossfade + 1,
                            dtype=np.float32,
                        )
                        / float(total)
                    )[:, None]
                    gain_curve[:crossfade] = (
                        float(old_gain) * (1.0 - alpha)
                        + float(new_gain) * alpha
                    )
                    gain_fade[3] = int(completed) + crossfade
                if int(gain_fade[3]) >= int(total):
                    self._gain_crossfade = None

        if gain_curve is not None:
            output *= gain_curve
        elif gain != 1.0:
            output *= gain
        np.clip(output, -1.0, 1.0, out=output)
        payload = np.asarray(output, dtype="<f4").tobytes()
        return payload + (b"\0" * trailing_bytes)

    def writeData(self, _data) -> int:
        return -1

    def bytesAvailable(self) -> int:
        return 65_536 + super().bytesAvailable()


class SynchronizedLayerPlayer(QObject):
    """One audio clock shared by every active generated-layer card."""

    activePathsChanged = Signal(tuple)
    positionChanged = Signal(float)
    playbackChanged = Signal(bool)
    errorOccurred = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._device: LayerMixDevice | None = None
        self._sink: QAudioSink | None = None
        self._playing = False
        self._stopping = False
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._emit_position)

    def setLayers(self, paths) -> tuple[str, ...]:
        self.stop(reset=True)
        decoded: dict[str, np.ndarray] = {}
        errors: list[str] = []
        for raw_path in paths:
            path = str(raw_path)
            try:
                audio, sample_rate = _decode_layer(path)
                if sample_rate != _SAMPLE_RATE:
                    raise ValueError(
                        f"expected {_SAMPLE_RATE} Hz, received {sample_rate} Hz"
                    )
                decoded[path] = audio
            except Exception as exc:
                errors.append(f"{Path(path).name}: {exc}")
        self._device = LayerMixDevice(decoded, self)
        if errors:
            self.errorOccurred.emit(" · ".join(errors))
        self.activePathsChanged.emit(())
        self.positionChanged.emit(0.0)
        return tuple(decoded)

    def activePaths(self) -> tuple[str, ...]:
        return self._device.activePaths() if self._device is not None else ()

    def allPaths(self) -> tuple[str, ...]:
        return self._device.allPaths() if self._device is not None else ()

    def positionRatio(self) -> float:
        return self._device.positionRatio() if self._device is not None else 0.0

    def isPlaying(self) -> bool:
        return self._playing

    def _create_sink(self) -> QAudioSink | None:
        if self._device is None:
            return None
        audio_format = QAudioFormat()
        audio_format.setSampleRate(_SAMPLE_RATE)
        audio_format.setChannelCount(_CHANNELS)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Float)
        output = QMediaDevices.defaultAudioOutput()
        if output.isNull() or not output.isFormatSupported(audio_format):
            self.errorOccurred.emit("The current audio output cannot play the synchronized preview.")
            return None
        sink = QAudioSink(output, audio_format, self)
        sink.setBufferSize(8192)
        sink.stateChanged.connect(self._sink_state_changed)
        return sink

    def setActive(self, path: str, active: bool) -> bool:
        if self._device is None or not self._device.setActive(str(path), bool(active)):
            return False
        active_paths = self._device.activePaths()
        self.activePathsChanged.emit(active_paths)
        if active_paths and not self._playing:
            self._start()
        elif not active_paths:
            self.stop(reset=True)
        return True

    def toggle(self, path: str) -> bool:
        path = str(path)
        active = path not in self.activePaths()
        return self.setActive(path, active)

    def playAll(self) -> bool:
        if self._device is None or not self.allPaths():
            return False
        self._device.setActivePaths(self.allPaths())
        self.activePathsChanged.emit(self._device.activePaths())
        if not self._playing:
            self._start()
        return True

    def playPaths(self, paths, *, restart: bool = False) -> bool:
        if self._device is None:
            return False
        self._device.setActivePaths(paths)
        if restart:
            self._device.setPositionRatio(0.0)
        active_paths = self._device.activePaths()
        self.activePathsChanged.emit(active_paths)
        if restart:
            self.positionChanged.emit(0.0)
        if active_paths and not self._playing:
            self._start()
        elif not active_paths:
            self.stop(reset=True)
        return bool(active_paths)

    def playSolo(self, path: str) -> bool:
        return self.playPaths((str(path),), restart=True)

    def setLayerVolume(self, path: str, gain: float) -> bool:
        if self._device is None:
            return False
        return self._device.setVolume(str(path), float(gain))

    def stopAll(self) -> None:
        self.stop(reset=True)

    def replaceLayer(self, path: str) -> bool:
        if self._device is None:
            return False
        try:
            audio, sample_rate = _decode_layer(str(path))
            if sample_rate != _SAMPLE_RATE:
                raise ValueError(
                    f"expected {_SAMPLE_RATE} Hz, received {sample_rate} Hz"
                )
        except Exception as exc:
            self.errorOccurred.emit(f"{Path(path).name}: {exc}")
            return False
        return self.replaceLayerPCM(str(path), audio, sample_rate=sample_rate)

    def replaceLayerPCM(
        self,
        path: str,
        audio,
        *,
        sample_rate: int = _SAMPLE_RATE,
    ) -> bool:
        if self._device is None or int(sample_rate) != _SAMPLE_RATE:
            return False
        replacement = np.asarray(audio, dtype=np.float32)
        if replacement.ndim == 1:
            replacement = np.repeat(replacement[:, None], _CHANNELS, axis=1)
        elif replacement.ndim == 2 and replacement.shape[1] == 1:
            replacement = np.repeat(replacement, _CHANNELS, axis=1)
        elif replacement.ndim == 2 and replacement.shape[1] > _CHANNELS:
            replacement = replacement[:, :_CHANNELS]
        if not self._device.replaceLayer(str(path), replacement):
            self.errorOccurred.emit(
                f"{Path(path).name}: updated audio no longer matches the shared loop timeline"
            )
            return False
        return True

    def restore(self, paths, ratio: float, *, playing: bool) -> None:
        if self._device is None:
            return
        self._device.setActivePaths(paths)
        self._device.setPositionRatio(ratio)
        active_paths = self._device.activePaths()
        self.activePathsChanged.emit(active_paths)
        self.positionChanged.emit(self._device.positionRatio())
        if active_paths and playing:
            self._start()

    def seek(self, ratio: float) -> None:
        if self._device is None:
            return
        self._device.setPositionRatio(ratio)
        self.positionChanged.emit(self._device.positionRatio())

    def _start(self) -> None:
        if self._device is None or not self._device.activePaths():
            return
        if self._sink is None:
            self._sink = self._create_sink()
        if self._sink is None:
            return
        self._sink.start(self._device)
        self._playing = True
        self._timer.start()
        self.playbackChanged.emit(True)

    def stop(self, *, reset: bool = False) -> None:
        if self._sink is not None:
            sink = self._sink
            self._sink = None
            self._stopping = True
            try:
                sink.stop()
                sink.deleteLater()
            finally:
                self._stopping = False
        was_playing = self._playing
        self._playing = False
        self._timer.stop()
        if reset and self._device is not None:
            self._device.setActivePaths(())
            self._device.setPositionRatio(0.0)
            self.activePathsChanged.emit(())
            self.positionChanged.emit(0.0)
        if was_playing:
            self.playbackChanged.emit(False)

    def _emit_position(self) -> None:
        if self._device is not None:
            self.positionChanged.emit(self._device.positionRatio())

    def _sink_state_changed(self, state) -> None:
        if self._stopping:
            return
        if state == QAudio.State.StoppedState and self._sink is not None:
            if self._sink.error() != QAudio.Error.NoError:
                self.errorOccurred.emit("The synchronized audio output stopped unexpectedly.")
                self.stop(reset=False)


__all__ = ["LayerMixDevice", "SynchronizedLayerPlayer"]
