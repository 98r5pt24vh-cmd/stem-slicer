"""Native PySide6 port of the validated Stem Slicer 1.6B HTML prototype.

The HTML prototype remains the visual specification only.  This module builds
the same fixed 1024 x 691 working surface with native Qt widgets and reuses the
validated audio workers from :mod:`functional_core`.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRect, QRectF, QThread, QTimer, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QActionGroup, QColor, QDrag, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsProxyWidget,
    QGraphicsOpacityEffect,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from filename_templates import TOKENS
from functional_core import (
    APP_NAME,
    APP_VERSION,
    TARGET_KEYS,
    canonical_loop_bpm,
    FileDragHandle,
    LayerCard,
    LineIcon,
    MainWindow as FunctionalMainWindow,
    QuickConvertManagerDialog,
    QuickExtractManagerDialog,
    Switch,
    button,
    fit_icon_button_width,
    icon_button,
    image,
    label,
    panel,
    resource_path,
)
from key_detection import format_camelot
from storage import format_decimal_size
from widgets import StudioRoot, TokenStrip
from stem_workflow import BatchWorkflowWorker, QuickConvertWorkflowWorker, QuickExtractWorkflowWorker


BASE_WIDTH = 1024
BASE_HEIGHT = 691

RED = "#ef5963"
RED_DARK = "#35171b"
PURPLE = "#b58ae5"
PURPLE_DARK = "#2c203c"
ORANGE = "#f0ab45"
ORANGE_DARK = "#4d3211"
CYAN = "#09baf2"
GREEN = "#31d26f"
TEXT = "#eef4f7"
MUTED = "#87959e"


def validated_stylesheet() -> str:
    """QSS translation of ``ui_prototype_1_6/index.html``."""
    return f"""
    * {{
        font-family: "SF Pro Display", "Helvetica Neue", sans-serif;
        color: {TEXT};
        outline: none;
    }}
    QMainWindow, QWidget#ValidatedCanvas {{ background: #070b0e; }}
    QGraphicsView {{ background: #070b0e; border: none; }}
    QFrame[role="topBar"] {{ background: #070c0f; border: none; border-bottom: 1px solid #17242c; }}
    QFrame[role="tabsBar"] {{ background: #080d10; border: none; border-bottom: 1px solid #17242c; }}
    QFrame[role="section"] {{ background: #0c1216; border: 1px solid #26343d; border-radius: 8px; }}
    QFrame[role="section"][accent="red"] {{ border-top-color: #b93d45; }}
    QFrame[role="section"][accent="purple"] {{ border-top-color: #7653a8; }}
    QFrame[role="section"][accent="orange"] {{ border-top-color: #a9742c; }}
    QFrame[role="metric"], QFrame[role="inset"], QFrame[role="pathBox"],
    QFrame[role="resultLine"], QFrame[role="operation"] {{
        background: #080d10; border: 1px solid #26343d; border-radius: 6px;
    }}
    QFrame[role="operation"][accent="red"] {{ border-left: 2px solid #b93d45; }}
    QFrame[role="operation"][accent="purple"] {{ border-left: 2px solid #8e68c5; }}
    QFrame[role="operation"][accent="orange"] {{ border-left: 2px solid #c48231; }}
    QFrame[role="operationSettings"] {{ background: #080d10; border: none; border-top: 1px solid #1d2b32; }}
    QLabel[role="sectionTitle"] {{ font-size: 13px; font-weight: 800; letter-spacing: 1px; }}
    QLabel[role="sectionDescription"] {{ color: {MUTED}; font-size: 9px; }}
    QLabel[role="operationTitle"] {{ font-size: 12px; font-weight: 800; }}
    QLabel[role="operationDescription"] {{ color: #7f8d95; font-size: 9px; }}
    QLabel[role="caps"] {{ color: #8d9aa2; font-size: 8px; font-weight: 800; letter-spacing: 1px; }}
    QLabel[role="metricTitle"] {{ color: {PURPLE}; font-size: 9px; font-weight: 800; letter-spacing: 1px; }}
    QLabel[role="metricValue"] {{ color: {TEXT}; font-size: 20px; font-weight: 750; }}
    QLabel[role="metricSub"] {{ color: #bac5ca; font-size: 9px; }}
    QLabel[role="modeName"] {{ color: {TEXT}; font-size: 9px; font-weight: 700; }}
    QLabel[role="modeDegree"] {{ color: #bac5ca; font-size: 8px; }}
    QLabel[role="path"] {{ color: #bcc7cc; font-size: 10px; }}
    QLabel[role="statusFile"] {{ color: #d9e2e6; font-size: 10px; font-weight: 700; }}
    QLabel[role="statusDetail"] {{ color: #a7b2b8; font-size: 9px; }}
    QLabel[role="storage"] {{ color: #d1d9dd; font-size: 10px; font-weight: 700; }}
    QLabel[role="preview"] {{ background: #171222; border: 1px solid #7653a8; border-radius: 4px; color: #dcc2ff; padding: 0 9px; font-size: 8px; font-weight: 750; }}
    QLabel[role="counter"] {{ color: #9ba8af; font-family: "SF Mono"; font-size: 9px; font-weight: 700; }}
    QLabel[role="ready"] {{ color: #cdd7dc; font-size: 10px; font-weight: 700; }}
    QPushButton {{
        background: #0c1419; border: 1px solid #30414b; border-radius: 5px;
        color: #dbe4e8; padding: 5px 9px; font-size: 8px; font-weight: 800;
    }}
    QPushButton:hover {{ background: #151e23; border-color: #4b606b; }}
    QPushButton:pressed {{ background: #080d10; }}
    QPushButton[accent="red"] {{ border-color: #b93d45; background: {RED_DARK}; color: #ffb5ba; }}
    QPushButton[accent="purple"] {{ border-color: #7653a8; background: {PURPLE_DARK}; color: #dcc2ff; }}
    QPushButton[accent="orange"] {{ border-color: #d89432; background: {ORANGE_DARK}; color: #ffdca5; }}
    QPushButton[role="destinationChoice"] {{
        background: #0c1419; border-color: #30414b; color: #aab5bb;
    }}
    QPushButton[role="destinationChoice"][active="true"] {{
        border-color: #7653a8; background: {PURPLE_DARK}; color: #dcc2ff;
    }}
    QPushButton[role="destinationChoice"]:disabled {{
        background: #0a1013; border-color: #253139; color: #59656c;
    }}
    QPushButton[role="destinationChoice"][active="true"]:disabled {{
        background: #0a1013; border-color: #253139; color: #59656c;
    }}
    QPushButton[role="segment"] {{ border-radius: 0; padding: 4px 8px; color: #87959e; }}
    QPushButton[role="segment"][position="first"] {{ border-top-left-radius: 5px; border-bottom-left-radius: 5px; }}
    QPushButton[role="segment"][position="last"] {{ border-top-right-radius: 5px; border-bottom-right-radius: 5px; }}
    QPushButton[role="segment"][active="true"] {{ border-color: #7653a8; background: {PURPLE_DARK}; color: #dcc2ff; }}
    QPushButton[role="process"] {{
        background: #35171b; border: 1px solid #b93d45; color: #ffd5d8;
        font-size: 11px; font-weight: 850; border-radius: 7px;
    }}
    QPushButton[role="process"]:disabled {{ background: #17191c; border-color: #343b40; color: #667078; }}
    QLineEdit, QComboBox {{
        background: #0d151a; border: 1px solid #2b3b44; border-radius: 5px;
        color: #e3e9ec; padding: 5px 7px; font-size: 9px;
    }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox QAbstractItemView {{ background: #0d151a; color: #e3e9ec; selection-background-color: #2c203c; }}
    QPushButton[role="scaleSelector"] {{
        background: #0d151a; border: 1px solid #2b3b44; border-radius: 5px;
        color: #e3e9ec; padding: 5px 17px 5px 7px; font-size: 9px; font-weight: 800;
    }}
    QPushButton[role="scaleSelector"]:hover {{ background: #151e23; border-color: #4b606b; }}
    QPushButton[role="choiceSelector"] {{
        background: #0d151a; border: 1px solid #2b3b44; border-radius: 5px;
        color: #e3e9ec; padding: 5px 18px 5px 7px; font-size: 10px;
        text-align: left;
    }}
    QPushButton[role="choiceSelector"]:hover {{ background: #151e23; border-color: #4b606b; }}
    QPushButton[role="choiceSelector"]:disabled {{ background: #0a1013; border-color: #253139; color: #59656c; }}
    QProgressBar {{ background: #071015; border: 1px solid #263a45; border-radius: 4px; color: transparent; height: 8px; }}
    QProgressBar::chunk {{ background: #ef5963; }}
    QScrollArea[role="layers"], QScrollArea[role="layers"] > QWidget > QWidget {{ background: #0e1215; border: 1px solid #30373d; border-radius: 6px; }}
    QScrollArea[role="layers"] > QWidget > QWidget {{ border: none; }}
    QFrame[role="layerCard"] {{ background: #12171a; border: 1px solid #323a41; border-radius: 6px; }}
    QLabel[role="layerName"] {{ color: #e0e6e9; font-size: 9px; font-weight: 750; }}
    QLabel[role="cardMeta"] {{ color: #87959e; font-family: "SF Mono"; font-size: 7px; }}
    QPushButton[role="layerPlay"] {{ padding: 0; border-radius: 12px; color: #57d84e; font-size: 10px; }}
    QScrollBar:vertical {{ background: #0d1012; width: 7px; margin: 3px 1px; }}
    QScrollBar::handle:vertical {{ background: #454c53; border-radius: 3px; min-height: 24px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QDialog[role="managerDialog"] {{ background: #101417; }}
    QScrollArea[role="managerList"], QScrollArea[role="managerList"] > QWidget > QWidget {{
        background: #0d1114; border: 1px solid #2f373d; border-radius: 6px;
    }}
    QLabel[role="pageTitle"] {{ color: #eef0f2; font-size: 17px; font-weight: 800; letter-spacing: 1px; }}
    QFrame[role="managerRow"] {{ background: #151a1e; border: 1px solid #343c43; border-radius: 6px; }}
    QLabel[role="managerName"] {{ color: #eef0f2; font-size: 12px; font-weight: 750; }}
    QLabel[role="muted"], QLabel[role="mutedSmall"] {{ color: #929aa1; font-size: 10px; }}
    QPushButton[role="danger"] {{ color: #ff796e; border-color: #71342f; background: #251513; }}
    """


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


class V16Toggle(QFrame):
    toggled = Signal(bool)

    def __init__(self, checked: bool = False, accent: str = "red", parent=None):
        super().__init__(parent)
        self._checked = bool(checked)
        self.accent = accent
        self.setFixedSize(40, 21)
        self.setCursor(Qt.PointingHandCursor)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool, emit: bool = True) -> None:
        checked = bool(checked)
        if checked == self._checked:
            return
        self._checked = checked
        self.update()
        if emit:
            self.toggled.emit(checked)

    def mousePressEvent(self, event):
        # A widget embedded in QGraphicsProxyWidget must accept the press to
        # retain the mouse grab and receive the matching release.
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

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        colors = {
            "red": ("#70232a", "#d9505a", RED),
            "purple": ("#452e62", "#8e68c5", PURPLE),
            "orange": ("#704815", "#d89432", ORANGE),
        }
        off_fill, border, glow = colors.get(self.accent, colors["red"])
        if not self._checked:
            off_fill, border, glow = "#172229", "#35444c", "#718089"
        p.setPen(QPen(QColor(border), 1))
        p.setBrush(QColor(off_fill))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 10, 10)
        diameter = 15
        x = self.width() - diameter - 3 if self._checked else 3
        if self._checked:
            p.setPen(Qt.NoPen)
            halo = QColor(glow); halo.setAlpha(60)
            p.setBrush(halo); p.drawEllipse(QRectF(x - 2, 1, diameter + 4, diameter + 4))
        p.setBrush(QColor("#effaff" if self._checked else "#718089"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(x, 3, diameter, diameter))


class Chevron(QWidget):
    def __init__(self, expanded=False, parent=None):
        super().__init__(parent)
        self.expanded = expanded
        self.setFixedSize(18, 18)

    def setExpanded(self, expanded):
        self.expanded = bool(expanded)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#778891"), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        if self.expanded:
            p.drawLine(4, 11, 9, 6); p.drawLine(9, 6, 14, 11)
        else:
            p.drawLine(4, 7, 9, 12); p.drawLine(9, 12, 14, 7)


class OperationHeader(QFrame):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.isEnabled():
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class V16Tab(QFrame):
    clicked = Signal()

    def __init__(self, icon_kind, title, parent=None):
        super().__init__(parent)
        self._active = False
        self.setCursor(Qt.PointingHandCursor)
        layout = QHBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(9)
        layout.addStretch()
        self.icon = LineIcon(icon_kind, "#74828b", 18)
        self.title = QLabel(title)
        self.title.setStyleSheet("font-size:12px;font-weight:800;letter-spacing:1px;color:#74828b")
        layout.addWidget(self.icon); layout.addWidget(self.title); layout.addStretch()

    def setActive(self, active):
        self._active = bool(active)
        color = RED if active else "#74828b"
        self.icon.color = QColor(color); self.icon.update()
        self.title.setStyleSheet(f"font-size:12px;font-weight:800;letter-spacing:1px;color:{color}")
        self.update()

    @property
    def active(self):
        return self._active

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.isEnabled():
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(); event.accept(); return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._active:
            p = QPainter(self); p.setPen(Qt.NoPen); p.setBrush(QColor(RED))
            p.drawRect(0, self.height() - 2, self.width(), 2)


class PopupChoiceRow(QFrame):
    """One precisely aligned row in an :class:`AnchoredChoiceSelector` popup."""

    chosen = Signal(str)

    def __init__(self, text: str, accent: str, parent=None):
        super().__init__(parent)
        self.value = str(text)
        self.accent = accent
        self._checked = False
        self._hovered = False
        self.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(7, 0, 7, 0)
        row.setSpacing(5)
        self.check_label = QLabel("")
        self.check_label.setAlignment(Qt.AlignCenter)
        self.check_label.setFixedWidth(12)
        self.text_label = QLabel(self.value)
        self.text_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        row.addWidget(self.check_label, 0, Qt.AlignVCenter)
        row.addWidget(self.text_label, 1, Qt.AlignVCenter)
        self._refresh_style()

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        self._checked = bool(checked)
        self.check_label.setText("✓" if self._checked else "")
        self._refresh_style()

    def setVisualScale(self, factor: float) -> None:
        factor = max(1.0, float(factor))
        self.setFixedHeight(round(25 * factor))
        self.layout().setContentsMargins(round(7 * factor), 0, round(7 * factor), 0)
        self.layout().setSpacing(round(5 * factor))
        self.check_label.setFixedWidth(round(12 * factor))
        font = self.font()
        font.setPixelSize(round(10 * factor))
        font.setBold(True)
        self.check_label.setFont(font)
        self.text_label.setFont(font)

    def _refresh_style(self) -> None:
        selected = QColor(self.accent).darker(290).name()
        if self._checked:
            background, text = selected, "#f5eaff"
        elif self._hovered:
            background, text = "#34434c", "#ffffff"
        else:
            background, text = "transparent", "#e3e9ec"
        self.setStyleSheet(f"QFrame{{background:{background};border:none;border-radius:4px}}")
        self.check_label.setStyleSheet(f"color:{self.accent};background:transparent;border:none")
        self.text_label.setStyleSheet(f"color:{text};background:transparent;border:none")

    def enterEvent(self, event):
        self._hovered = True
        self._refresh_style()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._refresh_style()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.isEnabled():
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.isEnabled() and self.rect().contains(event.position().toPoint()):
            self.chosen.emit(self.value)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class AnchoredChoiceSelector(QPushButton):
    """A compact, scaled popup selector with deterministic check alignment."""

    currentTextChanged = Signal(str)

    def __init__(self, items, *, accent=ORANGE, exact_popup_width=False, parent=None):
        values = tuple(str(item) for item in items)
        super().__init__(values[0] if values else "", parent)
        self.setProperty("role", "choiceSelector")
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(29)
        self._items = values
        self._current_text = values[0] if values else ""
        self._accent = accent
        self._exact_popup_width = bool(exact_popup_width)
        self._popup = QFrame(self, Qt.Popup | Qt.FramelessWindowHint)
        self._popup.setObjectName("anchoredChoicePopup")
        self._popup.setStyleSheet(
            "QFrame#anchoredChoicePopup{background:#0d151a;border:1px solid #384953;border-radius:5px}"
        )
        popup_layout = QVBoxLayout(self._popup)
        popup_layout.setContentsMargins(3, 3, 3, 3)
        popup_layout.setSpacing(0)
        self._rows = {}
        for value in values:
            choice = PopupChoiceRow(value, accent, self._popup)
            choice.chosen.connect(self._choose)
            popup_layout.addWidget(choice)
            self._rows[value] = choice
        if values:
            self._rows[values[0]].setChecked(True)
        # Compatibility for the previous scale-menu tests and diagnostics.
        self._menu = self._popup
        self.clicked.connect(self._show_menu)

    def count(self):
        return len(self._items)

    def itemText(self, index):
        return self._items[index] if 0 <= index < len(self._items) else ""

    def currentText(self):
        return self._current_text

    def setCurrentText(self, text):
        text = str(text)
        if text not in self._rows:
            return
        changed = text != self._current_text
        self._current_text = text
        self.setText(text)
        for value, row in self._rows.items():
            row.setChecked(value == text)
        if changed:
            self.currentTextChanged.emit(text)

    def _choose(self, text):
        self.setCurrentText(text)
        self._popup.hide()

    def _visual_scale(self) -> float:
        left = self.mapToGlobal(QPoint(0, 0))
        right = self.mapToGlobal(QPoint(self.width(), 0))
        return max(1.0, abs(right.x() - left.x()) / max(1, self.width()))

    def _popup_size(self):
        factor = self._visual_scale()
        for row in self._rows.values():
            row.setVisualScale(factor)
        margins = round(3 * factor)
        self._popup.layout().setContentsMargins(margins, margins, margins, margins)
        global_left = self.mapToGlobal(QPoint(0, 0))
        global_right = self.mapToGlobal(QPoint(self.width(), 0))
        visible_width = max(1, abs(global_right.x() - global_left.x()))
        if self._exact_popup_width:
            width = visible_width
        else:
            font = self.font()
            font.setPixelSize(round(10 * factor))
            longest = max((QFontMetrics(font).horizontalAdvance(item) for item in self._items), default=0)
            width = max(visible_width, longest + round(38 * factor))
        height = margins * 2 + sum(row.height() for row in self._rows.values())
        return width, height

    def _show_menu(self):
        if not self.isEnabled() or not self._items:
            return
        width, height = self._popup_size()
        self._popup.setFixedSize(width, height)
        top_left = self.mapToGlobal(QPoint(0, 0))
        bottom_right = self.mapToGlobal(QPoint(self.width(), self.height()))
        factor = self._visual_scale()
        gap = max(3, round(3 * factor))

        # Popup widgets are native top-level surfaces and are not clipped by
        # the QGraphicsView that scales the interface.  Keep them inside the
        # visible Stem Slicer canvas (and the current screen) so selectors near
        # the bottom always open upwards instead of disappearing on the desktop.
        host = self.window()
        host_top_left = host.mapToGlobal(QPoint(0, 0))
        host_bottom_right = host.mapToGlobal(QPoint(host.width(), host.height()))
        host_rect = QRect(
            min(host_top_left.x(), host_bottom_right.x()),
            min(host_top_left.y(), host_bottom_right.y()),
            max(1, abs(host_bottom_right.x() - host_top_left.x())),
            max(1, abs(host_bottom_right.y() - host_top_left.y())),
        )
        screen = self.screen()
        available = screen.availableGeometry() if screen is not None else None
        bounds = host_rect.intersected(available) if available is not None else host_rect
        if bounds.isEmpty():
            bounds = available if available is not None else host_rect

        x = bottom_right.x() - width
        below_y = bottom_right.y() + gap
        above_y = top_left.y() - height - gap
        below_space = bounds.bottom() - below_y + 1
        above_space = top_left.y() - gap - bounds.top()
        if height <= below_space:
            y = below_y
        elif height <= above_space:
            y = above_y
        else:
            y = below_y if below_space >= above_space else above_y

        x = max(bounds.left(), min(x, bounds.right() - width + 1))
        y = max(bounds.top(), min(y, bounds.bottom() - height + 1))
        self._popup.move(x, y)
        self._popup.show()
        self._popup.raise_()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#a9b5bb"), 1.3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        x, y = self.width() - 10, self.height() // 2
        p.drawLine(x - 3, y - 2, x, y + 1)
        p.drawLine(x, y + 1, x + 3, y - 2)


class ScaleSelector(AnchoredChoiceSelector):
    """Compact scale picker whose popup exactly matches the field width."""

    scaleChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(("100%", "110%", "120%", "130%", "140%", "150%"), accent=PURPLE, exact_popup_width=True, parent=parent)
        self.setProperty("role", "scaleSelector")
        self.setFixedWidth(68)
        self._value = 100
        self._actions = {percent: self._rows[f"{percent}%"] for percent in (100, 110, 120, 130, 140, 150)}

    def value(self):
        return self._value

    def setValue(self, percent, emit=False):
        percent = int(percent)
        if percent not in self._actions:
            return
        changed = percent != self._value
        self._value = percent
        super().setCurrentText(f"{percent}%")
        if emit and changed:
            self.scaleChanged.emit(percent)

    def setCurrentText(self, text):
        try:
            percent = int(str(text).strip().rstrip("%"))
        except (TypeError, ValueError):
            return
        self.setValue(percent, emit=True)

class TargetKeySelector(AnchoredChoiceSelector):
    def __init__(self, parent=None):
        super().__init__(TARGET_KEYS, accent=ORANGE, parent=parent)


class V16DropZone(QFrame):
    pathChanged = Signal(str)

    def __init__(
        self,
        kind: str,
        title: str,
        accent: str,
        *,
        allowed_extensions=None,
        vertical=False,
        parent=None,
    ):
        super().__init__(parent)
        self.kind = kind
        self.path = ""
        self.accent = accent
        self.allowed_extensions = set(allowed_extensions or ({".mp3", ".wav", ".flac"} if kind == "audio" else set()))
        self.highlighted = False
        self.setAcceptDrops(True)
        self.setProperty("role", "dropZone")
        self._empty_title = title
        self.icon = LineIcon("folder_in" if kind == "folder" else "audio_file", accent, 26)
        self.title_label = MiddleElideLabel(title); self.title_label.setProperty("role", "statusFile")
        self.subtitle_label = QLabel("or click to browse"); self.subtitle_label.setProperty("role", "statusDetail")
        self.browse = QPushButton("BROWSE FOLDER" if kind == "folder" else "BROWSE")
        self.browse.setProperty("accent", self._accent_name())
        self.browse.clicked.connect(self.choose)
        self.copy_host = QWidget()
        self.copy_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.copy_host.setFixedHeight(29)
        copy = QVBoxLayout(self.copy_host)
        copy.setContentsMargins(0, 0, 0, 0)
        copy.setSpacing(1)
        self.title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.subtitle_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        copy.addWidget(self.title_label)
        copy.addWidget(self.subtitle_label)
        if vertical:
            layout = QVBoxLayout(self); layout.setContentsMargins(8, 6, 8, 6); layout.setSpacing(3)
            layout.addStretch(); layout.addWidget(self.icon, 0, Qt.AlignHCenter); layout.addWidget(self.copy_host)
            self.title_label.setAlignment(Qt.AlignCenter); self.subtitle_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(self.browse, 0, Qt.AlignHCenter); layout.addStretch()
        else:
            layout = QHBoxLayout(self); layout.setContentsMargins(10, 5, 9, 5); layout.setSpacing(8)
            layout.addWidget(self.icon, 0, Qt.AlignVCenter)
            layout.addWidget(self.copy_host, 1, Qt.AlignVCenter)
            layout.addWidget(self.browse, 0, Qt.AlignVCenter)

    def _accent_name(self):
        if self.accent == PURPLE: return "purple"
        if self.accent == ORANGE: return "orange"
        return "red"

    def choose(self):
        if self.kind == "folder":
            selected = QFileDialog.getExistingDirectory(self, "Choose loops folder", self.path or os.path.expanduser("~/Music"))
        else:
            selected, _ = QFileDialog.getOpenFileName(
                self,
                "Choose one audio file",
                os.path.dirname(self.path) if self.path else os.path.expanduser("~/Music"),
                "Audio files (" + " ".join("*" + ext for ext in sorted(self.allowed_extensions)) + ")",
            )
        if selected:
            self.set_path(selected)

    def set_path(self, path):
        path = os.path.abspath(path) if path else ""
        if path:
            if self.kind == "folder" and not os.path.isdir(path): return False
            if self.kind == "audio" and (not os.path.isfile(path) or os.path.splitext(path)[1].lower() not in self.allowed_extensions): return False
        self.path = path
        self.title_label.setFullText(os.path.basename(path) if path else self._empty_title)
        self.title_label.setToolTip(path)
        self.pathChanged.emit(path)
        return True

    def _drop_path(self, mime):
        if not mime.hasUrls() or len(mime.urls()) != 1 or not mime.urls()[0].isLocalFile(): return ""
        path = os.path.normpath(mime.urls()[0].toLocalFile())
        if self.kind == "folder": return path if os.path.isdir(path) else ""
        return path if os.path.isfile(path) and os.path.splitext(path)[1].lower() in self.allowed_extensions else ""

    def dragEnterEvent(self, event):
        if self._drop_path(event.mimeData()): self.highlighted = True; self.update(); event.acceptProposedAction()
        else: event.ignore()

    def dragMoveEvent(self, event):
        if self._drop_path(event.mimeData()): self.highlighted = True; self.update(); event.acceptProposedAction()
        else: event.ignore()

    def dragLeaveEvent(self, event):
        self.highlighted = False; self.update(); super().dragLeaveEvent(event)

    def dropEvent(self, event):
        path = self._drop_path(event.mimeData()); self.highlighted = False
        if path and self.set_path(path): event.acceptProposedAction()
        else: event.ignore()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        color = self.accent if self.highlighted else QColor(self.accent).darker(155).name()
        pen = QPen(QColor(color), 1.1, Qt.DashLine); pen.setDashPattern([5, 4])
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(.7, .7, -1.2, -1.2), 6, 6)


class V16LayerCard(LayerCard):
    """Validated three-column layer card with musical metadata."""

    def __init__(self, layer, parent=None):
        QFrame.__init__(self, parent)
        self.layer = layer; self.setProperty("role", "layerCard"); self.setFixedHeight(78)
        layout = QVBoxLayout(self); layout.setContentsMargins(7, 5, 7, 5); layout.setSpacing(1)
        header = QHBoxLayout(); header.setSpacing(5)
        from functional_core import LayerPlayButton, MidiDragHandle, WaveformWidget
        self.play = LayerPlayButton(); self.play.setProperty("role", "layerPlay"); self.play.setFixedSize(25, 25)
        self.play.clicked.connect(lambda: self.playRequested.emit(layer["path"]))
        name = MiddleElideLabel(layer.get("display_name") or layer["name"])
        name.setProperty("role", "layerName"); name.setToolTip(layer["name"])
        self.midi_handle = MidiDragHandle(); self.midi_handle.setFixedSize(20, 20)
        header.addWidget(self.play); header.addWidget(name, 1); header.addWidget(self.midi_handle); header.addWidget(FileDragHandle(layer["path"]))
        layout.addLayout(header)
        self.waveform = WaveformWidget(layer["peaks"]); self.waveform.setFixedHeight(20)
        self.waveform.seekRequested.connect(lambda ratio: self.seekRequested.emit(layer["path"], ratio)); layout.addWidget(self.waveform)
        metadata = QHBoxLayout(); metadata.setSpacing(4)
        musical = f"{layer.get('key') or '—'} · {int(layer.get('bpm') or 0) or '—'} BPM"
        metadata.addWidget(label(musical, "cardMeta")); metadata.addStretch()
        from functional_core import format_duration
        metadata.addWidget(label(f"{format_duration(layer['duration'])} · {format_decimal_size(layer['bytes'])}", "cardMeta"))
        layout.addLayout(metadata)


class MiddleElideLabel(QLabel):
    """Keep the layer suffix visible when a card becomes narrow."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._full_text = str(text)
        self.setToolTip(self._full_text)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._refresh_elision()

    def setFullText(self, text: str) -> None:
        self._full_text = str(text)
        self.setToolTip(self._full_text)
        self._refresh_elision()

    def _refresh_elision(self) -> None:
        available = max(1, self.contentsRect().width())
        QLabel.setText(self, QFontMetrics(self.font()).elidedText(self._full_text, Qt.ElideMiddle, available))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_elision()


class ValidatedMainWindow(FunctionalMainWindow):
    """Functional app using the exact layout approved in the HTML prototype."""

    def _build(self):
        self.pending_quick_extract = ""
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.setWindowIcon(QIcon(resource_path("assets", "app-icon.png")))
        self.setStyleSheet(validated_stylesheet())

        self.view = QGraphicsView(self)
        self.view.setFrameShape(QFrame.NoFrame)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scene = QGraphicsScene(self.view)
        self.scene.setSceneRect(0, 0, BASE_WIDTH, BASE_HEIGHT)
        self.view.setScene(self.scene)
        self.canvas = StudioRoot(); self.canvas.setObjectName("ValidatedCanvas"); self.canvas.setFixedSize(BASE_WIDTH, BASE_HEIGHT)
        # A widget embedded through QGraphicsProxyWidget is its own style
        # propagation root.  Apply the validated theme to the canvas itself so
        # packaged and diagnostic launches render identically.
        self.canvas.setStyleSheet(validated_stylesheet())
        self.proxy = self.scene.addWidget(self.canvas)
        self.setCentralWidget(self.view)

        outer = QVBoxLayout(self.canvas); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        self._header(outer); self._tabs(outer)
        self.pages = QStackedWidget(); self.pages.addWidget(self._stem_page()); self.pages.addWidget(self._quick_page())
        outer.addWidget(self.pages, 1)
        self.quick_extract_bpm_switch.toggled.connect(self._sync_quick_target_fields)
        self.quick_extract_key_switch.toggled.connect(self._sync_quick_target_fields)
        self.quick_convert_bpm_switch.toggled.connect(self._sync_quick_target_fields)
        self.quick_convert_key_switch.toggled.connect(self._sync_quick_target_fields)
        self._sync_quick_target_fields()
        self._set_destination_mode(self.destination_mode)
        self._set_ui_scale(100)

    def _header(self, outer):
        header = QFrame(); header.setProperty("role", "topBar"); header.setFixedHeight(60)
        row = QHBoxLayout(header); row.setContentsMargins(19, 0, 19, 0); row.setSpacing(0)
        brand = QWidget(); brand.setFixedWidth(280); bl = QHBoxLayout(brand); bl.setContentsMargins(0, 0, 0, 0); bl.setSpacing(8)
        bl.addWidget(image(resource_path("assets", "antiworld-logo.png"), 35, 41))
        copy = QVBoxLayout(); copy.setSpacing(2); copy.addStretch()
        made = QLabel("MADE WITH <3 BY"); made.setStyleSheet("color:#ff2b1c;font-size:8px;font-weight:900")
        anti = QLabel("ANTIWORLD"); anti.setStyleSheet("color:#ff2b1c;font-size:13px;font-weight:950")
        copy.addWidget(made); copy.addWidget(anti); copy.addStretch(); bl.addLayout(copy); bl.addStretch(); row.addWidget(brand)
        row.addStretch(); row.addWidget(image(resource_path("assets", "stem-slicer-wordmark.png"), 235, 50)); row.addStretch()
        build = QWidget(); build.setFixedWidth(280); br = QHBoxLayout(build); br.setContentsMargins(0, 0, 0, 0); br.setSpacing(12); br.addStretch()
        bc = QVBoxLayout(); bc.setSpacing(2); title = QLabel("LOOP LAYER EXTRACTION SYSTEM"); version = QLabel("1.6B")
        title.setStyleSheet("color:#7e8a92;font-size:9px;font-weight:700"); version.setStyleSheet("color:#7e8a92;font-family:'SF Mono';font-size:9px;font-weight:700")
        title.setAlignment(Qt.AlignRight); version.setAlignment(Qt.AlignRight); bc.addWidget(title); bc.addWidget(version); br.addLayout(bc)
        self.scale_select = ScaleSelector()
        self.scale_select.scaleChanged.connect(self._set_ui_scale)
        br.addWidget(self.scale_select); row.addWidget(build); outer.addWidget(header)

    def _tabs(self, outer):
        tabs = QFrame(); tabs.setProperty("role", "tabsBar"); tabs.setFixedHeight(42)
        row = QHBoxLayout(tabs); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(0); row.addStretch()
        self.stem_tab = V16Tab("folder", "STEM SLICER"); self.stem_tab.setFixedWidth(210)
        self.quick_tab = V16Tab("bolt", "QUICK TOOLS"); self.quick_tab.setFixedWidth(210)
        self.stem_tab.clicked.connect(lambda: self.select_tab(0)); self.quick_tab.clicked.connect(lambda: self.select_tab(1))
        row.addWidget(self.stem_tab); row.addWidget(self.quick_tab); row.addStretch(); outer.addWidget(tabs)

    def _set_ui_scale(self, percent):
        factor = max(1.0, min(1.5, float(percent) / 100.0))
        self.view.setTransform(QTransform.fromScale(factor, factor))
        width, height = round(BASE_WIDTH * factor), round(BASE_HEIGHT * factor)
        self.view.setFixedSize(width, height); self.setFixedSize(width, height)

    @staticmethod
    def _section(accent, icon_kind, title, description):
        section = QFrame(); section.setProperty("role", "section"); section.setProperty("accent", accent)
        layout = QVBoxLayout(section); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        head = QWidget(); head.setFixedHeight(38); hl = QHBoxLayout(head); hl.setContentsMargins(13, 5, 13, 3); hl.setSpacing(8)
        color = {"red": RED, "purple": PURPLE, "orange": ORANGE}.get(accent, CYAN)
        hl.addWidget(LineIcon(icon_kind, color, 18)); copy = QVBoxLayout(); copy.setSpacing(1)
        heading = QLabel(title); heading.setProperty("role", "sectionTitle"); desc = QLabel(description); desc.setProperty("role", "sectionDescription")
        copy.addWidget(heading); copy.addWidget(desc); hl.addLayout(copy); hl.addStretch(); layout.addWidget(head)
        body = QWidget(); layout.addWidget(body, 1)
        return section, body

    def _stem_page(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(9, 9, 9, 9); layout.setSpacing(9)

        source, source_body = self._section("red", "folder_in", "SOURCE FOLDER", "Drop a folder containing loops to configure the batch.")
        source.setFixedHeight(118); source_layout = QHBoxLayout(source_body); source_layout.setContentsMargins(12, 0, 12, 8); source_layout.setSpacing(7)
        self.input_drop = V16DropZone("folder", "Drop a loop folder here", RED); self.input_drop.setFixedHeight(66)
        source_layout.addWidget(self.input_drop, 1)
        self.source_path_box = QFrame(); self.source_path_box.setProperty("role", "pathBox"); self.source_path_box.setFixedSize(300, 66)
        spl = QHBoxLayout(self.source_path_box); spl.setContentsMargins(11, 6, 11, 6); spl.setSpacing(10); spl.addWidget(LineIcon("folder", RED, 25))
        self.source_path_label = QLabel("No folder selected"); self.source_path_label.setProperty("role", "path"); self.source_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        spl.addWidget(self.source_path_label, 1); source_layout.addWidget(self.source_path_box); layout.addWidget(source)

        operations, operations_body = self._section("red", "gear", "OPERATIONS", "Enable only the operations required for this batch.")
        operations_layout = QVBoxLayout(operations_body); operations_layout.setContentsMargins(12, 0, 12, 8); operations_layout.setSpacing(6)

        self.layer_operation_card, layer_head, _ = self._operation_shell("red", "layers", "LAYER EXTRACTION", "Extract every detected layer from each loop.", True, False)
        self.layer_switch = layer_head.toggle
        layer_location = QHBoxLayout(); layer_location.setSpacing(6)
        out_label = QLabel("OUTPUT LOCATION"); out_label.setStyleSheet(f"color:{RED};font-size:8px;font-weight:800")
        out_label.setFixedWidth(77)
        layer_location.addWidget(out_label); layer_location.addWidget(LineIcon("folder", RED, 15))
        self.destination_path_label = MiddleElideLabel(""); self.destination_path_label.setProperty("role", "path"); self.destination_path_label.setFixedWidth(270)
        layer_location.addWidget(self.destination_path_label)
        self.change_root_button = QPushButton("CHANGE"); self.change_root_button.setProperty("accent", "red"); self.change_root_button.setFixedSize(76, 30)
        self.open_folder_button = QPushButton("OPEN FOLDER"); self.open_folder_button.setProperty("accent", "red"); self.open_folder_button.setFixedSize(112, 30)
        self.reset_destination_button = QPushButton("RESET"); self.reset_destination_button.setVisible(False)
        layer_location.addWidget(self.change_root_button); layer_location.addWidget(self.open_folder_button)
        # The header already ends with a stretch.  Appending the fixed-size
        # location group after it anchors CHANGE/OPEN FOLDER to the right,
        # regardless of the path length.
        layer_head.layout().addLayout(layer_location)
        operations_layout.addWidget(self.layer_operation_card)

        self.key_operation_card, key_head, self.key_panel = self._operation_shell("purple", "key_scan", "KEY ANALYSIS", "Detect keys and apply the selected output naming structure.", True, True)
        self.key_switch = key_head.toggle
        key_settings = QGridLayout(self.key_panel); key_settings.setContentsMargins(10, 7, 10, 7); key_settings.setHorizontalSpacing(8); key_settings.setVerticalSpacing(6)
        mode_box = QWidget(); ml = QVBoxLayout(mode_box); ml.setContentsMargins(0, 0, 0, 0); ml.setSpacing(5); ml.addWidget(self._caps("KEY MODE"))
        mode_row = QHBoxLayout(); mode_row.setSpacing(0); self.mode_buttons = {}
        for index, (value, text) in enumerate((("detected", "DETECTED"), ("relative_minor", "RELATIVE MINOR"), ("relative_major", "RELATIVE MAJOR"))):
            item = self._segment(text, index, 3, index == 0); item.clicked.connect(lambda checked=False, v=value: self._set_key_mode(v)); self.mode_buttons[value] = item; mode_row.addWidget(item)
        ml.addLayout(mode_row); key_settings.addWidget(mode_box, 0, 0)
        notation_box = QWidget(); nl = QVBoxLayout(notation_box); nl.setContentsMargins(0, 0, 0, 0); nl.setSpacing(5); nl.addWidget(self._caps("KEY NOTATION"))
        nr = QHBoxLayout(); nr.setSpacing(0); self.sharps_button = self._segment("SHARPS #", 0, 2, True); self.flats_button = self._segment("FLATS ♭", 1, 2, False)
        self.sharps_button.clicked.connect(lambda: self._set_accidentals("sharps")); self.flats_button.clicked.connect(lambda: self._set_accidentals("flats")); nr.addWidget(self.sharps_button); nr.addWidget(self.flats_button); nl.addLayout(nr); key_settings.addWidget(notation_box, 0, 1)
        name_box = QWidget(); namel = QVBoxLayout(name_box); namel.setContentsMargins(0, 0, 0, 0); namel.setSpacing(5); namel.addWidget(self._caps("OUTPUT NAME STRUCTURE · DRAG TO REORDER"))
        self.token_strip = TokenStrip(TOKENS, compact=True); self.token_strip.orderChanged.connect(self._token_order_changed); namel.addWidget(self.token_strip); key_settings.addWidget(name_box, 0, 2)
        destination = QWidget(); dl = QHBoxLayout(destination); dl.setContentsMargins(0, 0, 0, 0); dl.setSpacing(5); dl.addWidget(self._caps("KEY ANALYSIS DESTINATION"))
        self.copy_destination_button = QPushButton("COPY TO ANALYZED LOOPS"); self.copy_destination_button.setProperty("role", "destinationChoice")
        self.rename_destination_button = QPushButton("RENAME ORIGINALS"); self.rename_destination_button.setProperty("role", "destinationChoice")
        dl.addWidget(self.copy_destination_button); dl.addWidget(self.rename_destination_button); key_settings.addWidget(destination, 1, 0, 1, 2)
        preview = QWidget(); pl = QHBoxLayout(preview); pl.setContentsMargins(0, 0, 0, 0); pl.setSpacing(5); pl.addWidget(self._caps("PREVIEW"))
        self.name_preview_label = QLabel(""); self.name_preview_label.setProperty("role", "preview"); self.name_preview_label.setFixedHeight(29); pl.addWidget(self.name_preview_label, 1); key_settings.addWidget(preview, 1, 2)
        key_settings.setColumnStretch(0, 12); key_settings.setColumnStretch(1, 7); key_settings.setColumnStretch(2, 17)
        self.key_setting_widgets = [*self.mode_buttons.values(), self.sharps_button, self.flats_button, self.token_strip, self.copy_destination_button, self.rename_destination_button]
        self.key_opacity_effects = []
        self.key_destination_effect = None
        self.key_destination_visuals = {
            self.copy_destination_button: (LineIcon("copy", PURPLE, 1), QLabel()),
            self.rename_destination_button: (LineIcon("pencil", PURPLE, 1), QLabel()),
        }
        operations_layout.addWidget(self.key_operation_card)

        self.target_operation_card, target_head, self.target_panel = self._operation_shell("orange", "retarget", "CONVERT BPM & KEY", "Convert extracted layers, or every source loop when extraction is disabled.", False, True)
        self.convert_switch = target_head.toggle
        target_layout = QHBoxLayout(self.target_panel); target_layout.setContentsMargins(0, 7, 0, 7); target_layout.setSpacing(16); target_layout.addStretch()
        self.target_bpm_switch = V16Toggle(True, "orange"); self.target_bpm_input = QLineEdit("120"); self.target_bpm_input.setMaxLength(3); self.target_bpm_input.setFixedWidth(82); self.target_bpm_input.setAlignment(Qt.AlignCenter)
        bpm_option = self._target_option(self.target_bpm_switch, "TARGET BPM", self.target_bpm_input, 250); target_layout.addWidget(bpm_option)
        self.target_key_switch = V16Toggle(True, "orange"); self.target_key_combo = TargetKeySelector(); self.target_key_combo.setFixedWidth(240)
        key_option = self._target_option(self.target_key_switch, "TARGET KEY", self.target_key_combo, 390); target_layout.addWidget(key_option); target_layout.addStretch()
        operations_layout.addWidget(self.target_operation_card)
        operations_layout.addStretch(1)
        layout.addWidget(operations, 1)

        self.status_panel = QFrame(); self.status_panel.setProperty("role", "section"); self.status_panel.setFixedHeight(64)
        status_layout = QHBoxLayout(self.status_panel); status_layout.setContentsMargins(10, 5, 10, 6); status_layout.setSpacing(12)
        main = QVBoxLayout(); main.setSpacing(2); top = QHBoxLayout(); top.setSpacing(7)
        top.addWidget(self._caps("PROCESS STATUS")); top.addStretch(); main.addLayout(top)
        ready = QHBoxLayout(); ready.setSpacing(7); self.engine_state_icon = LineIcon("check", "#718089", 15); ready.addWidget(self.engine_state_icon)
        self.process_status = QLabel("Ready to process."); self.process_status.setProperty("role", "ready"); ready.addWidget(self.process_status)
        self.files_stat = QLabel("0 FILES"); self.success_stat = QLabel("0 SUCCESSFUL"); self.error_stat = QLabel("0 ERRORS")
        for stat in (self.files_stat, self.success_stat, self.error_stat): stat.setProperty("role", "caps"); ready.addWidget(stat)
        main.addLayout(ready)
        bottom = QHBoxLayout(); bottom.setSpacing(8); self.progress_bar = QProgressBar(); self.progress_bar.setRange(0, 100); self.progress_bar.setValue(0); bottom.addWidget(self.progress_bar, 1)
        self.progress_counter = QLabel("0 / 0"); self.progress_counter.setProperty("role", "counter"); bottom.addWidget(self.progress_counter); main.addLayout(bottom)
        status_layout.addLayout(main, 1); self.start_button = QPushButton("▶  PROCESS LOOPS"); self.start_button.setProperty("role", "process"); self.start_button.setFixedSize(210, 46); status_layout.addWidget(self.start_button)
        layout.addWidget(self.status_panel)

        self.results_title = QLabel("OUTPUT LOCATION")
        self.destination_info_label = QLabel("")
        self.layer_title = key_head.title_label  # compatibility is overwritten below
        self.layer_title = layer_head.title_label
        self.key_title = key_head.title_label
        self.workflow_sections = (source, operations, self.status_panel)
        self._update_name_preview()
        return page

    def _operation_shell(self, accent, icon_kind, title, description, checked, collapsible):
        card = QFrame(); card.setProperty("role", "operation"); card.setProperty("accent", accent)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(card); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        head = OperationHeader(); head.setFixedHeight(45); row = QHBoxLayout(head); row.setContentsMargins(11, 0, 11, 0); row.setSpacing(10)
        toggle = V16Toggle(checked, accent); row.addWidget(toggle); color = {"red": RED, "purple": PURPLE, "orange": ORANGE}[accent]
        row.addWidget(LineIcon(icon_kind, color, 20)); copy = QVBoxLayout(); copy.setSpacing(1)
        title_label = QLabel(title); title_label.setProperty("role", "operationTitle"); desc_label = QLabel(description); desc_label.setProperty("role", "operationDescription")
        copy.addWidget(title_label); copy.addWidget(desc_label); row.addLayout(copy); row.addStretch()
        head.toggle = toggle; head.title_label = title_label
        card.header = head
        arrow = Chevron(checked); head.arrow = arrow
        if collapsible: row.addWidget(arrow)
        layout.addWidget(head)
        settings = QFrame(); settings.setProperty("role", "operationSettings"); settings.setVisible(checked if collapsible else False); layout.addWidget(settings)
        if collapsible:
            def sync(active):
                settings.setVisible(active); arrow.setExpanded(active)
                card.updateGeometry()
                if card.parentWidget() is not None and card.parentWidget().layout() is not None:
                    card.parentWidget().layout().invalidate()
            toggle.toggled.connect(sync); head.clicked.connect(lambda: toggle.setChecked(not toggle.isChecked()))
        else:
            head.clicked.connect(lambda: toggle.setChecked(not toggle.isChecked()))
        return card, head, settings

    @staticmethod
    def _caps(text):
        item = QLabel(text); item.setProperty("role", "caps"); return item

    @staticmethod
    def _segment(text, index, total, active=False):
        item = QPushButton(text); item.setProperty("role", "segment"); item.setProperty("active", active)
        item.setProperty("position", "first" if index == 0 else "last" if index == total - 1 else "middle"); item.setFixedHeight(27); return item

    @staticmethod
    def _target_option(toggle, title, field, width):
        box = QFrame(); box.setProperty("role", "inset"); box.setFixedSize(width, 48)
        row = QHBoxLayout(box); row.setContentsMargins(10, 5, 10, 5); row.setSpacing(9); row.addWidget(toggle); row.addWidget(ValidatedMainWindow._caps(title)); row.addStretch(); row.addWidget(field); return box

    def _quick_page(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(9, 9, 9, 9); layout.setSpacing(9)
        extract, extract_body = self._section("red", "layers", "QUICK EXTRACT", "Extract layers from one loop, with optional target transformation.")
        extract_layout = QGridLayout(extract_body); extract_layout.setContentsMargins(12, 0, 12, 7); extract_layout.setHorizontalSpacing(8); extract_layout.setVerticalSpacing(4)
        left = QWidget(); left.setFixedWidth(360); left_layout = QVBoxLayout(left); left_layout.setContentsMargins(0, 0, 0, 0); left_layout.setSpacing(7)
        self.quick_extract_drop = V16DropZone("audio", "Drop one loop here", RED, allowed_extensions={".mp3"}, vertical=True); left_layout.addWidget(self.quick_extract_drop, 1)
        target = QFrame(); target.setProperty("role", "inset"); target.setFixedHeight(68); tl = QGridLayout(target); tl.setContentsMargins(10, 5, 10, 6); tl.setHorizontalSpacing(5); tl.setVerticalSpacing(4)
        tl.addWidget(self._caps("OPTIONAL TARGET"), 0, 0, 1, 2)
        self.quick_extract_bpm_switch = V16Toggle(True, "orange"); self.quick_extract_bpm_switch.setFixedWidth(34)
        self.quick_extract_bpm = QLineEdit("120"); self.quick_extract_bpm.setMaxLength(3); self.quick_extract_bpm.setFixedSize(58, 29); self.quick_extract_bpm.setAlignment(Qt.AlignCenter)
        bpm_line = QWidget(); bpm_line.setFixedWidth(132); bpmrow = QHBoxLayout(bpm_line); bpmrow.setContentsMargins(0, 0, 3, 0); bpmrow.setSpacing(4)
        bpmrow.addWidget(QLabel("BPM")); bpmrow.addWidget(self.quick_extract_bpm_switch); bpmrow.addWidget(self.quick_extract_bpm); tl.addWidget(bpm_line, 1, 0)
        self.quick_extract_key_switch = V16Toggle(True, "orange"); self.quick_extract_key_switch.setFixedWidth(34)
        self.quick_extract_key = TargetKeySelector(); self.quick_extract_key.setFixedWidth(130)
        key_line = QWidget(); keyrow = QHBoxLayout(key_line); keyrow.setContentsMargins(0, 0, 3, 0); keyrow.setSpacing(4)
        keyrow.addWidget(QLabel("KEY")); keyrow.addWidget(self.quick_extract_key_switch); keyrow.addWidget(self.quick_extract_key, 1); tl.addWidget(key_line, 1, 1)
        tl.setColumnStretch(1, 1)
        left_layout.addWidget(target); extract_layout.addWidget(left, 0, 0)
        self.quick_layers_area = QScrollArea(); self.quick_layers_area.setWidgetResizable(True); self.quick_layers_area.setProperty("role", "layers"); self.quick_layers_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.quick_layer_content = QWidget(); self.quick_layer_grid = QGridLayout(self.quick_layer_content); self.quick_layer_grid.setContentsMargins(8, 8, 8, 8); self.quick_layer_grid.setHorizontalSpacing(8); self.quick_layer_grid.setVerticalSpacing(8)
        self.quick_layers_area.setWidget(self.quick_layer_content); extract_layout.addWidget(self.quick_layers_area, 0, 1)
        self._populate_layer_cards([], "Once you drop an audio file, its layers will appear here.", show_empty_icon=True)
        storage_footer = QWidget(); self.quick_extract_storage_footer = storage_footer; storage_footer.setFixedHeight(32); sfl = QHBoxLayout(storage_footer); sfl.setContentsMargins(7, 2, 0, 1); sfl.setSpacing(7)
        sfl.addWidget(LineIcon("drive", "#9da5ac", 20)); self.quick_storage_label = QLabel("0 extractions · 0 o"); self.quick_storage_label.setProperty("role", "storage"); sfl.addWidget(self.quick_storage_label); sfl.addStretch()
        result_footer = QWidget(); self.quick_extract_result_footer = result_footer; result_footer.setFixedHeight(32); fl = QHBoxLayout(result_footer); fl.setContentsMargins(7, 2, 0, 1); fl.setSpacing(7)
        fl.addWidget(LineIcon("music_note", RED, 17)); self.quick_extract_filename = QLabel("Ready for one MP3 loop."); self.quick_extract_filename.setProperty("role", "statusFile"); fl.addWidget(self.quick_extract_filename)
        self.quick_extract_check = LineIcon("check", GREEN, 15); self.quick_extract_check.setVisible(False); fl.addWidget(self.quick_extract_check)
        self.quick_extract_status = QLabel(""); self.quick_extract_status.setProperty("role", "statusDetail"); fl.addWidget(self.quick_extract_status); fl.addStretch()
        open_extract = QPushButton("OPEN OUTPUT FOLDER"); open_extract.setProperty("accent", "red"); open_extract.clicked.connect(self._open_quick_root)
        manage_extract = QPushButton("MANAGE"); manage_extract.setProperty("accent", "red"); manage_extract.clicked.connect(self._manage_quick_storage)
        fl.addWidget(open_extract); fl.addWidget(manage_extract)
        extract_layout.addWidget(storage_footer, 1, 0)
        extract_layout.addWidget(result_footer, 1, 1)
        extract_layout.setColumnStretch(1, 1); layout.addWidget(extract, 1)
        self.quick_extract_drop.pathChanged.connect(self._quick_extract_requested)
        self.quick_show_results = QPushButton(); self.quick_show_results.setVisible(False); self.quick_show_results.setEnabled(False)

        scan, scan_body = self._section("purple", "key_scan", "QUICK SCAN", "Detect BPM, key relationships and relative modes from one loop.")
        scan.setFixedHeight(168); grid = QGridLayout(scan_body); grid.setContentsMargins(12, 0, 12, 6); grid.setHorizontalSpacing(6); grid.setVerticalSpacing(4)
        self.quick_scan_drop = V16DropZone("audio", "Drop one loop here", PURPLE, allowed_extensions={".mp3", ".wav", ".flac"}); self.quick_scan_drop.setFixedWidth(210); grid.addWidget(self.quick_scan_drop, 0, 0, 3, 1)
        self.quick_bpm_card = self._metric("BPM", "—", width=82); grid.addWidget(self.quick_bpm_card, 0, 1)
        self.quick_detected_card = self._metric("DETECTED KEY", "—", "—", width=150, bind="quick_detected"); grid.addWidget(self.quick_detected_card, 0, 2)
        self.quick_relative_card = self._metric("RELATIVE KEY", "—", "—", width=150, bind="quick_relative"); grid.addWidget(self.quick_relative_card, 0, 3)
        self.quick_modes_card = self._modes_metric(); grid.addWidget(self.quick_modes_card, 0, 4, 2, 1)
        status = QWidget(); st = QHBoxLayout(status); st.setContentsMargins(0, 0, 0, 0); st.setSpacing(6); st.addWidget(LineIcon("music_note", PURPLE, 17))
        self.quick_scan_filename_label = QLabel("Drop a file to begin."); self.quick_scan_filename_label.setProperty("role", "statusFile"); st.addWidget(self.quick_scan_filename_label)
        self.quick_scan_check = LineIcon("check", GREEN, 15); self.quick_scan_check.setVisible(False); st.addWidget(self.quick_scan_check)
        self.quick_scan_time_label = QLabel(""); self.quick_scan_time_label.setProperty("role", "statusDetail"); st.addWidget(self.quick_scan_time_label); st.addStretch(); grid.addWidget(status, 2, 1, 1, 2)
        controls = QWidget(); ctl = QHBoxLayout(controls); ctl.setContentsMargins(0, 0, 0, 0); ctl.setSpacing(5); ctl.addStretch()
        self.quick_degree_label = self._caps("DEGREE REFERENCE"); ctl.addWidget(self.quick_degree_label)
        self.quick_major_button = self._segment("MAJOR", 0, 2, True); self.quick_minor_button = self._segment("MINOR", 1, 2, False); self.quick_major_button.setFixedWidth(52); self.quick_minor_button.setFixedWidth(52)
        self.quick_major_button.clicked.connect(lambda: self._set_quick_degree_reference("major")); self.quick_minor_button.clicked.connect(lambda: self._set_quick_degree_reference("minor")); ctl.addWidget(self.quick_major_button); ctl.addWidget(self.quick_minor_button)
        self.quick_notation_label = self._caps("KEY NOTATION"); ctl.addWidget(self.quick_notation_label); self.quick_sharps_button = self._segment("SHARPS #", 0, 2, True); self.quick_flats_button = self._segment("FLATS ♭", 1, 2, False); self.quick_sharps_button.setFixedWidth(55); self.quick_flats_button.setFixedWidth(55)
        self.quick_sharps_button.clicked.connect(lambda: self._set_quick_accidentals("sharps")); self.quick_flats_button.clicked.connect(lambda: self._set_quick_accidentals("flats")); ctl.addWidget(self.quick_sharps_button); ctl.addWidget(self.quick_flats_button); grid.addWidget(controls, 2, 3, 1, 2)
        grid.setColumnStretch(4, 1); grid.setRowMinimumHeight(0, 68); grid.setRowMinimumHeight(1, 19); grid.setRowMinimumHeight(2, 23); layout.addWidget(scan)
        self.quick_scan_drop.pathChanged.connect(self._quick_scan_requested)

        convert, convert_body = self._section("orange", "retarget", "QUICK CONVERT", "Convert one loop to a selected BPM and key.")
        convert.setFixedHeight(118); cg = QGridLayout(convert_body); cg.setContentsMargins(12, 0, 12, 6); cg.setHorizontalSpacing(8); cg.setVerticalSpacing(4)
        self.quick_convert_drop = V16DropZone("audio", "Drop one loop here", ORANGE, allowed_extensions={".mp3", ".wav", ".flac"}); self.quick_convert_drop.setFixedWidth(285); cg.addWidget(self.quick_convert_drop, 0, 0)
        settings = QFrame(); self.quick_convert_settings = settings; settings.setProperty("role", "inset"); settings.setFixedWidth(350); setl = QHBoxLayout(settings); setl.setContentsMargins(8, 5, 8, 5); setl.setSpacing(5)
        setl.addWidget(QLabel("BPM")); self.quick_convert_bpm_switch = V16Toggle(True, "orange"); self.quick_convert_bpm_switch.setFixedWidth(34); setl.addWidget(self.quick_convert_bpm_switch); self.quick_convert_bpm = QLineEdit("120"); self.quick_convert_bpm.setMaxLength(3); self.quick_convert_bpm.setFixedSize(58, 29); self.quick_convert_bpm.setAlignment(Qt.AlignCenter); setl.addWidget(self.quick_convert_bpm)
        setl.addWidget(QLabel("KEY")); self.quick_convert_key_switch = V16Toggle(True, "orange"); self.quick_convert_key_switch.setFixedWidth(34); setl.addWidget(self.quick_convert_key_switch); self.quick_convert_key = TargetKeySelector(); self.quick_convert_key.setMinimumWidth(132); setl.addWidget(self.quick_convert_key, 1); cg.addWidget(settings, 0, 1)
        result = QFrame(); result.setProperty("role", "resultLine"); rl = QHBoxLayout(result); rl.setContentsMargins(10, 4, 8, 4); rl.setSpacing(6)
        self.quick_convert_check = LineIcon("check", GREEN, 15); self.quick_convert_check.setVisible(False); rl.addWidget(self.quick_convert_check)
        result_copy = QWidget(); result_copy_layout = QVBoxLayout(result_copy); result_copy_layout.setContentsMargins(0, 0, 0, 0); result_copy_layout.setSpacing(0); result_copy_layout.addStretch()
        self.quick_convert_filename = QLabel(""); self.quick_convert_filename.setProperty("role", "statusFile"); result_copy_layout.addWidget(self.quick_convert_filename)
        self.quick_convert_status = QLabel(""); self.quick_convert_status.setProperty("role", "statusDetail"); result_copy_layout.addWidget(self.quick_convert_status); result_copy_layout.addStretch(); rl.addWidget(result_copy, 1)
        self.quick_convert_drag = FileDragHandle(""); self.quick_convert_drag.setEnabled(False); rl.addWidget(self.quick_convert_drag); cg.addWidget(result, 0, 2)
        convert_storage_footer = QWidget(); self.quick_convert_storage_footer = convert_storage_footer; convert_storage_footer.setFixedHeight(32); csfl = QHBoxLayout(convert_storage_footer); csfl.setContentsMargins(7, 2, 0, 1); csfl.setSpacing(7)
        csfl.addWidget(LineIcon("drive", "#9da5ac", 20)); self.quick_convert_storage_label = QLabel("0 conversions · 0 o"); self.quick_convert_storage_label.setProperty("role", "storage"); csfl.addWidget(self.quick_convert_storage_label); csfl.addStretch()
        convert_status_footer = QWidget(); self.quick_convert_status_footer = convert_status_footer; convert_status_footer.setFixedHeight(32); cstfl = QHBoxLayout(convert_status_footer); cstfl.setContentsMargins(7, 2, 0, 1); cstfl.setSpacing(7)
        cstfl.addWidget(LineIcon("music_note", ORANGE, 17)); self.quick_convert_footer_filename = QLabel("Ready for one loop."); self.quick_convert_footer_filename.setProperty("role", "statusFile"); cstfl.addWidget(self.quick_convert_footer_filename)
        self.quick_convert_footer_check = LineIcon("check", GREEN, 15); self.quick_convert_footer_check.setVisible(False); cstfl.addWidget(self.quick_convert_footer_check)
        self.quick_convert_footer_status = QLabel(""); self.quick_convert_footer_status.setProperty("role", "statusDetail"); cstfl.addWidget(self.quick_convert_footer_status); cstfl.addStretch()
        convert_actions_footer = QWidget(); convert_actions_footer.setFixedHeight(32); cfl = QHBoxLayout(convert_actions_footer); cfl.setContentsMargins(0, 2, 0, 1); cfl.setSpacing(7); cfl.addStretch()
        open_convert = QPushButton("OPEN OUTPUT FOLDER"); open_convert.setProperty("accent", "orange"); open_convert.clicked.connect(self._open_quick_convert_root)
        manage_convert = QPushButton("MANAGE"); manage_convert.setProperty("accent", "orange"); manage_convert.clicked.connect(self._manage_quick_convert_storage); cfl.addWidget(open_convert); cfl.addWidget(manage_convert)
        cg.addWidget(convert_storage_footer, 1, 0)
        cg.addWidget(convert_status_footer, 1, 1)
        cg.addWidget(convert_actions_footer, 1, 2)
        cg.setColumnStretch(2, 1); layout.addWidget(convert); self.quick_convert_drop.pathChanged.connect(self._quick_convert_requested)

        self._refresh_quick_storage(); self._refresh_quick_convert_storage()
        return page

    def _metric(self, title, value, sub="", width=None, bind=None):
        card = QFrame(); card.setProperty("role", "metric"); card.setFixedHeight(68)
        if width: card.setFixedWidth(width)
        layout = QVBoxLayout(card); layout.setContentsMargins(6, 5, 6, 5); layout.setSpacing(0)
        title_label = QLabel(title); title_label.setProperty("role", "metricTitle"); title_label.setAlignment(Qt.AlignCenter); layout.addWidget(title_label)
        value_label = QLabel(value); value_label.setProperty("role", "metricValue"); value_label.setAlignment(Qt.AlignCenter); layout.addWidget(value_label, 1)
        sub_label = QLabel(sub); sub_label.setProperty("role", "metricSub"); sub_label.setAlignment(Qt.AlignCenter); layout.addWidget(sub_label)
        degree = QLabel(""); degree.setVisible(False)
        if title == "BPM": self.quick_bpm_value = value_label
        if bind == "quick_detected":
            self.quick_detected_value = value_label
            self.quick_detected_mode = self.quick_detected_modal = sub_label
            self.quick_detected_degree = degree
        if bind == "quick_relative":
            self.quick_relative_value = value_label
            self.quick_relative_mode = self.quick_relative_modal = sub_label
            self.quick_relative_degree = degree
        return card

    def _modes_metric(self):
        card = QFrame(); card.setProperty("role", "metric")
        layout = QVBoxLayout(card); layout.setContentsMargins(6, 5, 6, 4); layout.setSpacing(3)
        title = QLabel("RELATIVE MODES"); title.setProperty("role", "metricTitle"); layout.addWidget(title)
        row = QHBoxLayout(); row.setSpacing(4); self.quick_mode_labels = []
        for _ in range(5):
            pill = QFrame(); pill.setProperty("role", "inset"); pl = QVBoxLayout(pill); pl.setContentsMargins(2, 2, 2, 2); pl.setSpacing(0)
            key = QLabel("—"); key.setProperty("role", "modeName"); key.setAlignment(Qt.AlignCenter); degree = QLabel("—"); degree.setProperty("role", "modeDegree"); degree.setAlignment(Qt.AlignCenter)
            pl.addWidget(key); pl.addWidget(degree); row.addWidget(pill, 1); self.quick_mode_labels.append((key, degree))
        layout.addLayout(row, 1); self.quick_modes_note = QLabel("Scan a file to reveal its relative modes."); self.quick_modes_note.setProperty("role", "metricSub"); self.quick_modes_note.setAlignment(Qt.AlignCenter); layout.addWidget(self.quick_modes_note); return card

    def _populate_layer_cards(self, layers, empty_text=None, show_empty_icon=False):
        while self.quick_layer_grid.count():
            item = self.quick_layer_grid.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().setParent(None)
                item.widget().deleteLater()
        self.layer_cards = []
        self.quick_layers_empty_state = None; self.quick_layers_empty_icon = None
        if layers:
            rows = (len(layers) + 2) // 3
            for index, layer in enumerate(layers):
                card = V16LayerCard(layer); card.playRequested.connect(self._toggle_layer_playback); card.seekRequested.connect(self._seek_layer)
                self.quick_layer_grid.addWidget(card, index // 3, index % 3); self.layer_cards.append(card)
            self.quick_layer_content.setMinimumHeight(8 + rows * 86)
            self.quick_layer_grid.setRowStretch(rows, 1); return
        self.quick_layer_content.setMinimumHeight(0)
        state = QWidget(); state.setProperty("role", "quickLayersEmpty"); sl = QVBoxLayout(state); sl.setContentsMargins(8, 8, 8, 8); sl.setSpacing(4); sl.addStretch()
        if show_empty_icon:
            self.quick_layers_empty_icon = LineIcon("layers", "#777e85", 36); sl.addWidget(self.quick_layers_empty_icon, 0, Qt.AlignHCenter)
        self.quick_layers_empty_label = QLabel(empty_text or "No layers detected."); self.quick_layers_empty_label.setProperty("role", "statusDetail"); self.quick_layers_empty_label.setAlignment(Qt.AlignCenter); sl.addWidget(self.quick_layers_empty_label); sl.addStretch()
        self.quick_layers_empty_state = state; self.quick_layer_grid.addWidget(state, 0, 0, 1, 3); self.quick_layer_grid.setRowStretch(0, 1)

    def _connect_stem_controls(self):
        self.layer_switch.toggled.connect(self._sync_stem_state); self.key_switch.toggled.connect(self._sync_stem_state); self.convert_switch.toggled.connect(self._sync_stem_state)
        self.target_bpm_switch.toggled.connect(self._sync_stem_state); self.target_key_switch.toggled.connect(self._sync_stem_state)
        self.target_bpm_input.textChanged.connect(self._sync_stem_state)
        self.input_drop.pathChanged.connect(self._source_changed); self.change_root_button.clicked.connect(self._change_storage_root); self.open_folder_button.clicked.connect(self._open_current_destination)
        self.copy_destination_button.clicked.connect(lambda: self._set_destination_mode("copy_to_output")); self.rename_destination_button.clicked.connect(lambda: self._set_destination_mode("rename_in_place")); self.start_button.clicked.connect(self._start_batch)

    def _source_changed(self, path):
        self.source_path = path
        self.source_path_label.setText(path or "No folder selected"); self.source_path_label.setToolTip(path)
        self._update_destination_preview(); self._sync_stem_state()

    def _set_key_mode(self, mode):
        self.key_mode = mode
        for value, widget in self.mode_buttons.items(): widget.setProperty("active", value == mode); _repolish(widget)
        self._update_name_preview()

    def _set_accidentals(self, accidentals):
        self.accidentals = accidentals
        for value, widget in (("sharps", self.sharps_button), ("flats", self.flats_button)): widget.setProperty("active", value == accidentals); _repolish(widget)
        self._update_name_preview()

    def _set_quick_degree_reference(self, reference):
        self.quick_degree_reference = reference
        for value, widget in (("major", self.quick_major_button), ("minor", self.quick_minor_button)): widget.setProperty("active", value == reference); _repolish(widget)
        self._update_quick_scan_results()

    def _set_quick_accidentals(self, accidentals):
        self.quick_accidentals = accidentals
        for value, widget in (("sharps", self.quick_sharps_button), ("flats", self.quick_flats_button)): widget.setProperty("active", value == accidentals); _repolish(widget)
        self._update_quick_scan_results()

    def _update_destination_preview(self):
        pack_name = os.path.basename(self.source_path) if self.source_path else "Loop Pack Name"
        if self.custom_destination: root = self.custom_destination
        elif self.layer_switch.isChecked(): root = self.storage.category_path("extractions")
        elif self.convert_switch.isChecked(): root = self.storage.category_path("converted")
        else: root = self.storage.category_path("analyzed")
        preview = self.source_path if self.destination_mode == "rename_in_place" and self.source_path else os.path.join(root, pack_name)
        self.destination_path_label.setFullText(preview)

    def _current_destination(self):
        if self.destination_mode == "rename_in_place" and self.source_path: return self.source_path
        if self.custom_destination: return self.custom_destination
        if self.layer_switch.isChecked(): return self.storage.category_path("extractions")
        if self.convert_switch.isChecked(): return self.storage.category_path("converted")
        return self.storage.category_path("analyzed")

    def select_tab(self, index):
        self.pages.setCurrentIndex(index); self.stem_tab.setActive(index == 0); self.quick_tab.setActive(index == 1)

    @staticmethod
    def _valid_bpm(text):
        try:
            value = int(str(text).strip())
        except (TypeError, ValueError):
            return None
        return value if 1 <= value <= 999 else None

    def _sync_quick_target_fields(self, *_):
        extract_busy = bool(getattr(self, "quick_extract_busy", False))
        convert_busy = bool(getattr(self, "quick_convert_busy", False))
        self.quick_extract_bpm.setEnabled(self.quick_extract_bpm_switch.isChecked() and not extract_busy)
        self.quick_extract_key.setEnabled(self.quick_extract_key_switch.isChecked() and not extract_busy)
        self.quick_convert_bpm.setEnabled(self.quick_convert_bpm_switch.isChecked() and not convert_busy)
        self.quick_convert_key.setEnabled(self.quick_convert_key_switch.isChecked() and not convert_busy)
        self.quick_extract_bpm_switch.setEnabled(not extract_busy)
        self.quick_extract_key_switch.setEnabled(not extract_busy)
        self.quick_convert_bpm_switch.setEnabled(not convert_busy)
        self.quick_convert_key_switch.setEnabled(not convert_busy)

    def _update_name_preview(self):
        super()._update_name_preview()
        if hasattr(self, "name_preview_label"):
            text = self.name_preview_label.text()
            if text.startswith("♫   "):
                self.name_preview_label.setText(text[4:])

    def _update_quick_scan_results(self):
        super()._update_quick_scan_results()
        if not hasattr(self, "quick_bpm_value"):
            return
        bpm = canonical_loop_bpm((self.quick_scan_result or {}).get("bpm"))
        self.quick_bpm_value.setText(str(bpm) if bpm else "—")
        if self.quick_scan_result:
            for prefix in ("quick_detected", "quick_relative"):
                modal = getattr(self, f"{prefix}_modal")
                degree = getattr(self, f"{prefix}_degree")
                modal.setText(f"{modal.text()} · {degree.text()}")

    def _set_destination_mode(self, mode):
        if mode not in ("copy_to_output", "rename_in_place"):
            raise ValueError(f"Unknown destination mode: {mode}")
        self.destination_mode = mode
        for value, widget in (
            ("copy_to_output", self.copy_destination_button),
            ("rename_in_place", self.rename_destination_button),
        ):
            widget.setProperty("active", value == mode)
            _repolish(widget)
        self._update_destination_preview()

    def _processing_settings(self):
        bpm = self._valid_bpm(self.target_bpm_input.text())
        return {
            "enabled": self.key_switch.isChecked(),
            "extract_enabled": self.layer_switch.isChecked(),
            "mode": self.key_mode,
            "accidentals": self.accidentals,
            "destination_mode": self.destination_mode,
            "token_order": list(self.token_order),
            "convert_enabled": self.convert_switch.isChecked(),
            "target_bpm_enabled": self.target_bpm_switch.isChecked(),
            "target_bpm": bpm,
            "target_key_enabled": self.target_key_switch.isChecked(),
            "target_key": self.target_key_combo.currentText(),
        }

    def _sync_stem_state(self, *_):
        extract = self.layer_switch.isChecked()
        key = self.key_switch.isChecked()
        convert = self.convert_switch.isChecked()
        target_active = self.target_bpm_switch.isChecked() or self.target_key_switch.isChecked()
        bpm_valid = not self.target_bpm_switch.isChecked() or self._valid_bpm(self.target_bpm_input.text()) is not None
        requires_engine = key or convert
        engine_ready = self.key_engine_state == "ready"

        self.target_bpm_switch.setEnabled(convert and not self.busy)
        self.target_key_switch.setEnabled(convert and not self.busy)
        self.target_bpm_input.setEnabled(convert and self.target_bpm_switch.isChecked() and not self.busy)
        self.target_key_combo.setEnabled(convert and self.target_key_switch.isChecked() and not self.busy)
        for widget in self.key_setting_widgets:
            widget.setEnabled(key and engine_ready and not self.busy)
        destination_enabled = key and not extract and not convert and engine_ready and not self.busy
        self.copy_destination_button.setEnabled(destination_enabled)
        self.rename_destination_button.setEnabled(destination_enabled)
        for toggle in (self.layer_switch, self.key_switch, self.convert_switch):
            toggle.setEnabled(not self.busy)
        self.input_drop.setEnabled(not self.busy)

        count = 0
        if self.source_path and os.path.isdir(self.source_path):
            count = sum(name.lower().endswith(".mp3") for name in os.listdir(self.source_path))
        self.files_stat.setText(f"{count} FILES")
        if requires_engine and self.key_engine_state == "loading":
            status = "Loading musical key engine…"
        elif requires_engine and self.key_engine_state == "failed":
            status = "Key engine unavailable."
        elif convert and not target_active:
            status = "Enable Target BPM, Target Key, or both."
        elif convert and not bpm_valid:
            status = "Enter a valid Target BPM."
        elif not (extract or key or convert):
            status = "Enable at least one operation."
        elif not self.source_path:
            status = "Choose a source folder."
        else:
            status = f"Ready to process {count} loop{'s' if count != 1 else ''}."

        can_start = bool(
            self.source_path and count and (extract or key or convert) and not self.busy
            and (engine_ready or not requires_engine)
            and (not convert or (target_active and bpm_valid))
        )
        self.start_button.setText(f"▶  PROCESS {count} LOOP{'S' if count != 1 else ''}")
        self.start_button.setEnabled(can_start)
        self.process_status.setText(status)
        engine_color = GREEN if self.key_engine_state == "ready" else RED if self.key_engine_state == "failed" else "#718089"
        self.engine_state_icon.color = QColor(engine_color)
        self.engine_state_icon.update()
        if self.destination_mode == "rename_in_place" and (extract or convert):
            self.destination_mode = "copy_to_output"
        self._update_destination_preview()
        self._update_name_preview()

    @Slot(object)
    def _key_engine_ready(self, analyzer):
        self.key_analyzer = analyzer
        self.key_engine_state = "ready"
        self.engine_state_icon.color = QColor(GREEN)
        self.engine_state_icon.update()
        self._sync_stem_state()
        if self.pending_quick_scan:
            path, self.pending_quick_scan = self.pending_quick_scan, ""
            self._run_quick_scan(path)
        if self.pending_quick_extract:
            path, self.pending_quick_extract = self.pending_quick_extract, ""
            self._run_quick_extract(path)
        if self.pending_quick_convert:
            path, self.pending_quick_convert = self.pending_quick_convert, ""
            self._run_quick_convert(path)
        QTimer.singleShot(0, self._start_midi_engine)

    @Slot(str)
    def _key_engine_failed(self, message):
        self.key_engine_state = "failed"
        self.engine_state_icon.color = QColor(RED)
        self.engine_state_icon.update()
        self.process_status.setText(f"Key engine unavailable: {message}")
        self._sync_stem_state()
        if self.quick_scan_busy:
            self._quick_scan_failed(message)
            self._quick_scan_finished()
        if self.quick_extract_busy and self.pending_quick_extract:
            self._quick_extract_failed(message)
            self._quick_extract_finished()
        if self.quick_convert_busy:
            self._quick_convert_failed(message)
            self._quick_convert_finished()
        QTimer.singleShot(0, self._start_midi_engine)

    def _quick_extract_requested(self, path):
        if not path or self.quick_extract_busy or self.quick_scan_busy or self.quick_convert_busy or self.busy:
            return
        bpm_enabled = self.quick_extract_bpm_switch.isChecked()
        key_enabled = self.quick_extract_key_switch.isChecked()
        bpm = self._valid_bpm(self.quick_extract_bpm.text())
        if bpm_enabled and bpm is None:
            self.quick_extract_status.setText("Enter a valid target BPM.")
            return
        self._invalidate_midi_jobs()
        self._populate_layer_cards([], "Extracting layers…")
        self.quick_extract_busy = True
        self.quick_extract_drop.setEnabled(False)
        effect = QGraphicsOpacityEffect(self.quick_extract_drop)
        effect.setOpacity(0.45)
        self.quick_extract_drop.setGraphicsEffect(effect)
        self.quick_extract_opacity = effect
        self.quick_extract_filename.setText(os.path.basename(path))
        self.quick_extract_check.setVisible(False)
        self.quick_extract_status.setText(
            "Loading musical key engine…" if (bpm_enabled or key_enabled) and self.key_engine_state != "ready"
            else "Extracting layers…"
        )
        self.quick_show_results.setEnabled(False)
        self._sync_quick_target_fields()
        if bpm_enabled or key_enabled:
            if self.key_engine_state == "ready":
                self._run_quick_extract(path)
            elif self.key_engine_state == "failed":
                self._quick_extract_failed("Key engine unavailable.")
                self._quick_extract_finished()
            else:
                self.pending_quick_extract = path
                if self.key_engine_state == "unloaded":
                    self._start_key_engine()
        else:
            self._run_quick_extract(path)

    def _quick_scan_requested(self, path):
        if self.quick_extract_busy or self.quick_convert_busy or self.busy:
            return
        super()._quick_scan_requested(path)

    def _run_quick_extract(self, path):
        session_name = os.path.splitext(os.path.basename(path))[0]
        self.quick_extract_session = self.storage.unique_session_folder("quick", session_name)
        self.quick_extract_thread = QThread(self)
        self.quick_extract_worker = QuickExtractWorkflowWorker(
            self.key_analyzer,
            path,
            self.quick_extract_session,
            bpm_enabled=self.quick_extract_bpm_switch.isChecked(),
            bpm=self._valid_bpm(self.quick_extract_bpm.text()),
            key_enabled=self.quick_extract_key_switch.isChecked(),
            key_pair=self.quick_extract_key.currentText(),
        )
        self.quick_extract_worker.moveToThread(self.quick_extract_thread)
        self.quick_extract_thread.started.connect(self.quick_extract_worker.run)
        self.quick_extract_worker.completed.connect(self._quick_extract_completed)
        self.quick_extract_worker.failed.connect(self._quick_extract_failed)
        self.quick_extract_worker.finished.connect(self.quick_extract_thread.quit)
        self.quick_extract_worker.finished.connect(self.quick_extract_worker.deleteLater)
        self.quick_extract_thread.finished.connect(self.quick_extract_thread.deleteLater)
        self.quick_extract_thread.finished.connect(self._quick_extract_finished)
        self.quick_extract_thread.start()

    @Slot()
    def _quick_extract_finished(self):
        self.quick_extract_busy = False
        self.pending_quick_extract = ""
        self.quick_extract_drop.setGraphicsEffect(None)
        self.quick_extract_opacity = None
        self.quick_extract_drop.setEnabled(True)
        self.quick_extract_thread = None
        self.quick_extract_worker = None
        self._sync_quick_target_fields()

    def _quick_convert_requested(self, path):
        if not path or self.quick_convert_busy or self.quick_extract_busy or self.quick_scan_busy or self.busy:
            return
        bpm_enabled = self.quick_convert_bpm_switch.isChecked()
        key_enabled = self.quick_convert_key_switch.isChecked()
        bpm = self._valid_bpm(self.quick_convert_bpm.text())
        if not (bpm_enabled or key_enabled):
            self.quick_convert_status.setText("Enable BPM, Key, or both before converting.")
            return
        if bpm_enabled and bpm is None:
            self.quick_convert_status.setText("Enter a valid target BPM.")
            return
        self.quick_convert_busy = True
        self.quick_convert_path = path
        self.quick_convert_drag.set_path("")
        self.quick_convert_filename.setText(os.path.basename(path))
        self.quick_convert_footer_filename.setText(os.path.basename(path))
        self.quick_convert_check.setVisible(False)
        self.quick_convert_footer_check.setVisible(False)
        status = "Loading musical key engine…" if self.key_engine_state != "ready" else "Converting…"
        self.quick_convert_status.setText(status)
        self.quick_convert_footer_status.setText(status)
        self.quick_convert_drop.setEnabled(False)
        self._sync_quick_target_fields()
        if self.key_engine_state == "ready":
            self._run_quick_convert(path)
        elif self.key_engine_state == "failed":
            self._quick_convert_failed("Key engine unavailable.")
            self._quick_convert_finished()
        else:
            self.pending_quick_convert = path
            if self.key_engine_state == "unloaded":
                self._start_key_engine()

    def _run_quick_convert(self, path):
        session_name = os.path.splitext(os.path.basename(path))[0]
        self.quick_convert_session = self.storage.unique_session_folder("convert", session_name)
        self.quick_convert_thread = QThread(self)
        self.quick_convert_worker = QuickConvertWorkflowWorker(
            self.key_analyzer,
            path,
            self.quick_convert_session,
            bpm_enabled=self.quick_convert_bpm_switch.isChecked(),
            bpm=self._valid_bpm(self.quick_convert_bpm.text()),
            key_enabled=self.quick_convert_key_switch.isChecked(),
            key_pair=self.quick_convert_key.currentText(),
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
        self.quick_convert_footer_check.setVisible(True)
        self.quick_convert_filename.setText(os.path.basename(result["path"]))
        self.quick_convert_filename.setToolTip(result["path"])
        self.quick_convert_footer_filename.setText(os.path.basename(result["path"]))
        self.quick_convert_footer_filename.setToolTip(result["path"])
        status = f"Converted to {result['target_bpm']} BPM · {result['target_key']} · {elapsed:.1f}s"
        self.quick_convert_status.setText(status)
        self.quick_convert_footer_status.setText(status)
        self.quick_convert_drag.set_path(result["path"])
        self._refresh_quick_convert_storage()

    @Slot(str)
    def _quick_convert_failed(self, message):
        self.quick_convert_drag.set_path("")
        self.quick_convert_footer_check.setVisible(False)
        self.quick_convert_footer_status.setText(f"Conversion failed: {message}")
        super()._quick_convert_failed(message)

    @Slot()
    def _quick_convert_finished(self):
        self.quick_convert_busy = False
        self.pending_quick_convert = ""
        self.quick_convert_drop.setEnabled(True)
        self.quick_convert_thread = None
        self.quick_convert_worker = None
        self._sync_quick_target_fields()

    def _start_batch(self):
        if self.busy or self.quick_scan_busy or self.quick_extract_busy or self.quick_convert_busy or not self.source_path:
            return
        extract = self.layer_switch.isChecked()
        key_enabled = self.key_switch.isChecked()
        convert = self.convert_switch.isChecked()
        if (key_enabled or convert) and self.key_engine_state != "ready":
            return
        if convert and not (self.target_bpm_switch.isChecked() or self.target_key_switch.isChecked()):
            return
        if self.target_bpm_switch.isChecked() and self._valid_bpm(self.target_bpm_input.text()) is None:
            return
        if key_enabled and not extract and not convert and self.destination_mode == "rename_in_place":
            answer = QMessageBox.warning(
                self,
                "Rename original loops?",
                "Stem Slicer will rename every MP3 in the source folder after checking for filename collisions. Continue?",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if answer != QMessageBox.Yes:
                return

        if self.destination_mode == "rename_in_place" and key_enabled and not extract and not convert:
            output = ""
            self.last_results = self.source_path
        else:
            pack_name = os.path.basename(self.source_path)
            if self.custom_destination:
                output = self.storage.unique_session_folder_in(self.custom_destination, pack_name)
            else:
                category = "extractions" if extract else "converted" if convert else "analyzed"
                output = self.storage.unique_session_folder(category, pack_name)
            self.last_results = output

        self.busy = True
        self.progress_bar.setValue(0)
        self.progress_counter.setText("0 / 0")
        self.success_stat.setText("0 SUCCESSFUL")
        self.error_stat.setText("0 ERRORS")
        self.process_status.setText("Preparing audio engine…")
        self._sync_stem_state()

        self.batch_thread = QThread(self)
        self.batch_worker = BatchWorkflowWorker(
            self.source_path,
            output,
            self._processing_settings(),
            analyzer=self.key_analyzer if key_enabled or convert else None,
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

    @Slot(object, object)
    def _batch_completed(self, failures, manifest):
        self.progress_bar.setValue(100)
        self.process_status.setText("Processing complete.")
        total = 0
        if self.source_path and os.path.isdir(self.source_path):
            total = sum(name.lower().endswith(".mp3") for name in os.listdir(self.source_path))
        failed_files = {item[0] for item in failures}
        self.success_stat.setText(f"{max(0, total - len(failed_files))} SUCCESSFUL")
        self.error_stat.setText(f"{len(failed_files)} ERRORS")
        self.last_manifest = manifest
        if failures:
            QMessageBox.warning(self, "Stem Slicer", f"Completed with {len(failed_files)} warning(s).")

    @Slot(str)
    def _batch_failed(self, message):
        self.process_status.setText(f"Processing stopped: {message}")
        self.error_stat.setText("1 ERROR")
        QMessageBox.critical(self, "Stem Slicer", message)

    def closeEvent(self, event):
        if self.batch_thread is not None and self.batch_thread.isRunning():
            self.process_status.setText("Finish the current batch before closing Stem Slicer.")
            event.ignore()
            return
        super().closeEvent(event)
