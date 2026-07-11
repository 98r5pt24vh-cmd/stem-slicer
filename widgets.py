import os

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from theme import COLORS


def paint_surface(widget, painter, inset=False):
    painter.setRenderHint(QPainter.Antialiasing)
    fill = COLORS["surface_pressed"] if inset else COLORS["surface"]
    border = COLORS["border_soft"] if inset else COLORS["border"]
    painter.setPen(QPen(QColor(border), 1))
    painter.setBrush(QColor(fill))
    painter.drawRoundedRect(QRectF(widget.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)


class SurfacePanel(QFrame):
    def __init__(self, inset=False, parent=None):
        super().__init__(parent)
        self.inset = inset
        self.setObjectName("Inset" if inset else "Panel")

    def paintEvent(self, event):
        super().paintEvent(event)
        paint_surface(self, QPainter(self), self.inset)


class StudioRoot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StudioRoot")

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setPen(QPen(QColor(255, 255, 255, 9), 1))
        step = 48
        for x in range(0, self.width(), step):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), step):
            painter.drawLine(0, y, self.width(), y)


class SegmentedControl(QWidget):
    changed = Signal(str)

    def __init__(self, options, selected, parent=None):
        super().__init__(parent)
        self.buttons = {}
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        for value, label in options:
            button = QPushButton(label)
            button.setObjectName("Segment")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setFixedHeight(34)
            button.clicked.connect(lambda checked=False, item=value: self.changed.emit(item))
            self.group.addButton(button)
            self.buttons[value] = button
            layout.addWidget(button)
        self.setValue(selected)

    def value(self):
        for value, button in self.buttons.items():
            if button.isChecked():
                return value
        return next(iter(self.buttons))

    def setValue(self, value):
        if value in self.buttons:
            self.buttons[value].setChecked(True)

    def setEnabled(self, enabled):
        super().setEnabled(enabled)
        for button in self.buttons.values():
            button.setEnabled(enabled)


class ProcessModule(QFrame):
    toggled = Signal(bool)

    def __init__(self, eyebrow, title, description, checked=False, primary=False, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setProperty("active", checked)
        self.primary = primary
        self.setMinimumHeight(116)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 17, 20, 16)
        layout.setSpacing(5)

        top = QHBoxLayout()
        top.setSpacing(12)
        copy = QVBoxLayout()
        copy.setSpacing(3)
        eyebrow_label = QLabel(eyebrow.upper())
        eyebrow_label.setObjectName("Eyebrow")
        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        title_font = title_label.font()
        title_font.setPointSize(18 if primary else 15)
        title_font.setWeight(QFont.Weight.Black)
        title_label.setFont(title_font)
        description_label = QLabel(description)
        description_label.setObjectName("SectionDescription")
        description_label.setWordWrap(True)
        copy.addWidget(eyebrow_label)
        copy.addWidget(title_label)
        copy.addWidget(description_label)
        top.addLayout(copy, 1)

        self.toggle = QPushButton()
        self.toggle.setCheckable(True)
        self.toggle.setChecked(checked)
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.setFixedSize(88 if primary else 78, 36)
        self.toggle.clicked.connect(self.setChecked)
        top.addWidget(self.toggle, 0, Qt.AlignTop)
        layout.addLayout(top)
        self._refresh()

    def isChecked(self):
        return self.toggle.isChecked()

    def setChecked(self, checked):
        checked = bool(checked)
        self.toggle.blockSignals(True)
        self.toggle.setChecked(checked)
        self.toggle.blockSignals(False)
        self.setProperty("active", checked)
        self._refresh()
        self.toggled.emit(checked)

    def _refresh(self):
        checked = self.toggle.isChecked()
        self.toggle.setText("ACTIVE" if checked else "OFF")
        self.toggle.setStyleSheet(
            f"QPushButton {{ background: {COLORS['red'] if checked else '#25282d'};"
            f" color: {'white' if checked else COLORS['muted']};"
            f" border: 1px solid {'#ff674f' if checked else '#484c53'};"
            f" border-bottom: 2px solid {COLORS['red_dark'] if checked else '#090a0c'};"
            " border-radius: 5px; font-size: 10px; font-weight: 900; }"
            f"QPushButton:hover {{ background: {COLORS['red_hover'] if checked else '#30343a'}; }}"
        )
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and not self.toggle.geometry().contains(event.position().toPoint()):
            self.setChecked(not self.isChecked())
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        paint_surface(self, painter)
        painter.setRenderHint(QPainter.Antialiasing)
        accent = QColor(COLORS["red"] if self.isChecked() else "#393d43")
        painter.setPen(Qt.NoPen)
        painter.setBrush(accent)
        painter.drawRoundedRect(QRectF(0, 10, 4, self.height() - 20), 2, 2)


class FolderDrop(QFrame):
    pathChanged = Signal(str)

    def __init__(self, role, title, description, parent=None):
        super().__init__(parent)
        self.role = role
        self.path = ""
        self.highlighted = False
        self.setObjectName("Panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setMinimumHeight(102)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 16, 14)
        layout.setSpacing(6)
        heading = QHBoxLayout()
        heading.setSpacing(10)
        title_label = QLabel(title.upper())
        title_label.setObjectName("Eyebrow")
        heading.addWidget(title_label)
        heading.addStretch()
        self.browse = QPushButton("BROWSE")
        self.browse.setFixedWidth(92)
        self.browse.clicked.connect(self.chooseFolder)
        heading.addWidget(self.browse)
        layout.addLayout(heading)
        description_label = QLabel(description)
        description_label.setObjectName("SectionDescription")
        layout.addWidget(description_label)
        self.path_label = QLabel("Drop a folder here")
        self.path_label.setObjectName("PathValue")
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.path_label)

    def chooseFolder(self):
        selected = QFileDialog.getExistingDirectory(self, "Choose folder", self.path or os.path.expanduser("~"))
        if selected:
            self.setPath(selected)

    def setPath(self, path):
        path = os.path.abspath(path) if path else ""
        if path and not os.path.isdir(path):
            return
        self.path = path
        display = path if path else "Drop a folder here"
        metrics = QFontMetrics(self.path_label.font())
        self.path_label.setText(metrics.elidedText(display, Qt.ElideMiddle, max(160, self.path_label.width())))
        self.path_label.setToolTip(path)
        self.pathChanged.emit(path)

    def setRequired(self, required):
        self.setToolTip("Required" if required else "Not required when renaming original loops")

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile() and os.path.isdir(urls[0].toLocalFile()):
            event.acceptProposedAction()
            self.highlighted = True
            self.update()

    def dragLeaveEvent(self, event):
        self.highlighted = False
        self.update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.highlighted = False
        urls = event.mimeData().urls()
        if urls:
            self.setPath(urls[0].toLocalFile())
            event.acceptProposedAction()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        paint_surface(self, painter)
        if self.highlighted:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(QColor(COLORS["red"]), 2))
            painter.setBrush(QColor(255, 59, 33, 20))
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 7, 7)


class TokenStrip(QWidget):
    orderChanged = Signal(list)

    def __init__(self, tokens, parent=None):
        super().__init__(parent)
        self.tokens = list(tokens)
        self.drag_index = -1
        self.drag_offset = 0.0
        self.drag_x = 0.0
        self.press_x = 0.0
        self.drag_active = False
        self.setMinimumHeight(66)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(620, 66)

    def _font(self):
        font = QFont("SF Mono")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(10)
        font.setWeight(QFont.Weight.Bold)
        return font

    def _width(self, token):
        return max(100, QFontMetrics(self._font()).horizontalAdvance(token) + 42)

    def chipRects(self):
        widths = [self._width(token) for token in self.tokens]
        gap = 10
        total = sum(widths) + gap * max(0, len(widths) - 1)
        start = max(12, (self.width() - total) / 2)
        rects = []
        x = start
        for width in widths:
            rects.append(QRectF(x, 13, width, 40))
            x += width + gap
        return rects

    def _drawChip(self, painter, token, rect, active=False):
        enabled = self.isEnabled()
        if active:
            fill, border, text = COLORS["red"], "#ff745f", "#ffffff"
        elif enabled:
            fill, border, text = "#292c31", "#50555e", "#f0f1f3"
        else:
            fill, border, text = "#17191c", "#292c31", "#60656c"
        painter.setPen(QPen(QColor(border), 1))
        painter.setBrush(QColor(fill))
        painter.drawRoundedRect(rect, 5, 5)
        painter.setPen(QColor(text))
        painter.setFont(self._font())
        painter.drawText(rect, Qt.AlignCenter, token)
        if enabled and not active:
            grip_x = rect.left() + 12
            painter.setPen(QPen(QColor("#6b7078"), 1))
            for offset in (-3, 1, 5):
                painter.drawLine(QPoint(int(grip_x), int(rect.center().y() + offset)), QPoint(int(grip_x + 8), int(rect.center().y() + offset)))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#2b2e33"), 1))
        painter.setBrush(QColor("#0f1113"))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 6, 6)
        rects = self.chipRects()
        for index, (token, rect) in enumerate(zip(self.tokens, rects)):
            if not (self.drag_active and index == self.drag_index):
                self._drawChip(painter, token, rect)
        if self.drag_active and self.drag_index >= 0:
            slot = rects[self.drag_index]
            dragged = QRectF(self.drag_x, slot.y() - 3, slot.width(), slot.height())
            painter.setBrush(QColor(0, 0, 0, 90))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(dragged.translated(0, 5), 6, 6)
            self._drawChip(painter, self.tokens[self.drag_index], dragged, True)

    def _indexAt(self, point):
        for index, rect in enumerate(self.chipRects()):
            if rect.contains(point):
                return index
        return -1

    def mousePressEvent(self, event):
        if not self.isEnabled() or event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        self.drag_index = self._indexAt(event.position())
        if self.drag_index >= 0:
            rect = self.chipRects()[self.drag_index]
            self.press_x = event.position().x()
            self.drag_offset = self.press_x - rect.x()
            self.drag_x = rect.x()
            self.setCursor(QCursor(Qt.ClosedHandCursor))
        self.update()

    def mouseMoveEvent(self, event):
        if self.drag_index < 0:
            if self.isEnabled():
                self.setCursor(Qt.OpenHandCursor if self._indexAt(event.position()) >= 0 else Qt.ArrowCursor)
            return super().mouseMoveEvent(event)
        pointer_x = event.position().x()
        if not self.drag_active and abs(pointer_x - self.press_x) < 6:
            return
        self.drag_active = True
        rects = self.chipRects()
        width = rects[self.drag_index].width()
        self.drag_x = max(8.0, min(self.width() - width - 8.0, pointer_x - self.drag_offset))
        changed = False
        while self.drag_index > 0:
            left = rects[self.drag_index - 1]
            if pointer_x >= left.center().x():
                break
            token = self.tokens.pop(self.drag_index)
            self.drag_index -= 1
            self.tokens.insert(self.drag_index, token)
            rects = self.chipRects()
            changed = True
        while self.drag_index < len(self.tokens) - 1:
            right = rects[self.drag_index + 1]
            if pointer_x <= right.center().x():
                break
            token = self.tokens.pop(self.drag_index)
            self.drag_index += 1
            self.tokens.insert(self.drag_index, token)
            rects = self.chipRects()
            changed = True
        if changed:
            self.orderChanged.emit(list(self.tokens))
        self.update()

    def mouseReleaseEvent(self, event):
        if self.drag_index >= 0 and self.drag_active:
            self.orderChanged.emit(list(self.tokens))
        self.drag_index = -1
        self.drag_active = False
        self.unsetCursor()
        self.update()
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if self.drag_index < 0:
            self.unsetCursor()
        super().leaveEvent(event)
