"""Stem Slicer 1.9B Generate cards-as-slots interface."""

from __future__ import annotations

import math
import re

from PySide6.QtCore import QPointF, Qt, Signal, Slot
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


import generator_ui_base as _base

from functional_core import (
    LayerPlayButton,
    LineIcon,
    MidiDragHandle,
    MultiFileDragHandle,
)
from layer_library import TAXONOMY
from validated_ui import (
    GREEN,
    MUTED,
    ORANGE,
    PURPLE,
    RED,
    AnchoredChoiceSelector,
    MiddleElideLabel,
)
from storage import format_decimal_size


EXACT_KEYS = _base.EXACT_KEYS
RELATIVE_KEY_FAMILIES = _base.RELATIVE_KEY_FAMILIES
GenerateWaveform = _base.GenerateWaveform
GeneratePrototypeWindow = _base.GeneratePrototypeWindow


class PrototypeLayerVolumeButton(_base.LayerVolumeButton):
    """Volume control whose fader keeps the normal arrow pointer."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.slider.setCursor(Qt.ArrowCursor)
        self._popup.setCursor(Qt.ArrowCursor)


LayerVolumeButton = PrototypeLayerVolumeButton
_base.LayerVolumeButton = PrototypeLayerVolumeButton


class GenerateMidiDragHandle(MidiDragHandle):
    """Quick Extract's exact MIDI handle with an explicit restart state."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Keep the Quick Extract wordmark, but trim its Generate-card
        # footprint very slightly so it balances with the adjacent six dots.
        self.setFixedSize(28, 20)

    def set_processing(self) -> None:
        self.path = ""
        self.state = "processing"
        self._frame = 0
        self.setCursor(Qt.ArrowCursor)
        self.setToolTip("Generating MIDI…")
        if not self._timer.isActive():
            self._timer.start()
        self.update()


class CardCategorySelector(AnchoredChoiceSelector):
    """Card-native category picker sized for the longest taxonomy label."""

    def __init__(self, category: str, parent=None) -> None:
        super().__init__(
            TAXONOMY,
            accent=PURPLE,
            exact_popup_width=True,
            show_check=False,
            parent=parent,
        )
        self.setProperty("cardCategory", True)
        self.setStyleSheet(
            "QPushButton{background:#0f171b;border:1px solid #35434b;"
            "border-radius:5px;color:#e1e7ea;font-size:8px;font-weight:850;"
            "padding:0 15px 0 7px;text-align:left;}"
            "QPushButton:hover{background:#151e23;border-color:#7653a8;}"
            "QPushButton:disabled{color:#68747b;border-color:#273139;}"
        )
        self.ensurePolished()
        longest = max(
            self.fontMetrics().horizontalAdvance(label) for label in TAXONOMY
        )
        self.setFixedSize(max(90, longest + 24), 23)
        self.setCurrentText(category if category in TAXONOMY else "Lead")
        _base._compact_popup_rows(self)
        _base._prime_native_popup(self)


class CardRemoveButton(_base.CenteredRemoveButton):
    """Immediate red card removal control."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(20, 20)
        self.setToolTip("Remove this layer card")


class PreciseAddButton(QPushButton):
    """Green add button whose glyph is centered on the half-pixel grid."""

    def __init__(self, parent=None) -> None:
        super().__init__("", parent)
        self.setProperty("role", "slotAdd")
        self.setFixedSize(32, 32)
        self.setStyleSheet("padding:0")

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(
            QPen(
                QColor("#57d84e" if self.isEnabled() else "#667078"),
                1.8,
                Qt.SolidLine,
                Qt.RoundCap,
            )
        )
        # QRect.center() is integer based for an even-sized control and leaves
        # the glyph half a pixel high/left.  Use the actual visual centre.
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        painter.drawLine(QPointF(cx - 3.5, cy), QPointF(cx + 3.5, cy))
        painter.drawLine(QPointF(cx, cy - 3.5), QPointF(cx, cy + 3.5))


class SyncMixButton(QPushButton):
    """Second play control used to arm a layer in the synchronized mix."""

    def __init__(self, parent=None) -> None:
        super().__init__("", parent)
        self.setCheckable(True)
        self.setFixedSize(25, 25)
        self.setCursor(Qt.ArrowCursor)
        self.setStyleSheet(
            "QPushButton{background:#10171a;border:1px solid #40515a;"
            "border-radius:12px;"
            "padding:0;}"
            "QPushButton:hover{background:#152019;border-color:#57d84e;}"
            "QPushButton:checked{background:#17331a;border-color:#57d84e;"
            "color:#83f07b;}"
        )
        self.setToolTip("Play this layer in the synchronized mix")

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        active = self.isChecked()
        color = QColor("#83f07b" if active else "#72c978")
        painter.setPen(
            QPen(color, 1.35, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        )
        painter.setBrush(color)
        # Play triangle, shifted slightly left to reserve the sync badge.
        play = [QPointF(8.0, 8.0), QPointF(8.0, 16.0), QPointF(14.0, 12.0)]
        painter.drawPolygon(QPolygonF(play))
        painter.setBrush(Qt.NoBrush)
        # Two compact opposing arcs distinguish this from the solo Play button.
        painter.drawArc(13, 5, 7, 7, 35 * 16, 190 * 16)
        painter.drawLine(QPointF(18.6, 5.8), QPointF(20.2, 6.0))
        painter.drawLine(QPointF(18.6, 5.8), QPointF(19.2, 7.2))
        painter.drawArc(13, 13, 7, 7, 215 * 16, 190 * 16)
        painter.drawLine(QPointF(14.4, 19.2), QPointF(12.8, 19.0))
        painter.drawLine(QPointF(14.4, 19.2), QPointF(13.8, 17.8))


class PrototypeGenerateCard(_base.GenerateCard):
    """The generated audio card also acts as its own recipe slot."""

    categoryChoiceRequested = Signal(int, str)
    removeRequested = Signal(int)

    def __init__(self, data: dict, *, master: bool = False, parent=None) -> None:
        super().__init__(data, master=master, parent=parent)
        if self.master:
            return

        header = self.layout().itemAt(0).layout()
        header.removeWidget(self.name_label)
        self.name_label.hide()

        category = str(self.data.get("category") or "Lead")
        self.category_selector = CardCategorySelector(category, self)
        self.category_selector.setToolTip(
            "Choose the category this card will use on the next generation"
        )
        self.category_selector.currentTextChanged.connect(
            lambda text: self.categoryChoiceRequested.emit(
                self.slot_index, str(text)
            )
        )
        header.insertWidget(1, self.category_selector, 0, Qt.AlignVCenter)

        # Removing the original expanding name label also removed the spacer
        # which anchored Quick Extract's drag controls against the card's
        # right edge.  Restore that exact left/right structure so a card does
        # not jump when its placeholder becomes a generated result.
        header.insertStretch(max(0, header.indexOf(self.drag_handle)), 1)
        self.midi_handle = GenerateMidiDragHandle(self)
        header.insertWidget(
            max(0, header.indexOf(self.drag_handle)),
            self.midi_handle,
            0,
            Qt.AlignVCenter,
        )

        self.remove_button = CardRemoveButton(self)
        self.remove_button.clicked.connect(
            lambda _checked=False: self.removeRequested.emit(self.slot_index)
        )
        # KEEP and remove form a dedicated right-hand rail.  The drag handle
        # stays in the main card body until its final alignment is decided.
        header.removeWidget(self.lock_button)
        self.lock_button.setParent(self)
        self.lock_button.show()
        self.remove_button.setParent(self)
        self.remove_button.show()
        margins = self.layout().contentsMargins()
        self.layout().setContentsMargins(
            margins.left(), margins.top(), 39, margins.bottom()
        )
        self.setToolTip("")

    def setSlotIndex(self, slot_index: int) -> None:
        super().setSlotIndex(slot_index)

    def setMidiPath(self, path: str) -> None:
        self.midi_handle.set_midi_path(str(path or ""))

    def setMidiProcessing(self) -> None:
        self.midi_handle.set_processing()

    def setMixActive(self, active: bool) -> None:
        self.name_label.setMixActive(False)

    def mouseReleaseEvent(self, event) -> None:
        # KEEP is explicit in this proposal; clicking blank card space has no
        # hidden side effect.
        QFrame.mouseReleaseEvent(self, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        rail_width = 34
        rail_left = self.width() - rail_width
        half = self.height() // 2
        self.remove_button.move(
            rail_left + (rail_width - self.remove_button.width()) // 2,
            (half - self.remove_button.height()) // 2,
        )
        self.lock_button.move(
            rail_left + (rail_width - self.lock_button.width()) // 2,
            half + (self.height() - half - self.lock_button.height()) // 2,
        )

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#323a41"), 1.0))
        rail_left = self.width() - 34.5
        half_y = self.height() / 2.0
        painter.drawLine(
            QPointF(rail_left, 1.5),
            QPointF(rail_left, self.height() - 1.5),
        )
        painter.drawLine(
            QPointF(rail_left, half_y),
            QPointF(self.width() - 1.5, half_y),
        )


class RecipePlaceholderCard(QFrame):
    """Visible recipe slot before a layer has been generated for it."""

    categoryChoiceRequested = Signal(int, str)
    removeRequested = Signal(int)

    def __init__(self, slot_index: int, category: str, parent=None) -> None:
        super().__init__(parent)
        self.slot_index = int(slot_index)
        self.setProperty("role", "layerCard")
        self.setFixedHeight(78)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(7, 5, 39, 5)
        outer.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(4)
        play = LayerPlayButton()
        play.setProperty("role", "layerPlay")
        play.setFixedSize(25, 25)
        play.setStyleSheet("padding:0;border-radius:12px")
        play.setEnabled(False)
        header.addWidget(play)
        self.category_selector = CardCategorySelector(category, self)
        self.category_selector.currentTextChanged.connect(
            lambda text: self.categoryChoiceRequested.emit(
                self.slot_index, str(text)
            )
        )
        header.addWidget(self.category_selector)
        header.addStretch(1)

        self.keep_button = QPushButton("KEEP", self)
        self.keep_button.setProperty("role", "cardLock")
        self.keep_button.setFixedSize(28, 20)
        self.keep_button.setEnabled(False)

        self.remove_button = CardRemoveButton(self)
        self.remove_button.clicked.connect(
            lambda _checked=False: self.removeRequested.emit(self.slot_index)
        )
        grip = LineIcon("grip", "#69747b", 20, self)
        grip.setToolTip("Available after generation")
        header.addWidget(grip)
        outer.addLayout(header)

        empty_wave = GenerateWaveform([0.05] * 80)
        empty_wave.setEnabled(False)
        waveform_row = QHBoxLayout()
        waveform_row.setContentsMargins(0, 0, 0, 0)
        waveform_row.setSpacing(3)
        waveform_row.addWidget(empty_wave, 1)
        self.octave_selector = _base.OctaveSelector(self)
        self.octave_selector.setFixedSize(46, 18)
        self.octave_selector.setStyleSheet(
            "QPushButton{background:#151b1f;border:1px solid #3b454b;"
            "border-radius:4px;color:#6c767c;font-size:7px;font-weight:900;"
            "padding:0 9px 0 3px;text-align:left;}"
        )
        self.octave_selector.setCurrentText("0")
        self.octave_selector.setEnabled(False)
        waveform_row.addWidget(self.octave_selector, 0, Qt.AlignVCenter)
        self.volume_button = LayerVolumeButton(self)
        self.volume_button.setEnabled(False)
        waveform_row.addWidget(self.volume_button, 0, Qt.AlignVCenter)
        outer.addLayout(waveform_row)

        metadata = QHBoxLayout()
        metadata.setSpacing(4)
        hint = QLabel("Waiting for generation")
        hint.setProperty("role", "cardMeta")
        metadata.addWidget(hint)
        metadata.addStretch(1)
        self.alt_key_button = QPushButton("ALT KEY", self)
        self.alt_key_button.setProperty("role", "cardAltKey")
        self.alt_key_button.setFixedSize(34, 15)
        self.alt_key_button.setStyleSheet("font-size:6px;padding:0")
        self.alt_key_button.setEnabled(False)
        metadata.addWidget(self.alt_key_button, 0, Qt.AlignVCenter)
        outer.addLayout(metadata)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        rail_width = 34
        rail_left = self.width() - rail_width
        half = self.height() // 2
        self.remove_button.move(
            rail_left + (rail_width - self.remove_button.width()) // 2,
            (half - self.remove_button.height()) // 2,
        )
        self.keep_button.move(
            rail_left + (rail_width - self.keep_button.width()) // 2,
            half + (self.height() - half - self.keep_button.height()) // 2,
        )

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#323a41"), 1.0))
        rail_left = self.width() - 34.5
        half_y = self.height() / 2.0
        painter.drawLine(
            QPointF(rail_left, 1.5),
            QPointF(rail_left, self.height() - 1.5),
        )
        painter.drawLine(
            QPointF(rail_left, half_y),
            QPointF(self.width() - 1.5, half_y),
        )


class AddRecipeCard(QFrame):
    """A full-card add affordance that follows the recipe in reading order."""

    clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("role", "layerCard")
        self.setFixedHeight(78)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.addStretch(1)
        self.button = PreciseAddButton(self)
        self.button.setToolTip("Add another layer card")
        self.button.clicked.connect(self.clicked.emit)
        layout.addWidget(self.button, 0, Qt.AlignHCenter)
        label = QLabel("ADD LAYER")
        label.setProperty("role", "caps")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)
        layout.addStretch(1)


class SyncTransportButton(QPushButton):
    """Global synchronized transport with explicit green/red action states."""

    def __init__(self, parent=None) -> None:
        super().__init__("SYNC PLAY", parent)
        self.setFixedSize(66, 22)
        self.setCursor(Qt.ArrowCursor)
        self.setEnabled(False)
        self.setSyncPlaying(False)
        self.setToolTip("Play every generated layer from the same starting point")

    def setSyncPlaying(self, playing: bool) -> None:
        playing = bool(playing)
        self.setText("SYNC STOP" if playing else "SYNC PLAY")
        if playing:
            self.setStyleSheet(
                "QPushButton{background:#35171b;border:1px solid #a93e47;"
                "border-radius:5px;color:#ff7a82;font-size:7px;"
                "font-weight:900;padding:0;}"
                "QPushButton:hover{background:#481a20;border-color:#ef5963;}"
            )
        else:
            self.setStyleSheet(
                "QPushButton{background:#102116;border:1px solid #3b7a42;"
                "border-radius:5px;color:#69dc72;font-size:7px;"
                "font-weight:900;padding:0;}"
                "QPushButton:hover{background:#17331a;border-color:#57d84e;}"
                "QPushButton:disabled{background:#0c1114;border-color:#273138;"
                "color:#59646b;}"
            )


# Base GeneratePage methods resolve this global in their original module.
# Replacing it here preserves the proven controller wiring while changing only
# the card presentation.
_base.GenerateCard = PrototypeGenerateCard


class GeneratePage(_base.GeneratePage):
    """Functional 1.9 Generate page with cards replacing Recipe Slots."""

    midiBatchRequested = Signal(object)
    midiLayerRequested = Signal(object)

    def __init__(self, parent=None) -> None:
        self._sync_mode = False
        super().__init__(parent)
        for description in self.findChildren(QLabel):
            if description.text() == (
                "Choose a recipe and preview the generated loop with "
                "synchronized layer cards."
            ):
                description.setText(
                    "Generate a new loop from your layer library."
                )
                # Generate has enough breathing room for a clearer subtitle;
                # keep Layer Library's shared compact header untouched.
                description.setStyleSheet(
                    "color:#a7b2b8;font-size:10px;"
                )
                self.generate_description = description

    def _library_summary_widget(self) -> QFrame:
        """One compact status line plus one non-wrapping category line."""

        summary = QFrame()
        summary.setProperty("role", "pathBox")
        outer = QVBoxLayout(summary)
        outer.setContentsMargins(10, 4, 10, 4)
        outer.setSpacing(2)

        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        status_row.addWidget(LineIcon("folder", RED, 18))
        self.scan_status = MiddleElideLabel("No folder selected")
        self.scan_status.setProperty("role", "statusDetail")
        status_row.addWidget(self.scan_status, 1)

        self.library_total_value = QLabel("")
        self.library_total_value.setStyleSheet(
            f"color:{GREEN};font-size:8px;font-weight:900"
        )
        self.library_total_value.setVisible(False)
        status_row.addWidget(self.library_total_value)
        self.library_total_unit = QLabel("")
        self.library_total_unit.setVisible(False)
        status_row.addWidget(self.library_total_unit)

        # Kept as a hidden compatibility attribute for the base page.  The
        # compact summary deliberately displays only Loaded and Uncertain;
        # Safe is redundant with those two values.
        self.library_safe_badge = QLabel("", summary)
        self.library_safe_badge.setStyleSheet(
            f"color:{GREEN};font-size:8px;font-weight:900"
        )
        self.library_safe_badge.setVisible(False)
        self.library_review_badge = QLabel("")
        self.library_review_badge.setStyleSheet(
            f"color:{ORANGE};font-size:8px;font-weight:900"
        )
        self.library_review_badge.setVisible(False)
        status_row.addWidget(self.library_review_badge)

        self.scan_button = QPushButton("SCAN LIBRARY")
        self.scan_button.setProperty("accent", "red")
        self.scan_button.setFixedSize(92, 23)
        self.scan_button.setStyleSheet("font-size:7px;padding:0")
        self.scan_button.setEnabled(False)
        self.scan_button.clicked.connect(self._request_scan)
        status_row.addWidget(self.scan_button)
        outer.addLayout(status_row)

        self.coverage_flow_host = QWidget()
        self.coverage_flow_host.setFixedHeight(15)
        self.coverage_flow = QHBoxLayout(self.coverage_flow_host)
        self.coverage_flow.setContentsMargins(24, 0, 0, 0)
        self.coverage_flow.setSpacing(5)
        self.library_category_tokens: list[QLabel] = []
        outer.addWidget(self.coverage_flow_host)

        self.scan_progress = _base.QProgressBar()
        self.scan_progress.setRange(0, 100)
        self.scan_progress.setValue(0)
        self.scan_progress.setFixedHeight(3)
        outer.addWidget(self.scan_progress)
        return summary

    def _add_library_category_token(self, text: str) -> QLabel:
        token = QLabel(str(text))
        token.setStyleSheet(
            "color:#a7b2b8;font-size:7px;font-weight:750"
        )
        token.setFixedHeight(11)
        token.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.coverage_flow.addWidget(token)
        self.library_category_tokens.append(token)
        return token

    def _set_empty_library_coverage(self) -> None:
        self.library_total_value.clear()
        self.library_total_value.setVisible(False)
        self.library_total_unit.clear()
        self.library_total_unit.setVisible(False)
        self.library_safe_badge.clear()
        self.library_safe_badge.setVisible(False)
        self.library_review_badge.clear()
        self.library_review_badge.setVisible(False)
        self._clear_library_category_tokens()
        self._add_library_category_token(
            "SCAN A LIBRARY TO SEE CATEGORY COVERAGE"
        )
        self.coverage_flow.invalidate()

    @Slot(int, dict, int)
    def set_library_summary(
        self, total: int, counts: dict, review_count: int
    ) -> None:
        total = max(0, int(total))
        folder_name = (
            Path(self.library_path).name if self.library_path else "LIBRARY"
        )
        self.scan_status.setFullText(f"{folder_name} · LIBRARY READY")
        self.library_total_value.setText(f"{total} LOADED")
        self.library_total_value.setVisible(True)
        self.library_safe_badge.clear()
        self.library_safe_badge.setVisible(False)
        # review_count is the category-review count, not key uncertainty.
        # The real key figures arrive in set_scan_busy from the controller.
        self.library_review_badge.clear()
        self.library_review_badge.setVisible(False)

        self._clear_library_category_tokens()
        for label in TAXONOMY:
            count = int(counts.get(label, 0))
            if count > 0:
                self._add_library_category_token(f"{label} {count}")
        self.coverage_flow.addStretch(1)
        self.coverage_flow.invalidate()

        self._library_ready = total > max(0, int(review_count))
        self._loaded_library_path = (
            str(Path(self.library_path).resolve())
            if self._library_ready and self.library_path
            else ""
        )
        self.generate_button.setEnabled(
            self._library_ready and not self._generation_busy
        )
        self.generation_status.setFullText(
            "Library ready. Choose categories, BPM and target key."
        )

    @Slot(bool, int, str)
    def set_scan_busy(
        self, busy: bool, progress: int = 0, status: str = ""
    ) -> None:
        """Bind the compact badges to the controller's real key counts."""

        super().set_scan_busy(busy, progress, status)
        match = re.search(
            r"(?P<safe>\d+)\s+safe\s*/\s*(?P<uncertain>\d+)\s+uncertain",
            str(status),
            flags=re.IGNORECASE,
        )
        if busy or match is None:
            return
        uncertain = int(match.group("uncertain"))
        self.library_review_badge.setText(f"{uncertain} UNCERTAIN")
        self.library_review_badge.setVisible(True)
        folder_name = (
            Path(self.library_path).name if self.library_path else "LIBRARY"
        )
        self.scan_status.setFullText(f"{folder_name} · LIBRARY READY")

    def _compact_controls_widget(self) -> QWidget:
        controls = QWidget()
        controls.setFixedHeight(35)
        row = QHBoxLayout(controls)
        row.setContentsMargins(0, 1, 0, 3)
        row.setSpacing(6)

        row.addStretch(1)

        for category in ("Bass", "Chords", "Lead", "Counter"):
            self._add_slot(category)

        self.target_bpm_label = _base._caps("TARGET BPM")
        row.addWidget(self.target_bpm_label, 0, Qt.AlignVCenter)
        self.target_bpm = QLineEdit("140")
        self.target_bpm.setProperty("role", "targetValue")
        self.target_bpm.setAlignment(Qt.AlignCenter)
        self.target_bpm.setMaxLength(3)
        from PySide6.QtGui import QIntValidator

        self.target_bpm.setValidator(QIntValidator(40, 300, self.target_bpm))
        self.target_bpm.setFixedSize(46, 25)
        self.target_bpm.setStyleSheet("font-size:8px;padding:0 4px")
        row.addWidget(self.target_bpm, 0, Qt.AlignVCenter)
        row.addSpacing(8)

        self.target_key_label = _base._caps("TARGET KEY")
        row.addWidget(self.target_key_label, 0, Qt.AlignVCenter)
        self.target_key = _base.CompactKeySelector(
            RELATIVE_KEY_FAMILIES,
            accent=ORANGE,
            exact_popup_width=True,
            show_check=False,
        )
        self.target_key.setCurrentText("C major / A minor")
        self.target_key.setStyleSheet("font-size:8px;padding:0 15px 0 6px")
        self.target_key.ensurePolished()
        longest = max(
            self.target_key.fontMetrics().horizontalAdvance(key)
            for key in RELATIVE_KEY_FAMILIES
        )
        _base._compact_popup_rows(self.target_key)
        self.target_key.setFixedSize(
            max(longest + 24, self.target_key._popup.sizeHint().width()), 25
        )
        _base._prime_native_popup(self.target_key)
        row.addWidget(self.target_key, 0, Qt.AlignVCenter)

        self.preview_seed_button = QPushButton("PREVIOUS SEED")
        self.preview_seed_button.setProperty("accent", "orange")
        self.preview_seed_button.setFixedSize(90, 25)
        self.preview_seed_button.setStyleSheet("font-size:7px;padding:0")
        self.preview_seed_button.setEnabled(False)
        self.preview_seed_button.clicked.connect(self._request_preview_seed)
        row.addWidget(self.preview_seed_button, 0, Qt.AlignVCenter)

        self.generate_button = QPushButton("GENERATE")
        self.generate_button.setProperty("role", "convertAction")
        self.generate_button.setFixedSize(90, 25)
        self.generate_button.setStyleSheet("font-size:7px;padding:0")
        self.generate_button.setEnabled(False)
        self.generate_button.clicked.connect(self._request_generation)
        row.addWidget(self.generate_button, 0, Qt.AlignVCenter)
        return controls

    def _layers_bar_widget(self) -> QWidget:
        self.layers_bar = QWidget()
        self.layers_bar.setFixedHeight(26)
        row = QHBoxLayout(self.layers_bar)
        # Seven logical pixels on the right matches the inner edge of the
        # right-most card and keeps both controls visually anchored to it.
        row.setContentsMargins(0, 0, 7, 0)
        row.setSpacing(6)
        self.layers_label = _base._caps(
            "SELECT YOUR LAYER TYPES, THEN GENERATE YOUR LOOP"
        )
        row.addWidget(self.layers_label)
        row.addStretch(1)
        self.all_layers_transport = SyncTransportButton(self.layers_bar)
        self.all_layers_transport.clicked.connect(self._toggle_all_layers)
        row.addWidget(self.all_layers_transport, 0, Qt.AlignVCenter)
        self.drag_all = MultiFileDragHandle(parent=self.layers_bar)
        self.drag_all.setFixedSize(78, 22)
        self.drag_all.layout().setContentsMargins(7, 0, 3, 0)
        self.drag_all.layout().setSpacing(3)
        drag_label = self.drag_all.findChild(QLabel)
        if drag_label is not None:
            drag_label.setStyleSheet("font-size:7px;font-weight:900")
        row.addWidget(self.drag_all, 0, Qt.AlignVCenter)
        return self.layers_bar

    def _generation_footer_widget(self) -> QWidget:
        self.generation_footer = QWidget()
        self.generation_footer.setFixedHeight(32)
        history = QHBoxLayout(self.generation_footer)
        history.setContentsMargins(7, 2, 0, 1)
        history.setSpacing(7)
        history.addWidget(LineIcon("drive", "#9da5ac", 20))
        self.generation_storage_label = QLabel("0 generations · 0 o")
        self.generation_storage_label.setProperty("role", "storage")
        history.addWidget(self.generation_storage_label)
        history.addSpacing(18)
        history.addWidget(LineIcon("music_note", PURPLE, 17))
        self.generation_status = MiddleElideLabel(
            "Ready for a layer library."
        )
        self.generation_status.setProperty("role", "statusDetail")
        history.addWidget(self.generation_status, 1)
        self.open_output = QPushButton("OPEN OUTPUT FOLDER")
        self.open_output.setProperty("accent", "purple")
        self.open_output.clicked.connect(self.openOutputRequested.emit)
        history.addWidget(self.open_output)
        self.manage_button = QPushButton("MANAGE")
        self.manage_button.setProperty("accent", "purple")
        self.manage_button.clicked.connect(self.manageRequested.emit)
        history.addWidget(self.manage_button)
        return self.generation_footer

    def _add_slot(self, category: str) -> None:
        slot = _base.CompactRecipeSlotWidget(category, self)
        slot.hide()
        slot.selector.currentTextChanged.connect(
            lambda _text, item=slot: self._slot_category_changed(item)
        )
        self._slot_widgets.append(slot)
        self._slot_combos.append(slot.selector)
        if hasattr(self, "layers_grid"):
            if self._has_generation:
                self._append_missing_placeholders()
            else:
                self._show_empty_results(
                    "Choose categories, then generate the first loop."
                )

    def _refresh_slot_strip(self, *args, **kwargs) -> None:
        # Slots are logical only in this prototype; their visible expression is
        # the card itself.
        self._sync_recipe_slot_states()

    def _remove_slot(self, slot=None) -> None:
        if len(self._slot_widgets) <= 1:
            self.generation_status.setFullText(
                "Keep at least one layer card in the recipe."
            )
            return
        if isinstance(slot, int):
            index = int(slot)
            if not 0 <= index < len(self._slot_widgets):
                return
            slot = self._slot_widgets[index]
        elif slot is None:
            slot = self._slot_widgets[-1]
            index = len(self._slot_widgets) - 1
        else:
            try:
                index = self._slot_widgets.index(slot)
            except ValueError:
                return

        card = next(
            (item for item in self._stem_cards if item.recipe_slot is slot),
            None,
        )
        if card is not None and card.locked:
            card.setLocked(False, emit=True)

        self._slot_widgets.pop(index)
        self._slot_combos.pop(index)
        slot.hide()
        slot.deleteLater()

        if card is not None:
            if card.path in self._mix_paths:
                self._mix_paths.discard(card.path)
            if self._solo_path == card.path:
                self._solo_path = None
            if card in self._stem_cards:
                self._stem_cards.remove(card)
            if card in self._cards:
                self._cards.remove(card)
            self.layers_grid.removeWidget(card)
            card.hide()
            card.deleteLater()

        for existing in self._stem_cards:
            if existing.recipe_slot in self._slot_widgets:
                existing.setSlotIndex(
                    self._slot_widgets.index(existing.recipe_slot)
                )
        if self._has_generation:
            self._reflow_current_cards()
            self._mark_recipe_changed()
        else:
            self._show_empty_results(
                "Choose categories, then generate the first loop."
            )

    def _slot_category_changed(self, slot) -> None:
        try:
            index = self._slot_widgets.index(slot)
        except ValueError:
            return
        card = next(
            (item for item in self._stem_cards if item.recipe_slot is slot),
            None,
        )
        if card is not None and card.locked:
            card.setLocked(False, emit=True)
        if card is not None and hasattr(card, "category_selector"):
            blocked = card.category_selector.blockSignals(True)
            card.category_selector.setCurrentText(slot.selector.currentText())
            card.category_selector.blockSignals(blocked)
        if self._has_generation:
            self._mark_recipe_changed()

    @Slot(int, str)
    def _card_category_changed(self, slot_index: int, category: str) -> None:
        if not 0 <= int(slot_index) < len(self._slot_widgets):
            return
        slot = self._slot_widgets[int(slot_index)]
        slot.selector.setCurrentText(str(category))
        self._slot_category_changed(slot)

    @Slot(int)
    def _card_remove_requested(self, slot_index: int) -> None:
        self._remove_slot(int(slot_index))

    def _mark_recipe_changed(self) -> None:
        self.drag_all.setEnabled(False)
        self.generation_status.setFullText(
            "Recipe changed · Generate Again to refresh the hidden full loop."
        )

    def _clear_results(self) -> None:
        self._sync_mode = False
        super()._clear_results()

    def _show_empty_results(self, text: str) -> None:
        self._clear_results()
        for index, slot in enumerate(self._slot_widgets):
            card = RecipePlaceholderCard(
                index, slot.selector.currentText(), self.layers_content
            )
            card.categoryChoiceRequested.connect(self._card_category_changed)
            card.removeRequested.connect(self._card_remove_requested)
            self.layers_grid.addWidget(card, index // 3, index % 3)
        self._add_plus_card(len(self._slot_widgets))
        rows = max(1, math.ceil((len(self._slot_widgets) + 1) / 3))
        self.layers_content.setMinimumHeight(rows * 84 + 6)
        if hasattr(self, "generation_status") and text:
            self.generation_status.setFullText(text)

    def _add_plus_card(self, index: int) -> None:
        self.plus_card = AddRecipeCard(self.layers_content)
        self.plus_card.clicked.connect(lambda: self._add_slot("Lead"))
        self.add_slot_button = self.plus_card.button
        self.layers_grid.addWidget(
            self.plus_card, int(index) // 3, int(index) % 3
        )

    def _append_missing_placeholders(self) -> None:
        represented = {
            card.recipe_slot
            for card in self._stem_cards
            if card.recipe_slot in self._slot_widgets
        }
        for index, slot in enumerate(self._slot_widgets):
            if slot in represented:
                continue
            placeholder = RecipePlaceholderCard(
                index, slot.selector.currentText(), self.layers_content
            )
            placeholder.categoryChoiceRequested.connect(
                self._card_category_changed
            )
            placeholder.removeRequested.connect(self._card_remove_requested)
            self.layers_grid.addWidget(
                placeholder, index // 3, index % 3
            )
        self._reflow_current_cards()
        self._mark_recipe_changed()

    def _reflow_current_cards(self) -> None:
        widgets = []
        while self.layers_grid.count():
            item = self.layers_grid.takeAt(0)
            widget = item.widget()
            if widget is None:
                continue
            if isinstance(widget, AddRecipeCard):
                # Taking a widget out of a layout does not hide it.  Without
                # this explicit cleanup, every recipe edit leaves an orphaned
                # visible plus card behind the newly created one.
                widget.hide()
                widget.deleteLater()
                continue
            widgets.append(widget)
        ordered = []
        for index, slot in enumerate(self._slot_widgets):
            match = next(
                (
                    widget
                    for widget in widgets
                    if getattr(widget, "recipe_slot", None) is slot
                    or (
                        isinstance(widget, RecipePlaceholderCard)
                        and widget.slot_index == index
                    )
                ),
                None,
            )
            if match is None:
                match = RecipePlaceholderCard(
                    index, slot.selector.currentText(), self.layers_content
                )
                match.categoryChoiceRequested.connect(
                    self._card_category_changed
                )
                match.removeRequested.connect(self._card_remove_requested)
            if isinstance(match, RecipePlaceholderCard):
                match.slot_index = index
            ordered.append(match)
        for index, widget in enumerate(ordered):
            self.layers_grid.addWidget(widget, index // 3, index % 3)
        for widget in widgets:
            if widget not in ordered:
                widget.hide()
                widget.deleteLater()
        self._add_plus_card(len(ordered))
        rows = max(1, math.ceil((len(ordered) + 1) / 3))
        self.layers_content.setMinimumHeight(rows * 84 + 6)
        self._layer_player.setLayers(card.path for card in self._stem_cards)
        paths = ([self._master_path] if self._master_path else []) + [
            card.path for card in self._stem_cards
        ]
        self.drag_all.set_paths(paths)

    def _wire_card(self, card) -> None:
        super()._wire_card(card)
        if isinstance(card, PrototypeGenerateCard):
            card.categoryChoiceRequested.connect(self._card_category_changed)
            card.removeRequested.connect(self._card_remove_requested)

    @Slot(dict, list)
    def set_generation_results(self, master: dict, stems: list[dict]) -> None:
        self._sync_mode = False
        super().set_generation_results(master, stems)
        self.drag_all.setEnabled(True)
        self._add_plus_card(len(self._stem_cards))
        rows = max(1, math.ceil((len(self._stem_cards) + 1) / 3))
        self.layers_content.setMinimumHeight(rows * 84 + 6)
        self.all_layers_transport.setSyncPlaying(False)
        requests = tuple(
            {
                "path": card.path,
                "bpm": int(float(card.data.get("bpm") or 140)),
                "identity": card.identity,
            }
            for card in self._stem_cards
        )
        if requests:
            self.midiBatchRequested.emit(requests)

    @Slot(str, str)
    def set_layer_midi_path(self, audio_path: str, midi_path: str) -> None:
        audio_path = str(audio_path)
        card = next(
            (item for item in self._stem_cards if item.path == audio_path),
            None,
        )
        if card is not None and hasattr(card, "setMidiPath"):
            card.setMidiPath(str(midi_path or ""))

    @Slot()
    def set_all_midi_unavailable(self) -> None:
        for card in self._stem_cards:
            if hasattr(card, "setMidiPath"):
                card.setMidiPath("")

    @Slot(dict, object)
    def update_generation_layer(self, stem: dict, pcm=None) -> bool:
        updated = bool(super().update_generation_layer(stem, pcm))
        if not updated:
            return False
        identity = str(stem.get("identity") or "")
        card = next(
            (item for item in self._stem_cards if item.identity == identity),
            None,
        )
        if card is not None:
            card.setMidiProcessing()
            self.midiLayerRequested.emit(
                {
                    "path": card.path,
                    "bpm": int(float(card.data.get("bpm") or 140)),
                    "identity": card.identity,
                }
            )
        return True

    @Slot(tuple)
    def _active_layer_paths_changed(self, paths: tuple) -> None:
        active = set(paths)
        self.all_layers_transport.setSyncPlaying(self._sync_mode)
        for card in self._cards:
            card_is_playing = bool(
                card.path in active
                and (
                    self._sync_mode
                    or card.path == self._solo_path
                )
            )
            card.setPlaybackState(
                "playing" if card_is_playing else "stopped"
            )
            card.setMixActive(False)
            if card.path not in active:
                card.waveform.setProgress(0.0)

    @Slot()
    def _toggle_all_layers(self) -> None:
        if self._sync_mode:
            self._sync_mode = False
            self._mix_paths.clear()
            self._solo_path = None
            self._layer_player.stopAll()
            self.all_layers_transport.setSyncPlaying(False)
            return

        self._sync_mode = True
        self._solo_path = None
        self._mix_paths = {card.path for card in self._stem_cards}
        if not self._layer_player.playAll():
            self._sync_mode = False
            self._mix_paths.clear()
        self.all_layers_transport.setSyncPlaying(self._sync_mode)

    @Slot(str)
    def _play_path(self, path: str) -> None:
        path = str(path)
        if not self._sync_mode:
            super()._play_path(path)
            return

        device = getattr(self._layer_player, "_device", None)
        if device is None or path not in set(device.allPaths()):
            return
        active = path in set(device.activePaths())
        device.setActive(path, not active)
        if active:
            self._mix_paths.discard(path)
        else:
            self._mix_paths.add(path)
        active_paths = device.activePaths()
        self._layer_player.activePathsChanged.emit(active_paths)
        # Even when every layer is temporarily paused, the shared audio sink
        # keeps reading silence so its clock continues.  Re-enabled layers
        # therefore rejoin at the exact current synchronized position.
        if active_paths and not self._layer_player.isPlaying():
            self._layer_player._start()

    @Slot(str)
    def reset_generation_results(self, text: str) -> None:
        self._sync_mode = False
        super().reset_generation_results(text)
        self.all_layers_transport.setSyncPlaying(False)

    def generation_request(self) -> dict:
        request = super().generation_request()
        return request


GenerateCard = PrototypeGenerateCard

__all__ = [
    "EXACT_KEYS",
    "GenerateCard",
    "GeneratePage",
    "GeneratePrototypeWindow",
    "GenerateWaveform",
    "RELATIVE_KEY_FAMILIES",
]
