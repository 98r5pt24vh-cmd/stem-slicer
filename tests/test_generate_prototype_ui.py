import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STEM_SLICER_DISABLE_ENGINE_AUTOSTART", "1")

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QThread, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

import generator_controller
from generator_ui import GenerateCard, GeneratePage, GeneratePrototypeWindow
from layer_library import TAXONOMY
from validated_ui import AnchoredChoiceSelector, BASE_HEIGHT, BASE_WIDTH


APP = QApplication.instance() or QApplication([])


def _viewport_point(window, widget, local_point):
    canvas_point = widget.mapTo(window.canvas, local_point)
    scene_point = window.proxy.mapToScene(QPointF(canvas_point))
    return window.view.mapFromScene(scene_point)


class GeneratePrototypeUITests(unittest.TestCase):
    def setUp(self):
        self.window = GeneratePrototypeWindow()
        self.window.show()
        APP.processEvents()

    def tearDown(self):
        self.window.close()
        APP.processEvents()

    def test_shell_size_tabs_and_mandatory_targets(self):
        window = self.window
        self.assertEqual((window.width(), window.height()), (BASE_WIDTH, BASE_HEIGHT))
        self.assertEqual((window.canvas.width(), window.canvas.height()), (BASE_WIDTH, BASE_HEIGHT))
        self.assertEqual(
            [tab.title.text() for tab in (window.stem_tab, window.quick_tab, window.generate_tab)],
            ["STEM SLICER", "QUICK TOOLS", "GENERATE"],
        )
        self.assertEqual(
            [tab.width() for tab in (window.stem_tab, window.quick_tab, window.generate_tab)],
            [210, 210, 210],
        )
        self.assertLess(window.stem_tab.x(), window.quick_tab.x())
        self.assertLess(window.quick_tab.x(), window.generate_tab.x())
        self.assertFalse(window.stem_tab.isEnabled())
        self.assertFalse(window.quick_tab.isEnabled())
        self.assertTrue(window.generate_tab.isEnabled())
        self.assertTrue(
            window.stem_tab.testAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents
            )
        )
        self.assertTrue(
            window.quick_tab.testAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents
            )
        )
        self.assertFalse(window.stem_tab.active)
        self.assertFalse(window.quick_tab.active)
        self.assertTrue(window.generate_tab.active)

        clicked = []
        window.stem_tab.clicked.connect(lambda: clicked.append("stem"))
        window.quick_tab.clicked.connect(lambda: clicked.append("quick"))
        for tab in (window.stem_tab, window.quick_tab):
            point = _viewport_point(window, tab, tab.rect().center())
            QTest.mouseClick(window.view.viewport(), Qt.LeftButton, pos=point)
            APP.processEvents()
        self.assertEqual(clicked, [])
        self.assertTrue(window.generate_tab.active)

        self.assertEqual(window.target_bpm.text(), "140")
        self.assertEqual(window.target_key.currentText(), "A minor")
        self.assertFalse(hasattr(window, "target_bpm_switch"))
        self.assertFalse(hasattr(window, "target_key_switch"))
        self.assertEqual(
            [selector.currentText() for selector in window._slot_combos],
            ["Bass", "Chords", "Lead"],
        )
        self.assertEqual(window.preview_seed_button.text(), "PREVIOUS SEED")
        self.assertLess(
            window.preview_seed_button.mapTo(window.canvas, QPoint()).x(),
            window.generate_button.mapTo(window.canvas, QPoint()).x(),
        )
        self.assertFalse(window.preview_seed_button.isEnabled())

    def test_generate_requires_the_current_folder_to_be_scanned(self):
        window = self.window
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            self.assertTrue(window.library_drop.set_path(first))
            APP.processEvents()
            self.assertFalse(window.generate_button.isEnabled())

            window.set_generation_busy(False, "A failed scan must stay disabled")
            self.assertFalse(window.generate_button.isEnabled())

            window.set_library_summary(2, {"Bass": 1}, 1)
            self.assertTrue(window.generate_button.isEnabled())

            self.assertTrue(window.library_drop.set_path(second))
            APP.processEvents()
            self.assertFalse(window.generate_button.isEnabled())
            self.assertEqual(window.generate_button.text(), "GENERATE")
            self.assertFalse(window._has_generation)
            self.assertFalse(window.preview_seed_button.isEnabled())

    def test_changing_library_clears_stale_generation_actions(self):
        window = self.window
        window.set_generation_results(
            {
                "path": "/tmp/old-master.wav",
                "name": "old-master.wav",
                "display_name": "GENERATED LOOP",
                "category": "Master",
                "bpm": 140,
                "key": "A minor",
            },
            [],
        )
        self.assertTrue(window.open_output.isEnabled())
        self.assertEqual(window.generate_button.text(), "GENERATE AGAIN")
        self.assertTrue(window._has_generation)
        self.assertTrue(window.drag_all.isEnabled())

        with tempfile.TemporaryDirectory() as library:
            self.assertTrue(window.library_drop.set_path(library))
            APP.processEvents()

        self.assertFalse(window._cards)
        self.assertTrue(window.open_output.isEnabled())
        self.assertEqual(window.generate_button.text(), "GENERATE")
        self.assertFalse(window._has_generation)
        self.assertFalse(window.drag_all.isEnabled())

    def test_dropping_the_already_loaded_library_is_a_no_op(self):
        window = self.window
        with tempfile.TemporaryDirectory() as library:
            self.assertTrue(window.library_drop.set_path(library))
            window.set_library_summary(3, {"Bass": 1, "Lead": 2}, 0)
            self.assertTrue(window.generate_button.isEnabled())
            self.assertTrue(window.library_drop.set_path(library))
            APP.processEvents()

        self.assertTrue(window.generate_button.isEnabled())
        self.assertTrue(window._library_ready)
        self.assertIn("already loaded", window.scan_status._full_text)

    def test_waveform_scrub_survives_the_graphics_proxy_drag(self):
        window = self.window
        with tempfile.TemporaryDirectory() as temporary:
            wav_path = Path(temporary) / "master.wav"
            import wave

            with wave.open(str(wav_path), "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(48_000)
                stream.writeframes(b"\0\0" * 480)

            window.set_generation_results(
                {
                    "path": str(wav_path),
                    "name": wav_path.name,
                    "display_name": "GENERATED LOOP",
                    "category": "Master",
                    "bpm": 140,
                    "key": "A minor",
                },
                [
                    {
                        "path": str(wav_path),
                        "name": wav_path.name,
                        "display_name": "BASS",
                        "category": "Bass",
                        "slot_index": 0,
                        "identity": "waveform-test",
                        "bpm": 140,
                        "key": "A minor",
                    }
                ],
            )
            APP.processEvents()
            self.assertFalse(
                any(
                    label.isVisible()
                    and label.text()
                    == "Your synchronized generated layers will appear here."
                    for label in window.results_content.findChildren(QLabel)
                )
            )
            waveform = window._cards[0].waveform
            ratios = []
            waveform.seekRequested.connect(ratios.append)
            start = _viewport_point(
                window, waveform, QPoint(2, waveform.height() // 2)
            )
            middle = _viewport_point(
                window,
                waveform,
                QPoint(waveform.width() // 2, waveform.height() // 2),
            )
            end = _viewport_point(
                window,
                waveform,
                QPoint(waveform.width() - 2, waveform.height() // 2),
            )

            QTest.mousePress(window.view.viewport(), Qt.LeftButton, pos=start)
            move = QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(middle),
                QPointF(window.view.viewport().mapToGlobal(middle)),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            QApplication.sendEvent(window.view.viewport(), move)
            QTest.mouseRelease(window.view.viewport(), Qt.LeftButton, pos=end)
            APP.processEvents()

            self.assertGreaterEqual(len(ratios), 3)
            self.assertLess(ratios[0], 0.1)
            self.assertAlmostEqual(ratios[1], 0.5, delta=0.03)
            self.assertGreater(ratios[-1], 0.9)
            self.assertFalse(waveform.scrubbing)

    def test_seek_uses_the_shared_layer_transport_immediately(self):
        class FakeLayerPlayer:
            def __init__(self):
                self.active = ()
                self.solo = []
                self.ratios = []

            def activePaths(self):
                return self.active

            def playSolo(self, path):
                self.solo.append(path)
                self.active = (path,)
                return True

            def seek(self, ratio):
                self.ratios.append(ratio)

            def stop(self, *, reset=False):
                pass

        fake = FakeLayerPlayer()
        self.window._layer_player = fake
        self.window._seek_path("/tmp/example.wav", 0.625)
        self.assertEqual(fake.solo, ["/tmp/example.wav"])
        self.assertEqual(fake.ratios, [0.625])

    def test_play_is_solo_until_sync_transport_arms_the_shared_mix(self):
        page = GeneratePage()
        self.addCleanup(page.close)
        with tempfile.TemporaryDirectory() as temporary:
            import wave

            paths = []
            for name in ("bass.wav", "chords.wav"):
                path = Path(temporary) / name
                with wave.open(str(path), "wb") as stream:
                    stream.setnchannels(2)
                    stream.setsampwidth(2)
                    stream.setframerate(48_000)
                    stream.writeframes(b"\0\0\0\0" * 480)
                paths.append(path)

            stems = [
                {
                    "path": str(path),
                    "category": category,
                    "slot_index": index,
                    "identity": category.lower(),
                    "peaks": (0.1,),
                }
                for index, (path, category) in enumerate(
                    zip(paths, ("Bass", "Chords"))
                )
            ]
            page.set_generation_results(
                {"path": str(Path(temporary) / "master.mp3")},
                stems,
            )
            with patch.object(page._layer_player, "_start"):
                page._stem_cards[0].play.click()
                page._layer_player.seek(0.75)
                page._stem_cards[1].play.click()
                APP.processEvents()
                self.assertEqual(
                    page._layer_player.activePaths(),
                    (str(paths[1]),),
                )
                self.assertEqual(page._layer_player.positionRatio(), 0.0)
                self.assertEqual(
                    page._stem_cards[0].play.property("state"),
                    "stopped",
                )
                self.assertEqual(
                    page._stem_cards[1].play.property("state"),
                    "playing",
                )
                self.assertTrue(
                    all(
                        not card.name_label.property("mixActive")
                        for card in page._stem_cards
                    )
                )

                page.all_layers_transport.click()
                APP.processEvents()
                self.assertEqual(
                    set(page._layer_player.activePaths()),
                    {str(path) for path in paths},
                )
                self.assertTrue(
                    all(
                        card.play.property("state") == "playing"
                        for card in page._stem_cards
                    )
                )

                page._stem_cards[1].play.click()
                APP.processEvents()
                self.assertEqual(
                    page._layer_player.activePaths(),
                    (str(paths[0]),),
                )
                self.assertEqual(
                    page._stem_cards[1].play.property("state"),
                    "stopped",
                )

                page._stem_cards[1].play.click()
                APP.processEvents()
                self.assertEqual(
                    set(page._layer_player.activePaths()),
                    {str(path) for path in paths},
                )

    def test_play_all_button_becomes_stop_and_controls_every_layer(self):
        with tempfile.TemporaryDirectory() as temporary:
            import wave

            paths = []
            for name in ("bass.wav", "lead.wav"):
                path = Path(temporary) / name
                with wave.open(str(path), "wb") as stream:
                    stream.setnchannels(2)
                    stream.setsampwidth(2)
                    stream.setframerate(48_000)
                    stream.writeframes(b"\0\0\0\0" * 480)
                paths.append(path)
            self.window.set_generation_results(
                {"path": str(Path(temporary) / "master.mp3")},
                [
                    {
                        "path": str(path),
                        "category": category,
                        "slot_index": index,
                        "identity": category.lower(),
                        "peaks": (0.1,),
                    }
                    for index, (path, category) in enumerate(
                        zip(paths, ("Bass", "Lead"))
                    )
                ],
            )
            self.assertEqual(self.window.all_layers_transport.text(), "PLAY ALL")
            with patch.object(self.window._layer_player, "_start"):
                self.window.all_layers_transport.click()
                APP.processEvents()
                self.assertEqual(
                    set(self.window._layer_player.activePaths()),
                    {str(path) for path in paths},
                )
                self.assertEqual(self.window.all_layers_transport.text(), "STOP")

                self.window.all_layers_transport.click()
                APP.processEvents()
                self.assertEqual(self.window._layer_player.activePaths(), ())
                self.assertEqual(self.window.all_layers_transport.text(), "PLAY ALL")

    def test_transformed_layer_hot_swaps_without_losing_live_transport_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            import wave
            import numpy as np

            path = Path(temporary) / "bass.wav"
            with wave.open(str(path), "wb") as stream:
                stream.setnchannels(2)
                stream.setsampwidth(2)
                stream.setframerate(48_000)
                stream.writeframes(b"\0\0\0\0" * 480)
            stem = {
                "path": str(path),
                "category": "Bass",
                "slot_index": 0,
                "identity": "bass",
                "bpm": 140,
                "key": "A minor",
                "peaks": (0.1,),
            }
            self.window.set_generation_results(
                {"path": str(Path(temporary) / "master.mp3")},
                [stem],
            )
            with patch.object(self.window._layer_player, "_start"):
                self.window._layer_player.setActive(str(path), True)
            self.window._layer_player.seek(0.25)
            updated = dict(stem)
            updated.update(
                {
                    "manual_pitch_semitones": 12,
                    "peaks": (0.6,),
                }
            )
            pcm = np.full((480, 2), 0.25, dtype=np.float32)

            self.assertTrue(self.window.update_generation_layer(updated, pcm))
            self.assertEqual(self.window._layer_player.activePaths(), (str(path),))
            self.assertAlmostEqual(self.window._layer_player.positionRatio(), 0.25)
            self.assertIn("Pitch +12", self.window._stem_cards[0].metadata_label.text())
            self.assertEqual(self.window._stem_cards[0].octave_selector.text(), "OCT +1")

    def test_replacing_results_clears_the_shared_layer_transport(self):
        class FakeLayerPlayer:
            def __init__(self):
                self.calls = []

            def stop(self, *, reset=False):
                self.calls.append(reset)

        fake = FakeLayerPlayer()
        self.window._layer_player = fake

        self.window._clear_results()

        self.assertEqual(fake.calls, [True])

    def test_stem_card_can_be_kept_and_is_carried_by_the_request(self):
        window = self.window
        changes = []
        window.lockChanged.connect(
            lambda slot, identity, locked: changes.append(
                (slot, identity, locked)
            )
        )
        window.set_generation_results(
            {
                "path": "/tmp/master.mp3",
                "display_name": "GENERATED LOOP",
                "category": "Master",
                "bpm": 140,
                "key": "A minor",
                "peaks": (0.2, 0.4),
            },
            [
                {
                    "path": "/tmp/bass.mp3",
                    "display_name": "BASS",
                    "category": "Bass",
                    "slot_index": 0,
                    "identity": "bass-source-id",
                    "bpm": 140,
                    "key": "A minor",
                    "peaks": (0.3, 0.7),
                    "locked": False,
                }
            ],
        )
        card = window._stem_cards[0]
        self.assertEqual(card.lock_button.text(), "KEEP")

        card.lock_button.click()

        self.assertTrue(card.locked)
        self.assertEqual(card.lock_button.text(), "KEPT")
        self.assertEqual(changes[-1], (0, "bass-source-id", True))
        self.assertEqual(
            window.generation_request()["locked_slots"],
            ((0, "bass-source-id"),),
        )

        # KEEP is explicit: clicking blank card space has no hidden action.
        QTest.mouseClick(card, Qt.LeftButton, pos=QPoint(4, card.height() - 4))
        self.assertTrue(card.locked)
        self.assertEqual(changes[-1], (0, "bass-source-id", True))

    def test_alternate_key_button_toggles_alt_and_og_with_shared_busy_state(self):
        requests = []
        self.window.alternateKeyRequested.connect(
            lambda slot, identity: requests.append((slot, identity))
        )
        self.window.set_generation_results(
            {
                "path": "/tmp/master.mp3",
                "category": "Master",
                "peaks": (0.2,),
            },
            [
                {
                    "path": "/tmp/bass.mp3",
                    "category": "Bass",
                    "slot_index": 0,
                    "identity": "bass-source-id",
                    "alternate_key": "D minor",
                    "alternate_key_used": False,
                    "peaks": (0.3,),
                    "locked": False,
                }
            ],
        )
        card = self.window._stem_cards[0]
        self.assertIsNotNone(card.alternate_key_button)
        self.assertEqual(card.alternate_key_button.text(), "ALT KEY")
        # Native Windows font metrics are wider than Cocoa's.  Keep the
        # controls compact without asserting a macOS-only pixel width.
        self.assertLess(card.alternate_key_button.width(), 60)
        self.assertLess(card.lock_button.width(), 50)
        self.assertLessEqual(card.octave_selector.width(), 60)
        self.assertEqual(card.octave_selector.currentText(), "0")
        self.assertEqual(card.octave_selector.text(), "OCT 0")
        card.octave_selector._show_menu()
        APP.processEvents()
        octave_width = abs(
            card.octave_selector.mapToGlobal(
                QPoint(card.octave_selector.width(), 0)
            ).x()
            - card.octave_selector.mapToGlobal(QPoint(0, 0)).x()
        )
        self.assertEqual(card.octave_selector._popup.width(), octave_width)
        card.octave_selector._popup.hide()
        self.assertLess(card.normalization_button.width(), 65)
        card.alternate_key_button.click()
        self.assertEqual(requests, [(0, "bass-source-id")])
        self.assertFalse(card.locked)
        self.assertEqual(card.alternate_key_button.text(), "ALT…")
        self.assertTrue(
            all(
                not button.isEnabled()
                for button in (
                    card.alternate_key_button,
                    card.octave_selector,
                    card.normalization_button,
                )
            )
        )

        self.window.set_layer_transform_busy(0, "bass-source-id", False)
        self.assertEqual(card.alternate_key_button.text(), "ALT KEY")
        self.assertTrue(card.alternate_key_button.isEnabled())

        card.alternate_key_used = True
        card._refresh_transform_controls()
        self.assertEqual(card.alternate_key_button.text(), "OG KEY")
        self.assertTrue(card.alternate_key_button.isEnabled())
        card.alternate_key_button.click()
        self.assertEqual(
            requests,
            [(0, "bass-source-id"), (0, "bass-source-id")],
        )
        self.assertEqual(card.alternate_key_button.text(), "OG…")
        self.assertFalse(card.alternate_key_button.isEnabled())

        # The original controller-facing API remains a compatibility alias.
        self.window.set_alternate_key_busy(0, "bass-source-id", False)
        self.assertEqual(card.alternate_key_button.text(), "OG KEY")
        self.assertTrue(card.alternate_key_button.isEnabled())

        self.window.set_generation_busy(True, "busy")
        self.assertTrue(
            all(
                not button.isEnabled()
                for button in (
                    card.alternate_key_button,
                    card.octave_selector,
                    card.normalization_button,
                )
            )
        )
        self.window.set_generation_busy(False, "ready")
        self.assertEqual(card.alternate_key_button.text(), "OG KEY")
        self.assertTrue(card.alternate_key_button.isEnabled())

    def test_octave_selector_emits_exact_reversible_target_states(self):
        requests = []
        self.window.octaveShiftRequested.connect(
            lambda slot, identity, shift: requests.append(
                (slot, identity, shift)
            )
        )
        self.window.set_generation_results(
            {"path": "/tmp/master.mp3", "peaks": (0.2,)},
            [
                {
                    "path": "/tmp/bass.mp3",
                    "category": "Bass",
                    "slot_index": 0,
                    "identity": "bass-source-id",
                    "peaks": (0.3,),
                }
            ],
        )
        card = self.window._stem_cards[0]
        self.assertEqual(card.octave_shift, 0)
        self.assertEqual(card.data["octave_shift"], 0)
        self.assertFalse(card.data["normalized"])
        self.assertEqual(
            [card.octave_selector.itemText(index) for index in range(3)],
            ["+1", "0", "-1"],
        )
        self.assertEqual(card.octave_selector.currentText(), "0")
        self.assertTrue(
            all(row.check_label.width() == 0 for row in card.octave_selector._rows.values())
        )

        card.octave_selector.setCurrentText("-1")
        self.assertEqual(requests[-1], (0, "bass-source-id", -12))
        self.assertFalse(card.normalization_button.isEnabled())

        self.window.set_layer_transform_busy(0, "bass-source-id", False)
        card.octave_shift = -12
        card._refresh_transform_controls()
        self.assertEqual(card.octave_selector.currentText(), "-1")
        self.assertEqual(card.octave_selector.text(), "OCT -1")
        card.octave_selector.setCurrentText("0")
        self.assertEqual(requests[-1], (0, "bass-source-id", 0))

        self.window.set_layer_transform_busy(0, "bass-source-id", False)
        card.octave_shift = -12
        card._refresh_transform_controls()
        card.octave_selector.setCurrentText("+1")
        self.assertEqual(requests[-1], (0, "bass-source-id", 12))

        self.window.set_layer_transform_busy(0, "bass-source-id", False)
        card.octave_shift = 12
        card._refresh_transform_controls()
        self.assertEqual(card.octave_selector.currentText(), "+1")
        self.assertEqual(card.octave_selector.text(), "OCT +1")
        card.octave_selector.setCurrentText("0")
        self.assertEqual(requests[-1], (0, "bass-source-id", 0))

    def test_normalization_button_toggles_normalize_and_original(self):
        requests = []
        self.window.normalizationRequested.connect(
            lambda slot, identity, normalized: requests.append(
                (slot, identity, normalized)
            )
        )
        self.window.set_generation_results(
            {"path": "/tmp/master.mp3", "peaks": (0.2,)},
            [
                {
                    "path": "/tmp/bass.mp3",
                    "category": "Bass",
                    "slot_index": 0,
                    "identity": "bass-source-id",
                    "octave_shift": 12,
                    "normalized": False,
                    "peaks": (0.3,),
                }
            ],
        )
        card = self.window._stem_cards[0]
        self.assertEqual(card.octave_shift, 12)
        self.assertEqual(card.octave_selector.currentText(), "+1")
        self.assertEqual(card.octave_selector.text(), "OCT +1")
        self.assertFalse(card.normalized)
        self.assertEqual(card.normalization_button.text(), "NORMALIZE")

        card.normalization_button.click()
        self.assertEqual(requests[-1], (0, "bass-source-id", True))
        self.assertFalse(card.octave_selector.isEnabled())

        self.window.set_layer_transform_busy(0, "bass-source-id", False)
        card.normalized = True
        card._refresh_transform_controls()
        self.assertEqual(card.normalization_button.text(), "ORIGINAL")
        card.normalization_button.click()
        self.assertEqual(requests[-1], (0, "bass-source-id", False))

    def test_kept_card_locks_its_exact_recipe_slot_until_unkept(self):
        window = self.window
        window.set_generation_results(
            {
                "path": "/tmp/master.mp3",
                "category": "Master",
                "peaks": (0.2,),
            },
            [
                {
                    "path": "/tmp/bass.mp3",
                    "category": "Bass",
                    "slot_index": 0,
                    "identity": "bass-source-id",
                    "peaks": (0.3,),
                    "locked": True,
                }
            ],
        )
        card = window._stem_cards[0]
        slot = window._slot_widgets[0]
        self.assertTrue(card.locked)
        self.assertTrue(slot.property("locked"))
        self.assertFalse(slot.selector.isEnabled())
        self.assertFalse(slot.remove_button.isEnabled())

        before = len(window._slot_widgets)
        window._remove_slot(slot)
        self.assertEqual(len(window._slot_widgets), before)

        window.set_generation_busy(True, "busy")
        window.set_generation_busy(False, "ready")
        self.assertFalse(slot.selector.isEnabled())
        self.assertFalse(slot.remove_button.isEnabled())

        card.setLocked(False, emit=True)

        self.assertFalse(card.locked)
        self.assertFalse(slot.property("locked"))
        self.assertTrue(slot.selector.isEnabled())
        self.assertTrue(slot.remove_button.isEnabled())
        self.assertEqual(window.generation_request()["locked_slots"], ())

    def test_removing_an_earlier_slot_preserves_and_reindexes_keep(self):
        window = self.window
        window.set_generation_results(
            {
                "path": "/tmp/master.mp3",
                "category": "Master",
                "peaks": (0.2,),
            },
            [
                {
                    "path": "/tmp/lead.mp3",
                    "category": "Lead",
                    "slot_index": 2,
                    "identity": "lead-source-id",
                    "peaks": (0.3,),
                    "locked": True,
                }
            ],
        )
        card = window._stem_cards[0]
        lead_slot = window._slot_widgets[2]

        window._remove_slot(window._slot_widgets[0])
        APP.processEvents()

        self.assertTrue(card.locked)
        self.assertIs(card.recipe_slot, lead_slot)
        self.assertEqual(card.slot_index, 1)
        self.assertFalse(lead_slot.selector.isEnabled())
        self.assertFalse(lead_slot.remove_button.isEnabled())
        self.assertEqual(
            window.generation_request()["locked_slots"],
            ((1, "lead-source-id"),),
        )

    def test_keep_locks_only_the_exact_slot_with_duplicate_categories(self):
        window = self.window
        window._add_slot("Lead")
        window.set_generation_results(
            {
                "path": "/tmp/master.mp3",
                "category": "Master",
                "peaks": (0.2,),
            },
            [
                {
                    "path": "/tmp/lead.mp3",
                    "category": "Lead",
                    "slot_index": 2,
                    "identity": "lead-source-id",
                    "peaks": (0.3,),
                    "locked": True,
                }
            ],
        )

        exact_slot = window._slot_widgets[2]
        other_lead_slot = window._slot_widgets[3]
        self.assertFalse(exact_slot.selector.isEnabled())
        self.assertFalse(exact_slot.remove_button.isEnabled())
        self.assertTrue(other_lead_slot.selector.isEnabled())
        self.assertTrue(other_lead_slot.remove_button.isEnabled())

    def test_removing_an_unkept_slot_cannot_create_a_latent_keep(self):
        window = self.window
        window.set_generation_results(
            {
                "path": "/tmp/master.mp3",
                "category": "Master",
                "peaks": (0.2,),
            },
            [
                {
                    "path": "/tmp/bass.mp3",
                    "category": "Bass",
                    "slot_index": 0,
                    "identity": "bass-source-id",
                    "peaks": (0.3,),
                    "locked": False,
                }
            ],
        )
        card = window._stem_cards[0]

        window._remove_slot(window._slot_widgets[0])

        self.assertIsNone(card.recipe_slot)
        self.assertEqual(card.slot_index, -1)
        self.assertFalse(card.lock_button.isEnabled())
        self.assertEqual(window.generation_request()["locked_slots"], ())

    def test_recipe_slots_use_anchored_popups_and_have_no_six_slot_limit(self):
        window = self.window
        self.assertTrue(
            all(
                isinstance(selector, AnchoredChoiceSelector)
                for selector in window._slot_combos
            )
        )
        for _ in range(7):
            window._add_slot("Lead")
        APP.processEvents()

        self.assertEqual(len(window._slot_combos), 10)
        self.assertGreater(
            window.slot_host.width(),
            window.slot_scroll.viewport().width(),
        )
        self.assertEqual(
            len([slot for slot in window._slot_widgets if slot.remove_button]),
            10,
        )

        bass_slot = window._slot_widgets[0]
        window._remove_slot(bass_slot)
        APP.processEvents()
        self.assertEqual(window._slot_combos[0].currentText(), "Chords")
        self.assertEqual(len(window._slot_combos), 9)

    def test_generate_top_is_rebalanced_and_controls_are_compact(self):
        window = self.window
        top_width = window.library_section.width() + window.recipe_section.width()
        if os.name != "nt":
            # The obsolete standalone prototype is embedded in a transformed
            # QGraphicsView; the Windows offscreen plugin does not apply its
            # stretch factors until a real native window is exposed.
            self.assertLessEqual(window.library_section.width() / top_width, 0.34)
            self.assertGreater(
                window.recipe_section.width(), window.library_section.width() * 2
            )

        self.assertEqual((window.target_bpm.width(), window.target_bpm.height()), (46, 25))
        self.assertEqual((window.target_key.width(), window.target_key.height()), (94, 25))
        self.assertEqual(
            (window.preview_seed_button.width(), window.preview_seed_button.height()),
            (90, 26),
        )
        self.assertEqual(
            (window.generate_button.width(), window.generate_button.height()),
            (85, 26),
        )
        slot_y = window._slot_widgets[0].mapTo(window.canvas, QPoint()).y()
        plus_y = window.add_slot_button.mapTo(window.canvas, QPoint()).y()
        self.assertEqual(plus_y, slot_y)

        label_bottom = (
            window.recipe_slots_label.mapTo(window.canvas, QPoint()).y()
            + window.recipe_slots_label.height()
        )
        slot_top = window.slot_row.mapTo(window.canvas, QPoint()).y()
        self.assertEqual(slot_top - label_bottom, 3)
        drop_bottom = (
            window.library_drop.mapTo(window.canvas, QPoint()).y()
            + window.library_drop.height()
        )
        first_slot_bottom = (
            window._slot_widgets[0].mapTo(window.canvas, QPoint()).y()
            + window._slot_widgets[0].height()
        )
        plus_bottom = (
            window.add_slot_button.mapTo(window.canvas, QPoint()).y()
            + window.add_slot_button.height()
        )
        self.assertEqual((first_slot_bottom, plus_bottom), (drop_bottom, drop_bottom))

        section_left = window.recipe_section.mapTo(window.canvas, QPoint()).x()
        strip_left = window.slot_row.mapTo(window.canvas, QPoint()).x()
        self.assertEqual(strip_left - section_left, 13)
        last_slot = window._slot_widgets[-1]
        last_slot_right = (
            last_slot.mapTo(window.canvas, QPoint()).x() + last_slot.width()
        )
        plus_left = window.add_slot_button.mapTo(window.canvas, QPoint()).x()
        self.assertEqual(
            plus_left - last_slot_right,
            window.slot_layout.spacing(),
        )
        self.assertEqual(
            (window.add_slot_button.width(), window.add_slot_button.height()),
            (25, 25),
        )
        self.assertEqual(window.add_slot_button.property("role"), "slotAdd")

        first_slot = window._slot_widgets[0]
        self.assertLess(first_slot.remove_button.x(), first_slot.selector.x())
        self.assertEqual(first_slot.remove_button.property("role"), "slotRemove")
        self.assertEqual(first_slot.remove_button.text(), "")
        self.assertEqual(first_slot.layout().spacing(), 0)
        self.assertEqual(
            window.slot_row.layout().itemAt(1).widget(),
            window.add_slot_button,
        )

        bpm_gap = (
            window.target_bpm.mapTo(window.canvas, QPoint()).x()
            - window.target_bpm_label.mapTo(window.canvas, QPoint()).x()
            - window.target_bpm_label.width()
        )
        key_gap = (
            window.target_key.mapTo(window.canvas, QPoint()).x()
            - window.target_key_label.mapTo(window.canvas, QPoint()).x()
            - window.target_key_label.width()
        )
        self.assertEqual((bpm_gap, key_gap), (6, 6))

    def test_seven_compact_recipe_slots_fit_before_eight_needs_scrolling(self):
        window = self.window
        for _ in range(4):
            window._add_slot("Lead")
        APP.processEvents()

        self.assertEqual(len(window._slot_widgets), 7)
        seven_slot_overflow = window.slot_scroll.horizontalScrollBar().maximum()
        if os.name != "nt":
            self.assertEqual(seven_slot_overflow, 0)

        window._add_slot("Lead")
        APP.processEvents()
        self.assertEqual(len(window._slot_widgets), 8)
        self.assertGreater(
            window.slot_scroll.horizontalScrollBar().maximum(),
            seven_slot_overflow,
        )

    def test_recipe_slot_width_tracks_its_visible_category(self):
        window = self.window
        bass_slot = window._slot_widgets[0]
        bass_width = bass_slot.width()

        bass_slot.selector.setCurrentText("Rhythmic Pluck")
        APP.processEvents()

        self.assertGreater(bass_slot.width(), bass_width)
        native_padding = 20 if os.name != "nt" else 0
        self.assertGreaterEqual(
            bass_slot.selector.width(),
            bass_slot.selector.fontMetrics().horizontalAdvance("Rhythmic Pluck")
            + native_padding,
        )
        expected_host_width = sum(slot.width() for slot in window._slot_widgets)
        expected_host_width += (
            len(window._slot_widgets) - 1
        ) * window.slot_layout.spacing()
        self.assertEqual(window.slot_host.width(), expected_host_width)

    def test_add_button_follows_the_last_recipe_slot(self):
        window = self.window
        initial_x = window.add_slot_button.x()

        window._add_slot("Lead")
        APP.processEvents()

        last_slot = window._slot_widgets[-1]
        self.assertGreater(window.add_slot_button.x(), initial_x)
        self.assertEqual(
            window.add_slot_button.x() - (last_slot.x() + last_slot.width()),
            window.slot_layout.spacing(),
        )
        self.assertEqual(
            sum(
                1
                for index in range(window.slot_row.layout().count())
                if window.slot_row.layout().itemAt(index).widget()
                is window.add_slot_button
            ),
            1,
        )

    def test_library_coverage_has_a_clear_total_and_full_width_categories(self):
        window = self.window
        counts = {
            "Bass": 451,
            "Chords": 714,
            "Counter": 600,
            "Keys": 78,
            "Lead": 1063,
            "Pad": 310,
            "Pluck": 376,
            "Rhythmic Pluck": 149,
            "Vocal Chop": 92,
            "Bells": 4,
            "Strings": 18,
            "Texture": 6,
            "Guitar Lead": 8,
            "Guitar Chords": 7,
            "Vocal": 5,
            "Arp": 4,
            "Brass": 2,
            "Accent": 1,
            "Percussion": 1,
        }
        self.assertEqual(set(counts), set(TAXONOMY))

        window.set_library_summary(sum(counts.values()), counts, 0)
        APP.processEvents()

        self.assertEqual(window.library_total_value.text(), str(sum(counts.values())))
        self.assertEqual(window.library_total_unit.text(), "LAYERS")
        self.assertFalse(window.library_review_badge.isVisible())
        token_texts = [token.text() for token in window.library_category_tokens]
        self.assertEqual(
            token_texts,
            [f"{category} {counts[category]}" for category in TAXONOMY],
        )
        self.assertNotIn("ALL REVIEWED", " ".join(token_texts))
        self.assertLessEqual(
            window.coverage_flow.heightForWidth(window.coverage_flow_host.width()),
            window.coverage_flow_host.height(),
        )
        host_left = window.coverage_flow_host.mapTo(window.canvas, QPoint()).x()
        host_top = window.coverage_flow_host.mapTo(window.canvas, QPoint()).y()
        host_right = host_left + window.coverage_flow_host.width()
        host_bottom = host_top + window.coverage_flow_host.height()
        first_token = window.library_category_tokens[0]
        last_token = window.library_category_tokens[-1]
        token_top = first_token.mapTo(window.canvas, QPoint()).y()
        token_bottom = token_top + first_token.height()
        token_right = (
            last_token.mapTo(window.canvas, QPoint()).x()
            + last_token.width()
        )
        centering_tolerance = 1 if os.name != "nt" else 12
        self.assertLessEqual(
            abs((token_top - host_top) - (host_bottom - token_bottom)),
            centering_tolerance,
        )
        self.assertLessEqual(host_right - token_right, 12)
        self.assertFalse(hasattr(window, "master_label"))
        self.assertLess(
            window.library_total_value.mapTo(window.canvas, QPoint()).y(),
            window.layers_label.mapTo(window.canvas, QPoint()).y(),
        )

        window.set_library_summary(sum(counts.values()), counts, 4)
        APP.processEvents()
        self.assertTrue(window.library_review_badge.isVisible())
        self.assertEqual(window.library_review_badge.text(), "4 TO REVIEW")

    def test_nine_layer_cards_fit_without_scroll_and_ten_trigger_it(self):
        window = self.window

        def stems(count):
            return [
                {
                    "path": f"/tmp/layer-{index}.mp3",
                    "category": "Lead",
                    "slot_index": index,
                    "identity": f"identity-{index}",
                    "peaks": (0.1, 0.4),
                }
                for index in range(count)
            ]

        master = {
            "path": "/tmp/master.mp3",
            "category": "Master",
            "peaks": (0.2, 0.5),
        }
        window.set_generation_results(master, stems(9))
        APP.processEvents()

        self.assertEqual(window.layers_area.verticalScrollBar().maximum(), 0)
        self.assertEqual(len(window._stem_cards), 9)
        self.assertTrue(all(card.height() == 78 for card in window._stem_cards))
        self.assertTrue(
            all((card.play.width(), card.play.height()) == (25, 25) for card in window._stem_cards)
        )
        third_card = window._stem_cards[2]

        def right_edge(widget):
            return widget.mapTo(window.canvas, QPoint()).x() + widget.width()

        self.assertLessEqual(right_edge(third_card), right_edge(window.drag_all))
        self.assertTrue(window.drag_all.isVisible())
        self.assertEqual(window._cards, window._stem_cards)

        window.set_generation_results(master, stems(10))
        APP.processEvents()
        self.assertEqual(len(window._stem_cards), 10)
        self.assertGreater(window.layers_area.verticalScrollBar().maximum(), 0)

    def test_master_is_hidden_while_drag_all_keeps_master_and_unlimited_layers(self):
        window = self.window
        stems = [
            {
                "path": f"/tmp/layer-{index}.mp3",
                "category": "Lead",
                "slot_index": index,
                "identity": f"identity-{index}",
                "peaks": (0.1, 0.4),
            }
            for index in range(10)
        ]
        window.set_generation_results(
            {
                "path": "/tmp/master.mp3",
                "category": "Master",
                "peaks": (0.2, 0.5),
            },
            stems,
        )
        APP.processEvents()

        self.assertEqual(len(window._stem_cards), 10)
        self.assertFalse(hasattr(window, "master_host"))
        self.assertEqual(window._cards, window._stem_cards)
        self.assertTrue(
            all(card.parentWidget() is window.layers_content for card in window._stem_cards)
        )
        self.assertGreater(
            window.layers_content.minimumHeight(),
            window.layers_area.viewport().height(),
        )
        self.assertTrue(all(path.endswith(".mp3") for path in window.drag_all.paths))
        self.assertEqual(
            os.path.normcase(str(Path(window.drag_all.paths[0]).resolve())),
            os.path.normcase(str(Path("/tmp/master.mp3").resolve())),
        )

    def test_top_generate_becomes_generate_again_and_consumes_a_new_seed(self):
        generated = []
        initial_seed = self.window._seed
        self.window.generateRequested.connect(
            lambda payload: generated.append(("generate", payload["seed"]))
        )
        self.window.generateAgainRequested.connect(
            lambda payload: generated.append(("again", payload["seed"]))
        )

        self.window._request_generation()
        self.window.set_generation_results(
            {
                "path": "/tmp/master.mp3",
                "category": "Master",
                "peaks": (0.2,),
            },
            [],
        )
        self.assertEqual(self.window.generate_button.text(), "GENERATE AGAIN")
        self.assertFalse(hasattr(self.window, "again_button"))
        self.window._request_generation()

        self.assertEqual(
            generated,
            [
                ("generate", initial_seed),
                ("again", initial_seed + 1),
            ],
        )
        self.assertEqual(self.window._seed, initial_seed + 2)

    def test_drag_all_and_persistent_footer_follow_the_quick_extract_layout(self):
        window = self.window
        self.assertIs(window.drag_all.parentWidget(), window.layers_bar)
        self.assertGreater(
            window.generation_footer.mapTo(window.results_section, QPoint()).y(),
            window.layers_area.mapTo(window.results_section, QPoint()).y(),
        )
        self.assertTrue(window.open_output.isEnabled())
        self.assertTrue(window.manage_button.isEnabled())

        window.set_generation_history_summary(12, 24_700_000, 48)
        self.assertEqual(
            window.generation_storage_label.text(),
            "12 generations · 24,7 Mo",
        )

        window.set_generation_busy(True, "Rendering")
        self.assertFalse(window.manage_button.isEnabled())
        window.set_generation_busy(False, "Ready")
        self.assertTrue(window.manage_button.isEnabled())

    def test_preview_seed_emits_without_consuming_a_seed(self):
        emitted = []
        self.window.previewSeedRequested.connect(lambda: emitted.append(True))
        initial_seed = self.window._seed
        self.window.set_preview_seed_available(True)

        self.window._request_preview_seed()

        self.assertEqual(emitted, [True])
        self.assertEqual(self.window._seed, initial_seed)

        self.window.set_generation_busy(True, "busy")
        self.assertFalse(self.window.preview_seed_button.isEnabled())


class _FakeWindow(QObject):
    scanRequested = Signal(str)
    generateRequested = Signal(dict)
    generateAgainRequested = Signal(dict)
    previewSeedRequested = Signal()
    openOutputRequested = Signal()

    def __init__(self):
        super().__init__()
        self.preview_available = None
        self.results = None
        self.busy = None
        self.reset_text = None
        self.layer_updates = []

    def set_preview_seed_available(self, available):
        self.preview_available = bool(available)

    def set_generation_results(self, master, stems):
        self.results = (dict(master), [dict(item) for item in stems])

    def set_generation_busy(self, busy, status=""):
        self.busy = (bool(busy), str(status))

    def reset_generation_results(self, text):
        self.reset_text = str(text)

    def update_generation_layer(self, stem, pcm):
        self.layer_updates.append((dict(stem), pcm))
        return True


class _FakeClassifier:
    def __init__(self, **_kwargs):
        self.stopped = False

    def stop(self):
        self.stopped = True


class _CancellableWorker(QObject):
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.cancelled = threading.Event()

    def cancel(self):
        self.cancelled.set()

    @Slot()
    def run(self):
        self.entered.set()
        self.cancelled.wait(1.0)
        self.finished.emit()


class GeneratorControllerLifecycleTests(unittest.TestCase):
    def test_completed_card_transform_hot_swaps_only_that_layer(self):
        window = _FakeWindow()
        with patch.object(generator_controller, "MertLayerClassifier", _FakeClassifier):
            controller = generator_controller.GeneratorController(window)
        candidate = SimpleNamespace(identity="bass-a")
        selection = SimpleNamespace(
            candidate=candidate,
            source_key_rank=2,
            manual_pitch_semitones=12,
            normalization_enabled=False,
        )
        stem_result = SimpleNamespace(
            selection=selection,
            waveform_peaks=(0.2, 0.4),
        )
        pcm = object()
        render = SimpleNamespace(
            stem_results=(stem_result,),
            stem_audio_pcm=(pcm,),
            master_waveform_peaks=(0.3,),
            output_directory=Path("/tmp/generated"),
        )
        controller._generation_history.append(
            {
                "master": {"path": "/tmp/master.mp3", "peaks": ()},
                "stems": (
                    {
                        "path": "/tmp/bass.mp3",
                        "identity": "bass-a",
                        "slot_index": 0,
                        "category": "Bass",
                    },
                ),
                "render": object(),
                "plan": object(),
            }
        )
        controller._history_index = 0
        controller._layer_transform_target = (
            0,
            "bass-a",
            "manual_pitch",
            12,
        )
        payload = {
            "slot_index": 0,
            "identity": "bass-a",
            "operation": "manual_pitch",
            "render": render,
            "plan": object(),
        }

        with patch.object(
            generator_controller,
            "_selection_source_key_text",
            return_value="A minor",
        ), patch.object(controller, "refresh_generation_history"):
            controller._layer_transform_render_completed(payload)

        self.assertEqual(len(window.layer_updates), 1)
        self.assertIs(window.layer_updates[0][1], pcm)
        self.assertEqual(
            window.layer_updates[0][0]["manual_pitch_semitones"],
            12,
        )
        self.assertIsNone(window.results)
        self.assertEqual(window.busy, (False, "Pitch +12 applied · generated"))
        controller.shutdown()

    def test_scan_is_ignored_while_a_generation_or_card_rerender_is_active(self):
        with patch.object(generator_controller, "MertLayerClassifier", _FakeClassifier):
            window = _FakeWindow()
            controller = generator_controller.GeneratorController(window)
        controller._render_thread = object()
        self.addCleanup(setattr, controller, "_render_thread", None)
        with tempfile.TemporaryDirectory() as root:
            controller.start_scan(root)
        self.assertIsNone(window.reset_text)
        self.assertIsNone(window.busy)
        controller._render_thread = None
        controller.shutdown()

    def test_generation_payload_carries_previous_layers_and_combinations(self):
        with patch.object(generator_controller, "MertLayerClassifier", _FakeClassifier):
            controller = generator_controller.GeneratorController(_FakeWindow())
        controller._last_generation_identities = frozenset(
            {"previous-bass", "previous-lead"}
        )
        payload = controller._generation_payload({"seed": 7})

        self.assertEqual(payload["seed"], 7)
        self.assertEqual(
            set(payload["excluded_identities"]),
            {"previous-bass", "previous-lead"},
        )
        self.assertNotIn("recent_combinations", payload)
        controller.shutdown()

    def test_visible_snapshot_locks_are_kept_and_other_ids_are_excluded(self):
        with patch.object(generator_controller, "MertLayerClassifier", _FakeClassifier):
            controller = generator_controller.GeneratorController(_FakeWindow())
        controller._generation_history.append(
            {
                "seed": 11,
                "selection_identities": (
                    "lead-a",
                    "lead-b",
                    "pad-a",
                ),
                "locked_slots": ((1, "lead-b"),),
                "stems": (),
            }
        )
        controller._history_index = 0
        controller._last_generation_identities = frozenset({"newer-hidden"})

        payload = controller._generation_payload(
            {"categories": ["Lead", "Lead", "Pad"], "seed": 12}
        )

        self.assertEqual(payload["locked_slots"], ((1, "lead-b"),))
        self.assertEqual(
            set(payload["excluded_identities"]),
            {"lead-a", "pad-a"},
        )
        self.assertEqual(payload["history_base_index"], 0)
        controller.shutdown()

    def test_current_ui_locks_override_a_stale_history_slot(self):
        with patch.object(generator_controller, "MertLayerClassifier", _FakeClassifier):
            controller = generator_controller.GeneratorController(_FakeWindow())
        controller._generation_history.append(
            {
                "seed": 11,
                "selection_identities": ("bass-a", "harp-a"),
                "locked_slots": ((5, "harp-a"),),
                "stems": (),
            }
        )
        controller._history_index = 0

        payload = controller._generation_payload(
            {
                "categories": ["Bass", "Arp"],
                "locked_slots": (),
                "seed": 12,
            }
        )

        self.assertEqual(payload["locked_slots"], ())
        self.assertEqual(
            set(payload["excluded_identities"]),
            {"bass-a", "harp-a"},
        )
        controller.shutdown()

    def test_current_ui_keep_is_reindexed_before_generation(self):
        with patch.object(generator_controller, "MertLayerClassifier", _FakeClassifier):
            controller = generator_controller.GeneratorController(_FakeWindow())
        controller._generation_history.append(
            {
                "seed": 11,
                "selection_identities": ("bass-a", "harp-a"),
                "locked_slots": ((5, "legacy-harp"),),
                "stems": (),
            }
        )
        controller._history_index = 0

        payload = controller._generation_payload(
            {
                "categories": ["Bass", "Arp"],
                "locked_slots": ((1, "harp-a"),),
                "seed": 12,
            }
        )

        self.assertEqual(payload["locked_slots"], ((1, "harp-a"),))
        self.assertEqual(payload["excluded_identities"], ("bass-a",))
        controller.shutdown()

    def test_lock_change_is_persisted_by_slot_and_identity(self):
        with patch.object(generator_controller, "MertLayerClassifier", _FakeClassifier):
            controller = generator_controller.GeneratorController(_FakeWindow())
        controller._generation_history.append(
            {
                "seed": 11,
                "stems": (
                    {
                        "slot_index": 0,
                        "identity": "lead-a",
                        "category": "Lead",
                        "locked": False,
                    },
                    {
                        "slot_index": 1,
                        "identity": "lead-b",
                        "category": "Lead",
                        "locked": False,
                    },
                ),
            }
        )
        controller._history_index = 0

        controller.update_lock_state(1, "lead-b", True)

        snapshot = controller._generation_history[0]
        self.assertEqual(snapshot["locked_slots"], ((1, "lead-b"),))
        self.assertFalse(snapshot["stems"][0]["locked"])
        self.assertTrue(snapshot["stems"][1]["locked"])
        controller.shutdown()

    def test_successful_generation_truncates_the_future_preview_branch(self):
        with patch.object(generator_controller, "MertLayerClassifier", _FakeClassifier):
            controller = generator_controller.GeneratorController(_FakeWindow())
        controller._generation_history.extend(
            [{"seed": 11}, {"seed": 22}, {"seed": 33}]
        )
        controller._history_index = 0

        controller._truncate_history_after(0)

        self.assertEqual(
            [snapshot["seed"] for snapshot in controller._generation_history],
            [11],
        )
        self.assertEqual(controller._history_index, 0)
        controller.shutdown()

    def test_preview_restores_previous_render_without_changing_exclusions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old_output = root / "old"
            new_output = root / "new"
            old_output.mkdir()
            new_output.mkdir()
            old_master = old_output / "master.wav"
            old_stem = old_output / "lead.wav"
            new_master = new_output / "master.wav"
            for path in (old_master, old_stem, new_master):
                path.write_bytes(b"audio")
            window = _FakeWindow()
            with patch.object(generator_controller, "MertLayerClassifier", _FakeClassifier):
                controller = generator_controller.GeneratorController(window)
            controller._generation_history.extend(
                [
                    {
                        "seed": 11,
                        "output_directory": str(old_output),
                        "master": {"path": str(old_master)},
                        "stems": ({"path": str(old_stem)},),
                    },
                    {
                        "seed": 22,
                        "output_directory": str(new_output),
                        "master": {"path": str(new_master)},
                        "stems": (),
                    },
                ]
            )
            controller._history_index = 1
            exclusions = frozenset({"latest-a", "latest-b"})
            controller._last_generation_identities = exclusions

            controller.preview_previous_seed()

            self.assertEqual(controller._history_index, 0)
            self.assertEqual(controller.last_output, old_output)
            self.assertEqual(window.results[0]["path"], str(old_master))
            self.assertEqual(window.results[1][0]["path"], str(old_stem))
            self.assertFalse(window.preview_available)
            self.assertIn("Previous seed 11", window.busy[1])
            self.assertEqual(controller._last_generation_identities, exclusions)
            controller.shutdown()

    def test_preview_skips_a_missing_render_and_reaches_an_older_seed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            oldest_output = root / "oldest"
            newest_output = root / "newest"
            oldest_output.mkdir()
            newest_output.mkdir()
            oldest_master = oldest_output / "master.wav"
            newest_master = newest_output / "master.wav"
            oldest_master.write_bytes(b"audio")
            newest_master.write_bytes(b"audio")
            window = _FakeWindow()
            with patch.object(generator_controller, "MertLayerClassifier", _FakeClassifier):
                controller = generator_controller.GeneratorController(window)
            controller._generation_history.extend(
                [
                    {
                        "seed": 11,
                        "output_directory": str(oldest_output),
                        "master": {"path": str(oldest_master)},
                        "stems": (),
                    },
                    {
                        "seed": 22,
                        "output_directory": str(root / "missing"),
                        "master": {"path": str(root / "missing.wav")},
                        "stems": (),
                    },
                    {
                        "seed": 33,
                        "output_directory": str(newest_output),
                        "master": {"path": str(newest_master)},
                        "stems": (),
                    },
                ]
            )
            controller._history_index = 2

            controller.preview_previous_seed()

            self.assertEqual(controller._history_index, 0)
            self.assertEqual(controller.last_output, oldest_output)
            self.assertEqual(window.results[0]["path"], str(oldest_master))
            self.assertIn("Previous seed 11", window.busy[1])
            self.assertIn("skipped missing seed(s) 22", window.busy[1])
            controller.shutdown()

    def test_shutdown_cancels_and_joins_a_running_scan_thread(self):
        with patch.object(generator_controller, "MertLayerClassifier", _FakeClassifier):
            controller = generator_controller.GeneratorController(_FakeWindow())
        thread = QThread(controller)
        worker = _CancellableWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        controller._scan_thread = thread
        controller._scan_worker = worker
        classifier = controller.classifier
        thread.start()
        self.assertTrue(worker.entered.wait(1.0))

        controller.shutdown()

        self.assertTrue(worker.cancelled.is_set())
        self.assertFalse(thread.isRunning())
        self.assertTrue(classifier.stopped)
        self.assertIsNone(controller._scan_thread)
        self.assertIsNone(controller._scan_worker)


if __name__ == "__main__":
    unittest.main()
