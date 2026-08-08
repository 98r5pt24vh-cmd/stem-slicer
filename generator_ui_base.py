"""Generate-only prototype using the exact 1.8.3B visual shell."""

from __future__ import annotations

from array import array
import math
import os
from pathlib import Path
import secrets
import wave

from PySide6.QtCore import (
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QIcon,
    QIntValidator,
    QPainter,
    QPen,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QLayout,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from functional_core import (
    FileDragHandle,
    LayerPlayButton,
    LineIcon,
    MultiFileDragHandle,
    image,
    resource_path,
)
from layer_library import TAXONOMY
from key_confidence import DEFAULT_KEY_MARGIN_THRESHOLD
from storage import format_decimal_size
from synchronized_layer_player import SynchronizedLayerPlayer
from validated_ui import (
    BASE_HEIGHT,
    BASE_WIDTH,
    GREEN,
    MUTED,
    ORANGE,
    PURPLE,
    RED,
    AnchoredChoiceSelector,
    MiddleElideLabel,
    ScaleSelector,
    V16DropZone,
    V16Tab,
    validated_stylesheet,
)
from widgets import StudioRoot


class OctaveSelector(AnchoredChoiceSelector):
    """Compact octave selector whose popup values stay legible on layer cards."""

    def __init__(self, parent=None):
        super().__init__(
            ("+1", "0", "-1"),
            accent=PURPLE,
            exact_popup_width=True,
            show_check=False,
            parent=parent,
        )

    def setCurrentText(self, text):
        super().setCurrentText(text)
        self.setText(f"OCT {self.currentText()}")


class LayerMixLabel(MiddleElideLabel):
    """Clickable layer name used to assemble the synchronized live mix."""

    clicked = Signal()

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setProperty("mixClickable", True)
        self.setProperty("mixActive", False)
        self.setCursor(Qt.PointingHandCursor)

    def setMixActive(self, active: bool) -> None:
        self.setProperty("mixActive", bool(active))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.isEnabled():
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if (
            event.button() == Qt.LeftButton
            and self.isEnabled()
            and self.rect().contains(event.position().toPoint())
        ):
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


EXACT_KEYS = tuple(
    f"{tonic} {mode}"
    for mode in ("major", "minor")
    for tonic in (
        "C",
        "C#",
        "D",
        "D#",
        "E",
        "F",
        "F#",
        "G",
        "G#",
        "A",
        "A#",
        "B",
    )
)

RELATIVE_KEY_FAMILIES = (
    "C major / A minor",
    "C# major / A# minor",
    "D major / B minor",
    "D# major / C minor",
    "E major / C# minor",
    "F major / D minor",
    "F# major / D# minor",
    "G major / E minor",
    "G# major / F minor",
    "A major / F# minor",
    "A# major / G minor",
    "B major / G# minor",
)


def _compact_popup_rows(selector: AnchoredChoiceSelector) -> None:
    """Keep compact selector rows legible at every supported UI scale."""

    factor = selector._visual_scale()
    for row in selector._rows.values():
        row.setFixedHeight(round(23 * factor))
        row.layout().setContentsMargins(
            round(4 * factor), 0, round(4 * factor), 0
        )
        row.layout().setSpacing(round(2 * factor))
        row.check_label.setFixedWidth(
            round(8 * factor) if row._show_check else 0
        )
        font = row.font()
        font.setPixelSize(round(9 * factor))
        font.setBold(True)
        row.check_label.setFont(font)
        row.text_label.setFont(font)
    selector._popup.layout().invalidate()
    selector._popup.layout().activate()


def _compact_popup_height(selector: AnchoredChoiceSelector) -> int:
    margins = selector._popup.layout().contentsMargins()
    content_height = (
        margins.top()
        + margins.bottom()
        + sum(row.height() for row in selector._rows.values())
    )
    return max(content_height, selector._popup.sizeHint().height())


def _prime_native_popup(control) -> None:
    """Create a hidden native popup surface before its first user click."""

    popup = getattr(control, "_popup", None)
    if popup is None:
        return
    popup.ensurePolished()
    popup.winId()


class CompactKeySelector(AnchoredChoiceSelector):
    """Relative-key selector whose popup exactly follows the compact field."""

    def _popup_size(self):
        width, _height = super()._popup_size()
        _compact_popup_rows(self)
        return width, _compact_popup_height(self)


class LayerVolumeButton(QPushButton):
    """Neutral speaker control with a compact per-layer volume fader."""

    percentChanged = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__("", parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(18, 18)
        self.setStyleSheet(
            "QPushButton{background:#151b1f;border:1px solid #3b454b;"
            "border-radius:4px;padding:0;}"
            "QPushButton:hover{background:#20282d;border-color:#69757c;}"
        )
        self._percent = 100
        self._popup = QFrame(None, Qt.Popup | Qt.FramelessWindowHint)
        self._popup.setObjectName("layerVolumePopup")
        self._popup.setStyleSheet(
            "QFrame#layerVolumePopup{background:#0d151a;"
            "border:1px solid #566269;border-radius:4px;}"
            "QSlider::groove:vertical{background:#273138;width:2px;"
            "border-radius:1px;margin:4px 0;}"
            "QSlider::sub-page:vertical{background:#273138;border-radius:1px;}"
            "QSlider::add-page:vertical{background:#8b969c;border-radius:1px;}"
            "QSlider::handle:vertical{background:#d1d7da;"
            "border:1px solid #77838a;height:7px;margin:-3px -4px;"
            "border-radius:3px;}"
        )
        popup_layout = QVBoxLayout(self._popup)
        popup_layout.setContentsMargins(4, 5, 4, 5)
        popup_layout.setSpacing(0)
        self.slider = QSlider(Qt.Vertical, self._popup)
        self.slider.setRange(0, 100)
        self.slider.setValue(100)
        self.slider.setFixedSize(10, 54)
        popup_layout.addWidget(self.slider, 0, Qt.AlignHCenter)
        self._popup.setFixedSize(18, 64)
        _prime_native_popup(self)
        self.slider.valueChanged.connect(self._value_changed)
        self.clicked.connect(self._show_popup)
        self.destroyed.connect(self._popup.deleteLater)
        self.setToolTip("Layer volume · 100%")

    def _value_changed(self, value: int) -> None:
        self._percent = max(0, min(100, int(value)))
        self.setToolTip(f"Layer volume · {self._percent}%")
        self.percentChanged.emit(self._percent)
        self.update()

    def _show_popup(self) -> None:
        top_left = self.mapToGlobal(QPoint(0, 0))
        bottom_right = self.mapToGlobal(QPoint(self.width(), self.height()))
        screen = QApplication.screenAt(self.mapToGlobal(self.rect().center()))
        bounds = screen.availableGeometry() if screen is not None else None
        width, height = self._popup.width(), self._popup.height()
        x = bottom_right.x() - width
        below_y = bottom_right.y() + 3
        above_y = top_left.y() - height - 3
        y = below_y
        if bounds is not None:
            below_space = bounds.bottom() - below_y + 1
            above_space = top_left.y() - 3 - bounds.top()
            if height > below_space and above_space > below_space:
                y = above_y
            x = max(bounds.left(), min(x, bounds.right() - width + 1))
            y = max(bounds.top(), min(y, bounds.bottom() - height + 1))
        self._popup.move(x, y)
        self._popup.show()
        self._popup.raise_()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(
            QPen(
                QColor("#9aa4aa"),
                1.15,
                Qt.SolidLine,
                Qt.RoundCap,
                Qt.RoundJoin,
            )
        )
        painter.drawLine(QPointF(3.5, 7.0), QPointF(6.0, 7.0))
        painter.drawLine(QPointF(3.5, 11.0), QPointF(6.0, 11.0))
        painter.drawLine(QPointF(3.5, 7.0), QPointF(3.5, 11.0))
        painter.drawLine(QPointF(6.0, 7.0), QPointF(9.0, 4.8))
        painter.drawLine(QPointF(6.0, 11.0), QPointF(9.0, 13.2))
        painter.drawLine(QPointF(9.0, 4.8), QPointF(9.0, 13.2))
        if self._percent <= 0:
            painter.drawLine(QPointF(11.0, 7.0), QPointF(14.5, 11.0))
            painter.drawLine(QPointF(14.5, 7.0), QPointF(11.0, 11.0))
        else:
            painter.drawArc(
                QRectF(8.5, 5.8, 5.0, 6.4), -58 * 16, 116 * 16
            )
            if self._percent >= 50:
                painter.drawArc(
                    QRectF(7.8, 4.0, 8.0, 10.0), -55 * 16, 110 * 16
                )


def _caps(text: str) -> QLabel:
    item = QLabel(text)
    item.setProperty("role", "caps")
    return item


def _section(
    accent: str,
    icon_kind: str,
    title: str,
    description: str,
) -> tuple[QFrame, QWidget, QHBoxLayout]:
    section = QFrame()
    section.setProperty("role", "section")
    section.setProperty("accent", accent)
    layout = QVBoxLayout(section)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    head = QWidget()
    head.setFixedHeight(38)
    head_layout = QHBoxLayout(head)
    head_layout.setContentsMargins(13, 5, 13, 3)
    head_layout.setSpacing(8)
    color = {"red": RED, "purple": PURPLE, "orange": ORANGE}[accent]
    head_layout.addWidget(LineIcon(icon_kind, color, 18))
    copy = QVBoxLayout()
    copy.setSpacing(1)
    heading = QLabel(title)
    heading.setProperty("role", "sectionTitle")
    detail = QLabel(description)
    detail.setProperty("role", "sectionDescription")
    copy.addWidget(heading)
    copy.addWidget(detail)
    head_layout.addLayout(copy)
    head_layout.addStretch()
    layout.addWidget(head)
    body = QWidget()
    layout.addWidget(body, 1)
    return section, body, head_layout


class FlowLayout(QLayout):
    """Small deterministic flow used by the category-coverage summary."""

    def __init__(
        self,
        parent=None,
        *,
        horizontal_spacing: int = 8,
        vertical_spacing: int = 2,
    ) -> None:
        super().__init__(parent)
        self._items = []
        self.horizontal_spacing = int(horizontal_spacing)
        self.vertical_spacing = int(vertical_spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        margins = self.contentsMargins()
        inner_width = max(1, int(width) - margins.left() - margins.right())
        return (
            self._do_layout(QRect(0, 0, inner_width, 0), test_only=True)
            + margins.top()
            + margins.bottom()
        )

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        margins = self.contentsMargins()
        inner = rect.adjusted(
            margins.left(),
            margins.top(),
            -margins.right(),
            -margins.bottom(),
        )
        content_height = self._do_layout(inner, test_only=True)
        if 0 < content_height < inner.height():
            inner.translate(0, (inner.height() - content_height) // 2)
        self._do_layout(inner, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(
            margins.left() + margins.right(),
            margins.top() + margins.bottom(),
        )

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        x = rect.x()
        y = rect.y()
        line_height = 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width()
            if line_height and next_x > rect.right() + 1:
                x = rect.x()
                y += line_height + self.vertical_spacing
                next_x = x + hint.width()
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(x, y, hint.width(), hint.height()))
            x = next_x + self.horizontal_spacing
            line_height = max(line_height, hint.height())
        return max(0, y + line_height - rect.y())


class CenteredPlusButton(QPushButton):
    """Paint the plus glyph geometrically instead of relying on font baseline."""

    def __init__(self, parent=None) -> None:
        super().__init__("", parent)
        self.setProperty("role", "slotAdd")
        self.setFixedSize(25, 25)
        self.setStyleSheet("padding:0;")

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = "#57d84e" if self.isEnabled() else "#667078"
        painter.setPen(QPen(QColor(color), 1.7, Qt.SolidLine, Qt.RoundCap))
        center = self.rect().center()
        painter.drawLine(
            QPointF(center.x() - 3.0, center.y()),
            QPointF(center.x() + 3.0, center.y()),
        )
        painter.drawLine(
            QPointF(center.x(), center.y() - 3.0),
            QPointF(center.x(), center.y() + 3.0),
        )


class CenteredRemoveButton(QPushButton):
    """Paint a precisely centered remove glyph and a short divider."""

    def __init__(self, parent=None) -> None:
        super().__init__("", parent)
        self.setProperty("role", "slotRemove")
        self.setFixedSize(20, 23)
        self.setStyleSheet("padding:0;")

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        enabled = self.isEnabled()
        divider = "#6a3436" if enabled else "#293238"
        painter.setPen(
            QPen(QColor(divider), 1.0, Qt.SolidLine, Qt.RoundCap)
        )
        painter.drawLine(
            QPointF(self.width() - 0.5, 4.5),
            QPointF(self.width() - 0.5, self.height() - 4.5),
        )
        color = "#ef5963" if enabled else "#59646b"
        painter.setPen(
            QPen(QColor(color), 1.8, Qt.SolidLine, Qt.RoundCap)
        )
        center = QPointF(
            (self.width() - 1) / 2,
            (self.height() - 1) / 2,
        )
        radius = 3.0
        painter.drawLine(
            QPointF(center.x() - radius, center.y() - radius),
            QPointF(center.x() + radius, center.y() + radius),
        )
        painter.drawLine(
            QPointF(center.x() - radius, center.y() + radius),
            QPointF(center.x() + radius, center.y() - radius),
        )


def _read_wave_peaks(path: str, bins: int = 110) -> list[float]:
    """Read lightweight display peaks from a generated PCM16 WAV."""
    try:
        with wave.open(path, "rb") as stream:
            channels = max(1, stream.getnchannels())
            width = stream.getsampwidth()
            frames = stream.getnframes()
            if width != 2 or frames <= 0:
                raise ValueError
            raw = stream.readframes(frames)
        samples = array("h")
        samples.frombytes(raw)
        if os.sys.byteorder != "little":
            samples.byteswap()
        frame_count = len(samples) // channels
        step = max(1, math.ceil(frame_count / bins))
        peaks: list[float] = []
        for start in range(0, frame_count, step):
            end = min(frame_count, start + step)
            peak = 0
            for frame in range(start, end):
                base = frame * channels
                for channel in range(channels):
                    peak = max(peak, abs(samples[base + channel]))
            peaks.append(min(1.0, peak / 32767.0))
        return peaks or [0.0]
    except Exception:
        return [0.22 + 0.12 * math.sin(index * 0.7) for index in range(bins)]


class GenerateWaveform(QWidget):
    """Waveform whose drag gesture keeps the mouse grab under the Qt proxy."""

    seekRequested = Signal(float)

    def __init__(self, peaks: list[float], parent=None) -> None:
        super().__init__(parent)
        self.peaks = list(peaks) or [0.0]
        self.progress = 0.0
        self.scrubbing = False
        self.setFixedHeight(18)
        self.setCursor(Qt.PointingHandCursor)

    def setProgress(self, value: float) -> None:
        self.progress = max(0.0, min(1.0, float(value)))
        self.update()

    def _seek(self, x: float) -> None:
        if self.width() > 0:
            self.seekRequested.emit(
                max(0.0, min(1.0, float(x) / self.width()))
            )

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.scrubbing = True
            self._seek(event.position().x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.scrubbing and event.buttons() & Qt.LeftButton:
            self._seek(event.position().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.scrubbing:
            self._seek(event.position().x())
            self.scrubbing = False
            event.accept()
            return
        self.scrubbing = False
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        center = self.height() / 2
        step = self.width() / max(1, len(self.peaks))
        for index, value in enumerate(self.peaks):
            height = max(1.0, float(value) * (self.height() - 3))
            x = (index + 0.5) * step
            color = RED if x <= self.progress * self.width() else "#747c83"
            painter.setPen(
                QPen(
                    QColor(color),
                    1.2,
                    Qt.SolidLine,
                    Qt.RoundCap,
                )
            )
            painter.drawLine(
                QPointF(x, center - height / 2),
                QPointF(x, center + height / 2),
            )
        if self.progress > 0:
            x = self.progress * self.width()
            painter.setPen(QPen(QColor("#ff4a3b"), 1.4))
            painter.drawLine(
                QPointF(x, 1), QPointF(x, self.height() - 1)
            )


class GenerateCard(QFrame):
    playRequested = Signal(str)
    mixToggleRequested = Signal(str)
    seekRequested = Signal(str, float)
    lockChanged = Signal(int, str, bool)
    alternateKeyRequested = Signal(int, str)
    octaveShiftRequested = Signal(int, str, int)
    normalizationRequested = Signal(int, str, bool)
    volumeChanged = Signal(str, int)

    def __init__(self, data: dict, *, master: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.data = dict(data)
        self.path = str(data["path"])
        self.master = bool(master)
        self.slot_index = int(data.get("slot_index", -1))
        self.recipe_slot = None
        self.identity = str(data.get("identity") or "")
        self.locked = bool(data.get("locked", False)) and not self.master
        self.alternate_key = str(data.get("alternate_key") or "").strip()
        self.alternate_key_used = bool(data.get("alternate_key_used", False))
        self.octave_shift = int(
            data.get(
                "manual_pitch_semitones",
                data.get("octave_shift", 0),
            )
            or 0
        )
        if self.octave_shift not in {-12, 0, 12}:
            self.octave_shift = 0
        self.normalized = bool(
            data.get(
                "normalization_enabled",
                data.get("normalized", False),
            )
        )
        self.data["octave_shift"] = self.octave_shift
        self.data["normalized"] = self.normalized
        self.data["manual_pitch_semitones"] = self.octave_shift
        self.data["normalization_enabled"] = self.normalized
        self._transform_busy = False
        self._transform_enabled = True
        self.setProperty("role", "layerCard")
        self.setProperty("locked", self.locked)
        if not self.master:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip(
                "Click the card or KEEP to preserve this layer in the next generation."
            )
        self.setFixedHeight(78)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 3, 7, 3)
        layout.setSpacing(1)

        header = QHBoxLayout()
        header.setSpacing(3)
        self.play = LayerPlayButton()
        self.play.setProperty("role", "layerPlay")
        # Match Quick Extract exactly: 25 × 25 with a 12 px radius is round.
        self.play.setFixedSize(25, 25)
        self.play.setStyleSheet("padding:0;border-radius:12px;")
        self.play.setToolTip("Play this layer by itself")
        self.play.clicked.connect(
            lambda: self.playRequested.emit(self.path)
        )
        header.addWidget(self.play)
        self.name_label = LayerMixLabel(
            str(data.get("display_name") or data.get("name") or "Layer")
        )
        self.name_label.setProperty("role", "layerName")
        source_tooltip = str(data.get("source_name") or self.path)
        self.name_label.setToolTip(
            "Click to add or remove this layer from the synchronized mix.\n"
            + source_tooltip
        )
        self.name_label.clicked.connect(
            lambda: self.mixToggleRequested.emit(self.path)
        )
        header.addWidget(self.name_label, 1)
        self.alternate_key_button: QPushButton | None = None
        self.octave_selector: OctaveSelector | None = None
        self.normalization_button: QPushButton | None = None
        if (
            not self.master
            and self.slot_index >= 0
            and self.identity
            and self.alternate_key
        ):
            self.alternate_key_button = QPushButton()
            self.alternate_key_button.setProperty("role", "cardAltKey")
            self._make_compact_button(
                self.alternate_key_button,
                ("ALT KEY", "OG KEY", "ALT…", "OG…"),
                minimum_width=34,
            )
            self.alternate_key_button.setToolTip(
                f"Use the second key analysis: {self.alternate_key}"
            )
            self.alternate_key_button.clicked.connect(
                self._request_alternate_key
            )
            header.addWidget(self.alternate_key_button)
        self.lock_button: QPushButton | None = None
        if not self.master and self.slot_index >= 0 and self.identity:
            self.octave_selector = OctaveSelector()
            self.octave_selector.setProperty("role", "cardAltKey")
            self._make_compact_button(
                self.octave_selector,
                ("OCT +1", "OCT 0", "OCT -1"),
                minimum_width=46,
            )
            self.octave_selector.setStyleSheet(
                "font-size:7px;padding:0 14px 0 3px;text-align:left;"
            )
            self.octave_selector.setCurrentText(
                self._octave_label(self.octave_shift)
            )
            self.octave_selector.setToolTip(
                "Choose the original octave, one octave up, or one octave down"
            )
            self.octave_selector.currentTextChanged.connect(
                self._request_octave_choice
            )
            header.addWidget(self.octave_selector)

            self.normalization_button = QPushButton()
            self.normalization_button.setProperty("role", "cardAltKey")
            self._make_compact_button(
                self.normalization_button,
                ("NORMALIZE", "ORIGINAL"),
                minimum_width=44,
            )
            self.normalization_button.setToolTip(
                "Normalize this layer, or restore its original level"
            )
            self.normalization_button.clicked.connect(
                self._request_normalization
            )
            header.addWidget(self.normalization_button)

            self.lock_button = QPushButton()
            self.lock_button.setProperty("role", "cardLock")
            self.lock_button.setCheckable(True)
            self._make_compact_button(
                self.lock_button,
                ("KEEP", "KEPT"),
                minimum_width=28,
            )
            self.lock_button.setToolTip(
                "Keep this layer when generating the next loop"
            )
            self.lock_button.clicked.connect(
                lambda checked: self.setLocked(bool(checked), emit=True)
            )
            header.addWidget(self.lock_button)
        self.drag_handle = FileDragHandle(self.path)
        header.addWidget(self.drag_handle)
        layout.addLayout(header)

        supplied_peaks = data.get("peaks")
        peaks = (
            [float(value) for value in supplied_peaks]
            if isinstance(supplied_peaks, (list, tuple)) and supplied_peaks
            else _read_wave_peaks(self.path)
        )
        self.waveform = GenerateWaveform(peaks)
        self.waveform.seekRequested.connect(
            lambda ratio: self.seekRequested.emit(self.path, ratio)
        )
        layout.addWidget(self.waveform)

        metadata = QHBoxLayout()
        metadata.setSpacing(4)
        category = (
            "Full Loop"
            if self.master
            else str(data.get("category") or "Layer")
        )
        target = (
            f"{data.get('key') or '—'} · "
            f"{int(float(data.get('bpm') or 0)) or '—'} BPM"
        )
        pitch_suffix = (
            f" · Pitch {self.octave_shift:+d}"
            if not self.master and self.octave_shift
            else ""
        )
        normalized_suffix = (
            " · Normalized" if not self.master and self.normalized else ""
        )
        self.metadata_label = QLabel(
            f"{category} · {target}{pitch_suffix}{normalized_suffix}"
        )
        self.metadata_label.setProperty("role", "cardMeta")
        metadata.addWidget(self.metadata_label)
        metadata.addStretch()
        if data.get("source_name"):
            source = MiddleElideLabel(str(data["source_name"]))
            source.setProperty("role", "cardMeta")
            source.setToolTip(str(data["source_name"]))
            source.setMaximumWidth(160)
            metadata.addWidget(source)
        layout.addLayout(metadata)

        # Compact 1.9 card layout validated in the front-end model.  The
        # synchronized preview keeps the existing play/name semantics while
        # OCT and the neutral speaker control live beside the waveform.
        if self.alternate_key_button is not None:
            header.removeWidget(self.alternate_key_button)
            self.alternate_key_button.setFixedHeight(15)
            metadata.addWidget(
                self.alternate_key_button,
                0,
                Qt.AlignRight | Qt.AlignVCenter,
            )
        if self.octave_selector is not None:
            header.removeWidget(self.octave_selector)
            self.octave_selector.setFixedSize(46, 18)
            self.octave_selector.setStyleSheet(
                "QPushButton{background:#151b1f;border:1px solid #3b454b;"
                "border-radius:4px;color:#aab3b8;font-size:7px;"
                "font-weight:900;padding:0 9px 0 3px;text-align:left;}"
                "QPushButton:hover{background:#20282d;border-color:#69757c;}"
            )
            for row in self.octave_selector._rows.values():
                row.accent = "#8f999f"
                row._refresh_style()
            _prime_native_popup(self.octave_selector)
        if self.normalization_button is not None:
            header.removeWidget(self.normalization_button)
            self.normalization_button.hide()

        layout.removeWidget(self.waveform)
        waveform_row = QHBoxLayout()
        waveform_row.setContentsMargins(0, 0, 0, 0)
        waveform_row.setSpacing(3)
        waveform_row.addWidget(self.waveform, 1)
        if self.octave_selector is not None:
            waveform_row.addWidget(
                self.octave_selector,
                0,
                Qt.AlignVCenter,
            )
        self.volume_button = LayerVolumeButton(self)
        self.volume_button.percentChanged.connect(
            lambda percent: self.volumeChanged.emit(self.path, percent)
        )
        waveform_row.addWidget(self.volume_button, 0, Qt.AlignVCenter)
        layout.insertLayout(1, waveform_row)
        self.setLocked(self.locked, emit=False)
        self._refresh_transform_controls()

    def updateData(self, data: dict) -> None:
        """Refresh one transformed card without rebuilding the shared player."""

        self.data.update(dict(data))
        self.alternate_key = str(self.data.get("alternate_key") or "").strip()
        self.alternate_key_used = bool(
            self.data.get("alternate_key_used", self.alternate_key_used)
        )
        self.octave_shift = int(
            self.data.get("manual_pitch_semitones", self.octave_shift) or 0
        )
        if self.octave_shift not in {-12, 0, 12}:
            self.octave_shift = 0
        self.normalized = bool(
            self.data.get("normalization_enabled", self.normalized)
        )
        supplied_peaks = self.data.get("peaks")
        if isinstance(supplied_peaks, (list, tuple)) and supplied_peaks:
            self.waveform.peaks = [float(value) for value in supplied_peaks]
            self.waveform.update()
        category = str(self.data.get("category") or "Layer")
        target = (
            f"{self.data.get('key') or '—'} · "
            f"{int(float(self.data.get('bpm') or 0)) or '—'} BPM"
        )
        pitch_suffix = (
            f" · Pitch {self.octave_shift:+d}" if self.octave_shift else ""
        )
        normalized_suffix = " · Normalized" if self.normalized else ""
        self.metadata_label.setText(
            f"{category} · {target}{pitch_suffix}{normalized_suffix}"
        )
        self.setTransformBusy(False)

    @staticmethod
    def _make_compact_button(
        button: QPushButton,
        labels: tuple[str, ...],
        *,
        minimum_width: int,
    ) -> None:
        """Fit dense card controls to their longest label with tiny margins."""

        button.setStyleSheet("font-size:7px;padding:0;")
        button.ensurePolished()
        text_width = max(
            button.fontMetrics().horizontalAdvance(label) for label in labels
        )
        button.setFixedSize(max(int(minimum_width), text_width + 6), 20)

    def _can_request_transform(self) -> bool:
        return bool(
            not self.master
            and self.slot_index >= 0
            and self.identity
            and self._transform_enabled
            and not self._transform_busy
        )

    def _request_alternate_key(self) -> None:
        if (
            self.alternate_key_button is None
            or not self._can_request_transform()
        ):
            return
        self.setTransformBusy(True)
        self.alternateKeyRequested.emit(self.slot_index, self.identity)

    @staticmethod
    def _octave_label(shift: int) -> str:
        return {12: "+1", -12: "-1"}.get(int(shift), "0")

    def _request_octave_choice(self, text: str) -> None:
        shift = {"+1": 12, "0": 0, "-1": -12}.get(str(text))
        if shift is None:
            return
        self._request_octave_shift(shift)

    def _request_octave_shift(self, shift: int) -> None:
        if shift not in {-12, 0, 12} or not self._can_request_transform():
            self._refresh_transform_controls()
            return
        if shift == self.octave_shift:
            return
        self.setTransformBusy(True)
        self.octaveShiftRequested.emit(
            self.slot_index,
            self.identity,
            shift,
        )

    def _request_normalization(self) -> None:
        if self.normalization_button is None or not self._can_request_transform():
            return
        self.setTransformBusy(True)
        self.normalizationRequested.emit(
            self.slot_index,
            self.identity,
            not self.normalized,
        )

    def _refresh_transform_controls(self) -> None:
        enabled = self._transform_enabled and not self._transform_busy
        button = self.alternate_key_button
        if button is not None:
            if self._transform_busy:
                state = "busy"
                text = "OG…" if self.alternate_key_used else "ALT…"
            elif self.alternate_key_used:
                state = "alternate"
                text = "OG KEY"
            else:
                state = "ready"
                text = "ALT KEY"
            button.setProperty("state", state)
            button.setText(text)
            button.setToolTip(
                "Return to the original key analysis"
                if self.alternate_key_used
                else f"Use the second key analysis: {self.alternate_key}"
            )
            button.setEnabled(enabled)

        if self.octave_selector is not None:
            blocked = self.octave_selector.blockSignals(True)
            self.octave_selector.setCurrentText(
                self._octave_label(self.octave_shift)
            )
            self.octave_selector.blockSignals(blocked)
            self.octave_selector.setProperty(
                "state", "active" if self.octave_shift else "ready"
            )
            self.octave_selector.setEnabled(enabled)

        if self.normalization_button is not None:
            self.normalization_button.setProperty(
                "state", "active" if self.normalized else "ready"
            )
            self.normalization_button.setText(
                "ORIGINAL" if self.normalized else "NORMALIZE"
            )
            self.normalization_button.setEnabled(enabled)

        for transform_button in (
            self.alternate_key_button,
            self.octave_selector,
            self.normalization_button,
        ):
            if transform_button is None:
                continue
            transform_button.style().unpolish(transform_button)
            transform_button.style().polish(transform_button)
            transform_button.update()

    def _refresh_alternate_key_button(self) -> None:
        """Compatibility wrapper for existing UI/controller call sites."""

        self._refresh_transform_controls()

    def setTransformBusy(self, busy: bool) -> None:
        self._transform_busy = bool(busy)
        self._refresh_transform_controls()

    def setAlternateKeyBusy(self, busy: bool) -> None:
        """Compatibility alias for the original ALT-only API."""

        self.setTransformBusy(busy)

    def setTransformEnabled(self, enabled: bool) -> None:
        self._transform_enabled = bool(enabled)
        self._refresh_transform_controls()

    def setAlternateKeyEnabled(self, enabled: bool) -> None:
        """Compatibility alias for the original ALT-only API."""

        self.setTransformEnabled(enabled)

    def setLocked(self, locked: bool, *, emit: bool = False) -> None:
        if self.master or self.slot_index < 0 or not self.identity:
            locked = False
        changed = bool(locked) != self.locked
        self.locked = bool(locked)
        self.data["locked"] = self.locked
        self.setProperty("locked", self.locked)
        if self.lock_button is not None:
            blocked = self.lock_button.blockSignals(True)
            self.lock_button.setChecked(self.locked)
            self.lock_button.setText("KEPT" if self.locked else "KEEP")
            self.lock_button.blockSignals(blocked)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
        if emit and changed:
            self.lockChanged.emit(
                self.slot_index,
                self.identity,
                self.locked,
            )

    def setLockEnabled(self, enabled: bool) -> None:
        if self.lock_button is not None:
            self.lock_button.setEnabled(bool(enabled))
        if not self.master:
            self.setCursor(
                Qt.PointingHandCursor if enabled else Qt.ArrowCursor
            )

    def setSlotIndex(self, slot_index: int) -> None:
        """Keep the visible card aligned after another recipe slot is removed."""

        self.slot_index = int(slot_index)
        self.data["slot_index"] = self.slot_index

    def mouseReleaseEvent(self, event) -> None:
        if (
            event.button() == Qt.LeftButton
            and not self.master
            and self.isEnabled()
            and (self.lock_button is None or self.lock_button.isEnabled())
        ):
            self.setLocked(not self.locked, emit=True)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def setPlaybackState(self, state: str) -> None:
        self.play.setText("" if state == "playing" else "▶")
        self.play.setProperty("state", state)
        self.play.style().unpolish(self.play)
        self.play.style().polish(self.play)

    def setMixActive(self, active: bool) -> None:
        self.name_label.setMixActive(active)


class RecipeSlotWidget(QFrame):
    """One unified recipe slot: remove, category and popup arrow."""

    def __init__(self, category: str, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("role", "recipeSlot")
        row = QHBoxLayout(self)
        row.setContentsMargins(1, 1, 1, 1)
        row.setSpacing(0)
        self._recipe_locked = False
        self.remove_button = CenteredRemoveButton(self)
        self.remove_button.setToolTip("Remove this recipe slot")
        row.addWidget(self.remove_button, 0, Qt.AlignVCenter)
        self.selector = AnchoredChoiceSelector(TAXONOMY, accent=ORANGE)
        self.selector.setStyleSheet(
            "font-size:8px;padding:0 15px 0 4px;"
            "text-align:center;background:transparent;border:none;"
            "border-radius:0;"
        )
        self.selector.setFixedHeight(23)
        self.selector.setCurrentText(category)
        row.addWidget(self.selector, 1)
        self.selector.currentTextChanged.connect(self._fit_to_text)
        self._fit_to_text(category)

    def setRecipeLocked(
        self,
        locked: bool,
        *,
        controls_enabled: bool,
        can_remove: bool,
    ) -> None:
        """Keep one card and its exact recipe slot as one UI state."""

        self._recipe_locked = bool(locked)
        self.setProperty("locked", self._recipe_locked)
        self.selector.setEnabled(controls_enabled and not self._recipe_locked)
        self.remove_button.setEnabled(
            controls_enabled and can_remove and not self._recipe_locked
        )
        if self._recipe_locked:
            message = "Remove KEEP from the card before editing this slot"
            self.setToolTip(message)
            self.selector.setToolTip(message)
            self.remove_button.setToolTip(message)
        else:
            self.setToolTip("")
            self.selector.setToolTip("Choose the category for this recipe slot")
            self.remove_button.setToolTip("Remove this recipe slot")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _fit_to_text(self, text: str) -> None:
        """Keep compact slots readable instead of forcing one fixed width."""
        text_width = self.selector.fontMetrics().horizontalAdvance(str(text))
        selector_width = max(54, min(112, text_width + 26))
        self.selector.setFixedWidth(selector_width)
        self.setFixedSize(selector_width + 22, 25)


class CompactRecipeSlotWidget(RecipeSlotWidget):
    """Validated compact slot with a stable taxonomy popup."""

    def __init__(self, category: str, parent=None) -> None:
        super().__init__(category, parent)
        self.selector.ensurePolished()
        text_width = self.selector.fontMetrics().horizontalAdvance(
            "Rhythmic Pluck"
        )
        selector_width = max(54, min(112, text_width + 26))
        self._popup_logical_width = selector_width + 22
        original_popup_size = self.selector._popup_size

        def compact_popup_size():
            _width, _height = original_popup_size()
            _compact_popup_rows(self.selector)
            factor = self.selector._visual_scale()
            return (
                round(self._popup_logical_width * factor),
                _compact_popup_height(self.selector),
            )

        self.selector._popup_size = compact_popup_size
        _prime_native_popup(self.selector)


class GeneratePrototypeWindow(QMainWindow):
    scanRequested = Signal(str)
    generateRequested = Signal(dict)
    generateAgainRequested = Signal(dict)
    previewSeedRequested = Signal()
    lockChanged = Signal(int, str, bool)
    alternateKeyRequested = Signal(int, str)
    octaveShiftRequested = Signal(int, str, int)
    normalizationRequested = Signal(int, str, bool)
    openOutputRequested = Signal()
    manageRequested = Signal()
    dragAllRequested = Signal(tuple)
    closing = Signal()

    def __init__(self, parent=None, *, embedded: bool = False) -> None:
        super().__init__(parent)
        self._embedded = bool(embedded)
        self._seed = secrets.randbits(63)
        self._slot_combos: list[AnchoredChoiceSelector] = []
        self._slot_widgets: list[RecipeSlotWidget] = []
        self._cards: list[GenerateCard] = []
        self._stem_cards: list[GenerateCard] = []
        self._library_ready = False
        self._loaded_library_path = ""
        self._preview_seed_available = False
        self._scan_busy = False
        self._generation_busy = False
        self._has_generation = False
        self._master_path = ""
        self._mix_paths: set[str] = set()
        self._solo_path: str | None = None
        self._build()
        self._layer_player = SynchronizedLayerPlayer(self)
        self._layer_player.activePathsChanged.connect(
            self._active_layer_paths_changed
        )
        self._layer_player.positionChanged.connect(self._playback_position)
        self._layer_player.errorOccurred.connect(self._audio_preview_error)

    def _build(self) -> None:
        self.setWindowTitle("Stem Slicer 1.9B — Generate")
        self.setWindowIcon(QIcon(resource_path("assets", "app-icon.png")))
        self.setStyleSheet(validated_stylesheet())

        if self._embedded:
            # QMainWindow is a native window by default.  Force QWidget flags
            # before inserting it into the production QStackedWidget; nested
            # native windows do not render through the outer QGraphicsProxy.
            self.setWindowFlags(Qt.Widget)
            self.setObjectName("GenerateEmbeddedPage")
            self.setAcceptDrops(True)
            self.canvas = self
            page = self._generate_page()
            self.canvas = page
            self.setCentralWidget(page)
            return

        self.view = QGraphicsView(self)
        self.setAcceptDrops(True)
        self.view.setAcceptDrops(True)
        self.view.viewport().setAcceptDrops(True)
        self.view.setFrameShape(QFrame.NoFrame)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scene = QGraphicsScene(self.view)
        self.scene.setSceneRect(0, 0, BASE_WIDTH, BASE_HEIGHT)
        self.view.setScene(self.scene)
        self.canvas = StudioRoot()
        self.canvas.setObjectName("ValidatedCanvas")
        self.canvas.setFixedSize(BASE_WIDTH, BASE_HEIGHT)
        self.canvas.setAcceptDrops(True)
        self.canvas.setStyleSheet(validated_stylesheet())
        self.proxy = self.scene.addWidget(self.canvas)
        self.proxy.setAcceptDrops(True)
        self.setCentralWidget(self.view)

        outer = QVBoxLayout(self.canvas)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._header(outer)
        self._tabs(outer)
        outer.addWidget(self._generate_page(), 1)
        self._set_ui_scale(100)

    def _header(self, outer: QVBoxLayout) -> None:
        header = QFrame()
        header.setProperty("role", "topBar")
        header.setFixedHeight(60)
        row = QHBoxLayout(header)
        row.setContentsMargins(19, 0, 19, 0)
        row.setSpacing(0)
        brand = QWidget()
        brand.setFixedWidth(280)
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(8)
        brand_layout.addWidget(
            image(resource_path("assets", "antiworld-logo.png"), 35, 41)
        )
        copy = QVBoxLayout()
        copy.setSpacing(2)
        copy.addStretch()
        made = QLabel("MADE WITH <3 BY")
        made.setStyleSheet(
            "color:#ff2b1c;font-size:8px;font-weight:900"
        )
        anti = QLabel("ANTIWORLD")
        anti.setStyleSheet(
            "color:#ff2b1c;font-size:13px;font-weight:950"
        )
        copy.addWidget(made)
        copy.addWidget(anti)
        copy.addStretch()
        brand_layout.addLayout(copy)
        brand_layout.addStretch()
        row.addWidget(brand)
        row.addStretch()
        row.addWidget(
            image(
                resource_path("assets", "stem-slicer-wordmark.png"),
                235,
                50,
            )
        )
        row.addStretch()
        build = QWidget()
        build.setFixedWidth(280)
        build_layout = QHBoxLayout(build)
        build_layout.setContentsMargins(0, 0, 0, 0)
        build_layout.setSpacing(12)
        build_layout.addStretch()
        version_copy = QVBoxLayout()
        version_copy.setSpacing(2)
        title = QLabel("LOOP LAYER EXTRACTION SYSTEM")
        version = QLabel("1.9B")
        title.setStyleSheet(
            "color:#7e8a92;font-size:9px;font-weight:700"
        )
        version.setStyleSheet(
            "color:#7e8a92;font-family:'SF Mono';font-size:9px;"
            "font-weight:700"
        )
        title.setAlignment(Qt.AlignRight)
        version.setAlignment(Qt.AlignRight)
        version_copy.addWidget(title)
        version_copy.addWidget(version)
        build_layout.addLayout(version_copy)
        self.scale_select = ScaleSelector()
        self.scale_select.scaleChanged.connect(self._set_ui_scale)
        build_layout.addWidget(self.scale_select)
        row.addWidget(build)
        outer.addWidget(header)

    def _tabs(self, outer: QVBoxLayout) -> None:
        tabs = QFrame()
        tabs.setProperty("role", "tabsBar")
        tabs.setFixedHeight(42)
        row = QHBoxLayout(tabs)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addStretch()
        self.stem_tab = V16Tab("folder", "STEM SLICER")
        self.quick_tab = V16Tab("bolt", "QUICK TOOLS")
        self.generate_tab = V16Tab("dice", "GENERATE")
        for tab in (self.stem_tab, self.quick_tab, self.generate_tab):
            tab.setFixedWidth(210)
            row.addWidget(tab)
        for inactive in (self.stem_tab, self.quick_tab):
            inactive.setEnabled(False)
            inactive.setCursor(Qt.ArrowCursor)
            inactive.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )
            inactive.setToolTip(
                "Unavailable in the Generate-only prototype"
            )
        self.generate_tab.setActive(True)
        row.addStretch()
        outer.addWidget(tabs)

    def _generate_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(9, 9, 9, 9)
        layout.setSpacing(9)

        top = QHBoxLayout()
        top.setSpacing(9)
        library, library_body, _ = _section(
            "red",
            "folder_in",
            "LAYER LIBRARY",
            "Choose an existing folder of extracted layers, then scan it.",
        )
        self.library_section = library
        library.setFixedHeight(166)
        library_layout = QVBoxLayout(library_body)
        library_layout.setContentsMargins(12, 0, 12, 8)
        library_layout.setSpacing(5)
        self.library_drop = V16DropZone(
            "folder",
            "Drop your layer library here",
            RED,
            dialog_parent=self,
        )
        self.library_drop.setFixedHeight(57)
        self.library_drop.pathChanged.connect(self._folder_changed)
        library_layout.addWidget(self.library_drop)
        status_row = QHBoxLayout()
        status_row.setSpacing(7)
        self.scan_status = MiddleElideLabel("No folder selected")
        self.scan_status.setProperty("role", "statusDetail")
        status_row.addWidget(self.scan_status, 1)
        self.scan_button = QPushButton("SCAN LIBRARY")
        self.scan_button.setProperty("accent", "red")
        self.scan_button.setFixedSize(116, 29)
        self.scan_button.setEnabled(False)
        self.scan_button.clicked.connect(self._request_scan)
        status_row.addWidget(self.scan_button)
        library_layout.addLayout(status_row)
        self.scan_progress = QProgressBar()
        self.scan_progress.setRange(0, 100)
        self.scan_progress.setValue(0)
        library_layout.addWidget(self.scan_progress)
        top.addWidget(library, 13)

        recipe, recipe_body, _ = _section(
            "orange",
            "retarget",
            "GENERATE",
            "Choose layer slots and one mandatory BPM/key destination.",
        )
        self.recipe_section = recipe
        recipe.setFixedHeight(166)
        recipe_layout = QVBoxLayout(recipe_body)
        recipe_layout.setContentsMargins(12, 0, 12, 8)
        recipe_layout.setSpacing(0)
        # Line the slot controls up with the bottom edge of the library drop zone.
        recipe_layout.addSpacing(19)
        self.recipe_slots_label = _caps("RECIPE SLOTS")
        self.recipe_slots_label.setFixedHeight(11)
        self.recipe_slots_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        recipe_layout.addWidget(self.recipe_slots_label)
        recipe_layout.addSpacing(3)

        self.slot_row = QWidget()
        self.slot_row.setFixedHeight(34)
        slot_row_layout = QHBoxLayout(self.slot_row)
        slot_row_layout.setContentsMargins(0, 0, 0, 0)
        slot_row_layout.setSpacing(4)
        self.slot_host = QWidget()
        self.slot_layout = QHBoxLayout(self.slot_host)
        self.slot_layout.setContentsMargins(0, 0, 0, 0)
        self.slot_layout.setSpacing(4)
        self.slot_scroll = QScrollArea()
        self.slot_scroll.setProperty("role", "slotStrip")
        self.slot_scroll.setFrameShape(QFrame.NoFrame)
        self.slot_scroll.setWidgetResizable(False)
        self.slot_scroll.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.slot_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.slot_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.slot_scroll.setFixedHeight(34)
        self.slot_scroll.setWidget(self.slot_host)
        self.slot_scroll.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.add_slot_button = CenteredPlusButton(self.slot_row)
        self.add_slot_button.setToolTip("Add another layer slot")
        self.add_slot_button.clicked.connect(lambda: self._add_slot("Lead"))
        for category in ("Bass", "Chords", "Lead"):
            self._add_slot(category)
        slot_row_layout.addWidget(self.slot_scroll, 0, Qt.AlignTop)
        slot_row_layout.addWidget(self.add_slot_button, 0, Qt.AlignTop)
        slot_row_layout.addStretch(1)
        recipe_layout.addWidget(self.slot_row)
        recipe_layout.addStretch(1)

        self.target_row = QWidget()
        self.target_row.setFixedHeight(26)
        target_row_layout = QHBoxLayout(self.target_row)
        target_row_layout.setContentsMargins(0, 0, 0, 0)
        target_row_layout.setSpacing(6)
        self.target_bpm_label = _caps("TARGET BPM")
        target_row_layout.addWidget(
            self.target_bpm_label, 0, Qt.AlignVCenter
        )
        self.target_bpm = QLineEdit("140")
        self.target_bpm.setProperty("role", "targetValue")
        self.target_bpm.setAlignment(Qt.AlignCenter)
        self.target_bpm.setMaxLength(3)
        self.target_bpm.setValidator(QIntValidator(40, 300, self.target_bpm))
        self.target_bpm.setFixedSize(46, 25)
        self.target_bpm.setStyleSheet("font-size:8px;padding:0 4px;")
        target_row_layout.addWidget(self.target_bpm, 0, Qt.AlignVCenter)
        target_row_layout.addSpacing(18)
        self.target_key_label = _caps("TARGET KEY")
        target_row_layout.addWidget(
            self.target_key_label, 0, Qt.AlignVCenter
        )
        self.target_key = AnchoredChoiceSelector(
            EXACT_KEYS,
            accent=ORANGE,
            exact_popup_width=True,
        )
        self.target_key.setCurrentText("A minor")
        self.target_key.setFixedSize(94, 25)
        self.target_key.setStyleSheet(
            "font-size:8px;padding:0 15px 0 6px;"
        )
        target_row_layout.addWidget(self.target_key, 0, Qt.AlignVCenter)
        target_row_layout.addStretch(1)
        self.preview_seed_button = QPushButton("PREVIOUS SEED")
        self.preview_seed_button.setProperty("accent", "orange")
        self.preview_seed_button.setFixedSize(90, 26)
        self.preview_seed_button.setStyleSheet("font-size:7px;padding:0;")
        self.preview_seed_button.setEnabled(False)
        self.preview_seed_button.clicked.connect(self._request_preview_seed)
        target_row_layout.addWidget(
            self.preview_seed_button, 0, Qt.AlignVCenter
        )
        self.generate_button = QPushButton("GENERATE")
        self.generate_button.setProperty("role", "convertAction")
        self.generate_button.setFixedSize(85, 26)
        self.generate_button.setStyleSheet("font-size:8px;padding:0;")
        self.generate_button.setEnabled(False)
        self.generate_button.clicked.connect(self._request_generation)
        target_row_layout.addWidget(
            self.generate_button, 0, Qt.AlignVCenter
        )
        recipe_layout.addWidget(self.target_row)
        top.addWidget(recipe, 27)
        layout.addLayout(top)

        results, results_body, _ = _section(
            "purple",
            "layers",
            "GENERATED LOOP",
            "Build the preview live by playing synchronized layer cards.",
        )
        self.results_section = results
        results_layout = QVBoxLayout(results_body)
        results_layout.setContentsMargins(12, 0, 12, 6)
        results_layout.setSpacing(1)

        self.library_coverage = QWidget()
        self.library_coverage.setFixedHeight(39)
        coverage_layout = QVBoxLayout(self.library_coverage)
        coverage_layout.setContentsMargins(0, 0, 0, 0)
        coverage_layout.setSpacing(0)
        total_row = QWidget()
        total_row.setFixedHeight(16)
        total_row_layout = QHBoxLayout(total_row)
        total_row_layout.setContentsMargins(0, 0, 0, 0)
        total_row_layout.setSpacing(5)
        self.library_total_value = QLabel("—")
        self.library_total_value.setStyleSheet(
            f"color:{GREEN};font-size:13px;font-weight:900;"
        )
        self.library_total_value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        total_row_layout.addWidget(self.library_total_value)
        self.library_total_unit = QLabel("LAYERS")
        self.library_total_unit.setProperty("role", "caps")
        total_row_layout.addWidget(
            self.library_total_unit, 0, Qt.AlignVCenter
        )
        total_row_layout.addStretch(1)
        self.library_review_badge = QLabel("")
        self.library_review_badge.setStyleSheet(
            f"color:{ORANGE};font-size:8px;font-weight:850;"
        )
        self.library_review_badge.setVisible(False)
        total_row_layout.addWidget(
            self.library_review_badge, 0, Qt.AlignVCenter
        )
        coverage_layout.addWidget(total_row)
        self.coverage_flow_host = QWidget()
        self.coverage_flow_host.setFixedHeight(23)
        self.coverage_flow = FlowLayout(
            self.coverage_flow_host,
            horizontal_spacing=6,
            vertical_spacing=1,
        )
        self.library_category_tokens: list[QLabel] = []
        coverage_layout.addWidget(self.coverage_flow_host)
        results_layout.addWidget(self.library_coverage)

        self.coverage_divider = QFrame()
        self.coverage_divider.setFrameShape(QFrame.HLine)
        self.coverage_divider.setFixedHeight(1)
        self.coverage_divider.setStyleSheet(
            "background:#26343d;border:0"
        )
        results_layout.addWidget(self.coverage_divider)
        self.layers_bar = QWidget()
        self.layers_bar.setFixedHeight(26)
        layers_bar_layout = QHBoxLayout(self.layers_bar)
        # Match the right edge of the third card and its six-dot drag handle.
        layers_bar_layout.setContentsMargins(0, 0, 7, 0)
        layers_bar_layout.setSpacing(7)
        self.layers_label = _caps(
            "LAYERS · PLAY CARDS TO BUILD THE LOOP LIVE"
        )
        layers_bar_layout.addWidget(self.layers_label)
        layers_bar_layout.addStretch()
        self.all_layers_transport = QPushButton("PLAY ALL")
        self.all_layers_transport.setProperty("accent", "purple")
        self.all_layers_transport.setFixedHeight(22)
        self.all_layers_transport.setEnabled(False)
        self.all_layers_transport.clicked.connect(self._toggle_all_layers)
        layers_bar_layout.addWidget(
            self.all_layers_transport, 0, Qt.AlignVCenter
        )
        self.drag_all = MultiFileDragHandle()
        layers_bar_layout.addWidget(self.drag_all, 0, Qt.AlignVCenter)
        results_layout.addWidget(self.layers_bar)
        self.layers_area = QScrollArea()
        self.layers_area.setWidgetResizable(True)
        self.layers_area.setProperty("role", "layers")
        self.layers_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )
        self.layers_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.layers_content = QWidget()
        self.layers_grid = QGridLayout(self.layers_content)
        self.layers_grid.setContentsMargins(6, 6, 6, 6)
        self.layers_grid.setHorizontalSpacing(8)
        self.layers_grid.setVerticalSpacing(6)
        self.layers_area.setWidget(self.layers_content)
        results_layout.addWidget(self.layers_area, 1)

        self.generation_footer = QWidget()
        self.generation_footer.setFixedHeight(32)
        footer_layout = QHBoxLayout(self.generation_footer)
        footer_layout.setContentsMargins(7, 2, 0, 1)
        footer_layout.setSpacing(7)
        footer_layout.addWidget(LineIcon("drive", "#9da5ac", 20))
        self.generation_storage_label = QLabel("0 generations · 0 o")
        self.generation_storage_label.setProperty("role", "storage")
        footer_layout.addWidget(self.generation_storage_label)
        footer_layout.addSpacing(18)
        footer_layout.addWidget(LineIcon("music_note", PURPLE, 17))
        self.generation_status = MiddleElideLabel(
            "Ready for a layer library."
        )
        self.generation_status.setProperty("role", "statusDetail")
        footer_layout.addWidget(self.generation_status, 1)
        self.open_output = QPushButton("OPEN OUTPUT FOLDER")
        self.open_output.setProperty("accent", "purple")
        self.open_output.clicked.connect(self.openOutputRequested.emit)
        footer_layout.addWidget(self.open_output)
        self.manage_button = QPushButton("MANAGE")
        self.manage_button.setProperty("accent", "purple")
        self.manage_button.clicked.connect(self.manageRequested.emit)
        footer_layout.addWidget(self.manage_button)
        results_layout.addWidget(self.generation_footer)
        # Compatibility aliases retained for existing diagnostics/tests.
        self.results_area = self.layers_area
        self.results_content = self.layers_content
        self.results_grid = self.layers_grid
        self._show_empty_results(
            "Your synchronized generated layers will appear here."
        )
        self._set_empty_library_coverage()
        layout.addWidget(results, 1)
        return page

    def _add_slot(self, category: str) -> None:
        slot = RecipeSlotWidget(category, self.slot_host)
        selector = slot.selector
        slot.remove_button.clicked.connect(
            lambda _checked=False, item=slot: self._remove_slot(item)
        )
        selector.currentTextChanged.connect(
            lambda _text, item=slot: self._slot_category_changed(item)
        )
        self.slot_layout.addWidget(slot)
        self._slot_widgets.append(slot)
        self._slot_combos.append(selector)
        self._refresh_slot_strip()
        QTimer.singleShot(0, self._scroll_slots_to_end)

    def _remove_slot(self, slot: RecipeSlotWidget | None = None) -> None:
        if len(self._slot_combos) <= 1:
            return
        if slot is None:
            slot = self._slot_widgets[-1]
        try:
            index = self._slot_widgets.index(slot)
        except ValueError:
            return
        if slot in self._locked_recipe_slots():
            return
        for card in self._stem_cards:
            if card.recipe_slot is slot:
                card.recipe_slot = None
                card.setSlotIndex(-1)
                card.setLockEnabled(False)
                card.setTransformEnabled(False)
        selector = self._slot_combos.pop(index)
        self._slot_widgets.pop(index)
        self.slot_layout.removeWidget(slot)
        selector.setEnabled(False)
        slot.hide()
        slot.deleteLater()
        for card in self._stem_cards:
            if card.recipe_slot in self._slot_widgets:
                card.setSlotIndex(self._slot_widgets.index(card.recipe_slot))
        self._refresh_slot_strip()

    def _refresh_slot_strip(self) -> None:
        count = len(self._slot_widgets)
        width = sum(slot.width() for slot in self._slot_widgets)
        width += max(0, count - 1) * self.slot_layout.spacing()
        self.slot_host.setFixedSize(max(1, width), 25)
        self._sync_recipe_slot_states()
        self.slot_host.updateGeometry()
        self._resize_slot_scroll()
        QTimer.singleShot(0, self._resize_slot_scroll)

    def _resize_slot_scroll(self) -> None:
        row_layout = self.slot_row.layout()
        margins = row_layout.contentsMargins()
        capacity = (
            self.slot_row.width()
            - margins.left()
            - margins.right()
            - self.add_slot_button.width()
            - row_layout.spacing()
        )
        if capacity <= 0:
            return
        self.slot_scroll.setFixedWidth(
            min(max(1, self.slot_host.width()), capacity)
        )

    def _scroll_slots_to_end(self) -> None:
        scroll_bar = self.slot_scroll.horizontalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())

    def _slot_category_changed(self, slot: RecipeSlotWidget) -> None:
        self._refresh_slot_strip()
        try:
            slot_index = self._slot_widgets.index(slot)
        except ValueError:
            return
        category = slot.selector.currentText()
        for card in self._stem_cards:
            if (
                card.recipe_slot is slot
                and card.locked
                and str(card.data.get("category")) != category
            ):
                card.setLocked(False, emit=True)

    def _locked_recipe_slots(self) -> set[RecipeSlotWidget]:
        return {
            card.recipe_slot
            for card in self._stem_cards
            if (
                card.locked
                and card.recipe_slot in self._slot_widgets
                and str(card.data.get("category"))
                == card.recipe_slot.selector.currentText()
            )
        }

    def _sync_recipe_slot_states(self) -> None:
        locked_slots = self._locked_recipe_slots()
        can_remove = len(self._slot_widgets) > 1
        controls_enabled = not self._generation_busy
        for slot in self._slot_widgets:
            slot.setRecipeLocked(
                slot in locked_slots,
                controls_enabled=controls_enabled,
                can_remove=can_remove,
            )

    @Slot(int, str, bool)
    def _card_lock_changed(
        self,
        _slot_index: int,
        _identity: str,
        _locked: bool,
    ) -> None:
        self._sync_recipe_slot_states()

    def _clear_library_category_tokens(self) -> None:
        while self.coverage_flow.count():
            item = self.coverage_flow.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self.library_category_tokens.clear()

    def _add_library_category_token(self, text: str) -> QLabel:
        token = QLabel(str(text))
        token.setProperty("role", "libraryCategory")
        token.setStyleSheet(
            "color:#a7b2b8;font-size:8.5px;font-weight:700;"
        )
        token.setFixedHeight(11)
        self.coverage_flow.addWidget(token)
        self.library_category_tokens.append(token)
        return token

    def _set_empty_library_coverage(self) -> None:
        self.library_total_value.setText("—")
        self.library_total_unit.setText("LAYERS")
        self.library_review_badge.clear()
        self.library_review_badge.setVisible(False)
        self._clear_library_category_tokens()
        self._add_library_category_token(
            "SCAN A LIBRARY TO SEE CATEGORY COVERAGE"
        )
        self.coverage_flow.invalidate()
        self.coverage_flow_host.updateGeometry()

    def _folder_changed(self, path: str) -> None:
        normalized = os.path.realpath(path) if path else ""
        if (
            normalized
            and self._library_ready
            and normalized == self._loaded_library_path
        ):
            self.scan_status.setFullText(
                "Library already loaded from SQLite cache."
            )
            return
        self._library_ready = False
        self._loaded_library_path = ""
        self.scan_button.setEnabled(bool(path))
        self.generate_button.setEnabled(False)
        self._preview_seed_available = False
        self.preview_seed_button.setEnabled(False)
        self.scan_progress.setValue(0)
        self.scan_status.setFullText(
            "Folder selected · click Scan Library"
            if path
            else "No folder selected"
        )
        self._set_empty_library_coverage()
        self.generation_status.setFullText(
            "Scan the selected library before generating."
            if path
            else "Ready for a layer library."
        )
        self.reset_generation_results(
            "Scan the selected library to generate a new loop."
        )

    def _request_scan(self) -> None:
        if self.library_path:
            self.scanRequested.emit(self.library_path)

    def _validated_bpm(self) -> int | None:
        try:
            bpm = int(self.target_bpm.text())
        except ValueError:
            return None
        return bpm if 40 <= bpm <= 300 else None

    @property
    def library_path(self) -> str:
        return str(self.library_drop.path or "")

    def restore_library_path(self, path: str) -> bool:
        """Display a cached library path without requesting a new scan."""

        return bool(self.library_drop.set_path(path))

    def generation_request(self) -> dict:
        bpm = self._validated_bpm()
        if bpm is None:
            raise ValueError("Target BPM must be between 40 and 300.")
        locked_slots: list[tuple[int, str]] = []
        for card in self._stem_cards:
            slot = card.recipe_slot
            if (
                card.locked
                and slot in self._slot_widgets
                and slot.selector.currentText()
                == str(card.data.get("category"))
            ):
                slot_index = self._slot_widgets.index(slot)
                card.setSlotIndex(slot_index)
                locked_slots.append((slot_index, card.identity))
        return {
            "categories": [
                selector.currentText() for selector in self._slot_combos
            ],
            "target_bpm": bpm,
            "target_key": self.target_key.currentText(),
            "bars": 8,
            "seed": self._seed,
            "key_confidence_threshold": DEFAULT_KEY_MARGIN_THRESHOLD,
            "locked_slots": tuple(sorted(locked_slots)),
        }

    def _request_generation(self) -> None:
        try:
            request = self.generation_request()
        except ValueError as error:
            self.generation_status.setFullText(str(error))
            return
        self._seed += 1
        if self._has_generation:
            self.generateAgainRequested.emit(request)
        else:
            self.generateRequested.emit(request)

    def _request_again(self) -> None:
        try:
            request = self.generation_request()
        except ValueError as error:
            self.generation_status.setFullText(str(error))
            return
        self._seed += 1
        self.generateAgainRequested.emit(request)

    def _request_preview_seed(self) -> None:
        if self._preview_seed_available:
            self.previewSeedRequested.emit()

    @Slot(bool, int, str)
    def set_scan_busy(
        self, busy: bool, progress: int = 0, status: str = ""
    ) -> None:
        self._scan_busy = bool(busy)
        if busy:
            self._library_ready = False
            self.generate_button.setEnabled(False)
            self.preview_seed_button.setEnabled(False)
        self.scan_button.setEnabled(
            not busy and not self._generation_busy and bool(self.library_path)
        )
        self.library_drop.setEnabled(not busy and not self._generation_busy)
        self.scan_progress.setValue(max(0, min(100, int(progress))))
        if status:
            self.scan_status.setFullText(status)

    @Slot(int, dict, int)
    def set_library_summary(
        self, total: int, counts: dict, review_count: int
    ) -> None:
        self.library_total_value.setText(str(max(0, int(total))))
        self.library_total_unit.setText("LAYERS")
        review_count = max(0, int(review_count))
        self.library_review_badge.setText(
            f"{review_count} TO REVIEW" if review_count else ""
        )
        self.library_review_badge.setVisible(bool(review_count))
        self._clear_library_category_tokens()
        for label in TAXONOMY:
            count = int(counts.get(label, 0))
            if count > 0:
                self._add_library_category_token(f"{label} {count}")
        if not self.library_category_tokens:
            self._add_library_category_token("NO CATEGORIZED LAYERS")
        self.coverage_flow.invalidate()
        self.coverage_flow_host.updateGeometry()
        self._library_ready = total > review_count
        self._loaded_library_path = (
            os.path.realpath(self.library_path)
            if self._library_ready and self.library_path
            else ""
        )
        self.generate_button.setEnabled(
            self._library_ready and not self._generation_busy
        )
        self.generation_status.setFullText(
            "Library ready. Choose a recipe, BPM and exact key."
        )

    @Slot(bool, str)
    def set_generation_busy(self, busy: bool, status: str = "") -> None:
        self._generation_busy = bool(busy)
        self.generate_button.setEnabled(
            not busy and self._library_ready
        )
        self.preview_seed_button.setEnabled(
            not busy and self._preview_seed_available
        )
        self.add_slot_button.setEnabled(not busy)
        self.manage_button.setEnabled(not busy)
        self.scan_button.setEnabled(
            not busy and not self._scan_busy and bool(self.library_path)
        )
        self.library_drop.setEnabled(not busy and not self._scan_busy)
        self._sync_recipe_slot_states()
        for card in self._stem_cards:
            card.setLockEnabled(not busy)
            card.setTransformEnabled(not busy)
        self.target_bpm.setEnabled(not busy)
        self.target_key.setEnabled(not busy)
        if status:
            self.generation_status.setFullText(status)

    @Slot(bool)
    def set_preview_seed_available(self, available: bool) -> None:
        self._preview_seed_available = bool(available)
        self.preview_seed_button.setEnabled(
            self._preview_seed_available and not self._generation_busy
        )

    def _clear_results(self) -> None:
        if hasattr(self, "_layer_player"):
            self._layer_player.stop(reset=True)
        self._cards.clear()
        self._stem_cards.clear()
        self._mix_paths.clear()
        self._solo_path = None
        while self.layers_grid.count():
            item = self.layers_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self.layers_content.setMinimumHeight(0)
        self.layers_content.updateGeometry()
        self.layers_content.update()
        self.layers_area.viewport().update()
        self.canvas.update()
        self._sync_recipe_slot_states()

    def _show_empty_results(self, text: str) -> None:
        self._clear_results()
        empty = QLabel(text)
        empty.setAlignment(Qt.AlignCenter)
        empty.setStyleSheet(f"color:{MUTED};font-size:10px")
        self.layers_grid.addWidget(empty, 0, 0, 1, 3)

    @Slot(str)
    def reset_generation_results(self, text: str) -> None:
        """Clear stale cards when the active library is invalidated."""

        self._show_empty_results(text)
        self.drag_all.set_paths(())
        self.all_layers_transport.setText("PLAY ALL")
        self.all_layers_transport.setEnabled(False)
        self._has_generation = False
        self._master_path = ""
        self.generate_button.setText("GENERATE")

    @Slot(dict, list)
    def set_generation_results(
        self, master: dict, stems: list[dict]
    ) -> None:
        new_master_path = str(master.get("path") or "")
        preserve_live_mix = bool(
            self._master_path and self._master_path == new_master_path
        )
        active_identities = {
            card.identity
            for card in self._stem_cards
            if card.path in self._layer_player.activePaths()
        } if preserve_live_mix else set()
        previous_ratio = (
            self._layer_player.positionRatio() if preserve_live_mix else 0.0
        )
        was_playing = self._layer_player.isPlaying() if preserve_live_mix else False
        self._clear_results()
        for index, data in enumerate(stems):
            card = GenerateCard(data)
            if 0 <= card.slot_index < len(self._slot_widgets):
                candidate_slot = self._slot_widgets[card.slot_index]
                if (
                    candidate_slot.selector.currentText()
                    == str(card.data.get("category"))
                ):
                    card.recipe_slot = candidate_slot
            if card.recipe_slot is None:
                card.setLocked(False, emit=False)
                card.setSlotIndex(-1)
                card.setLockEnabled(False)
                card.setTransformEnabled(False)
            self._wire_card(card)
            self.layers_grid.addWidget(
                card, index // 3, index % 3
            )
            self._cards.append(card)
            self._stem_cards.append(card)
        for column in range(3):
            self.layers_grid.setColumnStretch(column, 1)
        rows = max(1, math.ceil(len(stems) / 3))
        self.layers_content.setMinimumHeight(rows * 76 + 6)
        if not stems:
            empty = QLabel("No individual layer was rendered.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(f"color:{MUTED};font-size:10px")
            self.layers_grid.addWidget(empty, 0, 0, 1, 3)
        paths = [str(master["path"])] + [
            str(item["path"]) for item in stems
        ]
        self.drag_all.set_paths(paths)
        self.dragAllRequested.emit(tuple(paths))
        self._master_path = new_master_path
        self._layer_player.setLayers(card.path for card in self._stem_cards)
        restore_paths = [
            card.path
            for card in self._stem_cards
            if card.identity and card.identity in active_identities
        ]
        if restore_paths:
            self._layer_player.restore(
                restore_paths,
                previous_ratio,
                playing=was_playing,
            )
        self.all_layers_transport.setText("PLAY ALL")
        self.all_layers_transport.setEnabled(bool(self._stem_cards))
        self._has_generation = True
        self.generate_button.setText("GENERATE AGAIN")
        self._sync_recipe_slot_states()

    @Slot(int, int, int)
    def set_generation_history_summary(
        self,
        generation_count: int,
        total_bytes: int,
        _layer_count: int = 0,
    ) -> None:
        count = max(0, int(generation_count))
        noun = "generation" if count == 1 else "generations"
        self.generation_storage_label.setText(
            f"{count} {noun} · {format_decimal_size(max(0, int(total_bytes)))}"
        )

    def _wire_card(self, card: GenerateCard) -> None:
        card.playRequested.connect(self._play_path)
        card.mixToggleRequested.connect(self._toggle_mix_path)
        card.seekRequested.connect(self._seek_path)
        card.lockChanged.connect(self._card_lock_changed)
        card.lockChanged.connect(self.lockChanged.emit)
        card.alternateKeyRequested.connect(self.alternateKeyRequested.emit)
        card.octaveShiftRequested.connect(self.octaveShiftRequested.emit)
        card.normalizationRequested.connect(self.normalizationRequested.emit)
        card.volumeChanged.connect(self._set_layer_volume)

    @Slot(str, int)
    def _set_layer_volume(self, path: str, percent: int) -> None:
        """Apply preview attenuation without restarting the shared audio clock."""

        self._layer_player.setLayerVolume(
            str(path),
            max(0.0, min(1.0, int(percent) / 100.0)),
        )

    @Slot(int, str, bool)
    def set_layer_transform_busy(
        self,
        slot_index: int,
        identity: str,
        busy: bool,
    ) -> None:
        for card in self._stem_cards:
            if (
                card.slot_index == int(slot_index)
                and card.identity == str(identity)
            ):
                card.setTransformBusy(bool(busy))
                return

    @Slot(int, str, bool)
    def set_alternate_key_busy(
        self,
        slot_index: int,
        identity: str,
        busy: bool,
    ) -> None:
        """Compatibility alias for the original ALT-only controller API."""

        self.set_layer_transform_busy(slot_index, identity, busy)

    @Slot(dict, object)
    def update_generation_layer(self, stem: dict, pcm=None) -> bool:
        """Hot-swap one card and its PCM while the common clock keeps running."""

        identity = str(stem.get("identity") or "")
        card = next(
            (item for item in self._stem_cards if item.identity == identity),
            None,
        )
        if card is None:
            return False
        if pcm is None:
            replaced = self._layer_player.replaceLayer(card.path)
        else:
            replaced = self._layer_player.replaceLayerPCM(card.path, pcm)
        if not replaced:
            card.setTransformBusy(False)
            return False
        card.updateData(stem)
        return True

    @Slot()
    def _toggle_all_layers(self) -> None:
        if self._layer_player.activePaths():
            self._mix_paths.clear()
            self._solo_path = None
            self._layer_player.stopAll()
        else:
            self._solo_path = None
            self._mix_paths = {card.path for card in self._stem_cards}
            self._layer_player.playAll()

    @Slot(str)
    def _play_path(self, path: str) -> None:
        path = str(path)
        already_solo = self._solo_path == path and self._layer_player.activePaths() == (path,)
        self._mix_paths.clear()
        self._solo_path = None if already_solo else path
        if already_solo:
            self._layer_player.stopAll()
        else:
            self._layer_player.playSolo(path)

    @Slot(str)
    def _toggle_mix_path(self, path: str) -> None:
        path = str(path)
        self._solo_path = None
        starting_new_mix = not self._mix_paths and path not in self._mix_paths
        if path in self._mix_paths:
            self._mix_paths.remove(path)
        else:
            self._mix_paths.add(path)
        self._layer_player.playPaths(
            self._mix_paths,
            restart=starting_new_mix,
        )

    @Slot(str, float)
    def _seek_path(self, path: str, ratio: float) -> None:
        ratio = max(0.0, min(1.0, ratio))
        if path not in self._layer_player.activePaths():
            self._mix_paths.clear()
            self._solo_path = str(path)
            self._layer_player.playSolo(path)
        self._layer_player.seek(ratio)

    @Slot(float)
    def _playback_position(self, ratio: float) -> None:
        active = set(self._layer_player.activePaths())
        for card in self._cards:
            card.waveform.setProgress(
                ratio if card.path in active else 0.0
            )

    @Slot(tuple)
    def _active_layer_paths_changed(self, paths: tuple) -> None:
        active = set(paths)
        self.all_layers_transport.setText("STOP" if active else "PLAY ALL")
        for card in self._cards:
            card.setPlaybackState(
                "playing"
                if card.path == self._solo_path and card.path in active
                else "stopped"
            )
            card.setMixActive(card.path in self._mix_paths and card.path in active)
            if card.path not in active:
                card.waveform.setProgress(0.0)

    @Slot(str)
    def _audio_preview_error(self, message: str) -> None:
        self.generation_status.setFullText(f"Audio preview: {message}")

    @Slot()
    def stop_audio(self) -> None:
        """Release the synchronized preview during app shutdown."""

        self._layer_player.stop(reset=True)

    @Slot(int)
    def _set_ui_scale(self, percent: int) -> None:
        factor = max(1.0, min(1.5, float(percent) / 100.0))
        self.view.setTransform(QTransform.fromScale(factor, factor))
        width = round(BASE_WIDTH * factor)
        height = round(BASE_HEIGHT * factor)
        self.view.setFixedSize(width, height)
        self.setFixedSize(width, height)

    def closeEvent(self, event) -> None:
        self.stop_audio()
        self.closing.emit()
        super().closeEvent(event)


class GeneratePage(GeneratePrototypeWindow):
    """Production Generate tab using the validated compact 1.9 layout."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent, embedded=True)
        for selector in self.findChildren(AnchoredChoiceSelector):
            _prime_native_popup(selector)

    def _generate_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(9, 9, 9, 9)
        layout.setSpacing(9)

        library, library_body, _ = _section(
            "red",
            "folder_in",
            "LAYER LIBRARY",
            "Choose one prepared folder of extracted layers for generation.",
        )
        self.library_section = library
        library.setFixedHeight(119)
        library_layout = QHBoxLayout(library_body)
        library_layout.setContentsMargins(12, 0, 12, 8)
        library_layout.setSpacing(8)
        self.library_drop = V16DropZone(
            "folder",
            "Drop your layer library here",
            RED,
            dialog_parent=self,
        )
        self.library_drop.setFixedHeight(63)
        self.library_drop.pathChanged.connect(self._folder_changed)
        library_layout.addWidget(self.library_drop, 13)
        library_layout.addWidget(self._library_summary_widget(), 27)
        layout.addWidget(library)

        results, results_body, _ = _section(
            "purple",
            "layers",
            "GENERATE",
            "Choose a recipe and preview the generated loop with synchronized layer cards.",
        )
        self.recipe_section = results
        self.results_section = results
        results_layout = QVBoxLayout(results_body)
        results_layout.setContentsMargins(12, 0, 12, 6)
        results_layout.setSpacing(1)
        results_layout.addWidget(self._compact_controls_widget())

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setFixedHeight(1)
        divider.setStyleSheet("background:#26343d;border:0")
        self.coverage_divider = divider
        results_layout.addWidget(divider)
        results_layout.addWidget(self._layers_bar_widget())
        results_layout.addWidget(self._layers_area_widget(), 1)
        results_layout.addWidget(self._generation_footer_widget())

        self.library_coverage = self.coverage_flow_host
        self.results_area = self.layers_area
        self.results_content = self.layers_content
        self.results_grid = self.layers_grid
        self._show_empty_results(
            "Your synchronized generated layers will appear here."
        )
        self._set_empty_library_coverage()
        layout.addWidget(results, 1)
        return page

    def _library_summary_widget(self) -> QFrame:
        summary = QFrame()
        summary.setProperty("role", "pathBox")
        outer = QVBoxLayout(summary)
        outer.setContentsMargins(10, 4, 10, 4)
        outer.setSpacing(1)

        library_row = QHBoxLayout()
        library_row.setSpacing(5)
        library_row.addWidget(LineIcon("folder", RED, 18))
        self.scan_status = MiddleElideLabel("No folder selected")
        self.scan_status.setProperty("role", "statusDetail")
        library_row.addWidget(self.scan_status, 1)
        self.scan_button = QPushButton("SCAN LIBRARY")
        self.scan_button.setProperty("accent", "red")
        self.scan_button.setFixedSize(92, 23)
        self.scan_button.setStyleSheet("font-size:7px;padding:0")
        self.scan_button.setEnabled(False)
        self.scan_button.clicked.connect(self._request_scan)
        library_row.addWidget(self.scan_button)
        outer.addLayout(library_row)

        total_row = QHBoxLayout()
        total_row.setContentsMargins(23, 0, 0, 0)
        total_row.setSpacing(5)
        self.library_total_value = QLabel("—")
        self.library_total_value.setStyleSheet(
            f"color:{GREEN};font-size:13px;font-weight:900"
        )
        total_row.addWidget(self.library_total_value)
        self.library_total_unit = QLabel("LAYERS")
        self.library_total_unit.setProperty("role", "caps")
        total_row.addWidget(self.library_total_unit)
        total_row.addStretch(1)
        self.library_review_badge = QLabel("")
        self.library_review_badge.setStyleSheet(
            f"color:{ORANGE};font-size:8px;font-weight:850"
        )
        self.library_review_badge.setVisible(False)
        total_row.addWidget(self.library_review_badge)
        outer.addLayout(total_row)

        self.coverage_flow_host = QWidget()
        self.coverage_flow = FlowLayout(
            self.coverage_flow_host,
            horizontal_spacing=6,
            vertical_spacing=1,
        )
        self.coverage_flow.setContentsMargins(23, 0, 0, 0)
        self.library_category_tokens: list[QLabel] = []
        outer.addWidget(self.coverage_flow_host, 1)

        self.scan_progress = QProgressBar()
        self.scan_progress.setRange(0, 100)
        self.scan_progress.setValue(0)
        self.scan_progress.setFixedHeight(3)
        outer.addWidget(self.scan_progress)
        return summary

    def _compact_controls_widget(self) -> QWidget:
        controls = QWidget()
        controls.setFixedHeight(48)
        row = QHBoxLayout(controls)
        row.setContentsMargins(0, 1, 0, 3)
        row.setSpacing(6)

        recipe_column = QVBoxLayout()
        recipe_column.setContentsMargins(0, 0, 0, 0)
        recipe_column.setSpacing(2)
        self.recipe_slots_label = _caps("RECIPE SLOTS")
        recipe_column.addWidget(self.recipe_slots_label)
        self.slot_row = QWidget()
        self.slot_row.setFixedHeight(28)
        slot_row_layout = QHBoxLayout(self.slot_row)
        slot_row_layout.setContentsMargins(0, 0, 0, 0)
        slot_row_layout.setSpacing(0)
        self.slot_scroll = QScrollArea()
        self.slot_scroll.setProperty("role", "slotStrip")
        self.slot_scroll.setFrameShape(QFrame.NoFrame)
        self.slot_scroll.setWidgetResizable(False)
        self.slot_scroll.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.slot_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.slot_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.slot_scroll.setFixedHeight(28)
        self.slot_scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollBar:horizontal{height:3px;background:#19232a;margin:0;}"
            "QScrollBar::handle:horizontal{background:#4b575e;"
            "min-width:24px;border-radius:1px;}"
            "QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0;}"
            "QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal{"
            "background:transparent;}"
        )
        self.slot_host = QWidget()
        self.slot_host.setFixedHeight(25)
        self.slot_host.setStyleSheet("background:transparent")
        self.slot_layout = QHBoxLayout(self.slot_host)
        self.slot_layout.setContentsMargins(0, 0, 0, 0)
        self.slot_layout.setSpacing(4)
        for category in ("Bass", "Chords", "Lead", "Counter"):
            self._add_slot(category)
        self.add_slot_button = CenteredPlusButton(self.slot_host)
        self.add_slot_button.setToolTip("Add another layer slot")
        self.add_slot_button.clicked.connect(lambda: self._add_slot("Lead"))
        self.slot_layout.addWidget(
            self.add_slot_button, 0, Qt.AlignVCenter
        )
        self.slot_scroll.setWidget(self.slot_host)
        slot_row_layout.addWidget(self.slot_scroll, 1)
        recipe_column.addWidget(self.slot_row)
        row.addLayout(recipe_column, 1)
        self._refresh_slot_strip(scroll_to_end=False)

        self.target_row = QWidget()
        self.target_row.setFixedHeight(25)
        target_layout = QHBoxLayout(self.target_row)
        target_layout.setContentsMargins(0, 0, 0, 0)
        target_layout.setSpacing(6)
        self.target_bpm_label = _caps("TARGET BPM")
        target_layout.addWidget(self.target_bpm_label, 0, Qt.AlignVCenter)
        self.target_bpm = QLineEdit("140")
        self.target_bpm.setProperty("role", "targetValue")
        self.target_bpm.setAlignment(Qt.AlignCenter)
        self.target_bpm.setMaxLength(3)
        self.target_bpm.setValidator(QIntValidator(40, 300, self.target_bpm))
        self.target_bpm.setFixedSize(46, 25)
        self.target_bpm.setStyleSheet("font-size:8px;padding:0 4px")
        target_layout.addWidget(self.target_bpm)
        target_layout.addSpacing(8)
        self.target_key_label = _caps("TARGET KEY")
        target_layout.addWidget(self.target_key_label, 0, Qt.AlignVCenter)
        self.target_key = CompactKeySelector(
            RELATIVE_KEY_FAMILIES,
            accent=ORANGE,
            exact_popup_width=True,
            show_check=False,
        )
        self.target_key.setCurrentText("C major / A minor")
        self.target_key.setStyleSheet(
            "font-size:8px;padding:0 15px 0 6px"
        )
        self.target_key.ensurePolished()
        longest = max(
            self.target_key.fontMetrics().horizontalAdvance(key)
            for key in RELATIVE_KEY_FAMILIES
        )
        _compact_popup_rows(self.target_key)
        target_key_width = max(
            longest + 24,
            self.target_key._popup.sizeHint().width(),
        )
        self.target_key.setFixedSize(target_key_width, 25)
        _prime_native_popup(self.target_key)
        target_layout.addWidget(self.target_key)
        row.addWidget(self.target_row, 0, Qt.AlignBottom)

        self.preview_seed_button = QPushButton("PREVIOUS SEED")
        self.preview_seed_button.setProperty("accent", "orange")
        self.preview_seed_button.setFixedSize(90, 25)
        self.preview_seed_button.setStyleSheet("font-size:7px;padding:0")
        self.preview_seed_button.setEnabled(False)
        self.preview_seed_button.clicked.connect(self._request_preview_seed)
        row.addWidget(self.preview_seed_button, 0, Qt.AlignBottom)
        self.generate_button = QPushButton("GENERATE")
        self.generate_button.setProperty("role", "convertAction")
        self.generate_button.setFixedSize(90, 25)
        self.generate_button.setStyleSheet("font-size:7px;padding:0")
        self.generate_button.setEnabled(False)
        self.generate_button.clicked.connect(self._request_generation)
        row.addWidget(self.generate_button, 0, Qt.AlignBottom)
        return controls

    def _layers_bar_widget(self) -> QWidget:
        self.layers_bar = QWidget()
        self.layers_bar.setFixedHeight(26)
        row = QHBoxLayout(self.layers_bar)
        row.setContentsMargins(0, 0, 7, 0)
        row.setSpacing(7)
        self.layers_label = _caps(
            "LAYERS · PLAY CARDS TO BUILD THE LOOP LIVE"
        )
        row.addWidget(self.layers_label)
        row.addStretch()
        self.all_layers_transport = QPushButton("PLAY ALL")
        self.all_layers_transport.setProperty("accent", "purple")
        self.all_layers_transport.setFixedHeight(22)
        self.all_layers_transport.setEnabled(False)
        self.all_layers_transport.clicked.connect(self._toggle_all_layers)
        row.addWidget(self.all_layers_transport, 0, Qt.AlignVCenter)
        self.drag_all = MultiFileDragHandle()
        row.addWidget(self.drag_all, 0, Qt.AlignVCenter)
        return self.layers_bar

    def _layers_area_widget(self) -> QScrollArea:
        self.layers_area = QScrollArea()
        self.layers_area.setWidgetResizable(True)
        self.layers_area.setProperty("role", "layers")
        self.layers_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.layers_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.layers_content = QWidget()
        self.layers_grid = QGridLayout(self.layers_content)
        self.layers_grid.setContentsMargins(6, 6, 6, 6)
        self.layers_grid.setHorizontalSpacing(8)
        self.layers_grid.setVerticalSpacing(6)
        self.layers_grid.setAlignment(Qt.AlignTop)
        self.layers_area.setWidget(self.layers_content)
        return self.layers_area

    def _generation_footer_widget(self) -> QWidget:
        self.generation_footer = QWidget()
        self.generation_footer.setFixedHeight(32)
        row = QHBoxLayout(self.generation_footer)
        row.setContentsMargins(7, 2, 0, 1)
        row.setSpacing(7)
        row.addWidget(LineIcon("drive", "#9da5ac", 20))
        self.generation_storage_label = QLabel("0 generations · 0 o")
        self.generation_storage_label.setProperty("role", "storage")
        row.addWidget(self.generation_storage_label)
        row.addSpacing(18)
        row.addWidget(LineIcon("music_note", PURPLE, 17))
        self.generation_status = MiddleElideLabel(
            "Ready for a layer library."
        )
        self.generation_status.setProperty("role", "statusDetail")
        row.addWidget(self.generation_status, 1)
        self.open_output = QPushButton("OPEN OUTPUT FOLDER")
        self.open_output.setProperty("accent", "purple")
        self.open_output.clicked.connect(self.openOutputRequested.emit)
        row.addWidget(self.open_output)
        self.manage_button = QPushButton("MANAGE")
        self.manage_button.setProperty("accent", "purple")
        self.manage_button.clicked.connect(self.manageRequested.emit)
        row.addWidget(self.manage_button)
        return self.generation_footer

    def _add_slot(self, category: str) -> None:
        slot = CompactRecipeSlotWidget(category, self.slot_host)
        selector = slot.selector
        slot.remove_button.clicked.connect(
            lambda _checked=False, item=slot: self._remove_slot(item)
        )
        selector.currentTextChanged.connect(
            lambda _text, item=slot: self._slot_category_changed(item)
        )
        insert_index = self.slot_layout.count()
        if hasattr(self, "add_slot_button"):
            insert_index = self.slot_layout.indexOf(self.add_slot_button)
        self.slot_layout.insertWidget(
            insert_index, slot, 0, Qt.AlignVCenter
        )
        self._slot_widgets.append(slot)
        self._slot_combos.append(selector)
        if hasattr(self, "slot_scroll"):
            self._refresh_slot_strip(scroll_to_end=True)

    def _refresh_slot_strip(self, *, scroll_to_end: bool = False) -> None:
        self._apply_slot_strip_geometry(scroll_to_end=scroll_to_end)
        QTimer.singleShot(
            0,
            lambda: self._apply_slot_strip_geometry(
                scroll_to_end=scroll_to_end
            ),
        )

    def _apply_slot_strip_geometry(self, *, scroll_to_end: bool) -> None:
        self.slot_layout.invalidate()
        self.slot_layout.activate()
        content_width = max(
            self.slot_layout.sizeHint().width(),
            self.slot_layout.minimumSize().width(),
            1,
        )
        self.slot_host.setFixedSize(content_width, 25)
        self._sync_recipe_slot_states()
        if scroll_to_end:
            self.slot_scroll.horizontalScrollBar().setValue(
                self.slot_scroll.horizontalScrollBar().maximum()
            )

    def _resize_slot_scroll(self) -> None:
        self._refresh_slot_strip(scroll_to_end=False)

    def _scroll_slots_to_end(self) -> None:
        self.slot_scroll.horizontalScrollBar().setValue(
            self.slot_scroll.horizontalScrollBar().maximum()
        )

    def generation_request(self) -> dict:
        request = super().generation_request()
        key_family = str(request["target_key"])
        if "/" in key_family:
            request["target_key"] = key_family.rsplit("/", 1)[-1].strip()
        return request


__all__ = [
    "EXACT_KEYS",
    "GeneratePage",
    "GenerateCard",
    "GeneratePrototypeWindow",
    "GenerateWaveform",
]
