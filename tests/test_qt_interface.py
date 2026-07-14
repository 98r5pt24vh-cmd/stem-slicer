import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STEM_SLICER_DISABLE_ENGINE_AUTOSTART", "1")

from PySide6.QtCore import QMimeData, QPoint, QPointF, QSize, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtMultimedia import QMediaPlayer

from app import DropZone, KeyEngineLoader, LayerCard, LineIcon, MainWindow, QuickExtractManagerDialog, QuickExtractWorker, WaveformWidget
from filename_templates import TOKENS
from theme import application_stylesheet
from widgets import TokenStrip
from storage import StorageManager


APP = QApplication.instance() or QApplication([])


class MemorySettings:
    def __init__(self, root):
        self.values = {"storage/root": root}

    def value(self, key, default="", type=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value


class QtInterfaceTests(unittest.TestCase):
    def test_key_engine_loader_warms_model_before_ready(self):
        events = []

        class FakeAnalyzer:
            def __init__(self, workers=1):
                events.append(("created", workers))

            def start(self):
                events.append(("started",))

            def analyze(self, path):
                events.append(("warmed", os.path.basename(path)))
                return {"camelot": "9A"}

        loader = KeyEngineLoader()
        loader.ready.connect(lambda analyzer: events.append(("ready", analyzer.__class__.__name__)))
        with patch("app.KeyAnalyzer", FakeAnalyzer):
            loader.run()
        APP.processEvents()

        self.assertIn(("warmed", "key-engine-warmup.wav"), events)
        self.assertIn(("ready", "FakeAnalyzer"), events)
        self.assertLess(
            events.index(("warmed", "key-engine-warmup.wav")),
            events.index(("ready", "FakeAnalyzer")),
        )

    def test_main_pages_are_stable_and_navigable(self):
        window = MainWindow()
        window.show()
        APP.processEvents()

        self.assertEqual(window.pages.count(), 2)
        self.assertEqual(window.pages.currentIndex(), 0)
        self.assertTrue(window.stem_tab.active)
        self.assertFalse(window.quick_tab.active)
        self.assertEqual((window.width(), window.height()), (1440, 864))
        self.assertEqual(window.minimumSize(), QSize(1440, 864))
        self.assertEqual(window.maximumSize(), QSize(1440, 864))

        original_pages = tuple(window.pages.widget(index) for index in range(2))
        QTest.mouseClick(window.quick_tab, Qt.LeftButton)
        APP.processEvents()
        self.assertEqual(window.pages.currentIndex(), 1)
        self.assertFalse(window.stem_tab.active)
        self.assertTrue(window.quick_tab.active)

        QTest.mouseClick(window.stem_tab, Qt.LeftButton)
        APP.processEvents()
        self.assertEqual(window.pages.currentIndex(), 0)
        self.assertEqual(original_pages, tuple(window.pages.widget(index) for index in range(2)))
        window.close()

    def test_quick_scan_locks_drop_while_engine_loads(self):
        with tempfile.TemporaryDirectory() as root:
            audio = os.path.join(root, "loop.wav")
            open(audio, "wb").close()
            window = MainWindow()
            window._start_key_engine = lambda: setattr(window, "key_engine_state", "loading")

            window._quick_scan_requested(audio)

            self.assertTrue(window.quick_scan_busy)
            self.assertFalse(window.quick_scan_drop.isEnabled())
            self.assertEqual(window.pending_quick_scan, audio)
            self.assertEqual(window.quick_scan_filename_label.text(), "loop.wav")
            self.assertIn("Loading", window.quick_scan_time_label.text())
            window._quick_scan_finished()
            window.close()

    def test_quick_scan_formats_result_without_rescanning(self):
        window = MainWindow()
        window.quick_scan_result = {"camelot": "3A"}
        window._update_quick_scan_results()
        self.assertEqual(window.quick_detected_value.text(), "A# minor")
        self.assertEqual(window.quick_relative_value.text(), "C# major")
        self.assertEqual(window.quick_detected_degree.text(), "VI")
        self.assertEqual(window.quick_relative_degree.text(), "I")

        window._set_quick_accidentals("flats")
        window._set_quick_degree_reference("minor")
        self.assertEqual(window.quick_detected_value.text(), "Bb minor")
        self.assertEqual(window.quick_relative_value.text(), "Db major")
        self.assertEqual(window.quick_detected_degree.text(), "I")
        self.assertEqual(window.quick_relative_degree.text(), "III")
        window.close()

    def test_quick_scan_modes_stay_empty_until_a_real_result(self):
        window = MainWindow()
        self.assertTrue(all((key.text(), degree.text()) == ("—", "—") for key, degree in window.quick_mode_labels))
        self.assertIn("Scan a file", window.quick_modes_note.text())

        window._set_quick_accidentals("flats")
        window._set_quick_degree_reference("minor")
        self.assertTrue(all((key.text(), degree.text()) == ("—", "—") for key, degree in window.quick_mode_labels))

        window._set_quick_accidentals("sharps")
        window._set_quick_degree_reference("major")
        window.quick_scan_result = {"camelot": "3A"}
        window._update_quick_scan_results()
        self.assertEqual(
            [(key.text(), degree.text()) for key, degree in window.quick_mode_labels],
            [
                ("D# Dorian", "II"),
                ("F Phrygian", "III"),
                ("F# Lydian", "IV"),
                ("G# Mixolydian", "V"),
                ("C Locrian", "VII"),
            ],
        )
        self.assertEqual(window.quick_modes_note.text(), "Same notes · different centers")

        window._quick_scan_failed("test")
        self.assertTrue(all((key.text(), degree.text()) == ("—", "—") for key, degree in window.quick_mode_labels))
        self.assertEqual(window.quick_detected_value.text(), "—")
        self.assertEqual(window.quick_relative_value.text(), "—")
        window.close()

    def test_quick_scan_accepts_only_supported_audio_files(self):
        with tempfile.TemporaryDirectory() as root:
            drop = DropZone("audio", interactive=True)
            for extension in (".mp3", ".wav", ".flac"):
                path = os.path.join(root, "loop" + extension)
                open(path, "wb").close()
                self.assertTrue(drop.set_path(path))
            unsupported = os.path.join(root, "loop.aiff")
            open(unsupported, "wb").close()
            self.assertFalse(drop.set_path(unsupported))
            texts = [item.text() for item in drop.findChildren(QLabel)]
            self.assertIn("Supported formats: MP3, WAV, FLAC", texts)
            drop.close()

    def test_quick_extract_drop_accepts_only_mp3(self):
        with tempfile.TemporaryDirectory() as root:
            drop = DropZone("audio", interactive=True, allowed_extensions={".mp3"})
            mp3 = os.path.join(root, "loop.mp3"); wav = os.path.join(root, "loop.wav")
            open(mp3, "wb").close(); open(wav, "wb").close()
            self.assertTrue(drop.set_path(mp3))
            self.assertFalse(drop.set_path(wav))
            drop.close()

    def test_quick_extract_empty_state_is_centered_and_replaced_immediately(self):
        window = MainWindow()
        window.select_tab(1)
        window.show()
        APP.processEvents()

        self.assertEqual(
            window.quick_layers_empty_label.text(),
            "Once you drop an audio file, its layers will appear here.",
        )
        self.assertEqual(window.quick_layers_empty_icon.kind, "layers")
        empty_center = window.quick_layers_empty_state.mapTo(
            window.quick_layer_content,
            window.quick_layers_empty_state.rect().center(),
        ).y()
        self.assertLessEqual(abs(empty_center - window.quick_layer_content.rect().center().y()), 1)
        self.assertLess(
            window.quick_layers_empty_icon.geometry().bottom(),
            window.quick_layers_empty_label.geometry().top(),
        )

        initial_state = window.quick_layers_empty_state
        window._populate_layer_cards([], "Extracting layers…")
        self.assertFalse(initial_state.isVisible())
        self.assertEqual(window.quick_layers_empty_label.text(), "Extracting layers…")
        self.assertIsNone(window.quick_layers_empty_icon)

        processing_state = window.quick_layers_empty_state
        layer = {
            "path": "/private/tmp/quick-layer.mp3",
            "name": "quick-layer.mp3",
            "bpm": 140,
            "duration": 1.0,
            "bytes": 32,
            "peaks": [0.0] * 72,
        }
        window._populate_layer_cards([layer])
        self.assertFalse(processing_state.isVisible())
        self.assertIsNone(window.quick_layers_empty_state)
        self.assertEqual(len(window.layer_cards), 1)
        window.close()

    def test_quick_audio_drop_contents_never_overlap(self):
        """Protect the compact Quick Scan/Extract drop-zone composition."""
        previous_stylesheet = APP.styleSheet()
        APP.setStyleSheet(application_stylesheet())
        drops = []
        try:
            with tempfile.TemporaryDirectory() as root:
                loaded_audio = os.path.join(root, "L ENERGY 147 +NRGY.mp3")
                open(loaded_audio, "wb").close()

                # Reproduce the two states shown in the UI: an empty Quick Scan
                # drop and a Quick Extract drop displaying a selected filename.
                scan_drop = DropZone("audio", interactive=True)
                extract_drop = DropZone("audio", compact=True, interactive=True, allowed_extensions={".mp3"})
                self.assertTrue(extract_drop.set_path(loaded_audio))
                drops.extend((scan_drop, extract_drop))

                for drop in drops:
                    drop.show()
                APP.processEvents()

                for drop in drops:
                    ordered_widgets = (
                        drop.icon,
                        drop.title_label,
                        drop.subtitle_label,
                        drop.browse,
                        drop.formats_label,
                    )

                    for upper, lower in zip(ordered_widgets, ordered_widgets[1:]):
                        self.assertFalse(
                            upper.geometry().intersects(lower.geometry()),
                            f"{type(upper).__name__} overlaps {type(lower).__name__}",
                        )
                        self.assertLess(
                            upper.geometry().bottom(),
                            lower.geometry().top(),
                            f"{type(upper).__name__} must remain above {type(lower).__name__}",
                        )
                    self.assertLessEqual(
                        drop.formats_label.geometry().bottom(),
                        drop.contentsRect().bottom(),
                    )
        finally:
            for drop in drops:
                drop.close()
            APP.setStyleSheet(previous_stylesheet)
            APP.processEvents()

    def test_drop_zone_accepts_native_drag_move_and_drop(self):
        with tempfile.TemporaryDirectory() as root:
            audio = os.path.join(root, "loop.mp3")
            open(audio, "wb").close()
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(audio)])
            actions = Qt.CopyAction | Qt.MoveAction
            drop = DropZone("audio", interactive=True)

            enter = QDragEnterEvent(QPoint(10, 10), actions, mime, Qt.LeftButton, Qt.NoModifier)
            drop.dragEnterEvent(enter)
            self.assertTrue(enter.isAccepted())
            self.assertEqual(enter.dropAction(), Qt.CopyAction)

            move = QDragMoveEvent(QPoint(10, 10), actions, mime, Qt.LeftButton, Qt.NoModifier)
            drop.dragMoveEvent(move)
            self.assertTrue(move.isAccepted())
            self.assertEqual(move.dropAction(), Qt.CopyAction)

            dropped = QDropEvent(QPointF(10, 10), actions, mime, Qt.LeftButton, Qt.NoModifier)
            drop.dropEvent(dropped)
            self.assertTrue(dropped.isAccepted())
            self.assertEqual(dropped.dropAction(), Qt.CopyAction)
            self.assertEqual(drop.path, audio)
            drop.close()

    def test_folder_drop_accepts_native_drag_move_and_drop(self):
        with tempfile.TemporaryDirectory() as root:
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(root)])
            actions = Qt.CopyAction | Qt.MoveAction
            drop = DropZone("folder")

            move = QDragMoveEvent(QPoint(10, 10), actions, mime, Qt.LeftButton, Qt.NoModifier)
            drop.dragMoveEvent(move)
            self.assertTrue(move.isAccepted())
            self.assertEqual(move.dropAction(), Qt.CopyAction)

            dropped = QDropEvent(QPointF(10, 10), actions, mime, Qt.LeftButton, Qt.NoModifier)
            drop.dropEvent(dropped)
            self.assertTrue(dropped.isAccepted())
            self.assertEqual(drop.path, root)
            drop.close()

    def test_pause_mark_is_painted_instead_of_using_a_platform_glyph(self):
        layer = {"path": "/tmp/layer.mp3", "name": "layer.mp3", "duration": 1, "bytes": 1, "peaks": [0.5] * 72}
        card = LayerCard(layer)
        card.setPlaybackState("playing")
        self.assertEqual(card.play.text(), "")
        self.assertEqual(card.play.property("state"), "playing")
        card.setPlaybackState("paused")
        self.assertEqual(card.play.text(), "▶")
        card.close()

    def test_layer_card_midi_handle_becomes_draggable_when_ready(self):
        layer = {"path": "/tmp/layer.mp3", "name": "layer.mp3", "duration": 1, "bytes": 1, "peaks": [0.5] * 72}
        card = LayerCard(layer)
        self.assertEqual(card.midi_handle.state, "processing")
        self.assertEqual((card.midi_handle.width(), card.midi_handle.height()), (32, 20))
        card.setMidiPath("/tmp/layer_1.mid")
        self.assertEqual(card.midi_handle.state, "ready")
        self.assertEqual(card.midi_handle.path, "/tmp/layer_1.mid")
        card.close()

    def test_quick_extract_worker_returns_real_layer_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            layer = os.path.join(root, "Loop_L1.mp3")
            with open(layer, "wb") as stream:
                stream.write(b"audio")
            diagnostics = [{
                "event": "exported", "output_exists": True,
                "output_name": "Loop_L1.mp3", "duration_seconds": 12.5,
                "output_bytes": 5,
            }]
            worker = QuickExtractWorker(os.path.join(root, "Loop.mp3"), root)
            results = []
            worker.completed.connect(lambda layers, elapsed: results.extend(layers))
            with patch("app.process_single_file", return_value=diagnostics), patch("app.waveform_peaks", return_value=[0.5] * 72):
                worker.run()
            APP.processEvents()
            self.assertEqual(results[0]["path"], layer)
            self.assertEqual(results[0]["duration"], 12.5)
            self.assertEqual(results[0]["bytes"], 5)
            self.assertEqual(len(results[0]["peaks"]), 72)

    def test_paused_layer_resumes_instead_of_stopping(self):
        class FakePlayer:
            def __init__(self): self.play_calls = 0
            def playbackState(self): return QMediaPlayer.PlaybackState.PausedState
            def play(self): self.play_calls += 1
            def stop(self): pass

        window = MainWindow(); fake = FakePlayer(); window.media_player = fake; window.active_layer_path = "/tmp/layer.mp3"
        window._toggle_layer_playback("/tmp/layer.mp3")
        self.assertEqual(fake.play_calls, 1)
        self.assertEqual(window.active_layer_path, "/tmp/layer.mp3")
        window.close()

    def test_waveform_scrubbing_reaches_both_extremes(self):
        waveform = WaveformWidget([0.5] * 72); waveform.resize(240, 22)
        values = []; waveform.seekRequested.connect(values.append)
        waveform._seek_from_x(240); waveform._seek_from_x(-10)
        self.assertEqual(values, [1.0, 0.0])
        waveform.setProgress(0.65)
        self.assertEqual(waveform.progress, 0.65)
        waveform.close()

    def test_each_edge_chip_can_cross_the_full_strip(self):
        strip = TokenStrip(TOKENS)
        strip.resize(700, 66)
        strip.setEnabled(True)
        strip.show()
        APP.processEvents()

        first = strip.chipRects()[0].center()
        last = strip.chipRects()[-1].center()
        QTest.mousePress(strip, Qt.LeftButton, Qt.NoModifier, QPoint(int(first.x()), int(first.y())))
        QTest.mouseMove(strip, QPoint(int(last.x() + 80), int(last.y())), 20)
        QTest.mouseRelease(strip, Qt.LeftButton, Qt.NoModifier, QPoint(int(last.x() + 80), int(last.y())))
        self.assertEqual(strip.tokens[-1], "KEY")

        last = strip.chipRects()[-1].center()
        first = strip.chipRects()[0].center()
        QTest.mousePress(strip, Qt.LeftButton, Qt.NoModifier, QPoint(int(last.x()), int(last.y())))
        QTest.mouseMove(strip, QPoint(max(2, int(first.x() - 80)), int(first.y())), 20)
        QTest.mouseRelease(strip, Qt.LeftButton, Qt.NoModifier, QPoint(max(2, int(first.x() - 80)), int(first.y())))
        self.assertEqual(strip.tokens[0], "KEY")
        strip.close()

    def test_stem_workflow_matrix(self):
        window = MainWindow()
        window._start_key_engine = lambda: None
        window.key_engine_state = "ready"

        self.assertTrue(window.layer_switch.isChecked())
        self.assertFalse(window.key_switch.isChecked())
        self.assertEqual(window.start_button.text(), "▶  EXTRACT LAYERS")
        self.assertEqual(window.start_button.property("role"), "primary")
        self.assertFalse(window.start_button.property("keyTextAccent"))
        self.assertFalse(window.copy_destination_button.isEnabled())
        self.assertTrue(all(effect.opacity() < 0.3 for effect in window.key_opacity_effects))
        self.assertTrue(window.input_drop.isEnabled())
        self.assertFalse(hasattr(window, "layer_source_overlay"))
        self.assertTrue(window.layer_operation_card.property("active"))
        self.assertFalse(window.key_operation_card.property("active"))

        window.key_switch.setChecked(True)
        self.assertEqual(window.start_button.text(), "▶  SCAN KEYS + EXTRACT LAYERS")
        self.assertEqual(window.start_button.property("role"), "primary")
        self.assertTrue(window.start_button.property("keyTextAccent"))
        self.assertFalse(window.copy_destination_button.isEnabled())
        self.assertTrue(all(effect.opacity() == 1.0 for effect in window.key_opacity_effects))
        self.assertEqual(window.copy_destination_button.property("role"), "disabled")
        self.assertEqual(window.rename_destination_button.property("role"), "disabled")

        window.layer_switch.setChecked(False)
        self.assertEqual(window.start_button.text(), "▶  SCAN KEYS")
        self.assertEqual(window.start_button.property("role"), "keyPrimary")
        self.assertFalse(window.start_button.property("keyTextAccent"))
        self.assertTrue(window.copy_destination_button.isEnabled())
        self.assertTrue(window.rename_destination_button.isEnabled())
        self.assertEqual(window.copy_destination_button.property("role"), "selected")
        self.assertEqual(window.rename_destination_button.property("role"), "secondary")
        self.assertTrue(window.input_drop.isEnabled())
        self.assertFalse(window.layer_operation_card.property("active"))
        self.assertTrue(window.key_operation_card.property("active"))
        self.assertEqual(window.results_title.property("role"), "keySmall")
        self.assertEqual(window.key_destination_effect.opacity(), 1.0)
        self.assertIsNone(window.layer_results_panel.graphicsEffect())
        self.assertTrue(window.layer_results_panel.isEnabled())

        window.key_switch.setChecked(False)
        self.assertEqual(window.start_button.text(), "SELECT A PROCESS")
        self.assertFalse(window.start_button.property("keyTextAccent"))
        self.assertFalse(window.start_button.isEnabled())
        self.assertTrue(window.input_drop.isEnabled())
        window.close()

    def test_operation_cards_toggle_everywhere_without_switch_double_toggle(self):
        window = MainWindow()
        window.key_engine_state = "ready"
        window.show()
        APP.processEvents()

        layer_events = []
        key_events = []
        window.layer_switch.toggled.connect(layer_events.append)
        window.key_switch.toggled.connect(key_events.append)

        self.assertTrue(window.layer_title.testAttribute(Qt.WA_TransparentForMouseEvents))
        self.assertTrue(window.layer_operation_icon.testAttribute(Qt.WA_TransparentForMouseEvents))
        QTest.mouseClick(window.layer_operation_card, Qt.LeftButton, Qt.NoModifier, QPoint(20, 30))
        self.assertFalse(window.layer_switch.isChecked())
        self.assertEqual(layer_events, [False])
        self.assertFalse(window.key_switch.isChecked())

        # A click on the switch itself must change the state exactly once.
        QTest.mouseClick(window.layer_switch, Qt.LeftButton)
        self.assertTrue(window.layer_switch.isChecked())
        self.assertEqual(layer_events, [False, True])

        title_point = window.key_title.mapTo(window.key_operation_card, window.key_title.rect().center())
        QTest.mouseClick(window.key_operation_card, Qt.LeftButton, Qt.NoModifier, title_point)
        self.assertTrue(window.key_switch.isChecked())
        self.assertEqual(key_events, [True])
        self.assertTrue(window.key_operation_card.property("active"))

        QTest.mouseClick(window.key_switch, Qt.LeftButton)
        self.assertFalse(window.key_switch.isChecked())
        self.assertEqual(key_events, [True, False])

        window.busy = True
        window._sync_stem_state()
        QTest.mouseClick(window.layer_operation_card, Qt.LeftButton, Qt.NoModifier, QPoint(20, 30))
        QTest.mouseClick(window.layer_switch, Qt.LeftButton)
        self.assertTrue(window.layer_switch.isChecked())
        self.assertEqual(layer_events, [False, True])
        window.close()

    def test_output_action_buttons_are_vertically_centered(self):
        window = MainWindow()
        window.show()
        APP.processEvents()
        panel_center = window.layer_results_panel.rect().center().y()
        for action in (window.change_root_button, window.open_folder_button):
            action_center = action.mapTo(window.layer_results_panel, action.rect().center()).y()
            self.assertLessEqual(abs(action_center - panel_center), 1)
        open_text = window.open_folder_button.text_label
        self.assertGreaterEqual(
            open_text.width(),
            QFontMetrics(open_text.font()).horizontalAdvance(open_text.text()),
        )
        self.assertLess(open_text.geometry().right(), window.open_folder_button.rect().right())
        window.close()

    def test_quick_tools_use_blue_scan_and_red_extract_scopes(self):
        previous_stylesheet = APP.styleSheet()
        APP.setStyleSheet(application_stylesheet())
        window = MainWindow()
        window.key_engine_state = "ready"
        window.key_switch.setChecked(True)
        window.select_tab(1)
        window.show()
        APP.processEvents()
        try:
            self.assertEqual(window.quick_scan_panel.property("sectionAccent"), "blue")
            self.assertEqual(window.quick_extract_panel.property("sectionAccent"), "red")
            self.assertEqual(window.quick_scan_drop.accent, "blue")
            self.assertEqual(window.quick_extract_drop.accent, "red")
            self.assertEqual(
                window.quick_scan_title.palette().color(window.quick_scan_title.foregroundRole()).name(),
                "#3ca7e8",
            )
            self.assertEqual(
                window.quick_extract_title.palette().color(window.quick_extract_title.foregroundRole()).name(),
                "#ff2b1c",
            )
            self.assertTrue(window.quick_scan_panel.isAncestorOf(window.quick_major_button))
            self.assertTrue(window.quick_extract_panel.isAncestorOf(window.quick_show_results))
            self.assertFalse(window.quick_extract_panel.isAncestorOf(window.quick_storage_label))
            self.assertEqual(
                window.start_button.palette().color(window.start_button.foregroundRole()).name(),
                "#b9e7ff",
            )

            neutral_section_surfaces = (
                window.quick_scan_panel,
                window.quick_extract_panel,
            )
            rendered_section_colors = [
                widget.grab().toImage().pixelColor(8, 8).name()
                for widget in neutral_section_surfaces
            ]
            self.assertEqual(rendered_section_colors, ["#14181b"] * len(rendered_section_colors))

            neutral_surfaces = (
                (window.quick_scan_drop, 12, 12),
                (window.quick_extract_drop, 12, 12),
                (window.quick_detected_card, 10, 10),
                (window.quick_relative_card, 10, 10),
                (window.quick_modes_card, 10, 10),
                (window.quick_layers_area.viewport(), 10, 10),
            )
            rendered_colors = [
                widget.grab().toImage().pixelColor(x, y).name()
                for widget, x, y in neutral_surfaces
            ]
            self.assertEqual(rendered_colors, ["#0e1215"] * len(rendered_colors))
        finally:
            window.close()
            APP.setStyleSheet(previous_stylesheet)
            APP.processEvents()

    def test_guided_workflow_sections_are_ordered_and_fit(self):
        previous_stylesheet = APP.styleSheet()
        APP.setStyleSheet(application_stylesheet())
        window = MainWindow()
        window.show()
        APP.processEvents()
        try:
            self.assertEqual(window.source_title.text(), "SOURCE FOLDER")
            self.assertEqual(window.operations_title.text(), "OPERATIONS")
            self.assertEqual(window.output_title.text(), "OUTPUT")
            self.assertIn("process", window.input_drop.title_label.text().lower())
            self.assertIs(window.input_drop.parentWidget(), window.source_panel)
            self.assertFalse(window.layer_operation_card.isAncestorOf(window.input_drop))
            self.assertEqual(window.input_drop.icon.kind, "folder_in")
            self.assertEqual(window.layer_operation_icon.kind, "layers")
            self.assertEqual(window.key_operation_icon.kind, "key_scan")
            self.assertEqual(window.results_location_icon.kind, "folder")
            self.assertEqual(window.open_folder_button.icon_widget.kind, "folder")
            self.assertEqual(window.open_folder_button.text_label.text(), "OPEN FOLDER")
            self.assertEqual(window.key_destination_title.text(), "KEY ANALYSIS DESTINATION")
            self.assertNotIn("KEY-ONLY", window.key_destination_title.text())
            self.assertEqual(window.stem_tab.icon.kind, "folder")

            page = window.pages.widget(0)
            previous_bottom = -1
            for section in window.workflow_sections:
                geometry = section.geometry()
                self.assertGreater(geometry.top(), previous_bottom)
                self.assertLessEqual(geometry.bottom(), page.contentsRect().bottom())
                previous_bottom = geometry.bottom()
        finally:
            window.close()
            APP.setStyleSheet(previous_stylesheet)
            APP.processEvents()

    def test_shared_source_stays_enabled_across_operations_and_busy(self):
        window = MainWindow()
        window.key_engine_state = "ready"

        for extract_enabled, key_enabled in ((True, False), (True, True), (False, True), (False, False)):
            window.layer_switch.setChecked(extract_enabled)
            window.key_switch.setChecked(key_enabled)
            self.assertTrue(window.input_drop.isEnabled())

        window.busy = True
        window._sync_stem_state()
        self.assertFalse(window.input_drop.isEnabled())
        self.assertFalse(window.layer_switch.isEnabled())
        self.assertFalse(window.key_switch.isEnabled())

        window.busy = False
        window._sync_stem_state()
        self.assertTrue(window.input_drop.isEnabled())
        window.close()

    def test_key_only_output_skin_and_destination_reset(self):
        window = MainWindow()
        window.key_engine_state = "ready"
        window.layer_switch.setChecked(False)
        window.key_switch.setChecked(True)

        self.assertEqual(window.start_button.property("role"), "keyPrimary")
        self.assertEqual(window.results_title.property("role"), "keySmall")
        self.assertEqual(window.key_destination_effect.opacity(), 1.0)
        window._set_destination_mode("rename_in_place")
        self.assertEqual(window.destination_mode, "rename_in_place")

        window.layer_switch.setChecked(True)
        self.assertEqual(window.destination_mode, "copy_to_output")
        self.assertEqual(window.start_button.property("role"), "primary")
        self.assertLess(window.key_destination_effect.opacity(), 0.3)
        self.assertIn("Extractions", window.destination_path_label.text())
        window.close()

    def test_quick_tools_page_survives_stem_skin_state_changes(self):
        window = MainWindow()
        quick_page = window.pages.widget(1)
        quick_controls = (window.quick_scan_drop, window.quick_extract_drop, window.quick_layer_content)
        for control in quick_controls:
            self.assertTrue(quick_page.isAncestorOf(control))

        window.layer_switch.setChecked(False)
        window.key_switch.setChecked(True)
        QTest.mouseClick(window.quick_tab, Qt.LeftButton)
        APP.processEvents()
        self.assertIs(window.pages.currentWidget(), quick_page)
        for control in quick_controls:
            self.assertTrue(quick_page.isAncestorOf(control))
        window.close()

    def test_quick_extract_manager_lists_extracts_and_layers(self):
        with tempfile.TemporaryDirectory() as workspace:
            settings = MemorySettings(workspace); storage = StorageManager(settings)
            session = os.path.join(storage.category_path("quick"), "CUTDATROPE")
            os.makedirs(session)
            for index in range(1, 4):
                with open(os.path.join(session, f"CUTDATROPE_L{index}.mp3"), "wb") as stream:
                    stream.write(b"x" * index)
            dialog = QuickExtractManagerDialog(storage)
            self.assertIn("1 extract", dialog.summary.text())
            self.assertIn("3 layers", dialog.summary.text())
            self.assertTrue(any(item.text() == "CUTDATROPE" for item in dialog.findChildren(QLabel)))
            dialog.close()

    def test_key_analysis_controls_drive_settings_and_preview(self):
        window = MainWindow()
        window._start_key_engine = lambda: None
        window.key_engine_state = "ready"
        window.key_switch.setChecked(True)

        window._set_key_mode("relative_major")
        window._set_accidentals("flats")
        window._token_order_changed(["LOOP NAME", "BPM", "KEY", "PROD NAME"])

        settings = window._processing_settings()
        self.assertEqual(settings["mode"], "relative_major")
        self.assertEqual(settings["accidentals"], "flats")
        self.assertEqual(
            settings["token_order"],
            ["LOOP NAME", "BPM", "KEY", "PROD NAME"],
        )
        self.assertEqual(window.mode_buttons["relative_major"].property("role"), "selected")
        self.assertEqual(window.mode_buttons["detected"].property("role"), "secondary")
        self.assertEqual(window.flats_button.property("role"), "selected")
        self.assertEqual(window.sharps_button.property("role"), "secondary")
        self.assertIn("CALLMEUR3 137 Db +NRGY_L1.mp3", window.name_preview_label.text())
        window.close()

    def test_embedded_token_strip_updates_window_order(self):
        window = MainWindow()
        window._start_key_engine = lambda: None
        window.key_engine_state = "ready"
        window.key_switch.setChecked(True)
        window.show()
        APP.processEvents()

        strip = window.token_strip
        self.assertEqual(strip._font().pointSizeF(), 9.5)
        metrics = QFontMetrics(strip._font())
        for token, rect in zip(strip.tokens, strip.chipRects()):
            text_left = rect.center().x() - metrics.horizontalAdvance(token) / 2
            six_dot_grip_right = rect.left() + 18.5
            self.assertGreaterEqual(text_left - six_dot_grip_right, 2)
        widths = {token: rect.width() for token, rect in zip(strip.tokens, strip.chipRects())}
        self.assertGreater(widths["LOOP NAME"], widths["KEY"])
        self.assertGreater(widths["PROD NAME"], widths["BPM"])
        first = strip.chipRects()[0].center()
        last = strip.chipRects()[-1].center()
        QTest.mousePress(strip, Qt.LeftButton, Qt.NoModifier, QPoint(int(first.x()), int(first.y())))
        QTest.mouseMove(strip, QPoint(int(last.x() + 50), int(last.y())), 20)
        QTest.mouseRelease(strip, Qt.LeftButton, Qt.NoModifier, QPoint(int(last.x() + 50), int(last.y())))

        self.assertEqual(window.token_order[-1], "KEY")
        self.assertIn("CALLMEUR3 137 +NRGY A#m_L1.mp3", window.name_preview_label.text())
        window.close()

    def test_storage_preview_does_not_create_session(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as source_parent:
            source = os.path.join(source_parent, "Untitled Folder")
            os.makedirs(source)
            window = MainWindow()
            window._start_key_engine = lambda: None
            window.key_engine_state = "ready"
            window.storage = StorageManager(MemorySettings(workspace))
            window.input_drop.set_path(source)

            expected = os.path.join(workspace, "Extractions", "Untitled Folder")
            self.assertEqual(window.destination_path_label.toolTip(), expected)
            self.assertFalse(os.path.exists(expected))

            window.key_switch.setChecked(True)
            window.layer_switch.setChecked(False)
            expected = os.path.join(workspace, "Analyzed Loops", "Untitled Folder")
            self.assertEqual(window.destination_path_label.toolTip(), expected)
            self.assertFalse(os.path.exists(expected))

            window._set_destination_mode("rename_in_place")
            self.assertEqual(window.destination_path_label.toolTip(), source)
            window.close()

    def test_selecting_source_refreshes_key_only_start_button(self):
        with tempfile.TemporaryDirectory() as source:
            open(os.path.join(source, "loop.mp3"), "wb").close()
            window = MainWindow()
            window._start_key_engine = lambda: None
            window.key_engine_state = "ready"

            window.key_switch.setChecked(True)
            window.layer_switch.setChecked(False)
            self.assertFalse(window.start_button.isEnabled())

            # This is the exact cold-launch order reported by the user: the
            # engine is ready and Key Analysis is selected before the folder.
            window.input_drop.set_path(source)

            self.assertTrue(window.start_button.isEnabled())
            self.assertEqual(window.start_button.text(), "▶  SCAN KEYS")
            window.close()

    def test_custom_destination_is_session_only_and_direct(self):
        with tempfile.TemporaryDirectory() as custom, tempfile.TemporaryDirectory() as source_parent:
            source = os.path.join(source_parent, "Loop Pack")
            os.makedirs(source)
            window = MainWindow()
            window.show()
            window.input_drop.set_path(source)
            APP.processEvents()
            default_title_position = window.destination_path_label.mapTo(window, QPoint(0, 0))

            window.custom_destination = custom
            window._update_destination_preview()
            APP.processEvents()
            expected = os.path.join(custom, "Loop Pack")
            self.assertEqual(window.destination_path_label.toolTip(), expected)
            self.assertFalse(window.reset_destination_button.isHidden())
            self.assertEqual(
                window.destination_info_label.text(),
                "Custom destination active for this session.",
            )
            self.assertNotIn("Analyzed Loops", expected)
            self.assertNotIn("Extractions", expected)
            self.assertEqual(
                window.destination_path_label.mapTo(window, QPoint(0, 0)).y(),
                default_title_position.y(),
            )

            window._reset_destination()
            self.assertEqual(window.custom_destination, "")
            self.assertTrue(window.reset_destination_button.isHidden())
            self.assertIn("Extractions", window.destination_path_label.toolTip())
            window.close()


if __name__ == "__main__":
    unittest.main()
