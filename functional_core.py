import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from array import array

from PySide6.QtCore import QEvent, QMimeData, QObject, QRectF, QStandardPaths, QThread, QTimer, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QDrag, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QFrame, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
    QComboBox, QLineEdit,
)

from engine import find_ffmpeg, process_audio, process_single_file, run_subprocess
from audio_convert import ConversionRequest, convert_audio
from filename_templates import TOKENS, parse_loop_filename, render_name
from key_detection import KeyAnalyzer, format_camelot
from storage import StorageManager, format_decimal_size, open_in_file_manager
from theme import application_stylesheet
from widgets import StudioRoot, TokenStrip


APP_NAME = "Stem Slicer"
APP_VERSION = "1.6B"
ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII")
MODE_NAMES = ("Ionian", "Dorian", "Phrygian", "Lydian", "Mixolydian", "Aeolian", "Locrian")
MAJOR_INTERVALS = (0, 2, 4, 5, 7, 9, 11)
SHARP_PITCHES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
FLAT_PITCHES = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")
TARGET_KEYS = (
    "C major / A minor", "C# major / A# minor", "D major / B minor",
    "D# major / C minor", "E major / C# minor", "F major / D minor",
    "F# major / D# minor", "G major / E minor", "G# major / F minor",
    "A major / F# minor", "A# major / G minor", "B major / G# minor",
)


def canonical_loop_bpm(value):
    """Display loop tempo in the producer range validated for the product."""
    bpm = float(value or 0)
    if bpm <= 0:
        return 0
    while bpm < 94:
        bpm *= 2
    while bpm > 186:
        bpm /= 2
    return int(round(bpm))


def key_parts(key):
    return (key[:-1], False) if key.endswith("m") else (key, True)


def pitch_index(note):
    aliases = {name: index for index, name in enumerate(SHARP_PITCHES)}
    aliases.update({name: index for index, name in enumerate(FLAT_PITCHES)})
    return aliases[note]


class KeyEngineLoader(QObject):
    ready = Signal(object)
    failed = Signal(str)
    finished = Signal()

    @Slot()
    def run(self):
        try:
            analyzer = KeyAnalyzer(workers=1)
            analyzer.start()
            # OpenKeyScan reports ready before PyTorch's first inference has
            # initialized its kernels and buffers. Warm the model here so the
            # first user scan has the same latency as every following scan.
            analyzer.analyze(
                resource_path("assets", "key-and-bpm-engine-warmup.wav"),
                bpm_mode="quick_scan_loop",
                structure_ffmpeg_path=find_ffmpeg(),
            )
            self.ready.emit(analyzer)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class BatchWorker(QObject):
    progress = Signal(int, int, str)
    completed = Signal(object, object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, source, output, settings, analyzer=None):
        super().__init__()
        self.source = source
        self.output = output
        self.settings = settings
        self.analyzer = analyzer

    @Slot()
    def run(self):
        try:
            process_audio(
                self.source,
                self.output,
                lambda current, total, status: self.progress.emit(current, total, status),
                lambda failures, manifest: self.completed.emit(failures, manifest),
                lambda message: self.failed.emit(str(message)),
                self.settings,
                analyzer=self.analyzer,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class QuickScanWorker(QObject):
    completed = Signal(object, float)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, analyzer, path):
        super().__init__()
        self.analyzer = analyzer
        self.path = path

    @Slot()
    def run(self):
        started = time.perf_counter()
        try:
            self.completed.emit(
                self.analyzer.analyze(
                    self.path,
                    bpm_mode="quick_scan_loop",
                    structure_ffmpeg_path=find_ffmpeg(),
                ),
                time.perf_counter() - started,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


def waveform_peaks(path, points=72):
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return [0.0] * points
    completed = run_subprocess(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", path, "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    samples = array("h")
    samples.frombytes(completed.stdout[: len(completed.stdout) // 2 * 2])
    if not samples:
        return [0.0] * points
    stride = max(1, len(samples) // points)
    values = [max(abs(value) for value in samples[index:index + stride]) for index in range(0, len(samples), stride)][:points]
    maximum = max(values) or 1
    return [value / maximum for value in values] + [0.0] * max(0, points - len(values))


class QuickExtractWorker(QObject):
    completed = Signal(object, float)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, source, output):
        super().__init__()
        self.source, self.output = source, output

    @Slot()
    def run(self):
        started = time.perf_counter()
        try:
            diagnostics = process_single_file(self.source, self.output)
            layers = []
            for row in diagnostics:
                if row.get("event") != "exported" or not row.get("output_exists"):
                    continue
                path = os.path.join(self.output, row["output_name"])
                layers.append({
                    "path": path,
                    "name": os.path.basename(path),
                    "bpm": int(row.get("bpm") or 140),
                    "duration": float(row.get("duration_seconds") or 0),
                    "bytes": int(row.get("output_bytes") or os.path.getsize(path)),
                    "peaks": waveform_peaks(path),
                })
            self.completed.emit(layers, time.perf_counter() - started)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class QuickConvertWorker(QObject):
    completed = Signal(object, float)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, analyzer, source, output, target_bpm, target_key):
        super().__init__()
        self.analyzer = analyzer
        self.source = source
        self.output = output
        self.target_bpm = target_bpm
        self.target_key = target_key

    @Slot()
    def run(self):
        started = time.perf_counter()
        try:
            analysis = self.analyzer.analyze(
                self.source,
                bpm_mode="quick_scan_loop",
                structure_ffmpeg_path=find_ffmpeg(),
            )
            source_bpm = canonical_loop_bpm(analysis.get("bpm"))
            if not source_bpm:
                raise ValueError("The source BPM could not be detected.")
            source_key = format_camelot(analysis["camelot"], "detected", "sharps")
            target_bpm = int(self.target_bpm or source_bpm)
            request = ConversionRequest(
                source=os.path.abspath(self.source),
                destination=os.path.abspath(self.output),
                source_bpm=source_bpm,
                target_bpm=target_bpm,
                source_key=source_key,
                target_key=self.target_key,
            )
            result = convert_audio(request)
            self.completed.emit({
                "path": str(result.output),
                "source_bpm": source_bpm,
                "target_bpm": target_bpm,
                "source_key": source_key,
                "target_key": self.target_key,
                "duration": 0.0,
                "bytes": os.path.getsize(result.output),
            }, time.perf_counter() - started)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class MidiWorker(QObject):
    ready = Signal()
    progress = Signal(int, str, str, int, int)
    completed = Signal(int, int, float)

    def __init__(self, converter):
        super().__init__()
        self.converter = converter
        self.latest_job_id = 0

    @Slot()
    def start(self):
        self.ready.emit()

    @Slot(object, str, int)
    def convert(self, layers, cache_path, job_id):
        started = time.perf_counter()
        ready_count = 0
        total = len(layers)
        for index, layer in enumerate(layers, 1):
            if job_id != self.latest_job_id:
                break
            path = layer["path"]
            midi_path = os.path.join(cache_path, f"layer_{index}.mid")
            try:
                self.converter.convert(path, midi_path, bpm=int(layer.get("bpm") or 140))
                if job_id != self.latest_job_id:
                    break
                ready_count += 1
                self.progress.emit(job_id, path, midi_path, index, total)
            except Exception:
                logging.exception("MIDI conversion failed for %s", path)
                if job_id == self.latest_job_id:
                    self.progress.emit(job_id, path, "", index, total)
        self.completed.emit(job_id, ready_count, time.perf_counter() - started)


class MidiEngineLoader(QObject):
    ready = Signal(object)
    failed = Signal(str)

    def run(self):
        try:
            from midi_conversion import MidiConverter
            self.ready.emit(MidiConverter())
        except Exception as exc:
            logging.exception("MIDI engine failed to start")
            self.failed.emit(str(exc))


class WaveformWidget(QWidget):
    seekRequested = Signal(float)

    def __init__(self, peaks, parent=None):
        super().__init__(parent); self.peaks = peaks; self.progress = 0.0; self.scrubbing = False; self.setFixedHeight(22); self.setCursor(Qt.PointingHandCursor)

    def setProgress(self, progress):
        self.progress = max(0.0, min(1.0, float(progress))); self.update()

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
        center = self.height() / 2; step = self.width() / max(1, len(self.peaks))
        for index, value in enumerate(self.peaks):
            height = max(1.0, value * (self.height() - 3))
            x = (index + 0.5) * step
            painter.setPen(QPen(QColor("#ff2b1c" if x <= self.progress * self.width() else "#747c83"), 1.2, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(x, center - height / 2, x, center + height / 2)
        if self.progress > 0:
            x = self.progress * self.width(); painter.setPen(QPen(QColor("#ff4a3b"), 1.4)); painter.drawLine(x, 1, x, self.height() - 1)

    def _seek_from_x(self, x):
        if self.width() > 0: self.seekRequested.emit(max(0.0, min(1.0, x / self.width())))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.width() > 0:
            self.scrubbing = True; self._seek_from_x(event.position().x())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.scrubbing and (event.buttons() & Qt.LeftButton): self._seek_from_x(event.position().x())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._seek_from_x(event.position().x()); self.scrubbing = False
        super().mouseReleaseEvent(event)


class FileDragHandle(QWidget):
    def __init__(self, path, parent=None):
        super().__init__(parent); self.path = path; self._press = None; self.setFixedSize(20, 20); self.setCursor(Qt.OpenHandCursor)

    def set_path(self, path):
        self.path = path
        self.setEnabled(bool(path))

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing); painter.setPen(Qt.NoPen); painter.setBrush(QColor("#777e85"))
        for x in (7, 13):
            for y in (5, 10, 15): painter.drawEllipse(QRectF(x - 1.5, y - 1.5, 3, 3))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton: self._press = event.position().toPoint()

    def mouseMoveEvent(self, event):
        if self._press is None or not (event.buttons() & Qt.LeftButton): return
        if (event.position().toPoint() - self._press).manhattanLength() < QApplication.startDragDistance(): return
        mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(self.path)])
        drag = QDrag(self); drag.setMimeData(mime); self.setCursor(Qt.ClosedHandCursor); drag.exec(Qt.CopyAction); self.setCursor(Qt.OpenHandCursor); self._press = None


class MidiDragHandle(QWidget):
    """Compact MIDI wordmark that becomes draggable when conversion finishes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = ""
        self.state = "processing"
        self._press = None
        self._frame = 0
        self._logo = QPixmap(resource_path("assets", "midi-logo-mask.png"))
        # Match the visual footprint of the adjacent 20 × 20 six-dot handle.
        # The MIDI wordmark needs a little extra width to preserve its shape.
        self.setFixedSize(32, 20)
        self.setToolTip("Generating MIDI…")
        self._timer = QTimer(self)
        self._timer.setInterval(360)
        self._timer.timeout.connect(self._advance)
        self._timer.start()

    def _advance(self):
        self._frame = (self._frame + 1) % 3
        self.update()

    def set_midi_path(self, path):
        self.path = path or ""
        self.state = "ready" if self.path else "failed"
        self._timer.stop()
        if self.path:
            self.setCursor(Qt.OpenHandCursor)
            self.setToolTip("Drag MIDI to your DAW")
        else:
            self.unsetCursor()
            self.setToolTip("MIDI conversion unavailable")
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor("#57d84e" if self.state == "ready" else "#ff2b1c" if self.state == "processing" else "#666d73")
        if self.state == "processing":
            color.setAlpha((145, 200, 255)[self._frame])
        logo = self._logo.scaled(self.width() - 5, self.height() - 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        tinted = QPixmap(logo.size()); tinted.fill(Qt.transparent)
        tint = QPainter(tinted); tint.drawPixmap(0, 0, logo); tint.setCompositionMode(QPainter.CompositionMode_SourceIn); tint.fillRect(tinted.rect(), color); tint.end()
        painter.drawPixmap((self.width() - tinted.width()) // 2, (self.height() - tinted.height()) // 2, tinted)

    def mousePressEvent(self, event):
        if self.state == "ready" and event.button() == Qt.LeftButton:
            self._press = event.position().toPoint()

    def mouseMoveEvent(self, event):
        if self.state != "ready" or self._press is None or not (event.buttons() & Qt.LeftButton):
            return
        if (event.position().toPoint() - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(self.path)])
        drag = QDrag(self); drag.setMimeData(mime); self.setCursor(Qt.ClosedHandCursor); drag.exec(Qt.CopyAction); self.setCursor(Qt.OpenHandCursor); self._press = None


class LayerPlayButton(QPushButton):
    """Keep the existing Play glyph, but paint Pause consistently on every OS."""

    def __init__(self, parent=None):
        super().__init__("▶", parent)
        self.setProperty("state", "stopped")

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.property("state") != "playing":
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#e1a83a"), 2.5, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(10.5, 8.5, 10.5, 16.5)
        painter.drawLine(14.5, 8.5, 14.5, 16.5)


class LayerCard(QFrame):
    playRequested = Signal(str)
    seekRequested = Signal(str, float)

    def __init__(self, layer, parent=None):
        super().__init__(parent); self.layer = layer; self.setProperty("role", "layerCard"); self.setFixedHeight(78)
        layout = QVBoxLayout(self); layout.setContentsMargins(9, 5, 9, 5); layout.setSpacing(1)
        header = QHBoxLayout(); header.setSpacing(7)
        self.play = LayerPlayButton(); self.play.setProperty("role", "layerPlay"); self.play.setFixedSize(25, 25); self.play.clicked.connect(lambda: self.playRequested.emit(layer["path"]))
        name = label(layer["name"], "layerName"); name.setToolTip(layer["name"])
        self.midi_handle = MidiDragHandle()
        header.addWidget(self.play); header.addWidget(name); header.addStretch(); header.addWidget(self.midi_handle); header.addWidget(FileDragHandle(layer["path"]))
        layout.addLayout(header); self.waveform = WaveformWidget(layer["peaks"]); self.waveform.seekRequested.connect(lambda ratio: self.seekRequested.emit(layer["path"], ratio)); layout.addWidget(self.waveform)
        metadata = QHBoxLayout(); metadata.addWidget(label(format_duration(layer["duration"]), "cardMeta")); metadata.addStretch(); metadata.addWidget(label(format_decimal_size(layer["bytes"]), "cardMeta")); layout.addLayout(metadata)

    def setPlaybackState(self, state):
        self.play.setText("" if state == "playing" else "▶")
        self.play.setProperty("state", state); self.play.style().unpolish(self.play); self.play.style().polish(self.play)

    def setProgress(self, progress):
        self.waveform.setProgress(progress)

    def setMidiPath(self, path):
        self.midi_handle.set_midi_path(path)


def format_duration(seconds):
    seconds = max(0, int(round(seconds))); return f"{seconds // 60:02d}:{seconds % 60:02d}"


class QuickExtractManagerDialog(QDialog):
    def __init__(self, storage, changed_callback=None, parent=None):
        super().__init__(parent)
        self.storage = storage; self.changed_callback = changed_callback; self.confirm_all = False
        self.setWindowTitle("Quick Extract Manager"); self.setModal(True); self.resize(760, 520)
        self.setProperty("role", "managerDialog")
        outer = QVBoxLayout(self); outer.setContentsMargins(18, 16, 18, 16); outer.setSpacing(10)
        title_row = QHBoxLayout(); title_copy = QVBoxLayout(); title_copy.setSpacing(2)
        title_copy.addWidget(label("QUICK EXTRACT HISTORY", "pageTitle")); title_copy.addWidget(label("Saved extracts remain available for DAWs and external projects.", "muted"))
        title_row.addLayout(title_copy); title_row.addStretch(); close_button = button("✕", "icon"); close_button.setFixedSize(36, 32); close_button.clicked.connect(self.accept); title_row.addWidget(close_button); outer.addLayout(title_row)
        self.summary = label("", "storage"); outer.addWidget(self.summary)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setProperty("role", "managerList")
        self.content = QWidget(); self.rows = QVBoxLayout(self.content); self.rows.setContentsMargins(6, 6, 6, 6); self.rows.setSpacing(7); self.scroll.setWidget(self.content); outer.addWidget(self.scroll, 1)
        bottom = QHBoxLayout(); open_button = icon_button("folder", "OPEN QUICK EXTRACT FOLDER", icon_size=17); open_button.clicked.connect(lambda: open_in_file_manager(self.storage.category_path("quick")))
        self.trash_all = button("MOVE ALL TO TRASH", "danger"); self.trash_all.clicked.connect(self._move_all)
        bottom.addWidget(open_button); bottom.addStretch(); bottom.addWidget(self.trash_all); outer.addLayout(bottom)
        self.refresh()

    def refresh(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        extracts = self.storage.list_quick_extracts(); total = sum(item["size"] for item in extracts); layers = sum(item["layers"] for item in extracts)
        self.summary.setText(f"{len(extracts)} extract{'s' if len(extracts) != 1 else ''}  ·  {layers} layers  ·  {format_decimal_size(total)}")
        if not extracts:
            empty = label("No saved Quick Extract history.", "muted"); empty.setAlignment(Qt.AlignCenter); self.rows.addWidget(empty); self.rows.addStretch(); self.trash_all.setEnabled(False); return
        self.trash_all.setEnabled(True)
        for extract in extracts:
            row = panel("managerRow"); layout = QHBoxLayout(row); layout.setContentsMargins(12, 8, 10, 8); layout.setSpacing(12)
            copy = QVBoxLayout(); name = label(extract["name"], "managerName"); name.setToolTip(extract["path"]); copy.addWidget(name); copy.addWidget(label(f"{extract['layers']} layer{'s' if extract['layers'] != 1 else ''}  ·  {format_decimal_size(extract['size'])}", "mutedSmall")); layout.addLayout(copy, 1)
            open_button = button("OPEN"); open_button.clicked.connect(lambda checked=False, path=extract["path"]: open_in_file_manager(path)); layout.addWidget(open_button)
            trash_button = button("MOVE TO TRASH", "danger"); trash_button.clicked.connect(lambda checked=False, path=extract["path"]: self._move_one(path)); layout.addWidget(trash_button)
            self.rows.addWidget(row)
        self.rows.addStretch()

    def _changed(self):
        self.confirm_all = False; self.trash_all.setText("MOVE ALL TO TRASH")
        self.refresh()
        if self.changed_callback: self.changed_callback()

    def _move_one(self, path):
        if self.storage.move_quick_extract_to_trash(path): self._changed()

    def _move_all(self):
        extracts = self.storage.list_quick_extracts()
        if not extracts: return
        if not self.confirm_all:
            self.confirm_all = True; self.trash_all.setText(f"CONFIRM: MOVE {len(extracts)} EXTRACTS TO TRASH"); return
        for extract in extracts:
            self.storage.move_quick_extract_to_trash(extract["path"])
        self._changed()


class QuickConvertManagerDialog(QDialog):
    def __init__(self, storage, changed_callback=None, parent=None):
        super().__init__(parent)
        self.storage = storage
        self.changed_callback = changed_callback
        self.confirm_all = False
        self.setWindowTitle("Quick Convert Manager")
        self.setModal(True)
        self.resize(760, 520)
        self.setProperty("role", "managerDialog")
        outer = QVBoxLayout(self); outer.setContentsMargins(18, 16, 18, 16); outer.setSpacing(10)
        title_row = QHBoxLayout(); title_copy = QVBoxLayout(); title_copy.setSpacing(2)
        title_copy.addWidget(label("QUICK CONVERT HISTORY", "pageTitle"))
        title_copy.addWidget(label("Saved conversions remain available for DAWs and external projects.", "muted"))
        title_row.addLayout(title_copy); title_row.addStretch()
        close_button = button("✕", "icon"); close_button.setFixedSize(36, 32); close_button.clicked.connect(self.accept)
        title_row.addWidget(close_button); outer.addLayout(title_row)
        self.summary = label("", "storage"); outer.addWidget(self.summary)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setProperty("role", "managerList")
        self.content = QWidget(); self.rows = QVBoxLayout(self.content); self.rows.setContentsMargins(6, 6, 6, 6); self.rows.setSpacing(7)
        self.scroll.setWidget(self.content); outer.addWidget(self.scroll, 1)
        bottom = QHBoxLayout()
        open_button = icon_button("folder", "OPEN QUICK CONVERT FOLDER", icon_size=17)
        open_button.clicked.connect(lambda: open_in_file_manager(self.storage.category_path("convert")))
        self.trash_all = button("MOVE ALL TO TRASH", "danger"); self.trash_all.clicked.connect(self._move_all)
        bottom.addWidget(open_button); bottom.addStretch(); bottom.addWidget(self.trash_all); outer.addLayout(bottom)
        self.refresh()

    def refresh(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        entries = self.storage.list_quick_conversions()
        total = sum(item["size"] for item in entries)
        self.summary.setText(f"{len(entries)} conversion{'s' if len(entries) != 1 else ''}  ·  {format_decimal_size(total)}")
        self.trash_all.setEnabled(bool(entries))
        if not entries:
            empty = label("No saved Quick Convert history.", "muted"); empty.setAlignment(Qt.AlignCenter)
            self.rows.addWidget(empty); self.rows.addStretch(); return
        for entry in entries:
            row = panel("managerRow"); row_layout = QHBoxLayout(row); row_layout.setContentsMargins(12, 8, 10, 8)
            copy = QVBoxLayout(); name = label(entry["name"], "managerName"); name.setToolTip(entry["path"])
            copy.addWidget(name); copy.addWidget(label(f"{format_decimal_size(entry['size'])}", "mutedSmall")); row_layout.addLayout(copy, 1)
            open_button = button("OPEN"); open_button.clicked.connect(lambda checked=False, path=entry["path"]: open_in_file_manager(path))
            trash_button = button("MOVE TO TRASH", "danger"); trash_button.clicked.connect(lambda checked=False, path=entry["path"]: self._move_one(path))
            row_layout.addWidget(open_button); row_layout.addWidget(trash_button); self.rows.addWidget(row)
        self.rows.addStretch()

    def _changed(self):
        self.confirm_all = False; self.trash_all.setText("MOVE ALL TO TRASH"); self.refresh()
        if self.changed_callback: self.changed_callback()

    def _move_one(self, path):
        if self.storage.move_quick_conversion_to_trash(path): self._changed()

    def _move_all(self):
        entries = self.storage.list_quick_conversions()
        if not entries: return
        if not self.confirm_all:
            self.confirm_all = True; self.trash_all.setText(f"CONFIRM: MOVE {len(entries)} CONVERSIONS TO TRASH"); return
        for entry in entries:
            self.storage.move_quick_conversion_to_trash(entry["path"])
        self._changed()


def resource_path(*parts):
    root = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, *parts)


def label(text="", role=None, wrap=False):
    item = QLabel(text)
    if role:
        item.setProperty("role", role)
    item.setWordWrap(wrap)
    return item


def image(path, width, height):
    item = QLabel()
    item.setAlignment(Qt.AlignCenter)
    item.setFixedSize(width, height)
    pixmap = QPixmap(path)
    if not pixmap.isNull():
        item.setPixmap(pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    return item


def panel(role="panel"):
    item = QFrame()
    item.setProperty("role", role)
    return item


def button(text, role="secondary"):
    item = QPushButton(text)
    item.setProperty("role", role)
    item.setCursor(Qt.PointingHandCursor)
    return item


def icon_button(kind, text, role="secondary", icon_size=17):
    item = button("", role)
    row = QHBoxLayout(item)
    row.setContentsMargins(12, 1, 12, 1)
    row.setSpacing(8)
    row.addStretch()
    item.icon_widget = LineIcon(kind, "#aeb4bb", icon_size)
    item.text_label = label(text, "buttonText")
    row.addWidget(item.icon_widget)
    row.addWidget(item.text_label)
    row.addStretch()
    return item


def fit_icon_button_width(item, minimum_width):
    """Keep icon-button labels intact across native platform font metrics."""
    item.ensurePolished()
    item.text_label.ensurePolished()
    margins = item.layout().contentsMargins()
    text_width = QFontMetrics(item.text_label.font()).horizontalAdvance(item.text_label.text())
    content_width = (
        margins.left()
        + item.icon_widget.width()
        + item.layout().spacing()
        + text_width
        + margins.right()
        + 4
    )
    item.setFixedWidth(max(minimum_width, content_width))
    return item


class LineIcon(QWidget):
    def __init__(self, kind, color="#a8afb6", size=28, parent=None):
        super().__init__(parent)
        self.kind, self.color = kind, QColor(color)
        self.setFixedSize(size, size)

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(self.color, max(1.7, self.width() / 15), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush); w, h = self.width(), self.height()
        if self.kind in ("folder", "folder_in", "folder_out"):
            if self.kind == "folder_out":
                # Shift the folder body right to reserve a clear exit lane for
                # the arrow, even at the compact 16 px output-location size.
                path = QPainterPath(); path.moveTo(.28*w, .31*h); path.lineTo(.28*w, .22*h)
                path.lineTo(.49*w, .22*h); path.lineTo(.59*w, .34*h); path.lineTo(.92*w, .34*h)
                path.lineTo(.92*w, .78*h); path.lineTo(.28*w, .78*h); path.closeSubpath(); p.drawPath(path)
            else:
                path = QPainterPath(); path.moveTo(.12*w, .31*h); path.lineTo(.12*w, .22*h)
                path.lineTo(.42*w, .22*h); path.lineTo(.52*w, .34*h); path.lineTo(.88*w, .34*h)
                path.lineTo(.88*w, .78*h); path.lineTo(.12*w, .78*h); path.closeSubpath(); p.drawPath(path)
            if self.kind == "folder_in":
                p.drawLine(.04*w, .55*h, .52*w, .55*h)
                p.drawLine(.40*w, .43*h, .52*w, .55*h)
                p.drawLine(.40*w, .67*h, .52*w, .55*h)
            elif self.kind == "folder_out":
                p.drawLine(.61*w, .55*h, .08*w, .55*h)
                p.drawLine(.27*w, .37*h, .08*w, .55*h)
                p.drawLine(.27*w, .73*h, .08*w, .55*h)
        elif self.kind == "bolt":
            path = QPainterPath(); path.moveTo(.58*w, .08*h); path.lineTo(.27*w, .53*h)
            path.lineTo(.49*w, .53*h); path.lineTo(.40*w, .92*h); path.lineTo(.75*w, .43*h)
            path.lineTo(.53*w, .43*h); path.closeSubpath(); p.setPen(Qt.NoPen); p.setBrush(self.color); p.drawPath(path)
        elif self.kind == "info":
            p.drawEllipse(QRectF(.16*w, .16*h, .68*w, .68*h)); p.drawLine(.5*w, .45*h, .5*w, .69*h)
            p.setBrush(self.color); p.drawEllipse(QRectF(.46*w, .29*h, .08*w, .08*h))
        elif self.kind == "gear":
            p.drawEllipse(QRectF(.28*w, .28*h, .44*w, .44*h)); p.drawEllipse(QRectF(.43*w, .43*h, .14*w, .14*h))
            for x1,y1,x2,y2 in ((.5,.08,.5,.25),(.5,.75,.5,.92),(.08,.5,.25,.5),(.75,.5,.92,.5),(.2,.2,.32,.32),(.68,.68,.8,.8),(.8,.2,.68,.32),(.32,.68,.2,.8)): p.drawLine(x1*w,y1*h,x2*w,y2*h)
        elif self.kind == "copy":
            p.drawRoundedRect(QRectF(.28*w, .24*h, .52*w, .55*h), 2, 2)
            p.drawRoundedRect(QRectF(.16*w, .12*h, .52*w, .55*h), 2, 2)
        elif self.kind == "pencil":
            path = QPainterPath(); path.moveTo(.20*w,.70*h); path.lineTo(.27*w,.48*h); path.lineTo(.68*w,.15*h)
            path.lineTo(.84*w,.32*h); path.lineTo(.43*w,.67*h); path.closeSubpath(); p.drawPath(path)
            p.drawLine(.27*w,.48*h,.43*w,.67*h); p.drawLine(.20*w,.70*h,.16*w,.84*h); p.drawLine(.16*w,.84*h,.31*w,.80*h)
        elif self.kind == "check":
            p.drawEllipse(QRectF(.10*w,.10*h,.80*w,.80*h)); p.drawLine(.28*w,.51*h,.43*w,.67*h); p.drawLine(.43*w,.67*h,.74*w,.34*h)
        elif self.kind == "grip":
            p.setPen(Qt.NoPen); p.setBrush(self.color)
            for x in (.34,.66):
                for y in (.24,.50,.76): p.drawEllipse(QRectF((x-.06)*w,(y-.06)*h,.12*w,.12*h))
        elif self.kind == "audio_file":
            path = QPainterPath(); path.moveTo(.18*w,.08*h); path.lineTo(.62*w,.08*h); path.lineTo(.84*w,.30*h)
            path.lineTo(.84*w,.92*h); path.lineTo(.18*w,.92*h); path.closeSubpath(); p.drawPath(path)
            p.drawLine(.62*w,.08*h,.62*w,.30*h); p.drawLine(.62*w,.30*h,.84*w,.30*h)
            speaker = QPainterPath(); speaker.moveTo(.31*w,.57*h); speaker.lineTo(.40*w,.57*h); speaker.lineTo(.50*w,.49*h)
            speaker.lineTo(.50*w,.69*h); speaker.lineTo(.40*w,.62*h); speaker.lineTo(.31*w,.62*h); speaker.closeSubpath(); p.drawPath(speaker)
            p.drawArc(QRectF(.46*w,.51*h,.16*w,.18*h), -55*16, 110*16); p.drawArc(QRectF(.44*w,.47*h,.24*w,.27*h), -53*16, 106*16)
        elif self.kind == "drive":
            p.drawRoundedRect(QRectF(.10*w,.20*h,.80*w,.62*h), 3, 3)
            p.drawLine(.10*w,.62*h,.90*w,.62*h)
            p.drawLine(.24*w,.34*h,.76*w,.34*h)
            p.setBrush(self.color); p.drawEllipse(QRectF(.75*w,.69*h,.09*w,.09*h))
        elif self.kind == "music_note":
            p.drawLine(.39*w,.22*h,.39*w,.68*h); p.drawLine(.72*w,.14*h,.72*w,.58*h)
            p.drawLine(.39*w,.22*h,.72*w,.14*h); p.drawLine(.39*w,.29*h,.72*w,.21*h)
            p.setBrush(self.color); p.drawEllipse(QRectF(.20*w,.63*h,.22*w,.16*h)); p.drawEllipse(QRectF(.53*w,.53*h,.22*w,.16*h))
        elif self.kind == "layers":
            top = QPainterPath(); top.moveTo(.50*w, .11*h); top.lineTo(.84*w, .29*h)
            top.lineTo(.50*w, .47*h); top.lineTo(.16*w, .29*h); top.closeSubpath(); p.drawPath(top)
            p.drawLine(.16*w, .46*h, .50*w, .64*h); p.drawLine(.50*w, .64*h, .84*w, .46*h)
            p.drawLine(.16*w, .63*h, .50*w, .81*h); p.drawLine(.50*w, .81*h, .84*w, .63*h)
        elif self.kind == "key_scan":
            for x1, y1, x2, y2 in (
                (.12, .31, .12, .12), (.12, .12, .31, .12),
                (.69, .12, .88, .12), (.88, .12, .88, .31),
                (.12, .69, .12, .88), (.12, .88, .31, .88),
                (.69, .88, .88, .88), (.88, .69, .88, .88),
            ):
                p.drawLine(x1*w, y1*h, x2*w, y2*h)
            p.drawEllipse(QRectF(.35*w, .32*h, .26*w, .26*h))
            p.drawLine(.57*w, .55*h, .72*w, .70*h)
        elif self.kind == "retarget":
            # Two clean opposing arrows: the native equivalent of the
            # validated Convert BPM & Key prototype icon.
            p.drawLine(.14*w, .36*h, .78*w, .36*h)
            p.drawLine(.64*w, .20*h, .80*w, .36*h)
            p.drawLine(.64*w, .52*h, .80*w, .36*h)
            p.drawLine(.86*w, .66*h, .22*w, .66*h)
            p.drawLine(.36*w, .50*h, .20*w, .66*h)
            p.drawLine(.36*w, .82*h, .20*w, .66*h)
        elif self.kind in ("play_button", "pause_button", "stop_button"):
            p.setPen(QPen(QColor("#747c84"), max(1.8, w / 13), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush); p.drawEllipse(QRectF(.08*w,.08*h,.84*w,.84*h))
            if self.kind == "play_button":
                # Softened triangular play mark: rounded joins and gently curved tips.
                p.setPen(QPen(QColor("#57d84e"), max(2.0, w / 8), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                path = QPainterPath(); path.moveTo(.40*w,.31*h); path.lineTo(.40*w,.69*h); path.lineTo(.70*w,.50*h); path.closeSubpath(); p.drawPath(path)
            elif self.kind == "pause_button":
                p.setPen(QPen(QColor("#e1a83a"), max(2.4, w / 8), Qt.SolidLine, Qt.RoundCap))
                p.drawLine(.43*w,.35*h,.43*w,.65*h); p.drawLine(.59*w,.35*h,.59*w,.65*h)
            else:
                p.setPen(Qt.NoPen); p.setBrush(QColor("#d74335")); p.drawRoundedRect(QRectF(.37*w,.37*h,.27*w,.27*h), 2.5, 2.5)


class DimOverlay(QWidget):
    """Paint a non-interactive shade over a panel without Qt graphics effects."""

    def __init__(self, target):
        super().__init__(target)
        self.target = target
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        target.installEventFilter(self)
        self.hide()

    def eventFilter(self, watched, event):
        if watched is self.target and event.type() in (QEvent.Resize, QEvent.Show):
            self.setGeometry(self.target.rect())
            self.raise_()
        return False

    def setDimmed(self, dimmed):
        self.setGeometry(self.target.rect())
        self.setVisible(bool(dimmed))
        if dimmed:
            self.raise_()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 6, 6)
        painter.fillPath(path, QColor(5, 8, 10, 178))


class TabButton(QFrame):
    clicked = Signal()

    def __init__(self, icon, title, subtitle, parent=None):
        super().__init__(parent)
        self.active = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(76)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        center = QHBoxLayout()
        center.setContentsMargins(0, 14, 0, 0)
        center.setSpacing(15)
        self.icon = LineIcon("folder" if icon == "folder" else "bolt", size=34)
        copy = QVBoxLayout()
        copy.setSpacing(2)
        self.title = label(title, "tabTitle")
        self.subtitle = label(subtitle, "tabSubtitle")
        self.title.setFixedHeight(22)
        self.subtitle.setFixedHeight(18)
        copy.addWidget(self.title)
        copy.addWidget(self.subtitle)
        center.addStretch()
        center.addWidget(self.icon)
        center.addLayout(copy)
        center.addStretch()
        layout.addLayout(center, 1)
        self.line = QFrame()
        self.line.setFixedHeight(3)
        self.line.setProperty("role", "tabLine")
        layout.addWidget(self.line)

    def setActive(self, active):
        self.active = active
        self.icon.color = QColor("#ff2b1c" if active else "#989ea5")
        self.icon.update()
        for widget in (self, self.title, self.subtitle, self.line):
            widget.setProperty("active", active)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class DropZone(QFrame):
    pathChanged = Signal(str)

    AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac"}

    def __init__(self, kind="folder", compact=False, interactive=False, allowed_extensions=None, accent=None, icon_kind=None):
        super().__init__()
        self.kind = kind
        self.path = ""
        self.highlighted = False
        self.accent = accent if accent in ("blue", "red") else None
        self.setProperty("role", "dropZone")
        if self.accent:
            self.setProperty("accent", self.accent)
        self.interactive = interactive or kind == "folder"
        self.allowed_extensions = set(allowed_extensions or self.AUDIO_EXTENSIONS)
        self.setAcceptDrops(self.interactive)
        if kind == "audio":
            self.setFixedSize(330, 150)
        else:
            self.setFixedHeight(150 if not compact else 126)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(4)
        icon_color = {"blue": "#3ca7e8", "red": "#ff2b1c"}.get(self.accent, "#aeb4bb")
        self.icon = LineIcon(icon_kind or "folder", icon_color, 48) if kind == "folder" else LineIcon("audio_file", icon_color, 42)
        self.title_label = label(
            "Drop a folder containing the loops you want to process"
            if kind == "folder" else "Drop one audio file here",
            "dropTitle" if kind == "folder" else "audioDropTitle",
        )
        self.title_label.setAlignment(Qt.AlignCenter)
        if kind == "folder":
            layout.addStretch()
        layout.addWidget(self.icon, 0, Qt.AlignHCenter)
        layout.addWidget(self.title_label)
        if kind != "folder":
            self.subtitle_label = label("or click to browse", "audioDropSubtitle")
            self.subtitle_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(self.subtitle_label)
        self.browse = button(
            "BROWSE" if kind == "folder" else "BROWSE FILE",
            "secondary" if kind == "folder" else "audioDropBrowse",
        )
        if self.accent:
            self.browse.setProperty("accent", self.accent)
        if kind == "folder":
            self.browse.setFixedWidth(112)
        else:
            self.browse.setFixedSize(122, 24)
        if kind == "folder":
            self.browse.clicked.connect(self.choose_folder)
        elif self.interactive:
            self.browse.clicked.connect(self.choose_audio)
        layout.addWidget(self.browse, 0, Qt.AlignHCenter)
        if kind != "folder":
            display_order = (".mp3", ".wav", ".flac")
            names = ", ".join(extension[1:].upper() for extension in display_order if extension in self.allowed_extensions)
            self.formats_label = label(f"Supported formats: {names}", "mutedSmall")
            self.formats_label.setAlignment(Qt.AlignCenter)
            layout.addSpacing(6)
            layout.addWidget(self.formats_label)
        layout.addStretch()

    def choose_folder(self):
        start = self.path or os.path.expanduser("~/Documents")
        selected = QFileDialog.getExistingDirectory(self, "Choose loops folder", start)
        if selected:
            self.set_path(selected)

    def choose_audio(self):
        start = os.path.dirname(self.path) if self.path else os.path.expanduser("~/Music")
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Choose one audio file",
            start,
            "Audio files (" + " ".join("*" + extension for extension in sorted(self.allowed_extensions)) + ")",
        )
        if selected:
            self.set_path(selected)

    def set_path(self, path):
        path = os.path.abspath(path) if path else ""
        if path:
            if self.kind == "folder" and not os.path.isdir(path):
                return False
            if self.kind == "audio" and (
                not os.path.isfile(path) or os.path.splitext(path)[1].lower() not in self.allowed_extensions
            ):
                return False
        self.path = path
        self.title_label.setText(os.path.basename(path) if path else "Drop a folder containing the loops you want to process")
        self.title_label.setToolTip(path)
        self.pathChanged.emit(path)
        return True

    def _drop_path(self, mime_data):
        if not self.interactive or not mime_data.hasUrls():
            return ""
        urls = mime_data.urls()
        if len(urls) != 1 or not urls[0].isLocalFile():
            return ""
        path = os.path.normpath(urls[0].toLocalFile())
        if self.kind == "folder":
            return path if os.path.isdir(path) else ""
        if self.kind == "audio" and os.path.isfile(path):
            return path if os.path.splitext(path)[1].lower() in self.allowed_extensions else ""
        return ""

    @staticmethod
    def _accept_copy(event):
        if event.possibleActions() & Qt.CopyAction:
            event.setDropAction(Qt.CopyAction)
        event.accept()

    def dragEnterEvent(self, event):
        if self._drop_path(event.mimeData()):
            self.highlighted = True
            self.update()
            self._accept_copy(event)
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._drop_path(event.mimeData()):
            self.highlighted = True
            self.update()
            self._accept_copy(event)
        else:
            self.highlighted = False
            self.update()
            event.ignore()

    def dragLeaveEvent(self, event):
        self.highlighted = False
        self.update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.highlighted = False
        path = self._drop_path(event.mimeData())
        if path and self.set_path(path):
            self._accept_copy(event)
        else:
            event.ignore()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        # Accent only the file icon, action button, and active drag feedback.
        # The resting drop surface and dashed frame stay neutral.
        base_color = "#67717a"
        highlight_color = {"blue": "#3ca7e8", "red": "#ff2b1c"}.get(self.accent, "#ff2b1c")
        pen = QPen(QColor(base_color), 1.25, Qt.DashLine)
        pen.setDashPattern([7, 6]); p.setPen(pen); p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(.8,.8,-1.3,-1.3), 6, 6)
        if self.highlighted:
            p.setPen(QPen(QColor(highlight_color), 2))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1.5, 1.5, -2, -2), 6, 6)


class OperationCard(QFrame):
    """A complete operation card that safely controls one Switch."""

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.setProperty("role", "operationCard")
        self.setProperty("operation", operation)
        self.setCursor(Qt.PointingHandCursor)
        self._target_switch = None
        self._pressed = False

    def bind_switch(self, target_switch, decorative_widgets=()):
        self._target_switch = target_switch
        for widget in decorative_widgets:
            widget.setAttribute(Qt.WA_TransparentForMouseEvents)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressed = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        pressed = self._pressed
        self._pressed = False
        if event.button() == Qt.LeftButton and pressed:
            if self.rect().contains(event.position().toPoint()) and self._target_switch is not None and self._target_switch.isEnabled():
                self._target_switch.setChecked(not self._target_switch.isChecked())
            event.accept()
            return
        super().mouseReleaseEvent(event)


class Switch(QFrame):
    toggled = Signal(bool)

    def __init__(self, checked=False):
        super().__init__()
        self.setProperty("role", "switch")
        self._checked = bool(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(76, 30)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(4, 3, 9, 3)
        self.dot = label("●", "switchDot")
        self.text_label = label("", "switchText")
        self.dot.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.text_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._refresh()

    def isChecked(self):
        return self._checked

    def setChecked(self, checked, emit=True):
        checked = bool(checked)
        if checked == self._checked:
            return
        self._checked = checked
        self._refresh()
        if emit:
            self.toggled.emit(checked)

    def _refresh(self):
        while self.row.count():
            self.row.takeAt(0)
        self.row.setContentsMargins(11, 3, 4, 3) if self._checked else self.row.setContentsMargins(4, 3, 11, 3)
        self.setProperty("active", self._checked)
        self.dot.setProperty("active", self._checked)
        self.text_label.setProperty("active", self._checked)
        self.text_label.setText("ON" if self._checked else "OFF")
        if self._checked:
            self.row.addWidget(self.text_label)
            self.row.addStretch()
            self.row.addWidget(self.dot)
        else:
            self.row.addWidget(self.dot)
            self.row.addStretch()
            self.row.addWidget(self.text_label)
        for widget in (self, self.dot, self.text_label):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.isEnabled():
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.setChecked(not self._checked)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    midiRequested = Signal(object, str, int)

    def __init__(self):
        super().__init__()
        self.storage = StorageManager()
        self.source_path = ""
        self.custom_destination = ""
        self.destination_mode = "copy_to_output"
        self.key_mode = "detected"
        self.accidentals = "sharps"
        self.token_order = list(TOKENS)
        self.quick_scan_busy = False
        self.pending_quick_scan = ""
        self.quick_scan_result = None
        self.quick_scan_path = ""
        self.quick_degree_reference = "major"
        self.quick_accidentals = "sharps"
        self.quick_scan_thread = None
        self.quick_scan_worker = None
        self.quick_extract_busy = False
        self.quick_extract_thread = None
        self.quick_extract_worker = None
        self.quick_extract_session = ""
        self.quick_convert_busy = False
        self.quick_convert_thread = None
        self.quick_convert_worker = None
        self.quick_convert_session = ""
        self.quick_convert_path = ""
        self.pending_quick_convert = ""
        self.midi_engine_state = "unloaded"
        self.midi_loader = None
        self.midi_loader_thread = None
        self.midi_thread = None
        self.midi_worker = None
        self.midi_job_id = 0
        self.pending_midi_job = None
        self.midi_cache = tempfile.mkdtemp(
            prefix="stem-slicer-quick-midi-",
            dir=QStandardPaths.writableLocation(QStandardPaths.TempLocation),
        )
        self.layer_cards = []
        self.active_layer_path = ""
        self.pending_layer_seek = None
        self.audio_output = QAudioOutput(self)
        self.media_player = QMediaPlayer(self)
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.playbackStateChanged.connect(self._playback_state_changed)
        self.media_player.mediaStatusChanged.connect(self._media_status_changed)
        self.media_player.positionChanged.connect(self._playback_position_changed)
        self.media_player.durationChanged.connect(self._playback_duration_changed)
        self.busy = False
        self.last_results = ""
        self.key_analyzer = None
        self.key_engine_state = "unloaded"
        self.key_loader_thread = None
        self.key_loader = None
        self.batch_thread = None
        self.batch_worker = None
        self.setWindowTitle(f"{APP_NAME} · {APP_VERSION}")
        self.setFixedSize(1440, 864)
        self.setWindowIcon(QIcon(resource_path("assets", "app-icon.png")))
        self._build()
        self._connect_stem_controls()
        self._sync_stem_state()
        self.select_tab(0)
        if os.environ.get("STEM_SLICER_DISABLE_ENGINE_AUTOSTART") != "1":
            self._start_key_engine()

    def _build(self):
        self.root = StudioRoot()
        self.setCentralWidget(self.root)
        outer = QVBoxLayout(self.root)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(10)
        self._header(outer)
        self._tabs(outer)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._stem_page())
        self.pages.addWidget(self._quick_page())
        outer.addWidget(self.pages, 1)

    def _header(self, outer):
        header = QFrame()
        header.setProperty("role", "header")
        header.setFixedHeight(112)
        row = QHBoxLayout(header)
        row.setContentsMargins(24, 10, 24, 10)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        brand.addWidget(image(resource_path("assets", "antiworld-logo.png"), 64, 70))
        copy = QVBoxLayout()
        copy.addStretch()
        copy.addWidget(label("MADE WITH <3 BY", "redSmall"))
        copy.addWidget(label("ANTIWORLD", "redBrand"))
        copy.addStretch()
        brand.addLayout(copy)
        row.addLayout(brand, 1)
        row.addWidget(image(resource_path("assets", "stem-slicer-wordmark.png"), 350, 88), 0, Qt.AlignCenter)
        build = QVBoxLayout()
        build.addStretch()
        a = label("LOOP LAYER EXTRACTION SYSTEM", "mutedSmall")
        b = label(APP_VERSION.upper(), "monoDim")
        a.setAlignment(Qt.AlignRight)
        b.setAlignment(Qt.AlignRight)
        build.addWidget(a)
        build.addWidget(b)
        build.addStretch()
        row.addLayout(build, 1)
        outer.addWidget(header)

    def _tabs(self, outer):
        shell = panel()
        shell.setFixedHeight(76)
        row = QHBoxLayout(shell)
        row.setContentsMargins(120, 0, 120, 0)
        row.setSpacing(78)
        self.stem_tab = TabButton("folder", "STEM SLICER", "Batch extract loops from a folder")
        self.quick_tab = TabButton("bolt", "QUICK TOOLS", "Fast operations on a single audio file")
        self.stem_tab.clicked.connect(lambda: self.select_tab(0))
        self.quick_tab.clicked.connect(lambda: self.select_tab(1))
        row.addWidget(self.stem_tab, 1)
        row.addWidget(self.quick_tab, 1)
        outer.addWidget(shell)

    def select_tab(self, index):
        self.pages.setCurrentIndex(index)
        self.stem_tab.setActive(index == 0)
        self.quick_tab.setActive(index == 1)

    def _stem_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        def step_heading(number, title, subtitle):
            heading = QHBoxLayout()
            heading.setSpacing(10)
            badge = label(str(number), "stepBadge")
            badge.setAlignment(Qt.AlignCenter)
            badge.setFixedSize(28, 28)
            copy = QVBoxLayout()
            copy.setSpacing(0)
            title_label = label(title, "workflowTitle")
            subtitle_label = label(subtitle, "mutedSmall")
            copy.addWidget(title_label)
            copy.addWidget(subtitle_label)
            heading.addWidget(badge, 0, Qt.AlignTop)
            heading.addLayout(copy)
            heading.addStretch()
            return heading, title_label

        # 1. The folder is shared by every workflow. It deliberately has no
        # extraction switch and never receives an extraction-only shade.
        source = panel("workflowPanel")
        source.setFixedHeight(170)
        self.source_panel = source
        self.layer_source_panel = source
        source_layout = QVBoxLayout(source)
        source_layout.setContentsMargins(16, 10, 16, 10)
        source_layout.setSpacing(6)
        source_heading, self.source_title = step_heading(
            1,
            "SOURCE FOLDER",
            "Select the folder containing the loops you want to process.",
        )
        source_layout.addLayout(source_heading)
        self.input_drop = DropZone("folder", compact=True, icon_kind="folder_in")
        self.input_drop.setFixedHeight(116)
        source_layout.addWidget(self.input_drop)
        layout.addWidget(source)

        # 2. Extraction and key analysis are sibling operations. Extraction is
        # intentionally compact because it has no additional parameters.
        operations = panel("workflowPanel")
        operations.setFixedHeight(236)
        self.operations_panel = operations
        operations_layout = QVBoxLayout(operations)
        operations_layout.setContentsMargins(14, 10, 14, 10)
        operations_layout.setSpacing(7)
        operations_heading, self.operations_title = step_heading(
            2,
            "OPERATIONS",
            "Enable Layer Extraction, Key Analysis, or both.",
        )
        operations_layout.addLayout(operations_heading)

        operation_row = QHBoxLayout()
        operation_row.setSpacing(12)

        self.layer_operation_card = OperationCard("extract")
        self.layer_operation_card.setProperty("active", True)
        self.layer_operation_card.setFixedHeight(60)
        layer_row = QHBoxLayout(self.layer_operation_card)
        layer_row.setContentsMargins(12, 6, 10, 6)
        layer_row.setSpacing(10)
        self.layer_operation_icon = LineIcon("layers", "#ff2b1c", 24)
        layer_row.addWidget(self.layer_operation_icon)
        layer_copy = QVBoxLayout()
        layer_copy.setSpacing(0)
        self.layer_title = label("LAYER EXTRACTION", "extractOperationTitle")
        self.layer_subtitle = label("Create playable layers from every loop.", "mutedSmall")
        layer_copy.addWidget(self.layer_title)
        layer_copy.addWidget(self.layer_subtitle)
        layer_row.addLayout(layer_copy)
        layer_row.addStretch()
        self.layer_switch = Switch(checked=True)
        layer_row.addWidget(self.layer_switch)
        self.layer_operation_card.bind_switch(
            self.layer_switch,
            (self.layer_operation_icon, self.layer_title, self.layer_subtitle),
        )
        operation_row.addWidget(self.layer_operation_card, 1)

        self.key_operation_card = OperationCard("key")
        self.key_operation_card.setProperty("active", False)
        self.key_operation_card.setFixedHeight(60)
        key_row = QHBoxLayout(self.key_operation_card)
        key_row.setContentsMargins(12, 6, 10, 6)
        key_row.setSpacing(10)
        self.key_operation_icon = LineIcon("key_scan", "#3ca7e8", 24)
        key_row.addWidget(self.key_operation_icon)
        key_copy = QVBoxLayout()
        key_copy.setSpacing(0)
        self.key_title = label("KEY ANALYSIS", "keyOperationTitle")
        self.key_subtitle = label("Detect keys and apply structured naming.", "mutedSmall")
        key_copy.addWidget(self.key_title)
        key_copy.addWidget(self.key_subtitle)
        key_row.addLayout(key_copy)
        key_row.addStretch()
        self.key_switch = Switch(checked=False)
        self.key_switch.setProperty("accent", "blue")
        key_row.addWidget(self.key_switch)
        self.key_operation_card.bind_switch(
            self.key_switch,
            (self.key_operation_icon, self.key_title, self.key_subtitle),
        )
        operation_row.addWidget(self.key_operation_card, 1)
        operations_layout.addLayout(operation_row)

        self.key_panel = QWidget()
        self.key_panel.setProperty("role", "keySettingsContainer")
        content = QHBoxLayout(self.key_panel)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(12)
        modes = panel("activeInner")
        ml = QVBoxLayout(modes); ml.setContentsMargins(0, 4, 0, 4); ml.setSpacing(3)
        mode_title = label("KEY MODE", "mutedCaps"); mode_title.setContentsMargins(10, 0, 10, 0); ml.addWidget(mode_title)
        self.key_setting_widgets = []
        mr = QHBoxLayout(); mr.setContentsMargins(10, 0, 10, 0)
        self.mode_buttons = {}
        for index, (mode, text) in enumerate((("detected", "DETECTED"), ("relative_minor", "RELATIVE MINOR"), ("relative_major", "RELATIVE MAJOR"))):
            mode_button = button(text, "selected" if index == 0 else "secondary")
            mode_button.setProperty("keyControl", True)
            mode_button.clicked.connect(lambda checked=False, value=mode: self._set_key_mode(value))
            self.mode_buttons[mode] = mode_button
            self.key_setting_widgets.append(mode_button)
            mr.addWidget(mode_button)
        ml.addLayout(mr)
        divider = QFrame(); divider.setProperty("role", "subtleSeparator"); divider.setFixedHeight(1); ml.addWidget(divider)
        notation_title = label("KEY NOTATION", "mutedCaps"); notation_title.setContentsMargins(10, 0, 10, 0); ml.addWidget(notation_title)
        ar = QHBoxLayout(); ar.setContentsMargins(10, 0, 10, 0)
        self.sharps_button = button("SHARPS #", "selected")
        self.flats_button = button("FLATS b")
        self.sharps_button.setProperty("keyControl", True)
        self.flats_button.setProperty("keyControl", True)
        self.sharps_button.clicked.connect(lambda: self._set_accidentals("sharps"))
        self.flats_button.clicked.connect(lambda: self._set_accidentals("flats"))
        self.key_setting_widgets.extend((self.sharps_button, self.flats_button))
        ar.addWidget(self.sharps_button); ar.addWidget(self.flats_button); ml.addLayout(ar)
        naming = panel("activeInner")
        nl = QVBoxLayout(naming); nl.setContentsMargins(12, 4, 12, 5); nl.setSpacing(2)
        nl.addWidget(label("OUTPUT NAME STRUCTURE", "mutedCaps"))
        nl.addWidget(label("Drag tokens to arrange how output files will be named.", "mutedSmall"))
        self.token_strip = TokenStrip(TOKENS, compact=True)
        self.token_strip.orderChanged.connect(self._token_order_changed)
        self.key_setting_widgets.append(self.token_strip)
        nl.addWidget(self.token_strip)
        nl.addWidget(label("PREVIEW", "mutedSmall"))
        self.name_preview_label = label("", "activeField")
        nl.addWidget(self.name_preview_label)
        content.addWidget(modes, 39)
        content.addWidget(naming, 61)
        operations_layout.addWidget(self.key_panel)
        self.key_opacity_effects = []
        for target in (modes, naming):
            effect = QGraphicsOpacityEffect(target)
            effect.setOpacity(0.28)
            target.setGraphicsEffect(effect)
            self.key_opacity_effects.append(effect)
        layout.addWidget(operations)

        # 3. Output is shared. Key-only destination choices live here instead
        # of inside Key Analysis settings, and remain visibly contextual.
        output = panel("workflowPanel")
        output.setFixedHeight(116)
        self.output_panel = output
        output_layout = QVBoxLayout(output)
        output_layout.setContentsMargins(14, 7, 14, 7)
        output_layout.setSpacing(3)
        output_heading, self.output_title = step_heading(
            3,
            "OUTPUT",
            "Review the destination generated by the selected operations.",
        )
        output_layout.addLayout(output_heading)

        output_columns = QHBoxLayout()
        output_columns.setSpacing(12)
        right = panel("resultPanel")
        self.layer_results_panel = right
        rl = QGridLayout(right)
        rl.setContentsMargins(10, 4, 10, 4)
        rl.setHorizontalSpacing(7)
        rl.setVerticalSpacing(2)
        self.results_title = label("EXTRACTED LAYERS LOCATION", "redSmall")
        rl.addWidget(self.results_title, 0, 0)
        location = QHBoxLayout()
        location.setContentsMargins(0, 0, 0, 0)
        location.setSpacing(7)
        self.results_location_icon = LineIcon("folder", "#a8afb6", 16)
        location.addWidget(self.results_location_icon)
        self.destination_path_label = label("", "muted")
        self.destination_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        location.addWidget(self.destination_path_label, 1)
        rl.addLayout(location, 1, 0)
        rl.setColumnStretch(0, 1)
        self.change_root_button = button("CHANGE")
        self.open_folder_button = icon_button("folder", "OPEN FOLDER", icon_size=16)
        fit_icon_button_width(self.open_folder_button, 150)
        self.reset_destination_button = button("RESET")
        self.reset_destination_button.setVisible(False)
        for item in (self.change_root_button, self.open_folder_button, self.reset_destination_button):
            item.setFixedHeight(27)
        rl.addWidget(self.change_root_button, 0, 1, 2, 1, Qt.AlignVCenter)
        rl.addWidget(self.open_folder_button, 0, 2, 2, 1, Qt.AlignVCenter)
        rl.addWidget(self.reset_destination_button, 0, 3, 2, 1, Qt.AlignVCenter)
        output_columns.addWidget(right, 58)

        destination_panel = panel("keyDestinationPanel")
        self.key_destination_panel = destination_panel
        destination_layout = QVBoxLayout(destination_panel)
        destination_layout.setContentsMargins(10, 4, 10, 4)
        destination_layout.setSpacing(2)
        self.key_destination_title = label("KEY ANALYSIS DESTINATION", "keySmall")
        destination_layout.addWidget(self.key_destination_title)
        dest = QHBoxLayout()
        dest.setSpacing(7)
        self.key_destination_visuals = {}
        for icon_kind, text in (("copy", "COPY TO ANALYZED LOOPS"), ("pencil", "RENAME ORIGINALS")):
            item = button("", "secondary")
            item.setProperty("keyDestination", True)
            item.setFixedHeight(27)
            item_l = QHBoxLayout(item); item_l.setContentsMargins(8, 1, 8, 1); item_l.setSpacing(5)
            item_l.addStretch()
            icon = LineIcon(icon_kind, "#9da4ab", 15)
            text_label = label(text, "buttonText")
            item_l.addWidget(icon); item_l.addWidget(text_label); item_l.addStretch(); dest.addWidget(item)
            self.key_destination_visuals[item] = (icon, text_label)
            self.key_setting_widgets.append(item)
            if icon_kind == "copy":
                self.copy_destination_button = item
            else:
                self.rename_destination_button = item
        destination_layout.addLayout(dest)
        self.key_destination_effect = QGraphicsOpacityEffect(destination_panel)
        self.key_destination_effect.setOpacity(0.28)
        destination_panel.setGraphicsEffect(self.key_destination_effect)
        output_columns.addWidget(destination_panel, 42)
        output_layout.addLayout(output_columns)

        info_row = QHBoxLayout()
        info_row.setSpacing(6)
        info_row.addWidget(LineIcon("info", "#4597c4", 14))
        self.destination_info_label = label(
            "Results are saved automatically to your Stem Slicer workspace.",
            "info",
        )
        info_row.addWidget(self.destination_info_label)
        info_row.addStretch()
        output_layout.addLayout(info_row)
        layout.addWidget(output)

        status = panel()
        status.setFixedHeight(86)
        self.status_panel = status
        sl = QHBoxLayout(status); sl.setContentsMargins(18, 10, 18, 10); sl.setSpacing(28)
        info = QVBoxLayout(); info.setSpacing(5)
        info.addWidget(label("PROCESS STATUS", "mutedCaps"))
        ready = QHBoxLayout(); ready.setSpacing(8); ready.addWidget(LineIcon("check", "#57d84e", 18)); self.process_status = label("Ready to choose a folder.", "status"); ready.addWidget(self.process_status); ready.addStretch(); info.addLayout(ready)
        progress = QHBoxLayout(); progress.setSpacing(16); self.progress_bar = QProgressBar(); self.progress_bar.setValue(0); progress.addWidget(self.progress_bar, 1); self.progress_counter = label("0 / 0", "mono"); progress.addWidget(self.progress_counter); info.addLayout(progress)
        sl.addLayout(info, 72)
        self.start_button = button("▶  EXTRACT LAYERS", "primary"); self.start_button.setFixedSize(310, 60); sl.addWidget(self.start_button)
        layout.addWidget(status)
        self.workflow_sections = (source, operations, output, status)
        self._update_name_preview()
        return page

    @staticmethod
    def _refresh_roles(*widgets):
        for widget in widgets:
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def _set_key_mode(self, mode):
        if mode not in self.mode_buttons:
            raise ValueError(f"Unknown key mode: {mode}")
        self.key_mode = mode
        for value, widget in self.mode_buttons.items():
            widget.setProperty("role", "selected" if value == mode else "secondary")
        self._refresh_roles(*self.mode_buttons.values())
        self._update_name_preview()

    def _set_accidentals(self, accidentals):
        if accidentals not in ("sharps", "flats"):
            raise ValueError(f"Unknown key notation: {accidentals}")
        self.accidentals = accidentals
        selected = self.sharps_button if accidentals == "sharps" else self.flats_button
        other = self.flats_button if accidentals == "sharps" else self.sharps_button
        selected.setProperty("role", "selected")
        other.setProperty("role", "secondary")
        self._refresh_roles(selected, other)
        self._update_name_preview()

    def _token_order_changed(self, order):
        order = list(order)
        if sorted(order) != sorted(TOKENS):
            raise ValueError("Invalid output-name token order")
        self.token_order = order
        self._update_name_preview()

    def _update_name_preview(self):
        if not hasattr(self, "name_preview_label"):
            return
        parts = parse_loop_filename("L CALLMEUR3 137 +NRGY.mp3")
        key = format_camelot("3A", self.key_mode, self.accidentals)
        layer_index = 1 if hasattr(self, "layer_switch") and self.layer_switch.isChecked() else None
        rendered = render_name(parts, self.token_order, key, layer_index=layer_index)
        self.name_preview_label.setText(f"♫   {rendered}")

    def _processing_settings(self):
        return {
            "enabled": self.key_switch.isChecked(),
            "extract_enabled": self.layer_switch.isChecked(),
            "mode": self.key_mode,
            "accidentals": self.accidentals,
            "destination_mode": self.destination_mode,
            "token_order": list(self.token_order),
        }

    def _connect_stem_controls(self):
        self.layer_switch.toggled.connect(self._sync_stem_state)
        self.key_switch.toggled.connect(self._sync_stem_state)
        self.input_drop.pathChanged.connect(self._source_changed)
        self.change_root_button.clicked.connect(self._change_storage_root)
        self.reset_destination_button.clicked.connect(self._reset_destination)
        self.open_folder_button.clicked.connect(self._open_current_destination)
        self.copy_destination_button.clicked.connect(lambda: self._set_destination_mode("copy_to_output"))
        self.rename_destination_button.clicked.connect(lambda: self._set_destination_mode("rename_in_place"))
        self.start_button.clicked.connect(self._start_batch)

    def _source_changed(self, path):
        self.source_path = path
        self._update_destination_preview()
        # The source path participates in the process-button state. Recompute
        # the complete workflow matrix here instead of waiting for a toggle to
        # change and incidentally trigger the refresh.
        self._sync_stem_state()

    def _change_storage_root(self):
        selected = QFileDialog.getExistingDirectory(
            self,
            "Choose a custom destination for this session",
            self.custom_destination or self.storage.root,
        )
        if selected:
            self.custom_destination = os.path.abspath(selected)
            self._update_destination_preview()

    def _reset_destination(self):
        self.custom_destination = ""
        self._update_destination_preview()

    def _current_destination(self):
        if self.destination_mode == "rename_in_place" and self.source_path:
            return self.source_path
        if self.custom_destination:
            return self.custom_destination
        category = "extractions" if self.layer_switch.isChecked() else "analyzed"
        return self.storage.category_path(category)

    def _open_current_destination(self):
        open_in_file_manager(self._current_destination())

    def _set_destination_mode(self, mode):
        if mode not in ("copy_to_output", "rename_in_place"):
            raise ValueError(f"Unknown destination mode: {mode}")
        self.destination_mode = mode
        selected = self.copy_destination_button if mode == "copy_to_output" else self.rename_destination_button
        other = self.rename_destination_button if mode == "copy_to_output" else self.copy_destination_button
        for widget, active_role in ((selected, "selected"), (other, "secondary")):
            locally_dimmed = not widget.isEnabled()
            widget.setProperty("role", "disabled" if locally_dimmed else active_role)
            icon, text_label = self.key_destination_visuals[widget]
            if locally_dimmed:
                icon.color = QColor("#454b51")
                text_role = "disabledButtonText"
            elif widget is selected:
                icon.color = QColor("#d9f2ff")
                text_role = "keySelectedButtonText"
            else:
                icon.color = QColor("#9da4ab")
                text_role = "buttonText"
            icon.update()
            text_label.setProperty("role", text_role)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            text_label.style().unpolish(text_label)
            text_label.style().polish(text_label)
        self._update_destination_preview()

    def _update_destination_preview(self):
        pack_name = os.path.basename(self.source_path) if self.source_path else "Loop Pack Name"
        if self.destination_mode == "rename_in_place" and self.source_path:
            preview = self.source_path
            info = "Original files will be renamed in place."
            custom_visible = False
        elif self.custom_destination:
            preview = os.path.join(self.custom_destination, pack_name)
            info = "Custom destination active for this session."
            custom_visible = True
        else:
            category = "extractions" if self.layer_switch.isChecked() else "analyzed"
            preview = os.path.join(self.storage.category_path(category), pack_name)
            info = "Results are saved automatically to your Stem Slicer workspace."
            custom_visible = False
        self.destination_path_label.setText(preview.replace(os.sep, " / "))
        self.destination_path_label.setToolTip(preview)
        self.destination_info_label.setText(info)
        self.reset_destination_button.setVisible(custom_visible)
        self.change_root_button.setEnabled(self.destination_mode != "rename_in_place" and not self.busy)

    def _sync_stem_state(self, *_):
        extract_enabled = self.layer_switch.isChecked()
        key_enabled = self.key_switch.isChecked()
        key_only = key_enabled and not extract_enabled

        engine_ready = self.key_engine_state == "ready"
        for widget in self.key_setting_widgets:
            widget.setEnabled(key_enabled and engine_ready and not self.busy)
        destination_enabled = key_only and engine_ready and not self.busy
        self.copy_destination_button.setEnabled(destination_enabled)
        self.rename_destination_button.setEnabled(destination_enabled)
        for effect in self.key_opacity_effects:
            effect.setOpacity(1.0 if key_enabled else 0.28)
        self.key_destination_effect.setOpacity(1.0 if key_only else 0.28)

        # Source Folder belongs to the complete workflow, not to Layer
        # Extraction. It stays fully visible and selectable in every idle state.
        self.input_drop.setEnabled(not self.busy)
        self.layer_switch.setEnabled(not self.busy)
        self.key_switch.setEnabled(not self.busy)

        self.layer_operation_card.setProperty("active", extract_enabled)
        self.key_operation_card.setProperty("active", key_enabled)
        self.layer_title.setProperty("active", extract_enabled)
        self.key_title.setProperty("active", key_enabled)
        self.key_panel.setProperty("active", key_enabled)

        if extract_enabled:
            self.results_title.setText("EXTRACTED LAYERS LOCATION")
            self.results_title.setProperty("role", "redSmall")
        elif key_enabled:
            self.results_title.setText("ANALYZED LOOPS LOCATION")
            self.results_title.setProperty("role", "keySmall")
        else:
            self.results_title.setText("RESULTS LOCATION")
            self.results_title.setProperty("role", "mutedCaps")

        if extract_enabled and key_enabled:
            action = "▶  SCAN KEYS + EXTRACT LAYERS"
            status = "Key analysis requires the musical key engine."
        elif extract_enabled:
            action = "▶  EXTRACT LAYERS"
            status = "Ready to choose a folder for extraction."
        elif key_enabled:
            action = "▶  SCAN KEYS"
            status = "Key analysis requires the musical key engine."
        else:
            action = "SELECT A PROCESS"
            status = "Enable Layer Extraction or Key Analysis."

        if key_enabled and self.key_engine_state == "loading":
            status = "Loading musical key engine…"
        elif key_enabled and self.key_engine_state == "failed":
            status = "Key engine unavailable."
        elif key_enabled and engine_ready:
            if not self.source_path:
                status = "Key engine ready."
            else:
                count = sum(1 for name in os.listdir(self.source_path) if name.lower().endswith(".mp3"))
                noun = f"{count} loop{'s' if count != 1 else ''}"
                status = f"Ready to scan and extract {noun}." if extract_enabled else f"Ready to scan {noun}."
        elif self.source_path and not key_enabled:
            count = sum(1 for name in os.listdir(self.source_path) if name.lower().endswith(".mp3"))
            status = f"Ready to extract {count} loop{'s' if count != 1 else ''}."

        can_start = bool(self.source_path) and (extract_enabled or key_enabled) and not self.busy
        if key_enabled:
            can_start = can_start and engine_ready
        self.start_button.setText(action)
        self.start_button.setEnabled(can_start)
        self.start_button.setProperty(
            "role",
            "keyPrimary" if key_only else ("primary" if extract_enabled else "secondary"),
        )
        self.start_button.setProperty("keyTextAccent", bool(extract_enabled and key_enabled))
        self.process_status.setText(status)
        if not key_only and self.destination_mode == "rename_in_place":
            self.destination_mode = "copy_to_output"
        self._set_destination_mode(self.destination_mode)
        self._update_destination_preview()
        self._update_name_preview()
        for widget in (
            self.layer_operation_card,
            self.key_operation_card,
            self.layer_title,
            self.key_title,
            self.key_panel,
            self.results_title,
            self.start_button,
        ):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def _start_key_engine(self):
        if self.key_engine_state in ("loading", "ready"):
            return
        self.key_engine_state = "loading"
        self.process_status.setText("Loading musical key engine…")
        self.key_loader_thread = QThread(self)
        self.key_loader = KeyEngineLoader()
        self.key_loader.moveToThread(self.key_loader_thread)
        self.key_loader_thread.started.connect(self.key_loader.run)
        self.key_loader.ready.connect(self._key_engine_ready)
        self.key_loader.failed.connect(self._key_engine_failed)
        self.key_loader.finished.connect(self.key_loader_thread.quit)
        self.key_loader.finished.connect(self.key_loader.deleteLater)
        self.key_loader_thread.finished.connect(self.key_loader_thread.deleteLater)
        self.key_loader_thread.finished.connect(self._key_loader_finished)
        self.key_loader_thread.start()

    @Slot(object)
    def _key_engine_ready(self, analyzer):
        self.key_analyzer = analyzer
        self.key_engine_state = "ready"
        self._sync_stem_state()
        if self.pending_quick_scan:
            path, self.pending_quick_scan = self.pending_quick_scan, ""
            self._run_quick_scan(path)
        if self.pending_quick_convert:
            path, self.pending_quick_convert = self.pending_quick_convert, ""
            self._quick_convert_requested(path)
        QTimer.singleShot(0, self._start_midi_engine)

    @Slot(str)
    def _key_engine_failed(self, message):
        self.key_engine_state = "failed"
        self.process_status.setText(f"Key engine unavailable: {message}")
        self._sync_stem_state()
        if self.quick_scan_busy:
            self._quick_scan_failed(message)
            self._quick_scan_finished()
        if self.quick_convert_busy:
            self._quick_convert_failed(message)
            self._quick_convert_finished()
        QTimer.singleShot(0, self._start_midi_engine)

    @Slot()
    def _key_loader_finished(self):
        self.key_loader_thread = None
        self.key_loader = None

    def _start_midi_engine(self):
        if self.midi_engine_state in ("loading", "ready"):
            return
        self.midi_engine_state = "loading"
        # A native Python thread keeps the interface responsive during the
        # secondary ONNX warm-up. A Qt QThread is used only after the model is
        # initialized; constructing the ONNX session directly in a QThread is
        # unstable on macOS.
        self.midi_loader = MidiEngineLoader()
        self.midi_loader.ready.connect(self._midi_converter_ready)
        self.midi_loader.failed.connect(self._midi_loader_failed)
        self.midi_loader_thread = threading.Thread(target=self.midi_loader.run, name="StemSlicerMidiLoader", daemon=True)
        self.midi_loader_thread.start()

    @Slot(object)
    def _midi_converter_ready(self, converter):
        self.midi_loader_thread = None
        self.midi_loader = None

        self.midi_thread = QThread(self)
        self.midi_worker = MidiWorker(converter)
        self.midi_worker.latest_job_id = self.midi_job_id
        self.midi_worker.moveToThread(self.midi_thread)
        self.midi_thread.started.connect(self.midi_worker.start)
        self.midiRequested.connect(self.midi_worker.convert)
        self.midi_worker.ready.connect(self._midi_engine_ready)
        self.midi_worker.progress.connect(self._midi_progress)
        self.midi_worker.completed.connect(self._midi_completed)
        self.midi_thread.start()

    @Slot(str)
    def _midi_loader_failed(self, message):
        self.midi_loader_thread = None
        self.midi_loader = None
        self.midi_engine_state = "failed"
        self._mark_pending_midi_unavailable(message)

    @Slot()
    def _midi_engine_ready(self):
        self.midi_engine_state = "ready"
        self._request_pending_midi()

    def _queue_midi_conversion(self, layers):
        self.midi_job_id += 1
        job_id = self.midi_job_id
        if self.midi_worker is not None:
            self.midi_worker.latest_job_id = job_id
        requests = [{"path": layer["path"], "bpm": int(layer.get("bpm") or 140)} for layer in layers]
        self.pending_midi_job = (job_id, requests)
        if not requests:
            self.pending_midi_job = None
            return
        if self.midi_engine_state == "failed":
            self._mark_pending_midi_unavailable()
            return
        self._request_pending_midi()

    def _invalidate_midi_jobs(self):
        self.midi_job_id += 1
        self.pending_midi_job = None
        if self.midi_worker is not None:
            # Plain Python state guarded by the GIL lets the active conversion
            # stop before processing another obsolete layer.
            self.midi_worker.latest_job_id = self.midi_job_id

    def _request_pending_midi(self):
        if self.midi_engine_state != "ready" or not self.pending_midi_job:
            return
        job_id, layers = self.pending_midi_job
        self.pending_midi_job = None
        self.midi_worker.latest_job_id = job_id
        job_cache = os.path.join(self.midi_cache, f"job-{job_id}")
        self.midiRequested.emit(layers, job_cache, job_id)

    @Slot(int, str, str, int, int)
    def _midi_progress(self, job_id, audio_path, midi_path, current, total):
        if job_id != self.midi_job_id:
            return
        for card in self.layer_cards:
            if card.layer["path"] == audio_path:
                card.setMidiPath(midi_path)
                break
        self.quick_extract_status.setText(f"{total} layers extracted  ·  Generating MIDI {current}/{total}…")

    @Slot(int, int, float)
    def _midi_completed(self, job_id, ready_count, elapsed):
        if job_id != self.midi_job_id:
            return
        total = len(self.layer_cards)
        layers_text = f"{total} layer{'s' if total != 1 else ''} extracted"
        midi_text = f"{ready_count} MIDI file{'s' if ready_count != 1 else ''} ready"
        if ready_count == total:
            self.quick_extract_status.setText(f"{layers_text}  ·  {midi_text}")
        else:
            self.quick_extract_status.setText(f"{layers_text}  ·  {midi_text}  ·  {total - ready_count} unavailable")

    def _mark_pending_midi_unavailable(self, _message=""):
        self.pending_midi_job = None
        for card in self.layer_cards:
            if card.midi_handle.state == "processing":
                card.setMidiPath("")
        if self.layer_cards:
            count = len(self.layer_cards)
            self.quick_extract_status.setText(f"{count} layers extracted  ·  MIDI unavailable")

    def _start_batch(self):
        if self.busy or self.quick_scan_busy or not self.source_path:
            return
        extract_enabled = self.layer_switch.isChecked()
        key_enabled = self.key_switch.isChecked()
        if key_enabled and self.key_engine_state != "ready":
            return
        if key_enabled and not extract_enabled and self.destination_mode == "rename_in_place":
            answer = QMessageBox.warning(
                self,
                "Rename original loops?",
                "Stem Slicer will rename every MP3 in the source folder after checking for filename collisions. Continue?",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if answer != QMessageBox.Yes:
                return

        if self.destination_mode == "rename_in_place" and not extract_enabled:
            output = ""
            self.last_results = self.source_path
        else:
            pack_name = os.path.basename(self.source_path)
            if self.custom_destination:
                output = self.storage.unique_session_folder_in(self.custom_destination, pack_name)
            else:
                category = "extractions" if extract_enabled else "analyzed"
                output = self.storage.unique_session_folder(category, pack_name)
            self.last_results = output

        settings = self._processing_settings()
        self.busy = True
        self.progress_bar.setValue(0)
        self.progress_counter.setText("0 / 0")
        self.process_status.setText("Preparing audio engine…")
        self._sync_stem_state()

        self.batch_thread = QThread(self)
        self.batch_worker = BatchWorker(
            self.source_path,
            output,
            settings,
            analyzer=self.key_analyzer if key_enabled else None,
        )
        self.batch_worker.moveToThread(self.batch_thread)
        self.batch_thread.started.connect(self.batch_worker.run)
        self.batch_worker.progress.connect(self._batch_progress)
        self.batch_worker.completed.connect(self._batch_completed)
        self.batch_worker.failed.connect(self._batch_failed)
        self.batch_worker.finished.connect(self.batch_thread.quit)
        self.batch_worker.finished.connect(self.batch_worker.deleteLater)
        self.batch_thread.finished.connect(self.batch_thread.deleteLater)
        self.batch_thread.finished.connect(self._batch_finished)
        self.batch_thread.start()

    @Slot(int, int, str)
    def _batch_progress(self, current, total, status):
        self.progress_bar.setValue(int(current * 100 / total) if total else 0)
        self.progress_counter.setText(f"{current} / {total}")
        self.process_status.setText(status)

    @Slot(object, object)
    def _batch_completed(self, failures, manifest):
        self.progress_bar.setValue(100)
        self.process_status.setText("Processing complete.")
        if failures:
            QMessageBox.warning(self, "Stem Slicer", f"Completed with {len(failures)} key-analysis warning(s).")

    @Slot(str)
    def _batch_failed(self, message):
        self.process_status.setText(f"Processing stopped: {message}")
        QMessageBox.critical(self, "Stem Slicer", message)

    @Slot()
    def _batch_finished(self):
        self.busy = False
        self.batch_thread = None
        self.batch_worker = None
        self._sync_stem_state()

    def closeEvent(self, event):
        self.media_player.stop()
        if self.midi_thread is not None and self.midi_thread.isRunning():
            self.midi_worker.latest_job_id = -1
            self.midi_thread.quit()
            if not self.midi_thread.wait(30_000):
                event.ignore()
                return
        if self.midi_loader_thread is not None and self.midi_loader_thread.is_alive():
            self.midi_loader_thread.join(10)
        if self.quick_extract_thread is not None and self.quick_extract_thread.isRunning():
            self.quick_extract_thread.quit()
            self.quick_extract_thread.wait(50_000)
        if self.quick_scan_thread is not None and self.quick_scan_thread.isRunning():
            self.quick_scan_thread.quit()
            self.quick_scan_thread.wait(50_000)
        if self.quick_convert_thread is not None and self.quick_convert_thread.isRunning():
            self.quick_convert_thread.quit()
            self.quick_convert_thread.wait(50_000)
        if self.key_loader_thread is not None and self.key_loader_thread.isRunning():
            self.key_loader_thread.quit()
            self.key_loader_thread.wait(50_000)
        if self.key_analyzer is not None:
            self.key_analyzer.stop()
            self.key_analyzer = None
        super().closeEvent(event)

    def _result_card(self, title, value, modal_name=None, degree=None, bind=None):
        card = panel("result")
        card.setFixedHeight(104)
        vl = QVBoxLayout(card); vl.setContentsMargins(8, 15, 8, 8); vl.setSpacing(2)
        t = label(title, "resultTitle"); t.setAlignment(Qt.AlignCenter)
        v = label(value, "keyValue"); v.setAlignment(Qt.AlignCenter)
        vl.addWidget(t); vl.addStretch(); vl.addWidget(v)
        if modal_name:
            modal = label(modal_name, "keyModeName"); modal.setAlignment(Qt.AlignCenter); vl.addWidget(modal)
        if degree:
            degree_label = label(degree, "degreeValue"); degree_label.setAlignment(Qt.AlignCenter); vl.addWidget(degree_label)
        else:
            degree_label = None
        vl.addStretch()
        if bind:
            setattr(self, f"{bind}_value", v)
            setattr(self, f"{bind}_modal", modal if modal_name else None)
            setattr(self, f"{bind}_degree", degree_label)
        return card

    def _modes_card(self):
        card = panel("result"); card.setFixedHeight(104)
        layout = QVBoxLayout(card); layout.setContentsMargins(14, 7, 14, 7); layout.setSpacing(3)
        title = label("RELATIVE MODES", "resultTitle"); title.setAlignment(Qt.AlignCenter); layout.addWidget(title)
        modes = QHBoxLayout(); modes.setSpacing(6)
        self.quick_mode_labels = []
        for _ in range(5):
            chip = QFrame(); chip.setProperty("role", "modeChip")
            chip_layout = QVBoxLayout(chip); chip_layout.setContentsMargins(7, 4, 7, 4); chip_layout.setSpacing(0)
            key = label("—", "modeFull"); key.setAlignment(Qt.AlignCenter)
            degree_label = label("—", "modeDegree"); degree_label.setAlignment(Qt.AlignCenter)
            chip_layout.addWidget(key); chip_layout.addWidget(degree_label); modes.addWidget(chip)
            self.quick_mode_labels.append((key, degree_label))
        layout.addLayout(modes)
        self.quick_modes_note = label("Scan a file to reveal its relative modes.", "modeNote")
        self.quick_modes_note.setAlignment(Qt.AlignCenter); layout.addWidget(self.quick_modes_note)
        return card

    def _set_quick_degree_reference(self, reference):
        if reference not in ("major", "minor"):
            raise ValueError(f"Unknown degree reference: {reference}")
        self.quick_degree_reference = reference
        self.quick_major_button.setProperty("role", "compactSelected" if reference == "major" else "compact")
        self.quick_minor_button.setProperty("role", "compactSelected" if reference == "minor" else "compact")
        self._refresh_roles(self.quick_major_button, self.quick_minor_button)
        self._update_quick_scan_results()

    def _set_quick_accidentals(self, accidentals):
        if accidentals not in ("sharps", "flats"):
            raise ValueError(f"Unknown key notation: {accidentals}")
        self.quick_accidentals = accidentals
        self.quick_sharps_button.setProperty("role", "compactSelected" if accidentals == "sharps" else "compact")
        self.quick_flats_button.setProperty("role", "compactSelected" if accidentals == "flats" else "compact")
        self._refresh_roles(self.quick_sharps_button, self.quick_flats_button)
        self._update_quick_scan_results()

    def _quick_scan_requested(self, path):
        if not path or self.quick_scan_busy or self.busy:
            return
        self.quick_scan_busy = True
        self.quick_scan_path = path
        self.quick_scan_result = None
        self._update_quick_scan_results()
        self.quick_scan_drop.setEnabled(False)
        self.quick_scan_opacity = QGraphicsOpacityEffect(self.quick_scan_drop)
        self.quick_scan_opacity.setOpacity(0.45)
        self.quick_scan_drop.setGraphicsEffect(self.quick_scan_opacity)
        self.quick_scan_filename_label.setText(os.path.basename(path))
        self.quick_scan_check.setVisible(False)
        self.quick_scan_time_label.setText("Loading musical key engine…" if self.key_engine_state != "ready" else "Analyzing…")
        if self.key_engine_state == "ready":
            self._run_quick_scan(path)
        elif self.key_engine_state == "failed":
            self._quick_scan_failed("Key engine unavailable.")
            self._quick_scan_finished()
        else:
            self.pending_quick_scan = path
            if self.key_engine_state == "unloaded":
                self._start_key_engine()

    def _run_quick_scan(self, path):
        self.quick_scan_time_label.setText("Analyzing…")
        self.quick_scan_thread = QThread(self)
        self.quick_scan_worker = QuickScanWorker(self.key_analyzer, path)
        self.quick_scan_worker.moveToThread(self.quick_scan_thread)
        self.quick_scan_thread.started.connect(self.quick_scan_worker.run)
        self.quick_scan_worker.completed.connect(self._quick_scan_completed)
        self.quick_scan_worker.failed.connect(self._quick_scan_failed)
        self.quick_scan_worker.finished.connect(self.quick_scan_thread.quit)
        self.quick_scan_worker.finished.connect(self.quick_scan_worker.deleteLater)
        self.quick_scan_thread.finished.connect(self.quick_scan_thread.deleteLater)
        self.quick_scan_thread.finished.connect(self._quick_scan_finished)
        self.quick_scan_thread.start()

    @Slot(object, float)
    def _quick_scan_completed(self, result, elapsed):
        self.quick_scan_result = result
        self.quick_scan_check.setVisible(True)
        self.quick_scan_time_label.setText(f"Analyzed in {elapsed:.1f} seconds")
        self._update_quick_scan_results()

    @Slot(str)
    def _quick_scan_failed(self, message):
        self.quick_scan_result = None
        self._update_quick_scan_results()
        self.quick_scan_check.setVisible(False)
        self.quick_scan_time_label.setText(f"Analysis failed: {message}")

    @Slot()
    def _quick_scan_finished(self):
        self.quick_scan_busy = False
        self.pending_quick_scan = ""
        self.quick_scan_drop.setGraphicsEffect(None)
        self.quick_scan_opacity = None
        self.quick_scan_drop.setEnabled(True)
        self.quick_scan_thread = None
        self.quick_scan_worker = None

    def _degree_for_mode(self, mode_index):
        if self.quick_degree_reference == "major":
            return ROMAN[mode_index]
        return ROMAN[(mode_index - 5) % 7]

    def _update_quick_scan_results(self):
        if not hasattr(self, "quick_detected_value"):
            return
        if not self.quick_scan_result:
            self.quick_bpm_value.setText("—")
            for prefix in ("quick_detected", "quick_relative"):
                getattr(self, f"{prefix}_value").setText("—")
                getattr(self, f"{prefix}_modal").setText("—")
                getattr(self, f"{prefix}_degree").setText("—")
            for key_label, degree_label in self.quick_mode_labels:
                key_label.setText("—")
                degree_label.setText("—")
            self.quick_modes_note.setText("Scan a file to reveal its relative modes.")
            return
        self.quick_bpm_value.setText(str(canonical_loop_bpm(self.quick_scan_result.get("bpm"))) or "—")
        camelot = self.quick_scan_result["camelot"]
        detected = format_camelot(camelot, "detected", self.quick_accidentals)
        detected_is_major = camelot.endswith("B")
        relative_mode = "relative_minor" if detected_is_major else "relative_major"
        relative = format_camelot(camelot, relative_mode, self.quick_accidentals)
        detected_note, _ = key_parts(detected)
        relative_note, relative_is_major = key_parts(relative)
        detected_index = 0 if detected_is_major else 5
        relative_index = 0 if relative_is_major else 5
        self.quick_detected_value.setText(f"{detected_note} {'major' if detected_is_major else 'minor'}")
        self.quick_detected_modal.setText(f"{detected_note} {MODE_NAMES[detected_index]}")
        self.quick_detected_degree.setText(self._degree_for_mode(detected_index))
        self.quick_relative_value.setText(f"{relative_note} {'major' if relative_is_major else 'minor'}")
        self.quick_relative_modal.setText(f"{relative_note} {MODE_NAMES[relative_index]}")
        self.quick_relative_degree.setText(self._degree_for_mode(relative_index))

        major_key = format_camelot(camelot, "relative_major", self.quick_accidentals)
        major_note, _ = key_parts(major_key)
        names = FLAT_PITCHES if self.quick_accidentals == "flats" else SHARP_PITCHES
        tonic = pitch_index(major_note)
        remaining_modes = (1, 2, 3, 4, 6)
        for (key_label, degree_label), mode_index in zip(self.quick_mode_labels, remaining_modes):
            note = names[(tonic + MAJOR_INTERVALS[mode_index]) % 12]
            key_label.setText(f"{note} {MODE_NAMES[mode_index]}")
            degree_label.setText(self._degree_for_mode(mode_index))
        self.quick_modes_note.setText("Same notes · different centers")

    def _quick_extract_requested(self, path):
        if not path or self.quick_extract_busy or self.busy or self.quick_scan_busy:
            return
        self._invalidate_midi_jobs()
        self._populate_layer_cards([], "Extracting layers…")
        self.quick_extract_busy = True
        self.quick_extract_drop.setEnabled(False)
        effect = QGraphicsOpacityEffect(self.quick_extract_drop); effect.setOpacity(0.45); self.quick_extract_drop.setGraphicsEffect(effect); self.quick_extract_opacity = effect
        self.quick_extract_filename.setText(os.path.basename(path))
        self.quick_extract_check.setVisible(False)
        self.quick_extract_status.setText("Extracting layers…")
        self.quick_show_results.setEnabled(False)
        session_name = os.path.splitext(os.path.basename(path))[0]
        self.quick_extract_session = self.storage.unique_session_folder("quick", session_name)
        self.quick_extract_thread = QThread(self)
        self.quick_extract_worker = QuickExtractWorker(path, self.quick_extract_session)
        self.quick_extract_worker.moveToThread(self.quick_extract_thread)
        self.quick_extract_thread.started.connect(self.quick_extract_worker.run)
        self.quick_extract_worker.completed.connect(self._quick_extract_completed)
        self.quick_extract_worker.failed.connect(self._quick_extract_failed)
        self.quick_extract_worker.finished.connect(self.quick_extract_thread.quit)
        self.quick_extract_worker.finished.connect(self.quick_extract_worker.deleteLater)
        self.quick_extract_thread.finished.connect(self.quick_extract_thread.deleteLater)
        self.quick_extract_thread.finished.connect(self._quick_extract_finished)
        self.quick_extract_thread.start()

    @Slot(object, float)
    def _quick_extract_completed(self, layers, elapsed):
        self._populate_layer_cards(layers)
        count = len(layers)
        self.quick_extract_check.setVisible(True)
        if count:
            self.quick_extract_status.setText(f"{count} layer{'s' if count != 1 else ''} extracted  ·  Generating MIDI…")
        else:
            self.quick_extract_status.setText("No complete layers were detected in this loop.")
        self.quick_show_results.setEnabled(True)
        self._refresh_quick_storage()
        self._queue_midi_conversion(layers)

    @Slot(str)
    def _quick_extract_failed(self, message):
        self._populate_layer_cards([], "Extraction failed. Drop the audio file again to retry.")
        self.quick_extract_check.setVisible(False)
        self.quick_extract_status.setText(f"Extraction failed: {message}")

    @Slot()
    def _quick_extract_finished(self):
        self.quick_extract_busy = False
        self.quick_extract_drop.setGraphicsEffect(None); self.quick_extract_opacity = None; self.quick_extract_drop.setEnabled(True)
        self.quick_extract_thread = None; self.quick_extract_worker = None

    def _populate_layer_cards(self, layers, empty_text="No complete layers were detected in this loop.", show_empty_icon=False):
        for row in range(self.quick_layer_grid.rowCount() + 2):
            self.quick_layer_grid.setRowStretch(row, 0)
        while self.quick_layer_grid.count():
            item = self.quick_layer_grid.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().setParent(None)
                item.widget().deleteLater()
        self.layer_cards = []
        self.quick_layers_empty_state = None
        self.quick_layers_empty_icon = None
        self.quick_layers_empty_label = None
        for index, layer in enumerate(layers):
            card = LayerCard(layer); card.playRequested.connect(self._toggle_layer_playback)
            card.seekRequested.connect(self._seek_layer)
            self.layer_cards.append(card); self.quick_layer_grid.addWidget(card, index // 3, index % 3)
        if layers:
            self.quick_layer_grid.setRowStretch((len(layers) + 2) // 3, 1)
            return

        empty_state = QWidget()
        empty_state.setProperty("role", "quickLayersEmpty")
        empty_layout = QVBoxLayout(empty_state)
        empty_layout.setContentsMargins(16, 16, 16, 16)
        empty_layout.setSpacing(7)
        empty_layout.addStretch()
        if show_empty_icon:
            self.quick_layers_empty_icon = LineIcon("layers", "#777e85", 42)
            empty_layout.addWidget(self.quick_layers_empty_icon, 0, Qt.AlignHCenter)
        self.quick_layers_empty_label = label(empty_text, "quickEmptyText", wrap=True)
        self.quick_layers_empty_label.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.quick_layers_empty_label)
        empty_layout.addStretch()
        self.quick_layers_empty_state = empty_state
        self.quick_layer_grid.addWidget(empty_state, 0, 0, 1, 3)
        self.quick_layer_grid.setRowStretch(0, 1)

    def _toggle_layer_playback(self, path):
        state = self.media_player.playbackState()
        if self.active_layer_path == path and state == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause(); return
        if self.active_layer_path == path and state == QMediaPlayer.PlaybackState.PausedState:
            self.media_player.play(); return
        self.media_player.stop(); self.active_layer_path = path; self.media_player.setSource(QUrl.fromLocalFile(path)); self.media_player.play()

    @Slot(str, float)
    def _seek_layer(self, path, ratio):
        ratio = max(0.0, min(1.0, float(ratio)))
        for card in self.layer_cards:
            if card.layer["path"] == path: card.setProgress(ratio)
        if self.active_layer_path != path:
            self.media_player.stop(); self.active_layer_path = path; self.pending_layer_seek = ratio
            self.media_player.setSource(QUrl.fromLocalFile(path)); self.media_player.play()
        else:
            duration = self.media_player.duration()
            if duration > 0:
                self.media_player.setPosition(int(duration * ratio))
            else:
                self.pending_layer_seek = ratio

    @Slot(object)
    def _playback_state_changed(self, state):
        self._update_layer_playback_states()

    @Slot(int)
    def _playback_position_changed(self, position):
        self._update_layer_progress(position, self.media_player.duration())

    @Slot(int)
    def _playback_duration_changed(self, duration):
        self._update_layer_progress(self.media_player.position(), duration)

    def _update_layer_progress(self, position, duration):
        progress = position / duration if duration > 0 else 0.0
        for card in self.layer_cards:
            card.setProgress(progress if card.layer["path"] == self.active_layer_path else 0.0)

    @Slot(object)
    def _media_status_changed(self, status):
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia) and self.pending_layer_seek is not None:
            duration = self.media_player.duration()
            if duration > 0:
                self.media_player.setPosition(int(duration * self.pending_layer_seek)); self.pending_layer_seek = None
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.active_layer_path = ""; self._update_layer_playback_states(); self._update_layer_progress(0, 0)

    def _update_layer_playback_states(self):
        player_state = self.media_player.playbackState()
        for card in self.layer_cards:
            if card.layer["path"] != self.active_layer_path:
                card.setPlaybackState("stopped")
            elif player_state == QMediaPlayer.PlaybackState.PlayingState:
                card.setPlaybackState("playing")
            elif player_state == QMediaPlayer.PlaybackState.PausedState:
                card.setPlaybackState("paused")
            else:
                card.setPlaybackState("stopped")

    def _show_quick_results(self):
        if self.quick_extract_session: open_in_file_manager(self.quick_extract_session)

    def _open_quick_root(self):
        open_in_file_manager(self.storage.category_path("quick"))

    def _quick_storage_stats(self):
        extracts = self.storage.list_quick_extracts()
        return len(extracts), sum(item["size"] for item in extracts)

    def _refresh_quick_storage(self):
        count, total = self._quick_storage_stats()
        self.quick_storage_label.setText(f"{count} extract{'s' if count != 1 else ''} · {format_decimal_size(total)}")

    def _manage_quick_storage(self):
        QuickExtractManagerDialog(self.storage, self._refresh_quick_storage, self).exec()

    def _quick_convert_output_name(self, source, bpm, target_key):
        parts = parse_loop_filename(source)
        parts["BPM"] = str(int(bpm))
        parts["KEY"] = target_key.split("/")[0].strip()
        return render_name(parts, ("LOOP NAME", "BPM", "KEY", "PROD NAME"))

    def _quick_convert_requested(self, path):
        if not path or self.quick_convert_busy or self.busy:
            return
        self.quick_convert_busy = True
        self.quick_convert_path = path
        self.quick_convert_filename.setText(os.path.basename(path))
        self.quick_convert_check.setVisible(False)
        self.quick_convert_status.setText("Loading musical key engine…" if self.key_engine_state != "ready" else "Converting…")
        self.quick_convert_drop.setEnabled(False)
        if self.key_engine_state == "loading":
            self.pending_quick_convert = path
            return
        if self.key_engine_state != "ready":
            self._quick_convert_failed("Key engine unavailable.")
            self._quick_convert_finished()
            return
        target_bpm = int(self.quick_convert_bpm.text() or 120)
        target_key = self.quick_convert_key.currentText()
        session_name = os.path.splitext(os.path.basename(path))[0]
        self.quick_convert_session = self.storage.unique_session_folder("convert", session_name)
        output = os.path.join(
            self.quick_convert_session,
            self._quick_convert_output_name(path, target_bpm, target_key),
        )
        self.quick_convert_thread = QThread(self)
        self.quick_convert_worker = QuickConvertWorker(
            self.key_analyzer, path, output, target_bpm, target_key,
        )
        self.quick_convert_worker.moveToThread(self.quick_convert_thread)
        self.quick_convert_thread.started.connect(self.quick_convert_worker.run)
        self.quick_convert_worker.completed.connect(self._quick_convert_completed)
        self.quick_convert_worker.failed.connect(self._quick_convert_failed)
        self.quick_convert_worker.finished.connect(self.quick_convert_thread.quit)
        self.quick_convert_worker.finished.connect(self.quick_convert_worker.deleteLater)
        self.quick_convert_thread.finished.connect(self.quick_convert_thread.deleteLater)
        self.quick_convert_thread.finished.connect(self._quick_convert_finished)
        self.quick_convert_thread.start()

    @Slot(object, float)
    def _quick_convert_completed(self, result, elapsed):
        self.quick_convert_check.setVisible(True)
        self.quick_convert_filename.setText(os.path.basename(result["path"]))
        self.quick_convert_filename.setToolTip(result["path"])
        self.quick_convert_status.setText(
            f"Converted to {result['target_bpm']} BPM · {result['target_key'].split('/')[0].strip()} · {elapsed:.1f}s"
        )
        self.quick_convert_drag.set_path(result["path"])
        self._refresh_quick_convert_storage()

    @Slot(str)
    def _quick_convert_failed(self, message):
        self.quick_convert_check.setVisible(False)
        self.quick_convert_status.setText(f"Conversion failed: {message}")

    @Slot()
    def _quick_convert_finished(self):
        self.quick_convert_busy = False
        self.pending_quick_convert = ""
        self.quick_convert_drop.setEnabled(True)
        self.quick_convert_thread = None
        self.quick_convert_worker = None

    def _quick_convert_storage_stats(self):
        entries = self.storage.list_quick_conversions()
        return len(entries), sum(item["size"] for item in entries)

    def _refresh_quick_convert_storage(self):
        count, total = self._quick_convert_storage_stats()
        self.quick_convert_storage_label.setText(
            f"{count} conversion{'s' if count != 1 else ''} · {format_decimal_size(total)}"
        )

    def _open_quick_convert_root(self):
        open_in_file_manager(self.storage.category_path("convert"))

    def _manage_quick_convert_storage(self):
        QuickConvertManagerDialog(self.storage, self._refresh_quick_convert_storage, self).exec()

    def _quick_page(self):
        page = QWidget()
        layout = QVBoxLayout(page); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(9)
        scan = panel(); scan.setProperty("sectionAccent", "blue"); scan.setFixedHeight(226); self.quick_scan_panel = scan
        scan_l = QVBoxLayout(scan); scan_l.setContentsMargins(18, 10, 18, 10); scan_l.setSpacing(6)
        heading = QHBoxLayout(); title = QVBoxLayout(); title.setSpacing(2)
        self.quick_scan_title = label("QUICK SCAN", "pageTitle")
        title.addWidget(self.quick_scan_title); title.addWidget(label("Detect key relationships from one audio file", "muted"))
        heading.addLayout(title); heading.addStretch()
        heading.addWidget(label("DEGREE REFERENCE", "degreeReference"))
        self.quick_major_button = button("MAJOR", "compactSelected"); self.quick_minor_button = button("MINOR", "compact"); self.quick_major_button.setFixedSize(68, 27); self.quick_minor_button.setFixedSize(68, 27)
        self.quick_major_button.clicked.connect(lambda: self._set_quick_degree_reference("major")); self.quick_minor_button.clicked.connect(lambda: self._set_quick_degree_reference("minor"))
        heading.addWidget(self.quick_major_button); heading.addWidget(self.quick_minor_button); heading.addSpacing(16)
        heading.addWidget(label("KEY NOTATION", "controlLabel"))
        self.quick_sharps_button = button("SHARPS #", "compactSelected"); self.quick_flats_button = button("FLATS b", "compact"); self.quick_sharps_button.setFixedSize(68, 27); self.quick_flats_button.setFixedSize(68, 27)
        self.quick_sharps_button.clicked.connect(lambda: self._set_quick_accidentals("sharps")); self.quick_flats_button.clicked.connect(lambda: self._set_quick_accidentals("flats"))
        heading.addWidget(self.quick_sharps_button); heading.addWidget(self.quick_flats_button); scan_l.addLayout(heading)
        body = QHBoxLayout(); body.setSpacing(18); self.quick_scan_drop = DropZone("audio", interactive=True, accent="blue"); self.quick_scan_drop.pathChanged.connect(self._quick_scan_requested); body.addWidget(self.quick_scan_drop, 0, Qt.AlignTop)
        results = QVBoxLayout()
        cards = QHBoxLayout(); cards.setSpacing(14)
        self.quick_bpm_card = self._result_card("BPM", "—", bind="quick_bpm")
        self.quick_detected_card = self._result_card("DETECTED KEY", "—", "—", "—", "quick_detected")
        self.quick_relative_card = self._result_card("RELATIVE KEY", "—", "—", "—", "quick_relative")
        self.quick_modes_card = self._modes_card()
        cards.addWidget(self.quick_bpm_card, 14)
        cards.addWidget(self.quick_detected_card, 24)
        cards.addWidget(self.quick_relative_card, 24)
        cards.addWidget(self.quick_modes_card, 38)
        results.addLayout(cards)
        scan_result = QFrame(); scan_result.setProperty("role", "resultLine"); scan_result.setFixedWidth(535)
        file_row = QHBoxLayout(scan_result); file_row.setContentsMargins(11, 6, 11, 6); file_row.setSpacing(8)
        file_row.addWidget(LineIcon("music_note", "#3ca7e8", 22)); self.quick_scan_filename_label = label("Drop a file to begin.", "scannedFile"); file_row.addWidget(self.quick_scan_filename_label)
        file_row.addSpacing(5); self.quick_scan_check = LineIcon("check", "#57d84e", 16); self.quick_scan_check.setVisible(False); file_row.addWidget(self.quick_scan_check); self.quick_scan_time_label = label("", "analyzedTime"); file_row.addWidget(self.quick_scan_time_label); file_row.addStretch()
        scan_footer = QWidget(); scan_footer.setFixedHeight(40)
        scan_footer_layout = QHBoxLayout(scan_footer); scan_footer_layout.setContentsMargins(0, 0, 0, 0)
        scan_footer_layout.addWidget(scan_result, 0, Qt.AlignVCenter); scan_footer_layout.addStretch()
        results.addWidget(scan_footer)
        results.addStretch(1)
        body.addLayout(results, 69); scan_l.addLayout(body)
        layout.addWidget(scan)

        convert = panel(); convert.setProperty("sectionAccent", "orange"); convert.setFixedHeight(142)
        convert_layout = QVBoxLayout(convert); convert_layout.setContentsMargins(18, 10, 18, 9); convert_layout.setSpacing(7)
        convert_heading = QVBoxLayout(); convert_heading.setSpacing(1)
        convert_heading.addWidget(label("QUICK CONVERT", "pageTitle"))
        convert_heading.addWidget(label("Convert one loop to a selected BPM and key", "muted"))
        convert_layout.addLayout(convert_heading)
        convert_body = QHBoxLayout(); convert_body.setSpacing(12)
        self.quick_convert_drop = DropZone("audio", compact=True, interactive=True, allowed_extensions={".mp3", ".wav", ".flac"}, accent="orange")
        self.quick_convert_drop.setFixedWidth(330); self.quick_convert_drop.pathChanged.connect(self._quick_convert_requested)
        convert_body.addWidget(self.quick_convert_drop)
        settings = panel("result"); settings_layout = QHBoxLayout(settings); settings_layout.setContentsMargins(12, 6, 12, 6); settings_layout.setSpacing(8)
        settings_layout.addWidget(label("BPM", "controlLabel"))
        self.quick_convert_bpm = QLineEdit("120"); self.quick_convert_bpm.setMaxLength(3); self.quick_convert_bpm.setFixedWidth(70)
        settings_layout.addWidget(self.quick_convert_bpm)
        settings_layout.addWidget(label("KEY", "controlLabel"))
        self.quick_convert_key = QComboBox(); self.quick_convert_key.addItems(TARGET_KEYS); self.quick_convert_key.setFixedWidth(220)
        settings_layout.addWidget(self.quick_convert_key); settings_layout.addStretch()
        convert_body.addWidget(settings, 1)
        converted = QFrame(); converted.setProperty("role", "resultLine"); converted_layout = QHBoxLayout(converted); converted_layout.setContentsMargins(10, 5, 10, 5); converted_layout.setSpacing(7)
        converted_layout.addWidget(LineIcon("music_note", "#e6a128", 20))
        self.quick_convert_filename = label("Ready for one loop.", "scannedFile"); converted_layout.addWidget(self.quick_convert_filename, 1)
        self.quick_convert_check = LineIcon("check", "#57d84e", 16); self.quick_convert_check.setVisible(False); converted_layout.addWidget(self.quick_convert_check)
        self.quick_convert_status = label("", "analyzedTime"); converted_layout.addWidget(self.quick_convert_status)
        self.quick_convert_drag = FileDragHandle(""); self.quick_convert_drag.setEnabled(False); converted_layout.addWidget(self.quick_convert_drag)
        convert_body.addWidget(converted, 1)
        convert_layout.addLayout(convert_body)
        convert_footer = QHBoxLayout(); convert_footer.setSpacing(8)
        convert_footer.addWidget(LineIcon("drive", "#e6a128", 20))
        self.quick_convert_storage_label = label("0 conversions · 0 o", "storage"); convert_footer.addWidget(self.quick_convert_storage_label); convert_footer.addStretch()
        convert_open = icon_button("folder", "OPEN OUTPUT FOLDER", icon_size=16); convert_open.clicked.connect(self._open_quick_convert_root)
        convert_manage = icon_button("gear", "MANAGE", icon_size=16); convert_manage.clicked.connect(self._manage_quick_convert_storage)
        convert_footer.addWidget(convert_open); convert_footer.addWidget(convert_manage); convert_layout.addLayout(convert_footer)
        layout.addWidget(convert)

        extract = panel(); extract.setProperty("sectionAccent", "red"); self.quick_extract_panel = extract
        el = QHBoxLayout(extract); el.setContentsMargins(18, 14, 18, 14); el.setSpacing(18)
        left_widget = QWidget(); left_widget.setFixedWidth(330)
        left = QVBoxLayout(left_widget); left.setContentsMargins(0, 0, 0, 0); left.setSpacing(7)
        extract_title = QVBoxLayout(); extract_title.setSpacing(2); self.quick_extract_title = label("QUICK EXTRACT", "pageTitle"); extract_title.addWidget(self.quick_extract_title); extract_title.addWidget(label("Extract playable layers from one loop", "muted")); left.addLayout(extract_title)
        self.quick_extract_drop = DropZone("audio", compact=True, interactive=True, allowed_extensions={".mp3"}, accent="red")
        self.quick_extract_drop.pathChanged.connect(self._quick_extract_requested)
        left.addWidget(self.quick_extract_drop)
        left.addStretch(); el.addWidget(left_widget)
        layers = QScrollArea(); self.quick_layers_area = layers; layers.setWidgetResizable(True); layers.setProperty("role", "layers"); layers.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.quick_layer_content = QWidget(); self.quick_layer_grid = QGridLayout(self.quick_layer_content); self.quick_layer_grid.setContentsMargins(8, 8, 8, 8); self.quick_layer_grid.setHorizontalSpacing(8); self.quick_layer_grid.setVerticalSpacing(8)
        layers.setWidget(self.quick_layer_content)
        self._populate_layer_cards(
            [],
            "Once you drop an audio file, its layers will appear here.",
            show_empty_icon=True,
        )
        right = QVBoxLayout(); right.setSpacing(7); right.addWidget(layers, 1)
        result_footer = QWidget(); result_footer.setFixedHeight(42)
        result_bar = QHBoxLayout(result_footer); result_bar.setContentsMargins(0, 0, 0, 0); result_bar.setSpacing(10)
        extract_result = QFrame(); extract_result.setProperty("role", "resultLine")
        extract_line = QHBoxLayout(extract_result); extract_line.setContentsMargins(11, 6, 11, 6); extract_line.setSpacing(8)
        extract_line.addWidget(LineIcon("music_note", "#ff2b1c", 22)); self.quick_extract_filename = label("Ready for one MP3 loop.", "scannedFile"); extract_line.addWidget(self.quick_extract_filename)
        extract_line.addSpacing(5); self.quick_extract_check = LineIcon("check", "#57d84e", 16); self.quick_extract_check.setVisible(False); extract_line.addWidget(self.quick_extract_check); self.quick_extract_status = label("", "success"); extract_line.addWidget(self.quick_extract_status); extract_line.addStretch()
        self.quick_show_results = button("SHOW RESULTS"); self.quick_show_results.setProperty("sectionAction", "extract"); self.quick_show_results.setEnabled(False); self.quick_show_results.clicked.connect(self._show_quick_results)
        result_bar.addWidget(extract_result, 1); result_bar.addWidget(self.quick_show_results, 0, Qt.AlignVCenter)
        right.addWidget(result_footer); el.addLayout(right, 72)
        layout.addWidget(extract, 50)
        footer = panel(); fl = QHBoxLayout(footer); fl.setContentsMargins(18, 8, 18, 8)
        fl.addWidget(LineIcon("drive", "#9da5ac", 24)); self.quick_storage_label = label("0 extracts · 0 o", "storage"); fl.addWidget(self.quick_storage_label); fl.addStretch()
        open_folder = icon_button("folder", "OPEN FOLDER", icon_size=18); fit_icon_button_width(open_folder, 170); open_folder.clicked.connect(self._open_quick_root)
        manage = icon_button("gear", "MANAGE", icon_size=18); fit_icon_button_width(manage, 145); manage.clicked.connect(self._manage_quick_storage)
        fl.addWidget(open_folder); fl.addWidget(manage); layout.addWidget(footer, 10)
        self._refresh_quick_storage()
        self._refresh_quick_convert_storage()
        return page


def main():
    if "--smoke-midi-engine" in sys.argv:
        result_path = os.environ.get("STEM_SLICER_SMOKE_RESULT")
        try:
            from midi_conversion import MidiConverter
            converter = MidiConverter()
            smoke_audio = os.environ.get("STEM_SLICER_SMOKE_AUDIO")
            smoke_midi = os.environ.get("STEM_SLICER_SMOKE_MIDI")
            if smoke_audio and smoke_midi:
                converter.convert(smoke_audio, smoke_midi, bpm=120)
            result = "ok"
            exit_code = 0
        except Exception as exc:
            result = f"{type(exc).__name__}: {exc}"
            exit_code = 1
        if result_path:
            with open(result_path, "w", encoding="utf-8") as output:
                output.write(result)
        raise SystemExit(exit_code)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(application_stylesheet())
    window = MainWindow()
    window.show()
    if "--smoke-ui" in sys.argv:
        result_path = os.environ.get("STEM_SLICER_SMOKE_RESULT")

        def complete_ui_smoke():
            if result_path:
                with open(result_path, "w", encoding="utf-8") as output:
                    output.write("ok")
            app.quit()

        QTimer.singleShot(750, complete_ui_smoke)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
