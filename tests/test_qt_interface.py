import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STEM_SLICER_DISABLE_ENGINE_AUTOSTART", "1")

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtMultimedia import QMediaPlayer

from app import DropZone, KeyEngineLoader, MainWindow, QuickExtractManagerDialog, QuickExtractWorker, WaveformWidget
from filename_templates import TOKENS
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
        self.assertFalse(window.copy_destination_button.isEnabled())
        self.assertTrue(all(effect.opacity() < 0.3 for effect in window.key_opacity_effects))

        window.key_switch.setChecked(True)
        self.assertEqual(window.start_button.text(), "▶  SCAN KEYS + EXTRACT LAYERS")
        self.assertFalse(window.copy_destination_button.isEnabled())
        self.assertTrue(all(effect.opacity() == 1.0 for effect in window.key_opacity_effects))

        window.layer_switch.setChecked(False)
        self.assertEqual(window.start_button.text(), "▶  SCAN KEYS")
        self.assertTrue(window.copy_destination_button.isEnabled())
        self.assertTrue(window.rename_destination_button.isEnabled())

        window.key_switch.setChecked(False)
        self.assertEqual(window.start_button.text(), "SELECT A PROCESS")
        self.assertFalse(window.start_button.isEnabled())
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
