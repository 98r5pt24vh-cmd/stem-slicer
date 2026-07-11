import os
import sys

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from engine import process_audio
from filename_templates import TOKENS, parse_loop_filename, render_name
from theme import COLORS, application_stylesheet
from widgets import FolderDrop, ProcessModule, SegmentedControl, StudioRoot, SurfacePanel, TokenStrip


APP_NAME = "Stem Slicer"
APP_VERSION = "1.4 Qt Prototype"


def resource_path(*parts):
    root = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, *parts)


def image_label(path, width, height):
    label = QLabel()
    label.setAlignment(Qt.AlignCenter)
    label.setFixedSize(width, height)
    pixmap = QPixmap(path)
    if not pixmap.isNull():
        label.setPixmap(pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    return label


def panel():
    return SurfacePanel()


def add_shadow(widget, blur=24, y=6, opacity=85):
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur)
    shadow.setOffset(0, y)
    shadow.setColor(QColor(0, 0, 0, opacity))
    widget.setGraphicsEffect(shadow)


class ProcessingWorker(QObject):
    progress = Signal(int, int, str)
    completed = Signal(object, object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, source, output, settings):
        super().__init__()
        self.source = source
        self.output = output
        self.settings = settings

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
            )
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker_thread = None
        self.worker = None
        self.busy = False
        self.setWindowTitle(f"{APP_NAME} · {APP_VERSION}")
        self.setMinimumSize(980, 720)
        self.resize(1240, 900)
        icon_path = resource_path("assets", "app-icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self._build()
        self._connect()
        self._syncState()

    def _build(self):
        self.root = StudioRoot()
        self.setCentralWidget(self.root)
        root_layout = QVBoxLayout(self.root)
        root_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        root_layout.addWidget(scroll)

        viewport = QWidget()
        viewport.setStyleSheet("background: transparent;")
        scroll.setWidget(viewport)
        viewport_layout = QHBoxLayout(viewport)
        viewport_layout.setContentsMargins(22, 18, 22, 20)
        viewport_layout.addStretch(1)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        content.setMaximumWidth(1320)
        content.setMinimumWidth(920)
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)
        viewport_layout.addWidget(content, 10)
        viewport_layout.addStretch(1)

        self._buildHeader()
        self._buildProcessSelection()
        self._buildFolders()
        self._buildAdvanced()
        self._buildProgress()

    def _buildHeader(self):
        header = panel()
        header.setMinimumHeight(116)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(22, 14, 22, 14)
        layout.setSpacing(18)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        brand.addWidget(image_label(resource_path("assets", "antiworld-logo.png"), 64, 72))
        lockup = QVBoxLayout()
        lockup.setSpacing(1)
        made = QLabel("MADE WITH <3 BY")
        made.setObjectName("Eyebrow")
        anti = QLabel("ANTIWORLD")
        anti.setStyleSheet(f"font-size: 15px; font-weight: 900; color: {COLORS['red']};")
        lockup.addStretch()
        lockup.addWidget(made)
        lockup.addWidget(anti)
        lockup.addStretch()
        brand.addLayout(lockup)
        layout.addLayout(brand, 2)

        layout.addStretch(1)
        wordmark = image_label(resource_path("assets", "stem-slicer-wordmark.png"), 370, 88)
        layout.addWidget(wordmark, 0, Qt.AlignCenter)
        layout.addStretch(1)

        build = QVBoxLayout()
        build.setSpacing(3)
        build.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        system = QLabel("LOOP LAYER EXTRACTION SYSTEM")
        system.setObjectName("Muted")
        system.setAlignment(Qt.AlignRight)
        version = QLabel(APP_VERSION.upper())
        version.setObjectName("Version")
        version.setAlignment(Qt.AlignRight)
        build.addWidget(system)
        build.addWidget(version)
        layout.addLayout(build, 2)
        self.content_layout.addWidget(header)

    def _buildProcessSelection(self):
        row = QHBoxLayout()
        row.setSpacing(14)
        self.slicer_module = ProcessModule(
            "01 / Core process",
            "STEM SLICER",
            "Extract every loop into clean, production-ready layers while preserving its original name.",
            checked=True,
            primary=True,
        )
        self.key_module = ProcessModule(
            "02 / Optional process",
            "KEY ANALYSIS",
            "Detect musical keys and organize output names before processing.",
            checked=False,
        )
        add_shadow(self.slicer_module, blur=22, y=5, opacity=75)
        row.addWidget(self.slicer_module, 3)
        row.addWidget(self.key_module, 2)
        self.content_layout.addLayout(row)

    def _buildFolders(self):
        row = QHBoxLayout()
        row.setSpacing(14)
        self.input_folder = FolderDrop("input", "Input folder", "Drop a folder containing MP3 loops")
        self.output_folder = FolderDrop("output", "Output folder", "Drop the export destination")
        row.addWidget(self.input_folder, 1)
        row.addWidget(self.output_folder, 1)
        self.content_layout.addLayout(row)

    def _buildAdvanced(self):
        heading = QHBoxLayout()
        advanced = QLabel("ADVANCED KEY WORKFLOW")
        advanced.setObjectName("Eyebrow")
        note = QLabel("Naming becomes active automatically with Key Analysis")
        note.setObjectName("Muted")
        heading.addWidget(advanced)
        heading.addSpacing(10)
        heading.addWidget(note)
        heading.addStretch()
        self.content_layout.addLayout(heading)

        row = QHBoxLayout()
        row.setSpacing(14)

        key_panel = panel()
        self.key_settings_panel = key_panel
        key_layout = QVBoxLayout(key_panel)
        key_layout.setContentsMargins(18, 15, 18, 16)
        key_layout.setSpacing(9)
        title = QLabel("KEY FORMAT")
        title.setObjectName("SectionTitle")
        description = QLabel("Choose how detected tonalities are written.")
        description.setObjectName("SectionDescription")
        key_layout.addWidget(title)
        key_layout.addWidget(description)

        mode_label = QLabel("TONAL MODE")
        mode_label.setObjectName("Eyebrow")
        key_layout.addWidget(mode_label)
        self.mode_control = SegmentedControl(
            [
                ("detected", "DETECTED"),
                ("relative_minor", "RELATIVE MINOR"),
                ("relative_major", "RELATIVE MAJOR"),
            ],
            "relative_minor",
        )
        key_layout.addWidget(self.mode_control)

        accidental_label = QLabel("ACCIDENTALS")
        accidental_label.setObjectName("Eyebrow")
        key_layout.addWidget(accidental_label)
        self.accidental_control = SegmentedControl(
            [("sharps", "SHARPS  #"), ("flats", "FLATS  b")],
            "sharps",
        )
        key_layout.addWidget(self.accidental_control)

        self.destination_box = SurfacePanel(inset=True)
        destination_layout = QVBoxLayout(self.destination_box)
        destination_layout.setContentsMargins(12, 10, 12, 11)
        destination_layout.setSpacing(6)
        destination_title = QLabel("ANALYSIS-ONLY DESTINATION")
        destination_title.setObjectName("Eyebrow")
        destination_layout.addWidget(destination_title)
        self.destination_control = SegmentedControl(
            [("copy_to_output", "COPY TO OUTPUT"), ("rename_in_place", "RENAME ORIGINALS")],
            "copy_to_output",
        )
        destination_layout.addWidget(self.destination_control)
        key_layout.addWidget(self.destination_box)
        key_layout.addStretch()
        key_panel.setMinimumHeight(236)

        naming_panel = panel()
        naming_layout = QVBoxLayout(naming_panel)
        naming_layout.setContentsMargins(18, 15, 18, 16)
        naming_layout.setSpacing(8)
        naming_header = QHBoxLayout()
        naming_copy = QVBoxLayout()
        naming_copy.setSpacing(2)
        naming_title = QLabel("OUTPUT NAME STRUCTURE")
        naming_title.setObjectName("SectionTitle")
        self.naming_description = QLabel("Enabled automatically when Key Analysis is active.")
        self.naming_description.setObjectName("SectionDescription")
        naming_copy.addWidget(naming_title)
        naming_copy.addWidget(self.naming_description)
        naming_header.addLayout(naming_copy)
        naming_header.addStretch()
        drag_hint = QLabel("DRAG TO REORDER")
        drag_hint.setObjectName("Eyebrow")
        naming_header.addWidget(drag_hint, 0, Qt.AlignTop)
        naming_layout.addLayout(naming_header)

        self.token_strip = TokenStrip(TOKENS)
        naming_layout.addWidget(self.token_strip)

        preview_box = SurfacePanel(inset=True)
        preview_layout = QVBoxLayout(preview_box)
        preview_layout.setContentsMargins(12, 8, 12, 9)
        preview_layout.setSpacing(2)
        preview_title = QLabel("LIVE PREVIEW")
        preview_title.setObjectName("Eyebrow")
        self.preview = QLabel()
        self.preview.setObjectName("PreviewValue")
        self.preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        preview_layout.addWidget(preview_title)
        preview_layout.addWidget(self.preview)
        naming_layout.addWidget(preview_box)
        naming_layout.addStretch()

        row.addWidget(key_panel, 5)
        row.addWidget(naming_panel, 7)
        self.content_layout.addLayout(row)

    def _buildProgress(self):
        process_panel = panel()
        process_layout = QVBoxLayout(process_panel)
        process_layout.setContentsMargins(18, 12, 18, 14)
        process_layout.setSpacing(8)
        top = QHBoxLayout()
        label = QLabel("PROCESS")
        label.setObjectName("Eyebrow")
        self.status = QLabel("Ready. Drop folders or use Browse.")
        self.status.setObjectName("Muted")
        top.addWidget(label)
        top.addSpacing(8)
        top.addWidget(self.status, 1)
        self.counter = QLabel("0 / 0")
        self.counter.setObjectName("Version")
        top.addWidget(self.counter)
        process_layout.addLayout(top)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        process_layout.addWidget(self.progress)
        self.content_layout.addWidget(process_panel)

        self.start_button = QPushButton("EXTRACT LAYERS")
        self.start_button.setObjectName("PrimaryAction")
        self.start_button.setMinimumHeight(50)
        self.start_button.setCursor(Qt.PointingHandCursor)
        self.content_layout.addWidget(self.start_button)

    def _connect(self):
        self.slicer_module.toggled.connect(self._syncState)
        self.key_module.toggled.connect(self._syncState)
        self.input_folder.pathChanged.connect(self._folderChanged)
        self.output_folder.pathChanged.connect(self._syncState)
        self.mode_control.changed.connect(self._updatePreview)
        self.accidental_control.changed.connect(self._updatePreview)
        self.destination_control.changed.connect(self._syncState)
        self.token_strip.orderChanged.connect(self._updatePreview)
        self.start_button.clicked.connect(self._start)

    def _folderChanged(self, path):
        self._updatePreview()
        self._syncState()

    def _syncState(self, *_):
        key_enabled = self.key_module.isChecked()
        extract_enabled = self.slicer_module.isChecked()
        self.mode_control.setEnabled(key_enabled and not self.busy)
        self.accidental_control.setEnabled(key_enabled and not self.busy)
        self.token_strip.setEnabled(key_enabled and not self.busy)
        self.destination_box.setVisible(key_enabled and not extract_enabled)
        self.key_settings_panel.setMinimumHeight(296 if key_enabled and not extract_enabled else 236)
        self.destination_control.setEnabled(key_enabled and not self.busy)
        destination = self.destination_control.value()
        output_required = extract_enabled or destination == "copy_to_output"
        self.output_folder.setEnabled(not self.busy and output_required)
        self.output_folder.setRequired(output_required)
        self.input_folder.setEnabled(not self.busy)
        self.slicer_module.setEnabled(not self.busy)
        self.key_module.setEnabled(not self.busy)

        if extract_enabled and key_enabled:
            action = "ANALYZE KEYS + EXTRACT LAYERS"
        elif extract_enabled:
            action = "EXTRACT LAYERS"
        elif key_enabled:
            action = "ANALYZE + ORGANIZE LOOPS"
        else:
            action = "SELECT A PROCESS"
        self.start_button.setText(action)

        valid = bool(self.input_folder.path) and (not output_required or bool(self.output_folder.path))
        valid = valid and (extract_enabled or key_enabled) and not self.busy
        self.start_button.setEnabled(valid)

        if not self.busy:
            if not extract_enabled and not key_enabled:
                self.status.setText("Enable Stem Slicer or Key Analysis.")
            elif not self.input_folder.path:
                self.status.setText("Choose an input folder to begin.")
            elif output_required and not self.output_folder.path:
                self.status.setText("Choose an output folder.")
            else:
                self.status.setText("Ready to process.")
        self.naming_description.setText(
            "Drag the active fields into the exact output order."
            if key_enabled
            else "Original filenames are preserved while Key Analysis is off."
        )
        self._updatePreview()

    def _exampleFilename(self):
        source = self.input_folder.path
        if source and os.path.isdir(source):
            files = sorted(item for item in os.listdir(source) if item.lower().endswith(".mp3"))
            if files:
                return files[0]
        return "L CALLMEUR3 137 +NRGY.mp3"

    def _updatePreview(self, *_):
        filename = self._exampleFilename()
        if not self.key_module.isChecked():
            stem, extension = os.path.splitext(filename)
            preview = f"{stem}_L1{extension}" if self.slicer_module.isChecked() else filename
        else:
            parts = parse_loop_filename(filename)
            layer_index = 1 if self.slicer_module.isChecked() else None
            preview = render_name(parts, self.token_strip.tokens, "A#m", layer_index)
        self.preview.setText(preview)
        self.preview.setToolTip(preview)

    def _start(self):
        if self.busy:
            return
        key_enabled = self.key_module.isChecked()
        extract_enabled = self.slicer_module.isChecked()
        destination = self.destination_control.value()
        if key_enabled and not extract_enabled and destination == "rename_in_place":
            answer = QMessageBox.warning(
                self,
                "Rename original loops?",
                "Stem Slicer will rename every MP3 in the input folder. A CSV manifest will be created first. Continue?",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if answer != QMessageBox.Yes:
                return

        settings = {
            "enabled": key_enabled,
            "extract_enabled": extract_enabled,
            "mode": self.mode_control.value(),
            "accidentals": self.accidental_control.value(),
            "destination_mode": destination,
            "token_order": list(self.token_strip.tokens),
        }
        self.busy = True
        self.progress.setValue(0)
        self.counter.setText("0 / 0")
        self.status.setText("Preparing audio engine...")
        self._syncState()

        self.worker_thread = QThread(self)
        self.worker = ProcessingWorker(self.input_folder.path, self.output_folder.path, settings)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._progressChanged)
        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(self._threadFinished)
        self.worker_thread.start()

    @Slot(int, int, str)
    def _progressChanged(self, current, total, status):
        percent = int((current / total) * 100) if total else 0
        self.progress.setValue(max(0, min(100, percent)))
        self.counter.setText(f"{current} / {total}")
        self.status.setText(status)

    @Slot(object, object)
    def _completed(self, failures, manifest):
        self.progress.setValue(100)
        self.status.setText("Processing complete.")
        details = "All files were processed successfully."
        if failures:
            details = f"Processing completed with {len(failures)} key-analysis warning(s)."
            visible_failures = "\n".join(
                f"- {filename}: {message}"
                for filename, message in failures[:6]
            )
            details += f"\n\n{visible_failures}"
            if len(failures) > 6:
                details += f"\n- ...and {len(failures) - 6} more"
        if manifest:
            details += f"\n\nRename manifest:\n{manifest}"
        QMessageBox.information(self, "Stem Slicer", details)

    @Slot(str)
    def _failed(self, message):
        self.status.setText("Processing stopped.")
        QMessageBox.critical(self, "Stem Slicer", message)

    @Slot()
    def _threadFinished(self):
        self.busy = False
        self.worker_thread = None
        self.worker = None
        self._syncState()

    def closeEvent(self, event):
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.information(self, "Stem Slicer", "Processing is still running. Wait for it to finish before closing.")
            event.ignore()
            return
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setStyle("Fusion")
    app.setStyleSheet(application_stylesheet())
    icon_path = resource_path("assets", "app-icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    window = MainWindow()
    window.show()

    screenshot_path = os.environ.get("STEM_SLICER_SCREENSHOT_PATH")
    if screenshot_path:
        def capture():
            screen = window.screen()
            screen.grabWindow(window.winId()).save(screenshot_path)
            app.quit()
        QTimer.singleShot(1200, capture)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
