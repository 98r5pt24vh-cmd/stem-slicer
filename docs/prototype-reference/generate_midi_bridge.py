"""Reuse Stem Slicer's persistent Quick Extract MIDI engine for Generate."""

from __future__ import annotations

import itertools
from pathlib import Path
import tempfile

from PySide6.QtCore import QObject, Slot


class GenerateMidiBridge(QObject):
    """Serialize Generate MIDI jobs through the already-loaded engine.

    Full generations are converted as one batch.  A live Alt Key, octave or
    normalization render queues only that changed card after the active batch,
    so every draggable MIDI file always corresponds to the transformed audio.
    """

    _job_ids = itertools.count(1_000_000_001)

    def __init__(self, page, service, *, engine_ready: bool = False, parent=None):
        super().__init__(parent)
        self.page = page
        self.service = service
        self._ready = bool(engine_ready)
        self._failed = False
        self._active_job_id: int | None = None
        self._pending_batch: tuple[dict, ...] = ()
        self._pending_layers: dict[str, dict] = {}
        self._cache_root = Path(
            tempfile.mkdtemp(prefix="stem-slicer-generate-midi-")
        )

        page.midiBatchRequested.connect(self.queue_batch)
        page.midiLayerRequested.connect(self.queue_layer)
        service.signals.ready.connect(self.engine_ready)
        service.signals.failed.connect(self.engine_failed)
        service.signals.progress.connect(self.progress)
        service.signals.completed.connect(self.completed)

    @staticmethod
    def _normalize_requests(layers) -> tuple[dict, ...]:
        requests: list[dict] = []
        for raw in layers or ():
            item = dict(raw)
            path = str(item.get("path") or "")
            if not path:
                continue
            requests.append(
                {
                    "path": path,
                    "bpm": int(float(item.get("bpm") or 140)),
                    "identity": str(item.get("identity") or ""),
                }
            )
        return tuple(requests)

    @Slot(object)
    def queue_batch(self, layers) -> None:
        requests = self._normalize_requests(layers)
        self._pending_batch = requests
        self._pending_layers.clear()
        if self._failed:
            self.page.set_all_midi_unavailable()
            return
        if not self._ready:
            return
        self._start_job(requests, replace_active=True)

    @Slot(object)
    def queue_layer(self, layer) -> None:
        requests = self._normalize_requests((layer,))
        if not requests:
            return
        request = requests[0]
        self._pending_layers[request["path"]] = request
        if self._failed:
            self.page.set_layer_midi_path(request["path"], "")
            return
        if self._ready and self._active_job_id is None:
            self._start_pending_layers()

    @Slot()
    def engine_ready(self) -> None:
        self._ready = True
        self._failed = False
        if self._pending_batch:
            self._start_job(self._pending_batch, replace_active=True)
        elif self._pending_layers and self._active_job_id is None:
            self._start_pending_layers()

    @Slot(str)
    def engine_failed(self, _message: str) -> None:
        self._failed = True
        self._ready = False
        self._active_job_id = None
        self._pending_batch = ()
        self._pending_layers.clear()
        self.page.set_all_midi_unavailable()

    def _start_pending_layers(self) -> None:
        pending = tuple(self._pending_layers.values())
        self._pending_layers.clear()
        self._start_job(pending, replace_active=False)

    def _start_job(self, layers, *, replace_active: bool) -> None:
        requests = self._normalize_requests(layers)
        if not requests:
            self._active_job_id = None
            return
        job_id = next(self._job_ids)
        cache_path = self._cache_root / f"job-{job_id}"
        cache_path.mkdir(parents=True, exist_ok=True)
        if replace_active:
            self._pending_batch = ()
        self._active_job_id = job_id
        # MidiEngineService's current contract is latest-job-wins.  The large
        # namespace cannot collide with Quick Extract's ordinary counters.
        self.service.latest_job_id = job_id
        self.service.submit(requests, str(cache_path), job_id)

    @Slot(int, str, str, int, int)
    def progress(
        self,
        job_id: int,
        audio_path: str,
        midi_path: str,
        _current: int,
        _total: int,
    ) -> None:
        if int(job_id) != self._active_job_id:
            return
        path = str(audio_path)
        # A newer transform of this same card is queued.  Never expose the
        # stale MIDI produced from its preceding audio revision.
        if path in self._pending_layers:
            return
        self.page.set_layer_midi_path(path, str(midi_path or ""))

    @Slot(int, int, float)
    def completed(
        self, job_id: int, _ready_count: int, _elapsed: float
    ) -> None:
        if int(job_id) != self._active_job_id:
            return
        still_owns_engine = self.service.latest_job_id == int(job_id)
        self._active_job_id = None
        if still_owns_engine and self._pending_layers:
            self._start_pending_layers()


__all__ = ["GenerateMidiBridge"]
